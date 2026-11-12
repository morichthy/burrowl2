// 阅读会话（设计稿 13）：AI 通过 MCP 查询 burrowl 的每个会话一条。
// "读了什么"由读取记录与检索命中算出；目的、认知、handoff 是 AI 自己维护的会话笔记（reading_note），
// 都是过程内容，不能作为依据。handoff 由 AI 提交快照：agent 已有自己的 handoff 就提交进来，没有就由 AI 写。
import { useEffect, useState } from "react";
import { call } from "../api";
import { href } from "../router";
import { copyText } from "../shell/toast";
import { Empty, ErrorBox, IdLink, Loading, Panel, RefText, Tag, Time, useLoad, usePoll } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

const shortId = (id: string) => (id.length > 16 ? `${id.slice(0, 16)}…` : id);

export function handoffPrompt(sessionId: string): string {
  return `请用 reading_note 为当前阅读会话（${sessionId}）补上 handoff：如果你的运行环境已有 handoff 或交接文件，把内容提交进来，并在 handoff_source 填它的绝对路径（工作台会实时读这个文件）；没有就直接写一份可交接或可用于写作的进展（目的、已得认知与依据、未解决的问题、下一步）。`;
}

// 首页卡片：最近几个阅读会话，点进去看详情
export function ReadingCard() {
  const [items, error, reload] = useLoad(() => call<any[]>("reading.list", { limit: 5 }), []);
  usePoll(reload, 10000);
  return (
    <Panel title="阅读会话" actions={<a href={href("reading")}>全部</a>}>
      <ErrorBox error={error} />
      {items && items.length === 0 && <Empty compact icon="search">AI 查询 burrowl 后，它读了什么、得到什么认知会出现在这里。</Empty>}
      {items && items.length > 0 && (
        <ul className="reading-list">
          {items.map((s) => (
            <li key={s.session_id}>
              <a href={href("reading", s.session_id)}>
                <span className="reading-purpose">{s.purpose || <span className="muted">（AI 还没写目的）</span>}</span>
                <span className="reading-meta small-text muted">
                  读原件 {s.artifacts_read} · 检索 {s.searches} · 认知 {s.findings}
                  {s.has_handoff ? " · 有 handoff" : ""}
                </span>
                <Time value={s.last_at} />
              </a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function Reading({ sessionId }: { sessionId?: string }) {
  return sessionId ? <ReadingDetail sessionId={sessionId} /> : <ReadingList />;
}

function ReadingList() {
  const [items, error, reload] = useLoad(() => call<any[]>("reading.list", { limit: 100 }), []);
  usePoll(reload, 10000);
  return (
    <Panel title="阅读会话" actions={<span className="muted">AI 的过程笔记，不能作为依据</span>}>
      <ErrorBox error={error} />
      {!items && !error && <Loading rows={4} />}
      {items && items.length === 0 && <Empty icon="search">还没有 AI 查询过 burrowl。</Empty>}
      {items && items.length > 0 && (
        <ul className="reading-list wide">
          {items.map((s) => (
            <li key={s.session_id}>
              <a href={href("reading", s.session_id)}>
                <span className="reading-purpose">{s.purpose || <span className="muted">（AI 还没写目的）</span>}</span>
                <span className="reading-meta small-text muted">
                  {s.actor} · 读原件 {s.artifacts_read} · 检索 {s.searches} · 认知 {s.findings} 条
                </span>
                {s.has_handoff ? <Tag tone="good">有 handoff</Tag> : <Tag>无 handoff</Tag>}
                <Time value={s.last_at} />
              </a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function ReadingDetail({ sessionId }: { sessionId: string }) {
  const [view, error, reload] = useLoad(() => call<any>("reading.get", { session_id: sessionId }), [sessionId]);
  usePoll(reload, 5000);
  if (error) return <ErrorBox error={error} />;
  if (!view) return <Loading rows={4} />;
  const unread = (view.returned as any[]).filter((h) => !h.read);
  return (
    <div className="reading">
      <Panel
        title={view.purpose || "（AI 还没写这次阅读的目的）"}
        actions={<span className="muted small-text" title={sessionId}>{view.actor} · {shortId(sessionId)}</span>}
      >
        <p className="muted small-text">
          <Time value={view.started_at} /> 开始，<Time value={view.last_at} /> 最后活动。目的、认知、handoff 是 AI 自己写的过程笔记，不能作为依据；要用请回到下面的原件与判断。
        </p>
      </Panel>

      <Panel title={`得到的认知（${view.findings.length}）`}>
        {view.findings.length === 0 ? (
          <Empty compact icon="bolt">AI 还没有写下认知。</Empty>
        ) : (
          <ol className="findings">
            {view.findings.map((f: any, i: number) => (
              <li key={i}>
                <p>{f.text}</p>
                {f.refs?.length > 0 && (
                  <p className="small-text muted">依据：{f.refs.map((r: string) => <span key={r}> <IdLink id={r} /></span>)}</p>
                )}
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <Panel title="这次用了 burrowl 的什么">
        <h4>读过的原件（{view.read.length}）</h4>
        {view.read.length === 0 ? (
          <p className="muted small-text">没有读过原件原文。</p>
        ) : (
          <ul className="reading-items">
            {view.read.map((r: any) => (
              <li key={r.id}>
                <IdLink id={r.id} />
                <span className="muted small-text">读了 {r.anchors.length} 段{r.times > 1 ? `（${r.times} 次）` : ""}</span>
                <a className="small-text" href={href("read", r.id)}>阅读</a>
              </li>
            ))}
          </ul>
        )}
        <h4>检索命中但没读原文（{unread.length}）</h4>
        {unread.length === 0 ? (
          <p className="muted small-text">命中的条目都读过，或没有检索。</p>
        ) : (
          <ul className="reading-items">
            {unread.map((h: any) => (
              <li key={h.id}><IdLink id={h.id} /><Tag title="只在检索结果里见到，没有读取记录">参考过</Tag></li>
            ))}
          </ul>
        )}
        <h4>写下的判断（{view.written.length}）</h4>
        {view.written.length === 0 ? (
          <p className="muted small-text">这次没有写判断。</p>
        ) : (
          <ul className="reading-items">
            {view.written.map((w: any) => (
              <li key={`${w.id}@${w.version}`}><IdLink id={w.id} /><span className="muted small-text">第 {w.version} 版</span></li>
            ))}
          </ul>
        )}
        <details>
          <summary>检索记录（{view.searches.length}）</summary>
          <ul className="reading-items">
            {view.searches.map((s: any, i: number) => (
              <li key={i}><Time value={s.at} /> <span>{s.query}</span><span className="muted small-text">{s.mode} · 返回 {s.hits.length} 条</span></li>
            ))}
          </ul>
        </details>
      </Panel>

      <HandoffPanel sessionId={sessionId} view={view} />
    </div>
  );
}

// Handoff：AI 登记了文件路径就实时读那个文件（人点"阅读"才读，展开期间每 3 秒刷新）；读不到退回 AI 提交的快照
function HandoffPanel({ sessionId, view }: { sessionId: string; view: any }) {
  const [open, setOpen] = useState(false);
  const [live, setLive] = useState<any>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const hasSource = !!view.handoff_source;
  useEffect(() => {
    if (!open || !hasSource) return;
    let stop = false;
    const load = () => call<any>("reading.handoff_file", { session_id: sessionId })
      .then((r) => { if (!stop) { setLive(r); setLiveError(null); } })
      .catch((e) => { if (!stop) setLiveError(e.message); });
    void load();
    const timer = window.setInterval(load, 3000);
    return () => { stop = true; window.clearInterval(timer); };
  }, [open, hasSource, sessionId, view.handoff_source]);
  const isLive = open && live?.available;
  const text: string | null = isLive ? live.text : view.handoff;
  const available = !!(view.handoff || hasSource);
  return (
    <Panel
      title="Handoff"
      actions={
        available ? (
          <>
            <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "收起 handoff" : "阅读 handoff"}</button>
            {text && <button type="button" onClick={() => void copyText(text, "已复制 handoff")}>复制</button>}
          </>
        ) : (
          <button type="button" onClick={() => void copyText(handoffPrompt(sessionId), "已复制给 AI 的提示")}>复制提示，让 AI 补一份</button>
        )
      }
    >
      {available ? (
        <>
          <p className="muted small-text">
            {isLive ? (
              <>实时读取自 <code>{live.path}</code>，文件修改于 <Time value={live.modified_at} />，展开期间每 3 秒刷新。</>
            ) : view.handoff ? (
              <>AI 提交的快照，更新于 <Time value={view.handoff_at} />
                {hasSource ? <>，来源 <code>{view.handoff_source}</code></> : "，由 AI 直接撰写"}。</>
            ) : (
              <>AI 登记了文件 <code>{view.handoff_source}</code>，但没有提交快照；点“阅读 handoff”读取。</>
            )}
            {open && hasSource && !isLive && (liveError ?? live?.reason) && <> 实时读取失败：{liveError ?? live.reason}。{view.handoff ? "下面显示的是快照。" : ""}</>}
          </p>
          {open && text && <RefText text={text} />}
        </>
      ) : (
        <Empty compact icon="inbox">AI 还没有提交 handoff。agent 自己有 handoff 时它应把内容提交进来并登记文件路径，没有就由它直接写；点右上角复制提示交给它。</Empty>
      )}
    </Panel>
  );
}
