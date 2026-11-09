// Agent：在本机启动 agent CLI，输出实时显示；运行记录按状态筛选。
import { useEffect, useRef, useState } from "react";
import { call, streamAgent } from "../api";
import { RUN_STATUS } from "../labels";
import { takePrompt } from "../router";
import { Action, Chips, Empty, IdLink, Panel, Tag, Time, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Agent() {
  const [agents] = useLoad(() => call<any[]>("agent.list"), []);
  const [agent, setAgent] = useState("");
  const [cwd, setCwd] = useState("");
  const [prompt, setPrompt] = useState(takePrompt);
  const [run, setRun] = useState<any>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [runs, , reloadRuns] = useLoad(() => call<any[]>("agent.runs", { limit: 50 }), []);
  usePoll(reloadRuns);
  const stop = useRef<() => void>(() => {});
  const consoleRef = useRef<HTMLPreElement>(null);
  useEffect(() => () => stop.current(), []);
  useEffect(() => {
    if (!agent && agents?.length) setAgent((agents.find((a) => a.available) ?? agents[0]).name);
  }, [agents, agent]);
  useEffect(() => {
    consoleRef.current?.scrollTo({ top: consoleRef.current.scrollHeight });
  }, [lines]);
  const watch = (r: any) => {
    stop.current();
    setRun(r);
    setLines([]);
    setRunning(true);
    stop.current = streamAgent(
      r.id,
      (line) => setLines((ls) => [...ls, line]),
      () => (setRunning(false), reloadRuns()),
    );
  };
  const counts = Object.fromEntries(Object.keys(RUN_STATUS).map((k) => [k, (runs ?? []).filter((r) => r.status === k).length]));
  const shown = (runs ?? []).filter((r) => !statusFilter.length || statusFilter.includes(r.status));
  return (
    <div className="split">
      <Panel title="启动 agent">
        <p className="muted">在本机启动 agent CLI 处理任务。它通过 MCP 回到本工作区读写，身份记为这次运行的 AI；输出保存在运行日志中。</p>
        <span className="filter-label">agent</span>
        <Chips
          all={null}
          options={(agents ?? []).map((a) => [a.name, a.available ? a.name : `${a.name}（未找到命令）`] as [string, string])}
          value={agent ? [agent] : []}
          onChange={(v) => setAgent(v[0] ?? agent)}
        />
        <input value={cwd} onChange={(e) => setCwd(e.target.value)} placeholder="工作目录（可选，默认数据目录）" />
        <textarea className="tall" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="任务，例如：核对 2号泵压力波动的原因，仅留存对后续排查有用的判断" />
        <div className="row">
          <Action label="启动" className="primary" disabled={!prompt.trim()} run={async () => watch(await call("agent.start", { agent, prompt, cwd: cwd || null }))} />
          {running && run && <Action label="停止" className="danger" run={() => call("agent.cancel", { run_id: run.id })} />}
        </div>
        {run && (
          <>
            <h3>
              <span className="mono">{run.id}</span> {running ? <Tag tone="accent">运行中…</Tag> : <Tag>已结束</Tag>}
            </h3>
            <pre className="console" ref={consoleRef}>
              {lines.join("")}
            </pre>
          </>
        )}
      </Panel>
      <aside>
        <Panel title="运行记录">
          <Chips multi options={Object.entries(RUN_STATUS)} value={statusFilter} onChange={setStatusFilter} counts={counts} />
          {shown.length === 0 && <Empty>没有运行记录</Empty>}
          <ul className="run-list">
            {shown.map((r) => (
              <li key={r.id} className={run?.id === r.id ? "on" : ""}>
                <button type="button" className="link" onClick={() => watch(r)}>
                  {r.agent} · {(r.data.prompt ?? "").slice(0, 40)}
                </button>
                <div className="muted">
                  <Tag tone={r.status === "done" ? "good" : r.status === "running" ? "accent" : "bad"}>{RUN_STATUS[r.status] ?? r.status}</Tag> <Time value={r.created_at} />
                  {r.data.artifact_id && (
                    <>
                      {" "}
                      · 对话原件 <IdLink id={r.data.artifact_id} />
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </aside>
    </div>
  );
}
