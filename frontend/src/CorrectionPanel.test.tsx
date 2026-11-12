import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { call } from "./api";
import { CorrectionPanel } from "./CorrectionPanel";
import { EntryLabels } from "./entryLabels";

vi.mock("./api", () => ({ call: vi.fn(), currentDb: () => "" }));

const J = "jdg_01JC0000000000000000000001";
const ART = "art_01JC0000000000000000000003";

const judgment = {
  id: J, ref: `${J}@1`, entry_kind: "judgment", kind: "conclusion", version: 1, head_version: 1, objects: ["2号泵"],
  data: { text: "出口压力 0.82 MPa[^1]", conditions: "旧条件", external_author: "某文献" },
};
const out = [{ id: "rel_1", predicate: "cites", other: `${ART}#p3-2`, origin: "judgment", phrase: "依据",
  qualifiers: { why: "读数", role: "数据", marker: "1" } }];

beforeEach(() => {
  vi.mocked(call).mockReset();
  window.location.hash = "";
});

describe("人工更正面板（设计稿 11 D-18、D-20）", () => {
  it("预填当前值，只提交改动的字段，提交前列出改动", async () => {
    vi.mocked(call).mockImplementation(async (op: string) => (op === "entry.correct" ? { ref: `${J}@2`, id: J } : {}));
    render(<EntryLabels><CorrectionPanel entry={judgment} out={out} reload={vi.fn()} /></EntryLabels>);
    expect((screen.getByLabelText(/^正文/) as HTMLTextAreaElement).value).toBe("出口压力 0.82 MPa[^1]");
    expect(screen.getByText("还没有改动。")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^条件/), { target: { value: "已知：试样 S1；不清楚：其他温度" } });
    fireEvent.click(screen.getByLabelText(/适用范围尚不清晰/));
    expect(screen.getByText(/这一版将改动：条件；适用范围未明/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "写新版本" }) as HTMLButtonElement).disabled).toBe(true); // 没写理由
    fireEvent.change(screen.getByLabelText(/^理由/), { target: { value: "范围未验证" } });
    fireEvent.click(screen.getByRole("button", { name: "写新版本" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("entry.correct", {
      id: J, reason: "范围未验证", conditions: "已知：试样 S1；不清楚：其他温度", scope_unclear: true,
    }));
    await waitFor(() => expect(window.location.hash).toBe(`#/entry/${encodeURIComponent(`${J}@2`)}`));
  });

  it("去掉依据并加一条带作用与原因的关系，一次提交；正文标记没有关系时不能提交", async () => {
    vi.mocked(call).mockImplementation(async (op: string) => (op === "entries.list" ? { items: [] } : { ref: `${J}@2` }));
    render(<EntryLabels><CorrectionPanel entry={judgment} out={out} reload={vi.fn()} /></EntryLabels>);
    fireEvent.click(screen.getByRole("button", { name: "去掉" }));
    fireEvent.change(screen.getByLabelText(/^理由/), { target: { value: "换依据" } });
    expect(screen.getByText(/还没有对应的关系/).textContent).toContain("[^1]"); // 去掉后 [^1] 悬空
    expect((screen.getByRole("button", { name: "写新版本" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("查找条目"), { target: { value: `${ART}#p4-1` } });
    fireEvent.click(await screen.findByRole("button", { name: "选用" }));
    fireEvent.change(screen.getByLabelText("作用"), { target: { value: "数据" } });
    fireEvent.change(screen.getByLabelText("原因"), { target: { value: "新读数" } });
    fireEvent.change(screen.getByLabelText("标记"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "加入" }));
    expect(screen.queryByText(/还没有对应的关系/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "写新版本" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("entry.correct", {
      id: J, reason: "换依据", relations_remove: ["rel_1"],
      relations_add: [{ predicate: "cites", target: `${ART}#p4-1`, why: "新读数", role: "数据", marker: "1" }],
    }));
  });

  it("原件：只改标题与来源档次，不需要新内容", async () => {
    vi.mocked(call).mockResolvedValue({ ref: `${ART}@2` });
    const art = { id: ART, ref: `${ART}@1`, entry_kind: "artifact", version: 1, head_version: 1, source_class: "external",
      objects: [], data: { title: "旧标题", external_tier: "web", metadata: { note: "旧" } } };
    render(<EntryLabels><CorrectionPanel entry={art} out={[]} reload={vi.fn()} /></EntryLabels>);
    fireEvent.change(screen.getByLabelText("标题"), { target: { value: "新标题" } });
    fireEvent.change(screen.getByLabelText("来源档次"), { target: { value: "peer_reviewed" } });
    fireEvent.change(screen.getByLabelText(/^理由/), { target: { value: "校对" } });
    fireEvent.click(screen.getByRole("button", { name: "写新版本" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("entry.correct", {
      id: ART, reason: "校对", title: "新标题", external_tier: "peer_reviewed",
    }));
  });
});
