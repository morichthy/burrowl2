import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { call } from "./api";
import { EntryLabels } from "./entryLabels";
import { EntryActions, availableActions } from "./EntryActions";

vi.mock("./api", () => ({ call: vi.fn(), currentDb: () => "" }));

const ART = "art_01JC0000000000000000000003";
const J = "jdg_01JC0000000000000000000001";

const version = (id: string, n: number, extra: object = {}) => ({
  ref: `${id}@${n}`, version: n, author_kind: "human", created_at: "2026-11-13T00:00:00Z", validity: "current",
  changes: [], relations_added: [], relations_removed: [], ...extra,
});
const history = (id: string, head = 1) => ({ head_version: head, current_ref: `${id}@${head}`, versions: Array.from({ length: head }, (_, i) => version(id, i + 1)) });

beforeEach(() => {
  vi.mocked(call).mockReset();
  vi.mocked(call).mockResolvedValue({});
  window.location.hash = "";
});

const open = () => fireEvent.click(screen.getByRole("button", { name: /^操作/ }));
const choose = (name: RegExp) => { open(); fireEvent.click(screen.getByRole("menuitem", { name })); };

describe("操作菜单按条目种类给出动作", () => {
  it("判断当前版 / 已撤回 / 历史版 / 原件", () => {
    const cur = { withdrawn: null };
    const keys = (entry: object, c: object, head: boolean) => availableActions(entry, c, head).map((a) => a.key);
    expect(keys({ entry_kind: "judgment" }, cur, true)).toEqual(["correct", "relations", "withdraw", "review", "ai", "request"]);
    expect(keys({ entry_kind: "judgment" }, { withdrawn: "vst_1" }, true)).toContain("unwithdraw");
    expect(keys({ entry_kind: "judgment" }, cur, false)).toEqual(["reactivate", "withdraw", "review", "ai", "request"]);
    expect(keys({ entry_kind: "artifact" }, { retired: null }, true)).toEqual(["correct", "defect", "retire", "confirmAll", "request", "outbound"]);
    expect(keys({ entry_kind: "artifact" }, { retired: "vst_1" }, true)).not.toContain("retire");
    expect(keys({ entry_kind: "record" }, {}, true)).toEqual(["correct", "defect"]);
  });
});

describe("操作表单", () => {
  const artifact = { id: ART, entry_kind: "artifact", version: 1, head_version: 1 };
  const judgment = { id: J, entry_kind: "judgment", version: 1, head_version: 1 };
  const render_ = (entry: object, h: object) => render(<EntryLabels><EntryActions entry={entry} history={h} relOut={[]} outbound reload={vi.fn()} /></EntryLabels>);

  it("退役：自带说明框，缺理由时写明还缺什么，写了才能提交；替代原件可不选", async () => {
    render_(artifact, history(ART));
    choose(/退役本原件/);
    const submit = screen.getByRole("button", { name: "退役本原件", hidden: false }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(screen.getByText("还缺：退役理由")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("说明"), { target: { value: "已被新版取代" } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => expect(call).toHaveBeenCalledWith("entry.version_state", { id: `${ART}@1`, action: "retire", reason: "已被新版取代", replaced_by: null }));
    await waitFor(() => expect(screen.queryByText("还缺：退役理由")).toBeNull());
  });

  it("撤回：各动作的说明框互不共用", async () => {
    render_(judgment, history(J));
    choose(/撤回本版/);
    fireEvent.change(screen.getByLabelText("说明"), { target: { value: "写错对象了" } });
    fireEvent.click(screen.getByRole("button", { name: "撤回本版" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("entry.version_state", { id: `${J}@1`, action: "withdraw", reason: "写错对象了" }));
    choose(/写新版本/);
    expect((screen.getByLabelText(/^理由/) as HTMLTextAreaElement).value).toBe("");
    expect(screen.getByText("还没有改动。")).toBeTruthy();
  });

  it("更正：写了理由并改了内容才能提交，只提交改动的项，提交后跳到新版本（设计稿 11 D-18）", async () => {
    vi.mocked(call).mockResolvedValue({ id: J, ref: `${J}@2` });
    render_(judgment, history(J));
    choose(/写新版本/);
    expect((screen.getByRole("button", { name: "写新版本" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/^理由/), { target: { value: "校准" } });
    fireEvent.change(screen.getByLabelText(/^正文/), { target: { value: "新的说法" } });
    fireEvent.click(screen.getByRole("button", { name: "写新版本" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("entry.correct", { id: J, reason: "校准", text: "新的说法" }));
  });

  it("历史版本只能让这一版重新生效，并提示当前版", () => {
    render_({ ...judgment, version: 1, head_version: 2 }, history(J, 2));
    open();
    expect(screen.getAllByRole("menuitem").map((x) => x.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("让这一版重新生效")]));
    expect(screen.queryByRole("menuitem", { name: /写新版本/ })).toBeNull();
    expect(screen.getByText(/当前是第 2 版/)).toBeTruthy();
  });

  it("复核、请人复核各自只显示自己的表单（不再带一排按钮）", async () => {
    vi.mocked(call).mockImplementation(async (op: string) => (op === "review.history" ? { kind: "judgment", items: [], review: null } : {}));
    render_(judgment, history(J));
    choose(/^复核/);
    await screen.findByText("依据仍支持它");
    expect(screen.queryByRole("button", { name: "请人复核" })).toBeNull();
    expect(screen.queryByRole("button", { name: "交给 AI 复核" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    choose(/请人复核/);
    await screen.findByPlaceholderText(/要看什么/);
    expect(screen.queryByText("依据仍支持它")).toBeNull();
  });

  it("原件的外发设置在操作里，提交后调用 artifact.policy", async () => {
    render_(artifact, history(ART));
    choose(/外发设置/);
    fireEvent.click(screen.getByRole("button", { name: "标为不外发" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("artifact.policy", { artifact_id: ART, outbound: false, reason: "" }));
  });
});
