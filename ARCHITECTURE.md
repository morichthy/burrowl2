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
| I1 | 账本只追加：`artifacts / events / records / reads / judgments / links / entry_objects` 不 UPDATE、不 DELETE | 数据库触发器（`store/migrations/ledger`）；`tests/test_store.py` | 历史被改写，判断层失去"当时谁认为了什么"的意义 |
| I2 | 框架永远不能作为依据 | `JudgmentService.basis_of` 拒绝框架 ID（含正文 `[[ID]]`） | 框架污染进入判断层（K2） |
| I3 | 写入时可信度由系统根据依据推出；本地实证只能由人标记 | `core/model.derive_credibility`；`judgment.write` 没有可信度参数，`local_observation` 对 AI 报 FORBIDDEN | AI 自评可信（Memory Reward Inflation） |
| I4 | 调用者身份由入口决定 | `interfaces/runtime.actor_for`：MCP 一律是 AI；命令行在 `BURROWL_ACTOR_ID=ai:…` 时是 AI | AI 冒充人做更正、复核 |
| I5 | 只能由人做的操作：更正、撤回、原件缺陷、复核、术语决定、启动/停止 agent、服务控制、导入旧版 | `effect="user"/"admin"`（MCP 不注册、`registry.call` 拒绝）；服务内 `actor.require_human` | 判断层被 AI 改写 |
| I6 | 变化只在框架层传播，只降不升 | `services/propagation.py`；`DOWNGRADE_ORDER` | 下游悄悄过时，或被错误"升级" |
| I7 | 派生条目的输入清单指向**固定版本** | `derivation_inputs` 记 `derived_version`；页面引用写 `pg_…@N` | 传播找不到受影响的框架 |
| I8 | 落盘格式只增不改，旧数据永远可读 | 编号迁移（只新增）；`FORMAT_VERSION`；导出导入按列名对齐 | 升级后读不了旧数据 |
| I9 | 索引可以随时删除重建；检索不返回旧版本的索引行 | `Workspace.rebuild_index`；`RetrievalService.search` 核对页面版本 | 旧内容残留在检索结果里 |
| I10 | 新版不打开旧版数据目录 | `Workspace.__init__` 发现 `.burrowl/` 且无 `ledger.sqlite` 时报 OLD_FORMAT | 在旧目录里建新库，旧数据读不到 |
| I11 | 过程内容不能作为结论的依据 | `JudgmentService._reject_process_evidence`；探索模式默认不返回过程内容 | 思路混进证据链（K2），探索被已有思路带偏（1.8） |

## 分层与依赖

```
interfaces   操作注册表 ops → CLI（Typer）│ HTTP 工作台（FastAPI）│ MCP（官方 SDK）；安装、后台服务
services     workspace（组合根）、capture、artifacts、judgments、framework、propagation、linking、
             retrieval、overview、agents、portability、import_v1
store │ index   store：SQLite 连接与迁移、账本仓库、框架仓库、内容寻址 blobs；index：分段与 FTS5
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
| IDX 索引 | `index/segment.py`、`index/fts.py` | 按自然边界分段（`seg:N`）、FTS5 trigram 检索、短查询退回 LIKE | 分段规则 → 升 `SEGMENTER_VERSION`（启动时整库重建）；定位格式 `seg:N` / `#seg-N` → artifacts.read、retrieval.expand、前端检索结果链接 |
| WS 组合根 | `services/workspace.py` | 打开三个库、迁移、装配各服务、`rebuild_index`、默认配置 | 新服务在这里装配；默认配置（agents、传播上限、连接阈值）→ README 与 DESIGN §0 |
| CAP 过程捕获 | `services/capture.py` | 过程日志（只追加）；长输出存 blob；触发"操作前未检查约束" | retrieval 的约束检查、`INTERNAL_OPS` 前缀 |
| ART 原件 | `services/artifacts.py` | 登记（受管 / 外部引用）、分段与索引、读取记录、事实记录升级（条件不能补写）、新版本差异传播 | linking（导入时机械连接）、propagation、judgments.basis_of（原件的依据来源） |
| JDG 判断 | `services/judgments.py` | 写判断与关系、依据校验与可信度推导、人工修改入口、当前主张状态、独立支持数 | MODEL、propagation、retrieval 坐标、framework.review（写回判断层）、linking.decide、import_v1（直接写账本，须遵守同样的口径） |
| FW 框架 | `services/framework.py` | 实体、页面版本与输入清单、建页门槛、AI 推断的边、人的复核（写回判断层） | store/framework、propagation、retrieval（页面版本过滤）、overview、前端 Pages / Entries / Graph |
| PROP 传播 | `services/propagation.py` | 沿输入清单标"输入已变化"，传递上限，超限标"未核查"并生成待决策 | `derivation_inputs` 的写入者（framework、linking、artifacts）、DESIGN §0 的上限 |
| LINK 术语连接 | `services/linking.py` | 对象归一化、三档连接、人的决定写回并加入别名表、导入时机械连接 | judgments（对象）、framework.review、前端 Decisions |
| RET 检索 | `services/retrieval.py` | 地位坐标、检索排序、展开、时间线、约束检查与"未检查"标记、`preview` | MODEL.rank_key、overview（复用坐标与 preview）、前端 Search / Entries、Skills 中的检索说明 |
| OVW 汇总 | `services/overview.py` | 首页最近操作与计数、条目浏览、关系图节点与边（`REL_CATEGORY`） | 关系或节点类型变化 → `REL_CATEGORY`、前端 `labels.CATEGORY / NODE_TYPE`、Graph 图例 |
| AGT agent 运行 | `services/agents.py` | 按命令模板启动 agent CLI，注入身份与会话，输出流式读取，结束后登记为对话原件 | runtime.actor_for（环境变量）、MCP 服务名、`config.json` 的 agents、前端 Agent |
| PORT 导出导入 | `services/portability.py` | JSONL + blobs + Markdown 页面导出；导入到空工作区 | 新表、新列（见 STORE） |
| IMP 旧版导入 | `services/import_v1.py` | 只读旧版 0.x 数据目录，按 DESIGN §7 映射到三列 | 旧版格式知识只在此处；新版写入口径变化时同步（可信度、关系名） |
| OPS 操作 | `interfaces/registry.py`、`interfaces/ops.py` | 一处定义全部操作；参数校验；effect 分类 | **改名或改参数** → 运行 `tools/gen_reference.py`、检查 `skills/` 中的工具名（`tests/test_docs.py`）、前端 `call("…")` 调用、`tests/test_interfaces.py` |
| CLI / HTTP / MCP | `interfaces/cli.py`、`interfaces/http.py`、`interfaces/mcp.py`、`interfaces/runtime.py` | 三个入口；数据目录与身份的确定；token 与静态文件；MCP 只暴露 read/write | I4、I5；旧版客户端登记参数兼容（`--data-dir`、`--mode`、`python -m burrowl.interfaces.cli`） |
| INST 安装与服务 | `interfaces/install.py`、`interfaces/server.py`、`packaging/**` | 安装根目录、数据目录登记、Skill 安装与升级、后台启动停止、进程内重启 | `setup.ps1` 布局、`build.py`、`server.json` 字段、开始菜单快捷方式（`burrowl open`）；试装必须带 `-NoPath -NoShortcut` |
| WEB 工作台 | `frontend/src/**`（构建到 `web/`） | 页面、筛选、关系图；只调用操作，不含业务规则 | 操作名与返回字段、`labels.ts` 与后端取值一致 |
| SKILL 工作流说明 | `skills/**` | 给使用 burrowl 的 agent 的规则与流程 | 工具名、参数语义、身份规则；安装记录中的文件名 |

## 状态由谁负责

| 状态 | 权威来源 | 边界 |
|---|---|---|
| 原件、过程日志、事实记录、读取记录、判断、判断间关系、条目对象 | `ledger.sqlite` + `blobs/` | 唯一不可替代、必须备份的部分；只追加 |
| 外部引用原件的内容 | 原文件本身（只登记路径与 sha256） | 文件被改动时读取报 CONFLICT，不静默读到新内容 |
| 判断的"当前主张状态"（被替代、更正、撤回、反对） | 无独立状态：由 `links` 实时计算（`JudgmentService.status`） | 不写回判断 |
| 实体、别名、页面与版本、边、输入清单、待决策、agent 运行 | `framework.sqlite` | 可修改；页面版本只增；重建要花 AI 成本，所以默认保留 |
| 时效与复核状态 | `pages.freshness/review`、`edges.freshness/review` | 时效只降不升，重写页面后回到 valid；复核结论同时写回判断层 |
| 全文索引 | `index.sqlite` | 可删除重建；`meta.segmenter_version` 不一致时启动即重建 |
| 配置 | 数据目录 `config.json` | agent 命令模板、传播上限、连接阈值、人的显示名 |
| 工作台端口、token、进程号、启动时间 | 数据目录 `server.json` | 端口首次启动时选一个空闲的；token 是访问口令 |
| agent 运行的 MCP 配置与输出 | 数据目录 `runs/<run_id>/` | 输出结束后登记为对话原件，此目录只是缓冲 |
| 安装位置、当前版本 | `<Root>/versions/`、`current` 联接、`current.txt` | 用户环境变量 `BURROWL_ROOT` 指向 Root |
| 数据目录登记 | `<Root>/workspaces-v2.json` | 不读旧版的 `workspaces.json` |
| Skill 安装记录 | `<Root>/burrowl-install.json`（与旧版格式相同） | 只替换或删除记录中且未被用户改过的文件 |
| 关系图视图 | 浏览器 `localStorage` | 每个浏览器自己的偏好，不是研究记录 |

## 主要数据流

```
写判断    judgment.write → 校验依据（拒绝框架）→ 推出可信度 → 写 judgments + links(used/关系)
          → 写索引 → propagation（依据、关系目标、同对象的框架条目 → 输入已变化）→ 记过程日志
人工修改  judgment.amend（人）→ 写 correction/retraction/defect 判断 + 关系 → 同上传播
登记原件  artifact.register → 内容寻址或登记指纹 → 分段建索引 → 机械连接实体 → 若有旧版本：比较片段哈希并传播
写框架页  page.write → 检查输入存在、建页门槛 → 新版本 + 输入清单 → 索引 → AI 写的进入待复核
复核      framework.review（人）→ 写 review 判断（可能写回 supersedes/opposes）→ 改复核状态 → 关闭待复核
agent     agent.start（人）→ 生成本次运行的 MCP 配置（身份、会话）→ 子进程 → 输出流 → 登记为对话原件
重启服务  server.restart（工作台）→ 经 current 启动器拉起新进程（--wait 等端口）→ 旧进程退出 → 页面检测到新启动时间后刷新
```

## 已知差距

- 身份靠入口和环境变量区分；本机进程可以伪造 `BURROWL_ACTOR_ID`，第一版不防范。
- 术语连接只按名称包含关系找候选，没有用条件冲突和向量相似度。
- 没有向量检索、重排；检索效果没有评测（冷读者测试、MINT-Eval 子集、ALCOA+ 清单都未接入）。
- 非文本原件只能登记和挂描述页，没有抽取。
- 导入时由服务端自动建实体页（草图 §12.2）未实现，交给 agent。
- 阅读会话、维护计划尚未开发（DESIGN §9）。
- 关系图在服务端一次算出全部边再裁剪，大数据量时需要改成按中心增量查询。
