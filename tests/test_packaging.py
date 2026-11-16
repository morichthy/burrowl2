"""模型与程序分开打包（2.4.3）：模型包清单、完整包与更新包的边界、安装时按文件核对模型。"""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"


@pytest.fixture
def build(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("burrowl_build", PACKAGING / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fake = tmp_path / "models.json"
    fake.write_text(json.dumps({"pack": 7, "models": {
        "alpha": {"model": "x/alpha", "license": "Apache-2.0", "source": "https://example.test/alpha",
                  "use": "测试", "files": ["config.json", "onnx/model.onnx"]},
    }}), encoding="utf-8")
    monkeypatch.setattr(mod, "MODELS_SPEC", fake)
    return mod


def make_source(base: Path, payload: bytes = b"weights-v1") -> Path:
    (base / "alpha" / "onnx").mkdir(parents=True)
    (base / "alpha" / "config.json").write_text("{}", encoding="utf-8")
    (base / "alpha" / "onnx" / "model.onnx").write_bytes(payload)
    (base / "alpha" / "unlisted.bin").write_bytes(b"not in the pack")
    (base / "other-model").mkdir()
    return base


def test_pack_lists_only_declared_files_with_sha256(build, tmp_path):
    src = make_source(tmp_path / "src")
    manifest = build.build_models_pack(src, tmp_path / "out")
    assert manifest["pack"] == 7
    files = manifest["models"]["alpha"]["files"]
    assert set(files) == {"config.json", "onnx/model.onnx"}
    assert files["onnx/model.onnx"] == hashlib.sha256(b"weights-v1").hexdigest()
    assert not (tmp_path / "out" / "alpha" / "unlisted.bin").exists()
    assert not (tmp_path / "out" / "other-model").exists()
    assert (tmp_path / "out" / "README.txt").read_text(encoding="utf-8").count("x/alpha") == 1


def test_missing_declared_file_is_an_error_not_a_smaller_pack(build, tmp_path):
    src = make_source(tmp_path / "src")
    (src / "alpha" / "onnx" / "model.onnx").unlink()
    with pytest.raises(SystemExit, match="模型文件缺失"):
        build.build_models_pack(src, tmp_path / "out")


def test_app_zip_has_no_models_and_full_zip_has_them(build, tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    app = tmp_path / "stage"
    app.mkdir()
    (app / "VERSION").write_text("9.9.9", encoding="utf-8")
    build.build_models_pack(make_source(tmp_path / "src"), tmp_path / "models")
    entries = build.tree_entries(app, Path("burrowl-9.9.9"))
    build.write_zip(tmp_path / "dist" / "app.zip", entries)
    build.write_zip(tmp_path / "dist" / "full.zip",
                    entries + build.tree_entries(tmp_path / "models", Path("burrowl-9.9.9") / "models"))
    import zipfile
    assert not [n for n in zipfile.ZipFile(tmp_path / "dist" / "app.zip").namelist() if "models" in n]
    full = zipfile.ZipFile(tmp_path / "dist" / "full.zip").namelist()
    assert "burrowl-9.9.9/models/models-pack.json" in full and "burrowl-9.9.9/models/alpha/onnx/model.onnx" in full
    assert (tmp_path / "dist" / "app.zip.sha256").read_text(encoding="utf-8").endswith("  app.zip\n")


@pytest.mark.skipif(sys.platform != "win32", reason="安装脚本是 PowerShell，只在 Windows 上运行")
def test_setup_syncs_models_by_file_hash(build, tmp_path):
    """-ModelsOnly：缺的复制；相同的不碰（时间不变）；不同的才覆盖；包里没有的模型目录不动。"""
    pack = tmp_path / "pack" / "models"
    build.build_models_pack(make_source(tmp_path / "src"), pack)
    script = tmp_path / "setup.ps1"  # 带 BOM，PowerShell 5.1 才按 UTF-8 读中文
    script.write_bytes(b"\xef\xbb\xbf" + (PACKAGING / "setup.ps1").read_text(encoding="utf-8-sig").encode("utf-8"))
    root = tmp_path / "root"
    (root / "models" / "someone-elses-model").mkdir(parents=True)
    (root / "models" / "someone-elses-model" / "w.onnx").write_bytes(b"keep")

    def run():
        done = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                               "-Root", str(root), "-ModelsOnly", "-Models", str(pack)],
                              capture_output=True, text=True, encoding="utf-8")
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout

    onnx = root / "models" / "alpha" / "onnx" / "model.onnx"
    assert "复制 2 个文件" in run() and onnx.read_bytes() == b"weights-v1"
    stamp = onnx.stat().st_mtime_ns
    assert "复制 0 个文件，已是最新 2 个" in run() and onnx.stat().st_mtime_ns == stamp

    onnx.write_bytes(b"damaged")  # 目标被改坏：核对不同，重新复制
    assert "复制 1 个文件" in run() and onnx.read_bytes() == b"weights-v1"
    assert (root / "models" / "someone-elses-model" / "w.onnx").read_bytes() == b"keep"
    assert not list((root / "models").rglob("*.part"))
    assert json.loads((root / "models" / "models-pack.json").read_text(encoding="utf-8"))["pack"] == 7
