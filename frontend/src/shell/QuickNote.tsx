// 记一笔（按 n）：不离开当前页，写一条人的判断或登记一份原件。和人工记录页调用同样的操作（judgment.write、artifact.register）；
// 写入是追加：写下后不能改，只能更正或撤回。可信度由系统推出，这里只显示规则，不让人声明。
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { call } from "../api";
import { EntryPicker } from "../EntryPicker";
import { KIND_HINT, WRITABLE_KIND } from "../labels";
import { splitList } from "../pages/Search";
import { go, href } from "../router";
import { ErrorBox } from "../ui";
import { Stamp } from "./Stamp";
import { toast } from "./toast";

type Mode = "judgment" | "artifact";
type Seed = { mode?: Mode; cites?: string[]; objects?: string[] };
type State = { open: boolean; seed: Seed; n: number };

let state: State = { open: false, seed: {}, n: 0 };
const listeners = new Set<() => void>();
function set(next: State) {
  state = next;
  for (const l of listeners) l();
}
export function openQuickNote(seed: Seed = {}): void {
  set({ open: true, seed, n: state.n + 1 });
}
export function closeQuickNote(): void {
  set({ ...state, open: false });
}
export function useQuickNote(): State {
  return useSyncExternalStore((l) => (listeners.add(l), () => listeners.delete(l)), () => state);
}

const ART_KINDS: [string, string][] = [["file", "文件"], ["log", "记录/日志"], ["literature", "文献"], ["dataset", "数据集"], ["image", "图片"], ["conversation", "对话"]];
const SOURCES: [string, string][] = [["local", "本地实证"], ["external", "外部报告"], ["inferred", "推断"]];

function Seg<T extends string>({ options, value, onChange, label }: { options: [T, string][]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segctl"role="radiogroup" aria-label={label}>
      {options.map(([k, text]) => (
        <button key={k} type="button" role="radio" aria-checked={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>
          {text}
        </button>
      ))}
    </div>
  );
}

export function QuickNote() {
  const { open, seed, n } = useQuickNote();
  if (!open) return null;
  return <NoteForm key={n} seed={seed} />;
}

function NoteForm({ seed }: { seed: Seed }) {
  const [mode, setMode] = useState<Mode>(seed.mode ?? "judgment");
  const [jd, setJd] = useState({ kind: "conclusion", text: "", objects: (seed.objects ?? []).join(", "), cites: (seed.cites ?? []).join(", "), conditions: "", local: false, reopen: "", scope: false });
  const [art, setArt] = useState({ kind: "file", source_class: "local", title: "", path: "", text: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLTextAreaElement | HTMLInputElement | null>(null);
  useEffect(() => first.current?.focus(), [mode]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r: any = mode === "judgment"
        ? await call("judgment.write", {
            kind: jd.kind,
            text: jd.text,
            objects: splitList(jd.objects),
            cites: splitList(jd.cites),
            conditions: jd.conditions || null,
            local_observation: jd.kind === "conclusion" && jd.local,
            reopen_condition: jd.kind === "process" && jd.reopen ? jd.reopen : null,
            scope_unclear: jd.scope,
          })
        : await call("artifact.register", {
            kind: art.kind,
            source_class: art.source_class,
            storage: "managed",
            title: art.title || null,
            ...(art.path ? { path: art.path } : { text: art.text }),
          });
      closeQuickNote();
      toast(mode === "judgment" ? "已写入判断" : "已登记原件");
      go("entry", r.id);
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setBusy(false);
    }
  };
  const ready = mode === "judgment" ? jd.text.trim().length > 0 : art.path.trim().length > 0 || art.text.trim().length > 0;
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      closeQuickNote();
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && ready && !busy) {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <div className="drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && closeQuickNote()}>
      <section className="drawer note" role="dialog" aria-modal="true" aria-label="记一笔" onKeyDown={onKey}>
        <header className="drawer-head">
          <h2>记一笔</h2>
          <span className="muted small-text">写下后不能改，只能更正或撤回</span>
          <button type="button" className="icon-button" onClick={closeQuickNote} title="关闭（Esc）" aria-label="关闭">×</button>
        </header>
        <div className="drawer-body">
          <div className="segctl"role="radiogroup" aria-label="记什么">
            <button type="button" role="radio" aria-checked={mode === "judgment"} className={mode === "judgment" ? "on" : ""} onClick={() => setMode("judgment")}>
              <Stamp layer="judgment" small />写判断
            </button>
            <button type="button" role="radio" aria-checked={mode === "artifact"} className={mode === "artifact" ? "on" : ""} onClick={() => setMode("artifact")}>
              <Stamp layer="original" small />登记原件
            </button>
          </div>
          {mode === "judgment" ? (
            <>
              <Seg label="判断类型" options={Object.entries(WRITABLE_KIND) as [string, string][]} value={jd.kind} onChange={(v) => setJd({ ...jd, kind: v })} />
              <p className="muted small-text">{KIND_HINT[jd.kind]}</p>
              <label className="field">
                <span>你认为什么</span>
                <textarea autoFocus ref={(el) => { first.current = el; }} rows={5} value={jd.text} onChange={(e) => setJd({ ...jd, text: e.target.value })} placeholder="写全对象和条件，不用指代词" />
              </label>
              {jd.kind === "conclusion" && (
                <label className="check">
                  <input type="checkbox" checked={jd.local} onChange={(e) => setJd({ ...jd, local: e.target.checked })} />
                  本地实证：这是我亲自看到或测到的
                </label>
              )}
              <label className="field">
                <span>依据</span>
                <input value={jd.cites} onChange={(e) => setJd({ ...jd, cites: e.target.value })} placeholder="原件段落、事实记录或判断的 ID，逗号分隔，如 art_…#p3-2" />
              </label>
              <details>
                <summary>从库里选依据</summary>
                <EntryPicker onPick={(ref) => setJd({ ...jd, cites: [jd.cites.trim().replace(/[,，]\s*$/, ""), ref].filter(Boolean).join(", ") })} />
              </details>
              <label className="field">
                <span>对象</span>
                <input value={jd.objects} onChange={(e) => setJd({ ...jd, objects: e.target.value })} placeholder="逗号分隔，如 3号阀, P-102" />
              </label>
              <label className="field">
                <span>条件（可选）</span>
                <input value={jd.conditions} onChange={(e) => setJd({ ...jd, conditions: e.target.value })} placeholder="写明哪些使用条件清楚、哪些不清楚" />
              </label>
              <label className="check">
                <input type="checkbox" checked={jd.scope} onChange={(e) => setJd({ ...jd, scope: e.target.checked })} />
                适用范围尚不清晰（说明里显示"适用范围未明"）
              </label>
              {jd.kind === "process" && (
                <label className="field">
                  <span>重开条件（可选）</span>
                  <input value={jd.reopen} onChange={(e) => setJd({ ...jd, reopen: e.target.value })} placeholder="停下的路线在什么条件下值得重新打开" />
                </label>
              )}
            </>
          ) : (
            <>
              <Seg label="原件类型" options={ART_KINDS} value={art.kind} onChange={(v) => setArt({ ...art, kind: v })} />
              <Seg label="依据来源" options={SOURCES} value={art.source_class} onChange={(v) => setArt({ ...art, source_class: v })} />
              <label className="field">
                <span>本机文件路径</span>
                <input autoFocus ref={(el) => { first.current = el; }} value={art.path} onChange={(e) => setArt({ ...art, path: e.target.value })} placeholder="与下面的原文二选一" />
              </label>
              <label className="field">
                <span>或直接粘贴原文</span>
                <textarea rows={5} value={art.text} onChange={(e) => setArt({ ...art, text: e.target.value })} />
              </label>
              <label className="field">
                <span>标题（可选）</span>
                <input value={art.title} onChange={(e) => setArt({ ...art, title: e.target.value })} />
              </label>
              <p className="muted small-text">
                外部原件的细分、只登记路径和指纹、登记某份原件的新版本：到 <a href={href("record")} onClick={closeQuickNote}>人工记录页</a>。
              </p>
            </>
          )}
          <ErrorBox error={error} />
        </div>
        <footer className="drawer-foot">
          <span className="muted small-text grow">{mode === "judgment" ? "可信度由系统按依据推出：人写入" : "PDF、PPTX、DOCX、Excel 登记时自动抽取文字"}</span>
          <button type="button" onClick={closeQuickNote}>取消</button>
          <button type="button" className="primary" disabled={!ready || busy} onClick={() => void submit()}>
            {busy ? "…" : mode === "judgment" ? "写入" : "登记"} <kbd>Ctrl Enter</kbd>
          </button>
        </footer>
      </section>
    </div>
  );
}
