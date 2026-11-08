// 待决策：按类型筛选（带数量），按影响范围排序；术语连接、复核、重新综合、未检查约束、传播超限。
// 设计稿 04 D-07：影响范围为 0 的折叠为"低影响"；另有每周抽查。复核项用统一的复核框（D-17），可多选交给 AI 复核（D-16）。
import { useState } from "react";
import { call } from "../api";
import { DECISION, PAGE_TYPE, REVIEW_VERDICT } from "../labels";
import { aiReviewPrompt, ReviewBox } from "../review";
import { delegate, href } from "../router";
import { Action, Chips, Empty, ErrorBox, IdLink, Panel, Tag, Time, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Decisions() {
  const [kinds, setKinds] = useState<string[]>([]);
  const [status, setStatus] = useState<string[]>(["open"]);
  const [picked, setPicked] = useState<string[]>([]);
  const [items, error, reload] = useLoad(() => call<any[]>("decision.list", { status: status[0] ?? null }), [status.join()]);
  usePoll(reload);
  const all = items ?? [];
  const counts = Object.fromEntries(Object.keys(DECISION).map((k) => [k, all.filter((d: any) => d.kind === k).length]));
  const shown = kinds.length ? all.filter((d: any) => kinds.includes(d.kind)) : all;
  const open = status[0] === "open";
  const main = open ? shown.filter((d: any) => d.impact > 0) : shown;
  const low = open ? shown.filter((d: any) => d.impact <= 0) : [];
  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const item = (d: any) => <DecisionItem key={d.id} d={d} reload={reload} picked={picked.includes(d.subject_id)} onPick={() => toggle(d.subject_id)} />;
  return (
    <>
      <Panel
        title="待决策"
        actions={
          <>
            <span className="muted">按影响范围排序；不阻塞导入和写入</span>
            {picked.length > 0 && (
              <button type="button" className="small primary" onClick={() => delegate(aiReviewPrompt(picked))}>
                交给 AI 复核（{picked.length}）
              </button>
            )}
          </>
        }
      >
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
        {main.length === 0 && low.length === 0 && <Empty>没有待决策项</Empty>}
        {main.map(item)}
        {low.length > 0 && (
          <details className="low-impact">
            <summary>低影响（{low.length} 项）：错了只影响浏览，不影响判断层</summary>
            {low.map(item)}
          </details>
        )}
      </Panel>
      {open && <Sample />}
    </>
  );
}

// 每周抽查（D-07）：从 AI 生成未复核的框架页里挑几页，人看过后用复核框确认或驳回；用来发现规则是否太松
function Sample() {
  const [data, error, reload] = useLoad(() => call<any>("review.sample"), []);
  const [openId, setOpenId] = useState<string | null>(null);
  if (error) return <ErrorBox error={error} />;
  if (!data || data.pages.length === 0) return null;
  return (
    <Panel title={`本周抽查（${data.week}）`} actions={<span className="muted">从 {data.pool} 页 AI 生成、未复核的框架页里挑出；同一周结果不变</span>}>
      <ul className="plain">
        {data.pages.map((p: any) => (
          <li key={p.id}>
            <a href={href("entry", p.id)}>{p.title}</a> <span className="muted">{PAGE_TYPE[p.type] ?? p.type}</span>{" "}
            <button type="button" className="link small-text" onClick={() => setOpenId(openId === p.id ? null : p.id)}>
              {openId === p.id ? "收起" : "复核"}
            </button>
            {openId === p.id && <ReviewBox itemId={p.id} reload={reload} compact />}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function DecisionItem({ d, reload, picked, onPick }: { d: any; reload: () => void; picked: boolean; onPick: () => void }) {
  const [closeReason, setCloseReason] = useState("");
  const [newName, setNewName] = useState(d.data.term ?? "");
  const [newKind, setNewKind] = useState("device");
  const open = d.status === "open";
  const reviewable = d.kind === "review" && d.subject_id && /^(pg|edg|jdg|art)_/.test(d.subject_id);
  return (
    <div className={`decision ${d.kind}`}>
      <div className="decision-head">
        {open && reviewable && !d.subject_id.startsWith("art_") && (
          <input type="checkbox" checked={picked} onChange={onPick} title="多选后一起交给 AI 复核" />
        )}
        <Tag tone={d.kind === "constraint_unchecked" || d.kind === "propagation_overflow" ? "bad" : "warn"}>{DECISION[d.kind] ?? d.kind}</Tag>
        <span className="mono">{d.id}</span>
        <span className="muted">影响 {d.impact}</span>
        {d.subject_id && <IdLink id={d.subject_id} />}
        <Time value={d.created_at} />
        {d.data.requested && <Tag>请人复核</Tag>}
        {!open && <Tag>{d.status === "resolved" ? (d.data.resolution?.by_ai ? "已由 AI 处理" : "已处理") : "已关闭"}</Tag>}
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
            {d.data.what} {d.data.title ?? ""} {d.data.reason ?? ""} {d.data.note && <span className="muted">（{d.data.note}）</span>}
          </p>
          {(d.data.notes ?? []).map((n: any, i: number) => (
            <p key={i} className="small-text">
              <Tag tone={n.verdict === "reject" ? "bad" : n.verdict === "confirm" ? "good" : "muted"}>
                {n.model ? `AI·${n.model}` : n.by} {n.verdict ? REVIEW_VERDICT[n.verdict] ?? n.verdict : "请人复核"}
              </Tag>{" "}
              {n.reason ?? n.note}
            </p>
          ))}
          {open && reviewable && <ReviewBox itemId={d.subject_id} reload={reload} compact />}
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
