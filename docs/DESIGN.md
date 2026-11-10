# Burrowl 2 设计稿：核心功能、功能架构与技术实现架构

- 状态：第一版（v2.0.0a1），2026-11-04。由 AI 按用户授权自行决定，后续再改。
- 模型依据：[docs/model/DESIGN-SKETCH.md](model/DESIGN-SKETCH.md)，是研究目录中同名文件的快照。下文用"草图 §n"指代它的第 n 节。
- 文献与源码依据：研究目录的 `FIELD-SURVEY.md` 第 13–19 节。
- 第一原则：**可扩展、可兼容、可升级**。数据结构只用通用、成熟的形式，不发明独特格式，因为后续还会有大版本改动。

## 0. 本版自行决定的挂起项

草图第 9 节中仍挂起的项，本版按下表处理。每一项都可以以后替换，替换时只影响表中写明的位置。

| 挂起项 | 本版决定 | 影响位置 |
|---|---|---|
| 稳定引用的写法 | 所有条目使用不可变 ID：`<类型前缀>_<ULID>`，例如 `jdg_01JC…`。底层只追加，所以 ID 本身就是版本。框架页用 `pg_…@版本号` 引用固定版本，原件段落用 `art_…#段落`（文本、Word 写 `seg-N`，PDF、PPT 写 `p3-2`；设计稿 01 D-14）。正文里的引用写成 `[[ID]]`，与 Obsidian 的维基链接兼容 | `core/ids.py`、`core/refs.py` |
| 人的第一手观察 | 人本人通过工作台或 CLI 写下、并勾选"本地实证"的结论，记为本地实证（D-14 起；原为按 observation 类型判断）。由 AI 转述的，按草图 §13 第 3 条记为 AI 判断，依据来源是"推断或讨论"，人确认后才成为人的判断 | `services/judgments.py` |
| 人的指令、约束、决定 | 一种判断类型（`constraint` / `decision` / `instruction`）。它们规定该怎么做，不陈述世界怎样，所以不参与"真假"排序。D-14 起三者合为一种 `normative`（规定） | `core/models.py`（实际：`core/model.py` 的 `NORMATIVE_KINDS`、`derive_credibility`） |
| 约束如何强制生效 | 三道机制：① 检索时，与查询对象相关的有效约束总是排在最前，并单独列出；② 提供 `constraints.check(objects)`，Skill 规定 agent 对某对象动手前必须调用；③ 过程日志中，如果对某对象的操作发生在对它的约束检查之前，就生成一条待决策项 | `services/constraints.py`（实际：`services/retrieval.py` 的 `check_constraints`、`flag_unchecked_constraints`，由 `services/capture.py` 触发；没有单独的模块） |
| 依赖传播的上限 | 沿派生输入清单做传递遍历，最多 8 跳、1000 个条目（参考 gbrain）。超出的部分标为"未核查"，并生成一条待决策项 | `services/propagation.py` |
| 文献新版本 | 新版本登记为新原件，用 `version_of` 指向旧版本。系统按片段哈希比较两版差异：引用了已变化片段的判断（`cited_segments`）、读取记录，以及以它们为输入的框架条目标为"输入已变化"。针对旧版的判断仍然成立，因为它说的是"旧版说了 X" | `services/artifacts.py` |
| 独立重复如何计入可信度 | 框架的当前可信度中报告"独立支持数"：支持同一判断的本地实证类依据，其原件互不相同、会话也互不相同，各算一次。只做报告，不打分 | `services/ranking.py`（实际：`services/judgments.py` 的 `independent_support`；没有单独的模块） |
| 记录成本 | 过程日志只追加、不进默认检索；只有被引用或被标记的才升级为正式条目。框架页只在"输入已变化"且被打开或被请求时才重新综合 | 全局 |

## 1. 核心功能

按草图的三列，加上使用与维护，共九块功能。

| # | 功能 | 做什么 | 草图依据 |
|---|---|---|---|
| F1 | **过程捕获** | 把操作、输出和自动可得的条件写入只追加的过程日志；会话、执行者、先后顺序由系统记录 | §2、§3、§13 |
| F2 | **原件登记与抽取** | 文件、对话、文献、数据集登记为原件：内容寻址保存，或只引用路径加指纹；可读文字放在原件的抽取层（按页等单元、带版式块和可信度档，可重建），按自然边界切段落；新版本用 `version_of` 链接 | §3、§12.1、设计稿 01 |
| F3 | **正式条目与读取记录** | 过程日志升级为事实记录（对象、条件、方法、结果、边界）；读到原件时自动留下读取日志（哪份、哪版、哪段、原文片段），不作为条目显示 | §2、§3、设计稿 01 D-03 |
| F4 | **判断层** | 写判断（AI 或人），引用依据；系统推出写入时可信度；判断之间的关系；人的更正、撤回和"原件有缺陷"；问题的"提问"与"针对" | §4、§5、§13 |
| F5 | **框架层** | 实体页、概念页、综合页、非文本原件的描述、关系图的边。每个条目生成时记下输入清单，带复核状态和时效 | §11 |
| F6 | **变化传播** | 新判断或新版本写入时，沿输入清单把受影响的框架条目标为"输入已变化"；只降不升 | §11.4 |
| F7 | **术语连接** | 三档：确定（别名表、标识）/ AI 较有把握 / 拿不准。人的决定写回判断层并加入别名表 | §12.3 |
| F8 | **检索与展开** | 全文检索按层过滤和排序；精确标识直接命中；按对象和时间过滤；对一条原件按四级展开背景；约束优先 | §7、§12.4 |
| F9 | **工作台与 agent 调用** | 待决策列表、输入已变化列表、条目查看、人工修改入口；在工作台直接启动本机 agent CLI（Claude Code、Codex 等），过程实时显示，输出留在运行日志 | §12.3、用户要求 |

## 2. 功能架构

```
            ┌──────────────── 接口层 interfaces ────────────────┐
            │  操作注册表 ops  →  CLI │ HTTP(工作台) │ MCP(agent) │
            └───────────────────────────────────────────────────┘
                              │ 只调服务
┌────────────── 服务层 services ──────────────────────────────────────────┐
│ capture   artifacts   records   judgments   framework   propagation      │
│ linking   retrieval   ranking   constraints decisions   agents(运行器)   │
└──────────────────────────────────────────────────────────────────────────┘
                              │ 只调存储与纯函数
┌── store ───────────────┐ ┌── index ─────────┐ ┌── core ────────────────────┐
│ ledger.sqlite（不可替代）│ │ index.sqlite      │ │ 模型、ID、引用、错误、     │
│ framework.sqlite（可再生）│ │ FTS5（可删除重建）│ │ 可信度推导、排序规则（纯函数）│
│ blobs/（内容寻址）       │ └──────────────────┘ └────────────────────────────┘
└────────────────────────┘
```

> 实际实现（核对于 2.0.0a10）：图中的 records、ranking、constraints、decisions 没有单独的服务模块。事实记录在 `services/artifacts.py`（`promote`）；排序规则在 `core/model.py`（`rank_key`），由 `services/retrieval.py` 使用；约束检查在 `services/retrieval.py`；待决策存于 `store/framework.py`（`add_decision`、`decisions`），由各服务生成。另有图中没有的 extraction、extractors、overview、checks、portability、import_v1。现行模块以 [ARCHITECTURE](../ARCHITECTURE.md) 的模块影响表为准。

**三份存储，按"能否再生"划分**（草图规则 ③）：

| 存储 | 内容 | 能否再生 | 写入规则 |
|---|---|---|---|
| `ledger.sqlite` + `blobs/` | 原件、过程日志、事实记录、读取记录、判断、判断间关系、原件的抽取记录（含嵌入图片、页面快照） | **不能**，是唯一需要备份的部分 | 只追加。数据库触发器拒绝 UPDATE 和 DELETE |
| `framework.sqlite` | 实体、别名、页面及其版本、图的边、派生输入清单、时效与复核状态、待决策项、agent 运行状态 | 能，但重建要花 AI 成本，所以默认保留 | 可修改；页面改写一律新增版本 |
| `index.sqlite` | 片段全文索引 | 能，随时可删除重建 | 每条记下它依据的条目和版本，过期条目不返回 |

**写入方向**：服务层只通过 `store` 写数据。框架层永远不能作为依据（规则 ①）：判断引用框架条目时，在服务层直接拒绝。

**谁写什么**在操作上的落实：每个操作带 `effect` 标记（沿用 burrowl）：

- `read`、`write`：MCP、HTTP、CLI 都开放；
- `user`：只在工作台和 CLI 开放，不出现在 MCP 工具列表中。更正、撤回、"原件有缺陷"、复核结论、术语连接决定都属于这一类。

调用者身份由接口层写入上下文，不能由参数指定：MCP 调用一律记为 AI，工作台和 CLI 记为人。

## 3. 技术实现架构

### 3.1 选型与借鉴

| 方面 | 选择 | 借鉴自 | 理由 |
|---|---|---|---|
| 语言与运行 | Python 3.12，uv 管理，src 布局 | burrowl | 沿用已验证的 Windows 本地环境 |
| 权威存储 | **SQLite（WAL）**，每张表"若干索引列 + 一个 JSON `data` 列" | Veracium（`id` + 索引列 + `json`）、Mem0 的 history 表、gbrain 的 frontmatter JSONB | 单文件、零运维、通用工具都能打开；新增字段放进 JSON，不需要改表 |
| 只追加的保证 | SQLite 触发器 `BEFORE UPDATE/DELETE … RAISE(ABORT)` | Ground Truth First / Veracium 的"取代而不删除" | 由数据库强制，不依赖代码自觉 |
| 大文件 | 内容寻址目录 `blobs/sha256/ab/cdef…`；也可以只登记外部路径加 sha256 | git-annex、DVC、burrowl 的 attachments | 通用做法，去重、可校验；工业大文件可以留在原处 |
| 结构迁移 | 编号的 SQL 迁移文件，加 `schema_migrations` 表；`meta` 表记录数据格式版本 | gbrain、Veracium 的 schema 版本 | 标准做法；旧数据永远可读 |
| 可移植格式 | 每张表可以导出为 JSONL；框架页导出为 Markdown + YAML frontmatter（与 Obsidian 兼容）；字段用 JSON Schema 描述（由 pydantic 生成） | Karpathy LLM Wiki、gbrain、burrowl 的交换包 | 大版本升级时可以通过"导出再导入"迁移，不依赖内部表结构 |
| ID | `<前缀>_<ULID>`（26 位，按时间排序） | 通用 | 可读的类型前缀，可以排序，可以离线生成 |
| 关系命名 | 尽量对应 W3C PROV：`used`（引用依据）、`wasDerivedFrom`、`wasRevisionOf`、`wasAttributedTo` | W3C PROV | 标准词表，便于以后对接外部系统 |
| 派生输入清单 | `derivation_inputs(derived_kind, derived_id, derived_version, input_id)`，加反向索引 | gbrain 的 `derivation_inputs`，**但加上版本**，并真正用于传播 | 源码阅读发现：gbrain 只记行 ID、不记版本，也没有用于传播 |
| 全文检索 | SQLite FTS5，trigram 分词（中文可用）；查询不足 3 个字时退回 LIKE。**2.0.0a13 起由设计稿 06 取代**：检索单元 + 双字切词 + OR + bm25，可选向量与重排 | burrowl（FTS5）、gbrain（Postgres FTS） | 不需要额外依赖。向量检索作为可选的后端接口预留，本版不实现 |
| 接口 | 一份操作注册表，生成 CLI（Typer）、HTTP（FastAPI）、MCP（官方 Python SDK） | burrowl 的 `interfaces/ops/registry.py` | 一个操作只写一次，三个入口行为一致；参数由 pydantic 校验 |
| 错误 | `BurrowlError(code, message, details)`，在接口层分别转成 HTTP Problem JSON、MCP 工具错误和退出码 | burrowl | 已验证有效 |
| 工作台 | FastAPI 只监听 127.0.0.1，带 token；React + Vite 前端，构建产物随包分发 | burrowl | 沿用 |
| AI 调用 | 服务端**不直接调用模型 API**。AI 工作由 agent 通过 MCP 完成；工作台通过"agent 运行器"启动本机 agent CLI | burrowl 的 MCP 配置方式 | 与模型无关，不在服务端保存密钥；可以接任何支持 MCP 的 agent |
| 依赖方向 | `interfaces → services → store / index → core`，由 import-linter 检查 | burrowl | 让变化局部化 |

**没有采用的做法**：

| 做法 | 来源 | 不采用的原因 |
|---|---|---|
| Postgres 加 3700 行表结构 | gbrain | 本地单用户场景运维太重；表随功能无限增长 |
| 图数据库（Neo4j 等） | Graphiti | 图是框架层，可以再生；用 SQLite 的边表就够了，需要时再投影到图库 |
| 不可变文件提交加 HEAD 的自定义格式 | burrowl | 格式独特，迁移成本高；SQLite 加 JSONL 导出更通用 |
| 每份规范都要求 spec 治理 | Veracium | 治理成本远高于收益 |
| 服务端内置 LLM 抽取 | Mem0、Graphiti、GraphRAG | 抽取结果就是框架；由 agent 在使用时生成，并按规则标注 |

### 3.2 数据结构

所有表都有 `id TEXT PRIMARY KEY`、`created_at`（ISO 8601 UTC）和 `data JSON`。下面只列索引列和关键字段。

**ledger.sqlite（只追加）**

| 表 | 关键列 | 说明 |
|---|---|---|
| `artifacts` 原件 | `kind`（file / conversation / literature / dataset / image / log）、`source_class`（local / external / inferred；D-14 前为 executed / external / discussion）、`sha256`、`storage`（managed / referenced）、`uri`、`version_of`、`captured_by`、`session_id` | `data`：标题、媒体类型、大小、外部报告细分（`external_tier`：peer_reviewed / preprint / vendor / web）、可核对的元数据 |
| `events` 过程日志 | `session_id`、`seq`、`actor_id`、`actor_kind`（human / ai / system）、`op`、`objects`（JSON 数组） | `data`：输入、输出（长输出存为 blob）、自动获得的条件 |
| `records` 事实记录 | `event_id` 或 `artifact_id`、`objects`、`boundary`（complete / truncated / partial / restricted） | `data`：条件、方法、结果（逐字）、缺口、升级理由 |
| `reads` 读取记录 | `artifact_id`、`artifact_sha256`、`locator`、`session_id`、`actor_id` | `data`：读到的原文片段、段落序号与 `anchors`、段落指纹、可信度档。自动日志，不作为条目显示（设计稿 01 D-03） |
| `extractions` 抽取记录 | `artifact_id`、`artifact_sha256`、`kind`（manifest / content / verification / snapshot）、`unit`、`actor_id` | 原件的抽取层（设计稿 01 D-10）：单元清单；某单元的文本、版式块、方法、可信度档；人的确认；页面快照 PDF 的指纹。当前抽取层 = 每个单元最新的 content。文本原件不写（原样复制，确定） |
| `judgments` 判断 | `kind`（conclusion / process / normative，系统记录 review / correction / retraction / defect / retirement；D-14 前为 12 种；retirement 见设计稿 02）、`author_id`、`author_kind`、`revises` | `data`：正文、条件、对象、外部作者、提取者；**写入时可信度**（由系统根据依据推出：来源类型集合、是否包含亲自执行、依据是否完整、外部报告细分）；`cited_segments`（引用的原件段落及其指纹、可信度档）；`citation_notices`（未读先引、引用未确认的识别文本） |
| `links` 判断间关系 | `rel`、`src_id`、`dst_id`、`author_id` | rel 取值：`used`（依据）、`depends_on`、`supports`、`opposes`、`answers`、`targets`（针对问题）、`supersedes`、`coexists_under`、`corrects`、`retracts`、`defect_of`、`wasRevisionOf`、`retires`（原件退役，设计稿 02）；`documents`（事实记录的出处）、`consumed` / `produced`（过程日志用到 / 产出的原件，设计稿 07）。`data`：理由、条件 |

**framework.sqlite（可修改，页面版本只增）**

| 表 | 关键列 | 说明 |
|---|---|---|
| `entities` | `kind`（device / system / material / person / concept / method / term）、`name` | 图的节点 |
| `aliases` | `alias`（归一化后）、`entity_id`、`decided_by`（判断 ID 或 `rule`） | 别名表；人的连接决定会写入这里 |
| `pages` | `type`（entity / concept / synthesis / description）、`slug`、`subject_id`、`head_version`、`freshness`（valid / inputs_changed / superseded / unchecked）、`review`（ai_generated / human_reviewed / rejected） | 页面头 |
| `page_versions` | `page_id`、`version`、`author_id` | `data`：Markdown 正文、摘要、生成方式 |
| `edges` | `rel`、`src_id`、`dst_id`、`origin`（projection / mechanical / ai_inferred / candidate）、`review`、`freshness` | 关系图的边 |
| `derivation_inputs` | `derived_kind`、`derived_id`、`derived_version`、`input_id` | 主键是这四列；按 `input_id` 建反向索引 |
| `decisions` 待决策 | `kind`（term_link / review / rederive / constraint_unchecked / propagation_overflow）、`status`（open / resolved / dismissed）、`impact` | `data`：候选、原文片段、处理结果 |
| `agent_runs` | `status`、`agent`、`session_id` | `data`：命令、提示词、退出码；输出另存为运行日志 |

**index.sqlite（可删除重建）**：`segments(artifact_id, ordinal, locator, sha256, text)` 加 FTS5 虚表；判断和框架页也各建一张 FTS 表。每行记下来源条目和版本；`meta` 中记录分段器版本，版本不一致时整库重建。

### 3.3 关键流程

1. **导入原件**：计算 sha256 → 登记 artifact（与已有版本内容相同时幂等）→ 按设置抽取（PDF、PPT、Word 自动；图片、音视频只登记单元）→ 按自然边界分段并建索引 → 记一条过程事件 → 机械连接（别名命中的实体建 `mentions` 边）→ 草图 §12.2 的框架维护（本版只做连接和时间线；建页由 agent 来做）。如果是新版本，就比较片段，引用已变化片段的框架条目标为"输入已变化"。
2. **写判断**：校验所有依据都在左边两列（原件、事实记录、读取记录、判断），不在就拒绝；原件段落要存在，记下段落指纹，未读先引、引用未确认的识别文本只提示 → 系统推出写入时可信度 → 写 `judgments` 和 `links(used)` → 传播：查 `derivation_inputs` 中引用了这些依据的、以及涉及同一对象的框架条目，标为"输入已变化"。
3. **人工修改**（effect=user）：写一条 `correction` / `retraction` / `defect` 判断，加上对应的关系 → 走同样的传播流程。
4. **框架页写入**（AI 通过 MCP）：给出正文和输入清单 → 新增页面版本，记录 `derivation_inputs`，时效设为"有效"、复核状态设为"AI 生成" → 生成一条待复核的待决策项。
5. **检索**：FTS 命中 → 按层过滤 → 排除被驳回和已被替代的 → 按草图 §12.4 逐级排序 → 与查询对象相关的约束放在最前 → 返回每条命中的地位坐标。
6. **agent 运行**：工作台提交任务 → 运行器按配置的命令模板启动子进程，例如 `claude -p {prompt} --mcp-config {mcp}` 或 `codex exec {prompt}` → 输出通过 SSE 实时推送 → 输出保存在运行日志。agent 运行期间通过 MCP 回到本服务读写。

### 3.4 兼容性与升级

- **数据格式版本**写在 `meta.format_version`。迁移只增不删：新增列或表；含义变化时新增字段，旧字段继续可读。
- **导出与导入**：`burrowl export <目录>` 输出每张表一个 JSONL 文件，加 `blobs/` 和 `manifest.json`；`burrowl import` 是反向操作。大版本升级可以完全靠它完成。
- **JSON Schema**：所有条目模型都由 pydantic 生成 schema，放在 `schemas/`，外部工具可以按它校验。
- **扩展点**：Python 入口点 `burrowl.ops`（新操作）、`burrowl.segmenters`（新格式的分段器）、`burrowl.agents`（新的 agent 运行器）。

## 4. 测试项

| 测试 | 验证什么 | 对应规则 |
|---|---|---|
| `test_ledger_append_only` | 对 ledger 各表执行 UPDATE 或 DELETE 一律失败 | §2 只追加 |
| `test_migrations` | 新库迁移到最新；重复执行幂等；记录格式版本 | §3.4 |
| `test_artifact_import` | 同内容幂等；外部引用存指纹；分段带定位；新版本差异会标记下游 | F2、§0 文献新版本 |
| `test_judgment_rules` | 不能引用框架条目；写入时可信度由系统推出，参数不能指定；混合来源列出全部；只有全部依据为本地实证时才算"我们验证过的" | 规则 ①②、§13 |
| `test_actor_rules` | 通过 MCP 写的判断作者是 AI；MCP 工具列表中没有 user 类操作；AI 不能更正或撤回 | §4、§13 |
| `test_propagation` | 新判断、更正、撤回、新版本都会把下游框架条目标为"输入已变化"；有传递上限；只降不升 | §11.4 |
| `test_linking` | 三档分流；人的决定写回判断层并加入别名表，同一叫法下次落入"确定"档 | §12.3 |
| `test_retrieval` | 排序逐级比较；约束在最前；已被替代的仍可检索但带标注；索引版本过期时不返回 | §7、§12.4 |
| `test_ops_interfaces` | 同一操作在 CLI、HTTP、MCP 结果一致；参数错误一次列全 | §2 |
| `test_agent_runner` | 用一个假的 agent 命令验证：输出可流式读取且留在运行日志 | F9 |

## 5. 本版不做

向量检索、重排、图可视化、知识中枢连接器、导入时由服务端自动建页（交给 agent）、多用户权限、安装打包。接口已经预留。

> 之后的进展：图可视化、安装打包已在 2.0.0a2–a7 实现；向量检索、重排、联想模式见[设计稿 06](design/06-retrieval-units-and-hybrid-search.md)（2.0.0a13）。

## 6. 进度记录

### v2.0.0a1（2026-11-04）

**已实现**：F1–F9 全部有第一版。

- 后端：`core` / `store` / `index` / `services` / `interfaces` 五层，由 import-linter 检查依赖方向。
- 接口：同一份操作注册表生成 CLI、HTTP、MCP。MCP 共 25 个工具；`user` / `admin` 类操作不在 MCP 中。
- 工作台：概览、检索、条目（含人工修改入口）、框架页（含复核）、待决策（含术语决定）、记录（人写原件和判断）、Agent（启动本机 agent CLI，输出实时显示）。

**验证**：

| 检查 | 结果 |
|---|---|
| pytest | 38 项通过 |
| ruff | 通过 |
| lint-imports | 1 个契约保持 |
| 前端 vitest | 2 项通过 |
| 前端 tsc | 通过 |
| 前端 vite build | 通过 |
| MCP 真实 stdio 往返 | 通过：工具列表中没有 `judgment_amend`；AI 写撤回被拒 |
| 浏览器手动检查 | 概览、检索、框架页、待决策、Agent 页都已检查；演示 agent 以运行身份写入判断，输出登记为对话原件 |

**实施中按实测修改的两处**：

1. 用精确标识（设备编号）检索时，会带出内部的过程日志。已改为默认不返回过程日志，加 `include_log` 才返回（草图 §2）。
2. 人写的约束原本被标成"推断或讨论 · 依据不完整"。约束、决定、指令规定该怎么做，不陈述世界怎样，所以写入时可信度加上 `normative`，不再参与真假排序（DESIGN §0）。

**已知差距**（下一版处理）：

- 身份靠入口和环境变量区分：命令行中设置了 `BURROWL_ACTOR_ID=ai:…` 才记为 AI。本机进程可以伪造这个变量，第一版不防范。
- 术语连接的候选只按名称包含关系查找，没有考虑条件冲突，也没有用到向量相似度。
- 待决策页中，复核理由与关闭理由共用一个输入框。
- 非文本原件（图片、波形）只能登记和挂描述页，没有抽取。
- 导入时由服务端自动建实体页（草图 §12.2）尚未实现，目前交给 agent。
- 没有评测：冷读者测试、MINT-Eval 子集、ALCOA+ 检查清单（草图 §10）都还没有接入。

## 7. 旧版数据导入

`burrowl call data.import_v1 source=<旧版数据目录>` 把旧版 burrowl（0.x）的数据导入到一个**新的空数据目录**。

- 导入只读旧目录，不改动其中任何文件。用真实旧数据试跑时，前后对整个目录做了指纹核对。
- 只能由人发起：命令行或工作台可以执行，MCP 中不提供。

**映射规则**：

| 旧版 | 新版 |
|---|---|
| 对象业务卡（research.json 等） | 框架：实体（kind=project）；所有导入条目的对象都带上它 |
| 来源登记 | 原件：20 MB 以内复制保存，更大的只登记路径和指纹；原件已不在时用原文快照；两者都没有时记为缺口 |
| 图片附件 | 原件（image） |
| Run 业务卡及其产出 | 原件，依据来源为本地实证 |
| L0 来源记录 | 指向它的原件；正文作为挂在原件上的描述页 |
| L1 导入原文 | 原件，各修订用 `version_of` 串起 |
| L2 叙述、L3 经验 | 判断，各修订用 `revises` 串起；`payload.claims` 中的每条结论另成一条判断 |
| 复核 | 人做的 → 复核判断，并按状态加上 supports / retracts / supersedes 关系；AI 做的 → 普通判断 |
| L4 概览、文稿、文稿章节 | 框架：综合页 |
| 关联 | 框架：AI 推断的边（related） |

**几项具体规定**：

- 旧版没有"依据来源"这一轴。除 Run 外，导入的原件都记为"推断"，并在元数据中注明"导入时未知"。
- 旧记录除正文外的全部字段原样保存在 `data.v1` 中。
- 正文里的旧链接改写为新 ID。

**按决定，旧数据暂不迁移**：旧数据目录原地归档。新版遇到旧格式目录会拒绝打开（OLD_FORMAT），以免在里面建新库。

## 8. 全局安装

布局与旧版相同，直接替换旧版的安装位置：

```
<Root>\versions\<版本>\   完整版本目录，自带 Python
<Root>\current            目录联接，指向当前版本
<Root>\bin\burrowl.cmd    在 PATH 中
```

- **构建与安装**：
  - 构建：`uv run python packaging/build.py`；
  - 构建后直接安装：`uv run python packaging/build.py --install`。
  - 安装脚本由旧版 `setup.ps1` 生成，只改了两处：不处理模型目录；自检改为 `burrowl version`。
- **数据目录**：
  - 优先级：`--data`（兼容旧写法 `--data-dir`）→ `BURROWL_DATA` → `burrowl init` 登记的默认目录。
  - 登记文件是 `<Root>\workspaces-v2.json`，不读旧版的 `workspaces.json`；每个目录有一个名称（默认取目录名，用在网址 `?db=` 里）。
- **工作台**：`burrowl start` / `stop` / `restart` / `status` / `open`。开始菜单的快捷方式运行的是 `burrowl open`。
  - 整个安装只有一个工作台进程，管理所有登记的数据目录（D-18）；状态文件是 `<Root>\server.json`。
- **MCP**：
  - 服务名仍是 `burrowl`。
  - 不带 `--data` 登记时跟着默认数据目录走（每次调用重新取）；带 `--data` 时固定连它，要连多个目录就登记多条。
  - 兼容旧版客户端的登记方式：`python -m burrowl.interfaces.cli mcp --data-dir X --mode auto`（固定连 X）。
- **Skill**：
  - 仍是 burrowl-work、burrowl-read、burrowl-consolidate 三个，加公共规则 RULES.md，内容按新模型重写。
  - `burrowl upgrade` 由安装脚本调用，读取与旧版格式相同的 `burrowl-install.json`，规则如下：
    - 替换没被用户改过的旧文件；
    - 删除旧版独有、也没被改过的文件，例如 recording.md；
    - 用户改过的文件保留并列出。

**已验证**：

| 检查 | 结果 |
|---|---|
| 打包 | 37 MB，包内自检通过 |
| 安装到临时根目录 | 通过（带 `-NoPath -NoShortcut`，不改系统） |
| `init` / `call` / `start` / `restart` / `stop` / `status` | 通过 |
| 旧格式数据目录 | 被拒绝 |
| MCP 往返 | 通过：用旧版的登记参数从安装后的解释器启动，25 个工具，不含 user 类操作 |

- 试装时用 `--install --root <目录>`，会自动带上 `-NoPath -NoShortcut`，不改用户 PATH、`BURROWL_ROOT` 和开始菜单快捷方式。
  - 这条规定的来由：试装时漏掉了这两个参数，改到了正式的这三项。已经恢复，并核对旧版 Skill 文件没有被改动。

**尚未执行**：切换本机的正式安装，即第二步。

## 9. 工作台（参考旧版布局，2026-11-05）

只改展示与交互，不改写入规则和数据结构。

**界面原则**（2026-11-11，用户确认只写原则，具体做法随版本调整）：
1. **地位先于内容**：条目出现的每个地方都标出所在的列与当前地位。原件绿、判断蓝、框架橙是语义色，全站一致，不挪作装饰；框架内容处处提示不能作为依据。
2. **档次分开显示**：人已复核、AI 已复核、AI 已核对、未确认的识别是不同的档，不用同一种"通过"标记。前端只显示服务端算出的地位，不自行推导。
3. **证据一步可达**：从结论能直接回到所引原件的段落。
4. **过时内容可见、可筛**：被替代、撤回、退役、依据失效的内容默认靠后或收起，同时有专门的筛选把它们集中列出，不靠隐藏来表达。
5. **用词与后果一致**：修改都是追加（更正、撤回、退役、替换），界面不用"编辑"暗示改写历史；彻底删除只用于已退役的内容，先预览影响再输入确认。确认的轻重跟着后果走。
6. **边界看得见**：只有人能做的操作只在工作台出现；会把内容交给大模型或外部 agent 的按钮写明交给谁。
7. **下一步可见**：暂时不能用的按钮灰掉并写明原因和去处，不隐藏；长任务显示状态、失败原因和日志位置，可以重试。
8. **常用的操作靠近对象**：作用于本条的操作放在本条的标题栏，去别处的入口与之分开；低频、需要写理由的修改默认收起。
9. **装饰不承载信息**：动效与装饰只为辨识和观感；动画停住时内容必须完整可见，系统要求减少动效时关闭；不依赖网络资源，离线可用。

**新增的只读操作**：
- `activity.recent`：最近操作；
- `stats.overview`：首页计数；
- `entries.list`：条目浏览；
- `graph.view`：关系图。

它们只汇总已有数据，不写入任何内容。

**新增的服务控制**：`server.info`、`server.restart`、`server.stop`。
- 重启和停止是 user 类操作，只在工作台进程里有效，MCP 中不出现。
- 重启时先启动新进程，等旧进程让出端口后再接管同一个网址。安装后的新进程经由 `current` 下的启动器启动，所以会加载新安装的版本。
- `index.html` 不缓存，重启后页面自动加载新的前端。

**页面**：
- 布局：左侧导航，分"工作"和"治理"两组，待决策、输入已变化的页数、运行中的 agent 显示为徽标；哈希路由 `#/页面/ID`。
- 首页：
  - 主栏是最近关键操作，按天分组成时间线；
  - 侧栏只放两张卡（2026-11-05 按用户意见精简）："待你处理"（按类型列出有数量的待决策，附说明与去处理的链接）；"正在进行"（运行中的 agent、已安装待生效的新版本，以及重启、停止服务）。判断的地位分布与框架统计不放首页，`stats.overview` 仍保留。
- 筛选条：
  - 检索：模式、列、依据来源、判断类型、是否显示被替代的、是否包含过程日志；
  - 条目：类型、当前地位（当前有效 / 被替代或撤回 / 已退役 / 依据失效，2026-11-11）、判断类型、作者、依据来源、对象、文字；
  - 框架页：类型、时效、复核、标题；
  - 待决策：类型和状态；
  - Agent：运行状态。
- 关系图：
  - 节点按三列着色，用形状区分类型；连线按关系类别区分线型；AI 推断的边用橙色虚线；已被替代的节点用红色虚线边框。
  - 可以按节点类型和关系类别筛选；支持中心加展开层数、双击换中心、隐藏后恢复、悬停说明、图例。
  - 视图记在浏览器本地。
  - 2026-11-11 起画布是深色"夜空"（浅色、深色主题相同）：节点带同色柔光、按相连数放大，依据、输入、提及等边按两端节点颜色渐变，AI 推断的边缓慢流动；画布占满整宽，图例与节点详情是画布上的浮层。颜色语义不变，只为深色底调亮。
- 第一次启动工作台时，从 8766 开始自动找空闲端口；侧栏顶部切换数据目录。

**待开发**（用户 2026-11-05 确认，后续需要）：
- **阅读会话**：旧版的"可见阅读会话"（筛选、笔记、等待用户回复）。新版目前只有 `search`、`entry.expand` 和读取记录，没有会话这一层。需要先讨论它在三列模型里的位置：读取记录属于原件一列，阅读笔记属于判断还是框架，要先定。
- **维护计划**：旧版的维护与监测（计划 → 处置 → 用户执行）。新版的"输入已变化"加待决策只覆盖了一部分。批量维护计划的形态待讨论。其中定期巡检已实现，见[设计稿 08](design/08-periodic-inspection.md)。

## 条目版本（2.0.0a23）

条目各版本保有原账本 ID，版本组和状态使用只追加关系。默认列表与检索显示各组最新的有效版。发布时新版自动具备生效资格，旧版仅在人工重新生效后具备资格。最新有效版不存在时不自动回退，销毁最新版后只保留存续组的版号上限。引用仍固定在原版，条目读取附上历史；旧更正、撤回与缺陷显示在被处置条目的历史中。撤回最新版不会恢复旧版。取消撤回只恢复指定版本的主张状态，仍保留撤回理由，最新版、引用与退役状态各自独立。取消缺陷标记只清除该版的当前缺陷状态，保留标记和取消的理由，适用于旧版缺陷记录。更正过程或事实记录时保留原始输出与出处，事后核实单列。销毁须先退役并确认预览，其他版本和外部引用保留；销毁版内容和组成员记录一并移除。原有非版本原件的销毁继续走设计稿 07。
