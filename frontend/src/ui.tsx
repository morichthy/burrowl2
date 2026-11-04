import { useCallback, useEffect, useState } from "react";
import { FRESHNESS, LAYER, REVIEW, SOURCE, TIER } from "./labels";

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

// 地位坐标：两个轴、复核状态、时效、是否被替代（草图 §11.2）
export function Coordinates({ c }: { c: any }) {
  if (!c) return null;
  const tags: [string, string][] = [];
  tags.push([`layer-${c.layer}`, LAYER[c.layer] ?? c.layer]);
  if (c.normative) tags.push(["bad", "规定（约束/决定/指令）"]);
  for (const s of c.source_classes ?? []) tags.push([`src-${s}`, SOURCE[s] ?? s]);
  for (const t of c.external_tiers ?? []) tags.push(["tier", TIER[t] ?? t]);
  if (c.verified_by_us) tags.push(["ok", "我们验证过"]);
  if (c.mixed) tags.push(["warn", "混合来源"]);
  if (c.complete === false) tags.push(["warn", "依据不完整"]);
  if (c.defective) tags.push(["bad", "原件有缺陷"]);
  if (c.review) tags.push([c.review === "rejected" ? "bad" : c.review === "ai_generated" ? "warn" : "ok", REVIEW[c.review] ?? c.review]);
  if (c.freshness && c.freshness !== "valid") tags.push(["warn", FRESHNESS[c.freshness] ?? c.freshness]);
  if (c.superseded) tags.push(["bad", "已被替代"]);
  if (c.opposed) tags.push(["warn", "有反对"]);
  if (c.independent_support > 1) tags.push(["ok", `独立支持 ${c.independent_support}`]);
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
export function RefText({ text, open }: { text: string; open: (id: string) => void }) {
  const parts = text.split(/(\[\[[^\]]+\]\])/g);
  return (
    <div className="body">
      {parts.map((p, i) => {
        const m = p.match(/^\[\[([^\]|]+)(?:\|([^\]]*))?\]\]$/);
        if (!m) return <span key={i}>{p}</span>;
        return (
          <a key={i} href="#" onClick={(e) => (e.preventDefault(), open(m[1]))}>
            {m[2] || m[1]}
          </a>
        );
      })}
    </div>
  );
}

export function IdLink({ id, open }: { id: string; open: (id: string) => void }) {
  return (
    <a href="#" className="mono" onClick={(e) => (e.preventDefault(), open(id))}>
      {id}
    </a>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  return error ? <div className="error">{error}</div> : null;
}

// 一个带"执行中"状态和错误显示的按钮
export function Action({ label, run, className }: { label: string; run: () => Promise<unknown>; className?: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <span>
      <button
        className={className}
        disabled={busy}
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
