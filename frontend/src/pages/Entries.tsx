// 条目浏览（筛选与检索页、关系图同名同序：依据来源 → 类型 → 现状 → 说明，设计稿 10 D-26）与条目详情
// （坐标、两栏关系区、版本历史与人的处置、框架页复核）。
// 原件的详情是原件页（Artifact.tsx）；对象（ent_…）的详情是对象页（设计稿 01 D-08）。
import { Fragment, useCallback, useEffect, useState, type ReactNode } from "react";
import { call } from "../api";
import { CopyEntryId, EntryName } from "../entryLabels";
import { AUTHOR, authorNote, CATEGORIES, ENTRY_KIND, ENTRY_STATUS, ENTRY_STATUS_HINT, EVENT_SCOPE, FRESHNESS, JUDGMENT_KIND, KIND, KIND_FILTER, LINK_REL, PAGE_TYPE, REVIEW, SOURCE, TIER, VALIDITY, VERSION_ACTION_LABEL, relPhrase } from "../labels";
import { delegate, go, href, hrefWith, useUrlState } from "../router";
import { Icon } from "../shell/icons";
import { copyText } from "../shell/toast";
import { setCursor, useShortcuts } from "../shell/shortcuts";
import { Stamp, layerOf } from "../shell/Stamp";
import { EntryPreview, useCursorPreview } from "./EntryPreview";
import { Action, Chips, Coordinates, Empty, ErrorBox, FilterRow, IdLink, Loading, PageHead, PageInputNotice, Panel, ReferenceWarnings, RefText, type RelationNote, stripMarkers, Tag, Time, useLoad } from "../ui";
import { openReader } from "../reader/open";
import { ArtifactView } from "./Artifact";
import { ClaimBody, CiteGroup, CiteGroups, citeOfRelation, groupCites, notesFromCites, type ClaimCite } from "../claim";
import { ReviewBox } from "../review";
import { EntryActions } from "../EntryActions";

/* eslint-disable @typescript-eslint/no-explicit-any */

const PAGE_SIZE = 30;

// 筛选条件都在网址里（#/entries?kind=artifact&status=retired…）：刷新、后退、把网址发给别人都不丢
const ENTRY_FILTERS = { kind: "judgment", jkind: "", author: "", source: "", object: "", q: "", retired: "", outputs: "", scope: "operations", status: "", quoted: "", offset: "0" };

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
        quoted: k === "judgment" && f.quoted ? true : null,
        limit: PAGE_SIZE,
        offset,
      }),
    [k, f.jkind, f.author, f.source, f.object, f.q, showRetired, showOutputs, f.scope, f.status, f.quoted, offset],
  );
  const [preview, setPreview] = useState<string | null>(null);
  useCursorPreview(useCallback((id: string) => setPreview((p) => (p ? id : p)), []));
  const statusOptions = Object.entries(ENTRY_STATUS).filter(([key]) =>
    k === "judgment" ? key !== "retired" : k === "artifact" ? !["lapsed", "withdrawn"].includes(key) : !["withdrawn", "retired"].includes(key));
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
          <a className="tag" href={hrefWith("entries", { status: "replaced" })}>被替代的判断</a>
          <a className="tag" href={hrefWith("entries", { quoted: "1" })}>转述的结论</a>
          <a className="tag" href={hrefWith("entries", { status: "lapsed" })}>依据已失效</a>
          <a className="tag" href={hrefWith("entries", { kind: "artifact", status: "retired", retired: "1" })}>已退役原件</a>
          <a className="tag" href={hrefWith("entries", { author: "human" })}>人写的判断</a>
        </div>
      </header>
      <div className={`entries-grid${preview ? " with-preview" : ""}`}>
        <aside className="filter-side panel" aria-label="筛选">
          {(k === "judgment" || k === "artifact") && <FilterGroup label="依据来源" options={Object.entries(SOURCE)} value={f.source} onChange={(v) => set({ source: v })} />}
          {k === "judgment" && <FilterGroup label="类型" options={Object.entries(KIND_FILTER)} value={f.jkind} onChange={(v) => set({ jkind: v })} />}
          {k === "event" && <FilterGroup label="日志" options={Object.entries(EVENT_SCOPE)} value={f.scope || "operations"} onChange={(v) => set({ scope: v.split(",").pop() || "operations" })} required />}
          {hasStatus && (
            <FilterGroup label="现状" options={statusOptions} value={f.status} onChange={(v) => set({ status: v })} hint={f.status && !f.status.includes(",") ? ENTRY_STATUS_HINT[f.status] : undefined} />
          )}
          {(k === "judgment" || k === "event") && (
            <FilterGroup label="说明 · 作者" options={Object.entries(AUTHOR)} value={f.author} onChange={(v) => set({ author: v })} />
          )}
          {k === "judgment" && (
            <label className="check" title="转述外部材料（有原作者）的结论">
              <input type="checkbox" checked={f.quoted === "1"} onChange={(e) => set({ quoted: e.target.checked ? "1" : "" })} />
              只看转述的
            </label>
          )}
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
                <label className="check" title="已撤回、依据全部失效的条目默认隐藏；取消撤回、恢复或替换原件后自动重新出现">
                  <input type="checkbox" checked={showRetired} onChange={(e) => set({ retired: e.target.checked ? "1" : "" })} />
                  显示已撤回、依据已失效的
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
                  className={`${(e.state?.validity ?? "current") !== "current" ? "dim" : ""}${preview === e.id ? " picked" : ""}`}
                  onClick={(ev) => {
                    if ((ev.target as HTMLElement).closest("a, button")) return;
                    setCursor(ev.currentTarget, false);
                    setPreview(e.id);
                  }}
                >
                  <Stamp layer={e.layer} />
                  <div className="erow-main">
                    <a className="erow-title" href={href("entry", e.id)} data-key="open" title={e.preview}>{e.title || e.preview || <EntryName id={e.id} />}</a>
                    <div className="erow-meta">
                      <Coordinates c={e} />
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

// 竖排的多选筛选：点一下选中，再点取消；选中多项是"或"（required 的组至少留一项）；值用逗号连起来写进网址
function FilterGroup({ label, options, value, onChange, hint, required }: { label: string; options: [string, string][]; value: string; onChange: (v: string) => void; hint?: string; required?: boolean }) {
  const chosen = value ? value.split(",") : [];
  const toggle = (key: string) => {
    const next = chosen.includes(key) ? chosen.filter((x) => x !== key) : [...chosen, key];
    onChange(next.length || !required ? next.join(",") : key);
  };
  return (
    <div className="filter-group" role="group" aria-label={label}>
      <p className="filter-label">{label}<span className="muted small-text">（可多选）</span></p>
      {options.map(([key, text]) => (
        <button key={key} type="button" role="checkbox" aria-checked={chosen.includes(key)} className={`fopt${chosen.includes(key) ? " on" : ""}`} onClick={() => toggle(key)}>
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

// 判断的标题：有标题就用标题；没有就显示推荐标题（正文第一句），人可以一键采用。
// 标题是标签，采用只追加一条标题记录，不产生新版本、不让框架页过期（D-101）。正文全文在下面的"本条"里。
function JudgmentTitle({ data, reload }: { data: any; reload: () => void }) {
  const entry = data.entry;
  const stored: string | undefined = entry.data?.title;
  const suggested: string | undefined = data.suggested_title;
  const shown = stored || suggested || stripMarkers(entry.data?.text ?? "").slice(0, 60);
  return (
    <>
      <h1><span className="entry-hero-text">{shown}</span></h1>
      {!stored && (
        <p className="small-text muted title-suggest">
          <Tag>推荐标题</Tag> 这条判断还没有标题，上面是正文第一句。
          {suggested && (
            <Action
              className="small"
              label="采用为标题"
              done="已采用"
              title="只记下标题，不产生新版本，正文与关系都不变"
              run={async () => {
                await call("judgment.title", { id: entry.id, title: suggested.slice(0, 60) });
                reload();
              }}
            />
          )}
        </p>
      )}
    </>
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
  const relOut: any[] = data?.relations?.out ?? [];
  const relIn: any[] = data?.relations?.in ?? [];
  const versionRow = data?.version_history?.versions?.find((v: any) => v.version === data?.entry?.version);
  const reviewKey = `${base}:${data?.coordinates?.state?.validity ?? ""}:${data?.coordinates?.state?.review ?? ""}`;
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
              {kind === "judgment" ? <JudgmentTitle data={data} reload={reloadAll} /> : <h1><EntryName id={id} /></h1>}
              <EntryMeta data={data} page={page} />
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
            <section className="status-strip" aria-label="坐标">
              <div><span className="label">坐标</span><Coordinates c={data.coordinates} full /></div>
              {data.note && <div className="muted small-text">{data.note}</div>}
            </section>
          )}
          <EntryKeys id={id} />
          {data.version_history && !base.startsWith("pg_") && (
            <EntryActions key={id} entry={data.entry} history={data.version_history} relOut={relOut} outbound={data.outbound !== false} reload={reloadAll} />
          )}
          {data.entry.entry_kind === "artifact" && versionRow?.retired &&
            <RetiredBanner artifactId={base} retirement={versionRow.retired} replacedBy={versionRow.replaced_by} reload={reload} />}
          <LapseNotice c={data.coordinates} />
          {chain ? (
            <div className="chain">
              <section className="chain-col" aria-label="本条指向">
                <h2>本条指向 <span className="muted">出边 · {relOut.length}</span></h2>
                <RelationGroups items={relOut} empty={kind === "judgment" ? "没有依据，也没有其他关系：依据来源记为推断。" : "没有指向别的条目。"} />
              </section>
              <span className="chain-flow" aria-hidden="true"><Icon name="chevron" /></span>
              <section className="chain-col main" aria-label="本条">
                <h2>本条 <span className="muted">全文与经过</span></h2>
                <div className="panel">
                  <EntryBody entry={data.entry} readSourceStatus={data.read_source_status} notes={notesOf(relOut)} />
                  {["judgment", "artifact"].includes(data.entry.entry_kind) && <ReviewBox key={reviewKey} itemId={base} reload={reload} mode="readonly" />}
                  <VersionHistory entry={data.entry} history={data.version_history} />
                </div>
                {expand && <Expand data={expand} />}
              </section>
              <span className="chain-flow" aria-hidden="true"><Icon name="chevron" /></span>
              <section className="chain-col" aria-label="指向本条">
                <h2>指向本条 <span className="muted">入边 · {relIn.length}</span></h2>
                <RelationGroups items={relIn} empty="还没有条目指向它。" />
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
                  {["judgment", "artifact"].includes(data.entry.entry_kind) && <ReviewBox key={reviewKey} itemId={base} reload={reload} mode="readonly" />}
                  <VersionHistory entry={data.entry} history={data.version_history} />
                </Panel>
              </div>
              <aside>
                {expand && <Expand data={expand} />}
                {relOut.length > 0 && <Panel title={`本条指向 · ${relOut.length}`}><RelationGroups items={relOut} empty="" /></Panel>}
                {relIn.length > 0 && <Panel title={`指向本条 · ${relIn.length}`}><RelationGroups items={relIn} empty="" /></Panel>}
              </aside>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// 标题下的一行：类型 · 第几版 · 作者 · 会话 · 时间；没有的项不占位（框架页的版本与作者在 page.get 里）
function EntryMeta({ data, page }: { data: any; page: any }) {
  const e = data.entry;
  const version = e.version ?? page?.version;
  const head = e.head_version ?? page?.page?.head_version;
  const author = e.author_id ?? e.actor_id ?? e.captured_by ?? e.promoted_by ?? page?.author_id;
  const kind = data.coordinates?.kind;
  const parts: ReactNode[] = [
    kind && (KIND[kind] ?? kind),
    version && `第 ${version} 版${head > version ? `（当前是第 ${head} 版）` : ""}`,
    author,
    e.session_id && <>会话 <span className="mono">{e.session_id}</span></>,
    <Time value={page ? e.updated_at ?? e.created_at : e.created_at} />,
  ].filter(Boolean);
  return (
    <p className="muted small-text">
      {parts.map((x, i) => <Fragment key={i}>{i > 0 && " · "}{x}</Fragment>)}
    </p>
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

// 关系区（设计稿 10 D-27）：按方向分两栏（本条指向 / 指向本条），每栏按谓词类别分组，顺序：证据流、立场与结构、
// 替代、过程、框架推断、自由标签。只有证据流参与地位与现状的推出；框架推断默认折叠、不作为依据；
// 自由标签显示它自己的标签，系统不赋予含义。
const RELATION_GROUPS = ["evidence", "stance", "replace", "process", "framework", "free"];
const GROUP_NOTE: Record<string, string> = {
  evidence: "参与地位与现状的推出",
  framework: "不作为依据",
  free: "系统不赋予含义",
};

function RelationGroups({ items, empty }: { items: any[]; empty: string }) {
  if (!items.length) return empty ? <Empty compact icon="info">{empty}</Empty> : null;
  return (
    <>
      {RELATION_GROUPS.map((cat) => {
        const list = items.filter((x) => (x.category ?? "free") === cat);
        if (!list.length) return null;
        const head = (
          <span className="rel-group-head">
            {CATEGORIES[cat] ?? cat} <span className="muted">{list.length}</span>
            {GROUP_NOTE[cat] && <span className="muted small-text"> · {GROUP_NOTE[cat]}</span>}
          </span>
        );
        const cards = relationCards(list);
        return cat === "framework" ? (
          <details key={cat} className="rel-group"><summary>{head}</summary>{cards}</details>
        ) : (
          <div key={cat} className="rel-group">{head}{cards}</div>
        );
      })}
    </>
  );
}

// 同一份原件的几个段落（同一种关系）收成一张卡，每行一段、带编号（设计稿 16 D-12）；其余照旧一条一张卡
function relationCards(list: any[]): ReactNode[] {
  const isSeg = (x: any) => typeof x.other === "string" && x.other.startsWith("art_") && x.other.includes("#");
  const seen = new Set<string>();
  const out: ReactNode[] = [];
  list.forEach((x, i) => {
    if (!isSeg(x)) {
      out.push(<RelationCard key={`${x.id ?? x.other}:${i}`} item={x} />);
      return;
    }
    const key = `${x.predicate}|${x.other.split("#")[0].split("@")[0]}`;
    if (seen.has(key)) return;
    seen.add(key);
    const same = list.map((y, j) => [y, j] as const).filter(([y]) => isSeg(y) && `${y.predicate}|${y.other.split("#")[0].split("@")[0]}` === key);
    if (same.length === 1) out.push(<RelationCard key={`${x.id ?? x.other}:${i}`} item={x} />);
    else out.push(<CiteGroup key={key} items={groupCites(same.map(([y, j]) => citeOfRelation(y, j)))[0]} />);
  });
  return out;
}

// 关系卡：对方的印、名称、这一端看的说法、对方的一行说明与限定
function RelationCard({ item }: { item: any }) {
  const other: string = item.other;
  const q = item.qualifiers ?? {};
  return (
    <a className="chain-card" id={item.id ? `rel-${item.id}` : undefined} href={href("entry", other)} title={other}>
      <span className="chain-card-head">
        <Stamp layer={layerOf(other)} small />
        <span className="clip grow">{item.other_label ?? <EntryName id={other} />}</span>
        <span className="tag" title={item.predicate}>{item.phrase ?? relPhrase(item.predicate, true, item.label)}</span>
        {q.role && <span className="tag role-tag" title="作用">{q.role}</span>}
        {q.marker && <span className="tag" title="对应正文里的引用标记">[{q.marker}]</span>}
      </span>
      {q.why && <span className="rel-why small-text">{q.why}</span>}
      <span className="chain-card-meta">
        <span className="mono muted">{other}</span>
        {item.other_validity && item.other_validity !== "current" && <Tag tone="warn">{VALIDITY[item.other_validity] ?? item.other_validity}</Tag>}
        {item.other_note && <span className="muted small-text">{item.other_note}</span>}
        {q.condition && <span className="muted small-text">条件：{q.condition}</span>}
        {q.reason && !q.why && <span className="muted small-text">理由：{q.reason}</span>}
        {q.auto && <span className="muted small-text">系统连接</span>}
        {item.review && item.review !== "ai_generated" && <span className="muted small-text">{REVIEW[item.review] ?? item.review}</span>}
      </span>
    </a>
  );
}

// 对象页（D-08）：关于这个对象的全部条目。约束在前，其次有争议的结论，其余按类型、时间；不含自动日志
const OBJECT_GROUPS: [string, string][] = [
  ["constraints", "有效约束"],
  ["disputed", "有争议的结论"],
  ["conclusion", "结论"],
  ["thought", "思路"],
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
                  <li key={t.id} className={(t.state?.validity ?? "current") !== "current" ? "superseded" : ""}>
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

// 这一版判断的关系按 marker 归类：正文里的 [^n] 对应哪几条关系（设计稿 11 D-06）
function notesOf(out: any[]): Record<string, RelationNote[]> {
  const notes: Record<string, RelationNote[]> = {};
  for (const x of out) {
    const m = x.qualifiers?.marker;
    if (m) (notes[m] ??= []).push(x);
  }
  return notes;
}

function EntryBody({ entry, readSourceStatus, notes }: { entry: any; readSourceStatus?: any; notes?: Record<string, RelationNote[]> }) {
  const d = entry.data ?? {};
  const kind = entry.entry_kind;
  return (
    <div className="entry">
      {kind === "judgment" && (
        <>
          <p className="meta">
            【{JUDGMENT_KIND[entry.kind] ?? entry.kind}】{entry.author_id} · <Time value={entry.created_at} />
          </p>
          <ClaimBody claim={d} notes={notes} needsConditions={entry.kind === "conclusion"} />
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
  ["version", "版本"],
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
          <h3>依据或评价了它的判断（解读，不是原件内容）</h3>
          {Object.entries(grouped).map(([k, list]) => (
            <div key={k}>
              <div className="muted small-text">
                {JUDGMENT_KIND[k] ?? k}（{list.length}）
              </div>
              <ul className="plain">
                {list.map((s: any) => (
                  <li key={s.ref + s.predicate + s.via}>
                    {s.predicate !== "cites" && <span className="tag">{relPhrase(s.predicate, true, s.label)}</span>} <IdLink id={s.ref ?? s.judgment_id} />
                    {String(s.via).split("#")[0].split("@")[0] !== data.entry.id && (
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
    if (key === "version") v = src.head_version > v ? `第 ${v} 版（当前是第 ${src.head_version} 版）` : `第 ${v} 版`;
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

// 依据失效（设计稿 07 D-02、设计稿 10 D-20）：依据全部失效的条目默认隐藏；部分失效的列出失效的依据
function LapseNotice({ c }: { c: any }) {
  const all = c?.state?.validity === "lapsed";
  const mark = (c?.state?.marks ?? []).find((m: any) => m.mark === "basis_lapsed");
  if (!all && !mark) return null;
  return (
    <div className="notice retired">
      <strong>{all ? "依据已全部失效，默认隐藏" : "部分依据已失效"}</strong>：
      {(mark?.via ?? []).map((g: any) => (
        <span key={g.rel ?? g.end}>
          {" "}
          {g.detail === "已删除" ? <span className="mono">{g.end}</span> : <IdLink id={g.end} />}（{g.detail}）
        </span>
      ))}
      。{all ? "它不在条目列表、默认检索和关系图里；恢复或替换原件后自动重新出现。" : "替换原件后按段落指纹重新核对。"}
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
  relations: "关系",
  events: "系统流水",
  reviews: "复核记录",
  version_states: "处置记录",
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
        <IdLink id={x.id} /> <span className="tag">{x.kind ? (KIND[x.kind] ?? x.kind) : (ENTRY_KIND[x.entry_kind] ?? x.entry_kind)}</span>
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
                      关系：{(x.rels ?? []).map((r: string) => relPhrase(r, true)).join("、")}
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
                    <IdLink id={e.src_id} name={e.src} /> <span className="tag">{LINK_REL[e.rel] ?? e.rel}</span> <IdLink id={e.dst_id} name={e.dst} />
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

// 版本历史里"改了哪些字段"的名字（设计稿 11 D-19）
const FIELD_CHANGED: Record<string, string> = {
  text: "正文", kind: "类型", conditions: "条件", scope_unclear: "适用范围未明", external_author: "原作者",
  reopen_condition: "重开条件", local_observation: "本地实证", objects: "对象", title: "标题", source_class: "依据来源",
  external_tier: "来源档次", metadata: "说明字段", sha256: "内容", output: "正文", result: "正文", excerpt: "正文",
};

// 版本历史（设计稿 10 D-01 至 D-04、D-18）：条目 ID 稳定，版本写 @n，当前版 = 最新版。只读：每一版列出作者、改动理由、
// 关系变化、处置。人要做的事（更正、改关系、撤回、标缺陷、退役、复核、外发……）都在页面上方的"操作"里（EntryActions）。
export function VersionHistory({ entry, history }: { entry: any; history?: any }) {
  if (!history) return null;
  const current = history.versions.find((v: any) => v.version === entry.version);
  if (!current) return null;
  const isHead = entry.version === history.head_version;
  return (
    <section className="amend">
      <h3>版本历史</h3>
      <p className="muted">
        本页是第 {current.version} 版{isHead ? "（当前版）" : <>；当前是第 {history.head_version} 版 <IdLink id={history.current_ref}>打开当前版</IdLink></>}。
      </p>
      <ol>
        {history.versions.map((v: any) => (
          <li key={v.ref}>
            <a href={href("entry", v.ref)} className={v.version === entry.version ? "on-version" : ""}>第 {v.version} 版</a>
            {" "}· {authorNote(v.author_kind, entry.entry_kind)} · <Time value={v.created_at} />
            {v.validity !== "current" && <> · {VALIDITY[v.validity] ?? v.validity}</>}
            {v.defective && " · 有缺陷"}
            {v.change_reason && <p>改动理由：{v.change_reason}</p>}
            {v.fields_changed?.length > 0 && (
              <p className="small-text muted">改了：{v.fields_changed.map((k: string) => FIELD_CHANGED[k] ?? k).join("、")}</p>
            )}
            {(v.relations_added?.length > 0 || v.relations_removed?.length > 0) && v.version > 1 && (
              <p className="small-text muted">
                {v.relations_added.map((r: any) => <span key={`a${r.predicate}${r.object}`}> +{relPhrase(r.predicate, true, r.label)} <IdLink id={r.object} /></span>)}
                {v.relations_removed.map((r: any) => <span key={`r${r.predicate}${r.object}`}> −{relPhrase(r.predicate, true, r.label)} <IdLink id={r.object} /></span>)}
              </p>
            )}
            {v.version !== entry.version && v.entry && (
              <details>
                <summary>查看这一版的正文</summary>
                <EntryBody entry={v.entry} />
              </details>
            )}
            {v.changes.map((c: any) => <p key={c.id}><Time value={c.created_at} /> · {VERSION_ACTION_LABEL[c.action] ?? c.action} · {c.reason}</p>)}
          </li>
        ))}
      </ol>
    </section>
  );
}

export function rederivePrompt(p: any): string {
  const target = p.title ? `${p.id}（${p.title}）` : p.id;
  return `请重新综合框架页 ${target}。用 page_get 读取它的当前版本和输入清单，用 entry_get / search 核对现有输入及相关的新判断、更正与撤回，然后用 page_write 写出新版本（沿用当前 slug），inputs 列出实际依据的条目。不要修改判断层。`;
}

const POINT_SUBKIND: Record<string, string> = { digest: "摘要", lesson: "经验" };

// 要点（设计稿 15 D-11、16、17）：与判断同一种论断，用同一套显示——正文（上标悬停看依据）、条件、原作者、对象；
// 依据按原件分组、每行带原文片段。不能作为依据，要引用请读段落。
function PointBlock({ point }: { point: any }) {
  const cites: ClaimCite[] = (point.cites ?? []).map((c: any, i: number) => ({
    id: `pt-${i}`, ref: c.cite_as, phrase: "依据", marker: c.marker, role: c.role, why: c.why, text: c.text,
  }));
  return (
    <div className="point">
      <p className="muted small-text">{point.status_note}</p>
      {point.archived && (
        <p className="warn-text">
          已归档：{point.archived.reason}
          {point.archived.merged_into && <> · 并入 <IdLink id={point.archived.merged_into} /></>}
        </p>
      )}
      <ClaimBody claim={point} notes={notesFromCites(cites)} quotedLabel="原作者" needsConditions={point.subkind !== "lesson"} />
      {point.use && (
        <p className="muted small-text" title={`检索命中按最近 ${point.use.window_days} 天统计`}>
          {POINT_SUBKIND[point.subkind] ?? "摘要"} · 来源 {point.use.sources} 处 · 关联 {point.use.links} 条 · 被 {point.use.pages} 页用到 · 近期被检索返回 {point.use.hits} 次
        </p>
      )}
      {point.source_changed?.length > 0 && (
        <p className="warn-text">来源已变化：{point.source_changed.map((c: any) => c.ref).join("、")}</p>
      )}
      <h4>出处</h4>
      <CiteGroups cites={cites} showText />
      {(point.links?.length ?? 0) > 0 && (
        <>
          <h4>关联</h4>
          <ul className="plain">
            {point.links.map((l: any) => (
              <li key={l.id}>
                <Tag>{relPhrase(l.rel, l.direction === "out")}</Tag> <IdLink id={l.other} />
                {l.why && <span className="muted small-text"> {l.why}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
      {(point.used_by?.length ?? 0) > 0 && (
        <>
          <h4>被综合进</h4>
          <ul className="plain">{point.used_by.map((id: string) => <li key={id}><IdLink id={id} /></li>)}</ul>
        </>
      )}
    </div>
  );
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
      {page.point ? <PointBlock point={page.point} /> : <RefText text={page.body} />}
      {!page.point && <h4>输入清单</h4>}
      <ul className="plain">
        {page.inputs.filter(() => !page.point).map((i: string) => (
          <li key={i}>
            <IdLink id={i} />
          </li>
        ))}
      </ul>
      <ReviewBox itemId={page.page.id} reload={reload} />
      {page.page.type !== "point" && <div className="row tight">
        <button type="button" onClick={() => delegate(rederivePrompt(page.page))}>
          {page.page.freshness === "valid" ? "再次交给 Agent 综合" : "交给 Agent 重新综合"}
        </button>
      </div>}
    </div>
  );
}
