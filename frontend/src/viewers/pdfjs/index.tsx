// PDF.js 阅读器（设计稿 03 D-08）：用 PDF.js 自带的阅读器组件（PDFViewer、EventBus、PDFLinkService、PDFFindController，
// 与 Firefox 内置 PDF 阅读器同一套）显示 PDF 与 Office 快照 PDF：连续滚动、懒渲染、缩放、单页与双页、目录、文内链接、查找。
// 标注方式 boxes：每页渲染后在页面容器上叠加段落框（框不接收鼠标，不挡文字选择；按坐标找块）。
// 只用 pdfjs-dist 的公开 API，不改它的源码；它的注释编辑器（会把注释写进 PDF）关闭。
import { useEffect, useRef } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import type { Mark, OutlineItem, ViewerProps } from "../../reader/contract";
import "./pdfjs.css";

/* eslint-disable @typescript-eslint/no-explicit-any */

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

// pdf_viewer.mjs 从 globalThis.pdfjsLib 取核心库，所以先挂上再动态加载
let viewerLib: Promise<any> | null = null;
function loadViewerLib(): Promise<any> {
  (globalThis as any).pdfjsLib = pdfjs;
  viewerLib ??= import("pdfjs-dist/web/pdf_viewer.mjs");
  return viewerLib;
}

type State = {
  viewer: any;
  bus: any;
  find: any;
  doc: pdfjs.PDFDocumentProxy | null;
  lastQuery: string;
};

function markClass(m: Mark, highlight: string | null, flash: string | null): string {
  return [
    "bw-mark",
    m.state.cited ? "cited" : m.state.read ? "read" : "",
    m.state.low ? "low" : "",
    m.type === "formula" ? "formula" : "",
    m.key === highlight ? "hover" : "",
    m.key === flash ? "flash" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

function interesting(m: Mark): boolean {
  return !!(m.state.cited || m.state.read || m.state.low || m.state.anchor);
}

export default function PdfjsViewer(props: ViewerProps) {
  const { source, marks, marksVisible, highlight, options } = props;
  const outer = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const state = useRef<State | null>(null);
  const flash = useRef<string | null>(null);
  const live = useRef(props);
  live.current = props;

  // 页 → 标注
  const byPage = useRef<Map<number, Mark[]>>(new Map());
  byPage.current = new Map();
  for (const m of marks) {
    if (m.page && m.box) {
      const list = byPage.current.get(m.page) ?? [];
      list.push(m);
      byPage.current.set(m.page, list);
    }
  }

  const drawPage = (div: HTMLElement) => {
    const n = Number(div.dataset.pageNumber);
    div.querySelector(":scope > .bw-marks")?.remove();
    const layer = document.createElement("div");
    layer.className = "bw-marks";
    const { marksVisible: visible, highlight: hl } = live.current;
    for (const m of byPage.current.get(n) ?? []) {
      if (!(visible && interesting(m)) && m.key !== hl && m.key !== flash.current) continue;
      const el = document.createElement("div");
      el.className = markClass(m, hl, flash.current);
      el.dataset.key = m.key;
      const [x, y, w, h] = m.box!;
      Object.assign(el.style, { left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` });
      layer.appendChild(el);
    }
    div.appendChild(layer);
  };
  const drawAll = () => container.current?.querySelectorAll<HTMLElement>(".page[data-page-number]").forEach(drawPage);

  // 打开文档、建阅读器
  useEffect(() => {
    let cancelled = false;
    const abort = new AbortController();
    let task: ReturnType<typeof pdfjs.getDocument> | null = null;
    (async () => {
      try {
        const [lib, data] = await Promise.all([loadViewerLib(), source.bytes()]);
        if (cancelled || !container.current) return;
        const asset = (dir: string) => new URL(`${dir}/`, source.assetBase).href;
        task = pdfjs.getDocument({
          data,
          cMapUrl: asset("cmaps"),
          cMapPacked: true,
          standardFontDataUrl: asset("standard_fonts"),
          wasmUrl: asset("wasm"),
          iccUrl: asset("iccs"),
        });
        const doc = await task.promise;
        if (cancelled) return;
        const bus = new lib.EventBus();
        const link = new lib.PDFLinkService({ eventBus: bus, externalLinkTarget: lib.LinkTarget.BLANK });
        const find = new lib.PDFFindController({ eventBus: bus, linkService: link });
        const viewer = new lib.PDFViewer({
          container: container.current,
          eventBus: bus,
          linkService: link,
          findController: find,
          removePageBorders: true,
          annotationMode: pdfjs.AnnotationMode.ENABLE,
          annotationEditorMode: pdfjs.AnnotationEditorType.DISABLE,
          abortSignal: abort.signal,
        });
        link.setViewer(viewer);
        state.current = { viewer, bus, find, doc, lastQuery: "" };
        bus.on("pagesinit", () => {
          applyOptions();
          drawAll();
          const anchor = live.current.marks.find((m) => m.state.anchor);
          if (anchor) window.setTimeout(() => scrollTo(anchor.key), 50);
        });
        bus.on("pagerendered", ({ source: pageView }: any) => pageView?.div && drawPage(pageView.div));
        bus.on("pagechanging", ({ pageNumber }: any) => {
          const unit = live.current.source.units.find((u) => u.page === pageNumber);
          if (unit) live.current.onLocation?.(unit.unit);
        });
        bus.on("scalechanging", ({ scale }: any) => live.current.onZoom?.(Math.round(scale * 100)));
        viewer.setDocument(doc);
        link.setDocument(doc, null);
        find.setDocument?.(doc);
        live.current.onReady({ scrollTo, find: runFind, zoom, goToPage: (n) => (viewer.currentPageNumber = n) });
        const outline = await doc.getOutline().catch(() => null);
        if (!cancelled && outline?.length) {
          const items: OutlineItem[] = [];
          const walk = (list: any[], level: number) => {
            for (const it of list) {
              items.push({ title: it.title, level, go: () => it.dest && link.goToDestination(it.dest) });
              if (it.items?.length) walk(it.items, level + 1);
            }
          };
          walk(outline, 0);
          live.current.onOutline?.(items);
        }
      } catch (e: any) {
        if (!cancelled) live.current.onError?.(String(e?.message ?? e));
      }
    })();
    return () => {
      cancelled = true;
      abort.abort();
      state.current?.viewer?.cleanup?.();
      void task?.destroy(); // 连同打开的文档一起销毁
      state.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.id, source.bytes]);

  const applyOptions = () => {
    const s = state.current;
    if (!s) return;
    const o = live.current.options;
    s.viewer.scrollMode = o.scroll === "page" ? 3 : 0; // ScrollMode.PAGE / VERTICAL
    s.viewer.spreadMode = o.spread ? 1 : 0; // SpreadMode.ODD / NONE
    s.viewer.currentScaleValue = /^\d+$/.test(o.zoom) ? String(Number(o.zoom) / 100) : o.zoom || "page-width";
  };
  useEffect(applyOptions, [options.scroll, options.spread, options.zoom]);
  // 容器宽度变化（切换对照视图、收起侧栏、窗口缩放）后，按"适合宽度 / 整页"重新计算缩放
  useEffect(() => {
    const el = container.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let last = el.clientWidth;
    const ro = new ResizeObserver(() => {
      const s = state.current;
      if (!s || Math.abs(el.clientWidth - last) < 4) return;
      last = el.clientWidth;
      const value = s.viewer.currentScaleValue;
      if (["page-width", "page-fit", "auto"].includes(value)) s.viewer.currentScaleValue = value;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(drawAll, [marks, marksVisible, highlight]);

  function scrollTo(key: string) {
    const s = state.current;
    const m = live.current.marks.find((x) => x.key === key);
    if (!s || !m?.page) return;
    s.viewer.currentPageNumber = m.page;
    window.setTimeout(() => {
      const view = s.viewer.getPageView(m.page! - 1);
      const div: HTMLElement | undefined = view?.div;
      const box = container.current;
      if (div && box && m.box) box.scrollTop = div.offsetTop + m.box[1] * div.clientHeight - box.clientHeight / 3;
      flash.current = key;
      drawAll();
      window.setTimeout(() => {
        if (flash.current === key) flash.current = null;
        drawAll();
      }, 2400);
    }, 30);
  }

  function runFind(query: string, previous = false) {
    const s = state.current;
    if (!s) return;
    s.bus.dispatch("find", {
      source: null,
      type: query === s.lastQuery ? "again" : "",
      query,
      caseSensitive: false,
      entireWord: false,
      highlightAll: true,
      findPrevious: previous,
      matchDiacritics: false,
    });
    s.lastQuery = query;
  }

  function zoom(z: string) {
    const s = state.current;
    if (!s) return;
    if (z === "in") s.viewer.increaseScale();
    else if (z === "out") s.viewer.decreaseScale();
    else s.viewer.currentScaleValue = /^\d+$/.test(z) ? String(Number(z) / 100) : z;
  }

  // 按坐标找鼠标下的块（同一点有几个框时取最小的）
  const hit = (e: React.MouseEvent): string | null => {
    const page = (e.target as HTMLElement).closest(".page[data-page-number]") as HTMLElement | null;
    if (!page) return null;
    const rect = page.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    let best: string | null = null;
    let area = Infinity;
    for (const m of byPage.current.get(Number(page.dataset.pageNumber)) ?? []) {
      const [bx, by, bw, bh] = m.box!;
      if (x >= bx - 0.004 && x <= bx + bw + 0.004 && y >= by - 0.004 && y <= by + bh + 0.004 && bw * bh < area) {
        best = m.key;
        area = bw * bh;
      }
    }
    return best;
  };
  const hovered = useRef<string | null>(null);

  return (
    <div ref={outer} className={`bw-pdfjs${options.invertDark ? " invert-dark" : ""}`}>
      <div
        ref={container}
        className="bw-pdfjs-container"
        onMouseMove={(e) => {
          if (!props.onHover) return;
          const k = hit(e);
          if (k !== hovered.current) {
            hovered.current = k;
            props.onHover(k);
          }
        }}
        onMouseLeave={() => {
          hovered.current = null;
          props.onHover?.(null);
        }}
        onClick={(e) => {
          if ((e.target as HTMLElement).closest("a")) return; // 文内链接
          if (String(window.getSelection() ?? "").trim()) return; // 正在选文字
          props.onMarkClick(hit(e));
        }}
      >
        <div className="pdfViewer" />
      </div>
    </div>
  );
}
