"""OpenAI 兼容响应适配器

将 Aily session 事件流转换为 OpenAI Chat Completion 格式（流式 / 非流式）。
"""

import json
import uuid
import time
import asyncio
from typing import AsyncGenerator

from .session_watcher import SessionWatcher


async def openai_stream(watcher: SessionWatcher, model_name: str,
                        agent_id: str, user_content: str) -> AsyncGenerator[str, None]:
    """OpenAI 流式响应：监听 watcher 事件，转为 chat.completion.chunk

    输出 SSE 格式：
      data: {chunk}\n\n
      ...
      data: [DONE]\n\n
    """
    completion_id = f'chatcmpl-{uuid.uuid4().hex[:24]}'
    created = int(time.time())

    # 首块：role
    chunk = {
        'id': completion_id,
        'object': 'chat.completion.chunk',
        'created': created,
        'model': model_name,
        'choices': [{
            'index': 0,
            'delta': {'role': 'assistant', 'content': ''},
            'finish_reason': None,
        }],
    }
    yield f'data: {json.dumps(chunk, ensure_ascii=False)}\n\n'

    sent_content = ''
    sent_reasoning = ''

    deadline = time.time() + 600  # 10 分钟超时
    while time.time() < deadline:
        try:
            event = await asyncio.wait_for(watcher.event_queue.get(), timeout=5)
        except asyncio.TimeoutError:
            if watcher.run_completed:
                break
            continue

        etype = event.get('type', '')
        payload = event.get('payload', {}) or {}

        if etype == 'message.update':
            msg = payload.get('message', {}) or {}
            content = msg.get('content', '') or ''
            reasoning = msg.get('reasoningContent', '') or ''

            # 增量内容
            if content and content != sent_content:
                delta_text = content[len(sent_content):] if content.startswith(sent_content) else content
                if delta_text:
                    chunk = {
                        'id': completion_id,
                        'object': 'chat.completion.chunk',
                        'created': created,
                        'model': model_name,
                        'choices': [{
                            'index': 0,
                            'delta': {'content': delta_text},
                            'finish_reason': None,
                        }],
                    }
                    yield f'data: {json.dumps(chunk, ensure_ascii=False)}\n\n'
                sent_content = content

            # 思考过程
            if reasoning and reasoning != sent_reasoning:
                delta_text = reasoning[len(sent_reasoning):] if reasoning.startswith(sent_reasoning) else reasoning
                if delta_text:
                    chunk = {
                        'id': completion_id,
                        'object': 'chat.completion.chunk',
                        'created': created,
                        'model': model_name,
                        'choices': [{
                            'index': 0,
                            'delta': {'reasoning_content': delta_text},
                            'finish_reason': None,
                        }],
                    }
                    yield f'data: {json.dumps(chunk, ensure_ascii=False)}\n\n'
                sent_reasoning = reasoning

        elif etype == 'message.create':
            msg = payload.get('message', {}) or {}
            # 跳过用户消息
            if msg.get('role') == 'user':
                continue

        elif etype == 'tool_call.create':
            tc = payload.get('toolCall', {}) or {}
            chunk = {
                'id': completion_id,
                'object': 'chat.completion.chunk',
                'created': created,
                'model': model_name,
                'choices': [{
                    'index': 0,
                    'delta': {
                        'tool_call': {
                            'name': tc.get('name', tc.get('toolName', '')),
                            'arguments': json.dumps(tc.get('arguments', {}), ensure_ascii=False),
                        }
                    },
                    'finish_reason': None,
                }],
            }
            yield f'data: {json.dumps(chunk, ensure_ascii=False)}\n\n'

        elif etype == 'run.completed':
            break

    # 结束块
    chunk = {
        'id': completion_id,
        'object': 'chat.completion.chunk',
        'created': created,
        'model': model_name,
        'choices': [{
            'index': 0,
            'delta': {},
            'finish_reason': 'stop',
        }],
    }
    yield f'data: {json.dumps(chunk, ensure_ascii=False)}\n\n'
    yield 'data: [DONE]\n\n'


async def openai_non_stream(watcher: SessionWatcher, model_name: str,
                            agent_id: str, user_content: str,
                            timeout: float = 600) -> dict:
    """OpenAI 非流式响应：等待完成，汇总内容"""
    events = await watcher.wait_for_completion(timeout=timeout)

    content = ''
    reasoning = ''
    tool_calls = []
    for event in events:
        etype = event.get('type', '')
        payload = event.get('payload', {}) or {}
        if etype == 'message.update':
            msg = payload.get('message', {}) or {}
            if msg.get('role') == 'user':
                continue
            if msg.get('content'):
                content = msg['content']
            if msg.get('reasoningContent'):
                reasoning = msg['reasoningContent']
        elif etype == 'tool_call.create':
            tc = payload.get('toolCall', {}) or {}
            tool_calls.append({
                'name': tc.get('name', tc.get('toolName', '')),
                'arguments': tc.get('arguments', {}),
            })

    message = {
        'role': 'assistant',
        'content': content,
    }
    if reasoning:
        message['reasoning_content'] = reasoning
    if tool_calls:
        message['tool_calls'] = tool_calls

    return {
        'id': f'chatcmpl-{uuid.uuid4().hex[:24]}',
        'object': 'chat.completion',
        'created': int(time.time()),
        'model': model_name,
        'choices': [{
            'index': 0,
            'message': message,
            'finish_reason': 'stop',
        }],
        'usage': {
            'prompt_tokens': len(user_content),
            'completion_tokens': len(content),
            'total_tokens': len(user_content) + len(content),
        },
    }
