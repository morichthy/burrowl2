// Agent：在本机启动 agent CLI，输出实时显示；运行记录按状态筛选。
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { call, streamAgent } from "../api";
import { RUN_STATUS } from "../labels";
import { modelJobLabel, modelJobStatus, type ModelJob } from "../modelJobs";
import { href, takePrompt } from "../router";
import { Action, Chips, Empty, ErrorBox, IdLink, Panel, Tag, Time, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
const AgentTerminal = lazy(() => import("../AgentTerminal").then((module) => ({ default: module.AgentTerminal })));


export function Agent({ runId }: { runId?: string } = {}) {
  const [agents] = useLoad(() => call<any[]>("agent.list"), []);
  const [dispatch, dispatchError] = useLoad(() => call<{ mode: string }>("agent.dispatch"), []);
  const [agent, setAgent] = useState("");
  const [cwd, setCwd] = useState("");
  const [prompt, setPrompt] = useState(takePrompt);
  const [preamble, setPreamble] = useState(true);
  const [run, setRun] = useState<any>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [autoClose, setAutoClose] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [runs, , reloadRuns] = useLoad(() => call<any[]>("agent.runs", { limit: 50 }), []);
  const [models, , reloadModels] = useLoad(() => call<any>("models.status"), []);
  const modelJobs: ModelJob[] = models?.jobs ?? [];
  const model = modelJobs.find((j) => j.id === selectedModel)
    ?? (!selectedModel && !run ? modelJobs.find((j) => j.status === "running" || j.status === "cancelling")
      ?? modelJobs.find((j) => j.status === "queued") : undefined);
  const modelId = model?.id;
  const [output, outputError, reloadOutput] = useLoad(
    () => modelId ? call<{ job_id: string; text: string }>("models.output", { job_id: modelId }) : Promise.resolve(null), [modelId],
  );
  const modelText = output && output.job_id === modelId ? output.text : "";
  usePoll(reloadRuns);
  usePoll(reloadModels, 1500);
  usePoll(reloadOutput, 1500);
  const stop = useRef<() => void>(() => {});
  const autoCloseRef = useRef(autoClose);
  autoCloseRef.current = autoClose;
  const consoleRef = useRef<HTMLPreElement>(null);
  useEffect(() => () => stop.current(), []);
  // 只列出设置中保存的配置；原先选中的配置被删除或改名后，改选可用的一条。
  useEffect(() => {
    if (!agents || !dispatch?.mode) return;
    if (!agents.some((a) => a.name === agent)) {
      const usable = agents.find((a) => dispatch?.mode === "terminal" ? a.terminal_available : a.available);
      setAgent((usable ?? agents[0])?.name ?? "");
    }
  }, [agents, agent, dispatch?.mode]);
  useEffect(() => {
    consoleRef.current?.scrollTo?.({ top: consoleRef.current.scrollHeight });
  }, [lines, modelText]);
  const watch = (r: any) => {
    stop.current();
    setSelectedModel(null);
    setRun(r);
    setPanelOpen(true);
    setLines([]);
    const live = r.status === "running" || r.status === "cancelling";
    setRunning(live);
    stop.current = streamAgent(
      r.id,
      (line) => setLines((ls) => [...ls, line]),
      () => {
        setRunning(false);
        if (live && r.data?.terminal && autoCloseRef.current) setPanelOpen(false);
        reloadRuns();
      },
    );
  };
  const openedRun = useRef(false);
  useEffect(() => {
    if (!runId || openedRun.current || !runs) return;
    openedRun.current = true;
    const target = runs.find((r) => r.id === runId);
    if (target) watch(target);
  }, [runId, runs]);
  const statuses = { queued: "排队中", ...RUN_STATUS };
  const records = [...(runs ?? []).map((r) => ({ ...r, source: "agent" })), ...modelJobs.map((j) => ({ ...j, source: "model" }))]
    .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  const counts = Object.fromEntries(Object.keys(statuses).map((k) => [k, records.filter((r) => r.status === k).length]));
  const shown = records.filter((r) => !statusFilter.length || statusFilter.includes(r.status));
  const terminal = dispatch?.mode === "terminal";
  const selectedAgent = agents?.find((a) => a.name === agent);
  const batch = runs?.find((r) => r.id === run?.id)?.data?.recognition_batch ?? run?.data?.recognition_batch;
  return (
    <div className="split">
      <Panel title="启动 agent">
        <p className="muted">在本机启动 agent CLI 处理任务。它通过 MCP 回到本工作区读写，身份记为这次运行的 AI；输出保存在运行日志中。启动项与巡检共用，可在<a href={href("settings")}>设置 → Agent</a>管理。</p>
        <ErrorBox error={dispatchError} />
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
          <Action label={terminal ? "启动终端" : "后台运行"} className="primary"
            disabled={!dispatch?.mode || !prompt.trim() || !(terminal ? selectedAgent?.terminal_available : selectedAgent?.available)}
            run={async () => watch(await call("agent.start", { agent, prompt, cwd: cwd || null, preamble }))} />
          {terminal && <label><input type="checkbox" checked={autoClose} onChange={(e) => setAutoClose(e.target.checked)} /> 会话结束后收起终端</label>}
        </div>
        {terminal && agent && !selectedAgent?.terminal_available && <p className="muted small-text">
          这个 Agent 暂未配置浏览器终端。可在「设置 → Agent」填写交互启动参数，或切换默认启动方式。
        </p>}
        {run && (
          <>
            <h3>
              <span className="mono">{run.id}</span> {running ? <Tag tone="accent">运行中…</Tag> : <Tag>已结束</Tag>}
            </h3>
            {batch && <p role="status">
              {batch.key.kind === "formula" ? "公式识别" : "识别复核"} · 已保存 {batch.saved}/{batch.total} 个块
              {batch.skipped ? `，跳过 ${batch.skipped} 个` : ""}
              {batch.ended && batch.missing ? `，未返回 ${batch.missing} 个` : ""}
              {batch.last_error ? ` · ${batch.last_error}` : ""}
            </p>}
            <div className="row">
              {running && <Action label={run.data?.terminal ? "结束会话" : "停止"} className="danger"
                run={() => call("agent.cancel", { run_id: run.id })} />}
              {run.data?.terminal && <button type="button" onClick={() => setPanelOpen(!panelOpen)}>
                {panelOpen ? "关闭面板" : running ? "重新打开终端" : "查看终端记录"}
              </button>}
            </div>
            {run.data?.terminal ? panelOpen && (
              <>
                {running && run.data.terminal_prompt && <details>
                  <summary>复制初始任务到终端</summary>
                  <pre>{run.data.terminal_prompt}</pre>
                  <Action label="复制任务" run={() => navigator.clipboard.writeText(run.data.terminal_prompt)} />
                </details>}
                <Suspense fallback={<p className="muted">正在打开终端…</p>}>
                  <AgentTerminal key={run.id} runId={run.id} chunks={lines} active={running} />
                </Suspense>
              </>
            ) : <pre className="console" ref={consoleRef}>{lines.join("")}</pre>}
          </>
        )}
        {model && (
          <>
            <h3>{modelJobLabel(model.kind)} · <IdLink id={model.artifact_id} /></h3>
            <p>{modelJobStatus(model)}{model.progress?.model && ` · ${model.progress.model}`}</p>
            <p className="muted small-text">
              {model.progress?.item_started_at ? "当前块开始于 " : model.finished_at ? "结束于 " : model.started_at ? "开始于 " : "提交于 "}
              <Time value={model.progress?.item_started_at ?? model.finished_at ?? model.started_at ?? model.created_at} />
            </p>
            {(model.error || model.progress?.last_error) && <p className="warn-text">最近错误：{model.error ?? model.progress?.last_error}</p>}
            {model.kind === "ai_check" && (model.status === "queued" || model.status === "running") && (
              <Action label={model.status === "queued" ? "取消排队" : "停止复核"} className="danger" run={async () => {
                await call("models.cancel", { job_id: model.id });
                setSelectedModel(model.id);
                reloadModels();
              }} />
            )}
            <pre className="console" ref={consoleRef}>{modelText || outputError || "等待任务输出…"}</pre>
            <p className="muted small-text">工作台重启会清空这里的任务输出。已保存的核对结果可在原件的复核记录里查看。</p>
          </>
        )}
      </Panel>
      <aside>
        <Panel title="运行记录">
          <Chips multi options={Object.entries(statuses)} value={statusFilter} onChange={setStatusFilter} counts={counts} />
          {shown.length === 0 && <Empty>没有运行记录</Empty>}
          <ul className="run-list">
            {shown.map((r) => (
              r.source === "model" ? (
                <li key={r.id} className={modelId === r.id ? "on" : ""}>
                  <button type="button" className="link" onClick={() => {
                    stop.current();
                    setRun(null);
                    setRunning(false);
                    setSelectedModel(r.id);
                  }}>{modelJobLabel(r.kind)}</button>
                  <div className="muted"><IdLink id={r.artifact_id} /> · {modelJobStatus(r)}</div>
                </li>
              ) : (
              <li key={r.id} className={run?.id === r.id ? "on" : ""}>
                <button type="button" className="link" onClick={() => run?.id === r.id ? setPanelOpen(true) : watch(r)}>
                  {r.agent} · {r.data.recognition_batch
                    ? (r.data.recognition_batch.key.kind === "formula" ? "公式识别" : "识别复核") + `（${r.data.recognition_batch.total}）`
                    : (r.data.prompt ?? "").slice(0, 40)}
                </button>
                <div className="muted">
                  <Tag tone={r.status === "done" ? "good" : r.status === "running" ? "accent" : "bad"}>{RUN_STATUS[r.status] ?? r.status}</Tag> <Time value={r.created_at} />
                  {r.data.artifact_id && (
                    <>
                      {" "}
                      · 对话原件 <IdLink id={r.data.artifact_id} />
                    </>
                  )}
                  {r.status !== "running" && r.data.prompt && !r.data.inspection_id && !r.data.recognition_batch && (
                    <button type="button" className="link small-text" onClick={() => {
                      setPrompt(r.data.prompt);
                      setCwd(r.data.cwd ?? "");
                      setPreamble(r.data.preamble ?? true);
                      if (agents?.some((a) => a.name === r.agent)) setAgent(r.agent);
                    }}>再次使用任务</button>
                  )}
                </div>
              </li>
              )
            ))}
          </ul>
        </Panel>
      </aside>
    </div>
  );
}
