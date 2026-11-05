"""工作台后台运行：start / stop / status / open（沿用旧版的使用方式）。

进程号写在数据目录的 server.json（与端口、token 同一文件）。判断是否在运行用一次带 token 的 HTTP 请求，
不用 os.kill(pid, 0)：Windows 上它会直接结束进程。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from ..services.workspace import Workspace
from .http import server_state


def url(state: dict) -> str:
    return f"http://127.0.0.1:{state['port']}/?token={state['token']}"


def running(ws: Workspace) -> bool:
    state = server_state(ws)
    req = urllib.request.Request(f"http://127.0.0.1:{state['port']}/api/ops",
                                 headers={"x-burrowl-token": state["token"]})
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except OSError:
        return False


def _spawn_serve(ws: Workspace, *, wait: bool) -> subprocess.Popen:
    """在后台启动 `serve`，不弹出命令行窗口。

    用 pythonw.exe（无控制台的解释器）直接启动，不经过 burrowl.cmd：cmd.exe 是控制台程序，
    经它启动会弹出一个窗口，而且关掉窗口服务也跟着结束。
    安装后优先用 current 联接下的解释器，这样重启后加载的是新安装的版本；
    同时补上 burrowl.cmd 原本设置的环境变量。
    """
    from .install import install_root  # noqa: PLC0415
    env = {**os.environ, "PYTHONUTF8": "1"}
    current = install_root() / "current"
    bundled = current / "python"
    if os.environ.get("BURROWL_HOME") and (bundled / "python.exe").exists():
        python = bundled / "python.exe"
        env.update(BURROWL_HOME=str(current) + os.sep, BURROWL_LAUNCHER=str(current / "burrowl.cmd"),
                   PYTHONNOUSERSITE="1")
    else:  # 开发环境
        python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    exe = str(windowless if windowless.exists() else python)
    command = [exe, "-m", "burrowl.interfaces.cli", "serve", "--data", str(ws.root)] + (["--wait"] if wait else [])
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    log = (ws.root / "serve.log").open("ab")
    return subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags,
                            close_fds=True, env=env)


def start(ws: Workspace) -> dict:
    state = server_state(ws)
    if running(ws):
        return {"running": True, "url": url(state), "already": True}
    proc = _spawn_serve(ws, wait=False)
    for _ in range(60):
        if running(ws):  # serve 可能换了端口（见 http.settle_port），所以重新读 server.json
            return {"running": True, "url": url(server_state(ws)), "pid": proc.pid}
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    return {"running": False, "log": str(ws.root / "serve.log")}


def stop(ws: Workspace) -> dict:
    state = server_state(ws)
    pid = state.get("pid")
    if not pid or not running(ws):
        return {"stopped": False, "reason": "工作台没有在运行"}
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, 15)
    state.pop("pid", None)
    (ws.root / "server.json").write_text(json.dumps(state), encoding="utf-8")
    return {"stopped": True}


def open_workbench(ws: Workspace) -> dict:
    result = start(ws)
    if result.get("running"):
        webbrowser.open(result["url"])
    return result


# ---------- 在工作台进程内部控制自己（工作台首页的"重启服务""停止服务"） ----------
def info(ws: Workspace) -> dict:
    """运行版本与已安装版本：安装了新版本但还没重启时 update_pending 为真。不返回 token。"""
    from .. import __version__  # noqa: PLC0415
    from .install import install_root  # noqa: PLC0415
    state = server_state(ws)
    current = install_root() / "current.txt"
    installed = current.read_text(encoding="utf-8").strip() if current.exists() else None
    return {"version": __version__, "installed_version": installed,
            "update_pending": bool(installed and installed != __version__),
            "pid": os.getpid(), "started_at": state.get("started_at"), "port": state.get("port"),
            "executable": Path(sys.executable).name, "log": str(ws.root / "serve.log"), "data": str(ws.root)}


def _exit_soon(delay: float = 0.8) -> None:
    """先让本次 HTTP 响应发出去，再结束进程。"""
    import threading  # noqa: PLC0415
    threading.Timer(delay, lambda: os._exit(0)).start()


def restart_self(ws: Workspace) -> dict:
    """启动一个新进程，等本进程释放端口后接管同一网址；随后本进程退出。新进程加载的是 current 指向的新版本。"""
    state = server_state(ws)
    _spawn_serve(ws, wait=True)
    _exit_soon()
    return {"restarting": True, "started_before": state.get("started_at")}


def stop_self() -> dict:
    _exit_soon()
    return {"stopping": True}


def wait_port_free(port: int, timeout: float = 60) -> None:
    import socket  # noqa: PLC0415
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.3)
