# 文档维护约定

目标：人和 AI 都能通过少量文档快速理解项目的结构、流程和容易互相影响的地方。文档要少而准，不重复。

## 一件事只在一个地方维护

| 内容 | 唯一位置 | 其他文档的做法 |
|---|---|---|
| 用途、安装、日常用法、数据目录 | 根 README | 只给简短说明和链接 |
| 不变式、分层、模块影响表、状态归属、数据流、已知差距 | 根 ARCHITECTURE | 不在别处维护第二份影响表 |
| 功能块、核心流程伪代码、代码导读 | docs/CORE | 不展开参数和常数 |
| 文档索引 | docs/README | 只做索引 |
| 文档职责与维护规则 | 本页 | Skill 只引用，不复制 |
| 测试选择与必查项 | docs/TESTING | 具体断言写在测试代码里 |
| 选择理由、被放弃的方案、事故与教训、未决讨论 | docs/DEVELOPMENT_HISTORY | 讨论全局方案前读；开发后补记 |
| 术语 | docs/GLOSSARY | 其他文档首次出现时链接这里 |
| 底层模型的讨论结论 | docs/model/DESIGN-SKETCH | 快照，源头在研究目录；更新时整体替换并注明日期 |
| 实现设计、各版本的决定与进度 | docs/DESIGN（基础设计）；之后的专题设计放 docs/design/ | 设计稿不等于已实现；完成后把稳定说明迁到 CORE / ARCHITECTURE，并更新进度 |
| 操作参数 | docs/reference/ops.md | 由 `tools/gen_reference.py` 生成，**不手写** |
| 使用 burrowl 的 agent 的规则 | skills/RULES.md 与各 Skill | 只写流程和判断规则；程序已强制的只提一句 |
| 开发本项目时的检查流程 | .claude/skills/burrowl-dev-check | 引用本页和 TESTING，不复制 |

## 维护闭环

1. **开发前**：在 ARCHITECTURE 的模块影响表中找到要改的模块，读"改动时一并检查"一列；查 DEVELOPMENT_HISTORY 中的相关决定。
2. **开发后**：按下表只更新受影响的部分。

| 改了什么 | 维护哪里 |
|---|---|
| 用户可见的功能、命令、安装方式、数据目录内容 | README |
| 模块、文件、依赖、状态、不变式、数据流、已知差距 | ARCHITECTURE（新文件必须进影响表，`tests/test_docs.py` 会检查） |
| 功能块的行为、核心流程 | docs/CORE |
| 操作名或参数 | 运行 `uv run python tools/gen_reference.py`；检查 skills 中的工具名与说明 |
| 取值（判断类型、关系、状态） | GLOSSARY、前端 `labels.ts`、`skills/RULES.md` |
| 测试分层或必查项 | docs/TESTING |
| 取舍、放弃的方案、事故 | docs/DEVELOPMENT_HISTORY（按编号追加） |
| 新增或移动文档 | docs/README |

3. **报告**：本次结果摘要中写清每份相关文档的处置：**已修改 / 已核对无需修改 / 延期（原因）**。

全局重构、发布或用户要求全面审查时，开发前后完整阅读六份必读文档和全部 Skill，逐项核对。

## 自动检查（`tests/test_docs.py`）

| 检查 | 防止什么 |
|---|---|
| 文档中的相对链接都能找到目标文件 | 移动或删除文件后留下死链 |
| `src/burrowl` 下每个源文件都出现在 ARCHITECTURE 的影响表中 | 新增模块没人知道它影响什么 |
| Skill 中提到的 burrowl 工具都存在，而且是 agent 可调用的（不是 user 或 admin） | 改名后 Skill 失效，或 Skill 让 agent 调用它无权调用的操作 |
| docs/reference/ops.md 与代码一致 | 参数表过期 |

这些检查只能发现"形式上"的不一致。语义上的变化，比如一个参数的含义变了，仍要靠上面的闭环人工核对。

## 控制增长，保留历史

- 必读文档只写跨模块理解所必需的内容；参数、示例、完整的测试矩阵放到生成文件或代码里。
- 新增文档前先看能否并入现有文件；新增后必须能从 docs/README 找到。
- 删除仍然有效的约束、被替代的方案或失败教训之前，先把它记入 DEVELOPMENT_HISTORY，写明去向和依据。
- 设计目标、用户要求、功能存在、验收通过，这四件事分开写。

这是人和 AI 共同遵守的开发约定，没有后台同步服务。
