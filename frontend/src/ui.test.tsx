import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EntryLabels } from "./entryLabels";
import { parseRoute } from "./router";
import { Chips, Coordinates, IdLink, PageInputNotice, RefText } from "./ui";

describe("Coordinates", () => {
  it("显示两个轴、复核和替代状态", () => {
    render(<Coordinates c={{ layer: "judgment", source_classes: ["external", "local"], external_tiers: ["preprint"], mixed: true, superseded: true, author_kind: "ai" }} />);
    for (const text of ["判断", "本地实证", "外部报告", "预印本", "混合来源", "已被替代", "AI 写"]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
  });
  it("仅撤回时显示撤回，保留历史排序标记但不显示被替代", () => {
    render(<Coordinates c={{ layer: "judgment", superseded: true, replaced: false, withdrawn: true }} />);
    expect(screen.getByText("已撤回")).toBeTruthy();
    expect(screen.queryByText("已被替代")).toBeNull();
  });
});

describe("RefText", () => {
  it("把 [[ID]] 渲染为指向条目页的链接", () => {
    render(<RefText text="见 [[jdg_01JC0000000000000000000001|那条判断]] 和正文" />);
    expect(screen.getByText("那条判断").closest("a")?.getAttribute("href")).toBe("#/entry/jdg_01JC0000000000000000000001");
  });
  it("按 Markdown 渲染标题、列表，标题里的引用仍是链接", () => {
    const { container } = render(<RefText text={"## 问题\n\n- 甲\n- 乙\n\n### 见 [[jdg_01JC0000000000000000000001|那条判断]]"} />);
    expect(container.querySelector("h2")?.textContent).toBe("问题");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("h3 a")?.getAttribute("href")).toBe("#/entry/jdg_01JC0000000000000000000001");
  });
  it("同屏按原引用批量取名，保留正文别名和精确的跳转目标", async () => {
    const original = "art_01JC0000000000000000000001#p3-2";
    const historical = "pg_01JC0000000000000000000002@1";
    const alias = "jdg_01JC0000000000000000000003";
    const fetchNames = vi.fn(async () => ({
      json: async () => ({ ok: true, result: { [original]: "实验记录 · 第 3 页", [historical]: "首次汇总 · 第 1 版" } }),
    }));
    vi.stubGlobal("fetch", fetchNames);
    try {
      render(<EntryLabels>
        <IdLink id={original} />
        <RefText text={`[[${original}]]；[[${historical}]]；[[${alias}|这条判断]]`} />
      </EntryLabels>);
      expect((await screen.findByText("首次汇总 · 第 1 版")).closest("a")?.getAttribute("href"))
        .toBe(`#/entry/${encodeURIComponent(historical)}`);
      expect(screen.getAllByText("实验记录 · 第 3 页")).toHaveLength(2);
      expect(screen.getAllByText("art_")).toHaveLength(2);
      expect(screen.getByText("这条判断").closest("a")?.getAttribute("title")).toBe(alias);
      await waitFor(() => expect(fetchNames).toHaveBeenCalledTimes(1));
      expect(fetchNames).toHaveBeenCalledWith("./api/ops/entry.labels", expect.objectContaining({
        body: JSON.stringify({ refs: [original, historical] }),
      }));
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("PageInputNotice", () => {
  it("列出历史版的受影响输入及当前版入口，跳过未变化的输入", () => {
    const ref = "art_01JC0000000000000000000001#seg-2";
    const current = "art_01JC0000000000000000000002";
    const other = "rec_01JC0000000000000000000003";
    render(<PageInputNotice page={{
      page: { head_version: 2, freshness: "inputs_changed" },
      version: 1,
      change_reason: "当前版的传播原因",
      inputs: [ref, other],
      input_statuses: { [ref]: { replaced: true, current_ref: current }, [other]: {} },
    }} />);
    expect(screen.getByText(ref).closest("a")?.getAttribute("href")).toBe(`#/entry/${encodeURIComponent(ref)}`);
    expect(screen.getByText("查看当前版本").getAttribute("href")).toBe(`#/entry/${current}`);
    expect(screen.queryByText(other)).toBeNull();
    expect(screen.queryByText(/当前版的传播原因/)).toBeNull();
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

describe("Chips 不可选项", () => {
  it("disabled 的项点击无效，并显示原因", () => {
    let value: string[] = [];
    render(<Chips multi options={[["framework", "框架"], ["judgment", "判断"]]} value={value} onChange={(v) => (value = v)} disabled={{ framework: "探索模式不返回框架页" }} />);
    const btn = screen.getByText("框架").closest("button")!;
    expect(btn.getAttribute("title")).toBe("探索模式不返回框架页");
    fireEvent.click(btn);
    expect(value).toEqual([]);
    fireEvent.click(screen.getByText("判断"));
    expect(value).toEqual(["judgment"]);
  });
});

describe("router", () => {
  it("解析哈希路由并解码中文", () => {
    expect(parseRoute("#/entry/jdg_X%23seg-1")).toEqual(["entry", "jdg_X#seg-1"]);
    expect(parseRoute("#/graph/%E6%B3%B5")).toEqual(["graph", "泵"]);
    expect(parseRoute("")).toEqual([]);
  });
});
