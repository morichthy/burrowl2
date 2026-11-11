// 轻提示：操作结果在右下角出现几秒后自己消失（复制、保存、提交之类）。出错的停留更久，点一下可以关掉。
// 只是反馈，不承载需要决定的内容：需要人决定的事仍在页面里。
import { useSyncExternalStore } from "react";

export type Tone = "good" | "bad" | "info";
type Item = { id: number; text: string; tone: Tone };

let items: Item[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((fn) => fn());

export function dismissToast(id: number): void {
  items = items.filter((t) => t.id !== id);
  emit();
}

export function toast(text: string, tone: Tone = "good"): void {
  const id = ++seq;
  // 同样的话不叠两条
  items = [...items.filter((t) => t.text !== text), { id, text, tone }].slice(-4);
  emit();
  window.setTimeout(() => dismissToast(id), tone === "bad" ? 7000 : 2800);
}

// 复制到剪贴板并提示；浏览器不允许时（非安全上下文等）把内容显示出来，方便手动复制
export async function copyText(text: string, what = "已复制"): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    toast(what);
    return true;
  } catch {
    toast(`浏览器不允许复制，请手动复制：${text}`, "bad");
    return false;
  }
}

const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

export function Toasts() {
  const list = useSyncExternalStore(subscribe, () => items);
  return (
    <div className="toasts" aria-live="polite">
      {list.map((t) => (
        <button key={t.id} type="button" className={`toast ${t.tone}`} role="status" onClick={() => dismissToast(t.id)} title="点一下关掉">
          <span className="toast-mark" aria-hidden="true">{t.tone === "bad" ? "!" : t.tone === "info" ? "i" : "✓"}</span>
          {t.text}
        </button>
      ))}
    </div>
  );
}
