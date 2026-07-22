#!/usr/bin/env python3
"""aily_server 入口

用法：
  python3 -m aily_server --port 8765 --config config.json
"""

import sys
import logging
import argparse

import uvicorn

from .config import Config
from .app import create_app

# ─── 日志 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aily")


def main():
    parser = argparse.ArgumentParser(description="Aily Workbench 长连接服务端 v2")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    parser.add_argument("--host", default=None, help="监听地址")
    parser.add_argument(
        "--debug", action="store_true", help="开启调试日志，原封不动保存请求和返回数据"
    )
    args = parser.parse_args()

    try:
        config = Config.load(args.config)
    except (FileNotFoundError, ValueError) as e:
        log.error(str(e))
        sys.exit(1)

    if args.port:
        config.port = args.port
    if args.host:
        config.host = args.host
    if args.debug:
        config.debug = True

    app = create_app(config)
    uvicorn.run(
        app, host=config.host, port=config.port, log_level="info", access_log=False
    )


if __name__ == "__main__":
    main()
