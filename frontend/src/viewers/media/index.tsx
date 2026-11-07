// 音视频阅读器（设计稿 03 D-12）：原生播放器 + 按时间戳的抽取文字，点一行跳到对应时刻，播放时当前一行高亮。
// 标注方式 text：每条时间戳文字（cue）一个元素。
import { useEffect, useRef, useState } from "react";
import type { ViewerProps } from "../../reader/contract";
import "./media.css";

function clock(t: number): string {
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

export default function MediaViewer(props: ViewerProps) {
  const { source, marks, marksVisible, highlight } = props;
  const player = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(0);
  const audio = source.mediaType.startsWith("audio/");
  const unit = source.units.find((u) => u.unit === "av");
  const cues = (unit?.blocks ?? []).map((b: { t?: number; text?: string }, i: number) => ({ i, t: b.t ?? 0, text: b.text ?? "" }));
  const markOf = (i: number) => marks.find((m) => m.unit === "av" && m.block === i);
  const live = useRef(props);
  live.current = props;

  useEffect(() => {
    const scrollTo = (key: string) => {
      const m = live.current.marks.find((x) => x.key === key);
      const el = list.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`);
      el?.scrollIntoView({ block: "center" });
      const cue = (live.current.source.units.find((u) => u.unit === "av")?.blocks ?? [])[m?.block ?? -1];
      if (player.current && cue?.t !== undefined) player.current.currentTime = cue.t;
    };
    live.current.onReady({ scrollTo });
  }, [source.id]);
  const seek = (t: number) => {
    if (!player.current) return;
    player.current.currentTime = t;
    void player.current.play();
  };
  const current = cues.reduce((best, c) => (c.t <= now ? c.i : best), -1);

  return (
    <div className="bw-media">
      <div className="bw-media-player">
        {audio ? (
          <audio ref={player} controls src={source.fileUrl} onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)} />
        ) : (
          <video ref={player} controls src={source.fileUrl} onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)} />
        )}
      </div>
      <div className="bw-media-cues" ref={list}>
        {!cues.length && <p className="bw-media-empty">还没有转写文字。</p>}
        {cues.map((c) => {
          const m = markOf(c.i);
          const cls = [
            "bw-cue",
            c.i === current ? "now" : "",
            marksVisible && m?.state.cited ? "bw-cited" : marksVisible && m?.state.read ? "bw-read" : "",
            m && m.key === highlight ? "bw-hover" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <div key={c.i} data-key={m?.key} className={cls} onMouseEnter={() => props.onHover?.(m?.key ?? null)}>
              <button type="button" onClick={() => seek(c.t)}>
                {clock(c.t)}
              </button>
              <span onClick={() => props.onMarkClick(m?.key ?? null)}>{c.text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
