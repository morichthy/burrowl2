// 可拖动的分隔条：阅读模式里调节对照视图两栏的比例、侧栏宽度。双击恢复默认。
// 拖动期间铺一层透明遮罩，防止 PDF 画布、外部引擎的 iframe 收走指针事件。
import { useState } from "react";

export function Splitter({ onDrag, onReset, label }: { onDrag: (clientX: number) => void; onReset?: () => void; label: string }) {
  const [dragging, setDragging] = useState(false);
  const start = (e: React.PointerEvent) => {
    e.preventDefault();
    setDragging(true);
    let frame = 0;
    const move = (ev: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => onDrag(ev.clientX));
    };
    const stop = () => {
      setDragging(false);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  };
  return (
    <>
      <div
        className={`splitter${dragging ? " dragging" : ""}`}
        role="separator"
        aria-orientation="vertical"
        aria-label={label}
        title={label}
        onPointerDown={start}
        onDoubleClick={onReset}
      />
      {dragging && <div className="splitter-cover" />}
    </>
  );
}
