// 条目浏览（按类型、判断类型、作者、依据来源、对象筛选）与条目详情（含人工修改入口、框架页复核）。
import { useEffect, useState } from "react";
import { call } from "../api";
import { ENTRY_KIND, FRESHNESS, JUDGMENT_KIND, KIND_FILTER, PAGE_TYPE, REVIEW, SOURCE } from "../labels";
import { delegate, go, href } from "../router";
import { Action, Chips, Coordinates, Empty, ErrorBox, FilterRow, IdLink, Panel, RefText, Time, useLoad } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

const PAGE_SIZE = 30;

export function Entries() {
  const [kind, setKind] = useState<string[]>(["judgment"]);
  const [jkind, setJkind] = useState<string[]>([]);
  const [author, setAuthor] = useState<string[]>([]);
  const [source, setSource] = useState<string[]>([]);
  const [object, setObject] = useState("");
  const [query, setQuery] = useState("");
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
        limit: PAGE_SIZE,
        offset,
      }),
    [k, jkind.join(), author.join(), source.join(), object, query, offset],
  );
  useEffect(() => setOffset(0), [k, jkind.join(), author.join(), source.join(), object, query]);
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
      </div>
      <ErrorBox error={error} />
      {data && (
        <>
          <p className="muted">共 {data.total} 条，按时间倒序</p>
          {data.items.length === 0 && <Empty>没有符合条件的条目</Empty>}
          <ul className="entry-list">
            {data.items.map((e: any) => (
              <li key={e.id} className={e.superseded ? "superseded" : ""}>
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
  const isEntity = base.startsWith("ent_");
  const [data, error, reload] = useLoad(() => (id && !isEntity ? call("entry.get", { id }) : Promise.resolve(null)), [id]);
  const [expand] = useLoad(() => (id && !base.startsWith("pg_") && !isEntity ? call("entry.expand", { id }) : Promise.resolve(null)), [id]);
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
        </form>
        {!id && <Empty>输入条目 ID，或从检索、条目列表、关系图中点开。</Empty>}
        {isEntity && <EntityView id={base} />}
        <ErrorBox error={error} />
        {data && (
          <Panel
            title={
              <>
                <span className="mono">{base}</span> <Coordinates c={data.coordinates} />
              </>
            }
          >
            <EntryBody entry={data.entry} />
            {page && (
              <PageView
                page={page}
                reload={() => {
                  reload();
                  reloadPage();
                }}
              />
            )}
            <Amend entry={data.entry} reload={reload} />
          </Panel>
        )}
      </div>
      <aside>
        {data?.links_out?.length > 0 && <Links title="它指向" links={data.links_out} field="dst_id" />}
        {data?.links_in?.length > 0 && <Links title="指向它" links={data.links_in} field="src_id" />}
        {expand && <Expand data={expand} />}
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

function EntityView({ id }: { id: string }) {
  const [timeline, error] = useLoad(() => call<any[]>("timeline", { object: id }), [id]);
  const [edges] = useLoad(() => call<any[]>("edge.list", { node_id: id }), [id]);
  return (
    <Panel title={<span className="mono">{id}</span>}>
      <ErrorBox error={error} />
      <h3>时间线（{timeline?.length ?? 0}）</h3>
      <ul className="entry-list">
        {(timeline ?? []).map((t) => (
          <li key={t.id}>
            <div className="entry-head">
              <IdLink id={t.id} /> <Coordinates c={t} /> <Time value={t.created_at} />
            </div>
            <div className="snippet">{t.preview}</div>
          </li>
        ))}
      </ul>
      <h3>相连的边（{edges?.length ?? 0}）</h3>
      <ul className="plain">
        {(edges ?? []).map((e) => (
          <li key={e.id}>
            <IdLink id={e.src_id} /> —{e.rel}→ <IdLink id={e.dst_id} />
          </li>
        ))}
      </ul>
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
      {kind === "artifact" && (
        <p className="meta">
          {d.title ?? "（无标题）"} · {entry.kind} · {entry.storage === "managed" ? "受管保存" : `外部引用 ${entry.uri}`} · sha256 {entry.sha256.slice(0, 12)}… · <Time value={entry.created_at} />
          {entry.version_of && (
            <>
              {" "}
              · 旧版本 <IdLink id={entry.version_of} />
            </>
          )}
        </p>
      )}
      {kind === "record" && (
        <>
          <p className="meta">
            方法：{d.method ?? "—"} · 边界：{entry.boundary} · 缺口：{(d.gaps ?? []).join("、") || "无"}
          </p>
          <pre>{d.result}</pre>
        </>
      )}
      {kind === "read" && <pre>{d.excerpt}</pre>}
      {kind === "event" && (
        <>
          <p className="meta">
            {entry.op} · {entry.actor_id} · 会话 {entry.session_id} #{entry.seq}
          </p>
          <pre>{JSON.stringify({ input: d.input, conditions: d.conditions }, null, 2)}</pre>
          {d.output && <pre>{d.output}</pre>}
        </>
      )}
      {entry.objects?.length > 0 && (
        <p>
          对象：
          {entry.objects.map((o: string) =>
            o.startsWith("ent_") ? (
              <IdLink key={o} id={o} />
            ) : (
              <span key={o} className="tag">
                {o}
              </span>
            ),
          )}
        </p>
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

function Expand({ data }: { data: any }) {
  return (
    <Panel title="背景">
      {data.conditions && (
        <>
          <h3>① 自带条件</h3>
          <pre>{JSON.stringify(data.conditions, null, 2)}</pre>
        </>
      )}
      {data.neighbors && (
        <>
          <h3>② 同一来源的前后内容</h3>
          {data.neighbors.map((n: any) => (
            <pre key={n.ordinal ?? n.id}>{n.text ?? `${n.op} ${JSON.stringify(n.data?.input)}`}</pre>
          ))}
        </>
      )}
      {data.same_objects?.length > 0 && (
        <>
          <h3>③ 同一对象的其他记录</h3>
          <ul className="plain">
            {data.same_objects.map((s: any) => (
              <li key={s.id}>
                <IdLink id={s.id} /> <Coordinates c={s} /> {s.preview}
              </li>
            ))}
          </ul>
        </>
      )}
      {data.interpretations?.length > 0 && (
        <>
          <h3>④ 引用了它的判断（解读，不是原件内容）</h3>
          <ul className="plain">
            {data.interpretations.map((s: any) => (
              <li key={s.judgment_id + s.rel}>
                <span className="tag">{s.rel}</span> <IdLink id={s.judgment_id} /> {s.preview}
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}

// 人工修改入口：更正、撤回、原件有缺陷（草图 §4）。只在工作台提供。
function Amend({ entry, reload }: { entry: any; reload: () => void }) {
  const [reason, setReason] = useState("");
  const kind = entry.entry_kind;
  const modes: [string, string][] =
    kind === "judgment"
      ? [
          ["correction", "更正（原来就错）"],
          ["retraction", "撤回（不再主张）"],
        ]
      : ["artifact", "event", "record", "read"].includes(kind)
        ? [["defect", "标记原件有缺陷"]]
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
