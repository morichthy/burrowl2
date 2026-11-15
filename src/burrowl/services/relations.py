"""关系（设计稿 10 D-07 至 D-11、D-21）：主语—谓词—宾语，一条一行，两端固定到版本。

- 写：按词表（core/vocab.py）校验谓词、谁能写、宾语种类、必填的限定；
- 读：同一个函数从两端取关系（出边 / 入边），反向名来自词表（D-10）；
- 判断层与机械关系存在账本 relations；框架推断的边、页面的输入清单与主题存在框架库，这里统一呈现成关系
  （可再生，不能作为依据）；
- 关系概况（D-21）：检索结果里给全部关系，每条压成 {p, ref}，只在超过上限时截断并写明剩余条数。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import kind_of, make_ref, parse_ref
from ..core.model import LAYER_OF_KIND
from ..core.vocab import CATEGORY_ORDER, PREDICATES, relation_phrase

DEFAULT_LINKS_MAX = 50
# 截断时的保留顺序：立场与替代、佐证与反驳 → 依据 → 过程 → 自由标签 → 框架推断与提及（D-21）
_KEEP_ORDER = {"supersedes": 0, "opposes": 0, "supports": 0, "coexists_under": 0, "answers": 0, "targets": 0,
               "assumes": 0,
               "cites": 1, "consumed": 2, "produced": 2, "relates": 3}


def category_of(predicate: str) -> str:
    return PREDICATES.get(predicate, {}).get("category", "free")


class RelationService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 写 ----------
    def check(self, actor: Actor, predicate: str, subject: dict, obj: str, *, label: str | None = None,
              qualifiers: dict | None = None) -> None:
        """subject 是主语条目（已取出的行，或即将写入的判断的 {entry_kind, kind}）。不合规就抛出。"""
        p = PREDICATES.get(predicate)
        if p is None or p["origin"] == "framework":
            allowed = [k for k, v in PREDICATES.items() if v["origin"] != "framework"]
            raise BurrowlError("INVALID_ARGUMENT", f"关系必须是 {', '.join(allowed)} 之一；核心谓词都不合适时用 "
                               "relates 并写 label", {"predicate": predicate})
        if actor.kind not in p["writers"]:
            if actor.kind == "ai" and "human" in p["writers"]:
                actor.require_human(f"写入「{p['label']}」关系")
            raise BurrowlError("FORBIDDEN", f"「{p['label']}」关系不能由 {actor.kind} 写入", {"predicate": predicate})
        if "label" in p["required"] and not (label or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "自由谓词 relates 必须写 label（如「导致」「是……的一种」）")
        for q in p["required"]:
            if q != "label" and not (qualifiers or {}).get(q):
                raise BurrowlError("INVALID_ARGUMENT", f"「{p['label']}」关系必须写明 {q}",
                                   {"predicate": predicate})
        target = self.target(obj)
        if p["evidential"]:
            self._reject_thought(predicate, subject, target, obj)
        if predicate == "cites" and subject.get("entry_kind") == "judgment":
            self._reject_inferred(target, obj)
        if predicate == "assumes" and target.get("entry_kind") != "judgment":
            raise BurrowlError("INVALID_ARGUMENT", "「前提」只能指向一条判断（通常是假设类思路）", {"ref": obj})

    def target(self, ref: str) -> dict:
        """关系的宾语：必须是账本里存在的条目（不能是框架条目、抽取记录）。返回那一版。"""
        base, version, _ = parse_ref(ref)
        kind = kind_of(base)
        if kind is None:
            raise BurrowlError("INVALID_REFERENCE", "不是合法的条目 ID", {"ref": ref})
        if LAYER_OF_KIND.get(kind) == "framework":
            raise BurrowlError("FRAMEWORK_NOT_EVIDENCE", "框架条目不能作为依据，请引用它所依据的原件或判断",
                               {"ref": ref})
        if kind == "extraction":
            raise BurrowlError("INVALID_REFERENCE", "抽取记录不能作为依据，请引用原件段落（art_…#p3-2）", {"ref": ref})
        if kind not in ("artifact", "event", "record", "read", "judgment"):
            raise BurrowlError("INVALID_REFERENCE", "这类条目不能作为关系的宾语", {"ref": ref, "kind": kind})
        entry = self.ws.ledger.get(make_ref(base, version))
        if entry is None:
            raise BurrowlError("NOT_FOUND", "关系指向的条目不存在", {"ref": ref})
        return entry

    def _reject_thought(self, predicate: str, subject: dict, target: dict, ref: str) -> None:
        """I11：思路不能作为结论的依据。cites 的宾语、supports 的主语是证据一方。
        思路可以被佐证（设计稿 15 D-27）：supports 的宾语可以是假设、联想类思路。"""
        if predicate == "cites" and subject.get("kind") == "conclusion" and target.get("kind") == "thought":
            raise BurrowlError("THOUGHT_NOT_EVIDENCE", "思路（提问、尝试、停下的路线、假设、联想、目的）"
                               "不能作为结论的依据，"
                               "请引用它背后的原件或结论；它依赖一条假设时用 assumes（前提）", {"refs": [ref]})
        if predicate == "supports" and subject.get("kind") == "thought":
            raise BurrowlError("THOUGHT_NOT_EVIDENCE", "思路不能佐证别的条目；要佐证请写成引用原件的结论",
                               {"refs": [ref]})
        if predicate == "supports" and target.get("kind") == "thought" \
                and (target.get("data") or {}).get("subkind") not in ("hypothesis", "association"):
            raise BurrowlError("THOUGHT_NOT_EVIDENCE", "思路里只有假设、联想可以被佐证", {"refs": [ref]})

    def _reject_inferred(self, target: dict, ref: str) -> None:
        """只有推断来源、没经人复核的结论不能作为依据（设计稿 15 D-07）：猜测请写成思路（假设）。"""
        if target.get("entry_kind") != "judgment" or target.get("kind") != "conclusion":
            return
        coords = self.ws.coordinates.of(target["ref"])
        if coords and coords["sources"] == ["inferred"] and coords["state"]["review"] != "human_confirmed":
            raise BurrowlError("INFERRED_NOT_EVIDENCE",
                               "这条结论的依据只有推断、也没有经人复核，不能作为依据；请引用它背后的原件，"
                               "或把它当作假设（思路）用 assumes 指向", {"refs": [ref]})

    def add(self, actor: Actor, predicate: str, subject: str, obj: str, *, label: str | None = None,
            qualifiers: dict | None = None, checked: bool = False) -> dict:
        """写一条关系。checked=True 表示调用方已经 check 过（写判断时整批先校验再写入）。"""
        if not checked:
            entry = self.ws.ledger.get(subject)
            if entry is None:
                raise BurrowlError("NOT_FOUND", "关系的主语不存在", {"subject": subject})
            self.check(actor, predicate, entry, obj, label=label, qualifiers=qualifiers)
        return self.ws.ledger.relate(predicate, subject, obj, actor.id, session_id=actor.session_id,
                                     label=(label or "").strip() or None, qualifiers=qualifiers)

    def mechanical(self, predicate: str, subject: str, obj: str, actor: Actor, qualifiers: dict | None = None) -> dict:
        """系统按规则建立的关系（用到、产出、事实记录的出处），不做写的人校验。"""
        return self.ws.ledger.relate(predicate, subject, obj, actor.id, session_id=actor.session_id,
                                     qualifiers=qualifiers)

    # ---------- 读 ----------
    def of(self, ref: str, *, direction: str = "both", include_framework: bool = True) -> dict:
        """一个条目的关系：{out: [...], in: [...]}。每条带 predicate、label、category、phrase（从这一端看的说法）、
        other（对端引用）、asserted_by、origin。账本条目带 `@n` 时只取那一版的出边。"""
        base, version, _ = parse_ref(ref)
        out, inc = [], []
        led = self.ws.ledger
        if direction in ("both", "out"):
            for r in led.relations_from(base, version=version):
                out.append(self._item(r, outgoing=True))
        if direction in ("both", "in"):
            for r in led.relations_to(base):
                inc.append(self._item(r, outgoing=False))
        if include_framework:
            fo, fi = self._framework(base, direction)
            out += fo
            inc += fi
        return {"out": out, "in": inc}

    def _item(self, r: dict, *, outgoing: bool) -> dict:
        p = r["predicate"]
        return {"id": r["id"], "predicate": p, "label": r.get("label"), "category": category_of(p),
                "phrase": relation_phrase(p, outgoing=outgoing, label=r.get("label")),
                "other": r["object"] if outgoing else r["subject"], "subject": r["subject"], "object": r["object"],
                "qualifiers": r.get("qualifiers") or {}, "asserted_by": r["asserted_by"],
                "created_at": r["created_at"], "origin": PREDICATES.get(p, {}).get("origin", "judgment")}

    def _framework(self, base: str, direction: str) -> tuple[list[dict], list[dict]]:
        """框架库里的边、页面输入清单、页面主题，呈现成关系（不能作为依据）。"""
        fw = self.ws.framework
        out, inc = [], []
        for e in fw.edges_of(base):
            if e["review"] == "rejected":
                continue
            item = {"id": e["id"], "predicate": e["rel"], "label": None, "category": category_of(e["rel"]),
                    "subject": e["src_id"], "object": e["dst_id"], "qualifiers": e.get("data") or {},
                    "asserted_by": e["origin"], "created_at": e["created_at"], "origin": "framework",
                    "review": e["review"]}
            if e["src_id"] == base and direction in ("both", "out"):
                out.append({**item, "other": e["dst_id"], "phrase": relation_phrase(e["rel"], outgoing=True)})
            if e["dst_id"] == base and direction in ("both", "in"):
                inc.append({**item, "other": e["src_id"], "phrase": relation_phrase(e["rel"], outgoing=False)})
        if base.startswith("pg_"):
            page = fw.page(base)
            if page and direction in ("both", "out"):
                for i in fw.inputs_of("page", base, page["head_version"]):
                    out.append(self._fw_item("derived_from", make_ref(base, page["head_version"]), i, True))
            if page and page.get("subject_id") and direction in ("both", "in"):  # 实体是主语：页面这一端是入边
                inc.append(self._fw_item("subject_of", page["subject_id"], base, False))
        elif direction in ("both", "in"):
            for kind, derived in fw.dependents([base]):
                if kind == "page":
                    page = fw.page(derived)
                    if page:
                        inc.append(self._fw_item("derived_from", make_ref(derived, page["head_version"]), base,
                                                 False))
            if base.startswith("ent_"):
                for page in fw.pages():
                    if page.get("subject_id") == base:
                        out.append(self._fw_item("subject_of", base, page["id"], True))
        return out, inc

    def _fw_item(self, predicate: str, subject: str, obj: str, outgoing: bool) -> dict:
        return {"id": None, "predicate": predicate, "label": None, "category": "framework", "subject": subject,
                "object": obj, "other": obj if outgoing else subject, "qualifiers": {}, "asserted_by": "system",
                "created_at": None, "origin": "framework",
                "phrase": relation_phrase(predicate, outgoing=outgoing)}

    def summary(self, ref: str, *, limit: int | None = None, explore: bool = False) -> dict:
        """关系概况（D-21）：全部出边入边，每条 {p, ref}（自由谓词加 label），按谓词类别排序；
        超过上限才截断，保留立场、替代、佐证与反驳、依据，写明各谓词还剩多少条。
        explore=True（探索模式）：不给框架推断的关系；原件一列不给依据或评价了它的判断（解读，设计稿 06 D-12）。"""
        limit = limit or int(self.ws.config.get("retrieval", {}).get("links_max", DEFAULT_LINKS_MAX))
        rel = self.of(ref, include_framework=not explore)
        if explore and parse_ref(ref)[0].startswith(("art_", "evt_", "rec_", "rd_")):
            rel["in"] = [x for x in rel["in"] if not x["other"].startswith("jdg_")]
        out = {"out": [], "in": []}
        truncated: dict[str, dict[str, int]] = {}
        for side in ("out", "in"):
            items = sorted(rel[side], key=lambda x: (_KEEP_ORDER.get(x["predicate"], 4),
                                                     CATEGORY_ORDER.index(x["category"])
                                                     if x["category"] in CATEGORY_ORDER else 9))
            for i, x in enumerate(items):
                if i < limit:
                    out[side].append({"p": x["predicate"], "ref": x["other"],
                                      **({"label": x["label"]} if x.get("label") else {})})
                else:
                    truncated.setdefault(side, {}).setdefault(x["predicate"], 0)
                    truncated[side][x["predicate"]] += 1
        if truncated:
            out["truncated"] = truncated
            out["more"] = "其余关系用 entry_get(ref, links=谓词, offset=…) 分页取全"
        return out

    def page(self, ref: str, *, predicate: str | None = None, side: str | None = None, offset: int = 0,
             limit: int = 100) -> dict:
        """entry_get 的关系分页：按谓词、方向取，带对端标题与坐标由调用方补。"""
        rel = self.of(ref)
        out = {}
        for s in ("out", "in"):
            if side and s != side:
                continue
            items = [x for x in rel[s] if predicate is None or x["predicate"] == predicate]
            out[s] = items[offset:offset + limit]
            out[f"{s}_total"] = len(items)
        return out

    def free_labels(self, *, min_count: int = 1) -> list[dict]:
        """自由谓词的常用标签（D-09）：巡检与整理时列出，由人决定归并、登记同义或升格。"""
        rows = self.ws.ledger.query("SELECT label, COUNT(*) AS n FROM effective_relations WHERE predicate='relates' "
                                    "GROUP BY label HAVING COUNT(*) >= ? ORDER BY n DESC, label", (min_count,))
        return [{"label": r["label"], "count": r["n"]} for r in rows]
