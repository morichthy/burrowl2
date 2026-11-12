// 关系图：默认按三列分泳道（原件 → 判断 → 框架），也可以换成力导向、层级、同心布局；按节点类型、关系类别筛选；中心 + 展开层数。
// 名称搜索只高亮命中（Enter 跳到下一处），勾"只看命中"才筛掉其余；右键节点有菜单；点两个节点可以找它们之间的路径；
// 专注只看选中节点和邻居；小地图在左下角。布局本身不做动画，只移动镜头。
// 框架层的图可以再生，这里只读：确认或驳回 AI 推断的边在条目页与待决策页完成。
// 设计稿 10 D-22 至 D-24：节点是条目，边是关系，按条目聚合（同一判断对同一条目的同一谓词画一条，标条数）；
// 证据流（依据、佐证、反驳）的箭头统一画成"证据 → 结论"；筛选顺序与条目页、检索页相同：综合程度 → 依据来源 → 类型 → 现状 → 说明。
import cytoscape from "cytoscape";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { call } from "../api";
import { CATEGORY, JUDGMENT_KIND, LAYER, NODE_COLOR, NODE_TYPE, PREDICATE_COLOR, REVIEW, SOURCE, SOURCE_LABEL, relPhrase } from "../labels";
import { go, href } from "../router";
import { Icon } from "../shell/icons";
import { useShortcuts } from "../shell/shortcuts";
import { Stamp } from "../shell/Stamp";
import { copyText, toast } from "../shell/toast";
import { Chips, Coordinates, Empty, ErrorBox, FilterRow, IdLink, useLoad } from "../ui";
import { ReviewBox } from "../review";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Layout = "lanes" | "cose" | "breadthfirst" | "concentric";
const LAYOUTS: [Layout, string][] = [["lanes", "三列泳道"], ["cose", "力导向"], ["breadthfirst", "层级"], ["concentric", "同心"]];
// legend、filters 是浮层的显示开关（全屏时尤其需要收起，避免挡住图）；随视图一起记在浏览器里
// layers / sources / kinds / quoted：综合程度 → 依据来源 → 类型 → 说明（转述）筛选节点（设计稿 10 D-24）
type View = {
  hops: number;
  nodeTypes: string[];
  categories: string[];
  hideSuperseded: boolean;
  layers: string[];
  sources: string[];
  sourceOnly: boolean;
  kinds: string[];
  keepRelated: boolean;
  quoted: boolean;
  query: string;
  onlyHits: boolean;
  excluded: string[];
  legend: boolean;
  filters: boolean;
  layout: Layout;
};
type Filter = Pick<View, "nodeTypes" | "categories" | "hideSuperseded" | "layers" | "sources" | "sourceOnly" | "kinds" | "keepRelated" | "quoted">;
const DEFAULT_FILTER: Filter = {
  nodeTypes: ["artifact", "judgment", "page", "entity"],
  categories: [],
  hideSuperseded: false,
  layers: [],
  sources: [],
  sourceOnly: false,
  kinds: [],
  keepRelated: false,
  quoted: false,
};
const CHAIN = ["evidence", "replace"];
// 常用组合（设计稿 09 D-16）：改动任一筛选后显示为"自定义"
const PRESETS: { key: string; label: string; hint: string; filter: Filter }[] = [
  { key: "default", label: "默认", hint: "全部节点、全部关系", filter: DEFAULT_FILTER },
  {
    key: "explore",
    label: "探索",
    hint: "只留原件与不带框架倾向的判断：去掉框架页、实体与过程判断，关系只留证据流与替代；与检索的探索模式一致",
    filter: { ...DEFAULT_FILTER, nodeTypes: ["artifact", "record", "judgment"], categories: CHAIN, layers: ["original", "judgment"], kinds: ["conclusion", "normative"] },
  },
  {
    key: "local",
    label: "只看本地实证",
    hint: "本地实证原件、依据全部为本地实证的判断，以及规定",
    filter: { ...DEFAULT_FILTER, nodeTypes: ["artifact", "record", "judgment"], layers: ["original", "judgment"], sources: ["local"], sourceOnly: true },
  },
  {
    key: "literature",
    label: "文献对照",
    hint: "转述外部材料的结论与外部原件，以及与它们有佐证或反驳关系的判断",
    filter: { ...DEFAULT_FILTER, nodeTypes: ["artifact", "judgment"], categories: ["evidence"], layers: ["original", "judgment"], sources: ["external"], quoted: true, keepRelated: true },
  },
  {
    key: "chain",
    label: "证据链",
    hint: "原件、事实记录、判断，关系只留证据流（依据、佐证、反驳）与替代，隐藏不是当前有效的",
    filter: { ...DEFAULT_FILTER, nodeTypes: ["artifact", "record", "judgment"], categories: CHAIN, hideSuperseded: true },
  },
];
const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
function presetOf(view: View): string {
  const hit = PRESETS.find(({ filter: f }) =>
    sameList(view.nodeTypes, f.nodeTypes) && sameList(view.categories, f.categories) && sameList(view.layers, f.layers) &&
    sameList(view.sources, f.sources) && sameList(view.kinds, f.kinds) &&
    view.hideSuperseded === f.hideSuperseded && view.sourceOnly === f.sourceOnly && view.keepRelated === f.keepRelated &&
    view.quoted === f.quoted);
  return hit?.key ?? "custom";
}
const DEFAULT_VIEW: View = {
  hops: 2,
  ...DEFAULT_FILTER,
  query: "",
  onlyHits: false,
  excluded: [],
  legend: false,
  filters: false,
  layout: "lanes",
};
const STORE = "burrowl-graph-view";
// 节点所在的列：原件类、判断、框架（框架页与对象）
const LANE: Record<string, number> = { artifact: 0, record: 0, read: 0, judgment: 1, page: 2, entity: 2 };
const LANE_NAME = ["original", "judgment", "framework"];
const LANE_LABEL = ["原件", "判断", "框架"];
const MANY = 80;

function loadView(): View {
  try {
    return { ...DEFAULT_VIEW, ...JSON.parse(localStorage.getItem(STORE) ?? "{}") };
  } catch {
    return DEFAULT_VIEW;
  }
}

export function Graph({ center }: { center?: string }) {
  const [view, setView] = useState<View>(loadView);
  const [selected, setSelected] = useState<any>(null);
  const [pathFrom, setPathFrom] = useState<string | null>(null);
  const [path, setPath] = useState<string[]>([]);
  const [focusMode, setFocusMode] = useState(false);
  const [hit, setHit] = useState(-1);
  const api = useRef<CanvasApi | null>(null);
  useEffect(() => {
    try {
      // 名称搜索是一时的，不记住
      localStorage.setItem(STORE, JSON.stringify({ ...view, query: "", onlyHits: false }));
    } catch {
      // 浏览器存储不可用时只是不记住视图
    }
  }, [view]);
  const [data, error] = useLoad(
    () =>
      call<any>("graph.view", {
        center: center ?? null,
        hops: view.hops,
        node_types: view.nodeTypes,
        categories: view.categories.length ? view.categories : null,
        hide_superseded: view.hideSuperseded,
        layers: view.layers.length ? view.layers : null,
        source_classes: view.sources.length ? view.sources : null,
        source_mode: view.sourceOnly ? "only" : "any",
        kinds: view.kinds.length ? view.kinds : null,
        quoted: view.quoted ? true : null,
        keep_related: view.keepRelated,
        limit: 300,
      }),
    [center, view.hops, view.nodeTypes.join(), view.categories.join(), view.hideSuperseded, view.layers.join(), view.sources.join(), view.sourceOnly, view.kinds.join(), view.keepRelated, view.quoted],
  );
  const q = view.query.trim().toLowerCase();
  const hits = useMemo(() => (q && data ? data.nodes.filter((n: any) => !view.excluded.includes(n.id) && ((n.label ?? "").toLowerCase().includes(q) || n.id.toLowerCase().includes(q))).map((n: any) => n.id as string) : []), [data, q, view.excluded]);
  const shown = useMemo(() => {
    if (!data) return null;
    const keep = new Set(hits);
    const nodes = data.nodes.filter((n: any) => !view.excluded.includes(n.id) && (!view.onlyHits || !q || keep.has(n.id) || n.id === center));
    const ids = new Set(nodes.map((n: any) => n.id));
    return { nodes, edges: data.edges.filter((e: any) => ids.has(e.source) && ids.has(e.target)) };
  }, [data, view.onlyHits, q, hits, view.excluded, center]);
  useEffect(() => setHit(-1), [q]);
  const typeCounts = useMemo(() => countBy(data?.nodes ?? [], (n: any) => n.type), [data]);
  const catCounts = useMemo(() => countBy(data?.edges ?? [], (e: any) => e.category), [data]);
  const set = (patch: Partial<View>) => setView({ ...view, ...patch });
  // 全屏（设计稿 03 D-07）：图铺满屏幕，筛选与节点详情变成浮层；Esc 退出
  const page = useRef<HTMLDivElement>(null);
  const [full, setFull] = useState(false);
  useEffect(() => {
    const onChange = () => !document.fullscreenElement && setFull(false);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  const toggleFull = () => {
    if (full) {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
      setFull(false);
    } else {
      setFull(true);
      if (page.current?.requestFullscreen) void page.current.requestFullscreen().catch(() => undefined);
    }
  };
  // 选中节点：如果正在找路径，选中的就是终点
  const select = useCallback((n: any) => {
    setSelected(n);
    setFocusMode(false);
    if (n && pathFrom && pathFrom !== n.id) {
      const found = api.current?.path(pathFrom, n.id) ?? [];
      setPath(found);
      setPathFrom(null);
      if (!found.length) toast("这两个节点在当前图里不相连", "info");
    }
  }, [pathFrom]);
  const nextHit = (step = 1) => {
    if (!hits.length) return;
    const i = hit < 0 ? (step > 0 ? 0 : hits.length - 1) : (hit + step + hits.length) % hits.length;
    setHit(i);
    api.current?.focus(hits[i]);
    setSelected(data?.nodes.find((n: any) => n.id === hits[i]) ?? null);
  };
  useShortcuts({
    "0": () => api.current?.fit(),
    ".": () => (selected ? setFocusMode((f) => !f) : false),
    f: toggleFull,
    "=": () => api.current?.zoom(1.25),
    "-": () => api.current?.zoom(0.8),
    Escape: () => {
      if (full) return setFull(false);
      if (path.length || pathFrom || focusMode) {
        setPath([]);
        setPathFrom(null);
        setFocusMode(false);
        return;
      }
      return false;
    },
  });

  const preset = presetOf(view);
  const filtered = preset !== "default" || view.excluded.length > 0;
  const filters = (
    <div className="graph-filters">
      <div className="filter-rows">
        <FilterRow label="组合">
          <div className="chips" role="group" aria-label="常用组合">
            {PRESETS.map((p) => (
              <button type="button" key={p.key} className={preset === p.key ? "on" : ""} title={p.hint} onClick={() => set(p.filter)}>
                {p.label}
              </button>
            ))}
            {preset === "custom" && <span className="muted small">自定义</span>}
          </div>
        </FilterRow>
        <FilterRow label="综合程度">
          <Chips multi options={Object.entries(LAYER)} value={view.layers} onChange={(v) => set({ layers: v })} />
        </FilterRow>
        <FilterRow label="依据来源">
          <div className="row tight">
            <Chips multi options={Object.entries(SOURCE)} value={view.sources} onChange={(v) => set({ sources: v })} />
            <label className="check" title="不勾：依据含所选来源之一即保留；勾上：依据全部在所选来源之内。只筛原件与判断，规定与框架不受影响">
              <input type="checkbox" checked={view.sourceOnly} onChange={(e) => set({ sourceOnly: e.target.checked })} />
              只含所选来源
            </label>
            <label className="check" title="同时保留与筛中节点有佐证、反驳关系的原件与判断">
              <input type="checkbox" checked={view.keepRelated} onChange={(e) => set({ keepRelated: e.target.checked })} />
              带上佐证与反驳的条目
            </label>
          </div>
        </FilterRow>
        <FilterRow label="类型">
          <Chips multi options={Object.entries(JUDGMENT_KIND)} value={view.kinds} onChange={(v) => set({ kinds: v })} />
        </FilterRow>
        <FilterRow label="现状 · 说明">
          <div className="row tight">
            <label className="check">
              <input type="checkbox" checked={view.hideSuperseded} onChange={(e) => set({ hideSuperseded: e.target.checked })} />
              只看当前有效的
            </label>
            <label className="check" title="只留转述外部材料（有原作者）的判断">
              <input type="checkbox" checked={view.quoted} onChange={(e) => set({ quoted: e.target.checked })} />
              只看转述的判断
            </label>
          </div>
        </FilterRow>
        <FilterRow label="节点">
          <Chips all={null} multi options={Object.entries(NODE_TYPE)} value={view.nodeTypes} onChange={(v) => set({ nodeTypes: v.length ? v : DEFAULT_VIEW.nodeTypes })} counts={typeCounts} />
        </FilterRow>
        <FilterRow label="关系">
          <Chips multi options={Object.entries(CATEGORY).map(([k, c]) => [k, c.label] as [string, string])} value={view.categories} onChange={(v) => set({ categories: v })} counts={catCounts} />
        </FilterRow>
        <FilterRow label="范围">
          <div className="row tight">
            {center && (
              <label className="check">
                展开层数
                <input type="number" className="narrow" min={1} max={4} value={view.hops} onChange={(e) => set({ hops: Number(e.target.value) || 1 })} />
              </label>
            )}
            <button type="button" className="small" onClick={() => setView({ ...DEFAULT_VIEW, legend: view.legend, filters: view.filters, layout: view.layout })} title="组合、节点、关系、范围、名称恢复默认">
              重置筛选
            </button>
          </div>
        </FilterRow>
      </div>
      {view.excluded.length > 0 && (
        <div className="hidden-bar">
          <span className="muted">已隐藏 {view.excluded.length} 个：</span>
          {view.excluded.map((id) => (
            <button key={id} type="button" className="hidden-chip" onClick={() => set({ excluded: view.excluded.filter((x) => x !== id) })}>
              {id.slice(0, 12)}… ×
            </button>
          ))}
          <button type="button" className="link" onClick={() => set({ excluded: [] })}>
            全部恢复
          </button>
        </div>
      )}
    </div>
  );
  const count = `${shown?.nodes.length ?? 0} 个节点 · ${shown?.edges.length ?? 0} 条关系${center ? ` · 中心展开 ${view.hops} 层` : ""}`;
  const selectedEdges = (shown?.edges ?? []).filter((e: any) => selected && (e.source === selected.id || e.target === selected.id));

  return (
    <div ref={page} className={`graph-page${full ? " full" : ""}`}>
      <header className="graph-bar">
        <div className="segctl" role="tablist" aria-label="两种图">
          <a role="tab" aria-selected="true" className="on" href={href("graph", center ?? "")}>关系图</a>
          <a role="tab" aria-selected="false" href={center?.startsWith("art_") ? href("coverage", center) : href("coverage")} title="原件被读过、被引用的覆盖情况">覆盖图</a>
        </div>
        <span className="muted small-text">{count}</span>
        <span className="grow" />
        <button type="button" className={`toggle${view.filters ? "" : ""}`} aria-pressed={view.filters} onClick={() => set({ filters: !view.filters })} title={view.filters ? "收起筛选" : "展开筛选"}>
          <Icon name="filter" size={15} />筛选{filtered ? " ●" : ""}
        </button>
        <button type="button" className="toggle" aria-pressed={view.legend} onClick={() => set({ legend: !view.legend })}>图例</button>
        {center && <button type="button" onClick={() => go("graph")}>取消中心</button>}
        <button type="button" className="primary" onClick={toggleFull} title={full ? "退出全屏（Esc）" : "图铺满屏幕（f）"}>
          <Icon name="expand" size={15} />{full ? "退出全屏" : "全屏"} <kbd>f</kbd>
        </button>
      </header>
      {view.filters && !full && <div className="panel graph-filter-panel">{filters}</div>}
      <ErrorBox error={error} />
      {data?.truncated && <div className="notice">节点过多，只显示了相连最多的一部分；请缩小范围或设置中心。</div>}
      <div className="graph-body">
        {shown && shown.nodes.length === 0 ? (
          <Empty>
            {center
              ? "图里没有这个中心条目：它可能已撤回、已退役或被隐藏（默认不画），也可能被左侧的筛选排除了。"
              : "没有符合条件的节点。"}
          </Empty>
        ) : (
          <Canvas
            data={shown}
            center={center}
            selectedId={selected?.id}
            onSelect={select}
            full={full}
            layoutKey={`${view.filters}`}
            layout={view.layout}
            hits={hits}
            currentHit={hit >= 0 ? hits[hit] : undefined}
            path={path}
            focusMode={focusMode}
            apiRef={api}
            onMenu={(id, action) => {
              const node = data?.nodes.find((n: any) => n.id === id);
              if (action === "center") go("graph", id);
              if (action === "open") go("entry", id);
              if (action === "hide") { set({ excluded: [...view.excluded, id] }); if (selected?.id === id) setSelected(null); }
              if (action === "copy") void copyText(id, "已复制 ID");
              if (action === "focus") { setSelected(node); setFocusMode(true); }
              if (action === "path") {
                if (selected && selected.id !== id) {
                  const found = api.current?.path(selected.id, id) ?? [];
                  setPath(found);
                  if (!found.length) toast("这两个节点在当前图里不相连", "info");
                } else {
                  setSelected(node);
                  setPathFrom(id);
                  toast("再点一个节点，画出两者之间的路径", "info");
                }
              }
            }}
          >
            <div className="graph-overlay graph-search" role="search">
              <Icon name="search" size={15} />
              <input
                value={view.query}
                onChange={(e) => set({ query: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); nextHit(e.shiftKey ? -1 : 1); }
                  if (e.key === "Escape") set({ query: "" });
                }}
                placeholder="按名称找节点"
                aria-label="按名称找节点"
              />
              {q && <span className="hit-count">{!hits.length ? "没有命中" : hit < 0 ? `${hits.length} 处` : `${hit + 1} / ${hits.length} 处`}</span>}
              {q && hits.length > 1 && <kbd title="Shift+Enter 上一处">Enter 下一个</kbd>}
              <label className="check"><input type="checkbox" checked={view.onlyHits} onChange={(e) => set({ onlyHits: e.target.checked })} />只看命中</label>
            </div>
            <div className="graph-overlay graph-layouts segctl" role="radiogroup" aria-label="布局">
              {LAYOUTS.map(([k, t]) => (
                <button key={k} type="button" role="radio" aria-checked={view.layout === k} className={view.layout === k ? "on" : ""} onClick={() => set({ layout: k })}>{t}</button>
              ))}
            </div>
            {full && view.filters && <div className="graph-overlay graph-overlay-filters">{filters}</div>}
            {view.legend && (
              <div className="graph-overlay graph-legend" role="region" aria-label="图例">
                <div className="overlay-head">
                  <strong>图例</strong>
                  <button type="button" className="pane-close static" onClick={() => set({ legend: false })} title="隐藏图例">×</button>
                </div>
                <Legend />
                <p className="graph-hint">单击看详情 · 双击换中心 · 右键节点有菜单 · 拖动平移 · 滚轮缩放</p>
              </div>
            )}
            {(pathFrom || path.length > 0 || focusMode) && (
              <div className="graph-overlay graph-mode">
                {pathFrom && <span>找路径：再点一个节点作为终点</span>}
                {path.length > 0 && <span>路径：{Math.ceil(path.length / 2)} 个节点</span>}
                {focusMode && <span>专注：只看选中节点和它的邻居</span>}
                <button type="button" className="small" onClick={() => { setPath([]); setPathFrom(null); setFocusMode(false); }}>退出 <kbd>Esc</kbd></button>
              </div>
            )}
          </Canvas>
        )}
        <aside className="graph-side" aria-label="选中的节点">
          {selected ? (
            <Focus
              node={selected}
              edges={selectedEdges}
              path={path}
              nodes={data?.nodes ?? []}
              focusMode={focusMode}
              onFocus={() => setFocusMode(!focusMode)}
              onPath={() => { setPathFrom(selected.id); setPath([]); toast("再点一个节点，画出两者之间的路径", "info"); }}
              onClose={() => { setSelected(null); setFocusMode(false); }}
              onHide={(id) => {
                set({ excluded: [...view.excluded, id] });
                setSelected(null);
              }}
            />
          ) : (
            <div className="graph-side-empty">
              <p className="label">还没有选中节点</p>
              <p className="muted small-text">单击节点看它的地位和邻居；右键有更多操作；先后点两个节点可以找它们之间的路径。</p>
              <ul className="lane-key">
                {LANE_LABEL.map((t, i) => <li key={t}><Stamp layer={LANE_NAME[i]} small />{t}</li>)}
              </ul>
              {(shown?.nodes.length ?? 0) > MANY && <p className="muted small-text">节点超过 {MANY} 个时只给命中、选中和相连多的节点画名称，其余悬停才显示。</p>}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function countBy(items: any[], key: (x: any) => string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const i of items) out[key(i)] = (out[key(i)] ?? 0) + 1;
  return out;
}

function Focus({ node, edges, path, nodes, focusMode, onFocus, onPath, onHide, onClose }: { node: any; edges: any[]; path: string[]; nodes: any[]; focusMode: boolean; onFocus: () => void; onPath: () => void; onHide: (id: string) => void; onClose: () => void }) {
  const [openEdge, setOpenEdge] = useState<string | null>(null);
  const pathNodes = path.filter((id) => nodes.some((n) => n.id === id));
  return (
    <div className="focus">
      <div className="overlay-head">
        <span className="focus-type">
          <Stamp layer={LANE_NAME[LANE[node.type] ?? 2]} small />
          {NODE_TYPE[node.type] ?? node.type}
        </span>
        <button type="button" className="pane-close static" onClick={onClose} title="关闭详情">×</button>
      </div>
      <p className="focus-title"><IdLink id={node.id} name={node.label} /></p>
      <p className="mono muted">{node.id}</p>
      <Coordinates c={node} />
      <div className="row">
        <a className="button small primary" href={href("entry", node.id)}>打开</a>
        <a className="button small" href={href("graph", node.id)}>以它为中心</a>
        <button type="button" className="small toggle" aria-pressed={focusMode} onClick={onFocus}>专注 <kbd>.</kbd></button>
        <button type="button" className="small" onClick={onPath}>找路径</button>
        <button type="button" className="small" onClick={() => onHide(node.id)}>隐藏</button>
      </div>
      {pathNodes.length > 0 && (
        <>
          <h3>路径</h3>
          <ol className="path-list">
            {pathNodes.map((id) => {
              const n = nodes.find((x) => x.id === id);
              return <li key={id}><Stamp layer={LANE_NAME[LANE[n?.type] ?? 2]} small /><IdLink id={id} name={n?.label} /></li>;
            })}
          </ol>
        </>
      )}
      <h3>相连的关系（{edges.length}）</h3>
      <ul className="plain focus-edges">
        {edges.map((e) => (
          <li key={e.id}>
            <i className="swatch" style={{ background: edgeColor(e.category) }} />
            {e.source === node.id ? "→" : "←"} <span className="tag">{edgeText(e, e.source === node.id)}</span> <IdLink id={e.source === node.id ? e.target : e.source} />
            {e.origin === "framework" && e.review && <span className="tag warn">框架推断·{REVIEW[e.review] ?? e.review}</span>}
            {String(e.id).startsWith("edg_") && (
              <button type="button" className="link small-text" onClick={() => setOpenEdge(openEdge === e.id ? null : e.id)}>
                {openEdge === e.id ? "收起" : "复核"}
              </button>
            )}
            {openEdge === e.id && <ReviewBox itemId={e.id} compact />}
          </li>
        ))}
      </ul>
    </div>
  );
}

// 边的说法：从主语一端看（outgoing）或从宾语一端看；同一对条目有多条关系时标出条数（"依据 5 段"）
const edgeText = (e: any, outgoing = true) => {
  const phrase = relPhrase(e.predicate ?? e.rel, outgoing, e.label);
  if ((e.count ?? 1) <= 1) return phrase;
  return e.predicate === "cites" && String(e.target).startsWith("art_") ? `${phrase} ${e.count} 段` : `${phrase} ×${e.count}`;
};

// 画布是"夜空"：深色底上颜色要更亮一些。语义不变（原件绿、判断蓝、框架橙；冲突红、替代紫），只调亮度
const NIGHT_NODE: Record<string, string> = {
  artifact: "#3fc08a",
  record: "#6fd0a5",
  read: "#a6dcc3",
  judgment: "#6b97ff",
  page: "#f2a649",
  entity: "#a3acc0",
};
const NIGHT_EDGE: Record<string, string> = {
  evidence: "#9aa6bd",
  stance: "#8fa8d6",
  replace: "#b58cff",
  process: "#6fd0a5",
  framework: "#f2a649",
  free: "#3cc6d0",
};
const NIGHT_PREDICATE: Record<string, string> = { supports: "#4ade80", opposes: "#ff6b6b" };
const nodeColor = (type: string) => NIGHT_NODE[type] ?? NODE_COLOR[type] ?? "#a3acc0";
const edgeColor = (category: string) => NIGHT_EDGE[category] ?? CATEGORY[category]?.color ?? "#9aa6bd";
// 依据与过程的边按两端节点的颜色渐变画（看得出从哪一列连向哪一列）；佐证、反驳、替代、框架推断保持本类的颜色
const GRADIENT_PREDICATES = new Set(["cites", "consumed", "produced"]);
const INFERRED = "#f2a649";
const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const LAYOUT = {
  name: "cose",
  animationDuration: 650,
  animationEasing: "ease-out-cubic",
  // 标签在节点下方：斥力与组件间距留出标签的宽度，避免相邻节点的标签叠在一起
  nodeRepulsion: (n: any) => 90000 + (n.data("size") ?? 18) * 3500,
  idealEdgeLength: (e: any) => (e.hasClass("pred-mentions") ? 65 : 105),
  edgeElasticity: () => 110,
  nodeOverlap: 40,
  gravity: 0.25,
  numIter: 1800,
  componentSpacing: 100,
  padding: 48,
  fit: true,
};

// 图例里的节点形状与图上一致（原件类是标签形、框架页圆角方形、实体六边形、判断圆形）
function Shape({ type }: { type: string }) {
  const fill = nodeColor(type);
  if (type === "page") return <svg width="14" height="14" aria-hidden="true"><rect x="1" y="1" width="12" height="12" rx="3" fill={fill} /></svg>;
  if (type === "entity") return <svg width="14" height="14" aria-hidden="true"><polygon points="7,1 12.5,4 12.5,10 7,13 1.5,10 1.5,4" fill={fill} /></svg>;
  if (type === "judgment") return <svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="6" fill={fill} /></svg>;
  return <svg width="14" height="14" aria-hidden="true"><path d="M1 3 Q1 1 3 1 H9 L13 7 L9 13 H3 Q1 13 1 11 Z" fill={fill} /></svg>;
}

function Legend() {
  return (
    <ul className="legend">
      {Object.entries(NODE_TYPE).map(([k, text]) => (
        <li key={k}>
          <Shape type={k} />
          {text}
        </li>
      ))}
      {Object.entries(CATEGORY).map(([k, c]) => (
        <li key={k} title={c.hint}>
          <svg width="28" height="8" aria-hidden="true">
            <line x1="0" y1="4" x2="28" y2="4" stroke={edgeColor(k)} strokeWidth="2.5" strokeDasharray={c.dash.join(" ")} />
          </svg>
          {c.label}
        </li>
      ))}
      <li>
        <svg width="28" height="8" aria-hidden="true">
          <line x1="0" y1="4" x2="28" y2="4" stroke={INFERRED} strokeWidth="2" strokeDasharray="5 4" />
        </svg>
        AI 推断·未复核
      </li>
      <li>
        <i className="dotmark superseded-mark" />
        已被替代
      </li>
      <li className="muted wide">节点越大，相连越多；依据来源见节点详情</li>
    </ul>
  );
}

type CanvasApi = { fit: () => void; zoom: (factor: number) => void; focus: (id: string) => void; path: (from: string, to: string) => string[] };
type MenuAction = "center" | "open" | "hide" | "copy" | "focus" | "path";
const MENU: [MenuAction, string][] = [["center", "以它为中心"], ["focus", "专注：只看它和邻居"], ["path", "找路径（和选中的节点）"], ["hide", "从图上隐藏"], ["copy", "复制 ID"], ["open", "打开条目"]];
const LANE_W = 380;

// 三列泳道：x 由节点所在的列决定，列内按相连数从多到少排；一列太长时折成几小列
function lanePositions(cy: cytoscape.Core): Record<string, { x: number; y: number }> {
  const lanes: cytoscape.NodeSingular[][] = [[], [], []];
  cy.nodes().forEach((n) => {
    const type = ["artifact", "record", "read", "judgment", "page", "entity"].find((t) => n.hasClass(t)) ?? "entity";
    lanes[LANE[type] ?? 2].push(n);
  });
  const pos: Record<string, { x: number; y: number }> = {};
  lanes.forEach((nodes, lane) => {
    nodes.sort((a, b) => b.degree(false) - a.degree(false) || String(a.data("label")).localeCompare(String(b.data("label"))));
    const rows = Math.max(8, Math.ceil(Math.sqrt(nodes.length) * 2.4));
    const cols = Math.ceil(nodes.length / rows) || 1;
    const colW = Math.min(150, (LANE_W - 60) / cols);
    nodes.forEach((n, i) => {
      const col = Math.floor(i / rows);
      const row = i % rows;
      const inCol = Math.min(rows, nodes.length - col * rows);
      pos[n.id()] = { x: lane * LANE_W + (col - (cols - 1) / 2) * colW, y: (row - (inCol - 1) / 2) * 62 + (col % 2) * 18 };
    });
  });
  return pos;
}

function runLayout(cy: cytoscape.Core, layout: Layout, center?: string) {
  if (layout === "lanes") {
    const pos = lanePositions(cy);
    cy.layout({ name: "preset", positions: (n: any) => pos[n.id()], animate: false, fit: false } as any).run();
  } else if (layout === "breadthfirst") {
    cy.layout({ name: "breadthfirst", directed: false, roots: center && cy.getElementById(center).length ? `#${CSS.escape(center)}` : undefined, spacingFactor: 1.15, animate: false, fit: false } as any).run();
  } else if (layout === "concentric") {
    cy.layout({ name: "concentric", concentric: (n: any) => (n.id() === center ? 1000 : n.degree()), levelWidth: () => 3, minNodeSpacing: 34, animate: false, fit: false } as any).run();
  } else {
    cy.layout({ ...LAYOUT, animate: false, fit: false } as any).run();
  }
}

function Canvas({
  data, center, selectedId, onSelect, full, layoutKey, layout, hits, currentHit, path, focusMode, apiRef, onMenu, children,
}: {
  data: any; center?: string; selectedId?: string; onSelect: (n: any) => void; full?: boolean; layoutKey?: string; layout: Layout;
  hits: string[]; currentHit?: string; path: string[]; focusMode: boolean; apiRef: { current: CanvasApi | null }; onMenu: (id: string, action: MenuAction) => void; children?: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const mini = useRef<HTMLCanvasElement>(null);
  const cyRef = useRef<cytoscape.Core>(undefined);
  const nodesRef = useRef(new Map<string, any>());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [tip, setTip] = useState<{ x: number; y: number; title: string; lines: string[] }>();
  const [menu, setMenu] = useState<{ x: number; y: number; id: string }>();
  const [bands, setBands] = useState<{ left: number; width: number; top: number }[]>([]);
  const [zoomPct, setZoomPct] = useState(100);
  const layoutRef = useRef(layout);
  layoutRef.current = layout;
  const inJsdom = typeof navigator !== "undefined" && navigator.userAgent.includes("jsdom");

  const fitAll = useCallback((animate = true) => {
    const cy = cyRef.current;
    if (!cy) return;
    const eles = cy.elements(":visible");
    if (animate && !reducedMotion()) cy.animate({ fit: { eles, padding: 56 } } as any, { duration: 320 });
    else cy.fit(eles, 56);
  }, []);

  // 泳道的底色跟着镜头移动；小地图跟着视图重画
  const syncOverlays = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    setZoomPct(Math.round(cy.zoom() * 100));
    if (layoutRef.current === "lanes" && cy.nodes().length) {
      const z = cy.zoom();
      const p = cy.pan();
      const top = Math.max(0, (cy.nodes().boundingBox({}).y1 - 60) * z + p.y);
      setBands([0, 1, 2].map((lane) => ({ left: (lane * LANE_W - LANE_W / 2) * z + p.x, width: LANE_W * z, top })));
    } else setBands([]);
    const canvas = mini.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    const visible = cy.nodes(":visible");
    if (!visible.length) return;
    const bb = visible.boundingBox({});
    const ext = cy.extent();
    const x1 = Math.min(bb.x1, ext.x1);
    const y1 = Math.min(bb.y1, ext.y1);
    const x2 = Math.max(bb.x2, ext.x2);
    const y2 = Math.max(bb.y2, ext.y2);
    const s = Math.min((W - 12) / (x2 - x1 || 1), (H - 12) / (y2 - y1 || 1));
    const ox = (W - (x2 - x1) * s) / 2 - x1 * s;
    const oy = (H - (y2 - y1) * s) / 2 - y1 * s;
    visible.forEach((n) => {
      const p = n.position();
      ctx.fillStyle = n.selected() ? "#ffffff" : n.data("color");
      ctx.globalAlpha = n.hasClass("dimq") || n.hasClass("offpath") ? 0.3 : 1;
      ctx.beginPath();
      ctx.arc(p.x * s + ox, p.y * s + oy, n.selected() ? 3.5 : 2.2, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.globalAlpha = 1;
    ctx.strokeStyle = "#e9ebf1";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(ext.x1 * s + ox, ext.y1 * s + oy, (ext.x2 - ext.x1) * s, (ext.y2 - ext.y1) * s);
    canvas.dataset.scale = String(s);
    canvas.dataset.ox = String(ox);
    canvas.dataset.oy = String(oy);
  }, []);

  useEffect(() => {
    if (!box.current || inJsdom) return;
    const cy = cytoscape({ container: box.current, style: style(), minZoom: 0.08, maxZoom: 4, wheelSensitivity: 0.3 });
    cy.on("tap", "node", (ev) => {
      setMenu(undefined);
      onSelectRef.current(nodesRef.current.get(ev.target.id()));
    });
    cy.on("tap", (ev) => {
      if (ev.target === cy) {
        setMenu(undefined);
        onSelectRef.current(null);
      }
    });
    cy.on("dbltap", "node", (ev) => go("graph", ev.target.id()));
    cy.on("cxttap", "node", (ev) => {
      const p = ev.target.renderedPosition();
      setTip(undefined);
      setMenu({ x: Math.min(p.x + 8, cy.width() - 220), y: Math.min(p.y + 8, cy.height() - 240), id: ev.target.id() });
    });
    cy.on("cxttap", (ev) => ev.target === cy && setMenu(undefined));
    cy.on("mouseover", "node", (ev) => {
      const n = nodesRef.current.get(ev.target.id());
      const p = ev.target.renderedPosition();
      cy.elements().addClass("faded");
      ev.target.closedNeighborhood().removeClass("faded").addClass("near");
      ev.target.connectedEdges().addClass("lit");
      setTip({
        x: Math.min(p.x + 16, cy.width() - 260),
        y: p.y + 16,
        title: n?.label ?? ev.target.id(),
        lines: [n?.status_note ?? NODE_TYPE[n?.type] ?? "", (n?.sources ?? []).map((s: string) => SOURCE_LABEL[s] ?? SOURCE[s] ?? s).join(" + "), `${ev.target.neighborhood().nodes().length} 个相连节点 · 右键有菜单`].filter(Boolean),
      });
    });
    cy.on("mouseover", "edge", (ev) => {
      const e = ev.target;
      const p = ev.renderedPosition;
      e.addClass("lit");
      setTip({ x: Math.min(p.x + 14, cy.width() - 260), y: p.y + 14, title: `${CATEGORY[e.data("category")]?.label ?? ""}：${e.data("text")}`, lines: [e.data("category") === "evidence" ? "箭头从证据指向结论" : e.data("origin") === "framework" ? "框架推断，不作为依据" : ""].filter(Boolean) });
    });
    cy.on("mouseout", "node, edge", () => {
      cy.elements().removeClass("faded near lit");
      setTip(undefined);
    });
    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        syncOverlays();
      });
    };
    cy.on("viewport", () => {
      setTip(undefined);
      setMenu(undefined);
      schedule();
    });
    cy.on("position select unselect", schedule);
    const block = (e: Event) => e.preventDefault();
    box.current.addEventListener("contextmenu", block);
    // AI 推断的边像"蚂蚁线"一样缓慢流动，提示它还没被复核；系统要求减少动效时不动
    let offset = 0;
    const timer = reducedMotion()
      ? 0
      : window.setInterval(() => {
          const inferred = cy.edges(".inferred");
          if (!inferred.length || document.hidden) return;
          offset = (offset - 1) % 900;
          inferred.style("line-dash-offset", offset);
        }, 70);
    cyRef.current = cy;
    apiRef.current = {
      fit: () => fitAll(),
      zoom: (factor) => cy.zoom({ level: Math.max(0.08, Math.min(4, cy.zoom() * factor)), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }),
      focus: (id) => {
        const n = cy.getElementById(id);
        if (!n.length) return;
        cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 1.1) } as any, { duration: reducedMotion() ? 0 : 300 });
      },
      path: (from, to) => {
        const r = cy.elements(":visible").aStar({ root: cy.getElementById(from), goal: cy.getElementById(to), directed: false });
        return r.found ? r.path.map((e) => e.id()) : [];
      },
    };
    const el = box.current;
    return () => {
      window.clearInterval(timer);
      if (frame) window.cancelAnimationFrame(frame);
      el.removeEventListener("contextmenu", block);
      apiRef.current = null;
      cy.destroy();
    };
  }, [inJsdom, apiRef, fitAll, syncOverlays]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !data) return;
    nodesRef.current = new Map(data.nodes.map((n: any) => [n.id, n]));
    const degree: Record<string, number> = {};
    for (const e of data.edges) {
      degree[e.source] = (degree[e.source] ?? 0) + 1;
      degree[e.target] = (degree[e.target] ?? 0) + 1;
    }
    // 节点很多时只给相连最多的一批画名称，其余悬停才显示
    const many = data.nodes.length > MANY;
    const loud = new Set(many ? [...data.nodes].sort((a: any, b: any) => (degree[b.id] ?? 0) - (degree[a.id] ?? 0)).slice(0, 30).map((n: any) => n.id) : []);
    const typeOf = new Map<string, string>(data.nodes.map((n: any) => [n.id, n.type]));
    cy.elements().remove();
    cy.add([
      ...data.nodes.map((n: any) => {
        const base = n.type === "page" || n.type === "entity" ? 24 : 16;
        const size = n.id === center ? 40 : base + Math.min(Math.sqrt(degree[n.id] ?? 0) * 5, 22);
        return {
          data: { id: n.id, label: (n.label ?? n.id).slice(0, 24), color: nodeColor(n.type), size },
          classes: [n.type, (n.state?.validity ?? "current") !== "current" ? "superseded" : "", n.id === center ? "center" : "", many && !loud.has(n.id) ? "quiet" : ""].join(" "),
        };
      }),
      ...data.edges.map((e: any, i: number) => {
        const inferred = e.origin === "framework" && e.review === "ai_generated";
        const grad = !inferred && GRADIENT_PREDICATES.has(e.predicate);
        // 证据流统一画成"证据 → 结论"（D-22）：evidence_from 是证据一端
        const from = e.evidence_from ?? e.source;
        const to = from === e.source ? e.target : e.source;
        const label = e.predicate === "relates" || (e.count ?? 1) > 1 ? edgeText(e) : "";
        return {
          data: {
            id: `e${i}:${e.id}`, source: from, target: to, rel: e.predicate, category: e.category, origin: e.origin,
            text: edgeText(e), label,
            grad: `${nodeColor(typeOf.get(from) ?? "")} ${nodeColor(typeOf.get(to) ?? "")}`,
          },
          classes: [`cat-${e.category}`, `pred-${e.predicate}`, inferred ? "inferred" : "", grad ? "grad" : "", label ? "labeled" : ""].join(" "),
        };
      }),
    ]);
    // 渐变两端的颜色逐条设置（渐变色不能从 data 映射）
    cy.edges(".grad").forEach((e) => {
      e.style("line-gradient-stop-colors", e.data("grad"));
    });
    // 布局本身不做动画（动画靠逐帧回调，页面在后台时会停在半路，图挤成一团）；只让镜头从稍远处推近
    runLayout(cy, layout, center);
    cy.resize();
    cy.fit(undefined, 56);
    if (cy.zoom() > 1.6) cy.zoom({ level: 1.6, position: { x: cy.width() / 2, y: cy.height() / 2 } as any });
    cy.center();
    if (!reducedMotion()) {
      const target = { zoom: cy.zoom(), pan: { ...cy.pan() } };
      cy.zoom({ level: target.zoom * 0.92, position: { x: cy.width() / 2, y: cy.height() / 2 } as any });
      cy.animate(target as any, { duration: 500, easing: "ease-out-cubic" });
    }
    syncOverlays();
    // 中心节点的光晕缓慢呼吸
    const centerNode = center ? cy.getElementById(center) : null;
    let alive = true;
    const breathe = (grow: boolean) => {
      if (!alive || !centerNode?.length || reducedMotion()) return;
      centerNode.animate({ style: { "underlay-padding": grow ? 16 : 8, "underlay-opacity": grow ? 0.34 : 0.18 } as any }, { duration: 1600, easing: "ease-in-out-sine", complete: () => breathe(!grow) });
    };
    breathe(true);
    return () => {
      alive = false;
      if (centerNode?.length) centerNode.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, center, layout]);

  // 搜索命中、路径、专注：只换样式类，不重排
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass("hit hit-now dimq onpath offpath gone");
      if (hits.length) {
        const set = new Set(hits);
        cy.nodes().forEach((n) => {
          if (set.has(n.id())) n.addClass("hit");
          else n.addClass("dimq");
        });
        if (currentHit) cy.getElementById(currentHit).addClass("hit-now");
      }
      if (path.length) {
        const set = new Set(path);
        cy.elements().forEach((e) => {
          e.addClass(set.has(e.id()) ? "onpath" : "offpath");
        });
      }
      if (focusMode && selectedId) {
        const keep = cy.getElementById(selectedId).closedNeighborhood();
        cy.elements().not(keep).addClass("gone");
      }
    });
    if (focusMode && selectedId) fitAll();
    if (!focusMode && !path.length) syncOverlays();
  }, [hits.join(), currentHit, path.join(), focusMode, selectedId, data, layout, fitAll, syncOverlays]);

  // 进入、退出全屏或筛选收起展开（画布高度变了）后，重算画布大小并适配视图
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const t = window.setTimeout(() => {
      cy.resize();
      fitAll(false);
      syncOverlays();
    }, 120);
    return () => window.clearTimeout(t);
  }, [full, layoutKey, fitAll, syncOverlays]);
  // 窗口大小变化时 cytoscape 不会自己重算画布
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      cyRef.current?.resize();
      syncOverlays();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [syncOverlays]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().unselect();
    if (selectedId) cy.getElementById(selectedId).select();
  }, [selectedId]);

  // 点小地图：把镜头移到那里
  const onMini = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const cy = cyRef.current;
    const c = mini.current;
    if (!cy || !c) return;
    const r = c.getBoundingClientRect();
    const s = Number(c.dataset.scale || 1);
    const mx = ((e.clientX - r.left) * (c.width / r.width) - Number(c.dataset.ox || 0)) / s;
    const my = ((e.clientY - r.top) * (c.height / r.height) - Number(c.dataset.oy || 0)) / s;
    cy.pan({ x: cy.width() / 2 - mx * cy.zoom(), y: cy.height() / 2 - my * cy.zoom() });
  };

  return (
    <div className="graph-wrap">
      {bands.map((b, i) => (
        <div key={i} className={`lane-band lane-${i}`} style={{ left: b.left, width: b.width }} aria-hidden="true">
          <span style={{ top: Math.max(56, b.top) }}><Stamp layer={LANE_NAME[i]} small />{LANE_LABEL[i]}</span>
        </div>
      ))}
      <div ref={box} className="graph" data-testid="graph" />
      <canvas ref={mini} className="graph-mini" width={368} height={224} onClick={onMini} aria-label="小地图：点击把镜头移到那里" role="img" />
      <div className="graph-overlay graph-zoom" role="group" aria-label="缩放">
        <button type="button" className="small" onClick={() => apiRef.current?.zoom(0.8)} aria-label="缩小" title="缩小（-）">−</button>
        <span className="mono">{zoomPct}%</span>
        <button type="button" className="small" onClick={() => apiRef.current?.zoom(1.25)} aria-label="放大" title="放大（=）">+</button>
        <button type="button" className="small" onClick={() => fitAll()} title="把全部节点缩放到画布内（0）"><Icon name="fit" size={14} />适应 <kbd>0</kbd></button>
      </div>
      {children}
      {menu && (
        <div className="graph-overlay graph-menu" role="menu" aria-label="节点菜单" style={{ left: menu.x, top: menu.y }}>
          <p className="graph-menu-title clip">{nodesRef.current.get(menu.id)?.label ?? menu.id}</p>
          {MENU.map(([k, t]) => (
            <button key={k} type="button" role="menuitem" onClick={() => { setMenu(undefined); onMenu(menu.id, k); }}>{t}</button>
          ))}
        </div>
      )}
      {tip && !menu && (
        <div className="graph-tip" style={{ left: tip.x, top: tip.y }}>
          <strong>{tip.title}</strong>
          {tip.lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function style(): cytoscape.StylesheetJson {
  const ink = "#0b0f1f";
  const rules: any[] = [
    {
      selector: "node",
      style: {
        "background-color": "data(color)",
        "background-opacity": 0.95,
        width: "data(size)",
        height: "data(size)",
        "border-width": 1.5,
        "border-color": "#ffffff",
        "border-opacity": 0.35,
        "underlay-color": "data(color)",
        "underlay-opacity": 0.16,
        "underlay-padding": 6,
        "underlay-shape": "ellipse",
        label: "data(label)",
        "font-size": 10.5,
        "font-family": "system-ui, 'Microsoft YaHei', sans-serif",
        color: "#e3e8f6",
        "text-valign": "bottom",
        "text-margin-y": 5,
        "text-wrap": "ellipsis",
        "text-max-width": "120px",
        "min-zoomed-font-size": 7,
        "text-outline-color": ink,
        "text-outline-width": 2.2,
        "text-outline-opacity": 0.85,
        "transition-property": "opacity, underlay-opacity, underlay-padding, border-width",
        "transition-duration": 180,
      },
    },
    { selector: "node.page", style: { shape: "round-rectangle" } },
    { selector: "node.entity", style: { shape: "hexagon" } },
    { selector: "node.artifact, node.record, node.read", style: { shape: "round-tag" } },
    { selector: "node.superseded", style: { "border-width": 2, "border-style": "dashed", "border-color": "#ff6b6b", "border-opacity": 1, opacity: 0.6, "underlay-opacity": 0 } },
    { selector: "node.center", style: { "border-width": 3, "border-color": "#ffffff", "border-opacity": 0.9, "font-weight": 600, "font-size": 12, "underlay-opacity": 0.24, "underlay-padding": 10 } },
    { selector: "node.near", style: { "underlay-opacity": 0.3, "underlay-padding": 9 } },
    { selector: "node:selected", style: { "border-width": 3, "border-color": "#ffffff", "border-opacity": 1, "underlay-opacity": 0.38, "underlay-padding": 12, "min-zoomed-font-size": 0 } },
    {
      selector: "edge",
      style: {
        width: 1.5,
        "curve-style": "bezier",
        "line-color": "#9aa6bd",
        "target-arrow-color": "#9aa6bd",
        "target-arrow-shape": "vee",
        "arrow-scale": 0.75,
        opacity: 0.6,
        "transition-property": "opacity, width",
        "transition-duration": 180,
      },
    },
    ...Object.entries(CATEGORY).map(([k, c]) => ({
      selector: `edge.cat-${k}`,
      style: { "line-color": edgeColor(k), "target-arrow-color": edgeColor(k), "target-arrow-shape": c.arrow, "line-style": c.dash.length ? "dashed" : "solid", "line-dash-pattern": c.dash.length ? c.dash : [1, 0] },
    })),
    ...Object.entries(PREDICATE_COLOR).map(([k, color]) => ({
      selector: `edge.pred-${k}`,
      style: { "line-color": NIGHT_PREDICATE[k] ?? color, "target-arrow-color": NIGHT_PREDICATE[k] ?? color, width: k === "cites" ? 1.2 : 2 },
    })),
    { selector: "edge.grad", style: { "line-fill": "linear-gradient" } },
    { selector: "edge.pred-mentions", style: { width: 1, opacity: 0.4 } },
    { selector: "edge.labeled", style: { label: "data(label)", "font-size": 9, color: "#c8d0e0", "text-rotation": "autorotate", "text-background-color": "#10151f", "text-background-opacity": 0.7, "text-background-padding": "2px" } },
    { selector: "edge.inferred", style: { "line-style": "dashed", "line-dash-pattern": [5, 4], "line-color": INFERRED, "target-arrow-color": INFERRED, opacity: 0.85 } },
    { selector: "edge.lit", style: { width: 2.6, opacity: 1, "z-index": 9 } },
    { selector: ".faded", style: { opacity: 0.08 } },
    // 节点很多时的"安静"节点只在悬停、选中、命中时显示名称
    { selector: "node.quiet", style: { label: "" } },
    { selector: "node.quiet.near, node.quiet:selected, node.quiet.hit, node.quiet.onpath", style: { label: "data(label)" } },
    { selector: ".dimq", style: { opacity: 0.28 } },
    { selector: "node.hit", style: { "border-width": 2.5, "border-color": "#f0b54e", "border-opacity": 1, "underlay-color": "#f0b54e", "underlay-opacity": 0.3 } },
    { selector: "node.hit-now", style: { "border-width": 4, "underlay-padding": 12, "font-weight": 700 } },
    { selector: ".offpath", style: { opacity: 0.12 } },
    { selector: "edge.onpath", style: { width: 3.2, "line-color": "#ffffff", "target-arrow-color": "#ffffff", "line-fill": "solid", opacity: 1, "z-index": 10 } },
    { selector: "node.onpath", style: { "border-width": 3, "border-color": "#ffffff", "border-opacity": 1 } },
    { selector: ".gone", style: { display: "none" } },
  ];
  return rules as unknown as cytoscape.StylesheetJson;
}
