// 条目页的"操作"：人对一条条目能做的事都收在这里（更正、改关系与依据、撤回、标缺陷、退役、复核、外发……）。
// 先在菜单里选一个动作（每项一句后果说明），页面里展开一张只属于它的表单：说明 → 该动作的专有项 → 摘要 → 提交。
// 每个动作各有自己的说明框；按钮灰着时旁边写明还缺什么。版本历史是只读的，见 Entries.tsx 的 VersionHistory。
import { useState, type ReactNode } from "react";
import { call } from "./api";
import { EntryPicker } from "./EntryPicker";
import { RelationEditor } from "./RelationEditor";
import { ReviewBox, type ReviewMode } from "./review";
import { go } from "./router";
import { Action, IdLink, Tag } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Level = "normal" | "impact";
type Def = { key: string; label: string; hint: string; level: Level };

const LEVEL_TEXT: Record<Level, string> = { normal: "可撤销", impact: "影响别的条目" };
const REVIEW_KEYS: Record<string, ReviewMode> = { review: "review", request: "request", confirmAll: "confirmAll", ai: "ai" };

// 当前条目、当前版本能做哪些动作（顺序即菜单顺序）
export function availableActions(entry: any, current: any, isHead: boolean): Def[] {
  const kind = entry.entry_kind;
  const judgment = kind === "judgment";
  const artifact = kind === "artifact";
  const out: Def[] = [];
  if (isHead) {
    out.push({
      key: "correct", level: "normal",
      label: artifact ? "登记新版" : judgment ? "写新版本（更正）" : "更正",
      hint: artifact ? "提供新的文件或正文，追加成新版本；旧版保留" : "改正文，追加成新版本；旧版保留，引用仍指向当时的版本",
    });
    if (judgment) out.push({ key: "relations", level: "normal", label: "改关系与依据", hint: "增删依据、佐证、反驳、替代等关系，写成新版本，正文不变" });
  } else if (!current.withdrawn && !current.retired) {
    out.push({ key: "reactivate", level: "normal", label: "让这一版重新生效", hint: "复制这一版的内容写成新的当前版" });
  }
  if (judgment) {
    out.push(current.withdrawn
      ? { key: "unwithdraw", level: "normal", label: "取消撤回", hint: "让这一版重新参与列表、检索与依据" }
      : { key: "withdraw", level: "impact", label: "撤回本版", hint: "不再参与检索；引用它的条目会标为依据有变化；可以取消撤回" });
  } else {
    out.push(current.defective
      ? { key: "undefect", level: "normal", label: "取消缺陷标记", hint: "去掉本版的缺陷标记" }
      : { key: "defect", level: "impact", label: "标记本版有缺陷", hint: "引用它的条目会标为依据有变化；内容不改，可以取消标记" });
  }
  if (artifact && isHead && !current.retired) {
    out.push({ key: "retire", level: "impact", label: "退役本原件", hint: "内容没错，只是不再单独出现；只引用它的条目会一并隐藏；可以撤销" });
  }
  if (judgment) {
    out.push({ key: "review", level: "normal", label: "复核", hint: "核对它与依据对不对得上；记为复核历史，条目本身不变" });
    out.push({ key: "ai", level: "normal", label: "交给 AI 复核", hint: "把复核任务带到 Agent 页；AI 复核不等于人已复核" });
  }
  if (artifact) out.push({ key: "confirmAll", level: "normal", label: "确认全部抽取", hint: "原件的复核就是确认抽取；逐单元确认见抽取层" });
  if (judgment || artifact) out.push({ key: "request", level: "normal", label: "请人复核", hint: "加入待决策列表，写一句要看什么" });
  if (artifact) out.push({ key: "outbound", level: "normal", label: "外发设置", hint: "决定定期巡检时原文能不能交给云端的 agent" });
  return out;
}

export function EntryActions({ entry, history, relOut, outbound, reload }: {
  entry: any; history?: any; relOut: any[]; outbound: boolean; reload: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  if (!history) return null;
  const current = history.versions.find((v: any) => v.version === entry.version);
  if (!current) return null;
  const isHead = entry.version === history.head_version;
  const actions = availableActions(entry, current, isHead);
  const def = actions.find((a) => a.key === active) ?? null;
  const close = () => setActive(null);
  const done = () => { close(); reload(); };
  return (
    <section className="entry-actions" aria-label="操作">
      <div className="entry-actions-bar">
        <div className="action-menu">
          <button type="button" className="primary" aria-expanded={menu} onClick={() => setMenu(!menu)}>操作 ▾</button>
          {menu && (
            <ul className="action-menu-list" role="menu">
              {actions.map((a) => (
                <li key={a.key} role="none">
                  <button type="button" role="menuitem" className={a.key === active ? "on" : ""} onClick={() => { setActive(a.key); setMenu(false); }}>
                    <span className="am-label">{a.label}</span>
                    <span className="am-hint muted small-text">{a.hint}</span>
                    <Tag tone={a.level === "impact" ? "warn" : "muted"}>{LEVEL_TEXT[a.level]}</Tag>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <span className="muted small-text">
          {isHead ? "对当前版的处置都是追加记录，原版本保留。" : <>这是历史版本；当前是第 {history.head_version} 版 <IdLink id={history.current_ref}>打开当前版</IdLink>。</>}
        </span>
      </div>
      {def && (
        <div className="action-card">
          <header>
            <strong>{def.label}</strong>
            <Tag tone={def.level === "impact" ? "warn" : "muted"}>{LEVEL_TEXT[def.level]}</Tag>
            <span className="muted small-text grow">{def.hint}</span>
            <button type="button" className="small link" onClick={close} aria-label="关闭">取消</button>
          </header>
          <Form def={def} entry={entry} current={current} relOut={relOut} outbound={outbound} done={done} />
        </div>
      )}
    </section>
  );
}

// 一张表单的骨架：说明框、专有项（children）、摘要、提交；缺什么就写什么
function Card({ summary, missing, label, danger, run, reason, setReason, children, reasonPlaceholder = "说明（必填）：为什么这样处置" }: {
  summary: string; missing: string[]; label: string; danger?: boolean; run: () => Promise<unknown>;
  reason?: string; setReason?: (v: string) => void; children?: ReactNode; reasonPlaceholder?: string;
}) {
  return (
    <div className="action-form">
      {setReason && <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder={reasonPlaceholder} aria-label="说明" />}
      {children}
      <div className="action-foot">
        <span className="muted small-text grow">{summary}</span>
        {missing.length > 0 && <span className="small-text missing">还缺：{missing.join("、")}</span>}
        <Action label={label} className={danger ? "danger" : "primary"} disabled={missing.length > 0} run={run} />
      </div>
    </div>
  );
}

function Form({ def, entry, current, relOut, outbound, done }: { def: Def; entry: any; current: any; relOut: any[]; outbound: boolean; done: () => void }) {
  switch (def.key) {
    case "correct": return <CorrectForm entry={entry} current={current} />;
    case "relations": return <RelationEditor entry={entry} out={relOut} reload={() => undefined} onDone={done} />;
    case "retire": return <RetireForm entry={entry} current={current} done={done} />;
    case "outbound": return <OutboundForm entry={entry} outbound={outbound} done={done} />;
    case "withdraw": case "unwithdraw": case "defect": case "undefect": case "reactivate":
      return <StateForm def={def} current={current} done={done} />;
    default: {
      const mode = REVIEW_KEYS[def.key];
      return mode ? <ReviewBox itemId={entry.id} mode={mode} onDone={done} /> : null;
    }
  }
}

// 撤回、取消撤回、标缺陷、取消缺陷、重新生效：只需要一句说明
function StateForm({ def, current, done }: { def: Def; current: any; done: () => void }) {
  const [reason, setReason] = useState("");
  return (
    <Card reason={reason} setReason={setReason} label={def.label} danger={def.level === "impact"}
      summary={`将追加：${def.label}（${current.ref}）`} missing={reason.trim() ? [] : ["说明"]}
      run={async () => {
        const out = await call<any>("entry.version_state", { id: current.ref, action: def.key, reason });
        if (def.key === "reactivate" && out?.ref) go("entry", out.ref);
        done();
      }} />
  );
}

function RetireForm({ entry, current, done }: { entry: any; current: any; done: () => void }) {
  const [reason, setReason] = useState("");
  const [replacement, setReplacement] = useState("");
  return (
    <Card reason={reason} setReason={setReason} reasonPlaceholder="退役理由（必填）" label="退役本原件" danger
      summary={`将退役 ${entry.id}${replacement ? `，替代原件 ${replacement.slice(-6)}` : "，不指定替代原件"}；退役后仍可打开、引用`}
      missing={reason.trim() ? [] : ["退役理由"]}
      run={async () => {
        await call("entry.version_state", { id: current.ref, action: "retire", reason, replaced_by: replacement || null });
        done();
      }}>
      {replacement ? (
        <div className="row tight">
          <span>替代它的原件：</span><IdLink id={replacement} />
          <button type="button" className="small link" onClick={() => setReplacement("")}>不指定</button>
        </div>
      ) : (
        <details>
          <summary>指定替代它的原件（可选，之后也能指定）</summary>
          <EntryPicker kinds={["artifact"]} exclude={[entry.id]} placeholder="查找替代它的原件" onPick={(ref) => setReplacement(ref.split("#")[0])} />
        </details>
      )}
    </Card>
  );
}

function CorrectForm({ entry, current }: { entry: any; current: any }) {
  const isJudgment = entry.entry_kind === "judgment";
  const isArtifact = entry.entry_kind === "artifact";
  const currentCites = (current.relations_added ?? []).filter((r: any) => r.predicate === "cites").map((r: any) => r.object);
  const [reason, setReason] = useState("");
  const [text, setText] = useState("");
  const [path, setPath] = useState("");
  const [cites, setCites] = useState<string | null>(null);
  const missing = [
    ...(reason.trim() ? [] : ["说明"]),
    ...(Boolean(text.trim()) !== Boolean(path.trim()) ? [] : [isArtifact ? "新版正文或文件路径（二选一）" : "新版正文"]),
  ];
  return (
    <Card reason={reason} setReason={setReason} reasonPlaceholder="更正理由（必填）" label="写新版本" missing={missing}
      summary={`将在 ${entry.id} 下追加第 ${entry.head_version + 1} 版`}
      run={async () => {
        const version = await call<any>("entry.correct", {
          id: entry.id, reason, text: text.trim() ? text : null, path: path.trim() || null,
          cites: cites === null ? null : cites.split(/[,，]/).map((id) => id.trim()).filter(Boolean),
        });
        go("entry", version.id);
      }}>
      <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="新版正文" aria-label="新版正文" />
      {isArtifact && <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="新版文件完整路径（与正文二选一）" />}
      {isJudgment && (
        <>
          <input value={cites ?? currentCites.join("，")} onChange={(e) => setCites(e.target.value)} placeholder="新版依据（逗号分隔；不改就沿用上一版）" />
          <details>
            <summary>从库里选依据</summary>
            <EntryPicker exclude={[entry.id]} onPick={(ref) => setCites([cites ?? currentCites.join("，"), ref].filter(Boolean).join("，"))} />
          </details>
        </>
      )}
    </Card>
  );
}

function OutboundForm({ entry, outbound, done }: { entry: any; outbound: boolean; done: () => void }) {
  const [reason, setReason] = useState("");
  return (
    <Card reason={reason} setReason={setReason} reasonPlaceholder="理由（可空）" label={outbound ? "标为不外发" : "恢复可外发"}
      summary={outbound
        ? "现在可以外发：定期巡检时，它的原文可能交给云端的巡检员、复核员 agent。"
        : "已标为不外发：巡检包里只列编号和规则检查结果，不含原文；平时的 AI 会话不受影响。"}
      missing={[]}
      run={async () => { await call("artifact.policy", { artifact_id: entry.id, outbound: !outbound, reason }); done(); }} />
  );
}
