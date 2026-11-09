// 设置（每个数据目录各自的 config.json）：抽取方式、页面快照的转换器、检索索引方式（设计稿 01 D-11、D-17、D-18）；
// 阅读：每种格式的默认阅读器（数据目录设置）与个人偏好（只存在本浏览器，设计稿 03 D-14）。
import { useState } from "react";
import { call } from "../api";
import { usePrefs } from "../reader/prefs";
import { VIEWERS } from "../reader/registry";
import { ErrorBox, Panel, Tag, useLoad } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Item = { key: string; label: string; hint: string; options: Record<string, string> };

const EXTRACTION: Item[] = [
  {
    key: "extraction.pdf",
    label: "PDF",
    hint: "内置：用 pypdfium2 抽取每页的文字层，没有文字层的页（扫描件）标为图片页。MinerU：登记时先内置抽取，MinerU 处理完后，还没被引用的原件改用 MinerU 的分段（公式整条、带 LaTeX），能和文字层对上的段落仍算“解析文字层”；已被引用的只补公式。需要先在“模型与引擎”里配置 MinerU",
    options: { auto: "内置抽取（登记时自动）", mineru: "MinerU 分段（没被引用的原件）", off: "不自动抽取（在原件页手动抽取）" },
  },
  { key: "extraction.pptx", label: "PPT（.pptx）", hint: "抽取每页的标题、正文、表格、备注，保留各块在页面上的位置", options: { auto: "登记时自动抽取", off: "不自动抽取" } },
  { key: "extraction.xlsx", label: "Excel（.xlsx）", hint: "每个工作表一个单元，按空行分开的表格区域成块（大区域每 50 行一块），块记下单元格范围；公式取文件里保存的计算结果", options: { auto: "登记时自动抽取", off: "不自动抽取" } },
  { key: "extraction.docx", label: "Word（.docx）", hint: "按文档顺序抽取标题、段落、列表、表格，嵌入图片在原位置显示", options: { auto: "登记时自动抽取", off: "不自动抽取" } },
  { key: "extraction.image", label: "图片、图片页", hint: "识别图片需要视觉模型，消耗较大；在原件页“交给 AI 抽取”或手动转写。识别结果标为 AI 识别，引用前提示对照原件", options: { on_demand: "按需（手动指定或 AI 明确调用时）" } },
  { key: "extraction.av", label: "音视频", hint: "转写需要语音模型；由 AI 用外部工具转写后提交带时间戳的文本，或人工转写", options: { on_demand: "按需（手动指定或 AI 明确调用时）" } },
];

const SNAPSHOT: Item = {
  key: "extraction.snapshot",
  label: "页面快照",
  hint: "PPT 和 Word 在工作台按原样显示时，需要用排版程序转成 PDF；快照只用于显示，不进索引、不作引用",
  options: { auto: "自动（Office 优先，其次 LibreOffice）", office: "只用 Microsoft Office", libreoffice: "只用 LibreOffice", none: "不生成（按抽取的版式块近似显示）" },
};

// AI 复核（设计稿 04 D-15）：AI 复核的结果记为"AI 已复核"，不等于人已复核
const REVIEW_AI: Item = {
  key: "review.ai",
  label: "AI 复核",
  hint: "AI 只能对照原件层、判断层核对条目，结果另记一档；确认后从待决策列表移出（请人复核的项不移出），认为有问题时排到前面。不是“不接受”时，OCR / AI 识别的文字与公式也可以交给大模型看图核对（结果为“AI 已核对”，不等于人已确认）。人已复核、会写回判断层的边、原件确认抽取，始终只能由人处理",
  options: { off: "不接受 AI 复核", framework: "只接受框架页与关联边", all: "框架页、关联边，以及依据已变化的判断" },
};

// 本地模型与大模型（设计稿 05）。本地模型（地址是本机）可以在登记、补抽后自动运行；大模型只在你点击时调用
const MODEL_ITEMS: Item[] = [
  { key: "models.layout", label: "版面抽取", hint: "版面分析模型：给 PDF 的公式块补 LaTeX、给段落记下行内公式。需要你自己运行服务，见下方说明", options: { none: "不用", mineru: "MinerU（mineru-api）" } },
  { key: "models.layout_mode", label: "版面引擎的结果", hint: "补公式不改段落与锚点（推荐）；整份替换会让段落编号变化，引用它的判断可能进入待复核", options: { formulas: "补公式（也插入内置抽取漏掉的公式）", formulas_only_existing: "只补已有公式块（段落编号完全不变）", replace: "整份替换为版面引擎的分段" } },
  { key: "models.layout_auto", label: "自动运行", hint: "登记、补抽 PDF 后自动排进队列；只有地址是本机（localhost、127.0.0.1）时才会自动运行", options: { on: "自动", off: "只在原件页手动运行" } },
  { key: "models.layout_tier", label: "MinerU 档位", hint: "basic 只用 CPU，公式用小模型识别；standard 另加 12 亿参数的视觉模型（CPU 12 线程以上或有显卡，第一次要多下载模型）；advanced 要显卡。换档位后在原件页重新抽取就会重新调用", options: { auto: "自动", flash: "flash（只抽文字层）", basic: "basic（CPU 可用）", standard: "standard", advanced: "advanced" } },
  { key: "models.formula", label: "公式识别", hint: "公式块旁的“识别”按钮用哪个模型", options: { none: "不用", follow_layout: "跟随版面引擎（MinerU 识别公式截图）" } },
  { key: "models.llm", label: "大模型", hint: "可选。只在你点击“用大模型识别”或“交给 AI 复核”识别结果时调用，登记、补抽、定时任务都不会调用", options: { none: "不用", openai: "OpenAI 兼容接口" } },
];

// 按需启动 MinerU（设计稿 05 D-19 至 D-21）
const LAUNCH: Item = {
  key: "models.layout_launch",
  label: "启动 MinerU",
  hint: "自动：需要时（登记、重新抽取、测试连接）用下面的命令在新的命令行窗口里启动 MinerU，空闲 10 分钟后关闭；测试连接时启动的，测完就关。只在地址是本机时启动",
  options: { manual: "我自己运行", auto: "需要时自动启动、用完关闭" },
};

const VIEWER_FORMATS: [string, string][] = [
  ["pdf", "PDF"],
  ["docx", "Word（.docx）"],
  ["pptx", "PPT（.pptx）"],
  ["xlsx", "Excel（.xlsx）"],
  ["text", "文本 / Markdown"],
  ["image", "图片"],
  ["av", "音视频"],
];
const VIEWER_HINT: Record<string, string> = {
  "docx-preview": "在浏览器里排版，连续展开，段落标记画在对应段落上",
  "pdfjs-snapshot": "用 Office / LibreOffice 生成的页面快照，逐页与原件一致；Word 快照上不画段落标记",
  pdfjs: "连续滚动、缩放、双页、目录、查找",
  sheet: "工作表标签、列宽、合并单元格，被引用的区域加底色",
  onlyoffice: "外部引擎原生显示，需要先在下面填写地址；段落标注只在侧栏",
};
const viewerItem = (fmt: string, label: string): Item => ({
  key: `viewer.${fmt}`,
  label,
  hint: "",
  options: Object.fromEntries(VIEWERS.map((v) => [v.id, `${v.label}（${v.license}）${VIEWER_HINT[v.id] ? ` — ${VIEWER_HINT[v.id]}` : ""}`])),
});

const INDEX: Item = {
  key: "index.multimodal_model",
  label: "多模态索引",
  hint: "文字索引总是建立（检索的是抽取出的文字）。多模态索引会直接按图像内容检索，尚未实现，目前只能选“无”",
  options: { none: "无" },
};

// 向量通道与重排（设计稿 06 D-07、D-08）：模型放在模型目录，旁边显示状态
const EMBEDDING: Item = {
  key: "index.embedding_model",
  label: "向量模型",
  hint: "向量通道能做换说法、跨语言的匹配；不用时只有关键词和短语两路。模型放在模型目录，不进安装包；向量在后台逐批补建",
  options: { "jina-v2-base-zh": "jina-embeddings-v2-base-zh（中英双语）", none: "不用向量" },
};
const RERANK: Item = {
  key: "index.rerank",
  label: "重排",
  hint: "用 Cross-encoder 重排融合后的前几个单元（个数见下方“检索参数”）。默认不重排：回归题上本机的重排模型让段落命中从 8/12 降到 7/12，每次检索多约 1 秒（设计稿 06 D-08 修订）",
  options: { off: "不重排", auto: "装了重排模型就重排" },
};
const CHANNEL_STATE: Record<string, string> = { ready: "已就绪", building: "补建中", off: "未启用", missing: "缺模型", error: "出错", on: "已启用" };

function ChannelStatus({ s }: { s: any }) {
  if (!s) return null;
  const tone = s.state === "ready" || s.state === "on" ? "good" : s.state === "missing" || s.state === "error" ? "warn" : undefined;
  return (
    <div className="small-text">
      状态：<Tag tone={tone}>{CHANNEL_STATE[s.state] ?? s.state}</Tag>
      {s.total != null && ` 已建 ${s.done} / ${s.total} 个单元`}
      {s.reason && <span className="muted">（{s.reason}）</span>}
    </div>
  );
}

// 检索参数（设计稿 06 D-21）：只影响查询、不用重建索引；工作台与 AI（MCP、命令行）读同一份，保存后下一次调用就生效
type NumItem = { key: string; label: string; hint: string };
const RETRIEVAL_GROUPS: [string, NumItem[]][] = [
  [
    "返回与展示",
    [
      { key: "retrieval.limit", label: "AI 检索返回条数", hint: "AI 与命令行调用检索、没有指定条数时返回几条（工作台检索页固定 60 条）" },
      { key: "retrieval.exact_limit", label: "字面查找条目数", hint: "字面查找没有指定条数时最多返回几个条目" },
      { key: "retrieval.passages_shown", label: "每条展示的命中单元", hint: "同一条目命中多处时展示几处；其余记为“还有 n 处命中未展示”" },
      { key: "retrieval.snippet_chars", label: "片段长度（字）", hint: "每个命中片段最多几个字。加大能少读几次原件，但 AI 每次检索读进的内容更多" },
      { key: "retrieval.basis_shown", label: "依据展示条数", hint: "判断的依据、框架页的输入清单各展示几条" },
      { key: "retrieval.relation_ids_shown", label: "一跳关系 ID 数", hint: "“引用它的判断”“用到它的框架页”各给几个 ID" },
      { key: "retrieval.links_shown", label: "判断关系条数", hint: "一条判断的支持、反对、替代等关系给几条" },
    ],
  ],
  [
    "召回与融合（高级）",
    [
      { key: "retrieval.pool_min", label: "候选池下限", hint: "每路召回至少取几个单元；实际取 max(下限, 返回条数 × 倍数)" },
      { key: "retrieval.pool_factor", label: "候选池倍数", hint: "见上一项" },
      { key: "retrieval.phrase_limit", label: "短语路段落数", hint: "整个查询作为短语出现的段落最多取几个" },
      { key: "retrieval.rrf_k", label: "RRF 常数", hint: "几路名次合并时的平滑常数：越大，各路前几名之间的差距越小" },
      { key: "retrieval.rerank_top", label: "重排候选数", hint: "设置为重排时，重排融合后的前几个单元" },
    ],
  ],
  [
    "联想",
    [
      { key: "retrieval.associate_seeds", label: "起点数", hint: "从检索的前几条出发" },
      { key: "retrieval.associate_fanout", label: "每种关系展开上限", hint: "每个节点每种关系最多展开几个；避免很泛的对象把全库连进来" },
      { key: "retrieval.associate_vector_min", label: "向量近邻阈值", hint: "相似度低于它的近邻不算；jina 上跨语言的同主题段落约 0.45，无关的约 0.1–0.3" },
    ],
  ],
];

// 数值设置改为"先改、再确认保存"：输入框只改草稿，页面底部列出改了什么、会带来什么影响，确认后一起保存
type Drafts = Record<string, string>;
const LABELS: Record<string, string> = {};

function fieldError(key: string, text: string, meta: any): string | null {
  if (!meta) return null;
  if (text.trim() === "") return "不能为空";
  const n = Number(text);
  if (!Number.isFinite(n)) return "要填数字";
  if (Number.isInteger(meta.default) && !Number.isInteger(n)) return "要填整数";
  if (n < meta.min || n > meta.max) return `取值要在 ${meta.min} 到 ${meta.max} 之间`;
  return null;
}

function NumberField({ item, value, meta, draft, onDraft }: { item: NumItem; value: any; meta: any; draft?: string; onDraft: (key: string, text: string | null) => void }) {
  LABELS[item.key] = item.label;
  const text = draft ?? (value == null ? "" : String(value));
  const error = draft != null ? fieldError(item.key, draft, meta) : null;
  const isDefault = meta && Number(value) === Number(meta.default);
  return (
    <tr className={draft != null ? "pending" : undefined}>
      <th>{item.label}</th>
      <td>
        <div className="row tight">
          <input
            type="number"
            className="num"
            value={text}
            min={meta?.min}
            max={meta?.max}
            step={Number.isInteger(meta?.default) ? 1 : 0.05}
            onChange={(e) => onDraft(item.key, e.target.value.trim() === String(value ?? "") ? null : e.target.value)}
            aria-label={item.label}
          />
          {meta && (
            <span className="muted small-text">
              {meta.min}–{meta.max}，默认 {meta.default}
              {!isDefault && " · 当前不是默认值"}
              {draft != null && !error && ` · 待保存（现为 ${value}）`}
            </span>
          )}
        </div>
        {error && <div className="small-text warn-text">{error}</div>}
        <div className="muted small-text">{item.hint}</div>
      </td>
    </tr>
  );
}

// 检索单元长度（设计稿 06 D-22）：改了要整库重建索引、重算向量
const UNIT_ITEMS: NumItem[] = [
  { key: "index.units_target", label: "检索单元目标长度", hint: "相邻段落合并到大约多少 token 就断开。中文按每字约 0.9 token 估计（300 ≈ 330 个汉字），英文约 4 个字母 1 token。短单元定位更准，长单元上下文更完整" },
  { key: "index.units_max", label: "检索单元上限", hint: "单元最多多少 token；单段更长时按句末切开。打开重排时不能超过 400（重排模型的输入上限 512，含查询与上下文）" },
  { key: "index.units_context_chars", label: "上下文字数", hint: "每个单元带的“标题 › 小节”上下文最多几个字；0 表示不带。打开重排时不能超过 160" },
];

function RetrievalParams({ data, drafts, onDraft }: { data: any; drafts: Drafts; onDraft: (key: string, text: string | null) => void }) {
  const values = data?.values ?? {};
  const numbers = data?.numbers ?? {};
  const changed = Object.keys(numbers).filter((k) => k.startsWith("retrieval.") && Number(values[k]) !== Number(numbers[k].default));
  return (
    <>
      <p className="muted small-text">
        只影响查询，不用重建索引。工作台和 AI（MCP、命令行）用同一份设置，保存后下一次检索就生效，AI 不用重启；检索结果的 <code>params</code> 写明本次用的值。改完后在页面底部确认保存；每次保存记一条过程日志（旧值、新值）。回归题按默认值评测，改动后结果可能和评测数字不一致。
      </p>
      {RETRIEVAL_GROUPS.map(([title, items]) => (
        <div key={title}>
          <h4>{title}</h4>
          <table className="kv settings">
            <tbody>
              {items.map((it) => (
                <NumberField key={it.key} item={it} value={values[it.key]} meta={numbers[it.key]} draft={drafts[it.key]} onDraft={onDraft} />
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <div className="row tight">
        <button type="button" className="small" disabled={!changed.length} onClick={() => changed.forEach((k) => onDraft(k, String(numbers[k].default)))}>
          全部恢复默认{changed.length ? `（${changed.length} 项不是默认值）` : ""}
        </button>
        <span className="muted small-text">只填进草稿，确认保存后才生效</span>
      </div>
    </>
  );
}

// 关键改变：保存前列出这次修改会带来什么（设计稿 06 D-21 至 D-23）。
// 一项修改：[键, 现值, 新值]；数值设置的现值、新值是数字，下拉设置是取值字符串
type Change = [string, any, any];
const OPTION_LABELS: Record<string, Record<string, string>> = {};
const shown = (key: string, v: any) => (OPTION_LABELS[key]?.[v] ?? (v === "" || v == null ? "（空）" : String(v)));

function nextOf(changes: Change[], values: any) {
  return (k: string) => {
    const c = changes.find(([key]) => key === k);
    return c ? c[2] : values[k];
  };
}

// 下拉设置的影响：只写会带来后果的；阅读器、快照这类只影响默认显示
function selectImpacts(key: string, to: string, values: any, next: (k: string) => any): string[] {
  const out: string[] = [];
  if (key.startsWith("extraction.")) {
    if (key === "extraction.pdf" && to === "mineru") {
      out.push("PDF 改为 MinerU 分段：MinerU 处理完后，还没被引用的 PDF 改用它的分段，这些原件的段落编号会变；已被引用的只补公式");
      if (!(next("models.layout") === "mineru" && next("models.layout_url"))) out.push("还没有配置 MinerU（模型与引擎 → 版面抽取、版面引擎地址）：配置之前仍按内置抽取处理");
    } else if (to === "off") out.push(`${LABELS[key] ?? key} 登记时不再自动抽取：要在原件页手动抽取，抽取前检索不到正文`);
    else out.push(`${LABELS[key] ?? key} 的抽取方式只影响以后的登记和重新抽取，已有的抽取不变`);
  }
  if (key === "extraction.snapshot" || key.startsWith("viewer.")) out.push(`${LABELS[key] ?? key}：只影响以后打开原件时的默认显示，不改数据`);
  if (key === "models.layout" && to === "mineru") out.push("启用 MinerU 版面抽取：需要填写版面引擎地址；PDF 的公式块会补上 LaTeX（OCR 档，未经人确认）");
  if (key === "models.layout" && to === "none") out.push("停用版面抽取：以后登记的 PDF 不再补公式 LaTeX，已有结果保留");
  if (key === "models.layout_mode" && to === "replace") out.push("版面引擎结果改为“整份替换”：处理过的 PDF 段落编号会变，引用它们的判断会进入待复核");
  if (key === "models.layout_mode" && to !== "replace") out.push("版面引擎只补公式，不改段落与锚点");
  if (key === "models.layout_auto" && to === "on") out.push("登记、补抽 PDF 后自动交给 MinerU 处理（只在地址是本机时），处理期间占用较多 CPU");
  if (key === "models.layout_auto" && to === "off") out.push("MinerU 不再自动运行，要在原件页手动处理");
  if (key === "models.layout_tier") out.push("MinerU 档位变了：以后的处理按新档位；已处理的原件要在原件页重新抽取才会重新调用");
  if (key === "models.layout_launch" && to === "auto") out.push("需要时按你填写的启动命令自动启动 MinerU（新命令行窗口），空闲 10 分钟后关闭");
  if (key === "models.formula") out.push(to === "none" ? "公式块旁的“识别”按钮停用" : "公式识别跟随版面引擎（MinerU 识别公式截图）");
  if (key === "models.llm" && to === "openai") {
    const url = String(next("models.llm_url") ?? "");
    const local = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(url);
    out.push(`启用大模型：只在你点击“用大模型识别”或“交给 AI 复核”时调用，登记和定时任务不会调用${url && !local ? "；接口地址不是本机，原件的截图会发到这个地址" : ""}`);
  }
  if (key === "review.ai") {
    const scope: Record<string, string> = { off: "不再接受 AI 复核", framework: "AI 只能复核框架页与关联边", all: "AI 可以复核框架页、关联边，以及依据已变化的判断" };
    out.push(`${scope[to] ?? to}；已有的复核记录不变，人已复核始终只能由人做`);
  }
  if (key === "index.embedding_model") {
    out.push(to === "none" ? "停用向量：检索只用关键词和短语，换说法、跨语言的查询可能找不全" : "换向量模型：要用新模型重算全部检索单元的向量（后台进行，数据多时要很久），完成前向量通道只覆盖一部分；进度见首页");
  }
  if (key === "index.rerank") {
    out.push(to === "auto" ? "打开重排（装了重排模型才生效）：每次检索多约 1 秒；回归题上段落命中从 8/12 降到 7/12" : "关闭重排：按融合顺序返回");
  }
  return out;
}

function impactsOf(changes: Change[], values: any, numbers: any): string[] {
  const out: string[] = [];
  const next = nextOf(changes, values);
  const num = (k: string) => Number(next(k));
  const keys = changes.map(([k]) => k);
  for (const [k, , to] of changes) if (!numbers[k]) out.push(...selectImpacts(k, to, values, next));
  if (keys.some((k) => k.startsWith("index.units_"))) {
    out.push("检索单元长度变了：保存后在后台整库重建索引（进度在首页“状态”卡），然后按新单元重算全部向量；完成前检索结果可能不全。段落编号和已有引用不变");
    const t = num("index.units_target");
    out.push(`新的目标长度约 ${t} token（约 ${Math.round(t / 0.9)} 个汉字）${t < 300 ? "：单元更短，定位更准，但每个命中带的上下文更少" : t > 300 ? "：单元更长，上下文更完整，但命中段落的定位更粗，关键词匹配更容易被稀释" : ""}`);
  }
  if (keys.some((k) => k.startsWith("retrieval."))) out.push("工作台和 AI 下一次检索就用新值，AI 不用重启");
  const load = (get: (k: string) => number) => get("retrieval.limit") * get("retrieval.passages_shown") * get("retrieval.snippet_chars");
  const before = load((k) => Number(values[k]));
  const after = load(num);
  if (before && after / before > 1.2) out.push(`AI 每次检索最多读进约 ${after.toLocaleString()} 字的片段（原来约 ${before.toLocaleString()} 字），占用更多上下文`);
  if (before && after / before < 0.8) out.push(`AI 每次检索最多读进约 ${after.toLocaleString()} 字的片段（原来约 ${before.toLocaleString()} 字），可能要多读几次原件`);
  if (keys.includes("retrieval.rerank_top") && next("index.rerank") === "auto") out.push(`重排候选改为 ${num("retrieval.rerank_top")} 个：每次检索的重排耗时大致按比例变化`);
  if (keys.some((k) => ["retrieval.rrf_k", "retrieval.pool_min", "retrieval.pool_factor", "retrieval.phrase_limit"].includes(k))) out.push("召回与融合参数变了：同一个查询的结果和名次可能不同");
  if (keys.some((k) => k.startsWith("retrieval.associate_"))) out.push("只影响联想（search_associate），不影响普通检索");
  if (keys.some((k) => k.startsWith("inspection."))) out.push("巡检设置只影响以后准备的巡检包；定时准备只在本机做规则检查，不调用大模型");
  if (keys.includes("inspection.interval_days") && num("inspection.interval_days") === 0) out.push("关闭定时准备：只能在巡检页手动准备巡检包");
  if (changes.some(([k, , v]) => numbers[k] && Number(v) !== Number(numbers[k].default))) out.push("有参数不是默认值：回归题是按默认值评测的，评测数字不再直接适用");
  return out;
}

function crossError(changes: Change[], values: any): string | null {
  const next = nextOf(changes, values);
  if (Number(next("index.units_target")) > Number(next("index.units_max"))) return "检索单元的目标长度不能大于上限";
  if (next("index.rerank") === "auto" && (Number(next("index.units_max")) > 400 || Number(next("index.units_context_chars")) > 160)) return "打开重排时，检索单元上限不能超过 400、上下文不能超过 160 字（重排模型的输入上限 512 token）";
  return null;
}

function PendingBar({ data, drafts, onDiscard, onSaved }: { data: any; drafts: Drafts; onDiscard: () => void; onSaved: (msg: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const values = data?.values ?? {};
  const numbers = data?.numbers ?? {};
  const keys = Object.keys(drafts);
  if (!keys.length) return null;
  const invalid = keys.filter((k) => numbers[k] && fieldError(k, drafts[k], numbers[k]));
  const changes: Change[] = keys
    .filter((k) => !invalid.includes(k))
    .map((k) => (numbers[k] ? [k, Number(values[k]), Number(drafts[k])] : [k, values[k], drafts[k]]));
  const cross = crossError(changes, values);
  const impacts = impactsOf(changes, values, numbers);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await call<any>("settings.set", { values: Object.fromEntries(changes.map(([k, , v]) => [k, v])) });
      onSaved(r.rebuild ? `已保存 ${changes.length} 项；索引正在后台重建，进度见首页“状态”卡` : `已保存 ${changes.length} 项`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="pending-bar" role="region" aria-label="待保存的修改">
      <strong>{keys.length} 项待保存</strong>
      <ul className="pending-list">
        {keys.map((k) => (
          <li key={k}>
            {LABELS[k] ?? k}：{shown(k, values[k])} → <strong>{shown(k, drafts[k])}</strong>
            {invalid.includes(k) && <span className="warn-text">（{fieldError(k, drafts[k], numbers[k])}）</span>}
          </li>
        ))}
      </ul>
      {impacts.length > 0 && (
        <ul className="pending-impacts small-text">
          {impacts.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      )}
      {cross && <div className="small-text warn-text">{cross}</div>}
      {error && <div className="small-text warn-text">{error}</div>}
      <div className="row tight">
        <button type="button" className="primary small" disabled={busy || invalid.length > 0 || !!cross} onClick={save}>
          {busy ? "正在保存…" : "确认保存"}
        </button>
        <button type="button" className="small" disabled={busy} onClick={onDiscard}>
          放弃修改
        </button>
      </div>
    </div>
  );
}

// 定期巡检（设计稿 07 D-03、D-09、D-11、D-25）：数值先改后存，agent 与措辞表单独保存
const INSPECTION_ITEMS: NumItem[] = [
  { key: "inspection.interval_days", label: "定时准备的周期（天）", hint: "到期时在本机做规则检查、生成巡检包，不调用大模型；0 关闭定时准备（仍可在巡检页手动准备）" },
  { key: "inspection.max_segments", label: "每期阅读预算（段）", hint: "巡检包里要巡检员读的段落总数上限；超出的可疑项留到下一期" },
  { key: "inspection.explore_ratio", label: "探索样本比例", hint: "预算中用于覆盖图里“命中未读”“相关未读”段落的比例；让阅读范围逐期扩大" },
  { key: "inspection.window_days", label: "检索命中统计窗口（天）", hint: "覆盖图统计“命中未读”看最近多少天的 AI 检索" },
  { key: "inspection.hit_min", label: "命中未读的次数", hint: "窗口内被检索返回不少于这么多次、从没被读，才记为“命中未读”" },
  { key: "inspection.related_min", label: "相关未读的相似度", hint: "有向量模型时，与近期判断的相似度不低于这个值才记为“相关未读”" },
  { key: "inspection.first_days", label: "第一期的范围（天）", hint: "第一期巡检看最近多少天写的判断；之后每期接着上一期的结束时间" },
];

function InspectionAgents({ values, save }: { values: Record<string, string>; save: (v: Record<string, string>) => Promise<void> }) {
  const [agents] = useLoad(() => call<any[]>("agent.list"), []);
  const [words, setWords] = useState(values["inspection.framework_words"] ?? "");
  const [results, setResults] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const names = (agents ?? []).map((a: any) => a.name);
  const same = values["inspection.inspector"] && values["inspection.inspector"] === values["inspection.reviewer"];
  const test = async (name: string) => {
    setBusy(name);
    setResults((r) => ({ ...r, [name]: "正在测试：会真的启动一次 agent，最多等 3 分钟…" }));
    try {
      const r = await call<any>("agent.test", { agent: name });
      const text = r.steps.map((s: any) => `${{ command: "命令", run: "运行", identity: "MCP 身份" }[s.step as string] ?? s.step}${s.ok ? "✓" : "✗"} ${s.detail ?? ""}${s.seconds != null ? `（${s.seconds} 秒）` : ""}`).join("；");
      setResults((x) => ({ ...x, [name]: `${r.ok ? "连接正常" : "有问题"}：${text}` }));
    } catch (e: any) {
      setResults((x) => ({ ...x, [name]: e.message }));
    } finally {
      setBusy(null);
    }
  };
  const role = (key: string, label: string, hint: string) => {
    const value = values[key] ?? "";
    const info = (agents ?? []).find((a: any) => a.name === value);
    return (
      <tr key={key}>
        <th>{label}</th>
        <td>
          <div className="row tight">
            <select value={value} onChange={(e) => save({ [key]: e.target.value })} aria-label={label}>
              <option value="">（不选：只复制领取提示）</option>
              {names.map((n: string) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            {value && info && (info.available ? <Tag tone="good">本机找得到</Tag> : <Tag tone="warn">本机找不到命令</Tag>)}
            {value && (
              <button type="button" className="small" disabled={!!busy} onClick={() => test(value)}>
                {busy === value ? "测试中…" : "测试连接"}
              </button>
            )}
          </div>
          {value && results[value] && <div className="small-text">{results[value]}</div>}
          <div className="muted small-text">{hint}</div>
        </td>
      </tr>
    );
  };
  return (
    <>
      <table className="kv settings">
        <tbody>
          {role("inspection.inspector", "巡检员 agent（辅）", "领取巡检包、读原件、提交发现；可以用便宜一些的模型。agent 命令模板在数据目录的 config.json 的 agents 里")}
          {role("inspection.reviewer", "复核员 agent（主）", "对每条发现自己重新读原件后确认、驳回或拿不准；发现涉及的判断要由它复核时，“复核”里的 AI 复核范围要设为“all”")}
          <tr>
            <th>评价性措辞</th>
            <td>
              <div className="row tight">
                <input className="grow" value={words} onChange={(e) => setWords(e.target.value)} aria-label="评价性措辞" />
                <button type="button" className="small" onClick={() => save({ "inspection.framework_words": words })}>
                  保存
                </button>
              </div>
              <div className="muted small-text">规则检查在判断里查找这些词（逗号分隔），草图 §4 不允许判断里出现评价性、框架性措辞；“目前有几种思路”总会检查</div>
            </td>
          </tr>
        </tbody>
      </table>
      {same && <p className="small-text warn-text">巡检员和复核员选了同一个 agent：可以保存，但二次检查的独立性降低。</p>}
      <p className="muted small-text">测试连接分三步：命令能否找到（--version）、用一句短提示启动一次、核对它经 MCP 调用 burrowl 时的身份。测试会真的调用一次大模型，测试运行也会登记为对话原件。</p>
    </>
  );
}

// 外部阅读引擎 ONLYOFFICE（设计稿 03 D-13）：引擎由用户自己运行，这里只填地址与密钥
function EngineSettings({ values, save }: { values: Record<string, string>; save: (v: Record<string, string>) => Promise<void> }) {
  const [url, setUrl] = useState(values["viewer.onlyoffice_url"] ?? "");
  const [back, setBack] = useState(values["viewer.onlyoffice_burrowl_url"] ?? "");
  const [secret, setSecret] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    try {
      setResult(await fn());
    } catch (e: any) {
      setResult(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <h4>外部引擎：ONLYOFFICE Docs（可选）</h4>
      <p className="muted small-text">
        Word、Excel、PPT 原生显示，还原度最高；引擎需要你自己安装运行（例如 <code>docker run -d -p 8080:80 -e JWT_SECRET=密钥 onlyoffice/documentserver</code>），burrowl 不打包也不启动它。只读查看，不能编辑；段落标注只在阅读模式的侧栏里列出。
      </p>
      <table className="kv settings">
        <tbody>
          <tr>
            <th>引擎地址</th>
            <td>
              <input className="grow" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:8080（留空表示不用）" />
            </td>
          </tr>
          <tr>
            <th>引擎访问 burrowl 的地址</th>
            <td>
              <input className="grow" value={back} onChange={(e) => setBack(e.target.value)} placeholder="留空：用浏览器访问工作台的地址；引擎在 Docker 里时填 http://host.docker.internal:端口" />
              <div className="muted small-text">引擎凭一次性令牌从这个地址取原件（只读，10 分钟内有效）</div>
            </td>
          </tr>
          <tr>
            <th>JWT 密钥</th>
            <td>
              <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={values["viewer.onlyoffice_secret"] ? "已设置（不显示；填新的会替换）" : "与引擎的 JWT_SECRET 相同；引擎关了 JWT 时留空"} />
            </td>
          </tr>
        </tbody>
      </table>
      <div className="row tight">
        <button
          type="button"
          className="primary small"
          disabled={busy}
          onClick={() =>
            run(async () => {
              await save({ "viewer.onlyoffice_url": url, "viewer.onlyoffice_burrowl_url": back, ...(secret ? { "viewer.onlyoffice_secret": secret } : {}) });
              setSecret("");
              return "已保存";
            })
          }
        >
          保存
        </button>
        <button type="button" className="small" disabled={busy || !url.trim()} onClick={() => run(async () => {
          const r = await call<any>("settings.check_engine", { url: url.trim() });
          return r.ok ? `连接正常（${r.url}）` : `连不上：${r.detail}`;
        })}>
          测试连接
        </button>
        {values["viewer.onlyoffice_secret"] && (
          <button type="button" className="small" disabled={busy} onClick={() => run(async () => (await save({ "viewer.onlyoffice_secret": "" }), "已清除密钥"))}>
            清除密钥
          </button>
        )}
        {result && <span className="small-text">{result}</span>}
      </div>
    </>
  );
}

// 模型服务地址：保存与测试连接（设计稿 05 D-05）
function ModelUrl({ valueKey, values, save, slot, placeholder }: { valueKey: string; values: Record<string, string>; save: (v: Record<string, string>) => Promise<void>; slot: string; placeholder: string }) {
  const [url, setUrl] = useState(values[valueKey] ?? "");
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const local = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(url.trim());
  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    try {
      setResult(await fn());
    } catch (e: any) {
      setResult(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="row tight">
        <input className="grow" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={placeholder} />
        <button type="button" className="small primary" disabled={busy} onClick={() => run(async () => (await save({ [valueKey]: url.trim() }), "已保存"))}>
          保存
        </button>
        <button type="button" className="small" disabled={busy || !values[valueKey]} onClick={() => run(async () => {
          const r = await call<any>("models.check", { slot });
          if (r.starting) {
            setResult(r.detail);
            return await waitCheck();
          }
          return r.ok ? `连接正常：${r.detail}` : `有问题：${r.detail}`;
        })}>
          测试连接
        </button>
      </div>
      {url.trim() && !local && <div className="small-text warn-text">不是本机地址：不会自动运行，只能在原件页手动调用</div>}
      {result && <div className="small-text">{result}</div>}
    </>
  );
}

// 自动启动时，测试连接在后台进行：轮询到结束（第一次运行要下载模型）
async function waitCheck(): Promise<string> {
  for (;;) {
    await new Promise((r) => setTimeout(r, 2000));
    const st = await call<any>("models.status");
    const c = st?.check ?? {};
    if (c.state === "done") {
      const tail = c.started ? "（这次测试启动的 MinerU 已关闭）" : "";
      return c.ok ? `连接正常：${c.detail}${tail}` : `有问题：${c.detail}${tail}`;
    }
  }
}

// 启动命令与运行状态（设计稿 05 D-19、D-20）
function LaunchFields({ values, save }: { values: Record<string, string>; save: (v: Record<string, string>) => Promise<void> }) {
  const [cmd, setCmd] = useState(values["models.layout_cmd"] ?? "");
  const [result, setResult] = useState<string | null>(null);
  const [status, , reload] = useLoad(() => call<any>("models.status"), []);
  const launch = status?.launch ?? {};
  const STATE: Record<string, string> = { stopped: "没有运行", starting: "正在启动", running: "运行中", failed: "启动失败" };
  return (
    <div className="field-stack">
      <div className="row tight">
        <input className="grow" value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder="mineru-api（或 mineru-api.exe 的完整路径）" aria-label="MinerU 启动命令" />
        <button type="button" className="small primary" onClick={async () => {
          try {
            await save({ "models.layout_cmd": cmd.trim() });
            setResult("已保存");
          } catch (e: any) {
            setResult(e.message);
          }
        }}>
          保存
        </button>
      </div>
      <div className="row tight small-text">
        <span className="muted">
          启动参数自动加上 --host 127.0.0.1 --port（取地址里的端口）和 --tier（档位不是“自动”时）。状态：{STATE[launch.state] ?? launch.state ?? "—"}
          {launch.pid ? `（进程 ${launch.pid}${launch.owned ? "，由工作台启动" : ""}）` : ""}
          {launch.error ? `：${launch.error}` : ""}
        </span>
        {launch.pid && (
          <button type="button" className="small" onClick={async () => {
            await call("models.stop");
            reload();
          }}>
            关闭 MinerU
          </button>
        )}
        {result && <span>{result}</span>}
      </div>
    </div>
  );
}

// 大模型接口：地址、模型名、密钥一起保存（设计稿 05 D-05）；只在人点击"用大模型识别"时调用
function LlmFields({ values, save }: { values: Record<string, string>; save: (v: Record<string, string>) => Promise<void> }) {
  const [url, setUrl] = useState(values["models.llm_url"] ?? "");
  const [model, setModel] = useState(values["models.llm_model"] ?? "");
  const [key, setKey] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    try {
      setResult(await fn());
    } catch (e: any) {
      setResult(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="field-stack">
      <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:11434/v1（OpenAI 兼容，含 /v1）" aria-label="大模型接口地址" />
      <div className="field-pair">
        <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="模型名（需能看图）" aria-label="模型名" />
        <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={values["models.llm_key"] ? "密钥已设置（填新的会替换）" : "API 密钥（本地服务可留空）"} aria-label="API 密钥" />
      </div>
      <div className="row tight">
        <button type="button" className="small primary" disabled={busy} onClick={() => run(async () => {
          await save({ "models.llm_url": url.trim(), "models.llm_model": model.trim(), ...(key ? { "models.llm_key": key } : {}) });
          setKey("");
          return "已保存";
        })}>
          保存
        </button>
        <button type="button" className="small" disabled={busy || !values["models.llm_url"]} onClick={() => run(async () => {
          const r = await call<any>("models.check", { slot: "llm" });
          return r.ok ? `连接正常：${r.detail}` : `有问题：${r.detail}`;
        })} title="用已保存的地址测试">
          测试连接
        </button>
        {values["models.llm_key"] && (
          <button type="button" className="small" disabled={busy} onClick={() => run(async () => (await save({ "models.llm_key": "" }), "已清除密钥"))}>
            清除密钥
          </button>
        )}
        {result && <span className="small-text">{result}</span>}
      </div>
    </div>
  );
}

// 个人偏好：只存在这台浏览器（localStorage），不影响别人
function ReadingPrefs() {
  const [p, set] = usePrefs();
  return (
    <>
      <h4>个人偏好（只在这台浏览器）</h4>
      <table className="kv settings">
        <tbody>
          <tr>
            <th>默认视图</th>
            <td>
              <select value={p.view} onChange={(e) => set({ view: e.target.value as typeof p.view })}>
                <option value="original">原样</option>
                <option value="compare">对照（原页 + 抽取文字）</option>
                <option value="text">文字</option>
              </select>
            </td>
          </tr>
          <tr>
            <th>翻页</th>
            <td>
              <select value={p.scroll} onChange={(e) => set({ scroll: e.target.value as typeof p.scroll })}>
                <option value="continuous">连续滚动</option>
                <option value="page">单页</option>
              </select>{" "}
              <label className="check">
                <input type="checkbox" checked={p.spread} onChange={(e) => set({ spread: e.target.checked })} /> 双页
              </label>
            </td>
          </tr>
          <tr>
            <th>默认缩放</th>
            <td>
              <select value={p.zoom} onChange={(e) => set({ zoom: e.target.value })}>
                <option value="page-width">适合宽度</option>
                <option value="page-fit">整页</option>
                <option value="auto">自动</option>
                {["75", "100", "125", "150", "200"].map((z) => (
                  <option key={z} value={z}>
                    {z}%
                  </option>
                ))}
              </select>
            </td>
          </tr>
          <tr>
            <th>显示</th>
            <td className="row tight">
              <label className="check">
                <input type="checkbox" checked={p.marks} onChange={(e) => set({ marks: e.target.checked })} /> 段落标注
              </label>
              <label className="check">
                <input type="checkbox" checked={p.sidebar} onChange={(e) => set({ sidebar: e.target.checked })} /> 展开侧栏
              </label>
              <label className="check">
                <input type="checkbox" checked={p.invertDark} onChange={(e) => set({ invertDark: e.target.checked })} /> 深色模式下反色显示 PDF 页面
              </label>
              <label className="check">
                <input type="checkbox" checked={p.fullscreen} onChange={(e) => set({ fullscreen: e.target.checked })} /> 进入阅读时请求浏览器全屏
              </label>
            </td>
          </tr>
        </tbody>
      </table>
    </>
  );
}

const SECTIONS: [string, string][] = [
  ["set-extract", "抽取方式"],
  ["set-snapshot", "页面快照"],
  ["set-reading", "阅读"],
  ["set-models", "模型与引擎"],
  ["set-review", "复核"],
  ["set-index", "检索索引"],
  ["set-retrieval", "检索参数"],
  ["set-inspection", "巡检"],
];

export function Settings() {
  const [data, error, reload] = useLoad(() => call<any>("settings.get"), []);
  const [health, , reloadHealth] = useLoad(() => call<any>("index.health"), []);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const onDraft = (key: string, text: string | null) => {
    setSavedMsg(null);
    setDrafts((d) => {
      const next = { ...d };
      if (text == null) delete next[key];
      else next[key] = text;
      return next;
    });
  };
  const saveMany = async (values: Record<string, any>) => {
    await call("settings.set", { values });
    reload();
  };
  const conv = data?.converters ?? {};
  const row = (item: Item, inactive?: string, group?: string) => {
    const choices: string[] = data?.choices?.[item.key] ?? Object.keys(item.options);
    const saved = data?.values?.[item.key] ?? "";
    const draft = drafts[item.key];
    LABELS[item.key] = group ? `${group} · ${item.label}` : item.label;
    OPTION_LABELS[item.key] = Object.fromEntries(Object.entries(item.options).map(([k, v]) => [k, v.split(/[（—]/)[0].trim() || v]));
    return (
      <tr key={item.key} className={[inactive ? "inactive" : "", draft != null ? "pending" : ""].join(" ").trim() || undefined}>
        <th>{item.label}</th>
        <td>
          <select value={draft ?? saved} onChange={(e) => onDraft(item.key, e.target.value === saved ? null : e.target.value)} disabled={choices.length < 2 || !!inactive}>
            {choices.map((c) => (
              <option key={c} value={c}>
                {item.options[c] ?? c}
              </option>
            ))}
          </select>
          {draft != null && <span className="muted small-text"> 待保存（现为 {OPTION_LABELS[item.key]?.[saved] ?? saved}）</span>}
          {inactive && <div className="small-text warn-text">{inactive}</div>}
          <div className="muted small-text">{item.hint}</div>
        </td>
      </tr>
    );
  };
  return (
    <div className="forms single settings-page">
      <nav className="section-nav" aria-label="设置分节">
        {SECTIONS.map(([sid, label]) => (
          <button key={sid} type="button" className="small" onClick={() => document.getElementById(sid)?.scrollIntoView({ behavior: "smooth", block: "start" })}>
            {label}
          </button>
        ))}
      </nav>
      <Panel id="set-extract" title="抽取方式" actions={<span className="muted">数据目录 {data?.data_name ?? ""}；只影响以后的抽取，已有的抽取可在原件页重新抽取</span>}>
        <ErrorBox error={error} />
        <p className="muted small-text">
          原件本身始终原样保存；抽取出的文字单独留痕、标出可信度档：原样复制 &gt; 解析文字层 &gt; 人工转写 &gt; OCR 识别 &gt; AI 识别。任何一档都可以在原件页由人确认。文本文件（.txt .md .csv .json .py …）登记时原样复制，不需要设置。
        </p>
        <table className="kv settings">
          <tbody>{EXTRACTION.map((it) => row(it))}</tbody>
        </table>
        {data?.values?.["extraction.pdf"] === "mineru" && !(data?.values?.["models.layout"] === "mineru" && data?.values?.["models.layout_url"]) && (
          <p className="small-text warn-text">PDF 选了 MinerU 分段，但还没有在下面的“模型与引擎”里配置 MinerU：现在仍按内置抽取处理。</p>
        )}
      </Panel>
      <Panel id="set-snapshot" title="页面快照">
        <table className="kv settings">
          <tbody>{row(SNAPSHOT)}</tbody>
        </table>
        <p className="small-text">
          本机：Microsoft PowerPoint {conv.office_powerpoint ? <Tag tone="good">可用</Tag> : <Tag>未安装</Tag>} · Microsoft Word {conv.office_word ? <Tag tone="good">可用</Tag> : <Tag>未安装</Tag>} · Microsoft Excel {conv.office_excel ? <Tag tone="good">可用</Tag> : <Tag>未安装</Tag>} · LibreOffice{" "}
          {conv.libreoffice ? <Tag tone="good">可用</Tag> : <Tag>未安装</Tag>}
        </p>
        <p className="muted small-text">转换在后台进行，不弹出窗口；用户自己打开着的 Office 文档不会被关闭。PPT 约 10 秒、Word 约 5 秒，LibreOffice 稍慢。</p>
      </Panel>
      <Panel id="set-reading" title="阅读" actions={<span className="muted">阅读模式：原件页、条目页的"阅读"按钮</span>}>
        <p className="muted small-text">默认阅读器保存在本数据目录；阅读模式的工具栏上也可以临时换一个（只影响那一次）。</p>
        <table className="kv settings">
          <tbody>{VIEWER_FORMATS.map(([fmt, label]) => row(viewerItem(fmt, label), undefined, "默认阅读器"))}</tbody>
        </table>
        <EngineSettings key={data ? "engine-ready" : "engine-loading"} values={data?.values ?? {}} save={saveMany} />
        <ReadingPrefs />
      </Panel>
      <Panel id="set-models" title="模型与引擎" actions={<span className="muted">本地模型可以自动运行；大模型只在你点击时调用（设计稿 05）</span>}>
        <p className="muted small-text">
          burrowl 不打包、不安装模型。先安装 MinerU：<code>uv tool install --python 3.12 "mineru&gt;=4.0,&lt;5"</code>。之后可以自己运行 <code>mineru-api --port 8790 --tier basic</code>，也可以把“启动 MinerU”设成自动，由工作台在需要时启动、用完关闭。第一次运行会下载约 0.8 GB 模型；Adam 论文 15 页在 CPU 上约 90 秒。
        </p>
        <table className="kv settings">
          <tbody>
            {row(MODEL_ITEMS[0])}
            <tr>
              <th>版面引擎地址</th>
              <td>
                <ModelUrl key={data ? "layout-ready" : "layout-loading"} valueKey="models.layout_url" values={data?.values ?? {}} save={saveMany} slot="layout" placeholder="http://127.0.0.1:8790" />
              </td>
            </tr>
            {row(LAUNCH)}
            <tr>
              <th>启动命令</th>
              <td>
                <LaunchFields key={data ? "launch-ready" : "launch-loading"} values={data?.values ?? {}} save={saveMany} />
              </td>
            </tr>
            {row(MODEL_ITEMS[1], data?.values?.["extraction.pdf"] === "mineru" ? "抽取方式选了 MinerU 分段：这一项不生效（没被引用的原件采用 MinerU 分段，已被引用的只补公式）" : undefined)}
            {MODEL_ITEMS.slice(2, 5).map((it) => row(it))}
            {row(MODEL_ITEMS[5])}
            <tr>
              <th>大模型接口</th>
              <td>
                {/* key 让组件在设置读到后重新挂载、取到已保存的值；同一单元格里的兄弟组件 key 必须不同（H-18） */}
                <LlmFields key={data ? "llm-ready" : "llm-loading"} values={data?.values ?? {}} save={saveMany} />
              </td>
            </tr>
          </tbody>
        </table>
      </Panel>
      <Panel id="set-review" title="复核">
        <table className="kv settings">
          <tbody>{row(REVIEW_AI)}</tbody>
        </table>
      </Panel>
      <Panel id="set-index" title="检索索引">
        <table className="kv settings">
          <tbody>
            {row(INDEX)}
            {row(EMBEDDING)}
            <tr>
              <th />
              <td>
                <ChannelStatus s={health?.vectors} />
              </td>
            </tr>
            {row(RERANK)}
            <tr>
              <th />
              <td>
                <ChannelStatus s={health?.rerank} />
              </td>
            </tr>
          </tbody>
        </table>
        <p className="muted small-text">向量补建、索引重建的进度见首页“状态”卡。</p>
        <h4>检索单元</h4>
        <p className="muted small-text">
          检索单元是索引里的派生物：原件的段落编号、判断的引用都不变。改了长度，确认保存后在后台整库重建索引（期间可以照常使用，检索结果可能不全），然后按新单元重算向量。段落本身怎样切分决定引用编号，不能在这里改。
        </p>
        <table className="kv settings">
          <tbody>
            {UNIT_ITEMS.map((it) => (
              <NumberField key={it.key} item={it} value={data?.values?.[it.key]} meta={data?.numbers?.[it.key]} draft={drafts[it.key]} onDraft={onDraft} />
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel id="set-retrieval" title="检索参数" actions={<span className="muted">工作台与 AI 共用（设计稿 06 D-21）</span>}>
        <RetrievalParams data={data} drafts={drafts} onDraft={onDraft} />
      </Panel>
      <Panel id="set-inspection" title="巡检" actions={<span className="muted">定时只准备、人点开跑（设计稿 07）</span>}>
        <InspectionAgents key={data ? "insp-ready" : "insp-loading"} values={data?.values ?? {}} save={saveMany} />
        <table className="kv settings">
          <tbody>
            {INSPECTION_ITEMS.map((it) => (
              <NumberField key={it.key} item={it} value={data?.values?.[it.key]} meta={data?.numbers?.[it.key]} draft={drafts[it.key]} onDraft={onDraft} />
            ))}
          </tbody>
        </table>
      </Panel>
      {savedMsg && !Object.keys(drafts).length && (
        <div className="pending-bar saved" role="status">
          {savedMsg}
          <button type="button" className="small" onClick={() => setSavedMsg(null)}>
            知道了
          </button>
        </div>
      )}
      <PendingBar
        data={data}
        drafts={drafts}
        onDiscard={() => setDrafts({})}
        onSaved={(msg) => {
          setDrafts({});
          setSavedMsg(msg);
          reload();
          reloadHealth();
        }}
      />
    </div>
  );
}
