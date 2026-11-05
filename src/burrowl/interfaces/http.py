"""工作台 HTTP 服务：只监听 127.0.0.1，所有 /api 请求需要 token（沿用 burrowl）。

    GET  /api/ops                 操作列表（名称、effect、说明、参数 schema）
    POST /api/ops/{name}          调用操作，请求体为参数对象
    GET  /api/agent/{run}/stream  agent 输出的 SSE 流
    GET  /                        工作台前端（web/ 下的构建产物）
调用者身份是人（配置 human_id），会话为本次服务进程。
"""
import asyncio
import json
import secrets
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ..core.actor import Actor
from ..core.errors import HTTP_STATUS, BurrowlError
from ..core.ids import new_id
from ..services.workspace import Workspace
from .registry import Ctx, call, load


def server_state(ws: Workspace) -> dict:
    """端口与 token 第一次启动时选定并存入数据目录，以后网址不变。"""
    path = ws.root / "server.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    state = {"port": _free_port(avoid=claimed_ports(ws)), "token": secrets.token_urlsafe(24)}
    path.write_text(json.dumps(state), encoding="utf-8")
    return state


def claimed_ports(ws: Workspace) -> dict[int, str]:
    """其他已登记数据目录记下的端口 → 数据目录。即使那个工作台此刻没运行，也不能分给别人（H-12）。"""
    from .install import registry  # noqa: PLC0415
    out: dict[int, str] = {}
    for root in registry().get("workspaces", []):
        other = Path(root)
        if other.resolve() == ws.root:
            continue
        try:
            out[int(json.loads((other / "server.json").read_text(encoding="utf-8"))["port"])] = str(other)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def port_free(port: int) -> bool:
    import socket  # noqa: PLC0415
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _free_port(start: int = 8766, tries: int = 40, avoid: dict[int, str] | None = None) -> int:
    """从 8766 起找一个没被占用、也没被其他数据目录记下的端口：多个数据目录的工作台可以同时运行。"""
    for port in range(start, start + tries):
        if port not in (avoid or {}) and port_free(port):
            return port
    return start


def settle_port(ws: Workspace) -> tuple[dict, str | None]:
    """启动前确认端口：被其他进程占用，或与默认数据目录以外的另一个数据目录撞号时，换一个端口并写回 server.json。

    默认数据目录保留自己的端口（它的网址最常用，开始菜单快捷方式也指向它）；返回 (state, 换端口的原因)。
    """
    from .install import registry  # noqa: PLC0415
    state = server_state(ws)
    claimed = claimed_ports(ws)
    reason = None
    default = registry().get("default")
    is_default = bool(default) and Path(default).resolve() == ws.root
    if state["port"] in claimed and not is_default:
        reason = f"端口 {state['port']} 已记给数据目录 {claimed[state['port']]}"
    elif not port_free(state["port"]):
        reason = f"端口 {state['port']} 已被其他程序占用"
    if reason:
        state = {**state, "port": _free_port(avoid=claimed)}
        (ws.root / "server.json").write_text(json.dumps(state), encoding="utf-8")
    return state, reason


def create_app(ws: Workspace, token: str) -> FastAPI:
    app = FastAPI(title="burrowl", docs_url=None, redoc_url=None)
    session = new_id("ses")
    web = Path(str(files("burrowl") / "web"))

    def actor(request: Request) -> Actor:
        return Actor(ws.config.get("human_id", "human:workbench"), "human",
                     request.headers.get("x-burrowl-session") or session)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            given = request.headers.get("x-burrowl-token") or request.query_params.get("token")
            if not given or not secrets.compare_digest(given, token):
                return JSONResponse({"code": "FORBIDDEN", "message": "缺少或错误的 token"}, status_code=403)
        return await call_next(request)

    @app.get("/api/ops")
    def ops():
        return [{"name": s.name, "effect": s.effect, "summary": s.summary, "schema": s.schema()}
                for s in load().values()]

    @app.post("/api/ops/{name}")
    async def invoke(name: str, request: Request):
        body = await request.body()
        arguments = json.loads(body) if body else {}
        ctx = Ctx(ws=ws, actor=actor(request), channel="http")
        try:
            result = await asyncio.to_thread(call, ctx, name, arguments)
        except BurrowlError as exc:
            return JSONResponse({"ok": False, **exc.problem()}, status_code=HTTP_STATUS.get(exc.code, 400))
        return {"ok": True, "result": result}

    @app.get("/api/agent/{run_id}/stream")
    async def stream(run_id: str):
        async def events():
            offset = 0
            while True:
                chunk = await asyncio.to_thread(ws.agents.output, run_id, offset)
                for line in chunk["lines"]:
                    yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
                offset = chunk["offset"]
                if not chunk["running"]:
                    yield f"event: end\ndata: {json.dumps(chunk['run'], ensure_ascii=False)}\n\n"
                    return
                await asyncio.sleep(0.3)
        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/{path:path}")
    def static(path: str):
        target = (web / path).resolve()
        if path and target.is_file() and web.resolve() in target.parents:
            return FileResponse(target)
        index = web / "index.html"
        if index.exists():
            # index.html 不缓存：升级或重启后浏览器直接拿到新前端；其余文件名带内容哈希，可以长期缓存
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"message": "前端尚未构建：npm --prefix frontend run build"}, status_code=404)

    return app
