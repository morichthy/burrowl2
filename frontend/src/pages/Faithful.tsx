// 原件原样显示与段落标记（设计稿 02 D-01、D-02、D-05、D-06、D-08、D-09）。
// 显示原件本来的样子由渲染引擎负责：PDF 用 PDF.js，Word 用 docx-preview，PPT 用页面快照；
// 抽取层只提供每段的位置（box，占页面的比例坐标），这里据此在原样画面上画框：被引用、被读过、低可信度、
// 当前锚点。点一个框弹出这段的抽取文字、引用写法、读取与引用它的判断。
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { fetchArtifactBytes, pageUrl } from "../api";
import { JUDGMENT_KIND } from "../labels";
import { IdLink, Time } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

// PDF.js 的 CMap、标准字体、解码器随前端构建复制到 web/pdfjs/（vite.config.ts），离线也能显示中文 PDF
function assetUrl(dir: string): string {
  return new URL(`./pdfjs/${dir}/`, document.baseURI).href;
}

// 原件页传给这里的上下文：抽取层、段落统计、段落按"单元 → 块"归组、当前锚点
export type MarkCtx = {
  id: string;
  layer: any;
  stats: Record<string, any>;
  byBlock: Record<string, Record<number, any[]>>;
  anchor: string;
  reload: () => void;
};

export type BlockRef = { unit: string; block: number } | null;

// ---------- 段落统计 ----------
export function mergeStats(list: any[]): { reads: any[]; citations: Record<string, any[]> } {
  const out = { reads: [] as any[], citations: {} as Record<string, any[]> };
  for (const s of list) {
    out.reads.push(...(s.reads ?? []));
    for (const [k, items] of Object.entries((s.citations ?? {}) as Record<string, any[]>)) {
      const target = (out.citations[k] ??= []);
      for (const item of items) if (!target.some((t) => t.judgment_id === item.judgment_id)) target.push(item);
    }
  }
  return out;
}

// 一个块上的标记：被引用、被读过、低可信度未确认、是当前锚点
export function blockMarks(ctx: MarkCtx, unit: any, block: number) {
  const segs = ctx.byBlock[unit.unit]?.[block] ?? [];
  const stat = mergeStats(segs.map((s) => ctx.stats[s.anchor]).filter(Boolean));
  const cited = Object.values(stat.citations).reduce((n, list) => n + list.length, 0);
  return {
    segs,
    stat,
    cited,
    read: stat.reads.length,
    low: ["ocr", "ai"].includes(unit.fidelity) && !unit.verified,
    anchor: segs.some((s) => s.anchor === ctx.anchor),
  };
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

// 一段（或一个块的几段）的详情：引用写法、抽取文字、读取记录、引用它的判断（按结论 / 过程 / 规定分组）
export function SegmentDetails({ ctx, segs, showText = false }: { ctx: MarkCtx; segs: any[]; showText?: boolean }) {
  const stat = mergeStats(segs.map((s) => ctx.stats[s.anchor]).filter(Boolean));
  const cites = Object.values(stat.citations).reduce((n: number, list: any) => n + list.length, 0);
  return (
    <div className="seg-details">
      {segs.map((s) => (
        <div key={s.anchor} className="row tight">
          <span className="mono small-text">
            {ctx.id}#{s.anchor}
          </span>
          <CopyText text={`${ctx.id}#${s.anchor}`} label="复制引用" />
        </div>
      ))}
      {showText && <div className="seg-text">{segs.map((s) => s.text).join("\n")}</div>}
      {stat.reads.length === 0 && cites === 0 && <p className="muted small-text">没有被读取或引用</p>}
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
  );
}

// ---------- 叠加层：在一页原样画面上按 box 画框 ----------
// 框本身不接收鼠标（不挡住文字选择）；容器按坐标找出鼠标下的块，悬停高亮、点击弹出详情。
export function MarkedSurface({
  ctx,
  unit,
  aspect,
  hovered,
  onHover,
  children,
}: {
  ctx: MarkCtx;
  unit: any;
  aspect: number;
  hovered?: BlockRef;
  onHover?: (b: BlockRef) => void;
  children: ReactNode;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const [flash, setFlash] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const blocks: any[] = unit.blocks ?? [];
  const boxed = useMemo(() => blocks.map((b, i) => ({ b, i })).filter(({ b }) => b.box && b.type !== "furniture"), [blocks]);
  const anchorBlock = boxed.find(({ i }) => blockMarks(ctx, unit, i).anchor)?.i ?? null;
  useEffect(() => {
    if (anchorBlock === null) return;
    setSelected(anchorBlock);
    setFlash(true);
    const t = window.setTimeout(() => setFlash(false), 2400);
    window.setTimeout(() => ref.current?.querySelector(".mark.anchor")?.scrollIntoView({ block: "center" }), 80);
    return () => window.clearTimeout(t);
  }, [anchorBlock]);
  const hit = (e: React.MouseEvent): number | null => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return null;
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    let best: number | null = null;
    let area = Infinity;
    for (const { b, i } of boxed) {
      const [bx, by, bw, bh] = b.box;
      if (x >= bx - 0.004 && x <= bx + bw + 0.004 && y >= by - 0.004 && y <= by + bh + 0.004 && bw * bh < area) {
        best = i;
        area = bw * bh;
      }
    }
    return best;
  };
  const isHovered = (i: number) => hovered?.unit === unit.unit && hovered?.block === i;
  const sel = selected !== null ? blocks[selected] : null;
  return (
    <div
      ref={ref}
      className="marked-surface"
      style={{ aspectRatio: String(aspect) }}
      onMouseMove={(e) => {
        const i = hit(e);
        if (onHover && (i === null ? hovered?.unit === unit.unit : !isHovered(i))) onHover(i === null ? null : { unit: unit.unit, block: i });
      }}
      onMouseLeave={() => onHover && hovered?.unit === unit.unit && onHover(null)}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest(".mark-pop")) return;
        if (String(window.getSelection() ?? "").trim()) return; // 正在选文字
        const i = hit(e);
        setSelected(i === selected ? null : i);
      }}
    >
      {children}
      <div className="marks">
        {boxed.map(({ b, i }) => {
          const m = blockMarks(ctx, unit, i);
          const cls = [
            "mark",
            m.cited ? "cited" : m.read ? "read" : "",
            m.low ? "low" : "",
            m.anchor ? "anchor" : "",
            m.anchor && flash ? "flash" : "",
            isHovered(i) ? "hover" : "",
            selected === i ? "selected" : "",
          ]
            .filter(Boolean)
            .join(" ");
          const [x, y, w, h] = b.box;
          return <div key={i} className={cls} style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }} />;
        })}
      </div>
      {sel && sel.box && (
        <div
          className="mark-pop"
          style={{
            left: `${Math.min(sel.box[0], 0.55) * 100}%`,
            top: `${Math.min((sel.box[1] + sel.box[3]) * 100 + 0.6, 92)}%`,
          }}
        >
          <div className="row tight">
            <strong className="small-text">{unit.label}</strong>
            <span className="grow" />
            <button type="button" className="link" onClick={() => setSelected(null)}>
              关闭
            </button>
          </div>
          {blockMarks(ctx, unit, selected!).segs.length ? <SegmentDetails ctx={ctx} segs={blockMarks(ctx, unit, selected!).segs} showText /> : <p className="muted small-text">这个块没有可引用的文字</p>}
        </div>
      )}
    </div>
  );
}

// ---------- PDF ----------
function useLazyVisible(margin = "800px") {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (visible || !ref.current) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setVisible(true), { rootMargin: margin });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [visible, margin]);
  return { ref, visible };
}

function useWidth(ref: React.RefObject<HTMLElement | null>) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    setWidth(ref.current.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(ref.current?.clientWidth ?? 0));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

export function usePdf(id: string) {
  const [doc, setDoc] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof pdfjs.getDocument> | null = null;
    // 先自己取字节再交给 PDF.js（不让 PDF.js 直接请求 /file）：下载管理器会拦截 PDF 响应，见 api.fetchArtifactBytes
    fetchArtifactBytes(id)
      .then((data) => {
        if (cancelled) return;
        task = pdfjs.getDocument({
          data,
          cMapUrl: assetUrl("cmaps"),
          cMapPacked: true,
          standardFontDataUrl: assetUrl("standard_fonts"),
          wasmUrl: assetUrl("wasm"),
          iccUrl: assetUrl("iccs"),
        });
        return task.promise;
      })
      .then(
        (d) => !cancelled && d && setDoc(d),
        (e) => !cancelled && setError(String(e?.message ?? e)),
      );
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [id]);
  return { doc, error };
}

function pageAspect(unit: any): number {
  const size = unit.meta?.size;
  if (!size) return 595 / 842;
  const rotated = [90, 270].includes(((unit.meta?.rotation ?? 0) % 360 + 360) % 360);
  return rotated ? size[1] / size[0] : size[0] / size[1];
}

// 一页 PDF：画布 + 可选中的文字层 + 段落框。进入视口附近才渲染，宽度变化后按新宽度重画。
export function PdfPageView({ ctx, doc, unit, hovered, onHover }: { ctx: MarkCtx; doc: pdfjs.PDFDocumentProxy; unit: any; hovered?: BlockRef; onHover?: (b: BlockRef) => void }) {
  const { ref, visible } = useLazyVisible();
  const width = useWidth(ref);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const rendered = useRef(0);
  useEffect(() => {
    if (!visible || !width || Math.abs(width - rendered.current) < 24) return;
    let cancelled = false;
    let task: any = null;
    (async () => {
      try {
        const page = await doc.getPage(unit.page);
        if (cancelled || !canvasRef.current || !textRef.current) return;
        const scale = width / page.getViewport({ scale: 1 }).width;
        const viewport = page.getViewport({ scale });
        const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
        const canvas = canvasRef.current;
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        task = page.render({ canvas, viewport, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined });
        await task.promise;
        if (cancelled) return;
        const text = textRef.current;
        text.replaceChildren();
        text.style.setProperty("--scale-factor", String(scale));
        text.style.setProperty("--total-scale-factor", String(scale));
        await new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: text, viewport }).render();
        rendered.current = width;
      } catch (e: any) {
        if (!cancelled && e?.name !== "RenderingCancelledException") setFailed(String(e?.message ?? e));
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel?.();
    };
  }, [visible, width, doc, unit.page]);
  return (
    <div ref={ref} className="pdf-page">
      {failed ? (
        <img className="page-image" src={pageUrl(ctx.id, unit.page)} alt={unit.label} loading="lazy" title={`PDF.js 渲染失败（${failed}），显示服务端渲染的页面图像`} />
      ) : (
        <MarkedSurface ctx={ctx} unit={unit} aspect={pageAspect(unit)} hovered={hovered} onHover={onHover}>
          <canvas ref={canvasRef} className="pdf-canvas" />
          <div ref={textRef} className="textLayer" />
        </MarkedSurface>
      )}
    </div>
  );
}

// ---------- PPT：页面快照上画框（D-09） ----------
export function SnapshotSlide({ ctx, unit }: { ctx: MarkCtx; unit: any }) {
  const aspect = ctx.layer.manifest?.aspect ?? 16 / 9;
  return (
    <MarkedSurface ctx={ctx} unit={unit} aspect={aspect}>
      <img className="slide-image fill" src={pageUrl(ctx.id, unit.page, 1.5, "snapshot")} alt={unit.label} loading="lazy" />
    </MarkedSurface>
  );
}

// ---------- Word：docx-preview 原样显示（D-08） ----------
// 渲染出的段落与表格按文字依次对应到抽取的版式块；对上的元素加上标记，点击弹出详情。
// 对上的块少于一半时退回"近似版式"（由调用方显示），避免标记落错位置。
const norm = (s: string) => s.replace(/\s+/g, "").slice(0, 40);

export function DocxOriginal({ ctx, unit, onFallback }: { ctx: MarkCtx; unit: any; onFallback: (why: string) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const style = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [state, setState] = useState<"loading" | "ok">("loading");
  const blocks: any[] = unit?.blocks ?? [];
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { renderAsync } = await import("docx-preview");
        const blob = new Blob([await fetchArtifactBytes(ctx.id)]);
        if (cancelled || !host.current || !style.current) return;
        await renderAsync(blob, host.current, style.current, { inWrapper: true, breakPages: true, renderComments: false, renderChanges: false });
        if (cancelled || !host.current) return;
        const elements = Array.from(host.current.querySelectorAll("article > p, article > table, article > div > p")) as HTMLElement[];
        let cursor = 0;
        let matched = 0;
        const candidates = blocks.map((b, i) => ({ b, i })).filter(({ b }) => b.type !== "image" && norm(b.text ?? (b.rows ?? []).flat().join("")));
        for (const { b, i } of candidates) {
          const key = norm(b.type === "table" ? (b.rows ?? []).flat().join("") : (b.text ?? ""));
          for (let j = cursor; j < elements.length; j++) {
            if (norm(elements[j].textContent ?? "").startsWith(key.slice(0, 20))) {
              const m = blockMarks(ctx, unit, i);
              const el = elements[j];
              el.dataset.block = String(i);
              el.classList.add("doc-mark");
              if (m.cited) el.classList.add("cited");
              else if (m.read) el.classList.add("read");
              if (m.anchor) {
                el.classList.add("anchor", "flash");
                window.setTimeout(() => el.scrollIntoView({ block: "center" }), 80);
                window.setTimeout(() => el.classList.remove("flash"), 2400);
              }
              cursor = j + 1;
              matched++;
              break;
            }
          }
        }
        if (candidates.length && matched < candidates.length / 2) {
          onFallback(`渲染出的段落只对上 ${matched} / ${candidates.length} 个版式块`);
          return;
        }
        setState("ok");
      } catch (e: any) {
        if (!cancelled) onFallback(String(e?.message ?? e));
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.id, unit?.extraction_id]);
  const segs = selected !== null ? blockMarks(ctx, unit, selected).segs : [];
  return (
    <div className="docx-original">
      {state === "loading" && <p className="muted">正在按原样排版 Word 文档…</p>}
      <div ref={style} />
      <div
        ref={host}
        onClick={(e) => {
          if (String(window.getSelection() ?? "").trim()) return;
          const el = (e.target as HTMLElement).closest("[data-block]") as HTMLElement | null;
          setSelected(el ? Number(el.dataset.block) : null);
        }}
      />
      {selected !== null && (
        <div className="mark-pop docked">
          <div className="row tight">
            <strong className="small-text">选中的段落</strong>
            <span className="grow" />
            <button type="button" className="link" onClick={() => setSelected(null)}>
              关闭
            </button>
          </div>
          {segs.length ? <SegmentDetails ctx={ctx} segs={segs} showText /> : <p className="muted small-text">这个块没有可引用的文字</p>}
        </div>
      )}
    </div>
  );
}
