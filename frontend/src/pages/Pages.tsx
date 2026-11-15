// 框架页：默认按新鲜度分三栏（输入已变化、待复核、最新），也可以切回表格；按类型、复核状态、时效筛选，按标题过滤。
// 输入已变化的可以交给 agent 重新综合（由人点了才开始）。筛选写在网址里（#/pages?fresh=inputs_changed）。
import { useMemo } from "react";
import { call } from "../api";
import { FRESHNESS, PAGE_TYPE, REVIEW } from "../labels";
import { delegate, href, list, unlist, useUrlState } from "../router";
import { openReader } from "../reader/open";
import { Stamp } from "../shell/Stamp";
import { Empty, ErrorBox, IdLink, Loading, Tag, Time, useLoad, usePoll } from "../ui";
import { rederivePrompt } from "./Entries";

/* eslint-disable @typescript-eslint/no-explicit-any */

const PAGE_FILTERS = { types: "", reviews: "", fresh: "", q: "", view: "board" };

export function Pages() {
  const [pages, error, reload] = useLoad(() => call<any[]>("page.list", {}), []);
  usePoll(reload);
  const [f, setF] = useUrlState(PAGE_FILTERS);
  const types = list(f.types);
  const reviews = list(f.reviews);
  const fresh = list(f.fresh);
  const all = pages ?? [];
  const count = (key: string): Record<string, number> => all.reduce((m: Record<string, number>, p: any) => ({ ...m, [p[key]]: (m[p[key]] ?? 0) + 1 }), {} as Record<string, number>);
  const shown = useMemo(
    () =>
      all.filter(
        (p: any) =>
          (types.length ? types.includes(p.type) : p.type !== "point") &&  // 要点默认不列（设计稿 15 D-35）
          (!reviews.length || reviews.includes(p.review)) &&
          (!fresh.length || fresh.includes(p.freshness)) &&
          (!f.q.trim() || p.title.toLowerCase().includes(f.q.trim().toLowerCase())),
      ),
    [all, f.types, f.reviews, f.fresh, f.q],
  );
  const stale = all.filter((p: any) => p.freshness !== "valid" && p.type !== "point");
  const toggle = (key: "types" | "reviews" | "fresh", cur: string[], v: string) =>
    setF({ [key]: unlist(cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]) } as Partial<typeof PAGE_FILTERS>);
  const typeCounts = count("type");
  const changedCol = shown.filter((p: any) => p.freshness !== "valid");
  const reviewCol = shown.filter((p: any) => p.freshness === "valid" && ["ai_generated", "rejected"].includes(p.review));
  const freshCol = shown.filter((p: any) => p.freshness === "valid" && !["ai_generated", "rejected"].includes(p.review));
  const filtered = types.length + reviews.length + fresh.length + (f.q ? 1 : 0);
  return (
    <div className="pages-page">
      <header className="page-head tight">
        <Stamp layer="framework" large />
        <div>
          <h1>框架页</h1>
          <p className="lede">AI 把原件和判断综合成的页面。可以随时重新生成，永远不能作依据。</p>
        </div>
        <div className="views">
          <div className="segctl" role="group" aria-label="种类">
            <button type="button" aria-pressed={!types.length} className={!types.length ? "on" : ""} onClick={() => setF({ types: "" })}>全部页面 <span className="count">{all.filter((p: any) => p.type !== "point").length}</span></button>
            {Object.entries(PAGE_TYPE).filter(([k]) => typeCounts[k]).map(([k, t]) => (
              <button key={k} type="button" aria-pressed={types.includes(k)} className={types.includes(k) ? "on" : ""} onClick={() => toggle("types", types, k)}>{t} <span className="count">{typeCounts[k]}</span></button>
            ))}
          </div>
          <div className="segctl" role="radiogroup" aria-label="视图">
            <button type="button" role="radio" aria-checked={f.view !== "table"} className={f.view !== "table" ? "on" : ""} onClick={() => setF({ view: "board" })}>分栏</button>
            <button type="button" role="radio" aria-checked={f.view === "table"} className={f.view === "table" ? "on" : ""} onClick={() => setF({ view: "table" })}>表格</button>
          </div>
          <input type="search" value={f.q} onChange={(e) => setF({ q: e.target.value })} placeholder="按标题找…" aria-label="按标题找" />
          {stale.length > 0 && (
            <button type="button" onClick={() => delegate(`以下框架页的输入已变化，请逐页重新综合（每页用 page_get 读取当前版本和输入清单，再用 page_write 写新版本）：\n${stale.map((p: any) => `- ${p.id}（${p.title}）`).join("\n")}`)}>
              全部交给 agent 重新综合（{stale.length}）
            </button>
          )}
        </div>
      </header>
      {(fresh.length > 0 || reviews.length > 0) && (
        <p className="result-note">
          <span>已按{fresh.length ? `时效（${fresh.map((k) => FRESHNESS[k] ?? k).join("、")}）` : ""}{reviews.length ? `复核（${reviews.map((k) => REVIEW[k] ?? k).join("、")}）` : ""}筛选</span>
          <button type="button" className="link" onClick={() => setF({ ...PAGE_FILTERS, view: f.view })}>清除 {filtered} 项筛选</button>
        </p>
      )}
      <ErrorBox error={error} />
      {!pages && !error && <Loading rows={3} />}
      {pages && shown.length === 0 && <Empty icon="pages">{all.length ? "没有符合条件的页面。" : "还没有框架页。AI 用 page_write 综合后会出现在这里。"}</Empty>}
      {pages && shown.length > 0 && (f.view === "table" ? (
        <PageTable pages={shown} />
      ) : (
        <div className="board">
          <Column title="输入已变化" tone="warn" note="依据变了，内容可能过时" pages={changedCol} empty="没有输入已变化的页面。" big />
          <Column title="待复核" tone="" note="AI 写的，还没人看过" pages={reviewCol} empty="没有待复核的页面。" />
          <Column title="最新" tone="good" note="输入没有变化" pages={freshCol} empty="没有。" compact />
        </div>
      ))}
    </div>
  );
}

function Column({ title, tone, note, pages, empty, big, compact }: { title: string; tone: string; note: string; pages: any[]; empty: string; big?: boolean; compact?: boolean }) {
  return (
    <section className="board-col" aria-label={title}>
      <h2><span className={`tag ${tone}`}>{title}</span><span className="num">{pages.length}</span><span className="muted small-text">{note}</span></h2>
      {pages.length === 0 && <Empty compact icon="check">{empty}</Empty>}
      {compact ? (
        pages.length > 0 && (
          <ul className="panel board-list">
            {pages.map((p) => (
              <li key={p.id} data-nav-item={p.id}>
                <Stamp layer="framework" small />
                <a href={href("entry", p.id)} className="clip grow" title={p.id}>{p.title}</a>
                <span className="muted small-text">{REVIEW[p.review] ?? p.review}</span>
                <button type="button" className="small" onClick={() => delegate(rederivePrompt(p))}>再次综合</button>
              </li>
            ))}
          </ul>
        )
      ) : (
        pages.map((p) => (
          <article key={p.id} className={`panel page-card${big ? " strong" : ""}`} data-nav-item={p.id}>
            <div className="page-card-head">
              <Stamp layer="framework" small />
              <a href={href("entry", p.id)} className="clip grow" title={p.id}><b>{p.title}</b></a>
              <span className="tag">{PAGE_TYPE[p.type] ?? p.type}</span>
            </div>
            <p className="muted small-text">
              第 {p.head_version} 版 · {REVIEW[p.review] ?? p.review} · 更新于 <Time value={p.updated_at} />
              {p.freshness !== "valid" && <> · <span className="warn-text">{FRESHNESS[p.freshness] ?? p.freshness}</span></>}
            </p>
            <div className="row tight">
              <button type="button" className={big ? "small primary" : "small"} onClick={() => delegate(rederivePrompt(p))}>
                {p.freshness === "valid" ? "再次综合" : "交给 Agent 重新综合"}
              </button>
              <button type="button" className="small" onClick={() => openReader(p.id)}>阅读</button>
              <a className="button small" href={href("graph", p.id)}>关系图</a>
            </div>
          </article>
        ))
      )}
    </section>
  );
}

function PageTable({ pages }: { pages: any[] }) {
  return (
    <div className="panel">
      <table>
        <thead>
          <tr>
            <th>页面</th>
            <th>类型</th>
            <th>版本</th>
            <th>复核</th>
            <th>时效</th>
            <th>更新</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {pages.map((p: any) => (
            <tr key={p.id} data-nav-item={p.id}>
              <td><IdLink id={p.id} name={p.title} /></td>
              <td>{PAGE_TYPE[p.type] ?? p.type}</td>
              <td>{p.head_version}</td>
              <td><Tag tone={p.review === "human_reviewed" ? "good" : p.review === "rejected" ? "bad" : "warn"}>{REVIEW[p.review]}</Tag></td>
              <td><Tag tone={p.freshness === "valid" ? "good" : "warn"}>{FRESHNESS[p.freshness]}</Tag></td>
              <td><Time value={p.updated_at} /></td>
              <td className="cell-actions">
                <a href={href("graph", p.id)}>关系图</a>
                <button type="button" className="small" onClick={() => delegate(rederivePrompt(p))}>
                  {p.freshness === "valid" ? "再次综合" : "交给 Agent 重新综合"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
