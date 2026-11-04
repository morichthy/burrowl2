# AGENTS.md

本仓库是 **burrowl 2**：AI 原生的研发记录与记忆系统。数据目录在仓库之外，由用户配置。帮助用户完成可追溯、可验证、可复用的工作；用户本轮的明确要求优先。

## 先读什么

| 任务 | 读什么 |
|---|---|
| 修改本项目的代码、Skill、文档、前端或打包 | [.claude/skills/burrowl-dev-check](.claude/skills/burrowl-dev-check/SKILL.md)，以及下方六份必读文档中受影响的部分 |
| 想快速看懂代码 | [docs/CORE](docs/CORE.md) 的"怎样读这份代码" |
| 用 burrowl 做研究或排查（不是开发它） | 已安装的 Skill：burrowl-work、burrowl-read、burrowl-consolidate（源文件在 [skills/](skills/)） |
| 简单问题：读源码、看配置、查命令状态 | 直接读必要的文件，不进入任何 Skill |

## 六份必读文档

| 文档                                                                  | 承载                             |
| ------------------------------------------------------------------- | ------------------------------ |
| [README](README.md)                                                 | 用途、安装、日常用法、数据目录                |
| [ARCHITECTURE](ARCHITECTURE.md)                                     | 不变式、分层、**模块影响表**、状态归属、数据流、已知差距 |
| [docs/CORE](docs/CORE.md)                                           | 功能块、核心流程、怎样读代码                 |
| [docs/README](docs/README.md)                                       | 全部文档的索引                        |
| [docs/DOCUMENTATION_MAINTENANCE](docs/DOCUMENTATION_MAINTENANCE.md) | 每件事写在哪里、维护闭环                   |
| [docs/TESTING](docs/TESTING.md)                                     | 按风险选择验证、不能省略的检查                |

- 底层模型的依据是 [docs/model/DESIGN-SKETCH](docs/model/DESIGN-SKETCH.md)（三列模型的讨论结论）；实现设计与各版本的进度在 [docs/DESIGN](docs/DESIGN.md)。
- 术语见 [docs/GLOSSARY](docs/GLOSSARY.md)；选择理由与历史见 [docs/DEVELOPMENT_HISTORY](docs/DEVELOPMENT_HISTORY.md)；操作参数见自动生成的 [docs/reference/ops.md](docs/reference/ops.md)。
- 局部开发按影响阅读和维护。全局重构、发布或用户要求全面审查时，开发前后完整阅读六份文档和全部 Skill。

## 不能破坏的约束（细节见 ARCHITECTURE）

1. 账本（原件与判断）只追加：不 UPDATE、不 DELETE，数据库触发器强制。
2. 框架永远不能作为依据；变化只在框架层传播，只降不升。
3. 调用者身份由入口决定（MCP 一律是 AI），写入时可信度由系统推出，参数不能指定。
4. 更正、撤回、复核、术语决定、启动 agent、服务控制只能由人做（effect=user），不出现在 MCP 中。
5. 落盘格式只增不改；旧数据永远可读；导出与导入是大版本升级的通道。
6. 依赖方向 `interfaces → services → store | index → core`，由 import-linter 检查。

## 开发命令

```
uv sync
uv run pytest
uv run ruff check src tests tools packaging
uv run lint-imports
uv run python tools/gen_reference.py        # 改了操作后重新生成 docs/reference/ops.md
npm --prefix frontend run build && npm --prefix frontend test
uv run python packaging/build.py --install --root <临时目录>   # 试装：不改 PATH、BURROWL_ROOT、快捷方式
```

## 记录与报告

- 完成时说明：改了什么、跑了哪些检查（结果）、哪些没跑（原因）、每份受影响文档的处置（已修改 / 已核对无需修改 / 延期及原因）。
- "已写文档"不等于"功能已实现"；"测试通过"不等于"真实场景有效"，分开报告。
- 不知道的字段留空或写明缺口，不编造。
- 动用户系统（PATH、环境变量、安装目录、客户端配置）之前先确认；试装一律用临时根目录。

## 语言

面向用户的文字、Skill、文档和代码注释用中文；标识符和协议字段用英文。术语第一次出现时链接术语表。
