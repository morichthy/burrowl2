"""入口共用：数据目录与调用者身份的确定。

身份规则（草图 §13；DESIGN §2）：
- MCP 入口一律是 AI；身份取 BURROWL_ACTOR_ID（agent 运行器会设置），否则为 ai:mcp；
- 工作台（HTTP）是人；
- 命令行默认是人；但 BURROWL_ACTOR_ID 以 ai: 开头时（agent 在子进程里调用命令行）记为 AI。
会话取 BURROWL_SESSION，否则每个进程新开一个；命令行以 AI 身份调用时按父进程与日期确定（设计稿 07 D-11）。
"""
import hashlib
import os
from datetime import UTC, date, datetime
from pathlib import Path

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import new_id
from .install import default_workspace


def data_dir(explicit: str | None = None) -> Path:
    """--data → BURROWL_DATA → burrowl init 登记的默认数据目录；都没有时报错，不猜一个位置。"""
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("BURROWL_DATA"):
        return Path(os.environ["BURROWL_DATA"]).expanduser()
    default = default_workspace()
    if default is None:
        raise BurrowlError("NO_DATA_DIR", "没有指定数据目录：用 --data，或先运行 burrowl init <目录> 登记默认数据目录")
    return default


_PROCESS_SESSION = os.environ.get("BURROWL_SESSION") or new_id("ses")


def parent_session(ppid: int | None = None, day: date | None = None) -> str:
    """命令行以 AI 身份调用、又没有 BURROWL_SESSION 时的会话（设计稿 07 D-11）：由父进程号和日期确定，
    同一个脚本或终端里连续的调用属于同一会话，而不是每次调用一个新会话。格式与 new_id 相同（ULID）。"""
    ppid = os.getppid() if ppid is None else ppid
    day = day or datetime.now(UTC).date()
    ms = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)
    value = (ms << 80) | int.from_bytes(hashlib.sha256(f"{ppid}:{day.isoformat()}".encode()).digest()[:10], "big")
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    chars = []
    for _ in range(26):
        chars.append(alphabet[value & 31])
        value >>= 5
    return "ses_" + "".join(reversed(chars))


def actor_for(channel: str, human_id: str = "human:cli") -> Actor:
    env_id = os.environ.get("BURROWL_ACTOR_ID")
    if channel == "mcp":
        return Actor(env_id or "ai:mcp", "ai", _PROCESS_SESSION)
    if channel == "cli" and env_id and env_id.startswith("ai:"):
        return Actor(env_id, "ai", os.environ.get("BURROWL_SESSION") or parent_session())
    return Actor(human_id, "human", _PROCESS_SESSION)
