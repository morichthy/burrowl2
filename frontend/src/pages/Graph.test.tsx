import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { call } from "../api";
import { Graph, edgeText, viaGroups } from "./Graph";

vi.mock("../api", () => ({ call: vi.fn(), currentDb: () => "" }));

// 一条判断依据一份已退役的原件（标记"依据已失效"，出处是那条依据关系），以及一条处置边与一条旧版本的关系
const DATA = {
  nodes: [
    {
      id: "jdg_A", type: "judgment", label: "判断甲", layer: "judgment", kind: "conclusion", sources: ["local"],
      state: { validity: "current", marks: [{ mark: "basis_lapsed", count: 1 }] }, notes: { author: "ai" },
      via: [{ mark: "basis_lapsed", rel: "rel_1", end: "art_X@1#seg-1" }],
    },
    { id: "art_X", type: "artifact", label: "原件乙", layer: "original", state: { validity: "retired" }, via: [] },
    { id: "art_Y", type: "artifact", label: "原件丙", layer: "original", state: { validity: "current" }, via: [] },
  ],
  edges: [
    { id: "rel_1", source: "jdg_A", target: "art_X", predicate: "cites", category: "evidence", count: 1, rels: ["rel_1"], evidence_from: "art_X" },
    { id: "rpl_1", source: "art_X", target: "art_Y", predicate: "replaced_by", category: "disposition", count: 1, rels: ["rpl_1"] },
  ],
  truncated: false,
  center: null,
};

beforeEach(() => {
  vi.mocked(call).mockReset();
  vi.mocked(call).mockResolvedValue(DATA);
  localStorage.clear();
});

const lastArgs = () => vi.mocked(call).mock.calls.filter((c) => c[0] === "graph.view").at(-1)?.[1] as any;

describe("关系图：旧版本的关系与人的处置（设计稿 10 D-39、D-40）", () => {
  it("默认两个开关都关；勾上后请求带上 history、dispositions", async () => {
    render(<Graph />);
    await waitFor(() => expect(lastArgs()).toBeTruthy());
    expect(lastArgs()).toMatchObject({ history: false, dispositions: false });
    fireEvent.click(screen.getByRole("button", { name: /筛选/ }));
    fireEvent.click(screen.getByLabelText("旧版本的关系"));
    await waitFor(() => expect(lastArgs()).toMatchObject({ history: true, dispositions: false }));
    fireEvent.click(screen.getByLabelText("人的处置"));
    await waitFor(() => expect(lastArgs()).toMatchObject({ history: true, dispositions: true }));
    // 开关算进组合：不再是"默认"
    expect(screen.getByText("自定义")).toBeTruthy();
  });

  it("处置、读取、旧版本、已撤销的边有自己的说法", () => {
    expect(edgeText({ predicate: "replaced_by" })).toBe("由…替代");
    expect(edgeText({ predicate: "replaced_by" }, false)).toBe("替代了");
    expect(edgeText({ predicate: "review_cites" })).toBe("复核补充依据");
    expect(edgeText({ predicate: "read_of" }, false)).toBe("被读取");
    expect(edgeText({ predicate: "cites", old: true })).toBe("依据（旧版本）");
    expect(edgeText({ predicate: "opposes", revoked: true })).toBe("反驳（已撤销）");
    expect(edgeText({ predicate: "cites", target: "art_X", count: 3 })).toBe("依据 3 段");
  });
});

describe("关系图：标记出处高亮（设计稿 10 D-41）", () => {
  it("按标记分组，另一端只取条目 ID", () => {
    expect(viaGroups(DATA.nodes[0])).toEqual([{ node: "jdg_A", mark: "basis_lapsed", rels: ["rel_1"], ends: ["art_X"] }]);
    expect(viaGroups(DATA.nodes[1])).toEqual([]);
  });

  it("选中节点后列出标记的出处，点一下高亮、再点或 Esc 取消", async () => {
    render(<Graph />);
    await waitFor(() => expect(lastArgs()).toBeTruthy());
    const search = await screen.findByLabelText("按名称找节点");
    fireEvent.change(search, { target: { value: "判断甲" } });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(await screen.findByText("标记的出处")).toBeTruthy();
    const mark = screen.getByRole("button", { name: /依据/ , pressed: false });
    fireEvent.click(mark);
    expect(mark.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText(/^出处：/)).toBeTruthy();
    fireEvent.click(mark);
    expect(mark.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(mark);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    await waitFor(() => expect(mark.getAttribute("aria-pressed")).toBe("false"));
  });
});
