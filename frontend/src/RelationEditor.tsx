// 人改关系（设计稿 10 D-29）：关系写在判断的出边上，改关系 = 判断的新版本（正文不变，旧版本的关系保留）。
// 可以：移除当前版的出边（含依据）、加关系（依据、佐证、反驳、回答、针对、条件并存、自由关系、替代）、
// 让别的判断指向本条（那条判断出新版本）。加关系时用条目选择器，不用手抄 ID。
import { useState } from "react";
import { call } from "./api";
import { EntryPicker } from "./EntryPicker";
import { PREDICATES, relPhrase } from "./labels";
import { go } from "./router";
import { Action, IdLink, Tag } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Dir = "out" | "in";
type Staged = { dir: Dir; predicate: string; target: string; label: string; condition: string };

// 人能写、并写在判断上的谓词（顺序按词表）
export const HUMAN_PREDICATES = Object.entries(PREDICATES)
  .filter(([, p]) => p.origin === "judgment" && p.writers.includes("human"))
  .map(([name]) => name);

const FIELD_HINT: Record<string, string> = {
  cites: "本条凭这条依据成立",
  supports: "本条佐证它（只在证据与结论之间）",
  opposes: "本条反驳它",
  answers: "本条回答它",
  targets: "本条针对它",
  coexists_under: "两条在某个条件下并存",
  relates: "自定义关系，系统不赋予含义",
  supersedes: "本条替代它（只有人能写）",
};

export function RelationEditor({ entry, out, reload }: { entry: any; out: any[]; reload: () => void }) {
  const [removed, setRemoved] = useState<string[]>([]);
  const [staged, setStaged] = useState<Staged[]>([]);
  const [reason, setReason] = useState("");
  const [draft, setDraft] = useState<Staged>({ dir: "out", predicate: "supports", target: "", label: "", condition: "" });
  if (entry.entry_kind !== "judgment") return null;
  if (entry.version !== entry.head_version) {
    return <p className="muted small-text">这是历史版本；改关系请回到当前版。</p>;
  }
  const mine = out.filter((x) => x.id && x.origin !== "framework" && x.origin !== "mechanical");
  const p = PREDICATES[draft.predicate];
  const needLabel = p?.required.includes("label");
  const needCondition = p?.required.includes("condition");
  const ready = Boolean(draft.target) && (!needLabel || draft.label.trim()) && (!needCondition || draft.condition.trim());
  const dirty = removed.length > 0 || staged.length > 0;
  const toggle = (id: string) => setRemoved((r) => (r.includes(id) ? r.filter((x) => x !== id) : [...r, id]));
  const spec = (s: Staged) => ({
    predicate: s.predicate, target: s.dir === "out" ? s.target : entry.id,
    ...(s.label.trim() ? { label: s.label.trim() } : {}), ...(s.condition.trim() ? { condition: s.condition.trim() } : {}),
  });
  const apply = async () => {
    const ownAdd = staged.filter((s) => s.dir === "out").map(spec);
    let latest: string | null = null;
    if (ownAdd.length || removed.length) {
      const v = await call<any>("entry.relate", { id: entry.id, reason, add: ownAdd, remove: removed });
      latest = v.ref;
    }
    // 让别的判断指向本条：每条来源判断各出一个新版本
    const bySource = new Map<string, Staged[]>();
    for (const s of staged.filter((x) => x.dir === "in")) bySource.set(s.target.split("#")[0].split("@")[0], [...(bySource.get(s.target.split("#")[0].split("@")[0]) ?? []), s]);
    for (const [source, list] of bySource) {
      await call("entry.relate", { id: source, reason, add: list.map((s) => ({ ...spec(s), target: entry.id })) });
    }
    setRemoved([]);
    setStaged([]);
    setReason("");
    if (latest) go("entry", latest);
    reload();
  };
  return (
    <section className="amend relation-editor">
      <h3>关系与依据</h3>
      <p className="muted small-text">
        关系写在判断上，改关系会写成这条判断的新版本（正文不变，旧版本的关系保留）。要让别的判断指向本条，选"指向本条"，那条判断会出新版本。
      </p>
      {mine.length > 0 && (
        <ul className="plain rel-edit-list">
          {mine.map((x) => (
            <li key={x.id} className={removed.includes(x.id) ? "removed" : ""}>
              <Tag>{x.phrase ?? relPhrase(x.predicate, true, x.label)}</Tag> <IdLink id={x.other} />
              {x.qualifiers?.condition && <span className="muted small-text"> · 条件：{x.qualifiers.condition}</span>}
              <button type="button" className="small link" onClick={() => toggle(x.id)}>{removed.includes(x.id) ? "不移除" : "移除"}</button>
            </li>
          ))}
        </ul>
      )}
      {mine.length === 0 && <p className="muted small-text">本条还没有出边。</p>}
      {staged.length > 0 && (
        <ul className="plain rel-edit-list staged">
          {staged.map((s, i) => (
            <li key={`${s.dir}${s.predicate}${s.target}${i}`}>
              <Tag tone="accent">新增</Tag> {s.dir === "out" ? "本条" : <IdLink id={s.target} />}{" "}
              <Tag>{relPhrase(s.predicate, true, s.label)}</Tag> {s.dir === "out" ? <IdLink id={s.target} /> : "本条"}
              {s.condition && <span className="muted small-text"> · 条件：{s.condition}</span>}
              <button type="button" className="small link" onClick={() => setStaged(staged.filter((_, j) => j !== i))}>撤销</button>
            </li>
          ))}
        </ul>
      )}
      <details className="amend-form">
        <summary>加一条关系</summary>
        <div className="row tight">
          <select value={draft.dir} onChange={(e) => setDraft({ ...draft, dir: e.target.value as Dir, target: "" })} aria-label="方向">
            <option value="out">本条 → 对方</option>
            <option value="in">对方 → 本条</option>
          </select>
          <select value={draft.predicate} onChange={(e) => setDraft({ ...draft, predicate: e.target.value })} aria-label="关系">
            {HUMAN_PREDICATES.map((name) => (
              <option key={name} value={name}>{PREDICATES[name].label}</option>
            ))}
          </select>
          <span className="muted small-text">{FIELD_HINT[draft.predicate]}{draft.dir === "in" && "（主语是对方那条判断）"}</span>
        </div>
        {needLabel && <input value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} placeholder="关系的名称（如：导致、是……的一种）" />}
        {needCondition && <input value={draft.condition} onChange={(e) => setDraft({ ...draft, condition: e.target.value })} placeholder="并存的条件" />}
        {draft.target ? (
          <div className="row tight">
            <span>对方：</span><IdLink id={draft.target} />
            <button type="button" className="small link" onClick={() => setDraft({ ...draft, target: "" })}>换一个</button>
          </div>
        ) : (
          <EntryPicker
            kinds={draft.dir === "in" ? ["judgment"] : ["judgment", "artifact", "record", "event"]}
            exclude={[entry.id]}
            placeholder={draft.dir === "in" ? "查找要指向本条的判断" : "查找对方：判断、原件（可选段落）、事实记录"}
            onPick={(ref) => setDraft({ ...draft, target: ref })}
          />
        )}
        <button type="button" disabled={!ready} onClick={() => {
          setStaged([...staged, draft]);
          setDraft({ ...draft, target: "", label: "", condition: "" });
        }}>加入待提交</button>
      </details>
      {dirty && (
        <div className="row tight">
          <input className="grow" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="理由（必填）：为什么改这些关系" />
          <Action label={`提交（${removed.length} 移除，${staged.length} 新增）`} disabled={!reason.trim()} run={apply} />
        </div>
      )}
    </section>
  );
}
