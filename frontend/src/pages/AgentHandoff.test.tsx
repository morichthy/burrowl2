import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { call } from "../api";
import { FindingGroups } from "../inspection";
import { ReviewBox } from "../review";
import { takePrompt } from "../router";
import { Agent } from "./Agent";
import { AiCheckButton } from "./Artifact";
import { Pages } from "./Pages";

vi.mock("../api", () => ({ call: vi.fn(), streamAgent: vi.fn() }));

beforeEach(() => {
  vi.mocked(call).mockReset();
  takePrompt();
});

it("抽取确认历史默认折叠，可以只撤销勾选的页", async () => {
  vi.mocked(call).mockResolvedValue({ kind: "artifact", items: [
    { id: "ex_keep", type: "verification", verdict: "confirm", unit: "p1", can_revoke: true },
    { id: "ex_undo", type: "verification", verdict: "confirm", unit: "p2", can_revoke: true },
  ] });
  render(<ReviewBox itemId="art_review" />);
  const summary = await screen.findByText("复核与变更记录（2 条）");
  expect(summary.closest("details")?.open).toBe(false);
  fireEvent.click(summary);
  fireEvent.click(screen.getByLabelText("选择撤销 p2 的抽取确认"));
  fireEvent.change(screen.getByLabelText("撤销理由"), { target: { value: "误点" } });
  fireEvent.click(screen.getByRole("button", { name: "撤销所选（1）" }));
  await waitFor(() => expect(call).toHaveBeenCalledWith("review.revoke", {
    item_id: "art_review", record_ids: ["ex_undo"], reason: "误点",
  }));
});

it("已通过 AI 复核的框架页仍能把复核任务带到 Agent 页", async () => {
  vi.mocked(call).mockResolvedValue({
    kind: "page", review: "ai_reviewed", ai_allowed: null, head_version: 2,
    items: [{ id: "rev_1", type: "review", method: "ai", verdict: "confirm", version: 2 }],
  });
  render(<ReviewBox itemId="pg_retry" />);
  fireEvent.click(await screen.findByRole("button", { name: "再次交给 AI 复核" }));
  expect(takePrompt()).toContain("pg_retry");
});

it("输入仍有效的框架页可再次综合，任务要求读取当前版本", async () => {
  vi.mocked(call).mockResolvedValue([
    { id: "pg_valid", title: "已综合的框架页", type: "synthesis", head_version: 2, review: "ai_reviewed", freshness: "valid" },
  ]);
  render(<Pages />);
  fireEvent.click(await screen.findByRole("button", { name: "再次综合" }));
  const prompt = takePrompt();
  expect(prompt).toContain("pg_valid");
  expect(prompt).toContain("当前版本");
  expect(prompt).not.toContain("输入已变化");
});

it("有旧 AI 结果的识别可以逐段重试，发起失败后按钮仍可点击", async () => {
  vi.mocked(call).mockRejectedValue(new Error("测试连接失败"));
  render(<AiCheckButton ids={["art_retry"]} items={[{ ai: { verdict: "unsure" } }]} anchor="p1-2" reload={vi.fn()} />);
  const button = screen.getByRole<HTMLButtonElement>("button", { name: "再次交给 AI 复核识别（1）" });
  fireEvent.click(button);
  await screen.findByText("测试连接失败");
  expect(button.disabled).toBe(false);
  fireEvent.click(button);
  await waitFor(() => expect(call).toHaveBeenCalledTimes(2));
  expect(call).toHaveBeenLastCalledWith("extraction.ai_check", { artifact_ids: ["art_retry"], anchors: ["p1-2"], repeat: true });
});

it("Agent 失败的运行可把任务和工作目录载回启动表单", async () => {
  vi.mocked(call).mockImplementation(async (op) => {
    if (op === "agent.list") return [{ name: "codex", available: true }];
    return [{ id: "run_failed", agent: "codex", status: "failed", data: { prompt: "重新核对", cwd: "trial" } }];
  });
  render(<Agent />);
  fireEvent.click(await screen.findByRole("button", { name: "再次使用任务" }));
  expect(screen.getByDisplayValue("重新核对")).toBeTruthy();
  expect(screen.getByDisplayValue("trial")).toBeTruthy();
  expect(vi.mocked(call).mock.calls.some(([op]) => op === "agent.start")).toBe(false);
});

it("Agent 运行列表同时显示普通运行和识别复核，并读取正在运行任务的输出", async () => {
  vi.mocked(call).mockImplementation(async (op) => {
    if (op === "agent.list") return [];
    if (op === "agent.runs") return [{ id: "run_regular", agent: "codex", status: "done", data: { prompt: "普通任务" } }];
    if (op === "models.output") return { job_id: "job_review", text: "[p3-5] CLI 正在核对" };
    return { jobs: [{ id: "job_review", kind: "ai_check", artifact_id: "art_retry", status: "running",
      progress: { total: 33, checked: 4, failed: 1, anchor: "p3-5" } }] };
  });
  render(<Agent />);
  expect(await screen.findByRole("button", { name: /普通任务/ })).toBeTruthy();
  expect(await screen.findByRole("button", { name: "识别复核" })).toBeTruthy();
  expect(await screen.findByText("[p3-5] CLI 正在核对")).toBeTruthy();
  expect(screen.getAllByText(/已处理 4\/33，失败 1，当前 p3-5/).length).toBeGreaterThan(0);
});

it("巡检发现已有复核意见时，仍能按编号再次交给复核员", async () => {
  vi.mocked(call).mockResolvedValue({ id: "run_retry" });
  render(<FindingGroups
    items={[{ id: "dec_retry", status: "open", impact: 2, data: {
      inspection_id: "insp_retry", session_id: "ses_first", review: "ai_flagged",
      reviewer: { verdict: "reject", reason: "请再核对", model: "first" },
    } }]}
    status={{ latest: { id: "insp_retry", status: "done" }, reviewer: { available: true, terminal_available: true }, review_ai: "all" }}
    reload={vi.fn()}
  />);
  fireEvent.click(screen.getByRole("button", { name: "再次交给复核员" }));
  await waitFor(() => expect(call).toHaveBeenCalledWith("inspection.start", {
    inspection_id: "insp_retry", role: "reviewer", finding_ids: ["dec_retry"],
  }));
  fireEvent.click(screen.getByRole("button", { name: "在终端再次复核" }));
  await waitFor(() => expect(window.location.hash).toBe("#/agent/run_retry"));
  expect(call).toHaveBeenCalledWith("inspection.start", {
    inspection_id: "insp_retry", role: "reviewer", finding_ids: ["dec_retry"], terminal: true,
  });
  window.location.hash = "";
});
