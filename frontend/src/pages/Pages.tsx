// 框架页：按类型、复核状态、时效筛选，按标题过滤；输入已变化的可以一键交给 agent 重新综合。
import { useMemo, useState } from "react";
import { call } from "../api";
import { FRESHNESS, PAGE_TYPE, REVIEW } from "../labels";
import { delegate, href } from "../router";
import { Chips, Empty, ErrorBox, FilterRow, Panel, Tag, Time, useLoad, usePoll } from "../ui";
import { rederivePrompt } from "./Entries";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Pages() {
  const [pages, error, reload] = useLoad(() => call<any[]>("page.list", {}), []);
  usePoll(reload);
  const [types, setTypes] = useState<string[]>([]);
  const [reviews, setReviews] = useState<string[]>([]);
  const [fresh, setFresh] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const all = pages ?? [];
  const count = (key: string) => Object.fromEntries(all.reduce((m: Map<string, number>, p: any) => m.set(p[key], (m.get(p[key]) ?? 0) + 1), new Map()));
  const shown = useMemo(
    () =>
      all.filter(
        (p: any) =>
          (!types.length || types.includes(p.type)) &&
          (!reviews.length || reviews.includes(p.review)) &&
          (!fresh.length || fresh.includes(p.freshness)) &&
          (!query.trim() || p.title.toLowerCase().includes(query.trim().toLowerCase())),
      ),
    [all, types, reviews, fresh, query],
  );
  const stale = all.filter((p: any) => p.freshness !== "valid");
  return (
    <Panel
      title="框架页"
      actions={
        stale.length > 0 && (
          <button type="button" onClick={() => delegate(`以下框架页的输入已变化，请逐页重新综合（每页用 page_get 读取当前版本和输入清单，再用 page_write 写新版本）：\n${stale.map((p: any) => `- ${p.id}（${p.title}）`).join("\n")}`)}>
            全部交给 agent 重新综合（{stale.length}）
          </button>
        )
      }
    >
      <p className="muted">框架回答"现在该信什么"，可以再生，永远不能作为依据。</p>
      <div className="filter-rows">
        <FilterRow label="类型">
          <Chips multi options={Object.entries(PAGE_TYPE)} value={types} onChange={setTypes} counts={count("type")} />
        </FilterRow>
        <FilterRow label="时效">
          <Chips multi options={Object.entries(FRESHNESS)} value={fresh} onChange={setFresh} counts={count("freshness")} />
        </FilterRow>
        <FilterRow label="复核">
          <Chips multi options={Object.entries(REVIEW).filter(([k]) => k !== "rule")} value={reviews} onChange={setReviews} counts={count("review")} />
        </FilterRow>
        <FilterRow label="标题">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="包含文字" />
        </FilterRow>
      </div>
      <ErrorBox error={error} />
      {shown.length === 0 ? (
        <Empty>没有符合条件的页面</Empty>
      ) : (
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
            {shown.map((p: any) => (
              <tr key={p.id}>
                <td>
                  <a href={href("entry", p.id)}>{p.title}</a>
                </td>
                <td>{PAGE_TYPE[p.type] ?? p.type}</td>
                <td>{p.head_version}</td>
                <td>
                  <Tag tone={p.review === "human_reviewed" ? "good" : p.review === "rejected" ? "bad" : "warn"}>{REVIEW[p.review]}</Tag>
                </td>
                <td>
                  <Tag tone={p.freshness === "valid" ? "good" : "warn"}>{FRESHNESS[p.freshness]}</Tag>
                </td>
                <td>
                  <Time value={p.updated_at} />
                </td>
                <td className="cell-actions">
                  <a href={href("graph", p.id)}>关系图</a>
                  {p.freshness !== "valid" && (
                    <button type="button" className="small" onClick={() => delegate(rederivePrompt(p))}>
                      交给 agent
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
