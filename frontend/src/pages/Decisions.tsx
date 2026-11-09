// 待决策：按类型筛选（带数量），按影响范围排序；术语连接、复核、重新综合、未检查约束、传播超限。
// 设计稿 04 D-07：影响范围为 0 的折叠为"低影响"；另有每周抽查。复核项用统一的复核框（D-17），可多选交给 AI 复核（D-16）。
// D-25："待确认的识别"按原件一行，和复核项一起勾选；"交给 AI 复核"对识别项直接调用大模型（D-23），其余复制提示。
import { useState } from "react";
import { call } from "../api";
import { DECISION, PAGE_TYPE, REVIEW_VERDICT } from "../labels";
import { aiReviewPrompt, ReviewBox } from "../review";
import { InspectionSection } from "../inspection";
import { delegate, href } from "../router";
import { Action, Chips, Empty, ErrorBox, IdLink, Panel, Tag, Time, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Decisions() {
  const [kinds, setKinds] = useState<string[]>([]);
  const [status, setStatus] = useState<string[]>(["open"]);
  const [picked, setPicked] = useState<string[]>([]);
  const [pickedArts, setPickedArts] = useState<string[]>([]);
  const [handoff, setHandoff] = useState<string | null>(null);
  const [items, error, reload] = useLoad(() => call<any[]>("decision.list", { status: status[0] ?? null }), [status.join()]);
  const [recog, , reloadRecog] = useLoad(() => call<any>("extraction.recognitions").catch(() => null), []);
  usePoll(reload);
  const all = items ?? [];
  const counts = Object.fromEntries(Object.keys(DECISION).map((k) => [k, all.filter((d: any) => d.kind === k).length]));
  const open = status[0] === "open";
  // 待处理的巡检发现在顶部的巡检栏下按巡检运行分组显示（设计稿 08 D-22、§9），不混在其他待决策项里
  const showInspection = open && (!kinds.length || kinds.includes("finding"));
  const openFindings = all.filter((d: any) => d.kind === "finding");
  const shown = (kinds.length ? all.filter((d: any) => kinds.includes(d.kind)) : all).filter((d: any) => !open || d.kind !== "finding");
  const main = open ? shown.filter((d: any) => d.impact > 0) : shown;
  const low = open ? shown.filter((d: any) => d.impact <= 0) : [];
  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const toggleArt = (id: string) => setPickedArts(pickedArts.includes(id) ? pickedArts.filter((x) => x !== id) : [...pickedArts, id]);
  const recogRows = ((recog?.artifacts ?? []) as any[]);
  const showRecog = open && (!kinds.length || kinds.includes("recognition"));
  const total = picked.length + pickedArts.length;
  // 一个按钮交出所有勾选项：识别项由工作台调用大模型核对，其余复制提示交给 AI 客户端
  const handOff = async () => {
    const parts: string[] = [];
    try {
      if (pickedArts.length) {
        const { jobs } = await call<any>("extraction.ai_check", { artifact_ids: pickedArts });
        parts.push(`${jobs.length} 份原件的识别结果已交给大模型核对（后台进行，完成后这里会更新）`);
        setPickedArts([]);
        watchJobs(jobs.map((j: any) => j.id), () => reloadRecog());
      }
      if (picked.length) {
        delegate(aiReviewPrompt(picked));
        parts.push(`${picked.length} 项复核的提示已复制，交给你的 AI 客户端`);
        setPicked([]);
      }
      setHandoff(parts.join("；"));
    } catch (e: any) {
      setHandoff(e.message);
    }
  };
  const item = (d: any) => <DecisionItem key={d.id} d={d} reload={reload} picked={picked.includes(d.subject_id)} onPick={() => toggle(d.subject_id)} />;
  return (
    <>
      <Panel
        title="待决策"
        actions={
          <>
            <span className="muted">按影响范围排序；不阻塞导入和写入</span>
            {total > 0 && (
              <button type="button" className="small primary" onClick={handOff} title="识别项：工作台调用设置里的大模型看图核对；框架页、边、判断：复制提示交给 AI 客户端">
                交给 AI 复核（{total}）
              </button>
            )}
          </>
        }
      >
        <div className="filter-rows">
          <span className="filter-label">类型</span>
          <Chips multi options={[...Object.entries(DECISION), ["recognition", "待确认的识别"]]} value={kinds} onChange={setKinds} counts={{ ...counts, recognition: recogRows.length }} />
          <span className="filter-label">状态</span>
          <Chips
            all="全部"
            options={[
              ["open", "待处理"],
              ["resolved", "已处理"],
              ["dismissed", "已关闭"],
            ]}
            value={status}
            onChange={setStatus}
          />
        </div>
        <ErrorBox error={error} />
        {handoff && <p className="small-text">{handoff}</p>}
        {showRecog && recogRows.length > 0 && <Recognitions rows={recogRows} allowed={recog?.ai_allowed} picked={pickedArts} onPick={toggleArt} />}
        {showInspection && <InspectionSection findings={openFindings} reloadFindings={reload} />}
        {main.length === 0 && low.length === 0 && !(showRecog && recogRows.length) && !(showInspection && openFindings.length) && <Empty>没有待决策项</Empty>}
        {main.map(item)}
        {low.length > 0 && (
          <details className="low-impact">
            <summary>低影响（{low.length} 项）：错了只影响浏览，不影响判断层</summary>
            {low.map(item)}
          </details>
        )}
      </Panel>
      {open && <Sample />}
    </>
  );
}

function watchJobs(ids: string[], done: () => void) {
  const left = new Set(ids);
  const tick = async () => {
    const st = await call<any>("models.status").catch(() => null);
    for (const j of st?.jobs ?? []) if (left.has(j.id) && (j.status === "done" || j.status === "failed")) left.delete(j.id);
    if (left.size) window.setTimeout(tick, 2000);
    done();
  };
  window.setTimeout(tick, 2000);
}

// 待确认的识别（D-25）：OCR / AI 识别、还没有人确认的段落与公式，每份原件一行；被判断引用过的排在前面
function Recognitions({ rows, allowed, picked, onPick }: { rows: any[]; allowed?: string | null; picked: string[]; onPick: (id: string) => void }) {
  return (
    <div className="decision recognition">
      <div className="decision-head">
        <Tag tone="warn">待确认的识别</Tag>
        <span className="muted small-text">{allowed ? `不能交给 AI：${allowed}` : "勾选后可交给大模型看图核对；AI 核对不等于人已确认，确认仍在原件页"}</span>
      </div>
      <ul className="plain">
        {rows.map((r) => (
          <li key={r.artifact_id} className="row tight">
            <input type="checkbox" checked={picked.includes(r.artifact_id)} onChange={() => onPick(r.artifact_id)} disabled={!!allowed || r.unchecked === 0} title={r.unchecked === 0 ? "都已核对过" : "勾选后交给 AI 复核"} />
            <a href={href("entry", r.artifact_id)}>{r.title ?? r.artifact_id}</a>
            {r.cited && <Tag tone="accent">已被引用</Tag>}
            <span className="muted small-text">
              {r.text ? `文字 ${r.text} 段` : ""}
              {r.text && r.latex ? " · " : ""}
              {r.latex ? `公式 ${r.latex} 条` : ""}
              {r.unchecked ? ` · 未核对 ${r.unchecked}` : ""}
            </span>
            {r.ai_confirmed > 0 && <Tag tone="good">AI 已核对 {r.ai_confirmed}</Tag>}
            {r.ai_rejected > 0 && <Tag tone="bad">AI 认为有问题 {r.ai_rejected}</Tag>}
            {r.ai_unsure > 0 && <Tag>AI 拿不准 {r.ai_unsure}</Tag>}
          </li>
        ))}
      </ul>
    </div>
  );
}

// 每周抽查（D-07）：从 AI 生成未复核的框架页里挑几页，人看过后用复核框确认或驳回；用来发现规则是否太松
function Sample() {
  const [data, error, reload] = useLoad(() => call<any>("review.sample"), []);
  const [openId, setOpenId] = useState<string | null>(null);
  if (error) return <ErrorBox error={error} />;
  if (!data || data.pages.length === 0) return null;
  return (
    <Panel title={`本周抽查（${data.week}）`} actions={<span className="muted">从 {data.pool} 页 AI 生成、未复核的框架页里挑出；同一周结果不变</span>}>
      <ul className="plain">
        {data.pages.map((p: any) => (
          <li key={p.id}>
            <a href={href("entry", p.id)}>{p.title}</a> <span className="muted">{PAGE_TYPE[p.type] ?? p.type}</span>{" "}
            <button type="button" className="link small-text" onClick={() => setOpenId(openId === p.id ? null : p.id)}>
              {openId === p.id ? "收起" : "复核"}
            </button>
            {openId === p.id && <ReviewBox itemId={p.id} reload={reload} compact />}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function DecisionItem({ d, reload, picked, onPick }: { d: any; reload: () => void; picked: boolean; onPick: () => void }) {
  const [closeReason, setCloseReason] = useState("");
  const [newName, setNewName] = useState(d.data.term ?? "");
  const [newKind, setNewKind] = useState("device");
  const open = d.status === "open";
  const reviewable = d.kind === "review" && d.subject_id && /^(pg|edg|jdg|art)_/.test(d.subject_id);
  return (
    <div className={`decision ${d.kind}`}>
      <div className="decision-head">
        {open && reviewable && !d.subject_id.startsWith("art_") && (
          <input type="checkbox" checked={picked} onChange={onPick} title="多选后一起交给 AI 复核" />
        )}
        <Tag tone={d.kind === "constraint_unchecked" || d.kind === "propagation_overflow" ? "bad" : "warn"}>{DECISION[d.kind] ?? d.kind}</Tag>
        <span className="mono">{d.id}</span>
        <span className="muted">影响 {d.impact}</span>
        {d.subject_id && <IdLink id={d.subject_id} />}
        <Time value={d.created_at} />
        {d.data.requested && <Tag>请人复核</Tag>}
        {!open && <Tag>{d.status === "resolved" ? (d.data.resolution?.by_ai ? "已由 AI 处理" : "已处理") : "已关闭"}</Tag>}
      </div>
      {d.kind === "term_link" && (
        <>
          <p>
            叫法「{d.data.term}」：{d.data.reason}
            {d.data.excerpt && <span className="muted">（原文：{d.data.excerpt}）</span>}
          </p>
          {open && (
            <>
              <div className="row">
                {d.data.candidates.map((c: any) => (
                  <Action key={c.id} label={`是 ${c.kind}「${c.name}」`} run={async () => (await call("term.decide", { decision_id: d.id, entity_id: c.id }), reload())} />
                ))}
              </div>
              <div className="row">
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="新实体名称" />
                <input value={newKind} onChange={(e) => setNewKind(e.target.value)} placeholder="类型" />
                <Action label="新建实体并连接" run={async () => (await call("term.decide", { decision_id: d.id, new_entity: { kind: newKind, name: newName } }), reload())} />
              </div>
            </>
          )}
        </>
      )}
      {d.kind === "review" && (
        <>
          <p>
            {d.data.what} {d.data.title ?? ""} {d.data.reason ?? ""} {d.data.note && <span className="muted">（{d.data.note}）</span>}
          </p>
          {(d.data.notes ?? []).map((n: any, i: number) => (
            <p key={i} className="small-text">
              <Tag tone={n.verdict === "reject" ? "bad" : n.verdict === "confirm" ? "good" : "muted"}>
                {n.model ? `AI·${n.model}` : n.by} {n.verdict ? REVIEW_VERDICT[n.verdict] ?? n.verdict : "请人复核"}
              </Tag>{" "}
              {n.reason ?? n.note}
            </p>
          ))}
          {open && reviewable && <ReviewBox itemId={d.subject_id} reload={reload} compact />}
        </>
      )}
      {d.kind === "rederive" && (
        <p>
          {d.data.title}：{d.data.reason}{" "}
          {open && (
            <button type="button" onClick={() => delegate(`处理待决策 ${d.id}：框架页 ${d.subject_id} 的输入已变化。请用 page_get 读取当前版本与输入清单，查看相关新判断后用 page_write 写出新版本，inputs 列出实际依据。`)}>
              交给 agent
            </button>
          )}
        </p>
      )}
      {d.kind === "finding" && (
        <p>
          {d.data.check_label}：{d.data.summary}
          {d.data.resolution?.reason && <span className="muted">（处理说明：{d.data.resolution.reason}）</span>}
        </p>
      )}
      {d.kind === "constraint_unchecked" && (
        <p>
          {d.data.actor_id} 执行 {d.data.op} 前没有检查约束：{d.data.constraints.map((c: any) => c.text).join("；")}
        </p>
      )}
      {d.kind === "propagation_overflow" && (
        <p>
          传播超过上限，{d.data.unchecked.length} 个条目标为"未核查"：{d.data.reason}
        </p>
      )}
      {open && (
        <div className="row">
          <input className="grow" value={closeReason} onChange={(e) => setCloseReason(e.target.value)} placeholder="关闭理由" />
          <Action label="关闭" run={async () => (await call("decision.dismiss", { decision_id: d.id, reason: closeReason || "不处理" }), reload())} />
        </div>
      )}
    </div>
  );
}
