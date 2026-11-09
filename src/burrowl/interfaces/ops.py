"""内置操作。函数的第一行说明会成为 MCP 工具描述和命令行帮助，所以写给使用者看。"""
from typing import Annotated, Any

from pydantic import Field

from .. import __version__
from ..core.errors import BurrowlError
from .registry import Ctx, op

IdList = list[str] | None


# ---------- 系统 ----------
@op("system.status")
def system_status(ctx: Ctx) -> dict:
    """工作区概况：各类条目数量、待决策数、输入已变化的框架页数，以及当前调用者身份。"""
    ws = ctx.ws
    count = lambda conn, table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: E731
    return {
        "version": __version__, "data": str(ws.root), "data_name": _name_of(ws.root),
        "actor": {"id": ctx.actor.id, "kind": ctx.actor.kind, "session": ctx.actor.session_id},
        "ledger": {t: count(ws.ledger_db, t) for t in ("artifacts", "events", "records", "reads", "judgments", "links")},
        "framework": {t: count(ws.framework_db, t) for t in ("entities", "pages", "edges")},
        "open_decisions": len(ws.framework.decisions("open")),
        "inputs_changed": len(ws.framework.pages(freshness="inputs_changed")),
    }


def _name_of(root) -> str | None:
    from .install import name_of  # noqa: PLC0415
    return name_of(root)


# ---------- 数据目录（一个工作台管理多个数据目录，D-18） ----------
@op("workspace.list")
def workspace_list(ctx: Ctx) -> dict:
    """已登记的数据目录（名称、路径、是否默认），以及本次调用连接的是哪一个。"""
    from . import install  # noqa: PLC0415
    return {"current": _name_of(ctx.ws.root), "current_path": str(ctx.ws.root),
            "items": install.workspaces()}


@op("workspace.add", effect="user")
def workspace_add(ctx: Ctx, path: Annotated[str, Field(description="数据目录的绝对路径")],
                  name: Annotated[str | None, Field(description="显示名称（用在网址 ?db= 里）；默认取目录名")] = None,
                  make_default: bool = False,
                  create: Annotated[bool, Field(description="目录里还没有 burrowl 数据时是否新建")] = False) -> dict:
    """登记一个数据目录；目录还不是 burrowl 数据目录时，需要 create=true 才新建。"""
    from pathlib import Path  # noqa: PLC0415

    from ..services.workspace import Workspace  # noqa: PLC0415
    from . import install  # noqa: PLC0415
    ctx.actor.require_human("登记数据目录")
    root = Path(path).expanduser()
    if not root.is_absolute():
        raise BurrowlError("INVALID_ARGUMENT", "请填写绝对路径")
    if not (root / "ledger.sqlite").exists() and not create:
        raise BurrowlError("NOT_FOUND", "这个目录里还没有 burrowl 数据；要新建请勾选“新建”", {"path": str(root)})
    Workspace(root).close()  # 打开一次：新建目录结构，旧版数据目录会在这里被拒绝
    install.register_workspace(root, make_default, name)
    return workspace_list(ctx)


@op("workspace.set_default", effect="user")
def workspace_set_default(ctx: Ctx, name: Annotated[str, Field(description="数据目录名称或路径")]) -> dict:
    """设为默认数据目录：工作台不带 ?db= 时打开它，不带 --data 的 MCP 与命令行也连接它。"""
    from . import install  # noqa: PLC0415
    ctx.actor.require_human("设置默认数据目录")
    install.set_default_workspace(name)
    return workspace_list(ctx)


@op("workspace.remove", effect="user")
def workspace_remove(ctx: Ctx, name: Annotated[str, Field(description="数据目录名称或路径")]) -> dict:
    """从登记表移除一个数据目录（不删除目录里的任何数据，之后可以重新登记）。默认目录不能移除。"""
    from . import install  # noqa: PLC0415
    ctx.actor.require_human("移除数据目录")
    install.unregister_workspace(name)
    return workspace_list(ctx)


# ---------- 过程捕获与原件 ----------
@op("capture.log", effect="write")
def capture_log(ctx: Ctx, op_name: Annotated[str, Field(description="操作名，如 exec.shell、measure.pressure")],
                input: dict | None = None, output: str | None = None, conditions: dict | None = None,
                objects: IdList = None,
                source_class: Annotated[str, Field(description="local 本地实证（默认）/ inferred 推断（如对话消息）")] = "local",
                inputs: Annotated[list[str] | None, Field(description="这次操作用到的原件 art_…（脚本、输入数据）")] = None,
                outputs: Annotated[list[str] | None, Field(description="这次操作产出的原件 art_…（结果文件）；也可在登记时用 produced_by")] = None) -> dict:
    """记录有核对或复用价值的实际过程（只追加）。动手前先调用 constraints_check，事后不能补写条件。"""
    ctx.ws.inspection.guard_original_write(ctx.actor)
    return ctx.ws.capture.log(ctx.actor, op_name, input=input, output=output, conditions=conditions,
                              objects=objects, source_class=source_class, inputs=inputs, outputs=outputs)


@op("artifact.register", effect="write")
def artifact_register(ctx: Ctx, kind: Annotated[str, Field(description="file/conversation/literature/dataset/image/log")],
                      source_class: Annotated[str, Field(description="local 本地实证（本项目内执行、测量或直接观察）/ external 外部报告 / inferred 推断")],
                      path: str | None = None, text: str | None = None, title: str | None = None,
                      storage: Annotated[str, Field(description="managed 复制保存 / referenced 只登记路径和指纹")] = "managed",
                      external_tier: Annotated[str | None, Field(description="peer_reviewed/preprint/vendor/web")] = None,
                      version_of: str | None = None, metadata: dict | None = None, objects: IdList = None,
                      produced_by: Annotated[str | None, Field(description="产生这份文件的过程日志 evt_…（例如运行脚本的那一条）")] = None) -> dict:
    """登记有核对或复用价值的原件，保留原文与可核对的元数据。同内容幂等；新版本用 version_of 指向旧版本。"""
    ctx.ws.inspection.guard_original_write(ctx.actor)
    return ctx.ws.artifacts.register(ctx.actor, kind=kind, source_class=source_class, path=path, text=text,
                                     title=title, storage=storage, external_tier=external_tier,
                                     version_of=version_of, metadata=metadata, objects=objects,
                                     produced_by=produced_by)


@op("artifact.read", effect="write")
def artifact_read(ctx: Ctx, artifact_id: str,
                  locator: Annotated[str | None, Field(description="省略读全部；段落 seg-3 / p3-2；段落范围 p3-8:p3-12（检索结果的 read_as）；单元 p3；单元范围 p3:p5；旧写法 seg:N-M")] = None) -> dict:
    """读原件（当前抽取层）的一段并留下读取记录。判断引用时写返回的 cite_as（原件段落 art_…#p3-2），不必引用读取记录。
    返回 notice 时说明这些段落来自 OCR / AI 识别、尚未确认，引用前请用 artifact_view 对照原件。"""
    return ctx.ws.artifacts.read(ctx.actor, artifact_id, locator)


@op("artifact.segments")
def artifact_segments(ctx: Ctx, artifact_id: str) -> list[dict]:
    """列出原件当前抽取层的全部段落：anchor（引用写 art_…#anchor）、单元、文本、可信度档（不产生读取记录）。"""
    ctx.ws.inspection.guard_artifact(ctx.actor, artifact_id)
    return ctx.ws.artifacts.segments(artifact_id)


@op("artifact.layer")
def artifact_layer(ctx: Ctx, artifact_id: str) -> dict:
    """原件的抽取层：格式、单元清单（页、幻灯片、嵌入图片…）、每个单元的状态、方法、可信度档、是否已确认、快照。"""
    ctx.ws.inspection.guard_artifact(ctx.actor, artifact_id)
    return ctx.ws.extraction.layer(artifact_id)


@op("artifact.extract", effect="write")
def artifact_extract(ctx: Ctx, artifact_id: str,
                     method: Annotated[str, Field(description="auto 用内置抽取器（重新）抽取 PDF/PPTX/DOCX / ai 提交 AI 识别的文本 / ocr 提交 OCR 工具的结果 / manual 人工转写（只有人）")] = "auto",
                     units: Annotated[IdList, Field(description="auto 时只重新抽取这些单元（如 p3）；省略为整份")] = None,
                     content: Annotated[list[dict] | None, Field(description="ai/ocr/manual：[{unit, text}]；视频的 text 写成 \"[00:01:23] 文字\" 一行一块")] = None,
                     blocks: Annotated[list[dict] | None, Field(description="ai/ocr/manual：给公式块补充 LaTeX，[{anchor, latex}]（anchor 如 p3-4，latex 不加 $）；不改块的文字与锚点。与 content 二选一")] = None,
                     model: Annotated[str | None, Field(description="method=ai 时写明模型")] = None,
                     note: str = "") -> dict:
    """抽取或补充原件的可读文本（原件本身不变，抽取单独留痕）。图片、图片页、视频默认不抽取：先用 artifact_view 看，
    再用 method=ai 提交。文本变化后，引用了旧文本的判断进入待复核。公式块可以用 blocks 补充 LaTeX
    （先用 artifact_view 带 anchor 看公式的裁切图）。"""
    if method == "auto":
        return ctx.ws.extraction.auto(ctx.actor, artifact_id, units=units, reason=note or "重新抽取")
    if blocks:
        if content:
            raise BurrowlError("INVALID_ARGUMENT", "content 与 blocks 不能同时提交")
        return ctx.ws.extraction.submit_latex(ctx.actor, artifact_id, method=method, blocks=blocks, model=model,
                                              note=note)
    return ctx.ws.extraction.submit(ctx.actor, artifact_id, method=method, content=content or [], model=model,
                                    note=note)


@op("artifact.view")
def artifact_view(ctx: Ctx, artifact_id: str,
                  unit: Annotated[str, Field(description="单元：PDF/PPT 的页 p3、图片 img、嵌入图片 img2")] = "",
                  anchor: Annotated[str | None, Field(description="段落锚点（如 p3-4）：只看这一块在原件上的裁切图，用于识别公式")] = None) -> dict:
    """看原件某个单元的图像（PDF 页、PPT 页快照、图片），用于识别图片内容或对照原件复核抽取的文字；
    给 anchor 时只看那一段（公式块）的裁切图。"""
    if not unit and not anchor:
        raise BurrowlError("INVALID_ARGUMENT", "unit 与 anchor 至少给一个")
    ctx.ws.inspection.guard_artifact(ctx.actor, artifact_id)
    return ctx.ws.extraction.view(artifact_id, unit, anchor)


@op("artifact.snapshot", effect="write")
def artifact_snapshot(ctx: Ctx, artifact_id: str, force: bool = False) -> dict:
    """为 PPTX / DOCX / Excel 生成页面快照（用本机 Office 或 LibreOffice 转成 PDF），工作台据此显示与原件一致的版式。"""
    return ctx.ws.extraction.snapshot(ctx.actor, artifact_id, force=force)


@op("artifact.verify_extraction", effect="user")
def artifact_verify_extraction(ctx: Ctx, artifact_id: str,
                               units: Annotated[IdList, Field(description="要确认的单元；省略为全部有文本的单元")] = None,
                               note: str = "") -> dict:
    """人确认抽取的文字与原件一致（逐单元或整份）。确认只针对当前那一版抽取。"""
    return ctx.ws.extraction.verify(ctx.actor, artifact_id, units=units, note=note)


@op("artifact.extraction_history")
def artifact_extraction_history(ctx: Ctx, artifact_id: str, unit: str) -> list[dict]:
    """一个单元的全部抽取记录（新的在前）：方法、可信度档、抽取者、是否确认。"""
    return ctx.ws.extraction.history(artifact_id, unit)


@op("artifact.segment_stats")
def artifact_segment_stats(ctx: Ctx, artifact_id: str) -> dict:
    """原件每个段落被读过几次、被哪些判断引用（按结论、过程、规定分组）。"""
    return ctx.ws.retrieval.segment_stats(artifact_id)


@op("extraction.status")
def extraction_status(ctx: Ctx) -> dict:
    """抽取与引用的状态检查：未抽取或失败的原件、待抽取的图片页、未读先引、引用未确认的识别文本、待复核的判断。"""
    return ctx.ws.extraction.status_report()


@op("extraction.backfill", effect="admin")
def extraction_backfill(ctx: Ctx) -> dict:
    """给还没有抽取层的原件补上抽取（升级后执行一次）：PDF / PPTX / DOCX 自动抽取，图片与音视频登记单元。"""
    return ctx.ws.extraction.backfill(ctx.actor)


@op("record.promote", effect="write")
def record_promote(ctx: Ctx, event_id: str | None = None, artifact_id: str | None = None, locator: str | None = None,
                   objects: IdList = None, method: str | None = None, result: str | None = None,
                   boundary: str = "complete", gaps: IdList = None, conditions: dict | None = None,
                   reason: str = "",
                   cites: Annotated[list[str] | None, Field(description="方法中各个定义出自哪里：原件段落 art_…#p3-2（如脚本里定义指标的几行）、原件、过程日志、事实记录；不能是判断与框架")] = None) -> dict:
    """把过程事件或原件片段升级为事实记录：对象、条件、方法、结果（逐字）、边界。条件不能补写，缺失的写进 gaps。
    方法写到一个不知道目的的人能复现或核对：数据怎么产生、各组怎么设置、指标怎么定义，并用 cites 指向原文。"""
    ctx.ws.inspection.guard_original_write(ctx.actor)
    return ctx.ws.artifacts.promote(ctx.actor, event_id=event_id, artifact_id=artifact_id, locator=locator,
                                    objects=objects, method=method, result=result, boundary=boundary, gaps=gaps,
                                    conditions=conditions, reason=reason, cites=cites)


# ---------- 判断 ----------
@op("judgment.write", effect="write")
def judgment_write(ctx: Ctx, kind: Annotated[str, Field(description="conclusion 结论（关于对象的陈述，可作依据）/ "
                                                                     "process 过程（提问、尝试、停下的路线、目的；不能作为结论的依据）/ "
                                                                     "normative 规定（约束、决定、指令）")],
                   text: Annotated[str, Field(description="写全对象和条件，不用指代词，不写「显然」「关键在于」等措辞")],
                   cites: Annotated[IdList, Field(description="依据：原件段落 art_…#p3-2（推荐，取 artifact_read 返回的 cite_as）、原件、事实记录、读取记录或判断的 ID；不能是框架页")] = None,
                   objects: IdList = None, conditions: str | None = None,
                   relations: Annotated[list[dict] | None, Field(
                       description="与其他判断的关系 [{rel, target, condition?}]，rel 取 supports/opposes/depends_on/"
                                   "answers/targets/coexists_under")] = None,
                   external_author: Annotated[str | None, Field(description="摘录文献论断时填原作者")] = None,
                   revises: str | None = None, revise_reason: str | None = None,
                   local_observation: Annotated[bool, Field(description="人亲自看到或测到（只有人能勾选）")] = False,
                   reopen_condition: Annotated[str | None, Field(description="过程内容：停下的路线在什么条件下值得重新打开")] = None) -> dict:
    """只收录工程、科研或其他重要、经常性工作中有长期价值的判断。只追加，可信度由依据推出。巡检会话不能写判断。"""
    return ctx.ws.judgments.write(ctx.actor, kind=kind, text=text, cites=cites, objects=objects,
                                  conditions=conditions, relations=relations, external_author=external_author,
                                  revises=revises, revise_reason=revise_reason, local_observation=local_observation,
                                  reopen_condition=reopen_condition)


@op("judgment.amend", effect="user")
def judgment_amend(ctx: Ctx, mode: Annotated[str, Field(description="correction 更正 / retraction 撤回 / defect 原件有缺陷"
                                                               "（retirement 原件退役保留给旧调用，等同 artifact.retire）")],
                   target: str, reason: str, cites: IdList = None) -> dict:
    """人工修改入口：更正、撤回判断，标记原件有缺陷。底层写一条新判断指向原条目，原条目不变。"""
    return ctx.ws.judgments.amend(ctx.actor, mode=mode, target=target, reason=reason, cites=cites)


@op("artifact.retire", effect="user")
def artifact_retire(ctx: Ctx, artifact_id: str,
                    action: Annotated[str, Field(description="retire 退役 / restore 撤销退役")] = "retire",
                    reason: str = "",
                    replaced_by: Annotated[str | None, Field(description="替代它的原件（可空）")] = None) -> dict:
    """退役原件（内容没错，只是不再单独出现在列表和检索里）或撤销退役。记为原件的状态历史，不写成判断。"""
    if action == "retire":
        return ctx.ws.judgments.retire(ctx.actor, artifact_id, reason=reason, replaced_by=replaced_by)
    if action == "restore":
        return ctx.ws.judgments.restore(ctx.actor, artifact_id, reason=reason)
    raise BurrowlError("INVALID_ARGUMENT", "action 必须是 retire 或 restore", {"action": action})


@op("artifact.replace", effect="user")
def artifact_replace(ctx: Ctx, artifact_id: Annotated[str, Field(description="已退役或已删除的原件")],
                     replacement: Annotated[str, Field(description="替代它的原件 art_…")], reason: str) -> dict:
    """给已退役或已删除的原件指定替代原件。引用旧原件段落的判断按段落指纹在替代原件里比对，对不上的进入待复核；
    受影响的框架页标为"输入已变化"，由人交给 agent 重新综合（设计稿 07 D-03）。"""
    return ctx.ws.judgments.replace(ctx.actor, artifact_id, replacement=replacement, reason=reason)


@op("artifact.delete_preview")
def artifact_delete_preview(ctx: Ctx, artifact_id: str) -> dict:
    """删除一份已退役的原件会删掉什么（依据全部来自它的判断与事实记录等）、哪些条目保留并标为"所引原件已删除"、
    哪些框架页会标为输入已变化；confirm 是执行删除时要带上的核对值（设计稿 07 D-04）。"""
    return ctx.ws.purge.preview(artifact_id)


@op("artifact.delete", effect="user")
def artifact_delete(ctx: Ctx, artifact_id: str,
                    confirm: Annotated[str, Field(description="artifact.delete_preview 返回的 confirm")]) -> dict:
    """彻底删除一份已退役的原件及预览里列出的条目：不留任何记录，不能撤销（设计稿 07 D-04、D-05）。"""
    return ctx.ws.purge.delete(ctx.actor, artifact_id, confirm=confirm)


# ---------- 框架 ----------
@op("entity.upsert", effect="write")
def entity_upsert(ctx: Ctx, kind: Annotated[str, Field(description="device/system/material/person/concept/method/term")],
                  name: str, description: str | None = None) -> dict:
    """建立或取回一个实体（图的节点）。同类同名只有一个。"""
    return ctx.ws.frameworks.entity_upsert(ctx.actor, kind=kind, name=name, description=description)


@op("entity.list")
def entity_list(ctx: Ctx, kind: str | None = None) -> list[dict]:
    """列出实体。"""
    return ctx.ws.framework.entities(kind)


@op("page.write", effect="write")
def page_write(ctx: Ctx, type: Annotated[str, Field(description="entity/concept/synthesis/description")], title: str,
               body: Annotated[str, Field(description="Markdown 正文；引用写成 [[ID]]")],
               inputs: Annotated[IdList, Field(description="输入清单：所依据的原件、判断、页面版本（pg_…@N）")] = None,
               slug: str | None = None, summary: str | None = None, subject_id: str | None = None) -> dict:
    """写框架页的新版本（实体页、概念页、综合页、非文本原件的描述）。AI 写的页面进入待复核列表。"""
    return ctx.ws.frameworks.page_write(ctx.actor, type=type, title=title, body=body, inputs=inputs, slug=slug,
                                        summary=summary, subject_id=subject_id)


@op("page.get")
def page_get(ctx: Ctx, page: Annotated[str, Field(description="pg_… 或 pg_…@版本号")]) -> dict:
    """读框架页的某个版本，附输入清单和其中已被替代的输入。"""
    return ctx.ws.frameworks.page_get(page)


@op("page.list")
def page_list(ctx: Ctx, type: str | None = None, freshness: str | None = None) -> list[dict]:
    """列出框架页；freshness=inputs_changed 可列出需要重新综合的页面。"""
    return ctx.ws.framework.pages(type_=type, freshness=freshness)


@op("edge.add", effect="write")
def edge_add(ctx: Ctx, rel: Annotated[str, Field(description="may_contradict/may_supersede/similar/analogy/related")],
             src_id: str, dst_id: str, reason: str, inputs: IdList = None) -> dict:
    """在关系图中加一条 AI 推断的边（未复核）。人确认后，可能矛盾、可能替代会写回判断层。"""
    return ctx.ws.frameworks.edge_add(ctx.actor, rel=rel, src_id=src_id, dst_id=dst_id, reason=reason, inputs=inputs)


@op("edge.list")
def edge_list(ctx: Ctx, node_id: str | None = None, rel: str | None = None, review: str | None = None) -> list[dict]:
    """列出关系图的边；给 node_id 时只列与它相连的边。"""
    if node_id:
        return ctx.ws.framework.edges_of(node_id)
    return ctx.ws.framework.edges(rel=rel, review=review)


@op("framework.review", effect="user")
def framework_review(ctx: Ctx, item_id: str, verdict: Annotated[str, Field(description="confirm / reject")],
                     reason: str, cites: IdList = None) -> dict:
    """review.submit 的旧名称，参数与效果相同。"""
    return ctx.ws.reviews.submit(ctx.actor, item_id=item_id, verdict=verdict, reason=reason, cites=cites)


# ---------- 复核（设计稿 04） ----------
@op("review.submit", effect="user")
def review_submit(ctx: Ctx, item_id: Annotated[str, Field(description="框架页 pg_…、边 edg_… 或判断 jdg_…")],
                  verdict: Annotated[str, Field(description="confirm 确认（判断：依据支持它）/ reject 驳回（判断：依据不支持它）")],
                  reason: str,
                  cites: Annotated[IdList, Field(description="补充的依据：原件段落、事实记录、判断；不能是框架")] = None,
                  local_observation: Annotated[bool, Field(description="复核判断时：人亲自看到或测到")] = False) -> dict:
    """人复核一个条目。结论记为它的复核历史，不写成新判断；判断的当前地位由依据（含补充的）重新推出。"""
    return ctx.ws.reviews.submit(ctx.actor, item_id=item_id, verdict=verdict, reason=reason, cites=cites,
                                 local_observation=local_observation)


@op("review.ai_submit", effect="write")
def review_ai_submit(ctx: Ctx, item_id: Annotated[str, Field(description="AI 生成未复核的框架页 pg_… 或关联边 edg_…；"
                                                                          "设置允许时也可以是待复核的判断 jdg_…；"
                                                                          "复核员复核巡检发现时写它的待决策编号 dec_…")],
                     verdict: Annotated[str, Field(description="confirm 确认 / reject 有问题 / unsure 拿不准")],
                     reason: str,
                     model: Annotated[str, Field(description="你的模型名，如 claude-opus-5-5")],
                     cites: Annotated[IdList, Field(description="依据：本会话读过的原件段落（cite_as）、事实记录、判断；"
                                                               "不能是框架页、边、过程内容。confirm / reject 至少一条")] = None,
                     proposed_change: Annotated[str, Field(description="仅巡检复核员确认发现后填写：有复用价值、可独立理解的拟写判断")] = "") -> dict:
    """AI 复核：对照原件层、判断层核对一个条目。结果另记一档（AI 已复核），不等于人已复核；拿不准就交 unsure。"""
    return ctx.ws.reviews.ai_submit(ctx.actor, item_id=item_id, verdict=verdict, reason=reason, model=model,
                                    cites=cites, proposed_change=proposed_change)


@op("review.request", effect="write")
def review_request(ctx: Ctx, item_id: Annotated[str, Field(description="任何条目：pg_… / edg_… / jdg_… / art_…")],
                   note: Annotated[str, Field(description="一句话：要看什么")]) -> dict:
    """请人复核：把条目加入待决策列表。"""
    return ctx.ws.reviews.request(ctx.actor, item_id=item_id, note=note)


@op("review.history")
def review_history(ctx: Ctx, item_id: str) -> dict:
    """一个条目的复核与变更历史、当前复核状态，以及现在能否交给 AI 复核（巡检发现的待决策编号 dec_… 返回它的提交、复核员意见与处理）。"""
    return ctx.ws.reviews.history(item_id)


@op("review.sample")
def review_sample(ctx: Ctx) -> dict:
    """本周抽查：从 AI 生成未复核的框架页里按周固定地挑几页，供人用确认 / 驳回处理。"""
    return ctx.ws.reviews.sample()


# ---------- 术语连接与待决策 ----------
@op("term.link", effect="write")
def term_link(ctx: Ctx, term: str, source_id: str | None = None, excerpt: str | None = None,
              proposed_entity_id: str | None = None) -> dict:
    """把一个叫法连到实体：确定的直接连；只有一个候选的建未复核的边；拿不准的进入待决策列表。"""
    return ctx.ws.linking.link_term(ctx.actor, term=term, source_id=source_id, excerpt=excerpt,
                                    proposed_entity_id=proposed_entity_id)


@op("term.decide", effect="user")
def term_decide(ctx: Ctx, decision_id: str, entity_id: str | None = None, new_entity: dict | None = None,
                note: str = "") -> dict:
    """人决定术语连接：写回判断层并加入别名表。new_entity 形如 {kind, name}。"""
    return ctx.ws.linking.decide(ctx.actor, decision_id=decision_id, entity_id=entity_id, new_entity=new_entity,
                                 note=note)


@op("decision.list")
def decision_list(ctx: Ctx, status: str | None = "open", kind: str | None = None) -> list[dict]:
    """待决策列表（按影响范围排序）：术语连接、待复核、需重新综合、操作前未检查约束、传播超限。
    影响范围为 0 的是低影响项（工作台默认折叠，设计稿 04 D-07）。"""
    return ctx.ws.framework.decisions(status, kind)


@op("decision.dismiss", effect="user")
def decision_dismiss(ctx: Ctx, decision_id: str, reason: str) -> dict:
    """关闭一条待决策项，不做处理。"""
    ctx.actor.require_human("关闭待决策项")
    return ctx.ws.framework.close_decision(decision_id, "dismissed", {"reason": reason, "by": ctx.actor.id})


# ---------- 检索 ----------
@op("search")
def search(ctx: Ctx, query: str, layers: Annotated[IdList, Field(description="original/judgment/framework")] = None,
           objects: IdList = None, mode: Annotated[str, Field(description="reuse 复用 / explore 探索（不给框架页，默认也不给过程内容）")] = "reuse",
           include_log: bool = False,
           include_process: Annotated[bool | None, Field(description="是否返回过程内容；省略时复用模式返回、探索模式不返回")] = None,
           include_retired: Annotated[bool, Field(description="是否返回已退役的原件（排在最后）")] = False,
           order: Annotated[str, Field(description="relevance 按相关度（默认）/ status 按地位逐级排")] = "relevance",
           limit: Annotated[int | None, Field(description="返回几条；省略时按设置（默认 20），本次用的值见结果的 params")] = None) -> dict:
    """检索（关键词 + 向量，设置为重排时重排）。名次只表示相关度；每条带地位坐标与 status_note 说明可靠程度。
    相关的有效约束列在最前；被替代、已退役的排在当前条目之后。每条带命中的段落（cite_as、read_as）、
    未展示的命中数（more_matches）、依据（basis）和一跳关系（relations）；params 是本次用的检索参数（每条最多展示
    几个命中单元等，人在设置里调整）；hints 说明结果的局限。"""
    out = ctx.ws.retrieval.search(query, layers=layers, objects=objects, mode=mode, include_log=include_log,
                                  include_process=include_process, include_retired=include_retired,
                                  limit=limit, order=order, actor=ctx.actor)
    ctx.ws.coverage.log_search(ctx.actor, "search", query, mode, out)  # 检索命中记录（设计稿 08 D-12）
    return ctx.ws.inspection.filter_result(ctx.actor, out)


@op("search.exact")
def search_exact(ctx: Ctx, text: Annotated[str, Field(description="要逐字查找的文字（不分词，不区分大小写）")],
                 layers: Annotated[IdList, Field(description="original/judgment/framework")] = None,
                 mode: Annotated[str, Field(description="reuse / explore（探索模式不给框架页，默认也不给过程内容）")] = "reuse",
                 include_process: bool | None = None, include_retired: bool = False,
                 limit: Annotated[int | None, Field(description="最多几个条目；省略时按设置（默认 50）")] = None) -> dict:
    """字面查找：列出含有这段文字的段落（带 cite_as），按条目分组，不排序。用于设备编号、错误码、函数名、原句。"""
    out = ctx.ws.retrieval.search_exact(text, layers=layers, mode=mode, include_process=include_process,
                                        include_retired=include_retired, limit=limit)
    return ctx.ws.inspection.filter_result(ctx.actor, out)


@op("search.associate")
def search_associate(ctx: Ctx, query: Annotated[str | None, Field(description="从这次检索的前 5 条出发；与 seeds 至少给一个")] = None,
                     seeds: Annotated[IdList, Field(description="从这些条目出发（可写原件段落 art_…#p3-2）")] = None,
                     hops: Annotated[int, Field(description="走几跳：1 或 2")] = 1,
                     mode: Annotated[str, Field(description="reuse / explore（探索模式只走判断关系、引用、共享对象和向量近邻）")] = "reuse",
                     include_process: bool | None = None, include_retired: bool = False, limit: int = 20) -> dict:
    """联想：从检索命中（或给定条目）出发，顺着判断关系、引用、输入清单、实体提及、共享对象、向量近邻走 1–2 跳，
    找出检索没有命中但连着的条目。每条带经过的路径 via，标为"联想，非检索命中"；不是默认检索的一部分。"""
    out = ctx.ws.associate.run(query=query, seeds=seeds, hops=hops, mode=mode, include_process=include_process,
                               include_retired=include_retired, limit=limit, actor=ctx.actor)
    ctx.ws.coverage.log_search(ctx.actor, "search.associate", query, mode, out)
    return ctx.ws.inspection.filter_result(ctx.actor, out)


@op("entry.get")
def entry_get(ctx: Ctx, id: str) -> dict:
    """按 ID 取任意条目，附地位坐标、指出和指入的关系。"""
    ws = ctx.ws
    base = id.split("#", 1)[0].split("@", 1)[0]
    entry = ws.get(base)
    if entry is None:
        raise BurrowlError("NOT_FOUND", "条目不存在", {"id": id})
    out: dict[str, Any] = {"entry": entry, "coordinates": ws.retrieval.coordinates(base)}
    if base.split("_")[0] in ("art", "evt", "rec", "rd", "jdg", "lnk"):
        out["links_out"] = ws.ledger.links_from(base)
        out["links_in"] = ws.ledger.links_to(base)
    out["edges"] = ws.framework.edges_of(base)
    if base.startswith("art_"):
        out["outbound"] = ws.inspection.outbound(base)  # 设计稿 08 D-30
    return out


@op("entry.expand")
def entry_expand(ctx: Ctx, id: Annotated[str, Field(description="条目 ID；原件段落写成 art_…#p3-2 或 art_…#seg-N")],
                 mode: str = "reuse") -> dict:
    """展开背景：来源（原件）或条件（日志、事实记录）→ 同一来源的前后内容 → 涉及的对象 → 引用了它的判断（解读，探索模式下隐藏）。"""
    ctx.ws.inspection.guard_artifact(ctx.actor, id)
    return ctx.ws.retrieval.expand(id, mode=mode)


@op("timeline")
def timeline(ctx: Ctx, object: str) -> list[dict]:
    """按对象列出全部条目，按时间排序（历史类查询）。"""
    return ctx.ws.retrieval.timeline(object)


@op("object.view")
def object_view(ctx: Ctx, object: Annotated[str, Field(description="实体 ID（ent_…）或对象名")]) -> dict:
    """对象页：关于这个对象的全部条目，约束在前，其次有争议的结论，其余按类型和时间；不含自动日志。"""
    return ctx.ws.retrieval.object_view(object)


@op("constraints.check", effect="write")
def constraints_check(ctx: Ctx, objects: list[str]) -> dict:
    """对某对象动手前必须调用：列出与它相关的有效约束、决定和指令，并留下"已检查"的记录。"""
    return ctx.ws.retrieval.check_constraints(ctx.actor, objects)


@op("session.events")
def session_events(ctx: Ctx, session_id: str | None = None) -> list[dict]:
    """列出一个会话的过程日志（默认当前会话）。"""
    return ctx.ws.capture.session(session_id or ctx.actor.session_id)


# ---------- agent ----------
@op("agent.list")
def agent_list(ctx: Ctx) -> list[dict]:
    """列出已配置的 agent 命令，以及本机是否找得到它们。"""
    return ctx.ws.agents.agents()


@op("agent.start", effect="user")
def agent_start(ctx: Ctx, agent: str, prompt: str, cwd: str | None = None, preamble: bool = True) -> dict:
    """在本机启动一个 agent CLI 处理任务；它通过 MCP 回到本工作区读写，输出留在运行日志。"""
    return ctx.ws.agents.start(ctx.actor, agent=agent, prompt=prompt, cwd=cwd, preamble=preamble)


@op("agent.output")
def agent_output(ctx: Ctx, run_id: str, offset: int = 0) -> dict:
    """读取 agent 运行的输出（从第 offset 行开始）。"""
    return ctx.ws.agents.output(run_id, offset)


@op("agent.runs")
def agent_runs(ctx: Ctx, limit: int = 50) -> list[dict]:
    """列出最近的 agent 运行。"""
    return ctx.ws.framework.runs(limit)


@op("agent.set_command", effect="user")
def agent_set_command(ctx: Ctx, agent: str,
                      executable: Annotated[str, Field(description="可执行文件：命令名或完整路径；留空恢复默认")] = "") -> dict:
    """修改 agent 命令模板里的可执行文件，其余参数不变（设计稿 08 D-39）。命令不在 PATH 里时填完整路径。"""
    return ctx.ws.agents.set_executable(ctx.actor, agent=agent, executable=executable)


@op("agent.save_command", effect="user")
def agent_save_command(ctx: Ctx, agent: str,
                       command: Annotated[list[str], Field(description="可执行文件和逐项启动参数；参数中须有 {prompt}，可用 {mcp_config}")]) -> dict:
    """新增或编辑 agent 的完整启动命令。保存后可将其选为巡检员或复核员。"""
    return ctx.ws.agents.save_command(ctx.actor, agent=agent, command=command)


@op("agent.test", effect="user")
def agent_test(ctx: Ctx, agent: str,
               timeout: Annotated[float, Field(description="最多等几秒")] = 180) -> dict:
    """测试 agent 连接：命令能否找到、能否经 MCP 调用 burrowl、身份是否正确（设计稿 08 D-26）。会真的启动一次 agent。"""
    return ctx.ws.agents.test(ctx.actor, agent=agent, timeout=timeout)


@op("agent.cancel", effect="user")
def agent_cancel(ctx: Ctx, run_id: str) -> dict:
    """停止正在运行的 agent。"""
    return ctx.ws.agents.cancel(ctx.actor, run_id)


# ---------- 维护 ----------
@op("index.rebuild", effect="admin")
def index_rebuild(ctx: Ctx, background: Annotated[bool, Field(description="在后台重建、立即返回（工作台用）；"
                                                                    "省略时等重建完再返回（命令行用）")] = False) -> dict:
    """从账本和框架整库重建全文索引。后台重建逐条取锁、不先清空，进度见 index.health 的 units.rebuild。"""
    if background:
        return {"rebuild": ctx.ws.start_rebuild("手动重建")}
    return ctx.ws.rebuild_index()


@op("index.embed", effect="admin")
def index_embed(ctx: Ctx, limit: Annotated[int | None, Field(description="最多补几个检索单元；省略时补完")] = None) -> dict:
    """补建检索单元的向量（工作台会在后台自动补；评测和首次升级时可以用它一次补完）。"""
    return ctx.ws.vectors.build(limit=limit)


@op("data.export", effect="admin")
def data_export(ctx: Ctx, target: str) -> dict:
    """导出为 JSONL + blobs + Markdown 页面（用于备份和大版本迁移）。"""
    return ctx.ws.portability.export(target)


@op("data.import", effect="admin")
def data_import(ctx: Ctx, source: str) -> dict:
    """从导出目录导入到空的工作区。"""
    return ctx.ws.portability.import_(source)


@op("data.import_v1", effect="admin")
def data_import_v1(ctx: Ctx, source: Annotated[str, Field(description="旧版 burrowl 数据目录（含 .burrowl/）")]) -> dict:
    """从旧版 burrowl 数据目录导入到空的工作区（只读旧目录）。旧记录的完整字段保存在 data.v1 中。"""
    return ctx.ws.import_v1.run(ctx.actor, source)


# ---------- 工作台首页、条目浏览、关系图（只读汇总） ----------
@op("activity.recent")
def activity_recent(ctx: Ctx, limit: int = 40) -> list[dict]:
    """最近的关键操作：登记原件、写判断（含更正撤回与复核）、事实记录、框架页新版本、agent 运行。"""
    return ctx.ws.overview.activity(limit)


@op("artifact.check")
def artifact_check(ctx: Ctx) -> dict:
    """检查外部原件（只登记路径和指纹的那类）是否还与登记时一致：changed 内容已变化，missing 原位置找不到。
    只读文件，不写账本；发现变化后请把新文件登记为新版本（artifact_register 的 version_of）。"""
    return ctx.ws.source_check.run()


@op("artifact.check_status")
def artifact_check_status(ctx: Ctx) -> dict:
    """上次原件检查的时间与结果、有问题的原件，以及定时检查是否开启。不重新检查。"""
    return ctx.ws.source_check.status()


@op("index.health")
def index_health(ctx: Ctx) -> dict:
    """检索索引是否覆盖全部原件、事实记录、判断和框架页（缺了用 index.rebuild 重建）、是否按当前的检索单元长度建成
    （units.current；units.rebuild 是本进程里的后台重建进度），以及向量通道（已建 done / total）与重排的状态。"""
    return {**ctx.ws.overview.index_health(), "vectors": ctx.ws.vectors.status(),
            "rerank": ctx.ws.vectors.rerank_status(),
            "units": {"current": not ctx.ws.index_stale(), "options": ctx.ws.unit_options(),
                      "rebuild": ctx.ws.rebuild_status()}}


@op("stats.overview")
def stats_overview(ctx: Ctx) -> dict:
    """工作区计数：判断的地位分布、框架页的时效与复核、待决策、agent 运行。"""
    return ctx.ws.overview.stats()


@op("entries.list")
def entries_list(ctx: Ctx, kind: Annotated[str, Field(description="artifact/event/record/read/judgment")] = "judgment",
                 judgment_kind: Annotated[str | None, Field(description="conclusion/process/normative，或 system（复核、更正、撤回、原件缺陷）")] = None, author_kind: str | None = None, source_class: str | None = None,
                 object: str | None = None, query: str | None = None,
                 include_retired: Annotated[bool, Field(description="是否包含已退役的原件，以及依据全部失效而隐藏的判断与事实记录")] = False,
                 limit: int = 50, offset: int = 0,
                 scope: Annotated[str, Field(description="过程日志：operations 操作日志（默认）/ system 系统流水（登记、读取、写判断、改设置……）/ all")] = "operations",
                 include_outputs: Annotated[bool, Field(description="原件列表是否包含运行产物（被某条过程日志 produced 的原件）")] = False) -> dict:
    """按类型、判断类型、作者、依据来源、对象浏览账本中的条目（按时间倒序）。"""
    return ctx.ws.overview.entries(kind=kind, judgment_kind=judgment_kind, author_kind=author_kind,
                                   source_class=source_class, object=object, query=query,
                                   include_retired=include_retired, limit=limit, offset=offset, scope=scope,
                                   include_outputs=include_outputs)


@op("graph.view")
def graph_view(ctx: Ctx, center: str | None = None, hops: int = 2, node_types: IdList = None,
               categories: IdList = None, hide_superseded: bool = False, limit: int = 300) -> dict:
    """关系图的节点和边。node_types：artifact/record/read/judgment/page/entity；categories：evidence/support/conflict/supersede/structure/derived/mention/association。"""
    return ctx.ws.overview.graph(center=center, hops=hops, node_types=node_types, categories=categories,
                                 hide_superseded=hide_superseded, limit=limit)


# ---------- 定期巡检（设计稿 08） ----------
@op("coverage.view")
def coverage_view(ctx: Ctx, artifact_id: Annotated[str | None, Field(description="省略时按原件、对象汇总；给出时列出这份原件每一段")] = None) -> dict:
    """覆盖图：原件段落分五档（被引用 / 读过未引 / 命中未读 / 相关未读 / 冷区）。框架内容，不能作为依据；
    没读过不等于有用。"""
    return ctx.ws.coverage.view(artifact_id)


@op("inspection.status")
def inspection_status(ctx: Ctx) -> dict:
    """定期巡检的概况：最近一期巡检包、是否到期、巡检员与复核员 agent 是否可用。"""
    return ctx.ws.inspection.status()


@op("inspection.tasks")
def inspection_tasks(ctx: Ctx, inspection_id: Annotated[str, Field(description="巡检包编号 insp_…")]) -> dict:
    """本期巡检的任务清单（工作台查看用，不记领取）：检查类别、规则看到了什么、针对的条目、要读的段落、是否已检查。"""
    return ctx.ws.inspection.tasks(inspection_id=inspection_id)


@op("inspection.guidelines")
def inspection_guidelines(ctx: Ctx) -> dict:
    """当前生效的巡检原则（设置为空时是默认文本）、默认文本，以及系统强制、不能改的巡检员与复核员规则（设计稿 08 D-36）。"""
    return ctx.ws.inspection.guidelines()


@op("inspection.list")
def inspection_list(ctx: Ctx, limit: int = 20) -> list[dict]:
    """最近几期巡检包的摘要。"""
    return ctx.ws.inspection.summaries(limit)


@op("inspection.prepare", effect="user")
def inspection_prepare(ctx: Ctx) -> dict:
    """现在准备巡检包：在本机做规则检查与探索抽样，不调用大模型。上一期准备好还没开跑时就地更新它。"""
    return ctx.ws.inspection.prepare(ctx.actor, trigger="manual")


@op("inspection.get", effect="write")
def inspection_get(ctx: Ctx, inspection_id: Annotated[str, Field(description="巡检包编号 insp_…")],
                   role: Annotated[str, Field(description="inspector 巡检员（领取任务）/ reviewer 复核员（领取待复核的发现）")] = "inspector",
                   finding_ids: Annotated[IdList, Field(description="复核员只看这些发现（待决策编号 dec_…）")] = None) -> dict:
    """领取巡检包：巡检员得到任务清单（要读的段落、要回答的问题），复核员得到待复核的发现。领取会记下本会话。"""
    return ctx.ws.inspection.get(ctx.actor, inspection_id=inspection_id, role=role, finding_ids=finding_ids)


@op("inspection.submit", effect="write")
def inspection_submit(ctx: Ctx, inspection_id: str, task_id: Annotated[str, Field(description="任务编号，如 t3")],
                      outcome: Annotated[str, Field(description="issue 有问题 / clear 检查过，没有问题")],
                      model: Annotated[str, Field(description="你的模型名")],
                      summary: Annotated[str, Field(description="issue 时写清发现了什么：对象、条件、哪里不一致或遗漏")] = "",
                      cites: Annotated[IdList, Field(description="依据：本会话读过的原件段落、事实记录或判断；不能是框架页")] = None,
                      targets: Annotated[IdList, Field(description="针对哪些条目；省略时用任务的 targets")] = None,
                      suggestion: Annotated[str, Field(description="oppose 写反对判断 / amend 请人更正或撤回 / read_more 补读 / contradict_edge 建可能矛盾边 / review 请人复核 / none")] = "review") -> dict:
    """巡检员提交一个任务的结果。issue 生成一条巡检发现：一项待决策，等复核员和人处理，不能被引用；
    你不能更正、撤回判断，也不要写判断。"""
    return ctx.ws.inspection.submit(ctx.actor, inspection_id=inspection_id, task_id=task_id, outcome=outcome,
                                    summary=summary, cites=cites, targets=targets, suggestion=suggestion, model=model)


@op("inspection.prompt")
def inspection_prompt(ctx: Ctx, inspection_id: str,
                      role: Annotated[str, Field(description="inspector / reviewer")] = "inspector",
                      finding_ids: IdList = None) -> dict:
    """给 AI 客户端的一句领取提示（巡检员或复核员）；agent 不可用时由人复制。"""
    return {"prompt": ctx.ws.inspection.prompt(inspection_id=inspection_id, role=role, finding_ids=finding_ids)}


@op("inspection.start", effect="user")
def inspection_start(ctx: Ctx, inspection_id: str,
                     role: Annotated[str, Field(description="inspector 开始巡检 / reviewer 交给复核员")] = "inspector",
                     finding_ids: IdList = None) -> dict:
    """用设置里的巡检员或复核员 agent 启动一次运行（只能由人点，设计稿 08 D-01、D-02）。"""
    return ctx.ws.inspection.start(ctx.actor, inspection_id=inspection_id, role=role, finding_ids=finding_ids)


@op("inspection.findings")
def inspection_findings(ctx: Ctx, inspection_id: str | None = None,
                        status: Annotated[str | None, Field(description="open 待处理 / resolved 已采纳 / dismissed 已驳回或忽略")] = None) -> list[dict]:
    """巡检发现列表（kind=finding 的待决策项，数据里有说明、依据、针对的条目、复核员意见）。"""
    return ctx.ws.inspection.findings(inspection_id, status)


@op("finding.resolve", effect="user")
def finding_resolve(ctx: Ctx, decision_id: Annotated[str, Field(description="巡检发现的待决策编号 dec_…")],
                    action: Annotated[str, Field(description="adopt 采纳 / reject 驳回 / ignore 忽略")],
                    reason: str = "",
                    apply_change: Annotated[bool, Field(description="采纳时明确将有依据的复核修改意见写入判断层")] = False,
                    target: Annotated[str | None, Field(description="写入时要更正的目标判断；省略则新增结论")] = None) -> dict:
    """人处理一条巡检发现。普通采纳只关闭发现；明确应用复核意见时才新增结论或追加更正。"""
    return ctx.ws.inspection.resolve(ctx.actor, decision_id=decision_id, action=action, reason=reason,
                                     apply_change=apply_change, target=target)


@op("inspection.close", effect="user")
def inspection_close(ctx: Ctx, inspection_id: str) -> dict:
    """关闭一期巡检（未处理的发现仍留在待决策里）。"""
    return ctx.ws.inspection.close(ctx.actor, inspection_id=inspection_id)


@op("inspection.export")
def inspection_export(ctx: Ctx, inspection_id: str) -> dict:
    """离线巡检包（Markdown）：任务、段落原文（不外发的原件不含原文）与要求的 JSON 回答格式。"""
    return ctx.ws.inspection.export(inspection_id=inspection_id)


@op("inspection.import", effect="user")
def inspection_import(ctx: Ctx, inspection_id: str,
                      text: Annotated[str, Field(description="AI 输出的 JSON 数组（可以带前后的文字）")],
                      model: Annotated[str, Field(description="给出结果的模型")]) -> dict:
    """贴回离线巡检的结果：记为经人转交，没有读取记录，复核员不能确认。"""
    return ctx.ws.inspection.import_result(ctx.actor, inspection_id=inspection_id, text=text, model=model)


@op("artifact.policy", effect="user")
def artifact_policy(ctx: Ctx, artifact_id: str,
                    outbound: Annotated[bool, Field(description="false 标为不外发 / true 恢复可外发")],
                    reason: str = "") -> dict:
    """标记原件是否外发：不外发的原件原文不进巡检包，巡检运行里读不到（设计稿 08 D-30、D-31）。"""
    return ctx.ws.inspection.set_policy(ctx.actor, artifact_id=artifact_id, outbound=outbound, reason=reason)


# ---------- 设置（每个数据目录各自的 config.json） ----------
SETTING_CHOICES = {
    # PDF 可以选 MinerU 分段（设计稿 05 D-15）
    "extraction.pdf": ["auto", "mineru", "off"], "extraction.pptx": ["auto", "off"], "extraction.docx": ["auto", "off"],
    "extraction.xlsx": ["auto", "off"],
    "extraction.image": ["on_demand"], "extraction.av": ["on_demand"],
    "extraction.snapshot": ["auto", "office", "libreoffice", "none"],
    "index.multimodal_model": ["none"],
    # 向量通道的模型与重排（设计稿 06 D-07、D-08）：模型放在 <安装根目录>/models/
    "index.embedding_model": ["jina-v2-base-zh", "none"], "index.rerank": ["off", "auto"],
    # 阅读模式的默认阅读器（设计稿 03 D-14）：名称与前端 frontend/src/reader/registry.ts 一致
    "viewer.pdf": ["pdfjs", "onlyoffice"], "viewer.docx": ["docx-preview", "pdfjs-snapshot", "onlyoffice"],
    "viewer.pptx": ["pdfjs-snapshot", "onlyoffice"], "viewer.xlsx": ["sheet", "pdfjs-snapshot", "onlyoffice"],
    "viewer.text": ["markdown", "sheet"], "viewer.image": ["image"], "viewer.av": ["media"],
    # AI 复核（设计稿 04 D-15）
    "review.ai": ["off", "framework", "all"],
    # 本地模型与大模型（设计稿 05）
    "models.layout": ["none", "mineru"], "models.layout_mode": ["formulas", "formulas_only_existing", "replace"],
    "models.layout_auto": ["on", "off"], "models.layout_tier": ["auto", "flash", "basic", "standard", "advanced"],
    "models.formula": ["none", "follow_layout"], "models.llm": ["none", "openai"],
    # 按需启动 MinerU（设计稿 05 D-19）
    "models.layout_launch": ["manual", "auto"],
}
# 自由填写的设置项（设计稿 03 D-13）：外部引擎地址、burrowl 对引擎的地址、JWT 密钥（读取时不返回原文）
SETTING_TEXT = {"viewer.onlyoffice_url", "viewer.onlyoffice_burrowl_url", "viewer.onlyoffice_secret",
                "models.layout_url", "models.layout_cmd", "models.llm_url", "models.llm_model", "models.llm_key",
                # 定期巡检（设计稿 08 D-25）：巡检员、复核员 agent 的名称（config.json 的 agents），评价性措辞表
                "inspection.inspector", "inspection.reviewer", "inspection.framework_words",
                # 巡检原则（设计稿 08 D-36）：多行文本，空表示用默认原则
                "inspection.guidelines"}
AGENT_SETTINGS = {"inspection.inspector", "inspection.reviewer"}
SECRET_SETTINGS = {"viewer.onlyoffice_secret", "models.llm_key"}
# 数值设置项（设计稿 06 D-21）：(最小值, 最大值)，类型跟默认值一致（整数或小数）。检索参数只影响查询，
# 工作台与 AI 读同一份配置；超出范围拒绝。默认值在 services/workspace.py 的 DEFAULT_CONFIG
SETTING_NUMBERS: dict[str, tuple[float, float]] = {
    "retrieval.limit": (5, 100), "retrieval.exact_limit": (10, 200),
    "retrieval.passages_shown": (1, 10), "retrieval.snippet_chars": (200, 2000), "retrieval.basis_shown": (1, 10),
    "retrieval.relation_ids_shown": (1, 20), "retrieval.links_shown": (1, 20),
    "retrieval.rerank_top": (5, 100), "retrieval.rrf_k": (10, 200), "retrieval.pool_min": (20, 500),
    "retrieval.pool_factor": (2, 20), "retrieval.phrase_limit": (5, 200),
    "retrieval.associate_seeds": (1, 20), "retrieval.associate_fanout": (5, 100),
    "retrieval.associate_vector_min": (0.2, 0.8),
    # 检索单元的长度（设计稿 06 D-22）：改了要整库重建索引、重算向量；保存时立即重建
    "index.units_target": (100, 800), "index.units_max": (150, 800), "index.units_context_chars": (0, 400),
    # 定期巡检（设计稿 08 D-03、D-09、D-11）
    "inspection.interval_days": (0, 90), "inspection.max_segments": (10, 500), "inspection.explore_ratio": (0.0, 0.8),
    "inspection.window_days": (7, 365), "inspection.hit_min": (1, 20), "inspection.related_min": (0.2, 0.9),
    "inspection.first_days": (1, 365),
}
UNIT_SETTINGS = ("units_target", "units_max", "units_context_chars")
# 打开重排时检索单元不能超过重排模型的输入（512 token，含查询与上下文）：沿用验证过的上限
RERANK_UNITS_MAX, RERANK_CONTEXT_MAX = 400, 160


def _check_index_settings(cfg: dict) -> None:
    """跨项校验：目标长度不超过上限；打开重排时单元上限与上下文不超过重排模型的输入。"""
    idx = cfg.get("index", {})
    if idx.get("units_target", 0) > idx.get("units_max", 0):
        raise BurrowlError("INVALID_ARGUMENT", "检索单元的目标长度不能大于上限",
                           {"units_target": idx.get("units_target"), "units_max": idx.get("units_max")})
    if idx.get("rerank") == "auto" and (idx.get("units_max", 0) > RERANK_UNITS_MAX
                                        or idx.get("units_context_chars", 0) > RERANK_CONTEXT_MAX):
        raise BurrowlError("INVALID_ARGUMENT",
                           f"打开重排时，检索单元上限不能超过 {RERANK_UNITS_MAX}、上下文不能超过 {RERANK_CONTEXT_MAX} 字"
                           "（重排模型的输入上限 512 token，含查询与上下文）",
                           {"units_max": idx.get("units_max"), "units_context_chars": idx.get("units_context_chars")})


def _setting_value(cfg: dict, key: str):
    group, name = key.split(".")
    return cfg.get(group, {}).get(name)


def _number(key: str, value) -> int | float:
    from ..services.workspace import DEFAULT_CONFIG  # noqa: PLC0415
    low, high = SETTING_NUMBERS[key]
    as_int = isinstance(_setting_value(DEFAULT_CONFIG, key), int)
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
        if as_int:
            if number != int(number):
                raise ValueError
            number = int(number)
    except (TypeError, ValueError):
        raise BurrowlError("INVALID_ARGUMENT", "这个设置项要填" + ("整数" if as_int else "数字"),
                           {"key": key}) from None
    if not low <= number <= high:
        raise BurrowlError("INVALID_ARGUMENT", f"取值要在 {low} 到 {high} 之间", {"key": key, "min": low, "max": high})
    return number


@op("settings.get")
def settings_get(ctx: Ctx) -> dict:
    """当前数据目录的抽取方式、阅读模式的默认阅读器与索引方式设置，以及本机可用的页面快照转换器。"""
    from ..services import extractors  # noqa: PLC0415
    from ..services.agents import AGENT_CLI_PRESETS  # noqa: PLC0415
    cfg = ctx.ws.config
    values = {key: _setting_value(cfg, key) for key in SETTING_CHOICES}
    for key in SETTING_TEXT:
        value = _setting_value(cfg, key) or ""
        values[key] = ("已设置" if value else "") if key in SECRET_SETTINGS else value
    from ..services.workspace import DEFAULT_CONFIG  # noqa: PLC0415
    numbers = {}
    for key, (low, high) in SETTING_NUMBERS.items():
        values[key] = _setting_value(cfg, key)
        numbers[key] = {"min": low, "max": high, "default": _setting_value(DEFAULT_CONFIG, key)}
    return {"values": values, "choices": SETTING_CHOICES, "text_settings": sorted(SETTING_TEXT), "numbers": numbers,
            "converters": extractors.converters(), "data_name": _name_of(ctx.ws.root),
            "agent_cli_presets": AGENT_CLI_PRESETS}


@op("settings.set", effect="user")
def settings_set(ctx: Ctx, values: Annotated[dict, Field(description="如 {\"extraction.pdf\": \"off\"}")]) -> dict:
    """修改当前数据目录的设置。抽取设置只影响以后的抽取（已有的抽取不变，可在原件页重新抽取）；阅读器设置立即生效；
    检索参数（retrieval.*）对工作台和 AI 的下一次调用生效；检索单元长度（index.units_*）保存后在后台整库重建索引
    （进度见 index.health 的 units.rebuild），向量随后在后台重算。每次修改记一条过程日志（旧值、新值，密钥不记原文）。"""
    ctx.actor.require_human("修改设置")
    changes: dict[str, dict] = {}
    for key, value in values.items():
        if key in SETTING_NUMBERS:
            group, name = key.split(".")
            changes.setdefault(group, {})[name] = _number(key, value)
            continue
        if key in SETTING_TEXT:
            value = str(value or "").strip()
            is_url = key.endswith("_url")
            if key == "inspection.guidelines" and len(value) > 4000:
                raise BurrowlError("INVALID_ARGUMENT", "巡检原则不能超过 4000 字", {"key": key})
            if key in AGENT_SETTINGS and value and value not in ctx.ws.config["agents"]:
                raise BurrowlError("INVALID_ARGUMENT", "没有配置这个 agent",
                                   {"key": key, "known": list(ctx.ws.config["agents"])})
            if key == "models.layout_cmd" and any(c in value for c in "&|<>^\n\r"):
                raise BurrowlError("INVALID_ARGUMENT", "启动命令只填可执行文件（命令名或完整路径），不能带 & | < > 等符号")
            if is_url and value and not value.startswith(("http://", "https://")):
                raise BurrowlError("INVALID_ARGUMENT", "地址要以 http:// 或 https:// 开头", {"key": key})
            group, name = key.split(".")
            changes.setdefault(group, {})[name] = value.rstrip("/") if is_url else value
            continue
        if key not in SETTING_CHOICES:
            raise BurrowlError("INVALID_ARGUMENT", "未知的设置项",
                               {"key": key, "known": [*SETTING_CHOICES, *SETTING_TEXT, *SETTING_NUMBERS]})
        if value not in SETTING_CHOICES[key]:
            raise BurrowlError("INVALID_ARGUMENT", "这个设置项不接受该取值", {"key": key, "choices": SETTING_CHOICES[key]})
        group, name = key.split(".")
        changes.setdefault(group, {})[name] = value
    before = ctx.ws.config
    _check_index_settings({g: {**before.get(g, {}), **changes.get(g, {})} for g in {*before, *changes}
                           if isinstance(before.get(g, {}), dict)})
    diff = {}
    for group, items in changes.items():
        for name, value in items.items():
            key, old = f"{group}.{name}", before.get(group, {}).get(name)
            if old == value:
                continue
            diff[key] = {"from": "（密钥）", "to": "（密钥）"} if key in SECRET_SETTINGS else {"from": old, "to": value}
    ctx.ws.save_config(changes)
    rebuild = None
    if ctx.ws.index_stale():  # 检索单元长度变了：在后台整库重建，不占着锁；向量按新单元的内容另行补建（设计稿 06 D-22）
        rebuild = ctx.ws.start_rebuild("检索单元长度变了")
    if diff:  # 可追溯：同一个查询前后结果不同，能对上是哪次改了哪个参数（设计稿 06 D-21）
        ctx.ws.capture.log(ctx.actor, "settings.set",
                           input={"changes": diff, **({"rebuild": "started"} if rebuild else {})})
    out = settings_get(ctx)
    if rebuild:
        out["rebuild"] = rebuild
    return out


@op("models.status")
def models_status(ctx: Ctx) -> dict:
    """本地模型与大模型的槽位（工具、地址、是否本机、是否自动运行）与本进程里最近的模型任务。"""
    return ctx.ws.models.status()


@op("models.check", effect="user")
def models_check(ctx: Ctx, slot: Annotated[str, Field(description="layout / formula / llm")]) -> dict:
    """测试连接：调用模型服务的健康检查，返回工具版本。"""
    return ctx.ws.models.check(slot)


@op("models.stop", effect="user")
def models_stop(ctx: Ctx) -> dict:
    """关闭 burrowl 启动的 MinerU 服务（设计稿 05 D-20）。"""
    ctx.actor.require_human("关闭模型服务")
    return {"stopped": ctx.ws.models.launch.stop(force=True), "launch": ctx.ws.models.launch.status()}


@op("artifact.layout_engine", effect="write")
def artifact_layout_engine(ctx: Ctx, artifact_id: str,
                           mode: Annotated[str | None, Field(description="formulas 补公式（默认）/ "
                                                                      "formulas_only_existing 只补已有公式块 / "
                                                                      "replace 整份替换（只有人）；"
                                                                      "省略时按设置")] = None,
                           fresh: Annotated[bool, Field(description="不用缓存，重新调用引擎")] = False,
                           wait: Annotated[bool, Field(description="等任务结束再返回")] = False) -> dict:
    """用本地版面引擎（MinerU）处理一份 PDF：给公式块补 LaTeX、给段落记下行内公式；replace 时整份替换抽取；
    抽取方式为 MinerU 时，还没被引用的原件采用引擎的分段。"""
    job = ctx.ws.models.run_layout(ctx.actor, artifact_id, mode=mode, fresh=fresh)
    if not wait:
        return job
    with ctx.ws.unlocked():
        return ctx.ws.models.wait(job["id"])


@op("artifact.recognize_formula", effect="write")
def artifact_recognize_formula(ctx: Ctx, artifact_id: str,
                               anchors: Annotated[IdList, Field(description="公式块的段落锚点，如 p3-4")],
                               engine: Annotated[str, Field(description="model 本地公式模型 / llm 大模型（只有人）")] = "model",
                               wait: bool = False) -> dict:
    """识别公式块的 LaTeX：结果标为模型识别（OCR 档或 AI 档），需要人确认。"""
    job = ctx.ws.models.recognize_formulas(ctx.actor, artifact_id, anchors=anchors or [], engine=engine)
    if not wait:
        return job
    with ctx.ws.unlocked():
        return ctx.ws.models.wait(job["id"])


@op("extraction.recognitions")
def extraction_recognitions(ctx: Ctx, artifact_id: Annotated[str | None, Field(description="省略时按原件汇总")] = None) -> dict:
    """待确认的识别：OCR / AI 识别、未经人确认的段落与公式 LaTeX，以及 AI 核对的结果（设计稿 04 D-25）。"""
    rec = ctx.ws.recognition
    if artifact_id:
        return {"artifact_id": artifact_id, "items": rec.items(artifact_id), "ai_allowed": rec.allowed()}
    return {"artifacts": rec.summary(), "ai_allowed": rec.allowed()}


@op("extraction.ai_check", effect="user")
def extraction_ai_check(ctx: Ctx, artifact_ids: Annotated[IdList, Field(description="原件 ID")],
                        anchors: Annotated[IdList, Field(description="只核对这些段落；省略时核对还没核对过的")] = None) -> dict:
    """把识别结果交给大模型看图核对（只有人能发起；设计稿 04 D-22、D-23）。结果为"AI 已核对"，不等于人已确认。"""
    return {"jobs": ctx.ws.recognition.enqueue(ctx.actor, artifact_ids or [], anchors=anchors)}


@op("settings.check_engine", effect="user")
def settings_check_engine(ctx: Ctx, url: Annotated[str | None, Field(description="引擎地址；省略时用设置里的 ONLYOFFICE 地址")] = None) -> dict:
    """测试能否连上外部阅读引擎（ONLYOFFICE Docs 的 /healthcheck）。"""
    from . import engines  # noqa: PLC0415
    target = url or engines.settings_of(ctx.ws)["url"]
    if not target:
        raise BurrowlError("INVALID_ARGUMENT", "还没有填写 ONLYOFFICE 的地址")
    return {"url": target, **engines.check_onlyoffice(target)}


# ---------- 工作台服务（只在工作台进程内有效） ----------
@op("server.info")
def server_info(ctx: Ctx) -> dict:
    """工作台进程的运行版本、已安装版本（是否需要重启）、进程号与启动时间。"""
    from . import server  # noqa: PLC0415
    return server.info(ctx.ws)


@op("server.restart", effect="user")
def server_restart(ctx: Ctx) -> dict:
    """重启工作台：新进程接管同一网址并加载已安装的新版本。命令行请用 burrowl restart。"""
    from . import server  # noqa: PLC0415
    _require_http(ctx)
    return server.restart_self()


@op("server.stop", effect="user")
def server_stop(ctx: Ctx) -> dict:
    """停止工作台。之后用 burrowl start 或开始菜单重新打开。"""
    from . import server  # noqa: PLC0415
    _require_http(ctx)
    return server.stop_self()


def _require_http(ctx: Ctx) -> None:
    ctx.actor.require_human("控制工作台服务")
    if ctx.channel != "http":
        raise BurrowlError("INVALID_ARGUMENT", "只能在工作台里使用；命令行请用 burrowl restart / burrowl stop")
