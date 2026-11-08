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
  { key: "extraction.pdf", label: "PDF", hint: "登记时用 pypdfium2 抽取每页的文字层；没有文字层的页（扫描件）标为图片页，等待 AI 或人工抽取", options: { auto: "登记时自动抽取", off: "不自动抽取（在原件页手动抽取）" } },
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
  hint: "AI 只能对照原件层、判断层核对条目，结果另记一档；确认后从待决策列表移出（请人复核的项不移出），认为有问题时排到前面。人已复核、会写回判断层的边、原件确认抽取，始终只能由人处理",
  options: { off: "不接受 AI 复核", framework: "只接受框架页与关联边", all: "框架页、关联边，以及依据已变化的判断" },
};

// 本地模型与大模型（设计稿 05）。本地模型（地址是本机）可以在登记、补抽后自动运行；大模型只在你点击时调用
const MODEL_ITEMS: Item[] = [
  { key: "models.layout", label: "版面抽取", hint: "版面分析模型：给 PDF 的公式块补 LaTeX、给段落记下行内公式。需要你自己运行服务，见下方说明", options: { none: "不用", mineru: "MinerU（mineru-api）" } },
  { key: "models.layout_mode", label: "版面引擎的结果", hint: "补公式不改段落与锚点（推荐）；整份替换会让段落编号变化，引用它的判断可能进入待复核", options: { formulas: "补公式（也插入内置抽取漏掉的公式）", formulas_only_existing: "只补已有公式块（段落编号完全不变）", replace: "整份替换为版面引擎的分段" } },
  { key: "models.layout_auto", label: "自动运行", hint: "登记、补抽 PDF 后自动排进队列；只有地址是本机（localhost、127.0.0.1）时才会自动运行", options: { on: "自动", off: "只在原件页手动运行" } },
  { key: "models.layout_tier", label: "MinerU 档位", hint: "basic 可以只用 CPU；standard、advanced 需要更多模型，通常要 GPU。auto 由 MinerU 自己选", options: { auto: "自动", flash: "flash（只抽文字层）", basic: "basic（CPU 可用）", standard: "standard", advanced: "advanced" } },
  { key: "models.formula", label: "公式识别", hint: "公式块旁的“识别”按钮用哪个模型", options: { none: "不用", follow_layout: "跟随版面引擎（MinerU 识别公式截图）" } },
  { key: "models.llm", label: "大模型", hint: "可选。只在你点击“用大模型识别”时调用，登记、补抽、定时任务都不会调用", options: { none: "不用", openai: "OpenAI 兼容接口" } },
];

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
];

export function Settings() {
  const [data, error, reload] = useLoad(() => call<any>("settings.get"), []);
  const [fail, setFail] = useState<string | null>(null);
  const [saved, setSaved] = useState("");
  const saveMany = async (values: Record<string, string>) => {
    await call("settings.set", { values });
    reload();
  };
  const set = async (key: string, value: string) => {
    setFail(null);
    try {
      await call("settings.set", { values: { [key]: value } });
      setSaved(key);
      window.setTimeout(() => setSaved(""), 1500);
      reload();
    } catch (e: any) {
      setFail(e.message);
    }
  };
  const conv = data?.converters ?? {};
  const row = (item: Item) => {
    const choices: string[] = data?.choices?.[item.key] ?? Object.keys(item.options);
    return (
      <tr key={item.key}>
        <th>{item.label}</th>
        <td>
          <select value={data?.values?.[item.key] ?? ""} onChange={(e) => set(item.key, e.target.value)} disabled={choices.length < 2}>
            {choices.map((c) => (
              <option key={c} value={c}>
                {item.options[c] ?? c}
              </option>
            ))}
          </select>
          {saved === item.key && <span className="muted small-text"> 已保存</span>}
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
        <ErrorBox error={error ?? fail} />
        <p className="muted small-text">
          原件本身始终原样保存；抽取出的文字单独留痕、标出可信度档：原样复制 &gt; 解析文字层 &gt; 人工转写 &gt; OCR 识别 &gt; AI 识别。任何一档都可以在原件页由人确认。文本文件（.txt .md .csv .json .py …）登记时原样复制，不需要设置。
        </p>
        <table className="kv settings">
          <tbody>{EXTRACTION.map(row)}</tbody>
        </table>
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
          <tbody>{VIEWER_FORMATS.map(([fmt, label]) => row(viewerItem(fmt, label)))}</tbody>
        </table>
        <EngineSettings key={data ? "engine-ready" : "engine-loading"} values={data?.values ?? {}} save={saveMany} />
        <ReadingPrefs />
      </Panel>
      <Panel id="set-models" title="模型与引擎" actions={<span className="muted">本地模型可以自动运行；大模型只在你点击时调用（设计稿 05）</span>}>
        <p className="muted small-text">
          burrowl 不打包、不启动模型：在本机运行 MinerU 后填写地址。安装与启动：<code>uv tool install --python 3.12 "mineru&gt;=4.0,&lt;5"</code>，然后 <code>mineru-api --port 8790 --tier basic</code>（第一次运行会下载约 0.8 GB 模型；Adam 论文 15 页在 CPU 上约 90 秒）。
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
            {MODEL_ITEMS.slice(1, 5).map(row)}
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
          <tbody>{row(INDEX)}</tbody>
        </table>
      </Panel>
    </div>
  );
}
