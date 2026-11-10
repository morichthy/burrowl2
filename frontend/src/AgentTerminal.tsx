// 浏览器终端只转发选中会话的键盘输入和尺寸，切换页面只释放显示组件。
import { useEffect, useRef, useState } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { call } from "./api";

export function AgentTerminal({ runId, chunks, active }: { runId: string; chunks: string[]; active: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const offset = useRef(0);
  const [error, setError] = useState("");

  useEffect(() => {
    const view = new Terminal({ cursorBlink: true, scrollback: 5000, disableStdin: !active });
    const fit = new FitAddon();
    view.loadAddon(fit);
    view.open(host.current!);
    terminal.current = view;
    offset.current = 0;
    // 连续键入与粘贴必须按顺序送达，不能由多个并行请求打乱字符顺序。
    let pending = Promise.resolve();
    let mounted = true;
    const send = (payload: Record<string, unknown>) => {
      pending = pending.then(async () => {
        if (!mounted) return;
        await call("agent.terminal_input", { run_id: runId, ...payload });
        if (mounted) setError("");
      }).catch((err: Error) => { if (mounted) setError(err.message); });
    };
    const keys = view.onData((text) => {
      if (view.options.disableStdin) return;
      // 每次发一段，不在 UTF-16 代理对之间切开。
      let chunk = "";
      for (const char of text) {
        if (chunk.length + char.length > 16384) {
          send({ text: chunk });
          chunk = "";
        }
        chunk += char;
      }
      if (chunk) send({ text: chunk });
    });
    const size = view.onResize(({ cols, rows }) => {
      if (!view.options.disableStdin) send({ cols: Math.min(cols, 500), rows: Math.min(rows, 200) });
    });
    const resize = new ResizeObserver(() => fit.fit());
    resize.observe(host.current!);
    fit.fit();
    if (active) view.focus();
    return () => {
      mounted = false;
      resize.disconnect();
      keys.dispose();
      size.dispose();
      view.dispose();
      terminal.current = null;
    };
  }, [runId, active]);

  useEffect(() => {
    const text = chunks.slice(offset.current).join("");
    if (text) terminal.current?.write(text);
    offset.current = chunks.length;
  }, [chunks, runId, active]);

  return (
    <>
      <div className="agent-terminal" aria-label="Agent 浏览器终端" ref={host} />
      {error && <p className="warn-text" role="status">{error}</p>}
    </>
  );
}
