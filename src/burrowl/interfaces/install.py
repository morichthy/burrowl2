"""安装位置、数据目录登记与 Skill 安装（沿用旧版的全局安装布局，DESIGN §8）。

安装根目录（root）：
    <root>/versions/<版本>/     每个版本一个完整目录（自带 Python）
    <root>/current              指向当前版本的目录联接；bin/burrowl.cmd 与 MCP 配置都经它找到当前版本
    <root>/bin/burrowl.cmd      加入用户 PATH 的启动器
    <root>/burrowl-install.json Skill 安装记录（与旧版格式相同：skill_dirs、skill_files）
    <root>/workspaces-v2.json   已登记的数据目录与默认数据目录（新版专用文件名，不读旧版的 workspaces.json）
开发环境（不在安装包内运行）时，root 是 ~/.burrowl2-dev。
"""
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from ..core.errors import BurrowlError

SKILL_FILES = ("RULES.md", "burrowl-work/SKILL.md", "burrowl-read/SKILL.md", "burrowl-consolidate/SKILL.md",
               "burrowl-inspect/SKILL.md")
AGENT_DISPATCH_MODES = ("terminal", "background")


def install_root() -> Path:
    home = os.environ.get("BURROWL_HOME")  # 启动器设置：<root>/current/ 或 <root>/versions/<版本>/
    if home:
        path = Path(home)
        return path.parent.parent if path.parent.name == "versions" else path.parent
    # 不经启动器、直接用安装包自带的 python.exe 运行时（MCP 登记就是这样）没有 BURROWL_HOME：
    # 按本文件所在位置认出安装布局 <root>/versions/<版本>/python/…（current 联接解析后也落在这里）
    for parent in Path(__file__).resolve().parents:
        if parent.parent.name == "versions" and (parent / "python").is_dir():
            return parent.parent.parent
    return Path.home() / ".burrowl2-dev"


def skills_source() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "skills" / "RULES.md").exists():
            return parent / "skills"
    raise BurrowlError("NOT_FOUND", "找不到 skills 目录")


def agent_dispatch() -> str:
    """一个安装内的工作台共用此偏好。已有安装在 Windows 默认使用终端。"""
    path = install_root() / "agent-dispatch"
    try:
        mode = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        mode = ""
    if not terminal_dispatch_supported():
        return "background"
    return mode if mode in AGENT_DISPATCH_MODES else "terminal"


def terminal_dispatch_supported() -> bool:
    return os.name == "nt"


def save_agent_dispatch(mode: str) -> None:
    root = install_root()
    root.mkdir(parents=True, exist_ok=True)
    # 每次写使用独立的临时文件，两个数据目录同时保存也不会相互覆盖临时内容。
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as tmp:
        path = Path(tmp.name)
        tmp.write(mode + "\n")
    try:
        path.replace(root / "agent-dispatch")
    finally:
        path.unlink(missing_ok=True)


# ---------- 数据目录登记 ----------
def _registry_path() -> Path:
    return install_root() / "workspaces-v2.json"


def registry() -> dict:
    """{"workspaces": [路径…], "default": 路径, "names": {路径: 名称}}。

    names 是 2.0.0a8 加的（名称用在工作台网址 ?db= 里），旧文件没有时按目录名补。
    """
    path = _registry_path()
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    state.setdefault("workspaces", [])
    state.setdefault("default", None)
    names = state.setdefault("names", {})
    for root in state["workspaces"]:
        if root not in names:
            names[root] = _unique_name(Path(root).name or "data", names, root)
    return state


def _unique_name(base: str, names: dict, own: str) -> str:
    """名称用在网址里（?db=名称），在已登记目录之间唯一；重名时加 -2、-3。"""
    taken = {v for k, v in names.items() if k != own}
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


def _save_registry(state: dict) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def register_workspace(data: Path, make_default: bool = True, name: str | None = None) -> dict:
    """登记数据目录。还没有默认目录时，第一个登记的自动成为默认。"""
    state = registry()
    resolved = str(data.resolve())
    if resolved not in state["workspaces"]:
        state["workspaces"].append(resolved)
    if name:
        state["names"][resolved] = _unique_name(name, state["names"], resolved)
    elif resolved not in state["names"]:
        state["names"][resolved] = _unique_name(Path(resolved).name or "data", state["names"], resolved)
    if make_default or not state["default"]:
        state["default"] = resolved
    _save_registry(state)
    return state


def default_workspace() -> Path | None:
    state = registry()
    value = state.get("default") or (state["workspaces"][0] if state["workspaces"] else None)
    return Path(value) if value else None


def workspaces() -> list[dict]:
    """已登记的数据目录：[{name, path, default, exists}]，默认目录排第一。"""
    state = registry()
    default = state.get("default")
    items = [{"name": state["names"][p], "path": p, "default": p == default,
              "exists": (Path(p) / "ledger.sqlite").exists()} for p in state["workspaces"]]
    return sorted(items, key=lambda i: not i["default"])


def find_workspace(key: str) -> Path:
    """按名称或路径找已登记的数据目录；找不到报 NOT_FOUND。"""
    state = registry()
    for root in state["workspaces"]:
        if state["names"].get(root) == key:
            return Path(root)
    try:
        resolved = str(Path(key).expanduser().resolve())
    except OSError:
        resolved = ""
    if resolved in state["workspaces"]:
        return Path(resolved)
    raise BurrowlError("NOT_FOUND", f"数据目录 {key!r} 没有登记",
                       {"workspaces": [i["name"] for i in workspaces()]})


def name_of(root: Path) -> str | None:
    return registry()["names"].get(str(Path(root).resolve()))


def set_default_workspace(key: str) -> dict:
    state = registry()
    state["default"] = str(find_workspace(key))
    _save_registry(state)
    return state


def unregister_workspace(key: str) -> dict:
    """只从登记表移除，不碰目录里的数据。默认目录不能移除：先把别的目录设为默认。"""
    state = registry()
    root = str(find_workspace(key))
    if root == state.get("default"):
        raise BurrowlError("CONFLICT", "这是默认数据目录，不能移除；先把另一个目录设为默认")
    state["workspaces"].remove(root)
    state["names"].pop(root, None)
    _save_registry(state)
    return state


# ---------- Skill 安装与升级 ----------
def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_path() -> Path:
    return install_root() / "burrowl-install.json"


def _load_record() -> dict:
    path = _record_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"skill_dirs": {}, "skill_files": {}}


def _save_record(record: dict) -> None:
    path = _record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def install_skills(target: Path) -> dict:
    """把 Skill 装到 target。只替换或删除仍与安装记录一致（用户没改过）的文件，旧版装的文件同样适用。"""
    record = _load_record()
    target = target.expanduser().resolve()
    source = skills_source()
    written, kept, removed = [], [], []
    wanted = set()
    for rel in SKILL_FILES:
        # 旧版把 RULES.md 写成 rules.md；Windows 文件名不区分大小写，记录里的键一律小写
        dest = target / (rel.lower() if rel == "RULES.md" else rel)
        key = str(dest).lower()
        wanted.add(key)
        new = (source / rel).read_bytes()
        if dest.exists() and record["skill_files"].get(key) not in (None, _hash(dest)) and dest.read_bytes() != new:
            kept.append(str(dest))  # 用户改过，不覆盖
            continue
        if dest.exists() and key not in record["skill_files"] and dest.read_bytes() != new:
            kept.append(str(dest))  # 不是本程序写的文件
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(new)
        record["skill_files"][key] = hashlib.sha256(new).hexdigest()
        written.append(str(dest))
    prefix = str(target).lower() + os.sep
    for key, digest in list(record["skill_files"].items()):
        if key.startswith(prefix) and key not in wanted:
            path = Path(key)
            if path.exists() and _hash(path) == digest:
                path.unlink()
                removed.append(key)
                del record["skill_files"][key]
            elif not path.exists():
                del record["skill_files"][key]
            else:
                kept.append(key)
    record["skill_dirs"][str(target)] = {"dev": False}
    _save_record(record)
    return {"target": str(target), "written": written, "kept_modified": kept, "removed_old": removed}


def upgrade_skills() -> list[dict]:
    """刷新安装记录中登记过的全部 Skill 目录（安装脚本切换版本后调用）。"""
    return [install_skills(Path(d)) for d in list(_load_record()["skill_dirs"]) if Path(d).exists()]
