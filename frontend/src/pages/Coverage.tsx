// 覆盖图（设计稿 07 D-10、D-11）：原件段落分五档。它是框架内容、不能作为依据；
// "没读过"不等于"有用"，所以这里不给覆盖率数字，只帮你看盲区在哪里（原则 4）。
import { COVERAGE_STATE } from "../labels";
import { call } from "../api";
import { href } from "../router";
import { Empty, ErrorBox, IdLink, Panel, Tag, Time, useLoad } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

const STATES = Object.keys(COVERAGE_STATE);
const MAX_CELLS = 400;

function Legend() {
  return (
    <div className="row tight small-text cov-legend">
      {STATES.map((s) => (
        <span key={s} className="row tight">
          <span className={`cov-cell ${s}`} /> {COVERAGE_STATE[s]}
        </span>
      ))}
    </div>
  );
}

export function Coverage({ artifactId }: { artifactId?: string }) {
  return artifactId ? <CoverageDetail artifactId={artifactId} /> : <CoverageOverview />;
}

function CoverageOverview() {
  const [data, error] = useLoad(() => call<any>("coverage.view"), []);
  const s = data?.settings;
  return (
    <>
      <Panel title="覆盖图" actions={<span className="muted">框架内容，不能作为依据；没读过不等于有用</span>}>
        <ErrorBox error={error} />
        <p className="muted small-text">
          每格是原件的一个段落。命中未读：{s?.window_days ?? "…"} 天内被 AI 检索返回不少于 {s?.hit_min ?? "…"} 次、从没被读；相关未读：和最近 30 天的判断最相关、从没被读。巡检包每期从这两档里抽一部分交给巡检员读。
        </p>
        <Legend />
        {data && (
          <p className="small-text">
            {STATES.map((k) => `${COVERAGE_STATE[k]} ${data.totals[k]}`).join(" · ")}
          </p>
        )}
        {data && data.artifacts.length === 0 && <Empty>还没有可读的原件</Empty>}
        <table className="cov-table">
          <tbody>
            {(data?.artifacts ?? []).map((a: any) => (
              <tr key={a.id}>
                <th>
                  <a href={href("coverage", a.id)}>{a.title ?? a.id}</a>
                  {!a.outbound && <Tag tone="warn">不外发</Tag>}
                  <div className="muted small-text">
                    {a.total} 段 · 命中未读 {a.counts.hit_unread} · 相关未读 {a.counts.related_unread}
                  </div>
                </th>
                <td>
                  <div className="cov-strip">
                    {a.cells.slice(0, MAX_CELLS).map((c: string, i: number) => (
                      <span key={i} className={`cov-cell ${c}`} title={COVERAGE_STATE[c]} />
                    ))}
                    {a.cells.length > MAX_CELLS && <span className="muted small-text">…还有 {a.cells.length - MAX_CELLS} 段</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      {data && data.objects.length > 0 && (
        <Panel title="按对象汇总">
          <table className="kv">
            <tbody>
              {data.objects.map((o: any) => (
                <tr key={o.object}>
                  <th>
                    <IdLink id={o.object} />
                  </th>
                  <td className="small-text">{STATES.map((k) => `${COVERAGE_STATE[k]} ${o.counts[k]}`).join(" · ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </>
  );
}

function CoverageDetail({ artifactId }: { artifactId: string }) {
  const [data, error] = useLoad(() => call<any>("coverage.view", { artifact_id: artifactId }), [artifactId]);
  return (
    <Panel title={`覆盖图：${data?.artifact?.title ?? artifactId}`} actions={<a href={href("coverage")}>← 全部原件</a>}>
      <ErrorBox error={error} />
      <Legend />
      {data && !data.artifact.outbound && <p className="small-text warn-text">这份原件标为不外发：巡检包里不含它的原文，巡检运行里读不到。</p>}
      <table className="cov-detail">
        <tbody>
          {(data?.segments ?? []).map((s: any) => (
            <tr key={s.anchor}>
              <td>
                <span className={`cov-cell ${s.state}`} title={COVERAGE_STATE[s.state]} />
              </td>
              <td className="mono">
                <a href={href("entry", `${artifactId}#${s.anchor}`)}>{s.anchor}</a>
              </td>
              <td>
                {s.head}
                <div className="muted small-text">
                  {COVERAGE_STATE[s.state]}
                  {s.hits ? ` · 检索返回 ${s.hits} 次` : ""}
                  {s.sessions ? ` · ${s.sessions} 个会话读过` : ""}
                  {s.related != null ? ` · 相关度 ${s.related}` : ""}
                  {s.last_read && (
                    <>
                      {" · 最后读于 "}
                      <Time value={s.last_read} />
                    </>
                  )}
                </div>
                {s.cited_by?.length > 0 && (
                  <div className="row tight small-text">
                    <span className="muted">引用它的判断</span>
                    {s.cited_by.slice(0, 5).map((id: string) => (
                      <IdLink key={id} id={id} />
                    ))}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
