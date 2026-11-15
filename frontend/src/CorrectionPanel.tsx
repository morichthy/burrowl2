// 人工更正面板（设计稿 11 D-18、D-20）：一次更正 = 一个新版本，关键字段与关系一起改，写一次理由。
// 判断：正文、类型、条件、适用范围未明、对象、原作者、重开条件、本地实证、依据与关系（带作用、原因、标记）。
// 原件：新内容（正文或文件路径，可不填）、标题、依据来源与档次、说明字段、对象。
// 过程日志、事实记录、读取记录：只改正文。预填当前值，只提交改动的项，提交前列出"这一版将改动什么"。
import { useMemo, useState } from "react";
import { call } from "./api";
import { EntryPicker } from "./EntryPicker";
import { HUMAN_PREDICATES } from "./RelationEditor";
import { ROLE_HINTS, SOURCE, TIER, relPhrase } from "./labels";
import { PREDICATES, SUBKIND_HINT, SUBKIND_OPTIONS } from "./labels";
import { go } from "./router";
import { Action, IdLink } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Added = { predicate: string; target: string; label: string; condition: string; why: string; role: string; marker: string };

const KIND_OPTIONS: [string, string][] = [["conclusion", "结论"], ["thought", "思路"], ["constraint", "约束"]];
const FIELD_NAME: Record<string, string> = {
  text: "正文", kind: "类型", subkind: "标签", conditions: "条件", scope_unclear: "适用范围未明", objects: "对象",
  external_author: "原作者", reopen_condition: "重开条件", local_observation: "本地实证",
  title: "标题", source_class: "依据来源", external_tier: "来源档次", metadata: "说明字段",
};

const splitList = (s: string) => s.split(/[,，、]/).map((x) => x.trim()).filter(Boolean);
const metaToText = (m: Record<string, any> | undefined) => Object.entries(m ?? {}).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join("\n");
const textToMeta = (s: string) => {
  const out: Record<string, string> = {};
  for (const line of s.split("\n")) {
    const i = line.indexOf(":");
    if (i > 0 && line.slice(0, i).trim()) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
};
const markersIn = (text: string) => [...new Set([...text.matchAll(/\[\^(\d{1,3})\]/g)].map((m) => m[1]))];

export function CorrectionPanel({ entry, out, reload, onDone }: { entry: any; out: any[]; reload: () => void; onDone?: () => void }) {
  const d = entry.data ?? {};
  const kind = entry.entry_kind;
  const isJudgment = kind === "judgment";
  const isArtifact = kind === "artifact";
  const body = isJudgment ? d.text ?? "" : kind === "record" ? d.result ?? "" : kind === "read" ? d.excerpt ?? "" : d.output ?? "";
  const initial = useMemo(() => ({
    text: body as string,
    kind: entry.kind as string,
    subkind: (d.subkind ?? "") as string,
    conditions: (d.conditions ?? "") as string,
    scope: Boolean(d.scope_unclear),
    objects: (entry.objects ?? []).join("，") as string,
    author: (d.external_author ?? "") as string,
    reopen: (d.reopen_condition ?? "") as string,
    local: Boolean(d.local_observation),
    title: (d.title ?? "") as string,
    sourceClass: (entry.source_class ?? "") as string,
    tier: (d.external_tier ?? "") as string,
    meta: metaToText(d.metadata),
  }), [entry.ref]); // eslint-disable-line react-hooks/exhaustive-deps
  const [f, setF] = useState(initial);
  const [path, setPath] = useState("");
  const [removed, setRemoved] = useState<string[]>([]);
  const [added, setAdded] = useState<Added[]>([]);
  const [draft, setDraft] = useState<Added>({ predicate: "cites", target: "", label: "", condition: "", why: "", role: "", marker: "" });
  const [reason, setReason] = useState("");
  const set = (patch: Partial<typeof initial>) => setF({ ...f, ...patch });

  const mine = out.filter((x) => x.id && x.origin !== "framework" && x.origin !== "mechanical");
  const textMarkers = isJudgment ? markersIn(f.text) : [];
  const relMarkers = new Set([
    ...mine.filter((x) => !removed.includes(x.id)).map((x) => x.qualifiers?.marker).filter(Boolean),
    ...added.map((a) => a.marker).filter(Boolean),
  ]);
  const dangling = textMarkers.filter((m) => !relMarkers.has(m));
  const extra = [...relMarkers].filter((m) => !textMarkers.includes(m) && added.some((a) => a.marker === m));

  // 改动摘要：和预填值比较，只列出真正改了的
  const changes: string[] = [];
  const diff = (label: string, a: unknown, b: unknown) => a !== b && changes.push(label);
  diff(FIELD_NAME.text, initial.text, f.text);
  if (isJudgment) {
    diff(FIELD_NAME.title, initial.title, f.title);
    diff(FIELD_NAME.kind, initial.kind, f.kind);
    diff(FIELD_NAME.subkind, initial.subkind, f.subkind);
    diff(FIELD_NAME.conditions, initial.conditions, f.conditions);
    diff(FIELD_NAME.scope_unclear, initial.scope, f.scope);
    diff(FIELD_NAME.external_author, initial.author, f.author);
    diff(FIELD_NAME.reopen_condition, initial.reopen, f.reopen);
    diff(FIELD_NAME.local_observation, initial.local, f.local);
  }
  if (isJudgment || isArtifact) diff(FIELD_NAME.objects, initial.objects, f.objects);
  if (isArtifact) {
    diff(FIELD_NAME.title, initial.title, f.title);
    diff(FIELD_NAME.source_class, initial.sourceClass, f.sourceClass);
    diff(FIELD_NAME.external_tier, initial.tier, f.tier);
    diff(FIELD_NAME.metadata, initial.meta, f.meta);
    if (path.trim()) changes.push("新内容（文件）");
  }
  const summary = [...changes, ...removed.map((id) => `去掉关系 ${id}`), ...added.map((a) => `加${relPhrase(a.predicate, true, a.label)} ${a.target}`)];

  const p = PREDICATES[draft.predicate];
  const needLabel = p?.required.includes("label");
  const needCondition = p?.required.includes("condition");
  const draftReady = Boolean(draft.target) && (!needLabel || draft.label.trim()) && (!needCondition || draft.condition.trim());
  const addDraft = () => {
    setAdded([...added, draft]);
    setDraft({ ...draft, target: "", label: "", condition: "", why: "", role: "", marker: "" });
  };
  const roles = ROLE_HINTS[draft.predicate] ?? [];

  const submit = async () => {
    const payload: Record<string, any> = { id: entry.id, reason };
    if (f.text !== initial.text) payload.text = f.text;
    if (isJudgment) {
      if (f.title !== initial.title) payload.title = f.title;
      if (f.kind !== initial.kind) payload.kind = f.kind;
      if (f.subkind !== initial.subkind || (f.kind !== initial.kind && f.subkind)) payload.subkind = f.subkind;
      if (f.conditions !== initial.conditions) payload.conditions = f.conditions;
      if (f.scope !== initial.scope) payload.scope_unclear = f.scope;
      if (f.author !== initial.author) payload.external_author = f.author;
      if (f.reopen !== initial.reopen) payload.reopen_condition = f.reopen;
      if (f.local !== initial.local) payload.local_observation = f.local;
      if (removed.length) payload.relations_remove = removed;
      if (added.length) {
        payload.relations_add = added.map((a) => ({
          predicate: a.predicate, target: a.target,
          ...(a.label.trim() ? { label: a.label.trim() } : {}), ...(a.condition.trim() ? { condition: a.condition.trim() } : {}),
          ...(a.why.trim() ? { why: a.why.trim() } : {}), ...(a.role.trim() ? { role: a.role.trim() } : {}),
          ...(a.marker.trim() ? { marker: a.marker.trim() } : {}),
        }));
      }
    }
    if (isJudgment || isArtifact) if (f.objects !== initial.objects) payload.objects = splitList(f.objects);
    if (isArtifact) {
      if (path.trim()) payload.path = path.trim();
      if (f.title !== initial.title) payload.title = f.title;
      if (f.sourceClass !== initial.sourceClass) payload.source_class = f.sourceClass;
      if (f.tier !== initial.tier) payload.external_tier = f.tier;
      if (f.meta !== initial.meta) payload.metadata = textToMeta(f.meta);
    }
    const version = await call<any>("entry.correct", payload);
    setRemoved([]);
    setAdded([]);
    setReason("");
    setPath("");
    go("entry", version.ref ?? version.id);
    reload();
    onDone?.();
  };

  return (
    <div className="correction">
      <p className="muted small-text">改动写成这一条的新版本，旧版本保留；没改的字段与关系沿用。</p>
      <label className="field">
        <span className="label">{isJudgment ? "正文（用 [^1] 标出引用）" : isArtifact ? "新版正文（可不填）" : "新版正文"}</span>
        <textarea value={f.text} onChange={(e) => set({ text: e.target.value })} rows={isJudgment ? 5 : 3} />
      </label>
      {isArtifact && (
        <label className="field">
          <span className="label">或：新版文件的完整路径（可不填）</span>
          <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\…\新版文件" />
        </label>
      )}
      {isJudgment && (
        <>
          <label className="field">
            <span className="label">标题（一句话概括，最多 60 字；列表、检索和条目页用它做名字。只改标题不产生新版本）</span>
            <input value={f.title} maxLength={60} onChange={(e) => set({ title: e.target.value })} />
          </label>
          <div className="row tight">
            <label className="field">
              <span className="label">类型</span>
              <select value={f.kind} onChange={(e) => set({ kind: e.target.value, subkind: SUBKIND_OPTIONS[e.target.value]?.[0]?.[0] ?? "" })}>
                {KIND_OPTIONS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </label>
            {SUBKIND_OPTIONS[f.kind] && (
              <label className="field">
                <span className="label">标签</span>
                <select value={f.subkind} onChange={(e) => set({ subkind: e.target.value })} title={SUBKIND_HINT[f.subkind] ?? ""}>
                  {SUBKIND_OPTIONS[f.kind].map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
              </label>
            )}
            <label className="field grow">
              <span className="label">原作者（转述外部材料时）</span>
              <input value={f.author} onChange={(e) => set({ author: e.target.value })} />
            </label>
          </div>
          <label className="field">
            <span className="label">条件（写明哪些使用条件清楚、哪些不清楚）</span>
            <textarea value={f.conditions} onChange={(e) => set({ conditions: e.target.value })} rows={2} />
          </label>
          <label className="check">
            <input type="checkbox" checked={f.scope} onChange={(e) => set({ scope: e.target.checked })} />
            适用范围尚不清晰，请读者当作线索（说明里显示"适用范围未明"）
          </label>
          {f.kind === "thought" && (
            <label className="field">
              <span className="label">重开条件</span>
              <input value={f.reopen} onChange={(e) => set({ reopen: e.target.value })} />
            </label>
          )}
          <label className="check">
            <input type="checkbox" checked={f.local} onChange={(e) => set({ local: e.target.checked })} />
            本地实证（我亲自看到或测到）
          </label>
        </>
      )}
      {isArtifact && (
        <>
          <label className="field">
            <span className="label">标题</span>
            <input value={f.title} onChange={(e) => set({ title: e.target.value })} />
          </label>
          <div className="row tight">
            <label className="field">
              <span className="label">依据来源</span>
              <select value={f.sourceClass} onChange={(e) => set({ sourceClass: e.target.value, tier: e.target.value === "external" ? f.tier : "" })}>
                {Object.entries(SOURCE).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </label>
            {f.sourceClass === "external" && (
              <label className="field">
                <span className="label">来源档次</span>
                <select value={f.tier} onChange={(e) => set({ tier: e.target.value })}>
                  <option value="">未标</option>
                  {Object.entries(TIER).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
              </label>
            )}
          </div>
          <label className="field">
            <span className="label">说明字段（每行 键: 值；按键覆盖，其余沿用）</span>
            <textarea value={f.meta} onChange={(e) => set({ meta: e.target.value })} rows={3} />
          </label>
        </>
      )}
      {(isJudgment || isArtifact) && (
        <label className="field">
          <span className="label">对象（逗号分隔）</span>
          <input value={f.objects} onChange={(e) => set({ objects: e.target.value })} />
        </label>
      )}
      {isJudgment && (
        <fieldset className="correction-relations">
          <legend>依据与关系（本条指向）</legend>
          {mine.length === 0 && <p className="muted small-text">还没有。</p>}
          <ul className="plain rel-edit-list">
            {mine.map((x) => (
              <li key={x.id} className={removed.includes(x.id) ? "removed" : ""}>
                <span className="tag">{x.phrase ?? relPhrase(x.predicate, true, x.label)}</span> <IdLink id={x.other} />
                {x.qualifiers?.role && <span className="tag role-tag">{x.qualifiers.role}</span>}
                {x.qualifiers?.marker && <span className="tag">[{x.qualifiers.marker}]</span>}
                {x.qualifiers?.why && <span className="muted small-text"> {x.qualifiers.why}</span>}
                <button type="button" className="small link" onClick={() => setRemoved(removed.includes(x.id) ? removed.filter((i) => i !== x.id) : [...removed, x.id])}>
                  {removed.includes(x.id) ? "不去掉" : "去掉"}
                </button>
              </li>
            ))}
            {added.map((a, i) => (
              <li key={`a${i}`} className="added">
                + <span className="tag">{relPhrase(a.predicate, true, a.label)}</span> <IdLink id={a.target} />
                {a.role && <span className="tag role-tag">{a.role}</span>}
                {a.marker && <span className="tag">[{a.marker}]</span>}
                {a.why && <span className="muted small-text"> {a.why}</span>}
                <button type="button" className="small link" onClick={() => setAdded(added.filter((_x, j) => j !== i))}>取消</button>
              </li>
            ))}
          </ul>
          <div className="row tight">
            <select aria-label="关系" value={draft.predicate} onChange={(e) => setDraft({ ...draft, predicate: e.target.value })}>
              {HUMAN_PREDICATES.map((name) => <option key={name} value={name}>{PREDICATES[name]?.label ?? name}</option>)}
            </select>
            {needLabel && <input aria-label="标签" placeholder="标签（如：导致）" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />}
            {needCondition && <input aria-label="条件" placeholder="条件" value={draft.condition} onChange={(e) => setDraft({ ...draft, condition: e.target.value })} />}
          </div>
          {draft.target
            ? <p className="small-text">对象：<IdLink id={draft.target} /> <button type="button" className="small link" onClick={() => setDraft({ ...draft, target: "" })}>换一个</button></p>
            : <EntryPicker exclude={[entry.id]} placeholder="查找要连接的条目或原件段落" onPick={(ref: string) => setDraft({ ...draft, target: ref })} />}
          <div className="row tight">
            <input aria-label="作用" list="role-hints" placeholder="作用（可选，如：定义）" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })} />
            <datalist id="role-hints">{roles.map((r) => <option key={r} value={r} />)}</datalist>
            <input aria-label="原因" className="grow" placeholder="原因（可选：这一段对应判断里的哪一点）" value={draft.why} onChange={(e) => setDraft({ ...draft, why: e.target.value })} />
            <input aria-label="标记" className="narrow" placeholder="[^n] 编号" value={draft.marker} onChange={(e) => setDraft({ ...draft, marker: e.target.value })} />
            <button type="button" disabled={!draftReady} onClick={addDraft}>加入</button>
          </div>
          {dangling.length > 0 && (
            <p className="warn small-text">正文里的 {dangling.map((m) => `[^${m}]`).join("、")} 还没有对应的关系：请在上面加一条关系并写上同样的标记编号，或删去这个标记。</p>
          )}
          {extra.length > 0 && (
            <p className="warn small-text">关系带了标记 {extra.map((m) => `[^${m}]`).join("、")}，但正文里没有：请在正文相应的句子后面写上。</p>
          )}
        </fieldset>
      )}
      <label className="field">
        <span className="label">理由（必填）</span>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
      </label>
      <p className="small-text" aria-live="polite">
        {summary.length ? <>这一版将改动：{summary.join("；")}</> : <span className="muted">还没有改动。</span>}
      </p>
      <Action label="写新版本" disabled={!reason.trim() || summary.length === 0 || dangling.length > 0} run={submit} />
    </div>
  );
}
