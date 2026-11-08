"""设计稿 05：本地模型（MinerU 版面引擎）、公式识别、调用边界（AC-01 至 AC-04 中可自动验证的部分）。
MinerU 用本文件里的假服务代替：接口形状按 MinerU 4.1.7 的 V1 任务接口与 docvortex.middle 2.0 实测。"""
import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call
from burrowl.services import model_adapters as ma
from burrowl.services.models import is_local

from .test_extraction import FORMULA_PAGE, formula_anchor, math_pdf, register


@pytest.fixture
def files(tmp_path):
    def make(name: str, data: bytes):
        path = tmp_path / name
        path.write_bytes(data)
        return path
    return make


# FORMULA_PAGE 第 1 页：公式 "a + b = g" 在 (250, 670)，编号 (1) 在 (500, 670)；页面 612 × 792
FORMULA_BOX = [250 / 612 - 0.005, (792 - 682) / 792, (512 - 250) / 612, 16 / 792]
PROSE_BOX = [0.118, 0.079, 0.56, 0.016]  # 与内置抽取的第一段位置相近
MISSED_BOX = [0.3, 0.5, 0.3, 0.03]  # 内置抽取里没有任何块的位置


def middle(extra_blocks=()):
    def bbox(b):
        return [b[0], b[1], b[0] + b[2], b[1] + b[3]]
    return {"schema": "docvortex.middle", "schema_version": "2.0",
            "metadata": {"producer": {"name": "mineru", "version": "4.1.7"}},
            "pages": [{"page_idx": 0, "blocks": [
                {"type": "header", "bbox": [0.1, 0.02, 0.5, 0.04], "content": [{"type": "text", "content": "Head"}]},
                {"type": "text", "bbox": bbox(PROSE_BOX), "content": [
                    {"type": "text", "content": "Prose line that explains the method "},
                    {"type": "equation_inline", "content": "x^2"},
                    {"type": "text", "content": " in plain words and keeps going on"}]},
                {"type": "equation", "bbox": bbox(FORMULA_BOX), "content": "a + b = \\gamma \\tag{1}"},
                *extra_blocks]}]}


class FakeMinerU:
    """假的 mineru-api：/v1/health、/v1/tiers、/v1/tasks（建任务 → 上传 → 查询 → 下载 ZIP）。"""

    def __init__(self, result: dict):
        self.result, self.calls = result, []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                fake.calls.append(("GET", self.path))
                base = f"http://127.0.0.1:{fake.port}"
                if self.path == "/v1/health":
                    return self._send(200, {"status": "ok", "version": "4.1.7"})
                if self.path == "/v1/tiers":
                    return self._send(200, {"data": [{"id": "flash"}, {"id": "basic"}]})
                if self.path == "/v1/tasks/t1":
                    return self._send(200, {"task_id": "t1", "status": "completed", "files": [{
                        "file_id": "f1", "status": "completed", "parse": {"parser_version": "4.1.7"},
                        "result_url": f"{base}/v1/files/f1/content"}]})
                if self.path == "/v1/files/f1/content":
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w") as z:
                        z.writestr("middle_json.json", json.dumps(fake.result))
                    return self._send(200, buf.getvalue(), "application/zip")
                self._send(404, {"error": "nf"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.calls.append(("POST", self.path, body))
                base = f"http://127.0.0.1:{fake.port}"
                self._send(202, {"task_id": "t1", "status": "waiting-file", "files": [{
                    "file_id": "f1", "upload": {"url": f"{base}/v1/tasks/t1/uploads/f1"}}]})

            def do_PUT(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                fake.calls.append(("PUT", self.path))
                self._send(200, {"status": "pending"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake_mineru():
    servers = []

    def make(result):
        s = FakeMinerU(result)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


def configure(ws, human, url, **extra):
    call(Ctx(ws=ws, actor=human, channel="http"), "settings.set",
         {"values": {"models.layout": "mineru", "models.layout_url": url, **extra}})


def test_is_local_and_normalize():
    assert is_local("http://127.0.0.1:8790") and is_local("http://localhost:8000") and is_local("http://[::1]:1")
    assert not is_local("http://192.168.1.5:8000") and not is_local("https://api.example.com")
    out = ma.normalize_mineru(middle([{"type": "table", "bbox": [0.1, 0.6, 0.9, 0.8], "content": [
        {"type": "table_body", "content": "<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>"}]}]),
        "4.1.7")
    blocks = out["pages"][0]["blocks"]
    assert out["pages"][0]["page"] == 1 and out["version"] == "4.1.7"
    assert [b["type"] for b in blocks] == ["furniture", "paragraph", "formula", "table"]
    assert blocks[1]["inline"][1] == {"t": "math", "v": "x^2"}
    assert blocks[1]["text"] == "Prose line that explains the method $x^2$ in plain words and keeps going on"
    assert blocks[2]["latex"] == "a + b = \\gamma \\tag{1}"
    x, y, w, h = blocks[2]["box"]
    assert abs(x - FORMULA_BOX[0]) < 1e-3 and abs(w - FORMULA_BOX[2]) < 1e-3
    assert blocks[3]["rows"] == [["a", "b"], ["1", "2"]]


def test_layout_engine_adds_latex_without_changing_anchors(ws, human, ai, files, fake_mineru):
    """AC-02：公式块得到 LaTeX、来源记 tool:mineru@版本、可信度档 ocr；段落锚点与指纹不变；漏掉的公式插入；
    段落记下行内公式；引用补了 LaTeX 的公式块提示低可信度。"""
    server = fake_mineru(middle([{"type": "equation", "bbox": [0.3, 0.5, 0.6, 0.53], "content": "e = mc^2"}]))
    art = register(ws, ai, files("f.pdf", math_pdf(FORMULA_PAGE)))
    anchor, _ = formula_anchor(ws, art["id"])
    before = {s["anchor"]: s["sha256"] for s in ws.extraction.segments(ws.artifacts._artifact(art["id"]))}
    configure(ws, human, server.url, **{"models.layout_mode": "formulas_only_existing"})
    out = call(Ctx(ws=ws, actor=ai, channel="mcp"), "artifact.layout_engine", {"artifact_id": art["id"], "wait": True})
    assert out["status"] == "done", out
    assert out["result"]["latex"] == 1 and out["result"]["inserted"] == 0
    a = ws.artifacts._artifact(art["id"])
    assert {s["anchor"]: s["sha256"] for s in ws.extraction.segments(a)} == before
    block = next(b for b in ws.extraction.units(a)[0]["blocks"] if b["type"] == "formula")
    assert block["latex"] == "a + b = \\gamma \\tag{1}"
    assert block["latex_source"]["method"] == "tool:mineru@4.1.7" and block["latex_source"]["fidelity"] == "ocr"
    para = next(b for b in ws.extraction.units(a)[0]["blocks"] if b.get("inline_math"))
    assert para["inline_math"]["runs"][1] == {"t": "math", "v": "x^2"}
    ws.artifacts.read(ai, art["id"], anchor)
    j = ws.judgments.write(ai, kind="conclusion", text="式 (1)", cites=[f"{art['id']}#{anchor}"])
    assert "LOW_FIDELITY_CITATION" in j["warning_codes"]
    # 默认模式 formulas：插入内置抽取漏掉的公式（不重新调用 MinerU，用缓存）
    calls = len(server.calls)
    out = ws.models.wait(ws.models.run_layout(human, art["id"], mode="formulas")["id"])
    assert out["result"]["inserted"] == 1 and len(server.calls) == calls
    formulas = [b for b in ws.extraction.units(ws.artifacts._artifact(art["id"]))[0]["blocks"] if b["type"] == "formula"]
    assert [f.get("latex") for f in formulas][-1] == "e = mc^2"


def test_layout_engine_keeps_human_latex_and_replace_is_human_only(ws, human, ai, files, fake_mineru):
    server = fake_mineru(middle())
    art = register(ws, ai, files("f.pdf", math_pdf(FORMULA_PAGE)))
    anchor, _ = formula_anchor(ws, art["id"])
    ws.extraction.submit_latex(human, art["id"], method="manual", blocks=[{"anchor": anchor, "latex": "a+b=g"}])
    configure(ws, human, server.url)
    ws.models.wait(ws.models.run_layout(ai, art["id"])["id"])
    block = next(b for b in ws.extraction.units(ws.artifacts._artifact(art["id"]))[0]["blocks"]
                 if b["type"] == "formula")
    assert block["latex"] == "a+b=g"  # 人工填写的不被覆盖（D-10）
    with pytest.raises(BurrowlError) as e:
        ws.models.run_layout(ai, art["id"], mode="replace")
    assert e.value.code == "FORBIDDEN"
    out = ws.models.wait(ws.models.run_layout(human, art["id"], mode="replace")["id"])
    assert out["status"] == "done" and out["result"]["replaced"] == 1
    unit = ws.extraction.units(ws.artifacts._artifact(art["id"]))[0]
    assert unit["fidelity"] == "ocr" and unit["method"] == "tool:mineru@4.1.7"


def test_auto_run_only_for_local_models_and_llm_never_auto(ws, human, ai, files, fake_mineru, monkeypatch):
    """AC-01、AC-03：本机地址的版面引擎在登记后自动运行；改成非本机地址后不再自动运行；
    大模型槽位没有自动选项，登记与补抽过程中不会被调用。"""
    called = []
    monkeypatch.setattr(ma, "llm_formula", lambda *a, **k: called.append(a) or "x")
    server = fake_mineru(middle())
    configure(ws, human, server.url, **{"models.llm": "openai", "models.llm_url": "http://127.0.0.1:9/v1",
                                        "models.llm_model": "m"})
    assert ws.models.status()["slots"]["llm"]["auto"] is False
    assert ws.models.status()["slots"]["layout"]["auto"] is True
    art = register(ws, ai, files("a.pdf", math_pdf(FORMULA_PAGE)))
    job = next(j for j in ws.models.status()["jobs"] if j["artifact_id"] == art["id"])
    assert ws.models.wait(job["id"])["status"] == "done"
    configure(ws, human, "http://192.168.1.50:8790")
    assert ws.models.status()["slots"]["layout"]["auto"] is False
    other = register(ws, ai, files("b.pdf", math_pdf(FORMULA_PAGE[:2])))
    assert not [j for j in ws.models.status()["jobs"] if j["artifact_id"] == other["id"]]
    ws.extraction.backfill(human)
    assert called == []
    with pytest.raises(BurrowlError) as e:  # 大模型只能由人显式调用
        ws.models.recognize_formulas(ai, art["id"], anchors=["p1-2"], engine="llm")
    assert e.value.code == "FORBIDDEN"


def test_recognize_formula_with_llm_when_human_clicks(ws, human, ai, files, monkeypatch):
    monkeypatch.setattr(ma, "llm_formula", lambda url, key, model, png: "\\alpha+\\beta=\\gamma")
    call(Ctx(ws=ws, actor=human, channel="http"), "settings.set", {"values": {
        "models.llm": "openai", "models.llm_url": "http://127.0.0.1:9/v1", "models.llm_model": "vlm-x",
        "models.llm_key": "sk-test"}})
    assert ws.models.status()["slots"]["llm"]["configured"]
    assert call(Ctx(ws=ws, actor=human, channel="http"), "settings.get", {})["values"]["models.llm_key"] == "已设置"
    art = register(ws, ai, files("f.pdf", math_pdf(FORMULA_PAGE)))
    anchor, _ = formula_anchor(ws, art["id"])
    out = ws.models.wait(ws.models.recognize_formulas(human, art["id"], anchors=[anchor], engine="llm")["id"])
    assert out["status"] == "done" and out["result"]["recognized"] == [anchor]
    block = next(b for b in ws.extraction.units(ws.artifacts._artifact(art["id"]))[0]["blocks"]
                 if b["type"] == "formula")
    assert block["latex"] == "\\alpha+\\beta=\\gamma"
    assert block["latex_source"]["method"] == "llm:vlm-x" and block["latex_source"]["fidelity"] == "ai"


def test_models_check_and_failure_does_not_break_extraction(ws, human, ai, files, fake_mineru):
    server = fake_mineru(middle())
    configure(ws, human, server.url)
    info = call(Ctx(ws=ws, actor=human, channel="http"), "models.check", {"slot": "layout"})
    assert info["ok"] and info["version"] == "4.1.7" and info["tiers"] == ["flash", "basic"]
    configure(ws, human, "http://127.0.0.1:9")  # 没有服务的端口
    art = register(ws, ai, files("a.pdf", math_pdf(FORMULA_PAGE)))
    job = next(j for j in ws.models.status()["jobs"] if j["artifact_id"] == art["id"])
    done = ws.models.wait(job["id"])
    assert done["status"] == "failed" and "连不上" in done["error"]
    assert ws.extraction.units(ws.artifacts._artifact(art["id"]))[0]["status"] == "text"  # 内置抽取不受影响
