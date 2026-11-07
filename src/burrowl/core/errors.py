"""统一错误：BurrowlError(code, message, details)，在接口层转换为 HTTP、MCP 与退出码。"""
from typing import Any


class BurrowlError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}

    def problem(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


# HTTP 状态码映射；未列出的按 400 处理
HTTP_STATUS = {"NOT_FOUND": 404, "FORBIDDEN": 403, "CONFLICT": 409, "STALE_ARTIFACT": 409, "INTERNAL_ERROR": 500}
