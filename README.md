# Aily Workbench Server v2

飞书 Aily Workbench 长连接服务端，通过 WebSocket 实时接收事件，提供 HTTP API 和 OpenAI 兼容接口。

## 功能

- WebSocket 长连接自动管理
- 创建/管理 Aily 任务
- 发送消息、监听会话事件（SSE 流）
- OpenAI 兼容的 `/v1/chat/completions` 接口
- 支持流式和非流式响应
- 自动解析智能体（Agent）

## 安装

```bash
cd project
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

## 配置

复制配置模板：

```bash
cp project/config.example.json config.json
```

编辑 `config.json`，填入飞书登录 cookie：

```json
{
  "port": 8765,
  "host": "0.0.0.0",
  "workspace_id": "你的工作区ID",
  "device_id": "你的设备ID",
  "cookie": "你的飞书Cookie"
}
```

## 启动

```bash
python -m project.main --config config.json
```

可选参数：
- `--port 8765` - 指定端口
- `--host 0.0.0.0` - 指定监听地址
- `--debug` - 开启调试模式

## API 接口

### 基础

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息 |
| GET | `/api/health` | 健康检查 |

### Aily 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/create` | 创建任务 |
| GET | `/api/agents` | 列出可用智能体 |
| GET | `/api/sessions/{task_id}` | 获取 session_id |
| POST | `/api/send` | 发送消息 |
| POST | `/api/watch` | 启动会话监听 |
| POST | `/api/stop` | 停止会话监听 |
| GET | `/api/events/{session_id}` | SSE 事件流 |

### OpenAI 兼容

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/models` | 列出模型（智能体） |
| POST | `/v1/chat/completions` | 聊天补全 |

## 使用示例

### 创建任务并监听

```bash
# 创建任务
curl -X POST http://localhost:8765/api/tasks/create \
  -H "Content-Type: application/json" \
  -d '{"title": "测试任务", "agent": "智能体名称"}'

# 监听事件
curl http://localhost:8765/api/events/{session_id}
```

### OpenAI 兼容调用

```bash
curl http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "智能体名称",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

## 项目结构

```
├── config.json                 # 运行时配置（已忽略）
├── project/
│   ├── main.py                 # 入口
│   ├── app.py                  # FastAPI 应用
│   ├── config.py               # 配置加载
│   ├── models.py               # 数据模型
│   ├── routes_aily.py          # Aily API 路由
│   ├── routes_openai.py        # OpenAI 兼容路由
│   ├── openai_adapter.py       # OpenAI 格式适配
│   ├── ws_manager.py           # WebSocket 管理
│   ├── http_client.py          # HTTP 客户端
│   ├── agent_resolver.py       # 智能体解析
│   └── requirements.txt        # 依赖
└── README.md
```

## License

Apache License 2.0
