# Aily Server v2

飞书 Aily Workbench 长连接服务端，通过 WebSocket 实时接收飞书事件，并提供 OpenAI 兼容的 HTTP API。

## 功能特性

- WebSocket 长连接接收飞书 Aily Workbench 事件
- OpenAI 兼容 API 接口
- 异步处理，高性能
- 自动重连机制

## 环境要求

- Python 3.9+
- pip

## 安装

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 安装依赖
pip install -r project/requirements.txt
```

## 配置

复制配置示例并填写配置：

```bash
cp project/config.example.json config.json
```

编辑 `config.json`，填入飞书登录 cookie 等必要信息。

## 运行

```bash
python aily_server.py
```

服务默认运行在 `http://0.0.0.0:8765`

## API 接口

服务启动后可使用以下接口：

- `GET /` - 服务状态
- `POST /v1/chat/completions` - OpenAI 兼容的对话接口
- WebSocket 连接用于接收实时事件

## 项目结构

```
├── aily_server.py          # 主程序（单文件版本）
├── project/                # 模块化版本
│   ├── app.py
│   ├── config.py
│   ├── routes_*.py
│   ├── ws_manager.py
│   └── requirements.txt
├── config.json             # 运行时配置（已忽略）
└── README.md
```

## License

MIT
