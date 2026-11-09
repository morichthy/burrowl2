# 专题设计稿

2.0 基础设计在 [../DESIGN.md](../DESIGN.md)。之后每个跨多步的专题（例如阅读会话、维护计划）在这里建一份设计稿：

- 文件名：`<序号>-<主题>.md`，例如 `01-reading-sessions.md`。
- 内容：问题、决定（编号）、对不变式与影响表的影响、任务与验收、进度记录。
- 设计稿不代表已实现；实现完成后，把稳定的说明迁到 CORE / ARCHITECTURE，在 DEVELOPMENT_HISTORY 记下决定，并在设计稿里更新进度。

| 设计稿 | 状态 |
|---|---|
| [01 读取降级、原件页与抽取层](01-reading-and-entry-view.md) | 已实现（2.0.0a10） |
| [02 原件原样显示、段落定位与原件退役](02-faithful-view-and-retirement.md) | 已实现（2.0.0a11）；2.0.0a14 起退役不再写成判断 |
| [03 阅读模式（全屏）、可更换的阅读器与公式](03-reader-mode-and-formulas.md) | 已实现（2.0.0a12、2.0.0a13；ONLYOFFICE 未在真实引擎上实测） |
| [04 减少人工复核：分档、按需复核与 AI 复核](04-review-load.md) | 已实现（2.0.0a14）；AC-08 真实 AI 客户端一轮复核未做 |
| [05 本地模型：版面抽取、公式识别与按版面对照](05-local-models-and-layout.md) | 已实现（2.0.0a14，MinerU）；公式正确率人工抽查未做 |
| [06 检索单元、混合检索、重排与联想](06-retrieval-units-and-hybrid-search.md) | 已实现（2.0.0a14，在另一个分支开发时编号为 04）；2.0.0a15 起检索参数与检索单元长度可在设置里改（D-21 至 D-23）；大评测待用户确认 |
| [07 定期巡检：规则检查、覆盖图与两道 AI 检查](07-periodic-inspection.md) | 已实现（未发版）；AC-07 真实 AI 客户端跑一期巡检未做 |

待开发事项见 [../DEVELOPMENT_HISTORY.md](../DEVELOPMENT_HISTORY.md) 的"未决讨论"。
