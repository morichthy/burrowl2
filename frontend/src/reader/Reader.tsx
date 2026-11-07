// 阅读模式外壳（设计稿 03 D-01、D-02、D-05、D-06、D-07）：全屏，只有阅读器本身。
// 外壳负责工具栏、侧栏（段落、引用、目录）、对照与文字视图、锚点跳转；原件怎么显示交给可更换的阅读器（registry.ts）。
// 判断与框架页条目打开宽版排版：正文居中，右侧是它的引用。
import { useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import { blobUrl, call, fetchArtifactBytes, fileUrl, pageUrl } from "../api";
import { FORMAT, JUDGMENT_KIND } from "../labels";
import { UnitSection, type Ctx } from "../pages/Artifact";
import { SegmentDetails, type BlockRef } from "../pages/Faithful";
import { href } from "../router";
import { ErrorBox, IdLink, RefText, Time, useLoad } from "../ui";
import type { Mark, OutlineItem, ViewerHandle, ViewerProps, ViewerSource } from "./contract";
import { buildMarks } from "./marks";
import { exitReader, openReader, toggleFullscreen } from "./open";
import { usePrefs, type ReaderView, type SideTab } from "./prefs";
import { pickViewer, viewersFor } from "./registry";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Reader({ target }: { target: string }) {
  const [id, anchor = ""] = target.split("#");
  useEffect(() => {
    document.body.classList.add("reading");
    return () => document.body.classList.remove("reading");
  }, []);
  if (!id) return <div className="reader">没有指定要阅读的条目</div>;
  return id.startsWith("art_") ? <ArtifactReader key={id} id={id} anchor={anchor} /> : <EntryReader key={id} id={id} />;
}

// ---------- 原件 ----------
const VIEW_LABEL: Record<ReaderView, string> = { original: "原样", compare: "对照", text: "文字" };

function ArtifactReader({ id, anchor }: { id: string; anchor: string }) {
  const [entry, eError] = useLoad(() => call<any>("entry.get", { id }), [id]);
  const [layer, lError, reloadLayer] = useLoad(() => call<any>("artifact.layer", { artifact_id: id }), [id]);
  const [segs, , reloadSegs] = useLoad(() => call<any[]>("artifact.segments", { artifact_id: id }).catch(() => []), [id]);
  const [stats, , reloadStats] = useLoad(() => call<any>("artifact.segment_stats", { artifact_id: id }), [id]);
  const [settings] = useLoad(() => call<any>("settings.get").catch(() => null), []);
  const [prefs, setPrefs] = usePrefs();
  const [chosen, setChosen] = useState<string>(""); // 本次临时换的阅读器
  const [failed, setFailed] = useState<string | null>(null);
  const [Comp, setComp] = useState<ComponentType<ViewerProps> | null>(null);
  const [handle, setHandle] = useState<ViewerHandle | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [location, setLocation] = useState("");
  const [outline, setOutline] = useState<OutlineItem[]>([]);
  const [zoomPct, setZoomPct] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const reload = () => {
    reloadLayer();
    reloadSegs();
    reloadStats();
  };

  const source = useMemo<ViewerSource | null>(() => {
    if (!layer || !entry) return null;
    const d = entry.entry?.data ?? {};
    return {
      id,
      title: d.title ?? id,
      format: layer.format,
      mediaType: layer.media_type ?? "",
      suffix: (d.suffix ?? (d.filename ? `.${String(d.filename).split(".").pop()}` : "")).toLowerCase(),
      bytes: () => fetchArtifactBytes(id),
      snapshotBytes: layer.snapshot ? () => fetchArtifactBytes(id, "snapshot/bytes") : undefined,
      fileUrl: fileUrl(id),
      pageUrl: (p, o = {}) => pageUrl(id, p, o.scale, o.source, o.clip),
      blobUrl: (sha, mime) => blobUrl(id, sha, mime),
      assetBase: new URL("./pdfjs/", document.baseURI).href,
      units: layer.units,
      text: layer.format === "text" ? (layer.units[0]?.text ?? "") : undefined,
    };
    // layer 重新加载（确认、重新抽取）时不重建来源，阅读器不必重新打开文档
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, !!layer, !!entry, !!layer?.snapshot]);

  const marks = useMemo(() => (layer && segs ? buildMarks(layer, segs, stats?.segments ?? {}, anchor) : []), [layer, segs, stats, anchor]);
  const info = { snapshot: !!layer?.snapshot };
  const picked = source ? pickViewer(source, info, [chosen, settings?.values?.[`viewer.${source.format}`]]) : { def: null, note: "" };
  const def = picked.def;

  useEffect(() => {
    setComp(null);
    setHandle(null);
    setFailed(null);
    setOutline([]);
    if (!def) return;
    let cancelled = false;
    def.load().then(
      (m) => !cancelled && setComp(() => m.default),
      (e) => !cancelled && setFailed(String(e?.message ?? e)),
    );
    return () => {
      cancelled = true;
    };
  }, [def?.id]);

  const extracted = !!layer?.extracted && layer.format !== "text";
  const views: ReaderView[] = extracted ? ["original", "compare", "text"] : ["original"];
  const view: ReaderView = failed && extracted ? "text" : views.includes(prefs.view) ? prefs.view : "original";
  const ctx: Ctx | null = layer
    ? { id, layer, stats: stats?.segments ?? {}, byBlock: byBlockOf(segs ?? []), anchor, onlyMarked: false, reload }
    : null;
  const selectedMark = marks.find((m) => m.key === selected) ?? null;
  const caps = def?.capabilities ?? [];
  const headings = useMemo(() => headingOutline(layer, marks), [layer, marks]);
  const toc = outline.length ? outline : headings.map((h) => ({ ...h, go: () => handle?.scrollTo(h.key) }));

  // 对照视图：左边翻到哪个单元，右边跟着滚到那个单元
  const pane = useRef<HTMLDivElement>(null);
  const paneHovered = useRef(false);
  useEffect(() => {
    if (view !== "compare" || !location || paneHovered.current) return;
    const el = pane.current?.querySelector<HTMLElement>(`[data-unit="${CSS.escape(location)}"]`);
    if (el && pane.current) pane.current.scrollTop = el.offsetTop - 8;
  }, [location, view]);

  if (eError || lError) return <div className="reader"><ErrorBox error={eError ?? lError} /></div>;
  if (!layer || !entry || !source || !ctx) return <div className="reader loading">正在打开…</div>;

  const pages = layer.units.filter((u: any) => u.kind === "page" || u.kind === "slide").length;
  const viewerEl =
    Comp && def && !failed ? (
      <Comp
        source={source}
        marks={marks}
        marksVisible={prefs.marks}
        highlight={hover ?? selected}
        options={prefs}
        onReady={setHandle}
        onMarkClick={(k) => {
          setSelected(k);
          if (k) setPrefs({ sidebar: true });
        }}
        onHover={setHover}
        onLocation={setLocation}
        onOutline={setOutline}
        onZoom={setZoomPct}
        onError={(m) => setFailed(m)}
      />
    ) : failed ? (
      <div className="reader-fallback">
        <p>{def?.label ?? "阅读器"}显示不了这份原件：{failed}</p>
        <a className="button" href={fileUrl(id)} target="_blank" rel="noreferrer">
          在新标签页打开原件
        </a>
      </div>
    ) : !def ? (
      <div className="reader-fallback">
        <p>{picked.note || "没有能显示这类原件的阅读器"}</p>
        <a className="button" href={fileUrl(id)} target="_blank" rel="noreferrer">
          在新标签页打开原件
        </a>
      </div>
    ) : (
      <div className="reader-fallback">正在加载阅读器…</div>
    );
  const textUnits = layer.units.filter((u: any) => !u.virtual && u.kind !== "image");
  const hoveredRef: BlockRef = hover ? { unit: hover.split(":")[0], block: Number(hover.split(":")[1]) } : null;

  return (
    <div ref={root} className={`reader${prefs.sidebar ? " with-side" : ""}`}>
      <header className="reader-bar">
        <button type="button" className="small" onClick={() => exitReader(id)} title="回到进入阅读前的页面">
          ← 退出阅读
        </button>
        <strong className="reader-title" title={source.title}>
          {source.title}
        </strong>
        <span className="muted small-text">
          {FORMAT[layer.format] ?? layer.format}
          {pages ? ` · ${pages} 页` : ""}
          {location && pages ? ` · ${layer.units.find((u: any) => u.unit === location)?.label ?? ""}` : ""}
        </span>
        <span className="grow" />
        {views.length > 1 && (
          <span className="seg-buttons">
            {views.map((v) => (
              <button key={v} type="button" className={v === view ? "primary small" : "small"} onClick={() => setPrefs({ view: v })}>
                {VIEW_LABEL[v]}
              </button>
            ))}
          </span>
        )}
        {view !== "text" && caps.includes("zoom") && handle?.zoom && (
          <span className="seg-buttons">
            <button type="button" className="small" onClick={() => handle.zoom?.("out")} title="缩小">
              −
            </button>
            <select
              className="small"
              value={/^\d+$/.test(prefs.zoom) || ["page-width", "page-fit", "auto"].includes(prefs.zoom) ? prefs.zoom : "page-width"}
              onChange={(e) => {
                setPrefs({ zoom: e.target.value });
                handle.zoom?.(e.target.value);
              }}
              title={zoomPct ? `当前 ${zoomPct}%` : ""}
            >
              <option value="page-width">适合宽度{zoomPct && prefs.zoom === "page-width" ? `（${zoomPct}%）` : ""}</option>
              <option value="page-fit">整页</option>
              <option value="auto">自动</option>
              {["75", "100", "125", "150", "200"].map((z) => (
                <option key={z} value={z}>
                  {z}%
                </option>
              ))}
            </select>
            <button type="button" className="small" onClick={() => handle.zoom?.("in")} title="放大">
              +
            </button>
          </span>
        )}
        {view !== "text" && caps.includes("paged") && (
          <>
            <label className="check small-text" title="两页并排">
              <input type="checkbox" checked={prefs.spread} onChange={(e) => setPrefs({ spread: e.target.checked })} /> 双页
            </label>
            <label className="check small-text" title="一次只显示一页，翻页切换">
              <input type="checkbox" checked={prefs.scroll === "page"} onChange={(e) => setPrefs({ scroll: e.target.checked ? "page" : "continuous" })} /> 单页
            </label>
          </>
        )}
        {view !== "text" && caps.includes("find") && handle?.find && (
          <form
            className="reader-find"
            onSubmit={(e) => {
              e.preventDefault();
              if (query.trim()) handle.find?.(query.trim(), (e.nativeEvent as SubmitEvent).submitter?.dataset.prev === "1");
            }}
          >
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="在原件中查找" />
            <button type="submit" className="small" data-prev="1" title="上一个">
              ↑
            </button>
            <button type="submit" className="small" title="下一个">
              ↓
            </button>
          </form>
        )}
        <label className="check small-text" title="段落标记：被引用、被读过、识别文本未确认">
          <input type="checkbox" checked={prefs.marks} onChange={(e) => setPrefs({ marks: e.target.checked })} /> 标注
        </label>
        {source && viewersFor(source, info).length > 1 && (
          <select className="small" value={def?.id ?? ""} onChange={(e) => setChosen(e.target.value)} title="临时换一个阅读器（只影响这一次；默认值在设置页改）">
            {viewersFor(source, info).map(({ def: d, ok, why }) => (
              <option key={d.id} value={d.id} disabled={!ok} title={why}>
                {d.label}
                {ok ? "" : `（${why}）`}
              </option>
            ))}
          </select>
        )}
        <button type="button" className="small" onClick={() => setPrefs({ sidebar: !prefs.sidebar })} title="侧栏：段落、引用、目录">
          ☰
        </button>
        <button type="button" className="small" onClick={() => toggleFullscreen()} title="全屏 / 退出全屏（Esc）">
          ⛶
        </button>
      </header>
      {picked.note && <div className="reader-note">{picked.note}</div>}
      {failed && extracted && <div className="reader-note">{def?.label}显示不了这份原件（{failed}），改为显示抽取的文字。</div>}
      <div className="reader-body">
        <div className={`reader-main view-${view}`}>
          {view !== "text" && <div className="reader-viewer">{viewerEl}</div>}
          {view !== "original" && (
            <div
              className="reader-pane"
              ref={pane}
              onMouseEnter={() => (paneHovered.current = true)}
              onMouseLeave={() => (paneHovered.current = false)}
            >
              <div className={view === "text" ? "reader-text" : ""}>
                {textUnits.map((u: any) => (
                  <UnitSection
                    key={u.unit}
                    ctx={ctx}
                    unit={u}
                    hovered={view === "compare" ? hoveredRef : undefined}
                    onHover={
                      view === "compare"
                        ? (b) => {
                            setHover(b ? `${b.unit}:${b.block}` : null);
                          }
                        : undefined
                    }
                  />
                ))}
              </div>
            </div>
          )}
        </div>
        {prefs.sidebar && (
          <aside className="reader-side">
            {selectedMark && (
              <div className="reader-selected">
                <div className="row tight">
                  <strong className="small-text">{layer.units.find((u: any) => u.unit === selectedMark.unit)?.label} · 选中的段落</strong>
                  <span className="grow" />
                  <button type="button" className="link" onClick={() => setSelected(null)}>
                    关闭
                  </button>
                </div>
                <SegmentDetails ctx={ctx} segs={(segs ?? []).filter((s) => selectedMark.anchors.includes(s.anchor))} showText />
              </div>
            )}
            <div className="seg-buttons side-tabs">
              {(
                [
                  ["marks", "段落"],
                  ["citations", "引用"],
                  ["outline", "目录"],
                ] as [SideTab, string][]
              ).map(([k, t]) => (
                <button key={k} type="button" className={prefs.sideTab === k ? "primary small" : "small"} onClick={() => setPrefs({ sideTab: k })}>
                  {t}
                </button>
              ))}
            </div>
            {prefs.sideTab === "marks" && (
              <MarkList
                marks={marks}
                layer={layer}
                onPick={(k) => {
                  setSelected(k);
                  handle?.scrollTo(k);
                }}
              />
            )}
            {prefs.sideTab === "citations" && <CitationList stats={stats} marks={marks} onPick={(k) => handle?.scrollTo(k)} />}
            {prefs.sideTab === "outline" &&
              (toc.length ? (
                <ul className="plain toc">
                  {toc.map((t, i) => (
                    <li key={i} style={{ paddingLeft: `${t.level * 12}px` }}>
                      <button type="button" className="link" onClick={t.go}>
                        {t.title}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted small-text">没有目录：PDF 没有自带书签，抽取层里也没有标题。</p>
              ))}
            <p className="muted small-text reader-credit">
              阅读器：{def?.label ?? "—"}（{def?.license ?? ""}）·{" "}
              <a href={href("entry", id)} onClick={() => document.fullscreenElement && void document.exitFullscreen()}>
                条目页
              </a>
            </p>
          </aside>
        )}
      </div>
    </div>
  );
}

function byBlockOf(segs: any[]): Record<string, Record<number, any[]>> {
  const out: Record<string, Record<number, any[]>> = {};
  for (const s of segs) {
    const unit = (out[s.unit] ??= {});
    (unit[s.block ?? s.ordinal] ??= []).push(s);
  }
  return out;
}

function headingOutline(layer: any, marks: Mark[]): { title: string; level: number; key: string }[] {
  if (!layer) return [];
  const keys = new Set(marks.map((m) => m.key));
  const out: { title: string; level: number; key: string }[] = [];
  for (const u of layer.units ?? []) {
    (u.blocks ?? []).forEach((b: any, i: number) => {
      const key = `${u.unit}:${i}`;
      if (b.type === "heading" && keys.has(key)) out.push({ title: b.text, level: Math.max(0, (b.level ?? 1) - 1), key });
    });
  }
  return out;
}

function MarkList({ marks, layer, onPick }: { marks: Mark[]; layer: any; onPick: (k: string) => void }) {
  const marked = marks.filter((m) => m.state.cited || m.state.read);
  if (!marked.length) return <p className="muted small-text">还没有被读过或被引用的段落。</p>;
  const label = (u: string) => layer.units.find((x: any) => x.unit === u)?.label ?? u;
  let last = "";
  return (
    <ul className="plain mark-list">
      {marked.map((m) => {
        const head = m.unit !== last ? label(m.unit) : null;
        last = m.unit;
        return (
          <li key={m.key}>
            {head && <div className="muted small-text unit-label">{head}</div>}
            <button type="button" className="link mark-item" onClick={() => onPick(m.key)}>
              <span className={`swatch ${m.state.cited ? "cited" : "read"}`} />
              <span className="mono small-text">{m.anchors[0]}</span> <span className="mark-text">{m.type === "formula" ? "〔公式〕" : ""}{m.text.slice(0, 60)}</span>
              <span className="muted small-text">
                {m.state.cited ? ` 引 ${m.state.cited}` : ""}
                {m.state.read ? ` 读 ${m.state.read}` : ""}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function CitationList({ stats, marks, onPick }: { stats: any; marks: Mark[]; onPick: (k: string) => void }) {
  // 按判断归并：每条判断引用了哪些段落
  const byJudgment = new Map<string, { kind: string; preview: string; anchors: string[] }>();
  for (const [anchor, st] of Object.entries((stats?.segments ?? {}) as Record<string, any>)) {
    for (const [kind, list] of Object.entries((st.citations ?? {}) as Record<string, any[]>)) {
      for (const c of list) {
        const j = byJudgment.get(c.judgment_id) ?? { kind, preview: String(c.preview ?? ""), anchors: [] as string[] };
        j.anchors.push(anchor);
        byJudgment.set(c.judgment_id, j);
      }
    }
  }
  if (!byJudgment.size) return <p className="muted small-text">还没有判断引用这份原件的段落。</p>;
  const keyOf = (anchor: string) => marks.find((m) => m.anchors.includes(anchor))?.key;
  const groups = ["conclusion", "process", "normative"];
  return (
    <div className="citation-list">
      {groups.map((g) => {
        const items = [...byJudgment.entries()].filter(([, j]) => j.kind === g);
        if (!items.length) return null;
        return (
          <div key={g}>
            <div className="muted small-text">
              {JUDGMENT_KIND[g] ?? g}（{items.length}）
            </div>
            {items.map(([jid, j]) => (
              <div key={jid} className="citation-item">
                <IdLink id={jid} /> <span className="small-text">{j.preview.slice(0, 90)}</span>
                <div className="small-text">
                  {j.anchors.map((a) => (
                    <button key={a} type="button" className="link mono" onClick={() => keyOf(a) && onPick(keyOf(a)!)}>
                      #{a}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

// ---------- 判断、框架页、事实记录：宽版排版（D-07） ----------
function EntryReader({ id }: { id: string }) {
  const [data, error] = useLoad(() => call<any>("entry.get", { id }), [id]);
  const [page] = useLoad(() => (id.startsWith("pg_") ? call<any>("page.get", { page: id }) : Promise.resolve(null)), [id]);
  if (error) return <div className="reader"><ErrorBox error={error} /></div>;
  if (!data) return <div className="reader loading">正在打开…</div>;
  const e = data.entry;
  const d = e.data ?? {};
  const text: string = page?.page?.body ?? page?.body ?? d.text ?? d.result ?? d.excerpt ?? "";
  const cites = page
    ? (page.inputs ?? []).map((i: string) => ({ rel: "输入", dst_id: i }))
    : (data.links_out ?? []).filter((l: any) => String(l.dst_id).startsWith("art_") || l.rel === "cites");
  return (
    <div className="reader with-side">
      <header className="reader-bar">
        <button type="button" className="small" onClick={() => exitReader(id)}>
          ← 退出阅读
        </button>
        <strong className="reader-title">{page?.page?.title ?? d.title ?? `${JUDGMENT_KIND[e.kind] ?? e.kind ?? e.entry_kind} ${id}`}</strong>
        <span className="muted small-text">
          {e.author_id ?? e.actor_id} · <Time value={e.created_at} />
        </span>
        <span className="grow" />
        <button type="button" className="small" onClick={() => toggleFullscreen()} title="全屏 / 退出全屏（Esc）">
          ⛶
        </button>
      </header>
      <div className="reader-body">
        <div className="reader-main">
          <div className="reader-pane">
            <article className="reader-article">
              <RefText text={text} />
              {d.conditions && <p>条件：{d.conditions}</p>}
            </article>
          </div>
        </div>
        <aside className="reader-side">
          <div className="muted small-text">它的依据与关系（{cites.length || (data.links_out ?? []).length}）</div>
          <ul className="plain">
            {(cites.length ? cites : (data.links_out ?? [])).map((l: any) => {
              const [base, anchor] = String(l.dst_id).split("#");
              return (
                <li key={`${l.rel}-${l.dst_id}`} className="citation-item">
                  <span className="tag muted">{l.rel}</span> <IdLink id={l.dst_id} />
                  {base.startsWith("art_") && (
                    <button type="button" className="link small-text" onClick={() => openReader(base, anchor)}>
                      在阅读模式中打开
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </aside>
      </div>
    </div>
  );
}
