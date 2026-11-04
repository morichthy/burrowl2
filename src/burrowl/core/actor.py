"""调用者身份。由接口层根据入口确定，不能由操作参数指定（草图 §13：描述可信度的字段不由被描述的一方填）。"""
from dataclasses import dataclass

from .errors import BurrowlError


@dataclass(frozen=True)
class Actor:
    id: str            # 例如 human:workbench、ai:claude:run_…
    kind: str          # human / ai / system
    session_id: str    # 过程日志的会话

    def require_human(self, what: str) -> None:
        if self.kind != "human":
            raise BurrowlError("FORBIDDEN", f"{what}只能由人通过工作台或命令行执行", {"actor": self.id})


SYSTEM = Actor("system", "system", "ses_system")
