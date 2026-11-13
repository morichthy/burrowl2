"""不可变 ID：`<前缀>_<ULID>`。ULID 是 48 位毫秒时间加 80 位随机数的 Crockford Base32 编码，按时间可排序。

条目 ID 稳定，版本写 `@n`（设计稿 10 D-01）：`jdg_…@3`、`art_…@2#p3-2`、`pg_…@4` 都是固定版本的引用；
不带 `@n` 指当前版。
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
    "vst": "version_state", # 人对某一版的处置：撤回、缺陷、退役及取消（设计稿 10 D-04）
    "rpl": "replacement",   # 原件的替换记录（设计稿 07 D-03：原件的状态历史，不是判断）
    "pol": "policy",        # 原件的外发标记（设计稿 08 D-30：人的决定，不是条目）
    "ttl": "title",         # 判断的标题记录（D-101：标题是标签，改标题不产生新版本，不是条目）
    "rel": "relation",      # 关系：主语—谓词—宾语（设计稿 10 D-07）
    "ent": "entity",        # 框架：实体
    "pg": "page",           # 框架：页面
    "edg": "edge",          # 框架：边
    "dec": "decision",      # 待决策
    "run": "agent_run",     # agent 运行
    "ses": "session",       # 会话
    "insp": "inspection",   # 框架：巡检包（设计稿 08 D-14）
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
    """`pg_X@3` → (`pg_X`, 3)；不带版本时版本为 None。段落锚点要先去掉（见 parse_ref）。"""
    base, _, version = ref.partition("@")
    return base, int(version) if version else None


def parse_ref(ref: str) -> tuple[str, int | None, str]:
    """`art_X@2#p3-2` → (`art_X`, 2, `p3-2`)；`jdg_X` → (`jdg_X`, None, "")。"""
    head, _, anchor = (ref or "").partition("#")
    base, version = split_version(head)
    return base, version, anchor


def make_ref(entry_id: str, version: int | None = None, anchor: str = "") -> str:
    out = f"{entry_id}@{version}" if version else entry_id
    return f"{out}#{anchor}" if anchor else out
