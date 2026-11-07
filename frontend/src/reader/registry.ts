// 阅读器注册表（设计稿 03 D-02、D-14）：工作台只通过这里使用阅读器。
// 新增阅读器：在 src/viewers/<名称>/ 写适配器与 README.md，在这里登记，并把名称加进后端
// interfaces/ops.py 的 SETTING_CHOICES（viewer.<格式>），设置页才能选它。
import type { ViewerDef, ViewerEnv, ViewerSource } from "./contract";

export const VIEWERS: ViewerDef[] = [
  {
    id: "pdfjs",
    label: "PDF.js",
    formats: ["pdf"],
    license: "Apache-2.0",
    capabilities: ["paged", "boxes", "find", "outline", "zoom"],
    load: () => import("../viewers/pdfjs"),
  },
  {
    id: "pdfjs-snapshot",
    label: "页面快照（PDF.js）",
    formats: ["pptx", "docx", "xlsx"],
    accepts: (_s, env) => env.snapshot || "还没有页面快照",
    license: "Apache-2.0",
    capabilities: ["paged", "boxes", "find", "zoom"],
    load: () => import("../viewers/pdfjs/snapshot"),
  },
  {
    id: "docx-preview",
    label: "docx-preview",
    formats: ["docx"],
    license: "Apache-2.0",
    capabilities: ["flow", "text", "outline"],
    load: () => import("../viewers/docx-preview"),
  },
  {
    id: "sheet",
    label: "表格",
    formats: ["xlsx", "text"],
    accepts: (s) => s.format === "xlsx" || [".csv", ".tsv"].includes(s.suffix) || "只显示 Excel、CSV、TSV",
    license: "Apache-2.0",
    capabilities: ["flow", "text"],
    load: () => import("../viewers/sheet"),
  },
  {
    id: "onlyoffice",
    label: "ONLYOFFICE（外部）",
    formats: ["pdf", "docx", "pptx", "xlsx"],
    accepts: (_s, env) => env.engines.onlyoffice || "设置里还没有填写 ONLYOFFICE 的地址",
    license: "AGPL-3.0（独立运行的外部服务）",
    external: true,
    capabilities: ["paged"],
    load: () => import("../viewers/onlyoffice"),
  },
  {
    id: "markdown",
    label: "文本 / Markdown",
    formats: ["text"],
    license: "MIT",
    capabilities: ["flow", "text", "outline"],
    load: () => import("../viewers/markdown"),
  },
  {
    id: "image",
    label: "图片",
    formats: ["image"],
    license: "—",
    capabilities: ["zoom"],
    load: () => import("../viewers/image"),
  },
  {
    id: "media",
    label: "音视频",
    formats: ["av"],
    license: "—",
    capabilities: ["flow", "text"],
    load: () => import("../viewers/media"),
  },
];

export function viewerById(id: string): ViewerDef | undefined {
  return VIEWERS.find((v) => v.id === id);
}

// 这一份原件能用的阅读器，以及每个不能用的原因
export function viewersFor(source: ViewerSource, env: ViewerEnv): { def: ViewerDef; ok: boolean; why: string }[] {
  return VIEWERS.filter((v) => v.formats.includes(source.format)).map((def) => {
    const r = def.accepts ? def.accepts(source, env) : true;
    return { def, ok: r === true, why: typeof r === "string" ? r : "" };
  });
}

// 选阅读器：临时指定的 > 数据目录设置的默认 > 第一个能用的
export function pickViewer(source: ViewerSource, env: ViewerEnv, preferred: (string | undefined)[]): { def: ViewerDef | null; note: string } {
  const list = viewersFor(source, env);
  for (const id of preferred) {
    if (!id) continue;
    const hit = list.find((x) => x.def.id === id);
    if (hit?.ok) return { def: hit.def, note: "" };
    if (hit) {
      const fallback = list.find((x) => x.ok);
      return { def: fallback?.def ?? null, note: `${hit.def.label}不能显示这份原件（${hit.why}），改用${fallback?.def.label ?? "文字视图"}` };
    }
  }
  const first = list.find((x) => x.ok);
  return { def: first?.def ?? null, note: first ? "" : "没有能显示这类原件的阅读器" };
}
