// 条目浏览（按类型、判断类型、作者、依据来源、对象筛选）与条目详情（含人工修改入口、框架页复核）。
// 原件的详情是原件页（Artifact.tsx）；对象（ent_…）的详情是对象页（设计稿 01 D-08）。
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { call } from "../api";
import { CopyEntryId, EntryName } from "../entryLabels";
import { EDGE_REL, ENTRY_KIND, ENTRY_STATUS, ENTRY_STATUS_HINT, EVENT_SCOPE, FRESHNESS, JUDGMENT_KIND, KIND_FILTER, LAPSE_REASON, LINK_REL, PAGE_TYPE, REVIEW, SOURCE, TIER, VERSION_ACTION_LABEL } from "../labels";
import { delegate, go, href, hrefWith, useUrlState } from "../router";
import { Icon } from "../shell/icons";
import { copyText } from "../shell/toast";
import { setCursor, useShortcuts } from "../shell/shortcuts";
import { Stamp, layerOf } from "../shell/Stamp";
import { EntryPreview, useCursorPreview } from "./EntryPreview";
import { Action, Chips, Coordinates, Empty, ErrorBox, FilterRow, IdLink, Loading, PageHead, PageInputNotice, Panel, ReferenceWarnings, RefText, Tag, Time, useLoad } from "../ui";
import { openReader } from "../reader/open";
import { ArtifactView } from "./Artifact";
import { ReviewBox } from "../review";

/* eslint-disable @typescript-eslint/no-explicit-any */

const PAGE_SIZE = 30;

// 筛选条件都在网址里（#/entries?kind=artifact&status=retired…）：刷新、后退、把网址发给别人都不丢
const ENTRY_FILTERS = { kind: "judgment", jkind: "", author: "", source: "", object: "", q: "", retired: "", outputs: "", scope: "operations", status: "", offset: "0" };

export function Entries() {
  const [f, setF] = useUrlState(ENTRY_FILTERS);
  // 换筛选条件时回到第一页
  const set = (patch: Partial<typeof ENTRY_FILTERS>) => setF({ offset: "0", ...patch });
  const k = f.kind || "judgment";
  const offset = Number(f.offset) || 0;
  const showRetired = f.retired === "1";
  const showOutputs = f.outputs === "1";
  const hasStatus = k !== "event" && k !== "read";
  const [stats] = useLoad(() => call<any>("stats.overview").catch(() => null), []);
  const [data, error] = useLoad(
    () =>
      call<any>("entries.list", {
        kind: k,
        judgment_kind: k === "judgment" ? (f.jkind || null) : null,
        author_kind: f.author || null,
        source_class: f.source || null,
        object: f.object.trim() || null,
        query: f.q.trim() || null,
        include_retired: showRetired,
        include_outputs: showOutputs,
        scope: f.scope || "operations",
        status: hasStatus ? (f.status || null) : null,
        limit: PAGE_SIZE,
        offset,
      }),
    [k, f.jkind, f.author, f.source, f.object, f.q, showRetired, showOutputs, f.scope, f.status, offset],
  );
  const [preview, setPreview] = useState<string | null>(null);
  useCursorPreview(useCallback((id: string) => setPreview((p) => (p ? id : p)), []));
  const statusOptions = Object.entries(ENTRY_STATUS).filter(([key]) => key !== "lapsed" || k !== "artifact");
  const changed = Object.entries(f).filter(([key, v]) => key !== "offset" && key !== "kind" && v !== (ENTRY_FILTERS as Record<string, string>)[key]).length;
  const l = stats?.ledger ?? {};
  const counts: Record<string, number | undefined> = { judgment: stats?.judgments?.total, artifact: l.artifacts, record: l.records, event: l.events };
  const LAYER_OF: Record<string, string> = { judgment: "judgment", artifact: "original", record: "original" };
  return (
    <div className="entries-page">
      <header className="page-head tight">
        <h1>条目</h1>
        <div className="segctl" role="tablist" aria-label="按类型看">
          {Object.entries(ENTRY_KIND).map(([key, text]) => (
            <button key={key} type="button" role="tab" aria-selected={k === key} className={k === key ? "on" : ""} onClick={() => { setPreview(null); set({ kind: key, status: "", jkind: "", source: "" }); }}>
              {LAYER_OF[key] && <Stamp layer={LAYER_OF[key]} small />}{text}
              {counts[key] != null && <span className="count">{counts[key]}</span>}
            </button>
          ))}
        </div>
        <div className="views" aria-label="常用视图">
          <span className="muted small-text">常用视图</span>
          <a className="tag" href={hrefWith("entries", { status: "superseded" })}>被替代的判断</a>
          <a className="tag" href={hrefWith("entries", { status: "lapsed" })}>依据已失效</a>
          <a className="tag" href={hrefWith("entries", { kind: "artifact", status: "retired", retired: "1" })}>已退役原件</a>
          <a className="tag" href={hrefWith("entries", { author: "human" })}>人写的判断</a>
        </div>
      </header>
      <div className={`entries-grid${preview ? " with-preview" : ""}`}>
        <aside className="filter-side panel" aria-label="筛选">
          {hasStatus && (
            <FilterGroup label="地位" options={statusOptions} value={f.status} onChange={(v) => set({ status: v })} hint={f.status ? ENTRY_STATUS_HINT[f.status] : undefined} />
          )}
          {k === "judgment" && <FilterGroup label="判断类型" options={Object.entries(KIND_FILTER)} value={f.jkind} onChange={(v) => set({ jkind: v })} />}
          {k === "event" && <FilterGroup label="日志" options={Object.entries(EVENT_SCOPE)} value={f.scope || "operations"} onChange={(v) => set({ scope: v || "operations" })} required />}
          {(k === "judgment" || k === "event") && (
            <FilterGroup label="作者" options={[["human", "人"], ["ai", "AI"], ["system", "系统"]]} value={f.author} onChange={(v) => set({ author: v })} />
          )}
          {(k === "judgment" || k === "artifact") && <FilterGroup label="依据来源" options={Object.entries(SOURCE)} value={f.source} onChange={(v) => set({ source: v })} />}
          <label className="field">
            <span>对象</span>
            <input value={f.object} onChange={(e) => set({ object: e.target.value })} placeholder="如 2号泵、P-102 或 ent_…" />
          </label>
          {k !== "event" && k !== "read" && (
            <div className="filter-group">
              <p className="filter-label">其他</p>
              {k === "artifact" ? (
                <>
                  <label className="check" title="已退役的原件内容不变、仍可打开和引用，只是默认不在列表和检索里出现">
                    <input type="checkbox" checked={showRetired} onChange={(e) => set({ retired: e.target.checked ? "1" : "" })} />
                    显示已退役的原件
                  </label>
                  <label className="check" title="运行产物（某次运行产出的文件）默认显示在那条过程日志与引用它的事实记录下">
                    <input type="checkbox" checked={showOutputs} onChange={(e) => set({ outputs: e.target.checked ? "1" : "" })} />
                    显示运行产物
                  </label>
                </>
              ) : (
                <label className="check" title="全部依据都来自已退役或已删除原件的条目默认隐藏；恢复或替换原件后自动重新出现">
                  <input type="checkbox" checked={showRetired} onChange={(e) => set({ retired: e.target.checked ? "1" : "" })} />
                  显示依据已全部失效的
                </label>
              )}
            </div>
          )}
          {changed > 0 && (
            <button type="button" onClick={() => setF({ ...ENTRY_FILTERS, kind: k })} title="筛选条件写在网址里，可以收藏或发给别人">
              清除 {changed} 项筛选
            </button>
          )}
          <p className="muted small-text">筛选写在网址里：刷新、后退、收藏都不丢。</p>
        </aside>
        <section className="results panel" aria-label="结果">
          <div className="results-head">
            <input type="search" className="grow" value={f.q} onChange={(e) => set({ q: e.target.value })} placeholder="在结果里找文字…" aria-label="在结果里找文字" />
            {data && <span className="muted small-text">{data.total} 条 · 最新在前</span>}
          </div>
          <ErrorBox error={error} />
          {!data && !error && <Loading />}
          {data && data.items.length === 0 && <Empty icon="filter">没有符合条件的条目。可以放宽左边的筛选，或按 Ctrl+K 直接按名称找。</Empty>}
          {data && (k === "event" ? (
            <SessionGroups items={data.items} />
          ) : (
            <ul className="erows">
              {data.items.map((e: any) => (
                <li
                  key={e.id}
                  data-nav-item={e.id}
                  className={`${e.superseded || e.retired || e.hidden ? "dim" : ""}${preview === e.id ? " picked" : ""}`}
                  onClick={(ev) => {
                    if ((ev.target as HTMLElement).closest("a, button")) return;
                    setCursor(ev.currentTarget, false);
                    setPreview(e.id);
                  }}
                >
                  <Stamp layer={e.layer} />
                  <div className="erow-main">
                    <a className="erow-title" href={href("entry", e.id)} data-key="open">{e.preview || <EntryName id={e.id} />}</a>
                    <div className="erow-meta">
                      {e.judgment_kind && <span className="tag">{JUDGMENT_KIND[e.judgment_kind]}</span>}
                      <Coordinates c={{ ...e, layer: undefined, judgment_kind: undefined }} />
                      <Time value={e.created_at} />
                    </div>
                  </div>
                  <RowActions id={e.id} onPreview={() => setPreview(e.id)} />
                </li>
              ))}
            </ul>
          ))}
          <div className="results-foot">
            <span><kbd>j</kbd> <kbd>k</kbd> 移动</span>
            <span><kbd>Space</kbd> 预览</span>
            <span><kbd>Enter</kbd> 打开</span>
            <span><kbd>r</kbd> 阅读</span>
            <span><kbd>v</kbd> 关系图</span>
            <span><kbd>c</kbd> 复制 ID</span>
            <span className="grow" />
            {data && data.total > PAGE_SIZE ? (
              <span className="pager">
                <button type="button" className="small" disabled={offset === 0} onClick={() => setF({ offset: String(Math.max(0, offset - PAGE_SIZE)) })}>上一页</button>
                <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} / {data.total}</span>
                <button type="button" className="small" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setF({ offset: String(offset + PAGE_SIZE) })}>下一页</button>
              </span>
            ) : data && <span>共 {data.total} 条</span>}
          </div>
        </section>
        {preview && <EntryPreview key={preview} id={preview} onClose={() => setPreview(null)} />}
      </div>
    </div>
  );
}

// 竖排的单选筛选：再点一次已选的项就取消（required 的组不能取消）
function FilterGroup({ label, options, value, onChange, hint, required }: { label: string; options: [string, string][]; value: string; onChange: (v: string) => void; hint?: string; required?: boolean }) {
  return (
    <div className="filter-group" role="radiogroup" aria-label={label}>
      <p className="filter-label">{label}</p>
      {options.map(([key, text]) => (
        <button key={key} type="button" role="radio" aria-checked={value === key} className={`fopt${value === key ? " on" : ""}`} onClick={() => onChange(value === key && !required ? "" : key)}>
          <i aria-hidden="true" />
          {text}
        </button>
      ))}
      {hint && <p className="muted small-text">{hint}</p>}
    </div>
  );
}

// 列表行内的常用操作：不用进详情就能预览、阅读、看关系、复制 ID（悬停或键盘光标停在这一行时出现）
export function RowActions({ id, onPreview }: { id: string; onPreview?: () => void }) {
  return (
    <span className="row-actions">
      {onPreview && (
        <button type="button" className="icon-button" title="在右侧预览（空格）" aria-label="预览" data-key="Space" onClick={onPreview}>
          <Icon name="open" />
        </button>
      )}
      <button type="button" className="icon-button" title="在阅读模式中打开（r）" aria-label="阅读" data-key="r" onClick={() => openReader(id.split("#")[0], id.split("#")[1])}>
        <Icon name="read" />
      </button>
      <a className="icon-button" href={href("graph", id.split("#")[0])} title="在关系图中以它为中心（v）" aria-label="关系图" data-key="v">
        <Icon name="graph" />
      </a>
      <button type="button" className="icon-button" title={`复制 ID：${id}（c）`} aria-label="复制 ID" data-key="c" onClick={() => void copyText(id, "已复制 ID")}>
        <Icon name="copy" />
      </button>
    </span>
  );
}

// 过程日志按会话归组（设计稿 07 D-10）：卡片上只有机械计数与时间范围，展开按顺序列出
function SessionGroups({ items }: { items: any[] }) {
  const groups: { session: string; items: any[] }[] = [];
  for (const e of items) {
    const last = groups[groups.length - 1];
    if (last && last.session === e.session_id) last.items.push(e);
    else groups.push({ session: e.session_id, items: [e] });
  }
  return (
    <div className="session-groups">
      {groups.map((g, i) => {
        const counts: Record<string, number> = {};
        for (const e of g.items) counts[e.op] = (counts[e.op] ?? 0) + 1;
        const sorted = [...g.items].sort((a, b) => a.seq - b.seq);
        return (
          <details key={`${g.session}:${i}`} className="session-group" open={groups.length === 1}>
            <summary>
              <span className="mono muted">{g.session}</span> · {g.items[0].actor_id} ·{" "}
              {Object.entries(counts)
                .map(([op, n]) => `${op} ${n}`)
                .join(" · ")}{" "}
              · <Time value={sorted[0].created_at} />
              {sorted.length > 1 && (
                <>
                  {" "}
                  – <Time value={sorted[sorted.length - 1].created_at} />
                </>
              )}
            </summary>
            <ul className="entry-list">
              {sorted.map((e) => (
                <li key={e.id}>
                  <div className="entry-head">
                    <span className="muted">#{e.seq}</span> <IdLink id={e.id} />
                    {e.system && <span className="tag muted">系统流水</span>}
                    {e.promoted_to?.map((r: string) => (
                      <span key={r} className="tag good">
                        已升级为 <IdLink id={r} />
                      </span>
                    ))}
                    <Time value={e.created_at} />
                  </div>
                  <div className="snippet">{e.preview}</div>
                  {(e.inputs?.length > 0 || e.outputs?.length > 0) && (
                    <div className="small-text">
                      {e.inputs?.length > 0 && (
                        <>
                          用到：
                          {e.inputs.map((a: string) => (
                            <IdLink key={a} id={a} />
                          ))}{" "}
                        </>
                      )}
                      {e.outputs?.length > 0 && (
                        <>
                          产出：
                          {e.outputs.map((a: string) => (
                            <IdLink key={a} id={a} />
                          ))}
                        </>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}

// ---------- 条目详情 ----------
// 判断、事实记录：上面是标题区和地位条，下面是证据链三栏——依据（它凭什么这么说）→ 本条 → 用到它的（它影响了谁）。
// 原件的正文是原件页（ArtifactView），框架页是 PageView，对象是对象页；它们共用标题区。
export function Entry({ id }: { id: string }) {
  const base = id.split("#")[0].split("@")[0];
  const anchor = id.includes("#") ? id.split("#")[1] : "";
  const isEntity = base.startsWith("ent_");
  const [data, error, reload] = useLoad(() => (id && !isEntity ? call("entry.get", { id }) : Promise.resolve(null)), [id]);
  const [expand, , reloadExpand] = useLoad(() => (id && !base.startsWith("pg_") && !isEntity ? call("entry.expand", { id }) : Promise.resolve(null)), [id]);
  const [page, pageError, reloadPage] = useLoad(() => (base.startsWith("pg_") ? call("page.get", { page: id }) : Promise.resolve(null)), [id]);
  if (!id) return <Empty icon="search">按 Ctrl+K 输入名称或 ID 打开一条，或从检索、条目列表、关系图中点开。</Empty>;
  if (isEntity) return <ObjectView id={base} />;
  const kind = data?.entry?.entry_kind;
  const chain = kind === "judgment" || kind === "record" || kind === "read" || kind === "event";
  const linksIn: any[] = (data?.links_in ?? []).filter((l: any) => kind !== "artifact" || !["produced", "consumed"].includes(l.rel));
  const reloadAll = () => {
    reload();
    reloadExpand();
    reloadPage();
  };
  return (
    <div className="entry-page">
      <ErrorBox error={error} />
      {!data && !error && <Loading rows={2} />}
      {data && (
        <>
          <header className="entry-hero">
            <Stamp layer={data.coordinates?.layer ?? layerOf(base)} large />
            <div className="grow">
              <h1>{kind === "judgment" ? <span className="entry-hero-text">{data.entry.data?.text}</span> : <EntryName id={id} />}</h1>
              <p className="muted small-text">
                {kind === "judgment" && <>{JUDGMENT_KIND[data.entry.kind] ?? data.entry.kind} · </>}
                {data.entry.author_id ?? data.entry.actor_id ?? data.entry.data?.captured_by ?? ""}
                {data.entry.session_id && <> · 会话 <span className="mono">{data.entry.session_id}</span></>} · <Time value={data.entry.created_at} />
              </p>
            </div>
            <div className="actions">
              {!base.startsWith("art_") && (
                <button type="button" className="primary" onClick={() => openReader(id.split("#")[0], anchor)} title="全屏阅读（r）">
                  <Icon name="read" size={15} />阅读 <kbd>r</kbd>
                </button>
              )}
              <a className="button" href={href("graph", base)} title="在关系图中以它为中心（v）">
                <Icon name="graph" size={15} />关系图 <kbd>v</kbd>
              </a>
              <CopyEntryId key={id} id={id} />
            </div>
          </header>
          {!base.startsWith("pg_") && (
            <section className="status-strip" aria-label="地位">
              <div><span className="label">地位</span><Coordinates c={{ ...data.coordinates, layer: undefined }} /></div>
            </section>
          )}
          <EntryKeys id={id} />
          {data.entry.entry_kind === "artifact" && data.coordinates?.retired &&
            <RetiredBanner artifactId={base} retirement={data.coordinates.retired} replacedBy={data.coordinates.replaced_by} reload={reload} />}
          <LapseNotice c={data.coordinates} />
          {chain ? (
            <div className="chain">
              <section className="chain-col" aria-label="依据">
                <h2>依据 <span className="muted">它凭什么这么说 · {(data.links_out ?? []).length}</span></h2>
                {(data.links_out ?? []).length ? (
                  (data.links_out ?? []).map((l: any) => <ChainCard key={l.id} link={l} field="dst_id" />)
                ) : (
                  <Empty compact icon="info">{kind === "judgment" ? "没有引用依据：可信度按\"仅推断\"计。" : "没有引用的条目。"}</Empty>
                )}
              </section>
              <span className="chain-flow" aria-hidden="true"><Icon name="chevron" /></span>
              <section className="chain-col main" aria-label="本条">
                <h2>本条 <span className="muted">全文与经过</span></h2>
                <div className="panel">
                  <EntryBody entry={data.entry} readSourceStatus={data.read_source_status} />
                  {["judgment", "artifact"].includes(data.entry.entry_kind) && !data.coordinates?.history && <ReviewBox key={`${base}:${data.coordinates?.retired ?? ""}:${data.coordinates?.review ?? ""}`} itemId={base} reload={reload} />}
                  <VersionPanel key={base} entry={data.entry} history={data.version_history} reload={reload} />
                </div>
                {expand && <Expand data={expand} />}
              </section>
              <span className="chain-flow" aria-hidden="true"><Icon name="chevron" /></span>
              <section className="chain-col" aria-label="用到它的">
                <h2>用到它的 <span className="muted">它影响了谁 · {linksIn.length}</span></h2>
                {linksIn.length ? linksIn.map((l: any) => <ChainCard key={l.id} link={l} field="src_id" />) : <Empty compact icon="info">还没有条目引用它。</Empty>}
                {data.edges?.length > 0 && <EdgeList edges={data.edges} />}
              </section>
            </div>
          ) : (
            <div className="split">
              <div>
                <Panel>
                  {data.entry.entry_kind === "artifact" ? (
                    <ArtifactView entry={data.entry} anchor={anchor} onChanged={reloadAll} />
                  ) : (
                    <EntryBody entry={data.entry} readSourceStatus={data.read_source_status} />
                  )}
                  <ErrorBox error={pageError} />
                  {page && <PageView page={page} reload={reloadAll} />}
                  {["judgment", "artifact"].includes(data.entry.entry_kind) && !data.coordinates?.history && <ReviewBox key={`${base}:${data.coordinates?.retired ?? ""}:${data.coordinates?.review ?? ""}`} itemId={base} reload={reload} />}
                  <VersionPanel key={base} entry={data.entry} history={data.version_history} reload={reload} />
                  {data.entry.entry_kind === "artifact" && <Outbound artifactId={base} outbound={data.outbound !== false} reload={reload} />}
                </Panel>
              </div>
              <aside>
                {expand && <Expand data={expand} />}
                {data.links_out?.length > 0 && <Links title="它指向" links={data.links_out} field="dst_id" />}
                {linksIn.length > 0 && <Links title="用到它的" links={linksIn} field="src_id" />}
                {data.entry.entry_kind === "artifact" && data.links_in?.some((l: any) => ["produced", "consumed"].includes(l.rel)) && (
                  <Links title="运行出处" links={data.links_in.filter((l: any) => ["produced", "consumed"].includes(l.rel))} field="src_id" />
                )}
                {data.edges?.length > 0 && <Panel title="关系图中的边"><EdgeList edges={data.edges} /></Panel>}
              </aside>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// 条目页的按键：r 阅读、v 关系图、c 复制 ID
function EntryKeys({ id }: { id: string }) {
  const base = id.split("#")[0].split("@")[0];
  useShortcuts({
    r: () => (base.startsWith("art_") ? false : void openReader(id.split("#")[0], id.split("#")[1])),
    v: () => go("graph", base),
    c: () => void copyText(id, "已复制 ID"),
  });
  return null;
}

// 证据链里的一张卡：对方的印、名称、关系、依据状态
function ChainCard({ link, field }: { link: any; field: "dst_id" | "src_id" }) {
  const other: string = link[field];
  return (
    <a className="chain-card" href={href("entry", other)} title={other}>
      <span className="chain-card-head">
        <Stamp layer={layerOf(other)} small />
        <span className="clip grow"><EntryName id={other} /></span>
        <span className="tag">{LINK_REL[link.rel] ?? link.rel}</span>
      </span>
      {(link.data?.condition || link.basis_status) && (
        <span className="chain-card-meta">
          <span className="mono muted">{other}</span>
          {link.data?.condition && <span className="muted small-text">条件：{link.data.condition}</span>}
          {link.data?.auto && <span className="muted small-text">系统连接</span>}
          <ReferenceWarnings status={link.basis_status} />
        </span>
      )}
    </a>
  );
}

function EdgeList({ edges }: { edges: any[] }) {
  return (
    <ul className="plain edge-list">
      {edges.map((e: any) => (
        <li key={e.id}>
          <IdLink id={e.src_id} /> —{EDGE_REL[e.rel] ?? e.rel}→ <IdLink id={e.dst_id} /> <span className="tag">{e.origin}</span> <span className="tag">{REVIEW[e.review] ?? e.review}</span>
        </li>
      ))}
    </ul>
  );
}

// 对象页（D-08）：关于这个对象的全部条目。约束在前，其次有争议的结论，其余按类型、时间；不含自动日志
const OBJECT_GROUPS: [string, string][] = [
  ["constraints", "有效约束与规定"],
  ["disputed", "有争议的结论"],
  ["conclusion", "结论"],
  ["process", "过程"],
  ["record", "事实记录"],
  ["artifact", "原件"],
  ["event", "过程日志"],
  ["system", "系统记录"],
];

function ObjectView({ id }: { id: string }) {
  const [view, error] = useLoad(() => call<any>("object.view", { object: id }), [id]);
  const [edges] = useLoad(() => call<any[]>("edge.list", { node_id: id }), [id]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const entity = view?.entity;
  return (
    <Panel
      title={
        <>
          <EntryName id={id} name={view?.name} /> {entity && <Tag>{entity.kind}</Tag>}
        </>
      }
      actions={<><CopyEntryId id={id} /> <a href={href("graph", id)}>在关系图中查看</a></>}
    >
      <ErrorBox error={error} />
      {entity?.data?.description && <p>{entity.data.description}</p>}
      {view?.pages?.length > 0 && (
        <p>
          框架页：
          {view.pages.map((p: any) => (
            <a key={p.id} href={href("entry", p.id)} className="tag accent">
              <EntryName id={p.id} name={p.title} />{p.freshness !== "valid" ? ` · ${FRESHNESS[p.freshness]}` : ""}
            </a>
          ))}
        </p>
      )}
      {view && <p className="muted">共 {view.total} 条（不含写判断、写框架页等自动日志；已升级为事实记录的过程日志只显示事实记录）</p>}
      {view &&
        OBJECT_GROUPS.map(([key, title]) => {
          const items: any[] = view.groups[key] ?? [];
          if (!items.length) return null;
          const limit = open[key] ? items.length : 8;
          return (
            <div key={key} className={`object-group ${key}`}>
              <h3>
                {title}（{items.length}）
              </h3>
              <ul className="entry-list">
                {items.slice(0, limit).map((t) => (
                  <li key={t.id} className={t.superseded ? "superseded" : ""}>
                    <div className="entry-head">
                      <IdLink id={t.id} /> <Coordinates c={t} /> <Time value={t.created_at} />
                    </div>
                    <div className="snippet">{t.preview}</div>
                  </li>
                ))}
              </ul>
              {items.length > limit && (
                <button type="button" className="link" onClick={() => setOpen({ ...open, [key]: true })}>
                  显示全部 {items.length} 条
                </button>
              )}
            </div>
          );
        })}
      {(edges ?? []).length > 0 && (
        <>
          <h3>相连的边（{edges?.length}）</h3>
          <ul className="plain">
            {(edges ?? []).map((e) => (
              <li key={e.id}>
                <IdLink id={e.src_id} /> —{e.rel}→ <IdLink id={e.dst_id} />
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}

function EntryBody({ entry, readSourceStatus }: { entry: any; readSourceStatus?: any }) {
  const d = entry.data ?? {};
  const kind = entry.entry_kind;
  return (
    <div className="entry">
      {kind === "judgment" && (
        <>
          <p className="meta">
            【{JUDGMENT_KIND[entry.kind] ?? entry.kind}】{entry.author_id} · <Time value={entry.created_at} />
            {d.external_author && ` · 原作者 ${d.external_author}（提取者 ${d.extracted_by}）`}
          </p>
          <RefText text={d.text} />
          {d.conditions && <p>条件：{d.conditions}</p>}
          {d.reopen_condition && <p>重开条件：{d.reopen_condition}</p>}
          {d.revise_reason && <p className="muted">改写原因：{d.revise_reason}</p>}
        </>
      )}
      {kind === "record" && (
        <>
          <p className="meta">
            方法：{d.method ?? "—"} · 边界：{entry.boundary} · 缺口：{(d.gaps ?? []).join("、") || "无"}
          </p>
          <pre>{d.result}</pre>
        </>
      )}
      {kind === "read" && (
        <>
          <p className="meta">
            读取日志：{entry.actor_id} 在 <Time value={entry.created_at} /> 读了{" "}
            <IdLink id={`${entry.artifact_id}#${(d.anchors ?? [])[0] ?? `seg-${(d.segments ?? [0])[0]}`}`} /> 的 {(d.anchors ?? d.segments ?? []).length} 段
          </p>
          <ReferenceWarnings status={readSourceStatus} />
          <p className="muted small-text">读取记录是自动日志；在原件页的段落旁可以看到每段被谁读过、被哪些判断引用。</p>
          <pre>{d.excerpt}</pre>
        </>
      )}
      {kind === "event" && (
        <>
          <p className="meta">
            {entry.op} · {entry.actor_id} · 会话 {entry.session_id} #{entry.seq}
          </p>
          {d.output && <pre>{d.output}</pre>}
        </>
      )}
    </div>
  );
}

function Links({ title, links, field }: { title: string; links: any[]; field: string }) {
  return (
    <Panel title={title}>
      <ul className="plain">
        {links.map((l) => (
          <li key={l.id}>
            <span className="tag" title={l.rel}>
              {LINK_REL[l.rel] ?? l.rel}
            </span>{" "}
            <IdLink id={l[field]} /> {l.data?.condition && `（条件：${l.data.condition}）`}
            <ReferenceWarnings status={l.basis_status} />
            {l.data?.auto && <span className="muted small-text">（系统连接）</span>}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// 附属区（D-09）：按类型命名并以表格显示；原始数据收进开关
const SOURCE_ROWS: [string, string][] = [
  ["title", "标题"],
  ["kind", "类型"],
  ["source_class", "依据来源"],
  ["external_tier", "外部细分"],
  ["storage", "保存方式"],
  ["filename", "文件名"],
  ["size", "大小"],
  ["path", "原位置"],
  ["captured_by", "登记人"],
  ["session_id", "会话"],
  ["created_at", "登记时间"],
  ["version_of", "旧版本"],
  ["newer_versions", "新版本"],
];

function Expand({ data }: { data: any }) {
  const interpretations: any[] = data.interpretations ?? [];
  const grouped: Record<string, any[]> = {};
  for (const i of interpretations) (grouped[i.judgment_kind ?? "other"] ??= []).push(i);
  return (
    <Panel title="背景">
      {data.source && (
        <>
          <h3>来源</h3>
          <KvTable rows={sourceRows(data.source)} />
          <Raw value={data.source} />
        </>
      )}
      {data.conditions && (
        <>
          <h3>条件</h3>
          <KvTable rows={conditionRows(data.conditions)} />
          {data.promoted_to?.length > 0 && (
            <p className="small-text">
              已升级为事实记录：
              {data.promoted_to.map((r: string) => (
                <IdLink key={r} id={r} />
              ))}
            </p>
          )}
          <Raw value={data.conditions} />
        </>
      )}
      {data.neighbors?.length > 0 && (
        <>
          <h3>同一来源的前后内容</h3>
          {data.neighbors.map((n: any) =>
            n.op ? (
              <div key={n.id} className="small-text">
                <IdLink id={n.id} /> {n.op}
              </div>
            ) : (
              <pre key={n.anchor ?? n.ordinal}>{n.text}</pre>
            ),
          )}
        </>
      )}
      {data.objects?.length > 0 && (
        <>
          <h3>涉及的对象</h3>
          <div className="tags">
            {data.objects.map((o: any) => (
              <a key={o.id} className="tag accent object-tag" href={href("entry", o.id)} title={o.id}>
                {o.name}
                {o.kind ? `（${o.kind}）` : ""} · {o.count} 条
              </a>
            ))}
          </div>
        </>
      )}
      {interpretations.length > 0 && (
        <>
          <h3>引用了它的判断（解读，不是原件内容）</h3>
          {Object.entries(grouped).map(([k, list]) => (
            <div key={k}>
              <div className="muted small-text">
                {JUDGMENT_KIND[k] ?? k}（{list.length}）
              </div>
              <ul className="plain">
                {list.map((s: any) => (
                  <li key={s.judgment_id + s.rel + s.via}>
                    {s.rel !== "used" && <span className="tag">{s.rel}</span>} <IdLink id={s.judgment_id} />
                    {s.via !== data.entry.id && (
                      <div className="small-text muted">
                        依据 <IdLink id={s.via} />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      )}
    </Panel>
  );
}

function sourceRows(src: any): [string, ReactNode][] {
  const rows: [string, ReactNode][] = [];
  for (const [key, label] of SOURCE_ROWS) {
    let v = src[key];
    if (key === "path" && !v) v = src.uri;
    if (v === null || v === undefined || (Array.isArray(v) && !v.length)) {
      if (["title", "path", "captured_by"].includes(key)) rows.push([label, <span className="muted">未记录</span>]);
      continue;
    }
    if (key === "source_class") v = SOURCE[v] ?? v;
    if (key === "external_tier") v = TIER[v] ?? v;
    if (key === "storage") v = v === "managed" ? "受管保存（复制进数据目录）" : "外部引用（只登记路径和指纹）";
    if (key === "size") v = formatSize(v);
    if (key === "created_at") v = <Time value={v} />;
    if (key === "version_of") v = <IdLink id={v} />;
    if (key === "newer_versions") v = (v as string[]).map((x) => <IdLink key={x} id={x} />);
    rows.push([label, v]);
  }
  for (const [k, v] of Object.entries(src.metadata ?? {})) rows.push([k, plain(v)]);
  return rows;
}

function conditionRows(c: any): [string, ReactNode][] {
  const rows: [string, ReactNode][] = [];
  const entries = Object.entries(c.conditions ?? {});
  if (!entries.length) rows.push(["条件", <span className="muted">未记录</span>]);
  for (const [k, v] of entries) rows.push([k, plain(v)]);
  if ("method" in c) rows.push(["方法", c.method ? plain(c.method) : <span className="muted">未记录</span>]);
  if (c.boundary) rows.push(["边界", c.boundary]);
  if ("gaps" in c) rows.push(["缺口", c.gaps?.length ? c.gaps.join("；") : "无"]);
  for (const [k, v] of Object.entries(c.input ?? {})) rows.push([`输入 · ${k}`, plain(v)]);
  if (c.from) rows.push(["来自", <IdLink id={c.from} />]);
  return rows;
}

function plain(v: unknown): ReactNode {
  if (v === null || v === undefined || v === "") return <span className="muted">未记录</span>;
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join("、");
  if (typeof v === "object") return <code>{JSON.stringify(v)}</code>;
  const text = String(v);
  return /^(art|evt|rec|rd|jdg|ent|pg)_[0-9A-Z]{26}/.test(text) ? <IdLink id={text} /> : text;
}

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function KvTable({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <table className="kv">
      <tbody>
        {rows.map(([k, v], i) => (
          <tr key={i}>
            <th>{k}</th>
            <td>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Raw({ value }: { value: unknown }) {
  return (
    <details className="raw">
      <summary>原始数据</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

// 依据失效（设计稿 07 D-02）：全部依据失效的条目已隐藏；部分失效的列出失效的依据
function LapseNotice({ c }: { c: any }) {
  if (!c?.hidden && !c?.lapsed_basis?.length) return null;
  const gaps: any[] = c.hidden ?? c.lapsed_basis;
  return (
    <div className="notice retired">
      <strong>{c.hidden ? "依据已全部失效，已隐藏" : "部分依据已失效"}</strong>：
      {gaps.map((g) => (
        <span key={g.ref}>
          {" "}
          <IdLink id={g.ref} />（{LAPSE_REASON[g.reason] ?? g.reason}）
        </span>
      ))}
      。{c.hidden ? "它不在条目列表、默认检索和关系图里；恢复或替换原件后自动重新出现。" : "这条依据作为缺口计入当前地位；替换原件后按段落指纹重新核对。"}
    </div>
  );
}

// 已退役的原件（设计稿 02 D-12）：顶部说明退役记录。退役是原件的状态历史，不是判断（2.0.0a14）。
// 退役后可以替换、可以彻底删除（设计稿 07 D-03、D-04）
function RetiredBanner({ artifactId, retirement, replacedBy, reload }: { artifactId: string; retirement: string; replacedBy?: string | null; reload: () => void }) {
  const [rec] = useLoad(() => call<any>("entry.get", { id: retirement }), [retirement]);
  const [reason, setReason] = useState("");
  const [replacement, setReplacement] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const e = rec?.entry;
  return (
    <div className="notice retired">
      <div>
        <strong>已退役</strong>：{e ? e.data?.reason ?? e.data?.text : "…"}
        {e && (
          <>
            （{e.actor_id ?? e.author_id} · <Time value={e.created_at} />）
          </>
        )}
        {(replacedBy ?? e?.data?.replaced_by) && (
          <>
            ，替代它的原件 <IdLink id={replacedBy ?? e.data.replaced_by} />
          </>
        )}
        。内容不变，仍可阅读和引用；默认不在条目列表和检索里出现。只引用它的条目已一并隐藏。
      </div>
      <div className="row tight">
        <input className="grow" value={reason} onChange={(ev) => setReason(ev.target.value)} placeholder="理由（撤销退役、替换都要写）" />
        <Action label="撤销退役" disabled={!reason.trim()} run={async () => (await call("artifact.retire", { artifact_id: artifactId, action: "restore", reason }), setReason(""), reload())} />
      </div>
      <div className="row tight">
        <input className="grow" value={replacement} onChange={(ev) => setReplacement(ev.target.value)} placeholder="替代它的原件 art_…" />
        <Action
          label="替换"
          disabled={!reason.trim() || !replacement.trim()}
          run={async () => (await call("artifact.replace", { artifact_id: artifactId, replacement: replacement.trim(), reason }), setReason(""), setReplacement(""), reload())}
        />
      </div>
      <div className="row tight">
        <Action label="彻底删除…" className="danger" run={async () => setPreview(await call("artifact.delete_preview", { artifact_id: artifactId }))} />
        <span className="muted small-text">先列出全部影响，确认后才删除</span>
      </div>
      {preview && <DeletePreview preview={preview} onDone={() => (setPreview(null), go("entries"))} onCancel={() => setPreview(null)} />}
    </div>
  );
}

const PURGE_TABLE: Record<string, string> = {
  artifacts: "原件",
  reads: "读取记录",
  extractions: "抽取记录",
  links: "关系",
  events: "系统流水",
  reviews: "复核记录",
  retirements: "退役与恢复记录",
  replacements: "替换记录",
  artifact_policies: "外发标记",
};
const PURGE_OP: Record<string, string> = {
  "artifact.register": "登记",
  "artifact.read": "读取",
  "artifact.retire": "退役",
  "artifact.restore": "撤销退役",
  "artifact.replace": "替换",
  "extraction.": "抽取",
  search: "检索命中",
};
const FILE_FATE: Record<string, string> = {
  deleted: "内容文件从数据目录删除。",
  shared: "内容文件还被别的原件使用，保留。",
  external: "这是外部引用的原件，磁盘上的原文件不动，只删除登记。",
};

// 彻底删除的确认对话框（设计稿 07 D-04、D-05）：盖住页面的对话框，影响逐项写出标题，按钮在固定的底栏
function DeletePreview({ preview, onDone, onCancel }: { preview: any; onDone: () => void; onCancel: () => void }) {
  const d = preview.delete;
  const [typed, setTyped] = useState("");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  const entry = (x: any, extra?: ReactNode) => (
    <li key={x.id}>
      <div className="purge-item-head">
        <IdLink id={x.id} /> <span className="tag">{x.kind ? (JUDGMENT_KIND[x.kind] ?? x.kind) : (ENTRY_KIND[x.entry_kind] ?? x.entry_kind)}</span>
        {x.author_kind === "human" && <span className="tag bad">人写</span>}
        {extra}
      </div>
      {x.preview && <div className="purge-item-text">{x.preview}</div>}
    </li>
  );
  const removed = [...d.judgments, ...d.records];
  const others = Object.entries(d.counts as Record<string, number>).filter(([t]) => !["judgments", "records", "artifacts", "events"].includes(t));
  const ops = Object.entries((d.events_by_op ?? {}) as Record<string, number>);
  const opLabel = (op: string) => PURGE_OP[op] ?? Object.entries(PURGE_OP).find(([k]) => k.endsWith(".") && op.startsWith(k))?.[1] ?? op;
  const name = preview.artifact.title ?? preview.artifact.id;
  const tail = preview.artifact.id.slice(-6).toUpperCase();
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal purge" role="dialog" aria-modal="true" aria-label="彻底删除" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>彻底删除「{name}」</h3>
          <p className="bad-text">{preview.note}。</p>
        </header>
        <div className="modal-body">
          <section>
            <h4>删除的原件</h4>
            <p>
              <IdLink id={preview.artifact.id} name={name} />
              <br />
              <span className="muted">{FILE_FATE[preview.artifact.file] ?? ""}</span>
            </p>
          </section>
          <section>
            <h4>一并删除、只依据它的判断与事实记录（{removed.length}）</h4>
            {removed.length ? <ul className="purge-list">{removed.map((x: any) => entry(x))}</ul> : <p className="muted">没有。没有判断或事实记录只依据这份原件。</p>}
          </section>
          <section>
            <h4>保留、指向它的地方显示为"已删除"（{preview.keep_with_gap.length}）</h4>
            {preview.keep_with_gap.length ? (
              <ul className="purge-list">
                {preview.keep_with_gap.map((x: any) =>
                  entry(
                    x,
                    <span className="muted small-text">
                      {" "}
                      关系：{(x.rels ?? []).map((r: string) => LINK_REL[r] ?? r).join("、")}
                      {x.lapsed && "；部分依据失效，计入缺口"}
                    </span>,
                  ),
                )}
              </ul>
            ) : (
              <p className="muted">没有。</p>
            )}
          </section>
          <section>
            <h4>标为"输入已变化"的框架页（{preview.pages.length}）</h4>
            {preview.pages.length ? (
              <ul className="purge-list">
                {preview.pages.map((pg: any) => (
                  <li key={pg.id}>
                    <div className="purge-item-head">
                      <IdLink id={pg.id} name={pg.title} /> <span className="tag">{PAGE_TYPE[pg.type] ?? pg.type}</span>
                    </div>
                    <div className="purge-item-text muted">
                      {pg.inputs_total} 项输入里有 {pg.inputs_hit.length} 项被删除；页面保留，需要重新综合。
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">没有。</p>
            )}
          </section>
          <section>
            <h4>删除的关系图的边（{d.edges.length}）</h4>
            {d.edges.length ? (
              <ul className="purge-list">
                {d.edges.map((e: any) => (
                  <li key={e.id}>
                    <IdLink id={e.src_id} name={e.src} /> <span className="tag">{EDGE_REL[e.rel] ?? LINK_REL[e.rel] ?? e.rel}</span> <IdLink id={e.dst_id} name={e.dst} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">没有。</p>
            )}
          </section>
          <section>
            <h4>删除的系统记录</h4>
            <p className="muted">
              系统流水 {d.counts.events ?? 0} 条{ops.length > 0 && `（${ops.map(([op, n]) => `${opLabel(op)} ${n}`).join("、")}）`}
              {others.map(([t, n]) => `；${PURGE_TABLE[t] ?? t} ${n} 条`).join("")}
              {d.blobs > 0 && `；文件 ${d.blobs} 个`}。
            </p>
          </section>
        </div>
        <footer>
          <label className="purge-confirm">
            输入原件 ID 的最后 6 位 <code>{tail}</code> 确认：
            <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
          </label>
          <div className="row tight">
            <button type="button" onClick={onCancel}>
              取消
            </button>
            <Action
              label="彻底删除（不可撤销）"
              className="danger solid"
              disabled={typed.trim().toUpperCase() !== tail}
              run={async () => (await call("artifact.delete", { artifact_id: preview.artifact.id, confirm: preview.confirm }), onDone())}
            />
          </div>
        </footer>
      </div>
    </div>
  );
}

// 人工修改入口：更正、撤回、原件有缺陷（草图 §4）、原件退役（设计稿 02 D-11）。只在工作台提供。
// "修改"声明原条目错了或不再需要；"复核"只看依据是否成立，在上面的复核框里（设计稿 04 D-17）
function VersionPanel({ entry, history, reload }: { entry: any; history?: any; reload: () => void }) {
  const [reason, setReason] = useState("");
  const [text, setText] = useState("");
  const [path, setPath] = useState("");
  const [cites, setCites] = useState<string | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [confirmId, setConfirmId] = useState("");
  if (!history) return null;
  const current = history.versions.find((v: any) => v.id === entry.id);
  if (!current) return null;
  const effective = history.versions.find((v: any) => v.id === history.current_id);
  const canReactivate = current.number < history.latest_number && !current.retired && !current.withdrawn
    && (!effective || effective.number < current.number);
  const isArtifact = entry.entry_kind === "artifact";
  const isJudgment = entry.entry_kind === "judgment";
  const legacyHistory = entry.entry_kind === "judgment" && ["review", "correction", "retraction", "defect", "retirement"].includes(entry.kind);
  const state = (action: string) => async () => {
    await call("entry.version_state", { id: entry.id, action, reason });
    setReason("");
    setPreview(null);
    reload();
  };
  return (
    <section className="amend">
      <h3>版本与变更历史</h3>
      <p className="muted">
        本页引用固定在第 {current.number} 版。{effective ? <> 当前有效版：第 {effective.number} 版 <IdLink id={effective.id} />。</> : " 当前无有效版。"}
      </p>
      <ol>
        {history.versions.map((v: any) => (
          <li key={v.id}>
            第 {v.number} 版 <IdLink id={v.id} />{v.number === history.latest_number && "（最新发布）"}
            {v.id === history.current_id && " · 当前有效"}
            {v.retired && " · 已退役"}{v.withdrawn && " · 已撤回"}{v.defective && " · 有缺陷"}
            {v.reason && <p>{v.reason}</p>}
            {v.id !== entry.id && v.entry && (
              <details>
                <summary>查看本版正文和依据</summary>
                {v.entry.data?.corrected_text && <p><strong>核实内容：</strong> {v.entry.data.corrected_text}</p>}
                <EntryBody entry={v.entry} />
                {v.cites?.map((ref: string) => <span key={ref}> <IdLink id={ref} /></span>)}
              </details>
            )}
            {v.changes.map((c: any) => <p key={c.id}><Time value={c.created_at} /> · {VERSION_ACTION_LABEL[c.data.action] ?? c.data.action} · {c.data.reason}</p>)}
          </li>
        ))}
      </ol>
      {entry.data?.corrected_text && <p><strong>本版核实内容：</strong> {entry.data.corrected_text}</p>}
      {!legacyHistory && (
        <details className="amend-form">
          <summary>
            修改本版：{isArtifact ? "登记新版、" : "追加更正版本、"}撤回、标记缺陷、退役{current.retired && !isArtifact ? "、销毁" : ""}
            <span className="muted small-text"> · 都是追加记录，原版本保留</span>
          </summary>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="变更理由（必填）" />
          {(entry.id === history.latest_id || entry.id === history.current_id) && (
            <>
              <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="新版正文或核实后的内容" />
              {isJudgment && <input value={cites ?? current.cites?.join("，") ?? ""}
                onChange={(e) => setCites(e.target.value)} placeholder="新版依据 ID（逗号分隔）" />}
              {isArtifact && <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="新版文件完整路径（与正文二选一）" />}
              <Action label="追加更正版本" disabled={!reason.trim() || !(Boolean(text.trim()) !== Boolean(path.trim()))}
                run={async () => {
                  const version = await call("entry.correct", { id: entry.id, reason, text: text.trim() ? text : null,
                    path: path.trim() || null, cites: cites === null ? null : cites.split(/[,，]/).map((id) => id.trim()).filter(Boolean) });
                  go("entry", version.id);
                }} />
            </>
          )}
          <div className="row tight">
            <Action label={current.withdrawn ? "取消撤回" : "撤回本版"} disabled={!reason.trim()}
              run={state(current.withdrawn ? "unwithdraw" : "withdraw")} />
            {canReactivate && <Action label="设为重新生效" disabled={!reason.trim()} run={state("reactivate")} />}
            <Action label={current.defective ? "取消缺陷标记" : "标记本版有缺陷"} disabled={!reason.trim()}
              run={state(current.defective ? "undefect" : "defect")} />
            <Action label={current.retired ? "取消退役" : "退役本版"} disabled={!reason.trim()}
              run={state(current.retired ? "restore" : "retire")} />
            {current.retired && !isArtifact && <Action label="预览销毁本版" className="danger"
              run={async () => { setConfirmId(""); setPreview(await call("entry.destroy_preview", { id: entry.id })); }} />}
          </div>
        </details>
      )}
      {preview && (
        <div className="notice retired">
          <p>销毁第 {current.number} 版后不可恢复。现有引用仍指向本版，显示版本不可用。</p>
          {preview.keep_with_gap.map((item: any) => <p key={item.id}>保留的引用项 <IdLink id={item.id} /></p>)}
          {preview.pages.map((item: any) => <p key={item.id}>需要重新核对的页面 <IdLink id={item.id} /></p>)}
          <input value={confirmId} onChange={(e) => setConfirmId(e.target.value)} placeholder="输入本版 ID 确认" />
          <Action label="彻底销毁本版" className="danger" disabled={confirmId.trim() !== entry.id}
            run={async () => {
              await call("entry.destroy", { id: entry.id, confirm: preview.confirm });
              go("entry", history.versions.filter((v: any) => v.id !== entry.id).at(-1)?.id ?? "");
              reload();
            }} />
        </div>
      )}
    </section>
  );
}

function Outbound({ artifactId, outbound, reload }: { artifactId: string; outbound: boolean; reload: () => void }) {
  const [reason, setReason] = useState("");
  return (
    <div className="amend">
      <h3>外发</h3>
      <p className="muted small-text">
        {outbound
          ? "现在可以外发：定期巡检时，它的原文可能交给云端的巡检员、复核员 agent。"
          : "已标为不外发：巡检包里只列它的编号和规则检查结果，不含原文；巡检运行里读不到它。平时的 AI 会话不受影响。"}
      </p>
      <div className="row tight">
        <input className="grow" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="理由（可空）" />
        <Action label={outbound ? "标为不外发" : "恢复可外发"} run={async () => (await call("artifact.policy", { artifact_id: artifactId, outbound: !outbound, reason }), setReason(""), reload())} />
      </div>
    </div>
  );
}

export function rederivePrompt(p: any): string {
  const target = p.title ? `${p.id}（${p.title}）` : p.id;
  return `请重新综合框架页 ${target}。用 page_get 读取它的当前版本和输入清单，用 entry_get / search 核对现有输入及相关的新判断、更正与撤回，然后用 page_write 写出新版本（沿用当前 slug），inputs 列出实际依据的条目。不要修改判断层。`;
}

function PageView({ page, reload }: { page: any; reload: () => void }) {
  return (
    <div className="page">
      <h3>
        {PAGE_TYPE[page.page.type] ?? page.page.type} · 第 {page.version} 版（共 {page.versions.length} 版）
        {page.version === page.page.head_version
          ? ` · ${REVIEW[page.page.review]} · ${FRESHNESS[page.page.freshness]}`
          : " · 历史版本"}
      </h3>
      {page.versions.length > 1 && (
        <p className="row tight">
          版本：
          {page.versions.map((v: any) => (
            <a key={v.version} href={href("entry", `${page.page.id}@${v.version}`)} className={v.version === page.version ? "on-version" : ""}>
              {v.version}
            </a>
          ))}
        </p>
      )}
      <PageInputNotice page={page} />
      <RefText text={page.body} />
      <h4>输入清单</h4>
      <ul className="plain">
        {page.inputs.map((i: string) => (
          <li key={i}>
            <IdLink id={i} />
          </li>
        ))}
      </ul>
      <ReviewBox itemId={page.page.id} reload={reload} />
      <div className="row tight">
        <button type="button" onClick={() => delegate(rederivePrompt(page.page))}>
          {page.page.freshness === "valid" ? "再次交给 Agent 综合" : "交给 Agent 重新综合"}
        </button>
      </div>
    </div>
  );
}
