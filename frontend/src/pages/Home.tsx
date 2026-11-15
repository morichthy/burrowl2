// 首页是"今日"：最上面一张墨色大卡写着有几件事等你处理（没有时也明说）；
// 然后是原件 → 判断 → 框架三张数字卡；下面左边是大尺寸的阅读会话，右边是最近动态和最近打开。
// 运行中的 agent 与系统状态（含重启、停止）在底部状态栏里，见 shell/SystemStatus.tsx。
// 数字都来自 stats.overview（只读汇总），这里不推导地位。
import { useState } from "react";
import { call } from "../api";
import { DECISION, JUDGMENT_KIND, REVIEW_VERDICT, SOURCE } from "../labels";
import { href, hrefWith } from "../router";
import { Icon } from "../shell/icons";
import { openQuickNote } from "../shell/QuickNote";
import { loadRecent } from "../shell/recent";
import { Stamp, layerOf } from "../shell/Stamp";
import { openSystemStatus } from "../shell/SystemStatus";
import { EntryName } from "../entryLabels";
import { ReadingCard } from "./Reading";
import { Empty, ErrorBox, IdLink, Loading, Panel, dayLabel, useLoad, usePoll } from "../ui";
import { UndoButton, RestoreButton } from "../shell/Undo";

/* eslint-disable @typescript-eslint/no-explicit-any */

// 待你处理：每类一行，只列有数量的；去处理的页面按类型分流
const TODO: { kind: string; hint: string; to: string }[] = [
  { kind: "constraint_unchecked", hint: "AI 操作前没有检查约束，请确认是否有影响", to: hrefWith("decisions", { kinds: "constraint_unchecked" }) },
  { kind: "review", hint: "AI 写的框架页或推断的关系，等你确认或驳回", to: hrefWith("decisions", { kinds: "review" }) },
  { kind: "term_link", hint: "叫法对不上实体，等你决定合并还是分开", to: hrefWith("decisions", { kinds: "term_link" }) },
  { kind: "rederive", hint: "框架页的依据变了，内容可能过时，需要重新综合", to: hrefWith("pages", { fresh: "inputs_changed" }) },
  { kind: "propagation_overflow", hint: "变化传播超过上限，部分条目未核查", to: hrefWith("decisions", { kinds: "propagation_overflow" }) },
  { kind: "finding", hint: "巡检员提出的问题；复核员确认的排在前面", to: hrefWith("decisions", { kinds: "finding" }) },];

type TodoRow = { kind: string; label: string; hint: string; to: string; count: number; onClick?: () => void };

function todoRows(stats: any, check: any, inspection?: any): TodoRow[] {
  const counts: Record<string, number> = stats?.decisions ?? {};
  const known = new Set(TODO.map((t) => t.kind));
  const rows: TodoRow[] = TODO.filter((t) => counts[t.kind]).map((t) => ({ ...t, label: DECISION[t.kind] ?? t.kind, count: counts[t.kind] }));
  // 服务端新加的待决策种类：也列出来，不漏
  for (const [kind, n] of Object.entries(counts)) {
    if (n && !known.has(kind)) rows.push({ kind, label: DECISION[kind] ?? kind, hint: "在待决策页处理", to: hrefWith("decisions", { kinds: kind }), count: n });
  }
  // 定期巡检（设计稿 08 D-01）：定时只准备巡检包，由你点"开始巡检"
  const insp = inspection?.latest;
  if (insp && insp.status === "ready" && insp.tasks) {
    rows.unshift({
      kind: "inspection", label: "本期巡检已准备好", count: insp.tasks,
      hint: `${insp.suspicious} 项可疑、${insp.explore} 处探索样本；在待决策页点开始巡检才会调用巡检员 agent`, to: href("decisions"),
    });
  }
  // 待消化的外部材料（设计稿 09 D-17）：不是待决策项，由你点按钮交给 AI 消化
  if (inspection?.digest_pending) {
    rows.push({
      kind: "digest", label: "外部材料待消化", count: inspection.digest_pending,
      hint: "登记了还没提取论断的文献与外部资料；在待决策页交给 AI 消化或复制提示", to: href("decisions"),
    });
  }
  // 原件检查不是待决策项：结果来自上次检查，确认后把新文件登记为新版本
  const problems = (check?.changed ?? 0) + (check?.missing ?? 0);
  if (problems) {
    rows.unshift({
      kind: "artifact_check", label: "外部原件已变化或丢失", count: problems,
      hint: "在底部状态栏的系统状态里查看是哪些；确认是新版本后登记为新版本", to: "#/", onClick: openSystemStatus,
    });
  }
  return rows;
}

export function Home() {
  const [activity, aError, reloadActivity] = useLoad(() => call<any[]>("activity.recent", { limit: 60 }), []);
  const [stats, sError, reloadStats] = useLoad(() => call<any>("stats.overview"), []);
  const [check, cError, reloadCheck] = useLoad(() => call<any>("artifact.check_status"), []);
  const [inspection, , reloadInspection] = useLoad(() => call<any>("inspection.status").catch(() => null), []);
  const [sys] = useLoad(() => call<any>("system.status").catch(() => null), []);
  usePoll(reloadInspection, 30000);
  usePoll(reloadActivity);
  usePoll(reloadStats);
  usePoll(reloadCheck, 30000);
  const todos = todoRows(stats, check, inspection);
  const now = new Date();
  return (
    <div className="dash">
      <header className="page-head">
        <div>
          <p className="eyebrow">
            {now.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" })}
            {sys?.data_name && <> · 数据目录 {sys.data_name}</>}
          </p>
          <h1>今日</h1>
        </div>
        <div className="actions">
          <button type="button" onClick={() => openQuickNote({ mode: "artifact" })} title="登记原件（不离开首页）"><Icon name="plus" size={15} />登记原件</button>
          <button type="button" onClick={() => openQuickNote({ mode: "judgment" })} title="写判断（n）"><Icon name="record" size={15} />写判断</button>
          <a className="button" href={href("search")} title="检索（g s）"><Icon name="search" size={15} />检索</a>
        </div>
      </header>
      <ErrorBox error={sError ?? cError} />
      {stats ? <TodoHero rows={todos} /> : !sError && <Loading rows={1} />}
      {stats && <Columns stats={stats} />}
      <div className="dash-grid">
        <ReadingCard limit={12} large />
        <div className="dash-side">
          <Feed activity={activity} error={aError} daily={stats?.daily} />
          <RecentCard />
        </div>
      </div>
    </div>
  );
}

// 待你处理：墨色大卡。有事时左边是总数和"按顺序处理"，右边每类一行；没事时明说没有
function TodoHero({ rows }: { rows: TodoRow[] }) {
  const total = rows.reduce((s, t) => s + t.count, 0);
  if (!rows.length) {
    return (
      <section className="todo-hero calm" aria-label="待你处理">
        <span className="todo-ok" aria-hidden="true"><Icon name="check" size={30} /></span>
        <div className="grow">
          <p className="todo-title">没有等你处理的事</p>
          <p className="soft">只有你能做的决定会出现在这里，左边导航的"待决策"上也会显示数字。</p>
        </div>
        <a className="button inv" href={href("search")}>去检索 <kbd>g s</kbd></a>
      </section>
    );
  }
  return (
    <section className="todo-hero" aria-label="待你处理">
      <div className="todo-total">
        <strong>{total}</strong>
        <div>
          <p className="todo-title">件事等你处理</p>
          <p className="soft">只有你能做的决定都在这里</p>
          <a className="button inv" href={href("decisions")}>按顺序处理 <kbd>g d</kbd></a>
        </div>
      </div>
      <ul className="todo-rows">
        {rows.map((t) => (
          <li key={t.kind}>
            <a href={t.to} onClick={t.onClick ? (e) => { e.preventDefault(); t.onClick?.(); } : undefined}>
              <strong>{t.count}</strong>
              <b>{t.label}</b>
              <span className="soft">{t.hint}</span>
              <span className="go">去处理 →</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

// 三列：原件 → 判断 → 框架，各一张数字卡；中间的箭头说明它们的关系（作依据、综合成）
function Columns({ stats }: { stats: any }) {
  const l = stats.ledger ?? {};
  const j = stats.judgments ?? {};
  const pages = stats.pages ?? {};
  const bySource = Object.entries((stats.artifacts_by_source ?? {}) as Record<string, number>).filter(([, n]) => n > 0);
  const stale = pages.freshness?.inputs_changed ?? 0;
  const unchecked = pages.freshness?.unchecked ?? 0;
  const unreviewed = pages.review?.ai_generated ?? 0;
  const chip = (n: number, text: string, tone = "", to?: string) => (n ? (to ? <a key={text} className={`tag ${tone}`} href={to}>{text} {n}</a> : <span key={text} className={`tag ${tone}`}>{text} {n}</span>) : null);
  return (
    <section className="columns" aria-label="三列概览">
      <a className="col-card" href={hrefWith("entries", { kind: "artifact" })} title="登记的原件、事实记录（不含过程日志和读取日志）">
        <span className="col-head"><Stamp layer="original" /><b>原件</b><small>原文如实 · 可作依据</small></span>
        <strong className="num">{(l.artifacts ?? 0) + (l.records ?? 0)}</strong>
        <span className="col-chips">
          {chip(l.artifacts ?? 0, "原件")}
          {chip(l.records ?? 0, "事实记录")}
          {bySource.map(([k, n]) => chip(n, SOURCE[k] ?? k))}
        </span>
      </a>
      <span className="col-flow" aria-hidden="true">作依据<Icon name="chevron" /></span>
      <a className="col-card" href={href("entries")} title="结论、思路、约束：只收稀缺内容（本地实证、跨来源的关系、读的人加的判断）">
        <span className="col-head"><Stamp layer="judgment" /><b>判断</b><small>谁依据什么认为了什么 · 可作依据</small></span>
        <strong className="num">{j.total ?? 0}</strong>
        <span className="col-chips">
          {chip(j.local_only ?? 0, "本地实证")}
          {chip(j.thought ?? 0, "思路")}
          {chip(j.by_author?.human ?? 0, "人写")}
          {chip(j.by_author?.ai ?? 0, "AI 写")}
          {chip(j.with_external ?? 0, "有外部依据")}
          {chip(j.inferred_only ?? 0, "仅推断")}
          {chip(j.replaced ?? 0, "被替代", "warn", hrefWith("entries", { status: "replaced" }))}
          {chip(j.opposed ?? 0, "有相反判断", "bad")}
        </span>
      </a>
      <span className="col-flow" aria-hidden="true">综合成<Icon name="chevron" /></span>
      <a className="col-card" href={href("pages")} title="实体页、概念页、综合页、要点；可以再生，永远不能作为依据">
        <span className="col-head"><Stamp layer="framework" /><b>框架</b><small>可再生 · 永远不能作依据</small></span>
        <strong className="num">{pages.total ?? 0}<small> 页</small></strong>
        <span className="col-chips">
          {chip(pages.points ?? 0, "要点", "", hrefWith("pages", { types: "point" }))}
          {chip(stale, "输入已变化", "warn", hrefWith("pages", { fresh: "inputs_changed" }))}
          {chip(unchecked, "未核查", "warn")}
          {chip(unreviewed, "AI 生成未复核")}
          {chip(stats.entities ?? 0, "对象")}
          {chip(stats.edges?.total ?? 0, "关系")}
          {!stale && !unchecked && !unreviewed && pages.total ? <span className="tag good">都是最新的</span> : null}
        </span>
      </a>
    </section>
  );
}

function localDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const ACTIVITY_LABEL: Record<string, [string, string]> = {
  artifact: ["登记原件", "original"],
  record: ["写事实记录", "original"],
  page: ["写框架页", "framework"],
  agent_run: ["运行 Agent", ""],
  "undo.apply": ["撤销", ""],
  "undo.restore": ["恢复撤销", ""],
};

function activityKind(kind: string): [string, string] {
  if (kind.startsWith("judgment.")) {
    const k = kind.slice(9);
    return [["correction", "retraction", "defect"].includes(k) ? (JUDGMENT_KIND[k] ?? "判断") : `写${JUDGMENT_KIND[k] ?? "判断"}`, "judgment"];
  }
  if (kind.startsWith("review.")) return [`复核 · ${REVIEW_VERDICT[kind.slice(7)] ?? kind.slice(7)}`, ""];
  return ACTIVITY_LABEL[kind] ?? [kind, ""];
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

// 最近动态：按天分组，可以只看人或只看 AI；同一条目上连续的同类操作（如 AI 逐块复核一份 PDF）合成一行，点开看每一次
function Feed({ activity, error, daily }: { activity: any[] | null; error: string | null; daily?: Record<string, number> }) {
  const [who, setWho] = useState<"" | "human" | "ai">("");
  const items = (activity ?? []).filter((a) => !who || (a.actor ?? "").startsWith(`${who}:`));
  const days = Object.entries(daily ?? {}) as [string, number][];
  const max = Math.max(1, ...days.map(([, n]) => n));
  const jump = (day: string) => document.getElementById(`day-${day}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  return (
    <Panel
      className="feed"
      title={<>最近动态 {days.length > 0 && (
        <span className="spark" role="group" aria-label="近两周每天新增条目数">
          {days.map(([day, n]) => (
            <button type="button" key={day} title={`${day.slice(5)}：新增 ${n} 条（点击跳到这一天）`} aria-label={`${day} 新增 ${n} 条`} onClick={() => jump(day)}>
              <i style={{ height: `${n ? Math.max(18, (n / max) * 100) : 8}%` }} className={n ? "" : "zero"} />
            </button>
          ))}
        </span>
      )}</>}
      actions={
        <div className="segctl" role="radiogroup" aria-label="谁做的">
          {([["", "全部"], ["human", "你"], ["ai", "AI"]] as const).map(([k, t]) => (
            <button key={k} type="button" role="radio" aria-checked={who === k} className={who === k ? "on" : ""} onClick={() => setWho(k)}>{t}</button>
          ))}
        </div>
      }
    >
      <ErrorBox error={error} />
      {!activity && !error && <Loading lines rows={6} />}
      {activity && (items.length ? <Timeline items={items} /> : <Empty icon="clock">{who ? "这段时间里没有这一方的操作。" : "还没有记录。登记原件、写判断或让 agent 工作后会出现在这里。"}</Empty>)}
      <p className="feed-foot"><a href={href("entries")}>浏览全部条目 →</a></p>
    </Panel>
  );
}

function Timeline({ items }: { items: any[] }) {
  const days = new Map<string, { id: string; runs: any[][] }>();
  for (const item of items) {
    const d = new Date(item.at);
    const key = dayLabel(d);
    const group = days.get(key) ?? { id: Number.isNaN(d.getTime()) ? "unknown" : localDay(d), runs: [] };
    const last = group.runs[group.runs.length - 1];
    const same = last && last[0].id === item.id && last[0].kind.split(".")[0] === item.kind.split(".")[0] && item.kind !== "agent_run";
    if (same) last.push(item);
    else group.runs.push([item]);
    days.set(key, group);
  }
  return (
    <div className="timeline">
      {[...days.entries()].map(([day, { id, runs }]) => (
        <section key={day} id={`day-${id}`}>
          <h4>{day}</h4>
          <ul className="activity">
            {runs.map((run) => <TimelineRow key={run[0].kind + run[0].id + run[0].at} run={run} />)}
          </ul>
        </section>
      ))}
    </div>
  );
}

function TimelineRow({ run }: { run: any[] }) {
  const [open, setOpen] = useState(false);
  const item = run[0];
  const [label, layer] = run.length > 1 && item.kind.startsWith("review.") ? ["复核", ""] : activityKind(item.kind);
  const counts: Record<string, number> = {};
  for (const r of run) counts[activityKind(r.kind)[0]] = (counts[activityKind(r.kind)[0]] ?? 0) + 1;
  const stampLayer = layer || (item.kind === "agent_run" ? "" : layerOf(item.id));
  return (
    <li className={item.kind.endsWith("correction") || item.kind.endsWith("retraction") || item.kind.endsWith("defect") ? "tone-bad" : ""}>
      <time title={item.at}>{clock(item.at)}</time>
      {item.kind === "agent_run" ? <span className="stamp sm none" aria-hidden="true"><Icon name="agent" size={12} /></span> : <Stamp layer={stampLayer} small />}
      <span className="what">
        {item.kind === "agent_run" ? <a href={href("agent", item.id)}>{item.summary}</a> : <IdLink id={item.id} />}
        {run.length > 1 ? (
          <button type="button" className="link small-text" aria-expanded={open} onClick={() => setOpen(!open)}>
            {Object.entries(counts).map(([k, n]) => `${k.replace("复核 · ", "")} ${n}`).join("、")}，共 {run.length} 次（{clock(run[run.length - 1].at)}–{clock(item.at)}）{open ? " 收起" : " 展开"}
          </button>
        ) : (
          (item.kind.startsWith("review.") || item.kind.startsWith("undo.")) && item.summary && <span className="muted small-text">{item.summary}</span>
        )}
        {open && (
          <ul className="run-detail">
            {run.map((r, i) => (
              <li key={i}><time>{clock(r.at)}</time> <span className="muted">{activityKind(r.kind)[0]}</span> {r.summary}</li>
            ))}
          </ul>
        )}
        {item.kind === "undo.apply" && item.undo_id ? (item.restored ? <span className="tag">已恢复</span> : <RestoreButton undoId={item.undo_id} />) : <UndoButton at={run[run.length - 1].at} label={item.summary ?? item.id} />}
      </span>
      <span className="tag">{actorLabel(item.actor)}</span>
      <span className="kind">{label}</span>
    </li>
  );
}

// 最近打开：本机浏览器记住的最近 12 条（快速跳转里也有）
function RecentCard() {
  const ids = loadRecent().slice(0, 6);
  return (
    <Panel title="最近打开">
      {ids.length === 0 ? (
        <Empty compact icon="clock">打开过的条目会出现在这里。</Empty>
      ) : (
        <ul className="recent-list">
          {ids.map((id) => (
            <li key={id}>
              <a href={href("entry", id)} title={id}><Stamp layer={layerOf(id)} small /><span><EntryName id={id} /></span></a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function actorLabel(actor: string): string {
  if (!actor) return "";
  if (actor.startsWith("ai:")) return "AI";
  if (actor.startsWith("human:")) return "人";
  if (actor.startsWith("system")) return "系统";
  if (actor.startsWith("v1:")) return "旧版";
  return actor;
}
