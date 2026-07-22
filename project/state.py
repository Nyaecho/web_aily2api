"""全局状态容器

在 FastAPI lifespan 中初始化，通过 app.state 访问。
路由通过 `request.app.state.server` 获取 ServerState 实例。
"""

from dataclasses import dataclass
from typing import Optional

from .http_client import AilyHTTPClient
from .agent_resolver import AgentResolver
from .ws_manager import WSConnectionManager
from .session_watcher import SessionWatcher
from .config import Config


@dataclass
class ServerState:
    """服务端运行时状态，持有所有核心组件实例"""

    config: Config
    http_client: Optional[AilyHTTPClient] = None
    agent_resolver: Optional[AgentResolver] = None
    ws_manager: Optional[WSConnectionManager] = None

    def make_watcher(self, session_id: str, task_id: str = None) -> SessionWatcher:
        """创建 SessionWatcher 实例"""
        return SessionWatcher(
            session_id=session_id,
            http_client=self.http_client,
            task_id=task_id,
        )

    async def auto_watch_session(
        self, session_id: str, task_id: str = None
    ) -> SessionWatcher:
        """自动启动一个 watcher（如果尚未存在）"""
        if not self.ws_manager or not self.ws_manager.connected:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=503, detail="WebSocket 未连接，请检查 cookie 是否过期"
            )
        if session_id in self.ws_manager.watchers:
            return self.ws_manager.watchers[session_id]
        watcher = self.make_watcher(session_id, task_id)
        await watcher.init()
        watcher.start_fallback()
        self.ws_manager.add_watcher(watcher)
        return watcher
