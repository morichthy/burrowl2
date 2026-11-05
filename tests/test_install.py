"""全局安装相关：Skill 安装与旧版文件的替换、数据目录登记、旧数据目录保护、旧版 MCP 登记参数兼容。"""
import hashlib
import json
import subprocess
import sys

import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces import install
from burrowl.interfaces.runtime import data_dir
from burrowl.services.workspace import Workspace


@pytest.fixture
def root(tmp_path, monkeypatch):
    home = tmp_path / "root" / "versions" / "2.0.0a1"
    home.mkdir(parents=True)
    monkeypatch.setenv("BURROWL_HOME", str(home))
    monkeypatch.delenv("BURROWL_DATA", raising=False)
    return tmp_path / "root"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_install_root_from_launcher(root):
    assert install.install_root() == root


def test_skills_replace_old_unmodified_files_only(root, tmp_path):
    target = tmp_path / "skills"
    old_rules, old_recording, user_work = b"old rules", b"old recording", b"user edited work skill"
    (target / "burrowl-work").mkdir(parents=True)
    (target / "rules.md").write_bytes(old_rules)
    (target / "recording.md").write_bytes(old_recording)
    (target / "burrowl-work" / "skill.md").write_bytes(user_work)
    key = lambda p: str((target / p).resolve()).lower()  # noqa: E731 - 旧版记录的键是小写全路径
    (root / "burrowl-install.json").write_text(json.dumps({
        "skill_dirs": {str(target.resolve()): {"dev": False}},
        "skill_files": {key("rules.md"): _sha(old_rules), key("recording.md"): _sha(old_recording),
                        key("burrowl-work/skill.md"): _sha(b"original work skill")}}), encoding="utf-8")
    result = install.upgrade_skills()[0]
    assert (target / "rules.md").read_text(encoding="utf-8").startswith("# burrowl 公共规则")
    assert not (target / "recording.md").exists()                         # 旧版独有且没改过：删除
    assert (target / "burrowl-work" / "skill.md").read_bytes() == user_work  # 用户改过：保留
    assert any("burrowl-work" in k for k in result["kept_modified"])
    assert (target / "burrowl-read" / "SKILL.md").exists()


def test_data_dir_registry_and_errors(root, tmp_path):
    with pytest.raises(BurrowlError) as e:
        data_dir()
    assert e.value.code == "NO_DATA_DIR"
    install.register_workspace(tmp_path / "d1")
    assert data_dir() == (tmp_path / "d1").resolve()
    assert (root / "workspaces-v2.json").exists() and not (root / "workspaces.json").exists()


def test_old_data_dir_is_refused(tmp_path):
    old = tmp_path / "old"
    (old / ".burrowl").mkdir(parents=True)
    with pytest.raises(BurrowlError) as e:
        Workspace(old)
    assert e.value.code == "OLD_FORMAT"
    assert not (old / "ledger.sqlite").exists()  # 没有在旧目录里建新库


def test_cli_accepts_old_mcp_registration_args(tmp_path):
    """旧版客户端登记的是 `python -m burrowl.interfaces.cli mcp --data-dir X --mode auto`。"""
    out = subprocess.run([sys.executable, "-m", "burrowl.interfaces.cli", "mcp", "--help"],
                         capture_output=True, text=True, encoding="utf-8", env={"PYTHONUTF8": "1", **_env()})
    assert out.returncode == 0 and "--data-dir" in out.stdout and "--mode" in out.stdout


def _env():
    import os  # noqa: PLC0415
    return dict(os.environ)


def test_install_root_without_launcher(tmp_path, monkeypatch):
    """MCP 登记直接用安装包的 python.exe，不经启动器、没有 BURROWL_HOME；仍要找到安装根目录（H-14）。"""
    monkeypatch.delenv("BURROWL_HOME", raising=False)
    pkg = tmp_path / "root" / "versions" / "2.0.0a9" / "python" / "Lib" / "site-packages" / "burrowl" / "interfaces"
    pkg.mkdir(parents=True)
    monkeypatch.setattr(install, "__file__", str(pkg / "install.py"))
    assert install.install_root() == tmp_path / "root"
