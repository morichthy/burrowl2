import { fireEvent, render, screen } from "@testing-library/react";
import { call } from "./api";
import { ReviewBox } from "./review";

vi.mock("./api", () => ({ call: vi.fn() }));

beforeEach(() => vi.mocked(call).mockReset());

it("页面输入已变化时，复核框说明确认会清除它并列出输入；时效有效时不显示", async () => {
  vi.mocked(call).mockResolvedValue({
    kind: "page", review: "ai_generated", ai_allowed: null, head_version: 1, freshness: "inputs_changed",
    inputs: ["jdg_A", "jdg_B"], changed_inputs: [], items: [],
  });
  const { unmount } = render(<ReviewBox itemId="pg_stale" />);
  fireEvent.click(await screen.findByRole("button", { name: "复核" }));
  expect(screen.getByRole("note").textContent).toMatch(/时效会回到“有效”/);
  expect(screen.getByRole("note").textContent).toMatch(/输入清单（2 项）/);
  unmount();
  vi.mocked(call).mockResolvedValue({ kind: "page", review: "ai_generated", ai_allowed: null, head_version: 1, freshness: "valid", items: [] });
  render(<ReviewBox itemId="pg_ok" />);
  fireEvent.click(await screen.findByRole("button", { name: "复核" }));
  expect(screen.queryByRole("note")).toBeNull();
});
