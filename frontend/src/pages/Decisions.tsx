// 待决策：按类型筛选（带数量），按影响范围排序；术语连接、复核、重新综合、未检查约束、传播超限。
import { useState } from "react";
import { call } from "../api";
import { DECISION } from "../labels";
import { delegate } from "../router";
import { Action, Chips, Empty, ErrorBox, IdLink, Panel, Tag, Time, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Decisions() {
  const [kinds, setKinds] = useState<string[]>([]);
  const [status, setStatus] = useState<string[]>(["open"]);
  const [items, error, reload] = useLoad(() => call<any[]>("decision.list", { status: status[0] ?? null }), [status.join()]);
  usePoll(reload);
  const all = items ?? [];
  const counts = Object.fromEntries(Object.keys(DECISION).map((k) => [k, all.filter((d: any) => d.kind === k).length]));
  const shown = kinds.length ? all.filter((d: any) => kinds.includes(d.kind)) : all;
  return (
    <Panel title="待决策" actions={<span className="muted">按影响范围排序；不阻塞导入和写入</span>}>
      <div className="filter-rows">
        <span className="filter-label">类型</span>
        <Chips multi options={Object.entries(DECISION)} value={kinds} onChange={setKinds} counts={counts} />
        <span className="filter-label">状态</span>
        <Chips
          all="全部"
          options={[
            ["open", "待处理"],
            ["resolved", "已处理"],
            ["dismissed", "已关闭"],
          ]}
          value={status}
          onChange={setStatus}
        />
      </div>
      <ErrorBox error={error} />
      {shown.length === 0 && <Empty>没有待决策项</Empty>}
      {shown.map((d: any) => (
        <DecisionItem key={d.id} d={d} reload={reload} />
      ))}
    </Panel>
  );
}

function DecisionItem({ d, reload }: { d: any; reload: () => void }) {
  const [reason, setReason] = useState("");
  const [closeReason, setCloseReason] = useState("");
  const [newName, setNewName] = useState(d.data.term ?? "");
  const [newKind, setNewKind] = useState("device");
  const open = d.status === "open";
  return (
    <div className={`decision ${d.kind}`}>
      <div className="decision-head">
        <Tag tone={d.kind === "constraint_unchecked" || d.kind === "propagation_overflow" ? "bad" : "warn"}>{DECISION[d.kind] ?? d.kind}</Tag>
        <span className="mono">{d.id}</span>
        <span className="muted">影响 {d.impact}</span>
        {d.subject_id && <IdLink id={d.subject_id} />}
        <Time value={d.created_at} />
        {!open && <Tag>{d.status === "resolved" ? "已处理" : "已关闭"}</Tag>}
      </div>
      {d.kind === "term_link" && (
        <>
          <p>
            叫法「{d.data.term}」：{d.data.reason}
            {d.data.excerpt && <span className="muted">（原文：{d.data.excerpt}）</span>}
          </p>
          {open && (
            <>
              <div className="row">
                {d.data.candidates.map((c: any) => (
                  <Action key={c.id} label={`是 ${c.kind}「${c.name}」`} run={async () => (await call("term.decide", { decision_id: d.id, entity_id: c.id }), reload())} />
                ))}
              </div>
              <div className="row">
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="新实体名称" />
                <input value={newKind} onChange={(e) => setNewKind(e.target.value)} placeholder="类型" />
                <Action label="新建实体并连接" run={async () => (await call("term.decide", { decision_id: d.id, new_entity: { kind: newKind, name: newName } }), reload())} />
              </div>
            </>
          )}
        </>
      )}
      {d.kind === "review" && (
        <>
          <p>
            {d.data.what} {d.data.title ?? ""} {d.data.reason ?? ""}
          </p>
          {open && (d.subject_id?.startsWith("pg_") || d.subject_id?.startsWith("edg_")) && (
            <div className="row">
              <input className="grow" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="复核理由（必填；会写回判断层）" />
              <Action label="确认" disabled={!reason.trim()} run={async () => (await call("framework.review", { item_id: d.subject_id, verdict: "confirm", reason }), reload())} />
              <Action label="驳回" className="danger" disabled={!reason.trim()} run={async () => (await call("framework.review", { item_id: d.subject_id, verdict: "reject", reason }), reload())} />
            </div>
          )}
        </>
      )}
      {d.kind === "rederive" && (
        <p>
          {d.data.title}：{d.data.reason}{" "}
          {open && (
            <button type="button" onClick={() => delegate(`处理待决策 ${d.id}：框架页 ${d.subject_id} 的输入已变化。请用 page_get 读取当前版本与输入清单，查看相关新判断后用 page_write 写出新版本，inputs 列出实际依据。`)}>
              交给 agent
            </button>
          )}
        </p>
      )}
      {d.kind === "constraint_unchecked" && (
        <p>
          {d.data.actor_id} 执行 {d.data.op} 前没有检查约束：{d.data.constraints.map((c: any) => c.text).join("；")}
        </p>
      )}
      {d.kind === "propagation_overflow" && (
        <p>
          传播超过上限，{d.data.unchecked.length} 个条目标为"未核查"：{d.data.reason}
        </p>
      )}
      {open && (
        <div className="row">
          <input className="grow" value={closeReason} onChange={(e) => setCloseReason(e.target.value)} placeholder="关闭理由" />
          <Action label="关闭" run={async () => (await call("decision.dismiss", { decision_id: d.id, reason: closeReason || "不处理" }), reload())} />
        </div>
      )}
    </div>
  );
}
