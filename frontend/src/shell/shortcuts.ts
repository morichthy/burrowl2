// 键盘快捷键：单键（"/"、"?"、"j"）、组合键（"mod+k"，mod 是 Ctrl 或 ⌘）、两键连按（"g e"，一秒内）。
// 正在输入框里打字时只响应组合键和 Esc，不抢字符。
import { useEffect, useRef } from "react";

export type Shortcut = { keys: string; label: string; group: string };

// 帮助面板里列出的快捷键（按 ? 打开）；全局的绑定在 Shell.tsx，页面自己的在各页
export const SHORTCUTS: Shortcut[] = [
  { group: "全局", keys: "Ctrl K", label: "快速跳转：找条目、去页面、做操作" },
  { group: "全局", keys: "/", label: "同上（不在输入框里时）" },
  { group: "全局", keys: "n", label: "记一笔：写判断或登记原件，不离开当前页" },
  { group: "全局", keys: "t", label: "切换主题：跟随系统 → 浅色 → 深色" },
  { group: "全局", keys: "?", label: "显示这张快捷键表" },
  { group: "全局", keys: "Esc", label: "关闭浮层；关系图里退出全屏" },
  { group: "前往（先按 g）", keys: "g h", label: "首页" },
  { group: "前往（先按 g）", keys: "g s", label: "检索" },
  { group: "前往（先按 g）", keys: "g e", label: "条目" },
  { group: "前往（先按 g）", keys: "g g", label: "关系图" },
  { group: "前往（先按 g）", keys: "g p", label: "框架页" },
  { group: "前往（先按 g）", keys: "g d", label: "待决策" },
  { group: "前往（先按 g）", keys: "g a", label: "Agent" },
  { group: "前往（先按 g）", keys: "g ,", label: "设置" },
  { group: "列表和队列", keys: "j k", label: "下一条、上一条（条目、检索结果、待决策、框架页）" },
  { group: "列表和队列", keys: "Space", label: "在右侧预览光标所在的一条" },
  { group: "列表和队列", keys: "Enter", label: "打开光标所在的一条" },
  { group: "列表和队列", keys: "r", label: "在阅读模式中打开" },
  { group: "列表和队列", keys: "v", label: "在关系图中以它为中心" },
  { group: "列表和队列", keys: "c", label: "复制 ID" },
  { group: "列表和队列", keys: "x", label: "勾选（待决策里交给 AI 前）" },
  { group: "关系图", keys: "0", label: "适应窗口" },
  { group: "关系图", keys: ".", label: "专注：只看选中节点和它的邻居" },
  { group: "关系图", keys: "f", label: "全屏" },
  { group: "关系图", keys: "Enter", label: "在名称搜索框里：跳到下一处命中" },
  { group: "关系图", keys: "右键节点", label: "以它为中心、展开邻居、找路径、隐藏、复制 ID" },
];

export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable;
}

function describe(e: KeyboardEvent): string {
  const mod = e.ctrlKey || e.metaKey;
  const key = e.key === " " ? "Space" : e.key.length === 1 ? e.key.toLowerCase() : e.key;
  return `${mod ? "mod+" : ""}${e.altKey ? "alt+" : ""}${key}`;
}

// map 的键：单键 "j"、组合键 "mod+k"、连按 "g e"。处理函数返回 false 表示这次不处理（不拦默认行为）
export function useShortcuts(map: Record<string, (e: KeyboardEvent) => void | boolean>, enabled = true): void {
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    if (!enabled) return;
    let prefix = "";
    let timer = 0;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing || e.defaultPrevented) return;
      const key = describe(e);
      const typing = isTyping(e.target);
      if (typing && !key.startsWith("mod+") && key !== "Escape") return;
      // 只有修饰键本身、或带了没绑定的 Ctrl/Alt 组合：不打断连按
      if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
      const handlers = ref.current;
      const combo = prefix ? `${prefix} ${key}` : key;
      window.clearTimeout(timer);
      const waiting = prefix;
      prefix = "";
      const run = handlers[combo] ?? (waiting ? undefined : handlers[key]);
      if (run) {
        if (run(e) !== false) e.preventDefault();
        return;
      }
      if (!waiting && Object.keys(handlers).some((k) => k.startsWith(`${key} `))) {
        prefix = key;
        timer = window.setTimeout(() => (prefix = ""), 1000);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, [enabled]);
}

// 列表里的键盘光标：页面给每一行加 data-nav-item（值是这一行的 ID），这里只管移动、滚动、打开和行内按键，不认识具体页面。
// 光标移动时发出 "nav-cursor" 事件（detail 是行的 data-nav-item），页面可以据此同步右侧的预览
export const CURSOR_EVENT = "nav-cursor";

function rows(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>("main [data-nav-item]")].filter((el) => el.offsetParent !== null);
}

export function cursorRow(): HTMLElement | null {
  return document.querySelector<HTMLElement>("main [data-nav-item].nav-cursor");
}

export function setCursor(row: HTMLElement | null, scroll = true): void {
  for (const el of document.querySelectorAll(".nav-cursor")) if (el !== row) el.classList.remove("nav-cursor");
  if (!row) return;
  row.classList.add("nav-cursor");
  if (scroll) row.scrollIntoView({ block: "nearest" });
  window.dispatchEvent(new CustomEvent(CURSOR_EVENT, { detail: row.dataset.navItem ?? "" }));
}

export function moveCursor(step: 1 | -1): boolean {
  const list = rows();
  if (!list.length) return false;
  const at = list.findIndex((el) => el.classList.contains("nav-cursor"));
  setCursor(list[at < 0 ? (step > 0 ? 0 : list.length - 1) : Math.max(0, Math.min(list.length - 1, at + step))]);
  return true;
}

export function openCursor(): boolean {
  const row = cursorRow();
  const link = row?.querySelector<HTMLAnchorElement>("[data-key~='open'], a[href]");
  if (!link) return false;
  link.click();
  return true;
}

// 行内按键：光标所在行里带 data-key="r"（或 "v"、"c"、"x"、"Space"）的元素被点击
export function cursorKey(key: string): boolean {
  const target = cursorRow()?.querySelector<HTMLElement>(`[data-key~='${key}']`);
  if (!target) return false;
  target.click();
  return true;
}
