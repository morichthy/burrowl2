import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EntryLabels } from "./entryLabels";
import { parseRoute } from "./router";
import { Chips, Coordinates, IdLink, PageInputNotice, RefText } from "./ui";

describe("Coordinates", () => {
  it("按 地位 → 类型 → 现状 → 说明 显示（设计稿 10 D-25）", () => {
    const { container } = render(<Coordinates c={{
      ref: "jdg_01JC0000000000000000000001@2", layer: "judgment", sources: ["local", "external:preprint"], kind: "conclusion",
      state: { validity: "replaced", review: "human_confirmed", marks: [{ mark: "opposed", count: 2 }] },
      notes: { author: "ai", quoted: "Li et al., 2020", marks: [{ mark: "recognition_unverified", count: 1 }] },
    }} />);
    const order = [...container.querySelectorAll(".tag, .note")].map((x) => x.textContent);
    expect(order).toEqual(["判断 · 本地实证 + 外部报告（预印本）", "结论", "被替代", "人已复核", "被反驳（2 处）",
      "AI写", "转述 · 原作者 Li et al., 2020", "依据含未确认的识别"]);
  });
  it("原件一列的作者写作“登记”，不叫“写”：人登记别人的论文不能显示成人写", () => {
    const { container } = render(<Coordinates c={{
      layer: "original", sources: ["external:peer_reviewed"], kind: "artifact",
      state: { validity: "current", review: "none", marks: [] }, notes: { author: "human", marks: [] },
    }} />);
    expect([...container.querySelectorAll(".tag, .note")].map((x) => x.textContent)).toEqual(["原件 · 外部报告（同行评议）", "原件", "人登记"]);
  });
  it("当前有效、未复核时不显示现状；标记带出处时列出出处", () => {
    render(<Coordinates full c={{
      layer: "judgment", sources: ["local"], kind: "conclusion",
      state: { validity: "current", review: "none", marks: [{ mark: "basis_changed", via: [{ rel: "rel_x", end: "jdg_01JC0000000000000000000002@1", detail: "当前为第 2 版", current: "jdg_01JC0000000000000000000002@2" }] }] },
      notes: { author: "human", marks: [] },
    }} />);
    expect(screen.queryByText("当前有效")).toBeNull();
    expect(screen.queryByText("未复核")).toBeNull();
    expect(screen.getByText("（当前为第 2 版）")).toBeTruthy();
    expect(screen.getByText("当前版").getAttribute("href")).toBe(`#/entry/${encodeURIComponent("jdg_01JC0000000000000000000002@2")}`);
  });
});

describe("RefText", () => {
  it("[[ID]] 显示为上标编号，底部列出引用（设计稿 09 D-14）", () => {
    const { container } = render(<RefText text="见 [[jdg_01JC0000000000000000000001|那条判断]] 和 [[art_01JC0000000000000000000002#p1-1]]，再见 [[jdg_01JC0000000000000000000001]]" />);
    expect(screen.getByText("那条判断").closest("a")).toBeNull(); // 作者写的文字保留，不再是长链接
    const sups = [...container.querySelectorAll("sup.ref-sup > a")].map((a) => a.textContent);
    expect(sups).toEqual(["1", "2", "1"]); // 同一条目共用一个编号
    expect(container.querySelector("sup.ref-sup > a")?.getAttribute("href")).toBe("#/entry/jdg_01JC0000000000000000000001");
    const items = container.querySelectorAll("ol.ref-list > li");
    expect(items).toHaveLength(2);
    expect(items[0].querySelector("a")?.getAttribute("title")).toBe("jdg_01JC0000000000000000000001");
    expect(items[1].querySelector("button.reader-link")).toBeTruthy(); // 原件段落有"阅读"入口
  });
  it("按 Markdown 渲染标题、列表，标题里的引用仍是链接", () => {
    const { container } = render(<RefText text={"## 问题\n\n- 甲\n- 乙\n\n### 见 [[jdg_01JC0000000000000000000001|那条判断]]"} />);
    expect(container.querySelector("h2")?.textContent).toBe("问题");
    expect(container.querySelectorAll("ul > li")).toHaveLength(2);
    expect(container.querySelector("h3 a")?.getAttribute("href")).toBe("#/entry/jdg_01JC0000000000000000000001");
  });
  it("同屏按原引用批量取名，引用列表保留精确的跳转目标", async () => {
    const original = "art_01JC0000000000000000000001#p3-2";
    const historical = "pg_01JC0000000000000000000002@1";
    const fetchNames = vi.fn(async () => ({
      json: async () => ({ ok: true, result: { [original]: "实验记录 · 第 3 页", [historical]: "首次汇总 · 第 1 版" } }),
    }));
    vi.stubGlobal("fetch", fetchNames);
    try {
      const { container } = render(<EntryLabels>
        <IdLink id={original} />
        <RefText text={`[[${original}]]；[[${historical}]]`} />
      </EntryLabels>);
      await screen.findAllByText("首次汇总 · 第 1 版");
      const listed = container.querySelectorAll("ol.ref-list > li a");
      expect(listed[1].getAttribute("href")).toBe(`#/entry/${encodeURIComponent(historical)}`);
      expect(listed[1].textContent).toContain("首次汇总 · 第 1 版");
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
      input_statuses: { [ref]: { validity: "current", current_ref: current }, [other]: { validity: "current" } },
    }} />);
    expect(screen.getByText(ref).closest("a")?.getAttribute("href")).toBe(`#/entry/${encodeURIComponent(ref)}`);
    expect(screen.getByText("查看当前版").getAttribute("href")).toBe(`#/entry/${current}`);
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
