// 论断（设计稿 16）：判断与要点是同一种论断，只是所在的列不同。两者共用这里的显示：
// - ClaimBody：正文（行内引用 [^n] 悬停看依据、点击跳到依据那一行）、条件、适用范围未明、原作者、对象；
// - CiteGroups：依据按原件分组，同一份原件的多个段落收在一张卡里，每行是"[编号] 段落 · 作用 · 说明"，
//   一眼能看出每个编号引用了哪一段，又不会一份原件占好几张卡（D-12）。
import type { ReactNode } from "react";
import { EntryName } from "./entryLabels";
import { relPhrase, VALIDITY } from "./labels";
import { href } from "./router";
import { Stamp, layerOf } from "./shell/Stamp";
import { RefText, type RelationNote, Tag } from "./ui";

export type ClaimCite = {
  id: string; // 行的锚点 rel-{id}：正文上标点击时跳到这里
  ref: string; // 被引的条目或段落（带版本）
  label?: string; // 对端的名称（"实验结果 results.json · 段落 0"）
  phrase?: string; // 关系的说法（依据、佐证……）
  marker?: string;
  role?: string;
  why?: string;
  text?: string; // 原文片段（要点带）
  validity?: string;
  note?: string;
  extra?: ReactNode;
};

export type Claim = {
  text: string;
  conditions?: string | null;
  scope_unclear?: boolean | null;
  external_author?: string | null;
  objects?: string[];
  reopen_condition?: string | null;
  change_reason?: string | null;
};

// 正文里 [^n] 对应的依据（悬停卡片的内容）
export function notesFromCites(cites: ClaimCite[]): Record<string, RelationNote[]> {
  const out: Record<string, RelationNote[]> = {};
  for (const c of cites) {
    if (!c.marker) continue;
    (out[c.marker] ??= []).push({ id: c.id, other: c.ref, phrase: c.phrase, qualifiers: { why: c.why, role: c.role, marker: c.marker } });
  }
  return out;
}

// needsConditions：结论和要点要写条件，没写时标出来；思路、约束没写就不显示这一行
export function ClaimBody({ claim, notes, quotedLabel = "转述 · 原作者", needsConditions = true }: {
  claim: Claim; notes?: Record<string, RelationNote[]>; quotedLabel?: string; needsConditions?: boolean;
}) {
  return (
    <div className="claim">
      <RefText text={claim.text ?? ""} notes={notes} />
      <dl className="kv claim-kv">
        {(claim.conditions || needsConditions) && (
          <>
            <dt>条件</dt>
            <dd>{claim.conditions || <span className="warn-text">没写条件</span>}</dd>
          </>
        )}
        {claim.scope_unclear && (
          <>
            <dt>适用范围</dt>
            <dd className="muted">未明：上面的条件写了哪些清楚、哪些不清楚，请当作线索，不要过度相信。</dd>
          </>
        )}
        {claim.external_author && (<><dt>{quotedLabel}</dt><dd>{claim.external_author}</dd></>)}
        {(claim.objects?.length ?? 0) > 0 && (<><dt>对象</dt><dd>{claim.objects!.join("、")}</dd></>)}
        {claim.reopen_condition && (<><dt>重开条件</dt><dd>{claim.reopen_condition}</dd></>)}
        {claim.change_reason && (<><dt>本版改动</dt><dd className="muted">{claim.change_reason}</dd></>)}
      </dl>
    </div>
  );
}

const baseOf = (ref: string) => ref.split("#")[0].split("@")[0];
// "实验结果 results.json · 段落 0" → ["实验结果 results.json", "段落 0"]
function splitLabel(label: string | undefined, ref: string): [string | undefined, string] {
  const anchor = ref.includes("#") ? ref.split("#")[1] : "";
  if (!label) return [undefined, anchor];
  const at = label.lastIndexOf(" · ");
  return at > 0 ? [label.slice(0, at), label.slice(at + 3)] : [label, anchor];
}
const markerNum = (c: ClaimCite) => (c.marker ? Number(c.marker) : 1e9);

// 把依据按原件分组：段落引用（art_…#…）按原件归到一组，其余各自一组；组内按编号排
export function groupCites(cites: ClaimCite[]): ClaimCite[][] {
  const groups = new Map<string, ClaimCite[]>();
  for (const c of cites) {
    const key = c.ref.startsWith("art_") && c.ref.includes("#") ? `${baseOf(c.ref)}|${c.phrase ?? ""}` : `${c.ref}|${c.id}`;
    (groups.get(key) ?? groups.set(key, []).get(key)!).push(c);
  }
  return [...groups.values()].map((g) => [...g].sort((a, b) => markerNum(a) - markerNum(b)));
}

export function CiteGroups({ cites, showText = false }: { cites: ClaimCite[]; showText?: boolean }) {
  return (
    <>
      {groupCites(cites).map((g) => (g.length > 1 || showText ? <CiteGroup key={g[0].id} items={g} showText={showText} /> : <CiteCard key={g[0].id} c={g[0]} />))}
    </>
  );
}

// 单条依据：与原来的关系卡一样
function CiteCard({ c }: { c: ClaimCite }) {
  return (
    <a className="chain-card" id={`rel-${c.id}`} href={href("entry", c.ref)} title={c.ref}>
      <span className="chain-card-head">
        <Stamp layer={layerOf(c.ref)} small />
        <span className="clip grow">{c.label ?? <EntryName id={c.ref} />}</span>
        {c.phrase && <span className="tag">{c.phrase}</span>}
        {c.role && <span className="tag role-tag" title="作用">{c.role}</span>}
        {c.marker && <span className="tag" title="对应正文里的引用标记">[{c.marker}]</span>}
      </span>
      {c.why && <span className="rel-why small-text">{c.why}</span>}
      <span className="chain-card-meta">
        <span className="mono muted">{c.ref}</span>
        {c.validity && c.validity !== "current" && <Tag tone="warn">{VALIDITY[c.validity] ?? c.validity}</Tag>}
        {c.note && <span className="muted small-text">{c.note}</span>}
        {c.extra}
      </span>
    </a>
  );
}

// 同一份原件的多段依据：一张卡，标题是原件，下面每行一段
export function CiteGroup({ items, showText = false }: { items: ClaimCite[]; showText?: boolean }) {
  const first = items[0];
  const art = baseOf(first.ref);
  const [title] = splitLabel(first.label, first.ref);
  const markers = [...new Set(items.map((c) => c.marker).filter(Boolean))];
  return (
    <div className="chain-card cite-group">
      <a className="chain-card-head" href={href("entry", art)} title={art}>
        <Stamp layer={layerOf(art)} small />
        <span className="clip grow">{title ?? <EntryName id={art} />}</span>
        {first.phrase && <span className="tag">{first.phrase}</span>}
        <span className="tag" title="引用了这份原件的几个段落">{items.length} 段</span>
        {markers.length > 0 && <span className="tag" title="对应正文里的引用标记">{markers.map((m) => `[${m}]`).join("")}</span>}
      </a>
      <ol className="cite-rows">
        {items.map((c) => {
          const [, seg] = splitLabel(c.label, c.ref);
          return (
            <li key={c.id} id={`rel-${c.id}`}>
              <a href={href("entry", c.ref)} title={c.ref} className="cite-row">
                <span className="cite-marker">{c.marker ? `[${c.marker}]` : "·"}</span>
                <span className="cite-seg">{seg || c.ref.split("#")[1]}</span>
                {c.role && <span className="tag role-tag">{c.role}</span>}
                {c.why && <span className="cite-why small-text">{c.why}</span>}
                {c.validity && c.validity !== "current" && <Tag tone="warn">{VALIDITY[c.validity] ?? c.validity}</Tag>}
              </a>
              {showText && c.text && <blockquote className="small-text cite-text">{c.text}</blockquote>}
            </li>
          );
        })}
      </ol>
      <span className="chain-card-meta">
        <span className="mono muted">{art}</span>
        {first.note && <span className="muted small-text">{first.note}</span>}
      </span>
    </div>
  );
}

// 关系区里的一条关系（entry.get 的 relations.out / in）转成依据行
export function citeOfRelation(x: any, i: number): ClaimCite {
  const q = x.qualifiers ?? {};
  return {
    id: x.id ?? `${x.other}-${i}`, ref: x.other, label: x.other_label, phrase: x.phrase ?? relPhrase(x.predicate, true, x.label),
    marker: q.marker, role: q.role, why: q.why, validity: x.other_validity, note: x.other_note,
  };
}
