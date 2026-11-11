import { describe, expect, it } from "vitest";
import { normalizeMath } from "./mathText";

describe("normalizeMath", () => {
  it("把 \\[ \\] 换成块公式，\\( \\) 换成行内公式", () => {
    expect(normalizeMath("前 \\[ \\frac{1}{2} \\] 后")).toBe("前 \n$$\n\\frac{1}{2}\n$$\n 后");
    expect(normalizeMath("设 \\(x_t\\) 为")).toBe("设 $x_t$ 为");
  });
  it("多行公式与多处公式", () => {
    expect(normalizeMath("\\[\na=b\n\\]\n\\(c\\)")).toBe("\n$$\na=b\n$$\n\n$c$");
  });
  it("代码里不改", () => {
    const code = "`\\(x\\)` 和\n```\n\\[y\\]\n```";
    expect(normalizeMath(code)).toBe(code);
  });
  it("没有分隔符时原样返回", () => {
    expect(normalizeMath("$a$ 与 $$b$$")).toBe("$a$ 与 $$b$$");
  });
});
