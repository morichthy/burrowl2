import { describe, expect, it } from "vitest";
import { buildMarks } from "./marks";
import { pickViewer } from "./registry";
import type { ViewerSource } from "./contract";

describe("buildMarks", () => {
  const layer = {
    units: [{ unit: "p2", page: 2, fidelity: "parsed", blocks: [{ type: "heading", box: [0.1, 0.1, 0.5, 0.02] }, { type: "formula", box: [0.3, 0.2, 0.4, 0.05] }] }],
  };
  const segs = [
    { anchor: "p2-1", unit: "p2", block: 0, text: "Title", fidelity: "parsed" },
    { anchor: "p2-2", unit: "p2", block: 1, text: "a+b", fidelity: "parsed" },
  ];
  it("每个块一个标注，带页码、位置、类型与账本里的状态", () => {
    const stats = { "p2-2": { reads: [{ id: "r1" }], citations: { conclusion: [{ judgment_id: "j1" }] } } };
    const marks = buildMarks(layer, segs, stats, "p2-2");
    expect(marks.map((m) => m.key)).toEqual(["p2:0", "p2:1"]);
    expect(marks[1]).toMatchObject({ page: 2, type: "formula", box: [0.3, 0.2, 0.4, 0.05], state: { cited: 1, read: 1, low: false, anchor: true } });
    expect(marks[0].state).toEqual({ cited: 0, read: 0, low: false, anchor: false });
  });
  it("文本原件的段落没有块：按段落序号分组", () => {
    const marks = buildMarks({ units: [{ unit: "doc" }] }, [{ anchor: "seg-0", unit: "doc", block: null, ordinal: 0, text: "x", fidelity: "copy" }], {}, "");
    expect(marks[0].key).toBe("doc:0");
  });
  it("AI 识别未确认的段落标为低可信度", () => {
    const marks = buildMarks({ units: [{ unit: "img" }] }, [{ anchor: "img-1", unit: "img", block: 0, text: "x", fidelity: "ai", verified: false }], {}, "");
    expect(marks[0].state.low).toBe(true);
  });
});

describe("pickViewer", () => {
  const source = { format: "docx" } as ViewerSource;
  it("按设置选阅读器", () => {
    expect(pickViewer(source, { snapshot: true, engines: {} }, ["pdfjs-snapshot"]).def?.id).toBe("pdfjs-snapshot");
  });
  it("选的阅读器不能用时退回能用的并说明原因", () => {
    const r = pickViewer(source, { snapshot: false, engines: {} }, ["pdfjs-snapshot"]);
    expect(r.def?.id).toBe("docx-preview");
    expect(r.note).toContain("还没有页面快照");
  });
  it("没有阅读器的格式", () => {
    expect(pickViewer({ format: "binary" } as ViewerSource, { snapshot: false, engines: {} }, []).def).toBeNull();
  });
  it("外部引擎没配置时不可选，配置后可选", () => {
    const xlsx = { format: "xlsx", suffix: ".xlsx" } as ViewerSource;
    expect(pickViewer(xlsx, { snapshot: false, engines: {} }, ["onlyoffice"]).def?.id).toBe("sheet");
    expect(pickViewer(xlsx, { snapshot: false, engines: { onlyoffice: true } }, ["onlyoffice"]).def?.id).toBe("onlyoffice");
  });
  it("CSV 可以用表格阅读器，普通文本不行", () => {
    expect(pickViewer({ format: "text", suffix: ".csv" } as ViewerSource, { snapshot: false, engines: {} }, ["sheet"]).def?.id).toBe("sheet");
    expect(pickViewer({ format: "text", suffix: ".md" } as ViewerSource, { snapshot: false, engines: {} }, ["sheet"]).def?.id).toBe("markdown");
  });
});
