# 10 条目、关系、坐标重整：存事实、推坐标、一套版本、一套谓词

| 项 | 内容 |
|---|---|
| 状态 | 设计稿（2026-11-12 第五稿），方向已与用户逐条确认，未实现 |
| 性质 | **2.1.0**，落盘格式号仍为 2，但**不兼容 2.0.x 数据**（用户决定：更新后新建数据库，旧数据目录不再使用；不做 1.x 导入）。用结构检查拒绝打开旧目录（D-03） |
| 关系 | 回到[草图](../model/DESIGN-SKETCH.md) §1、§11.2、§12.4 的双轴与三层；修订[设计稿 09](09-digesting-external-sources.md) D-02、D-15；替代 2.0 的条目版本做法（DESIGN"条目版本"一节、开发历史 D-58 至 D-62）；修订不变式 I3、I7、I8 的表述（§4） |
| 适用范围 | 存储（`store/`，新的基线迁移）、`core/`（ID、引用、词表）、几乎全部 `services/`、`interfaces/ops.py`、`interfaces/mcp.py`；前端全部显示坐标、引用、关系、版本的地方；全部 Skill 与文档；全部测试；删除 `services/import_v1.py` |
| 维护方式 | 决定有变化时先改 §3；每完成一个任务更新 §9；实现后把稳定说明迁到 CORE / ARCHITECTURE，在 DEVELOPMENT_HISTORY 补记 |

决定写作 `D-xx`，任务写作 `T-xx`，验收写作 `AC-xx`；代码注释与提交信息引用"设计稿 10 D-xx"。

## 1. 背景（2026-11-12）

### 1.1 用户提出的问题

1. 条目页"地位、判断类型、作者、依据来源"四个并列分类，看不出当初的双轴（依据来源 × 所处列）。
2. 关系图的判断类型里"文献论断"与结论并列。
3. 说明会随版本变化，展示、检索、下游是否处理妥当；检索是否把全部说明返回给 AI；命中旧版时是否带上新版。
4. 字段要少，能推出的就推出，为以后加功能留余地。
5. 引用要双向：引用了谁、被谁引用，AI 才能顺着线索与图去找、去读。
6. 支持、反对、依赖、回答等谓词与"引用 / 被引"是同一套主语—谓词—宾语，以后还要承载多元关系；现在一部分混在标志里。
7. 谓词会有想不到的种类；提示标记要能看出是哪条引用出了问题；引用与支持的地位是否不同。

### 1.2 现状（检索代码所得）

**条目落盘的内容**（以判断为例）：事实（`kind`、`text`、`conditions`、`objects`、`reopen_condition`、`external_author`、作者、会话、时间）之外，还存了推论快照：`credibility`（来源类别、外部档次、全为本地、混合、依据完整、依据条数、规定、含未确认识别）、`cited_segments` 的识别状态、`citation_notices`；以及旧的版本字段 `revises`。

**读取时拼出二十多个字段**（`RetrievalService.coordinates`），互相重复：`process`、`normative` 与 `judgment_kind`；`all_local`、`mixed` 与 `source_classes`；`complete` 混了"依据完整""有缺陷""依据失效"；`superseded` 在撤回、退役时也为真。

**"还算不算数"有四套算法**：`JudgmentService.status()`、`overview.entry_status()`、`overview.stats()` 的 SQL（还用写入时快照）、`VersionService.reference_status()`。

**版本有五套并存的机制**：`revises` 链、`version_of` 链、`entry_version*` 关系、`entry_version_state` 状态关系、旧的更正 / 撤回 / 缺陷判断。

**谓词分散在五处**：账本 `links`（`used`、`depends_on`、`supports`、`opposes`、`answers`、`targets`、`coexists_under`、`supersedes`、`corrects`、`retracts`、`defect_of`、`retires`、`wasRevisionOf`、`documents`、`consumed`、`produced`、`entry_version*`）、框架 `edges`（`may_contradict`、`may_supersede`、`similar`、`analogy`、`related`、`mentions`）、框架 `derivation_inputs` 与 `pages.subject_id`、账本 `entry_objects`、关系图的 `REL_CATEGORY`。

**引用、依赖、支持的地位不一致**：

| | 引用 `used` | 依赖 `depends_on` | 支持 `supports` |
|---|---|---|---|
| 算进写的人自己的依据来源 | 算 | **不算** | 不算 |
| 被指向的一方能看到什么 | — | — | 坐标里**什么都没有**，只在条目页入边里 |
| "独立支持数" | 实际只数**自己引用里**的本地实证依据 | 不参与 | 不参与 |

**版本对说明的影响**：更正判断时原作者与关系丢失、作者变成更正的人；版本历史只列号与状态；**只有旧版命中时检索什么也不返回**；引用方的坐标里没有"依据有变"；返回给 AI 时正常值也全部返回。

## 2. 原则

1. **三个部分**：**条目**（节点：说了什么、谁说的）、**关系**（主语—谓词—宾语，每条一行）、**坐标**（读取时推出的可靠程度与现状）。凡是"A 与 B 之间"的事都是关系，不是字段。
2. **存事实，推坐标**：账本只存推不出的事实；可靠程度、有效性、提示一律读时推出，可缓存、可删除重建。
3. **一套身份与版本**：条目 ID 稳定，版本 `@n`，所有关系两端都固定到版本。
4. **谓词核心固定、外围开放**：系统依赖其语义的谓词固定在词表里；其余用自由标签，定期由人归并。
5. **双向可查**：每条关系从两端都能看到。
6. **一个词表**：坐标取值、谓词、标记的名字、标签、分组、严重度、推出规则都在 `core/vocab.py`，`status_note`、前端、参考文档从它生成。
7. **只报例外，例外带出处**：返回给 AI 的坐标只写例外，正常值不写；每个标记都指向造成它的那条关系（或那次处置）。关系本身全部给出，不截成"前几个"（D-21）。
8. **显示顺序**：地位 → 类型 → 现状 → 说明。

## 3. 决定

### A. 条目：身份、版本、只存事实

| 编号 | 决定 | 理由 |
|---|---|---|
| D-01 | **条目 ID 稳定，版本写 `@n`**：原件、过程日志、事实记录、读取记录、判断都像框架页一样有版本号；账本各表主键为 `(id, version)`。`art_…@2#p3-2`、`jdg_…@3` 是固定版本的引用；不带 `@n` 指当前版，写入关系时系统补成当时的版本号再存。去掉 `revises`、`version_of`、`entry_version*`、旧的更正 / 撤回 / 缺陷判断与 `HISTORY_KINDS`、`AMEND_KINDS` | 五套版本机制合成一套 |
| D-02 | **新版本的产生与继承**：AI 改写自己会话写的判断、人更正任何条目，都产生新版本，界面只显示最终作者（人 / AI / 系统）。新版本沿用上一版的原作者、对象、关系、重开条件，只替换改动的内容；关系的主语换成新版本，旧版本的关系仍留在旧版本上 | 修掉更正时丢失原作者与关系的问题 |
| D-03 | **版本号与旧目录**：产品版本 2.1.0；`FORMAT_VERSION` 保持 2。打开数据目录时检查新结构才有的表（`relations`、`version_states`），没有就拒绝并提示"这是 2.0 的数据目录，请新建"，不做任何写入。更新后把默认数据目录换成新建的目录 | 用户决定不升格式号；结构检查防止新代码写坏旧库 |
| D-04 | **人的处置记在版本上**：撤回、取消撤回、标缺陷、取消缺陷、退役、取消退役、重新生效，记在只追加的 `version_states`（条目、版本、动作、理由、人、时间）。复核记在 `reviews`，同样带版本 | 一种处置一个地方 |
| D-05 | **判断只存这些字段**：`id`、`version`、`kind`、`text`、`conditions`、`objects`、`reopen_condition`（只用于过程）、`external_author`（转述外部材料时）、`local_observation`（只能人勾）、`author_id`、`author_kind`、`session_id`、`created_at`、`change_reason`（第 2 版起）、`inspection_finding`（来源追踪）。不再存 `credibility`、识别状态、`citation_notices`、`extracted_by`。写入时的提示照常返回给写的人，但不落盘。<br>落盘的事实只有三类：**条目字段**（本表与 D-06）、**关系**（D-07，判断写入时的 `cites` 等参数存成关系行，主语是这一版判断）、**人的处置与复核**（D-04）。坐标不落盘，读取时由这三类事实推出，每个坐标字段的来源见 C 节"坐标字段"表的最后一列 | 推论快照会与读时推论不一致 |
| D-06 | 其他条目（原件、过程日志、事实记录、读取记录）字段保持现状，只按 D-01 加版本列；事实记录、日志的 `corrected_text` 改为新版本的正文 | 统一 |

### B. 关系：一条一行，主语—谓词—宾语

| 编号 | 决定 | 理由 |
|---|---|---|
| D-07 | **关系的结构**：`id`（`rel_…`）、`predicate`、`label`（自由谓词的标签）、`subject`（带版本）、`object`（带版本与段落）、`qualifiers`（如 `condition`、`reason`、所引段落的指纹）、`args`（更多角色，D-11）、`asserted_by`、`created_at`。一条关系就是一行；一条判断是一个节点，挂着多条出边。存储按列分开：判断层与机械关系在账本 `relations`（只追加），框架推断的在框架库 `edges`（可再生、带复核状态）。`derivation_inputs`、`pages.subject_id` 改为关系 `derived_from`、`subject_of`。`entry_objects` 不是关系：对象是写的人给出的名称（如"3 号炉"），不是条目，仍作为条目的事实存放，只加版本列；框架把条目连到实体页时才用 `about` | 一种结构装下全部关系 |
| D-08 | **核心谓词（固定，系统依赖其语义）**，在 `core/vocab.py` 的 `PREDICATES` 定义名字、中文、反向中文、类别、来源（判断层 / 机械 / 框架推断）、谁能写、是否作为依据、主宾语允许的条目种类、可带的限定：<br>**证据流**：`cites` 依据（吸收原 `used`、`depends_on`、`documents`：A 依据 B，证据从 B 流向 A）、`supports` 佐证（B 事后为 A 作佐证，同样是证据从 B 流向 A）、`opposes` 反驳；<br>**立场与结构**：`coexists_under` 条件并存（限定 `condition`）、`answers` 回答、`targets` 针对；<br>**替代**：`supersedes`（只能人确认）；<br>**过程**：`consumed`、`produced`；<br>**框架**：`may_contradict`、`may_supersede`、`similar`、`analogy`、`related`、`mentions`、`about`、`derived_from`、`subject_of`。<br>`corrects`、`retracts`、`defect_of`、`retires`、`wasRevisionOf`、`entry_version*` 不再是谓词（由版本与 D-04 表达） | 一处定义；引用与依赖本是一件事 |
| D-09 | **自由谓词（开放）**：核心谓词都不合适时，用 `relates` 加自己写的 `label`（如"导致""是……的一种""先于"）。它照常存储、检索、画在图上，但系统不赋予语义：不算依据，不产生标记。巡检或整理时按使用次数列出常用标签，由人决定并入某个核心谓词、登记为同义说法，或升格为新的核心谓词（做法同术语连接与别名表）。AI 通过 `vocab.get` 与 MCP 提示里的简表先从核心谓词里选 | 想不到的谓词也写得进去，系统依赖的语义不被稀释 |
| D-10 | **双向**：每条关系从主语看是出边，从宾语看是入边（"被依据""被佐证""被反驳"）。检索、联想、`entry_get`、关系图用同一个函数取两端，反向名来自词表 | AI 能顺着引用与被引继续找 |
| D-11 | **多元关系**：二元加限定是常态；需要更多角色时，关系带 `args`（角色名 → 引用列表），角色在谓词里声明；关系有 ID，可以作为另一条关系的主语或宾语。第一版只实现二元加限定，`args` 留结构不启用 | 结构先定好，以后只加词表 |

### C. 坐标：读时推出

| 编号 | 决定 | 理由 |
|---|---|---|
| D-12 | **坐标四组**（见下面"坐标字段"表），所有条目统一 | 字段最少 |
| D-13 | **地位只由自己的依据决定**：`sources` 只看本条目自己的 `cites`（以及人勾的本地实证），不因别人后来的佐证或反驳而改变。被佐证、被反驳属于现状 | 地位描述"凭什么这么说"，佐证是事后发生的事 |
| D-14 | **标记带出处**：每个标记是 `{mark, via: [{rel, end, detail}]}`，只在出现时列出。`via` 不是关系，是"这个标记从哪来"：`rel` 是造成它的那条关系的 ID（如某条 `cites`），`end` 是那条关系另一端的引用（如 `art_…@1#p3-4`），`detail` 是那一处的情况（如"AI 认为有问题"）。由条目自身事实或人的处置推出的标记（`conditions_unstated`、`no_basis`、`defective`、`local_observation`）`via` 为空或指向那次处置。检索结果里只给标记名与处数（`status_note` 写"依据含未确认的识别（2 处）"）；`entry_get` 与条目页列出全部出处，可点开核对。第一批（名字、推出规则在词表 `MARKS`）：<br>**现状标记**：`corroborated` 被佐证（入边 `supports`，出处带佐证方与它的依据来源，如"有本地实证佐证"）；`opposed` 被反驳（入边 `opposes`）；`basis_changed` 依据有变化（出边 `cites` 指向的版本已不是当前版、被撤回，或段落指纹对不上；出处带当前版）；`basis_lapsed` 部分依据已退役或删除（出处带原因）；`defective` 本版被标缺陷；`inputs_changed`、`unchecked`（框架页）。<br>**说明标记**：`recognition_unverified` 依据含未经人确认的 OCR / AI 识别（含公式 LaTeX；出处带段落与状态：未核对 / AI 核对一致 / AI 认为有问题 / AI 拿不准；人确认后自动消失）；`conditions_unstated` 转述外部材料但没写条件；`basis_incomplete` 依据边界不完整；`no_basis` 结论没有依据；`local_observation` 人标了本地实证；`local_roots` 本地依据来自 N 个独立来源（替代原"独立支持数"）。<br>（旧版命中不是标记，见 D-19 的 `old_hits`。）<br>新情况加一个标记并写明推出规则，不加字段 | 知道是哪条引用出了问题；关系类的情况从关系推出，不重复存放 |
| D-15 | **"文献论断"不再是独立概念**：就是说明里有原作者（`quoted`）的结论，显示为"转述 · 原作者 Li et al., 2020"；它经本地实验验证后，现状里有"被佐证（本地实证）"。依据只有外部报告的 AI 推论由 `sources` 表达（修订设计稿 09 D-02） | 不再与依据来源重复；验证情况在原条目上看得见 |
| D-16 | **词表**：`core/vocab.py` 定义坐标取值、谓词、标记的名字、中文、分组、严重度、推出规则。`status_note` 按"地位 → 类型 → 现状 → 说明"生成；新操作 `vocab.get` 交给前端；`tools/gen_reference.py` 写进参考文档 | 名字只在一处 |
| D-17 | **缓存**：坐标与关系概况可以缓存在框架库，账本变化即失效、可删除重建，不能作为依据；第一版不做，重建测试数据后看检索耗时再定 | 留口子 |

**坐标字段**（D-12）：

| 组 | 字段 | 取值 | 替代现在的 | 从哪些事实推出 |
|---|---|---|---|---|
| — | `ref` | `jdg_…@3`：条目与当前版本 | `id` 与各种版本信息 | 条目 ID + 最新版本号 |
| 地位 | `layer` | `original` / `judgment` / `framework` | `layer` | 条目所在的表 |
| 地位 | `sources` | 来源记号列表：`local`、`external:peer_reviewed`、`external:preprint`、`external:vendor`、`external:web`、`external`、`inferred`；按 D-13 推出；框架为空 | `source_classes`、`external_tiers`、`all_local`、`mixed`、`includes_local`、写入时快照 | 原件：登记时的来源与档次字段；判断：本版出边 `cites` 所指版本的 `sources` 合并，加人勾的 `local_observation`；没有依据的结论为 `inferred`，人勾了本地实证为 `local` |
| 类型 | `kind` | 原件：`artifact` / `event` / `record` / `read`；判断：`conclusion` / `process` / `normative`；框架：`entity` / `concept` / `synthesis` / `description` | `entry_kind`、`judgment_kind`、`process`、`normative`、页面类型 | 条目所在的表 + 判断的 `kind` 字段 / 页面类型字段 |
| 现状 | `state` | `{validity, review, marks}`：`validity` 为 `current` / `replaced` / `withdrawn` / `retired` / `lapsed`；`review` 为 `none` / `ai_confirmed` / `ai_flagged` / `ai_unsure` / `human_confirmed` / `human_rejected`；`marks` 为现状标记 | `superseded`、`replaced`、`withdrawn`、`retired`、`hidden`、`review`、`ai_flag`、`opposed`、`independent_support`、`defective`、`lapsed_basis`、`freshness` | `validity`：有无更新的版本、`version_states`、入边 `supersedes`、出边 `cites` 所指版本是否全部失效；`review`：`reviews` 表中本版的最近一条；`marks`：入边 `supports` / `opposes`、出边 `cites` 所指版本的现状、`version_states` 的缺陷、框架输入的变化 |
| 说明 | `notes` | `{author, quoted, marks}`：`author` 当前版的最终作者；`quoted` 原作者；`marks` 为说明标记 | `author_kind`、`external_author`、`external_claim`、`conditions_unstated`、`complete`、`recognition_unverified` | `author`：本版 `author_kind`；`quoted`：`external_author` 字段；`marks`：本版字段（`conditions` 为空且有原作者、没有出边 `cites`、`local_observation`）与出边 `cites` 所指段落的识别状态、依据边界 |

"全部依据为本地实证" = `sources == ["local"]`；"混合" = `len(sources) > 1`；过程内容 = `kind == "process"`，都现推。

### D. 版本对展示、检索、下游

| 编号 | 决定 | 理由 |
|---|---|---|
| D-18 | **展示**：条目页显示当前版与它的坐标；版本历史每一版列出自己的作者、改动理由、依据与关系的变化、处置状态。打开旧版时顶部说明"这是第 n 版，当前是第 m 版"并给出当前版入口 | 说明是版本级的 |
| D-19 | **检索**：全部版本进索引；命中按条目折叠成一条结果，**当前版与命中的旧版都返回**，由 AI 决定要不要扩大阅读。结果的主体是当前版（坐标、`status_note`、它自己的命中段落，若有）；`old_hits` 列出命中的旧版：`{ref: jdg_…@2, snippet, replaced_by: jdg_…@3, change_reason}`，`change_reason` 是下一版写的改动理由。旧版命中的段落在当前版里原样存在时不重复列出。排序取各版命中分数的最高者。`status_note` 写"第 2 版也命中，当前为第 3 版"。读整版旧文用 `entry_get(jdg_…@2)`。当前版被撤回、退役的排在后面（默认不返回，`include_retired` 时返回） | 修掉"只有旧版命中就什么都没有"；被改掉的说法也可能正是要找的 |
| D-20 | **下游**：关系固定在版本，引用方的 `sources` 由所引版本推出，不随新版本变化；所引版本被替代、撤回或段落变化时引用方带 `basis_changed`；所引原件退役或删除时带 `basis_lapsed`，全部失效时 `validity = lapsed`。框架页的输入同理，`inputs_changed` 照旧传播 | 引用方不被悄悄改写，又知道依据有变 |
| D-21 | **返回给 AI**：检索、联想、字面查找的每条结果带坐标（正常值省略、标记只给名与处数）、`status_note`、命中段落，以及**全部关系** `links: {out, in}`。每条关系压成一项 `{p, ref}`（自由谓词加 `label`），按谓词类别排序（立场与替代 → 证据流 → 结构 → 过程 → 框架推断 → 自由标签），不带对端正文，所以条数多也不占多少篇幅。只有一个条目的关系超过上限（检索设置 `search.links_max`，默认 50）时才截断：先保留立场、替代、佐证与反驳，再保留依据，框架推断与提及最后；截断处写明各谓词还剩多少条，用 `entry_get(ref, links=谓词, offset)` 分页取全。`entry_get` 给出完整内容：各版说明、全部出边入边（带对端标题与坐标，分页）、标记的全部出处、复核与处置历史 | 只报例外；关系全给，AI 才能顺着引用与被引继续找；上限只防一份被几百条判断引用的原件撑爆结果 |

### E. 关系图

| 编号 | 决定 | 理由 |
|---|---|---|
| D-22 | **节点是条目，边是关系**；判断是完整表述，不拆成论点。默认**按条目聚合**：同一判断依据同一份原件的多个段落画成一条线，标"依据 5 段"；证据流（依据、佐证、反驳）箭头统一画成"证据 → 结论"的方向；立场与替代关系醒目，依据线较淡，框架推断的边虚线；自由谓词的边显示标签 | 判断有多条引用，逐条画会乱；聚合后仍保留全部关系 |
| D-23 | **多元关系**（D-11 启用后）画成菱形小节点，各角色连到它 | 常用画法，与结构兼容 |
| D-24 | **筛选**：综合程度 → 依据来源 → 类型（结论 / 过程 / 规定）→ 现状 → 说明（含"转述"）；关系按谓词类别筛选；五个常用组合（默认、探索、只看本地实证、文献对照、证据链）保留，"文献对照"改为按"转述 + 外部报告"选取（修订设计稿 09 D-15） | 与条目页、检索页同名同序 |

### F. 界面与文字

| 编号 | 决定 | 理由 |
|---|---|---|
| D-25 | **显示顺序**：地位 → 类型 → 现状 → 说明。地位显示为一个组合标签（"判断 · 外部报告（同行评议）""判断 · 本地实证 + 外部报告"）；类型一个标签；现状只在不是"当前有效"、有复核或有现状标记时显示；说明里作者、原作者与说明标记用小号字，标记可点开出处 | 用户要求 |
| D-26 | **三处筛选同名同序**：条目页、检索页、关系图都按 D-24 的顺序；检索页改为服务端筛选 | 一套名字 |
| D-27 | **条目页的关系区**：按方向分两栏，栏名不暗示"都是依据"："本条指向"（出边）与"指向本条"（入边）。每栏按谓词类别分组，顺序与词表一致：证据流（依据了 / 被依据，佐证了 / 被佐证，反驳了 / 被反驳）、立场与结构、替代、过程（用到 / 产出）、框架推断（注明"不作为依据"，默认折叠）、自由标签（显示标签，注明"系统不赋予含义"）。只有证据流组参与地位与现状的推出，组标题上注明。每行显示谓词的方向说法、对端标题与它的地位标签、有效性 | 不是所有关系都是依据；分组让"哪些算依据"一眼可见 |
| D-28 | **术语**：条目、关系（谓词）、坐标（地位 + 类型 + 现状 + 说明）；"地位"只指双轴；"依据"指 `cites`，"佐证"指 `supports`；"当前地位""地位坐标""文献论断""写入时可信度""独立支持数"不再使用。检索排序 `order` 为 `relevance` / `standing`。Skill、MCP instructions、GLOSSARY、README、CORE、ARCHITECTURE 统一 | 名字与实现一致 |

## 4. 对不变式的影响

| 不变式 | 影响 |
|---|---|
| I1 账本只追加 | 不变；新版本、关系、处置都是新行 |
| I2 框架不能作为依据 | 不变；框架类谓词与自由谓词在词表里一律"不作为依据" |
| I3 可信度由系统推出 | **改为**：坐标由系统在读取时从事实与关系推出，参数不能指定；本地实证只能由人标。不再有写入时快照 |
| I6 变化只在框架层传播 | 不变；判断层只多了读时推出的标记，不改判断本身 |
| I7 输入清单指向固定版本 | **扩大**：所有关系的两端都固定到版本 |
| I8 落盘格式只增不改 | **本次例外**（2.1.0，用户决定不兼容 2.0.x 数据，格式号不变，靠 D-03 的结构检查拒绝旧目录）；之后恢复 |
| I10 新版不打开旧版数据目录 | 照用，判断依据改为 D-03 的结构检查 |
| I11 过程内容不能作为结论的依据 | 不变；对"作为依据"的谓词（`cites`、`supports`）检查宾语类型 |

## 5. 影响清单（2026-11-12 检索代码所得）

| 位置 | 改动 |
|---|---|
| `store/migrations/ledger`、`framework` | 新的基线迁移，旧迁移归档不执行；账本各表加 `version`，主键 `(id, version)`；`links` → `relations`（加 `label`、`qualifiers`、`args`）；新表 `version_states`；`entry_objects` 改为 `about` 关系；框架库 `derivation_inputs`、`pages.subject_id` 改为关系；触发器照旧禁止 UPDATE / DELETE（`purge_gate` 保留） |
| `store/ledger.py`、`core/ids.py`、`core/refs.py`、`services/workspace.py` | 读写带版本；`@n` 对所有前缀生效；`rel_` 前缀；D-03 的结构检查 |
| `__init__.py`、`pyproject.toml`、`frontend/package.json`、`uv.lock` | 版本 2.1.0（`FORMAT_VERSION` 不变） |
| 新 `core/vocab.py`；`core/model.py` | 词表；`derive_credibility` 改为读时推出 `sources`；`rank_key` 读新坐标；去掉 `LINK_RELS`、`SUPERSEDING_RELS`、`EVIDENTIAL_RELS`、`HISTORY_KINDS`、`AMEND_KINDS`、`SYSTEM_KINDS` |
| 新 `services/relations.py` | 写关系（按词表校验谓词、谁能写、宾语类型）、按两端取关系、关系概况；替代 `judgments` 的关系校验、`overview.REL_CATEGORY`、`linking` 的提及写法、`framework` 的输入清单与 `edge_add` |
| `services/judgments.py` | `write` 只存 D-05 字段；`status`、`independent_support` 去掉（由标记代替）；`amend` 并入版本服务 |
| `services/versions.py` | 重写：新版本、继承、`version_states`、`validity_of`、历史 |
| `services/review.py` | 复核带版本；复核补充的依据并入 `sources` 推出 |
| `services/retrieval.py`、`services/associate.py` | 坐标与标记按 D-12 至 D-14；`status_note` 由词表生成；检索折叠到当前版（D-19）；结果带 `links`（D-21）；联想沿谓词走 |
| `services/overview.py`、`services/inspection.py`、`services/framework.py`、`services/purge.py`、`services/extraction.py`、`services/propagation.py`、`services/linking.py`、`services/coverage.py`、`services/digest.py` | 改读新坐标、`validity`、关系；统计、列表、关系图同一口径；巡检加"常用自由谓词"清单（D-09） |
| `services/portability.py` | 导出导入按新结构 |
| `services/import_v1.py` 与相关操作、测试、文档 | 删除 |
| `interfaces/ops.py`、`interfaces/mcp.py` | 参数与返回按 D-12、D-21、D-24、D-28；新操作 `vocab.get`；`entry_get` 加 `links`、`offset` 分页；设置 `search.links_max`；检索结果加 `old_hits`；`judgment_write` 的 `relations` 接受核心谓词与 `relates`+`label`；`edge.add` 并入写关系；重新生成 `docs/reference/ops.md` |
| 前端 `labels.ts`、`ui.tsx`（`Coordinates`、`RefText` 悬停卡片）、`entryLabels.tsx`、`router.ts`、`pages/Entries.tsx`（筛选、关系区、版本历史）、`Search.tsx`、`Graph.tsx`（聚合、方向、筛选）、`Home.tsx`、`EntryPreview.tsx`、`review.tsx`、`inspection.tsx`、`digest.tsx`、`Decisions.tsx` | 标签与谓词名从 `vocab.get` 取；按 D-18、D-22 至 D-27 |
| Skill 全部、GLOSSARY、README、CORE、ARCHITECTURE、DESIGN、DOCUMENTATION_MAINTENANCE、TESTING | 按 D-28；ARCHITECTURE 不变式表按 §4 |
| `tools/seed_demo.py`、评测工作区 `Burrowl-eval` | 种子按新结构重写；评测工作区重建数据后再跑回归题 |
| 测试 | 按新结构重写；保留原有行为断言（引用固定、只追加、过程不能作依据、AI 不能标本地实证、框架不能作依据……） |

## 6. 不采用

| 方案 | 不采用的原因 |
|---|---|
| 保留写入时快照，另算当前地位 | 两套来源档会不一致；快照能从固定版本的关系推出 |
| 关系类情况（被反驳、被佐证、依据有变）做成布尔字段 | 同一件事既是关系又是字段；改为从关系推出的标记 |
| 标记只写名字 | 不知道是哪条引用出的问题；改为带出处 |
| 谓词完全封闭 | 想不到的谓词写不进去 |
| 谓词完全开放、由 AI 随意写 | 系统依赖的语义（依据、替代、反驳）会被稀释 |
| 佐证算进被佐证方的依据来源 | 地位描述的是写的人当时凭什么这么说；佐证是事后的事，放在现状 |
| 写入时把判断拆成论点、关系图展开到论点 | 要求 AI 写入时分拆或事后切句，都不划算；保留多边关系，图上按条目聚合 |
| 检索只索引当前版 | 被更正前的说法也可能是要找的 |
| 旧版命中时只返回当前版、加一个标记 | AI 看不到命中的旧文字，无法判断要不要回去读；改为当前版与旧版命中段落一起返回 |
| 关系概况只给计数与前几个 | AI 会漏掉线索；关系项很短，改为全部给出，只在超大时截断并说明 |
| 标记出处叫 `refs` | 与引用、`ref` 坐标混淆；改为 `via`，直接指向造成标记的关系 |
| 界面区分"AI 改写"与"人更正" | 用户决定只显示最终作者 |
| 升格式号、1.x 导入、2.0.x 数据兼容 | 用户决定不做 |

## 7. 未决

1. 坐标与关系概况的缓存（D-17）是否在 2.1.0 就做：重建测试数据后看检索耗时。
2. 多元关系（D-11）第一批启用哪个谓词：等有实际用例。

## 8. 任务与验收

| 任务 | 内容 | 验收 |
|---|---|---|
| T-01 | D-01、D-03、D-04、D-06、D-07：基线迁移、带版本的账本、关系表、`@n`、结构检查 | AC-01：所有条目可写第 2 版；`art_…@1#p3-2`、`jdg_…@2`、`rel_…` 能解析；UPDATE / DELETE 被触发器拒绝；2.0 的数据目录被拒绝且没有写入任何东西 |
| T-02 | D-08 至 D-10、D-16：核心谓词、自由谓词、双向、词表 | AC-02：AI 写人才能写的谓词被拒绝；以过程判断为宾语的 `cites`、`supports` 被拒绝；`relates` 必须带 `label`；同一条关系从两端都取得到，反向名正确；常用自由标签能列出 |
| T-03 | D-02、D-05：版本继承、只存事实 | AC-03：人更正一条带原作者与关系的 AI 判断，新版保留原作者、对象、关系，最终作者为人；账本里没有推论字段 |
| T-04 | D-12 至 D-15：坐标与标记 | AC-04：坐标只含四组；每个标记有场景测试，`via` 指向造成它的关系，该关系所引版本恢复正常后标记消失；人确认识别后 `recognition_unverified` 消失；被本地实证佐证的转述结论 `sources` 不变、现状有 `corroborated` |
| T-05 | D-19 至 D-21：检索、下游、返回内容 | AC-05：只有旧版命中时返回当前版，`old_hits` 带旧版引用、命中段落与改动理由；当前版也含该段落时不重复；所引判断出新版后引用方带 `basis_changed` 且 `sources` 不变；结果的 `links` 含全部出入边，超过上限时保留立场与替代、写明剩余条数，`entry_get` 能分页取全；正常条目的 `status_note` 只有地位与类型 |
| T-06 | D-18、D-22 至 D-27：界面与关系图 | AC-06：三处筛选同名同序；显示顺序为地位 → 类型 → 现状 → 说明；条目页关系区分"本条指向 / 指向本条"两栏、按谓词类别分组，框架推断与自由标签注明不作依据；版本历史每版有自己的说明；关系图同一判断对同一原件只画一条线并标段数；前端测试覆盖 |
| T-07 | 删除 1.x 导入；D-28：Skill、文档、参考 | AC-07：`tests/test_docs.py` 通过；全文不再出现"地位坐标""当前地位""文献论断""写入时可信度""独立支持数" |
| T-08 | 重建 | AC-08：全部检查通过；`seed_demo` 生成新库；评测工作区重建后回归题结果不低于 2.0.x（单独报告） |

## 9. 进度

| 日期 | 记录 |
|---|---|
| 2026-11-12 | 第五稿。用户确认：检索命中旧版时当前版与旧版命中段落都返回（`old_hits`）；关系全部返回，只在超大时截断；条目页关系区按方向分栏、按谓词类别分组，不把全部关系叫"依据"；标记出处改名 `via` 并指向关系；补"坐标从哪些事实推出"；对象名仍是条目事实，不改为 `about` 关系 |
| 2026-11-12 | 第四稿。用户确认：格式号不升（结构检查拒绝旧目录）；关系一条一行，判断不拆论点，关系图按条目聚合；谓词核心固定、外围用自由标签并定期归并；标记带出处；依据吸收依赖，佐证是反向的证据流、不改被佐证方的地位，显示在现状 |
| 2026-11-12 | 第三稿。版本 2.1.x；双向引用；主语—谓词—宾语与多元关系；说明组；不做 1.x 导入；只显示最终作者 |
| 2026-11-12 | 第二稿。存事实、推坐标、一套版本 |
| 2026-11-12 | 初稿。四组整理，保留旧字段兼容 |
