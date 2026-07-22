"""调试日志中间件

当 config.debug = True 时，对每个 HTTP 请求原封不动地保存：
  - 请求方法、路径、headers、body
  - 响应状态码、headers、body

日志写入 debug_logs/ 目录，每个请求一个 JSON 文件。
流式响应（SSE）同样完整捕获。
"""

import os
import json
import logging
from datetime import datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

log = logging.getLogger('aily.debug')

DEBUG_LOG_DIR = 'debug_logs'
_counter = 0


def _next_seq() -> int:
    global _counter
    _counter += 1
    return _counter


def _sanitize_path(path: str) -> str:
    safe = ''.join(ch if ch.isalnum() else '_' for ch in path).strip('_')
    return safe[:60] if safe else 'root'


def _safe_json_parse(body: bytes):
    """尝试解析为 JSON，失败则返回原始字符串"""
    if not body:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body.decode('utf-8', errors='replace')


class DebugMiddleware(BaseHTTPMiddleware):
    """调试中间件：原封不动记录请求与响应数据"""

    def __init__(self, app, log_dir: str = DEBUG_LOG_DIR):
        super().__init__(app)
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        log.info(f'调试日志已开启，日志目录: {os.path.abspath(self.log_dir)}')

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # ── 读取请求 body ──
        request_body = await request.body()

        # body 已被读取，需重新构造 receive 供下游消费
        async def receive():
            return {'type': 'http.request', 'body': request_body, 'more_body': False}

        request = Request(request.scope, receive)

        # 请求元信息
        seq = _next_seq()
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        path_safe = _sanitize_path(request.url.path)

        log_entry = {
            'seq': seq,
            'timestamp': datetime.now().isoformat(),
            'request': {
                'method': request.method,
                'url': str(request.url),
                'path': request.url.path,
                'query_params': dict(request.query_params),
                'headers': dict(request.headers),
                'body': _safe_json_parse(request_body),
            },
            'response': None,
        }

        # ── 调用下游 ──
        response = await call_next(request)

        # ── 用 tee 包裹 body_iterator，既流式返回客户端又捕获完整 body ──
        chunks: list[bytes] = []
        original_iterator = response.body_iterator

        async def tee_iterator():
            async for chunk in original_iterator:
                chunks.append(chunk)
                yield chunk

        response.body_iterator = tee_iterator()

        # ── 等待响应完成后再写日志 ──
        # starlette 的 BaseHTTPMiddleware 会在返回后逐块发送，
        # 我们注册一个后台回调在发送完成后写日志
        async def on_finish():
            response_body = b''.join(chunks)
            log_entry['response'] = {
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'body': _safe_json_parse(response_body),
                'body_size': len(response_body),
            }
            filename = f'{seq:04d}_{ts}_{request.method}_{path_safe}.json'
            filepath = os.path.join(self.log_dir, filename)
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(log_entry, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log.error(f'写入调试日志失败: {e}')

        # hack: 通过 response 的 background tasks 确保发送完成后写日志
        from starlette.background import BackgroundTask
        if response.background is None:
            response.background = BackgroundTask(on_finish)
        else:
            # 已有 background task，追加
            original_bg = response.background
            async def combined_bg():
                await original_bg()
                await on_finish()
            response.background = BackgroundTask(combined_bg)

        return response
