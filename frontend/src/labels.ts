// 界面上的中文标签。字段取值与后端 core/model.py、services/overview.py 一致。

export const LAYER: Record<string, string> = { original: "原件", judgment: "判断", framework: "框架" };
export const SOURCE: Record<string, string> = { executed: "亲自执行", external: "外部报告", discussion: "推断或讨论" };
export const TIER: Record<string, string> = { peer_reviewed: "同行评议", preprint: "预印本", vendor: "厂商资料", web: "网页" };
export const REVIEW: Record<string, string> = {
  ai_generated: "AI 生成·未复核",
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
export const DECISION: Record<string, string> = {
  term_link: "术语连接",
  review: "待复核",
  rederive: "需重新综合",
  constraint_unchecked: "操作前未检查约束",
  propagation_overflow: "传播超限",
};
export const JUDGMENT_KIND: Record<string, string> = {
  claim: "论断",
  observation: "观察",
  question: "提问",
  constraint: "约束",
  decision: "决定",
  instruction: "指令",
  purpose: "目的",
  stop_reason: "停止原因",
  review: "复核",
  correction: "更正",
  retraction: "撤回",
  defect: "原件缺陷",
};
export const ENTRY_KIND: Record<string, string> = {
  judgment: "判断",
  artifact: "原件",
  record: "事实记录",
  read: "读取记录",
  event: "过程日志",
};
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
  supersede: { label: "替代/更正/撤回", color: "#8e5bd0", dash: [10, 3, 2, 3], arrow: "triangle-backcurve", hint: "替代、更正、撤回、改写、可能替代" },
  structure: { label: "依赖/回答/针对/并存", color: "#4f6a8f", dash: [2, 3], arrow: "square", hint: "依赖、回答、针对问题、在某条件下并存" },
  derived: { label: "框架输入", color: "#d98a2b", dash: [], arrow: "vee", hint: "框架页的输入清单与主题" },
  mention: { label: "提及", color: "#a3a3a3", dash: [], arrow: "none", hint: "原件提及实体（机械连接或术语连接）" },
  association: { label: "相似/类比", color: "#0e9aa7", dash: [3, 3], arrow: "none", hint: "AI 推断的相似、类比、相关" },
};
