// 设置（每个数据目录各自的 config.json）：抽取方式、页面快照的转换器、检索索引方式（设计稿 01 D-11、D-17、D-18）。
import { useState } from "react";
import { call } from "../api";
import { ErrorBox, Panel, Tag, useLoad } from "../ui";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Item = { key: string; label: string; hint: string; options: Record<string, string> };

const EXTRACTION: Item[] = [
  { key: "extraction.pdf", label: "PDF", hint: "登记时用 pypdfium2 抽取每页的文字层；没有文字层的页（扫描件）标为图片页，等待 AI 或人工抽取", options: { auto: "登记时自动抽取", off: "不自动抽取（在原件页手动抽取）" } },
  { key: "extraction.pptx", label: "PPT（.pptx）", hint: "抽取每页的标题、正文、表格、备注，保留各块在页面上的位置", options: { auto: "登记时自动抽取", off: "不自动抽取" } },
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

const INDEX: Item = {
  key: "index.multimodal_model",
  label: "多模态索引",
  hint: "文字索引总是建立（检索的是抽取出的文字）。多模态索引会直接按图像内容检索，尚未实现，目前只能选“无”",
  options: { none: "无" },
};

export function Settings() {
  const [data, error, reload] = useLoad(() => call<any>("settings.get"), []);
  const [fail, setFail] = useState<string | null>(null);
  const [saved, setSaved] = useState("");
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
    <div className="forms single">
      <Panel title="抽取方式" actions={<span className="muted">数据目录 {data?.data_name ?? ""}；只影响以后的抽取，已有的抽取可在原件页重新抽取</span>}>
        <ErrorBox error={error ?? fail} />
        <p className="muted small-text">
          原件本身始终原样保存；抽取出的文字单独留痕、标出可信度档：原样复制 &gt; 解析文字层 &gt; 人工转写 &gt; OCR 识别 &gt; AI 识别。任何一档都可以在原件页由人确认。文本文件（.txt .md .csv .json .py …）登记时原样复制，不需要设置。
        </p>
        <table className="kv settings">
          <tbody>{EXTRACTION.map(row)}</tbody>
        </table>
      </Panel>
      <Panel title="页面快照">
        <table className="kv settings">
          <tbody>{row(SNAPSHOT)}</tbody>
        </table>
        <p className="small-text">
          本机：Microsoft PowerPoint {conv.office_powerpoint ? <Tag tone="good">可用</Tag> : <Tag>未安装</Tag>} · Microsoft Word {conv.office_word ? <Tag tone="good">可用</Tag> : <Tag>未安装</Tag>} · LibreOffice{" "}
          {conv.libreoffice ? <Tag tone="good">可用</Tag> : <Tag>未安装</Tag>}
        </p>
        <p className="muted small-text">转换在后台进行，不弹出窗口；用户自己打开着的 Office 文档不会被关闭。PPT 约 10 秒、Word 约 5 秒，LibreOffice 稍慢。</p>
      </Panel>
      <Panel title="检索索引">
        <table className="kv settings">
          <tbody>{row(INDEX)}</tbody>
        </table>
      </Panel>
    </div>
  );
}
