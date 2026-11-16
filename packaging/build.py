"""构建 Windows 离线安装包：dist/burrowl-<版本>-win64.zip（+ .sha256）。布局与旧版相同（DESIGN §8）。

包内容（解压即用，不需要联网、不需要系统 Python）：
    python/            独立 CPython（取自 uv 管理的解释器），已装好全部依赖与 burrowl 本身（含工作台前端）
    skills/  docs/     Skill 与文档
    models/            （仅完整包）向量与重排模型 + models-pack.json（逐文件 SHA256）
    burrowl.cmd        启动器
    burrowl.ico        开始菜单快捷方式的图标
    setup.cmd / setup.ps1   安装到上次的安装根目录（或 -Root 指定），可切换和回滚
    VERSION、BUILD_INFO.json

产物（程序与模型分开，大模型没变时升级只需下载程序更新包）：
    burrowl-<版本>-win64.zip              程序更新包：不含模型，安装时保留已有模型
    burrowl-<版本>-win64-full.zip         完整离线包：程序 + 模型（--models 时生成）
    burrowl-models-<pack>-win64.zip       模型包：只更新模型用（--models-pack 时生成）

用法：uv run python packaging/build.py [--skip-frontend] [--models <模型目录>] [--models-pack]
      uv run python packaging/build.py --install [--root <安装根目录>] [--models <模型目录>]
          构建后直接安装，不生成 zip
"""
import argparse
import hashlib
import json
import os
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
MODELS_SPEC = ROOT / "packaging" / "models.json"


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


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def default_models_dir() -> Path | None:
    """--models 省略值：BURROWL_MODELS_DIR，否则 BURROWL_ROOT/models。没有就返回 None。"""
    if os.environ.get("BURROWL_MODELS_DIR"):
        return Path(os.environ["BURROWL_MODELS_DIR"])
    if os.environ.get("BURROWL_ROOT"):
        return Path(os.environ["BURROWL_ROOT"]) / "models"
    return None


def build_models_pack(source: Path, dest: Path) -> dict:
    """按 models.json 把模型文件复制到 dest（成为包里的 models/），写 models-pack.json 与 README.txt。
    只复制清单里列出的文件；缺一个就报错，不悄悄少带。返回 models-pack.json 的内容。"""
    spec = json.loads(MODELS_SPEC.read_text(encoding="utf-8"))
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    manifest = {"schema_version": 1, "pack": spec["pack"], "models": {}}
    lines = [f"burrowl 模型包 {spec['pack']}", "",
             "这些模型随 burrowl 完整包提供，工作台在本机用 ONNX Runtime 加载，运行时不联网。", ""]
    for name, info in spec["models"].items():
        files = {}
        for rel in info["files"]:
            src = source / name / rel
            if not src.is_file():
                raise SystemExit(f"模型文件缺失：{src}（模型目录 {source}）")
            target = dest / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            files[rel] = file_sha256(target)
        manifest["models"][name] = {"model": info["model"], "license": info["license"], "files": files}
        lines += [f"{name}/", f"  模型：{info['model']}（{info['license']}）", f"  来源：{info['source']}",
                  f"  用途：{info['use']}", ""]
    (dest / "models-pack.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dest / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def write_zip(archive: Path, entries: list[tuple[Path, Path]], *, level: int = 6) -> None:
    """entries：（磁盘文件, 包内路径）。写 .zip 与 .zip.sha256。"""
    DIST.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        for path, arcname in entries:
            zf.write(path, arcname)
    digest = file_sha256(archive)
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"built {archive} ({archive.stat().st_size / 1e6:.0f} MB) sha256={digest}")


def tree_entries(base: Path, prefix: Path) -> list[tuple[Path, Path]]:
    return [(p, prefix / p.relative_to(base)) for p in sorted(base.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts]


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
    parser.add_argument("--models", type=Path, nargs="?", const=Path(), metavar="DIR",
                        help="含模型的目录（packaging/models.json 列出的各模型文件夹）；给出后另生成完整离线包。"
                             "不带路径时取 BURROWL_MODELS_DIR 或 BURROWL_ROOT/models")
    parser.add_argument("--models-pack", action="store_true", help="同时生成只含模型的模型包（需要 --models）")
    options = parser.parse_args(argv)
    ver = version()
    models_src = None
    if options.models is not None:
        models_src = options.models if str(options.models) != "." else default_models_dir()
        if models_src is None or not models_src.is_dir():
            raise SystemExit(f"找不到模型目录：{models_src}；用 --models <目录> 指定")
    if options.models_pack and models_src is None:
        raise SystemExit("--models-pack 需要同时给出 --models")
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

    models_stage = None
    if models_src is not None:
        models_stage = BUILD / "models"
        manifest = build_models_pack(models_src, models_stage)
        print(f"模型包 {manifest['pack']}：{', '.join(manifest['models'])}")

    if options.install:
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(stage / "setup.ps1")]
        if models_stage is not None:
            args += ["-Models", str(models_stage)]
        if options.root:
            # 指定根目录多用于试装：不改用户 PATH、BURROWL_ROOT 与开始菜单快捷方式（它们指向正式安装）
            args += ["-Root", str(options.root.resolve()), "-NoPath", "-NoShortcut"]
        print(run(*args, cwd=stage))
        return

    prefix = Path(f"burrowl-{ver}")
    app_entries = tree_entries(stage, prefix)
    write_zip(DIST / f"burrowl-{ver}-win64.zip", app_entries)  # 程序更新包：不含模型
    if models_stage is not None:
        pack = json.loads((models_stage / "models-pack.json").read_text(encoding="utf-8"))["pack"]
        model_entries = tree_entries(models_stage, prefix / "models")
        write_zip(DIST / f"burrowl-{ver}-win64-full.zip", app_entries + model_entries, level=3)
        if options.models_pack:
            tools = [(stage / n, Path(f"burrowl-models-{pack}") / n) for n in ("setup.cmd", "setup.ps1")]
            write_zip(DIST / f"burrowl-models-{pack}-win64.zip",
                      tools + tree_entries(models_stage, Path(f"burrowl-models-{pack}") / "models"), level=3)

if __name__ == "__main__":
    main()
