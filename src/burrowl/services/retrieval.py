"""F8 检索与展开、约束生效（草图 §7、§12.4；DESIGN §0 约束如何强制生效；设计稿 06）。

检索（设计稿 06）：
- 召回落在检索单元上（相邻段落合并），几条路线用 RRF 合并：词法主路（双字 + 标识符，OR + bm25）、
  短语路（整个查询作为短语出现的段落）、向量路（可选）；设置为重排时重排前 rerank_top 个单元。
- 数量类参数（展示几个命中单元、片段长度、候选池、RRF 常数等）在 config.json 的 retrieval 组，
  工作台与 AI 读同一份，结果的 params 写明本次用的值（设计稿 06 D-21）。
- 同一条目的命中折叠成一条结果，带最多 3 个命中单元，命中再落回单元里最相关的段落（cite_as）。
- **名次只表示相关度**（D-09）；每条结果照常带地位坐标和一行说明。相关对象的有效约束单列在最前；
  已被替代、已退役的排在当前条目之后。order="status" 按草图 §12.4 的逐级规则排。
- 结果带继续查的线索（D-10 至 D-14）：依据（basis）、一跳关系（relations）、未展示的命中数、是否读过、提示。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import kind_of
from ..core.model import HISTORY_KINDS, INTERNAL_OPS, LAYER_OF_KIND, rank_key  # noqa: F401  INTERNAL_OPS 对外沿用
from ..index.tokenize import tokens

# 对象页不显示的自动日志：写判断、写框架页、检查约束这类系统操作的流水（设计稿 01 D-08）
AUTO_LOG_OPS = ("judgment.write", "framework.page_write", "constraints.check", "artifact.register", "artifact.read")
SOURCE_FIELDS = ("title", "filename", "suffix", "size", "media_type", "path", "external_tier")
# 检索参数的默认值（设计稿 06 D-21）：config.json 的 retrieval 组，DEFAULT_CONFIG 引用这里；
# 取值范围见 ops 的 SETTING_NUMBERS。
# 只影响查询，不用重建索引。limit / exact_limit 是省略 limit 时 search / search_exact 返回几条
RETRIEVAL_DEFAULTS = {
    "limit": 20, "exact_limit": 50,
    "passages_shown": 3,  # 每条结果展示几个命中单元
    "snippet_chars": 600,  # 每个片段最多几个字
    "basis_shown": 3,  # 依据 / 输入清单展示几条
    "relation_ids_shown": 5, "links_shown": 8,  # 一跳关系：引用它的判断、所在框架页各给几个 ID；判断的关系给几条
    "rerank_top": 20,  # 重排前几个单元（设置为重排时）
    "rrf_k": 60, "pool_min": 60, "pool_factor": 6,  # RRF 常数；每路候选池 max(pool_min, limit × pool_factor)
    "phrase_limit": 30,  # 短语路最多几个段落
    "associate_seeds": 5, "associate_fanout": 20,  # 联想：从前几条出发；每个节点每种关系最多展开几个
    "associate_vector_min": 0.4,  # 联想：向量近邻的最低相似度（jina 上跨语言的同主题段落约 0.45，无关的约 0.1–0.3）
}
LAYER_LABEL = {"original": "原件", "judgment": "判断", "framework": "框架"}
SOURCE_LABEL = {"local": "本地实证", "external": "外部报告", "inferred": "推断"}
TIER_LABEL = {"peer_reviewed": "同行评议", "preprint": "预印本", "vendor": "厂商资料", "web": "网页"}
SOURCE_FILTERS = ("all", "local", "external", "inferred")


def external_claim(judgment: dict, cred: dict) -> bool:
    """文献论断（设计稿 09 D-02）：带原作者，或当前依据全部是外部报告。规定不算。由系统推出，不落盘。"""
    if judgment.get("kind") != "conclusion":
        return False
    return bool(judgment["data"].get("external_author")) or set(cred.get("source_classes") or []) == {"external"}


def check_source(source: str) -> None:
    if source not in SOURCE_FILTERS:
        raise BurrowlError("INVALID_ARGUMENT", "source 必须是 all / local / external / inferred",
                           {"source": source})


def source_matches(coords: dict, source: str) -> bool:
    """按依据来源筛选（设计稿 09 D-03）。local：依据全部为本地实证的判断、本地实证原件，以及规定；
    external / inferred：依据含该来源的原件与判断。框架内容只在 all 时返回。"""
    if source == "all":
        return True
    if coords.get("layer") not in ("original", "judgment"):
        return False
    classes = set(coords.get("source_classes") or [])
    if source == "local":
        if coords.get("normative"):
            return True
        return coords.get("all_local", False) if coords.get("layer") == "judgment" else classes == {"local"}
    return source in classes


JUDGMENT_LABEL = {"conclusion": "结论", "process": "过程", "normative": "规定", "review": "复核",
                  "correction": "更正", "retraction": "撤回", "defect": "原件缺陷", "retirement": "原件退役"}


class RetrievalService:
    def __init__(self, ws):
        self.ws = ws

    def params(self) -> dict:
        """检索参数（设计稿 06 D-21）：config.json 的 retrieval 组，缺的键取默认值。"""
        return {**RETRIEVAL_DEFAULTS, **(self.ws.config.get("retrieval") or {})}

    # ---------- 地位坐标 ----------
    def coordinates(self, entry_id: str) -> dict:
        base = entry_id.split("#", 1)[0].split("@", 1)[0]
        kind = kind_of(base)
        if kind is None:
            raise BurrowlError("INVALID_REFERENCE", "不是合法的条目 ID", {"id": entry_id})
        layer = LAYER_OF_KIND.get(kind, "framework")
        if layer == "history":  # 复核记录、退役记录：变更历史，不是条目
            return {"layer": "history", "kind": kind, "source_classes": [], "external_tiers": []}
        if layer == "original":
            basis = self.ws.judgments.basis_of(base)
            state = self.ws.versions.state(base)
            out = {"layer": layer, "kind": kind, "source_classes": basis["source_classes"],
                   "external_tiers": basis["external_tiers"], "complete": basis["complete"],
                   "defective": bool(state["defective"]), "withdrawn": bool(state["withdrawn"]),
                   "retired": state["retired"]}
            if kind == "artifact" and out["retired"]:
                out["replaced_by"] = self.ws.judgments.replacement_of(base)
            elif kind == "record":  # 依据失效：隐藏或标注（设计稿 07 D-02）
                out.update(self.ws.purge.coordinates(base))
            return out
        if kind == "judgment":
            j = self.ws.ledger.get(base)
            written, status = j["data"]["credibility"], self.ws.judgments.status(base)
            if j["kind"] in HISTORY_KINDS:  # 旧版写成判断的复核、退役记录
                return {"layer": layer, "kind": kind, "judgment_kind": j["kind"], "author_kind": j["author_kind"],
                        "history": True, "source_classes": [], "external_tiers": []}
            # 当前地位 = 写入时的依据 + 复核补充的依据（设计稿 04 D-19）；写入时可信度另给 written_credibility
            review = self.ws.reviews.state(base)
            cred = self.ws.reviews.current_credibility(j, review)
            claim = external_claim(j, cred)
            return {"layer": layer, "kind": kind, "judgment_kind": j["kind"], "author_kind": j["author_kind"],
                    "source_classes": cred["source_classes"], "external_tiers": cred["external_tiers"],
                    "all_local": cred["all_local"], "mixed": cred["mixed"], "process": j["kind"] == "process",
                    "reopen_condition": j["data"].get("reopen_condition"),
                    "normative": cred.get("normative", False),
                    "complete": cred["basis_complete"] and not status["defective"], "superseded": status["superseded"],
                    "recognition_unverified": cred.get("recognition_unverified", []),
                    "replaced": status["replaced"], "withdrawn": status["retracted"],
                    "retired": status["retired"], "defective": status["defective"],
                    "opposed": bool(status["opposed_by"]), "independent_support": status["independent_support"],
                    "review": review["review"], "ai_flag": review["ai_flag"],
                    "external_claim": claim,
                    "conditions_unstated": claim and not str(j["data"].get("conditions") or "").strip(),
                    **({"written_credibility": written} if cred is not written else {}),
                    **self.ws.purge.coordinates(base)}
        item = self.ws.get(base) or {}
        out = {"layer": "framework", "kind": kind, "source_classes": [], "external_tiers": [],
               "review": item.get("review"), "freshness": item.get("freshness")}
        if kind in ("page", "edge"):
            out["ai_flag"] = self.ws.reviews.state(base)["ai_flag"]
        return out

    # ---------- 检索 ----------
    def search(self, query: str, *, layers: list[str] | None = None, objects: list[str] | None = None,
               mode: str = "reuse", include_log: bool = False, include_process: bool | None = None,
               include_retired: bool = False, limit: int | None = None, order: str = "relevance",
               actor: Actor | None = None, source: str = "all") -> dict:
        """mode=reuse：三列都返回；mode=explore：不返回框架内容，避免框架锚定（草图 §11.3 风险）。

        include_process：是否返回过程内容（提问、尝试、停下的路线）。省略时复用模式返回、探索模式不返回：
        "这条路试过了"最容易让探索变窄（1.8），但也能避免重复踩坑，所以只是默认隐藏（D-15）。
        include_retired：是否返回已退役的原件；返回时排在最后（设计稿 02 D-12）。
        order：relevance 按相关度（默认，设计稿 06 D-09）/ status 按地位逐级排（草图 §12.4）。
        actor：给出时，原件命中标出本会话是否读过（read_before）。
        limit：省略时取设置 retrieval.limit。
        source：按依据来源筛选（设计稿 09 D-03），all / local / external / inferred，见 source_matches。
        """
        check_source(source)
        p = self.params()
        limit = limit or p["limit"]
        if mode not in ("reuse", "explore"):
            raise BurrowlError("INVALID_ARGUMENT", "mode 必须是 reuse 或 explore")
        if order not in ("relevance", "status"):
            raise BurrowlError("INVALID_ARGUMENT", "order 必须是 relevance 或 status")
        if include_process is None:
            include_process = mode == "reuse"
        if mode == "explore":
            layers = [x for x in (layers or ["original", "judgment"]) if x != "framework"]
        objects = self.ws.linking.normalize_objects(objects or [])
        pool = max(p["pool_min"], limit * p["pool_factor"])

        # 1. 各路线在检索单元上的名次
        routes: dict[str, list] = {"lexical": self.ws.index.search_units(query, layers=layers, limit=pool)}
        phrase_units = []
        for h in self.ws.index.search_phrase(query, layers=layers, limit=p["phrase_limit"]):
            u = self.ws.index.unit_of_anchor(h.entry_id, _anchor(h.locator))
            if u is not None:
                phrase_units.append(u)
        routes["phrase"] = phrase_units
        dense = self.ws.vectors.search(query, layers=layers, limit=pool)
        routes["dense"] = dense["units"]

        # 2. RRF 合并（同一单元在一条路线里只算一次）；去掉旧版本、被驳回的框架页
        units: dict[int, object] = {}
        fused: dict[int, float] = {}
        ranks: dict[int, dict[str, int]] = {}
        page_ok: dict[str, bool] = {}
        for name, rows in routes.items():
            seen: set[int] = set()
            for u in rows:
                if u.rowid in seen:
                    continue
                if u.layer == "framework" and not page_ok.setdefault(u.entry_id, self._page_current(u)):
                    continue
                seen.add(u.rowid)
                units[u.rowid] = u
                fused[u.rowid] = fused.get(u.rowid, 0.0) + 1.0 / (p["rrf_k"] + len(seen))
                ranks.setdefault(u.rowid, {})[name] = len(seen)
        ordered = sorted(fused, key=lambda r: -fused[r])

        # 3. 重排前 rerank_top 个单元（D-08）；失败或未装模型时保持融合顺序
        rerank_top = p["rerank_top"]
        rerank = self.ws.vectors.rerank(query, [units[r] for r in ordered[:rerank_top]])
        if rerank["scores"] is not None:
            top = ordered[:rerank_top]
            score_of = dict(zip(top, rerank["scores"], strict=True))
            ordered = sorted(top, key=lambda r: -score_of[r]) + ordered[rerank_top:]

        # 4. 按条目折叠
        entries: dict[str, dict] = {}
        for pos, rid in enumerate(ordered):
            u = units[rid]
            item = entries.setdefault(u.entry_id, {"id": u.entry_id, "layer": u.layer, "units": [],
                                                   "relevance": pos, "score": fused[rid], "channels": {}})
            item["units"].append(u)
            for name, rank in ranks[rid].items():
                item["channels"][name] = min(item["channels"].get(name, rank), rank)

        # 5. 精确对象命中（设备编号等）：带有该对象的条目排在最前（不含过程日志）
        exact = self.ws.linking.resolve_certain(query.strip())
        exact_ids = []
        if exact:
            for entry_id in self.ws.ledger.entries_with_objects([exact]):
                if entry_id.startswith("rd_") or (entry_id.startswith("evt_") and not include_log):
                    continue  # 过程日志不进入默认检索（草图 §2）
                exact_ids.append(entry_id)
                item = entries.setdefault(entry_id, {"id": entry_id, "layer": LAYER_OF_KIND[kind_of(entry_id)],
                                                     "units": [], "relevance": -1, "score": 0.0, "channels": {}})
                item["exact"] = True
                item["channels"]["exact_object"] = 1
        if include_log:
            for ev in self.ws.ledger.query("SELECT id FROM events WHERE data LIKE ? ORDER BY created_at DESC LIMIT ?",
                                           (f"%{query}%", limit)):
                entries.setdefault(ev["id"], {"id": ev["id"], "layer": "original", "units": [], "relevance": 10 ** 6,
                                              "score": 0.0, "channels": {"log": 1}})

        # 6. 地位坐标、过滤；名次只表示相关度（D-09）
        hits = []
        old_versions = self.ws.versions.hidden_ids()
        for item in entries.values():
            item.update(self.coordinates(item["id"]))
            if layers and item["layer"] not in layers:
                continue
            if objects and not set(objects) & set(self._objects(item["id"])):
                continue
            if not source_matches(item, source):
                continue
            if item.get("process") and not include_process:
                continue
            if (item.get("retired") or item.get("hidden") or item["id"] in old_versions) and not include_retired:
                continue
            if item.get("history") or item["layer"] == "history":  # 旧版写成判断的复核、退役记录（2.0.0a14）
                continue
            hits.append(item)
        hits.sort(key=lambda h: (not h.get("exact"), h["relevance"]))
        for i, h in enumerate(hits, 1):
            h["relevance_rank"] = i
            del h["relevance"]
        if order == "status":
            def key(h):
                return (*rank_key({**h, "score": 0.0})[:3], h["relevance_rank"])
        else:
            def key(h):
                return h["relevance_rank"]
        def gone(h):
            return h.get("retired") or h.get("hidden")
        current = sorted((h for h in hits if not h.get("superseded") and not gone(h)), key=key)
        superseded = sorted((h for h in hits if h.get("superseded") and not gone(h)), key=key)
        superseded += sorted((h for h in hits if gone(h)), key=key)
        shown = (current + superseded)[:limit]

        # 7. 给 AI 的线索（D-10 至 D-14）
        terms = set(tokens(query))
        reads = self._session_reads(actor)
        counts = self.ws.index.unit_counts([h["id"] for h in shown])
        for h in shown:
            self._dress(h, terms, mode=mode, include_process=include_process, reads=reads,
                        unit_total=counts.get(h["id"], 0), params=p)
        for h in hits[limit:]:
            h.pop("units", None)
        related = set(objects)
        for h in current[:limit]:
            related.update(self._objects(h["id"]))
        channels = {"lexical": len(routes["lexical"]), "phrase": len(routes["phrase"]), "dense": dense["status"],
                    "rerank": rerank["status"], "exact_object": len(exact_ids)}
        return {"query": query, "mode": mode, "order": order, "source": source,
                "constraints": self.active_constraints(sorted(related)),
                "hits": shown, "total": len(hits), "channels": channels,
                "params": _shown_params(p, limit), "hints": self._hints(shown, channels)}

    def search_exact(self, text: str, *, layers: list[str] | None = None, mode: str = "reuse",
                     include_process: bool | None = None, include_retired: bool = False,
                     limit: int | None = None, source: str = "all") -> dict:
        """字面查找（设计稿 06 D-15）：含有这段文字的段落，按条目分组，不分词、不排序。
        limit：省略时取设置 retrieval.exact_limit。source：按依据来源筛选（设计稿 09 D-03）。"""
        check_source(source)
        limit = limit or self.params()["exact_limit"]
        if mode not in ("reuse", "explore"):
            raise BurrowlError("INVALID_ARGUMENT", "mode 必须是 reuse 或 explore")
        if include_process is None:
            include_process = mode == "reuse"
        if mode == "explore":
            layers = [x for x in (layers or ["original", "judgment"]) if x != "framework"]
        groups: dict[str, dict] = {}
        skip: set[str] = set()
        old_versions = self.ws.versions.hidden_ids()
        for h in self.ws.index.exact(text, layers=layers, limit=limit * 20):
            if h.entry_id in skip:
                continue
            g = groups.get(h.entry_id)
            if g is None:
                if h.layer == "framework" and not self._page_current(h):
                    skip.add(h.entry_id)
                    continue
                coords = self.coordinates(h.entry_id)
                if (coords.get("process") and not include_process) \
                        or ((coords.get("retired") or coords.get("hidden") or h.entry_id in old_versions)
                            and not include_retired) \
                        or coords.get("history") or coords["layer"] == "history" \
                        or not source_matches(coords, source):
                    skip.add(h.entry_id)
                    continue
                if len(groups) >= limit:
                    break
                g = groups[h.entry_id] = {"id": h.entry_id, **coords, "segments": []}
            anchor = _anchor(h.locator)
            seg = {"anchor": anchor, "text": _around(h.text, text, 240)}
            if h.entry_id.startswith("art_") and anchor != "title":
                seg["cite_as"] = f"{h.entry_id}#{anchor}"
            g["segments"].append(seg)
        for g in groups.values():
            g["status_note"] = self.status_note(g)
        return {"text": text, "mode": mode, "hits": list(groups.values()), "total": len(groups),
                "note": "字面查找：不分词、不排序，不区分大小写"}

    def status_note(self, c: dict) -> str:
        """地位坐标的一行说明（D-09）：名次只表示相关度，可靠与否看这里。"""
        head = LAYER_LABEL.get(c.get("layer"), c.get("layer", ""))
        parts = [head]
        if c.get("judgment_kind"):
            parts[0] = head + "·" + JUDGMENT_LABEL.get(c["judgment_kind"], c["judgment_kind"])
            parts.append("AI 写" if c.get("author_kind") == "ai" else "人写")
        if c.get("normative"):
            parts.append("规定：不参与真假排序")
        elif c.get("layer") == "framework":
            parts.append({"human_reviewed": "人已复核", "rejected": "被驳回", "ai_reviewed": "AI 已复核",
                          "rule": "按规则建立"}.get(c.get("review"), "AI 生成未复核"))
            if c.get("freshness") and c["freshness"] != "valid":
                parts.append({"inputs_changed": "输入已变化", "superseded": "被替代", "unchecked": "未核查"}
                             .get(c["freshness"], c["freshness"]))
            parts.append("不能作为依据")
        else:
            src = []
            for sc in c.get("source_classes", []):
                label = SOURCE_LABEL.get(sc, sc)
                if sc == "external" and c.get("external_tiers"):
                    label += "（" + "、".join(TIER_LABEL.get(t, t) for t in c["external_tiers"]) + "）"
                src.append(label)
            parts.append(" + ".join(src) or "无依据")
            if c.get("all_local"):
                parts.append("全部依据为本地实证")
            if c.get("external_claim"):  # 设计稿 09 D-02、D-08
                parts.append("文献论断：依据是外部报告，重要处回原文核对")
            if c.get("conditions_unstated"):
                parts.append("条件未说明，使用前对照自己的条件")
            if c.get("complete") is False:
                parts.append("依据不完整")
            if c.get("recognition_unverified"):
                only_ai = all(r.get("state") == "ai_confirmed" for r in c["recognition_unverified"])
                parts.append("依据含 AI 核对过、人未确认的识别" if only_ai else "依据含未复核的识别，关键处请对照原件")
            if c.get("layer") == "judgment" and c.get("review"):  # 复核折算的当前地位（设计稿 04 D-19）
                parts.append({"human_reviewed": "人已复核", "ai_reviewed": "AI 已复核",
                              "rejected": "复核未通过"}.get(c["review"], c["review"]))
            if c.get("written_credibility"):
                parts.append("当前地位含复核补充的依据")
        if c.get("replaced", c.get("superseded")):
            parts.append("已被替代")
        defect_label = "原件有缺陷" if c.get("layer") == "original" else "有缺陷"
        for flag, label in (("defective", defect_label), ("withdrawn", "已撤回"), ("opposed", "有反对"),
                            ("retired", "已退役"), ("hidden", "依据全部失效（原件已退役或已删除），已隐藏"),
                            ("lapsed_basis", "部分依据所引原件已退役或已删除"), ("ai_flag", "AI 复核认为有问题")):
            if c.get(flag):
                parts.append(label)
        if c.get("process"):
            parts.append("过程内容：不能作为结论的依据")
        return " · ".join(p for p in parts if p)

    def basis_mix(self, refs: list[str]) -> dict:
        """一组输入的依据构成（设计稿 09 D-12）：由系统从输入清单算出，不写进正文，不能作为依据。
        local / external / inferred：依据只有这一种来源的原件或判断；mixed：混合来源；framework：框架页等；
        external_only_claims：其中依据只有外部报告的结论（含文献论断）。"""
        mix = {"local": 0, "external": 0, "inferred": 0, "mixed": 0, "framework": 0, "external_only_claims": 0}
        for ref in dict.fromkeys(r.split("#", 1)[0].split("@", 1)[0] for r in refs):
            coords = self._safe_coordinates(ref)
            if coords is None or coords.get("layer") not in ("original", "judgment"):
                mix["framework"] += 1
                continue
            classes = set(coords.get("source_classes") or []) or {"inferred"}
            mix[next(iter(classes)) if len(classes) == 1 else "mixed"] += 1
            if coords.get("judgment_kind") == "conclusion" and classes == {"external"}:
                mix["external_only_claims"] += 1
        parts = [f"{SOURCE_LABEL[k]} {mix[k]}" for k in ("local", "external", "inferred") if mix[k]]
        if mix["external_only_claims"]:
            i = next((n for n, x in enumerate(parts) if x.startswith(SOURCE_LABEL["external"])), None)
            extra = f"（其中只有外部依据的结论 {mix['external_only_claims']}）"
            if i is not None:
                parts[i] += extra
        if mix["mixed"]:
            parts.append(f"混合来源 {mix['mixed']}")
        note = "依据：" + ("、".join(parts) if parts else "无原件或判断")
        if mix["external_only_claims"]:
            note += "；只有外部依据的重要结论，使用前回原文核对"
        mix["note"] = note
        return mix

    def _page_current(self, u) -> bool:
        """框架页只返回当前版本、未被驳回的索引行（草图 §12.1）。"""
        page = self.ws.framework.page(u.entry_id)
        return bool(page and page["head_version"] == u.version and page["review"] != "rejected")

    def _session_reads(self, actor: Actor | None) -> dict[str, set[str]] | None:
        if actor is None:
            return None
        out: dict[str, set[str]] = {}
        for r in self.ws.ledger.query("SELECT artifact_id, data FROM reads WHERE session_id = ?", (actor.session_id,)):
            anchors = r["data"].get("anchors") or [f"seg-{n}" for n in r["data"].get("segments", [])]
            out.setdefault(r["artifact_id"], set()).update(anchors)
        return out

    def _dress(self, h: dict, terms: set[str], *, mode: str, include_process: bool, reads: dict | None,
               unit_total: int, params: dict) -> None:
        """补上命中单元、依据、一跳关系等线索；保留旧字段（text、anchor、cite_as、unit…）便于兼容。"""
        base = h["id"]
        h["status_note"] = self.status_note(h)
        seg_text: dict[str, str] = {}
        seg_info: dict[str, dict] = {}
        units = h.pop("units", [])
        if base.startswith("art_") and units:
            seg_text = {_anchor(s["locator"]): s["text"] for s in self.ws.index.segments(base)}
            art = self.ws.ledger.get(base)
            try:
                seg_info = {s["anchor"]: s for s in self.ws.extraction.segments(art)} if art else {}
            except BurrowlError:
                seg_info = {}
        passages = []
        best_first = None
        shown, chars = params["passages_shown"], params["snippet_chars"]
        for u in units[:shown]:
            p: dict = {"text": u.text[:chars], "context": u.context}
            cited = [a for a in u.anchors if a in seg_text and a != "title"]
            if cited:
                # 最相关的段落：命中的词最多；一样多时取内容更多的（正文胜过只有几个字的标题）
                best = max(cited, key=lambda a: (len(terms & set(tokens(seg_text[a]))),
                                                 min(len(seg_text[a]), 400), -cited.index(a)))
                p.update(anchors=cited, cite_as=f"{base}#{best}",
                         read_as=cited[0] if len(cited) == 1 else f"{cited[0]}:{cited[-1]}",
                         text=_window(u.text, seg_text[best], chars))
                info = seg_info.get(best)
                if info:
                    p.update(unit=info["unit"], unit_label=info["unit_label"], fidelity=info["fidelity"],
                             verified=info["verified"])
                if best_first is None:
                    best_first = best
            passages.append(p)
        h["passages"] = passages
        h["more_matches"] = max(0, len(units) - len(passages))
        h["size"] = {"units": unit_total}
        if seg_text:
            h["size"]["segments"] = len([a for a in seg_text if a != "title"])
        first = passages[0] if passages else {}
        h["text"] = first.get("text") or self.preview(base)
        h["locator"] = best_first or ""
        if best_first:
            h["anchor"] = best_first
            h["cite_as"] = f"{base}#{best_first}"
            for k in ("unit", "unit_label", "fidelity", "verified"):
                if k in first:
                    h[k] = first[k]
        if reads is not None and base.startswith("art_"):
            had = reads.get(base, set())
            h["read_before"] = bool(had & {a for p in passages for a in p.get("anchors", [])})
            if had:
                h["read_anchors"] = sorted(had)[:20]
        h["basis"] = self._basis(base, include_process=include_process, limit=params["basis_shown"])
        if base.startswith("pg_"):  # 设计稿 09 D-12
            page = self.ws.framework.page(base)
            if page:
                h["basis_mix"] = self.basis_mix(self.ws.framework.inputs_of("page", base, page["head_version"]))
        h["relations"] = self._relations(base, mode=mode, include_process=include_process, params=params)

    def _basis(self, base: str, *, include_process: bool, limit: int) -> list[dict]:
        """判断的依据、框架页的输入清单（D-11）：最多 limit 条（设置 retrieval.basis_shown），每条一句片段；
        读全文由 AI 决定。"""
        refs: list[str] = []
        if base.startswith("jdg_"):
            j = self.ws.ledger.get(base)
            refs = [c["ref"] for c in j["data"].get("cited_segments", [])]
            refs += [lk["dst_id"] for lk in self.ws.ledger.links_from(base, "used")]
        elif base.startswith("pg_"):
            page = self.ws.framework.page(base)
            refs = self.ws.framework.inputs_of("page", base, page["head_version"]) if page else []
        out = []
        for ref in dict.fromkeys(refs):
            if len(out) >= limit:
                break
            target, _, anchor = ref.partition("#")
            target = target.split("@", 1)[0]
            coords = self._safe_coordinates(target)
            if coords is None:
                out.append({"ref": ref, "status_note": "所引版本不可用"})
                continue
            if coords.get("process") and not include_process:
                continue
            item = {"ref": ref, "layer": coords["layer"], "status_note": self.status_note(coords)}
            history = self.ws.versions.history(target)
            if history and len(history["versions"]) > 1:
                item["version_history"] = {**history, "versions": [
                    {k: v[k] for k in ("id", "number", "retired", "withdrawn", "defective")}
                    for v in history["versions"]
                ]}
            if anchor:
                seg = next((s for s in self.ws.index.segments(target) if _anchor(s["locator"]) == anchor), None)
                item["text"] = (seg["text"] if seg else "")[:200]
            else:
                item["text"] = self.preview(target)[:200]
            out.append(item)
        if len(dict.fromkeys(refs)) > len(out):
            out.append({"more": len(dict.fromkeys(refs)) - len(out)})
        return out

    def _relations(self, base: str, *, mode: str, include_process: bool, params: dict) -> dict:
        """一跳关系提示（D-12）：不增加命中。探索模式下不给框架页，也不给"引用它的判断"（解读）。"""
        out: dict = {}
        if base.startswith(("art_", "rec_", "evt_")):
            if mode != "explore":
                ids = [r["src_id"] for r in self.ws.ledger.query(
                    "SELECT DISTINCT src_id FROM links WHERE (dst_id = ? OR dst_id LIKE ?) AND src_id LIKE 'jdg_%'",
                    (base, f"{base}#%"))]
                if not include_process:
                    ids = [i for i in ids if (self.ws.ledger.get(i) or {}).get("kind") != "process"]
                if ids:
                    out["cited_by"] = {"count": len(ids), "ids": ids[:params["relation_ids_shown"]]}
        elif base.startswith("jdg_"):
            links = [("out", lk["rel"], lk["dst_id"]) for lk in self.ws.ledger.links_from(base) if lk["rel"] != "used"]
            links += [("in", lk["rel"], lk["src_id"]) for lk in self.ws.ledger.links_to(base)]
            items = []
            for direction, rel, other in links:
                if not include_process and other.startswith("jdg_"):
                    if (self.ws.ledger.get(other) or {}).get("kind") == "process":
                        continue
                items.append({"direction": direction, "rel": rel, "id": other})
            if items:
                out["links"] = items[:params["links_shown"]]
        if mode != "explore" and not base.startswith("pg_"):
            pages = self._pages_using(base)
            if pages:
                out["in_pages"] = pages[:params["relation_ids_shown"]]
        return out

    def _pages_using(self, base: str) -> list[str]:
        rs = self.ws.framework.conn.execute(
            "SELECT DISTINCT di.derived_id FROM derivation_inputs di JOIN pages p ON p.id = di.derived_id "
            "WHERE di.derived_kind = 'page' AND di.derived_version = p.head_version AND p.review != 'rejected' "
            "AND (di.input_id = ? OR di.input_id LIKE ?)", (base, f"{base}#%"))
        return [r[0] for r in rs]

    def _safe_coordinates(self, entry_id: str) -> dict | None:
        try:
            if self.ws.get(entry_id) is None:
                return None
            return self.coordinates(entry_id)
        except BurrowlError:
            return None

    def _hints(self, shown: list[dict], channels: dict) -> list[str]:
        hints = []
        if not shown:
            hints.append("没有命中：换个说法或拆成关键词再查；原件可能是另一种语言，用那种语言的术语也查一次；"
                         "设备编号、错误码等精确标识用 search_exact")
        more = [h for h in shown if h.get("more_matches")][:3]
        for h in more:
            hints.append(f"{h['id']} 还有 {h['more_matches']} 个命中单元未展示（共 {h['size']['units']} 个单元）："
                         "用 search_exact 找具体文字，或 artifact_read 读相关范围")
        if any(h["layer"] == "framework" for h in shown):
            hints.append("框架页只能帮助找方向，不能作为依据；依据见它的 basis（输入清单）")
        if self.ws.index_stale():  # 另一个进程刚改了检索单元长度、正在重建（设计稿 06 D-22）
            hints.append("索引正在按新的检索单元长度重建：这次结果可能不全，稍后再查一次")
        dense, rerank = channels["dense"], channels["rerank"]
        if dense.get("state") != "ready":
            label = {"off": "未启用", "missing": "缺模型", "building": "还在补建", "error": "出错"}
            hints.append("向量通道" + label.get(dense.get("state"), "未就绪")
                         + (f"（{dense['reason']}）" if dense.get("reason") else "")
                         + "：结果只来自或部分来自关键词匹配，跨语言、换说法的查询可能找不全")
        if rerank.get("state") in ("missing", "error"):  # 设置为不重排（默认）时不提示
            hints.append("重排未启用" + (f"（{rerank['reason']}）" if rerank.get("reason") else ""))
        hints.append("名次只表示相关度；可靠与否看每条的 status_note 与地位坐标")
        return hints

    # ---------- 展开 ----------
    def expand(self, entry_ref: str, *, mode: str = "reuse") -> dict:
        """一条原件一列条目的背景（设计稿 01 D-08、D-09）：
        来源（原件）或条件（过程日志、事实记录）→ 同一来源的前后内容 → 涉及的对象 → 引用了它的判断（解读）。"""
        base, _, anchor = entry_ref.partition("#")
        entry = self.ws.get(base)
        if entry is None:
            raise BurrowlError("NOT_FOUND", "条目不存在", {"id": entry_ref})
        out: dict = {"entry": entry, "coordinates": self.coordinates(base)}
        kind = kind_of(base)
        if kind == "record":
            out["conditions"] = {"conditions": entry["data"].get("conditions") or {},
                                 "method": entry["data"].get("method"), "boundary": entry["boundary"],
                                 "gaps": entry["data"].get("gaps") or [], "locator": entry["data"].get("locator"),
                                 "from": entry["event_id"] or entry["artifact_id"]}
        elif kind == "event":
            out["conditions"] = {"conditions": entry["data"].get("conditions") or {},
                                 "input": entry["data"].get("input") or {},
                                 "source_class": entry["data"].get("source_class", "local")}
            out["neighbors"] = self.ws.ledger.query(
                "SELECT * FROM events WHERE session_id = ? AND seq BETWEEN ? AND ? AND id != ? ORDER BY seq",
                (entry["session_id"], entry["seq"] - 2, entry["seq"] + 2, base))
            promoted = self.ws.ledger.query("SELECT id FROM records WHERE event_id = ?", (base,))
            out["promoted_to"] = [r["id"] for r in promoted]
        elif kind == "artifact":
            out["source"] = self.source_of(entry)
            if anchor:
                segs = self.ws.extraction.segments(entry)
                at = next((i for i, x in enumerate(segs) if x["anchor"] == anchor.replace("seg:", "seg-", 1)), None)
                if at is not None:
                    out["neighbors"] = [x for x in segs[max(0, at - 1):at + 2] if x["unit"] == segs[at]["unit"]]
        elif kind == "read":
            out["read_of"] = {"artifact_id": entry["artifact_id"],
                              "anchors": entry["data"].get("anchors")
                              or [f"seg-{n}" for n in entry["data"].get("segments", [])]}
        out["objects"] = self.object_tags(self._objects(base))
        if mode != "explore":
            out["interpretations"] = self.interpretations(base)
        out["framework"] = [e for e in self.ws.framework.edges_of(base) if e["review"] != "rejected"]
        return out

    def source_of(self, art: dict) -> dict:
        """原件的"来源"（D-09）：登记时能核对的信息，按键值对给出；元数据原样附上。"""
        d = art["data"]
        fields = {k: d.get(k) for k in SOURCE_FIELDS if d.get(k) is not None}
        return {"kind": art["kind"], "source_class": art["source_class"], "storage": art["storage"],
                "uri": art["uri"], "sha256": art["sha256"], "captured_by": art["captured_by"],
                "session_id": art["session_id"], "created_at": art["created_at"], "version_of": art["version_of"],
                "newer_versions": [r["id"] for r in self.ws.ledger.query(
                    "SELECT id FROM artifacts WHERE version_of = ?", (art["id"],))],
                **fields, "metadata": d.get("metadata") or {}}

    def interpretations(self, base: str) -> list[dict]:
        """引用了它的判断：直接引用、引用它的某个段落（art_…#段落）、经由它的读取记录引用。"""
        links = self.ws.ledger.query("SELECT * FROM effective_links WHERE dst_id = ? OR dst_id LIKE ? "
                                     "ORDER BY created_at",
                                     (base, f"{base}#%"))
        if base.startswith("art_"):
            links += self.ws.ledger.query(
                "SELECT l.* FROM links l JOIN reads r ON r.id = l.dst_id WHERE r.artifact_id = ? ORDER BY l.created_at",
                (base,))
        out, seen = [], set()
        for link in links:
            key = (link["src_id"], link["rel"], link["dst_id"])
            if key in seen or not link["src_id"].startswith("jdg_"):
                continue
            seen.add(key)
            j = self.ws.ledger.get(link["src_id"])
            out.append({"judgment_id": link["src_id"], "rel": link["rel"], "via": link["dst_id"],
                        "judgment_kind": j["kind"] if j else None, "preview": self.preview(link["src_id"]),
                        "note": "这是解读，不是原件内容"})
        return out

    def object_tags(self, objects: list[str]) -> list[dict]:
        """对象标签（D-08）：实体显示名称与类别；每个标签带"关于它的条目"数（不含自动日志）。"""
        out = []
        for obj in objects:
            entity = self.ws.framework.entity(obj) if obj.startswith("ent_") else None
            count = len([i for i in self.ws.ledger.entries_with_objects([obj]) if not i.startswith(("evt_", "rd_"))])
            out.append({"id": obj, "name": entity["name"] if entity else obj,
                        "kind": entity["kind"] if entity else None, "entity": entity is not None, "count": count})
        return out

    def segment_stats(self, artifact_id: str) -> dict:
        """每个段落被读过几次、被哪些判断引用（按结论 / 过程 / 规定分组，D-01、T-06）。"""
        art = self.ws.ledger.get(artifact_id)
        if art is None or art["entry_kind"] != "artifact":
            raise BurrowlError("NOT_FOUND", "原件不存在", {"artifact_id": artifact_id})
        stats: dict[str, dict] = {}

        def slot(anchor: str) -> dict:
            return stats.setdefault(anchor, {"reads": [], "citations": {}})

        reads = self.ws.ledger.query("SELECT * FROM reads WHERE artifact_id = ? ORDER BY created_at", (artifact_id,))
        read_anchors = {}
        for r in reads:
            anchors = r["data"].get("anchors") or [f"seg-{n}" for n in r["data"].get("segments", [])]
            read_anchors[r["id"]] = anchors
            for a in anchors:
                slot(a)["reads"].append({"id": r["id"], "actor_id": r["actor_id"], "created_at": r["created_at"]})
        whole = []
        for item in self.interpretations(artifact_id):
            if item["rel"] != "used":
                continue
            via = item["via"]
            if via == artifact_id:
                whole.append(item)
                continue
            anchors = [via.split("#", 1)[1].replace("seg:", "seg-", 1)] if "#" in via else read_anchors.get(via, [])
            for a in anchors:
                group = slot(a)["citations"].setdefault(item["judgment_kind"] or "other", [])
                if item["judgment_id"] not in [g["judgment_id"] for g in group]:
                    group.append({"judgment_id": item["judgment_id"], "via": via, "preview": item["preview"]})
        return {"artifact_id": artifact_id, "segments": stats, "whole_artifact": whole, "reads": len(reads)}

    def object_view(self, obj: str) -> dict:
        """对象页（D-08）：关于这个对象的全部条目。有效约束在前，其次有争议的结论，其余按类型、时间。
        不显示自动日志（写判断、写框架页等）；已升级为事实记录的过程日志只显示事实记录。"""
        key = (self.ws.linking.normalize_objects([obj]) or [obj])[0]
        entity = self.ws.framework.entity(key) if key.startswith("ent_") else None
        ids = self.ws.ledger.entries_with_objects([key])
        promoted = {r["event_id"] for r in self.ws.ledger.query(
            "SELECT event_id FROM records WHERE event_id IS NOT NULL")}
        excluded = self.ws.purge.excluded_ids()
        groups: dict[str, list[dict]] = {"constraints": [], "disputed": [], "conclusion": [], "process": [],
                                         "record": [], "artifact": [], "event": [], "system": []}
        for entry_id in ids:
            entry = self.ws.get(entry_id)
            if entry is None or entry_id.startswith("rd_"):
                continue
            if entry_id.startswith("evt_") and (entry["op"] in AUTO_LOG_OPS or entry_id in promoted):
                continue
            if entry_id.startswith("jdg_") and entry["kind"] in HISTORY_KINDS:
                continue
            if entry_id in excluded:  # 已退役的原件、依据全部失效的条目（设计稿 07 D-02）
                continue
            item = {"id": entry_id, "created_at": entry["created_at"], "preview": self.preview(entry_id),
                    **self.coordinates(entry_id)}
            if entry_id.startswith("jdg_"):
                status = self.ws.judgments.status(entry_id)
                item["superseded"] = status["superseded"]
                if entry["kind"] == "normative":
                    group = "constraints"
                elif entry["kind"] == "conclusion" and status["opposed_by"] and not status["superseded"]:
                    group = "disputed"
                elif entry["kind"] in ("conclusion", "process"):
                    group = entry["kind"]
                else:
                    group = "system"
            else:
                group = {"record": "record", "artifact": "artifact", "event": "event"}[entry["entry_kind"]]
            groups[group].append(item)
        for items in groups.values():
            items.sort(key=lambda i: i["created_at"], reverse=True)  # 新的在前
            items.sort(key=lambda i: bool(i.get("superseded")))  # 被替代的排到最后（稳定排序，组内仍按时间）
        pages = [dict(p) for p in self.ws.framework.conn.execute(
            "SELECT id, type, title, freshness, review FROM pages WHERE subject_id = ?", (key,))]
        return {"id": key, "name": entity["name"] if entity else key, "entity": entity,
                "groups": groups, "total": sum(len(v) for v in groups.values()), "pages": pages}

    def timeline(self, obj: str) -> list[dict]:
        """按对象和时间精确过滤（历史类查询）。"""
        key = self.ws.linking.normalize_objects([obj])
        ids = self.ws.ledger.entries_with_objects(key)
        items = [self.ws.get(i) for i in ids]
        items.sort(key=lambda e: e["created_at"])
        return [{"id": e["id"], "created_at": e["created_at"], "preview": self.preview(e["id"]),
                 **self.coordinates(e["id"])} for e in items]

    # ---------- 约束 ----------
    def active_constraints(self, objects: list[str]) -> list[dict]:
        if not objects:
            return []
        rows = self.ws.ledger.query(
            "SELECT DISTINCT j.id FROM judgments j JOIN entry_objects o ON o.entry_id = j.id "
            f"WHERE j.kind = 'normative' AND o.object IN ({','.join('?' * len(objects))})",
            objects)
        out = []
        for r in rows:
            if self.ws.judgments.status(r["id"])["superseded"]:
                continue
            j = self.ws.ledger.get(r["id"])
            out.append({"id": j["id"], "kind": j["kind"], "text": j["data"]["text"], "author_kind": j["author_kind"],
                        "author_id": j["author_id"], "objects": j["objects"], "created_at": j["created_at"]})
        return out

    def check_constraints(self, actor: Actor, objects: list[str]) -> dict:
        """agent 对某对象动手前必须调用（Skill 规定）；调用本身记入过程日志，作为"已检查"的凭据。"""
        objects = self.ws.linking.normalize_objects(objects)
        found = self.active_constraints(objects)
        self.ws.capture.log(actor, "constraints.check", input={"constraints": [c["id"] for c in found]},
                            objects=objects)
        return {"objects": objects, "constraints": found}

    def flag_unchecked_constraints(self, actor: Actor, event: dict) -> None:
        """对某对象的操作发生在对它的约束检查之前，就生成一条待决策项（DESIGN §0）。"""
        if event["op"].startswith(INTERNAL_OPS):
            return
        found = self.active_constraints(event["objects"])
        if not found:
            return
        checked = set()
        for ev in self.ws.ledger.query("SELECT objects FROM events WHERE session_id = ? AND op = 'constraints.check' "
                                       "AND seq < ?", (event["session_id"], event["seq"])):
            checked.update(ev["objects"])
        missing = [c for c in found if not set(c["objects"]) & checked]
        if missing:
            self.ws.framework.add_decision("constraint_unchecked", event["id"], len(missing), {
                "op": event["op"], "actor_id": actor.id, "constraints": missing,
                "note": "操作前没有检查相关约束"})

    # ---------- 内部 ----------
    def _objects(self, entry_id: str) -> list[str]:
        if entry_id.startswith("pg_"):
            page = self.ws.framework.page(entry_id)
            return [page["subject_id"]] if page and page["subject_id"] else []
        entry = self.ws.ledger.get(entry_id)
        return entry["objects"] if entry else []

    def preview(self, entry_id: str) -> str:
        e = self.ws.get(entry_id) or {}
        d = e.get("data") or {}
        return str(d.get("corrected_text") or d.get("text") or d.get("result") or d.get("excerpt")
                   or d.get("title") or d.get("output") or e.get("title") or e.get("op") or "")[:300]


def _shown_params(p: dict, limit: int) -> dict:
    """结果里写明本次用的检索参数：AI 不用猜"每条最多几个命中单元"之类的数字（设计稿 06 D-21）。"""
    keys = ("passages_shown", "snippet_chars", "basis_shown", "relation_ids_shown", "links_shown", "rerank_top",
            "rrf_k", "pool_min", "pool_factor", "phrase_limit")
    return {"limit": limit, **{k: p[k] for k in keys}}


def _anchor(locator: str) -> str:
    return locator.replace("seg:", "seg-", 1) if locator.startswith("seg:") else locator


def _window(unit_text: str, focus: str, size: int) -> str:
    """单元文本较长时，截取以最相关段落为起点的一段。"""
    if len(unit_text) <= size:
        return unit_text
    at = max(0, unit_text.find(focus[:40]))
    start = max(0, min(at - 60, len(unit_text) - size))
    return ("…" if start else "") + unit_text[start:start + size] + ("…" if start + size < len(unit_text) else "")


def _around(text: str, needle: str, size: int) -> str:
    at = text.lower().find(needle.lower())
    if at < 0 or len(text) <= size:
        return text[:size]
    start = max(0, at - size // 3)
    return ("…" if start else "") + text[start:start + size] + ("…" if start + size < len(text) else "")
