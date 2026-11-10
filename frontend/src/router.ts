// 哈希路由：#/页面/参数。页面可以后退、可以收藏和互相链接（沿用旧版工作台的做法）。
import { useEffect, useState } from "react";

export function parseRoute(hash: string): string[] {
  return hash
    .replace(/^#\/?/, "")
    .split("/")
    .filter(Boolean)
    .map(decodeURIComponent);
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

export function go(...parts: string[]): void {
  window.location.hash = href(...parts);
}

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
