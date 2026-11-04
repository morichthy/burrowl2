"""命令行入口 `burrowl`。

数据目录：--data（兼容旧写法 --data-dir）→ 环境变量 BURROWL_DATA → 已登记的默认数据目录（burrowl init）。

    burrowl init <目录>                 建立数据目录并登记为默认
    burrowl start | stop | restart | status | open   后台运行工作台 / 停止 / 重启 / 状态 / 打开浏览器
    burrowl serve [--port P]            前台运行工作台
    burrowl mcp                         stdio MCP 服务，供 agent 客户端拉起
    burrowl mcp-config                  输出标准的 MCP stdio 配置
    burrowl call OP [JSON]              调用任意操作，例如 burrowl call search '{"query":"压力"}'
    burrowl ops                         列出操作
    burrowl skills install <目录>       把 Skill 装到 agent 客户端的 Skill 目录
    burrowl upgrade                     刷新所有装过 Skill 的目录（安装脚本切换版本后自动调用）
    burrowl version                     版本与自检
"""
import json
import sys
from pathlib import Path

import typer

from .. import FORMAT_VERSION, __version__
from ..core.errors import BurrowlError
from ..services.workspace import Workspace
from . import install
from .registry import Ctx, call, load
from .runtime import actor_for, data_dir

app = typer.Typer(add_completion=False, no_args_is_help=True, help="burrowl：AI 原生的研发记录与记忆")
skills_app = typer.Typer(help="Skill 安装")
app.add_typer(skills_app, name="skills")
DATA = typer.Option(None, "--data", "--data-dir", help="数据目录（默认 BURROWL_DATA 或 burrowl init 登记的默认目录）")


def _print(value) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _workspace(data: str | None) -> Workspace:
    try:
        return Workspace(data_dir(data))
    except BurrowlError as exc:
        _print({"ok": False, **exc.problem()})
        raise typer.Exit(2) from exc


@app.command("init")
def init_cmd(path: Path, make_default: bool = typer.Option(True, help="登记为默认数据目录")):
    """建立数据目录并登记。"""
    ws = _workspace(str(path))
    state = install.register_workspace(ws.root, make_default)
    _print({"data": str(ws.root), "default": state["default"]})


@app.command("call")
def call_cmd(name: str, arguments: str = typer.Argument("{}", help="JSON 参数对象"), data: str | None = DATA):
    """调用一个操作。"""
    ws = _workspace(data)
    ctx = Ctx(ws=ws, actor=actor_for("cli", ws.config.get("human_id", "human:cli")), channel="cli")
    try:
        _print(call(ctx, name, json.loads(arguments)))
    except BurrowlError as exc:
        _print({"ok": False, **exc.problem()})
        raise typer.Exit(2) from exc
    except json.JSONDecodeError as exc:
        _print({"ok": False, "code": "INVALID_ARGUMENT", "message": f"参数不是合法 JSON：{exc}"})
        raise typer.Exit(2) from exc


@app.command("ops")
def ops_cmd():
    """列出全部操作及其 effect。"""
    for spec in load().values():
        sys.stdout.write(f"{spec.name:22} {spec.effect:6} {spec.summary}\n")


@app.command("mcp")
def mcp_cmd(data: str | None = DATA, mode: str | None = typer.Option(None, "--mode", help="兼容旧版登记的参数，忽略")):
    """以 stdio 运行 MCP 服务。"""
    from .mcp import run_stdio  # noqa: PLC0415 - 只在需要时加载 MCP SDK
    run_stdio(_workspace(data))


@app.command("mcp-config")
def mcp_config_cmd(data: str | None = DATA):
    """输出标准的 MCP stdio 服务配置，由 agent 客户端按自己的规范登记。"""
    _print({"mcpServers": {"burrowl": {
        "command": sys.executable,
        "args": ["-m", "burrowl.interfaces.cli", "mcp", "--data", str(data_dir(data).resolve())],
        "env": {"PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1"}}}})


@app.command("serve")
def serve_cmd(data: str | None = DATA, port: int | None = typer.Option(None, help="端口；默认沿用上次")):
    """前台运行工作台。"""
    import os  # noqa: PLC0415

    import uvicorn  # noqa: PLC0415

    from .http import create_app, server_state  # noqa: PLC0415
    ws = _workspace(data)
    state = server_state(ws)
    port = port or state["port"]
    (ws.root / "server.json").write_text(json.dumps({**state, "port": port, "pid": os.getpid()}), encoding="utf-8")
    sys.stdout.write(f"工作台：http://127.0.0.1:{port}/?token={state['token']}\n")
    sys.stdout.flush()
    uvicorn.run(create_app(ws, state["token"]), host="127.0.0.1", port=port, log_level="warning")


@app.command("start")
def start_cmd(data: str | None = DATA):
    """在后台启动工作台。"""
    from . import server  # noqa: PLC0415
    _print(server.start(_workspace(data)))


@app.command("stop")
def stop_cmd(data: str | None = DATA):
    """停止后台工作台。"""
    from . import server  # noqa: PLC0415
    _print(server.stop(_workspace(data)))


@app.command("restart")
def restart_cmd(data: str | None = DATA):
    """重启后台工作台（升级后让新代码生效）。"""
    from . import server  # noqa: PLC0415
    ws = _workspace(data)
    server.stop(ws)
    _print(server.start(ws))


@app.command("status")
def status_cmd(data: str | None = DATA):
    """工作台是否在运行，以及网址。"""
    from . import server  # noqa: PLC0415
    from .http import server_state  # noqa: PLC0415
    ws = _workspace(data)
    _print({"data": str(ws.root), "running": server.running(ws), "url": server.url(server_state(ws))})


@app.command("open")
def open_cmd(data: str | None = DATA):
    """打开工作台（没在运行就先在后台启动）。"""
    from . import server  # noqa: PLC0415
    _print(server.open_workbench(_workspace(data)))


@skills_app.command("install")
def skills_install_cmd(target: Path):
    """把 Skill 装到指定目录（如 ~/.claude/skills）。只替换本程序写过、用户没改过的文件。"""
    _print(install.install_skills(target))


@app.command("upgrade")
def upgrade_cmd():
    """刷新安装记录中所有 Skill 目录。"""
    _print(install.upgrade_skills())


@app.command("version")
def version_cmd():
    """版本、数据格式版本与自检。"""
    load()
    _print({"version": __version__, "format_version": FORMAT_VERSION, "install_root": str(install.install_root()),
            "default_data": str(install.default_workspace() or ""), "ops": len(load())})


def main() -> None:
    app()


if __name__ == "__main__":  # 旧版 MCP 登记用 `python -m burrowl.interfaces.cli`
    main()
