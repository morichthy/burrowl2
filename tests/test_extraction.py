"""抽取层、段落引用、读取降级、原件文件接口（设计稿 01 AC-01 至 AC-16 中可自动验证的部分）。"""
import asyncio
import base64
import hashlib
import hmac
import io
import json

import pytest
from fastapi.testclient import TestClient

from burrowl.core.errors import BurrowlError
from burrowl.interfaces import engines
from burrowl.interfaces.http import create_app
from burrowl.interfaces.mcp import build_server
from burrowl.interfaces.registry import Ctx, call
from burrowl.services import extractors as ex


# ---------- 样例文件（测试里现做，不依赖外部文件） ----------
def text_pdf(pages: list[str]) -> bytes:
    """手写一份最小的文字型 PDF：每页一段 Helvetica 文字，多行用 TJ 换行。"""
    return pdf_from_ops(["BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in text.split("\n"))
                         + " ET" for text in pages])


def pdf_from_ops(page_ops: list[str]) -> bytes:
    """按每页的内容流拼出一份最小的 PDF（Helvetica）。"""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for ops in page_ops:
        objects.append(f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream")
        content_no = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_no} 0 R "
                       "/Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def png(color=(200, 30, 30), size=(80, 40)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def image_pdf() -> bytes:
    """扫描件式的 PDF：整页只有一张图片，没有文字层。"""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), (240, 240, 240)).save(buf, format="PDF")
    return buf.getvalue()


def sample_pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "泵站月度汇报"
    slide.placeholders[1].text_frame.text = "2号泵出口压力稳定在 0.82 MPa"
    rows = slide.shapes.add_table(2, 2, Inches(1), Inches(4), Inches(4), Inches(1)).table
    rows.cell(0, 0).text, rows.cell(0, 1).text = "时间", "压力"
    rows.cell(1, 0).text, rows.cell(1, 1).text = "10:00", "0.82"
    slide.shapes.add_picture(io.BytesIO(png()), Inches(6), Inches(1))
    slide.notes_slide.notes_text_frame.text = "下月复查入口阀"
    prs.slides.add_slide(prs.slide_layouts[5]).shapes.title.text = "第二页"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def sample_docx() -> bytes:
    import docx
    d = docx.Document()
    d.add_heading("巡检规程", level=1)
    d.add_paragraph("每班检查一次 2号泵出口压力。")
    d.add_paragraph("记录压力", style="List Bullet")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "上限", "0.9 MPa"
    d.add_picture(io.BytesIO(png((10, 120, 10))))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


@pytest.fixture
def files(tmp_path):
    def make(name: str, data: bytes):
        path = tmp_path / name
        path.write_bytes(data)
        return str(path)
    return make


def register(ws, actor, path, kind="file", source_class="local", **kw):
    return ws.artifacts.register(actor, kind=kind, source_class=source_class, path=path, **kw)


# ---------- 文本原件：抽取层是虚拟的，与旧版分段完全一致 ----------
def test_text_artifact_layer_is_virtual_copy(ws, human, pump_log):
    segs = ws.artifacts.segments(pump_log["id"])
    assert [s["anchor"] for s in segs[:2]] == ["seg-0", "seg-1"] and segs[0]["locator"] == "seg:0"
    assert {s["fidelity"] for s in segs} == {"copy"}
    layer = ws.extraction.layer(pump_log["id"])
    assert layer["format"] == "text" and layer["units"][0]["text"].startswith("# 2号泵")
    assert not ws.ledger.query("SELECT id FROM extractions")


# ---------- PDF（AC-11、AC-12） ----------
def test_pdf_is_extracted_on_register_and_searchable(ws, ai, files):
    art = register(ws, ai, files("paper.pdf", text_pdf(["Adam uses moment estimates\nwith bias correction.",
                                                        "Default beta2 equals 0.999 in all runs."])),
                   kind="literature", source_class="external")
    layer = ws.extraction.layer(art["id"])
    assert [u["unit"] for u in layer["units"]] == ["p1", "p2"]
    assert {u["status"] for u in layer["units"]} == {"text"} and layer["units"][0]["fidelity"] == "parsed"
    hits = ws.retrieval.search("beta2")["hits"]
    assert hits and hits[0]["id"] == art["id"] and hits[0]["anchor"].startswith("p2-")
    assert hits[0]["fidelity"] == "parsed" and hits[0]["cite_as"] == f"{art['id']}#{hits[0]['anchor']}"
    # 读取：一次只写一条读取记录，不再写 artifact.read 过程日志（AC-03）
    before = ws.ledger.query("SELECT COUNT(*) AS n FROM events")[0]["n"]
    out = ws.artifacts.read(ai, art["id"], "p2")
    assert out["cite_as"] == [f"{art['id']}#p2-1"] and out["read"]["data"]["anchors"] == ["p2-1"]
    assert ws.ledger.query("SELECT COUNT(*) AS n FROM events")[0]["n"] == before
    # 重复抽取，文本相同不写新记录
    n = len(ws.ledger.query("SELECT id FROM extractions"))
    assert ws.extraction.auto(ai, art["id"])["written"] == []
    assert len(ws.ledger.query("SELECT id FROM extractions")) == n


def test_image_page_waits_for_ai_and_low_fidelity_is_flagged(ws, human, ai, files):
    art = register(ws, ai, files("scan.pdf", image_pdf()))
    unit = ws.extraction.layer(art["id"])["units"][0]
    assert unit["status"] == "image"
    with pytest.raises(BurrowlError) as e:
        ws.artifacts.read(ai, art["id"], "p1")
    assert e.value.code == "UNREADABLE" and "artifact_view" in e.value.message
    view = ws.extraction.view(art["id"], "p1")
    assert view["_image"]["mime"] == "image/png" and len(view["_image"]["base64"]) > 100
    with pytest.raises(BurrowlError):  # AI 识别必须写明模型
        ws.extraction.submit(ai, art["id"], method="ai", content=[{"unit": "p1", "text": "压力 0.82 MPa"}])
    with pytest.raises(BurrowlError) as e:  # 人工转写只有人能提交
        ws.extraction.submit(ai, art["id"], method="manual", content=[{"unit": "p1", "text": "x"}])
    assert e.value.code == "FORBIDDEN"
    ws.extraction.submit(ai, art["id"], method="ai", model="test-model",
                         content=[{"unit": "p1", "text": "巡检表：2号泵出口压力 0.82 MPa"}])
    read = ws.artifacts.read(ai, art["id"], "p1")
    assert "OCR / AI 识别" in read["notice"]
    j = ws.judgments.write(ai, kind="conclusion", text="扫描的巡检表记录 2号泵出口压力 0.82 MPa",
                           cites=[read["cite_as"][0]])
    assert j["warning_codes"] == ["LOW_FIDELITY_CITATION"]
    assert ws.extraction.status_report()["low_fidelity_citations"][0]["judgment_id"] == j["id"]
    ws.extraction.verify(human, art["id"])
    assert ws.extraction.status_report()["low_fidelity_citations"] == []
    j2 = ws.judgments.write(ai, kind="conclusion", text="同上，确认后引用", cites=[read["cite_as"][0]])
    assert j2["warning_codes"] == []
    with pytest.raises(BurrowlError):  # 确认只能由人做
        ws.extraction.verify(ai, art["id"])


# ---------- 段落引用（AC-02、AC-05） ----------
def test_segment_citation_checked_and_unread_flagged(ws, ai, pump_log):
    with pytest.raises(BurrowlError) as e:
        ws.judgments.write(ai, kind="conclusion", text="x", cites=[f"{pump_log['id']}#seg-99"])
    assert e.value.code == "INVALID_REFERENCE"
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.82 MPa", cites=[f"{pump_log['id']}#seg-1"])
    assert j["warning_codes"] == ["UNREAD_CITATION"] and j["data"]["credibility"]["source_classes"] == ["local"]
    assert j["data"]["cited_segments"][0]["sha256"] == ws.artifacts.segments(pump_log["id"])[1]["sha256"]
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    j2 = ws.judgments.write(ai, kind="conclusion", text="读过后再引用", cites=[f"{pump_log['id']}#seg-1"])
    assert j2["warning_codes"] == []
    rule = ws.judgments.write(ai, kind="normative", text="规定不提示未读", cites=[f"{pump_log['id']}#seg-2"])
    assert rule["warning_codes"] == []
    with pytest.raises(BurrowlError) as e:
        ex_id = ws.ledger.query("SELECT id FROM extractions LIMIT 1")
        ws.judgments.write(ai, kind="conclusion", text="x", cites=[ex_id[0]["id"]] if ex_id else ["ex_01JC0000000000000000000000"])
    assert e.value.code in ("INVALID_REFERENCE", "NOT_FOUND")


def test_new_version_marks_judgments_citing_removed_segment(ws, human, ai):
    v1 = ws.artifacts.register(human, kind="log", source_class="local", text="第一段\n\n第二段 0.82 MPa\n")
    j = ws.judgments.write(ai, kind="conclusion", text="压力 0.82 MPa", cites=[f"{v1['id']}#seg-1"])
    ent = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
    page = ws.frameworks.page_write(human, type="synthesis", title="压力综述", body="见判断", inputs=[j["id"]],
                                    subject_id=ent["id"])
    v2 = ws.artifacts.register(human, kind="log", source_class="local", text="第一段\n\n第二段 0.95 MPa\n",
                               version_of=v1["id"])
    assert j["id"] in v2["version_diff"]["affected_judgments"]
    assert ws.framework.page(page["id"])["freshness"] == "inputs_changed"


def test_reextraction_change_puts_judgment_into_recheck(ws, human, ai, files):
    art = register(ws, ai, files("scan.pdf", image_pdf()))
    ws.extraction.submit(ai, art["id"], method="ai", model="m1", content=[{"unit": "p1", "text": "压力 0.82 MPa"}])
    ws.artifacts.read(ai, art["id"], "p1")
    j = ws.judgments.write(ai, kind="conclusion", text="扫描件记 0.82 MPa", cites=[f"{art['id']}#p1-1"])
    out = ws.extraction.submit(ai, art["id"], method="ai", model="m2", content=[{"unit": "p1", "text": "压力 0.92 MPa"}])
    assert out["affected_judgments"] == [j["id"]]
    assert [r["judgment_id"] for r in ws.extraction.needs_recheck()] == [j["id"]]
    ws.artifacts.read(ai, art["id"], "p1")
    ws.judgments.write(ai, kind="conclusion", text="复核：应为 0.92 MPa", cites=[f"{art['id']}#p1-1"],
                       relations=[{"rel": "opposes", "target": j["id"]}])
    # AI 写的链接不让它离开待复核（设计稿 04 D-09）；人复核后才离开
    assert [r["judgment_id"] for r in ws.extraction.needs_recheck()] == [j["id"]]
    ws.reviews.submit(human, item_id=j["id"], verdict="reject", reason="新识别是 0.92 MPa")
    assert ws.extraction.needs_recheck() == []
    assert len(ws.extraction.history(art["id"], "p1")) == 3  # 图片页 → m1 → m2，全部保留


# ---------- PPTX / DOCX / 图片 / 视频（AC-12、AC-16） ----------
def test_pptx_keeps_layout_blocks(ws, ai, files):
    art = register(ws, ai, files("report.pptx", sample_pptx()))
    units = {u["unit"]: u for u in ws.extraction.layer(art["id"])["units"]}
    assert set(units) == {"p1", "p2", "img1"} and units["img1"]["status"] == "not_extracted"
    blocks = units["p1"]["blocks"]
    assert blocks[0]["type"] == "title" and blocks[-1]["type"] == "notes"
    assert {b["type"] for b in blocks} >= {"title", "text", "table", "image", "notes"}
    assert all(0 <= v <= 1.5 for b in blocks if b.get("box") for v in b["box"])
    assert "2号泵出口压力" in units["p1"]["text"] and "备注：下月复查入口阀" in units["p1"]["text"]
    image = next(b for b in blocks if b["type"] == "image")
    assert ws.blobs.has(image["sha256"]) and ws.extraction.owns_blob(art["id"], image["sha256"])
    assert ws.artifacts.segments(art["id"])[0]["anchor"] == "p1-1"


def test_docx_flow_uses_seg_anchors(ws, ai, files):
    art = register(ws, ai, files("rule.docx", sample_docx()))
    layer = ws.extraction.layer(art["id"])
    doc = layer["units"][0]
    assert doc["unit"] == "doc" and [b["type"] for b in doc["blocks"]] == ["heading", "paragraph", "list", "table",
                                                                             "image"]
    assert [u["unit"] for u in layer["units"]] == ["doc", "img1"]
    segs = ws.artifacts.segments(art["id"])
    assert segs[0]["anchor"] == "seg-0" and segs[0]["text"] == "巡检规程"
    read = ws.artifacts.read(ai, art["id"], "seg:1")
    assert read["cite_as"] == [f"{art['id']}#seg-1"]


def test_image_and_video_are_not_extracted_by_default(ws, human, ai, files):
    img = register(ws, ai, files("photo.png", png()), kind="image")
    vid = register(ws, ai, files("clip.mp4", b"\x00\x00\x00\x18ftypmp42fake"))
    assert ws.extraction.layer(img["id"])["units"][0]["status"] == "not_extracted"
    assert ws.extraction.view(img["id"], "img")["_image"]
    out = ws.extraction.submit(human, vid["id"], method="manual",
                               content=[{"unit": "av", "text": "[00:00:05] 开机\n[00:01:23] 压力升到 0.87 MPa"}])
    assert out["written"] == ["av"]
    segs = ws.artifacts.segments(vid["id"])
    assert [(s["anchor"], s["t"]) for s in segs] == [("av-1", 5), ("av-2", 83)] and segs[0]["fidelity"] == "manual"


# ---------- 设置（D-18 设置页） ----------
def test_settings_control_auto_extraction(ws, human, ai, files):
    ctx = Ctx(ws=ws, actor=human, channel="http")
    assert call(ctx, "settings.get", {})["values"]["extraction.pdf"] == "auto"
    with pytest.raises(BurrowlError):
        call(ctx, "settings.set", {"values": {"index.multimodal_model": "clip"}})
    with pytest.raises(BurrowlError):
        call(Ctx(ws=ws, actor=ai, channel="cli"), "settings.set", {"values": {"extraction.pdf": "off"}})
    call(ctx, "settings.set", {"values": {"extraction.pdf": "off"}})
    assert json.loads((ws.root / "config.json").read_text(encoding="utf-8"))["extraction"]["pdf"] == "off"
    art = register(ws, ai, files("later.pdf", text_pdf(["Not extracted yet."])))
    assert ws.extraction.layer(art["id"])["extracted"] is False
    assert ws.extraction.status_report()["unextracted"][0]["artifact_id"] == art["id"]
    assert ws.extraction.backfill(human)["extracted"] == [art["id"]]


def test_settings_choose_default_viewer(ws, human):
    """阅读模式的默认阅读器（设计稿 03 D-14）：只能由人改，取值限于已有的阅读器。"""
    ctx = Ctx(ws=ws, actor=human, channel="http")
    got = call(ctx, "settings.get", {})
    assert got["values"]["viewer.docx"] == "docx-preview" and "pdfjs-snapshot" in got["choices"]["viewer.docx"]
    call(ctx, "settings.set", {"values": {"viewer.docx": "pdfjs-snapshot"}})
    assert call(ctx, "settings.get", {})["values"]["viewer.docx"] == "pdfjs-snapshot"
    with pytest.raises(BurrowlError):
        call(ctx, "settings.set", {"values": {"viewer.docx": "nope"}})


# ---------- 对象标签与对象页（AC-08） ----------
def test_object_tags_and_object_view(ws, human, ai, pump_log):
    ent = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
    rule = ws.judgments.write(human, kind="normative", text="2号泵检修前必须关闭入口阀", objects=[ent["id"]])
    c = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力偏高", objects=[ent["id"]])
    ws.judgments.write(ai, kind="conclusion", text="不偏高", objects=[ent["id"]],
                       relations=[{"rel": "opposes", "target": c["id"]}])
    view = ws.retrieval.object_view(ent["id"])
    assert view["name"] == "2号泵" and view["groups"]["constraints"][0]["id"] == rule["id"]
    assert [i["id"] for i in view["groups"]["disputed"]] == [c["id"]]
    assert view["groups"]["event"] == []  # judgment.write 自动日志不显示
    out = ws.retrieval.expand(rule["id"])
    assert "same_objects" not in out and out["objects"][0]["name"] == "2号泵" and out["objects"][0]["count"] == 3


def test_expand_artifact_gives_source_and_interpretations(ws, ai, pump_log):
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    j = ws.judgments.write(ai, kind="conclusion", text="压力 0.82", cites=[f"{pump_log['id']}#seg-1"])
    out = ws.retrieval.expand(f"{pump_log['id']}#seg-1")
    assert out["source"]["storage"] == "managed" and out["source"]["title"] == "2号泵巡检"
    assert [i["judgment_id"] for i in out["interpretations"]] == [j["id"]]
    stats = ws.retrieval.segment_stats(pump_log["id"])
    assert len(stats["segments"]["seg-1"]["reads"]) == 1
    assert stats["segments"]["seg-1"]["citations"]["conclusion"][0]["judgment_id"] == j["id"]


# ---------- 原件文件接口（AC-01） ----------
def test_artifact_file_endpoint(ws, human, ai, files, tmp_path):
    pdf = text_pdf(["Hello page one."])
    art = register(ws, ai, files("a.pdf", pdf))
    client = TestClient(create_app(ws, "tok"))
    assert client.get(f"/api/artifact/{art['id']}/file").status_code == 403
    r = client.get(f"/api/artifact/{art['id']}/file?token=tok")
    assert r.status_code == 200 and r.content == pdf and r.headers["content-type"] == "application/pdf"
    assert "inline" in r.headers["content-disposition"]
    assert "attachment" in client.get(f"/api/artifact/{art['id']}/file?token=tok&download=true").headers[
        "content-disposition"]
    page = client.get(f"/api/artifact/{art['id']}/page/1.png?token=tok")
    assert page.status_code == 200 and page.content[:4] == b"\x89PNG"
    # 页面内渲染用的 /bytes：字节相同，但不是 PDF 类型、没有文件名，下载管理器的扩展不会拦截（H-16）
    assert client.get(f"/api/artifact/{art['id']}/bytes").status_code == 403
    raw = client.get(f"/api/artifact/{art['id']}/bytes", headers={"x-burrowl-token": "tok"})
    assert raw.status_code == 200 and raw.content == pdf
    assert raw.headers["content-type"].startswith("text/plain") and "content-disposition" not in raw.headers
    assert raw.headers["x-content-type-options"] == "nosniff"
    # 公式等的裁切图（设计稿 03 D-16）：只要页面上的一块，比整页小
    from PIL import Image
    clip = client.get(f"/api/artifact/{art['id']}/page/1.png?token=tok&clip=0.1,0.05,0.5,0.1")
    assert clip.status_code == 200
    whole, part = Image.open(io.BytesIO(page.content)).size, Image.open(io.BytesIO(clip.content)).size
    assert part[0] < whole[0] * 0.6 and part[1] < whole[1] * 0.2
    assert client.get(f"/api/artifact/{art['id']}/page/1.png?token=tok&clip=0.1,2,0.5,0.1").status_code == 400
    assert client.get(f"/api/artifact/{art['id']}/page/1.png?token=tok&clip=a,b").status_code == 400
    # PDF 没有快照（只有 PPTX / DOCX 才有）
    assert client.get(f"/api/artifact/{art['id']}/snapshot/bytes", headers={"x-burrowl-token": "tok"}).status_code == 404
    path = tmp_path / "ext.log"
    path.write_text("原始内容", encoding="utf-8")
    ext_art = ws.artifacts.register(human, kind="log", source_class="local", path=str(path), storage="referenced")
    assert client.get(f"/api/artifact/{ext_art['id']}/file?token=tok").content == "原始内容".encode()
    path.write_text("被改过的内容", encoding="utf-8")
    r = client.get(f"/api/artifact/{ext_art['id']}/file?token=tok")
    assert r.status_code == 409 and r.json()["code"] == "STALE_ARTIFACT"
    assert client.get(f"/api/artifact/{art['id']}/blob/{'0' * 64}?token=tok").status_code == 404


def test_mcp_artifact_view_returns_image(ws, ai, files):
    art = register(ws, ai, files("scan.pdf", image_pdf()))
    server = build_server(ws)
    result = asyncio.run(server.call_tool("artifact_view", {"artifact_id": art["id"], "unit": "p1"}))
    blocks = result[0] if isinstance(result, tuple) else result
    blocks = getattr(blocks, "content", blocks)
    types = [getattr(b, "type", None) for b in blocks]
    assert "image" in types and "text" in types


# ---------- 抽取器的纯函数 ----------
def positioned_pdf(pages: list[list[tuple[float, float, float, str]]]) -> bytes:
    """每页若干 (x, y, 字号, 文字)，各自定位；用来构造页眉页脚、上下标、双栏。"""
    return pdf_from_ops([" ".join(f"BT /F1 {size} Tf {x} {y} Td ({text}) Tj ET" for x, y, size, text in items)
                         for items in pages])


def body_lines(x: float, top: float, n: int, prefix: str, width_chars: int = 60) -> list[tuple]:
    return [(x, top - 14 * i, 11, (f"{prefix} line {i} " + "word " * 20)[:width_chars]) for i in range(n)]


def pdf_blocks(data: bytes) -> list[list[dict]]:
    return [c.blocks for c in ex.extract_pdf(data).contents]


def test_pdf_layout_merges_lines_and_records_boxes():
    """设计稿 02 AC-01：同一段的行并成一块；每块的 box 是页面比例坐标，落在页内并覆盖文字。"""
    items = [(72, 720, 11, "First paragraph starts here and the text runs on to fill the line"),
             (72, 706, 11, "and continues on the second line of the very same paragraph."),
             (72, 650, 11, "Second paragraph after a clear vertical gap, long enough to look like text."),
             (72, 636, 11, "It also has a second line that ends the paragraph.")]
    blocks = pdf_blocks(positioned_pdf([items]))[0]
    paras = [b for b in blocks if b["type"] == "paragraph"]
    assert len(paras) == 2
    assert paras[0]["text"].startswith("First paragraph") and paras[0]["text"].endswith("same paragraph.")
    x, y, w, h = paras[0]["box"]
    assert 0 <= x < 0.2 and 0 < y < 0.15 and 0 < w <= 1 - x and 0 < h < 0.1
    assert abs(x - 72 / 612) < 0.01 and abs(y - (792 - 731) / 792) < 0.02  # 左上角对得上 Td 的位置


def test_pdf_layout_joins_subscripts_into_their_line():
    """上下标（小字号的短片段）并入所在的行，不再单独成段（Adam 第 2 页的问题）。"""
    items = [(72, 720, 11, "The moving averages m"), (190, 717, 7, "t"),
             (196, 720, 11, " and v"), (226, 717, 7, "t"), (232, 720, 11, " are estimates of the moments.")]
    blocks = pdf_blocks(positioned_pdf([items]))[0]
    assert len(blocks) == 1 and "averages m" in blocks[0]["text"] and blocks[0]["text"].endswith("moments.")


def test_pdf_layout_marks_running_heads_and_page_numbers_as_furniture():
    pages = [[(72, 770, 9, "Proceedings of a Conference 2026"), *body_lines(72, 700, 3, f"Page {n} body"),
              (300, 30, 9, str(n))] for n in range(1, 5)]
    for blocks in pdf_blocks(positioned_pdf(pages)):
        kinds = {b["text"]: b["type"] for b in blocks}
        assert kinds["Proceedings of a Conference 2026"] == "furniture"
        assert [b for b in blocks if b["type"] == "furniture" and b["text"].isdigit()]
        assert all("Proceedings" not in ex.block_text(b) for b in blocks)  # 不进索引


def test_pdf_layout_reads_two_columns_left_then_right():
    left = body_lines(72, 700, 8, "Left", 40)
    right = body_lines(320, 700, 8, "Right", 40)
    blocks = pdf_blocks(positioned_pdf([[*right, *left]]))[0]
    text = " ".join(b["text"] for b in blocks)
    assert text.index("Left line 7") < text.index("Right line 0")


def math_pdf(items: list[tuple[float, float, float, str, str]]) -> bytes:
    """(x, y, 字号, 字体 F1=Helvetica / F2=Symbol, 文字)。Symbol 是数学字体（设计稿 03 D-15）。"""
    ops = " ".join(f"BT /{font} {size} Tf {x} {y} Td ({text}) Tj ET" for x, y, size, font, text in items)
    data = pdf_from_ops([ops]).decode("latin-1")
    data = data.replace("/Resources << /Font << /F1 3 0 R >> >>", "/Resources << /Font << /F1 3 0 R /F2 99 0 R >> >>")
    head, _, tail = data.partition("xref")
    head += "99 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Symbol >>\nendobj\n"
    return (head + "xref" + tail).encode("latin-1")  # 交叉引用表不含 99 号对象，pdfium 会自行修复


def test_pdf_layout_detects_display_formulas():
    """行间公式（数学字体占多数的行）成为 formula 块，分子分母并成一块，右侧编号并回；正文不受影响。"""
    prose = "Prose line that explains the method in plain words and keeps going on"
    items = [(72, 720, 11, "F1", prose), (72, 706, 11, "F1", "and ends here with a full stop."),
             (250, 670, 11, "F2", "a + b = g"), (262, 654, 11, "F2", "d - e"), (500, 662, 11, "F1", "(1)"),
             (72, 620, 11, "F1", "Another paragraph follows the equation and has enough words to be prose.")]
    blocks = pdf_blocks(math_pdf(items))[0]
    formulas = [b for b in blocks if b["type"] == "formula"]
    assert len(formulas) == 1
    assert formulas[0]["text"].endswith("(1)")
    x, y, w, h = formulas[0]["box"]
    assert x < 250 / 612 + 0.01 and x + w > 500 / 612 and h > 14 / 792
    paras = [b for b in blocks if b["type"] == "paragraph"]
    assert len(paras) == 2 and not any(b.get("math") for b in paras)
    assert ex.block_text(formulas[0])  # 公式块仍进索引，可以检索、引用


def test_pdf_layout_marks_inline_math_paragraphs():
    items = [(72, 720, 11, "F1", "Let the step size be"), (180, 720, 11, "F2", "a b g"),
             (230, 720, 11, "F1", "and the decay rates stay below one for every step we take here.")]
    blocks = pdf_blocks(math_pdf(items))[0]
    assert [b["type"] for b in blocks] == ["paragraph"] and blocks[0].get("math") is True


def test_cues_from_text():
    assert ex.cues_from_text("[01:02:03] a\n续行\n04:05 b") == [{"type": "cue", "t": 3723, "text": "a 续行"},
                                                               {"type": "cue", "t": 245, "text": "b"}]


def test_parallel_calls_on_one_workspace_are_serialized(ws, human, ai, files):
    """工作台的请求线程共用同一组 SQLite 连接：并行调用不能互相打乱结果（Workspace.lock）。"""
    from concurrent.futures import ThreadPoolExecutor
    art = register(ws, ai, files("report.pptx", sample_pptx()))
    ctx = Ctx(ws=ws, actor=human, channel="http")
    jobs = [("entry.get", {"id": art["id"]}), ("entry.expand", {"id": art["id"]}),
            ("artifact.layer", {"artifact_id": art["id"]}), ("artifact.segments", {"artifact_id": art["id"]}),
            ("artifact.segment_stats", {"artifact_id": art["id"]}), ("stats.overview", {})] * 8
    with ThreadPoolExecutor(12) as pool:
        results = list(pool.map(lambda job: call(ctx, *job), jobs))
    assert len(results) == len(jobs)


def test_auto_reextract_keeps_submitted_units(ws, human, ai, files):
    art = register(ws, ai, files("scan.pdf", image_pdf()))
    ws.extraction.submit(human, art["id"], method="manual", content=[{"unit": "p1", "text": "人工转写的内容"}])
    ws.extraction.auto(human, art["id"])
    ws.extraction.auto(human, art["id"], units=["p1"])  # 内置抽取器读不出文字，也不覆盖
    assert ws.extraction.layer(art["id"])["units"][0]["fidelity"] == "manual"


# ========== 设计稿 03 第二批：Excel 抽取（D-11）、公式 LaTeX 块补充（D-17）、外部阅读引擎 ONLYOFFICE（D-13） ==========
def sample_xlsx() -> bytes:
    import datetime

    import openpyxl
    wb = openpyxl.Workbook()
    a = wb.active
    a.title = "测量"
    a.append(["日期", "温度", "压力"])
    a.append([datetime.date(2026, 11, 1), 21.5, 0.82])
    a.append([datetime.date(2026, 11, 2), 22.0, "=B3*2"])
    a.append([])
    a.append(["备注", "第二个区域"])
    a.merge_cells("A5:B5")
    b = wb.create_sheet("空表")
    b.sheet_state = "hidden"
    c = wb.create_sheet("长表")
    for i in range(120):
        c.append([i, f"行 {i}"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- Excel 抽取（D-11） ----------
def test_xlsx_sheets_become_units_and_regions_become_table_blocks(ws, ai, files):
    art = register(ws, ai, files("data.xlsx", sample_xlsx()))
    layer = ws.extraction.layer(art["id"])
    assert layer["format"] == "xlsx" and layer["snapshot_supported"]
    units = {u["unit"]: u for u in layer["units"]}
    assert [u["label"] for u in layer["units"]] == ["工作表 测量", "工作表 空表（隐藏）", "工作表 长表"]
    blocks = units["s1"]["blocks"]
    assert [b["range"] for b in blocks] == ["A1:C3", "A5:A5"]  # 合并单元格只保留左上角的值
    assert blocks[0]["rows"][1] == ["2026-11-01", "21.5", "0.82"]
    assert units["s1"]["meta"]["merged"] == ["A5:B5"]
    assert units["s2"]["status"] == "empty"
    assert [b["range"] for b in units["s3"]["blocks"]] == ["A1:B50", "A51:B100", "A101:B120"]  # 大区域按行切开
    segs = ws.extraction.segments(ws.artifacts._artifact(art["id"]))
    assert segs[0]["anchor"] == "s1-1" and "日期 | 温度 | 压力" in segs[0]["text"]
    read = ws.artifacts.read(ai, art["id"], "s3-2")
    assert "行 50" in read["segments"][0]["text"]


def test_sheet_blocks_and_column_names():
    assert ex.col_name(1) == "A" and ex.col_name(26) == "Z" and ex.col_name(27) == "AA" and ex.col_name(703) == "AAA"
    blocks = ex.sheet_blocks([(2, ["", "x", "y"]), (3, ["", "", "z"]), (7, ["a"])])
    assert [b["range"] for b in blocks] == ["B2:C3", "A7:A7"] and blocks[0]["rows"] == [["x", "y"], ["", "z"]]


def test_extractor_upgrade_only_rebuilds_changed_formats(ws, human, ai, files):
    """抽取器版本升到 4 只是新增 Excel：已有的 PDF（版本 3）不必重建。"""
    pdf = register(ws, ai, files("m.pdf", math_pdf([(72, 720, 11, "F1", "Plain prose line that is long enough.")])))
    assert not ws.extraction.outdated(ws.artifacts._artifact(pdf["id"]))
    assert ws.extraction.backfill(human)["rebuilt"] == []


# ---------- 公式 LaTeX 块补充（D-17） ----------
FORMULA_PAGE = [(72, 720, 11, "F1", "Prose line that explains the method in plain words and keeps going on"),
                (250, 670, 11, "F2", "a + b = g"), (500, 670, 11, "F1", "(1)"),
                (72, 620, 11, "F1", "Another paragraph follows the equation and has enough words to be prose.")]


def formula_anchor(ws, art_id):
    art = ws.artifacts._artifact(art_id)
    unit = ws.extraction.units(art)[0]
    bi = next(i for i, b in enumerate(unit["blocks"]) if b["type"] == "formula")
    return next(s["anchor"] for s in ws.extraction.segments(art) if s["block"] == bi), unit


def test_latex_supplement_keeps_text_anchor_and_citations(ws, human, ai, files):
    art = register(ws, ai, files("f.pdf", math_pdf(FORMULA_PAGE)))
    anchor, unit = formula_anchor(ws, art["id"])
    ws.artifacts.read(ai, art["id"], anchor)
    ws.judgments.write(ai, kind="conclusion", text="式 (1) 成立", cites=[f"{art['id']}#{anchor}"])
    before = ws.extraction.segments(ws.artifacts._artifact(art["id"]))
    ctx = Ctx(ws=ws, actor=ai, channel="mcp")
    with pytest.raises(BurrowlError):  # AI 识别要写明模型
        call(ctx, "artifact.extract", {"artifact_id": art["id"], "method": "ai", "blocks": [{"anchor": anchor, "latex": "x"}]})
    with pytest.raises(BurrowlError):  # 人工填写只能由人
        call(ctx, "artifact.extract", {"artifact_id": art["id"], "method": "manual",
                                       "blocks": [{"anchor": anchor, "latex": "x"}]})
    prose = next(s["anchor"] for s in before if s["anchor"] != anchor)
    with pytest.raises(BurrowlError):  # 只有公式块可以补充 LaTeX
        call(ctx, "artifact.extract", {"artifact_id": art["id"], "method": "ai", "model": "m",
                                       "blocks": [{"anchor": prose, "latex": "x"}]})
    out = call(ctx, "artifact.extract", {"artifact_id": art["id"], "method": "ai", "model": "claude-opus-5-5",
                                         "blocks": [{"anchor": anchor, "latex": r"\alpha + \beta = \gamma"}]})
    assert out["written"] == [unit["unit"]]
    after = ws.extraction.segments(ws.artifacts._artifact(art["id"]))
    assert [(s["anchor"], s["sha256"]) for s in after] == [(s["anchor"], s["sha256"]) for s in before]
    block = next(b for b in ws.extraction.units(ws.artifacts._artifact(art["id"]))[0]["blocks"] if b["type"] == "formula")
    assert block["latex"] == r"\alpha + \beta = \gamma"
    assert block["latex_source"]["fidelity"] == "ai" and block["latex_source"]["method"] == "ai:claude-opus-5-5"
    assert ws.extraction.status_report()["needs_recheck"] == []  # 文字没变，引用不进待复核
    # 重复提交相同内容不写新记录；整份重新抽取时文字相同的公式块保留 LaTeX
    again = call(ctx, "artifact.extract", {"artifact_id": art["id"], "method": "ai", "model": "claude-opus-5-5",
                                           "blocks": [{"anchor": anchor, "latex": r"\alpha + \beta = \gamma"}]})
    assert again["written"] == []
    ws.extraction.auto(human, art["id"], reason="重新抽取")
    block = next(b for b in ws.extraction.units(ws.artifacts._artifact(art["id"]))[0]["blocks"] if b["type"] == "formula")
    assert block["latex"] == r"\alpha + \beta = \gamma"


def test_artifact_view_anchor_returns_block_crop(ws, ai, files):
    art = register(ws, ai, files("f.pdf", math_pdf(FORMULA_PAGE)))
    anchor, _ = formula_anchor(ws, art["id"])
    out = call(Ctx(ws=ws, actor=ai, channel="mcp"), "artifact.view", {"artifact_id": art["id"], "anchor": anchor})
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(out["_image"]["base64"])))
    assert out["type"] == "formula" and img.size[1] < 200  # 只有公式那一条，不是整页
    with pytest.raises(BurrowlError):
        call(Ctx(ws=ws, actor=ai, channel="mcp"), "artifact.view", {"artifact_id": art["id"]})


# ---------- 外部阅读引擎 ONLYOFFICE（D-13） ----------
def test_jwt_signature_is_hs256():
    token = engines.sign_jwt({"a": 1}, "s3cret")
    head, body, sig = token.split(".")
    pad = lambda x: x + "=" * (-len(x) % 4)  # noqa: E731
    assert json.loads(base64.urlsafe_b64decode(pad(head))) == {"alg": "HS256", "typ": "JWT"}
    assert json.loads(base64.urlsafe_b64decode(pad(body))) == {"a": 1}
    expect = hmac.new(b"s3cret", f"{head}.{body}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64decode(pad(sig)) == expect


def test_onlyoffice_settings_config_and_one_time_file_url(ws, human, ai, files):
    art = register(ws, ai, files("data.xlsx", sample_xlsx()))
    ctx = Ctx(ws=ws, actor=human, channel="http")
    client = TestClient(create_app(ws, "tok"))
    h = {"x-burrowl-token": "tok"}
    assert client.get(f"/api/artifact/{art['id']}/engine/onlyoffice", headers=h).json()["code"] == "ENGINE_UNAVAILABLE"
    with pytest.raises(BurrowlError):
        call(ctx, "settings.set", {"values": {"viewer.onlyoffice_url": "ftp://x"}})
    with pytest.raises(BurrowlError):  # 只有人能改设置
        call(Ctx(ws=ws, actor=ai, channel="mcp"), "settings.set", {"values": {"viewer.onlyoffice_url": "http://x"}})
    call(ctx, "settings.set", {"values": {"viewer.onlyoffice_url": "http://127.0.0.1:9/", "viewer.onlyoffice_secret": "k",
                                          "viewer.onlyoffice_burrowl_url": "http://host.docker.internal:8766"}})
    got = call(ctx, "settings.get", {})["values"]
    assert got["viewer.onlyoffice_url"] == "http://127.0.0.1:9" and got["viewer.onlyoffice_secret"] == "已设置"
    out = client.get(f"/api/artifact/{art['id']}/engine/onlyoffice", headers=h).json()
    cfg = out["config"]
    assert out["api"] == "http://127.0.0.1:9/web-apps/apps/api/documents/api.js"
    assert cfg["documentType"] == "cell" and cfg["editorConfig"]["mode"] == "view"
    assert cfg["document"]["permissions"]["edit"] is False and cfg["document"]["permissions"]["comment"] is False
    assert cfg["token"] == engines.sign_jwt({k: v for k, v in cfg.items() if k != "token"}, "k")
    url = cfg["document"]["url"]
    assert url.startswith("http://host.docker.internal:8766/engine-file/")
    path = url.split("8766", 1)[1]
    got = client.get(path)  # 引擎取文件不带 token
    assert got.status_code == 200 and got.content == sample_xlsx_bytes(ws, art)
    assert client.get("/engine-file/not-a-ticket").status_code == 403
    assert call(ctx, "settings.check_engine", {})["ok"] is False  # 端口 9 上没有引擎


def sample_xlsx_bytes(ws, art):
    return ws.artifacts.content(ws.artifacts._artifact(art["id"]))
