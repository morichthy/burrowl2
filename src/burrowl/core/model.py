"""记录模型的取值与规则（纯函数）。对应草图 §1 两个轴、§4 判断、§6 规则、§12.4 可信度。

两个轴：
- 综合程度（layer）：original（原件一列：原件、过程日志、事实记录、读取记录）/ judgment / framework；
- 依据来源（source_class）：executed（亲自执行或测量）/ external（外部报告）/ discussion（推断或讨论），
  三类之间没有固定高低。
"""
from typing import Literal

SourceClass = Literal["executed", "external", "discussion"]
ExternalTier = Literal["peer_reviewed", "preprint", "vendor", "web"]
ActorKind = Literal["human", "ai", "system"]
Boundary = Literal["complete", "truncated", "partial", "restricted"]

ARTIFACT_KINDS = ("file", "conversation", "literature", "dataset", "image", "log")

# 判断的言语类型。constraint / decision / instruction 规定该怎么做，不陈述世界怎样（DESIGN §0）
JUDGMENT_KINDS = (
    "claim", "observation", "question", "constraint", "decision", "instruction",
    "purpose", "stop_reason", "review", "correction", "retraction", "defect",
)
NORMATIVE_KINDS = ("constraint", "decision", "instruction")
# 只能由人通过人工修改入口写入的类型（草图 §4 更正与撤回、§13）
HUMAN_ONLY_KINDS = ("correction", "retraction", "defect", "review")

# 判断间关系，尽量对应 W3C PROV 命名（DESIGN §3.1）
LINK_RELS = (
    "used", "depends_on", "supports", "opposes", "answers", "targets",
    "supersedes", "coexists_under", "corrects", "retracts", "defect_of", "wasRevisionOf",
)
# 指向某条判断后，它就不再是"当前主张"的关系；检索时仍返回，但带标注（DESIGN §3.3 第 5 步）
SUPERSEDING_RELS = ("supersedes", "corrects", "retracts", "wasRevisionOf")

PAGE_TYPES = ("entity", "concept", "synthesis", "description")
EDGE_ORIGINS = ("projection", "mechanical", "ai_inferred", "candidate")
REVIEW_STATES = ("ai_generated", "human_reviewed", "rejected", "rule")  # rule：按规则建立，无需复核
FRESHNESS = ("valid", "inputs_changed", "superseded", "unchecked")

LAYER_OF_KIND = {
    "artifact": "original", "event": "original", "record": "original", "read": "original",
    "judgment": "judgment", "link": "judgment",
    "entity": "framework", "page": "framework", "edge": "framework",
}

EXTERNAL_RANK = {"peer_reviewed": 1, "preprint": 2, "vendor": 3, "web": 4}


def derive_credibility(basis: list[dict], *, author_kind: str, kind: str) -> dict:
    """推出判断的写入时可信度（草图 §13 第 1 条：由系统根据被引用条目推出，AI 不能自己声明）。

    basis 中每项至少有 source_classes（列表）、complete（布尔）、external_tiers（列表）。
    没有依据的判断：人写的 observation 记为亲自执行（DESIGN §0 人的第一手观察），其余记为推断或讨论。
    """
    normative = kind in NORMATIVE_KINDS  # 约束、决定、指令规定该怎么做，不陈述世界怎样，不参与真假排序
    if not basis and normative:
        classes, tiers, complete = set(), set(), True
    elif not basis:
        own = "executed" if (author_kind == "human" and kind == "observation") else "discussion"
        classes, tiers, complete = {own}, set(), own == "executed"
    else:
        classes = {c for b in basis for c in b["source_classes"]}
        tiers = {t for b in basis for t in b.get("external_tiers", [])}
        complete = all(b["complete"] for b in basis)
    return {
        "source_classes": sorted(classes),
        "external_tiers": sorted(tiers, key=lambda t: EXTERNAL_RANK.get(t, 9)),
        "includes_executed": "executed" in classes,
        # 规则 ②：只有全部依据都来自亲自执行，才能称为"我们验证过的"
        "verified_by_us": classes == {"executed"},
        "mixed": len(classes) > 1,
        "basis_complete": complete,
        "basis_count": len(basis),
        "normative": normative,
    }


def source_rank(source_classes: list[str], external_tiers: list[str]) -> int:
    """草图 §12.4 排序第 2 级：包含亲自执行 > 外部报告（按细分）> 推断。混合来源按最强的一个排。"""
    if "executed" in source_classes:
        return 0
    if "external" in source_classes:
        return min((EXTERNAL_RANK.get(t, 4) for t in external_tiers), default=4)
    return 5


LAYER_RANK = {"original": 0, "judgment": 1, "framework": 2}


def rank_key(hit: dict) -> tuple:
    """逐级比较，不打分（草图 §12.4）。hit 需含 layer、source_classes、external_tiers、review、opposed、score。

    第 1 级"排除被驳回和已被替代的"由调用方先过滤；这里只排序。score 是全文检索的相关度（越小越好）。
    """
    review = hit.get("review")
    review_rank = 0 if review == "human_reviewed" else 1
    return (
        source_rank(hit.get("source_classes", []), hit.get("external_tiers", [])),
        LAYER_RANK[hit["layer"]],
        review_rank + (1 if hit.get("opposed") else 0),
        hit.get("score", 0.0),
    )
