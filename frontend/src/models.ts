// 本地模型与大模型（设计稿 05）：槽位状态与模型任务。工作台只自动调用本地模型；大模型只在人点击时调用。
import { useEffect, useState } from "react";
import { call } from "./api";

/* eslint-disable @typescript-eslint/no-explicit-any */

let cached: Promise<any> | null = null;
let cachedAt = 0;

// 槽位状态（同一页面里共用一次请求，30 秒内不重复取）
export function loadModels(force = false): Promise<any> {
  if (!cached || force || Date.now() - cachedAt > 30000) {
    cachedAt = Date.now();
    cached = call<any>("models.status").catch(() => null);
  }
  return cached;
}

export function useModels(): any {
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    loadModels().then((d) => alive && setData(d));
    return () => {
      alive = false;
    };
  }, []);
  return data;
}

// 提交一个模型任务（版面引擎、公式识别），等它结束；失败时抛出原因
export async function runModelJob(op: string, args: Record<string, unknown>, onState?: (s: string) => void): Promise<any> {
  const job = await call<any>(op, args);
  onState?.(job.status);
  for (;;) {
    await new Promise((r) => setTimeout(r, 1500));
    const status = await loadModels(true);
    const j = (status?.jobs ?? []).find((x: any) => x.id === job.id);
    if (!j) return job;
    onState?.(j.status);
    if (j.status === "done") return j.result;
    if (j.status === "failed") throw new Error(j.error ?? "模型任务失败");
  }
}

export const JOB_STATUS: Record<string, string> = { queued: "排队中", running: "运行中", done: "完成", failed: "失败" };
export const JOB_KIND: Record<string, string> = { layout: "版面引擎", formula: "公式识别" };
