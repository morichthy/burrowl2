// 浏览器终端只转发选中会话的键盘输入和尺寸，切换页面只释放显示组件。
// 已结束的运行是"回放"：去掉备用屏幕与鼠标上报的控制序列，让全部输出留在普通缓冲区里，可以用滚轮或滚动条往上翻；
// 另有"文字记录"视图，纯文本、可选中复制。
import { useEffect, useMemo, useRef, useState } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { call } from "./api";
import { useTheme } from "./shell/theme";
import { pageIsDark, resolveTerminalTheme, useTerminalTheme } from "./terminalTheme";

// 备用屏幕（47、1047、1049）没有滚动历史；鼠标上报（1000–1006、1015）会让滚轮事件被交给已经结束的程序。
const REPLAY_MODES = new Set(["47", "1047", "1049", "1000", "1001", "1002", "1003", "1004", "1005", "1006", "1007", "1015"]);

// 只改回放：把这些模式从 ESC [ ? … h/l 里去掉，其余原样。结尾不完整的序列留到下一段再处理。
export function replayFilter(carry: string, text: string): [string, string] {
  const all = carry + text;
  const cut = all.search(/\x1b(?:\[[?0-9;]*)?$/); // eslint-disable-line no-control-regex
  const body = cut >= 0 ? all.slice(0, cut) : all;
  const out = body.replace(/\x1b\[\?([0-9;]+)([hl])/g, (_m, params: string, op: string) => { // eslint-disable-line no-control-regex
    const keep = params.split(";").filter((p) => !REPLAY_MODES.has(p));
    return keep.length ? `\x1b[?${keep.join(";")}${op}` : "";
  });
  return [out, cut >= 0 ? all.slice(cut) : ""];
}

// 终端输出 → 纯文本：去掉颜色和光标控制；用回车覆盖的进度行只留最后一版
export function plainText(raw: string): string {
  /* eslint-disable no-control-regex */
  return raw
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b\[[0-9;?<=>!]*[ -/]*[@-~]/g, "")
    .replace(/\x1b[()][0-9A-Za-z]/g, "")
    .replace(/\x1b[=>78MDEHc]/g, "")
    .split("\n")
    .map((line) => line.replace(/\r+$/, "").split("\r").pop() ?? "")
    .join("\n");
  /* eslint-enable no-control-regex */
}

export function AgentTerminal({ runId, chunks, active }: { runId: string; chunks: string[]; active: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const offset = useRef(0);
  const carry = useRef("");
  const [error, setError] = useState("");
  const [view, setView] = useState<"terminal" | "text">("terminal");
  const [choice] = useTerminalTheme();
  const [siteTheme] = useTheme();
  const [systemDark, setSystemDark] = useState(pageIsDark);
  const theme = useMemo(() => resolveTerminalTheme(choice, pageIsDark()), [choice, siteTheme, systemDark]);
  const themeRef = useRef(theme);
  themeRef.current = theme;

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media) return;
    const onChange = () => setSystemDark(pageIsDark());
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const view = new Terminal({
      cursorBlink: active, scrollback: 50000, disableStdin: !active, theme: themeRef.current,
      minimumContrastRatio: 4.5, // 程序用的暗淡颜色在任何配色下都不低于可读对比度
      fontSize: 13, scrollOnUserInput: true,
    });
    const fit = new FitAddon();
    view.loadAddon(fit);
    view.open(host.current!);
    terminal.current = view;
    offset.current = 0;
    carry.current = "";
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
    const resize = new ResizeObserver(() => {
      if (host.current && host.current.offsetParent !== null) fit.fit();
    });
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

  // 设置页换了配色，立即用在这个终端上（不重建、不丢内容）
  useEffect(() => {
    if (terminal.current) terminal.current.options.theme = theme;
  }, [theme, runId, active]);

  useEffect(() => {
    const fresh = chunks.slice(offset.current).join("");
    offset.current = chunks.length;
    if (!fresh) return;
    if (active) {
      terminal.current?.write(fresh);
    } else {
      const [text, rest] = replayFilter(carry.current, fresh);
      carry.current = rest;
      if (text) terminal.current?.write(text);
    }
  }, [chunks, runId, active]);

  const plain = useMemo(() => (view === "text" ? plainText(chunks.join("")) : ""), [view, chunks]);
  return (
    <>
      <div className="row tight terminal-tabs">
        <button type="button" className={view === "terminal" ? "primary small" : "small"} onClick={() => setView("terminal")}>终端</button>
        <button type="button" className={view === "text" ? "primary small" : "small"} onClick={() => setView("text")} title="去掉颜色和控制字符的纯文本，可以选中复制">文字记录</button>
        {!active && view === "terminal" && <span className="muted small-text">已结束：滚轮或右侧滚动条可以往上翻</span>}
      </div>
      <div className="agent-terminal" aria-label="Agent 浏览器终端" ref={host}
        style={{ background: theme.background, display: view === "terminal" ? undefined : "none" }} />
      {view === "text" && <pre className="console terminal-text" aria-label="Agent 运行的文字记录">{plain || "（没有输出）"}</pre>}
      {error && <p className="warn-text" role="status">{error}</p>}
    </>
  );
}
