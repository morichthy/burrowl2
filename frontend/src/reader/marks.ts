// 把抽取层与账本的段落统计转成阅读器的标注（设计稿 03 D-03 ②、D-04）。纯函数，可单独测试。
import type { Mark } from "./contract";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function buildMarks(layer: any, segments: any[], stats: Record<string, any>, anchor: string): Mark[] {
  const units = new Map<string, any>((layer?.units ?? []).map((u: any) => [u.unit, u]));
  const groups = new Map<string, { unit: string; block: number; segs: any[] }>();
  for (const s of segments) {
    const block = s.block ?? s.ordinal;
    const key = `${s.unit}:${block}`;
    const g = groups.get(key) ?? { unit: s.unit, block, segs: [] as any[] };
    g.segs.push(s);
    groups.set(key, g);
  }
  const out: Mark[] = [];
  for (const [key, g] of groups) {
    const unit = units.get(g.unit) ?? {};
    const block = s0(unit.blocks)?.[g.block];
    let cited = 0;
    let read = 0;
    for (const s of g.segs) {
      const st = stats[s.anchor];
      if (!st) continue;
      read += (st.reads ?? []).length;
      for (const list of Object.values((st.citations ?? {}) as Record<string, any[]>)) cited += list.length;
    }
    const fidelity = g.segs[0]?.fidelity ?? unit.fidelity;
    out.push({
      key,
      anchors: g.segs.map((s) => s.anchor),
      unit: g.unit,
      block: g.block,
      page: unit.page,
      box: block?.box,
      text: g.segs.map((s) => s.text).join("\n"),
      type: block?.type ?? "paragraph",
      state: {
        cited,
        read,
        low: ["ocr", "ai"].includes(fidelity) && !g.segs[0]?.verified,
        anchor: !!anchor && g.segs.some((s) => s.anchor === anchor),
      },
    });
  }
  return out;
}

function s0(blocks: any[] | undefined): any[] | undefined {
  return Array.isArray(blocks) ? blocks : undefined;
}
