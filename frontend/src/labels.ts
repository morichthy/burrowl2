// 界面上的中文标签。坐标取值、谓词、标记来自词表（vocab.gen.ts，由 tools/gen_reference.py 从 core/vocab.py 生成，
// 设计稿 10 D-16）；这里只放界面自己用的说法。
import { VOCAB } from "./vocab.gen";

type Labels = Record<string, string>;
const labels = (o: object): Labels => o as Labels;

// 坐标（设计稿 10 D-12）：地位 → 类型 → 现状 → 说明
export const LAYER: Labels = labels(VOCAB.layers);
export const SOURCE_LABEL: Labels = labels(VOCAB.sources); // 来源记号：local、external:peer_reviewed……
export const KIND: Labels = labels(VOCAB.kinds);
export const VALIDITY: Labels = labels(VOCAB.validity);
export const REVIEW_STATE: Labels = labels(VOCAB.review);
export const AUTHOR: Labels = labels(VOCAB.authors);
export const MARKS = VOCAB.marks as Record<string, { group: string; label: string; severity: string; rule: string }>;
export const PREDICATES = VOCAB.predicates as Record<string, { label: string; inverse: string; category: string; origin: string; evidential: boolean; basis: boolean; flow: string | null }>;
export const CATEGORIES: Labels = labels(VOCAB.categories);
export const CATEGORY_ORDER: string[] = [...VOCAB.category_order];
// 筛选用的依据来源大类（检索、条目、关系图同名同序，D-24）
export const SOURCE: Labels = { local: "本地实证", external: "外部报告", inferred: "推断" };
export const TIER: Labels = { peer_reviewed: "同行评议", preprint: "预印本", vendor: "厂商资料", web: "网页" };
// 框架页、边的复核列（框架库的缓存值）
export const REVIEW: Labels = {
  ai_generated: "AI 生成·未复核",
  ai_reviewed: "AI 已复核",
  human_reviewed: "人已复核",
  rejected: "被驳回",
  rule: "按规则",
};
export const FRESHNESS: Labels = {
  valid: "有效",
  inputs_changed: "输入已变化",
  superseded: "被替代",
  unchecked: "未核查",
};
// 复核历史里每一项的结论（设计稿 04 D-18）；原件另有抽取确认与退役
export const REVIEW_VERDICT: Labels = {
  confirm: "确认",
  reject: "驳回",
  unsure: "拿不准",
  request: "请人复核",
  verification: "确认抽取",
  retire: "退役",
  restore: "撤销退役",
};
// 关系的说法：出边用 label，入边用 inverse；自由谓词显示它自己的标签
export const relPhrase = (predicate: string, outgoing = true, label?: string | null): string =>
  predicate === "relates" ? (label || "关系") : (outgoing ? PREDICATES[predicate]?.label : PREDICATES[predicate]?.inverse) ?? predicate;
export const DECISION: Labels = {
  term_link: "术语连接",
  review: "待复核",
  rederive: "需重新综合",
  constraint_unchecked: "操作前未检查约束",
  propagation_overflow: "传播超限",
  finding: "巡检发现",
};
// 判断类型（D-14）：写的人只在三种里选
export const WRITABLE_KIND: Labels = {
  conclusion: "结论",
  process: "过程",
  normative: "规定",
};
export const JUDGMENT_KIND: Labels = { conclusion: "结论", process: "过程", normative: "规定" };
export const KIND_HINT: Labels = {
  conclusion: "关于对象的陈述，可以作为依据",
  process: "提问、尝试、停下的路线与重开条件、目的；不能作为结论的依据",
  normative: "约束、决定、指令；检索时排在最前，操作前必须检查",
};
// 条目列表按现状的有效性筛选（与后端 services/overview.ENTRY_STATUSES 一致）
export const ENTRY_STATUS: Labels = VALIDITY;
export const ENTRY_STATUS_HINT: Labels = {
  current: "当前版没有被替代、撤回、退役，依据也都还在",
  replaced: "有更新的版本，或被人确认的替代关系取代；内容仍在，只是不再是当前主张",
  withdrawn: "人撤回了当前版：不再主张，内容仍可查",
  retired: "人退役的原件：内容没错，只是不再单独出现；可以在这里彻底删除",
  lapsed: "依据全部落在已退役或已删除的原件上",
};
// 关系的中文（旧名沿用：判断层与框架推断的关系都在词表里）
export const LINK_REL: Labels = Object.fromEntries(Object.entries(PREDICATES).map(([k, v]) => [k, v.label]));
export const EDGE_REL: Labels = LINK_REL;
// 过程日志的两类（设计稿 07 D-10）
export const EVENT_SCOPE: Labels = { operations: "操作日志", system: "系统流水", all: "全部" };
// 待复核相关的提示（设计稿 04 D-11）
export const CITATION_NOTICE: Labels = {
  UNREAD_CITATION: "未读先引",
  LOW_FIDELITY_CITATION: "引用未确认的识别文字",
  RETIRED_CITATION: "引用已退役的原件",
  RECHECK_CITATION: "引用待复核的判断",
  CONDITIONS_UNSTATED: "转述但没写条件",
};
export const KIND_FILTER: Labels = WRITABLE_KIND;
export const kindGroup = (kind: string): string => kind;
export const ENTRY_KIND: Labels = {
  judgment: "判断",
  artifact: "原件",
  record: "事实记录",
  event: "过程日志",
};
// 读取记录是自动日志（设计稿 01 D-03）：不在条目列表里单独列出，从原件段落进入
// 抽取的可信度档（D-12）与单元状态
export const FIDELITY: Labels = { copy: "原样复制", parsed: "解析文字层", manual: "人工转写", ocr: "OCR 识别", ai: "AI 识别" };
export const UNIT_STATUS: Labels = { text: "有文本", image: "图片页·待抽取", empty: "空白", not_extracted: "未抽取", unreadable: "读不到" };
export const FORMAT: Labels = { text: "文本", pdf: "PDF", pptx: "PPT", docx: "Word", xlsx: "Excel", image: "图片", av: "音视频", binary: "其他文件" };
export const PAGE_TYPE: Labels = { entity: "实体页", concept: "概念页", synthesis: "综合页", description: "描述页" };
export const RUN_STATUS: Labels = { running: "运行中", done: "完成", failed: "失败", cancelled: "已停止", cancelling: "停止中" };

// 关系图：节点类型与颜色（按三列配色：原件绿、判断蓝、框架橙；实体灰）
export const NODE_TYPE: Labels = {
  artifact: "原件",
  record: "事实记录",
  read: "读取记录",
  judgment: "判断",
  page: "框架页",
  entity: "实体",
};
export const NODE_COLOR: Labels = {
  artifact: "#2f9e6f",
  record: "#4fb38a",
  read: "#8cc9ad",
  judgment: "#3b6fd8",
  page: "#d98a2b",
  entity: "#7b8494",
};
// 关系类别（词表 CATEGORIES，设计稿 10 D-22）：同一类同一种画法。证据流箭头统一画成"证据 → 结论"；
// 立场与替代醒目，依据线较淡，框架推断虚线，自由标签显示标签
export const CATEGORY: Record<string, { label: string; color: string; dash: number[]; arrow: string; hint: string }> = {
  evidence: { label: "证据流", color: "#6b7280", dash: [], arrow: "vee", hint: "依据、佐证、反驳：箭头从证据指向结论" },
  stance: { label: "立场与结构", color: "#4f6a8f", dash: [2, 3], arrow: "square", hint: "回答、针对、条件并存" },
  replace: { label: "替代", color: "#8e5bd0", dash: [10, 3, 2, 3], arrow: "triangle-backcurve", hint: "人确认的替代" },
  process: { label: "过程", color: "#2f9e6f", dash: [], arrow: "vee", hint: "一次运行用到、产出的文件" },
  framework: { label: "框架推断", color: "#d98a2b", dash: [6, 4], arrow: "none", hint: "可能矛盾、可能替代、相似、类比、提及、页面的输入与主题；不能作为依据" },
  free: { label: "自由标签", color: "#0e9aa7", dash: [3, 3], arrow: "vee", hint: "relates + 自己写的标签；系统不赋予含义" },
};
// 证据流里各谓词的颜色：佐证绿、反驳红、依据灰
export const PREDICATE_COLOR: Labels = { cites: "#9ca3af", supports: "#15803d", opposes: "#d64545" };

// 定期巡检（设计稿 08）
export const INSPECTION_STATUS: Labels = { ready: "准备好", running: "巡检中", done: "巡检完成", closed: "已关闭" };
export const CHECK_LABEL: Labels = {
  conflict: "疑似冲突",
  stale_basis: "依据变化后仍被引用",
  unread_neighbor: "相邻段落未读",
  rule: "与规则不符",
  uncaptured: "经验未收录",
  external_reliance: "高依赖的外部结论",
  explore: "探索样本",
};
export const FINDING_STATUS: Labels = { open: "待处理", adopt: "已采纳", reject: "已驳回", ignore: "已忽略", resolved: "已采纳", dismissed: "已关闭" };
export const FINDING_REVIEW: Labels = {
  ai_generated: "复核员还没看",
  ai_reviewed: "复核员确认",
  ai_flagged: "复核员认为不成立",
  ai_unsure: "复核员拿不准",
  human: "人已处理",
};
export const SUGGESTION: Labels = {
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
export const COVERAGE_STATE: Labels = {
  cited: "被引用",
  read: "读过未引",
  hit_unread: "命中未读",
  related_unread: "相关未读",
  cold: "冷区",
};

export const VERSION_ACTION_LABEL: Labels = {
  withdraw: "撤回", unwithdraw: "取消撤回", reactivate: "重新生效", defect: "标记缺陷",
  undefect: "取消缺陷标记",
  retire: "退役", restore: "取消退役",
};
