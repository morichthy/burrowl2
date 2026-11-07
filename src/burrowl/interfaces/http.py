"""工作台 HTTP 服务：只监听 127.0.0.1，所有 /api 请求需要 token（沿用 burrowl）。

    GET  /api/ops                 操作列表（名称、effect、说明、参数 schema）
    POST /api/ops/{name}          调用操作，请求体为参数对象
    GET  /api/agent/{run}/stream  agent 输出的 SSE 流
    GET  /api/artifact/{id}/file  原件文件（PDF、图片、文本、音视频内联显示，其余下载；设计稿 01 D-07）
    GET  /api/artifact/{id}/page/{n}.png   PDF 原页或 PPTX / DOCX 快照的第 n 页图像
    GET  /api/artifact/{id}/blob/{sha256}  原件里嵌入的图片
浏览器的 <img>、<video>、<iframe> 不能带请求头，所以这几个地址也接受 ?token=。
    GET  /                        工作台前端（web/ 下的构建产物）
每个请求用 ?db= 或请求头 x-burrowl-data 选数据目录（名称），不带时用默认数据目录（D-18）。
调用者身份是人（取所选数据目录配置的 human_id），会话为本次服务进程。
"""
import asyncio
import json
import secrets
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from ..core.actor import Actor
from ..core.errors import HTTP_STATUS, BurrowlError
from ..core.ids import new_id
from ..services import extractors
from ..services.workspace import Workspace
from .pool import WorkspacePool
from .registry import Ctx, call, load


def state_path() -> Path:
    """工作台是整个安装共用的一个进程（D-18），端口、token、进程号存在安装根目录的 server.json。"""
    from .install import install_root  # noqa: PLC0415
    return install_root() / "server.json"


def server_state() -> dict:
    """端口与 token 第一次启动时选定，以后网址不变。

    2.0.0a7 及以前每个数据目录各有一个工作台，状态存在数据目录的 server.json；
    第一次读时沿用默认数据目录那份的端口和 token，原来收藏的网址继续可用。
    """
    path = state_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    state = _legacy_state() or {"port": _free_port(), "token": secrets.token_urlsafe(24)}
    state = {"port": state["port"], "token": state["token"]}
    write_state(state)
    return state


def _legacy_state() -> dict | None:
    from .install import default_workspace  # noqa: PLC0415
    root = default_workspace()
    try:
        old = json.loads((root / "server.json").read_text(encoding="utf-8")) if root else None
        return old if old and old.get("port") and old.get("token") else None
    except (OSError, ValueError):
        return None


def write_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(path)


def port_free(port: int) -> bool:
    import socket  # noqa: PLC0415
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _free_port(start: int = 8766, tries: int = 40) -> int:
    for port in range(start, start + tries):
        if port_free(port):
            return port
    return start


def settle_port() -> tuple[dict, str | None]:
    """启动前确认端口：被其他程序占用时换一个并写回 server.json；返回 (state, 换端口的原因)。"""
    state = server_state()
    if port_free(state["port"]):
        return state, None
    reason = f"端口 {state['port']} 已被其他程序占用"
    state = {**state, "port": _free_port()}
    write_state(state)
    return state, reason


def create_app(pool: WorkspacePool | Workspace, token: str) -> FastAPI:
    """pool 可以直接给一个 Workspace（测试、单目录），等同于只连它的 WorkspacePool。"""
    pool = WorkspacePool.of(pool)
    app = FastAPI(title="burrowl", docs_url=None, redoc_url=None)
    app.state.pool = pool
    session = new_id("ses")
    web = Path(str(files("burrowl") / "web"))

    def workspace(request: Request) -> Workspace:
        """本次请求的数据目录：请求头 x-burrowl-data 或 ?db=（名称），都没有时是默认目录。"""
        return pool.resolve(request.headers.get("x-burrowl-data") or request.query_params.get("db"))

    def actor(ws: Workspace, request: Request) -> Actor:
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
        try:
            ws = await asyncio.to_thread(workspace, request)
            ctx = Ctx(ws=ws, actor=actor(ws, request), channel="http")
            result = await asyncio.to_thread(call, ctx, name, arguments)
        except BurrowlError as exc:
            return JSONResponse({"ok": False, **exc.problem()}, status_code=HTTP_STATUS.get(exc.code, 400))
        return {"ok": True, "result": result}

    @app.get("/api/agent/{run_id}/stream")
    async def stream(run_id: str, request: Request):
        try:
            ws = workspace(request)
        except BurrowlError as exc:
            return JSONResponse({"ok": False, **exc.problem()}, status_code=HTTP_STATUS.get(exc.code, 400))

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

    def problem(exc: BurrowlError) -> JSONResponse:
        return JSONResponse({"ok": False, **exc.problem()}, status_code=HTTP_STATUS.get(exc.code, 400))

    INLINE = ("application/pdf", "image/", "text/", "video/", "audio/", "application/json")

    @app.get("/api/artifact/{artifact_id}/file")
    def artifact_file(artifact_id: str, request: Request, download: bool = False):
        try:
            ws = workspace(request)
            with ws.lock:
                art = ws.artifacts._artifact(artifact_id)
                path = ws.artifacts.file_path(art)
        except BurrowlError as exc:
            return problem(exc)
        media = extractors.media_type_of(art)
        if media.startswith("text/") or media == "application/json":
            media += "; charset=utf-8"
        name = art["data"].get("filename") or f"{artifact_id}.txt"
        inline = not download and media.startswith(INLINE)
        # 原件不可变：同一 ID 的内容永远相同，可以长期缓存
        return FileResponse(path, media_type=media, filename=name,
                            content_disposition_type="inline" if inline else "attachment",
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/api/artifact/{artifact_id}/page/{page}.png")
    async def artifact_page(artifact_id: str, page: int, request: Request, scale: float = 1.5, source: str = "auto"):
        try:
            ws = workspace(request)
            def render() -> bytes:
                with ws.lock:
                    return ws.extraction.page_image(artifact_id, page, source=source, scale=scale)
            png = await asyncio.to_thread(render)
        except BurrowlError as exc:
            return problem(exc)
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/artifact/{artifact_id}/blob/{sha}")
    def artifact_blob(artifact_id: str, sha: str, request: Request, mime: str = "image/png"):
        try:
            ws = workspace(request)
            with ws.lock:
                owned = ws.extraction.owns_blob(artifact_id, sha)
            if not owned or not ws.blobs.has(sha):
                raise BurrowlError("NOT_FOUND", "这份原件里没有这个嵌入文件", {"sha256": sha})
        except BurrowlError as exc:
            return problem(exc)
        if not mime.startswith(("image/", "video/", "audio/", "application/pdf")):
            mime = "application/octet-stream"
        return FileResponse(ws.blobs.path(sha), media_type=mime,
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

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
