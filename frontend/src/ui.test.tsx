import { fireEvent, render, screen } from "@testing-library/react";
import { parseRoute } from "./router";
import { Chips, Coordinates, RefText } from "./ui";

describe("Coordinates", () => {
  it("显示两个轴、复核和替代状态", () => {
    render(<Coordinates c={{ layer: "judgment", source_classes: ["executed", "external"], external_tiers: ["preprint"], mixed: true, superseded: true, author_kind: "ai" }} />);
    for (const text of ["判断", "亲自执行", "外部报告", "预印本", "混合来源", "已被替代", "AI 写"]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
  });
});

describe("RefText", () => {
  it("把 [[ID]] 渲染为指向条目页的链接", () => {
    render(<RefText text="见 [[jdg_01JC0000000000000000000001|那条判断]] 和正文" />);
    expect(screen.getByText("那条判断").getAttribute("href")).toBe("#/entry/jdg_01JC0000000000000000000001");
  });
});

describe("Chips", () => {
  it("多选筛选：点选加入、再点取消、全部清空", () => {
    let value: string[] = [];
    const { rerender } = render(<Chips multi options={[["a", "甲"], ["b", "乙"]]} value={value} onChange={(v) => (value = v)} counts={{ a: 2, b: 0 }} />);
    fireEvent.click(screen.getByText("甲"));
    expect(value).toEqual(["a"]);
    rerender(<Chips multi options={[["a", "甲"], ["b", "乙"]]} value={value} onChange={(v) => (value = v)} />);
    fireEvent.click(screen.getByText("乙"));
    expect(value).toEqual(["a", "b"]);
    fireEvent.click(screen.getByText("全部"));
    expect(value).toEqual([]);
  });
  it("单选：选中项再点一次回到全部", () => {
    let value: string[] = ["a"];
    render(<Chips options={[["a", "甲"]]} value={value} onChange={(v) => (value = v)} />);
    fireEvent.click(screen.getByText("甲"));
    expect(value).toEqual([]);
  });
});

describe("router", () => {
  it("解析哈希路由并解码中文", () => {
    expect(parseRoute("#/entry/jdg_X%23seg-1")).toEqual(["entry", "jdg_X#seg-1"]);
    expect(parseRoute("#/graph/%E6%B3%B5")).toEqual(["graph", "泵"]);
    expect(parseRoute("")).toEqual([]);
  });
});
