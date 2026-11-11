// 哈希路由：#/页面/参数?筛选。页面可以后退、可以收藏和互相链接（沿用旧版工作台的做法）。
// "?" 之后是本页的筛选条件（如 #/entries?kind=artifact&status=retired）：刷新、后退、把网址发给别人都不丢。
import { useCallback, useEffect, useRef, useState } from "react";

function splitHash(hash: string): [string, string] {
  const raw = hash.replace(/^#\/?/, "");
  const at = raw.indexOf("?");
  return at < 0 ? [raw, ""] : [raw.slice(0, at), raw.slice(at + 1)];
}

export function parseRoute(hash: string): string[] {
  return splitHash(hash)[0]
    .split("/")
    .filter(Boolean)
    .map(decodeURIComponent);
}

export function parseQuery(hash: string): Record<string, string> {
  return Object.fromEntries(new URLSearchParams(splitHash(hash)[1]));
}

export function useRoute(): string[] {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function href(...parts: string[]): string {
  return "#/" + parts.filter(Boolean).map(encodeURIComponent).join("/");
}

// 带筛选条件的链接：空值不写进网址
export function hrefWith(page: string, query: Record<string, string | null | undefined>): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v) params.set(k, v);
  const qs = params.toString();
  return href(page) + (qs ? `?${qs}` : "");
}

export function go(...parts: string[]): void {
  window.location.hash = href(...parts);
}

// 列表页最后一次的网址（含筛选），本页面会话内有效：从条目详情"回到列表"时用，筛选不丢
const LAST = "burrowl-last:";
export function lastHref(page: string): string {
  try {
    return sessionStorage.getItem(LAST + page) ?? href(page);
  } catch {
    return href(page);
  }
}

// 把筛选条件放在网址里的页面状态。值都是字符串：多选用逗号连接（见 list / unlist），开关用 "1" / ""。
// 与默认值相同的不写进网址；改动用 replaceState，不产生多余的后退步骤。
export function useUrlState<T extends Record<string, string>>(defaults: T): [T, (patch: Partial<T>) => void] {
  const base = useRef(defaults);
  const read = useCallback((): T => {
    const query = parseQuery(window.location.hash);
    const next = { ...base.current };
    for (const key of Object.keys(next)) if (key in query) (next as Record<string, string>)[key] = query[key];
    return next;
  }, []);
  const [state, setState] = useState<T>(read);
  // 网址被别处改了（点了导航里同一页的链接、手改网址、后退）：重新读
  useEffect(() => {
    const onChange = () => setState(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, [read]);
  const patch = useCallback((change: Partial<T>) => {
    setState((before) => {
      const next = { ...before, ...change };
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(next)) if (value !== base.current[key]) params.set(key, value);
      const qs = params.toString();
      const path = splitHash(window.location.hash)[0];
      const hash = `#/${path}${qs ? `?${qs}` : ""}`;
      if (hash !== window.location.hash) {
        window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}${hash}`);
      }
      try {
        sessionStorage.setItem(LAST + (parseRoute(hash)[0] ?? ""), hash);
      } catch {
        // 存储不可用时只是不记住上一次的筛选
      }
      return next;
    });
  }, []);
  return [state, patch];
}

export const list = (value: string): string[] => (value ? value.split(",").filter(Boolean) : []);
export const unlist = (values: string[]): string => values.join(",");

// "交给 agent"：把任务文本带到 Agent 页（只在本页面会话内有效）
let pendingPrompt = "";
export function delegate(prompt: string, runId?: string): void {
  pendingPrompt = prompt;
  go("agent", ...(runId ? [runId] : []));
}
export function takePrompt(): string {
  const p = pendingPrompt;
  pendingPrompt = "";
  return p;
}
