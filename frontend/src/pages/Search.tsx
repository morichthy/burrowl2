// 检索：模式切换（复用 / 探索）、排序（相关度 / 地位）、按列看结果；筛选在服务端进行，与条目页、关系图同名同序
// （综合程度 → 依据来源 → 类型 → 现状 → 说明，设计稿 10 D-24、D-26）。
// 名次只表示相关度（设计稿 06 D-09）；每条显示坐标与一行说明、命中的段落、命中的旧版（设计稿 10 D-19）与关系概况。
// 检索词和筛选都写在网址里（#/search?q=…&mode=explore），刷新、后退、收藏都能回到这次检索。
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { call } from "../api";
import { EntryName } from "../entryLabels";
import { JUDGMENT_KIND, KIND_FILTER, LAYER, SOURCE, relPhrase } from "../labels";
import { href, list, unlist, useUrlState } from "../router";
import { Icon } from "../shell/icons";
import { setCursor } from "../shell/shortcuts";
import { Stamp } from "../shell/Stamp";
import { Coordinates, Empty, ErrorBox, IdLink, Loading, useLoad } from "../ui";
import { FidelityTag } from "./Artifact";
import { EntryPreview, useCursorPreview } from "./EntryPreview";
import { RowActions } from "./Entries";

/* eslint-disable @typescript-eslint/no-explicit-any */

const SEARCH_FILTERS = { q: "", objects: "", mode: "reuse", order: "relevance", layer: "", source: "", kinds: "", sup: "1", log: "", retired: "", thought: "", quoted: "" };
const LAYER_KEYS = Object.keys(LAYER);

// 把检索词在文字里标出来（只是显示，不影响排序）
function Marked({ text, words }: { text: string; words: string[] }): ReactNode {
  if (!words.length || !text) return text;
  const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(re).map((part, i) => (i % 2 === 1 ? <mark key={i}>{part}</mark> : <Fragment key={i}>{part}</Fragment>));
}

export function Search() {
  const [f, setF] = useUrlState(SEARCH_FILTERS);
  const [draft, setDraft] = useState(f.q);
  const [objDraft, setObjDraft] = useState(f.objects);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => setDraft(f.q), [f.q]);
  useEffect(() => input.current?.focus(), []);
  const mode = f.mode === "explore" ? "explore" : "reuse";
  // 过程内容：复用模式默认显示、探索模式默认隐藏（D-15）；手动改过就以网址里的为准
  const includeThought = f.thought ? f.thought === "1" : mode !== "explore";
  const [result, error] = useLoad(
    () =>
      f.q.trim()
        ? call<any>("search", {
            query: f.q,
            mode,
            order: f.order === "standing" || f.order === "status" ? "standing" : "relevance",
            objects: splitList(f.objects),
            layers: null,
            source: f.source || "all",
            kinds: list(f.kinds).length ? list(f.kinds) : null,
            quoted: f.quoted === "1" ? true : null,
            include_log: f.log === "1",
            include_retired: f.retired === "1",
            include_thought: includeThought,
            limit: 60,
          })
        : Promise.resolve(null),
    [f.q, f.objects, mode, f.order, f.log, f.retired, includeThought, f.source, f.kinds, f.quoted],
  );
  const loading = !!f.q.trim() && !result && !error;
  const [preview, setPreview] = useState<string | null>(null);
  useCursorPreview(useCallback((id: string) => setPreview((p) => (p ? id : p)), []));

  const kinds = list(f.kinds);
  const all: any[] = result?.hits ?? [];
  const validity = (h: any) => h.state?.validity ?? "current";
  // 依据来源、类型、说明在服务端筛选；是否显示被替代的、看哪一列在前端切换，不改变后端的排序与地位规则
  const filtered = useMemo(() => (f.sup === "1" ? all : all.filter((h) => validity(h) === "current")), [all, f.sup]);
  const hits = f.layer ? filtered.filter((h) => h.layer === f.layer) : filtered;
  const lead = hits.filter((h) => validity(h) === "current");
  const tail = hits.filter((h) => validity(h) !== "current");
  const [showTail, setShowTail] = useState(false);
  const words = f.q.trim().split(/\s+/).filter((w) => w.length > 0);
  const layerCount = (k: string) => filtered.filter((h) => h.layer === k).length;
  const toggleIn = (key: "kinds", v: string) => {
    const cur = list(f[key]);
    setF({ [key]: unlist(cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]) } as Partial<typeof SEARCH_FILTERS>);
  };
  const submit = () => setF({ q: draft.trim(), objects: objDraft.trim() });

  return (
    <div className="search-page">
      <form className="search-hero" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label className="search-box">
          <Icon name="search" />
          <input ref={input} type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="检索词，或设备编号、错误码" aria-label="检索内容" />
          <kbd>Enter</kbd>
        </label>
        <div className="segctl" role="radiogroup" aria-label="检索方式">
          <button type="button" role="radio" aria-checked={mode === "reuse"} className={mode === "reuse" ? "on" : ""} onClick={() => setF({ mode: "reuse", thought: "" })}>复用已有结论</button>
          <button type="button" role="radio" aria-checked={mode === "explore"} className={mode === "explore" ? "on" : ""} onClick={() => setF({ mode: "explore", thought: "", layer: f.layer === "framework" ? "" : f.layer })}>探索新路线</button>
        </div>
        <div className="segctl" role="radiogroup" aria-label="排序">
          <button type="button" role="radio" aria-checked={f.order === "relevance"} className={f.order === "relevance" ? "on" : ""} onClick={() => setF({ order: "relevance" })} title="按相关度排序；可靠与否看每条的坐标与说明">相关</button>
          <button type="button" role="radio" aria-checked={f.order !== "relevance"} className={f.order !== "relevance" ? "on" : ""} onClick={() => setF({ order: "standing" })} title="按依据来源 → 综合程度 → 复核逐级排序，不打分">地位</button>
        </div>
      </form>

      {result && (
        <div className="search-tabs">
          <div className="segctl" role="tablist" aria-label="按列看结果">
            <button type="button" role="tab" aria-selected={!f.layer} className={!f.layer ? "on" : ""} onClick={() => setF({ layer: "" })}>全部 <span className="count">{filtered.length}</span></button>
            {LAYER_KEYS.map((k) => (
              <button key={k} type="button" role="tab" aria-selected={f.layer === k} className={f.layer === k ? "on" : ""} disabled={mode === "explore" && k === "framework"} title={mode === "explore" && k === "framework" ? "探索模式不返回框架页" : undefined} onClick={() => setF({ layer: k })}>
                <Stamp layer={k} small />{LAYER[k]} <span className="count">{layerCount(k)}</span>
              </button>
            ))}
          </div>
          <span className="muted small-text">共命中 {result.total} · 不是当前有效的排在最后{f.retired !== "1" && " · 已撤回、已退役的不返回"}</span>
        </div>
      )}

      <div className={`entries-grid${preview ? " with-preview" : ""}`}>
        <aside className="filter-side panel" aria-label="筛选">
          <label className="field">
            <span>限定对象</span>
            <input value={objDraft} onChange={(e) => setObjDraft(e.target.value)} onBlur={submit} onKeyDown={(e) => e.key === "Enter" && submit()} placeholder="逗号分隔，可选" />
          </label>
          <div className="filter-group" role="radiogroup" aria-label="依据来源">
            <p className="filter-label">依据来源</p>
            {[["", "全部"], ...Object.entries(SOURCE)].map(([key, text]) => (
              <label key={key} className="check fcheck" title={key === "local" ? "依据全部为本地实证的原件与判断，以及规定" : undefined}>
                <input type="radio" name="search-source" checked={(f.source || "") === key} onChange={() => setF({ source: key })} />
                <span className="grow">{key === "local" ? "只要本地实证" : key ? `依据含${text}` : text}</span>
              </label>
            ))}
          </div>
          <CheckGroup label="类型" options={Object.entries(KIND_FILTER)} value={kinds} onToggle={(v) => toggleIn("kinds", v)} />
          {kinds.length > 0 && <p className="muted small-text">已选判断类型：只显示判断，原件与框架不显示。</p>}
          <div className="filter-group">
            <p className="filter-label">现状</p>
            <label className="check"><input type="checkbox" checked={f.sup === "1"} onChange={(e) => setF({ sup: e.target.checked ? "1" : "0" })} />含被替代的（排在最后）</label>
            <label className="check" title="当前版已撤回、已退役、依据全部失效的条目默认不返回；勾选后排在最后"><input type="checkbox" checked={f.retired === "1"} onChange={(e) => setF({ retired: e.target.checked ? "1" : "" })} />含已撤回、已退役的</label>
            <label className="check" title="提问、尝试、停下的路线、假设、联想、目的。探索模式默认隐藏，以免被已有思路带偏"><input type="checkbox" checked={includeThought} onChange={(e) => setF({ thought: e.target.checked ? "1" : "0" })} />含思路</label>
            <label className="check"><input type="checkbox" checked={f.log === "1"} onChange={(e) => setF({ log: e.target.checked ? "1" : "" })} />含过程日志</label>
          </div>
          <div className="filter-group">
            <p className="filter-label">说明</p>
            <label className="check" title="转述外部材料（有原作者）的结论"><input type="checkbox" checked={f.quoted === "1"} onChange={(e) => setF({ quoted: e.target.checked ? "1" : "" })} />只看转述的</label>
          </div>
          <div className="mode-note">
            <p className="filter-label">现在是：{mode === "explore" ? "探索新路线" : "复用已有结论"}</p>
            <p className="muted small-text">
              {mode === "explore"
                ? "不返回框架页，默认不含过程内容，免得被已有的综合和停下的路线带着走。"
                : "三列都返回，结果带地位。要走新路线时切到\"探索新路线\"。"}
            </p>
          </div>
          <p className="muted small-text">检索词和筛选都在网址里，可以直接收藏这次检索。</p>
        </aside>

        <section className="hits" aria-label="结果">
          <ErrorBox error={error} />
          {!f.q.trim() && <Empty icon="search">输入检索词后按 Enter。也可以在任何页面按 Ctrl+K 按名称或 ID 直接跳转。</Empty>}
          {loading && <Loading rows={4} />}
          {result && result.constraints.length > 0 && (
            <div className="constraints">
              <h3>相关的有效约束、决定和指令</h3>
              {result.constraints.map((c: any) => (
                <div key={c.id}>
                  <IdLink id={c.id} /> 【{JUDGMENT_KIND[c.kind]}】{c.text}
                </div>
              ))}
            </div>
          )}
          {result && (result.hints ?? []).filter((t: string) => !t.startsWith("名次只表示")).length > 0 && (
            <ul className="muted hints">
              {result.hints.filter((t: string) => !t.startsWith("名次只表示")).map((t: string) => <li key={t}>{t}</li>)}
            </ul>
          )}
          {result && hits.length === 0 && <Empty icon="filter">没有符合筛选条件的结果。可以放宽左边的筛选，或换成"探索新路线"。</Empty>}
          {lead.map((h, i) => <Hit key={h.id + (h.anchor ?? "")} h={h} rank={i + 1} words={words} picked={preview === h.id} onPick={() => setPreview(h.id)} />)}
          {tail.length > 0 && (
            <>
              <button type="button" className="tail-toggle" aria-expanded={showTail} onClick={() => setShowTail(!showTail)}>
                <Icon name="chevron" size={14} />
                <span className="grow">不是当前有效的 {tail.length} 条排在最后{showTail ? "" : "，点开查看"}</span>
                <span className="tag warn">被替代</span>
              </button>
              {showTail && tail.map((h, i) => <Hit key={h.id + (h.anchor ?? "")} h={h} rank={lead.length + i + 1} words={words} picked={preview === h.id} onPick={() => setPreview(h.id)} />)}
            </>
          )}
          {result && hits.length > 0 && (
            <p className="results-foot plain-foot">
              <span><kbd>j</kbd> <kbd>k</kbd> 移动</span><span><kbd>Space</kbd> 预览</span><span><kbd>Enter</kbd> 打开</span><span><kbd>r</kbd> 阅读</span><span><kbd>v</kbd> 关系图</span>
            </p>
          )}
        </section>
        {preview && <EntryPreview key={preview} id={preview} onClose={() => setPreview(null)} />}
      </div>
    </div>
  );
}

function Hit({ h, rank, words, picked, onPick }: { h: any; rank: number; words: string[]; picked: boolean; onPick: () => void }) {
  const cite = h.cite_as ?? (h.anchor ? `${h.id}#${h.anchor}` : h.id);
  return (
    <article
      className={`hit-card${(h.state?.validity ?? "current") !== "current" ? " dim" : ""}${picked ? " picked" : ""}`}
      data-nav-item={h.id}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a, button")) return;
        setCursor(e.currentTarget, false);
        onPick();
      }}
    >
      <span className="rank num">{rank}</span>
      <Stamp layer={h.layer} />
      <div className="hit-main">
        <div className="hit-head">
          <a href={href("entry", cite)} data-key="open" className="hit-title" title={cite}><EntryName id={cite} /></a>
          {h.unit_label && h.unit !== "doc" && <span className="tag">{h.unit_label}</span>}
          <FidelityTag fidelity={h.fidelity && h.fidelity !== "copy" ? h.fidelity : null} />
          {h.verified && <span className="tag good">已确认</span>}
        </div>
        {(h.passages?.length ? h.passages : [{ text: h.text }]).map((p: any, i: number) => (
          <p key={i} className="hit-text">
            {p.context && <span className="muted small-text">{p.context} · </span>}
            {p.cite_as && i > 0 && <><IdLink id={p.cite_as} />{" "}</>}
            <Marked text={p.text ?? ""} words={words} />
          </p>
        ))}
        {(h.old_hits ?? []).map((o: any) => (
          <p key={o.ref} className="hit-text old-hit">
            <span className="tag warn">旧版命中</span> <IdLink id={o.ref}>第 {o.ref.split("@")[1]} 版</IdLink>
            {o.change_reason && <span className="muted small-text"> · 下一版的改动理由：{o.change_reason}</span>}
            <br />
            <Marked text={o.snippet ?? ""} words={words} />
          </p>
        ))}
        <div className="hit-meta">
          <Coordinates c={h} />
          {h.more_matches > 0 && <span className="muted small-text">同一条目还有 {h.more_matches} 处命中未展示</span>}
          <LinkSummary links={h.links} />
        </div>
      </div>
      <RowActions id={h.id} onPreview={onPick} />
    </article>
  );
}

// 关系概况（设计稿 10 D-21）：出边、入边按谓词计数，悬停看引用
function LinkSummary({ links }: { links?: any }) {
  if (!links) return null;
  const count = (items: any[], outgoing: boolean) => {
    const by: Record<string, { n: number; refs: string[] }> = {};
    for (const x of items ?? []) {
      const key = relPhrase(x.p, outgoing, x.label);
      (by[key] ??= { n: 0, refs: [] }).n += 1;
      by[key].refs.push(x.ref);
    }
    return Object.entries(by);
  };
  const out = count(links.out, true);
  const inc = count(links.in, false);
  if (!out.length && !inc.length) return null;
  return (
    <span className="link-summary muted small-text">
      {[...out, ...inc].map(([phrase, v]) => (
        <span key={phrase} className="tag muted" title={v.refs.slice(0, 20).join("\n")}>{phrase} {v.n}</span>
      ))}
      {links.truncated && <span title={links.more}>（已截断）</span>}
    </span>
  );
}

// 竖排的多选筛选（带数量）
function CheckGroup({ label, options, value, onToggle, counts }: { label: string; options: [string, string][]; value: string[]; onToggle: (v: string) => void; counts?: Record<string, number> }) {
  return (
    <div className="filter-group" role="group" aria-label={label}>
      <p className="filter-label">{label}</p>
      {options.map(([key, text]) => (
        <label key={key} className="check fcheck">
          <input type="checkbox" checked={value.includes(key)} onChange={() => onToggle(key)} />
          <span className="grow">{text}</span>
          {counts && <span className="muted mono">{counts[key] ?? 0}</span>}
        </label>
      ))}
    </div>
  );
}

export function splitList(s: string): string[] | null {
  const items = s
    .split(/[,，]/)
    .map((x) => x.trim())
    .filter(Boolean);
  return items.length ? items : null;
}
