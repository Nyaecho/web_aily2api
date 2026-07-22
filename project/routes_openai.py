"""OpenAI 兼容 API 路由 (/v1/*)"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from .exceptions import CookieExpiredError, APIError
from .models import OpenAIChatRequest
from .openai_adapter import openai_stream, openai_non_stream

log = logging.getLogger("aily")

router = APIRouter(prefix="/v1", tags=["OpenAI 兼容"])


@router.get("/models")
async def list_models(request: Request):
    """OpenAI 兼容：列出模型（智能体）"""
    state = request.app.state.server
    try:
        agents = await state.agent_resolver.list_agents()
        return {
            "object": "list",
            "data": [a.to_openai_model() for a in agents],
        }
    except CookieExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/chat/completions")
async def chat_completions(req: OpenAIChatRequest, request: Request):
    """OpenAI 兼容聊天补全

    工作流程：
      1. 解析 model 字段 → agent_id
      2. 从 messages 提取用户最后一条消息作为任务内容
      3. 创建 Aily 任务（指定智能体）
      4. 自动获取 session_id + 启动 watch
      5. 流式/非流式返回 Agent 回复
    """
    state = request.app.state.server

    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")

    # 提取最后一条 user 消息
    user_message = None
    for m in reversed(req.messages):
        if m.role == "user":
            user_message = m.content
            break
    if not user_message:
        raise HTTPException(status_code=400, detail="未找到 user 消息")

    # 解析智能体
    agent_info = await state.agent_resolver.resolve(req.model)
    if not agent_info:
        raise HTTPException(
            status_code=404,
            detail=f"未找到模型/智能体: {req.model}。可用模型: GET /v1/models",
        )
    agent_id = agent_info.agent_id

    # 任务标题：取 messages[0] 或截取 user 消息前 50 字
    title = req.title or user_message[:50]
    if len(title) > 100:
        title = title[:100]

    # 创建任务
    try:
        result = await state.http_client.create_task(
            title=title,
            description=user_message,
            assignee_id=agent_id,
            assignee_type="agent",
            kind="oneshot",
        )
    except CookieExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except APIError as e:
        raise HTTPException(status_code=502, detail=str(e))

    task = result.get("task", {})
    task_id = task.get("taskId", "")
    task_url = result.get("taskUrl", "")

    # 等待 session_id
    session_id = None
    for _ in range(15):
        session_id = await state.http_client.get_session_id(task_id)
        if session_id:
            break
        await asyncio.sleep(1)
    if not session_id:
        raise HTTPException(
            status_code=504, detail=f"任务已创建 ({task_url}) 但未生成 session_id"
        )

    # 启动 watch
    watcher = await state.auto_watch_session(session_id, task_id)

    log.info(
        f"OpenAI chat: task={task_id} session={session_id} model={req.model} stream={req.stream}"
    )

    if req.stream:
        return StreamingResponse(
            openai_stream(watcher, req.model, agent_id, user_message),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    else:
        result = await openai_non_stream(watcher, req.model, agent_id, user_message)
        result["aily_task_id"] = task_id
        result["aily_task_url"] = task_url
        result["aily_session_id"] = session_id
        return JSONResponse(result)
