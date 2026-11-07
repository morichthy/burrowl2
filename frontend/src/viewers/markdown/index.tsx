// 文本 / Markdown 阅读器（设计稿 03 D-12）：文本原件按原样显示（原件本身就是文字，fidelity=copy）。
// Markdown 渲染表格、公式（KaTeX，$…$ 与 $$…$$）；CSV / TSV 显示为表格；JSON 格式化；其余文本保留原样换行。
// 标注方式 text：每段（seg-n）一个元素，按段落锚点标记。
import { useEffect, useMemo, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import type { ViewerProps } from "../../reader/contract";
import "./markdown.css";

const MARKDOWN = new Set([".md", ".markdown", ""]);

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

export default function MarkdownViewer(props: ViewerProps) {
  const { source, marks, marksVisible, highlight } = props;
  const root = useRef<HTMLDivElement>(null);
  const live = useRef(props);
  live.current = props;
  const suffix = source.suffix.toLowerCase();

  const scrollTo = (key: string) => {
    const el = root.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`);
    if (!el) return;
    el.scrollIntoView({ block: "center" });
    el.classList.add("bw-flash");
    window.setTimeout(() => el.classList.remove("bw-flash"), 2400);
  };
  useEffect(() => {
    live.current.onReady({ scrollTo });
    const anchor = live.current.marks.find((m) => m.state.anchor);
    if (anchor) window.setTimeout(() => scrollTo(anchor.key), 50);
  }, [source.id]);

  const table = useMemo(() => {
    if (suffix !== ".csv" && suffix !== ".tsv") return null;
    return (source.text ?? "")
      .split(/\r?\n/)
      .filter((l) => l.trim())
      .map((l) => splitCsv(l, suffix === ".tsv" ? "\t" : ","));
  }, [source.text, suffix]);

  if (table)
    return (
      <div className="bw-md">
        <div className="bw-md-page wide">
          <table className="bw-md-table">
            <tbody>
              {table.slice(0, 5000).map((r, i) => (
                <tr key={i}>{r.map((c, j) => (i === 0 ? <th key={j}>{c}</th> : <td key={j}>{c}</td>))}</tr>
              ))}
            </tbody>
          </table>
          {table.length > 5000 && <p>只显示前 5000 行，共 {table.length} 行。</p>}
        </div>
      </div>
    );
  if (suffix === ".json") {
    let text = source.text ?? "";
    try {
      text = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      /* 不是合法 JSON 时原样显示 */
    }
    return (
      <div className="bw-md">
        <pre className="bw-md-page wide bw-md-code">{text}</pre>
      </div>
    );
  }
  const md = MARKDOWN.has(suffix);
  return (
    <div className="bw-md" ref={root}>
      <article
        className={`bw-md-page${md ? "" : " wide"}`}
        onClick={(e) => {
          if (String(window.getSelection() ?? "").trim()) return;
          props.onMarkClick(((e.target as HTMLElement).closest("[data-key]") as HTMLElement | null)?.dataset.key ?? null);
        }}
      >
        {marks.map((m) => {
          const cls = [
            "bw-seg",
            marksVisible && m.state.cited ? "bw-cited" : marksVisible && m.state.read ? "bw-read" : "",
            m.key === highlight ? "bw-hover" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <div key={m.key} data-key={m.key} className={cls} onMouseEnter={() => props.onHover?.(m.key)} onMouseLeave={() => props.onHover?.(null)}>
              {md ? (
                <Markdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                  {m.text}
                </Markdown>
              ) : (
                <pre className="bw-md-code">{m.text}</pre>
              )}
            </div>
          );
        })}
        {!marks.length && <pre className="bw-md-code">{source.text}</pre>}
      </article>
    </div>
  );
}
