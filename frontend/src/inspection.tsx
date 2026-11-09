// 定期巡检（设计稿 08）在待决策页里的两部分：
// · 巡检栏：本期巡检包、开始巡检 / 复制领取提示（都由人点，D-01、D-27）、离线包与贴回（D-29）、关闭本期；
// · 巡检发现：每条就是一项待决策（kind=finding，§9），按巡检运行分组，"交给复核员"由人点（D-02、D-22），人采纳、驳回或忽略（D-23）。
import { useState } from "react";
import { call } from "./api";
import { CHECK_LABEL, FINDING_REVIEW, FINDING_STATUS, INSPECTION_STATUS, SUGGESTION } from "./labels";
import { href } from "./router";
import { Action, Empty, ErrorBox, IdLink, Tag, Time, useLoad, usePoll } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function InspectionBar({ status, reload }: { status: any; reload: () => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const [pasted, setPasted] = useState("");
  const [model, setModel] = useState("");
  const latest = status?.latest;
  const ins = status?.inspector ?? {};
  const startOrCopy = async () => {
    if (ins.available) {
      const run = await call<any>("inspection.start", { inspection_id: latest.id, role: "inspector" });
      setMsg(`巡检员 ${ins.agent} 已启动（${run.id}），输出见 Agent 页`);
    } else {
      const r = await call<any>("inspection.prompt", { inspection_id: latest.id, role: "inspector" });
      setPrompt(r.prompt);
      setMsg((await copy(r.prompt)) ? "领取提示已复制：交给任何连了 burrowl MCP 的 AI 客户端" : "请手动复制下面的领取提示");
    }
    reload();
  };
  if (!status) return null;
  return (
    <div className="decision inspection-bar">
      <div className="decision-head">
        <Tag tone="accent">定期巡检</Tag>
        {latest ? (
          <>
            <span>第 {latest.period} 期</span>
            <Tag tone={latest.status === "ready" ? "accent" : "muted"}>{INSPECTION_STATUS[latest.status] ?? latest.status}</Tag>
            <span className="muted small-text">
              准备于 <Time value={latest.prepared_at} />（{latest.trigger === "schedule" ? "定时" : "手动"}）· {latest.suspicious} 项可疑、{latest.explore} 处探索样本 · 已检查 {latest.checked}/{latest.tasks}
              {latest.human_only ? ` · ${latest.human_only} 项含不外发原件，只能由人看` : ""}
            </span>
          </>
        ) : (
          <span className="muted small-text">还没有巡检包；到期（每 {status.interval_days} 天）会在本机准备，也可以现在准备</span>
        )}
        <a className="small-text" href={href("coverage")}>
          覆盖图 →
        </a>
      </div>
      <div className="row tight">
        <Action label={latest?.status === "ready" ? "重新准备本期" : "现在准备巡检包"} disabled={latest && ["running", "done"].includes(latest.status)} run={async () => (await call("inspection.prepare"), reload())} />
        {latest && latest.status !== "closed" && <Action className="primary" label={ins.available ? `开始巡检（${ins.agent}）` : "复制领取提示"} run={startOrCopy} />}
        {latest && (
          <Action
            label="离线包"
            run={async () => {
              const r = await call<any>("inspection.export", { inspection_id: latest.id });
              setOffline(r.markdown);
            }}
          />
        )}
        {latest && latest.status !== "closed" && <Action label="关闭本期" run={async () => (await call("inspection.close", { inspection_id: latest.id }), reload())} />}
        <span className="muted small-text">定时只在本机做规则检查，不调用大模型；巡检员和复核员都由你点按钮启动</span>
      </div>
      {ins.agent && !ins.available && <p className="small-text warn-text">巡检员 agent「{ins.agent}」在本机找不到命令，改为复制领取提示。可以在设置页测试连接。</p>}
      {msg && <p className="small-text">{msg}</p>}
      {prompt && <textarea readOnly value={prompt} rows={3} className="mono" />}
      {offline != null && latest && (
        <div className="field-stack">
          <p className="muted small-text">客户端连不上 MCP 时用：把下面的内容交给 AI，再把它输出的 JSON 贴回来。贴回的发现记为“经人转交”，没有读取记录，复核员不能确认。</p>
          <textarea readOnly value={offline} rows={8} className="mono" />
          <div className="row tight">
            <button type="button" className="small" onClick={() => copy(offline)}>
              复制离线包
            </button>
          </div>
          <textarea value={pasted} onChange={(e) => setPasted(e.target.value)} rows={4} placeholder="贴回 AI 输出的 JSON 数组" />
          <div className="row tight">
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="给出结果的模型（必填）" />
            <Action
              label="贴回结果"
              disabled={!pasted.trim() || !model.trim()}
              run={async () => {
                const r = await call<any>("inspection.import", { inspection_id: latest.id, text: pasted, model });
                setMsg(`贴回了 ${r.created.length} 条发现${r.skipped.length ? `，${r.skipped.length} 项对不上任务` : ""}`);
                setPasted("");
                reload();
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// 巡检发现按巡检运行分组（D-22）：组标题显示运行、巡检员、复核员还没看过的数量
export function FindingGroups({ items, status, reload }: { items: any[]; status: any; reload: () => void }) {
  const [onlyDisagree, setOnlyDisagree] = useState(false);
  const shown = onlyDisagree ? items.filter((f) => f.data.reviewer && f.data.reviewer.verdict !== "confirm") : items;
  const groups = new Map<string, any[]>();
  for (const f of [...shown].sort((a, b) => b.impact - a.impact || a.created_at.localeCompare(b.created_at))) {
    const d = f.data;
    const key = `${d.inspection_id}|${d.run_id ?? d.session_id ?? (d.method === "relayed" ? "relayed" : "manual")}`;
    groups.set(key, [...(groups.get(key) ?? []), f]);
  }
  return (
    <>
      <div className="row tight">
        <label className="check">
          <input type="checkbox" checked={onlyDisagree} onChange={(e) => setOnlyDisagree(e.target.checked)} /> 只看巡检员与复核员意见不一致的
        </label>
        {status?.review_ai && status.review_ai !== "all" && <span className="muted small-text">发现针对的判断要由复核员一并复核时，“复核”里的 AI 复核范围要设为 all</span>}
        {status?.same_agent && <span className="small-text warn-text">巡检员和复核员用的是同一个 agent：二次检查的独立性降低</span>}
      </div>
      {groups.size === 0 && <Empty>{items.length ? "没有意见不一致的发现" : "没有巡检发现"}</Empty>}
      {[...groups.entries()].map(([key, list]) => (
        <FindingGroup key={key} groupKey={key} list={list} status={status} reload={reload} />
      ))}
    </>
  );
}

function FindingGroup({ groupKey, list, status, reload }: { groupKey: string; list: any[]; status: any; reload: () => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [inspectionId, runKey] = groupKey.split("|");
  const unreviewed = list.filter((f) => f.status === "open" && f.data.review === "ai_generated");
  const rev = status?.reviewer ?? {};
  const toReviewer = async () => {
    const ids = unreviewed.map((f) => f.id);
    if (rev.available) {
      const run = await call<any>("inspection.start", { inspection_id: inspectionId, role: "reviewer", finding_ids: ids });
      setMsg(`复核员 ${rev.agent} 已启动（${run.id}），输出见 Agent 页`);
    } else {
      const r = await call<any>("inspection.prompt", { inspection_id: inspectionId, role: "reviewer", finding_ids: ids });
      setMsg((await copy(r.prompt)) ? `复核提示已复制：${r.prompt}` : `请手动复制：${r.prompt}`);
    }
  };
  const label = runKey.startsWith("run_") ? `运行 ${runKey}` : runKey === "relayed" ? "经人转交的离线结果" : `会话 ${runKey}`;
  return (
    <div className="decision finding-group">
      <div className="decision-head">
        <Tag tone="accent">巡检发现</Tag>
        <span className="mono">{label}</span>
        <span className="muted">
          第 {list[0]?.data.period} 期 · {list.length} 项{unreviewed.length ? `，复核员还没看过 ${unreviewed.length} 项` : ""}
        </span>
        {list[0]?.data.by && <span className="muted small-text">巡检员 {list[0].data.by}</span>}
        <Time value={list[0]?.created_at} />
        {unreviewed.length > 0 && <Action className="small primary" label={rev.available ? `交给复核员（${rev.agent}）` : "复制复核提示"} run={toReviewer} />}
      </div>
      {msg && <p className="small-text">{msg}</p>}
      {list.map((f) => (
        <FindingItem key={f.id} f={f} reload={reload} />
      ))}
    </div>
  );
}

function FindingItem({ f, reload }: { f: any; reload: () => void }) {
  const [reason, setReason] = useState("");
  const d = f.data;
  const open = f.status === "open";
  const rv = d.reviewer;
  const tone = d.review === "ai_reviewed" ? "good" : d.review === "ai_flagged" ? "bad" : "muted";
  const resolve = (action: string) => async () => (await call("finding.resolve", { decision_id: f.id, action, reason }), reload());
  return (
    <div className="finding">
      <div className="row tight">
        <span className="mono">{f.id}</span>
        <Tag tone={d.check === "conflict" ? "bad" : "warn"}>{CHECK_LABEL[d.check] ?? d.check}</Tag>
        <Tag tone={tone}>{FINDING_REVIEW[d.review] ?? d.review}</Tag>
        {d.method === "relayed" && <Tag tone="warn">经人转交</Tag>}
        {!open && <Tag>{d.resolution?.action ? FINDING_STATUS[d.resolution.action] : FINDING_STATUS[f.status] ?? f.status}</Tag>}
      </div>
      <p>{d.summary}</p>
      <div className="row tight small-text">
        <span className="muted">针对</span>
        {(d.targets ?? []).map((id: string) => (
          <IdLink key={id} id={id} />
        ))}
        <span className="muted">依据</span>
        {(d.cites ?? []).map((id: string) => (
          <IdLink key={id} id={id} />
        ))}
      </div>
      <p className="muted small-text">
        建议：{SUGGESTION[d.suggestion] ?? d.suggestion} · 模型 {d.model}
      </p>
      {rv && (
        <p className="small-text">
          <Tag tone={rv.verdict === "confirm" ? "good" : rv.verdict === "reject" ? "bad" : "muted"}>复核员·{rv.model}</Tag> {rv.reason}
        </p>
      )}
      {open && (
        <>
          <div className="row tight">
            <input className="grow" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="处理说明（可空）" />
            <Action label="采纳" run={resolve("adopt")} />
            <Action label="驳回" run={resolve("reject")} />
            <Action label="忽略" run={resolve("ignore")} />
          </div>
          <p className="muted small-text">采纳只记下你认可这条发现；要改的请点上面针对的条目，用复核、更正、撤回或写反对判断。处理过的发现下一期不再提出。</p>
        </>
      )}
    </div>
  );
}

// 待决策页用：巡检栏 + 待处理的巡检发现
export function InspectionSection({ findings, reloadFindings }: { findings: any[]; reloadFindings: () => void }) {
  const [status, error, reload] = useLoad(() => call<any>("inspection.status"), []);
  usePoll(reload, 15000);
  return (
    <>
      <ErrorBox error={error} />
      <InspectionBar status={status} reload={() => (reload(), reloadFindings())} />
      {findings.length > 0 && <FindingGroups items={findings} status={status} reload={() => (reload(), reloadFindings())} />}
    </>
  );
}
