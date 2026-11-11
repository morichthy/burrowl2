import { describe, expect, it } from "vitest";
import { plainText, replayFilter } from "./AgentTerminal";
import { resolveTerminalTheme, TERMINAL_THEMES } from "./terminalTheme";

describe("replayFilter", () => {
  it("去掉备用屏幕与鼠标上报，其余序列保留", () => {
    const [out] = replayFilter("", "a\x1b[?1049hb\x1b[?1000;1006hc\x1b[?25ld\x1b[31me");
    expect(out).toBe("abc\x1b[?25ld\x1b[31me");
  });
  it("被切成两段的序列也能处理", () => {
    const [first, carry] = replayFilter("", "x\x1b[?10");
    expect(first).toBe("x");
    const [second, rest] = replayFilter(carry, "49hy");
    expect(second + rest).toBe("y");
  });
  it("多个模式只去掉要去掉的", () => {
    expect(replayFilter("", "\x1b[?25;1049h")[0]).toBe("\x1b[?25h");
  });
});

describe("plainText", () => {
  it("去掉颜色、光标控制，保留文字", () => {
    expect(plainText("\x1b[31m红\x1b[0m字\x1b]0;标题\x07\n第二行")).toBe("红字\n第二行");
  });
  it("回车覆盖的进度行只留最后一版", () => {
    expect(plainText("10%\r50%\r100%\r\n完成")).toBe("100%\n完成");
  });
});

describe("resolveTerminalTheme", () => {
  it("每套配色都有前景、背景和 16 色", () => {
    for (const [key] of TERMINAL_THEMES) {
      const t = resolveTerminalTheme(key, true);
      expect(t.background && t.foreground && t.brightBlack && t.brightWhite).toBeTruthy();
    }
  });
  it("跟随工作台时按页面深浅选择", () => {
    expect(resolveTerminalTheme("auto", false).background).toBe("#ffffff");
    expect(resolveTerminalTheme("auto", true).background).toBe("#0d1117");
  });
});
