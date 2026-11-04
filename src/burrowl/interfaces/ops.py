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
        "version": __version__, "data": str(ws.root),
        "actor": {"id": ctx.actor.id, "kind": ctx.actor.kind, "session": ctx.actor.session_id},
        "ledger": {t: count(ws.ledger_db, t) for t in ("artifacts", "events", "records", "reads", "judgments", "links")},
        "framework": {t: count(ws.framework_db, t) for t in ("entities", "pages", "edges")},
        "open_decisions": len(ws.framework.decisions("open")),
        "inputs_changed": len(ws.framework.pages(freshness="inputs_changed")),
    }


# ---------- 过程捕获与原件 ----------
@op("capture.log", effect="write")
def capture_log(ctx: Ctx, op_name: Annotated[str, Field(description="操作名，如 exec.shell、measure.pressure")],
                input: dict | None = None, output: str | None = None, conditions: dict | None = None,
                objects: IdList = None,
                source_class: Annotated[str, Field(description="local 本地实证（默认）/ inferred 推断（如对话消息）")] = "local") -> dict:
    """记一条过程事件（只追加）。对设备等对象的操作请先调用 constraints_check。条件只记当下能确定的，事后不能补写。"""
    return ctx.ws.capture.log(ctx.actor, op_name, input=input, output=output, conditions=conditions,
                              objects=objects, source_class=source_class)


@op("artifact.register", effect="write")
def artifact_register(ctx: Ctx, kind: Annotated[str, Field(description="file/conversation/literature/dataset/image/log")],
                      source_class: Annotated[str, Field(description="local 本地实证（本项目内执行、测量或直接观察）/ external 外部报告 / inferred 推断")],
                      path: str | None = None, text: str | None = None, title: str | None = None,
                      storage: Annotated[str, Field(description="managed 复制保存 / referenced 只登记路径和指纹")] = "managed",
                      external_tier: Annotated[str | None, Field(description="peer_reviewed/preprint/vendor/web")] = None,
                      version_of: str | None = None, metadata: dict | None = None, objects: IdList = None) -> dict:
    """登记原件（只记原文与可核对的元数据，不写总结）。同内容幂等；新版本用 version_of 指向旧版本。"""
    return ctx.ws.artifacts.register(ctx.actor, kind=kind, source_class=source_class, path=path, text=text,
                                     title=title, storage=storage, external_tier=external_tier,
                                     version_of=version_of, metadata=metadata, objects=objects)


@op("artifact.read", effect="write")
def artifact_read(ctx: Ctx, artifact_id: str,
                  locator: Annotated[str | None, Field(description="seg:N 或 seg:N-M；省略读全部")] = None) -> dict:
    """读原件的一段并留下读取记录；判断引用原件内容时，优先引用返回的读取记录 ID。"""
    return ctx.ws.artifacts.read(ctx.actor, artifact_id, locator)


@op("artifact.segments")
def artifact_segments(ctx: Ctx, artifact_id: str) -> list[dict]:
    """列出原件按自然边界切出的分段（不产生读取记录）。"""
    return ctx.ws.artifacts.segments(artifact_id)


@op("record.promote", effect="write")
def record_promote(ctx: Ctx, event_id: str | None = None, artifact_id: str | None = None, locator: str | None = None,
                   objects: IdList = None, method: str | None = None, result: str | None = None,
                   boundary: str = "complete", gaps: IdList = None, conditions: dict | None = None,
                   reason: str = "") -> dict:
    """把过程事件或原件片段升级为事实记录：对象、条件、方法、结果（逐字）、边界。条件不能补写，缺失的写进 gaps。"""
    return ctx.ws.artifacts.promote(ctx.actor, event_id=event_id, artifact_id=artifact_id, locator=locator,
                                    objects=objects, method=method, result=result, boundary=boundary, gaps=gaps,
                                    conditions=conditions, reason=reason)


# ---------- 判断 ----------
@op("judgment.write", effect="write")
def judgment_write(ctx: Ctx, kind: Annotated[str, Field(description="conclusion 结论（关于对象的陈述，可作依据）/ "
                                                                     "process 过程（提问、尝试、停下的路线、目的；不能作为结论的依据）/ "
                                                                     "normative 规定（约束、决定、指令）")],
                   text: Annotated[str, Field(description="写全对象和条件，不用指代词，不写「显然」「关键在于」等措辞")],
                   cites: Annotated[IdList, Field(description="依据：原件、事实记录、读取记录或判断的 ID；不能是框架页")] = None,
                   objects: IdList = None, conditions: str | None = None,
                   relations: Annotated[list[dict] | None, Field(
                       description="与其他判断的关系 [{rel, target, condition?}]，rel 取 supports/opposes/depends_on/"
                                   "answers/targets/coexists_under")] = None,
                   external_author: Annotated[str | None, Field(description="摘录文献论断时填原作者")] = None,
                   revises: str | None = None, revise_reason: str | None = None,
                   local_observation: Annotated[bool, Field(description="人亲自看到或测到（只有人能勾选）")] = False,
                   reopen_condition: Annotated[str | None, Field(description="过程内容：停下的路线在什么条件下值得重新打开")] = None) -> dict:
    """写一条判断（只追加）。写入时可信度由系统根据依据推出。认为别的判断不对时，写 opposes 关系，不能更正或撤回。"""
    return ctx.ws.judgments.write(ctx.actor, kind=kind, text=text, cites=cites, objects=objects,
                                  conditions=conditions, relations=relations, external_author=external_author,
                                  revises=revises, revise_reason=revise_reason, local_observation=local_observation,
                                  reopen_condition=reopen_condition)


@op("judgment.amend", effect="user")
def judgment_amend(ctx: Ctx, mode: Annotated[str, Field(description="correction 更正 / retraction 撤回 / defect 原件有缺陷")],
                   target: str, reason: str, cites: IdList = None) -> dict:
    """人工修改入口：更正、撤回判断，或标记原件有缺陷。底层写一条新判断指向原条目，原条目不变。"""
    return ctx.ws.judgments.amend(ctx.actor, mode=mode, target=target, reason=reason, cites=cites)


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
    """复核框架页或边。复核结论写回判断层成为一条新判断。"""
    return ctx.ws.frameworks.review(ctx.actor, item_id=item_id, verdict=verdict, reason=reason, cites=cites)


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
    """待决策列表（按影响范围排序）：术语连接、待复核、需重新综合、操作前未检查约束、传播超限。"""
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
           limit: int = 20) -> dict:
    """检索。结果带地位坐标，逐级排序；相关的有效约束列在最前；被替代的排在最后并带标注。"""
    return ctx.ws.retrieval.search(query, layers=layers, objects=objects, mode=mode, include_log=include_log,
                                   include_process=include_process,
                                   limit=limit)


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
    return out


@op("entry.expand")
def entry_expand(ctx: Ctx, id: Annotated[str, Field(description="条目 ID；原件片段写成 art_…#seg-N")],
                 mode: str = "reuse") -> dict:
    """展开背景：自带条件 → 同一来源的前后内容 → 同一对象的其他记录 → 引用了它的判断（解读，探索模式下隐藏）。"""
    return ctx.ws.retrieval.expand(id, mode=mode)


@op("timeline")
def timeline(ctx: Ctx, object: str) -> list[dict]:
    """按对象列出全部条目，按时间排序（历史类查询）。"""
    return ctx.ws.retrieval.timeline(object)


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
    """在本机启动一个 agent CLI 处理任务；它通过 MCP 回到本工作区读写，输出结束后登记为对话原件。"""
    return ctx.ws.agents.start(ctx.actor, agent=agent, prompt=prompt, cwd=cwd, preamble=preamble)


@op("agent.output")
def agent_output(ctx: Ctx, run_id: str, offset: int = 0) -> dict:
    """读取 agent 运行的输出（从第 offset 行开始）。"""
    return ctx.ws.agents.output(run_id, offset)


@op("agent.runs")
def agent_runs(ctx: Ctx, limit: int = 50) -> list[dict]:
    """列出最近的 agent 运行。"""
    return ctx.ws.framework.runs(limit)


@op("agent.cancel", effect="user")
def agent_cancel(ctx: Ctx, run_id: str) -> dict:
    """停止正在运行的 agent。"""
    return ctx.ws.agents.cancel(ctx.actor, run_id)


# ---------- 维护 ----------
@op("index.rebuild", effect="admin")
def index_rebuild(ctx: Ctx) -> dict:
    """从账本和框架整库重建全文索引。"""
    return ctx.ws.rebuild_index()


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


@op("stats.overview")
def stats_overview(ctx: Ctx) -> dict:
    """工作区计数：判断的地位分布、框架页的时效与复核、待决策、agent 运行。"""
    return ctx.ws.overview.stats()


@op("entries.list")
def entries_list(ctx: Ctx, kind: Annotated[str, Field(description="artifact/event/record/read/judgment")] = "judgment",
                 judgment_kind: Annotated[str | None, Field(description="conclusion/process/normative，或 system（复核、更正、撤回、原件缺陷）")] = None, author_kind: str | None = None, source_class: str | None = None,
                 object: str | None = None, query: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """按类型、判断类型、作者、依据来源、对象浏览账本中的条目（按时间倒序）。"""
    return ctx.ws.overview.entries(kind=kind, judgment_kind=judgment_kind, author_kind=author_kind,
                                   source_class=source_class, object=object, query=query, limit=limit, offset=offset)


@op("graph.view")
def graph_view(ctx: Ctx, center: str | None = None, hops: int = 2, node_types: IdList = None,
               categories: IdList = None, hide_superseded: bool = False, limit: int = 300) -> dict:
    """关系图的节点和边。node_types：artifact/record/read/judgment/page/entity；categories：evidence/support/conflict/supersede/structure/derived/mention/association。"""
    return ctx.ws.overview.graph(center=center, hops=hops, node_types=node_types, categories=categories,
                                 hide_superseded=hide_superseded, limit=limit)


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
    return server.restart_self(ctx.ws)


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
