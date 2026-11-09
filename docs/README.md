# 文档索引

## 必读（开发时）

| 文档 | 内容 |
|---|---|
| [../README.md](../README.md) | 用途、安装、日常用法、数据目录 |
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | 不变式、分层、模块影响表、状态归属、数据流、已知差距 |
| [CORE.md](CORE.md) | 功能块、核心流程、代码导读 |
| [README.md](README.md) | 本页 |
| [DOCUMENTATION_MAINTENANCE.md](DOCUMENTATION_MAINTENANCE.md) | 每件事写在哪里、维护闭环、自动检查 |
| [TESTING.md](TESTING.md) | 按影响选择验证、必查项 |

## 按需查阅

| 文档 | 内容 |
|---|---|
| [GLOSSARY.md](GLOSSARY.md) | 术语 |
| [DEVELOPMENT_HISTORY.md](DEVELOPMENT_HISTORY.md) | 决定、被放弃的方案、事故与教训、未决讨论 |
| [DESIGN.md](DESIGN.md) | 2.0 基础设计：核心功能、功能架构、技术实现架构、旧版导入、全局安装、工作台；各版本进度 |
| [model/DESIGN-SKETCH.md](model/DESIGN-SKETCH.md) | 底层三列模型的讨论结论（研究目录的快照） |
| [reference/ops.md](reference/ops.md) | 全部操作及参数（由 `tools/gen_reference.py` 生成） |
| [design/](design/) | 专题设计稿：[01 读取降级、原件页与抽取层](design/01-reading-and-entry-view.md)（已实现，2.0.0a10）；[02 原件原样显示、段落定位与原件退役](design/02-faithful-view-and-retirement.md)（已实现，2.0.0a11）；[03 阅读模式（全屏）、可更换的阅读器与公式](design/03-reader-mode-and-formulas.md)（已实现，2.0.0a12、2.0.0a13）；[04 减少人工复核：分档、按需复核与 AI 复核](design/04-review-load.md)（已实现，2.0.0a14）；[05 本地模型：版面抽取、公式识别与按版面对照](design/05-local-models-and-layout.md)（已实现，2.0.0a14）；[06 检索单元、混合检索、重排与联想](design/06-retrieval-units-and-hybrid-search.md)（已实现，2.0.0a14；检索参数进设置 2.0.0a15）；[07 原件的替换与删除、事实记录的出处、过程日志的阅读](design/07-replacement-deletion-and-provenance.md)（已实现，2.0.0a16）；[08 定期巡检：规则检查、覆盖图与两道 AI 检查](design/08-periodic-inspection.md)（已实现，2.0.0a17，§11 修订在 2.0.0a18；AC-07 未做） |

## 给使用 burrowl 的 agent

| 文件 | 内容 |
|---|---|
| [../skills/RULES.md](../skills/RULES.md) | 公共规则 |
| [../skills/burrowl-work/SKILL.md](../skills/burrowl-work/SKILL.md) | 记录工作 |
| [../skills/burrowl-read/SKILL.md](../skills/burrowl-read/SKILL.md) | 检索与阅读 |
| [../skills/burrowl-consolidate/SKILL.md](../skills/burrowl-consolidate/SKILL.md) | 维护框架 |
| [../skills/burrowl-inspect/SKILL.md](../skills/burrowl-inspect/SKILL.md) | 定期巡检：巡检员与复核员 |

## 给开发本项目的 agent

| 文件 | 内容 |
|---|---|
| [../AGENTS.md](../AGENTS.md) | 入口（`CLAUDE.md` 引用它） |
| [../.claude/skills/burrowl-dev-check/SKILL.md](../.claude/skills/burrowl-dev-check/SKILL.md) | 开发检查流程 |
