"""构建 Windows 离线安装包：dist/burrowl-<版本>-win64.zip（+ .sha256）。布局与旧版相同（DESIGN §8）。

包内容（解压即用，不需要联网、不需要系统 Python）：
    python/            独立 CPython（取自 uv 管理的解释器），已装好全部依赖与 burrowl 本身（含工作台前端）
    skills/  docs/     Skill 与文档
    burrowl.cmd        启动器
    burrowl.ico        开始菜单快捷方式的图标
    setup.cmd / setup.ps1   安装到上次的安装根目录（或 -Root 指定），可切换和回滚
    VERSION、BUILD_INFO.json

用法：uv run python packaging/build.py [--skip-frontend]
      uv run python packaging/build.py --install [--root <安装根目录>]   构建后直接安装，不生成 zip
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
PY_VERSION = "3.12"


def run(*args: str, cwd: Path = ROOT) -> str:
    print("$", " ".join(args))
    done = subprocess.run(args, cwd=cwd, text=True, capture_output=True, encoding="utf-8")
    if done.returncode:
        raise SystemExit(f"命令失败（{done.returncode}）：{' '.join(args)}\n"
                         f"{done.stdout[-3000:]}\n{done.stderr[-3000:]}")
    return done.stdout


def version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def standalone_python() -> Path:
    """uv 管理的解释器就是 python-build-standalone 构建；取最新的 3.12.x，没有就让 uv 下载。"""
    def candidates() -> list[Path]:
        base = Path(run("uv", "python", "dir").strip())
        found = [p for p in base.glob(f"cpython-{PY_VERSION}.*-windows-x86_64-none") if (p / "python.exe").is_file()]
        return sorted(found, key=lambda p: tuple(int(x) for x in p.name.split("-")[1].split(".")))
    if not candidates():
        run("uv", "python", "install", PY_VERSION)
    return candidates()[-1]


def build_info(ver: str) -> dict:
    commit = dirty = None
    try:
        commit = run("git", "rev-parse", "HEAD").strip()
        dirty = bool(run("git", "status", "--porcelain").strip())
    except (OSError, SystemExit):
        print("构建来源没有可用的 Git 信息，BUILD_INFO.json 中留空。")
    return {"version": ver, "git_commit": commit, "git_dirty": dirty,
            "built_at": datetime.now(UTC).isoformat(timespec="seconds")}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-frontend", action="store_true", help="使用已有的前端构建产物")
    parser.add_argument("--install", action="store_true", help="构建后直接安装到本机，不生成 zip")
    parser.add_argument("--root", type=Path, help="安装根目录（仅 --install）；省略时用上次的位置")
    options = parser.parse_args(argv)
    ver = version()
    stage = BUILD / f"burrowl-{ver}"
    if not stage.resolve().is_relative_to(BUILD.resolve()) or stage.resolve() == BUILD.resolve():
        raise SystemExit(f"拒绝清理构建目录以外的路径：{stage}")
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)

    # 1. 前端先构建：产物在 src/burrowl/web/，随 wheel 进入包内
    if not options.skip_frontend:
        run("npm.cmd" if sys.platform == "win32" else "npm", "run", "build", cwd=ROOT / "frontend")
    if not (ROOT / "src/burrowl/web/index.html").exists():
        raise SystemExit("缺少前端构建产物：npm --prefix frontend run build")

    # 2. 独立解释器 + 依赖 + 本包
    shutil.copytree(standalone_python(), stage / "python", ignore=shutil.ignore_patterns("__pycache__"))
    (stage / "python/Lib/EXTERNALLY-MANAGED").unlink(missing_ok=True)
    python = stage / "python/python.exe"
    wheels = BUILD / "wheels"
    shutil.rmtree(wheels, ignore_errors=True)
    run("uv", "build", "--wheel", "--out-dir", str(wheels))
    requirements = BUILD / "requirements.txt"
    run("uv", "export", "--no-dev", "--no-emit-project", "--no-hashes", "--format", "requirements-txt",
        "--output-file", str(requirements))
    run("uv", "pip", "install", "--python", str(python), "--quiet", "-r", str(requirements),
        *map(str, sorted(wheels.glob("*.whl"))))
    run(str(python), "-c", "import burrowl.interfaces.cli, burrowl.interfaces.mcp, importlib.resources as r;"
        "assert (r.files('burrowl') / 'web' / 'index.html').is_file()")

    # 3. Skill、文档、启动器与安装脚本
    shutil.copytree(ROOT / "skills", stage / "skills")
    shutil.copytree(ROOT / "docs", stage / "docs")
    shutil.copy2(ROOT / "README.md", stage / "README.md")
    shutil.copy2(ROOT / "packaging/burrowl.ico", stage / "burrowl.ico")
    # Windows 脚本统一 CRLF；.cmd 必须是纯 ASCII；.ps1 加 BOM（PowerShell 5.1 才按 UTF-8 读）
    for name in ("burrowl.cmd", "setup.cmd", "setup.ps1"):
        text = (ROOT / "packaging" / name).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\n", "\r\n")
        data = text.encode("ascii") if name.endswith(".cmd") else b"\xef\xbb\xbf" + text.encode("utf-8")
        (stage / name).write_bytes(data)
    (stage / "VERSION").write_text(ver, encoding="utf-8")
    (stage / "BUILD_INFO.json").write_text(json.dumps(build_info(ver), ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    run(str(stage / "burrowl.cmd"), "version", cwd=stage)  # 包内自检

    if options.install:
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(stage / "setup.ps1")]
        if options.root:
            # 指定根目录多用于试装：不改用户 PATH、BURROWL_ROOT 与开始菜单快捷方式（它们指向正式安装）
            args += ["-Root", str(options.root.resolve()), "-NoPath", "-NoShortcut"]
        print(run(*args, cwd=stage))
        return

    DIST.mkdir(exist_ok=True)
    archive = DIST / f"burrowl-{ver}-win64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(stage.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, Path(f"burrowl-{ver}") / path.relative_to(stage))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"built {archive} ({archive.stat().st_size / 1e6:.0f} MB) sha256={digest}")


if __name__ == "__main__":
    main()
