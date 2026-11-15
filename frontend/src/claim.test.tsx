import { render } from "@testing-library/react";
import { CiteGroups, groupCites, type ClaimCite } from "./claim";
import { foldPoints } from "./pages/Graph";

const A = "art_01JC0000000000000000000001";
const B = "art_01JC0000000000000000000002";
const cite = (id: string, ref: string, marker?: string, label?: string): ClaimCite => ({ id, ref, marker, label, phrase: "依据" });

describe("论断的依据（设计稿 16 D-12）", () => {
  it("同一份原件的多个段落收在一组，组内按编号排", () => {
    const groups = groupCites([
      cite("r1", `${A}@1#seg-2`, "2"), cite("r2", `${B}@1#seg-0`, "1"), cite("r3", `${A}@1#seg-0`, "1"), cite("r4", "jdg_01JC0000000000000000000009@1", "3"),
    ]);
    expect(groups.map((g) => g.map((c) => c.id))).toEqual([["r3", "r1"], ["r2"], ["r4"]]);
  });

  it("一组一张卡：原件名在标题，每行是编号和段落", () => {
    const { container } = render(<CiteGroups cites={[
      cite("r1", `${A}@1#seg-0`, "2", "实验结果 results.json · 段落 0"), cite("r2", `${A}@1#seg-1`, "2", "实验结果 results.json · 段落 1"),
    ]} />);
    expect(container.querySelectorAll(".chain-card")).toHaveLength(1);
    expect(container.querySelector(".chain-card-head")?.textContent).toContain("实验结果 results.json");
    expect([...container.querySelectorAll(".cite-row")].map((x) => x.textContent)).toEqual(["[2]段落 0", "[2]段落 1"]);
    expect(container.querySelector("#rel-r2")).not.toBeNull();
  });

  it("没有名称时按锚点写出页与段落", () => {
    const { container } = render(<CiteGroups cites={[cite("a", `${A}@1#p2-13`, "1"), cite("b", `${A}@1#seg-4`, "2")]} />);
    expect([...container.querySelectorAll(".cite-seg")].map((x) => x.textContent)).toEqual(["第 2 页 · 段落 13", "段落 4"]);
  });
});

describe("关系图的要点折叠（设计稿 16 D-13）", () => {
  const points = Array.from({ length: 5 }, (_, i) => ({ id: `pg_${i}`, type: "point", label: `要点 ${i}` }));
  const nodes = [{ id: A, type: "artifact" }, ...points, { id: "pg_x", type: "point" }];
  const edges = [
    ...points.map((p) => ({ id: `d${p.id}`, source: p.id, target: A, predicate: "derived_from", rel: "derived_from", count: 1 })),
    { id: "dx", source: "pg_x", target: B, predicate: "derived_from", rel: "derived_from", count: 1 },
  ];
  it("一份原件的要点不少于 4 条时收成一个节点，边合并", () => {
    const out = foldPoints(nodes, edges, new Set());
    const fold = out.nodes.find((n: any) => n.fold === A);
    expect(fold.label).toBe("要点 ×5");
    expect(out.nodes.map((n: any) => n.id)).toEqual([A, "pg_x", `fold:${A}`]);
    expect(out.edges.filter((e: any) => e.source === `fold:${A}`)).toHaveLength(1);
    expect(out.edges.find((e: any) => e.source === `fold:${A}`).count).toBe(5);
  });
  it("展开的原件不折叠", () => {
    expect(foldPoints(nodes, edges, new Set([A])).nodes).toHaveLength(nodes.length);
  });
});
