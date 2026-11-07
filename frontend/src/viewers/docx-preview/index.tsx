// docx-preview 阅读器（设计稿 03 D-09）：在浏览器里把 Word 文档排成 HTML，连续展开（不分页）。
// 标注方式 text：渲染出的段落与表格按文字依次对应到抽取的版式块（设计稿 02 D-08 实现修订），对上的元素加标记。
import { useEffect, useRef } from "react";
import type { Mark, ViewerProps } from "../../reader/contract";
import "./docx.css";

const norm = (s: string) => s.replace(/\s+/g, "").slice(0, 40);

export default function DocxPreviewViewer(props: ViewerProps) {
  const { source, marks, marksVisible, highlight } = props;
  const host = useRef<HTMLDivElement>(null);
  const style = useRef<HTMLDivElement>(null);
  const byKey = useRef(new Map<string, HTMLElement>());
  const live = useRef(props);
  live.current = props;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { renderAsync } = await import("docx-preview");
        const blob = new Blob([await source.bytes()]);
        if (cancelled || !host.current || !style.current) return;
        await renderAsync(blob, host.current, style.current, { inWrapper: true, breakPages: false, renderComments: false, renderChanges: false });
        if (cancelled || !host.current) return;
        const elements = Array.from(host.current.querySelectorAll("article > p, article > table, article > div > p, article h1, article h2, article h3")) as HTMLElement[];
        const map = new Map<string, HTMLElement>();
        let cursor = 0;
        const ordered = [...live.current.marks].sort((a, b) => a.block - b.block);
        for (const m of ordered) {
          const key = norm(m.text);
          if (!key) continue;
          for (let j = cursor; j < elements.length; j++) {
            if (norm(elements[j].textContent ?? "").startsWith(key.slice(0, 20))) {
              elements[j].dataset.key = m.key;
              map.set(m.key, elements[j]);
              cursor = j + 1;
              break;
            }
          }
        }
        byKey.current = map;
        paint();
        live.current.onReady({ scrollTo });
        const anchor = live.current.marks.find((m) => m.state.anchor);
        if (anchor) scrollTo(anchor.key);
      } catch (e) {
        if (!cancelled) live.current.onError?.(String((e as Error)?.message ?? e));
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.id]);

  const paint = () => {
    const { marks: list, marksVisible: visible, highlight: hl } = live.current;
    const state = new Map<string, Mark>(list.map((m) => [m.key, m]));
    for (const [key, el] of byKey.current) {
      const m = state.get(key);
      el.classList.toggle("bw-cited", !!(visible && m?.state.cited));
      el.classList.toggle("bw-read", !!(visible && !m?.state.cited && m?.state.read));
      el.classList.toggle("bw-low", !!(visible && m?.state.low));
      el.classList.toggle("bw-hover", key === hl);
    }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(paint, [marks, marksVisible, highlight]);

  function scrollTo(key: string) {
    const el = byKey.current.get(key);
    if (!el) return;
    el.scrollIntoView({ block: "center" });
    el.classList.add("bw-flash");
    window.setTimeout(() => el.classList.remove("bw-flash"), 2400);
  }

  return (
    <div className="bw-docx">
      <div ref={style} />
      <div
        ref={host}
        onClick={(e) => {
          if (String(window.getSelection() ?? "").trim()) return;
          const el = (e.target as HTMLElement).closest("[data-key]") as HTMLElement | null;
          props.onMarkClick(el?.dataset.key ?? null);
        }}
        onMouseOver={(e) => props.onHover?.(((e.target as HTMLElement).closest("[data-key]") as HTMLElement | null)?.dataset.key ?? null)}
      />
    </div>
  );
}
