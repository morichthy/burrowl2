// Agent 浏览器终端的配色：统一设置项，记在这台浏览器（localStorage），设置页改了以后 Agent 页立即使用。
import { useSyncExternalStore } from "react";
import type { ITheme } from "@xterm/xterm";

type Palette = Required<Pick<ITheme, "background" | "foreground" | "cursor" | "selectionBackground">> & { ansi: string[] };

// ansi 依次是 黑 红 绿 黄 蓝 品红 青 白，再是各自的亮色；亮黑（第 9 个）常用来显示"暗淡"文字，所以每套都保证它看得清。
const PALETTES: Record<string, Palette & { label: string }> = {
  dark: {
    label: "深色（默认，高对比）", background: "#0d1117", foreground: "#e6edf3", cursor: "#58a6ff", selectionBackground: "#264f78",
    ansi: ["#484f58", "#ff7b72", "#3fb950", "#d29922", "#58a6ff", "#bc8cff", "#39c5cf", "#b1bac4", "#8b949e", "#ffa198", "#56d364", "#e3b341", "#79c0ff", "#d2a8ff", "#56d4dd", "#f0f6fc"],
  },
  classic: {
    label: "经典黑底白字", background: "#000000", foreground: "#f2f2f2", cursor: "#ffffff", selectionBackground: "#3a5f9a",
    ansi: ["#000000", "#ff5555", "#50fa7b", "#f1fa8c", "#6ea8ff", "#ff79c6", "#8be9fd", "#e6e6e6", "#a0a0a0", "#ff8888", "#7dffa0", "#ffffaa", "#9cc2ff", "#ff9fdc", "#b0f0ff", "#ffffff"],
  },
  light: {
    label: "浅色", background: "#ffffff", foreground: "#1f2328", cursor: "#0969da", selectionBackground: "#b6d7ff",
    ansi: ["#24292f", "#cf222e", "#116329", "#7d4e00", "#0550ae", "#8250df", "#1b7c83", "#6e7781", "#57606a", "#a40e26", "#1a7f37", "#633c01", "#0969da", "#6639ba", "#3192aa", "#8c959f"],
  },
  paper: {
    label: "护眼米色", background: "#f6f1e3", foreground: "#2b2b2b", cursor: "#a04000", selectionBackground: "#e0d3a8",
    ansi: ["#2b2b2b", "#b3261e", "#2e6b34", "#8a5a00", "#1f4e8c", "#7b3f98", "#1d6f6f", "#6b6558", "#5c5648", "#c4372f", "#3a8341", "#a06b00", "#2a64b3", "#9150b0", "#2a8a8a", "#8a8472"],
  },
  solarizedDark: {
    label: "Solarized 深", background: "#002b36", foreground: "#93a1a1", cursor: "#93a1a1", selectionBackground: "#0a4a5a",
    ansi: ["#073642", "#dc322f", "#859900", "#b58900", "#268bd2", "#d33682", "#2aa198", "#eee8d5", "#657b83", "#cb4b16", "#7a8f00", "#c69a00", "#4aa3e0", "#6c71c4", "#35b8ae", "#fdf6e3"],
  },
  solarizedLight: {
    label: "Solarized 浅", background: "#fdf6e3", foreground: "#586e75", cursor: "#586e75", selectionBackground: "#e6dcb8",
    ansi: ["#073642", "#dc322f", "#738a05", "#a57705", "#268bd2", "#d33682", "#2aa198", "#8a8f87", "#586e75", "#cb4b16", "#657b83", "#7a5a00", "#1f6fb0", "#6c71c4", "#1f8a82", "#93a1a1"],
  },
  dracula: {
    label: "Dracula", background: "#282a36", foreground: "#f8f8f2", cursor: "#f8f8f2", selectionBackground: "#44475a",
    ansi: ["#44475a", "#ff5555", "#50fa7b", "#f1fa8c", "#bd93f9", "#ff79c6", "#8be9fd", "#bfbfbf", "#8e9bc7", "#ff6e6e", "#69ff94", "#ffffa5", "#d6acff", "#ff92df", "#a4ffff", "#ffffff"],
  },
  nord: {
    label: "Nord", background: "#2e3440", foreground: "#e5e9f0", cursor: "#d8dee9", selectionBackground: "#434c5e",
    ansi: ["#4c566a", "#bf616a", "#a3be8c", "#ebcb8b", "#81a1c1", "#b48ead", "#88c0d0", "#d8dee9", "#8f9db5", "#d08770", "#b5d19d", "#f0d9a0", "#9ab8d8", "#c6a0c0", "#9fd0de", "#eceff4"],
  },
  oneDark: {
    label: "One Dark", background: "#282c34", foreground: "#abb2bf", cursor: "#528bff", selectionBackground: "#3e4451",
    ansi: ["#5c6370", "#e06c75", "#98c379", "#e5c07b", "#61afef", "#c678dd", "#56b6c2", "#abb2bf", "#7f8794", "#ef8089", "#a9d68a", "#f0cf8f", "#74c0ff", "#d78ff0", "#6bd0dd", "#ffffff"],
  },
  gruvbox: {
    label: "Gruvbox 深", background: "#282828", foreground: "#ebdbb2", cursor: "#ebdbb2", selectionBackground: "#504945",
    ansi: ["#665c54", "#fb4934", "#b8bb26", "#fabd2f", "#83a598", "#d3869b", "#8ec07c", "#d5c4a1", "#a89984", "#ff6a52", "#cdd13a", "#ffd24a", "#9bbcb0", "#e29bb0", "#a3d493", "#fbf1c7"],
  },
};

export const AUTO = "auto";
export const TERMINAL_THEMES: [string, string][] = [
  [AUTO, "跟随工作台主题（浅色 / 深色）"],
  ...Object.entries(PALETTES).map(([key, p]) => [key, p.label] as [string, string]),
];
const KEY = "burrowl-terminal-theme";

export function loadTerminalTheme(): string {
  try {
    const saved = localStorage.getItem(KEY);
    return saved && (saved === AUTO || saved in PALETTES) ? saved : "dark";
  } catch {
    return "dark";
  }
}

// 把选择变成 xterm 的主题。"跟随工作台"按页面当前实际是浅色还是深色挑 light / dark。
export function resolveTerminalTheme(choice: string, pageDark: boolean): ITheme {
  const key = choice === AUTO ? (pageDark ? "dark" : "light") : choice in PALETTES ? choice : "dark";
  const p = PALETTES[key];
  const names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"] as const;
  const colors: Record<string, string> = {};
  names.forEach((n, i) => {
    colors[n] = p.ansi[i];
    colors[`bright${n[0].toUpperCase()}${n.slice(1)}`] = p.ansi[i + 8];
  });
  return { background: p.background, foreground: p.foreground, cursor: p.cursor, selectionBackground: p.selectionBackground, ...colors };
}

export function pageIsDark(): boolean {
  const forced = document.documentElement.dataset.theme;
  if (forced) return forced === "dark";
  return !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

// 设置页改了，同一页面的 Agent 终端立即跟着变；别的标签页通过 storage 事件同步
const listeners = new Set<() => void>();
let current: string | null = null;
const read = (): string => (current ??= loadTerminalTheme());
const subscribe = (l: () => void) => {
  listeners.add(l);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      current = loadTerminalTheme();
      l();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(l);
    window.removeEventListener("storage", onStorage);
  };
};

export function setTerminalTheme(choice: string): void {
  current = choice;
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    // 存储不可用时只在本次打开期间生效
  }
  for (const l of listeners) l();
}

export function useTerminalTheme(): [string, (t: string) => void] {
  return [useSyncExternalStore(subscribe, read), setTerminalTheme];
}
