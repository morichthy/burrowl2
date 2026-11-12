"""记录模型的取值与规则（纯函数）。对应草图 §1 两个轴、§4 判断、§6 规则、§12.4 可信度。

两个轴：
- 综合程度（layer）：original（原件一列：原件、过程日志、事实记录、读取记录）/ judgment / framework；
- 依据来源（source_class）：local（本地实证：在本项目内执行、测量或直接观察）/ external（外部报告）/
  inferred（推断：推理、讨论或 AI 生成，没有直接观测），三类之间没有固定高低。
"""
from typing import Literal

SourceClass = Literal["local", "external", "inferred"]
SOURCE_CLASSES = ("local", "external", "inferred")
ExternalTier = Literal["peer_reviewed", "preprint", "vendor", "web"]
ActorKind = Literal["human", "ai", "system"]
Boundary = Literal["complete", "truncated", "partial", "restricted"]

ARTIFACT_KINDS = ("file", "conversation", "literature", "dataset", "image", "log")

# 判断类型（D-14）。写的人只在三种里选：
#   conclusion 结论：关于对象的陈述，可以作为依据；
#   process    过程：提问、尝试、停下的原因与重开条件、目的。是重新综合框架的依据，但不能作为结论的依据；
#   normative  规定：约束、决定、指令。规定该怎么做，不陈述世界怎样，不参与真假排序，检索时排在最前。
# 更正、撤回、缺陷不再是判断（设计稿 10 D-01、D-04）：更正写成新版本，撤回、缺陷记在版本处置上。
# 谓词见 core/vocab.py。
WRITABLE_KINDS = ("conclusion", "process", "normative")
JUDGMENT_KINDS = WRITABLE_KINDS
NORMATIVE_KINDS = ("normative",)

PAGE_TYPES = ("entity", "concept", "synthesis", "description")
EDGE_ORIGINS = ("projection", "mechanical", "ai_inferred", "candidate")
# rule：按规则建立，无需复核；ai_reviewed：AI 已复核（设计稿 04 D-14，地位与"AI 生成未复核"相同）
REVIEW_STATES = ("ai_generated", "ai_reviewed", "human_reviewed", "rejected", "rule")
FRESHNESS = ("valid", "inputs_changed", "superseded", "unchecked")

# 系统流水：工作台、MCP 在做别的事时自动记下的过程日志（登记、读取、写判断、改设置……），不是操作或测量本身。
# 不触发"操作前未检查约束"，条目列表默认不列出（设计稿 07 D-10）
INTERNAL_OPS = ("artifact.", "judgment.", "framework.", "linking.", "constraints.", "agent.", "record.", "settings.",
                "extraction.", "review.", "search", "inspection.", "digest.", "reading.")

LAYER_OF_KIND = {
    "artifact": "original", "event": "original", "record": "original", "read": "original", "extraction": "original",
    "judgment": "judgment", "relation": "judgment",
    # 变更历史：不是条目，不能作为依据
    "review": "history", "version_state": "history", "replacement": "history", "policy": "history",
    "entity": "framework", "page": "framework", "edge": "framework",
    "inspection": "framework", "decision": "framework",  # 巡检包；待决策（含巡检发现，设计稿 08 §9）
}

EXTERNAL_RANK = {"peer_reviewed": 1, "preprint": 2, "vendor": 3, "web": 4}


LAYER_RANK = {"original": 0, "judgment": 1, "framework": 2}


def rank_key(hit: dict) -> tuple:
    """逐级比较，不打分（草图 §12.4）。hit 是带坐标的检索结果（设计稿 10 D-12）：

    第 1 级"排除被驳回和已被替代的"由调用方先排到后面；这里依次比较依据来源（含本地实证 > 外部按档次 > 推断）、
    综合程度、复核与反驳（人已复核在前；被反驳、人驳回降一级）、相关度（score 越小越好）。"""
    from .vocab import source_rank
    state = hit.get("state") or {}
    review = state.get("review", "none")
    marks = {m["mark"] for m in state.get("marks") or []}
    return (
        source_rank(hit.get("sources") or []),
        LAYER_RANK.get(hit["layer"], 3),
        (0 if review == "human_confirmed" else 1) + (1 if "opposed" in marks else 0)
        + (1 if review == "human_rejected" else 0),
        hit.get("score", 0.0),
    )
