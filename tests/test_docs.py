"""文档与代码的形式一致性（docs/DOCUMENTATION_MAINTENANCE.md "自动检查"）。

只能发现形式上的不一致；语义变化仍要按维护闭环人工核对。
"""
import re
import sys
from pathlib import Path

from burrowl.interfaces.registry import load

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "ARCHITECTURE.md", *sorted((ROOT / "docs").rglob("*.md")),
        *sorted((ROOT / "skills").rglob("*.md")), *sorted((ROOT / ".claude" / "skills").rglob("*.md"))]
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def test_relative_links_resolve():
    broken = []
    for doc in DOCS:
        if doc.parent.name == "model":
            continue  # 研究目录的快照，保持原文；其中的链接指向研究目录里的同级文件
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (doc.parent / target).exists():
                broken.append(f"{doc.relative_to(ROOT)} → {target}")
    assert not broken, "死链：\n" + "\n".join(broken)


def test_architecture_covers_every_source_file():
    """每个源文件都要出现在 ARCHITECTURE 的模块影响表中（写文件路径，或写所在目录加 /** 通配）。"""
    text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    table = text[text.index("## 模块影响表"):text.index("## 状态由谁负责")]
    missing = []
    for path in sorted((ROOT / "src" / "burrowl").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or "web" in path.relative_to(ROOT / "src" / "burrowl").parts:
            continue
        rel = path.relative_to(ROOT / "src" / "burrowl").as_posix()
        if rel.endswith("__init__.py") and rel != "__init__.py" and path.stat().st_size < 200:
            continue  # 只有一行说明的包标记文件
        parents = [rel.rsplit("/", i)[0] + "/**" for i in range(1, rel.count("/") + 1)]
        if f"`{rel}`" not in table and not any(f"`{p}`" in table for p in parents):
            missing.append(rel)
    assert not missing, "这些源文件没有出现在 ARCHITECTURE 的模块影响表中：\n" + "\n".join(missing)


def test_skills_only_mention_agent_callable_tools():
    """Skill 中写成 `xxx_yyy` 或 xxx_yyy( 的 burrowl 工具必须存在，而且 agent 可调用（read / write）。"""
    ops = load()
    agent_tools = {s.tool_name for s in ops.values() if s.effect in ("read", "write")}
    all_tools = {s.tool_name for s in ops.values()}
    problems = []
    for doc in sorted((ROOT / "skills").rglob("*.md")):
        for name in set(re.findall(r"`([a-z]+_[a-z_0-9]+)", doc.read_text(encoding="utf-8"))):
            if name in agent_tools:
                continue
            if name in all_tools:
                problems.append(f"{doc.name}: {name} 只能由人使用，Skill 不应让 agent 调用")
            elif name.split("_")[0] in {s.name.split(".")[0] for s in ops.values()}:
                problems.append(f"{doc.name}: 工具 {name} 不存在")
    assert not problems, "\n".join(problems)


def test_ops_reference_is_current():
    sys.path.insert(0, str(ROOT / "tools"))
    import gen_reference  # noqa: PLC0415

    current = (ROOT / "docs" / "reference" / "ops.md").read_text(encoding="utf-8")
    assert current == gen_reference.render(), "docs/reference/ops.md 已过期：运行 uv run python tools/gen_reference.py"
