"""词表（设计稿 10 D-08、D-14、D-16）：坐标取值、谓词、标记的名字、中文、分组、严重度只在这里定义一次。

`status_note`、前端标签（操作 vocab.get）、参考文档都从这里生成。纯数据与纯函数，不依赖其他模块。

三个部分（设计稿 10 §2）：
- 条目：节点，存事实；
- 关系：主语—谓词—宾语，一条一行，两端固定到版本；
- 坐标：读取时推出，四组——地位（layer × sources）、类型（kind）、现状（state）、说明（notes）。
"""

# ---------- 坐标取值（D-12） ----------
LAYERS = {"original": "原件", "judgment": "判断", "framework": "框架"}

# 依据来源记号：local、external:<档次>、external（未分档）、inferred
SOURCE_LABELS = {
    "local": "本地实证",
    "external:peer_reviewed": "外部报告（同行评议）",
    "external:preprint": "外部报告（预印本）",
    "external:vendor": "外部报告（厂商资料）",
    "external:web": "外部报告（网页）",
    "external": "外部报告",
    "inferred": "推断",
}
EXTERNAL_TIERS = ("peer_reviewed", "preprint", "vendor", "web")
# 排序用：越小越靠前（草图 §12.4：包含本地实证 > 外部报告（按细分）> 推断）
SOURCE_RANK = {"local": 0, "external:peer_reviewed": 1, "external:preprint": 2, "external:vendor": 3,
               "external:web": 4, "external": 4, "inferred": 5}

KINDS = {
    # 原件一列
    "artifact": "原件", "event": "过程日志", "record": "事实记录", "read": "读取记录",
    # 判断一列（写的人只在这三种里选）
    "conclusion": "结论", "thought": "思路", "constraint": "约束",
    # 框架一列
    "entity": "实体页", "concept": "概念页", "synthesis": "综合页", "description": "描述页", "point": "要点",
    "edge": "关联边",
}
# 思路的用途、约束的作用对象（设计稿 15 D-25、D-38）
SUBKIND_LABELS = {
    "question": "提问", "attempt": "尝试", "stopped": "停下的路线", "hypothesis": "假设", "association": "联想",
    "aim": "目的", "action": "行动", "usage": "使用",
}
JUDGMENT_KINDS = ("conclusion", "thought", "constraint")
ORIGINAL_KINDS = ("artifact", "event", "record", "read")
PAGE_KINDS = ("entity", "concept", "synthesis", "description", "point")

VALIDITY = {"current": "当前有效", "replaced": "被替代", "withdrawn": "已撤回", "retired": "已退役",
            "lapsed": "依据失效"}
REVIEW = {"none": "未复核", "ai_confirmed": "AI 已复核", "ai_flagged": "AI 认为有问题", "ai_unsure": "AI 拿不准",
          "human_confirmed": "人已复核", "human_rejected": "人驳回"}
AUTHORS = {"human": "人", "ai": "AI", "system": "系统"}

# ---------- 谓词（D-08、D-09） ----------
# category：evidence 证据流 / stance 立场与结构 / replace 替代 / thought 思路 / framework 框架推断 / free 自由标签
# origin：judgment 判断层（写的人主张）/ mechanical 系统按规则 / framework 框架推断（可再生，不能作为依据）
# writers：谁能写；evidential：宾语是否被当作依据（宾语不能是思路，I11）；
# basis：是否参与写的一方的依据来源推出（只有 cites，D-13）；flow：证据流向，subject_to_object 或 object_to_subject
# （关系图把证据流统一画成"证据 → 结论"，D-22）
CATEGORIES = {"evidence": "证据流", "stance": "立场与结构", "replace": "替代", "process": "过程",
              "framework": "框架推断（不作为依据）", "free": "自由标签（系统不赋予含义）"}
CATEGORY_ORDER = ("stance", "replace", "evidence", "process", "framework", "free")  # 关系概况的排序（D-21）

PREDICATES: dict[str, dict] = {
    "cites": {"label": "依据", "inverse": "被依据", "category": "evidence", "origin": "judgment",
              "writers": ("human", "ai", "system"), "evidential": True, "basis": True, "flow": "object_to_subject"},
    "supports": {"label": "佐证", "inverse": "被佐证", "category": "evidence", "origin": "judgment",
                 "writers": ("human", "ai"), "evidential": True, "basis": False, "flow": "subject_to_object"},
    "opposes": {"label": "反驳", "inverse": "被反驳", "category": "evidence", "origin": "judgment",
                "writers": ("human", "ai"), "evidential": False, "basis": False, "flow": "subject_to_object"},
    "coexists_under": {"label": "条件并存", "inverse": "条件并存", "category": "stance", "origin": "judgment",
                       "writers": ("human", "ai"), "qualifiers": ("condition",), "required": ("condition",)},
    "answers": {"label": "回答", "inverse": "被回答", "category": "stance", "origin": "judgment",
                "writers": ("human", "ai")},
    "targets": {"label": "针对", "inverse": "被针对", "category": "stance", "origin": "judgment",
                "writers": ("human", "ai")},
    # 前提（设计稿 15 D-28）：建立在一条尚未证实的假设上。不是依据，但前提被反驳、撤回时带"前提有变化"
    "assumes": {"label": "前提", "inverse": "是……的前提", "category": "stance", "origin": "judgment",
                "writers": ("human", "ai")},
    "supersedes": {"label": "替代", "inverse": "被替代", "category": "replace", "origin": "judgment",
                   "writers": ("human",)},
    "consumed": {"label": "用到", "inverse": "被用到", "category": "process", "origin": "mechanical",
                 "writers": ("human", "ai", "system")},
    "produced": {"label": "产出", "inverse": "产出自", "category": "process", "origin": "mechanical",
                 "writers": ("human", "ai", "system")},
    "relates": {"label": "关系", "inverse": "关系", "category": "free", "origin": "judgment",
                "writers": ("human", "ai"), "required": ("label",)},
    # 框架推断：存在框架库（可再生），由关系服务统一呈现
    "may_contradict": {"label": "可能矛盾", "inverse": "可能矛盾", "category": "framework", "origin": "framework"},
    "may_supersede": {"label": "可能替代", "inverse": "可能被替代", "category": "framework", "origin": "framework"},
    "may_support": {"label": "可能佐证", "inverse": "可能被佐证", "category": "framework", "origin": "framework"},
    "similar": {"label": "相似", "inverse": "相似", "category": "framework", "origin": "framework"},
    "analogy": {"label": "类比", "inverse": "类比", "category": "framework", "origin": "framework"},
    "related": {"label": "相关", "inverse": "相关", "category": "framework", "origin": "framework"},
    "mentions": {"label": "提及", "inverse": "被提及", "category": "framework", "origin": "framework"},
    "about": {"label": "关于", "inverse": "相关条目", "category": "framework", "origin": "framework"},
    "derived_from": {"label": "综合自", "inverse": "被综合进", "category": "framework", "origin": "framework"},
    "subject_of": {"label": "是……的主题", "inverse": "主题", "category": "framework", "origin": "framework"},
}
for _name, _p in PREDICATES.items():
    _p.setdefault("writers", ())
    _p.setdefault("evidential", False)
    _p.setdefault("basis", False)
    _p.setdefault("flow", None)
    _p.setdefault("qualifiers", ())
    _p.setdefault("required", ())

# 关系的说明（设计稿 11 D-01、D-02）：why 一句话，role 自由文本，marker 是正文里 [^n] 的编号。
# 只是写法提示，不是必填项；role 的候选只作输入建议，不校验。
NOTE_KEYS = ("why", "role", "marker")
ROLE_HINTS: dict[str, tuple[str, ...]] = {
    "cites": ("定义", "方法", "数据", "条件", "直接依据", "背景"),
    "supports": ("数值一致", "方法不同但结论一致", "条件更宽"),
    "opposes": ("数值冲突", "条件不同", "方法不同"),
}

LEDGER_PREDICATES = tuple(k for k, v in PREDICATES.items() if v["origin"] != "framework")
FRAMEWORK_PREDICATES = tuple(k for k, v in PREDICATES.items() if v["origin"] == "framework")
EVIDENTIAL = tuple(k for k, v in PREDICATES.items() if v["evidential"])
# AI 写判断时可以给出的关系（relations 参数）；人另外可以写 supersedes
AI_WRITABLE = tuple(k for k, v in PREDICATES.items() if "ai" in v["writers"] and v["origin"] == "judgment"
                    and k != "cites")
HUMAN_WRITABLE = tuple(k for k, v in PREDICATES.items() if "human" in v["writers"] and v["origin"] == "judgment"
                       and k != "cites")

# ---------- 标记（D-14） ----------
# group：state 现状 / notes 说明；severity：warn 需要留意 / info 提示
MARKS: dict[str, dict] = {
    "corroborated": {"group": "state", "label": "被佐证", "severity": "info",
                     "rule": "有入边 supports；出处带佐证方与它的依据来源"},
    "opposed": {"group": "state", "label": "被反驳", "severity": "warn", "rule": "有入边 opposes"},
    "basis_changed": {"group": "state", "label": "依据有变化", "severity": "warn",
                      "rule": "出边 cites 所指版本已不是当前版、被撤回，或所引段落的指纹对不上；出处带当前版"},
    "basis_lapsed": {"group": "state", "label": "部分依据已失效", "severity": "warn",
                     "rule": "出边 cites 所指原件已退役或已删除；全部失效时有效性为依据失效"},
    "defective": {"group": "state", "label": "本版有缺陷", "severity": "warn", "rule": "人在本版标了缺陷"},
    "inputs_changed": {"group": "state", "label": "输入已变化", "severity": "warn", "rule": "框架页的输入有变化"},
    "unchecked": {"group": "state", "label": "未核查", "severity": "info", "rule": "框架页尚未核查"},
    "recognition_unverified": {"group": "notes", "label": "依据含未确认的识别", "severity": "warn",
                               "rule": "出边 cites 所指段落来自未经人确认的 OCR / AI 识别（含公式 LaTeX）"},
    "conditions_unstated": {"group": "notes", "label": "转述但没写条件", "severity": "warn",
                            "rule": "有原作者的结论没有写条件"},
    "scope_unclear": {"group": "notes", "label": "适用范围未明", "severity": "warn",
                      "rule": "写的人声明了 scope_unclear（适用范围尚不清晰，条件里写明哪些清楚、哪些不清楚）"},
    "basis_incomplete": {"group": "notes", "label": "依据边界不完整", "severity": "info",
                         "rule": "所引事实记录的边界不完整，或所引判断依据不完整"},
    "no_basis": {"group": "notes", "label": "结论没有依据", "severity": "warn", "rule": "结论没有出边 cites"},
    "premise_changed": {"group": "state", "label": "前提有变化", "severity": "warn",
                        "rule": "出边 assumes 所指的前提被反驳、撤回或已不是当前版（设计稿 15 D-28）"},
    "same_source_support": {"group": "notes", "label": "只有同源佐证", "severity": "info",
                            "rule": "入边 supports 的一方与本条依据同一份原件，不计入被佐证（设计稿 15 D-18）"},
    "has_cautions": {"group": "notes", "label": "有使用前须知", "severity": "warn",
                     "rule": "有当前有效、未被反驳的使用约束针对本条（设计稿 15 D-38）"},
    "local_observation": {"group": "notes", "label": "人标了本地实证", "severity": "info",
                          "rule": "人写判断时勾了本地实证"},
    "local_roots": {"group": "notes", "label": "本地依据的独立来源", "severity": "info",
                    "rule": "本地实证依据来自互不相同的原件与会话，计数"},
}
STATE_MARKS = tuple(k for k, v in MARKS.items() if v["group"] == "state")
NOTE_MARKS = tuple(k for k, v in MARKS.items() if v["group"] == "notes")
WARN_MARKS = tuple(k for k, v in MARKS.items() if v["severity"] == "warn")


def predicate(name: str) -> dict | None:
    return PREDICATES.get(name)


def relation_phrase(name: str, *, outgoing: bool, label: str | None = None) -> str:
    """关系从某一端看的说法：出边"依据了"，入边"被依据"；自由谓词用它的标签。"""
    if name == "relates":
        return label or "关系"
    p = PREDICATES.get(name)
    if p is None:
        return name
    return p["label"] if outgoing else p["inverse"]


def source_of(source_class: str, tier: str | None = None) -> str:
    """原件登记时的来源与档次 → 来源记号。"""
    if source_class == "external":
        return f"external:{tier}" if tier in EXTERNAL_TIERS else "external"
    return source_class


def sort_sources(sources) -> list[str]:
    return sorted(set(sources), key=lambda s: (SOURCE_RANK.get(s, 9), s))


def source_rank(sources: list[str]) -> int:
    """排序第 2 级：混合来源按最强的一个排；没有来源（框架、规定）排最后。"""
    return min((SOURCE_RANK.get(s, 9) for s in sources), default=9)


def standing_label(layer: str, sources: list[str]) -> str:
    """地位的组合标签：判断 · 本地实证 + 外部报告（同行评议）。"""
    head = LAYERS.get(layer, layer)
    if not sources:
        return head
    return head + " · " + " + ".join(SOURCE_LABELS.get(s, s) for s in sort_sources(sources))


def mark_text(mark: dict) -> str:
    """一个标记的文字：名字 + 处数（出处多于一处时）。local_roots 写成"本地依据来自 N 个独立来源"。"""
    name = mark["mark"]
    if name == "local_roots":
        return f"本地依据来自 {mark.get('count', len(mark.get('via', [])))} 个独立来源"
    label = MARKS.get(name, {}).get("label", name)
    n = mark.get("count", len(mark.get("via") or []))
    return f"{label}（{n} 处）" if n > 1 else label


def status_note(coords: dict) -> str:
    """一行说明，按"地位 → 类型 → 现状 → 说明"（D-16、D-25）。正常条目只有地位与类型。"""
    kind = KINDS.get(coords["kind"], coords["kind"])
    if coords.get("subkind"):
        kind += f"（{SUBKIND_LABELS.get(coords['subkind'], coords['subkind'])}）"
    parts = [standing_label(coords["layer"], coords.get("sources") or []), kind]
    state = coords.get("state") or {}
    validity = state.get("validity", "current")
    if validity != "current":
        parts.append(VALIDITY.get(validity, validity))
    review = state.get("review", "none")
    if review not in ("none",):
        parts.append(REVIEW.get(review, review))
    parts.extend(mark_text(m) for m in state.get("marks") or [])
    notes = coords.get("notes") or {}
    if notes.get("quoted"):
        parts.append(f"转述 · 原作者 {notes['quoted']}")
    parts.extend(mark_text(m) for m in notes.get("marks") or [])
    return "；".join(parts)


def export() -> dict:
    """交给前端与参考文档的完整词表（操作 vocab.get）。"""
    return {"layers": LAYERS, "sources": SOURCE_LABELS, "kinds": KINDS, "validity": VALIDITY, "review": REVIEW,
            "authors": AUTHORS, "subkinds": SUBKIND_LABELS, "categories": CATEGORIES,
            "category_order": list(CATEGORY_ORDER),
            "predicates": {k: {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in v.items()}
                           for k, v in PREDICATES.items()},
            "marks": MARKS, "role_hints": {k: list(v) for k, v in ROLE_HINTS.items()}, "note_keys": list(NOTE_KEYS)}
