// 消化外部材料（设计稿 09）：
// · 待消化面板（待决策页巡检栏下面）：外部原件登记后还没有消化记录的，由你点"交给 AI 消化"或"复制提示"（D-04、D-17）；
// · 原件页的"提取的论断"：引用这份原件、带原作者的判断，以及消化记录（D-09）。
// 待消化清单由系统在本机算出，不调用大模型；AI 消化时自己读原件、写文献论断、更新综合页。
import { useState } from "react";
import { call } from "./api";
import { go } from "./router";
import { copyText } from "./shell/toast";
import { Action, ErrorBox, IdLink, Tag, Time, useLoad } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function DigestPanel({ onChange }: { onChange?: () => void }) {
  const [data, error, reload] = useLoad(() => call<any>("digest.list", { limit: 50 }), []);
  const [agents] = useLoad(() => call<any[]>("agent.list").catch(() => []), []);
  const [agent, setAgent] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  if (error) return <ErrorBox error={error} />;
  if (!data || !data.total) return null;
  const usable = (agents ?? []).filter((a: any) => a.available);
  const chosen = agent || usable[0]?.name || "";
  const ids = data.items.slice(0, 20).map((i: any) => i.id);
  const refresh = () => (reload(), onChange?.());
  return (
    <div className="decision inspection-bar">
      <div className="decision-head">
        <Tag tone="accent">待消化</Tag>
        <span>{data.total} 份外部材料还没有提取论断</span>
        <span className="muted small-text">消化：读原件，把材料自己的发现写成文献论断（带原作者和原文给出的条件），再并进相关综合页</span>
      </div>
      <ul className="plain small-text">
        {data.items.slice(0, 10).map((i: any) => (
          <li key={i.id} className="row tight">
            <IdLink id={i.id} />
            <span className="muted">
              登记于 <Time value={i.created_at} />
              {i.claims ? ` · 已有 ${i.claims} 条论断` : ""}
            </span>
            <Action className="small" label="不需要消化" run={async () => (await call("digest.skip", { artifact_id: i.id, reason: "人在待决策页跳过" }), refresh())} />
          </li>
        ))}
        {data.total > 10 && <li className="muted">还有 {data.total - 10} 份</li>}
      </ul>
      <div className="row tight">
        {usable.length > 0 && (
          <select value={chosen} onChange={(e) => setAgent(e.target.value)} aria-label="消化用的 agent">
            {usable.map((a: any) => (
              <option key={a.name} value={a.name}>
                {a.name}
              </option>
            ))}
          </select>
        )}
        <Action
          className="primary"
          label={`交给 AI 消化（前 ${ids.length} 份）`}
          disabled={!chosen}
          run={async () => {
            const p = await call<any>("digest.prompt", { artifact_ids: ids });
            const run = await call<any>("agent.start", { agent: chosen, prompt: p.prompt });
            if (run.data?.terminal) go("agent", run.id);
            setMsg(`已启动 ${chosen}（${run.id}）：输出在 Agent 页，消化完的材料会从这里消失`);
          }}
        />
        <Action
          label="复制提示"
          run={async () => {
            const p = await call<any>("digest.prompt", { artifact_ids: ids });
            setPrompt(p.prompt);
            await copyText(p.prompt, "提示已复制：交给任何连了 burrowl MCP 的 AI 客户端");
          }}
        />
        <span className="muted small-text">清单在本机算出，不调用大模型；只有你点按钮才会启动 agent</span>
      </div>
      {!usable.length && <p className="muted small-text">本机没有可用的 agent 命令：可以先复制提示，或到设置的「Agent」配置。</p>}
      {msg && <p className="small-text">{msg}</p>}
      {prompt && <textarea readOnly value={prompt} rows={3} className="mono" />}
    </div>
  );
}

// 原件页：从这份原件提取的论断与消化记录（D-09）
export function DigestInfo({ artifactId }: { artifactId: string }) {
  const [data, error, reload] = useLoad(() => call<any>("digest.view", { artifact_id: artifactId }), [artifactId]);
  if (error) return <ErrorBox error={error} />;
  if (!data || (!data.external && !data.claims.length)) return null;
  return (
    <section className="panel digest-info" aria-label="提取的论断">
      <div className="row tight">
        <h3>从这份原件提取的论断</h3>
        {data.pending ? <Tag tone="warn">待消化</Tag> : data.records.length ? <Tag tone="good">已消化</Tag> : null}
      </div>
      {data.claims.length ? (
        <ul className="plain">
          {data.claims.map((id: string) => (
            <li key={id}>
              <IdLink id={id} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small-text">还没有提取论断。</p>
      )}
      {data.records.map((r: any) => (
        <p key={r.id} className="muted small-text">
          {r.skipped ? "人决定不需要消化" : `消化：${r.claims.length} 条论断`}
          {r.note ? `（${r.note}）` : ""} · <Time value={r.at} /> · {r.by}
        </p>
      ))}
      {data.pending && (
        <div className="row tight">
          <Action
            label="复制消化提示"
            run={async () => {
              const p = await call<any>("digest.prompt", { artifact_ids: [artifactId] });
              await copyText(p.prompt, "提示已复制：交给任何连了 burrowl MCP 的 AI 客户端");
            }}
          />
          <Action label="不需要消化" run={async () => (await call("digest.skip", { artifact_id: artifactId, reason: "人在原件页跳过" }), reload())} />
        </div>
      )}
    </section>
  );
}
