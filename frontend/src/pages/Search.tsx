// 检索：模式切换（复用 / 探索）、排序（相关度 / 地位）、按列、依据来源、判断类型筛选，可选显示被替代的与过程日志。
// 名次只表示相关度（设计稿 06 D-09）；每条显示地位说明、命中的段落和未展示的命中数。
import { useEffect, useMemo, useState } from "react";
import { call } from "../api";
import { JUDGMENT_KIND, KIND_FILTER, LAYER, SOURCE, kindGroup } from "../labels";
import { href } from "../router";
import { Chips, Coordinates, Empty, ErrorBox, FilterRow, IdLink, Panel } from "../ui";
import { FidelityTag } from "./Artifact";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Mode = "reuse" | "explore";
type Order = "relevance" | "status";

export function Search() {
  const [query, setQuery] = useState("");
  const [objects, setObjects] = useState("");
  const [mode, setMode] = useState<Mode[]>(["reuse"]);
  const [order, setOrder] = useState<Order[]>(["relevance"]);
  const [layers, setLayers] = useState<string[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [kinds, setKinds] = useState<string[]>([]);
  const [showSuperseded, setShowSuperseded] = useState(true);
  const [includeLog, setIncludeLog] = useState(false);
  const [includeRetired, setIncludeRetired] = useState(false);
  // 过程内容：复用模式默认显示、探索模式默认隐藏（D-15）；切换模式时跟着变，之后可以手动改
  const [includeProcess, setIncludeProcess] = useState(true);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResult(
        await call("search", {
          query,
          mode: mode[0] ?? "reuse",
          order: order[0] ?? "relevance",
          objects: splitList(objects),
          layers: layers.length ? layers : null,
          include_log: includeLog,
          include_retired: includeRetired,
          include_process: includeProcess,
          limit: 60,
        }),
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // 模式、列、过程日志会改变后端的检索范围：已检索过时自动重新检索
  useEffect(() => {
    if (result) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode.join(), order.join(), layers.join(), includeLog, includeProcess, includeRetired]);

  // 依据来源、判断类型、是否显示被替代的在前端筛选：不改变后端的排序与地位规则
  const hits = useMemo(() => {
    let items: any[] = result?.hits ?? [];
    if (sources.length) items = items.filter((h) => sources.some((s) => (h.source_classes ?? []).includes(s)));
    // 选了判断类型就只看判断：原件和框架没有判断类型，一并隐去
    if (kinds.length) items = items.filter((h) => h.layer === "judgment" && kinds.includes(kindGroup(h.judgment_kind)));
    if (!showSuperseded) items = items.filter((h) => !h.superseded);
    return items;
  }, [result, sources, kinds, showSuperseded]);
  const count = (key: string, f: (h: any) => boolean) => [key, (result?.hits ?? []).filter(f).length] as const;
  const layerCounts = Object.fromEntries(Object.keys(LAYER).map((k) => count(k, (h) => h.layer === k)));
  const sourceCounts = Object.fromEntries(Object.keys(SOURCE).map((k) => count(k, (h) => (h.source_classes ?? []).includes(k))));
  const kindCounts = Object.fromEntries(Object.keys(KIND_FILTER).map((k) => count(k, (h) => h.layer === "judgment" && kindGroup(h.judgment_kind) === k)));

  return (
    <Panel title="检索">
      <form
        className="row search-bar"
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
      >
        <input className="grow" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="检索词，或设备编号、错误码" />
        <input value={objects} onChange={(e) => setObjects(e.target.value)} placeholder="限定对象（逗号分隔，可选）" />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "…" : "检索"}
        </button>
      </form>
      <div className="filter-rows">
        <FilterRow label="模式">
          <Chips<Mode>
            all={null}
            options={[
              ["reuse", "复用：三列都返回"],
              ["explore", "探索：不返回框架页，避免被已有结论锚定"],
            ]}
            value={mode}
            onChange={(v) => {
              const next = v.length ? v : (["reuse"] as Mode[]);
              setMode(next);
              // 探索模式不返回框架页："列"里去掉框架；其余筛选保留用户的选择
              if (next[0] === "explore") setLayers((ls) => ls.filter((l) => l !== "framework"));
              setIncludeProcess(next[0] !== "explore");
            }}
          />
        </FilterRow>
        <FilterRow label="排序">
          <Chips<Order>
            all={null}
            options={[
              ["relevance", "相关度"],
              ["status", "地位：依据来源 → 综合程度 → 复核"],
            ]}
            value={order}
            onChange={(v) => setOrder(v.length ? v : (["relevance"] as Order[]))}
          />
        </FilterRow>
        <FilterRow label="列">
          <Chips
            options={Object.entries(LAYER)}
            value={layers}
            onChange={setLayers}
            multi
            counts={result ? layerCounts : undefined}
            disabled={mode[0] === "explore" ? { framework: "探索模式不返回框架页" } : {}}
          />
        </FilterRow>
        <FilterRow label="依据来源">
          <Chips options={Object.entries(SOURCE)} value={sources} onChange={setSources} multi counts={result ? sourceCounts : undefined} />
        </FilterRow>
        <FilterRow label="判断类型">
          <Chips
            options={Object.entries(KIND_FILTER)}
            value={kinds}
            onChange={setKinds}
            multi
            counts={result ? kindCounts : undefined}
          />
          {kinds.length > 0 && <span className="muted filter-note">已选判断类型：只显示判断，原件与框架不显示</span>}
        </FilterRow>
        <FilterRow label="其他">
          <label className="check">
            <input type="checkbox" checked={showSuperseded} onChange={(e) => setShowSuperseded(e.target.checked)} />
            显示已被替代的（排在最后）
          </label>
          <label className="check" title="提问、尝试、停下的路线。探索模式默认隐藏，以免被已有思路带偏">
            <input type="checkbox" checked={includeProcess} onChange={(e) => setIncludeProcess(e.target.checked)} />
            包含过程内容
          </label>
          <label className="check">
            <input type="checkbox" checked={includeLog} onChange={(e) => setIncludeLog(e.target.checked)} />
            包含过程日志
          </label>
          <label className="check" title="已退役的原件内容不变，只是默认不在检索里出现（设计稿 02 D-12）；勾选后排在最后">
            <input type="checkbox" checked={includeRetired} onChange={(e) => setIncludeRetired(e.target.checked)} />
            包含已退役的原件
          </label>
        </FilterRow>
      </div>
      <ErrorBox error={error} />
      {result && (
        <>
          {result.constraints.length > 0 && (
            <div className="constraints">
              <h3>相关的有效约束、决定和指令</h3>
              {result.constraints.map((c: any) => (
                <div key={c.id}>
                  <IdLink id={c.id} /> 【{JUDGMENT_KIND[c.kind]}】{c.text}
                </div>
              ))}
            </div>
          )}
          <p className="muted">
            显示 {hits.length} / {result.hits.length} 条（共命中 {result.total}）。
            {order[0] === "status" ? '按"依据来源 → 综合程度 → 复核"逐级排序，不打分。' : "按相关度排序；可靠与否看每条的地位说明。"}
            被替代、已退役的排在最后。
          </p>
          {(result.hints ?? []).filter((t: string) => !t.startsWith("名次只表示")).length > 0 && (
            <ul className="muted hints">
              {result.hints
                .filter((t: string) => !t.startsWith("名次只表示"))
                .map((t: string) => (
                  <li key={t}>{t}</li>
                ))}
            </ul>
          )}
          {hits.length === 0 && <Empty>没有符合筛选条件的结果</Empty>}
          {hits.map((h: any) => (
            <div key={h.id} className={`hit layer-${h.layer}${h.superseded || h.retired ? " superseded" : ""}`}>
              <div className="hit-head">
                <IdLink id={h.cite_as ?? (h.anchor ? `${h.id}#${h.anchor}` : h.id)} /> <Coordinates c={h} />
                {h.unit_label && h.unit !== "doc" && <span className="tag">{h.unit_label}</span>}
                <FidelityTag fidelity={h.fidelity && h.fidelity !== "copy" ? h.fidelity : null} />
                {h.verified && <span className="tag good">已确认</span>}
                <a className="graph-link" href={href("graph", h.id)} title="在关系图中以它为中心">
                  关系图
                </a>
              </div>
              {h.status_note && <div className="muted small">{h.status_note}</div>}
              {(h.passages?.length ? h.passages : [{ text: h.text }]).map((p: any, i: number) => (
                <div key={i} className="snippet">
                  {p.context && <span className="muted small">{p.context} · </span>}
                  {p.cite_as && i > 0 && (
                    <>
                      <IdLink id={p.cite_as} />{" "}
                    </>
                  )}
                  {p.text}
                </div>
              ))}
              {h.more_matches > 0 && <div className="muted small">同一条目还有 {h.more_matches} 处命中未展示</div>}
            </div>
          ))}
        </>
      )}
    </Panel>
  );
}

export function splitList(s: string): string[] | null {
  const items = s
    .split(/[,，]/)
    .map((x) => x.trim())
    .filter(Boolean);
  return items.length ? items : null;
}
