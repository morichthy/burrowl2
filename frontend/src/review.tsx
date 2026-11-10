// 统一的复核框（设计稿 04 D-17）：条目页（原件、判断、框架页）、关系图中边的详情、待决策页都用这一个组件。
// 显示当前复核状态与"复核与变更"历史，以及三个操作：复核、请人复核、交给 AI 复核。
import { useState } from "react";
import { call } from "./api";
import { REVIEW, REVIEW_VERDICT } from "./labels";
import { delegate } from "./router";
import { Action, IdLink, Tag, Time, useLoad } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

const KIND_LABEL: Record<string, string> = { page: "框架页", edge: "关系", judgment: "判断", artifact: "原件" };

// "交给 AI 复核"：把任务带到 Agent 页，由使用者选择并启动 CLI。
export function aiReviewPrompt(ids: string[]): string {
  return [
    `请用 burrowl 对下列条目做 AI 复核：${ids.join("、")}。`,
    "每一条：先用 entry_get / page_get 看它和它的输入清单（判断看它引用的原件段落），再用 artifact_read 读相关的原件段落，",
    "核对它是否如实反映了依据，然后调用 review_ai_submit（item_id、verdict、reason、model=你的模型名、cites）。",
    "要求：依据只能是原件段落（cite_as）、事实记录或判断，不能是框架页或边；引用的段落必须是本会话读过的；",
    "确认或驳回至少一条依据；依据只有未经人确认的 OCR / AI 识别文字时不能确认；拿不准就交 unsure（会请人复核）。",
    "不要复核本会话自己写的条目，不要修改判断层。",
  ].join("\n");
}

export function ReviewBox({ itemId, reload, compact, aiOnly }: { itemId: string; reload?: () => void; compact?: boolean; aiOnly?: boolean }) {
  const [hist, error, reloadHist] = useLoad(() => call<any>("review.history", { item_id: itemId }), [itemId]);
  const [mode, setMode] = useState<"" | "review" | "request">("");
  const [verdict, setVerdict] = useState("confirm");
  const [reason, setReason] = useState("");
  const [cites, setCites] = useState("");
  const [local, setLocal] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [undoReason, setUndoReason] = useState("");
  const [confirmAll, setConfirmAll] = useState(false);
  const [onlyRevocable, setOnlyRevocable] = useState(false);
  const done = () => {
    setMode("");
    setReason("");
    setCites("");
    setLocal(false);
    reloadHist();
    reload?.();
  };
  if (error) return <div className="error">{error}</div>;
  if (!hist) return null;
  const kind = hist.kind as string;
  const isJudgment = kind === "judgment";
  const items = (hist.items ?? []) as any[];
  const eligible = items.filter((h) => h.can_revoke);
  const selectedIds = eligible.map((h) => h.id).filter((id) => selected.includes(id));
  const reviewedByAi = items.some((h) => h.type === "review" && h.method === "ai" && h.verdict !== "request"
    && (kind !== "page" || h.version == null || h.version === hist.head_version));
  return (
    <div className={`review-box ${compact ? "compact" : ""}`}>
      <div className="review-head">
        <strong>复核</strong>
        {kind === "artifact" ? (
          <span className="muted small-text">原件的复核就是确认抽取（逐单元在上面的抽取层里，或在这里一次确认全部）</span>
        ) : (
          <Tag tone={hist.review === "human_reviewed" ? "good" : hist.review === "rejected" ? "bad" : "warn"}>
            {hist.review ? REVIEW[hist.review] ?? hist.review : "未复核"}
          </Tag>
        )}
        {hist.ai_flag && <Tag tone="bad">AI 认为有问题</Tag>}
        {hist.open_decision && <Tag tone="warn">在待决策里（影响 {hist.open_decision.impact}）</Tag>}
      </div>
      {items.length > 0 && (
        <details className="review-history-panel">
          <summary>复核与变更记录（{items.length} 条）</summary>
          {!aiOnly && kind === "artifact" && <label className="check small-text">
            <input type="checkbox" checked={onlyRevocable} onChange={(e) => setOnlyRevocable(e.target.checked)} />
            只看可撤销的抽取确认（{eligible.length} 条）
          </label>}
          {!aiOnly && eligible.length > 0 && <div className="row tight">
            <span className="muted small-text">勾选要撤销的人工记录。未勾选的记录继续有效。</span>
            {selectedIds.length > 0 && <>
              <input aria-label="撤销理由" placeholder="撤销理由" value={undoReason} onChange={(e) => setUndoReason(e.target.value)} />
              <Action label={`撤销所选（${selectedIds.length}）`} disabled={!undoReason.trim()} run={async () => {
                await call("review.revoke", { item_id: itemId, record_ids: selectedIds, reason: undoReason.trim() });
                setSelected([]);
                setUndoReason("");
                done();
              }} />
              <button type="button" className="small" onClick={() => setSelected([])}>清空选择</button>
            </>}
          </div>}
        <ul className="review-history">
          {[...(onlyRevocable ? eligible : items)].reverse().map((h: any) => (
            <li key={h.id}>
              {!aiOnly && h.can_revoke && <input type="checkbox" checked={selected.includes(h.id)}
                aria-label={`选择撤销${h.unit ? ` ${h.unit} 的抽取确认` : ` ${REVIEW_VERDICT[h.verdict] ?? "复核"}`}`}
                onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, h.id] : ids.filter((id) => id !== h.id))} />}{" "}
              <Time value={h.created_at} /> <span className="muted">{h.actor_id}</span>{" "}
              <Tag tone={h.method === "ai" ? "warn" : "muted"}>{h.method === "ai" ? `AI${h.model ? `·${h.model}` : ""}` : "人"}</Tag>{" "}
              <strong>{h.type === "review_revoked" ? (h.unit ? "撤销抽取确认" : "撤销人工复核") : REVIEW_VERDICT[h.type === "review" ? h.verdict : h.type] ?? h.verdict}</strong>
              {h.revoked && <Tag tone="muted">已撤销</Tag>}
              {h.unit && <span className="muted"> {h.unit}</span>}
              {h.anchor && <span className="muted"> {h.anchor}{h.part === "latex" ? "（公式）" : "（识别文字）"}</span>}
              {h.local_observation && <Tag tone="good">本地实证</Tag>}
              {h.legacy && <span className="muted small-text">（旧版记录 <IdLink id={h.id} />）</span>}
              {h.reason && <span>：{h.reason}</span>}
              {h.replaced_by && (
                <span>
                  {" "}
                  · 替代它的原件 <IdLink id={h.replaced_by} />
                </span>
              )}
              {h.cites?.length > 0 && (
                <span className="muted small-text">
                  {" "}
                  依据：
                  {h.cites.map((c: string) => (
                    <span key={c}>
                      <IdLink id={c} />{" "}
                    </span>
                  ))}
                </span>
              )}
              {h.link_id && <span className="muted small-text"> · {h.revoked ? "原写回关系已失效" : "已写回判断层"} <IdLink id={h.link_id} /></span>}
            </li>
          ))}
        </ul>
        </details>
      )}
      <div className="row tight">
        {!aiOnly && (kind === "artifact" ? (
          <button type="button" className="small" onClick={() => setConfirmAll(!confirmAll)}>确认全部抽取</button>
        ) : (
          <button type="button" className={mode === "review" ? "primary small" : "small"} onClick={() => setMode(mode === "review" ? "" : "review")}>
            复核
          </button>
        ))}
        {!aiOnly && <button type="button" className={mode === "request" ? "primary small" : "small"} onClick={() => setMode(mode === "request" ? "" : "request")}>
          请人复核
        </button>}
        {kind !== "artifact" && (
          <button type="button" className="small" disabled={!!hist.ai_allowed} title={hist.ai_allowed ?? "把复核任务带到 Agent 页"} onClick={() => delegate(aiReviewPrompt([itemId]))}>
            {reviewedByAi ? "再次交给 AI 复核" : "交给 AI 复核"}
          </button>
        )}
      </div>
      {confirmAll && <div className="row tight">
        <span>将确认当前所有有文本的抽取单元。</span>
        <Action label="确认全部单元" run={async () => {
          await call("artifact.verify_extraction", { artifact_id: itemId });
          setConfirmAll(false);
          done();
        }} />
        <button type="button" className="small" onClick={() => setConfirmAll(false)}>取消</button>
      </div>}
      {mode === "review" && (
        <div className="review-form">
          <div className="row tight">
            <label className="check">
              <input type="radio" checked={verdict === "confirm"} onChange={() => setVerdict("confirm")} />
              {isJudgment ? "依据仍支持它" : "确认"}
            </label>
            <label className="check">
              <input type="radio" checked={verdict === "reject"} onChange={() => setVerdict("reject")} />
              {isJudgment ? "依据不支持它" : "驳回"}
            </label>
          </div>
          {isJudgment && <p className="muted small-text">核对它与依据对不对得上，不在互相冲突的判断之间裁决。结论记为这条判断的复核历史，判断本身和写入时可信度不变。</p>}
          {kind === "edge" && <p className="muted small-text">两端都是判断的可能矛盾、可能替代，确认后写回判断层（写一条反对或替代关系）。</p>}
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="理由（必填）" />
          <input className="grow" value={cites} onChange={(e) => setCites(e.target.value)} placeholder="补充的依据（可选）：原件段落 art_…#p3-2、事实记录、判断 ID，用空格或逗号分开；不能是框架页" />
          {isJudgment && (
            <label className="check" title="你亲自看到或测到；当前地位会据此重新推出">
              <input type="checkbox" checked={local} onChange={(e) => setLocal(e.target.checked)} />
              本地实证（我亲自看到或测到）
            </label>
          )}
          <Action
            className={verdict === "reject" ? "danger" : "primary"}
            label={`提交${KIND_LABEL[kind] ?? ""}复核`}
            disabled={!reason.trim()}
            run={async () => {
              await call("review.submit", {
                item_id: itemId,
                verdict,
                reason,
                cites: cites.split(/[\s,，]+/).filter(Boolean),
                local_observation: local,
              });
              done();
            }}
          />
        </div>
      )}
      {mode === "request" && (
        <div className="review-form">
          <input className="grow" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="一句话：要看什么（加入待决策列表）" />
          <Action label="加入待复核" disabled={!reason.trim()} run={async () => (await call("review.request", { item_id: itemId, note: reason }), done())} />
        </div>
      )}
    </div>
  );
}
