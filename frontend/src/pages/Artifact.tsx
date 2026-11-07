// 原件页（设计稿 01 §3、D-01、D-15、D-16、D-17）：默认显示抽取结果，并按格式优化，原件随时可以打开。
// 显示什么与检索什么一致：都来自当前抽取层。段落旁标出被读过几次、被哪些判断引用；识别文本标出可信度档。
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { blobUrl, call, fileUrl, pageUrl } from "../api";
import { FIDELITY, FORMAT, JUDGMENT_KIND, UNIT_STATUS } from "../labels";
import { delegate, href } from "../router";
import { Action, ErrorBox, IdLink, Tag, Time, useLoad } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

const PAGE_STEP = 20; // 一次显示的页数；更多的点"显示更多"

type Ctx = {
  id: string;
  layer: any;
  stats: Record<string, any>;
  byBlock: Record<string, Record<number, any[]>>;
  anchor: string;
  onlyMarked: boolean;
  reload: () => void;
};

export function ArtifactView({ entry, anchor, onChanged }: { entry: any; anchor: string; onChanged?: () => void }) {
  const id = entry.id;
  const [layer, lError, reloadLayer] = useLoad(() => call<any>("artifact.layer", { artifact_id: id }), [id]);
  const [segs, , reloadSegs] = useLoad(() => call<any[]>("artifact.segments", { artifact_id: id }).catch(() => []), [id]);
  const [stats, , reloadStats] = useLoad(() => call<any>("artifact.segment_stats", { artifact_id: id }), [id]);
  const [onlyMarked, setOnlyMarked] = useState(false);
  const reload = () => {
    reloadLayer();
    reloadSegs();
    reloadStats();
    onChanged?.();
  };
  // 段落按"单元 → 版式块"归组：显示版式块时把它的段落标记挂上去
  const byBlock = useMemo(() => {
    const out: Record<string, Record<number, any[]>> = {};
    for (const s of segs ?? []) {
      const unit = (out[s.unit] ??= {});
      (unit[s.block ?? s.ordinal] ??= []).push(s);
    }
    return out;
  }, [segs]);
  useEffect(() => {
    if (!anchor || !segs) return;
    window.setTimeout(() => document.getElementById(`seg-${anchor}`)?.scrollIntoView({ block: "center" }), 50);
  }, [anchor, segs]);
  if (lError) return <ErrorBox error={lError} />;
  if (!layer) return <p className="muted">读取原件…</p>;
  const ctx: Ctx = { id, layer, stats: stats?.segments ?? {}, byBlock, anchor: anchor.replace(/^seg:/, "seg-"), onlyMarked, reload };
  const marked = Object.keys(ctx.stats).length;
  return (
    <div className="artifact">
      <Toolbar entry={entry} layer={layer} reload={reload} />
      <Summary entry={entry} layer={layer} stats={stats} />
      {marked > 0 && (
        <label className="check small-text">
          <input type="checkbox" checked={onlyMarked} onChange={(e) => setOnlyMarked(e.target.checked)} /> 只看被读过或被引用的段落（{marked} 段）
        </label>
      )}
      <Body entry={entry} ctx={ctx} segs={segs ?? []} />
    </div>
  );
}

// ---------- 工具条与概况 ----------
function Toolbar({ entry, layer, reload }: { entry: any; layer: any; reload: () => void }) {
  const id = entry.id;
  const unverified = layer.units.filter((u: any) => u.status === "text" && !u.verified && !u.virtual).length;
  return (
    <div className="toolbar">
      <a className="button" href={fileUrl(id)} target="_blank" rel="noreferrer">
        打开原件
      </a>
      <a className="button" href={fileUrl(id, true)}>
        下载
      </a>
      {entry.storage === "referenced" && <CopyText text={entry.data?.path} label="复制原路径" />}
      {layer.auto_supported && <Action label={layer.extracted ? "重新抽取" : "抽取"} run={async () => (await call("artifact.extract", { artifact_id: id, method: "auto" }), reload())} />}
      {layer.snapshot_supported && (
        <Action label={layer.snapshot ? "重新生成快照" : "生成页面快照"} run={async () => (await call("artifact.snapshot", { artifact_id: id, force: !!layer.snapshot }), reload())} />
      )}
      {unverified > 0 && <Action label={`确认全部抽取（${unverified}）`} run={async () => (await call("artifact.verify_extraction", { artifact_id: id }), reload())} />}
    </div>
  );
}

function Summary({ entry, layer, stats }: { entry: any; layer: any; stats: any }) {
  const d = entry.data ?? {};
  const units = layer.units as any[];
  const pages = units.filter((u) => u.kind === "page" || u.kind === "slide").length;
  const methods = [...new Set(units.map((u) => u.method).filter(Boolean))];
  const fidelities = [...new Set(units.map((u) => u.fidelity).filter(Boolean))] as string[];
  const verified = units.filter((u) => u.verified).length;
  const counts = layer.counts ?? {};
  return (
    <div className="artifact-summary">
      <h3>{d.title ?? "（无标题）"}</h3>
      <p className="meta">
        {FORMAT[layer.format] ?? layer.format}
        {pages ? ` · ${pages} 页` : ""} · {entry.storage === "managed" ? "受管保存" : "外部引用"} · <Time value={entry.created_at} />
        {stats?.reads ? ` · 被读过 ${stats.reads} 次` : ""}
      </p>
      <p className="meta">
        抽取：
        {!layer.extracted ? (
          <Tag tone="warn">还没有抽取</Tag>
        ) : (
          <>
            {fidelities.map((f) => (
              <FidelityTag key={f} fidelity={f} />
            ))}{" "}
            {methods.join("、")}
            {Object.keys(counts).length > 1 || !counts.text ? (
              <span className="muted">
                {fidelities.length ? " · " : ""}
                {Object.entries(counts)
                  .map(([status, n]) => `${UNIT_STATUS[status] ?? status} ${n}`)
                  .join(" · ")}
              </span>
            ) : null}
            {verified > 0 && <span className="muted"> · 已确认 {verified}</span>}
          </>
        )}
        {layer.manifest_error && <Tag tone="bad">抽取失败：{layer.manifest_error}</Tag>}
      </p>
      {layer.derived_texts?.from && (
        <p className="meta">
          派生自 <IdLink id={layer.derived_texts.from} />（旧的登记方式：抽取文本单独登记为一份原件）
        </p>
      )}
      {layer.derived_texts?.texts?.length > 0 && (
        <p className="meta">
          旧的派生文本：
          {layer.derived_texts.texts.map((t: string) => (
            <IdLink key={t} id={t} />
          ))}
          （独立登记的文本原件；这份原件现在有自己的抽取层）
        </p>
      )}
    </div>
  );
}

// ---------- 按格式显示 ----------
function Body({ entry, ctx, segs }: { entry: any; ctx: Ctx; segs: any[] }) {
  const f = ctx.layer.format;
  if (f === "text") return <TextBody entry={entry} ctx={ctx} segs={segs} />;
  if (!ctx.layer.extracted && f !== "image" && f !== "av") {
    return <p className="empty">{f === "binary" ? "这类文件没有内置抽取器，可以点“打开原件”查看。" : "还没有抽取：点上方“抽取”。"}</p>;
  }
  if (f === "pdf") return <Pages ctx={ctx} render={(u) => <PdfPage ctx={ctx} unit={u} />} />;
  if (f === "pptx")
    return (
      <>
        <SnapshotNotice ctx={ctx} />
        <Pages ctx={ctx} render={(u) => <Slide ctx={ctx} unit={u} />} />
      </>
    );
  if (f === "docx") return <DocBody ctx={ctx} />;
  if (f === "image") return <ImageBody ctx={ctx} />;
  if (f === "av") return <AvBody ctx={ctx} />;
  return <p className="empty">这类文件没有内置抽取器，可以点“打开原件”查看。</p>;
}

function Pages({ ctx, render }: { ctx: Ctx; render: (u: any) => ReactNode }) {
  const pages = ctx.layer.units.filter((u: any) => u.kind === "page" || u.kind === "slide");
  const anchorUnit = ctx.anchor.split("-")[0];
  const [shown, setShown] = useState(() => Math.max(PAGE_STEP, pages.findIndex((u: any) => u.unit === anchorUnit) + 3));
  const visible = ctx.onlyMarked ? pages.filter((u: any) => hasMarks(ctx, u.unit)) : pages.slice(0, shown);
  return (
    <div className="pages">
      {visible.map((u: any) => (
        <div key={u.unit}>{render(u)}</div>
      ))}
      {!ctx.onlyMarked && shown < pages.length && (
        <button type="button" onClick={() => setShown(shown + PAGE_STEP)}>
          显示更多（还有 {pages.length - shown} 页）
        </button>
      )}
    </div>
  );
}

function hasMarks(ctx: Ctx, unit: string): boolean {
  return Object.values(ctx.byBlock[unit] ?? {}).some((list) => list.some((s) => ctx.stats[s.anchor]));
}

// 单元的标题行：名称、状态、可信度档、是否确认，以及本单元的操作
function UnitHead({ ctx, unit, extra }: { ctx: Ctx; unit: any; extra?: ReactNode }) {
  const [history, setHistory] = useState<any[] | null>(null);
  const id = ctx.id;
  return (
    <div className="unit-head">
      <strong>{unit.label}</strong>
      {unit.status !== "text" ? <Tag tone={unit.status === "image" || unit.status === "not_extracted" ? "warn" : "muted"}>{UNIT_STATUS[unit.status] ?? unit.status}</Tag> : <FidelityTag fidelity={unit.fidelity} />}
      {unit.verified && <Tag tone="good">已确认</Tag>}
      {unit.fidelity && ["ocr", "ai"].includes(unit.fidelity) && !unit.verified && <Tag tone="warn">引用前请对照原件</Tag>}
      {extra}
      <span className="unit-actions">
        {unit.status === "text" && !unit.verified && !unit.virtual && (
          <Action className="link" label="确认" run={async () => (await call("artifact.verify_extraction", { artifact_id: id, units: [unit.unit] }), ctx.reload())} />
        )}
        {ctx.layer.auto_supported && (unit.kind === "page" || unit.kind === "slide") && (
          <Action className="link" label="重新抽取" run={async () => (await call("artifact.extract", { artifact_id: id, method: "auto", units: [unit.unit] }), ctx.reload())} />
        )}
        {unit.extraction_id && (
          <button type="button" className="link" onClick={async () => setHistory(history ? null : await call("artifact.extraction_history", { artifact_id: id, unit: unit.unit }))}>
            {history ? "收起历史" : "抽取历史"}
          </button>
        )}
      </span>
      {history && (
        <ul className="history">
          {history.map((h) => (
            <li key={h.id}>
              <Time value={h.created_at} /> {h.actor_id} · {UNIT_STATUS[h.status] ?? h.status}
              {h.fidelity && <FidelityTag fidelity={h.fidelity} />} {h.method} {h.verified && <Tag tone="good">已确认</Tag>}
              {h.text && <div className="muted small-text">{h.text.slice(0, 160)}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------- PDF ----------
function PdfPage({ ctx, unit }: { ctx: Ctx; unit: any }) {
  const [showImage, setShowImage] = useState(unit.status === "image");
  const n = unit.page;
  return (
    <section className="unit" id={`unit-${unit.unit}`}>
      <UnitHead
        ctx={ctx}
        unit={unit}
        extra={
          <>
            <a href={`${fileUrl(ctx.id)}#page=${n}`} target="_blank" rel="noreferrer" className="small-text">
              看原页 ↗
            </a>
            {unit.status === "text" && (
              <button type="button" className="link" onClick={() => setShowImage(!showImage)}>
                {showImage ? "隐藏页面图像" : "对照页面图像"}
              </button>
            )}
          </>
        }
      />
      <div className={showImage && unit.status === "text" ? "side-by-side" : ""}>
        {showImage && <img className="page-image" src={pageUrl(ctx.id, n)} alt={unit.label} loading="lazy" />}
        {unit.status === "text" && <Blocks ctx={ctx} unit={unit} />}
      </div>
      {(unit.status === "image" || unit.status === "not_extracted") && <ExtractBox ctx={ctx} unit={unit} />}
      {unit.status === "empty" && <p className="muted small-text">空白页</p>}
    </section>
  );
}

// ---------- PPTX ----------
function Slide({ ctx, unit }: { ctx: Ctx; unit: any }) {
  const snap = ctx.layer.snapshot;
  const aspect = ctx.layer.manifest?.aspect ?? 16 / 9;
  return (
    <section className="unit slide" id={`unit-${unit.unit}`}>
      <UnitHead ctx={ctx} unit={unit} extra={!snap && <Tag tone="muted">近似版式</Tag>} />
      {snap ? (
        <img className="slide-image" src={pageUrl(ctx.id, unit.page, 1.5, "snapshot")} alt={unit.label} loading="lazy" />
      ) : (
        <div className="slide-canvas" style={{ aspectRatio: String(aspect) }}>
          {(unit.blocks ?? []).map((b: any, i: number) =>
            b.box ? (
              <div key={i} className={`slide-box ${b.type}`} style={{ left: `${b.box[0] * 100}%`, top: `${b.box[1] * 100}%`, width: `${b.box[2] * 100}%`, height: `${b.box[3] * 100}%` }}>
                {b.type === "image" ? <img src={blobUrl(ctx.id, b.sha256, b.mime)} alt="" /> : <span>{blockPlain(b)}</span>}
              </div>
            ) : null,
          )}
        </div>
      )}
      <Blocks ctx={ctx} unit={unit} />
    </section>
  );
}

// 没有快照时自动生成一次（设置为 none 或没有转换器时显示原因，保留近似版式）
function useAutoSnapshot(ctx: Ctx) {
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  const [reason, setReason] = useState("");
  const tried = useRef(false);
  useEffect(() => {
    if (!ctx.layer.snapshot_supported || ctx.layer.snapshot || !ctx.layer.extracted || tried.current) return;
    tried.current = true;
    setState("busy");
    call("artifact.snapshot", { artifact_id: ctx.id })
      .then(() => {
        setState("idle");
        ctx.reload();
      })
      .catch((e) => {
        setState("failed");
        setReason(e.message);
      });
  }, [ctx]);
  return { state, reason };
}

function SnapshotNotice({ ctx }: { ctx: Ctx }) {
  const { state, reason } = useAutoSnapshot(ctx);
  if (state === "busy") return <div className="notice">正在用本机的 Office 生成页面快照（约 10 秒），完成后显示与原件一致的版式…</div>;
  if (state === "failed") return <div className="notice">没有生成页面快照：{reason}。下面按抽取的版式块近似显示。</div>;
  return null;
}

// ---------- DOCX ----------
function DocBody({ ctx }: { ctx: Ctx }) {
  const [mode, setMode] = useState<"flow" | "pages">("flow");
  const doc = ctx.layer.units.find((u: any) => u.unit === "doc");
  const snap = ctx.layer.snapshot;
  return (
    <>
      <SnapshotNotice ctx={ctx} />
      <div className="row tight">
        <button type="button" className={mode === "flow" ? "primary small" : "small"} onClick={() => setMode("flow")}>
          正文
        </button>
        <button type="button" className={mode === "pages" ? "primary small" : "small"} disabled={!snap} onClick={() => setMode("pages")} title={snap ? "" : "还没有页面快照"}>
          逐页快照{snap ? `（${snap.pages} 页）` : ""}
        </button>
      </div>
      {mode === "pages" && snap ? (
        <div className="pages">
          {Array.from({ length: snap.pages }, (_, i) => (
            <img key={i} className="slide-image" src={pageUrl(ctx.id, i + 1, 1.5, "snapshot")} alt={`第 ${i + 1} 页`} loading="lazy" />
          ))}
        </div>
      ) : (
        doc && (
          <section className="unit doc-flow">
            <UnitHead ctx={ctx} unit={doc} />
            <Blocks ctx={ctx} unit={doc} />
          </section>
        )
      )}
    </>
  );
}

// ---------- 图片、音视频 ----------
function ImageBody({ ctx }: { ctx: Ctx }) {
  const unit = ctx.layer.units.find((u: any) => u.unit === "img") ?? { unit: "img", label: "图片", status: "not_extracted", kind: "image" };
  return (
    <section className="unit">
      <img className="original-image" src={fileUrl(ctx.id)} alt="原件" />
      <UnitHead ctx={ctx} unit={unit} />
      {unit.status === "text" ? <Blocks ctx={ctx} unit={unit} /> : <ExtractBox ctx={ctx} unit={unit} />}
    </section>
  );
}

function AvBody({ ctx }: { ctx: Ctx }) {
  const ref = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  const unit = ctx.layer.units.find((u: any) => u.unit === "av") ?? { unit: "av", label: "音视频", status: "not_extracted", kind: "media" };
  const audio = String(ctx.layer.media_type).startsWith("audio/");
  const seek = (t: number) => {
    if (!ref.current) return;
    ref.current.currentTime = t;
    void ref.current.play();
  };
  return (
    <section className="unit">
      {audio ? <audio ref={ref} controls src={fileUrl(ctx.id)} className="original-audio" /> : <video ref={ref} controls src={fileUrl(ctx.id)} className="original-media" />}
      <UnitHead ctx={ctx} unit={unit} />
      {unit.status === "text" ? <Blocks ctx={ctx} unit={unit} onSeek={seek} /> : <ExtractBox ctx={ctx} unit={unit} />}
    </section>
  );
}

// ---------- 文本原件 ----------
function TextBody({ entry, ctx, segs }: { entry: any; ctx: Ctx; segs: any[] }) {
  const suffix = entry.data?.suffix ?? (entry.data?.media_type === "text/markdown" ? ".md" : "");
  const unit = ctx.layer.units[0];
  if (unit?.status === "unreadable") return <ErrorBox error={unit.error} />;
  if (suffix === ".csv" || suffix === ".tsv") return <CsvTable text={unit?.text ?? ""} sep={suffix === ".tsv" ? "\t" : ","} />;
  if (suffix === ".json") return <pre className="code">{prettyJson(unit?.text ?? "")}</pre>;
  const markdown = suffix === ".md" || suffix === ".markdown" || !suffix;
  const shown = ctx.onlyMarked ? segs.filter((s) => ctx.stats[s.anchor]) : segs;
  return (
    <div className={markdown ? "doc-flow" : ""}>
      {shown.map((s) => (
        <Segment key={s.anchor} ctx={ctx} seg={s}>
          {markdown ? <Md text={s.text} /> : <pre className="code">{s.text}</pre>}
        </Segment>
      ))}
    </div>
  );
}

function Md({ text }: { text: string }) {
  return (
    <div className="md">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  );
}

function prettyJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function CsvTable({ text, sep }: { text: string; sep: string }) {
  const rows = text
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map((l) => splitCsv(l, sep));
  return (
    <div className="table-wrap">
      <table className="data-table">
        <tbody>
          {rows.slice(0, 500).map((r, i) => (
            <tr key={i}>{r.map((c, j) => (i === 0 ? <th key={j}>{c}</th> : <td key={j}>{c}</td>))}</tr>
          ))}
        </tbody>
      </table>
      {rows.length > 500 && <p className="muted">只显示前 500 行，共 {rows.length} 行；完整内容请打开原件。</p>}
    </div>
  );
}

function splitCsv(line: string, sep: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"' && line[i + 1] === '"' && quoted) {
      cur += '"';
      i++;
    } else if (ch === '"') quoted = !quoted;
    else if (ch === sep && !quoted) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

// ---------- 版式块（D-16）与段落 ----------
function Blocks({ ctx, unit, onSeek }: { ctx: Ctx; unit: any; onSeek?: (t: number) => void }) {
  const segsOf = ctx.byBlock[unit.unit] ?? {};
  const blocks: any[] = unit.blocks ?? [];
  return (
    <div className="blocks">
      {blocks.map((b, i) => {
        const segs = segsOf[i] ?? [];
        if (ctx.onlyMarked && !segs.some((s) => ctx.stats[s.anchor])) return null;
        const body = <BlockView ctx={ctx} block={b} onSeek={onSeek} />;
        if (!segs.length) return <div key={i}>{body}</div>;
        return (
          <Segment key={i} ctx={ctx} seg={segs[0]} more={segs.slice(1)}>
            {body}
          </Segment>
        );
      })}
    </div>
  );
}

function BlockView({ ctx, block: b, onSeek }: { ctx: Ctx; block: any; onSeek?: (t: number) => void }) {
  switch (b.type) {
    case "heading": {
      const Tag = `h${Math.min(6, (b.level ?? 1) + 2)}` as "h3";
      return <Tag className="blk-heading">{b.text}</Tag>;
    }
    case "title":
      return <h4 className="blk-heading">{paras(b)}</h4>;
    case "text":
      return (
        <ul className="blk-text">
          {(b.paragraphs ?? []).map((p: any, i: number) => (
            <li key={i} style={{ marginLeft: `${(p.level ?? 0) * 1.2}em` }}>
              {p.text}
            </li>
          ))}
        </ul>
      );
    case "list":
      return (
        <div className="blk-list" style={{ marginLeft: `${(b.level ?? 0) * 1.2 + 0.4}em` }}>
          {b.ordered ? "1." : "•"} {b.text}
        </div>
      );
    case "table":
      return (
        <div className="table-wrap">
          <table className="data-table">
            <tbody>
              {(b.rows ?? []).map((r: string[], i: number) => (
                <tr key={i}>{r.map((c, j) => (i === 0 ? <th key={j}>{c}</th> : <td key={j}>{c}</td>))}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "image": {
      const sub = ctx.layer.units.find((u: any) => u.unit === b.unit);
      return (
        <figure className="blk-image">
          <img src={blobUrl(ctx.id, b.sha256, b.mime)} alt={b.alt ?? ""} loading="lazy" />
          {sub && (
            <figcaption>
              <UnitHead ctx={ctx} unit={sub} />
              {sub.status === "text" ? <div className="muted">{sub.text}</div> : <ExtractBox ctx={ctx} unit={sub} compact />}
            </figcaption>
          )}
        </figure>
      );
    }
    case "media":
      return <div className="notice">嵌入的音视频：{b.alt || b.note}（请打开原件播放）</div>;
    case "notes":
      return <div className="blk-notes">备注：{b.text}</div>;
    case "cue":
      return (
        <div className="blk-cue">
          <button type="button" className="link mono" onClick={() => onSeek?.(b.t)}>
            {clock(b.t)}
          </button>{" "}
          {b.text}
        </div>
      );
    case "chart":
      return <div className="muted">{b.text}</div>;
    default:
      return <p className={`blk-para${b.bold ? " bold" : ""}${b.italic ? " italic" : ""}`}>{b.text}</p>;
  }
}

function paras(b: any): string {
  return (b.paragraphs ?? []).map((p: any) => p.text).join(" ");
}

function blockPlain(b: any): string {
  if (b.type === "table") return (b.rows ?? []).map((r: string[]) => r.join(" | ")).join("\n");
  if (b.paragraphs) return b.paragraphs.map((p: any) => p.text).join("\n");
  return b.text ?? "";
}

function clock(t: number): string {
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

// 一段：正文 + 右侧的读取与引用标记；点开列出读取日志和引用它的判断（按结论 / 过程 / 规定分组）
function Segment({ ctx, seg, more = [], children }: { ctx: Ctx; seg: any; more?: any[]; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const all = [seg, ...more];
  const stat = mergeStats(all.map((s) => ctx.stats[s.anchor]).filter(Boolean));
  const highlighted = all.some((s) => s.anchor === ctx.anchor);
  const cites = Object.values(stat.citations).reduce((n: number, list: any) => n + list.length, 0);
  return (
    <div id={`seg-${seg.anchor}`} className={`seg${highlighted ? " hl" : ""}${stat.reads.length ? " read" : ""}${cites ? " cited" : ""}`}>
      {more.map((s) => (
        <span key={s.anchor} id={`seg-${s.anchor}`} />
      ))}
      <div className="seg-body">{children}</div>
      <div className="seg-meta">
        <button type="button" className="link" onClick={() => setOpen(!open)} title={`引用写 ${ctx.id}#${seg.anchor}`}>
          <span className="mono">{seg.anchor}</span>
          {stat.reads.length > 0 && <span> · 读 {stat.reads.length}</span>}
          {Object.entries(stat.citations).map(([k, list]: [string, any]) => (
            <span key={k}>
              {" "}
              · {JUDGMENT_KIND[k] ?? k} {list.length}
            </span>
          ))}
        </button>
        {open && (
          <div className="seg-pop">
            <CopyText text={`${ctx.id}#${seg.anchor}`} label="复制引用" />
            {stat.reads.length === 0 && cites === 0 && <p className="muted">没有被读取或引用</p>}
            {stat.reads.map((r: any) => (
              <div key={r.id} className="small-text">
                读取 <Time value={r.created_at} /> {r.actor_id}
              </div>
            ))}
            {Object.entries(stat.citations).map(([k, list]: [string, any]) => (
              <div key={k}>
                <div className="small-text muted">{JUDGMENT_KIND[k] ?? k}</div>
                {list.map((c: any) => (
                  <div key={c.judgment_id} className="small-text">
                    <IdLink id={c.judgment_id} /> {c.preview?.slice(0, 80)}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function mergeStats(list: any[]): { reads: any[]; citations: Record<string, any[]> } {
  const out = { reads: [] as any[], citations: {} as Record<string, any[]> };
  for (const s of list) {
    out.reads.push(...s.reads);
    for (const [k, items] of Object.entries(s.citations as Record<string, any[]>)) {
      const target = (out.citations[k] ??= []);
      for (const item of items) if (!target.some((t) => t.judgment_id === item.judgment_id)) target.push(item);
    }
  }
  return out;
}

// ---------- 抽取：交给 AI，或人工转写 ----------
function ExtractBox({ ctx, unit, compact }: { ctx: Ctx; unit: any; compact?: boolean }) {
  const [manual, setManual] = useState(false);
  const [text, setText] = useState("");
  const media = unit.kind === "media";
  const prompt = media
    ? `请为原件 ${ctx.id} 的音视频提交转写：用你能用的转写工具得到带时间戳的文字，然后用 artifact_extract 提交（method=ai，model 写使用的模型，content=[{unit: "av", text: "[00:00:05] …"}]）。只转写听到的内容，不要总结。`
    : `请识别原件 ${ctx.id} 的${unit.label}（单元 ${unit.unit}）：先用 artifact_view(artifact_id="${ctx.id}", unit="${unit.unit}") 看图像，然后用 artifact_extract 提交（method=ai，model 写你的模型名，content=[{unit: "${unit.unit}", text: …}]）。只转写看到的文字和数字，表格按行写，不要总结或补充。`;
  return (
    <div className={`extract-box${compact ? " compact" : ""}`}>
      {!compact && <span className="muted small-text">{media ? "音视频默认不转写。" : "图片默认不抽取。"}</span>}
      <button type="button" className="small" onClick={() => delegate(prompt)}>
        交给 AI 抽取
      </button>
      <button type="button" className="small" onClick={() => setManual(!manual)}>
        {manual ? "取消" : "手动转写"}
      </button>
      {manual && (
        <div className="forms single">
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={media ? "[00:00:05] 一行一段，带时间戳" : "按原样转写；空行分段"} />
          <Action
            label="提交转写"
            disabled={!text.trim()}
            run={async () => {
              await call("artifact.extract", { artifact_id: ctx.id, method: "manual", content: [{ unit: unit.unit, text }] });
              setManual(false);
              setText("");
              ctx.reload();
            }}
          />
        </div>
      )}
    </div>
  );
}

// ---------- 小部件 ----------
export function FidelityTag({ fidelity }: { fidelity: string | null | undefined }) {
  if (!fidelity) return null;
  const tone = fidelity === "copy" || fidelity === "parsed" ? "good" : fidelity === "manual" ? "accent" : "warn";
  return <Tag tone={tone}>{FIDELITY[fidelity] ?? fidelity}</Tag>;
}

export function CopyText({ text, label }: { text?: string; label: string }) {
  const [state, setState] = useState("");
  return (
    <button
      type="button"
      className="small"
      disabled={!text}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text ?? "");
          setState("已复制");
        } catch {
          setState("请手动复制");
        }
        window.setTimeout(() => setState(""), 1500);
      }}
    >
      {state || label}
    </button>
  );
}

export function AnchorLink({ id, anchor, children }: { id: string; anchor?: string; children?: ReactNode }) {
  return <a href={href("entry", anchor ? `${id}#${anchor}` : id)}>{children ?? (anchor ? `${id}#${anchor}` : id)}</a>;
}
