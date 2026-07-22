"""配置文件加载"""

import os
import re
import json
from dataclasses import dataclass

from .constants import (
    DEFAULT_WORKSPACE_ID,
    DEFAULT_DEVICE_ID,
    DEFAULT_PORT,
    DEFAULT_HOST,
)


@dataclass
class Config:
    """服务端配置"""

    cookie: str = ""
    csrf_token: str = ""
    device_id: str = DEFAULT_DEVICE_ID
    port: int = DEFAULT_PORT
    host: str = DEFAULT_HOST
    workspace_id: str = DEFAULT_WORKSPACE_ID
    debug: bool = False

    @classmethod
    def load(cls, path: str) -> "Config":
        """从 JSON 配置文件加载

        自动从 cookie 中提取 csrf_token（swp_csrf_token 或 x-lgw-csrf-token）。
        """
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"配置文件不存在: {path}\n请先运行 update_cookie.py 生成配置文件"
            )
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookie = data.get("cookie", "")
        if not cookie:
            raise ValueError("配置文件中 cookie 为空，请运行 update_cookie.py 更新")
        csrf = ""
        m = re.search(r"(?:swp_csrf_token|x-lgw-csrf-token)=([^;]+)", cookie)
        if m:
            csrf = m.group(1)
        return cls(
            cookie=cookie,
            csrf_token=csrf,
            device_id=data.get("device_id", DEFAULT_DEVICE_ID),
            port=data.get("port", DEFAULT_PORT),
            host=data.get("host", DEFAULT_HOST),
            workspace_id=data.get("workspace_id", DEFAULT_WORKSPACE_ID),
        )
