"""从操作注册表生成 docs/reference/ops.md，从词表（core/vocab.py）生成 docs/reference/vocab.md 与
frontend/src/vocab.gen.ts（设计稿 10 D-16）。改了任何操作、谓词、标记、坐标取值后运行：

    uv run python tools/gen_reference.py

tests/test_docs.py 会检查生成结果与代码一致。
"""
import json
import sys
from pathlib import Path

from burrowl.core import vocab
from burrowl.interfaces.registry import load

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "reference" / "ops.md"
VOCAB_MD = ROOT / "docs" / "reference" / "vocab.md"
VOCAB_TS = ROOT / "frontend" / "src" / "vocab.gen.ts"
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


def render_vocab_ts() -> str:
    data = json.dumps(vocab.export(), ensure_ascii=False, indent=2)
    return ("// 由 tools/gen_reference.py 从 src/burrowl/core/vocab.py 生成，不要手改（设计稿 10 D-16）。\n"
            f"export const VOCAB = {data} as const;\n")


def render_vocab_md() -> str:
    v = vocab.export()
    lines = ["# 词表", "", "由 `tools/gen_reference.py` 从 `src/burrowl/core/vocab.py` 生成，不要手改"
             "（设计稿 10 D-16）。坐标四组按显示顺序：地位（综合程度 × 依据来源）→ 类型 → 现状 → 说明。", ""]
    for title, key in (("综合程度 layer", "layers"), ("依据来源 sources", "sources"), ("类型 kind", "kinds"),
                       ("有效性 state.validity", "validity"), ("复核 state.review", "review"),
                       ("作者 notes.author", "authors")):
        lines += [f"## {title}", "", "| 取值 | 中文 |", "|---|---|"]
        lines += [f"| `{k}` | {label} |" for k, label in v[key].items()]
        lines.append("")
    lines += ["## 谓词", "", "核心谓词由系统依赖其含义；核心谓词都不合适时用 `relates` 加自由标签（D-09）。", "",
              "| 谓词 | 说法 | 反向说法 | 类别 | 来源 | 谁能写 | 作为依据 | 参与依据来源 |",
              "|---|---|---|---|---|---|---|---|"]
    for k, p in v["predicates"].items():
        lines.append(f"| `{k}` | {p['label']} | {p['inverse']} | {v['categories'][p['category']]} | {p['origin']} | "
                     f"{'、'.join(p['writers']) or '—'} | {'是' if p['evidential'] else ''} | "
                     f"{'是' if p['basis'] else ''} |")
    lines += ["", "## 标记", "", "每个标记带出处 via（造成它的关系与另一端，D-14）。", "",
              "| 标记 | 组 | 中文 | 严重度 | 推出规则 |", "|---|---|---|---|---|"]
    for k, m in v["marks"].items():
        lines.append(f"| `{k}` | {'现状' if m['group'] == 'state' else '说明'} | {m['label']} | {m['severity']} | "
                     f"{m['rule']} |")
    return "\n".join(lines) + "\n"


OUTPUTS = ((OUT, render), (VOCAB_MD, render_vocab_md), (VOCAB_TS, render_vocab_ts))


if __name__ == "__main__":
    for path, fn in OUTPUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fn(), encoding="utf-8", newline="\n")
        sys.stdout.write(f"wrote {path}\n")
