"""设计稿 05：本地模型（MinerU 版面引擎）、公式识别、调用边界（AC-01 至 AC-04 中可自动验证的部分）。
MinerU 用本文件里的假服务代替：接口形状按 MinerU 4.1.7 的 V1 任务接口与 docvortex.middle 2.0 实测。"""
import io
import json
import os
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces import install
from burrowl.interfaces.registry import Ctx, call
from burrowl.services import agents as agent_service
from burrowl.services import model_adapters as ma
from burrowl.services.models import is_local

from .test_extraction import FORMULA_PAGE, formula_anchor, math_pdf
from .test_extraction import register as _register


def register(ws, *args, **kw):
    """像操作入口一样在数据目录的锁里登记：模型任务线程会等登记全部完成再读账本（同一个 SQLite 连接）。"""
    with ws.lock:
        return _register(ws, *args, **kw)


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

    def __init__(self, result: dict, port: int = 0):
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

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


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


def test_configured_agent_cli_as_llm(ws, human, ai, files, tmp_path):
    """用真实子进程模拟视觉 CLI，覆盖设置、试连、识别、复核及配置引用。"""
    cli = tmp_path / "fake_model.py"
    cli.write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "assert not any(k.startswith('BURROWL_') for k in os.environ)\n"
        "assert 'task.txt' in sys.argv[1]\n"
        "task = Path('task.txt').read_text(encoding='utf-8')\n"
        "if 'BURROWL_OK' in task:\n"
        "    assert not Path('input.png').exists()\n"
        "    print('BURROWL_OK')\n"
        "else:\n"
        "    assert Path('input.png').read_bytes().startswith(bytes([137]) + b'PNG')\n"
        "    print('{\"verdict\":\"confirm\"}' if 'verdict' in task else '$a+b=c$')\n",
        encoding="utf-8",
    )
    ctx = Ctx(ws, human, "http")
    with pytest.raises(BurrowlError, match="选择"):
        call(ctx, "settings.set", {"values": {"models.llm": "agent"}})
    command = [sys.executable, str(cli), "{prompt}"]
    # 用 Claude 模板创建后换了可执行文件：大模型调用应传已保存的参数，不能加 Claude 专用选项。
    saved = call(ctx, "agent.save_command", {"agent": "vision", "command": command, "cli_type": "claude"})
    assert saved["model_timeout_seconds"] == 600
    assert call(ctx, "agent.save_command", {"agent": "vision", "command": command,
                                           "model_timeout_seconds": 1200})["model_timeout_seconds"] == 1200
    call(ctx, "settings.set", {"values": {"models.llm": "agent", "models.llm_agent": "vision"}})
    renamed = call(ctx, "agent.save_command", {"agent": "vision-2", "previous": "vision", "command": command})
    assert renamed["model_timeout_seconds"] == 1200
    assert call(ctx, "settings.get", {})["values"]["models.llm_agent"] == "vision-2"
    with pytest.raises(BurrowlError, match="大模型"):
        call(ctx, "agent.delete", {"agent": "vision-2"})
    assert call(ctx, "models.check", {"slot": "llm"})["ok"]
    assert not ws.models.can_auto("llm")

    art = register(ws, ai, files("vision.pdf", math_pdf(FORMULA_PAGE)))
    anchor, _ = formula_anchor(ws, art["id"])
    assert not ws.models.status()["jobs"]
    with pytest.raises(BurrowlError) as error:
        ws.models.recognize_formulas(ai, art["id"], anchors=[anchor], engine="llm")
    assert error.value.code == "FORBIDDEN"
    job = ws.models.recognize_formulas(human, art["id"], anchors=[anchor], engine="llm")
    done = ws.models.wait(job["id"])
    assert done["status"] == "done", done
    item = next(i for i in ws.recognition.items(art["id"]) if i["anchor"] == anchor and i["part"] == "latex")
    assert item["text"] == "a+b=c"
    job = ws.recognition.enqueue(human, [art["id"]], anchors=[anchor])[0]
    done = ws.models.wait(job["id"])
    assert done["status"] == "done" and done["result"]["confirm"] == 1, done
    assert any(i["ai"]["model"] == "agent:vision-2" for i in ws.recognition.items(art["id"]) if i.get("ai"))
    call(ctx, "settings.set", {"values": {"models.llm": "none"}})
    assert call(ctx, "agent.delete", {"agent": "vision-2"})["deleted"]
    assert not call(ctx, "settings.get", {})["values"]["models.llm_agent"]


@pytest.mark.parametrize("stream", [False, True])
def test_agent_cli_as_llm_times_out(monkeypatch, stream):
    """外部 CLI 卡住时，工作台能结束这次调用并报告超时。"""
    monkeypatch.setattr(agent_service, "_MODEL_TIMEOUT", 6)
    spec = {"command": [sys.executable, "-c", "import time; time.sleep(60)", "{prompt}"],
            "model_timeout_seconds": 1}
    with pytest.raises(BurrowlError, match="1 秒") as error:
        agent_service.AgentService.model_answer(spec, "测试", on_output=(lambda _: None) if stream else None)
    assert error.value.code == "MODEL_ERROR"


def test_agent_model_output_is_published_before_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_service, "_MODEL_TIMEOUT", 6)
    marker = tmp_path / "output-received"
    command = [sys.executable, "-u", "-c",
               "import sys, time; from pathlib import Path\n"
               "print('first', flush=True)\n"
               "while not Path(sys.argv[1]).exists(): time.sleep(0.05)\n"
               "print('last', flush=True)", str(marker), "{prompt}"]
    chunks = []

    def publish(chunk):
        chunks.append(chunk)
        if "first" in "".join(chunks):
            marker.touch()

    assert agent_service.AgentService.model_answer({"command": command}, "测试", on_output=publish) == "first\nlast"
    assert "".join(chunks).splitlines() == ["first", "last"]


@pytest.mark.skipif(os.name != "nt", reason="浏览器终端使用 Windows ConPTY")
def test_dispatch_33_recognitions_in_one_terminal(ws, human, ai, files, tmp_path, monkeypatch):
    """一次工作台提交、一个真实终端进程；保存中间结果，忽略未知编号，核对模式跨数据目录。"""
    from burrowl.services.workspace import Workspace

    monkeypatch.setattr(install, "install_root", lambda: tmp_path / "install")
    ctx = Ctx(ws, human, "http")
    assert call(ctx, "agent.dispatch", {})["mode"] == "terminal"
    art = register(ws, ai, files("demo.txt", b"test"))
    items = [{"anchor": f"p1-{i}", "part": "latex", "unit": "p1", "text": f"x={i}",
              "extraction_id": "ex_snapshot"} for i in range(1, 34)]
    monkeypatch.setattr(ws.recognition, "items", lambda _: items)
    monkeypatch.setattr(ws.recognition, "_image", lambda *_: b"PNG")
    monkeypatch.setattr(ws.extraction, "find", lambda *args: {"extraction_id": "ex_snapshot", "verified": False})
    script = tmp_path / "recognition-agent.py"
    script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "assert sys.stdin.isatty()\n"
        "items = json.loads(Path('manifest.json').read_text(encoding='utf-8'))\n"
        "assert len(items) == 33 and len({i['id'] for i in items}) == 33\n"
        "assert all(Path(i['image']).read_bytes() == b'PNG' for i in items)\n"
        "def put(i):\n"
        "    Path(f'results/{i}.json').write_text(json.dumps({'verdict':'confirm','reason':i}), encoding='utf-8')\n"
        "put('0001')\n"
        "put('9999')\n"
        "print('READY', flush=True)\n"
        "assert input() == 'finish'\n"
        "for item in items[1:]: put(item['id'])\n",
        encoding="utf-8",
    )
    call(ctx, "agent.save_command", {"agent": "demo", "command": [sys.executable, "{prompt}"],
                                     "terminal_args": ["-u", str(script), "{prompt}"]})
    call(ctx, "settings.set", {"values": {"models.llm": "agent", "models.llm_agent": "demo"}})
    args = {"artifact_ids": [art["id"]], "dispatch": True}
    reply = call(ctx, "extraction.ai_check", args)
    run_id = reply["run"]["id"]

    def wait_for(predicate):
        for _ in range(100):
            with ws.lock:
                run = ws.framework.run(run_id)
            if predicate(run):
                return run
            time.sleep(0.05)
        pytest.fail("识别终端未到达预期状态")

    try:
        assert reply["jobs"] == [] and reply["run"]["data"]["terminal"]
        wait_for(lambda r: r["data"]["recognition_batch"]["saved"] == 1)
        assert call(ctx, "extraction.ai_check", args)["run"]["id"] == run_id
        assert [r["id"] for r in call(ctx, "agent.runs", {})] == [run_id]
        call(ctx, "agent.terminal_input", {"run_id": run_id, "text": "finish\r"})
        completed = wait_for(lambda r: r["data"]["recognition_batch"]["ended"])
        assert completed["status"] == "done"
        assert completed["data"]["recognition_batch"]["saved"] == 33
        assert len(ws.recognition.checks(art["id"])) == 33
    finally:
        if ws.agents.output(run_id)["running"]:
            call(ctx, "agent.cancel", {"run_id": run_id})
            wait_for(lambda r: r["data"]["recognition_batch"]["ended"])

    other = Workspace(tmp_path / "other")
    try:
        call(ctx, "agent.dispatch", {"mode": "background"})
        assert call(Ctx(other, human, "http"), "agent.dispatch", {})["mode"] == "background"
        monkeypatch.setattr(ws.recognition, "enqueue", lambda actor, ids, **kwargs: [{"artifact_id": ids[0]}])
        assert call(ctx, "extraction.ai_check", args) == {"jobs": [{"artifact_id": art["id"]}]}
    finally:
        other.close()


@pytest.mark.skipif(os.name != "nt", reason="浏览器终端使用 Windows ConPTY")
def test_terminal_formula_is_saved_as_unverified_ai_extraction(ws, human, ai, files, tmp_path, monkeypatch):
    monkeypatch.setattr(install, "install_root", lambda: tmp_path / "install")
    ctx = Ctx(ws, human, "http")
    art = register(ws, ai, files("terminal-formula.pdf", math_pdf(FORMULA_PAGE)))
    anchor, _ = formula_anchor(ws, art["id"])
    script = ("import json; from pathlib import Path; "
              "assert Path('images/0001.png').read_bytes().startswith(bytes([137])+b'PNG'); "
              "Path('results/0001.json').write_text(json.dumps({'latex': 'a+b=c'}), encoding='utf-8')")
    call(ctx, "agent.save_command", {"agent": "vision", "command": [sys.executable, "{prompt}"],
                                     "terminal_args": ["-c", script, "{prompt}"]})
    call(ctx, "settings.set", {"values": {"models.llm": "agent", "models.llm_agent": "vision"}})
    rid = call(ctx, "artifact.recognize_formula", {
        "artifact_id": art["id"], "anchors": [anchor], "engine": "llm", "dispatch": True,
    })["run"]["id"]
    assert ws.agents.wait(rid, timeout=8)["status"] == "done"
    for _ in range(100):
        with ws.lock:
            batch = ws.framework.run(rid)["data"]["recognition_batch"]
        if batch["ended"]:
            break
        time.sleep(0.05)
    assert batch["ended"] and batch["saved"] == 1
    item = next(i for i in ws.recognition.items(art["id"]) if i["anchor"] == anchor)
    assert item["text"] == "a+b=c" and item["part"] == "latex"


# ---------- 设计稿 05 §9：MinerU 作为 PDF 抽取方式、按文字层核对、缓存按档位、自动启动 ----------
def txt_middle(extra_blocks=()):
    m = middle([{"type": "text", "bbox": [0.118, 0.3, 0.7, 0.33], "content": [
        {"type": "text", "content": "Words that the text layer never contained at all"}]}, *extra_blocks])
    m["extensions"] = {"mineru": {"tier": "basic", "parse_mode": "txt"}}
    return m


def test_mineru_extraction_takes_engine_segments_when_uncited(ws, human, ai, files, fake_mineru):
    """D-15 至 D-17：抽取方式选 MinerU，原件还没被引用，登记后采用引擎分段；能在文字层里对上的块是解析文字层档，
    对不上的和公式是 OCR 档；之后内置重新抽取不覆盖引擎分段的页。"""
    server = fake_mineru(txt_middle())
    configure(ws, human, server.url, **{"extraction.pdf": "mineru", "models.layout_auto": "off"})
    assert ws.models.status()["segment_by_engine"]
    art = register(ws, ai, files("m.pdf", math_pdf(FORMULA_PAGE)))
    job = next(j for j in ws.models.status()["jobs"] if j["artifact_id"] == art["id"])
    done = ws.models.wait(job["id"])
    assert done["status"] == "done" and done["result"]["mode"] == "replace", done
    assert done["result"]["requested_mode"] == "segment" and done["result"]["parsed_blocks"] == 1
    a = ws.artifacts._artifact(art["id"])
    unit = ws.extraction.units(a)[0]
    assert unit["method"] == "tool:mineru@4.1.7" and unit["fidelity"] == "ocr"
    segs = ws.extraction.segments(a)
    prose = next(s for s in segs if s["text"].startswith("Prose line"))
    assert prose["fidelity"] == "parsed"
    assert next(s for s in segs if s["text"].startswith("Words that"))["fidelity"] == "ocr"
    assert next(s for s in segs if "gamma" in s["text"])["fidelity"] == "ocr"
    ws.artifacts.read(ai, art["id"], prose["anchor"])
    j = ws.judgments.write(ai, kind="conclusion", text="方法的说明", cites=[f"{art['id']}#{prose['anchor']}"])
    assert "LOW_FIDELITY_CITATION" not in j["warning_codes"]  # 取自文字层的块不提示
    ws.extraction.auto(human, art["id"], reason="重新抽取")
    assert ws.extraction.units(ws.artifacts._artifact(art["id"]))[0]["method"] == "tool:mineru@4.1.7"


def test_mineru_extraction_only_adds_formulas_when_cited(ws, human, ai, files, fake_mineru):
    """D-16：已被引用的原件不换分段，只补公式，并说明原因。"""
    server = fake_mineru(txt_middle())
    art = register(ws, ai, files("c.pdf", math_pdf(FORMULA_PAGE)))
    anchor, _ = formula_anchor(ws, art["id"])
    ws.artifacts.read(ai, art["id"], anchor)
    ws.judgments.write(ai, kind="conclusion", text="式 (1)", cites=[f"{art['id']}#{anchor}"])
    assert ws.extraction.is_cited(art["id"])
    configure(ws, human, server.url, **{"extraction.pdf": "mineru"})
    out = ws.models.wait(ws.models.run_layout(human, art["id"])["id"])
    assert out["result"]["mode"] == "formulas" and "已被判断引用" in out["result"]["note"]
    unit = ws.extraction.units(ws.artifacts._artifact(art["id"]))[0]
    assert unit["method"] != "tool:mineru@4.1.7" and unit["fidelity"] == "parsed"


def test_layout_cache_follows_tier(ws, human, ai, files, fake_mineru):
    """D-18：缓存记下档位；档位改了就重新调用并覆盖；fresh 时不用缓存。"""
    server = fake_mineru(middle())
    configure(ws, human, server.url, **{"models.layout_tier": "basic", "models.layout_auto": "off"})
    art = register(ws, ai, files("t.pdf", math_pdf(FORMULA_PAGE)))

    def posts():
        return [c for c in server.calls if c[0] == "POST"]
    ws.models.wait(ws.models.run_layout(human, art["id"])["id"])
    ws.models.wait(ws.models.run_layout(human, art["id"])["id"])
    assert len(posts()) == 1
    configure(ws, human, server.url, **{"models.layout_tier": "flash"})
    ws.models.wait(ws.models.run_layout(human, art["id"])["id"])
    assert len(posts()) == 2 and posts()[-1][2]["tier"] == "flash"
    cached = json.loads(ws.models._cache_path(ws.artifacts._artifact(art["id"])).read_text(encoding="utf-8"))
    assert cached["tier"] == "flash"
    ws.models.wait(ws.models.run_layout(human, art["id"], fresh=True)["id"])
    assert len(posts()) == 3


def test_recognition_state_is_a_note_mark_and_clears_pending(ws, human, ai, files, fake_mineru, monkeypatch):
    """设计稿 04 D-26、设计稿 10 D-14：AI 引用人未确认的识别，说明里带 recognition_unverified（出处带状态，
    读时推出）；全部 AI 核对一致的原件不再进待决策。"""

    def recog(j):
        c = ws.coordinates.of(j["id"])
        return [(v["end"], v["state"]) for m in c["notes"]["marks"] if m["mark"] == "recognition_unverified"
                for v in m["via"]]

    monkeypatch.setattr(ma, "llm_check", lambda *a: {"verdict": "confirm", "reason": "一致"})
    server = fake_mineru(txt_middle())
    configure(ws, human, server.url, **{"extraction.pdf": "mineru", "models.llm": "openai",
                                        "models.llm_url": "http://127.0.0.1:9/v1", "models.llm_model": "vlm-x"})
    art = register(ws, ai, files("d.pdf", math_pdf(FORMULA_PAGE)))
    ws.models.wait(next(j for j in ws.models.status()["jobs"] if j["artifact_id"] == art["id"])["id"])
    anchor = next(i["anchor"] for i in ws.recognition.items(art["id"]) if i["part"] == "latex")
    ref = f"{art['id']}#{anchor}"
    ws.artifacts.read(ai, art["id"], anchor)
    first = ws.judgments.write(ai, kind="conclusion", text="式 (1) 成立", cites=[ref])
    pinned = ref.replace("#", "@1#")
    assert recog(first) == [(pinned, "unchecked")]
    assert "没有任何复核" in " ".join(first["warnings"]) and "再检查" in " ".join(first["warnings"])
    assert [r["level"] for r in ws.recognition.summary() if r["artifact_id"] == art["id"]] == ["backlog"]  # 只是没核对
    ws.models.wait(ws.recognition.enqueue(human, [art["id"]])[0]["id"])
    assert all(r["artifact_id"] != art["id"] for r in ws.recognition.summary())  # 全部 AI 核对一致
    second = ws.judgments.write(ai, kind="conclusion", text="式 (1) 再次成立", cites=[ref])
    assert recog(second) == [(pinned, "ai_confirmed")] and recog(first) == [(pinned, "ai_confirmed")]  # 读时推出
    third = ws.judgments.write(ai, kind="conclusion", text="由前一条推出", cites=[second["id"]])
    assert recog(third) == []  # 只看自己的依据关系
    mine = ws.judgments.write(human, kind="conclusion", text="人自己看过", cites=[ref])
    assert recog(mine) == []
    assert not [x for x in ws.extraction.status_report()["low_fidelity_citations"] if x["judgment_id"] == second["id"]]


def test_ai_check_of_recognitions(ws, human, ai, files, fake_mineru, monkeypatch):
    """设计稿 04 D-22 至 D-25：识别结果交给大模型核对；只有人能发起；结果记为 AI，不等于人已确认。"""
    seen = []
    second_started = threading.Event()
    release = threading.Event()

    def fake_check(url, key, model, png, part, content):
        seen.append((part, png[:4]))
        if len(seen) == 2:
            second_started.set()
            assert release.wait(10)
        if part == "latex":
            return {"verdict": "reject", "reason": "图中是 g", "suggestion": "a + b = g \\tag{1}"}
        return {"verdict": "confirm", "reason": "一致"}
    monkeypatch.setattr(ma, "llm_check", fake_check)
    server = fake_mineru(txt_middle())
    configure(ws, human, server.url, **{"extraction.pdf": "mineru", "models.llm": "openai",
                                        "models.llm_url": "http://127.0.0.1:9/v1", "models.llm_model": "vlm-x"})
    art = register(ws, ai, files("r.pdf", math_pdf(FORMULA_PAGE)))
    ws.models.wait(next(j for j in ws.models.status()["jobs"] if j["artifact_id"] == art["id"])["id"])
    summary = call(Ctx(ws=ws, actor=human, channel="http"), "extraction.recognitions", {})
    row = next(r for r in summary["artifacts"] if r["artifact_id"] == art["id"])
    assert row["latex"] == 1 and row["text"] == 1 and row["unchecked"] == 2 and summary["ai_allowed"] is None
    with pytest.raises(BurrowlError):
        call(Ctx(ws=ws, actor=ai, channel="mcp"), "extraction.ai_check", {"artifact_ids": [art["id"]]})
    jobs = call(Ctx(ws=ws, actor=human, channel="http"), "extraction.ai_check", {"artifact_ids": [art["id"]]})["jobs"]
    try:
        assert second_started.wait(10)
        progress = ws.models.job(jobs[0]["id"])["progress"]
        assert progress["total"] == 2 and progress["checked"] == 1 and progress["anchor"]
        with ws.lock:
            assert sum(bool(i.get("ai")) for i in ws.recognition.items(art["id"])) == 1
        assert ws.recognition.enqueue(human, [art["id"]])[0]["id"] == jobs[0]["id"]
    finally:
        release.set()
    done = ws.models.wait(jobs[0]["id"])
    assert done["status"] == "done" and done["result"]["confirm"] == 1 and done["result"]["reject"] == 1, done
    assert {p for p, _ in seen} == {"text", "latex"} and all(h == b"\x89PNG" for _, h in seen)
    items = ws.recognition.items(art["id"])
    latex = next(i for i in items if i["part"] == "latex")
    assert latex["ai"]["verdict"] == "reject" and latex["ai"]["suggestion"].startswith("a + b = g")
    assert all(not s["verified"] for s in ws.extraction.segments(ws.artifacts._artifact(art["id"])))
    hist = ws.reviews.history(art["id"])
    assert any(h.get("anchor") == latex["anchor"] and h["method"] == "ai" for h in hist["items"])
    again = ws.models.wait(ws.recognition.enqueue(human, [art["id"]])[0]["id"])  # 核对过的不重复核对
    assert again["result"]["checked"] == 0
    def fail_check(*args):
        raise BurrowlError("MODEL_ERROR", "模拟连接失败")

    monkeypatch.setattr(ma, "llm_check", fail_check)
    retry_args = {"artifact_ids": [art["id"]], "repeat": True}
    human_ctx = Ctx(ws=ws, actor=human, channel="http")
    retry = call(human_ctx, "extraction.ai_check", retry_args)["jobs"][0]
    failed = ws.models.wait(retry["id"])
    assert failed["result"]["unsure"] == failed["progress"]["failed"] == 2
    assert failed["progress"]["last_error"] == "模拟连接失败"
    monkeypatch.setattr(ma, "llm_check", fake_check)
    retry = call(human_ctx, "extraction.ai_check", retry_args)["jobs"][0]
    assert ws.models.wait(retry["id"])["result"]["checked"] == 2
    latest = next(i for i in ws.recognition.items(art["id"]) if i["part"] == "latex")
    assert latest["ai"]["verdict"] == "reject" and latest["ai"]["review_id"] != latex["ai"]["review_id"]
    assert len([r for r in ws.reviews.history(art["id"])["items"] if r.get("part") == "latex"]) == 3

    waiting = threading.Event()
    release_last = threading.Event()
    calls = []

    def cancel_check(*args):
        calls.append(args[4])
        if len(calls) == 2:
            waiting.set()
            assert release_last.wait(10)
        return {"verdict": "confirm"}

    monkeypatch.setattr(ma, "llm_check", cancel_check)
    running = call(human_ctx, "extraction.ai_check", retry_args)["jobs"][0]["id"]
    try:
        assert waiting.wait(10)
        queued = ws.recognition.enqueue(human, [art["id"]], anchors=[latex["anchor"]])[0]["id"]
        assert call(human_ctx, "models.cancel", {"job_id": queued})["status"] == "cancelled"
        assert call(human_ctx, "models.cancel", {"job_id": running})["status"] == "cancelling"
    finally:
        release_last.set()
    stopped = ws.models.wait(running, timeout=10)
    assert stopped["status"] == "cancelled" and stopped["progress"]["checked"] == 1
    assert ws.models.wait(queued, timeout=10)["status"] == "cancelled" and len(calls) == 2
    assert len([r for r in ws.reviews.history(art["id"])["items"] if r["method"] == "ai"]) == 7

    call(Ctx(ws=ws, actor=human, channel="http"), "settings.set", {"values": {"review.ai": "off"}})
    with pytest.raises(BurrowlError) as e:
        ws.recognition.enqueue(human, [art["id"]])
    assert e.value.code == "REVIEW_DISABLED"


def test_launcher_starts_on_demand_and_stops(ws, human, ai, files, monkeypatch):
    """D-19 至 D-21：连不上时按设置的命令启动；测试连接启动的随后关闭；任务用完、空闲后关闭；命令找不到时提示安装。"""
    import os
    import socket
    import sys
    import time as _time

    from burrowl.services import model_launch as ml

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    started, killed = [], []

    def spawn(self):
        started.append(FakeMinerU(middle(), port=port))
        self._own_pid = os.getpid()
        self._write_record({"pid": os.getpid(), "owner_pid": os.getpid(), "command": ["fake"],
                            "started_at": _time.time(), "last_used": _time.time()})
        return os.getpid()
    monkeypatch.setattr(ml.Launcher, "_spawn", spawn)
    monkeypatch.setattr(ml, "_kill_tree", lambda pid: killed.append(pid) or started[-1].close())
    url = f"http://127.0.0.1:{port}"
    configure(ws, human, url, **{"models.layout_launch": "auto", "models.layout_cmd": "no-such-mineru-cmd",
                                 "models.layout_auto": "off"})
    with pytest.raises(BurrowlError) as e:
        ws.models.check("layout")
    assert e.value.code == "MODEL_NOT_INSTALLED"
    configure(ws, human, url, **{"models.layout_cmd": sys.executable})
    assert ws.models.check("layout")["starting"]
    end = _time.monotonic() + 20
    while ws.models.status()["check"].get("state") != "done" and _time.monotonic() < end:
        _time.sleep(0.1)
    check = ws.models.status()["check"]
    assert check["ok"] and check["started"] and killed, check  # 这次测试启动的，测完关闭
    art = register(ws, ai, files("l.pdf", math_pdf(FORMULA_PAGE)))
    done = ws.models.wait(ws.models.run_layout(human, art["id"])["id"])
    assert done["status"] == "done" and len(started) == 2
    assert ws.models.launch.owns() and not ws.models.launch.maybe_stop_idle()  # 刚用过，不关
    rec = ws.models.launch.record()
    rec["last_used"] -= ml.IDLE_SECONDS + 1
    ws.models.launch._write_record(rec)
    assert ws.models.launch.maybe_stop_idle() and len(killed) == 2
    with pytest.raises(BurrowlError):  # 启动命令只有人能改
        call(Ctx(ws=ws, actor=ai, channel="mcp"), "settings.set", {"values": {"models.layout_cmd": "evil"}})


def test_human_verifies_single_block(ws, human, ai, files, fake_mineru, monkeypatch):
    """设计稿 04 D-27：人可以只确认一块（如一条公式），同页其他块仍未确认；AI 不能确认。"""
    server = fake_mineru(txt_middle())
    configure(ws, human, server.url, **{"extraction.pdf": "mineru"})
    art = register(ws, ai, files("b.pdf", math_pdf(FORMULA_PAGE)))
    ws.models.wait(next(j for j in ws.models.status()["jobs"] if j["artifact_id"] == art["id"])["id"])
    items = ws.recognition.items(art["id"])
    latex = next(i for i in items if i["part"] == "latex")
    with pytest.raises(BurrowlError):
        ws.extraction.verify(ai, art["id"], anchors=[latex["anchor"]])
    out = ws.extraction.verify(human, art["id"], anchors=[latex["anchor"]], note="人工核对")
    assert out["blocks"] and out["verified"] == []
    after = ws.recognition.items(art["id"])
    assert all(i["anchor"] != latex["anchor"] for i in after) and len(after) == len(items) - 1
    segs = {s["anchor"]: s["verified"] for s in ws.extraction.segments(ws.artifacts._artifact(art["id"]))}
    assert segs[latex["anchor"]] and not all(segs.values())
    assert ws.extraction.verify(human, art["id"], anchors=[latex["anchor"]])["blocks"] == []  # 重复确认不再写
    hist = ws.reviews.history(art["id"])["items"]
    assert any(h["type"] == "verification" and h["can_revoke"] for h in hist)
