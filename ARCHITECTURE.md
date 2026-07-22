# 项目架构说明

## 概述

Aily Workbench Server v2 是一个 Python 异步服务端，通过 WebSocket 长连接实时接收飞书 Aily Workbench 事件，并提供 HTTP API（含 OpenAI 兼容协议）供其他进程调用。

## 模块结构

```
project/
├── main.py                 # 程序入口
├── app.py                  # FastAPI 应用创建与生命周期
├── config.py               # 配置加载
├── constants.py            # 全局常量
├── models.py               # 请求/响应数据模型
├── exceptions.py           # 自定义异常
├── utils.py                # 工具函数
│
├── routes_aily.py          # Aily 原生 API 路由
├── routes_openai.py        # OpenAI 兼容 API 路由
├── openai_adapter.py       # OpenAI 格式适配器
│
├── http_client.py          # Aily HTTP API 客户端
├── ws_manager.py           # WebSocket 长连接管理
├── session_watcher.py      # Session 事件监听器
├── agent_resolver.py       # 智能体解析器
├── proto.py                # Protobuf 编解码
└── debug_logger.py         # 调试日志中间件
```

## 核心模块详解

### 入口与应用

#### `main.py`
程序入口，解析命令行参数，加载配置，启动 uvicorn 服务器。

```
用法: python -m project.main --config config.json --port 8765 --debug
```

#### `app.py`
FastAPI 应用工厂，通过 lifespan 管理组件生命周期：
- **启动时**: 初始化 `ServerState`、HTTP 客户端、WebSocket 连接
- **关闭时**: 断开 WebSocket、关闭 HTTP 客户端

路由通过 `request.app.state.server` 访问全局状态。

#### `state.py`
全局状态容器 `ServerState`，持有所有核心组件实例：
- `config` - 配置
- `http_client` - HTTP 客户端
- `agent_resolver` - 智能体解析器
- `ws_manager` - WebSocket 管理器

提供 `auto_watch_session()` 方法自动创建并启动 watcher。

---

### 配置与模型

#### `config.py`
`Config` 数据类，从 JSON 文件加载配置：
- 自动从 cookie 提取 `csrf_token`
- 校验 cookie 是否存在

#### `constants.py`
全局常量定义：
- API 地址 (`BASE_URL`, `API_PREFIX`)
- WebSocket 地址 (`WS_URL`)
- 时间间隔（心跳、ticket 续期、轮询）
- 默认配置值

#### `models.py`
Pydantic 请求模型：
- `CreateTaskRequest` - 创建任务
- `SendMessage` - 发送消息
- `WatchRequest` / `StopRequest` - 监听控制
- `OpenAIChatRequest` - OpenAI 兼容请求

#### `exceptions.py`
自定义异常：
- `CookieExpiredError` - Cookie 过期
- `APIError` - API 调用错误

---

### 路由层

#### `routes_aily.py`
Aily 原生 API (`/api/*`)：

| 端点 | 功能 |
|------|------|
| `GET /api/health` | 健康检查 |
| `POST /api/tasks/create` | 创建任务（支持指定智能体、自动 watch） |
| `GET /api/agents` | 列出可用智能体 |
| `GET /api/sessions/{task_id}` | 获取 session_id |
| `POST /api/send` | 发送消息 |
| `POST /api/watch` | 启动会话监听 |
| `POST /api/stop` | 停止会话监听 |
| `GET /api/events/{session_id}` | SSE 事件流 |

#### `routes_openai.py`
OpenAI 兼容 API (`/v1/*`)：

| 端点 | 功能 |
|------|------|
| `GET /v1/models` | 列出模型（智能体列表） |
| `POST /v1/chat/completions` | 聊天补全（流式/非流式） |

工作流程：解析 model → 创建任务 → 获取 session → 启动 watch → 返回响应

#### `openai_adapter.py`
将 Aily session 事件流转换为 OpenAI 格式：
- `openai_stream()` - 流式 SSE 响应
- `openai_non_stream()` - 非流式汇总响应

支持 `content`、`reasoning_content`、`tool_call` 等字段。

---

### 通信层

#### `http_client.py`
`AilyHTTPClient` 封装 Aily Workbench HTTP API：
- `create_task()` - 创建任务
- `list_members()` - 列出成员
- `send_comment()` - 发送评论
- `get_session_id()` - 获取 session_id
- `fetch_events()` - 拉取事件
- `fetch_ticket()` - 获取 WebSocket ticket

自动处理 Cookie 过期检测和错误码转换。

#### `ws_manager.py`
`WSConnectionManager` 管理 WebSocket 长连接：
- 通过 ticket 建立连接
- 心跳保活（15 秒间隔）
- ticket 定期续期（240 秒间隔）
- 接收消息，解码 protobuf frame
- 收到推送时触发所有 watcher 增量拉取

#### `session_watcher.py`
`SessionWatcher` 监听单个 session 的事件流：
- `init()` - 拉取历史事件
- `on_ws_push()` - WS 推送回调，触发增量拉取
- `start_fallback()` - 启动兜底轮询（5 秒间隔）
- `events_stream()` - SSE 流生成器
- `wait_for_completion()` - 阻塞等待完成

#### `agent_resolver.py`
`AgentResolver` 智能体解析器：
- 支持 agent_id 精确匹配、名称匹配、模糊匹配
- 数据来源：优先 `aily-cli`，回退到 members API
- 5 分钟缓存

#### `proto.py`
Protobuf 编解码模块，处理 Aily WebSocket 的 `pbbp2` 子协议：
- 手工实现 varint 编解码
- `encode_frame()` / `decode_frame()` - frame 编解码

---

### 辅助模块

#### `utils.py`
工具函数：
- `json_decode()` - 解码 Aily API 中 JSON 编码的字符串

#### `debug_logger.py`
调试中间件 `DebugMiddleware`：
- `--debug` 模式下记录完整请求/响应
- 写入 `debug_logs/` 目录
- 支持 SSE 流式响应捕获

---

## 数据流

### 普通 API 调用
```
Client → HTTP API → routes_aily → http_client → Aily API
                      ↓
               session_watcher ← ws_manager ← WebSocket
                      ↓
               events_stream (SSE) → Client
```

### OpenAI 兼容调用
```
Client → /v1/chat/completions → routes_openai
           ↓
       agent_resolver (解析智能体)
           ↓
       http_client.create_task
           ↓
       session_watcher (监听事件)
           ↓
       openai_adapter (格式转换)
           ↓
       SSE Stream / JSON Response → Client
```

## 依赖

- `fastapi` - Web 框架
- `uvicorn` - ASGI 服务器
- `httpx` - 异步 HTTP 客户端
- `websockets` - WebSocket 客户端
- `pydantic` - 数据校验
