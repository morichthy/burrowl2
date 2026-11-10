// 首页、Agent 页和原件页共用任务状态，区分排队、逐块核对和已结束。
export type ModelJob = {
  id: string;
  kind: string;
  artifact_id: string;
  status: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  error?: string;
  progress?: { total: number; checked: number; failed: number; model?: string; anchor?: string;
    item_started_at?: string; last_error?: string };
};

export function modelJobLabel(kind: string): string {
  return ({ ai_check: "识别复核", formula: "公式识别", layout: "版面抽取" } as Record<string, string>)[kind] ?? kind;
}

export function modelJobStatus(job: ModelJob): string {
  if (job.status === "queued") return "排队中";
  const progress = job.progress;
  const done = progress ? ` · 已处理 ${progress.checked}/${progress.total}${progress.failed ? `，失败 ${progress.failed}` : ""}` : "";
  if (job.status === "failed") return `任务失败${done}`;
  if (job.status === "cancelled") return `已停止${done}`;
  if (job.status === "cancelling") return `停止中${done}`;
  if (job.status === "done") return `已结束${done}`;
  if (job.kind !== "ai_check") return "运行中";
  if (!progress) return "正在准备原件截图";
  return `运行中${done}${progress.anchor ? `，当前 ${progress.anchor}` : ""}`;
}
