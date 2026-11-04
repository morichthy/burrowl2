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


def start(ws: Workspace) -> dict:
    state = server_state(ws)
    if running(ws):
        return {"running": True, "url": url(state), "already": True}
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    exe = str(windowless if windowless.exists() else python)
    log = (ws.root / "serve.log").open("ab")
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen([exe, "-m", "burrowl", "serve", "--data", str(ws.root)], stdout=log, stderr=log,
                            stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True,
                            env={**os.environ, "PYTHONUTF8": "1"})
    for _ in range(60):
        if running(ws):
            return {"running": True, "url": url(state), "pid": proc.pid}
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
