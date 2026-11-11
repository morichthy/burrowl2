// 待决策：左边是队列（按影响范围排序，可按类型、状态筛选），右边一次只看一件，按"是什么、为什么要你看、下一步"排。
// 设计稿 04 D-07：影响范围为 0 的折叠为"低影响"；另有每周抽查。复核项用统一的复核框（D-17），可多选交给 AI 复核（D-16）。
// D-25："待确认的识别"按原件一行，和复核项一起勾选；"交给 AI 复核"对识别项直接调用大模型（D-23），其余复制提示。
// 批量只有"交给 AI"：确认和关闭要一件一件来（关闭要写理由）。筛选和选中的那件写在网址里。
import { useEffect, useState } from "react";
import { call } from "../api";
import { DECISION, PAGE_TYPE, REVIEW_VERDICT } from "../labels";
import { aiReviewPrompt, ReviewBox } from "../review";
import { InspectionSection } from "../inspection";
import { delegate, go, list, unlist, useUrlState } from "../router";
import { setCursor, useShortcuts } from "../shell/shortcuts";
import { toast } from "../shell/toast";
import { EntryName } from "../entryLabels";
import { Action, Empty, ErrorBox, IdLink, Loading, Panel, Tag, Time, useLoad, usePoll } from "../ui";
import { rederivePrompt } from "./Entries";

/* eslint-disable @typescript-eslint/no-explicit-any */

const DECISION_FILTERS = { kinds: "", status: "open", at: "" };
const STATUS: [string, string][] = [["open", "待处理"], ["resolved", "已处理"], ["dismissed", "已关闭"], ["", "全部"]];

// 为什么要你看：每类一句，说明这件事为什么只能由人决定
const WHY: Record<string, string> = {
  term_link: "叫法和实体的对应关系决定了检索和关系图怎么连，连错会把不相干的内容合在一起；术语决定只能由人做。",
  review: "这是 AI 写的框架页、推断的关系或请人复核的条目。AI 复核不等于人已复核，人确认后它的复核状态才会变。",
  rederive: "框架页的输入变了，页面内容可能已经过时。框架永远不能作依据，但过时的综合会误导阅读。",
  constraint_unchecked: "AI 对设备或对象动手前应当先检查约束，这次没有检查。需要你确认这次操作有没有违反约束。",
  propagation_overflow: "一次变化影响的条目超过了上限，没有逐条核查。需要你决定是否逐条看。",
  finding: "巡检员发现的问题。巡检发现不能作为依据；复核员确认的排在前面，由你采纳、驳回或忽略。",
};

function decisionTitle(d: any): string {
  if (d.kind === "term_link") return `「${d.data.term}」对应哪个实体`;
  if (d.kind === "review") return `${d.data.what ?? "复核"} ${d.data.title ?? ""}`.trim();
  if (d.kind === "rederive") return `重新综合：${d.data.title ?? ""}`;
  if (d.kind === "finding") return d.data.check_label ?? "巡检发现";
  if (d.kind === "constraint_unchecked") return `${d.data.op ?? "操作"} 前没有检查约束`;
  if (d.kind === "propagation_overflow") return "变化传播超过上限";
  return DECISION[d.kind] ?? d.kind;
}

export function Decisions() {
  const [f, setF] = useUrlState(DECISION_FILTERS);
  const kinds = list(f.kinds);
  const [picked, setPicked] = useState<string[]>([]);
  const [pickedArts, setPickedArts] = useState<string[]>([]);
  const [handoff, setHandoff] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [items, error, reload] = useLoad(() => call<any[]>("decision.list", { status: f.status || null }), [f.status]);
  const [recog, , reloadRecog] = useLoad(() => call<any>("extraction.recognitions", { dispatch: true }).catch(() => null), []);
  usePoll(reload);
  const all = items ?? [];
  const counts: Record<string, number> = Object.fromEntries(Object.keys(DECISION).map((k) => [k, all.filter((d: any) => d.kind === k).length]));
  const open = f.status === "open";
  // 待处理的巡检发现在下面的巡检栏按巡检运行分组显示（设计稿 08 D-22、§9），不混在队列里
  const showInspection = open && (!kinds.length || kinds.includes("finding"));
  const openFindings = all.filter((d: any) => d.kind === "finding");
  const shown = (kinds.length ? all.filter((d: any) => kinds.includes(d.kind)) : all).filter((d: any) => !open || d.kind !== "finding");
  const main = open ? shown.filter((d: any) => d.impact > 0) : shown;
  const low = open ? shown.filter((d: any) => d.impact <= 0) : [];
  const queue = [...main, ...low];
  const current = queue.find((d: any) => d.id === f.at) ?? queue[0] ?? null;
  const index = current ? queue.indexOf(current) : -1;
  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const toggleArt = (id: string) => setPickedArts(pickedArts.includes(id) ? pickedArts.filter((x) => x !== id) : [...pickedArts, id]);
  // 只有 AI 认为有问题或拿不准的算待决策；还没核对的是积压，折叠显示、不计数（设计稿 04 D-28）
  const recogAll = ((recog?.artifacts ?? []) as any[]);
  const recogRows = recogAll.filter((r) => r.level === "attention");
  const recogBacklog = recogAll.filter((r) => r.level !== "attention");
  const showRecog = open && (!kinds.length || kinds.includes("recognition"));
  const total = picked.length + pickedArts.length;
  const reviewable = (d: any) => d.status === "open" && d.kind === "review" && d.subject_id && /^(pg|edg|jdg)_/.test(d.subject_id);
  const pickable = queue.filter(reviewable);
  const allPicked = pickable.length > 0 && pickable.every((d: any) => picked.includes(d.subject_id));
  const go2 = (step: number) => {
    if (!queue.length) return;
    const next = queue[Math.max(0, Math.min(queue.length - 1, index + step))];
    setF({ at: next.id });
  };
  useEffect(() => {
    const row = current ? document.querySelector<HTMLElement>(`[data-nav-item="${current.id}"]`) : null;
    if (row) setCursor(row, true);
  }, [current?.id]);
  useShortcuts({ j: () => go2(1), k: () => go2(-1) });
  // 处理完一件：重新加载，并自动跳到下一件
  const done = () => {
    const next = queue[index + 1] ?? queue[index - 1];
    setF({ at: next?.id ?? "" });
    reload();
  };
  // 一次提交选中的识别块。普通复核任务仍带到 Agent 页，可查看并选择 Agent。
  const handOff = async () => {
    const parts: string[] = [];
    setSending(true);
    try {
      let runId: string | undefined;
      if (pickedArts.length) {
        const repeat = pickedArts.filter((id) => recogRows.some((r) => r.artifact_id === id && r.unchecked === 0));
        const { jobs, run } = await call<any>("extraction.ai_check", {
          artifact_ids: pickedArts, repeat_artifact_ids: repeat, dispatch: true,
        });
        runId = run?.id;
        setPickedArts([]);
        parts.push(runId || jobs.length ? `${pickedArts.length} 份原件已交给 AI 核对` : "没有可提交的识别块");
        if (jobs.length) {
          watchJobs(jobs.map((j: any) => j.id), (failures) => {
            reloadRecog();
            if (failures) setHandoff(`${failures} 份原件的核对未完成，可再次勾选重试`);
          });
        }
      }
      if (picked.length) {
        delegate(aiReviewPrompt(picked), runId);
        parts.push(`${picked.length} 项复核的任务已带到 Agent 页`);
        setPicked([]);
      } else if (runId) go("agent", runId);
      setHandoff(parts.join("；"));
      toast(parts.join("；"));
    } catch (e: any) {
      setHandoff([...parts, e.message].join("；"));
    } finally {
      setSending(false);
    }
  };
  const kindOptions: [string, string, number][] = [
    ...Object.entries(DECISION).map(([k, t]) => [k, t, counts[k] ?? 0] as [string, string, number]),
    ["recognition", "待确认的识别", recogRows.length],
  ];
  const row = (d: any) => (
    <li key={d.id} data-nav-item={d.id} className={current?.id === d.id ? "picked" : ""} onClick={(e) => { if (!(e.target as HTMLElement).closest("input, a")) setF({ at: d.id }); }}>
      <input type="checkbox" aria-label="选中这一件，交给 AI 复核" checked={picked.includes(d.subject_id)} disabled={!reviewable(d)} onChange={() => toggle(d.subject_id)} data-key="x" title={reviewable(d) ? "勾选后一起交给 AI 复核" : "这一类不能批量交给 AI"} />
      <span className="grow q-main">
        <a href={`#/decisions?${new URLSearchParams({ ...(f.kinds ? { kinds: f.kinds } : {}), ...(f.status !== "open" ? { status: f.status } : {}), at: d.id })}`} data-key="open" onClick={(e) => { e.preventDefault(); setF({ at: d.id }); }} className="clip">{decisionTitle(d)}</a>
        <span className="muted small-text clip">{d.subject_id ? <EntryName id={d.subject_id} /> : null} · 影响 {d.impact} · <Time value={d.created_at} /></span>
      </span>
      <span className={`tag ${d.kind === "constraint_unchecked" || d.kind === "propagation_overflow" ? "bad" : ""}`}>{DECISION[d.kind] ?? d.kind}</span>
    </li>
  );
  return (
    <div className="decisions-page">
      <header className="page-head tight">
        <h1>待决策</h1>
        <div className="segctl" role="group" aria-label="按种类">
          <button type="button" aria-pressed={!kinds.length} className={!kinds.length ? "on" : ""} onClick={() => setF({ kinds: "", at: "" })}>全部 <span className="count">{all.length + (open ? recogRows.length : 0)}</span></button>
          {kindOptions.filter(([k, , n]) => n > 0 || kinds.includes(k)).map(([k, t, n]) => (
            <button key={k} type="button" aria-pressed={kinds.includes(k)} className={kinds.includes(k) ? "on" : ""} onClick={() => setF({ kinds: unlist(kinds.includes(k) ? kinds.filter((x) => x !== k) : [...kinds, k]), at: "" })}>
              {t} <span className="count">{n}</span>
            </button>
          ))}
        </div>
        <div className="segctl" role="radiogroup" aria-label="状态">
          {STATUS.map(([k, t]) => (
            <button key={k || "all"} type="button" role="radio" aria-checked={f.status === k} className={f.status === k ? "on" : ""} onClick={() => setF({ status: k, at: "" })}>{t}</button>
          ))}
        </div>
        <span className="muted small-text views">按影响范围排序；不阻塞导入和写入</span>
      </header>
      <ErrorBox error={error} />
      {!items && !error && <Loading rows={3} />}
      {items && (
        <div className="decision-grid">
          <section className="panel queue" aria-label="队列">
            {pickable.length > 0 && (
              <label className="check queue-all">
                <input type="checkbox" checked={allPicked} onChange={() => setPicked(allPicked ? [] : pickable.map((d: any) => d.subject_id))} />
                <span className="grow">全选能交给 AI 的 {pickable.length} 件</span>
                {picked.length > 0 && <span className="muted">已选 {picked.length}</span>}
              </label>
            )}
            {queue.length === 0 && !(showRecog && recogRows.length) && <Empty compact icon="check">{open ? "没有待处理的事。" : "没有符合条件的待决策项。"}</Empty>}
            <ul className="qrows">{main.map(row)}</ul>
            {low.length > 0 && (
              <details className="low-impact" open={low.some((d: any) => d.id === current?.id)}>
                <summary>低影响（{low.length} 项）：错了只影响浏览，不影响判断层</summary>
                <ul className="qrows">{low.map(row)}</ul>
              </details>
            )}
            {showRecog && recogRows.length > 0 && <Recognitions rows={recogRows} allowed={recog?.ai_allowed} picked={pickedArts} onPick={toggleArt} />}
            {showRecog && recogBacklog.length > 0 && (
              <details className="low-impact">
                <summary>还没核对的识别（{recogBacklog.length} 份原件）：积压，不算待决策</summary>
                <label className="check queue-all">
                  <input type="checkbox" disabled={!!recog?.ai_allowed}
                    checked={recogBacklog.every((r) => pickedArts.includes(r.artifact_id))}
                    onChange={(e) => {
                      const ids = recogBacklog.map((r) => r.artifact_id);
                      setPickedArts(e.target.checked ? [...new Set([...pickedArts, ...ids])] : pickedArts.filter((x) => !ids.includes(x)));
                    }} />
                  <span className="grow">全选这 {recogBacklog.length} 份，交给 AI 核对（AI 认为一致的不会再出现）</span>
                </label>
                <Recognitions rows={recogBacklog} allowed={recog?.ai_allowed} picked={pickedArts} onPick={toggleArt} quiet />
              </details>
            )}
            <div className="queue-foot">
              {handoff && <p className="small-text">{handoff}</p>}
              <span className="grow small-text">{total > 0 ? `已选 ${total} 件` : "勾选后可以一起交给 AI"}</span>
              <button type="button" className="primary" disabled={sending || total === 0} onClick={handOff} title="按 Agent 全局启动方式提交复核">
                交给 AI 复核（{total}）
              </button>
            </div>
            <p className="muted small-text queue-note">只有"交给 AI"可以批量做；确认和关闭要一件一件来。</p>
          </section>
          <section className="panel detail" aria-label="这一件">
            {current ? (
              <DecisionItem key={current.id} d={current} reload={reload} done={done} position={`第 ${index + 1} / ${queue.length} 件`} />
            ) : (
              <Empty icon="check">{open ? "没有等你处理的事。有新的会出现在这里和左边导航的\"待决策\"上。" : "选左边的一件查看。"}</Empty>
            )}
          </section>
        </div>
      )}
      {showInspection && <InspectionSection findings={openFindings} reloadFindings={reload} />}
      {open && <Sample />}
    </div>
  );
}

function watchJobs(ids: string[], done: (failures: number) => void) {
  const left = new Set(ids);
  let failures = 0;
  const tick = async () => {
    try {
      const st = await call<any>("models.status");
      for (const id of left) {
        const job = st.jobs.find((j: any) => j.id === id);
        if (job && !["done", "failed", "cancelled"].includes(job.status)) continue;
        if (!job || job.status !== "done") failures += 1;
        left.delete(id);
      }
      if (left.size) window.setTimeout(tick, 2000);
      else done(failures);
    } catch {
      done(failures + left.size);
    }
  };
  window.setTimeout(tick, 2000);
}

// 待确认的识别（D-25）：OCR / AI 识别、还没有人确认的段落与公式，每份原件一行；被判断引用过的排在前面
function Recognitions({ rows, allowed, picked, onPick, quiet }: { rows: any[]; allowed?: string | null; picked: string[]; onPick: (id: string) => void; quiet?: boolean }) {
  return (
    <div className="decision recognition">
      {!quiet && (
        <div className="decision-head">
          <Tag tone="warn">待确认的识别</Tag>
          <span className="muted small-text">{allowed ? `不能交给 AI：${allowed}` : "AI 认为有问题或拿不准的块；确认在原件页，可逐块或整组确认"}</span>
        </div>
      )}
      <ul className="plain">
        {rows.map((r) => (
          <li key={r.artifact_id} className="row tight">
            <input type="checkbox" checked={picked.includes(r.artifact_id)} onChange={() => onPick(r.artifact_id)} disabled={!!allowed} title={r.unchecked === 0 ? "勾选后重新复核识别" : "勾选后交给 AI 复核未核对的识别"} />
            <IdLink id={r.artifact_id} name={r.title} />
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
            {r.unchecked === 0 && <span className="muted small-text">可勾选重新复核</span>}
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
            <IdLink id={p.id} name={p.title} /> <span className="muted">{PAGE_TYPE[p.type] ?? p.type}</span>{" "}
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

// 一件待决策：是什么 → 为什么要你看 → 下一步。关闭（不处理）收在最后，要写理由
function DecisionItem({ d, reload, done, position }: { d: any; reload: () => void; done: () => void; position: string }) {
  const [closeReason, setCloseReason] = useState("");
  const [newName, setNewName] = useState(d.data.term ?? "");
  const [newKind, setNewKind] = useState("device");
  const open = d.status === "open";
  const reviewable = d.kind === "review" && d.subject_id && /^(pg|edg|jdg|art)_/.test(d.subject_id);
  return (
    <article className={`decision-card ${d.kind}`}>
      <header className="decision-top">
        <Tag tone={d.kind === "constraint_unchecked" || d.kind === "propagation_overflow" ? "bad" : "warn"}>{DECISION[d.kind] ?? d.kind}</Tag>
        <span className="mono muted">{d.id}</span>
        <span className="muted small-text">影响 {d.impact} · <Time value={d.created_at} /></span>
        {d.data.requested && <Tag>请人复核</Tag>}
        {!open && <Tag>{d.status === "resolved" ? (d.data.resolution?.by_ai ? "已由 AI 处理" : "已处理") : "已关闭"}</Tag>}
        <span className="grow" />
        <span className="muted small-text">{position} <kbd>j</kbd> <kbd>k</kbd></span>
      </header>
      <ol className="steps">
        <li>
          <p className="label">是什么</p>
          <p className="step-title">{decisionTitle(d)}</p>
          {d.subject_id && <p><IdLink id={d.subject_id} /></p>}
          {d.kind === "term_link" && (
            <p>
              叫法「{d.data.term}」：{d.data.reason}
              {d.data.excerpt && <span className="muted">（原文：{d.data.excerpt}）</span>}
            </p>
          )}
          {d.kind === "review" && (
            <>
              <p>{d.data.reason ?? ""} {d.data.note && <span className="muted">（{d.data.note}）</span>}</p>
              {(d.data.notes ?? []).map((n: any, i: number) => (
                <p key={i} className="small-text">
                  <Tag tone={n.verdict === "reject" ? "bad" : n.verdict === "confirm" ? "good" : "muted"}>
                    {n.model ? `AI·${n.model}` : n.by} {n.verdict ? REVIEW_VERDICT[n.verdict] ?? n.verdict : "请人复核"}
                  </Tag>{" "}
                  {n.reason ?? n.note}
                </p>
              ))}
            </>
          )}
          {d.kind === "rederive" && <p>{d.data.reason}</p>}
          {d.kind === "finding" && (
            <p>
              {d.data.summary}
              {d.data.resolution?.reason && <span className="muted">（处理说明：{d.data.resolution.reason}）</span>}
            </p>
          )}
          {d.kind === "constraint_unchecked" && (
            <p>{d.data.actor_id} 执行 {d.data.op} 前没有检查约束：{d.data.constraints.map((c: any) => c.text).join("；")}</p>
          )}
          {d.kind === "propagation_overflow" && <p>传播超过上限，{d.data.unchecked.length} 个条目标为"未核查"：{d.data.reason}</p>}
        </li>
        <li>
          <p className="label">为什么要你看</p>
          <p>{WHY[d.kind] ?? "这件事需要人来决定。"}</p>
        </li>
        <li>
          <p className="label">下一步</p>
          {d.kind === "term_link" && open && (
            <>
              <div className="row">
                {d.data.candidates.map((c: any) => (
                  <Action key={c.id} className="primary" label={`是 ${c.kind}「${c.name}」`} done="已连接到实体" run={async () => { await call("term.decide", { decision_id: d.id, entity_id: c.id }); done(); }} />
                ))}
              </div>
              <div className="row">
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="新实体名称" aria-label="新实体名称" />
                <input value={newKind} onChange={(e) => setNewKind(e.target.value)} placeholder="类型" aria-label="新实体类型" />
                <Action label="新建实体并连接" done="已新建实体并连接" run={async () => { await call("term.decide", { decision_id: d.id, new_entity: { kind: newKind, name: newName } }); done(); }} />
              </div>
            </>
          )}
          {reviewable && (open || !d.subject_id.startsWith("art_")) && <ReviewBox itemId={d.subject_id} reload={reload} compact aiOnly={!open} />}
          {d.kind === "rederive" && (
            <div className="row">
              <button type="button" className="primary" onClick={() => delegate(rederivePrompt({ id: d.subject_id, title: d.data.title }))}>
                {open ? "交给 Agent 重新综合" : "再次交给 Agent 综合"}
              </button>
              <span className="muted small-text">重新综合由你点了才开始，会带到 Agent 页确认后再启动。</span>
            </div>
          )}
          {(d.kind === "constraint_unchecked" || d.kind === "propagation_overflow" || d.kind === "finding") && d.subject_id && (
            <p className="muted small-text">打开 <IdLink id={d.subject_id} /> 核对后，在下面写明处理说明并关闭。</p>
          )}
          {open && (
            <details className="close-box" open={!reviewable && d.kind !== "term_link" && d.kind !== "rederive"}>
              <summary>{reviewable || d.kind === "term_link" || d.kind === "rederive" ? "都不合适：关闭这件事并写理由" : "处理完：写明理由并关闭"}</summary>
              <div className="row">
                <input className="grow" value={closeReason} onChange={(e) => setCloseReason(e.target.value)} placeholder="关闭理由" aria-label="关闭理由" />
                <Action label="关闭" done="已关闭" run={async () => { await call("decision.dismiss", { decision_id: d.id, reason: closeReason || "不处理" }); done(); }} />
              </div>
            </details>
          )}
        </li>
      </ol>
    </article>
  );
}
