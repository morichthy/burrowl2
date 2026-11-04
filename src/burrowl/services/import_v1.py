"""从旧版 burrowl（0.x）数据目录导入到新版的空工作区。只读旧数据目录，不修改其中任何文件。

映射规则（旧版概念 → 新版三列，DESIGN §7）：

| 旧版 | 新版 |
|---|---|
| 对象（research.json 等业务卡） | 框架：实体（kind=project）；所有导入条目的对象都带上它 |
| 来源登记 sources.json | 原件：≤ 20 MB 复制保存，更大的只登记路径和指纹；原件不在时用原文快照 |
| 图片附件 attachments/ | 原件（image） |
| Run 业务卡 runs/*/run.json | 原件（log，亲自执行） |
| L0 source 记录 | 指向它的来源原件；正文作为挂在原件上的描述页 |
| L1 detail（导入的原文） | 原件（file），各修订用 version_of 串起 |
| L2 narrative、L3 experience | 判断（claim），各修订用 revises 串起；payload.claims 中的每条结论另成一条判断 |
| review | 人做的复核 → 复核判断；AI 的"复核" → 普通判断（草图 §13：AI 不能复核） |
| L4 overview、document、document_section | 框架：综合页 |
| association | 框架：AI 推断的边（related） |

不知道的就留空或记为缺口，不猜：
- 旧版没有"依据来源"这一轴：Run 的业务卡与产出记为 executed（亲自执行）；
  其余原件记为 discussion（推断或讨论），并在元数据中注明"导入时未知"。
- 旧记录的完整 JSON 保存在条目的 data.v1 中，任何映射丢掉的字段都能找回。
"""
import json
import re
from pathlib import Path

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_file
from ..core.model import derive_credibility

MANAGED_LIMIT = 20 * 1024 * 1024
OWNER_CARDS = ("research.json", "knowledge.json", "project.json", "task.json", "owner.json")
LINK_RE = re.compile(r"\[\[(@[^\]|]+)(\|[^\]]*)?\]\]")


class ImportV1:
    def __init__(self, ws):
        self.ws = ws

    def run(self, actor: Actor, source: str) -> dict:
        actor.require_human("导入旧版数据")
        root = Path(source).expanduser().resolve()
        if not (root / ".burrowl").is_dir():
            raise BurrowlError("INVALID_ARGUMENT", "不是旧版 burrowl 数据目录（缺少 .burrowl/）", {"path": str(root)})
        if self.ws.ledger.query("SELECT id FROM artifacts LIMIT 1") or \
                self.ws.ledger.query("SELECT id FROM judgments LIMIT 1"):
            raise BurrowlError("CONFLICT", "只能导入到空的工作区")
        self.root = root
        self.system = Actor("system:import-v1", "system", actor.session_id)
        self.map: dict[str, str] = {}          # 旧 ID（MEM-/SRC-/CLM-/RUN-…）→ 新 ID
        self.report: dict = {"counts": {}, "gaps": []}
        self.run_outputs = self._run_outputs()
        self._sources()
        self._attachments()
        owners = self._owners()
        self._runs()
        for owner_id, (entity_id, memory) in owners.items():
            self._records(owner_id, entity_id, memory)
        self.report["index"] = self.ws.rebuild_index()
        self.report["mapped"] = len(self.map)
        return self.report

    # ---------- 原件 ----------
    def _sources(self) -> None:
        registry = _json(self.root / ".burrowl" / "sources.json") or {}
        roots = {r["root_id"]: r["path"] for r in registry.get("roots", [])}
        for s in registry.get("sources", []):
            base = Path(roots[s["root"]]) if s.get("root") in roots else self.root
            path = (base / s["path"]).resolve()
            # 旧版没有依据来源一轴：Run 的产出记为亲自执行，其余记为推断或讨论并注明"导入时未知"
            executed = s["source_id"] in self.run_outputs
            cls = "executed" if executed else "discussion"
            meta = {"v1": s, "source_class_note": "旧版 Run 的产出" if executed else "旧版没有依据来源一轴，导入时未知"}
            art = None
            if path.is_file() and sha256_file(path) == s.get("sha256"):
                storage = "managed" if path.stat().st_size <= MANAGED_LIMIT else "referenced"
                art = self.ws.artifacts.register(self.system, kind="file", source_class=cls, path=str(path),
                                                 title=s.get("title"), storage=storage, metadata=meta)
            else:
                text = self._snapshot_text(s["source_id"], s.get("sha256"))
                if text is not None:
                    meta["from_snapshot"] = True
                    art = self.ws.artifacts.register(self.system, kind="file", source_class=cls, text=text,
                                                     title=s.get("title"), metadata=meta)
            if art is None:
                self._gap(f"来源 {s['source_id']} 的原件已不在原位置或内容已变，也没有原文快照，未导入", s.get("path"))
                continue
            self.map[s["source_id"]] = art["id"]
            self._count("artifacts.sources")

    def _snapshot_text(self, source_id: str, sha: str | None) -> str | None:
        folder = self.root / ".burrowl" / "snapshots" / source_id
        if not folder.is_dir():
            return None
        files = [folder / f"{sha}.json"] if sha and (folder / f"{sha}.json").exists() else sorted(folder.glob("*.json"))
        if not files:
            return None
        snap = _json(files[-1])
        return "\n\n".join(seg.get("text", "") for seg in snap.get("segments", []))

    def _attachments(self) -> None:
        for f in sorted((self.root / "attachments").glob("*")) if (self.root / "attachments").is_dir() else []:
            art = self.ws.artifacts.register(self.system, kind="image", source_class="discussion", path=str(f),
                                             metadata={"v1_attachment": f.name})
            self.map[f"SRC-ATT-{f.stem[:16].upper()}"] = art["id"]
            self._count("artifacts.attachments")

    def _runs(self) -> None:
        for card in self._run_cards():
            run = _json(card)
            readme = card.parent / "README.md"
            text = json.dumps(run, ensure_ascii=False, indent=2)
            if readme.exists():
                text += "\n\n" + readme.read_text(encoding="utf-8", errors="replace")
            run_id = run.get("run_id") or card.parent.name.upper()
            art = self.ws.artifacts.register(self.system, kind="log", source_class="executed", text=text,
                                             title=f"旧版 Run {run_id}", metadata={"v1_run": run_id})
            self.map[run_id] = art["id"]
            self._count("artifacts.runs")

    def _run_cards(self) -> list[Path]:
        return [c for c in sorted(self.root.rglob("runs/*/run.json")) if ".burrowl" not in c.parts]

    def _run_outputs(self) -> set[str]:
        """Run 业务卡登记的产出来源 ID；这些原件按"亲自执行"导入。"""
        return {item.get("path") for card in self._run_cards() for item in (_json(card) or {}).get("artifacts", [])}

    # ---------- 对象 ----------
    def _owners(self) -> dict:
        owners = {}
        for name in OWNER_CARDS:
            for card in sorted(self.root.glob(f"*/*/{name}")):
                memory = card.parent / "memory"
                data = _json(card)
                owner_id = data.get("research_id") or data.get("owner_id") or data.get("id") or card.parent.name
                if owner_id in owners or not memory.is_dir():
                    continue
                entity = self.ws.frameworks.entity_upsert(self.system, kind="project",
                                                          name=data.get("title") or card.parent.name,
                                                          description=data.get("description"))
                self.map[owner_id] = entity["id"]
                owners[owner_id] = (entity["id"], memory)
                self._count("entities.owners")
        return owners

    # ---------- 记录 ----------
    def _records(self, owner_id: str, entity_id: str, memory: Path) -> None:
        revisions: dict[str, list[dict]] = {}
        for f in memory.glob("commits/*/records/*.json"):
            rec = _json(f)
            revisions.setdefault(rec["record_id"], []).append(rec)
        heads = set((_json(memory / "commits" / _json(memory / "HEAD.json")["commit_id"] / "manifest.json")
                     or {}).get("record_heads", {}))
        order = {"source": 0, "detail": 1, "narrative": 2, "experience": 3, "review": 4, "association": 5,
                 "document_section": 6, "overview": 7, "document": 8}
        ordered = sorted(revisions.items(), key=lambda kv: (order.get(kv[1][0]["kind"], 9), kv[1][0]["created_at"]))
        for record_id, revs in ordered:
            revs.sort(key=lambda r: r["revision"])
            handler = getattr(self, f"_kind_{revs[0]['kind']}", None)
            if handler is None:
                self._gap(f"未识别的旧记录类型 {revs[0]['kind']}，未导入", record_id)
                continue
            handler(record_id, revs, entity_id)
            if heads and record_id not in heads and record_id in self.map:
                self._removed(record_id, entity_id)

    def _kind_source(self, record_id: str, revs: list[dict], entity_id: str) -> None:
        rec = revs[-1]
        target = next((s["target_id"] for s in rec["sources"] if s["target_id"] in self.map), None)
        if target is None:
            self._gap("L0 来源记录指向的原件没有导入", record_id)
            return
        self.map[record_id] = self.map[target]
        if rec.get("body_markdown", "").strip():
            self._page("description", rec, entity_id, subject=self.map[target], inputs=[self.map[target]])

    def _kind_detail(self, record_id: str, revs: list[dict], entity_id: str) -> None:
        prev = None
        for rec in revs:
            art = self.ws.artifacts.register(self.system, kind="file", source_class="discussion",
                                             text=self._text(rec), title=rec.get("title"), version_of=prev,
                                             metadata={"v1": _meta(rec)}, objects=[entity_id])
            prev = art["id"]
        self.map[record_id] = prev
        self._count("artifacts.l1")

    def _judgment_kind(self, record_id: str, revs: list[dict], entity_id: str) -> None:
        prev = None
        for rec in revs:
            prev = self._judgment(rec, entity_id, revises=prev)
        self.map[record_id] = prev
        for claim in revs[-1]["payload"].get("claims") or []:
            text = claim.get("statement") or claim.get("text") or json.dumps(claim, ensure_ascii=False)
            jid = self._insert_judgment("claim", text, revs[-1], entity_id, cites=[prev], extra={"v1_claim": claim})
            if claim.get("claim_id"):
                self.map[claim["claim_id"]] = jid
        self._count("judgments")

    _kind_narrative = _judgment_kind
    _kind_experience = _judgment_kind

    def _kind_review(self, record_id: str, revs: list[dict], entity_id: str) -> None:
        rec = revs[-1]
        p = rec["payload"]
        reviewer = p.get("reviewer") or rec["created_by"]
        target = self.map.get(p.get("target_claim_id") or "")
        text = f"旧版复核：状态 {p.get('state')}，成熟度 {p.get('maturity')}。{p.get('reason') or ''}"
        human = reviewer.get("kind") == "human"
        relations = []
        if human and target:
            rel = {"rejected": "retracts", "retracted": "retracts", "superseded": "supersedes"}.get(p.get("state"))
            relations = [(rel or "supports", target)]
        jid = self._insert_judgment("review" if human else "claim", text, rec, entity_id,
                                    cites=[target] if target and not relations else [], relations=relations)
        self.map[record_id] = jid
        self._count("judgments.reviews")

    def _kind_association(self, record_id: str, revs: list[dict], entity_id: str) -> None:
        p = revs[-1]["payload"]
        src = self.map.get((p.get("from") or {}).get("target_id", "") if isinstance(p.get("from"), dict)
                           else p.get("from") or "")
        dst = self.map.get((p.get("to") or {}).get("target_id", "") if isinstance(p.get("to"), dict)
                           else p.get("to") or "")
        if not (src and dst):
            self._gap("关联两端未全部导入，未建边", record_id)
            return
        edge = self.ws.framework.add_edge(rel="related", src_id=src, dst_id=dst, origin="ai_inferred",
                                          review="ai_generated", inputs=[src, dst],
                                          data={"reason": p.get("explanation"), "v1": _meta(revs[-1])})
        self.map[record_id] = edge["id"]
        self._count("edges.associations")

    def _kind_overview(self, record_id: str, revs: list[dict], entity_id: str) -> None:
        self.map[record_id] = self._page("synthesis", revs[-1], entity_id, subject=entity_id)

    _kind_document = _kind_overview
    _kind_document_section = _kind_overview

    # ---------- 写入辅助 ----------
    def _judgment(self, rec: dict, entity_id: str, revises: str | None) -> str:
        return self._insert_judgment("claim", self._text(rec), rec, entity_id, revises=revises)

    def _insert_judgment(self, kind: str, text: str, rec: dict, entity_id: str, *, cites: list | None = None,
                         relations: list | None = None, revises: str | None = None, extra: dict | None = None) -> str:
        """直接写账本：保留旧版的作者与时间。依据只取能对上的原件和判断，框架条目放进 data.v1 不作依据。"""
        refs = [*(cites or []), *self._refs(rec)]
        ledger_refs = [r for r in dict.fromkeys(refs) if r and r.split("_")[0] in ("art", "rec", "rd", "jdg")]
        basis = [self.ws.judgments.basis_of(r) for r in ledger_refs]
        author = rec.get("created_by") or {"id": "unknown", "kind": "ai"}
        author_kind = author.get("kind") if author.get("kind") in ("human", "ai") else "ai"
        cred = derive_credibility(basis, author_kind=author_kind, kind=kind)
        data = {"text": text or rec.get("title") or "", "conditions": None, "credibility": cred,
                "v1": _meta(rec), **(extra or {})}
        if revises:
            data["revise_reason"] = rec.get("change_reason")
        j = self.ws.ledger.insert("judgments", "jdg", {
            "created_at": rec.get("updated_at") or rec["created_at"], "kind": kind,
            "author_id": f"v1:{author.get('id')}", "author_kind": author_kind, "revises": revises,
            "session_id": None, "data": data}, objects=[entity_id])
        for r in ledger_refs:
            self.ws.ledger.link("used", j["id"], r, j["author_id"])
        for rel, target in relations or []:
            self.ws.ledger.link(rel, j["id"], target, j["author_id"], {"imported": True})
        if revises:
            self.ws.ledger.link("wasRevisionOf", j["id"], revises, j["author_id"], {"reason": rec.get("change_reason")})
        return j["id"]

    def _page(self, type_: str, rec: dict, entity_id: str, *, subject: str, inputs: list[str] | None = None) -> str:
        refs = [*(inputs or []), *self._refs(rec)]
        slug = f"v1-{rec.get('handle') or rec['record_id'].lower()}"
        page = self.ws.framework.write_page(
            page_id=None, type_=type_, slug=slug, title=rec.get("title") or slug, subject_id=subject,
            author_id=f"v1:{(rec.get('created_by') or {}).get('id')}", review="ai_generated",
            inputs=[r for r in dict.fromkeys(refs) if r],
            version_data={"body": self._text(rec), "summary": None, "author_kind": "ai", "v1": _meta(rec)},
            page_data={"imported_from_v1": rec["record_id"]})
        self.ws.frameworks.index_page(page["id"])
        self._count(f"pages.{type_}")
        return page["id"]

    def _refs(self, rec: dict) -> list[str]:
        out = []
        for s in [*rec.get("sources", []), *(link.get("ref") or {} for link in rec.get("links", []))]:
            new = self.map.get(s.get("target_id", ""))
            if new:
                out.append(new)
        return out

    def _text(self, rec: dict) -> str:
        """正文中的旧链接 [[@短名#块|文字]] 换成新 ID；对不上的保持原样。"""
        by_text = {link.get("text"): (link.get("ref") or {}).get("target_id") for link in rec.get("links", [])}
        body = rec.get("body_markdown") or ""

        def swap(m: re.Match) -> str:
            new = self.map.get(by_text.get(m.group(1)) or "")
            return f"[[{new}{m.group(2) or ''}]]" if new else m.group(0)
        title = rec.get("title")
        text = LINK_RE.sub(swap, body)
        return f"{title}\n\n{text}" if title and title not in text[:200] else text

    def _removed(self, record_id: str, entity_id: str) -> None:
        target = self.map[record_id]
        if not target.startswith("jdg_"):
            return
        j = self.ws.ledger.insert("judgments", "jdg", {
            "kind": "retraction", "author_id": self.system.id, "author_kind": "system", "revises": None,
            "session_id": None, "data": {"text": "该记录在旧版中已删除（导入时按旧版状态记录）",
                                         "conditions": None, "credibility": derive_credibility(
                                             [], author_kind="system", kind="retraction")}},
            objects=[entity_id])
        self.ws.ledger.link("retracts", j["id"], target, self.system.id, {"imported": True})
        self._count("judgments.removed_in_v1")

    def _count(self, key: str) -> None:
        self.report["counts"][key] = self.report["counts"].get(key, 0) + 1

    def _gap(self, message: str, ref) -> None:
        self.report["gaps"].append({"message": message, "ref": ref})


def _json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _meta(rec: dict) -> dict:
    """旧记录除正文外的全部字段，原样保存。"""
    return {k: v for k, v in rec.items() if k != "body_markdown"}
