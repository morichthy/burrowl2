"""不可变 ID：`<前缀>_<ULID>`。ULID 是 48 位毫秒时间加 80 位随机数的 Crockford Base32 编码，按时间可排序。

底层只追加，所以 ID 本身就是版本；框架页用 `pg_…@版本号` 引用固定版本（DESIGN §0）。
"""
import os
import re
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

PREFIXES = {
    "art": "artifact",      # 原件
    "evt": "event",         # 过程日志
    "rec": "record",        # 事实记录（正式条目）
    "rd": "read",           # 读取记录（设计稿 01 D-03：自动日志，不作为条目显示）
    "ex": "extraction",     # 抽取记录（设计稿 01 D-10：原件的抽取层，不是条目）
    "jdg": "judgment",      # 判断
    "rev": "review",        # 复核记录（设计稿 04 D-18：被复核条目的变更历史，不是条目）
    "ret": "retirement",    # 原件退役与恢复记录（原件的状态历史，不是判断）
    "rpl": "replacement",   # 原件的替换记录（设计稿 07 D-03：原件的状态历史，不是判断）
    "lnk": "link",          # 判断间关系
    "ent": "entity",        # 框架：实体
    "pg": "page",           # 框架：页面
    "edg": "edge",          # 框架：边
    "dec": "decision",      # 待决策
    "run": "agent_run",     # agent 运行
    "ses": "session",       # 会话
}

ID_RE = re.compile(r"^(?P<prefix>[a-z]+)_(?P<ulid>[0-9A-HJKMNP-TV-Z]{26})(?:@(?P<version>\d+))?$")


def ulid(now_ms: int | None = None) -> str:
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix}")
    return f"{prefix}_{ulid()}"


def kind_of(entry_id: str) -> str | None:
    """返回 ID 对应的条目类型；不是合法 ID 时返回 None。"""
    m = ID_RE.match(entry_id)
    return PREFIXES.get(m.group("prefix")) if m else None


def split_version(ref: str) -> tuple[str, int | None]:
    """`pg_X@3` → (`pg_X`, 3)；不带版本时版本为 None。"""
    base, _, version = ref.partition("@")
    return base, int(version) if version else None
