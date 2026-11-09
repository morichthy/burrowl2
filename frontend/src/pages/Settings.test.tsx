import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { call } from "../api";
import { Settings } from "./Settings";

vi.mock("../api", () => ({ call: vi.fn() }));

it("从巡检区直接新增自定义 agent，保存后两个角色都可选择", async () => {
  const agents = ["claude", "codex"].map((name) => ({
    name, command: [name, "{prompt}"], executable: name, default_executable: name, available: true,
  }));
  vi.mocked(call).mockImplementation(async (op, args) => {
    if (op === "agent.list") return [...agents];
    if (op === "agent.save_command") {
      const [executable, ...parameters] = args?.command as string[];
      const agent = {
        name: args?.agent as string, command: [executable, ...parameters],
        executable, default_executable: executable, available: true,
      };
      agents.push(agent);
      return agent;
    }
    if (op === "settings.get") return { values: {} };
    return {};
  });
  render(<Settings />);
  const editor = within(await screen.findByRole("group", { name: "新增自定义 agent" }));
  fireEvent.change(editor.getByLabelText("名称"), { target: { value: "自定义" } });
  fireEvent.change(editor.getByLabelText("可执行文件"), { target: { value: "my-agent" } });
  fireEvent.click(editor.getByRole("button", { name: "保存命令" }));
  await waitFor(() => {
    for (const name of ["巡检员 agent（辅）", "复核员 agent（主）"]) {
      const select = screen.getByRole("combobox", { name });
      expect(within(select).getByRole("option", { name: "自定义" })).toBeTruthy();
    }
  });
  expect(call).toHaveBeenCalledWith("agent.save_command", { agent: "自定义", command: ["my-agent", "{prompt}"] });
});
