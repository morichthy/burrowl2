import { type MouseEvent, type ReactNode, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import Markdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { call } from "./api";
import { normalizeMath } from "./mathText";
import { EntryName } from "./entryLabels";
import { AUTHOR, FRESHNESS, KIND, LAYER, MARKS, REVIEW_STATE, SOURCE_LABEL, VALIDITY } from "./labels";
import katex from "katex";
import "katex/dist/katex.min.css";
import { openReader } from "./reader/open";
import { href } from "./router";
import { Icon } from "./shell/icons";
import { toast } from "./shell/toast";

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

// 页面标题区：页名、一句说明（这页是什么、有什么边界）、本页的操作
export function PageHead({ title, note, lede, actions }: { title: ReactNode; note?: ReactNode; lede?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>
          {title}
          {note != null && <span className="title-note">{note}</span>}
        </h1>
        {lede && <p className="lede">{lede}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}

// 空状态：一个图标加一句话；compact 用在卡片里
export function Empty({ children, icon = "inbox", compact }: { children: ReactNode; icon?: string; compact?: boolean }) {
  return (
    <div className={`empty${compact ? " compact" : ""}`}>
      <span className="empty-art"><Icon name={icon} /></span>
      <p>{children}</p>
    </div>
  );
}

// 加载中的占位：几条灰色的块（列表）或几行线（正文）
export function Loading({ rows = 4, lines }: { rows?: number; lines?: boolean }) {
  return (
    <div className={`skeleton${lines ? " lines" : ""}`} role="status" aria-label="正在加载">
      {Array.from({ length: rows }, (_, i) => <i key={i} />)}
    </div>
  );
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

// 坐标（设计稿 10 D-12、D-25）：地位 → 类型 → 现状 → 说明。地位是一个组合标签（综合程度 × 依据来源），
// 类型一个标签；现状只在不是"当前有效"、有复核或有现状标记时显示；说明（作者、原作者、说明标记）用小号字。
// 标记的出处（via）悬停可见；full 时在下面列出全部出处，可点开核对。
const SEVERITY_TONE: Record<string, string> = { warn: "warn", info: "muted" };

export function standingLabel(c: any): string {
  const head = LAYER[c.layer] ?? c.layer ?? "";
  const sources: string[] = c.sources ?? [];
  return sources.length ? `${head} · ${sources.map((s) => SOURCE_LABEL[s] ?? s).join(" + ")}` : head;
}

export function markText(m: any): string {
  if (m.mark === "local_roots") return `本地依据来自 ${m.count ?? m.via?.length ?? 0} 个独立来源`;
  const label = MARKS[m.mark]?.label ?? m.mark;
  const n = m.count ?? m.via?.length ?? 0;
  return n > 1 ? `${label}（${n} 处）` : label;
}

function markTitle(m: any): string | undefined {
  const via: any[] = m.via ?? [];
  const rule = MARKS[m.mark]?.rule;
  const lines = via.map((v) => `${v.end ?? ""}${v.detail ? `：${v.detail}` : ""}`).filter(Boolean);
  return [rule, ...lines].filter(Boolean).join("\n") || undefined;
}

export function Coordinates({ c, full = false, hideStanding = false }: { c: any; full?: boolean; hideStanding?: boolean }) {
  if (!c) return null;
  const state = c.state ?? {};
  const notes = c.notes ?? {};
  const validity = state.validity ?? "current";
  const review = state.review ?? "none";
  const stateMarks: any[] = state.marks ?? [];
  const noteMarks: any[] = notes.marks ?? [];
  const reviewTone = review === "human_confirmed" ? "good" : review === "human_rejected" || review === "ai_flagged" ? "bad" : "warn";
  const allMarks = [...stateMarks, ...noteMarks].filter((m) => m.via?.length);
  return (
    <span className="coords">
      <span className="tags">
        {!hideStanding && c.layer && <span className={`tag layer-${c.layer} standing`} title="地位：综合程度 × 依据来源">{standingLabel(c)}</span>}
        {c.kind && <span className="tag kind">{KIND[c.kind] ?? c.kind}</span>}
        {validity !== "current" && <span className={`tag ${validity === "replaced" ? "bad" : "muted"}`}>{VALIDITY[validity] ?? validity}</span>}
        {review !== "none" && <span className={`tag ${reviewTone}`}>{REVIEW_STATE[review] ?? review}</span>}
        {stateMarks.map((m, i) => (
          <span key={`s${i}`} className={`tag ${m.mark === "corroborated" ? "good" : SEVERITY_TONE[MARKS[m.mark]?.severity] ?? "muted"}`} title={markTitle(m)}>
            {markText(m)}
          </span>
        ))}
        {(notes.author || notes.quoted || noteMarks.length > 0) && (
          <span className="coord-notes">
            {notes.author && <span className="note">{AUTHOR[notes.author] ?? notes.author}写</span>}
            {notes.quoted && <span className="note">转述 · 原作者 {notes.quoted}</span>}
            {noteMarks.map((m, i) => (
              <span key={`n${i}`} className={`note ${MARKS[m.mark]?.severity === "warn" ? "warn" : ""}`} title={markTitle(m)}>
                {markText(m)}
              </span>
            ))}
          </span>
        )}
      </span>
      {full && allMarks.length > 0 && (
        <ul className="mark-via plain small-text">
          {allMarks.map((m, i) => (
            <li key={i}>
              <strong>{MARKS[m.mark]?.label ?? m.mark}</strong>：
              {m.via.map((v: any, j: number) => (
                <span key={j}>
                  {" "}
                  {v.end && (v.detail === "已删除" ? <span className="mono">{v.end}</span> : <IdLink id={v.end} />)}
                  {v.detail && <span className="muted">（{v.detail}）</span>}
                  {v.current && <> → <IdLink id={v.current}>当前版</IdLink></>}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}

// 正文：Markdown（标题、列表、表格、代码等）；$…$ 与 $$…$$ 用 KaTeX 显示（设计稿 03 D-19）。判断、框架页、事实记录的正文都走这里。
// [[ID]] 显示为上标编号（设计稿 09 D-14）：同一条目在一篇正文里共用一个编号；悬停显示条目名与地位，点击跳到正文底部的
// "引用"列表（完整条目名、链接，原件段落另有"阅读"入口）。[[ID|文字]] 保留作者写的文字，后面跟上标。
const REF = /\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/g;
const REF_SCHEME = "bwref:";

function RefLink({ refId, name }: { refId: string; name?: string }) {
  const [base, anchor] = refId.split("#");
  return (
    <span>
      <IdLink id={refId} name={name} />
      {base.startsWith("art_") && (
        <button type="button" className="link reader-link" title="在阅读模式中打开" onClick={() => openReader(base, anchor)}>
          ⛶
        </button>
      )}
    </span>
  );
}

// 悬停卡片：条目名、ID，第一次悬停时取地位坐标
function RefSup({ refId, n, name, anchorId }: { refId: string; n: number; name?: string; anchorId: string }) {
  const [coords, setCoords] = useState<any>(null);
  const asked = useRef(false);
  const load = () => {
    if (asked.current) return;
    asked.current = true;
    call<any>("entry.get", { id: refId }).then((r) => setCoords(r.coordinates), () => setCoords(null));
  };
  const jump = (e: MouseEvent) => {
    e.preventDefault();
    document.getElementById(anchorId)?.scrollIntoView({ block: "nearest" });
  };
  return (
    <>
      {name && <span className="ref-alias">{name}</span>}
      <sup className="ref-sup" onMouseEnter={load} onFocus={load}>
        <a href={href("entry", refId)} onClick={jump} aria-label={`引用 ${n}`}>
          {n}
        </a>
        <span className="ref-card" role="tooltip">
          <span className="ref-card-name">
            <EntryName id={refId} />
          </span>
          <span className="mono muted small">{refId}</span>
          {coords && <Coordinates c={coords} />}
        </span>
      </sup>
    </>
  );
}

// [[ID|名]] 先换成内部链接再交给 Markdown：这样标题、列表、表格里的引用也能用
function refsToLinks(text: string): { source: string; refs: string[] } {
  const refs: string[] = [];
  const source = text.replace(REF, (_all, id: string, name?: string) => {
    if (!refs.includes(id)) refs.push(id);
    return `[ref](${REF_SCHEME}${encodeURIComponent(id)}~${encodeURIComponent(name ?? "")})`;
  });
  return { source, refs };
}

export function RefText({ text }: { text: string }) {
  const { source, refs } = useMemo(() => refsToLinks(normalizeMath(text)), [text]);
  const uid = useId().replace(/:/g, "");
  const components = useMemo<Components>(() => ({
    a({ href: target, children, node: _node, ...rest }) {
      if (target?.startsWith(REF_SCHEME)) {
        const [id, name] = target.slice(REF_SCHEME.length).split("~").map(decodeURIComponent);
        const n = refs.indexOf(id) + 1;
        return <RefSup refId={id} n={n} name={name || undefined} anchorId={`${uid}-ref-${n}`} />;
      }
      return <a href={target} target="_blank" rel="noreferrer noopener" {...rest}>{children}</a>;
    },
  }), [refs, uid]);
  return (
    <div className="body">
      <Markdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={components} urlTransform={(url) => url}>
        {source}
      </Markdown>
      {refs.length > 0 && (
        <ol className="ref-list" aria-label="引用">
          {refs.map((id, i) => (
            <li key={id} id={`${uid}-ref-${i + 1}`}>
              <RefLink refId={id} />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// 一条 LaTeX 公式（公式块的 LaTeX 补充，设计稿 03 D-17）；写错时显示原文
export function TeX({ tex, display = true }: { tex: string; display?: boolean }) {
  try {
    return <span className={display ? "math-display" : "math-inline"} dangerouslySetInnerHTML={{ __html: katex.renderToString(tex, { displayMode: display, throwOnError: true, output: "html" }) }} />;
  } catch {
    return <code>{tex}</code>;
  }
}

export function IdLink({ id, name, children }: { id: string; name?: string; children?: ReactNode }) {
  return (
    <a href={href("entry", id)} title={id}>
      {children ?? <EntryName id={id} name={name} />}
    </a>
  );
}

// 一个引用（带版本与段落）现在的状况（后端 CoordinateService.ref_status）
export type ReferenceStatus = {
  missing?: boolean;
  anchor_missing?: boolean;
  validity?: string;
  status_note?: string;
  current_ref?: string | null;
};

export function referenceWarnings(status?: ReferenceStatus): string[] {
  if (!status) return [];
  return [
    status.missing && "条目已不可用",
    status.anchor_missing && "所引段落已不可用",
    status.validity && status.validity !== "current" && `所引版本${VALIDITY[status.validity] ?? status.validity}`,
    status.current_ref && "所引不是当前版",
  ].filter((label): label is string => typeof label === "string");
}

// 原引用保留原 ID、版本和段落。当前版作为单独的跳转入口，避免把旧锚点套到新版上。
export function ReferenceWarnings({ status }: { status?: ReferenceStatus }) {
  return (
    <>
      {referenceWarnings(status).map((label) => <Tag key={label} tone="warn">{label}</Tag>)}
      {status?.current_ref && <> <IdLink id={status.current_ref}>查看当前版</IdLink></>}
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
  return error ? (
    <div className="error" role="alert">
      <Icon name="alert" />
      <span>{error}</span>
    </div>
  ) : null;
}

// 一个带"执行中"状态和错误显示的按钮；done 是成功后右下角的轻提示（不写就不提示）
export function Action({ label, run, className, disabled, done, title }: { label: string; run: () => Promise<unknown>; className?: string; disabled?: boolean; done?: string; title?: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="action">
      <button
        type="button"
        className={className}
        title={title}
        disabled={busy || disabled}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await run();
            if (done) toast(done);
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
