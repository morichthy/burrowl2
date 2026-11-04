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

from ..core.errors import BurrowlError

SKILL_FILES = ("RULES.md", "burrowl-work/SKILL.md", "burrowl-read/SKILL.md", "burrowl-consolidate/SKILL.md")


def install_root() -> Path:
    home = os.environ.get("BURROWL_HOME")  # 启动器设置：<root>/current/ 或 <root>/versions/<版本>/
    if home:
        path = Path(home)
        return path.parent.parent if path.parent.name == "versions" else path.parent
    return Path.home() / ".burrowl2-dev"


def skills_source() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "skills" / "RULES.md").exists():
            return parent / "skills"
    raise BurrowlError("NOT_FOUND", "找不到 skills 目录")


# ---------- 数据目录登记 ----------
def _registry_path() -> Path:
    return install_root() / "workspaces-v2.json"


def registry() -> dict:
    path = _registry_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"workspaces": [], "default": None}


def register_workspace(data: Path, make_default: bool = True) -> dict:
    state = registry()
    resolved = str(data.resolve())
    if resolved not in state["workspaces"]:
        state["workspaces"].append(resolved)
    if make_default:
        state["default"] = resolved
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def default_workspace() -> Path | None:
    value = registry().get("default")
    return Path(value) if value else None


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
