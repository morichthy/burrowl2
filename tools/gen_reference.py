"""从操作注册表生成 docs/reference/ops.md。改了任何操作的名字、参数或说明后运行：

    uv run python tools/gen_reference.py

tests/test_docs.py 会检查生成结果与代码一致。
"""
import sys
from pathlib import Path

from burrowl.interfaces.registry import load

OUT = Path(__file__).resolve().parents[1] / "docs" / "reference" / "ops.md"
EFFECT = {"read": "读取", "write": "写入", "user": "仅人（工作台/命令行）", "admin": "维护（工作台/命令行）"}


def _type(schema: dict) -> str:
    if "anyOf" in schema:
        return " 或 ".join(_type(s) for s in schema["anyOf"] if s.get("type") != "null") + "（可空）"
    if schema.get("type") == "array":
        return f"{_type(schema.get('items', {}))}[]"
    return schema.get("type", "any")


def render() -> str:
    lines = ["# 操作参考", "", "由 `tools/gen_reference.py` 从代码生成，不要手改。MCP 工具名把点换成下划线；"
             "effect 为「仅人」「维护」的操作不出现在 MCP 中。", ""]
    ops = load()
    lines += ["| 操作 | MCP 工具 | effect | 说明 |", "|---|---|---|---|"]
    for name, spec in sorted(ops.items()):
        tool = spec.tool_name if spec.effect in ("read", "write") else "—"
        lines.append(f"| [`{name}`](#{name.replace('.', '')}) | {tool} | {EFFECT[spec.effect]} | {spec.summary} |")
    for name, spec in sorted(ops.items()):
        schema = spec.schema()
        required = set(schema.get("required", []))
        lines += ["", f"## {name}", "", spec.summary, ""]
        props = schema.get("properties", {})
        if not props:
            lines.append("无参数。")
            continue
        lines += ["| 参数 | 类型 | 必填 | 默认 | 说明 |", "|---|---|---|---|---|"]
        for key, prop in props.items():
            default = "" if key in required else f"`{prop.get('default')!r}`"
            lines.append(f"| `{key}` | {_type(prop)} | {'是' if key in required else ''} | {default} | "
                         f"{prop.get('description', '')} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    sys.stdout.write(f"wrote {OUT}\n")
