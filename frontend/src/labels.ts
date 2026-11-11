// 界面上的中文标签。字段取值与后端 core/model.py、services/overview.py 一致。

export const LAYER: Record<string, string> = { original: "原件", judgment: "判断", framework: "框架" };
// 依据来源：本地实证（本项目内执行、测量或直接观察）/ 外部报告 / 推断（推理、讨论或 AI 生成）
export const SOURCE: Record<string, string> = { local: "本地实证", external: "外部报告", inferred: "推断" };
// 关系图按判断类型筛选（设计稿 09 D-15）：三种可写类型加"文献论断"（系统推出的标签，不是类型）
export const GRAPH_JUDGMENT: Record<string, string> = { conclusion: "结论", process: "过程", normative: "规定", external_claim: "文献论断" };
export const TIER: Record<string, string> = { peer_reviewed: "同行评议", preprint: "预印本", vendor: "厂商资料", web: "网页" };
export const REVIEW: Record<string, string> = {
  ai_generated: "AI 生成·未复核",
  ai_reviewed: "AI 已复核",
  human_reviewed: "人已复核",
  rejected: "被驳回",
  rule: "按规则",
};
export const FRESHNESS: Record<string, string> = {
  valid: "有效",
  inputs_changed: "输入已变化",
  superseded: "被替代",
  unchecked: "未核查",
};
// 复核历史里每一项的结论（设计稿 04 D-18）；原件另有抽取确认与退役
export const REVIEW_VERDICT: Record<string, string> = {
  confirm: "确认",
  reject: "驳回",
  unsure: "拿不准",
  request: "请人复核",
  verification: "确认抽取",
  retire: "退役",
  restore: "撤销退役",
};
export const DECISION: Record<string, string> = {
  term_link: "术语连接",
  review: "待复核",
  rederive: "需重新综合",
  constraint_unchecked: "操作前未检查约束",
  propagation_overflow: "传播超限",
  finding: "巡检发现",
};
// 判断类型（D-14）：写的人只选前三种；其余是系统记录，由人工操作生成。
// review、retirement 是 2.0.0a13 及以前写成判断的复核与退役，已改记为条目的变更历史，列表里不再出现
export const JUDGMENT_KIND: Record<string, string> = {
  conclusion: "结论",
  process: "过程",
  normative: "规定",
  review: "复核",
  correction: "更正",
  retraction: "撤回",
  defect: "原件缺陷",
  retirement: "原件退役",
};
export const WRITABLE_KIND: Record<string, string> = {
  conclusion: "结论",
  process: "过程",
  normative: "规定",
};
export const KIND_HINT: Record<string, string> = {
  conclusion: "关于对象的陈述，可以作为依据",
  process: "提问、尝试、停下的路线与重开条件、目的；不能作为结论的依据",
  normative: "约束、决定、指令；检索时排在最前，操作前必须检查",
};
// 条目列表按当前地位筛选（与后端 services/overview.ENTRY_STATUSES 一致）
export const ENTRY_STATUS: Record<string, string> = { current: "当前有效", superseded: "被替代 / 撤回", retired: "已退役", lapsed: "依据失效" };
export const ENTRY_STATUS_HINT: Record<string, string> = {
  current: "没有被替代、撤回、退役，依据也都还在",
  superseded: "已被新版本、替代、更正或撤回取代；内容仍在，只是不再是当前主张",
  retired: "人退役的原件或版本：内容没错，只是不再单独出现；可以在这里彻底删除",
  lapsed: "引用的原件已退役或删除，依据全部或部分失效",
};
// 依据失效的原因（设计稿 07 D-01）
export const LAPSE_REASON: Record<string, string> = { retired: "所引原件已退役", deleted: "已删除", hidden: "所依据的条目已隐藏" };
// 条目之间的关系（账本 links）。documents、consumed、produced 是事实记录与过程日志的出处（设计稿 07 D-07、D-08）
export const LINK_REL: Record<string, string> = {
  used: "依据",
  depends_on: "依赖",
  supports: "支持",
  opposes: "反对",
  answers: "回答",
  targets: "针对",
  coexists_under: "在条件下并存",
  supersedes: "替代",
  corrects: "更正",
  retracts: "撤回",
  defect_of: "原件缺陷",
  retires: "退役",
  wasRevisionOf: "改写自",
  documents: "出处",
  consumed: "用到",
  produced: "产出",
};
// 框架层关系图的边（framework edges）：提及、AI 推断的关系
export const EDGE_REL: Record<string, string> = {
  mentions: "提及",
  may_contradict: "可能矛盾",
  may_supersede: "可能替代",
  similar: "相似",
  analogy: "类比",
  related: "相关",
};
// 过程日志的两类（设计稿 07 D-10）
export const EVENT_SCOPE: Record<string, string> = { operations: "操作日志", system: "系统流水", all: "全部" };
export const SYSTEM_KINDS = ["review", "correction", "retraction", "defect", "retirement"];
// 待复核相关的提示（设计稿 04 D-11）
export const CITATION_NOTICE: Record<string, string> = {
  UNREAD_CITATION: "未读先引",
  LOW_FIDELITY_CITATION: "引用未确认的识别文字",
  RETIRED_CITATION: "引用已退役的原件",
  RECHECK_CITATION: "引用待复核的判断",
  CONDITIONS_UNSTATED: "文献论断没写条件",
};
// 筛选用：三种判断类型加"系统记录"一组
export const KIND_FILTER: Record<string, string> = { ...WRITABLE_KIND, system: "系统记录" };
export const kindGroup = (kind: string): string => (SYSTEM_KINDS.includes(kind) ? "system" : kind);
export const ENTRY_KIND: Record<string, string> = {
  judgment: "判断",
  artifact: "原件",
  record: "事实记录",
  event: "过程日志",
};
// 读取记录是自动日志（设计稿 01 D-03）：不在条目列表里单独列出，从原件段落进入
// 抽取的可信度档（D-12）与单元状态
export const FIDELITY: Record<string, string> = { copy: "原样复制", parsed: "解析文字层", manual: "人工转写", ocr: "OCR 识别", ai: "AI 识别" };
export const UNIT_STATUS: Record<string, string> = { text: "有文本", image: "图片页·待抽取", empty: "空白", not_extracted: "未抽取", unreadable: "读不到" };
export const FORMAT: Record<string, string> = { text: "文本", pdf: "PDF", pptx: "PPT", docx: "Word", xlsx: "Excel", image: "图片", av: "音视频", binary: "其他文件" };
export const PAGE_TYPE: Record<string, string> = { entity: "实体页", concept: "概念页", synthesis: "综合页", description: "描述页" };
export const RUN_STATUS: Record<string, string> = { running: "运行中", done: "完成", failed: "失败", cancelled: "已停止", cancelling: "停止中" };

// 关系图：节点类型与颜色（按三列配色：原件绿、判断蓝、框架橙；实体灰）
export const NODE_TYPE: Record<string, string> = {
  artifact: "原件",
  record: "事实记录",
  read: "读取记录",
  judgment: "判断",
  page: "框架页",
  entity: "实体",
};
export const NODE_COLOR: Record<string, string> = {
  artifact: "#2f9e6f",
  record: "#4fb38a",
  read: "#8cc9ad",
  judgment: "#3b6fd8",
  page: "#d98a2b",
  entity: "#7b8494",
};
// 关系类别：同一类同一种画法（图例与筛选按类别）
export const CATEGORY: Record<string, { label: string; color: string; dash: number[]; arrow: string; hint: string }> = {
  evidence: { label: "依据", color: "#6b7280", dash: [], arrow: "vee", hint: "判断引用的依据、原件缺陷" },
  support: { label: "支持", color: "#15803d", dash: [], arrow: "triangle", hint: "支持" },
  conflict: { label: "反对/可能矛盾", color: "#d64545", dash: [7, 4], arrow: "tee", hint: "反对（判断层）、可能矛盾（AI 推断）" },
  supersede: { label: "替代/更正/撤回", color: "#8e5bd0", dash: [10, 3, 2, 3], arrow: "triangle-backcurve", hint: "替代、更正、撤回、改写、可能替代、原件退役" },
  structure: { label: "依赖/回答/针对/并存", color: "#4f6a8f", dash: [2, 3], arrow: "square", hint: "依赖、回答、针对问题、在某条件下并存" },
  derived: { label: "框架输入", color: "#d98a2b", dash: [], arrow: "vee", hint: "框架页的输入清单与主题" },
  mention: { label: "提及", color: "#a3a3a3", dash: [], arrow: "none", hint: "原件提及实体（机械连接或术语连接）" },
  association: { label: "相似/类比", color: "#0e9aa7", dash: [3, 3], arrow: "none", hint: "AI 推断的相似、类比、相关" },
};

// 定期巡检（设计稿 08）
export const INSPECTION_STATUS: Record<string, string> = { ready: "准备好", running: "巡检中", done: "巡检完成", closed: "已关闭" };
export const CHECK_LABEL: Record<string, string> = {
  conflict: "疑似冲突",
  stale_basis: "依据变化后仍被引用",
  unread_neighbor: "相邻段落未读",
  rule: "与规则不符",
  uncaptured: "经验未收录",
  external_reliance: "高依赖的外部论断",
  explore: "探索样本",
};
export const FINDING_STATUS: Record<string, string> = { open: "待处理", adopt: "已采纳", reject: "已驳回", ignore: "已忽略", resolved: "已采纳", dismissed: "已关闭" };
export const FINDING_REVIEW: Record<string, string> = {
  ai_generated: "复核员还没看",
  ai_reviewed: "复核员确认",
  ai_flagged: "复核员认为不成立",
  ai_unsure: "复核员拿不准",
  human: "人已处理",
};
export const SUGGESTION: Record<string, string> = {
  oppose: "写一条反对判断",
  amend: "请人更正或撤回",
  read_more: "补读某段",
  contradict_edge: "建可能矛盾边",
  capture: "补写判断",
  verify_local: "建议本地验证",
  review: "请人复核",
  none: "无需处理",
};
// 覆盖图的五档（D-11）：颜色只为区分，不表示好坏
export const COVERAGE_STATE: Record<string, string> = {
  cited: "被引用",
  read: "读过未引",
  hit_unread: "命中未读",
  related_unread: "相关未读",
  cold: "冷区",
};

export const VERSION_ACTION_LABEL: Record<string, string> = {
  withdraw: "撤回", unwithdraw: "取消撤回", reactivate: "重新生效", defect: "标记缺陷",
  undefect: "取消缺陷标记",
  retire: "退役", restore: "取消退役", legacy_correction: "历史更正说明",
};
