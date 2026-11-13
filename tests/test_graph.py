"""坐标的内存图（设计稿 10 G 组）：对比测试、字段声明核对、别的连接写入、彻底删除、回滚。"""
import random

import pytest

from burrowl.core.actor import Actor
from burrowl.core.errors import BurrowlError
from burrowl.services import graph as graph_mod
from burrowl.services.coordinates import DATA_READS, READS
from burrowl.services.workspace import Workspace
from tests.reference_coordinates import SqlCoordinates
from tests.test_extraction import image_pdf


# ---------- 对比：图上推出的坐标与 SQL 参照完全一致（D-36） ----------
def all_refs(ws) -> list[str]:
    refs = []
    for table in ("artifact_versions", "event_versions", "record_versions", "read_versions", "judgment_versions"):
        refs += [f"{r['id']}@{r['version']}" for r in ws.ledger.query(f"SELECT id, version FROM {table}")]
        refs += [r["id"] for r in ws.ledger.query(f"SELECT DISTINCT id FROM {table}")]
    refs += [r[0] for r in ws.framework_db.execute("SELECT id FROM pages")]
    refs += [r[0] for r in ws.framework_db.execute("SELECT id FROM edges")]
    refs += [r[0] for r in ws.framework_db.execute("SELECT id FROM entities")]
    return refs


def assert_same(ws, note=""):
    ref_impl = SqlCoordinates(ws)
    for ref in all_refs(ws):
        got, want = ws.coordinates.of(ref), ref_impl.of(ref)
        assert got == want, f"{note} {ref}\n图：{got}\n参照：{want}"
        assert ws.coordinates.sources(ref) == ref_impl.sources(ref), f"{note} {ref} sources"


class World:
    """随机操作：每一步挑一种写入；不合规则的（AI 不能做的、对象不对的）直接跳过。"""

    def __init__(self, ws, files, seed):
        self.ws, self.files, self.rng = ws, files, random.Random(seed)
        self.human = Actor("human:tester", "human", "ses_01JC0000000000000000000001")
        self.ais = [Actor("ai:a", "ai", "ses_01JC00000000000000000000A1"),
                    Actor("ai:b", "ai", "ses_01JC00000000000000000000B2")]
        self.n = 0
        ws.save_config({"review": {"ai": "all"}})  # 让 AI 复核判断也能发生

    def ids(self, table):
        return [r["id"] for r in self.ws.ledger.query(f"SELECT DISTINCT id FROM {table}")]

    def pick(self, items):
        return self.rng.choice(items) if items else None

    def segment_refs(self):
        out = []
        for a in self.ids("artifact_versions"):
            try:
                out += [f"{a}#{s['anchor']}" for s in self.ws.artifacts.segments(a)[:4]]
            except BurrowlError:
                pass
        return out

    # 各种写入
    def register_text(self):
        self.n += 1
        tier = self.pick([None, "peer_reviewed", "vendor"])
        self.ws.artifacts.register(self.human, kind="log", source_class="external" if tier else "local",
                                   external_tier=tier, text=f"第 {self.n} 份\n\n压力 0.{self.n} MPa\n\n温度 {self.n} 度\n",
                                   title=f"记录 {self.n}")

    def register_scan(self):
        self.n += 1
        path = self.files(f"scan{self.n}.pdf", image_pdf())
        art = self.ws.artifacts.register(self.pick(self.ais), kind="file", source_class="local", path=path)
        self.ws.extraction.submit(self.pick(self.ais), art["id"], method="ai", model="m",
                                  content=[{"unit": "p1", "text": f"扫描 {self.n} 压力 0.8 MPa"}])

    def read(self):
        art = self.pick(self.ids("artifact_versions"))
        if art:
            self.ws.artifacts.read(self.pick(self.ais), art)

    def write_judgment(self, actor=None):
        actor = actor or self.pick(self.ais + [self.human])
        pool = self.segment_refs() + self.ids("judgment_versions") + self.ids("read_versions") \
            + self.ids("record_versions")
        cites = self.rng.sample(pool, k=min(len(pool), self.rng.randint(0, 3)))
        for c in cites:  # AI 引原件段落前先读，免得只得到提示
            if c.startswith("art_"):
                self.ws.artifacts.read(actor if actor.kind == "ai" else self.ais[0], c.split("#")[0])
        rels = []
        target = self.pick(self.ids("judgment_versions"))
        if target and self.rng.random() < 0.5:
            preds = ["supports", "opposes"] + (["supersedes"] if actor.kind == "human" else [])
            rels.append({"rel": self.pick(preds), "target": target})
        self.n += 1
        self.ws.judgments.write(actor, kind=self.pick(["conclusion", "conclusion", "normative", "process"]),
                                text=f"判断 {self.n}", cites=cites, relations=rels,
                                external_author=self.pick([None, None, "Li et al."]),
                                scope_unclear=self.rng.random() < 0.2,
                                local_observation=actor.kind == "human" and self.rng.random() < 0.3)

    def promote(self):
        art = self.pick(self.ids("artifact_versions"))
        if art:
            self.ws.artifacts.promote(self.pick(self.ais), artifact_id=art, method="读表",
                                      boundary=self.pick(["complete", "partial"]),
                                      gaps=["缺下午的数据"], result="0.8 MPa")

    def revise(self):
        j = self.pick(self.ids("judgment_versions"))
        if j:
            self.ws.versions.correct(self.human, j, reason="更正", text=f"更正 {self.rng.random():.3f}")

    def change_state(self):
        e = self.pick(self.ids("judgment_versions") + self.ids("record_versions") + self.ids("artifact_versions"))
        if e:
            st = self.ws.versions.state(e)
            options = ["unwithdraw" if st["withdrawn"] else "withdraw", "undefect" if st["defective"] else "defect"]
            if e.startswith("art_"):
                options = options[1:]
            self.ws.versions.change_state(self.human, e, self.pick(options), "处置")

    def retire(self):
        art = self.pick(self.ids("artifact_versions"))
        other = self.pick(self.ids("artifact_versions"))
        if art:
            self.ws.judgments.retire(self.human, art, reason="过时",
                                     replaced_by=other if other != art and self.rng.random() < 0.3 else None)

    def restore(self):
        art = self.pick(self.ids("artifact_versions"))
        if art:
            self.ws.judgments.restore(self.human, art, reason="恢复")

    def replace(self):
        retired = [a for a in self.ids("artifact_versions") if self.ws.judgments.retirement_of(a)]
        art, new = self.pick(retired), self.pick(self.ids("artifact_versions"))
        if art and new:
            self.ws.judgments.replace(self.human, art, replacement=new, reason="替代")

    def human_review(self):
        item = self.pick(self.ids("judgment_versions") + self.pages())
        if item:
            self.ws.reviews.submit(self.human, item_id=item, verdict=self.pick(["confirm", "reject"]), reason="看过",
                                   local_observation=item.startswith("jdg_") and self.rng.random() < 0.3)

    def ai_review(self):
        item = self.pick(self.ids("judgment_versions") + self.pages())
        if item:
            actor = self.pick(self.ais)
            for c in self.ws.ledger.relations_from(item, "cites") if item.startswith("jdg_") else []:
                if c["object_id"].startswith("art_"):
                    self.ws.artifacts.read(actor, c["object_id"])  # 复核前先读所引原件
            self.ws.reviews.ai_submit(actor, item_id=item, verdict=self.pick(["confirm", "reject",
                                                                                           "unsure"]),
                                      reason="核对", model="m")

    def raw_review(self):
        """直接追加复核记录（跳过 AI 复核的流程检查）：对比测试只关心推出规则对任何合法记录都与参照一致。"""
        scans = [a for a in self.ids("artifact_versions") if self.ws.ledger.get(a)["data"].get("suffix") == ".pdf"]
        target = self.pick(self.ids("judgment_versions") + self.pages() + self.ids("artifact_versions") + scans * 3)
        if not target:
            return
        kind = {"jdg": "judgment", "pg": "page", "art": "artifact"}[target.split("_", 1)[0]]
        method = self.pick(["ai", "ai", "human"])
        data = {}
        if kind == "artifact":  # 识别核对：针对某一段的文字或公式
            segs = self.ws.artifacts.segments(target)
            if not segs:
                return
            seg = self.pick(segs)
            data = {"anchor": seg["anchor"], "part": self.pick(["text", "latex"]),
                    "extraction_id": seg.get("extraction_id")}
            method = "ai"
        elif kind == "page":
            data = {"version": self.ws.framework.page(target)["head_version"]}
        else:
            extra = self.pick(self.segment_refs())
            data = {"cites": [extra] if extra and self.rng.random() < 0.5 else [],
                    "local_observation": method == "human" and self.rng.random() < 0.3}
        head = self.ws.ledger.head_version(target) if kind == "judgment" else None
        self.ws.ledger.insert("reviews", "rev", {
            "target_id": target, "target_version": self.pick([head, head, None]) if head else None,
            "target_kind": kind, "verdict": self.pick(["confirm", "reject", "unsure"]), "method": method,
            "actor_id": "ai:a" if method == "ai" else "human:tester", "session_id": "ses_x", "data": data})

    def revoke(self):
        item = self.pick(self.ids("judgment_versions") + self.pages())
        if item:
            rows = [i for i in self.ws.reviews.history(item)["items"] if i.get("can_revoke") and not i.get("revoked")]
            if rows:
                self.ws.reviews.revoke(self.human, item_id=item, record_ids=[rows[0]["id"]], reason="撤销")

    def reextract(self):
        scans = [a for a in self.ids("artifact_versions") if self.ws.ledger.get(a)["data"].get("suffix") == ".pdf"]
        art = self.pick(scans)
        if art:
            self.ws.extraction.submit(self.pick(self.ais), art, method="ai", model="m2",
                                      content=[{"unit": "p1", "text": f"重识别 {self.rng.random():.3f}"}])

    def verify(self):
        scans = [a for a in self.ids("artifact_versions") if self.ws.ledger.get(a)["data"].get("suffix") == ".pdf"]
        art = self.pick(scans)
        if art:
            self.ws.extraction.verify(self.human, art, units=["p1"])

    def pages(self):
        return [r[0] for r in self.ws.framework_db.execute("SELECT id FROM pages")]

    def page(self):
        inputs = self.ids("judgment_versions")[:3]
        self.n += 1
        ent = self.ws.frameworks.entity_upsert(self.human, kind="device", name=f"设备 {self.n % 3}")
        self.ws.frameworks.page_write(self.pick(self.ais), type="synthesis", title=f"综述 {self.n}", body="见判断",
                                      inputs=inputs, subject_id=ent["id"])

    def other_connection(self):
        other = Workspace(self.ws.root)
        try:
            World(other, self.files, self.rng.random()).write_judgment(self.ais[1])
        finally:
            other.close()

    def purge(self):
        retired = [a for a in self.ids("artifact_versions") if self.ws.judgments.retirement_of(a)]
        art = self.pick(retired)
        if art:
            preview = self.ws.purge.preview(art)
            self.ws.purge.delete(self.human, art, confirm=preview["confirm"])

    def step(self):
        actions = [self.register_text, self.register_scan, self.read, self.write_judgment, self.write_judgment,
                   self.write_judgment, self.promote, self.revise, self.change_state, self.retire, self.restore,
                   self.replace, self.human_review, self.ai_review, self.revoke, self.reextract, self.verify,
                   self.page, self.other_connection, self.purge, self.raw_review, self.raw_review]
        action = self.pick(actions)
        try:
            action()
        except BurrowlError:
            pass  # 不合规则的随机操作：跳过
        return action.__name__


@pytest.fixture
def files(tmp_path):
    def make(name, data):
        path = tmp_path / name
        path.write_bytes(data)
        return str(path)
    return make


@pytest.mark.parametrize("seed", range(10))
def test_graph_matches_sql_reference_under_random_writes(ws, files, seed):
    world = World(ws, files, seed)
    for _ in range(3):
        world.register_text()
    world.register_scan()
    assert_same(ws, "初始")
    done = []
    for i in range(60):
        done.append(world.step())
        if i % 3 == 2 or done[-1] in ("purge", "other_connection"):
            assert_same(ws, f"seed={seed} 第 {i} 步（{done[-1]}）")
    assert_same(ws, f"seed={seed} 结束")
    assert ws.coordinates.graph.stats()["versions"] > 10


# ---------- 字段声明（D-37） ----------
def test_rules_declare_exactly_what_the_graph_exposes():
    """推出规则声明读的字段与图上暴露的字段完全一致：规则要用新字段，两边同时声明。"""
    assert READS == graph_mod.NODE_FIELDS
    assert DATA_READS == graph_mod.DATA_FIELDS


def test_graph_fields_come_from_ledger_and_framework_columns(ws):
    """图上声明的字段（算出的除外）在来源表里都有列。"""
    for kind, fields in graph_mod.NODE_FIELDS.items():
        if kind in graph_mod.SOURCE_TABLE:
            cols = {r[1] for r in ws.ledger_db.execute(f"PRAGMA table_info({graph_mod.SOURCE_TABLE[kind]})")}
        else:
            cols = {r[1] for r in ws.framework_db.execute(f"PRAGMA table_info({graph_mod.FRAMEWORK_TABLE[kind]})")}
        missing = fields - graph_mod.COMPUTED - graph_mod.PROBES - cols
        assert not missing, f"{kind} 声明了表里没有的字段：{missing}"


def test_reading_undeclared_field_fails_loudly(ws, human, pump_log):
    ws.coordinates.of(pump_log["id"])
    node = ws.coordinates.graph.entry(pump_log["id"])
    assert node["source_class"] == "local"
    with pytest.raises(KeyError, match="D-37"):
        node.get("uri")  # 表里有，但没声明给图
    with pytest.raises(KeyError, match="D-37"):
        node["data"]["title"]


# ---------- 合并与重建（D-32、D-33） ----------
def test_incremental_merge_without_rebuild(ws, human, ai, pump_log):
    j = ws.judgments.write(ai, kind="conclusion", text="a", cites=[pump_log["id"]])
    ws.coordinates.of(j["id"])
    g = ws.coordinates.graph
    rebuilds, gen = g.rebuilds, g.generation
    ws.coordinates.of(j["id"])
    assert g.generation == gen  # 没有写入：不合并、不重算
    j2 = ws.judgments.write(ai, kind="conclusion", text="b", relations=[{"rel": "supports", "target": j["id"]}])
    marks = [m["mark"] for m in ws.coordinates.of(j["id"])["state"]["marks"]]
    assert "corroborated" in marks and g.generation > gen and g.rebuilds == rebuilds
    assert ws.coordinates.of(j2["id"]) is not None


def test_other_connection_writes_are_seen(ws, human, ai, pump_log):
    j = ws.judgments.write(ai, kind="conclusion", text="a", cites=[pump_log["id"]])
    assert ws.coordinates.of(j["id"])["state"]["validity"] == "current"
    other = Workspace(ws.root)
    try:
        other.versions.change_state(human, j["id"], "withdraw", "撤回")
    finally:
        other.close()
    assert ws.coordinates.of(j["id"])["state"]["validity"] == "withdrawn"
    assert ws.coordinates.graph.rebuilds == 1


def test_purge_triggers_rebuild(ws, human, ai, pump_log):
    other = ws.artifacts.register(human, kind="log", source_class="local", text="另一份\n\n0.9 MPa", title="另一份")
    j = ws.judgments.write(ai, kind="conclusion", text="a", cites=[pump_log["id"], other["id"]])
    ws.coordinates.of(j["id"])
    ws.judgments.retire(human, pump_log["id"], reason="过时")
    marks = [m["mark"] for m in ws.coordinates.of(j["id"])["state"]["marks"]]
    assert "basis_lapsed" in marks
    preview = ws.purge.preview(pump_log["id"])
    rebuilds = ws.coordinates.graph.rebuilds
    ws.purge.delete(human, pump_log["id"], confirm=preview["confirm"])
    assert ws.ledger.get(j["id"]) is not None and ws.ledger.get(pump_log["id"]) is None
    assert ws.coordinates.graph.head_version(pump_log["id"]) is not None  # 还没读：图上仍是删除前的
    lapsed = next(m for m in ws.coordinates.of(j["id"])["state"]["marks"] if m["mark"] == "basis_lapsed")
    assert lapsed["via"][0]["detail"] == "已删除"
    assert ws.coordinates.graph.rebuilds == rebuilds + 1  # 删了行：不按新增行合并，整图重建
    assert ws.coordinates.graph.head_version(pump_log["id"]) is None
    assert len(all_refs(ws)) > 2
    assert_same(ws, "删除后")


def test_rolled_back_rows_do_not_stay_in_graph(ws, human, ai, pump_log):
    from burrowl.core.sql import transaction
    j = ws.judgments.write(ai, kind="conclusion", text="a", cites=[pump_log["id"]])
    ws.coordinates.of(j["id"])
    with pytest.raises(RuntimeError), transaction(ws.ledger_db):
        ws.versions.change_state(human, j["id"], "withdraw", "撤回")
        assert ws.coordinates.of(j["id"])["state"]["validity"] == "withdrawn"  # 事务里读得到自己写的
        raise RuntimeError("回滚")
    assert ws.coordinates.of(j["id"])["state"]["validity"] == "current"


def test_returned_coordinates_are_copies(ws, ai, pump_log):
    j = ws.judgments.write(ai, kind="conclusion", text="a", cites=[pump_log["id"]])
    c = ws.coordinates.of(j["id"])
    c["state"]["validity"] = "改掉"
    c["sources"].append("改掉")
    again = ws.coordinates.of(j["id"])
    assert again["state"]["validity"] == "current" and "改掉" not in again["sources"]


def test_latest_ai_recognition_check_wins(ws, human, ai, files):
    """同一段落多次 AI 核对：取最近一次（与 RecognitionReview.checks 一致）。"""
    from tests.test_extraction import register
    art = register(ws, ai, files("scan.pdf", image_pdf()))
    ws.extraction.submit(ai, art["id"], method="ai", model="m", content=[{"unit": "p1", "text": "压力 0.82 MPa"}])
    ws.artifacts.read(ai, art["id"], "p1")
    j = ws.judgments.write(ai, kind="conclusion", text="扫描件记 0.82 MPa", cites=[f"{art['id']}#p1-1"])
    seg = ws.artifacts.segments(art["id"])[0]

    def check(verdict):
        ws.ledger.insert("reviews", "rev", {
            "target_id": art["id"], "target_version": None, "target_kind": "artifact", "verdict": verdict,
            "method": "ai", "actor_id": "ai:b", "session_id": "ses_y",
            "data": {"anchor": seg["anchor"], "part": "text", "extraction_id": seg["extraction_id"]}})

    def detail():
        marks = ws.coordinates.of(j["id"])["notes"]["marks"]
        return next(m for m in marks if m["mark"] == "recognition_unverified")["via"][0]["state"]
    assert detail() == "unchecked"
    check("reject")
    assert detail() == "ai_flagged"
    check("unsure")
    assert detail() == "ai_unsure"
    check("confirm")  # AI 看图核对一致：标记仍在（人没确认），说明写"AI 核对一致"
    assert detail() == "ai_confirmed"
    assert_same(ws, "多次核对")
