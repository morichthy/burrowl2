// 条目选择器：人写依据、加关系时不用手抄 ID。三个来源：最近打开的条目、按文字查找（判断 / 原件 / 事实记录）、
// 直接粘贴 ID（含原件段落 art_…#p3-2）。原件可以展开段落，选到的是段落引用。只读，不改任何数据。
import { useEffect, useMemo, useState } from "react";
import { call } from "./api";
import { EntryName } from "./entryLabels";
import { ENTRY_KIND, JUDGMENT_KIND } from "./labels";
import { loadRecent } from "./shell/recent";
import { Tag } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

export const PICKABLE_PREFIX = /^(art|jdg|rec|evt|rd)_/;
const REF_PATTERN = /^(art|jdg|rec|evt|rd)_[0-9A-HJKMNP-TV-Z]{26}(?:@\d+)?(?:#[\w-]+)?$/i;
export type PickKind = "judgment" | "artifact" | "record" | "event";
const DEFAULT_KINDS: PickKind[] = ["judgment", "artifact", "record"];

type Hit = { id: string; title: string; meta: string };

async function findHits(q: string, kinds: PickKind[]): Promise<Hit[]> {
  const lists = await Promise.all(
    kinds.map((kind) =>
      call<any>("entries.list", { kind, query: q, limit: 6 })
        .then((r) =>
          (r.items as any[]).map((e): Hit => ({
            id: e.id,
            title: e.preview || e.id,
            meta: kind === "judgment" ? (JUDGMENT_KIND[e.kind] ?? "判断") : (ENTRY_KIND[kind] ?? kind),
          })),
        )
        .catch(() => [] as Hit[]),
    ),
  );
  return lists.flat();
}

export function EntryPicker({ onPick, kinds = DEFAULT_KINDS, exclude = [], placeholder = "输入文字查找，或粘贴 ID" }: {
  onPick: (ref: string) => void;
  kinds?: PickKind[];
  exclude?: string[];
  placeholder?: string;
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null); // 展开段落的原件
  const text = q.trim();
  const kindKey = kinds.join(",");
  const skip = useMemo(() => new Set(exclude.map((x) => x.split("#")[0].split("@")[0])), [exclude]);
  const recent = useMemo(() => loadRecent().filter((id) => PICKABLE_PREFIX.test(id) && kinds.some((k) => KIND_PREFIX[k] === id.split("_")[0])), [kindKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (text.length < 1 || REF_PATTERN.test(text)) {
      setHits([]);
      return;
    }
    let alive = true;
    setBusy(true);
    const timer = setTimeout(() => {
      findHits(text, kinds).then((r) => alive && (setHits(r), setBusy(false)));
    }, 250);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [text, kindKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (ref: string) => {
    onPick(ref);
    setQ("");
    setOpen(null);
  };
  const row = (id: string, title?: string, meta?: string) => (
    <li key={id} className="picker-row">
      <span className="clip grow" title={id}>
        {meta && <Tag>{meta}</Tag>} {title ?? <EntryName id={id} />} <span className="mono muted small-text">{id.slice(-6)}</span>
      </span>
      {id.startsWith("art_") && (
        <button type="button" className="small" onClick={() => setOpen(open === id ? null : id)}>
          {open === id ? "收起段落" : "选段落…"}
        </button>
      )}
      <button type="button" className="small" onClick={() => pick(id)}>选用</button>
      {open === id && <Segments artifactId={id} onPick={pick} />}
    </li>
  );
  const pastedRef = REF_PATTERN.test(text) ? text : null;
  const shown = hits.filter((h) => !skip.has(h.id));
  return (
    <div className="picker">
      <input className="grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} aria-label="查找条目" />
      <ul className="picker-list plain">
        {pastedRef && (
          <li className="picker-row">
            <span className="clip grow"><EntryName id={pastedRef} /></span>
            <button type="button" className="small" onClick={() => pick(pastedRef)}>选用</button>
          </li>
        )}
        {!text && recent.filter((id) => !skip.has(id)).length > 0 && <li className="muted small-text">最近打开</li>}
        {!text && recent.filter((id) => !skip.has(id)).map((id) => row(id))}
        {text && !pastedRef && shown.map((h) => row(h.id, h.title, h.meta))}
        {text && !pastedRef && !busy && shown.length === 0 && <li className="muted small-text">没有找到；也可以直接粘贴 ID。</li>}
      </ul>
    </div>
  );
}

const KIND_PREFIX: Record<PickKind, string> = { judgment: "jdg", artifact: "art", record: "rec", event: "evt" };

// 原件的段落：点一段，选到的是 art_…#anchor；可以按文字过滤
function Segments({ artifactId, onPick }: { artifactId: string; onPick: (ref: string) => void }) {
  const [segs, setSegs] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    let alive = true;
    call<any[]>("artifact.segments", { artifact_id: artifactId }).then(
      (r) => alive && setSegs(r),
      (e) => alive && setError(e.message ?? String(e)),
    );
    return () => {
      alive = false;
    };
  }, [artifactId]);
  if (error) return <p className="error small-text">{error}</p>;
  if (!segs) return <p className="muted small-text">读取段落…</p>;
  if (!segs.length) return <p className="muted small-text">这份原件还没有抽取出可引用的段落；可以引用整份原件。</p>;
  const f = filter.trim().toLowerCase();
  const list = segs.filter((s) => !f || String(s.text ?? "").toLowerCase().includes(f)).slice(0, 40);
  return (
    <div className="picker-segs">
      <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="按段落文字过滤" aria-label="过滤段落" />
      <ul className="plain">
        {list.map((s) => (
          <li key={s.anchor} className="picker-row">
            <span className="mono muted small-text">#{s.anchor}</span>
            <span className="clip grow" title={s.text}>{String(s.text ?? "").slice(0, 120)}</span>
            <button type="button" className="small" onClick={() => onPick(`${artifactId}#${s.anchor}`)}>引用此段</button>
          </li>
        ))}
        {list.length === 0 && <li className="muted small-text">没有匹配的段落。</li>}
      </ul>
    </div>
  );
}
