"""FastAPI 应用创建与生命周期管理"""

import time
import logging

from fastapi import FastAPI
from contextlib import asynccontextmanager

from .config import Config
from .state import ServerState
from .http_client import AilyHTTPClient
from .agent_resolver import AgentResolver
from .ws_manager import WSConnectionManager
from .exceptions import CookieExpiredError
from .routes_aily import router as aily_router
from .routes_openai import router as openai_router
from .debug_logger import DebugMiddleware

log = logging.getLogger('aily')


def create_app(config: Config) -> FastAPI:
    """创建 FastAPI 应用实例

    通过 lifespan 管理 ServerState 的初始化与清理。
    路由通过 request.app.state.server 访问状态。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ── 启动 ──
        state = ServerState(config=config)
        state.http_client = AilyHTTPClient(config)
        state.agent_resolver = AgentResolver(state.http_client)
        state.ws_manager = WSConnectionManager(state.http_client, config)
        app.state.server = state

        try:
            await state.ws_manager.connect()
        except CookieExpiredError as e:
            log.error(str(e))

        log.info(f'服务启动: {config.host}:{config.port}  workspace={config.workspace_id}')
        yield

        # ── 关闭 ──
        if state.ws_manager:
            await state.ws_manager.disconnect()
        if state.http_client:
            await state.http_client.close()
        log.info('服务已关闭')

    app = FastAPI(title='Aily Workbench Server', version='2.0', lifespan=lifespan)

    # 调试中间件：--debug 时原封不动保存请求和返回数据
    if config.debug:
        app.add_middleware(DebugMiddleware)

    app.include_router(aily_router)
    app.include_router(openai_router)

    @app.get('/')
    async def root():
        return {
            'service': 'Aily Workbench Server',
            'version': '2.0',
            'workspace_id': config.workspace_id,
            'endpoints': {
                'health': 'GET /api/health',
                'create_task': 'POST /api/tasks/create',
                'list_agents': 'GET /api/agents',
                'send': 'POST /api/send',
                'watch': 'POST /api/watch',
                'stop': 'POST /api/stop',
                'events': 'GET /api/events/{session_id}',
                'sessions': 'GET /api/sessions/{task_id}',
                'openai_models': 'GET /v1/models',
                'openai_chat': 'POST /v1/chat/completions',
            },
        }

    return app
