import { fireEvent, render, screen } from "@testing-library/react";
import { call } from "../api";
import { Reading, ReadingCard } from "./Reading";

vi.mock("../api", () => ({ call: vi.fn() }));

beforeEach(() => vi.mocked(call).mockReset());

const session = {
  session_id: "ses_A", actor: "ai:claude", purpose: "核对泵压", searches: 2, artifacts_read: 1, notes: 2, findings: 1, has_handoff: true,
  last_at: "2026-11-13T01:00:00.000Z",
};

it("首页卡片列出会话的目的、用量，并链到详情", async () => {
  vi.mocked(call).mockResolvedValue([session]);
  render(<ReadingCard />);
  const link = (await screen.findByText("核对泵压")).closest("a");
  expect(link?.getAttribute("href")).toBe("#/reading/ses_A");
  expect(screen.getByText(/读原件 1 · 检索 2 · 认知 1 · 有 handoff/)).toBeTruthy();
});

it("详情页：handoff 点击才展开；没读原文的命中单独标明", async () => {
  vi.mocked(call).mockResolvedValue({
    session_id: "ses_A", actor: "ai:claude", started_at: "2026-11-13T00:00:00.000Z", last_at: "2026-11-13T01:00:00.000Z",
    purpose: "核对泵压", findings: [{ text: "出口压力 0.82", refs: [] }], handoff: "# 交接内容XYZ", handoff_source: "HANDOFF.md",
    handoff_at: "2026-11-13T01:00:00.000Z", notes: [], read: [], returned: [{ id: "art_x", at: "t", read: false }],
    searches: [], written: [], refs_in_findings: [],
  });
  render(<Reading sessionId="ses_A" />);
  expect(await screen.findByText("出口压力 0.82")).toBeTruthy();
  expect(screen.getByText("参考过")).toBeTruthy();
  expect(screen.queryByText("交接内容XYZ")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "阅读 handoff" }));
  expect(await screen.findByText("交接内容XYZ")).toBeTruthy();
});

it("AI 登记了 handoff 文件路径时，点击阅读实时读文件，读不到退回快照", async () => {
  const base = {
    session_id: "ses_C", actor: "ai:x", started_at: "2026-11-13T00:00:00.000Z", last_at: "2026-11-13T00:00:00.000Z", purpose: "p",
    findings: [], handoff: "旧快照内容", handoff_source: "D:/w/HANDOFF.md", handoff_at: "2026-11-13T00:00:00.000Z", notes: [], read: [],
    returned: [], searches: [], written: [], refs_in_findings: [],
  };
  let live: any = { available: true, path: "D:/w/HANDOFF.md", text: "文件里的最新内容", modified_at: "2026-11-13T02:00:00.000Z" };
  vi.mocked(call).mockImplementation(async (name: string) => (name === "reading.get" ? base : live));
  render(<Reading sessionId="ses_C" />);
  fireEvent.click(await screen.findByRole("button", { name: "阅读 handoff" }));
  expect(await screen.findByText("文件里的最新内容")).toBeTruthy();
  expect(call).toHaveBeenCalledWith("reading.handoff_file", { session_id: "ses_C" });
  live = { available: false, path: "D:/w/HANDOFF.md", reason: "文件不存在或不可访问" };
  fireEvent.click(screen.getByRole("button", { name: "收起 handoff" }));
  fireEvent.click(screen.getByRole("button", { name: "阅读 handoff" }));
  expect(await screen.findByText("旧快照内容")).toBeTruthy();
  expect(screen.getByText(/实时读取失败：文件不存在或不可访问/)).toBeTruthy();
});

it("没有 handoff 时给出让 AI 补一份的提示按钮", async () => {
  vi.mocked(call).mockResolvedValue({
    session_id: "ses_B", actor: "ai:x", started_at: "2026-11-13T00:00:00.000Z", last_at: "2026-11-13T00:00:00.000Z", purpose: null,
    findings: [], handoff: null, handoff_source: null, handoff_at: null, notes: [], read: [], returned: [], searches: [], written: [], refs_in_findings: [],
  });
  render(<Reading sessionId="ses_B" />);
  expect(await screen.findByRole("button", { name: "复制提示，让 AI 补一份" })).toBeTruthy();
  expect(screen.getByText("（AI 还没写这次阅读的目的）")).toBeTruthy();
});
