import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { call } from "../api";
import { Settings } from "./Settings";

vi.mock("../api", () => ({ call: vi.fn() }));

it("两个角色独立保存命令，按各自的设置启用、测试和关闭", async () => {
  const agents = new Map(["claude", "codex", "legacy"].map((name) => [name, {
    name, command: [name, "{prompt}"], cli_type: undefined as string | undefined, available: true,
  }]));
  let values = { "inspection.inspector": "legacy", "inspection.reviewer": "" };
  vi.mocked(call).mockImplementation(async (op, args) => {
    if (op === "agent.list") return [...agents.values()];
    if (op === "agent.save_command") {
      const name = args?.agent as string;
      const agent = { name, command: args?.command as string[], cli_type: args?.cli_type as string | undefined, available: true };
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
  const page = render(<Settings />);
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
  const reviewerCommand = within(cli.closest("tr")!);
  fireEvent.change(cli, { target: { value: "custom" } });
  const override = "mcp_servers.burrowl.tools.system_status.approval_mode='approve'";
  fireEvent.change(args, { target: { value: `exec\n--skip-git-repo-check\n-c\n{codex_mcp_config}\n-c\n${override}\n{prompt}` } });
  fireEvent.click(reviewerCommand.getByRole("button", { name: "保存并测试连接" }));
  await reviewerCommand.findByText(/连接正常/);
  expect(call).toHaveBeenCalledWith("agent.test", { agent: "inspection-reviewer" });
  const saved = agents.get("inspection-reviewer");
  expect(saved?.cli_type).toBe("custom");
  expect(saved?.command).toEqual(["codex", "exec", "--skip-git-repo-check", "-c", "{codex_mcp_config}", "-c", override, "{prompt}"]);
  fireEvent.change(reviewer, { target: { value: "enabled" } });
  await waitFor(() => expect(reviewer.value).toBe("enabled"));
  expect(values).toEqual({ "inspection.inspector": "", "inspection.reviewer": "inspection-reviewer" });
  // 即使手填参数恰好等于预设，重进页面也按显式类型恢复。
  saved!.command = ["codex", "exec", "--skip-git-repo-check", "-c", "{codex_mcp_config}", "{prompt}"];
  page.unmount();
  render(<Settings />);
  // 表单可能先渲染预设，再异步加载已保存配置；等待已保存的类型真正显示。
  await waitFor(() => expect(screen.getByLabelText<HTMLSelectElement>("复核 agent CLI 类型").value).toBe("custom"));
});
