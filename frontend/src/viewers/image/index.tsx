// 图片阅读器（设计稿 03 D-12）：可缩放（滚轮、按钮）、拖动的单图查看器。
import { useEffect, useRef, useState } from "react";
import type { ViewerProps } from "../../reader/contract";
import "./image.css";

export default function ImageViewer(props: ViewerProps) {
  const { source } = props;
  const [scale, setScale] = useState(0); // 0 = 适合窗口
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [fit, setFit] = useState(1);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const img = useRef<HTMLImageElement>(null);
  const live = useRef(props);
  live.current = props;
  const effective = scale || fit;

  const measure = () => {
    const b = box.current;
    const i = img.current;
    if (!b || !i || !i.naturalWidth) return;
    setFit(Math.min(b.clientWidth / i.naturalWidth, b.clientHeight / i.naturalHeight, 1));
  };
  useEffect(() => {
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  useEffect(() => live.current.onZoom?.(Math.round(effective * 100)), [effective]);
  useEffect(() => {
    live.current.onReady({
      scrollTo: () => undefined,
      zoom: (z) => {
        setScale((s) => {
          const cur = s || fit;
          if (z === "in") return Math.min(cur * 1.25, 16);
          if (z === "out") return Math.max(cur / 1.25, 0.05);
          if (/^\d+$/.test(z)) return Number(z) / 100;
          setOffset({ x: 0, y: 0 });
          return 0;
        });
      },
    });
  }, [fit]);

  return (
    <div
      ref={box}
      className="bw-image"
      onWheel={(e) => {
        const cur = scale || fit;
        setScale(Math.min(Math.max(cur * (e.deltaY < 0 ? 1.1 : 1 / 1.1), 0.05), 16));
      }}
      onMouseDown={(e) => {
        drag.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
      }}
      onMouseMove={(e) => {
        if (drag.current) setOffset({ x: drag.current.ox + e.clientX - drag.current.x, y: drag.current.oy + e.clientY - drag.current.y });
      }}
      onMouseUp={() => (drag.current = null)}
      onMouseLeave={() => (drag.current = null)}
      onDoubleClick={() => {
        setScale(0);
        setOffset({ x: 0, y: 0 });
      }}
    >
      <img
        ref={img}
        src={source.fileUrl}
        alt={source.title}
        draggable={false}
        onLoad={measure}
        onError={() => props.onError?.("图片无法显示")}
        style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${effective})` }}
      />
    </div>
  );
}
