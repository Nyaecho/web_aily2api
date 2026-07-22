"""辅助函数"""

import json


def json_decode(val: str) -> str:
    """解码 Aily API 中 JSON 编码的字符串字段

    Aily 部分 API 字段（如 toValue、sessionId）会返回 JSON-marshaled 字符串：
      '""' → ''
      '"session_xxx"' → 'session_xxx'
      '"hello"' → 'hello'
    """
    if not isinstance(val, str) or not val:
        return val
    # 快速判断：只有看起来像 JSON 编码的才尝试解析
    if val.startswith('"') and val.endswith('"'):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val
