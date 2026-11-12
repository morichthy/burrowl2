// 首页是"今日"：最上面一张墨色大卡写着有几件事等你处理（没有时也明说）；
// 然后是原件 → 判断 → 框架三张数字卡；下面左边是最近动态，右边是进行中、最近打开和系统状态。
// 数字都来自 stats.overview（只读汇总），这里不推导地位。
import { useState } from "react";
import { call } from "../api";
import { DECISION, JUDGMENT_KIND, REVIEW_VERDICT, SOURCE } from "../labels";
import { delegate, href, hrefWith } from "../router";
import { aiReviewPrompt } from "../review";
import { Icon } from "../shell/icons";
import { openQuickNote } from "../shell/QuickNote";
import { loadRecent } from "../shell/recent";
import { Stamp, layerOf } from "../shell/Stamp";
import { copyText } from "../shell/toast";
import { EntryName } from "../entryLabels";
import { Action, Dot, Empty, ErrorBox, IdLink, Loading, Panel, Time, dayLabel, useLoad, usePoll } from "../ui";

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

const scrollToStatus = () => document.getElementById("status")?.scrollIntoView({ behavior: "smooth", block: "start" });

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
      hint: "在下面的系统状态里查看是哪些；确认是新版本后登记为新版本", to: "#/", onClick: scrollToStatus,
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
        <Feed activity={activity} error={aError} daily={stats?.daily} />
        <div className="dash-side">
          <OngoingCard />
          <RecentCard />
          <StatusCard check={check} reloadCheck={reloadCheck} />
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
      <a className="col-card" href={href("entries")} title="结论、过程、规定与系统记录">
        <span className="col-head"><Stamp layer="judgment" /><b>判断</b><small>谁依据什么认为了什么 · 可作依据</small></span>
        <strong className="num">{j.total ?? 0}</strong>
        <span className="col-chips">
          {chip(j.by_author?.human ?? 0, "人写")}
          {chip(j.by_author?.ai ?? 0, "AI 写")}
          {chip(j.with_external ?? 0, "有外部依据")}
          {chip(j.inferred_only ?? 0, "仅推断")}
          {chip(j.replaced ?? 0, "被替代", "warn", hrefWith("entries", { status: "replaced" }))}
          {chip(j.opposed ?? 0, "有相反判断", "bad")}
        </span>
      </a>
      <span className="col-flow" aria-hidden="true">综合成<Icon name="chevron" /></span>
      <a className="col-card" href={href("pages")} title="实体页、概念页、综合页；可以再生，永远不能作为依据">
        <span className="col-head"><Stamp layer="framework" /><b>框架</b><small>可再生 · 永远不能作依据</small></span>
        <strong className="num">{pages.total ?? 0}<small> 页</small></strong>
        <span className="col-chips">
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
          item.kind.startsWith("review.") && item.summary && <span className="muted small-text">{item.summary}</span>
        )}
        {open && (
          <ul className="run-detail">
            {run.map((r, i) => (
              <li key={i}><time>{clock(r.at)}</time> <span className="muted">{activityKind(r.kind)[0]}</span> {r.summary}</li>
            ))}
          </ul>
        )}
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

function ago(iso: string | null | undefined): string {
  if (!iso) return "从未";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  if (min < 48 * 60) return `${Math.round(min / 60)} 小时前`;
  return `${Math.round(min / 1440)} 天前`;
}

// 状态：外部原件检查、索引覆盖、工作台服务（重启与停止在这里，升级后用于加载新版本）、当前连接的数据目录
function StatusCard({ check, reloadCheck }: { check: any; reloadCheck: () => void }) {
  const [info, infoError] = useLoad(() => call<any>("server.info"), []);
  const [health, , reloadHealth] = useLoad(() => call<any>("index.health"), []);
  // 后台重建索引、补建向量时每 3 秒刷新进度，平时每分钟（设计稿 06 D-22）
  const busyIndex = health?.units?.rebuild?.state === "running" || health?.vectors?.state === "building";
  usePoll(reloadHealth, busyIndex ? 3000 : 60000);
  const [checking, setChecking] = useState(false);
  const [phase, setPhase] = useState<"idle" | "restarting" | "stopped" | "timeout">("idle");
  const [fail, setFail] = useState<string | null>(null);
  const [showProblems, setShowProblems] = useState(false);

  const runCheck = async () => {
    setChecking(true);
    setFail(null);
    try {
      await call("artifact.check");
      reloadCheck();
    } catch (e: any) {
      setFail(e.message);
    } finally {
      setChecking(false);
    }
  };
  const rebuild = async () => {
    setFail(null);
    try {
      await call("index.rebuild", { background: true });
      reloadHealth();
    } catch (e: any) {
      setFail(e.message);
    }
  };
  const restart = async () => {
    setFail(null);
    try {
      const result = await call<any>("server.restart");
      setPhase("restarting");
      // 新进程等旧进程退出后接管同一网址；启动时间变了说明已是新进程，刷新页面加载新前端
      for (let i = 0; i < 90; i++) {
        await new Promise((r) => window.setTimeout(r, 1000));
        try {
          const now = await call<any>("server.info");
          if (now.started_at && now.started_at !== result.started_before) {
            window.location.reload();
            return;
          }
        } catch {
          // 重启期间连接失败是正常的
        }
      }
      setPhase("timeout");
    } catch (e: any) {
      setFail(e.message);
    }
  };
  const stop = async () => {
    if (!window.confirm("停止工作台？之后运行 burrowl start，或从开始菜单打开“burrowl 工作台”。")) return;
    try {
      await call("server.stop");
      setPhase("stopped");
    } catch (e: any) {
      setFail(e.message);
    }
  };

  const problems = check?.problems ?? [];
  const checkTone = checking ? "accent pulse" : !check?.checked_at ? "muted" : check.missing ? "bad" : check.changed ? "warn" : "good";
  const checkText = checking
    ? "正在检查…"
    : !check
      ? "…"
      : !check.referenced_total
        ? "没有外部原件"
        : !check.checked_at
          ? `${check.referenced_total} 份，尚未检查`
          : problems.length
            ? `${check.changed ? `${check.changed} 份已变化` : ""}${check.changed && check.missing ? "，" : ""}${check.missing ? `${check.missing} 份已丢失` : ""}`
            : `${check.checked} 份全部一致`;
  const schedule = check?.schedule;
  const job = health?.units?.rebuild;
  const rebuilding = job?.state === "running";
  const stale = health && health.units && !health.units.current;
  const vec = health?.vectors;
  // 指示灯：只有索引按当前设置建成、向量也补完（或没启用）才是绿灯。
  // 重建中、向量补建中是蓝色呼吸灯（结果可能不全，但能照常用）；需要处理的问题是黄灯
  const vecBuilding = vec?.state === "building";
  const vecPct = vecBuilding && vec.total ? Math.floor((vec.done / vec.total) * 100) : 0;
  const indexTone = !health
    ? "muted"
    : rebuilding || vecBuilding
      ? "accent pulse"
      : health.missing || stale || job?.state === "failed" || vec?.state === "missing" || vec?.state === "error"
        ? "warn"
        : "good";
  const indexText = !health
    ? "…"
    : rebuilding
      ? `正在重建 ${job.done} / ${job.total || "…"}`
      : stale
        ? "需要按新的检索单元长度重建"
        : health.missing
          ? `缺 ${health.missing} 条`
          : vecBuilding
            ? `完整，向量补建中 ${vecPct}%`
            : "完整";

  return (
    <Panel id="status" title="系统状态">
      <ErrorBox error={infoError ?? fail} />
      {phase === "restarting" && <div className="notice">正在重启，完成后页面会自动刷新…</div>}
      {phase === "stopped" && <div className="notice">工作台已停止。重新打开：运行 burrowl start，或从开始菜单打开“burrowl 工作台”。</div>}
      {phase === "timeout" && <div className="notice">90 秒内没有等到新进程，请查看日志或运行 burrowl status。</div>}
      {info?.update_pending && phase === "idle" && (
        <div className="notice">
          已安装 {info.installed_version}，当前运行 {info.version}：重启后生效。AI 客户端里的 MCP 需在客户端重启。
        </div>
      )}
      <ul className="lights">
        <li>
          <span className={`light ${checkTone}`} />
          <div>
            <div>
              外部原件 <strong>{checkText}</strong>
            </div>
            <div className="muted small-text" title={check?.checked_at ?? ""}>
              上次检查 {ago(check?.checked_at)}
              {check?.trigger === "schedule" ? "（定时）" : check?.checked_at ? "（手动）" : ""} ·{" "}
              {schedule?.enabled ? `每 ${schedule.interval_hours} 小时定时检查` : "定时检查已关闭"}
            </div>
            {problems.length > 0 && (
              <button type="button" className="link small-text" onClick={() => setShowProblems(!showProblems)}>
                {showProblems ? "收起" : "查看是哪些"}
              </button>
            )}
            {showProblems && (
              <ul className="problem-list">
                {problems.map((p: any) => (
                  <li key={p.artifact_id}>
                    <Dot tone={p.status === "missing" ? "bad" : "warn"} />
                    <IdLink id={p.artifact_id} name={p.title} />
                    <span className="muted">{p.status === "missing" ? "已丢失" : "已变化"}</span>
                    {p.status === "changed" && <a href={href("record", p.artifact_id)}>登记新版本</a>}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button type="button" className="small" disabled={checking} onClick={runCheck}>
            立即检查
          </button>
        </li>
        <ExtractionLight />
        <ModelLight />
        <li>
          <span className={`light ${indexTone}`} />
          <div>
            检索索引 <strong>{indexText}</strong>
            <div className="muted small-text">
              覆盖原件、事实记录、判断和框架页{health ? `，共 ${health.expected} 条` : ""}
              {rebuilding && "；后台进行，期间可以照常使用，检索结果可能不全"}
              {stale && !rebuilding && "；别的进程改了设置时，由它在后台重建，也可以在这里重建"}
            </div>
            {rebuilding && <progress className="index-progress" max={job.total || 1} value={job.done} />}
            {job?.state === "failed" && <div className="small-text warn-text">上次重建失败：{job.errors?.at(-1)}</div>}
            {job?.state === "done" && job.errors?.length > 0 && <div className="small-text warn-text">重建完成，{job.errors.length} 条出错：{job.errors[0]}</div>}
            {vec && vec.state !== "off" && (
              <div className="muted small-text">
                向量{" "}
                {vec.state === "ready"
                  ? `已建完（${vec.total} 个单元）`
                  : vec.state === "building"
                    ? `后台补建中 ${vec.done} / ${vec.total}：补完前向量通道只覆盖一部分`
                    : vec.state === "missing"
                      ? "缺模型，检索只用关键词"
                      : `出错：${vec.reason ?? ""}`}
              </div>
            )}
          </div>
          {(health?.missing || stale) && !rebuilding ? (
            <button type="button" className="small" onClick={rebuild}>
              重建
            </button>
          ) : (
            <span />
          )}
        </li>
        <li>
          <span className={`light ${info?.update_pending ? "warn" : info ? "good" : "muted"}`} />
          <div title={`${info?.data ?? ""}\n进程 ${info?.pid ?? ""}`}>
            工作台 <strong>{info?.version ?? "…"}</strong>
            <div className="muted small-text">启动于 {ago(info?.started_at)}</div>
          </div>
          <span className="service-buttons">
            <button type="button" className={`small ${info?.update_pending ? "primary" : ""}`} disabled={phase !== "idle"} onClick={restart}>
              重启
            </button>
            <button type="button" className="small" disabled={phase !== "idle"} onClick={stop}>
              停止
            </button>
          </span>
        </li>
        <li>
          <span className={`light ${info ? "accent" : "muted"}`} />
          <div>
            数据目录 <a href={href("databases")}>{info?.data_name ?? ""}</a>
            {info?.port ? <span className="muted small-text"> · 端口 {info.port}</span> : null}
            <code className="data-path" title={info?.data ?? ""}>
              {info?.data ?? "…"}
            </code>
          </div>
          <CopyButton text={info?.data} />
        </li>
      </ul>
    </Panel>
  );
}

// 抽取与引用（设计稿 01 D-05、D-12、D-13；设计稿 02 D-07、D-15）：未抽取的原件、抽取器升级后待重建的原件、
// 待抽取的图片页、未读先引、引用未确认的识别文本、待复核的判断、建议退役的旧派生文本
const EXTRACTION_ITEMS: [string, string, string][] = [
  ["needs_recheck", "抽取已变化，引用它的判断待复核", "bad"],
  ["recheck_citations", "引用了待复核的判断（它的依据已变化）", "warn"],
  ["failed", "抽取失败的原件", "bad"],
  ["low_fidelity_citations", "引用了未确认的 OCR / AI 识别文本", "warn"],
  ["unread_citations", "未读先引（引用的段落没有读取记录）", "warn"],
  ["unextracted", "还没有抽取的原件", "warn"],
  ["outdated", "抽取器已升级、待按新版重建的原件（补抽）", "warn"],
  ["image_pages", "有图片页待抽取的原件", "muted"],
  ["retire_suggestions", "建议退役（旧的派生文本，已由原件自己的抽取层取代）", "muted"],
];
// 默认折叠的分组：AI 已核对过的待复核判断，不再算待处理（设计稿 04 D-14）
const FOLDED_ITEMS: [string, string][] = [["ai_checked_recheck", "AI 已核对（待复核的判断，AI 复核认为依据仍支持）"]];

// 本地模型（设计稿 05 D-04）：槽位与最近的模型任务；没有配置任何模型时不显示
function ModelLight() {
  const [status, , reload] = useLoad(() => call<any>("models.status").catch(() => null), []);
  usePoll(reload, 5000);
  if (!status) return null;
  const slots = Object.entries(status.slots ?? {}).filter(([, s]: any) => s.configured) as [string, any][];
  if (!slots.length) return null;
  const jobs: any[] = status.jobs ?? [];
  const running = jobs.filter((j) => j.status === "running" || j.status === "cancelling");
  const queued = jobs.filter((j) => j.status === "queued");
  const failed = jobs.filter((j) => j.status === "failed").slice(0, 3);
  const name: Record<string, string> = { layout: "版面", formula: "公式", embedding: "向量", llm: "大模型" };
  return (
    <li>
      <span className={`light ${failed.length ? "warn" : "good"}`} />
      <div>
        模型{" "}
        <strong>
          {slots.map(([k, s]) => `${name[k] ?? k} ${s.adapter}${s.auto ? "（自动）" : ""}`).join("，")}
        </strong>
        <div className="muted small-text">
          {running.length} 个运行中 · {queued.length} 个排队
          {jobs.length > 0 && <> · <a href={href("agent")}>查看模型任务</a></>}
        </div>
      </div>
      <span />
    </li>
  );
}

function ExtractionLight() {
  const [status, error, reload] = useLoad(() => call<any>("extraction.status"), []);
  usePoll(reload, 60000);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const counts = EXTRACTION_ITEMS.map(([key, label, tone]) => ({ key, label, tone, items: (status?.[key] ?? []) as any[] })).filter((c) => c.items.length);
  const serious = counts.find((c) => c.tone === "bad") ? "bad" : counts.find((c) => c.tone === "warn") ? "warn" : "good";
  const backfill = async () => {
    setBusy(true);
    try {
      await call("extraction.backfill");
      reload();
    } finally {
      setBusy(false);
    }
  };
  return (
    <li>
      <span className={`light ${!status ? "muted" : counts.length ? serious : "good"}`} />
      <div>
        抽取与引用 <strong>{error ? "读取失败" : !status ? "…" : counts.length ? counts.map((c) => `${c.label.split("（")[0]} ${c.items.length}`).join("，") : "没有问题"}</strong>
        {counts.length > 0 && (
          <div>
            <button type="button" className="link small-text" onClick={() => setOpen(!open)}>
              {open ? "收起" : "查看是哪些"}
            </button>
          </div>
        )}
        {open && (
          <ul className="problem-list">
            {counts.map((c) =>
              c.items.slice(0, 8).map((item: any, i: number) => (
                <li key={`${c.key}-${i}`}>
                  <Dot tone={c.tone} />
                  <IdLink id={item.judgment_id ?? item.artifact_id} name={item.title} />
                  <span className="muted">{c.label}</span>
                  {c.key === "retire_suggestions" && (
                    <Action
                      className="small"
                      label="退役"
                      run={async () => {
                        await call("artifact.retire", { artifact_id: item.artifact_id, reason: item.reason, replaced_by: item.source_id });
                        reload();
                      }}
                    />
                  )}
                </li>
              )),
            )}
          </ul>
        )}
        {open && status?.needs_recheck?.length > 0 && (
          <button type="button" className="link small-text" onClick={() => delegate(aiReviewPrompt(status.needs_recheck.map((r: any) => r.judgment_id)))} title="需要设置里允许 AI 复核判断（review.ai = all）">
            把待复核的判断交给 AI 复核（{status.needs_recheck.length}）
          </button>
        )}
        {open &&
          FOLDED_ITEMS.map(([key, label]) =>
            status?.[key]?.length ? (
              <details key={key} className="small-text">
                <summary>
                  {label}：{status[key].length}
                </summary>
                <ul className="problem-list">
                  {status[key].map((item: any) => (
                    <li key={item.judgment_id}>
                      <Dot tone="muted" />
                      <IdLink id={item.judgment_id} />
                    </li>
                  ))}
                </ul>
                <button type="button" className="link small-text" onClick={() => delegate(aiReviewPrompt(status[key].map((r: any) => r.judgment_id)))}>
                  再次交给 AI 复核（{status[key].length}）
                </button>
              </details>
            ) : null,
          )}
      </div>
      {status?.unextracted?.length || status?.outdated?.length ? (
        <button type="button" className="small" disabled={busy} onClick={backfill}>
          {busy ? "抽取中…" : "补抽"}
        </button>
      ) : (
        <span />
      )}
    </li>
  );
}

function CopyButton({ text }: { text?: string }) {
  return (
    <button type="button" className="icon-button" disabled={!text} title="复制数据目录的路径" aria-label="复制路径" onClick={() => void copyText(text ?? "", "已复制路径")}>
      <Icon name="copy" />
    </button>
  );
}

// 正在进行：运行中的 agent
function OngoingCard() {
  const [runs, , reloadRuns] = useLoad(() => call<any[]>("agent.runs", { limit: 20 }), []);
  usePoll(reloadRuns);
  const running = (runs ?? []).filter((r) => r.status === "running" || r.status === "cancelling");
  return (
    <Panel title="正在进行">
      {running.length ? (
        <ul className="todo-list">
          {running.map((r) => (
            <li key={r.id}>
              <a href={href("agent", r.id)}>
                <Dot tone="accent pulse" />
                <span title={r.data.prompt}>
                  {r.agent}：{(r.data.prompt ?? "").slice(0, 24)}
                </span>
                <Time value={r.created_at} />
              </a>
            </li>
          ))}
        </ul>
      ) : (
        runs && <Empty compact icon="bolt">没有正在进行的 agent</Empty>
      )}
    </Panel>
  );
}
