"""Aily Workbench API 路由 (/api/*)"""

import asyncio
import time
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .exceptions import CookieExpiredError, APIError
from .models import CreateTaskRequest, SendMessage, WatchRequest, StopRequest

log = logging.getLogger('aily')

router = APIRouter(prefix='/api', tags=['Aily Workbench'])


@router.get('/health')
async def health(request: Request):
    """健康检查"""
    state = request.app.state.server
    ws = state.ws_manager
    return {
        'ws_connected': ws.connected if ws else False,
        'cookie_valid': ws.connected if ws else False,
        'ticket_expires_at': ws.ticket_data.get('expiresAt') if ws and ws.ticket_data else None,
        'active_watchers': len(ws.watchers) if ws else 0,
        'workspace_id': state.config.workspace_id,
        'server_time': int(time.time()),
    }


@router.post('/tasks/create')
async def create_task(req: CreateTaskRequest, request: Request):
    """创建新任务，可指定智能体；自动复用 session_id 并启动 watch"""
    state = request.app.state.server

    # 解析智能体
    assignee_id = None
    agent_info = None
    if req.agent:
        agent_info = await state.agent_resolver.resolve(req.agent)
        if not agent_info:
            raise HTTPException(status_code=404, detail=f'未找到智能体: {req.agent}')
        assignee_id = agent_info.agent_id

    try:
        result = await state.http_client.create_task(
            title=req.title,
            description=req.description,
            assignee_id=assignee_id,
            assignee_type='agent' if assignee_id else '',
            kind=req.kind,
        )
    except CookieExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except APIError as e:
        raise HTTPException(status_code=502, detail=str(e))

    task = result.get('task', {})
    task_id = task.get('taskId', '')
    task_url = result.get('taskUrl', '')

    response = {
        'ok': True,
        'task_id': task_id,
        'task_url': task_url,
        'task': task,
        'agent': agent_info.name if agent_info else None,
        'agent_id': assignee_id,
        'session_id': None,
        'watching': False,
    }

    # 自动获取 session_id 并启动 watch
    if req.auto_watch and task_id:
        try:
            session_id = None
            for _ in range(10):
                session_id = await state.http_client.get_session_id(task_id)
                if session_id:
                    break
                await asyncio.sleep(1)
            if session_id:
                response['session_id'] = session_id
                watcher = await state.auto_watch_session(session_id, task_id)
                response['watching'] = True
                response['max_seq'] = watcher.max_seq
        except Exception as e:
            log.warning(f'自动 watch 失败: {e}')

    return response


@router.get('/agents')
async def list_agents(request: Request):
    """列出可用智能体"""
    state = request.app.state.server
    try:
        agents = await state.agent_resolver.list_agents()
        return {
            'ok': True,
            'agents': [
                {
                    'agent_id': a.agent_id,
                    'name': a.name,
                    'description': a.description,
                    'role': a.role,
                    'avatar_url': a.avatar_url,
                }
                for a in agents
            ],
        }
    except CookieExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get('/sessions/{task_id}')
async def get_session(task_id: str, request: Request):
    """获取 task 的 session_id"""
    state = request.app.state.server
    try:
        session_id = await state.http_client.get_session_id(task_id)
        if not session_id:
            raise HTTPException(status_code=404, detail='未找到 session_id')
        return {'ok': True, 'session_id': session_id, 'task_id': task_id}
    except CookieExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post('/send')
async def send_message(msg: SendMessage, request: Request):
    """发送消息到 task；可自动 watch"""
    state = request.app.state.server
    try:
        result = await state.http_client.send_comment(
            task_id=msg.task_id,
            content=msg.content,
            mentions=msg.mentions,
            notable=msg.notable,
            client_request_id=msg.client_request_id,
        )
    except CookieExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except APIError as e:
        raise HTTPException(status_code=502, detail=str(e))

    comment = result.get('comment', {})
    response = {
        'ok': True,
        'comment_id': comment.get('commentId'),
        'session_id': result.get('sessionId'),
        'created_at': comment.get('createdAt'),
        'watching': False,
    }

    if msg.auto_watch:
        try:
            session_id = result.get('sessionId') or await state.http_client.get_session_id(msg.task_id)
            if session_id:
                response['session_id'] = session_id
                await state.auto_watch_session(session_id, msg.task_id)
                response['watching'] = True
        except Exception as e:
            log.warning(f'自动 watch 失败: {e}')

    return response


@router.post('/watch')
async def start_watch(req: WatchRequest, request: Request):
    """启动 session 监听"""
    state = request.app.state.server
    if req.session_id in state.ws_manager.watchers:
        return {'ok': True, 'session_id': req.session_id, 'message': '已在监听'}
    watcher = await state.auto_watch_session(req.session_id, req.task_id)
    return {'ok': True, 'session_id': req.session_id, 'max_seq': watcher.max_seq}


@router.post('/stop')
async def stop_watch(req: StopRequest, request: Request):
    """停止 session 监听"""
    state = request.app.state.server
    watcher = state.ws_manager.watchers.pop(req.session_id, None) if state.ws_manager else None
    if watcher:
        await watcher.stop_fallback()
        return {'ok': True, 'session_id': req.session_id}
    raise HTTPException(status_code=404, detail='未找到该 session 的监听')


@router.get('/events/{session_id}')
async def event_stream(session_id: str, request: Request):
    """SSE 流式事件"""
    state = request.app.state.server
    watcher = state.ws_manager.watchers.get(session_id) if state.ws_manager else None
    if not watcher:
        raise HTTPException(status_code=404, detail='未找到该 session 的监听，请先 POST /api/watch')
    return StreamingResponse(
        watcher.events_stream(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'},
    )
