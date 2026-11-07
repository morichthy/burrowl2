// 阅读器契约（设计稿 03 D-03）：阅读模式外壳与各阅读器之间只通过这里的类型交互。
// 数据进（原件来源、标注、选项），事件出（点了哪段、看到哪一页、悬停哪段）；阅读器拿不到账本的写入能力。
// 阅读器（src/viewers/<名称>/）只能 import 本文件与它自己用到的第三方库，不能 import 工作台的页面、api.ts、labels.ts（D-05，
// 由 src/reader/isolation.test.ts 检查）。
import type { ComponentType } from "react";

/* eslint-disable @typescript-eslint/no-explicit-any */

// 原件来源：由外壳通过 api.ts 准备好，阅读器不直接调后端
export type ViewerSource = {
  id: string; // 原件 ID
  title: string;
  format: string; // pdf / docx / pptx / text / image / av / binary
  mediaType: string;
  suffix: string; // 文件扩展名，如 .md
  bytes: () => Promise<ArrayBuffer>; // 原件字节
  snapshotBytes?: () => Promise<ArrayBuffer>; // PPTX / DOCX 页面快照的 PDF 字节（有快照时才有）
  fileUrl: string; // 原件地址（<img>、<video> 用）
  pageUrl: (page: number, opts?: { scale?: number; source?: string; clip?: number[] }) => string;
  blobUrl: (sha: string, mime?: string) => string;
  assetBase: string; // 随前端打包的资源目录（PDF.js 的 CMap、字体等）
  units: Unit[]; // 抽取层的单元（页、幻灯片、整篇文档…），带块
  text?: string; // 文本原件的全文（原样复制，fidelity=copy）
  engine?: (name: string) => Promise<{ api: string; config: unknown }>; // 外部阅读引擎的签名配置（设置里配置了才有）
};

// 选阅读器时用到的环境：有没有页面快照、配置了哪些外部引擎
export type ViewerEnv = { snapshot: boolean; engines: Record<string, boolean> };

export type Unit = {
  unit: string; // p3、s2、doc、img、av…
  label: string;
  kind: string; // page / slide / doc / image / media / text
  page?: number;
  blocks?: any[];
  meta?: any;
};

// 一段标注：段落的锚点与位置，加上它在账本里的状态
export type Mark = {
  key: string; // `${unit}:${block}`，同一个块的几段共用一个 key
  anchors: string[]; // 这个块里的段落锚点（art_…#p3-2 的 p3-2）
  unit: string;
  block: number;
  page?: number; // 单元对应的页码（PDF 页、快照页）
  box?: number[]; // [x, y, 宽, 高]，占页面的比例，左上原点
  range?: string; // 表格块的单元格范围，如 A1:F20（Excel）
  text: string; // 抽取出的文字（文字定位用）
  type: string; // 块类型：paragraph / heading / formula / table …
  state: { cited: number; read: number; low: boolean; anchor: boolean };
};

export type ViewerOptions = {
  scroll: "continuous" | "page"; // 连续滚动 / 单页
  zoom: string; // "page-width" / "page-fit" / "auto" / 百分比数字的字符串
  spread: boolean; // 双页
  invertDark: boolean; // 深色模式下反色显示页面
};

export type OutlineItem = { title: string; level: number; go: () => void };

// 阅读器挂载后交给外壳的句柄；没有的能力留空
export type ViewerHandle = {
  scrollTo: (key: string) => void; // 滚到某个标注
  goToPage?: (page: number) => void; // 翻到第几页（缩略图用）
  find?: (query: string, previous?: boolean) => void;
  zoom?: (z: "in" | "out" | string) => void;
};

export type ViewerProps = {
  source: ViewerSource;
  marks: Mark[];
  marksVisible: boolean;
  highlight: string | null; // 外壳要求高亮的标注（对照视图悬停右侧时）
  options: ViewerOptions;
  onReady: (handle: ViewerHandle) => void;
  onMarkClick: (key: string | null) => void;
  onHover?: (key: string | null) => void;
  onLocation?: (unit: string) => void; // 当前看到的单元
  onOutline?: (items: OutlineItem[]) => void;
  onZoom?: (percent: number) => void;
  onError?: (message: string) => void; // 显示不了：外壳退回别的阅读器或文字视图
};

export type Capability = "paged" | "flow" | "boxes" | "text" | "native_annotations" | "find" | "outline" | "zoom";

export type ViewerDef = {
  id: string; // 与数据目录设置 viewer.<格式> 的取值一致
  label: string;
  formats: string[];
  // 能否显示这一份：例如 pdfjs-snapshot 需要已有快照
  accepts?: (source: ViewerSource, env: ViewerEnv) => boolean | string;
  license: string;
  external?: boolean; // 需要外部服务
  capabilities: Capability[];
  load: () => Promise<{ default: ComponentType<ViewerProps> }>;
};
