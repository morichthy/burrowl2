// 阅读器与工作台代码隔离（设计稿 03 D-05）：src/viewers/<名称>/ 只能 import 契约、本目录内的文件和第三方包。
// 与后端用 import-linter 检查分层是同一个思路。
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");
const VIEWERS = join(SRC, "viewers");
const CONTRACT = join(SRC, "reader", "contract");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(name) ? [p] : [];
  });
}

function imports(file: string): string[] {
  const text = readFileSync(file, "utf-8");
  return [...text.matchAll(/(?:import|export)\s[^"']*?from\s+["']([^"']+)["']|import\(\s*["']([^"']+)["']\s*\)|import\s+["']([^"']+)["']/g)].map(
    (m) => m[1] ?? m[2] ?? m[3],
  );
}

export function violations(): string[] {
  const out: string[] = [];
  for (const viewer of readdirSync(VIEWERS)) {
    const root = join(VIEWERS, viewer);
    if (!statSync(root).isDirectory()) continue;
    for (const file of files(root)) {
      for (const spec of imports(file)) {
        if (!spec.startsWith(".")) continue; // 第三方包
        const target = resolve(dirname(file), spec.replace(/\?.*$/, ""));
        const inside = target === root || target.startsWith(root + sep);
        if (!inside && target.replace(/\.(ts|tsx)$/, "") !== CONTRACT) out.push(`${relative(SRC, file)} → ${spec}`);
      }
    }
  }
  return out;
}

describe("阅读器隔离", () => {
  it("阅读器只依赖契约、自己目录内的文件和第三方包", () => {
    expect(violations()).toEqual([]);
  });

  it("每个阅读器目录都有 README.md（来源、版本、许可证、能力、限制）", () => {
    const missing = readdirSync(VIEWERS).filter((v) => statSync(join(VIEWERS, v)).isDirectory() && !readdirSync(join(VIEWERS, v)).includes("README.md"));
    expect(missing).toEqual([]);
  });
});
