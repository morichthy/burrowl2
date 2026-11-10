import { type ReactNode, useCallback, useEffect, useState } from "react";
import { EntryName } from "./entryLabels";
import { FRESHNESS, LAPSE_REASON, LAYER, REVIEW, SOURCE, TIER } from "./labels";
import katex from "katex";
import "katex/dist/katex.min.css";
import { openReader } from "./reader/open";
import { href } from "./router";

/* eslint-disable @typescript-eslint/no-explicit-any */

// 通用的异步数据加载：返回 [数据, 错误, 重新加载]
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): [T | null, string | null, () => void] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setError(null);
    fn()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message ?? String(e)));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return [data, error, useCallback(() => setTick((t) => t + 1), [])];
}

// 定时刷新：AI 通过 MCP 写入时，工作台停在某页也能看到新内容；窗口回到前台时立即刷新
export function usePoll(reload: () => void, ms = 5000) {
  useEffect(() => {
    const timer = window.setInterval(reload, ms);
    window.addEventListener("focus", reload);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", reload);
    };
  }, [reload, ms]);
}

export function Panel({ title, actions, children, className, id }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section id={id} className={`panel ${className ?? ""}`}>
      {title || actions ? (
        <header>
          <h2>{title}</h2>
          <div className="actions">{actions}</div>
        </header>
      ) : null}
      {children}
    </section>
  );
}

export function Tag({ children, tone = "muted", title }: { children: ReactNode; tone?: string; title?: string }) {
  return (
    <span className={`tag ${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Dot({ tone = "muted" }: { tone?: string }) {
  return <span className={`status-dot ${tone}`} />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

// 时间：今天 / 昨天只显示时刻，更早的显示日期；悬停看完整时间
export function Time({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  const d = new Date(value);
  return (
    <time className="time" title={d.toLocaleString("zh-CN")}>
      {dayLabel(d)} {d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
    </time>
  );
}

export function dayLabel(date: Date): string {
  if (Number.isNaN(date.getTime())) return "时间未知";
  const today = new Date();
  const days = Math.round((new Date(today.toDateString()).getTime() - new Date(date.toDateString()).getTime()) / 86_400_000);
  if (days === 0) return "今天";
  if (days === 1) return "昨天";
  return date.toLocaleDateString("zh-CN", { year: today.getFullYear() === date.getFullYear() ? undefined : "numeric", month: "long", day: "numeric" });
}

// 筛选条：一排可点选的标签（沿用旧版 chips）。multi=true 可多选；空选表示"全部"
export function Chips<T extends string>({
  options,
  value,
  onChange,
  multi = false,
  counts,
  all = "全部",
  label,
  disabled = {},
}: {
  options: [T, string][];
  value: T[];
  onChange: (v: T[]) => void;
  multi?: boolean;
  counts?: Record<string, number>;
  all?: string | null;
  label?: string;
  disabled?: Partial<Record<T, string>>; // 不可选的项及原因（悬停显示）
}) {
  const toggle = (key: T) => {
    if (disabled[key]) return;
    if (!multi) return onChange(value.includes(key) && all ? [] : [key]);
    onChange(value.includes(key) ? value.filter((v) => v !== key) : [...value, key]);
  };
  return (
    <div className="chips" role="group" aria-label={label}>
      {all !== null && (
        <button type="button" className={value.length === 0 ? "on" : ""} onClick={() => onChange([])}>
          {all}
        </button>
      )}
      {options.map(([key, text]) => (
        <button type="button" key={key} className={value.includes(key) ? "on" : ""} onClick={() => toggle(key)} disabled={!!disabled[key]} title={disabled[key]}>
          {text}
          {counts && <span className="count">{counts[key] ?? 0}</span>}
        </button>
      ))}
    </div>
  );
}

export function FilterRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <span className="filter-label">{label}</span>
      <div>{children}</div>
    </>
  );
}

// 地位坐标：两个轴、复核状态、时效、是否被替代（草图 §11.2）
export function Coordinates({ c }: { c: any }) {
  if (!c) return null;
  const tags: [string, string][] = [];
  tags.push([`layer-${c.layer}`, LAYER[c.layer] ?? c.layer]);
  if (c.normative) tags.push(["bad", "规定"]);
  if (c.process) tags.push(["muted", "过程内容"]);
  for (const s of c.source_classes ?? []) tags.push([`src-${s}`, SOURCE[s] ?? s]);
  for (const t of c.external_tiers ?? []) tags.push(["tier", TIER[t] ?? t]);
  if (c.all_local) tags.push(["good", "全部依据为本地实证"]);
  if (c.mixed) tags.push(["warn", "混合来源"]);
  if (c.complete === false) tags.push(["warn", "依据不完整"]);
  if (c.defective) tags.push(["bad", c.layer === "original" ? "原件有缺陷" : "有缺陷"]);
  if (c.review) tags.push([c.review === "rejected" ? "bad" : c.review === "ai_generated" || c.review === "ai_reviewed" ? "warn" : "good", REVIEW[c.review] ?? c.review]);
  if (c.ai_flag) tags.push(["bad", "AI 认为有问题"]);
  if (c.freshness && c.freshness !== "valid") tags.push(["warn", FRESHNESS[c.freshness] ?? c.freshness]);
  if (c.replaced ?? c.superseded) tags.push(["bad", "已被替代"]);
  if (c.withdrawn) tags.push(["bad", "已撤回"]);
  if (c.retired) tags.push(["muted", c.replaced_by ? "已退役 · 有替代" : "已退役"]);
  if (c.hidden) tags.push(["muted", "依据全部失效 · 已隐藏"]);
  if (c.lapsed_basis?.length) tags.push(["warn", c.lapsed_basis.some((g: any) => g.reason === "deleted") ? "部分依据已删除" : "部分依据已退役"]);
  if (c.opposed) tags.push(["warn", "有反对"]);
  if (c.independent_support > 1) tags.push(["good", `独立支持 ${c.independent_support}`]);
  if (c.author_kind) tags.push(["muted", c.author_kind === "ai" ? "AI 写" : c.author_kind === "human" ? "人写" : "系统"]);
  return (
    <span className="tags">
      {tags.map(([cls, text], i) => (
        <span key={i} className={`tag ${cls}`}>
          {text}
        </span>
      ))}
    </span>
  );
}

// 正文中的 [[ID]] 渲染为可点击的链接
// 正文：[[ID|文字]] 是条目链接（原件段落另有"阅读"入口，在阅读模式中打开）；$…$ 与 $$…$$ 用 KaTeX 显示（设计稿 03 D-19）
export function RefText({ text }: { text: string }) {
  const parts = text.split(/(\[\[[^\]]+\]\])/g);
  return (
    <div className="body">
      {parts.map((p, i) => {
        const m = p.match(/^\[\[([^\]|]+)(?:\|([^\]]*))?\]\]$/);
        if (!m) return <MathText key={i} text={p} />;
        const [base, anchor] = m[1].split("#");
        return (
          <span key={i}>
            <IdLink id={m[1]} name={m[2]} />
            {base.startsWith("art_") && (
              <button type="button" className="link reader-link" title="在阅读模式中打开" onClick={() => openReader(base, anchor)}>
                ⛶
              </button>
            )}
          </span>
        );
      })}
    </div>
  );
}

// $$…$$（行间）与 $…$（行内）：开头的 $ 后、结尾的 $ 前不能是空格，避免把"$5 和 $6"当成公式
const MATH = /(\$\$[^$]+?\$\$|\$(?=\S)[^$\n]+?(?<=\S)\$)/g;

// 一条 LaTeX 公式（公式块的 LaTeX 补充，设计稿 03 D-17）；写错时显示原文
export function TeX({ tex, display = true }: { tex: string; display?: boolean }) {
  try {
    return <span className={display ? "math-display" : "math-inline"} dangerouslySetInnerHTML={{ __html: katex.renderToString(tex, { displayMode: display, throwOnError: true, output: "html" }) }} />;
  } catch {
    return <code>{tex}</code>;
  }
}

function MathText({ text }: { text: string }) {
  if (!text.includes("$")) return <span>{text}</span>;
  return (
    <>
      {text.split(MATH).map((piece, i) => {
        const display = piece.startsWith("$$") && piece.endsWith("$$") && piece.length > 4;
        const inline = !display && piece.length > 2 && piece.startsWith("$") && piece.endsWith("$") && i % 2 === 1;
        if (!display && !inline) return <span key={i}>{piece}</span>;
        const tex = display ? piece.slice(2, -2) : piece.slice(1, -1);
        try {
          return <span key={i} className={display ? "math-display" : "math-inline"} dangerouslySetInnerHTML={{ __html: katex.renderToString(tex, { displayMode: display, throwOnError: true, output: "html" }) }} />;
        } catch {
          return <span key={i}>{piece}</span>;
        }
      })}
    </>
  );
}

export function IdLink({ id, name, children }: { id: string; name?: string; children?: ReactNode }) {
  return (
    <a href={href("entry", id)} title={id}>
      {children ?? <EntryName id={id} name={name} />}
    </a>
  );
}

export type ReferenceStatus = {
  missing?: boolean;
  anchor_missing?: boolean;
  withdrawn?: boolean;
  retired?: boolean;
  defective?: boolean;
  replaced?: boolean;
  freshness?: string;
  lapse?: "hidden" | "partial";
  current_ref?: string | null;
  changed_refs?: string[];
  basis_gaps?: { ref: string; reason: string }[];
};

export function referenceWarnings(status?: ReferenceStatus): string[] {
  if (!status) return [];
  return [
    status.missing && "条目已不可用",
    status.anchor_missing && "所引段落已不可用",
    status.withdrawn && "所引版本已撤回",
    status.retired && "所引版本已退役",
    status.defective && "所引版本有缺陷",
    status.replaced && "所引版本已被替代或更正",
    status.freshness !== "valid" && status.freshness && FRESHNESS[status.freshness],
    status.lapse === "hidden" && "该条目的依据已全部失效",
    status.lapse === "partial" && "该条目的部分依据已失效",
    !!status.changed_refs?.length && "原件段落已变化，待复核",
  ].filter((label): label is string => typeof label === "string");
}

// 原引用保留原 ID 和段落。新版作为单独的跳转入口，避免把旧锚点套到新版上。
export function ReferenceWarnings({ status }: { status?: ReferenceStatus }) {
  return (
    <>
      {referenceWarnings(status).map((label) => <Tag key={label} tone="warn">{label}</Tag>)}
      {status?.current_ref && <> <IdLink id={status.current_ref}>查看当前版本</IdLink></>}
      {status?.changed_refs?.map((ref) => <span key={ref}> <IdLink id={ref} /></span>)}
      {status?.basis_gaps?.map(({ ref, reason }) => (
        <span key={ref}> {reason === "deleted" ? <span className="mono">{ref}</span> : <IdLink id={ref} />}
          （{LAPSE_REASON[reason] ?? reason}）
        </span>
      ))}
    </>
  );
}

export function PageInputNotice({ page }: { page: any }) {
  // 旧版使用的是自己的输入清单，不能套用当前版的传播状态。
  const head = page.version === page.page.head_version;
  const changed = (page.inputs as string[]).filter((ref) => referenceWarnings(page.input_statuses?.[ref]).length);
  const stale = head && ["inputs_changed", "unchecked"].includes(page.page.freshness);
  if (!changed.length && !stale) return null;
  return (
    <div className="notice">
      {changed.length > 0 && <>
        <strong>这一版有 {changed.length} 条输入需要留意</strong>
        <ul className="plain">
          {changed.map((ref) => {
            const status = page.input_statuses[ref];
            return <li key={ref}>{status.missing ? <span className="mono">{ref}</span> : <IdLink id={ref} />} <ReferenceWarnings status={status} /></li>;
          })}
        </ul>
      </>}
      {stale && page.change_reason && <div>标记原因：{page.change_reason}</div>}
      {stale && !changed.length && <div>当前未能定位到清单里的具体变化项。</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  return error ? <div className="error">{error}</div> : null;
}

// 一个带"执行中"状态和错误显示的按钮
export function Action({ label, run, className, disabled }: { label: string; run: () => Promise<unknown>; className?: string; disabled?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="action">
      <button
        type="button"
        className={className}
        disabled={busy || disabled}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await run();
          } catch (e: any) {
            setError(e.message ?? String(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "…" : label}
      </button>
      {error && <span className="error inline">{error}</span>}
    </span>
  );
}

// 按比例分段的条形图（首页计数用）
export function Bar({ parts }: { parts: [number, string][] }) {
  const total = parts.reduce((s, [n]) => s + n, 0);
  if (!total) return null;
  return (
    <div className="bar" aria-hidden="true">
      {parts.map(([n, tone], i) => (n ? <span key={i} className={tone} style={{ flexGrow: n }} /> : null))}
    </div>
  );
}
