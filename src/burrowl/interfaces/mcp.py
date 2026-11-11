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
- 日常工程、科研及其他重要或经常性工作，只收录有核对、决策或复用价值的材料、实际过程和判断。
  例行操作和临时对话留在运行记录。
- 巡检会话不能写判断。巡检员交发现，复核员可附依据提出修改意见，由人确认写入。
- 对设备或对象动手前先调用 constraints_check；值得留存的操作与测量用 capture_log 记录，条件只记当下能确定的；
  用到的文件写 inputs，产出的文件登记时用 produced_by 指向这条日志。
- 读原件用 artifact_read，它会留下读取记录；判断用 judgment_write，cites 优先填原件段落（artifact_read 返回的 cite_as，
  如 art_…#p3-2），也可以填原件、事实记录或判断的 ID。未读先引会得到 UNREAD_CITATION 提示；
  引用已由人退役的原件（含经读取记录、事实记录间接引用）会得到 RETIRED_CITATION 提示，请改引替代它的原件；
  引用依据已变化、尚未复核的判断会得到 RECHECK_CITATION 提示，请回到原件核对。
  引用人未确认的 OCR / AI 识别段落会得到 LOW_FIDELITY_CITATION 提示，写入成功但判断可信度降级；
  关键公式请对照原图二次检查。
- PDF、PPTX、DOCX、Excel 登记时自动抽取文字；图片、扫描页、视频默认不抽取：用 artifact_view 看图，识别后用
  artifact_extract（method=ai，写明 model）提交。OCR / AI 识别的段落未经人确认，引用前对照原件复核。
- PDF 的行间公式是 formula 块，抽出的字符不是公式结构：用 artifact_view（anchor=段落锚点）看公式裁切图，
  识别后用 artifact_extract 的 blocks=[{anchor, latex}] 补充 LaTeX（不改段落文字与锚点）。
- 判断类型只有三种：conclusion 结论、process 过程（提问、尝试、停下的路线；不能作为结论的依据）、normative 规定。
- 外部材料（文献、厂商资料、网页，source_class=external）登记后要消化：按 Skill burrowl-work 的「消化外部材料」，
  把材料自己的发现写成结论并填 external_author，conditions 只写原文给出的条件（没说明的写"原文未说明：…"），
  每份写完调用 digest_submit；digest_list 列出待消化的材料。
- 按地位使用判断：依据只有外部报告或推断（status_note 写"文献论断"或"推断"）而结论要用于动手、决策或作新结论的
  依据时，先用 artifact_read 回原文核对条件；文献条件常不全。要只看本地实证时 search 用 source=local。
- 写入时可信度由系统推出，你不能声明；你不能更正或撤回判断，有值得留存的异议时写 opposes 关系的新判断。
- 当前连接的数据目录见 system_status 的 data / data_name。
- 检索用 search；结果带地位坐标，被替代的排在最后，已退役的原件默认不返回（include_retired=true 时排在最后）。
  探索新路线时用 mode=explore，默认不返回框架页和过程内容。
- 框架页用 page_write 写，并给出 inputs；输入变化后页面会标为 inputs_changed，需要重新综合。
- 定期巡检：收到“用 inspection_get 领取巡检包 insp_…”时，按 Skill burrowl-inspect 逐个任务读原件、
  用 inspection_submit 提交；
  复核员对巡检发现用 review_ai_submit（item_id 写发现的待决策编号 dec_…），确认前必须自己读过发现引用的段落。
  巡检发现不能作为依据。
- 配置了本地版面引擎（MinerU）时，PDF 的公式块会带 LaTeX（来源 tool:mineru@版本，OCR 档、未经人确认）；
  需要时可以用 artifact_layout_engine 让它处理一份 PDF，用 artifact_recognize_formula（engine=model）识别单个公式。
- AI 复核用 review_ai_submit：只对照原件层、判断层（本会话读过的原件段落、事实记录、判断，不能是框架页或边），
  不复核本会话自己写的条目，拿不准就交 unsure。结果记为"AI 已复核"，不等于人已复核；需要人看的用 review_request。
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
