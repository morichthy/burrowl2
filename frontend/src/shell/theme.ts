// 主题：跟随系统 / 浅色 / 深色。选择记在浏览器本地；"跟随系统"时不写 data-theme，由样式表里的媒体查询决定。
import { useCallback, useSyncExternalStore } from "react";

export type Theme = "system" | "light" | "dark";
export const THEME_LABEL: Record<Theme, string> = { system: "跟随系统", light: "浅色", dark: "深色" };
const KEY = "burrowl-theme";

export function loadTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

export function saveTheme(theme: Theme): void {
  applyTheme(theme);
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // 存储不可用时只在本次打开期间生效
  }
}

export const nextTheme = (theme: Theme): Theme => (theme === "system" ? "light" : theme === "light" ? "dark" : "system");

// 主题是全局的：顶栏按钮、快捷键 t、设置页的"界面"改的是同一份，任何一处改了其余都跟着变
const listeners = new Set<() => void>();
let current: Theme | null = null;
const read = (): Theme => (current ??= loadTheme());

export function useTheme(): [Theme, (t: Theme) => void] {
  const theme = useSyncExternalStore((l) => (listeners.add(l), () => listeners.delete(l)), read);
  const set = useCallback((t: Theme) => {
    saveTheme(t);
    current = t;
    for (const l of listeners) l();
  }, []);
  return [theme, set];
}