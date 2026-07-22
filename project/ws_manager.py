"""WebSocket 长连接管理器"""

import logging
import asyncio
from typing import Optional, Dict
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed

from .constants import WS_URL, WS_SUBPROTOCOL, HEARTBEAT_INTERVAL, TICKET_REFRESH_INTERVAL
from .exceptions import CookieExpiredError
from .proto import decode_frame, encode_frame
from .session_watcher import SessionWatcher

log = logging.getLogger('aily')


class WSConnectionManager:
    """管理与 Aily Workbench 的 WebSocket 长连接

    职责：
      - 通过 HTTP API 获取 ticket，建立 WS 连接
      - 定时心跳保活
      - 定时续期 ticket 并重连
      - 接收 WS 消息，解码 protobuf frame
      - 收到推送时触发所有 SessionWatcher 增量拉取
    """

    def __init__(self, http, config):
        self.http = http
        self.config = config
        self.ws = None
        self.connected = False
        self.ticket_data: Optional[dict] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._ticket_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None
        self.watchers: Dict[str, SessionWatcher] = {}

    def build_ws_url(self, ticket: str) -> str:
        """构造带 ticket 的 WS URL"""
        params = urlencode({
            'device_platform': 'web',
            'version_code': 'fws_1.0.0',
            'access_key': 'c8dd92325e6ecf2c7e8b9f66428110cc',
            'fpid': '1595',
            'aid': '1017241',
            'device_id': self.config.device_id,
            'xsack': '1', 'xaack': '0', 'xsqos': '1',
            'qos_level': '2', 'qos_sdk_version': '2',
            'ticket': ticket,
        })
        return f'{WS_URL}?{params}'

    async def connect(self):
        """建立 WS 连接"""
        try:
            self.ticket_data = await self.http.fetch_ticket()
            ticket = self.ticket_data['ticket']
            url = self.build_ws_url(ticket)
            log.info(f'连接 WebSocket: {WS_URL}')
            self.ws = await websockets.connect(
                url, subprotocols=[WS_SUBPROTOCOL],
                ping_interval=None, ping_timeout=None, close_timeout=5,
            )
            self.connected = True
            log.info('WebSocket 已连接')
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._ticket_task = asyncio.create_task(self._ticket_refresh_loop())
            self._receive_task = asyncio.create_task(self._receive_loop())
            return True
        except CookieExpiredError:
            raise
        except Exception as e:
            log.error(f'WS 连接失败: {e}')
            self.connected = False
            return False

    async def disconnect(self):
        """断开 WS 连接，取消所有后台任务"""
        for task in [self._heartbeat_task, self._ticket_task, self._receive_task]:
            if task and not task.done():
                task.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.connected = False

    async def reconnect(self):
        """重连"""
        log.info('重新连接 WebSocket...')
        await self.disconnect()
        await asyncio.sleep(1)
        await self.connect()

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self.connected:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if self.ws:
                    await self.ws.send('hi')
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f'心跳失败: {e}')
                self.connected = False
                break

    async def _ticket_refresh_loop(self):
        """ticket 续期循环"""
        while self.connected:
            try:
                await asyncio.sleep(TICKET_REFRESH_INTERVAL)
                log.info('续期 WS ticket...')
                self.ticket_data = await self.http.fetch_ticket()
                log.info('ticket 续期成功，重连 WS...')
                await self.reconnect()
                break
            except asyncio.CancelledError:
                break
            except CookieExpiredError:
                log.error('Cookie 过期，无法续期 ticket')
                self.connected = False
                break
            except Exception as e:
                log.warning(f'ticket 续期失败: {e}')
                await asyncio.sleep(10)

    async def _receive_loop(self):
        """接收循环：解码 frame 并触发 watcher"""
        while self.connected:
            try:
                if not self.ws:
                    self.connected = False
                    break
                data = await self.ws.recv()
                if isinstance(data, str):
                    if data in ('hi', 'pong'):
                        continue
                    log.debug(f'WS 文本消息: {data[:100]}')
                    continue
                frame = decode_frame(data)
                if frame.get('service') == 0 and frame.get('method') == 5:
                    log_id = frame.get('log_id', 0)
                    ack = encode_frame(
                        seq_id=0, log_id=log_id,
                        service=9000, method=5,
                        headers=[{'key': 'cursor_file_name', 'value': 'FILE_NOT_EXIST'}],
                        frame_type=32,
                    )
                    await self.ws.send(ack)
                # 触发所有 watcher
                for watcher in list(self.watchers.values()):
                    asyncio.create_task(watcher.on_ws_push())
            except asyncio.CancelledError:
                break
            except ConnectionClosed:
                log.warning('WS 连接已关闭')
                self.connected = False
                break
            except Exception as e:
                log.error(f'WS 接收错误: {e}')
                await asyncio.sleep(0.5)

    def add_watcher(self, watcher: SessionWatcher):
        self.watchers[watcher.session_id] = watcher

    def remove_watcher(self, session_id: str):
        self.watchers.pop(session_id, None)
