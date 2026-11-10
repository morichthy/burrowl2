// 关系图（参考旧版）：按节点类型、关系类别筛选；中心 + 展开层数；双击换中心；隐藏与恢复；悬停说明；图例。
// 框架层的图可以再生，这里只读：确认或驳回 AI 推断的边在条目页与待决策页完成。
import cytoscape from "cytoscape";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { call } from "../api";
import { CATEGORY, EDGE_REL, LINK_REL, NODE_COLOR, NODE_TYPE, REVIEW, SOURCE } from "../labels";
import { go, href } from "../router";
import { Chips, Coordinates, Empty, ErrorBox, FilterRow, IdLink, Panel, useLoad } from "../ui";
import { ReviewBox } from "../review";

/* eslint-disable @typescript-eslint/no-explicit-any */

// legend、filters 是浮层的显示开关（全屏时尤其需要收起，避免挡住图）；随视图一起记在浏览器里
type View = { hops: number; nodeTypes: string[]; categories: string[]; hideSuperseded: boolean; query: string; excluded: string[]; legend: boolean; filters: boolean };
const DEFAULT_VIEW: View = {
  hops: 2,
  nodeTypes: ["artifact", "judgment", "page", "entity"],
  categories: [],
  hideSuperseded: false,
  query: "",
  excluded: [],
  legend: true,
  filters: true,
};
const STORE = "burrowl-graph-view";

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
  useEffect(() => {
    try {
      localStorage.setItem(STORE, JSON.stringify(view));
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
        limit: 300,
      }),
    [center, view.hops, view.nodeTypes.join(), view.categories.join(), view.hideSuperseded],
  );
  const shown = useMemo(() => {
    if (!data) return null;
    const q = view.query.trim().toLowerCase();
    const nodes = data.nodes.filter((n: any) => !view.excluded.includes(n.id) && (!q || (n.label ?? "").toLowerCase().includes(q) || n.id === center));
    const ids = new Set(nodes.map((n: any) => n.id));
    return { nodes, edges: data.edges.filter((e: any) => ids.has(e.source) && ids.has(e.target)) };
  }, [data, view.query, view.excluded, center]);
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
  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setFull(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);
  const toggleFull = () => {
    if (full) {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
      setFull(false);
    } else {
      setFull(true);
      if (page.current?.requestFullscreen) void page.current.requestFullscreen().catch(() => undefined);
    }
  };

  const filtered = view.categories.length > 0 || !!view.query || view.hideSuperseded || view.excluded.length > 0;
  const filters = (
    <div className="graph-filters">
      <div className="filter-rows">
        <FilterRow label="节点">
          <Chips all={null} multi options={Object.entries(NODE_TYPE)} value={view.nodeTypes} onChange={(v) => set({ nodeTypes: v.length ? v : DEFAULT_VIEW.nodeTypes })} counts={typeCounts} />
        </FilterRow>
        <FilterRow label="关系">
          <Chips multi options={Object.entries(CATEGORY).map(([k, c]) => [k, c.label] as [string, string])} value={view.categories} onChange={(v) => set({ categories: v })} counts={catCounts} />
        </FilterRow>
        <FilterRow label="范围">
          <div className="row tight">
            <input value={view.query} onChange={(e) => set({ query: e.target.value })} placeholder="按名称筛选" />
            {center && (
              <label className="check">
                展开层数
                <input type="number" className="narrow" min={1} max={4} value={view.hops} onChange={(e) => set({ hops: Number(e.target.value) || 1 })} />
              </label>
            )}
            <label className="check">
              <input type="checkbox" checked={view.hideSuperseded} onChange={(e) => set({ hideSuperseded: e.target.checked })} />
              隐藏已被替代的
            </label>
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

  const hint = "单击看详情 · 双击换中心 · 拖动平移 · 滚轮缩放";
  return (
    <div ref={page} className={`graph-page${full ? " full" : ""}`}>
      <Panel
        title={
          <>
            关系图 <span className="title-note">{count}</span>
          </>
        }
        actions={
          <>
            <span className="seg-buttons" role="group" aria-label="显示">
              <button type="button" className="toggle" aria-pressed={view.filters} onClick={() => set({ filters: !view.filters })} title={view.filters ? "收起筛选" : "展开筛选"}>
                筛选{!view.filters && filtered ? " ●" : ""}
              </button>
              <button type="button" className="toggle" aria-pressed={view.legend} onClick={() => set({ legend: !view.legend })} title={view.legend ? "隐藏图例" : "显示图例"}>
                图例
              </button>
            </span>
            {center && (
              <button type="button" onClick={() => go("graph")}>
                取消中心
              </button>
            )}
            <button type="button" onClick={() => setView({ ...DEFAULT_VIEW, legend: view.legend, filters: view.filters })} title="节点、关系、范围恢复默认；不改图例与筛选的显示">
              重置筛选
            </button>
            <button type="button" className="primary" onClick={toggleFull} title={full ? "退出全屏（Esc）" : "图铺满屏幕，筛选、图例与详情变成可收起的浮层"}>
              {full ? "退出全屏" : "全屏"}
            </button>
          </>
        }
      >
        {!full && view.filters && filters}
        <ErrorBox error={error} />
        {data?.truncated && <div className="notice">节点过多，只显示了相连最多的一部分；请缩小范围或设置中心。</div>}
        {shown && shown.nodes.length === 0 ? (
          <Empty>没有符合条件的节点。</Empty>
        ) : (
          <Canvas data={shown} center={center} selectedId={selected?.id} onSelect={setSelected} full={full} layoutKey={`${view.filters}`}>
            {full && view.filters && <div className="graph-overlay graph-overlay-filters">{filters}</div>}
            {view.legend && (
              <div className="graph-overlay graph-legend" role="region" aria-label="图例">
                <div className="overlay-head">
                  <strong>图例</strong>
                  <button type="button" className="pane-close static" onClick={() => set({ legend: false })} title="隐藏图例（上方的“图例”按钮可重新打开）">
                    ×
                  </button>
                </div>
                <Legend />
                <p className="graph-hint">{hint}</p>
              </div>
            )}
            {selected && (
              <div className="graph-overlay graph-focus" role="region" aria-label="节点详情">
                <Focus
                  node={selected}
                  onClose={() => setSelected(null)}
                  edges={(shown?.edges ?? []).filter((e: any) => e.source === selected.id || e.target === selected.id)}
                  onHide={(id) => {
                    set({ excluded: [...view.excluded, id] });
                    setSelected(null);
                  }}
                />
              </div>
            )}
          </Canvas>
        )}
      </Panel>
    </div>
  );
}

function countBy(items: any[], key: (x: any) => string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const i of items) out[key(i)] = (out[key(i)] ?? 0) + 1;
  return out;
}

function Focus({ node, edges, onHide, onClose }: { node: any; edges: any[]; onHide: (id: string) => void; onClose: () => void }) {
  const [openEdge, setOpenEdge] = useState<string | null>(null);
  return (
    <>
      <div className="overlay-head">
        <span className="focus-type">
          <Shape type={node.type} />
          {NODE_TYPE[node.type] ?? node.type}
        </span>
        <button type="button" className="pane-close static" onClick={onClose} title="关闭详情">
          ×
        </button>
      </div>
      <p className="focus-title"><IdLink id={node.id} name={node.label} /></p>
      <Coordinates c={node} />
      <div className="row">
        <a className="button small primary" href={href("entry", node.id)}>
          打开条目
        </a>
        <a className="button small" href={href("graph", node.id)}>
          以它为中心
        </a>
        <button type="button" className="small" onClick={() => onHide(node.id)}>
          隐藏
        </button>
      </div>
      <h3>相连的关系（{edges.length}）</h3>
      <ul className="plain focus-edges">
        {edges.map((e) => (
          <li key={e.id}>
            <i className="swatch" style={{ background: edgeColor(e.category) }} />
            {e.source === node.id ? "→" : "←"} <span className="tag">{relLabel(e.rel)}</span> <IdLink id={e.source === node.id ? e.target : e.source} />
            {e.origin === "ai_inferred" && <span className="tag warn">AI 推断·{REVIEW[e.review] ?? e.review}</span>}
            {String(e.id).startsWith("edg_") && (
              <button type="button" className="link small-text" onClick={() => setOpenEdge(openEdge === e.id ? null : e.id)}>
                {openEdge === e.id ? "收起" : "复核"}
              </button>
            )}
            {openEdge === e.id && <ReviewBox itemId={e.id} compact />}
          </li>
        ))}
      </ul>
    </>
  );
}

/// 框架页的输入清单与主题（overview 的 input / about）
const FRAME_REL: Record<string, string> = { input: "输入", about: "主题" };
const relLabel = (rel: string) => EDGE_REL[rel] ?? LINK_REL[rel] ?? FRAME_REL[rel] ?? rel;

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
  support: "#4ade80",
  conflict: "#ff6b6b",
  supersede: "#b58cff",
  structure: "#8fa8d6",
  derived: "#f2a649",
  mention: "#7f899c",
  association: "#3cc6d0",
};
const nodeColor = (type: string) => NIGHT_NODE[type] ?? NODE_COLOR[type] ?? "#a3acc0";
const edgeColor = (category: string) => NIGHT_EDGE[category] ?? CATEGORY[category]?.color ?? "#9aa6bd";
// 这几类边按两端节点的颜色渐变画（看得出从哪一列连向哪一列）；冲突、替代、支持、相似保持本类的颜色
const GRADIENT_CATEGORIES = new Set(["evidence", "derived", "mention", "structure"]);
const INFERRED = "#f2a649";
const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const LAYOUT = {
  name: "cose",
  animationDuration: 650,
  animationEasing: "ease-out-cubic",
  // 标签在节点下方：斥力与组件间距留出标签的宽度，避免相邻节点的标签叠在一起
  nodeRepulsion: (n: any) => 90000 + (n.data("size") ?? 18) * 3500,
  idealEdgeLength: (e: any) => (e.hasClass("cat-mention") ? 65 : 105),
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

function Canvas({ data, center, selectedId, onSelect, full, layoutKey, children }: { data: any; center?: string; selectedId?: string; onSelect: (n: any) => void; full?: boolean; layoutKey?: string; children?: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core>(undefined);
  const nodesRef = useRef(new Map<string, any>());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [tip, setTip] = useState<{ x: number; y: number; title: string; lines: string[] }>();
  const inJsdom = typeof navigator !== "undefined" && navigator.userAgent.includes("jsdom");

  useEffect(() => {
    if (!box.current || inJsdom) return;
    const cy = cytoscape({ container: box.current, style: style(), minZoom: 0.1, maxZoom: 4, wheelSensitivity: 0.3 });
    cy.on("tap", "node", (ev) => onSelectRef.current(nodesRef.current.get(ev.target.id())));
    cy.on("tap", (ev) => ev.target === cy && onSelectRef.current(null));
    cy.on("dbltap", "node", (ev) => go("graph", ev.target.id()));
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
        lines: [NODE_TYPE[n?.type] ?? "", (n?.source_classes ?? []).map((s: string) => SOURCE[s]).join("、"), `${ev.target.neighborhood().nodes().length} 个相连节点`].filter(Boolean),
      });
    });
    cy.on("mouseover", "edge", (ev) => {
      const e = ev.target;
      const p = ev.renderedPosition;
      e.addClass("lit");
      setTip({ x: Math.min(p.x + 14, cy.width() - 260), y: p.y + 14, title: `${CATEGORY[e.data("category")]?.label ?? ""}：${relLabel(e.data("rel"))}`, lines: [e.data("origin") === "ai_inferred" ? "AI 推断" : e.data("origin")] });
    });
    cy.on("mouseout", "node, edge", () => {
      cy.elements().removeClass("faded near lit");
      setTip(undefined);
    });
    cy.on("viewport", () => setTip(undefined));
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
    return () => {
      window.clearInterval(timer);
      cy.destroy();
    };
  }, [inJsdom]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !data) return;
    nodesRef.current = new Map(data.nodes.map((n: any) => [n.id, n]));
    const degree: Record<string, number> = {};
    for (const e of data.edges) {
      degree[e.source] = (degree[e.source] ?? 0) + 1;
      degree[e.target] = (degree[e.target] ?? 0) + 1;
    }
    const typeOf = new Map<string, string>(data.nodes.map((n: any) => [n.id, n.type]));
    cy.elements().remove();
    cy.add([
      ...data.nodes.map((n: any) => {
        const base = n.type === "page" || n.type === "entity" ? 24 : 16;
        const size = n.id === center ? 40 : base + Math.min(Math.sqrt(degree[n.id] ?? 0) * 5, 22);
        return {
          data: { id: n.id, label: (n.label ?? n.id).slice(0, 24), color: nodeColor(n.type), size },
          classes: [n.type, n.superseded ? "superseded" : "", n.id === center ? "center" : ""].join(" "),
        };
      }),
      ...data.edges.map((e: any, i: number) => {
        const inferred = e.origin === "ai_inferred" || e.origin === "candidate";
        const grad = !inferred && GRADIENT_CATEGORIES.has(e.category);
        return {
          data: {
            id: `e${i}:${e.id}`, source: e.source, target: e.target, rel: e.rel, category: e.category, origin: e.origin,
            grad: `${nodeColor(typeOf.get(e.source) ?? "")} ${nodeColor(typeOf.get(e.target) ?? "")}`,
          },
          classes: [`cat-${e.category}`, inferred ? "inferred" : "", grad ? "grad" : ""].join(" "),
        };
      }),
    ]);
    // 渐变两端的颜色逐条设置（渐变色不能从 data 映射）
    cy.edges(".grad").forEach((e) => {
      e.style("line-gradient-stop-colors", e.data("grad"));
    });
    // 斥力与边长参考旧版：节点越大斥力越强；提及这类细边拉得近一些，避免实体周围挤成一团。
    // 布局本身不做动画（动画靠逐帧回调，页面在后台时会停在半路，图挤成一团）；只让镜头从稍远处推近
    cy.layout({ ...LAYOUT, animate: false } as any).run();
    cy.resize();
    cy.fit(undefined, 48);
    // 节点很少时不放大过头
    if (cy.zoom() > 1.6) cy.zoom({ level: 1.6, position: { x: cy.width() / 2, y: cy.height() / 2 } as any });
    cy.center();
    if (!reducedMotion()) {
      const target = { zoom: cy.zoom(), pan: { ...cy.pan() } };
      cy.zoom({ level: target.zoom * 0.9, position: { x: cy.width() / 2, y: cy.height() / 2 } as any });
      cy.animate(target as any, { duration: 700, easing: "ease-out-cubic" });
    }
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
  }, [data, center]);

  // 进入、退出全屏或筛选收起展开（画布高度变了）后，重算画布大小并适配视图
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const t = window.setTimeout(() => {
      cy.resize();
      cy.fit(undefined, 40);
    }, 120);
    return () => window.clearTimeout(t);
  }, [full, layoutKey]);
  // 窗口大小变化时 cytoscape 不会自己重算画布
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => cyRef.current?.resize());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().unselect();
    if (selectedId) cy.getElementById(selectedId).select();
  }, [selectedId]);

  const relayout = () => cyRef.current?.layout({ ...LAYOUT, animate: false, randomize: true } as any).run();
  const fit = () => {
    const cy = cyRef.current;
    if (cy) cy.animate({ fit: { eles: cy.elements(), padding: 40 } } as any, { duration: reducedMotion() ? 0 : 350 });
  };

  return (
    <div className="graph-wrap">
      <div ref={box} className="graph" data-testid="graph" />
      <div className="graph-controls">
        <button type="button" className="small" onClick={relayout} title="重新随机排布一次">
          重新布局
        </button>
        <button type="button" className="small" onClick={fit} title="把全部节点缩放到画布内">
          适应窗口
        </button>
      </div>
      {children}
      {tip && (
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
    { selector: "edge.grad", style: { "line-fill": "linear-gradient" } },
    { selector: "edge.cat-mention", style: { width: 1, opacity: 0.4 } },
    { selector: "edge.inferred", style: { "line-style": "dashed", "line-dash-pattern": [5, 4], "line-color": INFERRED, "target-arrow-color": INFERRED, opacity: 0.85 } },
    { selector: "edge.lit", style: { width: 2.6, opacity: 1, "z-index": 9 } },
    { selector: ".faded", style: { opacity: 0.08 } },
  ];
  return rules as unknown as cytoscape.StylesheetJson;
}
