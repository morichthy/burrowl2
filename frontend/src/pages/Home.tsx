// 首页：主栏是最近关键操作（按天分组的时间线）；侧栏只放两件事：需要人处理的事项、正在进行的操作。
import { useState } from "react";
import { call } from "../api";
import { DECISION, JUDGMENT_KIND } from "../labels";
import { href } from "../router";
import { Dot, Empty, ErrorBox, Panel, Time, dayLabel, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

const ACTIVITY_LABEL: Record<string, [string, string]> = {
  artifact: ["原件", "src"],
  record: ["事实记录", "src"],
  page: ["框架页", "fw"],
  agent_run: ["agent", "muted"],
};

// 待你处理：每类待决策一行，只列有数量的；去处理的页面按类型分流
const TODO: { kind: string; tone: string; hint: string; to: string }[] = [
  { kind: "constraint_unchecked", tone: "bad", hint: "AI 操作前没有检查约束，请确认是否有影响", to: "decisions" },
  { kind: "review", tone: "accent", hint: "AI 写的框架页或推断的关系，等你确认或驳回", to: "decisions" },
  { kind: "term_link", tone: "warn", hint: "叫法对不上实体，等你决定", to: "decisions" },
  { kind: "rederive", tone: "warn", hint: "框架页的输入已变化，可以交给 agent 重新综合", to: "pages" },
  { kind: "propagation_overflow", tone: "bad", hint: "变化传播超过上限，部分条目未核查", to: "decisions" },
];

export function Home() {
  const [activity, aError, reloadActivity] = useLoad(() => call<any[]>("activity.recent", { limit: 40 }), []);
  usePoll(reloadActivity);
  return (
    <div className="home">
      <div className="home-main">
        <Panel title="最近关键操作" actions={<a href={href("entries")}>浏览全部条目 →</a>}>
          <ErrorBox error={aError} />
          {activity?.length ? <Timeline items={activity} /> : <Empty>还没有记录。登记原件、写判断或让 agent 工作后会出现在这里。</Empty>}
        </Panel>
      </div>
      <div className="home-side">
        <TodoCard />
        <OngoingCard />
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

function TodoCard() {
  const [stats, error, reload] = useLoad(() => call<any>("stats.overview"), []);
  usePoll(reload);
  const counts: Record<string, number> = stats?.decisions ?? {};
  const rows = TODO.filter((t) => counts[t.kind]);
  const total = rows.reduce((s, t) => s + counts[t.kind], 0);
  return (
    <Panel title={`待你处理${total ? `（${total}）` : ""}`} actions={total ? <a href={href("decisions")}>全部 →</a> : null}>
      <ErrorBox error={error} />
      {stats && rows.length === 0 && <Empty>没有需要你处理的事项</Empty>}
      <ul className="todo-list">
        {rows.map((t) => (
          <li key={t.kind}>
            <a href={href(t.to)}>
              <Dot tone={t.tone} />
              <span>{DECISION[t.kind]}</span>
              <strong>{counts[t.kind]}</strong>
            </a>
            <div className="muted">{t.hint}</div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// 正在进行：运行中的 agent、待生效的新版本；工作台服务的重启与停止也在这里（升级后用于加载新版本）
function OngoingCard() {
  const [runs, , reloadRuns] = useLoad(() => call<any[]>("agent.runs", { limit: 20 }), []);
  const [info, infoError] = useLoad(() => call<any>("server.info"), []);
  usePoll(reloadRuns);
  const [phase, setPhase] = useState<"idle" | "restarting" | "stopped" | "timeout">("idle");
  const [fail, setFail] = useState<string | null>(null);
  const running = (runs ?? []).filter((r) => r.status === "running" || r.status === "cancelling");
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
    <Panel title="正在进行">
      <ErrorBox error={infoError ?? fail} />
      {phase === "restarting" && <div className="notice">正在重启，完成后页面会自动刷新…</div>}
      {phase === "stopped" && <div className="notice">工作台已停止。重新打开：运行 burrowl start，或从开始菜单打开“burrowl 工作台”。</div>}
      {phase === "timeout" && <div className="notice">90 秒内没有等到新进程，请查看日志或运行 burrowl status。</div>}
      {info?.update_pending && phase === "idle" && (
        <div className="notice">
          已安装 {info.installed_version}，当前运行 {info.version}：重启后生效。AI 客户端里的 MCP 需在客户端重启。
        </div>
      )}
      {running.length ? (
        <ul className="todo-list">
          {running.map((r) => (
            <li key={r.id}>
              <a href={href("agent")}>
                <Dot tone="accent" />
                <span title={r.data.prompt}>
                  {r.agent}：{(r.data.prompt ?? "").slice(0, 24)}
                </span>
                <Time value={r.created_at} />
              </a>
            </li>
          ))}
        </ul>
      ) : (
        !info?.update_pending && <Empty>没有正在进行的操作</Empty>
      )}
      <div className="service-row">
        <span className="muted" title={`${info?.data ?? ""}\n进程 ${info?.pid ?? ""}`}>
          工作台 {info?.version ?? "…"}
        </span>
        <button type="button" className={`small ${info?.update_pending ? "primary" : ""}`} disabled={phase !== "idle"} onClick={restart}>
          重启服务
        </button>
        <button type="button" className="small" disabled={phase !== "idle"} onClick={stop}>
          停止
        </button>
      </div>
    </Panel>
  );
}
