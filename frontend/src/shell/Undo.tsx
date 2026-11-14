// 撤销到某个时刻（设计稿 14 D-10 至 D-17）：首页最新动态的每一行都能"撤销到这里"。
// 先预览要删掉的全部内容（所有人、所有会话），确认后执行；删掉的内容存进数据目录 undo/ 下的恢复包，
// 撤销那一行上有"恢复"按钮。只有人能做（undo.* 是 effect=user，不在 MCP 里）。
import { useEffect, useState } from "react";
import { call } from "../api";
import { Action, IdLink } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

const TABLE: Record<string, string> = {
  artifact_versions: "原件版本",
  judgment_versions: "判断版本",
  record_versions: "事实记录版本",
  event_versions: "过程日志与系统流水",
  read_versions: "读取记录",
  relations: "关系",
  version_states: "处置记录",
  extractions: "抽取记录",
  reviews: "复核记录",
  replacements: "替换记录",
  artifact_policies: "外发标记",
  judgment_titles: "标题",
  entry_objects: "对象标签",
  entities: "实体",
  aliases: "别名",
  pages: "框架页",
  page_versions: "框架页版本",
  edges: "关系图的边",
  decisions: "待决策",
  derivation_inputs: "框架输入清单",
};

const who = (actor: string) => (actor.startsWith("human:") ? "人" : actor.startsWith("ai:") ? "AI" : "系统") + ` ${actor.split(":").slice(1).join(":")}`;

export function UndoButton({ at, label }: { at: string; label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="link small-text undo-here" title="把数据回到这一条之前（预览后确认）" onClick={() => setOpen(true)}>
        撤销到这里…
      </button>
      {open && <UndoDialog at={at} label={label} onClose={() => setOpen(false)} />}
    </>
  );
}

// 恢复要点两次：第一次只换成"确认恢复"，不弹浏览器对话框
export function RestoreButton({ undoId }: { undoId: string }) {
  const [asking, setAsking] = useState(false);
  if (!asking)
    return (
      <button type="button" className="small" title="把这次撤销删掉的内容放回去" onClick={() => setAsking(true)}>
        恢复…
      </button>
    );
  return (
    <span className="row tight">
      <Action
        className="small solid"
        label="确认恢复"
        title="把这次撤销删掉的内容全部放回去（只能恢复一次）"
        run={async () => {
          await call("undo.restore", { undo_id: undoId });
          window.location.reload();
        }}
      />
      <button type="button" className="small" onClick={() => setAsking(false)}>取消</button>
    </span>
  );
}

function UndoDialog({ at, label, onClose }: { at: string; label: string; onClose: () => void }) {
  const [include, setInclude] = useState(true);
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    setPreview(null);
    setChecked(false);
    call<any>("undo.preview", { at, include }).then(setPreview, (e) => setError(String(e?.message ?? e)));
  }, [at, include]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const counts = Object.entries((preview?.counts ?? {}) as Record<string, number>);
  const empty = preview && counts.length === 0;
  return (
    <div className="modal-backdrop top" onClick={onClose}>
      <div className="modal purge" role="dialog" aria-modal="true" aria-label="撤销到这里" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>撤销到「{label.slice(0, 40)}」</h3>
          <p className="muted small-text">
            时间 <code>{at}</code>。这一刻之后所有人、所有会话写入的内容都会删掉（不只是这一条）。
          </p>
          <div className="segctl" role="radiogroup" aria-label="这一条本身">
            <button type="button" role="radio" aria-checked={include} className={include ? "on" : ""} onClick={() => setInclude(true)}>连这一条一起撤销</button>
            <button type="button" role="radio" aria-checked={!include} className={!include ? "on" : ""} onClick={() => setInclude(false)}>保留这一条</button>
          </div>
        </header>
        <div className="modal-body">
          {error && <p className="bad-text">{error}</p>}
          {!preview && !error && <p className="muted">正在列出影响范围…</p>}
          {empty && <p className="muted">这之后没有写入，不需要撤销。</p>}
          {preview && !empty && (
            <>
              <section>
                <h4>删掉的条目或版本（{preview.entries.length}）</h4>
                <ul className="purge-list">
                  {preview.entries.slice(0, 60).map((e: any) => (
                    <li key={e.id}>
                      <div className="purge-item-head">
                        <IdLink id={e.id} name={e.label} />{" "}
                        <span className="tag">{e.whole ? "整条删除" : `删掉第 ${e.versions.join("、")} 版`}</span>
                        {e.by && <span className="muted small-text"> {who(e.by)}</span>}
                      </div>
                    </li>
                  ))}
                </ul>
                {preview.entries.length > 60 && <p className="muted small-text">还有 {preview.entries.length - 60} 条未列出。</p>}
              </section>
              <section>
                <h4>谁写的</h4>
                <p className="muted">{Object.entries(preview.by_actor as Record<string, number>).map(([a, n]) => `${who(a)} ${n} 行`).join("；")}</p>
              </section>
              {preview.pages_rolled_back.length > 0 && (
                <section>
                  <h4>回到那时最后一版、需要重新综合的框架页（{preview.pages_rolled_back.length}）</h4>
                  <ul className="purge-list">
                    {preview.pages_rolled_back.map((id: string) => <li key={id}><IdLink id={id} /></li>)}
                  </ul>
                </section>
              )}
              <section>
                <h4>各类记录</h4>
                <p className="muted">
                  {counts.map(([t, n]) => `${TABLE[t] ?? t} ${n}`).join("；")}
                  {preview.blobs > 0 && `；文件 ${preview.blobs} 个`}。
                </p>
                <p className="small-text">{preview.note}。</p>
              </section>
            </>
          )}
        </div>
        <footer>
          <input className="grow" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="理由（记在系统流水里，可不填）" />
          <label className="purge-confirm">
            <input type="checkbox" aria-label="我看过上面的列表" checked={checked} onChange={(e) => setChecked(e.target.checked)} disabled={!preview || empty} /> 我看过上面的列表
          </label>
          <div className="row tight">
            <button type="button" onClick={onClose}>取消</button>
            <Action
              label="撤销"
              className="danger solid"
              disabled={!preview || empty || !checked}
              run={async () => {
                await call("undo.apply", { at, include, confirm: preview.confirm, reason });
                window.location.reload();
              }}
            />
          </div>
        </footer>
      </div>
    </div>
  );
}
