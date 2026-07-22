"""Session 事件监听器"""

from __future__ import annotations

import json
import time
import logging
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Set, List, AsyncGenerator, TYPE_CHECKING

from .constants import FALLBACK_POLL_INTERVAL

if TYPE_CHECKING:
    from .http_client import AilyHTTPClient

log = logging.getLogger("aily")


@dataclass
class SessionWatcher:
    """监听一个 Aily session 的事件流

    工作方式：
      - init() 拉取历史事件，记录 max_seq
      - on_ws_push() 被 WS 管理器触发时做增量拉取
      - start_fallback() 启动兜底轮询（WS 不可靠时的保底方案）
      - events_stream() 提供 SSE 流
      - wait_for_completion() 阻塞等待完成
    """

    session_id: str
    http_client: "AilyHTTPClient"
    seen_seqs: Set[int] = field(default_factory=set)
    max_seq: int = 0
    run_completed: bool = False
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    _fallback_task: Optional[asyncio.Task] = None
    task_id: Optional[str] = None  # 关联的 task_id

    async def init(self):
        """初始化：拉取历史事件"""
        try:
            items = await self.http_client.fetch_events(self.session_id)
            for item in items:
                seq = item.get("seq", 0)
                self.seen_seqs.add(seq)
                if seq > self.max_seq:
                    self.max_seq = seq
            log.info(
                f"Session {self.session_id}: 初始拉取 {len(items)} 条历史事件, maxSeq={self.max_seq}"
            )
        except Exception as e:
            log.warning(f"Session {self.session_id}: 初始拉取失败: {e}")

    async def on_ws_push(self):
        """WS 推送回调：触发增量拉取"""
        await self._pull_incremental()

    async def _pull_incremental(self):
        """增量拉取新事件并入队"""
        if self.run_completed:
            return
        try:
            items = await self.http_client.fetch_events(self.session_id)
            new_items = sorted(
                [it for it in items if it.get("seq", 0) not in self.seen_seqs],
                key=lambda x: x.get("seq", 0),
            )
            for item in new_items:
                seq = item.get("seq", 0)
                self.seen_seqs.add(seq)
                if seq > self.max_seq:
                    self.max_seq = seq
                payload = item.get("payload", {})
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        pass
                event = {
                    "type": item.get("type", "unknown"),
                    "seq": seq,
                    "payload": payload,
                    "timestamp": int(time.time()),
                }
                await self.event_queue.put(event)
                if event["type"] == "run.completed":
                    self.run_completed = True
        except Exception as e:
            log.warning(f"Session {self.session_id}: 增量拉取失败: {e}")

    def start_fallback(self):
        """启动兜底轮询任务"""
        if self._fallback_task and not self._fallback_task.done():
            return
        self._fallback_task = asyncio.create_task(self._fallback_loop())

    async def stop_fallback(self):
        """停止兜底轮询"""
        if self._fallback_task and not self._fallback_task.done():
            self._fallback_task.cancel()

    async def _fallback_loop(self):
        """兜底轮询循环"""
        while not self.run_completed:
            try:
                await asyncio.sleep(FALLBACK_POLL_INTERVAL)
                await self._pull_incremental()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"兜底轮询失败: {e}")

    async def events_stream(self) -> AsyncGenerator[str, None]:
        """SSE 事件流生成器"""
        while True:
            try:
                event = await asyncio.wait_for(self.event_queue.get(), timeout=30)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] == "run.completed":
                    yield f"data: {json.dumps({'type': 'stream.end', 'reason': 'run.completed'}, ensure_ascii=False)}\n\n"
                    break
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"

    async def wait_for_completion(self, timeout: float = 600) -> List[dict]:
        """阻塞等待 session 完成，返回所有新事件"""
        events = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                event = await asyncio.wait_for(self.event_queue.get(), timeout=5)
                events.append(event)
                if event["type"] == "run.completed":
                    return events
            except asyncio.TimeoutError:
                if self.run_completed:
                    return events
                continue
        return events
