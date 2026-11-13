// 底部状态栏与"系统状态"面板：数据目录、索引、外部原件、抽取与引用、工作台服务、运行中的 Agent 都在这里。
// 状态栏只放"灯 + 几个字"的摘要，点任意一项向上弹出面板，看详情、立即检查、重建索引、重启与停止工作台；
// 安装了新版本需要重启时，状态栏上直接出现"重启以更新"。其余数字只来自服务端，不在前端推断。
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { call, currentDb } from "../api";
import { EntryLabels } from "../entryLabels";
import { delegate, href } from "../router";
import { aiReviewPrompt } from "../review";
import { Action, Dot, ErrorBox, IdLink, Time, useLoad, usePoll } from "../ui";
import { Icon } from "./icons";
import { copyText } from "./toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

type PanelKind = "system" | "agent" | null;
const OPEN_EVENT = "burrowl:open-status";

// 页面里的链接（如首页"外部原件已变化"）用它直接打开面板
export function openSystemStatus() {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: "system" }));
}

function ago(iso: string | null | undefined): string {
  if (!iso) return "从未";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  if (min < 48 * 60) return `${Math.round(min / 60)} 小时前`;
  return `${Math.round(min / 1440)} 天前`;
}

const WORST = ["good", "accent", "warn", "bad"];
const worst = (tones: string[]) => tones.reduce((a, b) => (WORST.indexOf(b) > WORST.indexOf(a) ? b : a), "good");

export function StatusBar({ status, health, reloadHealth, runs }: { status: any; health: any; reloadHealth: () => void; runs: number }) {
  const [open, setOpen] = useState<PanelKind>(null);
  const close = useCallback(() => setOpen(null), []);
  const [info, infoError, reloadInfo] = useLoad(() => call<any>("server.info"), []);
  const [check, , reloadCheck] = useLoad(() => call<any>("artifact.check_status").catch(() => null), []);
  const [extraction, extractionError, reloadExtraction] = useLoad(() => call<any>("extraction.status"), []);
  usePoll(reloadCheck, 30000);
  usePoll(reloadInfo, 60000);
  usePoll(reloadExtraction, 60000);
  useEffect(() => {
    const on = (e: Event) => setOpen((e as CustomEvent).detail ?? "system");
    window.addEventListener(OPEN_EVENT, on);
    return () => window.removeEventListener(OPEN_EVENT, on);
  }, []);

  // 后台重建索引、补建向量时每 3 秒刷新进度，平时每分钟（设计稿 06 D-22）
  const busyIndex = health?.units?.rebuild?.state === "running" || health?.vectors?.state === "building";
  usePoll(reloadHealth, busyIndex ? 3000 : 60000);

  const idx = indexLight(health);
  const chk = checkLight(check, false);
  const extCounts = extractionCounts(extraction);
  const ext = !extraction ? "muted" : extCounts.some((c) => c.tone === "bad") ? "bad" : extCounts.some((c) => c.tone === "warn") ? "warn" : "good";
  const svc = info?.update_pending ? "warn" : info ? "good" : "muted";
  const overall = worst([idx.tone, chk.tone, ext, svc].map((t) => (t === "muted" ? "good" : t.split(" ")[0])));
  const ledger = status?.ledger ? Object.values(status.ledger as Record<string, number>).reduce((s: number, n: any) => s + n, 0) : null;
  const toggle = (p: Exclude<PanelKind, null>) => setOpen((o) => (o === p ? null : p));

  return (
    <footer className="statusbar" aria-label="系统状态">
      <button type="button" className="sb-item" aria-expanded={open === "system"} onClick={() => toggle("system")} title="打开系统状态：外部原件、抽取、索引、服务">
        <span className={`status-dot ${overall}`} />系统状态
      </button>
      <a href={href("databases")} className="hide-narrow" title={`数据目录：${info?.data ?? ""}（点击管理或切换）`}>
        数据目录 {status?.data_name ?? currentDb() ?? "…"}
      </a>
      {ledger != null && <span className="hide-narrow" title="账本里的原件、判断、事实记录、读取记录、日志与连接">账本 {ledger.toLocaleString("zh-CN")} 条</span>}
      <button type="button" className="sb-item hide-narrow" onClick={() => toggle("system")} title={idx.text}>
        <span className={`status-dot ${idx.tone}`} />{idx.short}
      </button>
      {check?.referenced_total ? (
        <button type="button" className="sb-item hide-narrow" onClick={() => toggle("system")} title={chk.text}>
          <span className={`status-dot ${chk.tone}`} />{chk.short}
        </button>
      ) : null}
      {extCounts.length > 0 && (
        <button type="button" className="sb-item hide-narrow" onClick={() => toggle("system")} title="抽取与引用有需要处理的项">
          <span className={`status-dot ${ext}`} />抽取与引用 {extCounts.reduce((s, c) => s + c.items.length, 0)}
        </button>
      )}
      {info?.update_pending ? (
        <ServiceRestart info={info} />
      ) : (
        <button type="button" className="sb-item hide-narrow" onClick={() => toggle("system")} title={`工作台进程 ${info?.pid ?? ""}`}>
          <span className={`status-dot ${svc}`} />工作台 {info?.version ?? "…"}
        </button>
      )}
      <span className="grow" />
      <button type="button" className="sb-item" aria-expanded={open === "agent"} onClick={() => toggle("agent")} title="运行中的 Agent">
        {runs > 0 ? <><span className="status-dot warn pulse" />{runs} 个 Agent 运行中</> : "没有 Agent 在运行"}
      </button>
      <span className="hide-narrow">按 <kbd>?</kbd> 看快捷键</span>
      {open && (
        <Popover onClose={close}>
          {open === "system" ? (
            <SystemPanel
              info={info} infoError={infoError} check={check} reloadCheck={reloadCheck} health={health} reloadHealth={reloadHealth}
              extraction={extraction} extractionError={extractionError} reloadExtraction={reloadExtraction}
            />
          ) : (
            <AgentPanel onClose={close} />
          )}
        </Popover>
      )}
    </footer>
  );
}

// 向上弹出的面板：点外面或按 Esc 关闭
function Popover({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (ref.current?.contains(t) || t.closest?.(".statusbar button, .statusbar a")) return;
      onClose();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [onClose]);
  return (
    <div className="status-pop" role="dialog" aria-label="状态详情" ref={ref}>
      <EntryLabels>{children}</EntryLabels>
    </div>
  );
}

// 需要重启时状态栏上的醒目按钮；重启流程与面板里的"重启"共用
function ServiceRestart({ info }: { info: any }) {
  const { phase, fail, restart } = useRestart();
  return (
    <span className="sb-update">
      <span className="status-dot warn" />
      已装 {info.installed_version}，运行 {info.version}
      <button type="button" className="small primary" disabled={phase !== "idle"} onClick={restart} title={fail ?? "重启工作台以加载新版本；AI 客户端里的 MCP 需在客户端重启"}>
        {phase === "restarting" ? "重启中…" : "重启以更新"}
      </button>
    </span>
  );
}

function useRestart() {
  const [phase, setPhase] = useState<"idle" | "restarting" | "stopped" | "timeout">("idle");
  const [fail, setFail] = useState<string | null>(null);
  const restart = useCallback(async () => {
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
  }, []);
  const stop = useCallback(async () => {
    if (!window.confirm("停止工作台？之后运行 burrowl start，或从开始菜单打开“burrowl 工作台”。")) return;
    try {
      await call("server.stop");
      setPhase("stopped");
    } catch (e: any) {
      setFail(e.message);
    }
  }, []);
  return { phase, fail, restart, stop };
}

function checkLight(check: any, checking: boolean) {
  const problems = check?.problems ?? [];
  const tone = checking ? "accent pulse" : !check?.checked_at ? "muted" : check.missing ? "bad" : check.changed ? "warn" : "good";
  const text = checking
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
  const short = problems.length ? `外部原件 ${problems.length} 份有问题` : check?.checked_at ? "外部原件一致" : "外部原件未检查";
  return { tone, text, short, problems };
}

// 指示灯：只有索引按当前设置建成、向量也补完（或没启用）才是绿灯。
// 重建中、向量补建中是蓝色呼吸灯（结果可能不全，但能照常用）；需要处理的问题是黄灯
function indexLight(health: any) {
  const job = health?.units?.rebuild;
  const rebuilding = job?.state === "running";
  const stale = !!(health && health.units && !health.units.current);
  const vec = health?.vectors;
  const vecBuilding = vec?.state === "building";
  const vecPct = vecBuilding && vec.total ? Math.floor((vec.done / vec.total) * 100) : 0;
  const tone = !health
    ? "muted"
    : rebuilding || vecBuilding
      ? "accent pulse"
      : health.missing || stale || job?.state === "failed" || vec?.state === "missing" || vec?.state === "error"
        ? "warn"
        : "good";
  const text = !health
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
  const short = !health ? "索引…" : rebuilding ? `索引重建 ${job.done}/${job.total || "…"}` : stale ? "索引需重建" : health.missing ? `索引缺 ${health.missing} 条` : vecBuilding ? `向量补建 ${vecPct}%` : "索引正常";
  return { tone, text, short, job, rebuilding, stale, vec };
}

function SystemPanel(p: {
  info: any; infoError: string | null; check: any; reloadCheck: () => void; health: any; reloadHealth: () => void;
  extraction: any; extractionError: string | null; reloadExtraction: () => void;
}) {
  const { info, check, health } = p;
  const [checking, setChecking] = useState(false);
  const [fail, setFail] = useState<string | null>(null);
  const [showProblems, setShowProblems] = useState(false);
  const { phase, fail: svcFail, restart, stop } = useRestart();
  const runCheck = async () => {
    setChecking(true);
    setFail(null);
    try {
      await call("artifact.check");
      p.reloadCheck();
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
      p.reloadHealth();
    } catch (e: any) {
      setFail(e.message);
    }
  };
  const chk = checkLight(check, checking);
  const idx = indexLight(health);
  const schedule = check?.schedule;
  const { job, rebuilding, stale, vec } = idx;
  return (
    <div className="status-pop-body">
      <h2 className="status-pop-title">系统状态</h2>
      <ErrorBox error={p.infoError ?? fail ?? svcFail} />
      {phase === "restarting" && <div className="notice">正在重启，完成后页面会自动刷新…</div>}
      {phase === "stopped" && <div className="notice">工作台已停止。重新打开：运行 burrowl start，或从开始菜单打开“burrowl 工作台”。</div>}
      {phase === "timeout" && <div className="notice">90 秒内没有等到新进程，请查看日志或运行 burrowl status。</div>}
      {info?.update_pending && phase === "idle" && (
        <div className="notice">已安装 {info.installed_version}，当前运行 {info.version}：重启后生效。AI 客户端里的 MCP 需在客户端重启。</div>
      )}
      <ul className="lights">
        <li>
          <span className={`light ${chk.tone}`} />
          <div>
            <div>外部原件 <strong>{chk.text}</strong></div>
            <div className="muted small-text" title={check?.checked_at ?? ""}>
              上次检查 {ago(check?.checked_at)}
              {check?.trigger === "schedule" ? "（定时）" : check?.checked_at ? "（手动）" : ""} ·{" "}
              {schedule?.enabled ? `每 ${schedule.interval_hours} 小时定时检查` : "定时检查已关闭"}
            </div>
            {chk.problems.length > 0 && (
              <button type="button" className="link small-text" onClick={() => setShowProblems(!showProblems)}>{showProblems ? "收起" : "查看是哪些"}</button>
            )}
            {showProblems && (
              <ul className="problem-list">
                {chk.problems.map((q: any) => (
                  <li key={q.artifact_id}>
                    <Dot tone={q.status === "missing" ? "bad" : "warn"} />
                    <IdLink id={q.artifact_id} name={q.title} />
                    <span className="muted">{q.status === "missing" ? "已丢失" : "已变化"}</span>
                    {q.status === "changed" && <a href={href("record", q.artifact_id)}>登记新版本</a>}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button type="button" className="small" disabled={checking} onClick={runCheck}>立即检查</button>
        </li>
        <ExtractionLight status={p.extraction} error={p.extractionError} reload={p.reloadExtraction} />
        <ModelLight />
        <li>
          <span className={`light ${idx.tone}`} />
          <div>
            检索索引 <strong>{idx.text}</strong>
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
          {(health?.missing || stale) && !rebuilding ? <button type="button" className="small" onClick={rebuild}>重建</button> : <span />}
        </li>
        <li>
          <span className={`light ${info?.update_pending ? "warn" : info ? "good" : "muted"}`} />
          <div title={`${info?.data ?? ""}\n进程 ${info?.pid ?? ""}`}>
            工作台 <strong>{info?.version ?? "…"}</strong>
            <div className="muted small-text">启动于 {ago(info?.started_at)}</div>
          </div>
          <span className="service-buttons">
            <button type="button" className={`small ${info?.update_pending ? "primary" : ""}`} disabled={phase !== "idle"} onClick={restart}>重启</button>
            <button type="button" className="small" disabled={phase !== "idle"} onClick={stop}>停止</button>
          </span>
        </li>
        <li>
          <span className={`light ${info ? "accent" : "muted"}`} />
          <div>
            数据目录 <a href={href("databases")}>{info?.data_name ?? ""}</a>
            {info?.port ? <span className="muted small-text"> · 端口 {info.port}</span> : null}
            <code className="data-path" title={info?.data ?? ""}>{info?.data ?? "…"}</code>
          </div>
          <CopyButton text={info?.data} />
        </li>
      </ul>
    </div>
  );
}

// 正在进行的 Agent：点一行进入详情
function AgentPanel({ onClose }: { onClose: () => void }) {
  const [runs, , reload] = useLoad(() => call<any[]>("agent.runs", { limit: 20 }), []);
  usePoll(reload);
  const running = (runs ?? []).filter((r) => r.status === "running" || r.status === "cancelling");
  return (
    <div className="status-pop-body">
      <h2 className="status-pop-title">正在进行的 Agent</h2>
      {running.length ? (
        <ul className="todo-list">
          {running.map((r) => (
            <li key={r.id}>
              <a href={href("agent", r.id)} onClick={onClose}>
                <Dot tone="accent pulse" />
                <span title={r.data.prompt}>{r.agent}：{(r.data.prompt ?? "").slice(0, 40)}</span>
                <Time value={r.created_at} />
              </a>
            </li>
          ))}
        </ul>
      ) : (
        runs && <p className="muted small-text">没有正在进行的 agent。</p>
      )}
      <p className="small-text"><a href={href("agent")} onClick={onClose}>打开 Agent 页 →</a></p>
    </div>
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

export function extractionCounts(status: any) {
  return EXTRACTION_ITEMS.map(([key, label, tone]) => ({ key, label, tone, items: (status?.[key] ?? []) as any[] })).filter((c) => c.items.length);
}

function ExtractionLight({ status, error, reload }: { status: any; error: string | null; reload: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const counts = extractionCounts(status);
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
