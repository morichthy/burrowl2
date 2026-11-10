// Agent：在本机启动 agent CLI，输出实时显示；运行记录按状态筛选。
import { useEffect, useRef, useState } from "react";
import { call, streamAgent } from "../api";
import { RUN_STATUS } from "../labels";
import { href, takePrompt } from "../router";
import { Action, Chips, Empty, IdLink, Panel, Tag, Time, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Agent() {
  const [agents] = useLoad(() => call<any[]>("agent.list"), []);
  const [agent, setAgent] = useState("");
  const [cwd, setCwd] = useState("");
  const [prompt, setPrompt] = useState(takePrompt);
  const [preamble, setPreamble] = useState(true);
  const [run, setRun] = useState<any>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [runs, , reloadRuns] = useLoad(() => call<any[]>("agent.runs", { limit: 50 }), []);
  usePoll(reloadRuns);
  const stop = useRef<() => void>(() => {});
  const consoleRef = useRef<HTMLPreElement>(null);
  useEffect(() => () => stop.current(), []);
  // 只列出设置中保存的配置；原先选中的配置被删除或改名后，改选可用的一条。
  useEffect(() => {
    if (!agents) return;
    if (!agents.some((a) => a.name === agent)) setAgent((agents.find((a) => a.available) ?? agents[0])?.name ?? "");
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
        <p className="muted">在本机启动 agent CLI 处理任务。它通过 MCP 回到本工作区读写，身份记为这次运行的 AI；输出保存在运行日志中。启动项与巡检共用，可在<a href={href("settings")}>设置 → Agent</a>管理。</p>
        <span className="filter-label">agent</span>
        {agents && agents.length === 0 && <Empty>还没有 Agent 配置，请先在<a href={href("settings")}>设置 → Agent</a>新增一条。</Empty>}
        <Chips
          all={null}
          options={(agents ?? []).map((a) => [a.name, a.available ? a.name : `${a.name}（未找到命令）`] as [string, string])}
          value={agent ? [agent] : []}
          onChange={(v) => setAgent(v[0] ?? agent)}
        />
        <input value={cwd} onChange={(e) => setCwd(e.target.value)} placeholder="工作目录（可选，默认数据目录）" />
        <textarea className="tall" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="任务，例如：核对 2号泵压力波动的原因，仅留存对后续排查有用的判断" />
        <div className="row">
          <Action label="启动" className="primary" disabled={!prompt.trim() || !agent} run={async () => watch(await call("agent.start", { agent, prompt, cwd: cwd || null, preamble }))} />
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
                  {r.status !== "running" && r.data.prompt && !r.data.inspection_id && (
                    <button type="button" className="link small-text" onClick={() => {
                      setPrompt(r.data.prompt);
                      setCwd(r.data.cwd ?? "");
                      setPreamble(r.data.preamble ?? true);
                      if (agents?.some((a) => a.name === r.agent)) setAgent(r.agent);
                    }}>再次使用任务</button>
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
