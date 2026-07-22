"""智能体解析器"""

import json
import time
import logging
from dataclasses import dataclass
from typing import Optional, List

log = logging.getLogger("aily")


@dataclass
class AgentInfo:
    """智能体信息"""

    agent_id: str
    name: str
    description: str = ""
    role: str = "member"
    avatar_url: str = ""

    def to_openai_model(self) -> dict:
        """转为 OpenAI /v1/models 格式"""
        return {
            "id": self.name or self.agent_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "aily",
            "agent_id": self.agent_id,
            "description": self.description,
            "role": self.role,
        }


class AgentResolver:
    """解析智能体名/ID，支持模糊匹配

    数据来源策略：
      1. 优先调用 `aily-cli agent list`（带 name/description）
      2. 回退到 workbench members API（只有 agent_id）
      3. 两者结果合并去重
    """

    def __init__(self, http):
        self.http = http
        self._cache: List[AgentInfo] = []
        self._cache_time: float = 0
        self._cache_ttl: float = 300  # 5 分钟

    async def _fetch_via_aily_cli(self) -> Optional[List[AgentInfo]]:
        """通过 aily-cli 子进程获取带 name 的智能体列表"""
        import subprocess

        try:
            result = subprocess.run(
                ["aily-cli", "agent", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
            agents = []
            for m in data.get("members", []):
                a = m.get("agent", {})
                if not a:
                    continue
                agents.append(
                    AgentInfo(
                        agent_id=a.get("agentId", m.get("agentId", "")),
                        name=a.get("name", ""),
                        description=a.get("description", ""),
                        role=m.get("role", "member"),
                        avatar_url=a.get("avatarUrl", ""),
                    )
                )
            return agents if agents else None
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            return None

    async def _fetch_via_members_api(self) -> List[AgentInfo]:
        """通过 workbench members API 获取（只有 agent_id）"""
        members = await self.http.list_members()
        return [
            AgentInfo(
                agent_id=m.get("agentId", ""),
                name="",  # members API 不返回 name
                role=m.get("role", "member"),
            )
            for m in members
            if m.get("agentId")
        ]

    async def list_agents(self, force_refresh: bool = False) -> List[AgentInfo]:
        """列出所有可用智能体（带缓存）"""
        now = time.time()
        if (
            not force_refresh
            and self._cache
            and (now - self._cache_time) < self._cache_ttl
        ):
            return self._cache

        # 策略 1: aily-cli 子进程（带 name）
        agents = await self._fetch_via_aily_cli()

        # 策略 2: 回退到 members API
        if not agents:
            agents = await self._fetch_via_members_api()
        else:
            # 合并：aily-cli 已经有 name，再用 members API 补充 role 信息
            try:
                api_agents = await self._fetch_via_members_api()
                api_roles = {a.agent_id: a.role for a in api_agents}
                for a in agents:
                    if a.agent_id in api_roles:
                        a.role = api_roles[a.agent_id]
            except Exception:
                pass

        self._cache = agents
        self._cache_time = now
        return agents

    async def resolve(self, query: str) -> Optional[AgentInfo]:
        """根据名称或 ID 解析智能体

        支持：
          - agent_id 精确匹配（agent_xxx）
          - 中文/英文名精确匹配
          - 名称模糊匹配
          - 描述模糊匹配
        """
        if not query:
            return None
        agents = await self.list_agents()
        # 1. agent_id 精确匹配
        for a in agents:
            if a.agent_id == query:
                return a
        # 2. 名称精确匹配
        for a in agents:
            if a.name == query:
                return a
        # 3. 名称模糊匹配
        matches = [a for a in agents if query in a.name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return min(matches, key=lambda x: len(x.name))
        # 4. 描述模糊匹配
        desc_matches = [a for a in agents if a.description and query in a.description]
        if desc_matches:
            return desc_matches[0]
        return None
