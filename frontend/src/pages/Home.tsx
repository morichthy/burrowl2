// 首页：主栏是问候语、三列比例与近两周热度、最近关键操作（按天分组的时间线）；
// 侧栏三张卡：状态（原件检查、索引、服务）、需要人处理的事项、正在进行的 agent。
import { useState, type ReactNode } from "react";
import { call } from "../api";
import { DECISION, JUDGMENT_KIND } from "../labels";
import { delegate, href } from "../router";
import { aiReviewPrompt } from "../review";
import { Action, Dot, ErrorBox, IdLink, Panel, Time, dayLabel, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

const ACTIVITY_LABEL: Record<string, [string, string]> = {
  artifact: ["原件", "src"],
  record: ["事实记录", "src"],
  page: ["框架页", "fw"],
  agent_run: ["agent", "muted"],
};

// 待你处理：每类一行，只列有数量的；去处理的页面按类型分流
const TODO: { kind: string; tone: string; hint: string; to: string }[] = [
  { kind: "constraint_unchecked", tone: "bad", hint: "AI 操作前没有检查约束，请确认是否有影响", to: "decisions" },
  { kind: "review", tone: "accent", hint: "AI 写的框架页或推断的关系，等你确认或驳回", to: "decisions" },
  { kind: "term_link", tone: "warn", hint: "叫法对不上实体，等你决定", to: "decisions" },
  { kind: "rederive", tone: "warn", hint: "框架页的输入已变化，可以交给 agent 重新综合", to: "pages" },
  { kind: "propagation_overflow", tone: "bad", hint: "变化传播超过上限，部分条目未核查", to: "decisions" },
  { kind: "finding", tone: "accent", hint: "巡检员提出的问题；复核员确认的排在前面，由你采纳、驳回或忽略", to: "decisions" },
];

type TodoRow = { kind: string; label: string; tone: string; hint: string; to: string; count: number };

function todoRows(stats: any, check: any, inspection?: any): TodoRow[] {
  const counts: Record<string, number> = stats?.decisions ?? {};
  const rows: TodoRow[] = TODO.filter((t) => counts[t.kind]).map((t) => ({ ...t, label: DECISION[t.kind], count: counts[t.kind] }));
  // 定期巡检（设计稿 08 D-01）：定时只准备巡检包，由你点"开始巡检"
  const insp = inspection?.latest;
  if (insp && insp.status === "ready" && insp.tasks) {
    rows.unshift({
      kind: "inspection", label: `本期巡检已准备好：${insp.suspicious} 项可疑、${insp.explore} 处探索样本`, tone: "accent", count: insp.tasks,
      hint: "定时只在本机做了规则检查；在待决策页点开始巡检才会调用巡检员 agent", to: "decisions",
    });
  }
  // 原件检查不是待决策项：结果来自上次检查，确认后把新文件登记为新版本
  const problems = (check?.changed ?? 0) + (check?.missing ?? 0);
  if (problems) {
    rows.unshift({
      kind: "artifact_check", label: "外部原件已变化或丢失", tone: check.missing ? "bad" : "warn", count: problems,
      hint: "在状态卡里查看是哪些；确认是新版本后登记为新版本", to: "",
    });
  }
  return rows;
}

export function Home() {
  const [activity, aError, reloadActivity] = useLoad(() => call<any[]>("activity.recent", { limit: 40 }), []);
  const [stats, sError, reloadStats] = useLoad(() => call<any>("stats.overview"), []);
  const [check, cError, reloadCheck] = useLoad(() => call<any>("artifact.check_status"), []);
  const [inspection, , reloadInspection] = useLoad(() => call<any>("inspection.status").catch(() => null), []);
  usePoll(reloadInspection, 30000);
  usePoll(reloadActivity);
  usePoll(reloadStats);
  usePoll(reloadCheck, 30000);
  const todos = todoRows(stats, check, inspection);
  return (
    <div className="home">
      <div className="home-main">
        <Greeting stats={stats} todo={todos.reduce((s, t) => s + t.count, 0)} />
        <Panel title="最近关键操作" actions={<a href={href("entries")}>浏览全部条目 →</a>}>
          <ErrorBox error={aError} />
          {stats && <Overview stats={stats} />}
          {activity?.length ? (
            <Timeline items={activity} />
          ) : (
            <Calm title="还没有记录">登记原件、写判断或让 agent 工作后会出现在这里。</Calm>
          )}
        </Panel>
      </div>
      <div className="home-side">
        <StatusCard check={check} reloadCheck={reloadCheck} />
        <TodoCard rows={todos} loaded={!!stats} error={sError ?? cError} />
        <OngoingCard />
      </div>
    </div>
  );
}

// 问候语：按时段问候，后接一句当日概况
function Greeting({ stats, todo }: { stats: any; todo: number }) {
  const h = new Date().getHours();
  const hello = h < 5 ? "夜深了" : h < 11 ? "早上好" : h < 13 ? "中午好" : h < 18 ? "下午好" : "晚上好";
  const days = Object.values(stats?.daily ?? {}) as number[];
  const today = days.length ? days[days.length - 1] : 0;
  return (
    <div className="greeting">
      <strong>{hello}</strong>
      {stats && (
        <span className="muted">
          今天新增 {today} 条{todo ? ` · ${todo} 件待你处理` : " · 没有待你处理的事项"}
        </span>
      )}
    </div>
  );
}

function localDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// 三列比例条 + 近两周活动热度（点一格跳到时间线里那一天，如果已加载）
function Overview({ stats }: { stats: any }) {
  const l = stats.ledger ?? {};
  const cols = [
    { key: "src", name: "原件", n: (l.artifacts ?? 0) + (l.records ?? 0), hint: "登记的原件、事实记录（不含过程日志和读取日志）" },
    { key: "jd", name: "判断", n: stats.judgments?.total ?? 0, hint: "结论、过程、规定与系统记录" },
    { key: "fw", name: "框架", n: stats.pages?.total ?? 0, hint: "实体页、概念页、综合页" },
  ];
  const total = cols.reduce((s, c) => s + c.n, 0);
  const daily = Object.entries(stats.daily ?? {}) as [string, number][];
  const max = Math.max(1, ...daily.map(([, n]) => n));
  const jump = (day: string) => document.getElementById(`day-${day}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  return (
    <div className="overview">
      <div className="columns-bar" role="img" aria-label={cols.map((c) => `${c.name} ${c.n}`).join("，")}>
        {total ? cols.filter((c) => c.n > 0).map((c) => <span key={c.key} className={c.key} style={{ flexGrow: c.n }} title={`${c.name} ${c.n}：${c.hint}`} />) : <span className="none" />}
      </div>
      <div className="columns-legend">
        {cols.map((c) => (
          <span key={c.key} title={c.hint}>
            <i className={c.key} />
            {c.name} <strong>{c.n}</strong>
          </span>
        ))}
        <span className="heat" aria-label="近两周每天新增条目数">
          {daily.map(([day, n]) => (
            <button
              type="button"
              key={day}
              className={`cell l${n === 0 ? 0 : Math.min(4, Math.ceil((n / max) * 4))}`}
              title={`${day.slice(5)}：新增 ${n} 条`}
              aria-label={`${day} 新增 ${n} 条`}
              onClick={() => jump(day)}
            />
          ))}
        </span>
      </div>
    </div>
  );
}

function Timeline({ items }: { items: any[] }) {
  const groups = new Map<string, { id: string; rows: any[] }>();
  for (const item of items) {
    const d = new Date(item.at);
    const key = dayLabel(d);
    const group = groups.get(key) ?? { id: Number.isNaN(d.getTime()) ? "unknown" : localDay(d), rows: [] };
    group.rows.push(item);
    groups.set(key, group);
  }
  return (
    <div className="activity-timeline">
      {[...groups.entries()].map(([day, { id, rows }]) => (
        <section key={day} id={`day-${id}`}>
          <h4>{day}</h4>
          <ul className="activity">
            {rows.map((item) => {
              const [label, tone] = item.kind.startsWith("judgment.")
                ? [JUDGMENT_KIND[item.kind.slice(9)] ?? "判断", ["correction", "retraction", "defect"].includes(item.kind.slice(9)) ? "bad" : "jd"]
                : (ACTIVITY_LABEL[item.kind] ?? [item.kind, "muted"]);
              return (
                <li key={item.kind + item.id} className={`tone-${tone}`}>
                  <time title={item.at}>{new Date(item.at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time>
                  <span className={`kind ${tone}`}>{label}</span>
                  {item.kind === "agent_run" ? <a href={href("agent")}>{item.summary}</a> : <IdLink id={item.id} />}
                  <span className="actor">{actorLabel(item.actor)}</span>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
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

// 空状态：一个小插图加一句话，比一行灰字更像"已经清空了"
function Calm({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="calm">
      <svg viewBox="0 0 64 40" width="64" height="40" aria-hidden="true">
        <path d="M4 34 Q20 18 32 26 T60 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.35" />
        <circle cx="46" cy="10" r="5" fill="currentColor" opacity="0.5" />
        <path d="M14 34 l4 -6 l4 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" opacity="0.6" />
      </svg>
      <div>
        <strong>{title}</strong>
        {children && <div className="muted">{children}</div>}
      </div>
    </div>
  );
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
    <Panel title="状态">
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

// 复制到剪贴板；浏览器不允许时（非安全上下文等）提示手动复制
function CopyButton({ text }: { text?: string }) {
  const [state, setState] = useState<"idle" | "done" | "fail">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text ?? "");
      setState("done");
    } catch {
      setState("fail");
    }
    window.setTimeout(() => setState("idle"), 1500);
  };
  return (
    <button type="button" className="small" disabled={!text} onClick={copy}>
      {state === "done" ? "已复制" : state === "fail" ? "请手动复制" : "复制"}
    </button>
  );
}

function TodoCard({ rows, loaded, error }: { rows: TodoRow[]; loaded: boolean; error: string | null }) {
  const total = rows.reduce((s, t) => s + t.count, 0);
  return (
    <Panel title={`待你处理${total ? `（${total}）` : ""}`} actions={total ? <a href={href("decisions")}>全部 →</a> : null}>
      <ErrorBox error={error} />
      {loaded && rows.length === 0 && <Calm title="都处理完了">有需要你确认的事项时会出现在这里。</Calm>}
      <ul className="todo-list">
        {rows.map((t) => (
          <li key={t.kind}>
            <a href={href(t.to)}>
              <Dot tone={t.tone} />
              <span>{t.label}</span>
              <strong>{t.count}</strong>
            </a>
            <div className="muted">{t.hint}</div>
          </li>
        ))}
      </ul>
    </Panel>
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
              <a href={href("agent")}>
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
        runs && <p className="empty">没有正在进行的 agent</p>
      )}
    </Panel>
  );
}
