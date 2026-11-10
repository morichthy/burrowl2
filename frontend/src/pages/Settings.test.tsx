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

it("Agent 配置可按模板连续新增，也可改名和删除", async () => {
  const presets = {
    claude: ["claude", "-p", "{prompt}", "--mcp-config", "{mcp_config}"],
    codex: ["codex", "exec", "--skip-git-repo-check", "-c", "{codex_mcp_config}", "{prompt}"],
  };
  let agents = Object.entries(presets).map(([name, command]) => ({ name, command, available: true }));
  vi.mocked(call).mockReset();
  vi.mocked(call).mockImplementation(async (op, args: any) => {
    if (op === "agent.list") return agents;
    if (op === "agent.save_command") {
      const agent = { name: args.agent, command: args.command, cli_type: args.cli_type, available: true };
      agents = args.previous
        ? agents.map((a) => (a.name === args.previous ? agent : a))
        : [...agents.filter((a) => a.name !== args.agent), agent];
      return agent;
    }
    if (op === "agent.delete") {
      agents = agents.filter((a) => a.name !== args.agent);
      return { agent: args.agent, deleted: true };
    }
    if (op === "settings.get") return { values: {}, agent_cli_presets: presets };
    return {};
  });
  render(<Settings />);
  fireEvent.click(await screen.findByRole("button", { name: "新增 Agent" }));
  fireEvent.click(screen.getByRole("button", { name: "新增 Agent" }));
  const names = screen.getAllByLabelText<HTMLInputElement>("新 Agent 名称");
  expect(names.map((input) => input.value)).toEqual(["claude-2", "claude-3"]);
  expect(screen.getAllByLabelText<HTMLTextAreaElement>("新 Agent 启动参数（每行一项）")[0].value).toBe(presets.claude.slice(1).join("\n"));
  fireEvent.change(names[1], { target: { value: "codex" } });
  expect(screen.getByText("这个名称已存在")).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button", { name: "放弃新增" })[1]);
  fireEvent.click(screen.getByRole("button", { name: "保存新 Agent 设置" }));
  await screen.findByLabelText("claude-2 命令");
  expect(call).toHaveBeenCalledWith("agent.save_command", { agent: "claude-2", command: presets.claude, cli_type: "claude" });

  fireEvent.change(screen.getByLabelText("codex 名称"), { target: { value: "codex-巡检" } });
  fireEvent.click(screen.getByRole("button", { name: "保存codex 设置" }));
  await screen.findByLabelText("codex-巡检 命令");
  expect(call).toHaveBeenCalledWith("agent.save_command", { agent: "codex-巡检", command: presets.codex, previous: "codex" });

  vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "删除claude" }));
  await waitFor(() => expect(screen.queryByLabelText("claude 命令")).toBeNull());
  expect(agents.map((a) => a.name)).toEqual(["codex-巡检", "claude-2"]);
});

it("大模型可以选择已保存的 Agent CLI，保存后才能试连", async () => {
  let values = { "models.llm": "openai", "models.llm_agent": "" };
  vi.mocked(call).mockReset();
  vi.mocked(call).mockImplementation(async (op, args) => {
    if (op === "agent.list") return [{ name: "视觉模型", command: ["codex", "{prompt}"], available: true }];
    if (op === "settings.get") return { values };
    if (op === "settings.set") values = { ...values, ...(args?.values as typeof values) };
    if (op === "models.check") return { ok: true, detail: "测试通过" };
    return {};
  });
  render(<Settings />);
  const model = screen.getByRole<HTMLSelectElement>("combobox", { name: "大模型" });
  await waitFor(() => expect(model.value).toBe("openai"));
  fireEvent.change(model, { target: { value: "agent" } });
  const save = screen.getByRole<HTMLButtonElement>("button", { name: "确认保存" });
  expect(save.disabled).toBe(true);
  const choice = screen.getByRole("combobox", { name: "大模型使用的 Agent CLI" });
  fireEvent.change(choice, { target: { value: "视觉模型" } });
  expect(screen.queryByLabelText("大模型接口地址")).toBeNull();
  fireEvent.click(save);
  await screen.findByText("发送一条测试文字，不使用原件");
  const test = within(screen.getByText("发送一条测试文字，不使用原件").parentElement!);
  fireEvent.click(test.getByRole("button", { name: "测试连接" }));
  await test.findByText("连接正常：测试通过");
  expect(call).toHaveBeenCalledWith("settings.set", { values: { "models.llm": "agent", "models.llm_agent": "视觉模型" } });
  expect(call).toHaveBeenCalledWith("models.check", { slot: "llm" });
});
