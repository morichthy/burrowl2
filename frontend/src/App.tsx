import { useEffect, useRef, useState } from "react";
import { call, streamAgent } from "./api";
import { DECISION, FRESHNESS, JUDGMENT_KIND, LAYER, REVIEW } from "./labels";
import { Action, Coordinates, ErrorBox, IdLink, RefText, useLoad } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Tab = "home" | "search" | "entry" | "pages" | "decisions" | "record" | "agent";
const TABS: [Tab, string][] = [
  ["home", "概览"],
  ["search", "检索"],
  ["entry", "条目"],
  ["pages", "框架页"],
  ["decisions", "待决策"],
  ["record", "记录"],
  ["agent", "Agent"],
];

export default function App() {
  const [tab, setTab] = useState<Tab>("home");
  const [entryId, setEntryId] = useState("");
  // 交给 agent 的任务文本：从其他页面一键带入 Agent 页
  const [agentPrompt, setAgentPrompt] = useState("");
  const open = (id: string) => {
    setEntryId(id);
    setTab("entry");
  };
  const delegate = (prompt: string) => {
    setAgentPrompt(prompt);
    setTab("agent");
  };
  return (
    <div className="app">
      <header>
        <strong>burrowl</strong>
        <nav>
          {TABS.map(([key, label]) => (
            <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === "home" && <Home open={open} go={setTab} />}
        {tab === "search" && <Search open={open} />}
        {tab === "entry" && <Entry id={entryId} setId={setEntryId} open={open} delegate={delegate} />}
        {tab === "pages" && <Pages open={open} delegate={delegate} />}
        {tab === "decisions" && <Decisions open={open} delegate={delegate} />}
        {tab === "record" && <Record open={open} />}
        {tab === "agent" && <Agent prompt={agentPrompt} setPrompt={setAgentPrompt} open={open} />}
      </main>
    </div>
  );
}

// ---------- 概览 ----------
function Home({ open, go }: { open: (id: string) => void; go: (t: Tab) => void }) {
  const [status, error] = useLoad(() => call("system.status"), []);
  const [decisions] = useLoad(() => call<any[]>("decision.list", { status: "open" }), []);
  const [changed] = useLoad(() => call<any[]>("page.list", { freshness: "inputs_changed" }), []);
  const [runs] = useLoad(() => call<any[]>("agent.runs", { limit: 5 }), []);
  const byKind: Record<string, number> = {};
  for (const d of decisions ?? []) byKind[d.kind] = (byKind[d.kind] ?? 0) + 1;
  return (
    <section>
      <ErrorBox error={error} />
      {status && (
        <div className="cards">
          <div className="card">
            <h3>原件一列</h3>
            <p>原件 {status.ledger.artifacts} · 过程事件 {status.ledger.events} · 事实记录 {status.ledger.records} · 读取记录 {status.ledger.reads}</p>
          </div>
          <div className="card">
            <h3>判断一列</h3>
            <p>判断 {status.ledger.judgments} · 关系 {status.ledger.links}</p>
          </div>
          <div className="card">
            <h3>框架</h3>
            <p>实体 {status.framework.entities} · 页面 {status.framework.pages} · 边 {status.framework.edges}</p>
          </div>
          <div className="card clickable" onClick={() => go("decisions")}>
            <h3>待决策 {status.open_decisions}</h3>
            <p>{Object.entries(byKind).map(([k, n]) => `${DECISION[k] ?? k} ${n}`).join(" · ") || "无"}</p>
          </div>
        </div>
      )}
      <h2>输入已变化的框架页</h2>
      {(changed ?? []).length === 0 && <p className="muted">没有</p>}
      <ul>
        {(changed ?? []).map((p) => (
          <li key={p.id}>
            <IdLink id={p.id} open={open} /> {p.title}
          </li>
        ))}
      </ul>
      <h2>最近的 agent 运行</h2>
      <ul>
        {(runs ?? []).map((r) => (
          <li key={r.id}>
            <span className="mono">{r.id}</span> {r.agent} · {r.status} · {r.data.prompt?.slice(0, 60)}
          </li>
        ))}
      </ul>
      {status && <p className="muted">数据目录：{status.data} · 版本 {status.version}</p>}
    </section>
  );
}

// ---------- 检索 ----------
function Search({ open }: { open: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("reuse");
  const [objects, setObjects] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setError(null);
    try {
      setResult(await call("search", { query, mode, objects: splitList(objects) }));
    } catch (e: any) {
      setError(e.message);
    }
  };
  return (
    <section>
      <div className="row">
        <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} placeholder="检索词，或设备编号、错误码" />
        <input value={objects} onChange={(e) => setObjects(e.target.value)} placeholder="对象（逗号分隔，可选）" />
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="reuse">复用（三列都返回）</option>
          <option value="explore">探索（不返回框架页）</option>
        </select>
        <button onClick={run}>检索</button>
      </div>
      <ErrorBox error={error} />
      {result && (
        <>
          {result.constraints.length > 0 && (
            <div className="constraints">
              <h3>相关的有效约束</h3>
              {result.constraints.map((c: any) => (
                <div key={c.id}>
                  <IdLink id={c.id} open={open} /> 【{JUDGMENT_KIND[c.kind]}】{c.text}
                </div>
              ))}
            </div>
          )}
          <p className="muted">共 {result.total} 条，按"依据来源 → 综合程度 → 复核"逐级排序；被替代的排在最后</p>
          {result.hits.map((h: any) => (
            <div key={h.id} className={`hit ${h.superseded ? "superseded" : ""}`}>
              <div>
                <IdLink id={h.locator && h.locator.startsWith("seg:") ? `${h.id}#seg-${h.ordinal}` : h.id} open={open} /> <Coordinates c={h} />
              </div>
              <div className="snippet">{h.text}</div>
            </div>
          ))}
        </>
      )}
    </section>
  );
}

// ---------- 条目 ----------
function Entry({ id, setId, open, delegate }: { id: string; setId: (s: string) => void; open: (id: string) => void; delegate: (p: string) => void }) {
  const [input, setInput] = useState(id);
  useEffect(() => setInput(id), [id]);
  const base = id.split("#")[0].split("@")[0];
  const [data, error, reload] = useLoad(() => (id ? call("entry.get", { id }) : Promise.resolve(null)), [id]);
  const [expand] = useLoad(() => (id && !base.startsWith("pg_") && !base.startsWith("ent_") ? call("entry.expand", { id }) : Promise.resolve(null)), [id]);
  const [page] = useLoad(() => (base.startsWith("pg_") ? call("page.get", { page: id }) : Promise.resolve(null)), [id]);
  return (
    <section>
      <div className="row">
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setId(input.trim())} placeholder="条目 ID，如 jdg_… / art_…#seg-3 / pg_…@2" />
        <button onClick={() => setId(input.trim())}>打开</button>
      </div>
      <ErrorBox error={error} />
      {data && (
        <>
          <h2>
            <span className="mono">{base}</span> <Coordinates c={data.coordinates} />
          </h2>
          <EntryBody entry={data.entry} open={open} />
          {page && <PageView page={page} open={open} reload={reload} delegate={delegate} />}
          <Amend entry={data.entry} reload={reload} />
          {data.links_out?.length > 0 && <Links title="它指向" links={data.links_out} field="dst_id" open={open} />}
          {data.links_in?.length > 0 && <Links title="指向它" links={data.links_in} field="src_id" open={open} />}
          {expand && <Expand data={expand} open={open} />}
          {data.edges?.length > 0 && (
            <>
              <h3>关系图中的边</h3>
              <ul>
                {data.edges.map((e: any) => (
                  <li key={e.id}>
                    <IdLink id={e.src_id} open={open} /> —{e.rel}→ <IdLink id={e.dst_id} open={open} /> <span className="tag muted">{e.origin}</span> <span className="tag">{REVIEW[e.review] ?? e.review}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}

function EntryBody({ entry, open }: { entry: any; open: (id: string) => void }) {
  const d = entry.data ?? {};
  const kind = entry.entry_kind;
  return (
    <div className="entry">
      {kind === "judgment" && (
        <>
          <p>
            【{JUDGMENT_KIND[entry.kind] ?? entry.kind}】作者 {entry.author_id} · {entry.created_at}
            {d.external_author && ` · 原作者 ${d.external_author}（提取者 ${d.extracted_by}）`}
          </p>
          <RefText text={d.text} open={open} />
          {d.conditions && <p>条件：{d.conditions}</p>}
        </>
      )}
      {kind === "artifact" && (
        <p>
          {d.title ?? "（无标题）"} · {entry.kind} · {entry.storage === "managed" ? "受管保存" : `外部引用 ${entry.uri}`} · sha256 {entry.sha256.slice(0, 12)}…
          {entry.version_of && (
            <>
              {" "}
              · 旧版本 <IdLink id={entry.version_of} open={open} />
            </>
          )}
        </p>
      )}
      {kind === "record" && (
        <>
          <p>方法：{d.method ?? "—"} · 边界：{entry.boundary} · 缺口：{(d.gaps ?? []).join("、") || "无"}</p>
          <pre>{d.result}</pre>
        </>
      )}
      {kind === "read" && <pre>{d.excerpt}</pre>}
      {kind === "event" && (
        <>
          <p>
            {entry.op} · {entry.actor_id} · 会话 {entry.session_id} #{entry.seq}
          </p>
          <pre>{JSON.stringify({ input: d.input, conditions: d.conditions }, null, 2)}</pre>
          {d.output && <pre>{d.output}</pre>}
        </>
      )}
      {entry.objects?.length > 0 && (
        <p>
          对象：
          {entry.objects.map((o: string) => (o.startsWith("ent_") ? <IdLink key={o} id={o} open={open} /> : <span key={o} className="tag">{o}</span>))}
        </p>
      )}
    </div>
  );
}

function Links({ title, links, field, open }: { title: string; links: any[]; field: string; open: (id: string) => void }) {
  return (
    <>
      <h3>{title}</h3>
      <ul>
        {links.map((l) => (
          <li key={l.id}>
            {l.rel} <IdLink id={l[field]} open={open} /> {l.data?.condition && `（条件：${l.data.condition}）`}
          </li>
        ))}
      </ul>
    </>
  );
}

function Expand({ data, open }: { data: any; open: (id: string) => void }) {
  return (
    <div className="expand">
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
          <ul>
            {data.same_objects.map((s: any) => (
              <li key={s.id}>
                <IdLink id={s.id} open={open} /> <Coordinates c={s} /> {s.preview}
              </li>
            ))}
          </ul>
        </>
      )}
      {data.interpretations?.length > 0 && (
        <>
          <h3>④ 引用了它的判断（解读，不是原件内容）</h3>
          <ul>
            {data.interpretations.map((s: any) => (
              <li key={s.judgment_id + s.rel}>
                {s.rel} <IdLink id={s.judgment_id} open={open} /> {s.preview}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

// 人工修改入口：更正、撤回、原件有缺陷（草图 §4）。只在工作台提供。
function Amend({ entry, reload }: { entry: any; reload: () => void }) {
  const [reason, setReason] = useState("");
  const kind = entry.entry_kind;
  const modes: [string, string][] =
    kind === "judgment" ? [["correction", "更正（原来就错）"], ["retraction", "撤回（不再主张）"]] : ["artifact", "event", "record", "read"].includes(kind) ? [["defect", "标记原件有缺陷"]] : [];
  if (modes.length === 0) return null;
  return (
    <div className="amend">
      <h3>修改</h3>
      <p className="muted">原条目不会改变；系统写一条新判断指向它，并把受影响的框架页标为"输入已变化"。</p>
      <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="理由（必填）" />
      {modes.map(([mode, label]) => (
        <Action key={mode} label={label} run={async () => (await call("judgment.amend", { mode, target: entry.id, reason }), setReason(""), reload())} />
      ))}
    </div>
  );
}

// ---------- 框架页 ----------
function Pages({ open, delegate }: { open: (id: string) => void; delegate: (p: string) => void }) {
  const [freshness, setFreshness] = useState("");
  const [pages, error] = useLoad(() => call<any[]>("page.list", { freshness: freshness || null }), [freshness]);
  return (
    <section>
      <div className="row">
        <select value={freshness} onChange={(e) => setFreshness(e.target.value)}>
          <option value="">全部</option>
          {Object.entries(FRESHNESS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      <ErrorBox error={error} />
      <table>
        <thead>
          <tr>
            <th>页面</th>
            <th>类型</th>
            <th>版本</th>
            <th>复核</th>
            <th>时效</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(pages ?? []).map((p) => (
            <tr key={p.id}>
              <td>
                <a href="#" onClick={(e) => (e.preventDefault(), open(p.id))}>
                  {p.title}
                </a>
              </td>
              <td>{p.type}</td>
              <td>{p.head_version}</td>
              <td>{REVIEW[p.review]}</td>
              <td className={p.freshness !== "valid" ? "warn-text" : ""}>{FRESHNESS[p.freshness]}</td>
              <td>{p.freshness !== "valid" && <button onClick={() => delegate(rederivePrompt(p))}>交给 agent 重新综合</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function rederivePrompt(p: any): string {
  return `框架页 ${p.id}（${p.title}）的输入已变化。请用 page_get 读取它的当前版本和输入清单，用 entry_get / search 查看相关的新判断、更正与撤回，然后用 page_write 写出新版本（同一 slug：${p.slug}），inputs 列出实际依据的条目。不要修改判断层。`;
}

function PageView({ page, open, reload, delegate }: { page: any; open: (id: string) => void; reload: () => void; delegate: (p: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <div className="page">
      <h3>
        {page.page.title} · 第 {page.version} 版（共 {page.versions.length} 版）· {REVIEW[page.page.review]} · {FRESHNESS[page.page.freshness]}
      </h3>
      {page.superseded_inputs.length > 0 && <div className="warn-box">这一版用到的输入中有 {page.superseded_inputs.length} 条已被替代、更正或撤回</div>}
      <RefText text={page.body} open={open} />
      <h4>输入清单</h4>
      <ul>
        {page.inputs.map((i: string) => (
          <li key={i}>
            <IdLink id={i} open={open} />
          </li>
        ))}
      </ul>
      <div className="amend">
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="复核理由（必填）；复核结论会写回判断层" />
        <Action label="确认" run={async () => (await call("framework.review", { item_id: page.page.id, verdict: "confirm", reason }), reload())} />
        <Action label="驳回" className="danger" run={async () => (await call("framework.review", { item_id: page.page.id, verdict: "reject", reason }), reload())} />
        <button onClick={() => delegate(rederivePrompt(page.page))}>交给 agent 重新综合</button>
      </div>
    </div>
  );
}

// ---------- 待决策 ----------
function Decisions({ open, delegate }: { open: (id: string) => void; delegate: (p: string) => void }) {
  const [kind, setKind] = useState("");
  const [items, error, reload] = useLoad(() => call<any[]>("decision.list", { status: "open", kind: kind || null }), [kind]);
  return (
    <section>
      <div className="row">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">全部类型</option>
          {Object.entries(DECISION).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <span className="muted">按影响范围排序；不阻塞导入和写入</span>
      </div>
      <ErrorBox error={error} />
      {(items ?? []).length === 0 && <p className="muted">没有待决策项</p>}
      {(items ?? []).map((d) => (
        <DecisionItem key={d.id} d={d} open={open} reload={reload} delegate={delegate} />
      ))}
    </section>
  );
}

function DecisionItem({ d, open, reload, delegate }: { d: any; open: (id: string) => void; reload: () => void; delegate: (p: string) => void }) {
  const [reason, setReason] = useState("");
  const [newName, setNewName] = useState(d.data.term ?? "");
  const [newKind, setNewKind] = useState("device");
  return (
    <div className="decision">
      <div>
        <span className="tag">{DECISION[d.kind] ?? d.kind}</span> <span className="mono">{d.id}</span> · 影响 {d.impact}
        {d.subject_id && (
          <>
            {" "}
            · <IdLink id={d.subject_id} open={open} />
          </>
        )}
      </div>
      {d.kind === "term_link" && (
        <>
          <p>
            叫法「{d.data.term}」：{d.data.reason}
            {d.data.excerpt && <span className="muted">（原文：{d.data.excerpt}）</span>}
          </p>
          {d.data.candidates.map((c: any) => (
            <Action key={c.id} label={`是 ${c.kind}「${c.name}」`} run={async () => (await call("term.decide", { decision_id: d.id, entity_id: c.id }), reload())} />
          ))}
          <div className="row">
            <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="新实体名称" />
            <input value={newKind} onChange={(e) => setNewKind(e.target.value)} placeholder="类型" />
            <Action label="新建实体并连接" run={async () => (await call("term.decide", { decision_id: d.id, new_entity: { kind: newKind, name: newName } }), reload())} />
          </div>
        </>
      )}
      {d.kind === "review" && (
        <>
          <p>
            {d.data.what} {d.data.title ?? ""} {d.data.reason ?? ""}
          </p>
          <div className="row">
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="复核理由" />
            {(d.subject_id?.startsWith("pg_") || d.subject_id?.startsWith("edg_")) && (
              <>
                <Action label="确认" run={async () => (await call("framework.review", { item_id: d.subject_id, verdict: "confirm", reason }), reload())} />
                <Action label="驳回" className="danger" run={async () => (await call("framework.review", { item_id: d.subject_id, verdict: "reject", reason }), reload())} />
              </>
            )}
          </div>
        </>
      )}
      {d.kind === "rederive" && (
        <p>
          {d.data.title}：{d.data.reason} <button onClick={() => delegate(`处理待决策 ${d.id}：框架页 ${d.subject_id} 的输入已变化。请用 page_get 读取当前版本与输入清单，查看相关新判断后用 page_write 写出新版本，inputs 列出实际依据。`)}>交给 agent</button>
        </p>
      )}
      {d.kind === "constraint_unchecked" && (
        <p>
          {d.data.actor_id} 执行 {d.data.op} 前没有检查约束：{d.data.constraints.map((c: any) => c.text).join("；")}
        </p>
      )}
      {d.kind === "propagation_overflow" && <p>传播超过上限，{d.data.unchecked.length} 个条目标为"未核查"：{d.data.reason}</p>}
      <div className="row">
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="关闭理由" />
        <Action label="关闭" run={async () => (await call("decision.dismiss", { decision_id: d.id, reason: reason || "不处理" }), reload())} />
      </div>
    </div>
  );
}

// ---------- 记录（人写） ----------
function Record({ open }: { open: (id: string) => void }) {
  const [art, setArt] = useState({ kind: "file", source_class: "executed", path: "", text: "", title: "", storage: "managed", external_tier: "" });
  const [jd, setJd] = useState({ kind: "observation", text: "", objects: "", cites: "", conditions: "" });
  const [last, setLast] = useState<string | null>(null);
  return (
    <section className="forms">
      <div className="card">
        <h3>登记原件</h3>
        <p className="muted">只记原文与可核对的元数据。大文件可以只登记路径和指纹（外部引用）。</p>
        <div className="row">
          <select value={art.kind} onChange={(e) => setArt({ ...art, kind: e.target.value })}>
            {["file", "log", "literature", "dataset", "image", "conversation"].map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
          <select value={art.source_class} onChange={(e) => setArt({ ...art, source_class: e.target.value })}>
            <option value="executed">亲自执行或测量</option>
            <option value="external">外部报告</option>
            <option value="discussion">推断或讨论</option>
          </select>
          {art.source_class === "external" && (
            <select value={art.external_tier} onChange={(e) => setArt({ ...art, external_tier: e.target.value })}>
              <option value="">细分（可选）</option>
              <option value="peer_reviewed">同行评议</option>
              <option value="preprint">预印本</option>
              <option value="vendor">厂商资料</option>
              <option value="web">网页</option>
            </select>
          )}
          <select value={art.storage} onChange={(e) => setArt({ ...art, storage: e.target.value })}>
            <option value="managed">复制保存</option>
            <option value="referenced">只登记路径</option>
          </select>
        </div>
        <input value={art.title} onChange={(e) => setArt({ ...art, title: e.target.value })} placeholder="标题（可选）" />
        <input value={art.path} onChange={(e) => setArt({ ...art, path: e.target.value })} placeholder="本机文件路径（与下面的文本二选一）" />
        <textarea value={art.text} onChange={(e) => setArt({ ...art, text: e.target.value })} placeholder="或直接粘贴原文" />
        <Action
          label="登记"
          run={async () => {
            const r = await call("artifact.register", {
              kind: art.kind,
              source_class: art.source_class,
              storage: art.storage,
              title: art.title || null,
              external_tier: art.external_tier || null,
              ...(art.path ? { path: art.path } : { text: art.text }),
            });
            setLast(r.id);
          }}
        />
      </div>
      <div className="card">
        <h3>写判断（人）</h3>
        <p className="muted">你本人写下的现场观察记为"亲自执行或测量"；约束、决定、指令会在检索时排在最前。</p>
        <select value={jd.kind} onChange={(e) => setJd({ ...jd, kind: e.target.value })}>
          {["observation", "constraint", "decision", "instruction", "question", "claim", "purpose", "stop_reason"].map((k) => (
            <option key={k} value={k}>
              {JUDGMENT_KIND[k]}
            </option>
          ))}
        </select>
        <textarea value={jd.text} onChange={(e) => setJd({ ...jd, text: e.target.value })} placeholder="写全对象和条件，不用指代词" />
        <input value={jd.objects} onChange={(e) => setJd({ ...jd, objects: e.target.value })} placeholder="对象（逗号分隔），如 3号阀, P-102" />
        <input value={jd.cites} onChange={(e) => setJd({ ...jd, cites: e.target.value })} placeholder="依据 ID（逗号分隔，可选）" />
        <input value={jd.conditions} onChange={(e) => setJd({ ...jd, conditions: e.target.value })} placeholder="条件（可选）" />
        <Action
          label="写入"
          run={async () => {
            const r = await call("judgment.write", { kind: jd.kind, text: jd.text, objects: splitList(jd.objects), cites: splitList(jd.cites), conditions: jd.conditions || null });
            setLast(r.id);
          }}
        />
      </div>
      {last && (
        <p>
          已写入 <IdLink id={last} open={open} />
        </p>
      )}
    </section>
  );
}

// ---------- Agent ----------
function Agent({ prompt, setPrompt, open }: { prompt: string; setPrompt: (s: string) => void; open: (id: string) => void }) {
  const [agents] = useLoad(() => call<any[]>("agent.list"), []);
  const [agent, setAgent] = useState("");
  const [cwd, setCwd] = useState("");
  const [run, setRun] = useState<any>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [runs, , reloadRuns] = useLoad(() => call<any[]>("agent.runs", { limit: 20 }), []);
  const stop = useRef<() => void>(() => {});
  useEffect(() => () => stop.current(), []);
  useEffect(() => {
    if (!agent && agents?.length) setAgent((agents.find((a) => a.available) ?? agents[0]).name);
  }, [agents, agent]);
  const watch = (r: any) => {
    stop.current();
    setRun(r);
    setLines([]);
    setRunning(true);
    stop.current = streamAgent(
      r.id,
      (line) => setLines((ls) => [...ls, line]),
      () => (setRunning(false), reloadRuns()),
    );
  };
  return (
    <section>
      <p className="muted">在本机启动 agent CLI 处理任务。它通过 MCP 回到本工作区读写，身份记为这次运行的 AI；输出结束后登记为对话原件。</p>
      <div className="row">
        <select value={agent} onChange={(e) => setAgent(e.target.value)}>
          {(agents ?? []).map((a) => (
            <option key={a.name} value={a.name}>
              {a.name}
              {a.available ? "" : "（未找到命令）"}
            </option>
          ))}
        </select>
        <input value={cwd} onChange={(e) => setCwd(e.target.value)} placeholder="工作目录（可选，默认数据目录）" />
      </div>
      <textarea className="tall" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="任务，例如：读取 art_… 的巡检记录，判断 2号泵压力波动的可能原因，并写成判断" />
      <div className="row">
        <Action label="启动" run={async () => watch(await call("agent.start", { agent, prompt, cwd: cwd || null }))} />
        {running && run && <Action label="停止" className="danger" run={() => call("agent.cancel", { run_id: run.id })} />}
      </div>
      {run && (
        <>
          <h3>
            <span className="mono">{run.id}</span> {running ? "运行中…" : "已结束"}
          </h3>
          <pre className="console">{lines.join("")}</pre>
        </>
      )}
      <h3>运行记录</h3>
      <ul>
        {(runs ?? []).map((r) => (
          <li key={r.id}>
            <a href="#" onClick={(e) => (e.preventDefault(), watch(r))}>
              {r.id}
            </a>{" "}
            {r.agent} · {r.status} · {r.data.prompt?.slice(0, 50)}
            {r.data.artifact_id && (
              <>
                {" "}
                · 对话原件 <IdLink id={r.data.artifact_id} open={open} />
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function splitList(s: string): string[] | null {
  const items = s
    .split(/[,，]/)
    .map((x) => x.trim())
    .filter(Boolean);
  return items.length ? items : null;
}

export { LAYER };
