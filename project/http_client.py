"""Aily HTTP API 客户端"""

import time
import logging
from typing import Optional, List

import httpx

from .constants import BASE_URL, API_PREFIX
from .exceptions import CookieExpiredError, APIError
from .utils import json_decode

log = logging.getLogger('aily')


class AilyHTTPClient:
    """与 Aily Workbench HTTP API 交互"""

    def __init__(self, config):
        self.config = config
        self.client = httpx.AsyncClient(timeout=30, follow_redirects=False)

    # ── 任务创建 / 列表 ──

    async def create_task(self, title: str, description: str = '',
                          assignee_id: str = None, assignee_type: str = 'agent',
                          kind: str = 'oneshot', parts: list = None) -> dict:
        """创建新任务，返回 {task, taskUrl}"""
        url = f'{BASE_URL}{API_PREFIX}/workspaces/{self.config.workspace_id}/tasks'
        body = {
            'title': title,
            'description': description,
            'assigneeType': assignee_type,
            'kind': kind,
        }
        if assignee_id:
            body['assigneeId'] = assignee_id
        if parts:
            body['parts'] = parts

        resp = await self.client.post(url, headers=self._headers(svc_method='aily_workbench_CreateTask'),
                                       json=body)
        await self._check(resp, 'CreateTask')
        data = resp.json()
        return data.get('data', {})

    async def list_members(self) -> List[dict]:
        """列出 workspace 下的所有成员（含智能体）"""
        url = f'{BASE_URL}{API_PREFIX}/workspaces/{self.config.workspace_id}/members?pageSize=50'
        resp = await self.client.get(url, headers=self._headers())
        await self._check(resp, 'ListMembers')
        data = resp.json()
        return data.get('data', {}).get('members', [])

    # ── 消息 / Session ──

    async def send_comment(self, task_id: str, content: str, mentions: list = None,
                           notable: bool = False, client_request_id: str = None) -> dict:
        """发送评论消息到 task"""
        url = f'{BASE_URL}{API_PREFIX}/workspaces/-/tasks/{task_id}/comments'
        body = {
            'type': 'comment',
            'content': content,
            'attachmentIds': [],
            'parts': [],
            'clientRequestId': client_request_id or f'py_server_{int(time.time()*1000)}',
            'notable': notable,
            'mentions': mentions or [],
        }
        resp = await self.client.post(url, headers=self._headers(svc_method='aily_workbench_CreateComment'),
                                       json=body)
        await self._check(resp, 'CreateComment')
        data = resp.json().get('data', {})
        # 解码 JSON 编码的 sessionId
        if data.get('sessionId') and isinstance(data['sessionId'], str):
            data['sessionId'] = json_decode(data['sessionId'])
        return data

    async def get_session_id(self, task_id: str) -> Optional[str]:
        """获取 task 的 session_id

        注意：timeline API 的 toValue 字段是 JSON 编码的字符串
              '""' → 空字符串
              '"session_xxx"' → 实际 session_id
        """
        url = f'{BASE_URL}{API_PREFIX}/workspaces/-/tasks/{task_id}/timeline/scroll?pageSize=10&direction=newer'
        resp = await self.client.get(url, headers=self._headers())
        await self._check(resp, 'TimelineScroll')
        data = resp.json()
        for item in data.get('data', {}).get('items', []):
            for change in item.get('changes', []):
                if change.get('field') == 'sessionId':
                    val = change.get('toValue', '')
                    if not val:
                        continue
                    # JSON 解码 toValue
                    try:
                        val = json_decode(val)
                    except (ValueError, TypeError):
                        pass
                    if val and isinstance(val, str):
                        return val
        return None

    async def fetch_events(self, session_id: str, page_size: int = 200) -> list:
        """拉取 session 的事件列表"""
        url = f'{BASE_URL}{API_PREFIX}/sessions/{session_id}/events?pageSize={page_size}'
        resp = await self.client.get(url, headers=self._headers(accept_only=True))
        await self._check(resp, 'Events')
        return resp.json().get('data', {}).get('items', [])

    async def fetch_ticket(self) -> dict:
        """获取 WebSocket 连接 ticket"""
        url = f'{BASE_URL}{API_PREFIX}/ws/ticket'
        resp = await self.client.post(url, headers=self._headers(svc_method='FrontierBackService_GetSessionTicket'),
                                       json={})
        await self._check(resp, 'FetchTicket')
        return resp.json()['data']

    # ── 内部 ──

    async def _check(self, resp: httpx.Response, op: str):
        """检查 HTTP 响应，抛出对应异常"""
        if resp.status_code in (302, 401):
            raise CookieExpiredError(f'Cookie 已过期（{op}），请运行 update_cookie.py 更新')
        if resp.status_code >= 400:
            raise APIError(f'{op} HTTP {resp.status_code}: {resp.text[:200]}')
        try:
            data = resp.json()
        except Exception:
            return
        if data.get('code') not in (0, None):
            msg = data.get('msg', '')
            if 'login' in str(msg).lower() or 'expired' in str(msg).lower():
                raise CookieExpiredError(f'Cookie 已过期（{op}）：{msg}')
            raise APIError(f'{op} error: {msg}', code=data.get('code', -1))

    def _headers(self, accept_only: bool = False, svc_method: str = '') -> dict:
        """构造请求头"""
        h = {
            'Cookie': self.config.cookie,
            'Accept': 'application/json, text/plain, */*',
            'Referer': f'{BASE_URL}/',
        }
        if not accept_only:
            h.update({
                'Content-Type': 'application/json',
                'x-lgw-csrf-token': self.config.csrf_token,
                'x-svc-method': svc_method or 'aily_workbench_CreateComment',
                'x-lsc-bizid': '149',
                'x-lsc-terminal': 'web',
                'x-lsc-version': '1',
                'x-lang': 'zh-CN',
                'Origin': BASE_URL,
            })
        return h

    async def close(self):
        await self.client.aclose()
