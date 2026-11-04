// 首页：主栏是最近关键操作（按天分组的时间线）；侧栏是待决策、判断的地位分布、框架时效、agent 与工作台服务。
import { useState } from "react";
import { call } from "../api";
import { DECISION, FRESHNESS, JUDGMENT_KIND, RUN_STATUS } from "../labels";
import { href } from "../router";
import { Bar, Dot, Empty, ErrorBox, Panel, Tag, Time, dayLabel, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

const ACTIVITY_LABEL: Record<string, [string, string]> = {
  artifact: ["原件", "src"],
  record: ["事实记录", "src"],
  page: ["框架页", "fw"],
  agent_run: ["agent", "muted"],
};

export function Home() {
  const [activity, aError, reloadActivity] = useLoad(() => call<any[]>("activity.recent", { limit: 40 }), []);
  const [stats, sError, reloadStats] = useLoad(() => call<any>("stats.overview"), []);
  usePoll(reloadActivity);
  usePoll(reloadStats);
  return (
    <div className="home">
      <div className="home-main">
        <Panel title="最近关键操作" actions={<a href={href("entries")}>浏览全部条目 →</a>}>
          <ErrorBox error={aError} />
          {activity?.length ? <Timeline items={activity} /> : <Empty>还没有记录。登记原件、写判断或让 agent 工作后会出现在这里。</Empty>}
        </Panel>
      </div>
      <div className="home-side">
        <ErrorBox error={sError} />
        {stats && (
          <>
            <DecisionsCard counts={stats.decisions} />
            <JudgmentsCard j={stats.judgments} ledger={stats.ledger} />
            <FrameworkCard pages={stats.pages} edges={stats.edges} entities={stats.entities} />
            <AgentCard />
          </>
        )}
        <ServerCard />
      </div>
    </div>
  );
}

function Timeline({ items }: { items: any[] }) {
  const groups = new Map<string, any[]>();
  for (const item of items) {
    const key = dayLabel(new Date(item.at));
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return (
    <div className="activity-timeline">
      {[...groups.entries()].map(([day, rows]) => (
        <section key={day}>
          <h4>{day}</h4>
          <ul className="activity">
            {rows.map((item) => {
              const [label, tone] = item.kind.startsWith("judgment.")
                ? [JUDGMENT_KIND[item.kind.slice(9)] ?? "判断", ["correction", "retraction", "defect"].includes(item.kind.slice(9)) ? "bad" : "jd"]
                : (ACTIVITY_LABEL[item.kind] ?? [item.kind, "muted"]);
              const target = item.kind === "agent_run" ? href("agent") : href("entry", item.id);
              return (
                <li key={item.kind + item.id}>
                  <time title={item.at}>{new Date(item.at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time>
                  <span className={`kind ${tone}`}>{label}</span>
                  <a href={target}>{item.summary}</a>
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

function Row({ tone, label, value, to }: { tone: string; label: string; value: number; to?: string }) {
  return (
    <li>
      <Dot tone={value ? tone : "muted"} />
      {to ? <a href={to}>{label}</a> : <span>{label}</span>}
      <strong className={value ? "" : "muted"}>{value}</strong>
    </li>
  );
}

function DecisionsCard({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((s, n) => s + n, 0);
  const tones: Record<string, string> = { term_link: "warn", review: "accent", rederive: "warn", constraint_unchecked: "bad", propagation_overflow: "bad" };
  return (
    <Panel title="待决策" actions={<a href={href("decisions")}>去处理 →</a>}>
      <div className="big-number">
        <strong>{total}</strong>
        <span>项等你处理（不阻塞导入和写入）</span>
      </div>
      <Bar parts={Object.keys(DECISION).map((k) => [counts[k] ?? 0, tones[k]])} />
      <ul className="status-list">
        {Object.entries(DECISION).map(([k, text]) => (
          <Row key={k} tone={tones[k]} label={text} value={counts[k] ?? 0} />
        ))}
      </ul>
    </Panel>
  );
}

function JudgmentsCard({ j, ledger }: { j: any; ledger: Record<string, number> }) {
  return (
    <Panel title="判断的地位" actions={<a href={href("entries")}>浏览 →</a>}>
      <div className="big-number">
        <strong>{j.total}</strong>
        <span>条判断 · 原件 {ledger.artifacts} · 事实记录 {ledger.records}</span>
      </div>
      <Bar parts={[[j.executed_only, "good"], [j.with_external, "accent"], [j.mixed, "warn"], [j.discussion_only, "muted"], [j.normative, "bad"]]} />
      <ul className="status-list">
        <Row tone="good" label="全部依据来自亲自执行" value={j.executed_only} />
        <Row tone="accent" label="只来自外部报告" value={j.with_external} />
        <Row tone="warn" label="混合来源" value={j.mixed} />
        <Row tone="muted" label="只有推断或讨论" value={j.discussion_only} />
        <Row tone="bad" label="约束、决定、指令" value={j.normative} />
      </ul>
      <ul className="status-list compact">
        <Row tone="bad" label="已被替代、更正或撤回" value={j.superseded} />
        <Row tone="warn" label="有反对" value={j.opposed} />
        <li className="muted">
          人写 {j.by_author.human ?? 0} · AI 写 {j.by_author.ai ?? 0} · 系统 {j.by_author.system ?? 0}
        </li>
      </ul>
    </Panel>
  );
}

function FrameworkCard({ pages, edges, entities }: { pages: any; edges: any; entities: number }) {
  const f = pages.freshness as Record<string, number>;
  return (
    <Panel title="框架" actions={<a href={href("pages")}>框架页 →</a>}>
      <div className="big-number">
        <strong>{pages.total}</strong>
        <span>个页面 · 实体 {entities} · 边 {edges.total}</span>
      </div>
      <Bar parts={[[f.valid ?? 0, "good"], [f.inputs_changed ?? 0, "warn"], [f.unchecked ?? 0, "bad"]]} />
      <ul className="status-list">
        {(["valid", "inputs_changed", "unchecked"] as const).map((k) => (
          <Row key={k} tone={k === "valid" ? "good" : k === "inputs_changed" ? "warn" : "bad"} label={FRESHNESS[k]} value={f[k] ?? 0} to={k === "valid" ? undefined : href("pages")} />
        ))}
        <Row tone="warn" label="AI 生成、未复核" value={pages.review?.ai_generated ?? 0} />
        <Row tone="warn" label="AI 推断的边" value={edges.origin?.ai_inferred ?? 0} to={href("graph")} />
      </ul>
    </Panel>
  );
}

function AgentCard() {
  const [runs] = useLoad(() => call<any[]>("agent.runs", { limit: 4 }), []);
  return (
    <Panel title="Agent" actions={<a href={href("agent")}>启动 →</a>}>
      {runs?.length ? (
        <ul className="status-list">
          {runs.map((r) => (
            <li key={r.id}>
              <Dot tone={r.status === "running" ? "accent" : r.status === "done" ? "good" : "bad"} />
              <a href={href("agent")} title={r.data.prompt}>
                {r.agent}：{(r.data.prompt ?? "").slice(0, 22)}
              </a>
              <span className="muted">{RUN_STATUS[r.status] ?? r.status}</span>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>还没有运行过 agent。</Empty>
      )}
    </Panel>
  );
}

// 工作台服务：安装新版本后在这里重启即可加载；AI 客户端里的 MCP 是另外的进程，需要在客户端重启。
function ServerCard() {
  const [info, error, reload] = useLoad(() => call<any>("server.info"), []);
  const [phase, setPhase] = useState<"idle" | "restarting" | "stopped" | "timeout">("idle");
  const [fail, setFail] = useState<string | null>(null);
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
  return (
    <Panel title="工作台服务">
      <ErrorBox error={error ?? fail} />
      {phase === "restarting" && <div className="notice">正在重启，完成后页面会自动刷新…</div>}
      {phase === "stopped" && <div className="notice">工作台已停止。重新打开：运行 burrowl start，或从开始菜单打开“burrowl 工作台”。</div>}
      {phase === "timeout" && <div className="notice">90 秒内没有等到新进程，请查看日志或运行 burrowl status。</div>}
      {info && (
        <ul className="status-list">
          <li>
            <Dot tone={info.update_pending ? "warn" : "good"} />
            <span>运行版本</span>
            <span className="muted">
              {info.version}
              {info.update_pending ? `（已安装 ${info.installed_version}，重启后生效）` : ""}
            </span>
          </li>
          <li>
            <Dot />
            <span>进程</span>
            <span className="muted" title={info.log}>
              {info.executable} · {info.pid} · <Time value={info.started_at} />
            </span>
          </li>
          <li className="path">
            <span>数据目录</span>
            <code title={info.data}>{info.data}</code>
          </li>
        </ul>
      )}
      <div className="row">
        <button type="button" className={info?.update_pending ? "primary" : ""} disabled={phase !== "idle"} onClick={restart}>
          重启服务
        </button>
        <button type="button" disabled={phase !== "idle"} onClick={stop}>
          停止服务
        </button>
        <button type="button" className="link" onClick={reload}>
          刷新
        </button>
      </div>
      <Tag tone="muted">AI 客户端里的 MCP 是另外的进程，升级后需在客户端重启</Tag>
    </Panel>
  );
}
