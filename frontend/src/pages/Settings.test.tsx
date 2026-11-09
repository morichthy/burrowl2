import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { call } from "../api";
import { Settings } from "./Settings";

vi.mock("../api", () => ({ call: vi.fn() }));

it("两个角色独立保存命令，按各自的设置启用、测试和关闭", async () => {
  const agents = new Map(["claude", "codex", "legacy"].map((name) => [name, {
    name, command: [name, "{prompt}"], available: true,
  }]));
  let values = { "inspection.inspector": "legacy", "inspection.reviewer": "" };
  vi.mocked(call).mockImplementation(async (op, args) => {
    if (op === "agent.list") return [...agents.values()];
    if (op === "agent.save_command") {
      const name = args?.agent as string;
      const agent = { name, command: args?.command as string[], available: true };
      agents.set(name, agent);
      return agent;
    }
    if (op === "settings.get") return { values, agent_cli_presets: {
      claude: ["claude", "-p", "{prompt}", "--mcp-config", "{mcp_config}"],
      codex: ["codex", "exec", "--skip-git-repo-check", "-c", "{codex_mcp_config}", "{prompt}"],
    } };
    if (op === "settings.set") values = { ...values, ...(args?.values as typeof values) };
    if (op === "agent.test") return { ok: true, steps: [] };
    return {};
  });
  render(<Settings />);
  await waitFor(() => {
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "巡检员 agent（辅）" });
    expect(select.value).toBe("enabled");
    expect(select.disabled).toBe(false);
  });
  const inspector = screen.getByRole<HTMLSelectElement>("combobox", { name: "巡检员 agent（辅）" });
  const reviewer = screen.getByRole("combobox", { name: "复核员 agent（主）" }) as HTMLSelectElement;
  expect(inspector.value).toBe("enabled");
  expect(within(inspector).getAllByRole("option").map((item) => item.textContent)).toEqual(["不选，只复制领取提示", "使用巡检 agent"]);
  expect(within(reviewer).getAllByRole("option").map((item) => item.textContent)).toEqual(["不选，只复制领取提示", "使用复核 agent"]);
  expect(screen.queryByText("新增自定义 agent")).toBeNull();

  fireEvent.change(inspector, { target: { value: "" } });
  await waitFor(() => expect(inspector.value).toBe(""));
  expect(agents.get("inspection-inspector")?.command).toEqual(["legacy", "{prompt}"]);

  const cli = screen.getByLabelText<HTMLSelectElement>("复核 agent CLI 类型");
  const args = screen.getByLabelText<HTMLTextAreaElement>("复核 agent 启动参数（每行一项）");
  expect(cli.value).toBe("codex");
  fireEvent.change(cli, { target: { value: "claude" } });
  expect(args.value).toContain("--mcp-config");
  fireEvent.change(cli, { target: { value: "codex" } });
  expect(args.value).toBe("exec\n--skip-git-repo-check\n-c\n{codex_mcp_config}\n{prompt}");
  expect(call).not.toHaveBeenCalledWith("agent.save_command", expect.objectContaining({ agent: "inspection-reviewer" }));
  fireEvent.click(screen.getByRole("button", { name: "保存复核 agent 设置" }));
  await screen.findByText("已保存", { selector: "[role=status]" });
  fireEvent.change(reviewer, { target: { value: "enabled" } });
  await waitFor(() => expect(reviewer.value).toBe("enabled"));
  const reviewerRow = reviewer.closest("tr")!;
  fireEvent.click(within(reviewerRow).getByRole("button", { name: "测试连接" }));
  await waitFor(() => expect(call).toHaveBeenCalledWith("agent.test", { agent: "inspection-reviewer" }));
  expect(agents.get("inspection-reviewer")?.command).toEqual(["codex", "exec", "--skip-git-repo-check", "-c", "{codex_mcp_config}", "{prompt}"]);
  expect(values).toEqual({ "inspection.inspector": "", "inspection.reviewer": "inspection-reviewer" });
});
