// 阅读模式的个人偏好（设计稿 03 D-14 ②）：只存在这台浏览器的 localStorage，不进数据目录。
// 每种格式默认用哪个阅读器是数据目录设置（settings.get / settings.set 的 viewer.*），不在这里。
import { useEffect, useState } from "react";
import type { ViewerOptions } from "./contract";

export type ReaderView = "original" | "compare" | "text";
export type SideTab = "marks" | "citations" | "outline";

export type ReaderPrefs = ViewerOptions & {
  view: ReaderView;
  marks: boolean; // 默认显示标注
  sidebar: boolean; // 侧栏默认展开
  sideTab: SideTab;
  fullscreen: boolean; // 进入阅读模式时请求浏览器全屏
};

export const DEFAULT_PREFS: ReaderPrefs = {
  view: "original",
  scroll: "continuous",
  zoom: "page-width",
  spread: false,
  invertDark: false,
  marks: true,
  sidebar: true,
  sideTab: "marks",
  fullscreen: true,
};

const KEY = "burrowl-reader-prefs";

export function loadPrefs(): ReaderPrefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function savePrefs(prefs: ReaderPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // 浏览器不允许本地存储时只在本页有效
  }
}

export function usePrefs(): [ReaderPrefs, (patch: Partial<ReaderPrefs>) => void] {
  const [prefs, setPrefs] = useState(loadPrefs);
  useEffect(() => savePrefs(prefs), [prefs]);
  return [prefs, (patch) => setPrefs((p) => ({ ...p, ...patch }))];
}
