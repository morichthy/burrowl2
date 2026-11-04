// 人工记录：人登记原件、写判断（结论、过程、规定）。勾选"本地实证"的结论表示你亲自看到或测到。
import { useState } from "react";
import { call } from "../api";
import { KIND_HINT, WRITABLE_KIND } from "../labels";
import { Action, Chips, IdLink, Panel } from "../ui";
import { splitList } from "./Search";

export function Record() {
  const [art, setArt] = useState({ kind: "file", source_class: "local", path: "", text: "", title: "", storage: "managed", external_tier: "" });
  const [jd, setJd] = useState({ kind: "conclusion", text: "", objects: "", cites: "", conditions: "", local: false, reopen: "" });
  const [last, setLast] = useState<string | null>(null);
  return (
    <div className="forms">
      <Panel title="登记原件">
        <p className="muted">只记原文与可核对的元数据。大文件可以只登记路径和指纹（外部引用）。</p>
        <span className="filter-label">类型</span>
        <Chips all={null} options={[["file", "文件"], ["log", "记录/日志"], ["literature", "文献"], ["dataset", "数据集"], ["image", "图片"], ["conversation", "对话"]]} value={[art.kind]} onChange={(v) => setArt({ ...art, kind: v[0] ?? "file" })} />
        <span className="filter-label">依据来源</span>
        <Chips all={null} options={[["local", "本地实证"], ["external", "外部报告"], ["inferred", "推断"]]} value={[art.source_class]} onChange={(v) => setArt({ ...art, source_class: v[0] ?? "local" })} />
        {art.source_class === "external" && (
          <Chips all="细分未知" options={[["peer_reviewed", "同行评议"], ["preprint", "预印本"], ["vendor", "厂商资料"], ["web", "网页"]]} value={art.external_tier ? [art.external_tier] : []} onChange={(v) => setArt({ ...art, external_tier: v[0] ?? "" })} />
        )}
        <span className="filter-label">保存方式</span>
        <Chips all={null} options={[["managed", "复制保存"], ["referenced", "只登记路径和指纹"]]} value={[art.storage]} onChange={(v) => setArt({ ...art, storage: v[0] ?? "managed" })} />
        <input value={art.title} onChange={(e) => setArt({ ...art, title: e.target.value })} placeholder="标题（可选）" />
        <input value={art.path} onChange={(e) => setArt({ ...art, path: e.target.value })} placeholder="本机文件路径（与下面的文本二选一）" />
        <textarea value={art.text} onChange={(e) => setArt({ ...art, text: e.target.value })} placeholder="或直接粘贴原文" />
        <Action
          label="登记"
          className="primary"
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
      </Panel>
      <Panel title="写判断（人）">
        <span className="filter-label">判断类型</span>
        <Chips all={null} options={Object.entries(WRITABLE_KIND)} value={[jd.kind]} onChange={(v) => setJd({ ...jd, kind: v[0] ?? "conclusion" })} />
        <p className="muted">{KIND_HINT[jd.kind]}</p>
        {jd.kind === "conclusion" && (
          <label className="check">
            <input type="checkbox" checked={jd.local} onChange={(e) => setJd({ ...jd, local: e.target.checked })} />
            本地实证：这是我亲自看到或测到的
          </label>
        )}
        <textarea value={jd.text} onChange={(e) => setJd({ ...jd, text: e.target.value })} placeholder="写全对象和条件，不用指代词" />
        <input value={jd.objects} onChange={(e) => setJd({ ...jd, objects: e.target.value })} placeholder="对象（逗号分隔），如 3号阀, P-102" />
        <input value={jd.cites} onChange={(e) => setJd({ ...jd, cites: e.target.value })} placeholder="依据 ID（逗号分隔，可选）" />
        <input value={jd.conditions} onChange={(e) => setJd({ ...jd, conditions: e.target.value })} placeholder="条件（可选）" />
        {jd.kind === "process" && <input value={jd.reopen} onChange={(e) => setJd({ ...jd, reopen: e.target.value })} placeholder="重开条件（可选）：停下的路线在什么条件下值得重新打开" />}
        <Action
          label="写入"
          className="primary"
          run={async () => {
            const r = await call("judgment.write", {
              kind: jd.kind,
              text: jd.text,
              objects: splitList(jd.objects),
              cites: splitList(jd.cites),
              conditions: jd.conditions || null,
              local_observation: jd.kind === "conclusion" && jd.local,
              reopen_condition: jd.kind === "process" && jd.reopen ? jd.reopen : null,
            });
            setLast(r.id);
          }}
        />
      </Panel>
      {last && (
        <p>
          已写入 <IdLink id={last} />
        </p>
      )}
    </div>
  );
}
