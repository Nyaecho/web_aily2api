"""aily_server — Aily Workbench 长连接服务端 (v2 模块化版)

架构：
  外部脚本 (Playwright 登录) → 写入 config.json (cookie)
  Python 服务端读取 config.json → WS 长连接到 Aily
  其他进程通过 HTTP API 调用服务端（也支持 OpenAI 兼容协议）

模块结构：
  constants.py        — 全局常量
  exceptions.py       — 自定义异常
  proto.py            — Protobuf 编解码
  utils.py            — 辅助函数
  config.py           — 配置加载
  http_client.py      — Aily HTTP API 客户端
  agent_resolver.py   — 智能体解析器
  session_watcher.py  — Session 事件监听器
  ws_manager.py       — WebSocket 长连接管理器
  models.py           — Pydantic 请求模型
  state.py            — 全局状态容器
  openai_adapter.py   — OpenAI 兼容响应适配器
  routes_aily.py      — /api/* 路由
  routes_openai.py    — /v1/* 路由
  app.py              — FastAPI 应用创建与生命周期
  main.py             — 入口
"""
