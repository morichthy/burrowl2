// 工作台的骨架：左侧深色图标导航、吸顶的顶栏（返回、所在位置、快速跳转、记一笔、主题、快捷键）、主区、底部状态栏。
// 快速跳转、记一笔、快捷键、轻提示都挂在这里；页面本身不知道它们的存在。
import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { call, currentDb } from "../api";
import { EntryLabels, EntryName } from "../entryLabels";
import { go, href, lastHref } from "../router";
import { useLoad, usePoll } from "../ui";
import { Icon } from "./icons";
import { Palette, type Command } from "./Palette";
import { QuickNote, openQuickNote, useQuickNote } from "./QuickNote";
import { pushRecent } from "./recent";
import { SHORTCUTS, cursorKey, moveCursor, openCursor, useShortcuts } from "./shortcuts";
import { THEME_LABEL, nextTheme, useTheme } from "./theme";
import { toast } from "./toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

// 导航：八项，第三项是 "g 某键" 的那个键。覆盖图在关系图页的页签里，人工记录并入"记一笔"，数据目录在导航底部
export const NAV: [string, string, string][] = [
  ["", "首页", "h"],
  ["search", "检索", "s"],
  ["entries", "条目", "e"],
  ["graph", "关系图", "g"],
  ["pages", "框架页", "p"],
  ["decisions", "待决策", "d"],
  ["agent", "Agent", "a"],
  ["settings", "设置", ","],
];
const PAGE_NAME: Record<string, string> = {
  ...Object.fromEntries(NAV.map(([key, text]) => [key, text])),
  coverage: "覆盖图",
  reading: "阅读会话",
  record: "人工记录",
  databases: "数据目录",
};
// 不在导航里的页面高亮到它所属的那一项
const NAV_OWNER: Record<string, string> = { reading: "", coverage: "graph", record: "entries", databases: "settings" };

// 所在位置：页面 › 具体的一条。条目回到的是带着上次筛选的列表
function Crumbs({ route }: { route: string[] }) {
  const [page, a] = route;
  const parts: [ReactNode, string?][] = [];
  if (page === "entry") {
    const base = (a ?? "").split("#")[0].split("@")[0];
    const list = base.startsWith("pg_") ? "pages" : "entries";
    parts.push([PAGE_NAME[list], lastHref(list)]);
    if (a) parts.push([<EntryName key={a} id={base} />]);
  } else {
    const key = page ?? "";
    parts.push([PAGE_NAME[key] ?? "首页", a ? lastHref(key) : undefined]);
    if (a && (page === "graph" || page === "coverage")) parts.push([<EntryName key={a} id={a} />]);
    else if (a && page === "record") parts.push(["登记新版本"]);
    else if (a && page === "reading") parts.push([<span key={a} className="mono">{a.slice(0, 14)}…</span>]);
    else if (a && page === "agent") parts.push([<span key={a} className="mono">{a.slice(0, 14)}…</span>]);
  }
  return (
    <nav className="crumbs" aria-label="所在位置">
      {parts.map(([text, to], i) => (
        <span key={i} className={i === parts.length - 1 ? "crumb here" : "crumb"}>
          {i > 0 && <span className="crumb-sep" aria-hidden="true">/</span>}
          {to ? <a href={to}>{text}</a> : <span>{text}</span>}
        </span>
      ))}
    </nav>
  );
}

function ShortcutHelp({ onClose }: { onClose: () => void }) {
  const groups = [...new Set(SHORTCUTS.map((s) => s.group))];
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal shortcuts-help" role="dialog" aria-modal="true" aria-label="快捷键">
        <header>
          <h3>快捷键</h3>
          <button type="button" className="pane-close static" onClick={onClose} title="关闭（Esc）">×</button>
        </header>
        <div className="modal-body shortcut-groups">
          {groups.map((g) => (
            <section key={g}>
              <h4>{g}</h4>
              <dl>
                {SHORTCUTS.filter((s) => s.group === g).map((s) => (
                  <div key={s.keys}>
                    <dt>{s.keys.split(" ").map((k, i) => (k === "/" ? <span key={i} className="muted"> / </span> : <kbd key={i}>{k}</kbd>))}</dt>
                    <dd>{s.label}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
          <p className="muted small-text shortcut-foot">在输入框里打字时，单键快捷键不生效。</p>
        </div>
      </div>
    </div>
  );
}

// 底部状态栏：只显示服务端给出的状态，不在前端推断
function StatusBar({ status, health, runs }: { status: any; health: any; runs: number }) {
  const ledger = status?.ledger ? Object.values(status.ledger as Record<string, number>).reduce((s, n) => s + n, 0) : null;
  const vectors = health?.vectors?.state;
  const indexTone = !health ? "" : health.missing > 0 ? "warn" : vectors && vectors !== "ready" && vectors !== "off" ? "warn" : "good";
  const indexText = !health ? "索引…" : health.missing > 0 ? `索引缺 ${health.missing} 条` : vectors === "ready" || vectors === "off" || !vectors ? "索引正常" : `向量${vectors === "building" ? "生成中" : `：${vectors}`}`;
  return (
    <footer className="statusbar" aria-label="系统状态">
      <a href={href("databases")} title="数据目录：点击管理或切换">
        <span className="status-dot good" />数据目录 {status?.data_name ?? currentDb() ?? "…"}
      </a>
      {ledger != null && <span title="账本里的原件、判断、事实记录、读取记录、日志与连接">账本 {ledger.toLocaleString("zh-CN")} 条</span>}
      <a href="#/" onClick={(e) => { e.preventDefault(); window.location.hash = "#/"; setTimeout(() => document.getElementById("status")?.scrollIntoView({ block: "start" }), 300); }} title="在首页查看系统状态的详情">
        <span className={`status-dot ${indexTone}`} />{indexText}
      </a>
      <a href={href("agent")} title="Agent 任务">
        {runs > 0 ? <><span className="status-dot warn pulse" />{runs} 个 Agent 运行中</> : "没有 Agent 在运行"}
      </a>
      <span className="grow" />
      <span className="hide-narrow">按 <kbd>?</kbd> 看快捷键</span>
      {status?.version && <span>burrowl {status.version}</span>}
    </footer>
  );
}

export function Shell({ route, children }: { route: string[]; children: ReactNode }) {
  const [stats, , reload] = useLoad(() => call<any>("stats.overview"), []);
  const [status, , reloadStatus] = useLoad(() => call<any>("system.status"), []);
  const [health, , reloadHealth] = useLoad(() => call<any>("index.health").catch(() => null), []);
  usePoll(useCallback(() => { reload(); reloadStatus(); }, [reload, reloadStatus]), 8000);
  usePoll(reloadHealth, 30000);
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const note = useQuickNote();
  const [theme, setTheme] = useTheme();

  const decisions = Object.values((stats?.decisions ?? {}) as Record<string, number>).reduce((s, n) => s + n, 0);
  const badges: Record<string, number> = {
    decisions,
    pages: stats?.pages?.freshness?.inputs_changed ?? 0,
    agent: stats?.runs?.running ?? 0,
  };
  const BADGE_HINT: Record<string, string> = { decisions: "件待你处理", pages: "页输入已变化", agent: "个 Agent 运行中" };
  const page0 = route[0] ?? "";
  const current = page0 === "entry" ? ((route[1] ?? "").startsWith("pg_") ? "pages" : "entries") : (NAV_OWNER[page0] ?? page0);
  // 页面是整个窗口在滚动：换页（或换一个条目）时回到顶部，不沿用上一页的滚动位置
  const place = `${route[0] ?? ""}/${route[1] ?? ""}`;
  useLayoutEffect(() => {
    window.scrollTo(0, 0);
  }, [place]);
  useEffect(() => {
    if (route[0] === "entry" && route[1]) pushRecent(route[1]);
  }, [route]);

  const cycleTheme = useCallback(() => {
    const next = nextTheme(theme);
    setTheme(next);
    toast(`主题：${THEME_LABEL[next]}`, "info");
  }, [theme, setTheme]);
  // 记一笔：在条目页打开时，把当前条目（含段落锚点）预填为依据
  const quickNote = useCallback(() => openQuickNote(route[0] === "entry" && route[1] && !route[1].startsWith("pg_") && !route[1].startsWith("ent_") ? { cites: [route[1]] } : {}), [route]);

  const commands = useMemo<Command[]>(() => {
    const action = (id: string, title: string, text: string, icon: string, run: () => void, keys?: string): Command => ({
      id: `do:${id}`, group: "操作", title, text: `${title} ${text}`, icon, run, keys,
    });
    return [
      action("note", "记一笔：写判断", "note jiyibi xie panduan 判断 结论 规定 过程 new 新建", "plus", () => openQuickNote({ mode: "judgment" }), "n"),
      action("register", "记一笔：登记原件", "register dengji yuanjian 原件 文件 粘贴", "plus", () => openQuickNote({ mode: "artifact" })),
      action("record", "打开人工记录页（登记新版本等）", "record renggong jilu", "record", () => go("record")),
      action("agent", "启动 Agent", "agent qidong run 任务", "bolt", () => go("agent")),
      action("databases", "切换数据目录", "database shujumulu qiehuan 目录", "databases", () => go("databases")),
      action("theme", `切换主题（现在：${THEME_LABEL[theme]}）`, "theme zhuti dark light 深色 浅色 夜间", theme === "dark" ? "moon" : theme === "light" ? "sun" : "auto", cycleTheme, "t"),
      action("help", "查看快捷键", "shortcuts keyboard kuaijiejian help 帮助", "keyboard", () => setHelp(true), "?"),
    ];
  }, [theme, cycleTheme]);

  const goKeys = Object.fromEntries(NAV.filter(([, , k]) => k).map(([key, , k]) => [`g ${k}`, () => (key ? go(key) : void (window.location.hash = "#/"))]));
  useShortcuts({
    "mod+k": () => setPalette((p) => !p),
    "/": () => setPalette(true),
    "?": () => setHelp((h) => !h),
    n: quickNote,
    t: cycleTheme,
    Escape: () => {
      if (!palette && !help) return false;
      setPalette(false);
      setHelp(false);
    },
    j: () => moveCursor(1),
    k: () => moveCursor(-1),
    Enter: (e) => (e.target === document.body || (e.target as HTMLElement).closest?.("[data-nav-item]") ? openCursor() : false),
    Space: () => cursorKey("Space"),
    r: () => cursorKey("r"),
    v: () => cursorKey("v"),
    c: () => cursorKey("c"),
    x: () => cursorKey("x"),
    ...goKeys,
  }, !note.open);

  const runs = stats?.runs?.running ?? 0;
  return (
    <div className="app">
      <nav className="rail" aria-label="主导航">
        <a className="rail-logo" href="#/" title="burrowl 研发工作台" aria-label="burrowl 首页">b</a>
        {NAV.map(([key, text, k]) => (
          <a
            key={key}
            href={key ? href(key) : "#/"}
            className={current === key ? "on" : ""}
            aria-current={current === key ? "page" : undefined}
            title={`${text}${k ? `（g ${k}）` : ""}${badges[key] ? ` · ${badges[key]} ${BADGE_HINT[key]}` : ""}`}
          >
            <Icon name={key || "home"} />
            <span className="rail-text">{text}</span>
            {badges[key] ? <b className="rail-badge" aria-label={`${badges[key]} ${BADGE_HINT[key]}`}>{badges[key] > 99 ? "99+" : badges[key]}</b> : null}
          </a>
        ))}
        <span className="grow" />
        <a className={`rail-db${current === "settings" && page0 === "databases" ? " on" : ""}`} href={href("databases")} title={`数据目录：${status?.data_name ?? ""}（点击切换）`} aria-label={`数据目录 ${status?.data_name ?? ""}，点击切换`}>
          {(status?.data_name ?? "·").slice(0, 1).toUpperCase()}
        </a>
      </nav>
      <div className="stage">
        <EntryLabels key={place}>
          <header className="topbar">
            {route[0] ? (
              <button type="button" className="icon-button" onClick={() => window.history.back()} title="返回上一处">
                <Icon name="back" />
              </button>
            ) : null}
            <Crumbs route={route} />
            <button type="button" className="palette-trigger" onClick={() => setPalette(true)} title="快速跳转（Ctrl+K 或 /）">
              <Icon name="search" />
              <span>找条目、去页面、做操作</span>
              <kbd>Ctrl K</kbd>
            </button>
            <button type="button" className="top-new" onClick={quickNote} title="记一笔：写判断或登记原件，不离开当前页（n）">
              <Icon name="plus" size={15} />
              记一笔 <kbd>N</kbd>
            </button>
            <button type="button" className="icon-button" onClick={cycleTheme} title={`主题：${THEME_LABEL[theme]}（点击切换，t）`} aria-label={`主题：${THEME_LABEL[theme]}`}>
              <Icon name={theme === "dark" ? "moon" : theme === "light" ? "sun" : "auto"} />
            </button>
            <button type="button" className="icon-button" onClick={() => setHelp(true)} title="快捷键（?）" aria-label="快捷键">
              <Icon name="keyboard" />
            </button>
          </header>
          <Palette open={palette} onClose={() => setPalette(false)} commands={commands} />
        </EntryLabels>
        <main key={current}>
          <EntryLabels key={place}>{children}</EntryLabels>
        </main>
        <StatusBar status={status} health={health} runs={runs} />
      </div>
      {help && <ShortcutHelp onClose={() => setHelp(false)} />}
      <QuickNote />
    </div>
  );
}
