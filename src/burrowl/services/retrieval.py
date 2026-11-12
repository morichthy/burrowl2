"""F8 检索与展开、约束生效（草图 §7、§12.4；DESIGN §0 约束如何强制生效；设计稿 06、10）。

检索（设计稿 06）：
- 召回落在检索单元上（相邻段落合并），几条路线用 RRF 合并：词法主路（双字 + 标识符，OR + bm25）、
  短语路（整个查询作为短语出现的段落）、向量路（可选）；设置为重排时重排前 rerank_top 个单元。
- 数量类参数（展示几个命中单元、片段长度、候选池、RRF 常数等）在 config.json 的 retrieval 组，
  工作台与 AI 读同一份，结果的 params 写明本次用的值（设计稿 06 D-21）。
- **名次只表示相关度**（D-09）；每条结果带坐标（设计稿 10 D-12：地位 → 类型 → 现状 → 说明）与一行说明。
  相关对象的有效约束单列在最前；不是"当前有效"的排在当前条目之后。order="standing" 按草图 §12.4 的逐级规则排。

版本（设计稿 10 D-19）：全部版本进索引；命中按条目折叠成一条结果，主体是当前版，命中的旧版列在 old_hits
（版本、命中段落、被哪一版替代、改动理由），由 AI 决定要不要扩大阅读。

返回给 AI（设计稿 10 D-21）：坐标只写例外（正常值省略，标记只给名字与处数）、status_note、命中段落、依据片段，
以及全部关系 links（出边与入边，每条 {p, ref}），只在超过上限时截断并写明剩余条数。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import kind_of, make_ref, parse_ref
from ..core.model import INTERNAL_OPS, LAYER_OF_KIND, rank_key  # noqa: F401  INTERNAL_OPS 对外沿用
from ..core.vocab import JUDGMENT_KINDS, KINDS, SOURCE_LABELS, status_note
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
    "links_max": 50,  # 每条结果的关系（出边 + 入边）超过这个数才截断（设计稿 10 D-21）
    "rerank_top": 20,  # 重排前几个单元（设置为重排时）
    "rrf_k": 60, "pool_min": 60, "pool_factor": 6,  # RRF 常数；每路候选池 max(pool_min, limit × pool_factor)
    "phrase_limit": 30,  # 短语路最多几个段落
    "associate_seeds": 5, "associate_fanout": 20,  # 联想：从前几条出发；每个节点每种关系最多展开几个
    "associate_vector_min": 0.4,  # 联想：向量近邻的最低相似度（jina 上跨语言的同主题段落约 0.45，无关的约 0.1–0.3）
}
SOURCE_FILTERS = ("all", "local", "external", "inferred")
GONE = ("withdrawn", "retired", "lapsed")  # 当前版不再算数：默认不返回（include_retired 时排在最后）


def check_source(source: str) -> None:
    if source not in SOURCE_FILTERS:
        raise BurrowlError("INVALID_ARGUMENT", "source 必须是 all / local / external / inferred",
                           {"source": source})


def source_matches(coords: dict, source: str) -> bool:
    """按依据来源筛选（设计稿 09 D-03、设计稿 10 D-24）。local：依据全部为本地实证的原件与判断，以及没有依据来源的规定；
    external / inferred：依据含该来源的原件与判断。框架内容只在 all 时返回。"""
    if source == "all":
        return True
    if coords.get("layer") not in ("original", "judgment"):
        return False
    sources = coords.get("sources") or []
    if source == "local":
        return sources == ["local"] or (coords.get("kind") == "normative" and not sources)
    if source == "external":
        return any(s.startswith("external") for s in sources)
    return source in sources


def filter_matches(coords: dict, *, kinds: list[str] | None = None, quoted: bool | None = None) -> bool:
    """类型、说明的筛选（设计稿 10 D-24、D-26）：kinds 是类型取值；quoted=True 只要转述（有原作者）的。"""
    if kinds and coords.get("kind") not in kinds:
        return False
    if quoted is not None and bool((coords.get("notes") or {}).get("quoted")) != quoted:
        return False
    return True


def is_gone(coords: dict) -> bool:
    return (coords.get("state") or {}).get("validity") in GONE


def is_current(coords: dict) -> bool:
    return (coords.get("state") or {}).get("validity", "current") == "current"


class RetrievalService:
    def __init__(self, ws):
        self.ws = ws

    def params(self) -> dict:
        """检索参数（设计稿 06 D-21）：config.json 的 retrieval 组，缺的键取默认值。"""
        return {**RETRIEVAL_DEFAULTS, **(self.ws.config.get("retrieval") or {})}

    # ---------- 坐标 ----------
    def coordinates(self, ref: str, *, memo: dict | None = None) -> dict:
        """完整坐标（设计稿 10 D-12）。变更历史（复核、处置）不是条目，没有坐标。"""
        base = parse_ref(ref)[0]
        kind = kind_of(base)
        if kind is None:
            raise BurrowlError("INVALID_REFERENCE", "不是合法的条目 ID", {"id": ref})
        coords = self.ws.coordinates.of(ref.split("#", 1)[0], memo=memo)
        if coords is None:
            raise BurrowlError("NOT_FOUND", "条目不存在或没有坐标", {"id": ref})
        return coords

    def status_note(self, coords: dict) -> str:
        return status_note(coords)

    # ---------- 检索 ----------
    def search(self, query: str, *, layers: list[str] | None = None, objects: list[str] | None = None,
               mode: str = "reuse", include_log: bool = False, include_process: bool | None = None,
               include_retired: bool = False, limit: int | None = None, order: str = "relevance",
               actor: Actor | None = None, source: str = "all", kinds: list[str] | None = None,
               quoted: bool | None = None) -> dict:
        """mode=reuse：三列都返回；mode=explore：不返回框架内容，避免框架锚定（草图 §11.3 风险）。

        include_process：是否返回过程内容（提问、尝试、停下的路线）。省略时复用模式返回、探索模式不返回：
        "这条路试过了"最容易让探索变窄（1.8），但也能避免重复踩坑，所以只是默认隐藏（D-15）。
        include_retired：是否返回当前版已撤回、已退役、依据失效的条目；返回时排在最后（设计稿 02 D-12）。
        order：relevance 按相关度（默认，设计稿 06 D-09）/ standing 按地位逐级排（草图 §12.4）。
        actor：给出时，原件命中标出本会话是否读过（read_before）。
        limit：省略时取设置 retrieval.limit。
        筛选（设计稿 10 D-24，顺序：综合程度 layers → 依据来源 source → 类型 kinds → 说明 quoted）。
        """
        check_source(source)
        p = self.params()
        limit = limit or p["limit"]
        if mode not in ("reuse", "explore"):
            raise BurrowlError("INVALID_ARGUMENT", "mode 必须是 reuse 或 explore")
        if order == "status":
            order = "standing"
        if order not in ("relevance", "standing"):
            raise BurrowlError("INVALID_ARGUMENT", "order 必须是 relevance 或 standing")
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
            u = self.ws.index.unit_of_version_anchor(h.entry_id, h.version, _anchor(h.locator))
            if u is not None:
                phrase_units.append(u)
        routes["phrase"] = phrase_units
        dense = self.ws.vectors.search(query, layers=layers, limit=pool)
        routes["dense"] = dense["units"]

        # 2. RRF 合并（同一单元在一条路线里只算一次）；去掉被驳回的框架页
        units: dict[int, object] = {}
        fused: dict[int, float] = {}
        ranks: dict[int, dict[str, int]] = {}
        page_ok: dict[str, bool] = {}
        for name, rows in routes.items():
            seen: set[int] = set()
            for u in rows:
                if u.rowid in seen:
                    continue
                if u.layer == "framework" and not page_ok.setdefault(u.entry_id, self._page_ok(u.entry_id)):
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

        # 4. 按条目折叠（全部版本，设计稿 10 D-19）
        entries: dict[str, dict] = {}
        for pos, rid in enumerate(ordered):
            u = units[rid]
            item = entries.setdefault(u.entry_id, {"id": u.entry_id, "units": [], "relevance": pos,
                                                   "score": fused[rid], "channels": {}})
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
                item = entries.setdefault(entry_id, {"id": entry_id, "units": [], "relevance": -1, "score": 0.0,
                                                     "channels": {}})
                item["exact"] = True
                item["channels"]["exact_object"] = 1
        if include_log:
            for ev in self.ws.ledger.query("SELECT id FROM events WHERE data LIKE ? ORDER BY created_at DESC LIMIT ?",
                                           (f"%{query}%", limit)):
                entries.setdefault(ev["id"], {"id": ev["id"], "units": [], "relevance": 10 ** 6,
                                              "score": 0.0, "channels": {"log": 1}})

        # 6. 坐标、过滤；名次只表示相关度（D-09）
        hits = []
        memo: dict = {}
        for item in entries.values():
            coords = self._safe_coordinates(item["id"], memo)
            if coords is None:
                continue
            item["coords"] = coords
            if layers and coords["layer"] not in layers:
                continue
            if objects and not set(objects) & set(self._objects(item["id"])):
                continue
            if not source_matches(coords, source) or not filter_matches(coords, kinds=kinds, quoted=quoted):
                continue
            if coords["kind"] == "process" and not include_process:
                continue
            if is_gone(coords) and not include_retired:
                continue
            hits.append(item)
        hits.sort(key=lambda h: (not h.get("exact"), h["relevance"]))
        for i, h in enumerate(hits, 1):
            h["relevance_rank"] = i
            del h["relevance"]
        if order == "standing":
            def key(h):
                return (*rank_key({**h["coords"], "score": 0.0})[:3], h["relevance_rank"])
        else:
            def key(h):
                return h["relevance_rank"]
        current = sorted((h for h in hits if is_current(h["coords"])), key=key)
        rest = sorted((h for h in hits if not is_current(h["coords"]) and not is_gone(h["coords"])), key=key)
        rest += sorted((h for h in hits if is_gone(h["coords"])), key=key)
        shown = (current + rest)[:limit]

        # 7. 给 AI 的线索（D-10 至 D-14；设计稿 10 D-19、D-21）
        terms = set(tokens(query))
        reads = self._session_reads(actor)
        counts = self.ws.index.unit_counts([h["id"] for h in shown])
        out_hits = [self._dress(h, terms, include_process=include_process, reads=reads,
                                unit_total=counts.get(h["id"], 0), params=p) for h in shown]
        related = set(objects)
        for h in current[:limit]:
            related.update(self._objects(h["id"]))
        channels = {"lexical": len(routes["lexical"]), "phrase": len(routes["phrase"]), "dense": dense["status"],
                    "rerank": rerank["status"], "exact_object": len(exact_ids)}
        return {"query": query, "mode": mode, "order": order, "source": source,
                "constraints": self.active_constraints(sorted(related)),
                "hits": out_hits, "total": len(hits), "channels": channels,
                "params": _shown_params(p, limit), "hints": self._hints(out_hits, channels)}

    def search_exact(self, text: str, *, layers: list[str] | None = None, mode: str = "reuse",
                     include_process: bool | None = None, include_retired: bool = False,
                     limit: int | None = None, source: str = "all", kinds: list[str] | None = None,
                     quoted: bool | None = None) -> dict:
        """字面查找（设计稿 06 D-15）：含有这段文字的段落，按条目分组，不分词、不排序。
        旧版命中的段落列在 old_hits（设计稿 10 D-19）。limit：省略时取设置 retrieval.exact_limit。"""
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
        memo: dict = {}
        for h in self.ws.index.exact(text, layers=layers, limit=limit * 20):
            if h.entry_id in skip:
                continue
            g = groups.get(h.entry_id)
            if g is None:
                if h.layer == "framework" and not self._page_ok(h.entry_id):
                    skip.add(h.entry_id)
                    continue
                coords = self._safe_coordinates(h.entry_id, memo)
                if coords is None or (coords["kind"] == "process" and not include_process) \
                        or (is_gone(coords) and not include_retired) \
                        or not source_matches(coords, source) \
                        or not filter_matches(coords, kinds=kinds, quoted=quoted):
                    skip.add(h.entry_id)
                    continue
                if len(groups) >= limit:
                    break
                g = groups[h.entry_id] = {"coords": coords, "segments": [], "old": {}}
            anchor = _anchor(h.locator)
            head = parse_ref(g["coords"]["ref"])[1]
            seg = {"anchor": anchor, "text": _around(h.text, text, 240)}
            if head is not None and h.version and h.version < head:
                g["old"].setdefault(h.version, []).append(seg)
                continue
            if h.entry_id.startswith("art_") and anchor != "title":
                seg["cite_as"] = f"{h.entry_id}#{anchor}"
            g["segments"].append(seg)
        out = []
        for entry_id, g in groups.items():
            item = {"id": entry_id, **self.ws.coordinates.compact(g["coords"]), "segments": g["segments"]}
            current_text = " ".join(s["text"] for s in g["segments"])
            old_hits = self._old_hits(entry_id, {v: [s["text"] for s in segs] for v, segs in g["old"].items()},
                                      current_text)
            if old_hits:
                item["old_hits"] = old_hits
            item["status_note"] = self._note(g["coords"], old_hits)
            out.append(item)
        return {"text": text, "mode": mode, "hits": out, "total": len(out),
                "note": "字面查找：不分词、不排序，不区分大小写"}

    def basis_mix(self, refs: list[str]) -> dict:
        """一组输入的依据构成（设计稿 09 D-12）：由系统从输入清单算出，不写进正文，不能作为依据。
        local / external / inferred：依据只有这一种来源的原件或判断；mixed：混合来源；framework：框架页等；
        external_only_claims：其中依据只有外部报告的结论。"""
        mix = {"local": 0, "external": 0, "inferred": 0, "mixed": 0, "framework": 0, "external_only_claims": 0}
        memo: dict = {}
        for ref in dict.fromkeys(r.split("#", 1)[0] for r in refs):
            coords = self._safe_coordinates(ref, memo)
            if coords is None or coords["layer"] not in ("original", "judgment"):
                mix["framework"] += 1
                continue
            classes = {s.split(":", 1)[0] for s in coords["sources"]} or {"inferred"}
            mix[next(iter(classes)) if len(classes) == 1 else "mixed"] += 1
            if coords["kind"] == "conclusion" and classes == {"external"}:
                mix["external_only_claims"] += 1
        labels = {"local": SOURCE_LABELS["local"], "external": SOURCE_LABELS["external"],
                  "inferred": SOURCE_LABELS["inferred"]}
        parts = [f"{labels[k]} {mix[k]}" for k in ("local", "external", "inferred") if mix[k]]
        if mix["external_only_claims"]:
            i = next((n for n, x in enumerate(parts) if x.startswith(labels["external"])), None)
            if i is not None:
                parts[i] += f"（其中只有外部依据的结论 {mix['external_only_claims']}）"
        if mix["mixed"]:
            parts.append(f"混合来源 {mix['mixed']}")
        note = "依据：" + ("、".join(parts) if parts else "无原件或判断")
        if mix["external_only_claims"]:
            note += "；只有外部依据的重要结论，使用前回原文核对"
        mix["note"] = note
        return mix

    def _page_ok(self, page_id: str) -> bool:
        """框架页未被驳回才返回（草图 §12.1）；旧版命中按条目折叠。"""
        page = self.ws.framework.page(page_id)
        return bool(page and page["review"] != "rejected")

    def _session_reads(self, actor: Actor | None) -> dict[str, set[str]] | None:
        if actor is None:
            return None
        out: dict[str, set[str]] = {}
        for r in self.ws.ledger.query("SELECT artifact_id, data FROM read_versions WHERE session_id = ?",
                                      (actor.session_id,)):
            anchors = r["data"].get("anchors") or [f"seg-{n}" for n in r["data"].get("segments", [])]
            out.setdefault(r["artifact_id"], set()).update(anchors)
        return out

    def _note(self, coords: dict, old_hits: list[dict]) -> str:
        note = status_note(coords)
        if old_hits:
            head = parse_ref(coords["ref"])[1]
            versions = "、".join(f"第 {parse_ref(o['ref'])[1]} 版" for o in old_hits)
            note += f"；{versions}也命中，当前为第 {head} 版"
        return note

    def _old_hits(self, entry_id: str, by_version: dict[int, list[str]], current_text: str) -> list[dict]:
        """命中的旧版（设计稿 10 D-19）：版本、命中段落、被哪一版替代、下一版写的改动理由。
        旧版命中的段落在当前版里原样存在时不重复列出。"""
        if not by_version:
            return []
        if entry_id.startswith(("art_", "evt_", "rec_", "rd_", "jdg_")):
            current_full = current_text + " " + " ".join(
                s["text"] for s in self.ws.index.segments(entry_id))
        else:
            current_full = current_text
        out = []
        for version in sorted(by_version, reverse=True):
            snippets = [t for t in dict.fromkeys(by_version[version]) if t.strip() and t.strip() not in current_full]
            if not snippets:
                continue
            nxt = self._version_row(entry_id, version + 1)
            out.append({"ref": make_ref(entry_id, version), "snippet": snippets[0],
                        **({"more": len(snippets) - 1} if len(snippets) > 1 else {}),
                        "replaced_by": make_ref(entry_id, version + 1),
                        "change_reason": (nxt or {}).get("change_reason")})
        return out

    def _version_row(self, entry_id: str, version: int) -> dict | None:
        if entry_id.startswith("pg_"):
            pv = self.ws.framework.page_version(entry_id, version)
            return {"change_reason": (pv or {}).get("data", {}).get("reason")} if pv else None
        e = self.ws.ledger.get(make_ref(entry_id, version))
        return {"change_reason": e["data"].get("change_reason")} if e else None

    def _dress(self, h: dict, terms: set[str], *, include_process: bool, reads: dict | None,
               unit_total: int, params: dict) -> dict:
        """一条结果：坐标（只写例外）、一行说明、命中段落、旧版命中、依据片段、全部关系（设计稿 10 D-21）。"""
        base = h["id"]
        coords = h["coords"]
        head = parse_ref(coords["ref"])[1]
        all_units = h.get("units", [])
        units = [u for u in all_units if head is None or not u.version or u.version >= head]
        old_units: dict[int, list[str]] = {}
        for u in all_units:
            if head is not None and u.version and u.version < head:
                old_units.setdefault(u.version, []).append(u.text[:params["snippet_chars"]])
        out = {"id": base, **self.ws.coordinates.compact(coords), "channels": h["channels"],
               "relevance_rank": h["relevance_rank"], **({"exact": True} if h.get("exact") else {})}
        seg_text: dict[str, str] = {}
        seg_info: dict[str, dict] = {}
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
        out["passages"] = passages
        out["more_matches"] = max(0, len(units) - len(passages))
        out["size"] = {"units": unit_total}
        if seg_text:
            out["size"]["segments"] = len([a for a in seg_text if a != "title"])
        old_hits = self._old_hits(base, old_units, " ".join(p["text"] for p in passages))
        if old_hits:
            out["old_hits"] = old_hits
        out["status_note"] = self._note(coords, old_hits)
        first = passages[0] if passages else {}
        out["text"] = first.get("text") or self.preview(base)
        if best_first:
            out["anchor"] = best_first
            out["cite_as"] = f"{base}#{best_first}"
            for k in ("unit", "unit_label", "fidelity", "verified"):
                if k in first:
                    out[k] = first[k]
        if reads is not None and base.startswith("art_"):
            had = reads.get(base, set())
            out["read_before"] = bool(had & {a for p in passages for a in p.get("anchors", [])})
            if had:
                out["read_anchors"] = sorted(had)[:20]
        out["basis"] = self._basis(coords["ref"], include_process=include_process, limit=params["basis_shown"])
        if base.startswith("pg_"):  # 设计稿 09 D-12
            page = self.ws.framework.page(base)
            if page:
                out["basis_mix"] = self.basis_mix(self.ws.framework.inputs_of("page", base, page["head_version"]))
        out["links"] = self.ws.relations.summary(coords["ref"], limit=int(params["links_max"]))
        return out

    def _basis(self, ref: str, *, include_process: bool, limit: int) -> list[dict]:
        """判断这一版的依据、框架页的输入清单（D-11）：最多 limit 条（设置 retrieval.basis_shown），
        每条一句片段与一行说明；读全文由 AI 决定。"""
        base, version, _ = parse_ref(ref)
        refs: list[str] = []
        if base.startswith(("jdg_", "rec_")):
            refs = [r["object"] for r in self.ws.ledger.relations_from(base, "cites", version=version)]
        elif base.startswith("pg_"):
            page = self.ws.framework.page(base)
            refs = self.ws.framework.inputs_of("page", base, page["head_version"]) if page else []
        out = []
        memo: dict = {}
        for target in dict.fromkeys(refs):
            if len(out) >= limit:
                break
            coords = self._safe_coordinates(target, memo)
            if coords is None:
                out.append({"ref": target, "status_note": "所引条目已不存在"})
                continue
            if coords["kind"] == "process" and not include_process:
                continue
            item = {"ref": target, "status_note": status_note(coords)}
            t_base, t_version, anchor = parse_ref(target)
            if anchor:
                seg = next((s for s in self.ws.index.segments(t_base) if _anchor(s["locator"]) == anchor), None)
                item["text"] = (seg["text"] if seg else "")[:200]
            else:
                item["text"] = self.preview(make_ref(t_base, t_version))[:200]
            out.append(item)
        if len(dict.fromkeys(refs)) > len(out):
            out.append({"more": len(dict.fromkeys(refs)) - len(out)})
        return out

    def _safe_coordinates(self, ref: str, memo: dict | None = None) -> dict | None:
        try:
            return self.ws.coordinates.of(ref.split("#", 1)[0], memo=memo)
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
        if any(h.get("old_hits") for h in shown):
            hints.append("old_hits 是命中的旧版文字：当前版已改，需要时用 entry_get 读那一版（如 jdg_…@2）")
        if any(h["layer"] == "framework" for h in shown):
            hints.append("框架页只能帮助找方向，不能作为依据；依据见它的 basis（输入清单）")
        if any((h.get("links") or {}).get("truncated") for h in shown):
            hints.append("有结果的关系超过上限被截断：用 entry_get(ref, links=谓词, offset=…) 取全")
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
        hints.append("名次只表示相关度；可靠与否看每条的 status_note 与坐标（地位 → 类型 → 现状 → 说明）")
        return hints

    # ---------- 展开 ----------
    def expand(self, entry_ref: str, *, mode: str = "reuse") -> dict:
        """一条原件一列条目的背景（设计稿 01 D-08、D-09）：
        来源（原件）或条件（过程日志、事实记录）→ 同一来源的前后内容 → 涉及的对象 → 依据了它的判断（解读）。"""
        base, version, anchor = parse_ref(entry_ref)
        entry = self.ws.get(make_ref(base, version))
        if entry is None:
            raise BurrowlError("NOT_FOUND", "条目不存在", {"id": entry_ref})
        coords = self.coordinates(make_ref(base, version))
        out: dict = {"entry": entry, "coordinates": coords, "status_note": status_note(coords)}
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
            out["read_of"] = {"artifact_id": entry["artifact_id"], "artifact_version": entry.get("artifact_version"),
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
                "session_id": art["session_id"], "created_at": art["created_at"], "ref": art["ref"],
                "version": art["version"], "head_version": art["head_version"],
                **fields, "metadata": d.get("metadata") or {}}

    def interpretations(self, base: str) -> list[dict]:
        """依据或评价了它的判断：直接指向它（任一版、任一段落），或经由读过它的读取记录。"""
        rels = self.ws.ledger.relations_to(base)
        if base.startswith("art_"):
            for rd in self.ws.ledger.query("SELECT DISTINCT id FROM read_versions WHERE artifact_id = ?", (base,)):
                rels += self.ws.ledger.relations_to(rd["id"])
        out, seen = [], set()
        for r in rels:
            key = (r["subject"], r["predicate"], r["object"])
            if key in seen or not r["subject_id"].startswith("jdg_"):
                continue
            seen.add(key)
            j = self.ws.ledger.get(r["subject"])
            out.append({"judgment_id": r["subject_id"], "ref": r["subject"], "predicate": r["predicate"],
                        "via": r["object"], "judgment_kind": j["kind"] if j else None,
                        "preview": self.preview(r["subject"]), "note": "这是解读，不是原件内容"})
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
        """每个段落被读过几次、被哪些判断依据（按结论 / 过程 / 规定分组，D-01、T-06）。"""
        art = self.ws.ledger.get(artifact_id)
        if art is None or art["entry_kind"] != "artifact":
            raise BurrowlError("NOT_FOUND", "原件不存在", {"artifact_id": artifact_id})
        artifact_id = art["id"]
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
            if item["predicate"] != "cites":
                continue
            v_base, _, v_anchor = parse_ref(item["via"])
            if v_base == artifact_id and not v_anchor:
                whole.append(item)
                continue
            anchors = [v_anchor.replace("seg:", "seg-", 1)] if v_anchor else read_anchors.get(v_base, [])
            for a in anchors:
                group = slot(a)["citations"].setdefault(item["judgment_kind"] or "other", [])
                if item["judgment_id"] not in [g["judgment_id"] for g in group]:
                    group.append({"judgment_id": item["judgment_id"], "via": item["via"], "preview": item["preview"]})
        return {"artifact_id": artifact_id, "segments": stats, "whole_artifact": whole, "reads": len(reads)}

    def object_view(self, obj: str) -> dict:
        """对象页（D-08）：关于这个对象的全部条目。有效约束在前，其次被反驳的结论，其余按类型、时间。
        不显示自动日志（写判断、写框架页等）；已升级为事实记录的过程日志只显示事实记录。"""
        key = (self.ws.linking.normalize_objects([obj]) or [obj])[0]
        entity = self.ws.framework.entity(key) if key.startswith("ent_") else None
        ids = self.ws.ledger.entries_with_objects([key])
        promoted = {r["event_id"] for r in self.ws.ledger.query(
            "SELECT event_id FROM records WHERE event_id IS NOT NULL")}
        groups: dict[str, list[dict]] = {"constraints": [], "disputed": [], "conclusion": [], "process": [],
                                         "record": [], "artifact": [], "event": []}
        memo: dict = {}
        for entry_id in ids:
            entry = self.ws.get(entry_id)
            if entry is None or entry_id.startswith("rd_"):
                continue
            if entry_id.startswith("evt_") and (entry["op"] in AUTO_LOG_OPS or entry_id in promoted):
                continue
            coords = self._safe_coordinates(entry_id, memo)
            if coords is None or is_gone(coords):  # 已撤回、已退役、依据全部失效（设计稿 07 D-02）
                continue
            item = {"id": entry_id, "created_at": entry["created_at"], "preview": self.preview(entry_id),
                    **self.ws.coordinates.compact(coords), "status_note": status_note(coords)}
            if entry_id.startswith("jdg_"):
                marks = {m["mark"] for m in coords["state"]["marks"]}
                if entry["kind"] == "normative":
                    group = "constraints"
                elif entry["kind"] == "conclusion" and "opposed" in marks and is_current(coords):
                    group = "disputed"
                else:
                    group = entry["kind"]
            else:
                group = entry["entry_kind"]
            groups[group].append(item)
        for items in groups.values():
            items.sort(key=lambda i: i["created_at"], reverse=True)  # 新的在前
            items.sort(key=lambda i: (i.get("state") or {}).get("validity", "current") != "current")
        pages = [dict(p) for p in self.ws.framework.conn.execute(
            "SELECT id, type, title, freshness, review FROM pages WHERE subject_id = ?", (key,))]
        return {"id": key, "name": entity["name"] if entity else key, "entity": entity,
                "groups": groups, "total": sum(len(v) for v in groups.values()), "pages": pages}

    def timeline(self, obj: str) -> list[dict]:
        """按对象和时间精确过滤（历史类查询）。"""
        key = self.ws.linking.normalize_objects([obj])
        ids = self.ws.ledger.entries_with_objects(key)
        items = [e for e in (self.ws.get(i) for i in ids) if e]
        items.sort(key=lambda e: e["created_at"])
        memo: dict = {}
        out = []
        for e in items:
            coords = self._safe_coordinates(e["id"], memo)
            out.append({"id": e["id"], "created_at": e["created_at"], "preview": self.preview(e["id"]),
                        **(self.ws.coordinates.compact(coords) if coords else {})})
        return out

    # ---------- 约束 ----------
    def active_constraints(self, objects: list[str]) -> list[dict]:
        if not objects:
            return []
        rows = self.ws.ledger.query(
            "SELECT DISTINCT j.id FROM judgments j JOIN entry_objects o ON o.entry_id = j.id AND o.version = j.version "
            f"WHERE j.kind = 'normative' AND o.object IN ({','.join('?' * len(objects))})",
            objects)
        out = []
        for r in rows:
            if self.ws.versions.validity(r["id"]) != "current":
                continue
            j = self.ws.ledger.get(r["id"])
            out.append({"id": j["id"], "ref": j["ref"], "kind": j["kind"], "text": j["data"]["text"],
                        "author_kind": j["author_kind"], "author_id": j["author_id"], "objects": j["objects"],
                        "created_at": j["created_at"]})
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

    def preview(self, entry_ref: str) -> str:
        e = self.ws.get(entry_ref) or {}
        d = e.get("data") or {}
        return str(d.get("text") or d.get("result") or d.get("excerpt") or d.get("title") or d.get("output")
                   or e.get("title") or e.get("op") or "")[:300]


def kind_label(kind: str) -> str:
    return KINDS.get(kind, kind)


def _shown_params(p: dict, limit: int) -> dict:
    """结果里写明本次用的检索参数：AI 不用猜"每条最多几个命中单元"之类的数字（设计稿 06 D-21）。"""
    keys = ("passages_shown", "snippet_chars", "basis_shown", "links_max", "rerank_top", "rrf_k", "pool_min",
            "pool_factor", "phrase_limit")
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


__all__ = ["JUDGMENT_KINDS", "RETRIEVAL_DEFAULTS", "RetrievalService", "check_source", "filter_matches",
           "source_matches"]
