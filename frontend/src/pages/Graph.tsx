// 关系图（参考旧版）：按节点类型、关系类别筛选；中心 + 展开层数；双击换中心；隐藏与恢复；悬停说明；图例。
// 框架层的图可以再生，这里只读：确认或驳回 AI 推断的边在条目页与待决策页完成。
import cytoscape from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { call } from "../api";
import { CATEGORY, NODE_COLOR, NODE_TYPE, REVIEW, SOURCE } from "../labels";
import { go, href } from "../router";
import { Chips, Coordinates, Empty, ErrorBox, FilterRow, IdLink, Panel, useLoad } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

type View = { hops: number; nodeTypes: string[]; categories: string[]; hideSuperseded: boolean; query: string; excluded: string[] };
const DEFAULT_VIEW: View = {
  hops: 2,
  nodeTypes: ["artifact", "judgment", "page", "entity"],
  categories: [],
  hideSuperseded: false,
  query: "",
  excluded: [],
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

  return (
    <div ref={page} className={`split wide-left graph-page${full ? " full" : ""}`}>
      <Panel
        title="关系图"
        actions={
          <>
            <button type="button" onClick={toggleFull} title={full ? "退出全屏（Esc）" : "图铺满屏幕，筛选与详情变成浮层"}>
              {full ? "退出全屏" : "全屏"}
            </button>
            {center && (
              <button type="button" onClick={() => go("graph")}>
                取消中心
              </button>
            )}
            <button type="button" onClick={() => setView(DEFAULT_VIEW)}>
              重置筛选
            </button>
          </>
        }
      >
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
        <ErrorBox error={error} />
        {data?.truncated && <div className="notice">节点过多，只显示了相连最多的一部分；请缩小范围或设置中心。</div>}
        {shown && shown.nodes.length === 0 ? (
          <Empty>没有符合条件的节点。</Empty>
        ) : (
          <Canvas data={shown} center={center} selectedId={selected?.id} onSelect={setSelected} full={full} />
        )}
        <p className="muted">
          {shown?.nodes.length ?? 0} 个节点、{shown?.edges.length ?? 0} 条关系{center ? `，以 ${center} 为中心展开 ${view.hops} 层` : ""}。单击查看，双击以它为中心；节点颜色是所在的列，红色虚线边框表示已被替代，橙色虚线连线是 AI 推断、尚未复核。
        </p>
      </Panel>
      <aside>
        <Focus
          node={selected}
          edges={(shown?.edges ?? []).filter((e: any) => selected && (e.source === selected.id || e.target === selected.id))}
          onHide={(id) => {
            set({ excluded: [...view.excluded, id] });
            setSelected(null);
          }}
        />
      </aside>
    </div>
  );
}

function countBy(items: any[], key: (x: any) => string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const i of items) out[key(i)] = (out[key(i)] ?? 0) + 1;
  return out;
}

function Focus({ node, edges, onHide }: { node: any; edges: any[]; onHide: (id: string) => void }) {
  if (!node) {
    return (
      <Panel title="图例">
        <Legend />
      </Panel>
    );
  }
  return (
    <Panel title={NODE_TYPE[node.type] ?? node.type}>
      <p className="focus-title">{node.label}</p>
      <p>
        <IdLink id={node.id} />
      </p>
      <Coordinates c={node} />
      <div className="row">
        <a className="button" href={href("entry", node.id)}>
          打开条目
        </a>
        <a className="button" href={href("graph", node.id)}>
          以它为中心
        </a>
        <button type="button" onClick={() => onHide(node.id)}>
          隐藏
        </button>
      </div>
      <h3>相连的关系（{edges.length}）</h3>
      <ul className="plain">
        {edges.map((e) => (
          <li key={e.id}>
            <i className="swatch" style={{ background: CATEGORY[e.category]?.color }} />
            {e.source === node.id ? "→" : "←"} <span className="tag">{e.rel}</span> <IdLink id={e.source === node.id ? e.target : e.source} />
            {e.origin === "ai_inferred" && <span className="tag warn">AI 推断·{REVIEW[e.review] ?? e.review}</span>}
          </li>
        ))}
      </ul>
      <Panel title="图例" className="flat">
        <Legend />
      </Panel>
    </Panel>
  );
}

function Legend() {
  return (
    <ul className="legend">
      {Object.entries(NODE_TYPE).map(([k, text]) => (
        <li key={k}>
          <i className="dotmark" style={{ background: NODE_COLOR[k] }} />
          {text}
        </li>
      ))}
      {Object.entries(CATEGORY).map(([k, c]) => (
        <li key={k} title={c.hint}>
          <svg width="28" height="8" aria-hidden="true">
            <line x1="0" y1="4" x2="28" y2="4" stroke={c.color} strokeWidth="2.5" strokeDasharray={c.dash.join(" ")} />
          </svg>
          {c.label}
        </li>
      ))}
      <li>
        <i className="dotmark superseded-mark" />
        已被替代（红色虚线边框）
      </li>
      <li className="muted">依据来源：{Object.values(SOURCE).join(" / ")}（见右侧坐标）</li>
    </ul>
  );
}

function Canvas({ data, center, selectedId, onSelect, full }: { data: any; center?: string; selectedId?: string; onSelect: (n: any) => void; full?: boolean }) {
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
      const near = ev.target.closedNeighborhood();
      cy.elements().addClass("faded");
      near.removeClass("faded");
      setTip({
        x: Math.min(p.x + 14, cy.width() - 260),
        y: p.y + 14,
        title: n?.label ?? ev.target.id(),
        lines: [NODE_TYPE[n?.type] ?? "", (n?.source_classes ?? []).map((s: string) => SOURCE[s]).join("、"), `${ev.target.neighborhood().nodes().length} 个相连节点`].filter(Boolean),
      });
    });
    cy.on("mouseover", "edge", (ev) => {
      const e = ev.target;
      const p = ev.renderedPosition;
      setTip({ x: Math.min(p.x + 14, cy.width() - 260), y: p.y + 14, title: `${CATEGORY[e.data("category")]?.label ?? ""}：${e.data("rel")}`, lines: [e.data("origin") === "ai_inferred" ? "AI 推断" : e.data("origin")] });
    });
    cy.on("mouseout", "node, edge", () => {
      cy.elements().removeClass("faded");
      setTip(undefined);
    });
    cy.on("viewport", () => setTip(undefined));
    cyRef.current = cy;
    return () => cy.destroy();
  }, [inJsdom]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !data) return;
    nodesRef.current = new Map(data.nodes.map((n: any) => [n.id, n]));
    cy.elements().remove();
    cy.add([
      ...data.nodes.map((n: any) => ({
        data: { id: n.id, label: (n.label ?? n.id).slice(0, 24), color: NODE_COLOR[n.type] ?? "#999", size: n.id === center ? 34 : n.type === "page" || n.type === "entity" ? 26 : 18 },
        classes: [n.type, n.superseded ? "superseded" : "", n.id === center ? "center" : ""].join(" "),
      })),
      ...data.edges.map((e: any, i: number) => ({
        data: { id: `e${i}:${e.id}`, source: e.source, target: e.target, rel: e.rel, category: e.category, origin: e.origin },
        classes: [`cat-${e.category}`, e.origin === "ai_inferred" || e.origin === "candidate" ? "inferred" : ""].join(" "),
      })),
    ]);
    // 斥力与边长参考旧版：节点越大斥力越强；提及这类细边拉得近一些，避免实体周围挤成一团
    cy.layout({
      name: "cose",
      animate: false,
      nodeRepulsion: (n: any) => 60000 + (n.data("size") ?? 18) * 3000,
      idealEdgeLength: (e: any) => (e.hasClass("cat-mention") ? 50 : 80),
      edgeElasticity: () => 120,
      nodeOverlap: 24,
      gravity: 0.3,
      numIter: 1500,
      componentSpacing: 60,
      padding: 30,
    } as any).run();
    cy.fit(undefined, 30);
    // 节点很少时不放大过头，节点很多时也保证标签能读
    if (cy.zoom() > 1.6) cy.zoom({ level: 1.6, position: { x: cy.width() / 2, y: cy.height() / 2 } as any });
    cy.center();
  }, [data, center]);

  // 进入、退出全屏或窗口大小变化后，重算画布大小并适配视图
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const t = window.setTimeout(() => {
      cy.resize();
      cy.fit(undefined, 30);
    }, 120);
    return () => window.clearTimeout(t);
  }, [full]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().unselect();
    if (selectedId) cy.getElementById(selectedId).select();
  }, [selectedId]);

  return (
    <div className="graph-wrap">
      <div ref={box} className="graph" data-testid="graph" />
      <div className="graph-controls">
        <button type="button" onClick={() => cyRef.current?.fit(undefined, 30)}>
          适应窗口
        </button>
      </div>
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
  const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const text = dark ? "#e5e7eb" : "#1f2328";
  const rules: any[] = [
    {
      selector: "node",
      style: {
        "background-color": "data(color)",
        width: "data(size)",
        height: "data(size)",
        label: "data(label)",
        "font-size": 10,
        color: text,
        "text-valign": "bottom",
        "text-margin-y": 4,
        "text-wrap": "ellipsis",
        "text-max-width": "120px",
        "min-zoomed-font-size": 7,
        "text-background-color": dark ? "#181b22" : "#ffffff",
        "text-background-opacity": 0.85,
        "text-background-padding": "2px",
        "text-background-shape": "roundrectangle",
      },
    },
    { selector: "node.page", style: { shape: "round-rectangle" } },
    { selector: "node.entity", style: { shape: "hexagon" } },
    { selector: "node.artifact, node.record, node.read", style: { shape: "round-tag" } },
    { selector: "node.superseded", style: { "border-width": 2, "border-style": "dashed", "border-color": "#d64545", opacity: 0.65 } },
    { selector: "node.center", style: { "border-width": 4, "border-color": "#2563eb", "font-weight": 600 } },
    { selector: "node:selected", style: { "border-width": 3, "border-color": "#2563eb", "min-zoomed-font-size": 0 } },
    {
      selector: "edge",
      style: { width: 1.6, "curve-style": "bezier", "line-color": "#9ca3af", "target-arrow-color": "#9ca3af", "target-arrow-shape": "vee", "arrow-scale": 0.8, opacity: 0.85 },
    },
    ...Object.entries(CATEGORY).map(([k, c]) => ({
      selector: `edge.cat-${k}`,
      style: { "line-color": c.color, "target-arrow-color": c.color, "target-arrow-shape": c.arrow, "line-style": c.dash.length ? "dashed" : "solid", "line-dash-pattern": c.dash.length ? c.dash : [1, 0] },
    })),
    { selector: "edge.cat-mention", style: { width: 1, opacity: 0.5 } },
    { selector: "edge.inferred", style: { "line-style": "dashed", "line-dash-pattern": [5, 4], "line-color": "#d08a2c", "target-arrow-color": "#d08a2c" } },
    { selector: ".faded", style: { opacity: 0.12 } },
  ];
  return rules as unknown as cytoscape.StylesheetJson;
}

