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
- 更正、撤回、复核、术语决定、退役原件、启动 agent 只能由人来做。AI 可以做"AI 复核"：结果另记为"AI 已复核"，不等于人已复核。

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

前端依赖用 npm 安装，需要代理时只在命令里带上，不改用户的 npm 配置：

```bash
npm --prefix frontend install --proxy=http://127.0.0.1:7890 --https-proxy=http://127.0.0.1:7890
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
| `index.sqlite`              | 检索索引：引用段落、检索单元、向量缓存          | 能，随时可删除重建     |
| `config.json`               | 配置                                | —             |
| `runs/`                     | agent 运行的 MCP 配置和输出               | 输出已登记为原件      |
| `checks.json`               | 外部原件上次检查的结果                       | 能，随时重新检查      |

工作台的端口、token 和进程号存在安装根目录的 `server.json`，不在数据目录里。

原件的文字放在它的抽取层里（设计稿 01）：PDF、PPT、Word 登记时自动抽取，图片、扫描页、音视频默认不抽取，在原件页"交给 AI 抽取"或手动转写。抽取方式、页面快照用的转换器（本机 Office 或 LibreOffice）在"治理 → 设置"里按数据目录设置。

原件页（设计稿 02）有三种视图，记在浏览器里：

- **原样**（默认）：PDF 用内置的 PDF.js 显示原页，Word 在浏览器里按原样排版，PPT 显示页面快照；被引用、被读过、识别未确认的段落在原页上画框，点一个段落看引用写法（`art_…#p3-2`）、读取记录和引用它的判断。
- **对照**：左边原页、右边抽取出的段落，悬停任一边另一边同步高亮，用来检查抽取是否正确，逐页"确认"。
- **文字**：抽取出的文字，与检索、引用一致。PDF 里的行间公式显示为原件上那一块的截图（抽取出的字符可展开），夹着行内公式的段落旁有"看原件这段"。

**阅读模式**（设计稿 03）：原件页工具栏、判断与框架页条目右上角的"阅读"进入全屏阅读，判断正文里引用的原件段落旁的 ⛶ 也能直接进入。PDF 与 PPT / Word 的页面快照用 PDF.js 阅读器连续显示（缩放、单页 / 双页、目录、查找），Word 也可以用浏览器排版连续展开，文本、Markdown（含公式）、图片、音视频各有对应的阅读器；"原样 / 对照 / 文字"三种视图同样全屏可用。右侧栏列出被读过、被引用的段落、引用这份原件的判断和目录，点一项跳到原件位置。工具栏上的"缩略图""侧栏""标注"是开关。按 Esc 退出浏览器全屏，"← 退出阅读"回到原来的页面。

Excel 原件（.xlsx）登记时按工作表抽取表格区域（引用写 `art_…#s1-2` 这样的锚点），阅读模式里用表格阅读器显示（工作表标签、列宽、合并单元格，被引用的区域加底色），也可以生成页面快照。PDF 的公式块旁有"交给 AI 识别""填写 LaTeX"：补上的 LaTeX 用公式排版显示，并标出来源（AI 识别 / 人工）与是否确认，"对照原件"切回截图。

**外部引擎 ONLYOFFICE（可选）**：想让 Word、Excel、PPT 完全按 Office 的样子显示时，自己运行一个 ONLYOFFICE Docs（例如 `docker run -d -p 8080:80 -e JWT_SECRET=<密钥> onlyoffice/documentserver`），在"设置 → 阅读"里填写引擎地址、JWT 密钥；引擎在 Docker 里时，"引擎访问 burrowl 的地址"填 `http://host.docker.internal:<工作台端口>`。点"测试连接"，再把对应格式的默认阅读器换成"ONLYOFFICE（外部）"。引擎只读显示，不能编辑；段落标注只在侧栏列出。每种格式默认用哪个阅读器在"治理 → 设置 → 阅读"里按数据目录选，工具栏上也可以临时换；默认视图、缩放、是否显示标注等个人偏好只存在本浏览器。关系图面板右上角的"全屏"让图铺满屏幕；"筛选""图例"两个开关收起对应的浮层，节点详情在选中节点时出现、可以关闭。

升级到新版本后，首页状态卡的"补抽"会给还没有抽取层的原件补上抽取，并把旧版抽取器做的抽取层按新版重建（2.0.0a11 起 PDF 按位置分段、带段落位置，2.0.0a12 起识别公式块，2.0.0a13 起抽取 Excel；人工、AI 提交过的页保留）；也可以用 `burrowl call extraction.backfill`。重建后文字变了的段落，引用它的判断会进入待复核。

不再需要单独出现的原件（例如旧版另行登记的"抽取文本"）可以**退役**：在原件页"修改"里填理由（可以写明替代它的原件）后点"退役"，或在首页状态卡的"建议退役"里一键处理。退役不删除任何东西：原件仍可打开、阅读、引用，只是不再出现在条目列表和默认检索里（列表与检索里勾选"显示 / 包含已退役"可以看到）；以它为输入的框架页标为"输入已变化"；引用它的判断可信度不变，新引用会提示改引替代它的原件。在原件页顶部"撤销退役"即可恢复。退役记为原件的状态历史（原件页"复核"框里能看到），不是一条判断；账本只追加，没有删除功能。

**本地模型（可选）**：在"设置 → 模型与引擎"里接一个本机运行的 MinerU，PDF 的公式就能得到 LaTeX、行内公式按公式显示。安装与启动（Python 3.11–3.14）：

```
uv tool install --python 3.12 "mineru>=4.0,<5"
mineru-api --port 8790 --tier basic
```

第一次运行会下载约 0.8 GB 模型；basic 档只用 CPU，Adam 论文 15 页约 90 秒。地址填 `http://127.0.0.1:8790`，点"测试连接"。之后登记、补抽的 PDF 会自动排队处理（只有本机地址才会自动运行），原件页也可以点"用版面引擎补公式"。默认只给公式块补 LaTeX，段落与锚点不变；补上的 LaTeX 标为"OCR 识别·未确认"，需要你确认。公式块旁的"识别"用 MinerU 识别单个公式截图。也可以配置一个 OpenAI 兼容的大模型接口，它只在你点击"用大模型识别"时调用，登记、补抽、定时任务都不会调用。阅读模式的对照视图里，文字栏可以切换"阅读顺序 / 按版面"。

**复核**：原件、判断、框架页、关系图里的边都有同一个"复核"框，显示复核状态与历史，可以复核、请人复核，或"交给 AI 复核"（复制一段提示给你的 AI 客户端）。复核判断时只核对它与依据是否对得上，可以补充依据、勾选本地实证，判断本身和写入时可信度不变。AI 写的综合页、关联边不再逐条进待决策；待决策里影响为 0 的项默认折叠，另有每周抽查。AI 复核能接受的范围在"设置 → 复核"里选（默认只接受框架页与关联边）。

外部原件（只登记路径和指纹的那类）由工作台每 6 小时检查一次是否变化或丢失（所有登记的数据目录都查），首页"状态"卡也可以立即检查。间隔在 `config.json` 的 `artifact_check.interval_hours` 中设置，设为 0 关闭。发现变化后，确认是新版本就在"人工记录"里登记为新版本。

**检索**（设计稿 06）：关键词和自然语言都可以，命中一部分词也能召回；结果按相关度排，每条写明它的地位（原件 / 判断 / 框架、依据来源、是否被替代）。向量通道默认用 jina-embeddings-v2-base-zh（中英双语），模型放在 `<安装根目录>/models/jina-embeddings-v2-base-zh/`（或 `BURROWL_MODELS_DIR`），不随安装包提供；工作台在后台补建向量，没有模型时只用关键词。重排默认关闭，可在"设置"里打开（`index.rerank=auto`，模型目录 `models/cross-encoder/`）。要一次补完向量：`burrowl call index.embed`。

备份或迁移时使用 `burrowl call data.export target=<目录>`。导出内容是 JSONL、blobs，以及兼容 Obsidian 的 Markdown 页面。
