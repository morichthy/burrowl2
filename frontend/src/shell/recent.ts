// 最近打开的条目：只记 ID（名称每次从后端取），存在浏览器本地，按数据目录分开。用于快速跳转里的"最近打开"。
import { currentDb } from "../api";

const LIMIT = 12;
const key = () => `burrowl-recent:${currentDb()}`;

export function loadRecent(): string[] {
  try {
    const saved = JSON.parse(localStorage.getItem(key()) ?? "[]");
    return Array.isArray(saved) ? saved.filter((x) => typeof x === "string").slice(0, LIMIT) : [];
  } catch {
    return [];
  }
}

export function pushRecent(id: string): void {
  // 段落、版本后缀不算另一条
  const base = id.split("#")[0].split("@")[0];
  if (!base) return;
  try {
    localStorage.setItem(key(), JSON.stringify([base, ...loadRecent().filter((x) => x !== base)].slice(0, LIMIT)));
  } catch {
    // 存储不可用时只是没有"最近打开"
  }
}
