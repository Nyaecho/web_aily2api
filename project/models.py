"""Pydantic 请求模型"""

from typing import Optional, List

from pydantic import BaseModel


# ─── Aily Workbench API 模型 ──

class CreateTaskRequest(BaseModel):
    title: str
    description: str = ''
    agent: Optional[str] = None  # 智能体名称或 ID，如 "前端" 或 "agent_xxx"
    kind: str = 'oneshot'
    auto_watch: bool = True  # 创建后自动启动 watch


class SendMessage(BaseModel):
    task_id: str
    content: str
    mentions: list = []
    notable: bool = False
    client_request_id: Optional[str] = None
    auto_watch: bool = True


class WatchRequest(BaseModel):
    session_id: str
    task_id: Optional[str] = None


class StopRequest(BaseModel):
    session_id: str


# ─── OpenAI 兼容 API 模型 ──

class OpenAIMessage(BaseModel):
    role: str
    content: str


class OpenAIChatRequest(BaseModel):
    model: str
    messages: List[OpenAIMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    title: Optional[str] = None  # 任务标题（可选，默认从 messages 提取）
