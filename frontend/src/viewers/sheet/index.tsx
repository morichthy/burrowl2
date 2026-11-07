// 表格阅读器（设计稿 03 D-11）：用 SheetJS CE 在浏览器里解析 Excel / CSV / TSV，显示为只读表格。
// 工作表标签、列标（A、B…）与行号、冻结的表头行、列宽、合并单元格；大表只渲染看得到的行（虚拟滚动）。
// 标注方式 text：Excel 的抽取块带单元格范围（如 A1:F20），被引用、被读过的范围加底色，点单元格选中它所在的块。
import { useEffect, useMemo, useRef, useState } from "react";
import * as XLSX from "xlsx";
import type { Mark, ViewerProps } from "../../reader/contract";
import "./sheet.css";

const ROW_H = 24;
const OVERSCAN = 20;
const MAX_COLS = 200;

type Range = { s: { r: number; c: number }; e: { r: number; c: number } };

function decode(ref: string): Range | null {
  try {
    return XLSX.utils.decode_range(ref) as Range;
  } catch {
    return null;
  }
}

function within(r: number, c: number, range: Range): boolean {
  return r >= range.s.r && r <= range.e.r && c >= range.s.c && c <= range.e.c;
}

export default function SheetViewer(props: ViewerProps) {
  const { source, marks, marksVisible, highlight } = props;
  const [book, setBook] = useState<XLSX.WorkBook | null>(null);
  const [index, setIndex] = useState(0);
  const [top, setTop] = useState(0);
  const [height, setHeight] = useState(600);
  const [flash, setFlash] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const live = useRef(props);
  live.current = props;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await source.bytes();
        const tsv = source.suffix === ".tsv";
        const wb =
          source.format === "text"
            ? XLSX.read(new TextDecoder("utf-8").decode(data), { type: "string", raw: true, ...(tsv ? { FS: "\t" } : {}) })
            : XLSX.read(data, { type: "array", cellDates: true, cellStyles: false });
        if (!cancelled) setBook(wb);
      } catch (e) {
        if (!cancelled) live.current.onError?.(String((e as Error)?.message ?? e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source.id, source.bytes, source.format, source.suffix]);

  const sheetName = book?.SheetNames[index];
  const sheet = sheetName ? book!.Sheets[sheetName] : null;
  const unit = `s${index + 1}`;
  const dims = useMemo(() => (sheet?.["!ref"] ? decode(sheet["!ref"]) : null), [sheet]);
  const rows = dims ? dims.e.r + 1 : 0;
  const cols = dims ? Math.min(dims.e.c + 1, MAX_COLS) : 0;
  const merges = useMemo(() => ((sheet?.["!merges"] ?? []) as Range[]), [sheet]);
  const widths = useMemo(() => {
    const info = (sheet?.["!cols"] ?? []) as { wpx?: number; wch?: number; hidden?: boolean }[];
    return Array.from({ length: cols }, (_, c) => {
      const w = info[c];
      if (w?.hidden) return 0;
      return Math.max(40, Math.min(480, w?.wpx ?? (w?.wch ? w.wch * 7.5 + 10 : 96)));
    });
  }, [sheet, cols]);
  // 只有 Excel 的抽取块带范围；CSV 的段落是文本段，不在表格上标
  const ranges = useMemo(
    () => marks.filter((m) => m.unit === unit && m.range).map((m) => ({ m, range: decode(m.range!) })).filter((x): x is { m: Mark; range: Range } => !!x.range),
    [marks, unit],
  );

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const update = () => setHeight(el.clientHeight);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [book]);
  useEffect(() => {
    if (book) live.current.onLocation?.(unit);
  }, [book, unit]);

  // 句柄：滚到某个标注所在的工作表与行
  useEffect(() => {
    if (!book) return;
    live.current.onReady({
      scrollTo: (key) => {
        const m = live.current.marks.find((x) => x.key === key);
        const range = m?.range ? decode(m.range) : null;
        const n = m ? Number(m.unit.replace(/^s/, "")) - 1 : -1;
        if (!m || !range || n < 0 || n >= book.SheetNames.length) return;
        setIndex(n);
        window.setTimeout(() => {
          if (box.current) box.current.scrollTop = Math.max(0, range.s.r * ROW_H - 3 * ROW_H);
        }, 30);
        setFlash(key);
        window.setTimeout(() => setFlash((f) => (f === key ? null : f)), 2400);
      },
    });
  }, [book]);
  useEffect(() => {
    const anchor = marks.find((m) => m.state.anchor && m.range);
    if (!book || !anchor) return;
    const n = Number(anchor.unit.replace(/^s/, "")) - 1;
    const range = decode(anchor.range!);
    if (n >= 0 && range) {
      setIndex(n);
      window.setTimeout(() => box.current && (box.current.scrollTop = Math.max(0, range.s.r * ROW_H - 3 * ROW_H)), 30);
      setFlash(anchor.key);
    }
    // 只在打开时跳一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [book]);

  if (!book) return <div className="bw-sheet loading">正在打开表格…</div>;

  const first = Math.max(0, Math.floor(top / ROW_H) - OVERSCAN);
  const last = Math.min(rows, Math.ceil((top + height) / ROW_H) + OVERSCAN);
  const coveredBy = (r: number, c: number) => merges.find((m) => within(r, c, m));
  const markAt = (r: number, c: number) => {
    let best: { m: Mark; range: Range } | null = null;
    for (const x of ranges) if (within(r, c, x.range) && (!best || (x.range.e.r - x.range.s.r) < (best.range.e.r - best.range.s.r))) best = x;
    return best?.m ?? null;
  };
  const body = [];
  for (let r = first; r < last; r++) {
    const cells = [];
    for (let c = 0; c < cols; c++) {
      if (!widths[c]) continue;
      const merge = coveredBy(r, c);
      if (merge && (merge.s.r !== r || merge.s.c !== c) && !(r === first && merge.s.r < first && merge.s.c === c)) continue;
      const span = merge
        ? { rowSpan: Math.min(merge.e.r, last - 1) - Math.max(merge.s.r, first) + 1, colSpan: Math.min(merge.e.c, cols - 1) - merge.s.c + 1 }
        : {};
      const addr = XLSX.utils.encode_cell({ r: merge ? merge.s.r : r, c });
      const cell = sheet![addr] as XLSX.CellObject | undefined;
      const m = markAt(r, c);
      const cls = [
        m && marksVisible && m.state.cited ? "cited" : m && marksVisible && m.state.read ? "read" : "",
        m && marksVisible && m.state.low ? "low" : "",
        m && (m.key === highlight || m.key === flash) ? "hover" : "",
        cell?.t === "n" ? "num" : "",
      ]
        .filter(Boolean)
        .join(" ");
      cells.push(
        <td key={c} {...span} className={cls} data-key={m?.key} title={cell?.f ? `=${cell.f}` : undefined}>
          {cell ? (cell.w ?? (cell.v instanceof Date ? cell.v.toISOString().slice(0, 10) : String(cell.v ?? ""))) : ""}
        </td>,
      );
    }
    body.push(
      <tr key={r} style={{ height: ROW_H }}>
        <th className="rownum">{r + 1}</th>
        {cells}
      </tr>,
    );
  }

  return (
    <div className="bw-sheet">
      <div
        ref={box}
        className="bw-sheet-grid"
        onScroll={(e) => setTop(e.currentTarget.scrollTop)}
        onClick={(e) => {
          if (String(window.getSelection() ?? "").trim()) return;
          props.onMarkClick(((e.target as HTMLElement).closest("[data-key]") as HTMLElement | null)?.dataset.key ?? null);
        }}
        onMouseOver={(e) => props.onHover?.(((e.target as HTMLElement).closest("[data-key]") as HTMLElement | null)?.dataset.key ?? null)}
      >
        <table>
          <colgroup>
            <col style={{ width: 48 }} />
            {widths.map((w, c) => (w ? <col key={c} style={{ width: w }} /> : null))}
          </colgroup>
          <thead>
            <tr>
              <th className="corner" />
              {widths.map((w, c) => (w ? <th key={c}>{XLSX.utils.encode_col(c)}</th> : null))}
            </tr>
          </thead>
          <tbody>
            {first > 0 && (
              <tr style={{ height: first * ROW_H }}>
                <td colSpan={cols + 1} className="spacer" />
              </tr>
            )}
            {body}
            {last < rows && (
              <tr style={{ height: (rows - last) * ROW_H }}>
                <td colSpan={cols + 1} className="spacer" />
              </tr>
            )}
          </tbody>
        </table>
        {!rows && <p className="bw-sheet-empty">这个工作表是空的。</p>}
      </div>
      <div className="bw-sheet-tabs">
        {book.SheetNames.map((name, i) => (
          <button
            key={name}
            type="button"
            className={i === index ? "on" : ""}
            onClick={() => {
              setIndex(i);
              setTop(0);
              if (box.current) box.current.scrollTop = 0;
            }}
          >
            {name}
            {(book.Workbook?.Sheets?.[i]?.Hidden ?? 0) ? "（隐藏）" : ""}
          </button>
        ))}
        {dims && dims.e.c + 1 > MAX_COLS && <span className="bw-sheet-note">只显示前 {MAX_COLS} 列</span>}
      </div>
    </div>
  );
}
