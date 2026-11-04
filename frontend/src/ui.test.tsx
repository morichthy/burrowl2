import { fireEvent, render, screen } from "@testing-library/react";
import { Coordinates, RefText } from "./ui";

describe("Coordinates", () => {
  it("显示两个轴、复核和替代状态", () => {
    render(<Coordinates c={{ layer: "judgment", source_classes: ["executed", "external"], external_tiers: ["preprint"], mixed: true, superseded: true, author_kind: "ai" }} />);
    for (const text of ["判断", "亲自执行", "外部报告", "预印本", "混合来源", "已被替代", "AI 写"]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
  });
});

describe("RefText", () => {
  it("把 [[ID]] 渲染为可点击链接", () => {
    const opened: string[] = [];
    render(<RefText text="见 [[jdg_01JC0000000000000000000001|那条判断]] 和正文" open={(id) => opened.push(id)} />);
    fireEvent.click(screen.getByText("那条判断"));
    expect(opened).toEqual(["jdg_01JC0000000000000000000001"]);
  });
});
