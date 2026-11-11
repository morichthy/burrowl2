// 定期巡检（设计稿 08）在待决策页里的两部分：
// · 巡检栏：本期巡检包、开始巡检 / 复制领取提示（都由人点，D-01、D-27）、离线包与贴回（D-29）、关闭本期；
// · 巡检发现：每条就是一项待决策（kind=finding，§9），按巡检运行分组，"交给复核员"由人点（D-02、D-22），人采纳、驳回或忽略（D-23）。
import { useState } from "react";
import { call } from "./api";
import { CHECK_LABEL, FINDING_REVIEW, FINDING_STATUS, INSPECTION_STATUS, KIND_HINT, SUGGESTION, WRITABLE_KIND } from "./labels";
import { DigestPanel } from "./digest";
import { go, href } from "./router";
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
  const rev = status?.reviewer ?? {};
  const start = async () => {
    const run = await call<any>("inspection.start", { inspection_id: latest.id, role: "inspector" });
    if (run.data?.terminal) go("agent", run.id);
    setMsg(`巡检 agent 已启动（${run.id}）：运行输出在 Agent 页，交上来的发现会出现在本栏下方`);
    reload();
  };
  const copyPrompt = async () => {
    const r = await call<any>("inspection.prompt", { inspection_id: latest.id, role: "inspector" });
    setPrompt(r.prompt);
    setMsg((await copy(r.prompt)) ? "领取提示已复制：交给任何连了 burrowl MCP 的 AI 客户端" : "请手动复制下面的领取提示");
  };
  // 不能启动巡检员的原因（设计稿 08 D-37）：按钮一直显示，灰掉时写明原因
  const blocked = !ins.agent ? "尚未启用巡检 agent" : !ins.available ? "本机找不到巡检 agent 的命令" : null;
  const open = latest && latest.status !== "closed";
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
        {open && <Action className="primary" label={latest.status === "ready" ? "开始巡检" : "再次运行巡检"} disabled={!!blocked} run={start} />}
        {open && <Action label="复制领取提示" run={copyPrompt} />}
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
      {open && blocked && (
        <p className="small-text warn-text">
          {blocked}，现在不能点“开始巡检”：到 <a href={href("settings")}>设置 → 巡检</a> 选择 agent、填命令路径并测试连接；也可以先点“复制领取提示”，交给任何连了 burrowl MCP 的 AI 客户端。
        </p>
      )}
      <p className="muted small-text">
        巡检 agent：{ins.agent ? "已启用" : "只复制提示"}{ins.agent && !ins.available ? "（找不到命令）" : ""} · 复核 agent：{rev.agent ? "已启用" : "只复制提示"}
        {rev.agent && !rev.available ? "（找不到命令）" : ""}。巡检员交的每条发现会出现在本栏下方，按运行分组；复核员在每组标题上的“交给复核员”启动；agent 的原始输出在{" "}
        <a href={href("agent")}>Agent 页</a>；巡检原则在设置页。
      </p>
      {latest && <TaskList inspectionId={latest.id} count={latest.tasks} />}
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

// 本期任务（D-37）：展开时才读取；可疑项在前，探索样本另折叠
function TaskList({ inspectionId, count }: { inspectionId: string; count: number }) {
  const [shown, setShown] = useState(false);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<any>(null);
  const toggle = async (open: boolean) => {
    setShown(open);
    if (open && !data) {
      try {
        setData(await call<any>("inspection.tasks", { inspection_id: inspectionId }));
      } catch (e) {
        setError(e);
      }
    }
  };
  const tasks: any[] = data?.tasks ?? [];
  const suspicious = tasks.filter((t) => t.check !== "explore");
  const explore = tasks.filter((t) => t.check === "explore");
  return (
    <details className="task-list" onToggle={(e) => toggle((e.target as HTMLDetailsElement).open)}>
      <summary className="small-text">本期任务（{count} 项）：规则检查看到了什么、要巡检员读哪些段落</summary>
      {shown && (
        <>
          <ErrorBox error={error} />
          {!data && !error && <p className="muted small-text">读取中…</p>}
          {data && suspicious.length === 0 && <p className="muted small-text">本期没有可疑项，只有探索样本</p>}
          {suspicious.map((t) => (
            <TaskRow key={t.id} t={t} />
          ))}
          {explore.length > 0 && (
            <details>
              <summary className="small-text">探索样本（{explore.length} 处）：没人读过、但被检索命中或与近期结论相关的段落</summary>
              {explore.map((t) => (
                <TaskRow key={t.id} t={t} />
              ))}
            </details>
          )}
        </>
      )}
    </details>
  );
}

function TaskRow({ t }: { t: any }) {
  const d = t.detail ?? {};
  // 各类检查的 detail 不同：与规则不符是问题列表，依据变化是按提示码分组，冲突是理由与共同对象
  const notes: string[] = [];
  if (Array.isArray(d.problems)) notes.push(...d.problems);
  else if (d.problems) notes.push(...Object.keys(d.problems).map((k) => d.labels?.[k] ?? k));
  if (d.reason) notes.push(d.reason + (d.objects?.length ? `（共同对象：${d.objects.join("、")}）` : ""));
  if (d.cited?.length) notes.push(`结论引用了 ${d.cited.join("、")}，附近有没读过的段落`);
  if (d.basis_complete === false) notes.push("依据边界不完整");
  if (t.check === "external_reliance") notes.push(`只有外部报告或推断作依据，被 ${d.dependents ?? 0} 条判断依赖、进入 ${d.pages ?? 0} 份页面，没有本地实证支持${d.external_author ? `（原作者：${d.external_author}）` : ""}`);
  if (t.check === "uncaptured") notes.push(`会话 ${d.session_id} 有 ${d.count ?? 0} 条操作没有任何判断提到${d.ops?.length ? `（${d.ops.join("、")}）` : ""}`);
  if (d.state) notes.push(`${d.state === "hit_unread" ? `被检索命中 ${d.hits ?? 0} 次、没人读过` : "与近期结论相关、没人读过"}${d.head ? `：${d.head}` : ""}`);
  return (
    <div className="task-row small-text">
      <div className="row tight">
        <span className="mono">{t.id}</span>
        <Tag tone={t.check === "conflict" ? "bad" : t.check === "explore" ? "muted" : "warn"}>{t.check_label ?? CHECK_LABEL[t.check] ?? t.check}</Tag>
        {t.done > 0 ? <Tag tone="good">已检查</Tag> : <Tag>未检查</Tag>}
        {t.human_only && <Tag tone="warn">含不外发原件</Tag>}
        <span>{t.title}</span>
      </div>
      {notes.length > 0 && <div>规则看到：{notes.join("；")}</div>}
      <div className="muted">{t.question}</div>
      <div className="row tight">
        {(t.targets ?? []).length > 0 && <span className="muted">针对</span>}
        {(t.targets ?? []).map((id: string) => (
          <IdLink key={id} id={id} />
        ))}
        {(t.read ?? []).length > 0 && <span className="muted">要读</span>}
        {(t.read ?? []).map((id: string) => (
          <IdLink key={id} id={id} />
        ))}
      </div>
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
  const reviewed = list.filter((f) => f.status === "open" && f.data.reviewer);
  const rev = status?.reviewer ?? {};
  const canReview = status?.latest?.id === inspectionId && status.latest.status !== "closed" && status.review_ai !== "off";
  const toReviewer = async (findings: any[]) => {
    const ids = findings.map((f) => f.id);
    if (rev.available) {
      const run = await call<any>("inspection.start", {
        inspection_id: inspectionId, role: "reviewer", finding_ids: ids,
      });
      if (run.data?.terminal) go("agent", run.id);
      setMsg(`复核 agent 已启动（${run.id}），输出见 Agent 页`);
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
        {canReview && unreviewed.length > 0 && <Action className="small primary" label={rev.available ? "交给复核员" : "复制复核提示"} run={() => toReviewer(unreviewed)} />}
        {canReview && reviewed.length > 0 && <Action className="small" label={rev.available ? "再次交给复核员" : "复制再次复核提示"} run={() => toReviewer(reviewed)} />}
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
  const [target, setTarget] = useState("");
  const d = f.data;
  const open = f.status === "open";
  const rv = d.reviewer;
  // 复核员提出的类型（D-41）；旧发现没有类型时按结论。人可以在写入前改
  const [kind, setKind] = useState<string>(rv?.proposed_kind || "conclusion");
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
      {rv?.proposed_change && (
        <div>
          <p><strong>复核员修改意见</strong> <Tag>{WRITABLE_KIND[rv.proposed_kind || "conclusion"]}</Tag>：{rv.proposed_change}</p>
          {rv.proposed_conditions && <p className="small-text">条件：{rv.proposed_conditions}</p>}
          {rv.proposed_reopen_condition && <p className="small-text">重开条件：{rv.proposed_reopen_condition}</p>}
        </div>
      )}
      {d.reviewer_history?.length > 0 && <details className="small-text">
        <summary>以往的复核意见（{d.reviewer_history.length}）</summary>
        {d.reviewer_history.map((r: any, i: number) => (
          <p key={i}><Time value={r.at} /> · {r.model} · {FINDING_REVIEW[{ confirm: "ai_reviewed", reject: "ai_flagged", unsure: "ai_unsure" }[r.verdict as string] ?? ""]} · {r.reason}
            {r.proposed_change && <span> · 修改意见：{r.proposed_change}</span>}
          </p>
        ))}
      </details>}
      {d.resolution?.judgment_id && <p>已写入判断 <IdLink id={d.resolution.judgment_id} /></p>}
      {open && (
        <>
          <div className="row tight">
            <input className="grow" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="处理说明（可空）" />
            <Action label="采纳" run={resolve("adopt")} />
            <Action label="驳回" run={resolve("reject")} />
            <Action label="忽略" run={resolve("ignore")} />
          </div>
          {rv?.verdict === "confirm" && rv.proposed_change && (
            <div className="row tight">
              <select aria-label="写入复核意见的方式" value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="">新增判断</option>
                {(d.targets ?? []).filter((id: string) => id.startsWith("jdg_")).map((id: string) =>
                  <option key={id} value={id}>更正 {id}</option>)}
              </select>
              {!target && (
                <select aria-label="新增判断的类型" value={kind} onChange={(e) => setKind(e.target.value)} title={KIND_HINT[kind]}>
                  {Object.entries(WRITABLE_KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              )}
              <Action label="采纳并写入判断" run={async () => {
                await call("finding.resolve", { decision_id: f.id, action: "adopt", reason, apply_change: true,
                  target: target || null, kind: target ? null : kind });
                reload();
              }} />
            </div>
          )}
          <p className="muted small-text">普通采纳只处理这条发现。有依据的复核修改意见，可由你确认写入。</p>
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
      <DigestPanel onChange={reload} />
      {findings.length > 0 && <FindingGroups items={findings} status={status} reload={() => (reload(), reloadFindings())} />}
    </>
  );
}
