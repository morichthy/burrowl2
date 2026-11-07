// 条目浏览（按类型、判断类型、作者、依据来源、对象筛选）与条目详情（含人工修改入口、框架页复核）。
// 原件的详情是原件页（Artifact.tsx）；对象（ent_…）的详情是对象页（设计稿 01 D-08）。
import { useEffect, useState, type ReactNode } from "react";
import { call } from "../api";
import { ENTRY_KIND, FRESHNESS, JUDGMENT_KIND, KIND_FILTER, PAGE_TYPE, REVIEW, SOURCE, TIER } from "../labels";
import { delegate, go, href } from "../router";
import { Action, Chips, Coordinates, Empty, ErrorBox, FilterRow, IdLink, Panel, RefText, Tag, Time, useLoad } from "../ui";
import { openReader } from "../reader/open";
import { ArtifactView } from "./Artifact";

/* eslint-disable @typescript-eslint/no-explicit-any */

const PAGE_SIZE = 30;

export function Entries() {
  const [kind, setKind] = useState<string[]>(["judgment"]);
  const [jkind, setJkind] = useState<string[]>([]);
  const [author, setAuthor] = useState<string[]>([]);
  const [source, setSource] = useState<string[]>([]);
  const [object, setObject] = useState("");
  const [query, setQuery] = useState("");
  const [showRetired, setShowRetired] = useState(false);
  const [offset, setOffset] = useState(0);
  const k = kind[0] ?? "judgment";
  const [data, error] = useLoad(
    () =>
      call<any>("entries.list", {
        kind: k,
        judgment_kind: k === "judgment" ? (jkind[0] ?? null) : null,
        author_kind: author[0] ?? null,
        source_class: source[0] ?? null,
        object: object.trim() || null,
        query: query.trim() || null,
        include_retired: k === "artifact" && showRetired,
        limit: PAGE_SIZE,
        offset,
      }),
    [k, jkind.join(), author.join(), source.join(), object, query, showRetired, offset],
  );
  useEffect(() => setOffset(0), [k, jkind.join(), author.join(), source.join(), object, query, showRetired]);
  return (
    <Panel title="条目" actions={<span className="muted">原件一列与判断一列；只追加，不修改</span>}>
      <div className="filter-rows">
        <FilterRow label="类型">
          <Chips all={null} options={Object.entries(ENTRY_KIND)} value={kind} onChange={(v) => setKind(v.length ? v : ["judgment"])} />
        </FilterRow>
        {k === "judgment" && (
          <FilterRow label="判断类型">
            <Chips options={Object.entries(KIND_FILTER)} value={jkind} onChange={setJkind} />
          </FilterRow>
        )}
        {(k === "judgment" || k === "event") && (
          <FilterRow label="作者">
            <Chips
              options={[
                ["human", "人"],
                ["ai", "AI"],
                ["system", "系统"],
              ]}
              value={author}
              onChange={setAuthor}
            />
          </FilterRow>
        )}
        {(k === "judgment" || k === "artifact") && (
          <FilterRow label="依据来源">
            <Chips options={Object.entries(SOURCE)} value={source} onChange={setSource} />
          </FilterRow>
        )}
        <FilterRow label="对象 / 文字">
          <div className="row tight">
            <input value={object} onChange={(e) => setObject(e.target.value)} placeholder="对象，如 2号泵、P-102 或 ent_…" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="包含文字" />
          </div>
        </FilterRow>
        {k === "artifact" && (
          <FilterRow label="其他">
            <label className="check" title="已退役的原件内容不变、仍可打开和引用，只是默认不在列表和检索里出现">
              <input type="checkbox" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} />
              显示已退役的原件
            </label>
          </FilterRow>
        )}
      </div>
      <ErrorBox error={error} />
      {data && (
        <>
          <p className="muted">共 {data.total} 条，按时间倒序</p>
          {data.items.length === 0 && <Empty>没有符合条件的条目</Empty>}
          <ul className="entry-list">
            {data.items.map((e: any) => (
              <li key={e.id} className={e.superseded || e.retired ? "superseded" : ""}>
                <div className="entry-head">
                  <IdLink id={e.id} />
                  {e.judgment_kind && <span className="kind jd">{JUDGMENT_KIND[e.judgment_kind]}</span>}
                  <Coordinates c={e} />
                  <Time value={e.created_at} />
                </div>
                <div className="snippet">{e.preview}</div>
              </li>
            ))}
          </ul>
          <div className="pager">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              上一页
            </button>
            <span className="muted">
              {data.total ? offset + 1 : 0}–{Math.min(offset + PAGE_SIZE, data.total)} / {data.total}
            </span>
            <button type="button" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
              下一页
            </button>
          </div>
        </>
      )}
    </Panel>
  );
}

// ---------- 条目详情 ----------
export function Entry({ id }: { id: string }) {
  const [input, setInput] = useState(id);
  const base = id.split("#")[0].split("@")[0];
  const anchor = id.includes("#") ? id.split("#")[1] : "";
  const isEntity = base.startsWith("ent_");
  const [data, error, reload] = useLoad(() => (id && !isEntity ? call("entry.get", { id }) : Promise.resolve(null)), [id]);
  const [expand, , reloadExpand] = useLoad(() => (id && !base.startsWith("pg_") && !isEntity ? call("entry.expand", { id }) : Promise.resolve(null)), [id]);
  const [page, , reloadPage] = useLoad(() => (base.startsWith("pg_") ? call("page.get", { page: id }) : Promise.resolve(null)), [id]);
  return (
    <div className="split">
      <div>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            go("entry", input.trim());
          }}
        >
          <input className="grow" value={input} onChange={(e) => setInput(e.target.value)} placeholder="条目 ID，如 jdg_… / art_…#seg-3 / pg_…@2 / ent_…" />
          <button type="submit">打开</button>
          {id && (
            <a className="button" href={href("graph", base)}>
              在关系图中查看
            </a>
          )}
          {id && !isEntity && (
            <button type="button" onClick={() => openReader(base, anchor)} title="全屏阅读（设计稿 03 D-01、D-07）">
              阅读
            </button>
          )}
        </form>
        {!id && <Empty>输入条目 ID，或从检索、条目列表、关系图中点开。</Empty>}
        {isEntity && <ObjectView id={base} />}
        <ErrorBox error={error} />
        {data && (
          <Panel
            title={
              <>
                <span className="mono">{base}</span> <Coordinates c={data.coordinates} />
              </>
            }
          >
            {data.coordinates?.retired && <RetiredBanner retirement={data.coordinates.retired} reload={reload} />}
            {data.entry.entry_kind === "artifact" ? (
              <ArtifactView
                entry={data.entry}
                anchor={anchor}
                onChanged={() => {
                  reload();
                  reloadExpand();
                }}
              />
            ) : (
              <EntryBody entry={data.entry} />
            )}
            {page && (
              <PageView
                page={page}
                reload={() => {
                  reload();
                  reloadPage();
                }}
              />
            )}
            <Amend entry={data.entry} retired={data.coordinates?.retired} reload={reload} />
          </Panel>
        )}
      </div>
      <aside>
        {expand && <Expand data={expand} />}
        {data?.links_out?.length > 0 && <Links title="它指向" links={data.links_out} field="dst_id" />}
        {data?.links_in?.length > 0 && data.entry.entry_kind !== "artifact" && <Links title="指向它" links={data.links_in} field="src_id" />}
        {data?.edges?.length > 0 && (
          <Panel title="关系图中的边">
            <ul className="plain">
              {data.edges.map((e: any) => (
                <li key={e.id}>
                  <IdLink id={e.src_id} /> —{e.rel}→ <IdLink id={e.dst_id} /> <span className="tag muted">{e.origin}</span> <span className="tag">{REVIEW[e.review] ?? e.review}</span>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </aside>
    </div>
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
          {view?.name ?? id} {entity && <Tag>{entity.kind}</Tag>} <span className="mono muted">{id}</span>
        </>
      }
      actions={<a href={href("graph", id)}>在关系图中查看</a>}
    >
      <ErrorBox error={error} />
      {entity?.data?.description && <p>{entity.data.description}</p>}
      {view?.pages?.length > 0 && (
        <p>
          框架页：
          {view.pages.map((p: any) => (
            <a key={p.id} href={href("entry", p.id)} className="tag accent">
              {PAGE_TYPE[p.type] ?? p.type}「{p.title}」{p.freshness !== "valid" ? ` · ${FRESHNESS[p.freshness]}` : ""}
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

function EntryBody({ entry }: { entry: any }) {
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
            <a href={href("entry", `${entry.artifact_id}#${(d.anchors ?? [])[0] ?? `seg-${(d.segments ?? [0])[0]}`}`)}>原件 {entry.artifact_id}</a> 的 {(d.anchors ?? d.segments ?? []).length} 段（{entry.locator}）
          </p>
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
            <span className="tag">{l.rel}</span> <IdLink id={l[field]} /> {l.data?.condition && `（条件：${l.data.condition}）`}
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
                    {s.rel !== "used" && <span className="tag">{s.rel}</span>} <IdLink id={s.judgment_id} /> {s.preview}
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

// 已退役的原件（设计稿 02 D-12、D-13）：顶部说明退役记录，撤销退役 = 撤回那条退役记录
function RetiredBanner({ retirement, reload }: { retirement: string; reload: () => void }) {
  const [rec] = useLoad(() => call<any>("entry.get", { id: retirement }), [retirement]);
  const [reason, setReason] = useState("");
  return (
    <div className="notice retired">
      <div>
        <strong>已退役</strong>：{rec?.entry?.data?.text ?? "…"}（<IdLink id={retirement} />
        {rec?.entry && (
          <>
            {" "}
            · {rec.entry.author_id} · <Time value={rec.entry.created_at} />
          </>
        )}
        ）。内容不变，仍可阅读和引用；默认不在条目列表和检索里出现。
      </div>
      <div className="row tight">
        <input className="grow" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="撤销退役的理由（必填）" />
        <Action label="撤销退役" disabled={!reason.trim()} run={async () => (await call("judgment.amend", { mode: "retraction", target: retirement, reason }), setReason(""), reload())} />
      </div>
    </div>
  );
}

// 人工修改入口：更正、撤回、原件有缺陷（草图 §4）、原件退役（设计稿 02 D-11）。只在工作台提供。
function Amend({ entry, retired, reload }: { entry: any; retired?: string | null; reload: () => void }) {
  const [reason, setReason] = useState("");
  const kind = entry.entry_kind;
  const modes: [string, string][] =
    kind === "judgment"
      ? [
          ["correction", "更正（原来就错）"],
          ["retraction", "撤回（不再主张）"],
        ]
      : ["artifact", "event", "record", "read"].includes(kind)
        ? [["defect", "标记原件有缺陷"], ...(kind === "artifact" && !retired ? ([["retirement", "退役（内容没错，不再单独出现）"]] as [string, string][]) : [])]
        : [];
  if (modes.length === 0) return null;
  return (
    <div className="amend">
      <h3>修改</h3>
      <p className="muted">原条目不会改变；系统写一条新判断指向它，并把受影响的框架页标为"输入已变化"。</p>
      <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="理由（必填）" />
      {modes.map(([mode, label]) => (
        <Action key={mode} label={label} disabled={!reason.trim()} run={async () => (await call("judgment.amend", { mode, target: entry.id, reason }), setReason(""), reload())} />
      ))}
    </div>
  );
}

export function rederivePrompt(p: any): string {
  return `框架页 ${p.id}（${p.title}）的输入已变化。请用 page_get 读取它的当前版本和输入清单，用 entry_get / search 查看相关的新判断、更正与撤回，然后用 page_write 写出新版本（同一 slug：${p.slug}），inputs 列出实际依据的条目。不要修改判断层。`;
}

function PageView({ page, reload }: { page: any; reload: () => void }) {
  const [reason, setReason] = useState("");
  return (
    <div className="page">
      <h3>
        {PAGE_TYPE[page.page.type] ?? page.page.type}「{page.page.title}」· 第 {page.version} 版（共 {page.versions.length} 版）· {REVIEW[page.page.review]} · {FRESHNESS[page.page.freshness]}
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
      {page.superseded_inputs.length > 0 && <div className="notice">这一版用到的输入中有 {page.superseded_inputs.length} 条已被替代、更正或撤回</div>}
      <RefText text={page.body} />
      <h4>输入清单</h4>
      <ul className="plain">
        {page.inputs.map((i: string) => (
          <li key={i}>
            <IdLink id={i} />
          </li>
        ))}
      </ul>
      <div className="amend">
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="复核理由（必填）；复核结论会写回判断层" />
        <Action label="确认" disabled={!reason.trim()} run={async () => (await call("framework.review", { item_id: page.page.id, verdict: "confirm", reason }), reload())} />
        <Action label="驳回" className="danger" disabled={!reason.trim()} run={async () => (await call("framework.review", { item_id: page.page.id, verdict: "reject", reason }), reload())} />
        <button type="button" onClick={() => delegate(rederivePrompt(page.page))}>
          交给 agent 重新综合
        </button>
      </div>
    </div>
  );
}
