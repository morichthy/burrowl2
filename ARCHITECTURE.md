# 技术架构

本页只维护**现行**的约束、模块、影响关系、状态归属和已知差距。改代码前先在"模块影响表"里找到要改的模块，再沿"改动时一并检查"一列核对，避免漏掉互相影响的地方。

- 用途与用法：[README](README.md)；功能与流程：[docs/CORE](docs/CORE.md)；术语：[docs/GLOSSARY](docs/GLOSSARY.md)；理由与历史：[docs/DEVELOPMENT_HISTORY](docs/DEVELOPMENT_HISTORY.md)。

## 评价标准

1. **控制依赖，让变化局部化**：按变化原因划分模块，上层只依赖下层。
2. **控制状态，让行为可推理**：每类状态只有一个权威来源和明确的转换；能再生的就不当成权威。
3. **用证据说话**：功能是否正确由测试证明；检索与排序的效果用可重复的评测证明，不凭感觉调。

## 不变式（必须守住）

| # | 不变式 | 由什么保证 | 破坏后的后果 |
|---|---|---|---|
| I1 | 账本只追加：`artifacts / events / records / reads / judgments / links / entry_objects / extractions / reviews / retirements` 不 UPDATE、不 DELETE | 数据库触发器（`store/migrations/ledger`）；`tests/test_store.py` | 历史被改写，判断层失去"当时谁认为了什么"的意义 |
| I2 | 框架永远不能作为依据 | `JudgmentService.basis_of` 拒绝框架 ID（含正文 `[[ID]]`） | 框架污染进入判断层（K2） |
| I3 | 写入时可信度由系统根据依据推出；本地实证只能由人标记 | `core/model.derive_credibility`；`judgment.write` 没有可信度参数，`local_observation` 对 AI 报 FORBIDDEN | AI 自评可信（Memory Reward Inflation） |
| I4 | 调用者身份由入口决定 | `interfaces/runtime.actor_for`：MCP 一律是 AI；命令行在 `BURROWL_ACTOR_ID=ai:…` 时是 AI；本地模型自动写入时是系统（`system:model`），大模型核对识别结果时是系统（`system:llm`，记下发起的人） | AI 冒充人做更正、复核 |
| I5 | 只能由人做的操作：更正、撤回、原件缺陷、原件退役、复核（`review.submit` 与别名 `framework.review`）、确认抽取、术语决定、启动/停止 agent、服务控制、导入旧版。AI 复核（`review.ai_submit`）是另一种操作：记录里方式为 AI，只产生"AI 已复核"或把条目留在 / 排到待决策前面，不产生"人已复核""被驳回"，不写回判断层（设计稿 04 D-12 至 D-14）；"请人复核"（`review.request`）只是加入待决策列表，AI 也可以调用。识别结果的 AI 核对（`extraction.ai_check`）只能由人发起，结果是"AI 已核对"，不等于确认抽取（设计稿 04 D-22 至 D-24）。按需启动 MinerU 只运行人在设置里填写的命令，AI 不能修改（设计稿 05 D-19） | `effect="user"/"admin"`（MCP 不注册、`registry.call` 拒绝）；服务内 `actor.require_human`；`ReviewService.ai_submit` 的限制（依据只能是原件层与判断层、先读后复核、不复核本会话写的、只复核 AI 生成未复核的条目） | 判断层被 AI 改写 |
| I6 | 变化只在框架层传播，只降不升 | `services/propagation.py`；`DOWNGRADE_ORDER` | 下游悄悄过时，或被错误"升级" |
| I7 | 派生条目的输入清单指向**固定版本** | `derivation_inputs` 记 `derived_version`；页面引用写 `pg_…@N` | 传播找不到受影响的框架 |
| I8 | 落盘格式只增不改，旧数据永远可读 | 编号迁移（只新增）；`FORMAT_VERSION`；导出导入按列名对齐 | 升级后读不了旧数据 |
| I9 | 索引可以随时删除重建；检索不返回旧版本的索引行 | `Workspace.rebuild_index`；`RetrievalService.search` 核对页面版本 | 旧内容残留在检索结果里 |
| I10 | 新版不打开旧版数据目录 | `Workspace.__init__` 发现 `.burrowl/` 且无 `ledger.sqlite` 时报 OLD_FORMAT | 在旧目录里建新库，旧数据读不到 |
| I11 | 过程内容不能作为结论的依据 | `JudgmentService._reject_process_evidence`；探索模式默认不返回过程内容 | 思路混进证据链（K2），探索被已有思路带偏（1.8） |
| I12 | 工作台只自动调用本地模型（专用模型、地址是本机）；大模型只在人显式调用时才调用 | `ModelService.can_auto`（`llm` 槽位永远为否、非本机地址为否）；`recognize_formulas(engine="llm")` 要求是人；`tests/test_models.py` 断言登记、补抽中不调用大模型 | 原件在没人决定时被发给通用大模型或别的机器（设计稿 05 §2） |

## 分层与依赖

```
interfaces   操作注册表 ops → CLI（Typer）│ HTTP 工作台（FastAPI）│ MCP（官方 SDK）；安装、后台服务
services     workspace（组合根）、capture、artifacts、judgments、framework、propagation、linking、
             retrieval、overview、agents、portability、import_v1
store │ index   store：SQLite 连接与迁移、账本仓库、框架仓库、内容寻址 blobs；
                index：分段、切词、检索单元、FTS5、嵌入与重排模型的加载（设计稿 06）
core         模型取值与规则（纯函数）、ID、引用、错误、身份、时间、哈希、事务辅助
```

- 上层只能导入下层，store 与 index 互不导入（`pyproject.toml` 的 import-linter 契约）。
- 服务之间不在模块级互相导入，只通过 `Workspace` 的属性互相调用（`ws.judgments`、`ws.propagation`……），装配集中在 `services/workspace.py`。
- 错误统一为 `BurrowlError(code, message, details)`，在接口层转为 HTTP 状态码、MCP 工具错误和命令行退出码。

## 模块影响表

路径相对于 `src/burrowl/`。**改一个模块时，"改动时一并检查"列中的每一项都要看一遍**；`tests/test_docs.py` 会检查本表覆盖了全部源文件。

| 模块 | 文件 | 职责 | 改动时一并检查 |
|---|---|---|---|
| MODEL 模型与规则 | `core/model.py` | 两个轴（`SOURCE_CLASSES`）、判断类型（`WRITABLE_KINDS`、`SYSTEM_KINDS`）、关系（含 `EVIDENTIAL_RELS`）、页面与边的状态取值；`derive_credibility`；`rank_key` | judgments（写入校验）、retrieval（坐标与排序）、overview（统计口径）、propagation（`SUPERSEDING_RELS`）、前端 `labels.ts`（中文名与颜色）、`skills/RULES.md` 的描述、`docs/GLOSSARY` |
| CORE 其他基础 | `core/ids.py`、`core/refs.py`、`core/actor.py`、`core/errors.py`、`core/clock.py`、`core/hashing.py`、`core/sql.py`、`__init__.py`、`__main__.py` | ID 前缀与格式、`[[ID]]` 引用、调用者身份、错误、版本号与 `FORMAT_VERSION` | ID 或引用格式 → 前端 `ui.tsx` 的 RefText 正则、`router.ts`；新前缀 → `store/ledger.TABLE_OF_PREFIX`、`Workspace.get`、overview 图节点类型；版本号 → `pyproject.toml`、`frontend/package.json` 同步 |
| STORE 存储 | `store/db.py`、`store/ledger.py`、`store/framework.py`、`store/blobs.py`、`store/migrations/**` | 连接与迁移、账本仓库（只插入）、框架仓库、内容寻址文件 | **新增表或列** → 新迁移文件（不改旧文件）、`portability.LEDGER_TABLES/FRAMEWORK_TABLES`、`import_v1`、`tests/test_store.LEDGER_TABLES`；账本新表必须加不可改触发器；含义变化 → `FORMAT_VERSION` 与导入兼容 |
| IDX 索引 | `index/segment.py`、`index/fts.py`、`index/tokenize.py`、`index/units.py`、`index/embed.py`、`index/rerank.py` | 按自然边界分段（`seg:N`）；引用段落表 `docs`（trigram：短语路、字面查找）；检索单元表 `units`（相邻段落合并、机械上下文、双字切词、OR + bm25）；向量缓存 `vectors`（按内容指纹，`clear` 不删）；本地 ONNX 嵌入（平均池化）与 Cross-encoder 重排的加载与指纹（设计稿 06） | 分段规则 → 升 `SEGMENTER_VERSION`；切词 → `TOKENIZER_VERSION`；检索单元规则或默认长度 → `UNITS_VERSION`（任一变化启动时整库重建，`Workspace.INDEX_VERSION`）；数据目录的单元长度设置 `index.units_*` 由 `build_units` 的参数接收，非默认值写进 `Workspace.index_version()`，保存设置时重建（设计稿 06 D-22）；`segment.MAX_CHARS` 决定文本原件的 `seg-N`，不能做成设置；单元上限 `units.MAX` 必须小于重排模型的输入上限；定位格式 `seg:N` / `#seg-N` / `#p3-2` / 段落范围 `p3-8:p3-12` → extraction.select / find、retrieval.expand、judgments 的段落引用、前端检索结果与原件页 |
| WS 组合根 | `services/workspace.py` | 打开三个库、迁移、装配各服务、`rebuild_index`（`INDEX_VERSION` 不一致时启动即重建）、默认配置与 `save_config`、`refresh_config`（`config.json` 被别的进程改过就重读）、`unit_options` / `index_version` / `index_stale`（检索单元长度设置与索引版本）、数据目录的锁（`lock`、`unlocked`） | 新服务在这里装配；默认配置（agents、传播上限、连接阈值、抽取方式、索引方式与嵌入模型、重排）→ README、DESIGN §0、ops 的 `SETTING_CHOICES`、前端 Settings；在请求线程之外读写账本的代码必须先取 `lock` |
| CAP 过程捕获 | `services/capture.py` | 过程日志（只追加）；长输出存 blob；触发"操作前未检查约束" | retrieval 的约束检查、`INTERNAL_OPS` 前缀 |
| ART 原件 | `services/artifacts.py` | 登记（受管 / 外部引用）、原件文件位置（外部原件先核指纹）、索引、读取记录、事实记录升级（条件不能补写）、新版本差异传播（含 `cited_segments`） | extraction（段落来源）、linking（导入时机械连接）、propagation、judgments.basis_of（原件的依据来源） |
| EXT 抽取层 | `services/extraction.py`、`services/extractors.py`、`services/pdf_layout.py` | 原件的单元清单、按单元的文字与版式块、可信度档与人的确认、重建与待复核（含抽取器升级后的补抽重建）、页面快照与页面图像、段落引用检查（设计稿 01）；PDF 按字符位置分段，块带 `box`，页眉页脚标为 `furniture`（设计稿 02 D-03、D-04）；按数学字体识别行间公式块 `formula`、行内公式段落标 `math`（设计稿 03 D-15）；公式块的 LaTeX 补充（复制一条 content、只在块上加 `latex` 与 `latex_source`，文字与锚点不变，重新抽取时按文字保留，D-17）；Excel 按工作表抽取表格块（带单元格范围 `range`，D-11）；各格式按 `FORMAT_VERSION_SINCE` 判断是否要重建；页面区域裁切图（`clip`）、单块裁切图给 AI（`artifact_view` 的 `anchor`）与快照 PDF 字节 | 新格式或抽取结果变化 → 升 `EXTRACTOR_VERSION`（已有原件由 `extraction.backfill` 重建，引用已变段落的判断进入待复核）；块的 `box` 格式 → 前端 `pages/Faithful.tsx` 的叠加层、`reader/marks.ts` 与 `viewers/pdfjs`；块类型（`formula`、`math`）与字段（`latex`、`range`）→ 前端 `pages/Artifact.tsx` 的 BlockView、`reader/marks.ts`、`viewers/sheet`；某个格式的抽取结果变化 → 同时改 `FORMAT_VERSION_SINCE`，否则补抽不会重建它；段落格式 → IDX、judgments、前端 Artifact；单元或块的字段 → 前端 `pages/Artifact.tsx`；可信度档 → `labels.FIDELITY`、Skills；快照转换器 → 设置页与 README |
| JDG 判断 | `services/judgments.py` | 写判断与关系、依据校验与可信度推导、原件段落引用（`cited_segments`、未读先引、低可信度、已退役原件、待复核判断的提示）、人工修改入口（更正、撤回、缺陷）、当前主张状态、原件退役与恢复（`retire`、`restore`，记 `retirements` 表，不写判断；`retirement_of`、`retired_ids` 合并旧版的 retirement 判断计算）、独立支持数 | MODEL、propagation、retrieval 坐标、review（写回判断层的链接）、linking.decide、import_v1（直接写账本，须遵守同样的口径）；退役状态 → 条目列表（overview）、检索（retrieval）、建页门槛（framework）、定时检查（checks）、建议退役（extraction）、复核历史（review）；`HISTORY_KINDS`（旧版写成判断的复核、退役）→ 列表、检索、关系图、对象页、统计都要排除 |
| MDL 本地模型 | `services/models.py`、`services/model_adapters.py`、`services/model_launch.py`、`services/recognition.py` | 模型槽位（版面抽取、公式识别、大模型；向量模型见 RET 的 `vectors`，设计稿 06）与自动运行的条件（只有本机地址的本地模型；大模型永远不自动调用）、进程内任务队列（调用模型时放开数据目录的锁）、MinerU 适配器（V1 任务接口、`docvortex.middle` 2.0 → 统一的版面结果）、引擎结果写进抽取层（公式块补 LaTeX 与分组 `latex_group` / `latex_box` / `latex_parts`、段落的 `inline_math`、整份替换）、单个公式识别、OpenAI 兼容的大模型调用（设计稿 05） | 设置组 `models`（`SETTING_CHOICES`、`SETTING_TEXT`、设置页）；EXT 的 `_content`、`_after_write`、`_view_block`、`on_register`、`backfill`；块的新字段 → 前端 `pages/Artifact.tsx` 的 FormulaView、MathParagraph、LayoutPage 与 `models.ts`；MinerU 升级改了输出结构 → 只改 `model_adapters.py`，并用真实服务核对；缓存 `cache/models/` |
| REV 复核 | `services/review.py` | 人的复核（框架页、边、判断；确认写回判断层的边直接写 opposes / supersedes 链接）、AI 复核与它的限制、请人复核、复核历史（含旧版复核判断、原件的抽取确认与退役）、判断的复核状态与当前地位、按需复核的触发（页面成为两个以上页面的输入）、每周抽查（设计稿 04） | 账本表 `reviews`；框架页与边的 `review` 列（缓存）；retrieval 坐标与 `MODEL.rank_key`；extraction 的待复核（`recheck_entry` 只认人的处理）；framework.page_write / edge_add、linking 何时开待决策；设置 `review.ai`；前端 `review.tsx`、Decisions、Entries、Graph、Home；Skill burrowl-consolidate；导出导入 |
| FW 框架 | `services/framework.py` | 实体、页面版本与输入清单（版本数据记下写入的会话）、建页门槛、AI 推断的边；AI 页面与关联边不再逐条进待复核，只有会写回判断层的边进（设计稿 04 D-01、D-02）；`review` 转给 REV | store/framework、propagation、retrieval（页面版本过滤）、overview、前端 Pages / Entries / Graph |
| PROP 传播 | `services/propagation.py` | 沿输入清单标"输入已变化"，传递上限，超限标"未核查"并生成待决策 | `derivation_inputs` 的写入者（framework、linking、artifacts）、DESIGN §0 的上限 |
| LINK 术语连接 | `services/linking.py` | 对象归一化、三档连接（影响范围为 0 的"较有把握"不进待复核，设计稿 04 D-03）、人的决定记为对新边的复核记录并加入别名表、导入时机械连接 | judgments（对象）、review、前端 Decisions |
| RET 检索 | `services/retrieval.py`、`services/vectors.py`、`services/associate.py` | 地位坐标与 `status_note`（判断带复核折算的当前地位，设计稿 04 D-19）；检索（检索单元上的词法、短语、向量三路 RRF，可选重排，按条目折叠，名次只表示相关度，`order=status` 按地位排）；结果线索（命中单元、`more_matches`、`basis`、`relations`、`read_before`、`hints`）；字面查找 `search_exact`；向量补建与状态、重排（`vectors`）；联想模式（`associate`，设计稿 06 D-17）；检索参数 `params()`（`config.json` 的 `retrieval` 组，默认值 `RETRIEVAL_DEFAULTS`，结果带 `params`，设计稿 06 D-21）；展开（来源 / 条件、对象标签、解读）、段落统计、对象页、时间线、约束检查与"未检查"标记、`preview`；旧版写成判断的复核、退役记录不返回 | MODEL.rank_key（`order=status`）、overview（复用坐标与 preview）、IDX、REV（复核状态）、前端 Search / Entries、Skills 中的检索说明（`skills/burrowl-read`）；探索模式不给框架页、框架关系和解读（检索、联想、展开三处一致）；模型目录 → `vectors.models_dir`、README；检索参数 → ops 的 `SETTING_NUMBERS`（范围）、前端 Settings 的"检索参数"、Skill burrowl-read 中 `params` 的说明 |
| OVW 汇总 | `services/overview.py` | 首页最近操作与计数、条目浏览、关系图节点与边（`REL_CATEGORY`） | 关系或节点类型变化 → `REL_CATEGORY`、前端 `labels.CATEGORY / NODE_TYPE`、Graph 图例 |
| CHK 原件检查 | `services/checks.py` | 外部原件是否与登记时一致（先比大小和修改时间，变了才重算指纹）；判断是否到期（`due`），调度在 `interfaces/pool.py` | `config.json` 的 `artifact_check`、`checks.json` 字段、前端首页状态卡与待你处理 |
| AGT agent 运行 | `services/agents.py` | 按命令模板启动 agent CLI，注入身份与会话，输出流式读取，结束后登记为对话原件 | runtime.actor_for（环境变量）、MCP 服务名、`config.json` 的 agents、前端 Agent |
| PORT 导出导入 | `services/portability.py` | JSONL + blobs + Markdown 页面导出；导入到空工作区 | 新表、新列（见 STORE） |
| IMP 旧版导入 | `services/import_v1.py` | 只读旧版 0.x 数据目录，按 DESIGN §7 映射到三列 | 旧版格式知识只在此处；新版写入口径变化时同步（可信度、关系名） |
| OPS 操作 | `interfaces/registry.py`、`interfaces/ops.py` | 一处定义全部操作；参数校验；effect 分类 | **改名或改参数** → 运行 `tools/gen_reference.py`、检查 `skills/` 中的工具名（`tests/test_docs.py`）、前端 `call("…")` 调用、`tests/test_interfaces.py` |
| CLI / HTTP / MCP | `interfaces/cli.py`、`interfaces/http.py`、`interfaces/mcp.py`、`interfaces/runtime.py`、`interfaces/pool.py`、`interfaces/engines.py` | 三个入口；外部阅读引擎（ONLYOFFICE）的签名配置与一次性取文件令牌（设计稿 03 D-13）；数据目录与身份的确定（HTTP 按请求选目录，MCP 不带 `--data` 时每次取默认目录，D-18）；token 与静态文件；MCP 只暴露 read/write；pool 按需打开各数据目录（每次取都核对 `config.json` 是否被别的进程改过，设计稿 06 D-21）并调度所有目录的定时检查与后台补建向量（设计稿 06 D-07） | I4、I5；旧版客户端登记参数兼容（`--data-dir`、`--mode`、`python -m burrowl.interfaces.cli`） |
| INST 安装与服务 | `interfaces/install.py`、`interfaces/server.py`、`packaging/**` | 安装根目录、数据目录登记（名称、默认目录）、Skill 安装与升级、后台启动停止、进程内重启 | `setup.ps1` 布局、`build.py`、`server.json` 字段、开始菜单快捷方式（`burrowl open`）；试装必须带 `-NoPath -NoShortcut` |
| WEB 工作台 | `frontend/src/**`（构建到 `web/`） | 页面、筛选、关系图（可全屏）；原件页的原样显示与段落标记（`pages/Faithful.tsx`：PDF.js、docx-preview、PPT 快照，设计稿 02）；阅读模式外壳（`reader/`：全屏、侧栏、对照与文字视图、阅读器契约与注册表、个人偏好）与可更换的阅读器（`viewers/<名称>/`，设计稿 03）；只调用操作，不含业务规则 | 操作名与返回字段、`labels.ts` 与后端取值一致；PDF.js 的 CMap、字体、解码器由 `vite.config.ts` 复制到 `web/pdfjs/`，升级 `pdfjs-dist` 时核对这几个目录（阅读器组件 `pdf_viewer.mjs` 与核心库版本必须一致）；**阅读器只依赖 `reader/contract.ts`、本目录与第三方包**（`reader/isolation.test.ts` 检查），每个阅读器目录有 README（来源、版本、许可证）；新增阅读器 → `reader/registry.ts` 与后端 `SETTING_CHOICES` 的 `viewer.<格式>` |
| SKILL 工作流说明 | `skills/**` | 给使用 burrowl 的 agent 的规则与流程 | 工具名、参数语义、身份规则；安装记录中的文件名 |

## 状态由谁负责

| 状态 | 权威来源 | 边界 |
|---|---|---|
| 原件、过程日志、事实记录、读取记录、判断、判断间关系、条目对象、原件的抽取记录 | `ledger.sqlite` + `blobs/` | 唯一不可替代、必须备份的部分；只追加 |
| 原件的当前抽取层 | 无独立状态：每个单元最新的一条 `extractions.content`（文本原件由原文直接算出） | 重建只追加新记录；人工和 AI 提交过的单元，整份重建时保留 |
| 页面图像 | 数据目录 `cache/pages/` | 派生缓存，随时可删除；快照 PDF 本身在 blobs 并有抽取记录 |
| 抽取方式、快照转换器、索引方式、嵌入模型、重排 | 数据目录 `config.json` 的 `extraction`、`index` | 抽取设置只影响以后的抽取；换嵌入模型后由后台补建新模型的向量；工作台"设置"页修改（只有人） |
| 检索单元长度 | 数据目录 `config.json` 的 `index.units_*` | 人在设置页修改；保存的进程立即重建索引，别的进程在重建完成前检索时提示可能不全（设计稿 06 D-22） |
| 检索参数 | 数据目录 `config.json` 的 `retrieval` 组 | 人在设置页修改，每次修改记过程日志 `settings.set`；工作台、MCP、命令行读同一份，别的进程下一次调用就重读（设计稿 06 D-21） |
| 外部引用原件的内容 | 原文件本身（只登记路径与 sha256） | 文件被改动时读取报 CONFLICT、工作台打开报 STALE_ARTIFACT，不静默读到新内容 |
| 外部原件的检查结果 | 数据目录 `checks.json` | 可随时重算，不写账本；只查每条版本链的最新一版 |
| 判断的"当前主张状态"（被替代、更正、撤回、反对） | 无独立状态：由 `links` 实时计算（`JudgmentService.status`） | 不写回判断 |
| 实体、别名、页面与版本、边、输入清单、待决策、agent 运行 | `framework.sqlite` | 可修改；页面版本只增；重建要花 AI 成本，所以默认保留 |
| 时效与复核状态 | `pages.freshness/review`、`edges.freshness/review` | 时效只降不升，重写页面后回到 valid；复核状态是复核历史（`reviews`）的缓存，AI 改写页面后回到"AI 生成未复核" |
| 本地模型与大模型的设置 | 数据目录 `config.json` 的 `models` 组 | 人在设置页修改；大模型密钥读取时不返回原文 |
| 版面引擎的原始结果 | 数据目录 `cache/models/<适配器>/<原件 sha256>.json`（记下档位） | 可随时删除，删掉后下次重新调用引擎；档位与设置不同时重新调用并覆盖；写进抽取层的结果在账本里 |
| MinerU 的启动记录 | 数据目录 `cache/models/mineru-launch.json`、`mineru-launch.log`、`mineru-work/`（MinerU 的工作目录：上传文件与锁文件） | 进程号、端口、最后使用时间；由 `model_launch.py` 维护，可随时删除；启动它的进程空闲 10 分钟后关闭服务 |
| 模型任务队列 | 进程内存（`ModelService`） | 可丢弃；重启后由"补抽"或原件页重新发起；每个进程（工作台、MCP）各有一个 |
| 复核历史 | 账本 `reviews`（设计稿 04 D-18） | 人和 AI 的复核、请人复核；不是条目，不进检索、不能被引用；由 `services/review.py` 唯一写入；不能再生 |
| 判断的复核状态与当前地位 | 无独立状态：由写入时的依据加上 `reviews` 里补充的依据实时算出（`ReviewService.state`、`current_credibility`） | 写入时可信度存在判断里，永远不变；检索排序、坐标用当前地位（D-19） |
| 检索索引（引用段落、检索单元、向量缓存） | `index.sqlite` | 可删除重建；`meta.index_version` 不一致时启动即重建；向量按内容指纹与模型指纹缓存，重建索引不删 |
| 嵌入与重排模型 | 模型目录：`BURROWL_MODELS_DIR`，否则 `<BURROWL_ROOT 或安装根目录>/models/` | 不进安装包；有 `model-manifest.json` 时加载前逐个核对指纹，否则以 onnx 文件的 sha256 为指纹；进程内加载的本地模型，可以自动调用（I12） |
| 配置 | 数据目录 `config.json` | agent 命令模板、传播上限、连接阈值、人的显示名 |
| 工作台端口、token、进程号、启动时间 | `<Root>/server.json` | 整个安装一个工作台进程（D-18）；首次沿用默认数据目录旧 `server.json` 的端口和 token，否则从 8766 起找空闲端口；启动时被占用就换端口；token 是访问口令 |
| 工作台当前数据目录 | 浏览器网址 `?db=名称`（每个标签页各自） | 打开时没有 `db` 就写入当时的默认目录，之后别处改默认也不会让这个标签页换目录；服务端不保存"当前目录" |
| agent 运行的 MCP 配置与输出 | 数据目录 `runs/<run_id>/` | 输出结束后登记为对话原件，此目录只是缓冲 |
| 安装位置、当前版本 | `<Root>/versions/`、`current` 联接、`current.txt` | 用户环境变量 `BURROWL_ROOT` 指向 Root |
| 数据目录登记、名称、默认目录 | `<Root>/workspaces-v2.json` | 不读旧版的 `workspaces.json`；移除登记不删数据；默认目录不能移除 |
| Skill 安装记录 | `<Root>/burrowl-install.json`（与旧版格式相同） | 只替换或删除记录中且未被用户改过的文件 |
| 关系图视图、原件页的视图（原样 / 对照 / 文字） | 浏览器 `localStorage` | 每个浏览器自己的偏好，不是研究记录 |
| 原件是否已退役 | 账本 `retirements`（退役 / 恢复，按时间取最后一条），合并 2.0.0a13 以前的 `retirement` 判断与对它的撤回（`JudgmentService.retirement_history`） | 不写回原件，也不写判断；撤销退役 = 写一条 restore |

## 主要数据流

```
写判断    judgment.write → 校验依据（拒绝框架）→ 推出可信度 → 写 judgments + links(used/关系)
          → 写索引 → propagation（依据、关系目标、同对象的框架条目 → 输入已变化）→ 记过程日志
人工修改  judgment.amend（人）→ 写 correction/retraction/defect 判断 + 关系 → 同上传播
退役原件  artifact.retire（人）→ 写 retirements 一行（retire / restore）→ 以它为输入的框架页标为输入已变化
          （原件不再出现在条目列表、默认检索、建页门槛和定时检查中；内容、抽取、旧引用都不变）
登记原件  artifact.register → 内容寻址或登记指纹 → 分段、合并成检索单元、建索引 → 机械连接实体 → 若有旧版本：比较片段哈希并传播
          （向量不等：工作台后台线程补建，检索结果报告"已建 m / n"）
          → PDF 且本机版面引擎开着自动运行（或抽取方式为 MinerU）：排进模型任务队列
版面引擎  任务队列 →（设置为自动启动时：MinerU 没在运行就启动）→ 放锁调用 MinerU（结果缓存，记档位）
          → 取锁：抽取方式为 MinerU 且原件没被引用 → 采用引擎分段，逐块与文字层核对定档（parsed / ocr）；
            否则公式块补 LaTeX、段落记行内公式（锚点、指纹不变）→ 写 content（来源 tool:mineru@版本）→ 重建索引
识别核对  人点"交给 AI 复核" → 任务队列 → 逐块裁切原件图像 → 调用大模型 → 写 reviews（方式 AI，"AI 已核对"）
检索      search → 词法 / 短语 / 向量三路在检索单元上 RRF → 可选重排 → 按条目折叠 → 地位坐标与过滤 → 名次 = 相关度
          → 被替代、已退役的放后 → 补上命中单元、依据、一跳关系、提示；相关对象的有效约束单列
写框架页  page.write → 检查输入存在、建页门槛 → 新版本 + 输入清单 → 索引 → 用到的 AI 页面若已是两个以上页面的输入 → 开待复核
复核      review.submit（人）→ 写 reviews 一行（边：可能写回 supersedes/opposes 链接）→ 改复核状态 → 关闭待复核 → 传播
AI 复核   review.ai_submit（AI）→ 检查设置、对象、会话、依据（层、相关、已读、识别文字）→ 写 reviews 一行
          → confirm：AI 已复核、关闭待复核（请人复核开出的只附结论）；reject / unsure：待复核保留并排到前面
agent     agent.start（人）→ 生成本次运行的 MCP 配置（身份、会话）→ 子进程 → 输出流 → 登记为对话原件
重启服务  server.restart（工作台）→ 用 current 下的无窗口解释器 pythonw 拉起新进程（不经 burrowl.cmd，--wait 等端口）→ 旧进程退出 → 页面检测到新启动时间后刷新
```

## 已知差距

- 身份靠入口和环境变量区分；本机进程可以伪造 `BURROWL_ACTOR_ID`，第一版不防范。
- 术语连接只按名称包含关系找候选，没有用条件冲突和向量相似度。
- 检索效果只有小范围回归题（评测工作区 `Burrowl-eval` 的 regression-v1，12 题）；大评测（LongMemEval、MINT-Eval、GraphRAG-Bench、SciFact、合成中文）尚未运行，须由用户确认（设计稿 06 AC-07）。跨语言题在 4 题中只有 1 题落到正确段落（其余落到正确条目）。
- 重排默认关闭：本机的重排模型（mmarco-mMiniLMv2）在回归题上降低了段落命中，还要约 1 秒（设计稿 06 D-08 修订）。
- 向量是暴力检索（numpy 全量矩阵乘），约 10 万个检索单元以上需要换近似最近邻索引。
- 图片、扫描页、音视频没有内置的识别或转写：只能由 AI（`artifact.extract method=ai`）、外部 OCR 工具或人工提交文字；没有多模态索引，检索只按抽取出的文字（设计稿 01 D-11、D-18）。识别提交的文字没有位置，原样视图里只能整页标记（设计稿 02 §5）。
- PDF 按位置分段是规则方法：行间公式按数学字体识别，大公式偶尔仍拆成几块（显示上用原件裁切图，不影响阅读），行内公式只标出所在段落；公式的 LaTeX 要由 AI、OCR 工具或人补充（设计稿 03 D-17），没有补充时显示原件截图；复杂表格不识别为表格；Excel 抽取不含单元格格式、图表、图片，公式取文件里保存的计算结果（用 openpyxl 等不计算公式的程序生成的文件没有计算结果）；外部引擎 ONLYOFFICE 只做了只读显示，社区版不能在文档上画段落标注，也还没有在真实引擎上实测（设计稿 03 §8）；Word 原样视图按文字顺序对应版式块，对上的少于一半时退回近似版式（设计稿 02 D-04、D-08）。
- 导入时由服务端自动建实体页（草图 §12.2）未实现，交给 agent。
- 阅读会话、维护计划尚未开发（DESIGN §9）。
- 关系图在服务端一次算出全部边再裁剪，大数据量时需要改成按中心增量查询。
- 本地模型：MinerU 只接了 4.x 的 V1 任务接口（按 4.1.7 实测）；内置抽取把一条公式切成几块时按位置分组，算法框、正文中被切出的公式片段对不上（Adam 论文 73 块里 7 块）；行内公式只在引擎的一段与内置抽取的一段位置和长度都相近时才记上；任务队列不跨进程，MCP 进程登记的 PDF 由 MCP 进程自己调用 MinerU（设计稿 05 §6）；自动启动的 MinerU 由两个进程共用，靠数据目录里的启动记录协调，启动它的进程退出后留下的服务要等下一个需要它的进程接管后才会空闲关闭。MinerU 分段时段落里的行内公式按段落的档计（只核对了文字片段）。
- 判断的复核状态与当前地位每次从复核历史算出，没有缓存（设计稿 04 D-18 原定缓存到框架库）；检索结果多时会多查几次 `reviews`。AI 复核的"同一会话"判断对 2.0.0a14 以前写的框架页从过程日志里查，边没有记会话的不检查。
