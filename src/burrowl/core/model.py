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
# 系统记录由人工操作生成，不可直接选择：更正、撤回、原件缺陷（草图 §4、§13）。
# review（复核）与 retirement（原件退役）是 2.0.0a13 及以前写成判断的历史记录：照常可读，但已不再写入，
# 也不作为判断出现在列表、检索、关系图里（HISTORY_KINDS）。复核改记 reviews 表（设计稿 04 D-18、D-21），
# 退役改记 retirements 表。
WRITABLE_KINDS = ("conclusion", "process", "normative")
SYSTEM_KINDS = ("review", "correction", "retraction", "defect", "retirement")
HISTORY_KINDS = ("review", "retirement")
AMEND_KINDS = ("correction", "retraction", "defect")
JUDGMENT_KINDS = WRITABLE_KINDS + SYSTEM_KINDS
NORMATIVE_KINDS = ("normative",)
HUMAN_ONLY_KINDS = SYSTEM_KINDS

# 判断间关系，尽量对应 W3C PROV 命名（DESIGN §3.1）
LINK_RELS = (
    "used", "depends_on", "supports", "opposes", "answers", "targets",
    "supersedes", "coexists_under", "corrects", "retracts", "defect_of", "wasRevisionOf", "retires",
)
# 指向某条判断后，它就不再是"当前主张"的关系；检索时仍返回，但带标注（DESIGN §3.3 第 5 步）
SUPERSEDING_RELS = ("supersedes", "corrects", "retracts", "wasRevisionOf")
# 结论通过这些关系依赖的对象必须是证据（原件或结论），不能是过程内容（D-15，防止思路混进证据链）
EVIDENTIAL_RELS = ("used", "depends_on", "supports")

PAGE_TYPES = ("entity", "concept", "synthesis", "description")
EDGE_ORIGINS = ("projection", "mechanical", "ai_inferred", "candidate")
# rule：按规则建立，无需复核；ai_reviewed：AI 已复核（设计稿 04 D-14，地位与"AI 生成未复核"相同）
REVIEW_STATES = ("ai_generated", "ai_reviewed", "human_reviewed", "rejected", "rule")
FRESHNESS = ("valid", "inputs_changed", "superseded", "unchecked")

LAYER_OF_KIND = {
    "artifact": "original", "event": "original", "record": "original", "read": "original", "extraction": "original",
    "judgment": "judgment", "link": "judgment",
    "review": "history", "retirement": "history",  # 变更历史：不是条目，不能作为依据
    "policy": "history",  # 原件的外发标记（设计稿 07 D-30）
    "entity": "framework", "page": "framework", "edge": "framework",
    "inspection": "framework", "decision": "framework",  # 巡检包；待决策（含巡检发现，设计稿 07 §9）
}

EXTERNAL_RANK = {"peer_reviewed": 1, "preprint": 2, "vendor": 3, "web": 4}


def derive_credibility(basis: list[dict], *, author_kind: str, kind: str, local_observation: bool = False) -> dict:
    """推出判断的写入时可信度（草图 §13 第 1 条：由系统根据被引用条目推出，AI 不能自己声明）。

    basis 中每项至少有 source_classes（列表）、complete（布尔）、external_tiers（列表）。
    没有依据时：规定不参与真假排序；人勾选"本地实证"（亲自看到或测到）的记为 local；其余记为 inferred。
    local_observation 只对人有效，调用方负责拒绝 AI 的勾选。
    """
    normative = kind in NORMATIVE_KINDS
    if not basis and normative:
        classes, tiers, complete = set(), set(), True
    elif not basis:
        own = "local" if (author_kind == "human" and local_observation) else "inferred"
        classes, tiers, complete = {own}, set(), own == "local"
    else:
        classes = {c for b in basis for c in b["source_classes"]}
        if author_kind == "human" and local_observation:
            classes.add("local")
        tiers = {t for b in basis for t in b.get("external_tiers", [])}
        complete = all(b["complete"] for b in basis)
    return {
        "source_classes": sorted(classes),
        "external_tiers": sorted(tiers, key=lambda t: EXTERNAL_RANK.get(t, 9)),
        "includes_local": "local" in classes,
        # 规则 ②：只有全部依据都是本地实证，才能称为"全部依据为本地实证"
        "all_local": classes == {"local"},
        "mixed": len(classes) > 1,
        "basis_complete": complete,
        "basis_count": len(basis),
        "normative": normative,
    }


def source_rank(source_classes: list[str], external_tiers: list[str]) -> int:
    """草图 §12.4 排序第 2 级：包含本地实证 > 外部报告（按细分）> 推断。混合来源按最强的一个排。"""
    if "local" in source_classes:
        return 0
    if "external" in source_classes:
        return min((EXTERNAL_RANK.get(t, 4) for t in external_tiers), default=4)
    return 5


LAYER_RANK = {"original": 0, "judgment": 1, "framework": 2}


def rank_key(hit: dict) -> tuple:
    """逐级比较，不打分（草图 §12.4）。hit 需含 layer、source_classes、external_tiers、review、opposed、score。

    第 1 级"排除被驳回和已被替代的"由调用方先过滤；这里只排序。score 是全文检索的相关度（越小越好）。
    判断的 review 是复核折算出的当前状态（设计稿 04 D-19）：同一依据来源档内人已复核的在前；
    复核未通过（rejected）与"有反对"一样降一级；AI 已复核与未复核相同。
    """
    review = hit.get("review")
    review_rank = 0 if review == "human_reviewed" else 1
    return (
        source_rank(hit.get("source_classes", []), hit.get("external_tiers", [])),
        LAYER_RANK.get(hit["layer"], 3),
        review_rank + (1 if hit.get("opposed") else 0) + (1 if hit["layer"] == "judgment" and review == "rejected"
                                                           else 0),
        hit.get("score", 0.0),
    )
