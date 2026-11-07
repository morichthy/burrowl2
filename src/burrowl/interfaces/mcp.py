"""MCP 服务（stdio）：把 effect 为 read / write 的操作暴露为工具；user 与 admin 操作不出现在工具列表中。

工具名把点换成下划线（judgment.write → judgment_write）。调用者身份一律是 AI。
连接哪个数据目录（D-18）：登记时带 --data 就固定连它；不带时每次调用都取登记表里当前的默认数据目录，
在工作台改了默认，下一次调用就跟着变，不用重启客户端。
"""
import base64
import inspect
import json
from typing import Any

import anyio
from anyio import to_thread
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image

from ..core.errors import BurrowlError
from ..services.workspace import Workspace
from .pool import WorkspacePool
from .registry import Ctx, OpSpec, call, load
from .runtime import actor_for

INSTRUCTIONS = """burrowl 是 AI 原生的研发记录与记忆工作区，内容分三列：
原件（原文如实，可作依据）、判断（当时谁依据什么认为了什么，可作依据）、框架（实体页、综合页、关系图，可再生，永远不能作依据）。
- 对设备或对象动手前先调用 constraints_check；操作与测量用 capture_log 记录，条件只记当下能确定的。
- 读原件用 artifact_read，它会留下读取记录；判断用 judgment_write，cites 优先填原件段落（artifact_read 返回的 cite_as，
  如 art_…#p3-2），也可以填原件、事实记录或判断的 ID。未读先引会得到 UNREAD_CITATION 提示。
- PDF、PPTX、DOCX 登记时自动抽取文字；图片、扫描页、视频默认不抽取：用 artifact_view 看图，识别后用
  artifact_extract（method=ai，写明 model）提交。OCR / AI 识别的段落未经人确认，引用前对照原件复核。
- 判断类型只有三种：conclusion 结论、process 过程（提问、尝试、停下的路线；不能作为结论的依据）、normative 规定。
- 写入时可信度由系统推出，你不能声明；你不能更正或撤回判断，认为不对时写 opposes 关系的新判断。
- 当前连接的数据目录见 system_status 的 data / data_name。
- 检索用 search；结果带地位坐标，被替代的排在最后。探索新路线时用 mode=explore，默认不返回框架页和过程内容。
- 框架页用 page_write 写，并给出 inputs；输入变化后页面会标为 inputs_changed，需要重新综合。
"""


def visible_ops() -> list[OpSpec]:
    return [s for s in load().values() if s.effect in ("read", "write")]


def _tool(pool: WorkspacePool, spec: OpSpec):
    params = list(inspect.signature(spec.fn).parameters.values())[1:]

    def invoke(kwargs: dict) -> Any:
        ctx = Ctx(ws=pool.resolve(), actor=actor_for("mcp"), channel="mcp")
        return call(ctx, spec.name, kwargs)

    async def tool(**kwargs: Any) -> Any:
        try:
            result = await to_thread.run_sync(lambda: invoke(kwargs))
        except BurrowlError as exc:
            raise ToolError(json.dumps(exc.problem(), ensure_ascii=False)) from exc
        image = result.pop("_image", None) if isinstance(result, dict) else None
        if image:  # artifact_view：把图像作为图片内容交给模型，而不是一长串 base64 文本
            return [json.dumps(result, ensure_ascii=False),
                    Image(data=base64.b64decode(image["base64"]), format=image["mime"].split("/")[1])]
        return json.dumps(result, ensure_ascii=False)

    tool.__signature__ = inspect.Signature(params, return_annotation=str)
    tool.__annotations__ = {p.name: p.annotation for p in params} | {"return": str}
    tool.__name__ = spec.tool_name
    tool.__doc__ = spec.summary
    return tool


def build_server(target: Workspace | WorkspacePool) -> MCPServer:
    pool = WorkspacePool.of(target)
    server = MCPServer(name="burrowl", instructions=INSTRUCTIONS)
    for spec in visible_ops():
        server.add_tool(_tool(pool, spec), name=spec.tool_name, description=spec.summary, structured_output=False)
    return server


def run_stdio(target: Workspace | WorkspacePool) -> None:
    anyio.run(build_server(target).run_stdio_async)
