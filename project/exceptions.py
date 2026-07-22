"""自定义异常"""


class CookieExpiredError(Exception):
    """Cookie 已过期，需要重新登录更新"""

    pass


class APIError(Exception):
    """Aily API 调用错误"""

    def __init__(self, msg: str, code: int = -1):
        super().__init__(msg)
        self.code = code
