import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { call } from "./api";
import { EntryLabels } from "./entryLabels";
import { EntryPicker } from "./EntryPicker";
import { RelationEditor } from "./RelationEditor";

vi.mock("./api", () => ({ call: vi.fn(), currentDb: () => "" }));

const J = "jdg_01JC0000000000000000000001";
const OTHER = "jdg_01JC0000000000000000000002";
const ART = "art_01JC0000000000000000000003";

beforeEach(() => {
  vi.mocked(call).mockReset();
  window.location.hash = "";
});

describe("条目选择器", () => {
  it("按文字查找后可以选用；原件可以展开选到段落", async () => {
    vi.mocked(call).mockImplementation(async (op: string, args?: any) => {
      if (op === "entries.list") return { items: args.kind === "artifact" ? [{ id: ART, preview: "泵试验报告" }] : [] };
      if (op === "artifact.segments") return [{ anchor: "p3-2", text: "出口压力 0.82 MPa" }];
      return {};
    });
    const picked: string[] = [];
    render(<EntryLabels><EntryPicker onPick={(r) => picked.push(r)} /></EntryLabels>);
    fireEvent.change(screen.getByLabelText("查找条目"), { target: { value: "泵" } });
    await screen.findByText("泵试验报告");
    fireEvent.click(screen.getByRole("button", { name: "选段落…" }));
    fireEvent.click(await screen.findByRole("button", { name: "引用此段" }));
    expect(picked).toEqual([`${ART}#p3-2`]);
  });

  it("直接粘贴 ID 即可选用", async () => {
    const picked: string[] = [];
    render(<EntryLabels><EntryPicker onPick={(r) => picked.push(r)} /></EntryLabels>);
    vi.mocked(call).mockResolvedValue({});
    fireEvent.change(screen.getByLabelText("查找条目"), { target: { value: OTHER } });
    fireEvent.click(await screen.findByRole("button", { name: "选用" }));
    expect(picked).toEqual([OTHER]);
  });
});

describe("关系编辑器", () => {
  const entry = { id: J, entry_kind: "judgment", version: 1, head_version: 1 };
  const out = [{ id: "rel_1", predicate: "cites", other: ART, origin: "judgment", phrase: "依据", qualifiers: {} }];

  it("移除一条出边并加一条关系，一次提交成新版本", async () => {
    vi.mocked(call).mockImplementation(async (op: string, args?: any) => {
      if (op === "entries.list") return { items: args.kind === "judgment" ? [{ id: OTHER, preview: "另一条结论", kind: "conclusion" }] : [] };
      if (op === "entry.relate") return { ref: `${J}@2` };
      return {};
    });
    const reload = vi.fn();
    render(<EntryLabels><RelationEditor entry={entry} out={out} reload={reload} /></EntryLabels>);
    fireEvent.click(screen.getByRole("button", { name: "移除" }));
    fireEvent.click(screen.getByText("加一条关系"));
    fireEvent.change(screen.getByLabelText("查找条目"), { target: { value: "另一" } });
    fireEvent.click((await screen.findAllByRole("button", { name: "选用" }))[0]);
    fireEvent.click(screen.getByRole("button", { name: "加入待提交" }));
    fireEvent.change(screen.getByPlaceholderText(/理由/), { target: { value: "换依据并补佐证" } });
    fireEvent.click(screen.getByRole("button", { name: /^提交（/ }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("entry.relate", {
      id: J, reason: "换依据并补佐证", add: [{ predicate: "supports", target: OTHER }], remove: ["rel_1"],
    }));
    await waitFor(() => expect(window.location.hash).toBe(`#/entry/${encodeURIComponent(`${J}@2`)}`));
  });

  it("让别的判断指向本条：在那条判断上出新版本", async () => {
    vi.mocked(call).mockImplementation(async (op: string, args?: any) => {
      if (op === "entries.list") return { items: args.kind === "judgment" ? [{ id: OTHER, preview: "另一条结论", kind: "conclusion" }] : [] };
      return {};
    });
    render(<EntryLabels><RelationEditor entry={entry} out={[]} reload={vi.fn()} /></EntryLabels>);
    fireEvent.click(screen.getByText("加一条关系"));
    fireEvent.change(screen.getByLabelText("方向"), { target: { value: "in" } });
    fireEvent.change(screen.getByLabelText("关系"), { target: { value: "opposes" } });
    fireEvent.change(screen.getByLabelText("查找条目"), { target: { value: "另一" } });
    fireEvent.click((await screen.findAllByRole("button", { name: "选用" }))[0]);
    fireEvent.click(screen.getByRole("button", { name: "加入待提交" }));
    fireEvent.change(screen.getByPlaceholderText(/理由/), { target: { value: "有相反测量" } });
    fireEvent.click(screen.getByRole("button", { name: /^提交（/ }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("entry.relate", {
      id: OTHER, reason: "有相反测量", add: [{ predicate: "opposes", target: J }],
    }));
  });

  it("历史版本不显示编辑，非判断不渲染", () => {
    const { container, rerender } = render(<RelationEditor entry={{ ...entry, version: 1, head_version: 2 }} out={[]} reload={vi.fn()} />);
    expect(container.textContent).toContain("回到当前版");
    rerender(<RelationEditor entry={{ ...entry, entry_kind: "artifact" }} out={[]} reload={vi.fn()} />);
    expect(container.textContent).toBe("");
  });
});

describe("原件退役入口", () => {
  it("退役区有自己的理由输入框，写了理由才能点，替代原件可不填", async () => {
    const { VersionPanel } = await import("./pages/Entries");
    vi.mocked(call).mockResolvedValue({});
    const entry = { id: ART, entry_kind: "artifact", version: 1, head_version: 1 };
    const history = { head_version: 1, current_ref: `${ART}@1`, versions: [{ ref: `${ART}@1`, version: 1, author_kind: "human", created_at: "2026-11-13T00:00:00Z", validity: "current", changes: [], relations_added: [], relations_removed: [] }] };
    render(<EntryLabels><VersionPanel entry={entry} history={history} reload={vi.fn()} /></EntryLabels>);
    const button = screen.getByRole("button", { name: "退役本原件" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("退役理由"), { target: { value: "已被新版取代" } });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(call).toHaveBeenCalledWith("entry.version_state", { id: `${ART}@1`, action: "retire", reason: "已被新版取代", replaced_by: null }));
  });
});
