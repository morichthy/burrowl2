// 界面上的中文标签。字段取值与后端 core/model.py 一致。

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
