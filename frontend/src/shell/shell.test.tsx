import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { call } from "../api";
import { hrefWith, list, parseQuery, parseRoute, unlist, useUrlState } from "../router";
import { Palette, matches, type Command } from "./Palette";
import { QuickNote, openQuickNote } from "./QuickNote";
import { cursorKey, moveCursor, useShortcuts } from "./shortcuts";
import { Stamp, layerOf } from "./Stamp";
import { useTheme } from "./theme";

vi.mock("../api", () => ({ call: vi.fn(), currentDb: () => "" }));

beforeEach(() => {
  vi.mocked(call).mockReset();
  window.location.hash = "";
});

describe("网址里的筛选", () => {
  it("路由忽略问号后面的筛选，筛选单独解析", () => {
    expect(parseRoute("#/entries?kind=artifact&status=retired")).toEqual(["entries"]);
    expect(parseQuery("#/entries?kind=artifact&status=retired")).toEqual({ kind: "artifact", status: "retired" });
    expect(hrefWith("search", { q: "泵 压力", mode: "" })).toBe("#/search?q=%E6%B3%B5+%E5%8E%8B%E5%8A%9B");
    expect(list("a,b")).toEqual(["a", "b"]);
    expect(unlist(["a", "b"])).toBe("a,b");
  });

  function Probe() {
    const [f, set] = useUrlState({ kind: "judgment", q: "" });
    return (
      <div>
        <span data-testid="kind">{f.kind}</span>
        <span data-testid="q">{f.q}</span>
        <button type="button" onClick={() => set({ kind: "artifact", q: "泵" })}>改</button>
        <button type="button" onClick={() => set({ kind: "judgment" })}>回默认</button>
      </div>
    );
  }

  it("打开带筛选的网址时恢复筛选，改动写回网址，默认值不写", async () => {
    window.location.hash = "#/entries?kind=record";
    render(<Probe />);
    expect(screen.getByTestId("kind").textContent).toBe("record");
    fireEvent.click(screen.getByText("改"));
    await waitFor(() => expect(window.location.hash).toBe("#/entries?kind=artifact&q=%E6%B3%B5"));
    fireEvent.click(screen.getByText("回默认"));
    await waitFor(() => expect(window.location.hash).toBe("#/entries?q=%E6%B3%B5"));
  });
});

describe("快速跳转", () => {
  const cmd = (title: string, text: string, run = vi.fn()): Command => ({ id: title, group: "前往", title, text, run });

  it("按标题、拼音别名逐词匹配", () => {
    const c = cmd("框架页", "框架页 pages kuangjiaye kjy");
    expect(matches(c, "kjy")).toBe(true);
    expect(matches(c, "框架 pages")).toBe(true);
    expect(matches(c, "检索")).toBe(false);
  });

  it("输入名称会查条目，回车打开第一条", async () => {
    vi.mocked(call).mockImplementation(async (op: string, args?: any) => {
      if (op === "entries.list") return { items: args.kind === "judgment" ? [{ id: "jdg_01JC0000000000000000000001", preview: "warmup 减小震荡", layer: "judgment", kind: "conclusion" }] : [] };
      return [];
    });
    const onClose = vi.fn();
    render(<Palette open onClose={onClose} commands={[]} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "warmup" } });
    expect(await screen.findByText("warmup 减小震荡")).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    await waitFor(() => expect(window.location.hash).toBe("#/entry/jdg_01JC0000000000000000000001"));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("快捷键", () => {
  function Keys({ log }: { log: string[] }) {
    useShortcuts({ "g e": () => void log.push("g e"), j: () => void log.push("j"), "mod+k": () => void log.push("mod+k") });
    return <input aria-label="输入框" />;
  }

  it("连按、单键、组合键；在输入框里只响应组合键", () => {
    const log: string[] = [];
    render(<Keys log={log} />);
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "e" });
    fireEvent.keyDown(window, { key: "j" });
    fireEvent.keyDown(screen.getByLabelText("输入框"), { key: "j" });
    fireEvent.keyDown(screen.getByLabelText("输入框"), { key: "k", ctrlKey: true });
    expect(log).toEqual(["g e", "j", "mod+k"]);
  });

  it("j 移动列表光标，行内按键点击带 data-key 的元素", () => {
    const clicked = vi.fn();
    render(
      <main>
        <ul>
          <li data-nav-item="a"><button type="button" data-key="r" onClick={() => clicked("a")}>阅读</button></li>
          <li data-nav-item="b"><button type="button" data-key="r" onClick={() => clicked("b")}>阅读</button></li>
        </ul>
      </main>,
    );
    // jsdom 里 offsetParent 总是 null：模拟成可见
    for (const el of document.querySelectorAll<HTMLElement>("[data-nav-item]")) Object.defineProperty(el, "offsetParent", { get: () => document.body });
    Element.prototype.scrollIntoView = vi.fn();
    moveCursor(1);
    moveCursor(1);
    expect(document.querySelector(".nav-cursor")?.getAttribute("data-nav-item")).toBe("b");
    expect(cursorKey("r")).toBe(true);
    expect(clicked).toHaveBeenCalledWith("b");
  });
});

describe("主题", () => {
  function Two() {
    const [a, setA] = useTheme();
    const [b] = useTheme();
    return (
      <div>
        <span data-testid="a">{a}</span>
        <span data-testid="b">{b}</span>
        <button type="button" onClick={() => setA("dark")}>深色</button>
      </div>
    );
  }
  it("一处切换，其余跟着变，并写在 <html data-theme>", () => {
    render(<Two />);
    act(() => screen.getByText("深色").click());
    expect(screen.getByTestId("b").textContent).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("印与记一笔", () => {
  it("印用字和颜色同时标出三列", () => {
    render(<Stamp layer="framework" />);
    expect(screen.getByRole("img", { name: "框架" }).textContent).toBe("框");
    expect(layerOf("art_x")).toBe("original");
    expect(layerOf("jdg_x")).toBe("judgment");
    expect(layerOf("pg_x")).toBe("framework");
  });

  it("记一笔写入人的判断，依据预填当前条目，写完跳到新条目", async () => {
    vi.mocked(call).mockResolvedValue({ id: "jdg_new" });
    render(<QuickNote />);
    act(() => openQuickNote({ cites: ["art_1#p3-2"] }));
    expect((screen.getByPlaceholderText(/原件段落/) as HTMLInputElement).value).toBe("art_1#p3-2");
    fireEvent.change(screen.getByPlaceholderText("写全对象和条件，不用指代词"), { target: { value: "warmup 加长后前期更稳" } });
    fireEvent.click(screen.getByRole("button", { name: /写入/ }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("judgment.write", expect.objectContaining({ kind: "conclusion", text: "warmup 加长后前期更稳", cites: ["art_1#p3-2"] })));
    await waitFor(() => expect(window.location.hash).toBe("#/entry/jdg_new"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
