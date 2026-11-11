// 原件页（设计稿 01 §3、D-15、D-16、D-17；设计稿 02 D-01、D-05、D-06、D-08）。
// PDF、Word、PPT 默认按原样显示（渲染引擎负责），段落标记按抽取层的位置画在原样画面上；
// "对照"并排显示原页与抽取的块，"文字"显示抽取层（与检索、引用一致）。识别文本标出可信度档。
import { DigestInfo } from "../digest";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { normalizeMath } from "../mathText";
import rehypeKatex from "rehype-katex";
import { blobUrl, call, fileUrl, pageUrl } from "../api";
import { FIDELITY, FORMAT, JUDGMENT_KIND, UNIT_STATUS } from "../labels";
import { modelJobStatus } from "../modelJobs";
import { openReader } from "../reader/open";
import { delegate, go, href } from "../router";
import { Action, ErrorBox, IdLink, Tag, TeX, Time, useLoad } from "../ui";
import { JOB_STATUS, runModelJob, useModels } from "../models";
import { CopyText, DocxOriginal, PdfPageView, SegmentDetails, SnapshotSlide, mergeStats, usePdf, type BlockRef } from "./Faithful";

export { CopyText };

/* eslint-disable @typescript-eslint/no-explicit-any */

const PAGE_STEP = 20; // 一次显示的页数；更多的点"显示更多"

export type Ctx = {
  id: string;
  layer: any;
  stats: Record<string, any>;
  byBlock: Record<string, Record<number, any[]>>;
  anchor: string;
  onlyMarked: boolean;
  reload: () => void;
  // 待确认的识别与 AI 核对结果（设计稿 04 D-24）：段落锚点 → 项
  recog: Record<string, any>;
  recogAllowed?: string | null;
  terminal?: boolean;
};

export function ArtifactView({ entry, anchor, onChanged }: { entry: any; anchor: string; onChanged?: () => void }) {
  const id = entry.id;
  const [layer, lError, reloadLayer] = useLoad(() => call<any>("artifact.layer", { artifact_id: id }), [id]);
  const [segs, , reloadSegs] = useLoad(() => call<any[]>("artifact.segments", { artifact_id: id }).catch(() => []), [id]);
  const [stats, , reloadStats] = useLoad(() => call<any>("artifact.segment_stats", { artifact_id: id }), [id]);
  const [recog, , reloadRecog] = useLoad(() => call<any>("extraction.recognitions", { artifact_id: id, dispatch: true }).catch(() => null), [id]);
  const [onlyMarked, setOnlyMarked] = useState(false);
  const reload = () => {
    reloadLayer();
    reloadSegs();
    reloadStats();
    reloadRecog();
    onChanged?.();
  };
  const recogMap = useMemo(() => Object.fromEntries(((recog?.items ?? []) as any[]).map((i) => [i.anchor, i])), [recog]);
  // 段落按"单元 → 版式块"归组：显示版式块时把它的段落标记挂上去
  const byBlock = useMemo(() => {
    const out: Record<string, Record<number, any[]>> = {};
    for (const s of segs ?? []) {
      const unit = (out[s.unit] ??= {});
      (unit[s.block ?? s.ordinal] ??= []).push(s);
    }
    return out;
  }, [segs]);
  useEffect(() => {
    if (!anchor || !segs) return;
    window.setTimeout(() => document.getElementById(`seg-${anchor}`)?.scrollIntoView({ block: "center" }), 50);
  }, [anchor, segs]);
  if (lError) return <ErrorBox error={lError} />;
  if (!layer) return <p className="muted">读取原件…</p>;
  const ctx: Ctx = { id, layer, stats: stats?.segments ?? {}, byBlock, anchor: anchor.replace(/^seg:/, "seg-"),
    onlyMarked, reload, recog: recogMap, recogAllowed: recog?.ai_allowed, terminal: recog?.terminal };
  const marked = Object.keys(ctx.stats).length;
  return (
    <div className="artifact">
      <Summary entry={entry} layer={layer} stats={stats} />
      <Toolbar entry={entry} layer={layer} reload={reload} anchor={anchor} recog={recog} />
      <RecogSummary id={id} items={recog?.items ?? []} reload={reload} />
      <DigestInfo artifactId={id} />
      {marked > 0 && (
        <label className="check small-text">
          <input type="checkbox" checked={onlyMarked} onChange={(e) => setOnlyMarked(e.target.checked)} /> 只看被读过或被引用的段落（{marked} 段）
        </label>
      )}
      <Body entry={entry} ctx={ctx} segs={segs ?? []} />
    </div>
  );
}

// ---------- 工具条与概况 ----------
function Toolbar({ entry, layer, reload, anchor, recog }: { entry: any; layer: any; reload: () => void; anchor?: string; recog?: any }) {
  const id = entry.id;
  // 只数需要人确认的识别（OCR / AI 识别的文字与公式 LaTeX，设计稿 01 D-12）：与下面的"AI 复核识别"一致。
  // 解析文字层（PDF 文字页、Word、PPT）与原样复制的单元可以确认，但不需要，不算在这里
  const unverified = new Set(((recog?.items ?? []) as any[]).map((i) => i.unit)).size;
  return (
    <div className="toolbar">
      <button type="button" className="primary" onClick={() => openReader(id, anchor || undefined)} title="全屏阅读：连续滚动、缩放、查找、目录，侧栏列出被引用的段落（设计稿 03）">
        阅读
      </button>
      <a className="button" href={fileUrl(id)} target="_blank" rel="noreferrer">
        打开原件
      </a>
      <a className="button" href={fileUrl(id, true)}>
        下载
      </a>
      {entry.storage === "referenced" && <CopyText text={entry.data?.path} label="复制原路径" />}
      {layer.auto_supported && <Action label={layer.extracted ? "重新抽取" : "抽取"} run={async () => (await call("artifact.extract", { artifact_id: id, method: "auto" }), reload())} />}
      {layer.snapshot_supported && (
        <Action label={layer.snapshot ? "重新生成快照" : "生成页面快照"} run={async () => (await call("artifact.snapshot", { artifact_id: id, force: !!layer.snapshot }), reload())} />
      )}
      {layer.format === "pdf" && <LayoutEngineButton id={id} reload={reload} />}
      <AiCheckButton ids={[id]} items={recog?.items ?? []} allowed={recog?.ai_allowed} reload={reload} />
      {unverified > 0 && <span className="muted small-text">{unverified} 个单元有未确认的 OCR / AI 识别（在各单元标题或公式旁确认）</span>}
    </div>
  );
}

// AI 复核识别的结果一览（设计稿 04 D-26）：不接受的（有问题、拿不准）直接展开，接受的折叠；点锚点跳到原件里的位置
function RecogSummary({ id, items, reload }: { id: string; items: any[]; reload: () => void }) {
  const groups: [string, string, string, any[]][] = [
    ["reject", "AI 不接受（认为有问题）", "bad", items.filter((i) => i.ai?.verdict === "reject")],
    ["unsure", "AI 拿不准", "warn", items.filter((i) => i.ai?.verdict === "unsure")],
    ["confirm", "AI 接受（核对一致）", "good", items.filter((i) => i.ai?.verdict === "confirm")],
  ];
  const unchecked = items.filter((i) => !i.ai).length;
  if (!items.some((i) => i.ai)) return null;
  return (
    <section className="recog-summary small-text" aria-label="AI 复核识别结果">
      <div className="row tight">
        <strong>AI 复核识别</strong>
        {groups.map(([k, label, tone, list]) => list.length > 0 && <Tag key={k} tone={tone}>{label} {list.length}</Tag>)}
        {unchecked > 0 && <Tag tone="muted">未核对 {unchecked}</Tag>}
        <span className="muted">AI 核对不等于人已确认；引用这些段落的 AI 判断会按状态降低可信度</span>
      </div>
      {groups.map(([k, label, tone, list]) =>
        list.length === 0 ? null : (
          <details key={k} open={k !== "confirm"}>
            <summary>{label}（{list.length}）</summary>
            <ul className="plain">
              {list.map((i) => (
                <li key={i.anchor} className="recog-item">
                  <div className="row tight">
                    <a href={href("entry", `${id}#${i.anchor}`)} className="mono" title="跳到原件里的这一段">{i.anchor}</a>
                    <Tag tone={tone}>{i.part === "latex" ? "公式" : "文字"}</Tag>
                    <ConfirmBlock id={id} anchor={i.anchor} reload={reload} />
                  </div>
                  <code className="recog-full">{String(i.text)}</code>
                  {i.ai?.reason && <p className="recog-full muted">{i.ai.model ? `${i.ai.model}：` : ""}{i.ai.reason}</p>}
                  {i.ai?.suggestion && <p className="recog-full muted">建议：<code>{String(i.ai.suggestion)}</code></p>}
                </li>
              ))}
            </ul>
            {k !== "confirm" && list.length > 1 && (
              <Action className="link" label={`我看过了，确认这 ${list.length} 块`}
                run={async () => {
                  if (!window.confirm(`确认这 ${list.length} 块的识别与原件一致？这是人的确认，AI 的意见会被覆盖。`)) return;
                  await call("artifact.verify_extraction", { artifact_id: id, anchors: list.map((i) => i.anchor), note: "人工逐块核对（批量）" });
                  reload();
                }} />
            )}
          </details>
        ),
      )}
    </section>
  );
}

// 人只确认这一块（一条公式或一段文字）与原件一致；不影响同一页的其他块（设计稿 04 D-27）
function ConfirmBlock({ id, anchor, reload }: { id: string; anchor: string; reload: () => void }) {
  return (
    <Action className="link" label="我核对过，确认这一块" run={async () => (await call("artifact.verify_extraction", { artifact_id: id, anchors: [anchor], note: "人工逐块核对" }), reload())} />
  );
}

// 用本地版面引擎（MinerU）处理这份 PDF：补公式 LaTeX、记下行内公式（设计稿 05 D-06、D-07）
// 抽取方式为 MinerU 时（设计稿 05 D-15、D-16），主按钮是"用 MinerU 重新抽取"：没被引用时采用 MinerU 分段，否则只补公式
function LayoutEngineButton({ id, reload }: { id: string; reload: () => void }) {
  const models = useModels();
  const [state, setState] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const slot = models?.slots?.layout;
  if (!slot?.configured) return null;
  const segment = !!models?.segment_by_engine;
  const run = (mode?: string, fresh?: boolean) => async () => {
    if (mode === "replace" && !window.confirm("用版面引擎的分段整份替换这份原件的抽取？段落编号会变，引用它的判断可能进入待复核；人工、AI 提交过的页保留。")) return;
    setError(null);
    setNote(null);
    try {
      const r = await runModelJob("artifact.layout_engine", { artifact_id: id, ...(mode ? { mode } : {}), ...(fresh ? { fresh } : {}) }, (s) => setState(JOB_STATUS[s] ?? s));
      if (r?.note) setNote(r.note);
      else if (r?.mode === "replace") setNote(`已采用 ${r.tool ?? "版面引擎"} 的分段：${r.parsed_blocks ?? 0} 块取自文字层，${r.ocr_blocks ?? 0} 块为 OCR 识别`);
      reload();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setState("");
    }
  };
  const tier = models?.launch?.enabled ? "（需要时自动启动 MinerU）" : "";
  return (
    <span className="row tight">
      <button type="button" disabled={!!state} onClick={run()} title={segment ? `还没被引用：采用 ${slot.adapter} 的分段；已被引用：只补公式${tier}` : `用 ${slot.adapter}（${slot.url}）补公式 LaTeX 与行内公式；段落与锚点不变${tier}`}>
        {state ? `版面引擎：${state}` : segment ? "用 MinerU 重新抽取" : "用版面引擎补公式"}
      </button>
      <button type="button" className="link small-text" disabled={!!state} onClick={run(undefined, true)} title="不用缓存的结果，重新调用 MinerU（换了档位后会自动重新调用，不需要点这个）">
        重新调用
      </button>
      <button type="button" className="link small-text" disabled={!!state} onClick={run("replace")} title="整份替换为版面引擎的分段">
        整份替换
      </button>
      {note && <span className="muted small-text">{note}</span>}
      {error && <span className="error inline">{error}</span>}
    </span>
  );
}

// 识别结果交给大模型看图核对（设计稿 04 D-22、D-23）：只核对还没核对过的
export function AiCheckButton({ ids, items, allowed, reload, anchor }: { ids: string[]; items: any[]; allowed?: string | null; reload: () => void; anchor?: string }) {
  const [state, setState] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("");
  const todo = items.filter((i) => !i.ai).length;
  if (!items.length) return null;
  const submit = async (repeat: boolean) => {
    setError(null);
    setOutcome("");
    setState("提交中…");
    try {
      const { jobs, run } = await call<any>("extraction.ai_check", {
        artifact_ids: ids, repeat, dispatch: true, ...(anchor ? { anchors: [anchor] } : {}),
      });
      if (run) {
        go("agent", run.id);
        return;
      }
      if (!jobs.length) setOutcome("没有可提交的块");
      for (const job of jobs) {
        setState(modelJobStatus(job));
        for (;;) {
          await new Promise((r) => setTimeout(r, 1500));
          const st = await call<any>("models.status");
          const j = (st?.jobs ?? []).find((x: any) => x.id === job.id);
          if (!j) throw new Error("找不到这次核对任务，可再次发起");
          if (j.status === "done" || j.status === "cancelled") {
            setOutcome(modelJobStatus(j));
            if (j.progress?.last_error) setError(j.progress.last_error);
            break;
          }
          if (j.status === "failed") throw new Error(j.error ?? "核对失败");
          setState(modelJobStatus(j));
        }
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setState("");
      reload();
    }
  };
  return (
    <span className="row tight">
      {todo > 0 && <button type="button" disabled={!!state || !!allowed} onClick={() => submit(false)} title={allowed ?? "把未核对的识别交给大模型看图核对"}>
        交给 AI 复核识别（{todo}）
      </button>}
      {todo < items.length && <button type="button" disabled={!!state || !!allowed} onClick={() => submit(true)} title={allowed ?? "重新看图核对已有 AI 结果且未经人确认的识别"}>
        再次交给 AI 复核识别（{items.length - todo}）
      </button>}
      {(state || outcome) && <span role="status">{state || outcome}</span>}
      {state && <a href={href("agent")}>在 Agent 页查看输出</a>}
      {error && <span className="error inline">{error}</span>}
    </span>
  );
}

function Summary({ entry, layer, stats }: { entry: any; layer: any; stats: any }) {
  const d = entry.data ?? {};
  const units = layer.units as any[];
  const pages = units.filter((u) => u.kind === "page" || u.kind === "slide").length;
  const methods = [...new Set(units.map((u) => u.method).filter(Boolean))];
  const fidelities = [...new Set(units.map((u) => u.fidelity).filter(Boolean))] as string[];
  const verified = units.filter((u) => u.verified).length;
  const counts = layer.counts ?? {};
  return (
    <div className="artifact-summary">
      <h3>{d.title ?? "（无标题）"}</h3>
      <p className="meta">
        {FORMAT[layer.format] ?? layer.format}
        {pages ? ` · ${pages} 页` : ""} · {entry.storage === "managed" ? "受管保存" : "外部引用"} · <Time value={entry.created_at} />
        {stats?.reads ? ` · 被读过 ${stats.reads} 次` : ""}
      </p>
      <p className="meta">
        抽取：
        {!layer.extracted ? (
          <Tag tone="warn">还没有抽取</Tag>
        ) : (
          <>
            {fidelities.map((f) => (
              <FidelityTag key={f} fidelity={f} />
            ))}{" "}
            {methods.join("、")}
            {Object.keys(counts).length > 1 || !counts.text ? (
              <span className="muted">
                {fidelities.length ? " · " : ""}
                {Object.entries(counts)
                  .map(([status, n]) => `${UNIT_STATUS[status] ?? status} ${n}`)
                  .join(" · ")}
              </span>
            ) : null}
            {verified > 0 && <span className="muted"> · 已确认 {verified}</span>}
          </>
        )}
        {layer.manifest_error && <Tag tone="bad">抽取失败：{layer.manifest_error}</Tag>}
      </p>
      {layer.derived_texts?.from && (
        <p className="meta">
          派生自 <IdLink id={layer.derived_texts.from} />（旧的登记方式：抽取文本单独登记为一份原件）
        </p>
      )}
      {layer.derived_texts?.texts?.length > 0 && (
        <p className="meta">
          旧的派生文本：
          {layer.derived_texts.texts.map((t: string) => (
            <IdLink key={t} id={t} />
          ))}
          （独立登记的文本原件；这份原件现在有自己的抽取层）
        </p>
      )}
    </div>
  );
}

// ---------- 按格式显示 ----------
function Body({ entry, ctx, segs }: { entry: any; ctx: Ctx; segs: any[] }) {
  const f = ctx.layer.format;
  if (f === "text") return <TextBody entry={entry} ctx={ctx} segs={segs} />;
  if (!ctx.layer.extracted && f !== "image" && f !== "av") {
    return <p className="empty">{f === "binary" ? "这类文件没有内置抽取器，可以点“打开原件”查看。" : "还没有抽取：点上方“抽取”。"}</p>;
  }
  if (f === "pdf") return <PdfBody ctx={ctx} />;
  if (f === "pptx")
    return (
      <>
        <SnapshotNotice ctx={ctx} />
        <Pages ctx={ctx} render={(u) => <Slide ctx={ctx} unit={u} />} />
      </>
    );
  if (f === "docx") return <DocBody ctx={ctx} />;
  if (f === "xlsx") return <SheetBody ctx={ctx} />;
  if (f === "image") return <ImageBody ctx={ctx} />;
  if (f === "av") return <AvBody ctx={ctx} />;
  return <p className="empty">这类文件没有内置抽取器，可以点“打开原件”查看。</p>;
}

function Pages({ ctx, render }: { ctx: Ctx; render: (u: any) => ReactNode }) {
  const pages = ctx.layer.units.filter((u: any) => u.kind === "page" || u.kind === "slide");
  const anchorUnit = ctx.anchor.split("-")[0];
  const [shown, setShown] = useState(() => Math.max(PAGE_STEP, pages.findIndex((u: any) => u.unit === anchorUnit) + 3));
  const visible = ctx.onlyMarked ? pages.filter((u: any) => hasMarks(ctx, u.unit)) : pages.slice(0, shown);
  return (
    <div className="pages">
      {visible.map((u: any) => (
        <div key={u.unit}>{render(u)}</div>
      ))}
      {!ctx.onlyMarked && shown < pages.length && (
        <button type="button" onClick={() => setShown(shown + PAGE_STEP)}>
          显示更多（还有 {pages.length - shown} 页）
        </button>
      )}
    </div>
  );
}

function hasMarks(ctx: Ctx, unit: string): boolean {
  return Object.values(ctx.byBlock[unit] ?? {}).some((list) => list.some((s) => ctx.stats[s.anchor]));
}

// 单元的标题行：名称、状态、可信度档、是否确认，以及本单元的操作
function UnitHead({ ctx, unit, extra }: { ctx: Ctx; unit: any; extra?: ReactNode }) {
  const [history, setHistory] = useState<any[] | null>(null);
  const id = ctx.id;
  return (
    <div className="unit-head">
      <strong>{unit.label}</strong>
      {unit.status !== "text" ? <Tag tone={unit.status === "image" || unit.status === "not_extracted" ? "warn" : "muted"}>{UNIT_STATUS[unit.status] ?? unit.status}</Tag> : <FidelityTag fidelity={unit.fidelity} />}
      {unit.verified && <Tag tone="good">已确认</Tag>}
      {unit.fidelity && ["ocr", "ai"].includes(unit.fidelity) && !unit.verified && <Tag tone="warn">引用前请对照原件</Tag>}
      {(() => {
        // 版面引擎分段的页逐块定档（设计稿 05 D-17）
        const fids = (unit.blocks ?? []).filter((b: any) => b.fidelity && b.type !== "furniture").map((b: any) => b.fidelity);
        const parsed = fids.filter((f: string) => f === "parsed").length;
        return parsed > 0 && parsed < fids.length ? <span className="muted small-text">逐块定档：{parsed} 块取自文字层，{fids.length - parsed} 块为 OCR 识别</span> : null;
      })()}
      {extra}
      <span className="unit-actions">
        {unit.status === "text" && !unit.verified && !unit.virtual && (
          <Action className="link" label="确认" run={async () => (await call("artifact.verify_extraction", { artifact_id: id, units: [unit.unit] }), ctx.reload())} />
        )}
        {ctx.layer.auto_supported && (unit.kind === "page" || unit.kind === "slide") && (
          <Action className="link" label="重新抽取" run={async () => (await call("artifact.extract", { artifact_id: id, method: "auto", units: [unit.unit] }), ctx.reload())} />
        )}
        {unit.status === "text" && !unit.verified && ["ocr", "ai"].includes(unit.fidelity) &&
          ["page", "slide", "image", "media"].includes(unit.kind) && (
          <button type="button" className="link" onClick={() => delegate(extractPrompt(ctx.id, unit))}>交给 AI 重新抽取</button>
        )}
        {unit.extraction_id && (
          <button type="button" className="link" onClick={async () => setHistory(history ? null : await call("artifact.extraction_history", { artifact_id: id, unit: unit.unit }))}>
            {history ? "收起历史" : "抽取历史"}
          </button>
        )}
      </span>
      {history && (
        <ul className="history">
          {history.map((h) => (
            <li key={h.id}>
              <Time value={h.created_at} /> {h.actor_id} · {UNIT_STATUS[h.status] ?? h.status}
              {h.fidelity && <FidelityTag fidelity={h.fidelity} />} {h.method} {h.verified && <Tag tone="good">已确认</Tag>}
              {h.text && <div className="muted small-text">{h.text.slice(0, 160)}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------- PDF（设计稿 02 D-02、D-05、D-06） ----------
type View = "original" | "compare" | "text";
const VIEW_KEY = "burrowl-artifact-view";

function useView(supported: View[]): [View, (v: View) => void] {
  const [view, setView] = useState<View>(() => {
    try {
      const saved = localStorage.getItem(VIEW_KEY) as View | null;
      return saved && supported.includes(saved) ? saved : supported[0];
    } catch {
      return supported[0];
    }
  });
  const set = (v: View) => {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* 浏览器不允许本地存储时只在本页记住 */
    }
  };
  return [view, set];
}

const VIEW_LABEL: Record<View, [string, string]> = {
  original: ["原样", "按原件本来的样子显示，段落标记画在原页上；点一个段落看引用写法、读取与引用"],
  compare: ["对照", "左边原页、右边抽取出的段落，悬停任一边另一边同步高亮；用来检查抽取是否正确"],
  text: ["文字", "抽取出的文字（与检索、引用一致），方便复制和通读"],
};

function ViewSwitch({ views, view, setView }: { views: View[]; view: View; setView: (v: View) => void }) {
  return (
    <div className="row tight view-switch">
      {views.map((v) => (
        <button key={v} type="button" className={v === view ? "primary small" : "small"} title={VIEW_LABEL[v][1]} onClick={() => setView(v)}>
          {VIEW_LABEL[v][0]}
        </button>
      ))}
      <span className="muted small-text">{VIEW_LABEL[view][1]}</span>
    </div>
  );
}

function MarkLegend() {
  return (
    <p className="mark-legend small-text muted">
      <span className="swatch cited" /> 被引用 <span className="swatch read" /> 被读过 <span className="swatch low" /> 识别文本未确认
    </p>
  );
}

function PdfBody({ ctx }: { ctx: Ctx }) {
  const views: View[] = ["original", "compare", "text"];
  const [view, setView] = useView(views);
  const { doc, error } = usePdf(ctx.id);
  const [hovered, setHovered] = useState<BlockRef>(null);
  const noBoxes = ctx.layer.units.some((u: any) => u.status === "text") && !ctx.layer.units.some((u: any) => (u.blocks ?? []).some((b: any) => b.box));
  const pdfjsFailed = view !== "text" && !doc && !!error;
  return (
    <>
      <ViewSwitch views={views} view={view} setView={setView} />
      {view !== "text" && noBoxes && <div className="notice">这份 PDF 的抽取层是旧版抽取器做的，没有段落位置，原页上画不出段落标记：点上方"重新抽取"，或首页状态卡的"补抽"。</div>}
      {pdfjsFailed && <div className="notice">PDF.js 打不开这份 PDF（{error}），改为显示抽取的文字。</div>}
      {view !== "text" && !pdfjsFailed && <MarkLegend />}
      {view === "text" || pdfjsFailed ? (
        <Pages ctx={ctx} render={(u) => <PdfPage ctx={ctx} unit={u} />} />
      ) : !doc ? (
        <p className="muted">正在打开 PDF…</p>
      ) : (
        <Pages
          ctx={ctx}
          render={(u) =>
            view === "original" ? (
              <section className="unit" id={`unit-${u.unit}`}>
                <UnitHead ctx={ctx} unit={u} />
                <PdfPageView ctx={ctx} doc={doc} unit={u} />
                {(u.status === "image" || u.status === "not_extracted") && <ExtractBox ctx={ctx} unit={u} />}
              </section>
            ) : (
              <section className="unit" id={`unit-${u.unit}`}>
                <UnitHead ctx={ctx} unit={u} />
                <div className="compare">
                  <PdfPageView ctx={ctx} doc={doc} unit={u} hovered={hovered} onHover={setHovered} />
                  <div className="compare-text">
                    {u.status === "text" ? <Blocks ctx={ctx} unit={u} hovered={hovered} onHover={setHovered} /> : <ExtractBox ctx={ctx} unit={u} />}
                  </div>
                </div>
              </section>
            )
          }
        />
      )}
    </>
  );
}

function PdfPage({ ctx, unit }: { ctx: Ctx; unit: any }) {
  const [showImage, setShowImage] = useState(unit.status === "image");
  const n = unit.page;
  return (
    <section className="unit" id={`unit-${unit.unit}`}>
      <UnitHead
        ctx={ctx}
        unit={unit}
        extra={
          <>
            <a href={`${fileUrl(ctx.id)}#page=${n}`} target="_blank" rel="noreferrer" className="small-text">
              看原页 ↗
            </a>
            {unit.status === "text" && (
              <button type="button" className="link" onClick={() => setShowImage(!showImage)}>
                {showImage ? "隐藏页面图像" : "对照页面图像"}
              </button>
            )}
          </>
        }
      />
      <div className={showImage && unit.status === "text" ? "side-by-side" : ""}>
        {showImage && <img className="page-image" src={pageUrl(ctx.id, n)} alt={unit.label} loading="lazy" />}
        {unit.status === "text" && <Blocks ctx={ctx} unit={unit} />}
      </div>
      {(unit.status === "image" || unit.status === "not_extracted") && <ExtractBox ctx={ctx} unit={unit} />}
      {unit.status === "empty" && <p className="muted small-text">空白页</p>}
    </section>
  );
}

// ---------- PPTX ----------
function Slide({ ctx, unit }: { ctx: Ctx; unit: any }) {
  const snap = ctx.layer.snapshot;
  const aspect = ctx.layer.manifest?.aspect ?? 16 / 9;
  return (
    <section className="unit slide" id={`unit-${unit.unit}`}>
      <UnitHead ctx={ctx} unit={unit} extra={!snap && <Tag tone="muted">近似版式</Tag>} />
      {snap ? (
        <SnapshotSlide ctx={ctx} unit={unit} />
      ) : (
        <div className="slide-canvas" style={{ aspectRatio: String(aspect) }}>
          {(unit.blocks ?? []).map((b: any, i: number) =>
            b.box ? (
              <div key={i} className={`slide-box ${b.type}`} style={{ left: `${b.box[0] * 100}%`, top: `${b.box[1] * 100}%`, width: `${b.box[2] * 100}%`, height: `${b.box[3] * 100}%` }}>
                {b.type === "image" ? <img src={blobUrl(ctx.id, b.sha256, b.mime)} alt="" /> : <span>{blockPlain(b)}</span>}
              </div>
            ) : null,
          )}
        </div>
      )}
      <Blocks ctx={ctx} unit={unit} />
    </section>
  );
}

// 没有快照时自动生成一次（设置为 none 或没有转换器时显示原因，保留近似版式）
function useAutoSnapshot(ctx: Ctx) {
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  const [reason, setReason] = useState("");
  const tried = useRef(false);
  useEffect(() => {
    if (!ctx.layer.snapshot_supported || ctx.layer.snapshot || !ctx.layer.extracted || tried.current) return;
    tried.current = true;
    setState("busy");
    call("artifact.snapshot", { artifact_id: ctx.id })
      .then(() => {
        setState("idle");
        ctx.reload();
      })
      .catch((e) => {
        setState("failed");
        setReason(e.message);
      });
  }, [ctx]);
  return { state, reason };
}

function SnapshotNotice({ ctx }: { ctx: Ctx }) {
  const { state, reason } = useAutoSnapshot(ctx);
  if (state === "busy") return <div className="notice">正在用本机的 Office 生成页面快照（约 10 秒），完成后显示与原件一致的版式…</div>;
  if (state === "failed") return <div className="notice">没有生成页面快照：{reason}。下面按抽取的版式块近似显示。</div>;
  return null;
}

// ---------- DOCX ----------
function DocBody({ ctx }: { ctx: Ctx }) {
  const [mode, setMode] = useState<"original" | "flow" | "pages">("original");
  const [fallback, setFallback] = useState("");
  const doc = ctx.layer.units.find((u: any) => u.unit === "doc");
  const snap = ctx.layer.snapshot;
  const effective = mode === "original" && fallback ? "flow" : mode;
  return (
    <>
      <SnapshotNotice ctx={ctx} />
      <div className="row tight">
        <button
          type="button"
          className={effective === "original" ? "primary small" : "small"}
          disabled={!!fallback}
          title={fallback ? `不能按原样显示：${fallback}` : "在浏览器里按 Word 的样式排版，段落标记画在对应的段落上"}
          onClick={() => setMode("original")}
        >
          原样
        </button>
        <button type="button" className={effective === "flow" ? "primary small" : "small"} onClick={() => setMode("flow")}>
          正文
        </button>
        <button type="button" className={effective === "pages" ? "primary small" : "small"} disabled={!snap} onClick={() => setMode("pages")} title={snap ? "" : "还没有页面快照"}>
          逐页快照{snap ? `（${snap.pages} 页）` : ""}
        </button>
      </div>
      {fallback && mode === "original" && <div className="notice">不能按原样显示（{fallback}），下面按抽取的版式块近似显示。</div>}
      {effective === "original" && doc ? (
        <>
          <MarkLegend />
          <DocxOriginal ctx={ctx} unit={doc} onFallback={setFallback} />
        </>
      ) : effective === "pages" && snap ? (
        <div className="pages">
          {Array.from({ length: snap.pages }, (_, i) => (
            <img key={i} className="slide-image" src={pageUrl(ctx.id, i + 1, 1.5, "snapshot")} alt={`第 ${i + 1} 页`} loading="lazy" />
          ))}
        </div>
      ) : (
        doc && (
          <section className="unit doc-flow">
            <UnitHead ctx={ctx} unit={doc} />
            <Blocks ctx={ctx} unit={doc} />
          </section>
        )
      )}
    </>
  );
}

// ---------- Excel（设计稿 03 D-11）：每个工作表的表格块；完整的表格在阅读模式里看 ----------
function SheetBody({ ctx }: { ctx: Ctx }) {
  return (
    <>
      <div className="notice">
        这里按抽取出的表格区域显示（每块标出单元格范围，引用写块的锚点）。完整的表格（列宽、合并单元格、所有工作表）请点上方"阅读"。
      </div>
      {ctx.layer.units.map((u: any) => (
        <section key={u.unit} className="unit" id={`unit-${u.unit}`}>
          <UnitHead ctx={ctx} unit={u} extra={u.meta?.truncated_at_row ? <Tag tone="warn">只抽取了前 {u.meta.truncated_at_row} 行</Tag> : null} />
          {u.status === "text" ? <Blocks ctx={ctx} unit={u} /> : <p className="muted small-text">空表</p>}
        </section>
      ))}
    </>
  );
}

// ---------- 图片、音视频 ----------
function ImageBody({ ctx }: { ctx: Ctx }) {
  const unit = ctx.layer.units.find((u: any) => u.unit === "img") ?? { unit: "img", label: "图片", status: "not_extracted", kind: "image" };
  return (
    <section className="unit">
      <img className="original-image" src={fileUrl(ctx.id)} alt="原件" />
      <UnitHead ctx={ctx} unit={unit} />
      {unit.status === "text" ? <Blocks ctx={ctx} unit={unit} /> : <ExtractBox ctx={ctx} unit={unit} />}
    </section>
  );
}

function AvBody({ ctx }: { ctx: Ctx }) {
  const ref = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  const unit = ctx.layer.units.find((u: any) => u.unit === "av") ?? { unit: "av", label: "音视频", status: "not_extracted", kind: "media" };
  const audio = String(ctx.layer.media_type).startsWith("audio/");
  const seek = (t: number) => {
    if (!ref.current) return;
    ref.current.currentTime = t;
    void ref.current.play();
  };
  return (
    <section className="unit">
      {audio ? <audio ref={ref} controls src={fileUrl(ctx.id)} className="original-audio" /> : <video ref={ref} controls src={fileUrl(ctx.id)} className="original-media" />}
      <UnitHead ctx={ctx} unit={unit} />
      {unit.status === "text" ? <Blocks ctx={ctx} unit={unit} onSeek={seek} /> : <ExtractBox ctx={ctx} unit={unit} />}
    </section>
  );
}

// ---------- 文本原件 ----------
function TextBody({ entry, ctx, segs }: { entry: any; ctx: Ctx; segs: any[] }) {
  const suffix = entry.data?.suffix ?? (entry.data?.media_type === "text/markdown" ? ".md" : "");
  const unit = ctx.layer.units[0];
  if (unit?.status === "unreadable") return <ErrorBox error={unit.error} />;
  if (suffix === ".csv" || suffix === ".tsv") return <CsvTable text={unit?.text ?? ""} sep={suffix === ".tsv" ? "\t" : ","} />;
  if (suffix === ".json") return <pre className="code">{prettyJson(unit?.text ?? "")}</pre>;
  const markdown = suffix === ".md" || suffix === ".markdown" || !suffix;
  const shown = ctx.onlyMarked ? segs.filter((s) => ctx.stats[s.anchor]) : segs;
  return (
    <div className={markdown ? "doc-flow" : ""}>
      {shown.map((s) => (
        <Segment key={s.anchor} ctx={ctx} seg={s}>
          {markdown ? <Md text={s.text} /> : <pre className="code">{s.text}</pre>}
        </Segment>
      ))}
    </div>
  );
}

function Md({ text }: { text: string }) {
  return (
    <div className="md">
      <Markdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
        {normalizeMath(text)}
      </Markdown>
    </div>
  );
}

function prettyJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function CsvTable({ text, sep }: { text: string; sep: string }) {
  const rows = text
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map((l) => splitCsv(l, sep));
  return (
    <div className="table-wrap">
      <table className="data-table">
        <tbody>
          {rows.slice(0, 500).map((r, i) => (
            <tr key={i}>{r.map((c, j) => (i === 0 ? <th key={j}>{c}</th> : <td key={j}>{c}</td>))}</tr>
          ))}
        </tbody>
      </table>
      {rows.length > 500 && <p className="muted">只显示前 500 行，共 {rows.length} 行；完整内容请打开原件。</p>}
    </div>
  );
}

function splitCsv(line: string, sep: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"' && line[i + 1] === '"' && quoted) {
      cur += '"';
      i++;
    } else if (ch === '"') quoted = !quoted;
    else if (ch === sep && !quoted) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

// ---------- 按版面摆放（设计稿 05 D-13）：每页一张与原件同比例的纸，各块按 box 绝对定位，文字按块的大小缩放 ----------
function LayoutPage({ ctx, unit, hovered, onHover }: { ctx: Ctx; unit: any; hovered?: BlockRef; onHover?: (b: BlockRef) => void }) {
  const [pw, ph] = (unit.meta?.size as number[] | undefined) ?? [612, 792];
  const ratio = unit.meta?.aspect ?? pw / ph;
  const blocks: any[] = unit.blocks ?? [];
  const segsOf = ctx.byBlock[unit.unit] ?? {};
  return (
    <div className="layout-page" style={{ aspectRatio: String(ratio) }}>
      {blocks.map((b, i) => {
        if (!b.box || (b.latex_group && !b.latex)) return null;
        const box: number[] = b.type === "formula" && b.latex_box ? b.latex_box : b.box;
        const [x, y, w, h] = box;
        const marked = (segsOf[i] ?? []).some((s: any) => ctx.stats[s.anchor]);
        const on = hovered?.unit === unit.unit && hovered?.block === i;
        // 字号：按块的面积和字数估计（单位是页面宽度的百分比，cqw），不超过正文常见字号
        const text = String(b.text ?? "");
        const areaCqw = w * 100 * (h * 100 / ratio);
        const heightCqw = (h * 100) / ratio;
        const font =
          b.type === "formula" && b.latex
            ? Math.max(0.5, Math.min(1.6, heightCqw / 2.6 / (b.latex_parts?.length ?? 1))) // 行间公式约 2.6 倍字高
            : Math.max(0.6, Math.min(1.9, Math.sqrt(areaCqw / Math.max(text.length, 1) / 0.62)));
        return (
          <FitBox
            key={i}
            font={Math.min(font, heightCqw / 1.15)}
            className={`lp-block lp-${b.type}${marked ? " marked" : ""}${on ? " on" : ""}`}
            style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }}
            title={(segsOf[i] ?? []).map((s: any) => s.anchor).join(" ")}
            onMouseEnter={onHover ? () => onHover({ unit: unit.unit, block: i }) : undefined}
            onMouseLeave={onHover ? () => onHover(null) : undefined}
          >
            <LayoutBlock ctx={ctx} unit={unit} block={b} box={box} />
          </FitBox>
        );
      })}
    </div>
  );
}

// 放不下就缩小字号：渲染后比较内容与框的大小，每次缩小 10%，最多 10 次；页面宽度变化时重新计算
function FitBox({ font, children, ...rest }: { font: number; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      let size = font;
      el.style.fontSize = `${size}cqw`;
      for (let n = 0; n < 10 && (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1); n++) {
        size *= 0.9;
        el.style.fontSize = `${size}cqw`;
      }
    };
    fit();
    const ro = new ResizeObserver(fit);
    if (el.parentElement) ro.observe(el.parentElement);
    const t = window.setTimeout(fit, 300); // KaTeX 字体加载后再算一次
    return () => {
      ro.disconnect();
      window.clearTimeout(t);
    };
  }, [font]);
  return (
    <div ref={ref} {...rest}>
      {children}
    </div>
  );
}

function LayoutBlock({ ctx, unit, block: b, box }: { ctx: Ctx; unit: any; block: any; box: number[] }) {
  if (b.type === "formula") {
    return b.latex ? (
      <div className="lp-tex">{(b.latex_parts ?? [b.latex]).map((t: string, i: number) => <TeX key={i} tex={t} />)}</div>
    ) : (
      <img src={pageUrl(ctx.id, unit.page, 3, clipSource(ctx), box)} alt={b.text} loading="lazy" />
    );
  }
  if (b.type === "table") {
    return (
      <table className="lp-table">
        <tbody>
          {(b.rows ?? []).map((r: string[], i: number) => (
            <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (b.type === "image") return <img src={blobUrl(ctx.id, b.sha256, b.mime)} alt={b.alt ?? ""} loading="lazy" />;
  const runs: any[] | undefined = b.inline_math?.runs;
  return <>{runs ? runs.map((r, i) => (r.t === "math" ? <TeX key={i} tex={r.v} display={false} /> : <span key={i}>{r.v}</span>)) : b.text}</>;
}

// ---------- 版式块（D-16）与段落 ----------
function Blocks({ ctx, unit, onSeek, hovered, onHover }: { ctx: Ctx; unit: any; onSeek?: (t: number) => void; hovered?: BlockRef; onHover?: (b: BlockRef) => void }) {
  const segsOf = ctx.byBlock[unit.unit] ?? {};
  const blocks: any[] = unit.blocks ?? [];
  return (
    <div className="blocks">
      {blocks.map((b, i) => {
        if (b.type === "furniture" && !onHover) return null; // 页眉页脚：不分段；对照视图里淡色显示
        const segs = segsOf[i] ?? [];
        if (ctx.onlyMarked && !segs.some((s) => ctx.stats[s.anchor])) return null;
        const body = <BlockView ctx={ctx} unit={unit} block={b} index={i} onSeek={onSeek} />;
        const sync = onHover
          ? {
              className: hovered?.unit === unit.unit && hovered?.block === i ? "hover-sync on" : "hover-sync",
              onMouseEnter: () => onHover({ unit: unit.unit, block: i }),
              onMouseLeave: () => onHover(null),
            }
          : {};
        if (!segs.length)
          return (
            <div key={i} {...sync}>
              {body}
            </div>
          );
        return (
          <div key={i} {...sync}>
            <Segment ctx={ctx} seg={segs[0]} more={segs.slice(1)}>
              {body}
            </Segment>
          </div>
        );
      })}
    </div>
  );
}

function BlockView({ ctx, unit, block: b, index, onSeek }: { ctx: Ctx; unit: any; block: any; index: number; onSeek?: (t: number) => void }) {
  switch (b.type) {
    case "formula":
      return <FormulaView ctx={ctx} unit={unit} block={b} index={index} />;
    case "heading": {
      const Tag = `h${Math.min(6, (b.level ?? 1) + 2)}` as "h3";
      return <Tag className="blk-heading">{b.text}</Tag>;
    }
    case "title":
      return <h4 className="blk-heading">{paras(b)}</h4>;
    case "text":
      return (
        <ul className="blk-text">
          {(b.paragraphs ?? []).map((p: any, i: number) => (
            <li key={i} style={{ marginLeft: `${(p.level ?? 0) * 1.2}em` }}>
              {p.inline_math ? <InlineRuns block={p} /> : p.text}
            </li>
          ))}
        </ul>
      );
    case "list":
      return (
        <div className="blk-list" style={{ marginLeft: `${(b.level ?? 0) * 1.2 + 0.4}em` }}>
          {b.ordered ? "1." : "•"} {b.text}
        </div>
      );
    case "table":
      return (
        <div className="table-wrap">
          {b.range && <div className="muted small-text mono">{b.range}</div>}
          <table className="data-table">
            <tbody>
              {(b.rows ?? []).map((r: string[], i: number) => (
                <tr key={i}>{r.map((c, j) => (i === 0 ? <th key={j}>{c}</th> : <td key={j}>{c}</td>))}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "image": {
      const sub = ctx.layer.units.find((u: any) => u.unit === b.unit);
      return (
        <figure className="blk-image">
          <img src={blobUrl(ctx.id, b.sha256, b.mime)} alt={b.alt ?? ""} loading="lazy" />
          {sub && (
            <figcaption>
              <UnitHead ctx={ctx} unit={sub} />
              {sub.status === "text" ? <div className="muted">{sub.text}</div> : <ExtractBox ctx={ctx} unit={sub} compact />}
            </figcaption>
          )}
        </figure>
      );
    }
    case "media":
      return <div className="notice">嵌入的音视频：{b.alt || b.note}（请打开原件播放）</div>;
    case "notes":
      return <div className="blk-notes">备注：{b.text}</div>;
    case "cue":
      return (
        <div className="blk-cue">
          <button type="button" className="link mono" onClick={() => onSeek?.(b.t)}>
            {clock(b.t)}
          </button>{" "}
          {b.text}
        </div>
      );
    case "chart":
      return <div className="muted">{b.text}</div>;
    case "furniture":
      return <div className="blk-furniture">{b.text}</div>;
    default:
      return (b.math || b.inline_math) && b.box && unit?.page ? (
        <MathParagraph ctx={ctx} unit={unit} block={b} />
      ) : (
        <p className={`blk-para${b.bold ? " bold" : ""}${b.italic ? " italic" : ""}`}>{b.inline_math ? <InlineRuns block={b} /> : b.text}</p>
      );
  }
}

// Office 公式（设计稿 03 D-20）：LaTeX 由原件的公式结构直接转写，与识别结果不同，不需要人确认
const OMML = "omml";
function latexMethod(method?: string): string | undefined {
  return method === OMML ? "Office 公式（原件结构）" : method;
}

// 没有页面位置的段落（Word、PPT）夹着行内公式：按文字与公式的序列显示，可切回抽取文字
function InlineRuns({ block: b }: { block: any }) {
  const [raw, setRaw] = useState(false);
  const runs: any[] = b.inline_math?.runs ?? [];
  const exact = b.inline_math?.source === OMML;
  return (
    <>
      {raw ? b.text : runs.map((r, i) => (r.t === "math" ? <TeX key={i} tex={r.v} display={false} /> : <span key={i}>{r.v}</span>))}{" "}
      <button type="button" className="link small-text" onClick={() => setRaw(!raw)}
        title={exact ? "行内公式由原件的 Office 公式结构转写；检索与引用用的是抽取文字" : `行内公式来自 ${b.inline_math?.source}，未经人确认；检索与引用用的是抽取文字`}>
        {raw ? "看公式" : "看抽取文字"}
      </button>
    </>
  );
}

// ---------- 公式（设计稿 03 D-16）：先显示原件上这一块的裁切图，抽取出的原始字符折叠在下面 ----------
function clipSource(ctx: Ctx): string {
  return ctx.layer.format === "pdf" ? "original" : "snapshot";
}

// 有 LaTeX（设计稿 03 D-17）时用 KaTeX 显示，标出来源与是否确认，可以切回原件截图对照
function FormulaView({ ctx, unit, block: b, index }: { ctx: Ctx; unit: any; block: any; index: number }) {
  const [failed, setFailed] = useState(false);
  const [showClip, setShowClip] = useState(false);
  const [editing, setEditing] = useState(false);
  const [tex, setTex] = useState(b.latex ?? "");
  const [busy, setBusy] = useState("");
  const models = useModels();
  const canClip = b.box && unit?.page && (ctx.layer.format === "pdf" || ctx.layer.snapshot);
  const anchor: string | undefined = ctx.byBlock[unit?.unit]?.[index]?.[0]?.anchor;
  const src = b.latex_source;
  // 一条公式被内置抽取切成几块时，版面引擎把它们并成一组：第一块带整条 LaTeX，其余几块并入它（设计稿 05 D-06）
  if (b.latex_group && !b.latex) {
    return (
      <div className="blk-formula merged small-text muted" title={b.text}>
        ↑ 并入上面的公式 <code>{b.text.slice(0, 40)}</code>
      </div>
    );
  }
  const box = b.latex_box ?? b.box;
  const clip = canClip && !failed ? <img src={pageUrl(ctx.id, unit.page, 3, clipSource(ctx), box)} alt={b.text} loading="lazy" onError={() => setFailed(true)} /> : <code>{b.text}</code>;
  const recognize = (engine: "model" | "llm") => async () => {
    setBusy(engine === "llm" ? "大模型识别中…" : "识别中…");
    try {
      const result = await runModelJob("artifact.recognize_formula", {
        artifact_id: ctx.id, anchors: [anchor], engine, ...(engine === "llm" && { dispatch: true }),
      }, (s) => setBusy(`${JOB_STATUS[s] ?? s}…`));
      if (result?.run) go("agent", result.run.id);
      ctx.reload();
    } catch (e: any) {
      window.alert(e.message);
    } finally {
      setBusy("");
    }
  };
  const prompt = anchor
    ? `请识别原件 ${ctx.id} 的公式 ${anchor}：先用 artifact_view(artifact_id="${ctx.id}", anchor="${anchor}") 看公式的裁切图，然后用 artifact_extract 提交（method=ai，model 写你的模型名，blocks=[{anchor: "${anchor}", latex: …}]）。只写看到的公式，不加 $，编号写成 \\tag{n}。`
    : "";
  return (
    <div className="blk-formula">
      {b.latex && !showClip ? (b.latex_parts ?? [b.latex]).map((t: string, i: number) => <TeX key={i} tex={t} />) : clip}
      <div className="row tight small-text muted formula-meta">
        {b.latex ? (
          <>
            <FidelityTag fidelity={src?.fidelity} />
            {unit.verified ? <Tag tone="good">已确认</Tag> : ["ai", "ocr"].includes(src?.fidelity) && <Tag tone="warn">未确认</Tag>}
            <span>{latexMethod(src?.method)}</span>
            <button type="button" className="link" onClick={() => setShowClip(!showClip)}>
              {showClip ? "看 LaTeX" : canClip ? "对照原件" : "看抽取文字"}
            </button>
          </>
        ) : null}
        {anchor && (
          <>
            {busy && <span>{busy}</span>}
            {/* Office 公式的 LaTeX 来自原件结构，不需要再识别；Word 也没有可裁切的页面位置 */}
            {!busy && src?.method !== OMML && models?.slots?.formula?.configured && (
              <button type="button" className="link" onClick={recognize("model")} title="用本地公式模型识别（设置 → 模型与引擎）">
                识别
              </button>
            )}
            {src?.method !== OMML && (
              <button type="button" className="link" disabled={!!busy}
                onClick={ctx.terminal !== false || models?.slots?.llm?.configured ? recognize("llm") : () => delegate(prompt)}>
                {b.latex ? "再次交给 AI 识别" : "交给 AI 识别"}
              </button>
            )}
            <button type="button" className="link" onClick={() => setEditing(!editing)}>
              {editing ? "取消" : b.latex ? "改 LaTeX" : "填写 LaTeX"}
            </button>
          </>
        )}
      </div>
      {editing && anchor && (
        <div className="forms single formula-edit">
          <textarea value={tex} onChange={(e) => setTex(e.target.value)} placeholder="LaTeX，不加 $，如 m_t \leftarrow \beta_1 m_{t-1} + (1-\beta_1) g_t" />
          {tex.trim() && <TeX tex={tex} />}
          <Action
            label="保存（人工填写）"
            disabled={!tex.trim()}
            run={async () => {
              await call("artifact.extract", { artifact_id: ctx.id, method: "manual", blocks: [{ anchor, latex: tex }] });
              setEditing(false);
              ctx.reload();
            }}
          />
        </div>
      )}
      {(!b.latex || showClip) && canClip && !failed && (
        <details className="small-text muted">
          <summary>抽取出的字符</summary>
          <code>{b.text}</code>
        </details>
      )}
    </div>
  );
}

// 夹着行内公式的段落：版面引擎给出行内公式时按它的文字与公式显示（KaTeX），抽取文字仍是检索与引用的依据（设计稿 05 D-12）
function MathParagraph({ ctx, unit, block: b }: { ctx: Ctx; unit: any; block: any }) {
  const [show, setShow] = useState(false);
  const [raw, setRaw] = useState(false);
  const runs: any[] | undefined = b.inline_math?.runs;
  return (
    <div className="blk-math">
      <p className={`blk-para${b.bold ? " bold" : ""}`}>
        {runs && !raw ? runs.map((r, i) => (r.t === "math" ? <TeX key={i} tex={r.v} display={false} /> : <span key={i}>{r.v}</span>)) : b.text}{" "}
        {runs && (
          <button type="button" className="link small-text" onClick={() => setRaw(!raw)} title={`行内公式来自 ${b.inline_math.source}，未经人确认；检索与引用用的是抽取文字`}>
            {raw ? "看公式" : "看抽取文字"}
          </button>
        )}{" "}
        <button type="button" className="link small-text" onClick={() => setShow(!show)} title="这段夹着行内公式，抽取出的字符可能不准">
          {show ? "收起原件" : "看原件这段"}
        </button>
      </p>
      {show && <img className="math-clip" src={pageUrl(ctx.id, unit.page, 2.5, clipSource(ctx), b.box)} alt={b.text} />}
    </div>
  );
}

// 阅读模式的对照、文字视图用：一个单元的标题行（状态、确认、重新抽取）与它的块（设计稿 03 D-06）。
// layout=true 时按块在页面上的位置摆放（设计稿 05 D-13）；没有位置的单元仍按阅读顺序
export function UnitSection({ ctx, unit, hovered, onHover, layout }: { ctx: Ctx; unit: any; hovered?: BlockRef; onHover?: (b: BlockRef) => void; layout?: boolean }) {
  const placed = layout && unit.status === "text" && unit.page && (unit.blocks ?? []).some((b: any) => b.box);
  return (
    <section className="unit" id={`rd-unit-${unit.unit}`} data-unit={unit.unit}>
      <UnitHead ctx={ctx} unit={unit} />
      {placed ? <LayoutPage ctx={ctx} unit={unit} hovered={hovered} onHover={onHover} /> : unit.status === "text" ? <Blocks ctx={ctx} unit={unit} hovered={hovered} onHover={onHover} /> : unit.status === "empty" ? <p className="muted small-text">空白页</p> : <ExtractBox ctx={ctx} unit={unit} />}
    </section>
  );
}

function paras(b: any): string {
  return (b.paragraphs ?? []).map((p: any) => p.text).join(" ");
}

function blockPlain(b: any): string {
  if (b.type === "table") return (b.rows ?? []).map((r: string[]) => r.join(" | ")).join("\n");
  if (b.paragraphs) return b.paragraphs.map((p: any) => p.text).join("\n");
  return b.text ?? "";
}

function clock(t: number): string {
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

// 一段：正文 + 右侧的读取与引用标记；点开列出读取日志和引用它的判断（按结论 / 过程 / 规定分组）
function Segment({ ctx, seg, more = [], children }: { ctx: Ctx; seg: any; more?: any[]; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const all = [seg, ...more];
  const stat = mergeStats(all.map((s) => ctx.stats[s.anchor]).filter(Boolean));
  const highlighted = all.some((s) => s.anchor === ctx.anchor);
  const cites = Object.values(stat.citations).reduce((n: number, list: any) => n + list.length, 0);
  return (
    <div id={`seg-${seg.anchor}`} className={`seg${highlighted ? " hl" : ""}${stat.reads.length ? " read" : ""}${cites ? " cited" : ""}`}>
      {more.map((s) => (
        <span key={s.anchor} id={`seg-${s.anchor}`} />
      ))}
      <div className="seg-body">{children}</div>
      <div className="seg-meta">
        <button type="button" className="link" onClick={() => setOpen(!open)} title={`引用写 ${ctx.id}#${seg.anchor}`}>
          <span className="mono">{seg.anchor}</span>
          {stat.reads.length > 0 && <span> · 读 {stat.reads.length}</span>}
          {Object.entries(stat.citations).map(([k, list]: [string, any]) => (
            <span key={k}>
              {" "}
              · {JUDGMENT_KIND[k] ?? k} {list.length}
            </span>
          ))}
        </button>
        <RecogFlag ctx={ctx} item={all.map((s) => ctx.recog[s.anchor]).find(Boolean)} />
        {open && (
          <div className="seg-pop">
            <SegmentDetails ctx={ctx} segs={all} />
          </div>
        )}
      </div>
    </div>
  );
}

const AI_VERDICT_LABEL: Record<string, string> = { confirm: "AI 已核对", reject: "AI 认为有问题", unsure: "AI 拿不准" };

// 段落旁的识别标记：未确认的识别、AI 核对结论；AI 给出改正的公式时可以一键采用（按 AI 识别档提交，仍需确认）
function RecogFlag({ ctx, item }: { ctx: Ctx; item?: any }) {
  const [open, setOpen] = useState(false);
  if (!item) return null;
  const ai = item.ai;
  const label = ai ? AI_VERDICT_LABEL[ai.verdict] ?? ai.verdict : item.part === "latex" ? "公式未确认" : "识别未确认";
  const tone = !ai ? "muted" : ai.verdict === "confirm" ? "good" : ai.verdict === "reject" ? "bad" : "warn";
  return (
    <span className="recog-flag">
      <button type="button" className="link small-text" onClick={() => setOpen(!open)} title={ai?.reason ?? "OCR / AI 识别的内容，还没有人确认"}>
        <Tag tone={tone}>{label}</Tag>
      </button>
      {open && (
        <span className="seg-pop small-text">
          {ai?.model && <span className="muted">{ai.model}：</span>}
          <span className="recog-full">{ai?.reason}</span>
          {ai?.suggestion && (
            <>
              <br />
              建议：<code>{ai.suggestion}</code>{" "}
              {item.part === "latex" && (
                <Action className="link" label="采用建议" run={async () => (await call("artifact.extract", { artifact_id: ctx.id, method: "ai", model: ai.model || "llm", blocks: [{ anchor: item.anchor, latex: ai.suggestion }], note: "采用 AI 核对给出的改正" }), ctx.reload())} />
              )}
            </>
          )}
          <ConfirmBlock id={ctx.id} anchor={item.anchor} reload={ctx.reload} />
          <AiCheckButton ids={[ctx.id]} items={[item]} allowed={ctx.recogAllowed} anchor={item.anchor} reload={ctx.reload} />
        </span>
      )}
    </span>
  );
}

// ---------- 抽取：交给 AI，或人工转写 ----------
function extractPrompt(id: string, unit: any): string {
  return unit.kind === "media"
    ? `请为原件 ${id} 的音视频提交转写：用你能用的转写工具得到带时间戳的文字，然后用 artifact_extract 提交（method=ai，model 写使用的模型，content=[{unit: "av", text: "[00:00:05] …"}]）。只转写听到的内容，不要总结。`
    : `请识别原件 ${id} 的${unit.label}（单元 ${unit.unit}）：先用 artifact_view(artifact_id="${id}", unit="${unit.unit}") 看图像，然后用 artifact_extract 提交（method=ai，model 写你的模型名，content=[{unit: "${unit.unit}", text: …}]）。只转写看到的文字和数字，表格按行写，不要总结或补充。`;
}

function ExtractBox({ ctx, unit, compact }: { ctx: Ctx; unit: any; compact?: boolean }) {
  const [manual, setManual] = useState(false);
  const [text, setText] = useState("");
  const media = unit.kind === "media";
  return (
    <div className={`extract-box${compact ? " compact" : ""}`}>
      {!compact && <span className="muted small-text">{media ? "音视频默认不转写。" : "图片默认不抽取。"}</span>}
      <button type="button" className="small" onClick={() => delegate(extractPrompt(ctx.id, unit))}>
        交给 AI 抽取
      </button>
      <button type="button" className="small" onClick={() => setManual(!manual)}>
        {manual ? "取消" : "手动转写"}
      </button>
      {manual && (
        <div className="forms single">
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={media ? "[00:00:05] 一行一段，带时间戳" : "按原样转写；空行分段"} />
          <Action
            label="提交转写"
            disabled={!text.trim()}
            run={async () => {
              await call("artifact.extract", { artifact_id: ctx.id, method: "manual", content: [{ unit: unit.unit, text }] });
              setManual(false);
              setText("");
              ctx.reload();
            }}
          />
        </div>
      )}
    </div>
  );
}

// ---------- 小部件 ----------
export function FidelityTag({ fidelity }: { fidelity: string | null | undefined }) {
  if (!fidelity) return null;
  const tone = fidelity === "copy" || fidelity === "parsed" ? "good" : fidelity === "manual" ? "accent" : "warn";
  return <Tag tone={tone}>{FIDELITY[fidelity] ?? fidelity}</Tag>;
}

export function AnchorLink({ id, anchor, children }: { id: string; anchor?: string; children?: ReactNode }) {
  return <IdLink id={anchor ? `${id}#${anchor}` : id}>{children}</IdLink>;
}
