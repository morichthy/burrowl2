# burrowl 2

AI 原生的研发记录与记忆系统，面向两类场景：资料不全、有权限限制的长链条工业排查，以及多路线并行的探索性研究。

- 设计稿：[docs/DESIGN.md](docs/DESIGN.md)，包括核心功能、功能架构、技术实现架构和测试项。
- 底层模型：[docs/model/DESIGN-SKETCH.md](docs/model/DESIGN-SKETCH.md)，是研究目录中同名文件的快照。

## 一句话模型

内容分三列：

- **原件**：只保证原文如实；
- **判断**：如实记下当时谁、依据什么、认为了什么；
- **框架**：实体页、综合页、关系图，可以再生和丢弃，永远不能作为依据。

原件和判断只追加。"现在该信什么"由框架回答。变化只在框架层传播，而且只降不升。

## 安装与运行（开发环境）

```bash
uv sync
```

```bash
uv run burrowl init D:/BurrowlData2/main
```

```bash
uv run burrowl serve
```

`init` 建立数据目录并登记为默认；`serve` 启动工作台，终端会打印带 token 的网址。

一个工作台管理所有登记的数据目录：侧栏顶部切换，"治理 → 数据目录"里登记、设为默认、移除登记（不删数据）。网址里的 `?db=名称` 表示当前目录，两个标签页可以各开一个。命令行对应 `burrowl data list | add | default | remove`。每个目录的账本、框架、索引互相独立，一个请求只作用于一个目录。

```bash
uv run burrowl mcp-config
```

这条命令输出标准的 MCP stdio 配置，交给 agent 客户端登记。不带 `--data` 时，AI 每次调用连接当时的默认数据目录，在工作台改了默认就跟着变；要固定连某个目录，用 `mcp-config --data <目录>` 另登记一条（登记名默认 `burrowl-<名称>`）。

```bash
uv run burrowl call search query=压力 limit=5 --data D:/BurrowlData2/main
```

`burrowl call` 的参数写成 `key=value`（值能按 JSON 解析就按 JSON，例如数字、`true`、列表），也可以用 `@参数.json` 从文件读，或用 `-` 从标准输入读。不建议在 cmd / PowerShell 里直接写整段 JSON：经 `burrowl.cmd` 转发时引号会被拆坏。


这条命令从命令行调用任意操作。

```bash
uv run burrowl ops
```

这条命令列出全部操作，以及每个操作的 effect：
- `user` 和 `admin` 类操作不会出现在 MCP 中；
- 更正、撤回、复核、术语决定、启动 agent 只能由人来做。

## 在工作台使用 agent

工作台的 Agent 页按数据目录 `config.json` 中的 `agents` 命令模板启动本机 agent CLI。

- 模板中可以使用两个占位符：`{prompt}` 是任务文本，`{mcp_config}` 是运行器为本次运行生成的 MCP 配置文件路径。
- 默认配置了 `claude` 和 `codex` 两项。本机找不到对应命令时，界面会标注"未找到命令"。
- 每次运行有独立的身份（`ai:<agent>:<run_id>`）和会话。agent 通过 MCP，或在子进程里调用命令行写入的内容，作者都记为这次运行的 AI。
- 输出实时显示，运行结束后登记为对话原件。
- 框架页、待决策项上有"交给 agent"按钮，会把任务文本带到 Agent 页。

## 演示数据

```bash
uv run python tools/seed_demo.py data
```

```bash
uv run burrowl serve --data data
```

`--data` 会先登记这个目录（已有默认目录时不改默认），再在工作台里切换到它。

`tools/demo_agent.py` 是一个不调用模型的演示 agent，用来展示 agent 通过命令行回到工作区读写。

## 开发与维护

- 入口：[AGENTS.md](AGENTS.md)（Claude Code 经 `CLAUDE.md` 自动读取）；开发检查流程：[.claude/skills/burrowl-dev-check](.claude/skills/burrowl-dev-check/SKILL.md)。
- 改代码前先看 [ARCHITECTURE](ARCHITECTURE.md) 的模块影响表；想看懂代码，从 [docs/CORE](docs/CORE.md) 的怎样读这份代码开始。
- 全部文档见 [docs/README](docs/README.md)；每件事写在哪里、怎样维护见 [docs/DOCUMENTATION_MAINTENANCE](docs/DOCUMENTATION_MAINTENANCE.md)。

## 开发命令

```bash
uv run pytest
```

```bash
uv run ruff check src tests tools packaging
```

```bash
uv run lint-imports
```

```bash
npm --prefix frontend run build
```

```bash
npm --prefix frontend test
```

前端构建产物输出到 `src/burrowl/web/`，随 Python 包分发。

## 数据目录

| 文件                          | 内容                                | 能否再生          |
| --------------------------- | --------------------------------- | ------------- |
| `ledger.sqlite`             | 原件、过程日志、事实记录、读取记录、判断、判断间关系、原件的抽取记录 | **不能**，必须备份   |
| `blobs/`                    | 受管原件的内容，按 sha256 寻址               | **不能**，必须备份   |
| `cache/`                     | 页面图像等派生缓存                          | 能，随时可删除        |
| `framework.sqlite`          | 实体、别名、页面与版本、边、派生输入清单、待决策、agent 运行 | 能，但重建要花 AI 成本 |
| `index.sqlite`              | 全文索引                              | 能，随时可删除重建     |
| `config.json`               | 配置                                | —             |
| `runs/`                     | agent 运行的 MCP 配置和输出               | 输出已登记为原件      |
| `checks.json`               | 外部原件上次检查的结果                       | 能，随时重新检查      |

工作台的端口、token 和进程号存在安装根目录的 `server.json`，不在数据目录里。

原件的文字放在它的抽取层里（设计稿 01）：PDF、PPT、Word 登记时自动抽取，图片、扫描页、音视频默认不抽取，在原件页"交给 AI 抽取"或手动转写。原件页默认显示抽取结果，按格式排版（PDF 逐页、PPT 显示页面快照、Word 显示正文、视频带可点击的时间戳），随时可以打开或下载原件。每段标出被读过几次、被哪些判断引用；识别出的文字标出可信度档，可以逐页确认。抽取方式、页面快照用的转换器（本机 Office 或 LibreOffice）在"治理 → 设置"里按数据目录设置。升级到 2.0.0a10 后，已有的 PDF 等原件需要补抽一次：首页状态卡的"补抽"，或 `burrowl call extraction.backfill`。

外部原件（只登记路径和指纹的那类）由工作台每 6 小时检查一次是否变化或丢失（所有登记的数据目录都查），首页"状态"卡也可以立即检查。间隔在 `config.json` 的 `artifact_check.interval_hours` 中设置，设为 0 关闭。发现变化后，确认是新版本就在"人工记录"里登记为新版本。

备份或迁移时使用 `burrowl call data.export target=<目录>`。导出内容是 JSONL、blobs，以及兼容 Obsidian 的 Markdown 页面。
