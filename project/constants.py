"""全局常量定义"""

BASE_URL = 'https://aily.feishu.cn'
API_PREFIX = '/workbench/api/v1'
WS_URL = 'wss://aily-workbench-ws.feishu.cn/ws/v2'
WS_SUBPROTOCOL = 'pbbp2'

HEARTBEAT_INTERVAL = 15        # WebSocket 心跳间隔（秒）
TICKET_REFRESH_INTERVAL = 240  # WS ticket 续期间隔（秒）
FALLBACK_POLL_INTERVAL = 5     # 兜底轮询间隔（秒）

DEFAULT_WORKSPACE_ID = '7664492972083334362'
DEFAULT_DEVICE_ID = '75832975860815'
DEFAULT_PORT = 8765
DEFAULT_HOST = '0.0.0.0'
