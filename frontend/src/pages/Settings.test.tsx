import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { call } from "../api";
import { Settings } from "./Settings";

vi.mock("../api", () => ({ call: vi.fn() }));

it("两种巡检角色共用 Agent 列表，编辑和测试只更新所选配置", async () => {
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
    if (op === "models.check") return { ok: true, detail: "测试通过" };
    if (op === "settings.set") values = { ...values, ...(args?.values as typeof values) };
    if (op === "agent.test") return { ok: true, steps: [] };
    return {};
  });
  const page = render(<Settings />);
  await waitFor(() => {
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "巡检员 agent（辅）" });
    expect(select.value).toBe("legacy");
    expect(select.disabled).toBe(false);
  });
  const inspector = screen.getByRole<HTMLSelectElement>("combobox", { name: "巡检员 agent（辅）" });
  const reviewer = screen.getByRole<HTMLSelectElement>("combobox", { name: "复核员 agent（主）" });
  for (const select of [inspector, reviewer]) {
    expect(within(select).getAllByRole("option").map((item) => item.textContent)).toEqual(["不选，只复制领取提示", "claude", "codex", "legacy"]);
  }

  fireEvent.change(reviewer, { target: { value: "legacy" } });
  await waitFor(() => expect(reviewer.value).toBe("legacy"));
  expect(inspector.value).toBe("legacy");
  fireEvent.change(inspector, { target: { value: "" } });
  await waitFor(() => expect(inspector.value).toBe(""));
  expect(reviewer.value).toBe("legacy");
  expect(call).not.toHaveBeenCalledWith("agent.save_command", expect.anything());

  const command = screen.getByLabelText<HTMLInputElement>("legacy 命令");
  const args = screen.getByLabelText<HTMLTextAreaElement>("legacy 启动参数（每行一项）");
  const editor = within(command.closest("tr")!);
  fireEvent.change(command, { target: { value: "codex" } });
  const override = "mcp_servers.burrowl.tools.system_status.approval_mode='approve'";
  fireEvent.change(args, { target: { value: `exec\n--skip-git-repo-check\n-c\n{codex_mcp_config}\n-c\n${override}\n{prompt}` } });
  fireEvent.click(editor.getByRole("button", { name: "保存并测试连接" }));
  await editor.findByText(/连接正常/);
  expect(call).toHaveBeenCalledWith("agent.test", { agent: "legacy" });
  const saved = agents.get("legacy");
  expect(saved?.command).toEqual(["codex", "exec", "--skip-git-repo-check", "-c", "{codex_mcp_config}", "-c", override, "{prompt}"]);

  for (const name of ["AGY-巡检", "AGY-复核"]) {
    fireEvent.click(await screen.findByRole("button", { name: "新增 Agent" }));
    fireEvent.change(screen.getByLabelText("新 Agent 命令"), { target: { value: "agy" } });
    fireEvent.change(screen.getByLabelText("新 Agent 名称"), { target: { value: name } });
    fireEvent.change(screen.getByLabelText("新 Agent 启动参数（每行一项）"), { target: { value: "--print\n{prompt}" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新 Agent 设置" }));
    await within(reviewer).findByRole("option", { name });
    expect(agents.get(name)?.command).toEqual(["agy", "--print", "{prompt}"]);
  }
  expect(values).toEqual({ "inspection.inspector": "", "inspection.reviewer": "legacy" });

  const llm = within(screen.getByLabelText("大模型接口地址").closest("tr")!);
  fireEvent.change(llm.getByLabelText("大模型接口地址"), { target: { value: "https://example.test/v1" } });
  fireEvent.change(llm.getByLabelText("模型名"), { target: { value: "vision-test" } });
  fireEvent.click(llm.getByRole("button", { name: "保存并测试连接" }));
  await llm.findByText("连接正常：测试通过");
  expect(call).toHaveBeenCalledWith("settings.set", { values: { "models.llm_url": "https://example.test/v1", "models.llm_model": "vision-test" } });
  expect(call).toHaveBeenCalledWith("models.check", { slot: "llm" });
  page.unmount();
  render(<Settings />);
  expect((await screen.findByLabelText<HTMLTextAreaElement>("legacy 启动参数（每行一项）")).value)
    .toBe(saved!.command.slice(1).join("\n"));
});
