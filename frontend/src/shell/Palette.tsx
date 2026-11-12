// 快速跳转（Ctrl+K 或 /）：一个输入框里找条目（按名称或 ID）、去页面、执行常用操作。
// 只调用已有的只读操作（entries.list、page.list、entity.list），不含业务规则；只有人能做的写操作不放在这里。
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { call } from "../api";
import { EntryName } from "../entryLabels";
import { ENTRY_KIND, JUDGMENT_KIND, PAGE_TYPE } from "../labels";
import { go, href, hrefWith } from "../router";
import { Icon } from "./icons";
import { Stamp } from "./Stamp";
import { loadRecent } from "./recent";

/* eslint-disable @typescript-eslint/no-explicit-any */

export type Command = {
  id: string;
  group: string;
  title: ReactNode;
  text: string; // 用来匹配输入的文字（名称 + 别名）
  hint?: string;
  icon?: string;
  layer?: "original" | "judgment" | "framework";
  keys?: string;
  run: () => void;
};

const ID_PATTERN = /^(art|jdg|rec|rd|pg|ent|evt|edg|dec|run|ses|lnk)_[0-9A-Za-z]{6,}(?:[@#][\w-]+)*$/;

// 去页面：别名让英文、拼音首字母也能找到
export const PAGE_COMMANDS: [string, string, string, string][] = [
  ["", "首页", "home", "home shouye sy 概览 仪表盘"],
  ["search", "检索", "search", "search jiansuo js 搜索 查找"],
  ["entries", "条目", "entries", "entries tiaomu tm 原件 判断 事实记录 过程日志"],
  ["graph", "关系图", "graph", "graph guanxitu gxt 图"],
  ["pages", "框架页", "pages", "pages kuangjiaye kjy 综合页 实体页"],
  ["coverage", "覆盖图", "coverage", "coverage fugaitu fgt 读取 引用"],
  ["decisions", "待决策", "decisions", "decisions daijuece djc 复核 巡检 待办"],
  ["record", "人工记录", "record", "record rengongjilu rgjl 登记原件 写判断"],
  ["agent", "Agent", "agent", "agent 任务 运行"],
  ["databases", "数据目录", "databases", "databases shujumulu sjml 切换"],
  ["settings", "设置", "settings", "settings shezhi sz 模型 抽取 巡检"],
];

const SETTING_SECTIONS: [string, string][] = [
  ["set-extract", "抽取方式"], ["set-snapshot", "页面快照"], ["set-reading", "阅读"], ["set-models", "模型与引擎"],
  ["set-agents", "Agent"], ["set-review", "复核"], ["set-index", "检索索引"], ["set-retrieval", "检索参数"], ["set-inspection", "巡检"], ["set-ui", "界面"],
];

function staticCommands(extra: Command[]): Command[] {
  const nav = (id: string, title: string, to: string, text: string, icon: string, hint?: string): Command => ({
    id, group: "前往", title, text: `${title} ${text}`, icon, hint, run: () => (window.location.hash = to),
  });
  return [
    ...PAGE_COMMANDS.map(([key, title, icon, alias]) => nav(`page:${key}`, title, key ? href(key) : "#/", alias, icon)),
    nav("view:retired", "已退役的原件", hrefWith("entries", { kind: "artifact", status: "retired" }), "tuiyi retired 过时", "filter", "条目 · 筛选"),
    nav("view:replaced", "被替代的判断", hrefWith("entries", { status: "replaced" }), "tidai replaced 过时", "filter", "条目 · 筛选"),
    nav("view:lapsed", "依据失效的判断", hrefWith("entries", { status: "lapsed" }), "shixiao lapsed 过时", "filter", "条目 · 筛选"),
    nav("view:stale", "输入已变化的框架页", hrefWith("pages", { fresh: "inputs_changed" }), "stale bianhua 重新综合", "filter", "框架页 · 筛选"),
    nav("view:events", "过程日志", hrefWith("entries", { kind: "event" }), "event rizhi 会话", "filter", "条目 · 筛选"),
    ...SETTING_SECTIONS.map(([sid, title]) => nav(`set:${sid}`, `设置 · ${title}`, hrefWith("settings", { at: sid }), "settings shezhi", "settings")),
    ...extra,
  ];
}

type Found = { id: string; title: string; meta: string; layer?: Command["layer"] };

// 按名称找条目：三类账本条目各取几条，加上框架页和实体（都是只读操作）
async function findEntries(q: string): Promise<Found[]> {
  const entries = (kind: string) =>
    call<any>("entries.list", { kind, query: q, limit: 5 })
      .then((r) => (r.items as any[]).map((e): Found => ({
        id: e.id,
        title: e.preview || e.id,
        meta: e.kind && kind === "judgment" ? (JUDGMENT_KIND[e.kind] ?? "判断") : (ENTRY_KIND[kind] ?? kind),
        layer: e.layer,
      })))
      .catch(() => [] as Found[]);
  const lower = q.toLowerCase();
  const pages = call<any[]>("page.list", {})
    .then((rows) => rows.filter((p) => String(p.title ?? "").toLowerCase().includes(lower)).slice(0, 5)
      .map((p): Found => ({ id: p.id, title: p.title, meta: PAGE_TYPE[p.type] ?? "框架页", layer: "framework" })))
    .catch(() => [] as Found[]);
  const entities = call<any[]>("entity.list", {})
    .then((rows) => rows.filter((e) => String(e.name ?? "").toLowerCase().includes(lower)).slice(0, 5)
      .map((e): Found => ({ id: e.id, title: e.name, meta: `对象 · ${e.kind}` })))
    .catch(() => [] as Found[]);
  return (await Promise.all([entries("judgment"), entries("artifact"), entries("record"), pages, entities])).flat();
}

export function matches(command: Command, q: string): boolean {
  const text = command.text.toLowerCase();
  return q.toLowerCase().split(/\s+/).filter(Boolean).every((word) => text.includes(word));
}

export function Palette({ open, onClose, commands = [] }: { open: boolean; onClose: () => void; commands?: Command[] }) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Found[]>([]);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const q = query.trim();

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setFound([]);
    setActive(0);
    input.current?.focus();
  }, [open]);

  // 输入停顿一下再查，后发的结果不被先发的覆盖
  useEffect(() => {
    if (!open || q.length < 2 || ID_PATTERN.test(q)) {
      setFound([]);
      setBusy(false);
      return;
    }
    let alive = true;
    setBusy(true);
    const timer = window.setTimeout(() => {
      findEntries(q).then((rows) => {
        if (!alive) return;
        setFound(rows);
        setBusy(false);
      });
    }, 160);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [q, open]);

  const items = useMemo<Command[]>(() => {
    if (!open) return [];
    const base = staticCommands(commands);
    const entry = (id: string, group: string, title: ReactNode, meta: string, layer?: Command["layer"]): Command => ({
      id: `${group}:${id}`, group, title, text: "", hint: meta, layer, icon: group === "最近打开" ? "clock" : "target", run: () => go("entry", id),
    });
    if (!q) {
      return [
        ...loadRecent().slice(0, 6).map((id) => entry(id, "最近打开", <EntryName id={id} />, "")),
        ...base.filter((c) => c.id.startsWith("page:") || c.group === "操作"),
      ];
    }
    const out: Command[] = [];
    if (ID_PATTERN.test(q)) out.push({ ...entry(q, "条目", <>打开 <span className="mono">{q}</span></>, "按 ID"), icon: "open" });
    out.push(...base.filter((c) => matches(c, q)).slice(0, 8));
    out.push(...found.map((f) => entry(f.id, "条目", f.title, f.meta, f.layer)));
    out.push({
      id: "search", group: "检索", title: <>在全部内容里检索「{q}」</>, text: "", icon: "search", hint: "正文、段落、判断",
      run: () => (window.location.hash = hrefWith("search", { q })),
    });
    return out;
  }, [open, q, found, commands]);

  useEffect(() => setActive(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector(".palette-item.on")?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  if (!open) return null;
  const pick = (c: Command | undefined) => {
    if (!c) return;
    onClose();
    c.run();
  };
  let lastGroup = "";
  return (
    <div className="palette-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="快速跳转">
        <div className="palette-input">
          <Icon name="search" />
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="找条目（名称或 ID）、去页面、执行操作…"
            aria-label="快速跳转"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === "ArrowDown") (e.preventDefault(), setActive((a) => Math.min(items.length - 1, a + 1)));
              else if (e.key === "ArrowUp") (e.preventDefault(), setActive((a) => Math.max(0, a - 1)));
              else if (e.key === "Enter") (e.preventDefault(), pick(items[active]));
              else if (e.key === "Escape") (e.preventDefault(), e.stopPropagation(), onClose());
            }}
          />
          {busy && <span className="spinner" aria-label="正在查找" />}
          <kbd>Esc</kbd>
        </div>
        <div className="palette-list" id="palette-list" role="listbox" ref={listRef}>
          {items.map((c, i) => {
            const head = c.group !== lastGroup ? <div className="palette-group">{c.group}</div> : null;
            lastGroup = c.group;
            return (
              <div key={c.id}>
                {head}
                <button
                  type="button"
                  role="option"
                  aria-selected={i === active}
                  className={`palette-item${i === active ? " on" : ""}`}
                  onMouseMove={() => i !== active && setActive(i)}
                  onClick={() => pick(c)}
                >
                  {c.layer ? <Stamp layer={c.layer} small /> : <Icon name={c.icon ?? "chevron"} />}
                  <span className="palette-title">{c.title}</span>
                  {c.hint && <span className="palette-hint">{c.hint}</span>}
                  {c.keys && <kbd>{c.keys}</kbd>}
                </button>
              </div>
            );
          })}
          {q.length === 1 && <div className="palette-note">再输入一个字开始找条目</div>}
        </div>
        <footer className="palette-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
          <span><kbd>Enter</kbd> 打开</span>
          <span className="grow" />
          <span className="layer-key"><Stamp layer="original" small />原件<Stamp layer="judgment" small />判断<Stamp layer="framework" small />框架（不能作依据）</span>
        </footer>
      </div>
    </div>
  );
}
