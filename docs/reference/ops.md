# 操作参考

由 `tools/gen_reference.py` 从代码生成，不要手改。MCP 工具名把点换成下划线；effect 为「仅人」「维护」的操作不出现在 MCP 中。

| 操作 | MCP 工具 | effect | 说明 |
|---|---|---|---|
| [`activity.recent`](#activityrecent) | activity_recent | 读取 | 最近的关键操作：登记原件、写判断（含更正撤回与复核）、事实记录、框架页新版本、agent 运行。 |
| [`agent.cancel`](#agentcancel) | — | 仅人（工作台/命令行） | 停止正在运行的 agent。 |
| [`agent.list`](#agentlist) | agent_list | 读取 | 列出已配置的 agent 命令，以及本机是否找得到它们。 |
| [`agent.output`](#agentoutput) | agent_output | 读取 | 读取 agent 运行的输出（从第 offset 行开始）。 |
| [`agent.runs`](#agentruns) | agent_runs | 读取 | 列出最近的 agent 运行。 |
| [`agent.start`](#agentstart) | — | 仅人（工作台/命令行） | 在本机启动一个 agent CLI 处理任务；它通过 MCP 回到本工作区读写，输出结束后登记为对话原件。 |
| [`artifact.check`](#artifactcheck) | artifact_check | 读取 | 检查外部原件（只登记路径和指纹的那类）是否还与登记时一致：changed 内容已变化，missing 原位置找不到。 只读文件，不写账本；发现变化后请把新文件登记为新版本（artifact_register 的 version_of）。 |
| [`artifact.check_status`](#artifactcheck_status) | artifact_check_status | 读取 | 上次原件检查的时间与结果、有问题的原件，以及定时检查是否开启。不重新检查。 |
| [`artifact.extract`](#artifactextract) | artifact_extract | 写入 | 抽取或补充原件的可读文本（原件本身不变，抽取单独留痕）。图片、图片页、视频默认不抽取：先用 artifact_view 看， 再用 method=ai 提交。文本变化后，引用了旧文本的判断进入待复核。公式块可以用 blocks 补充 LaTeX （先用 artifact_view 带 anchor 看公式的裁切图）。 |
| [`artifact.extraction_history`](#artifactextraction_history) | artifact_extraction_history | 读取 | 一个单元的全部抽取记录（新的在前）：方法、可信度档、抽取者、是否确认。 |
| [`artifact.layer`](#artifactlayer) | artifact_layer | 读取 | 原件的抽取层：格式、单元清单（页、幻灯片、嵌入图片…）、每个单元的状态、方法、可信度档、是否已确认、快照。 |
| [`artifact.read`](#artifactread) | artifact_read | 写入 | 读原件（当前抽取层）的一段并留下读取记录。判断引用时写返回的 cite_as（原件段落 art_…#p3-2），不必引用读取记录。 返回 notice 时说明这些段落来自 OCR / AI 识别、尚未确认，引用前请用 artifact_view 对照原件。 |
| [`artifact.register`](#artifactregister) | artifact_register | 写入 | 登记原件（只记原文与可核对的元数据，不写总结）。同内容幂等；新版本用 version_of 指向旧版本。 |
| [`artifact.segment_stats`](#artifactsegment_stats) | artifact_segment_stats | 读取 | 原件每个段落被读过几次、被哪些判断引用（按结论、过程、规定分组）。 |
| [`artifact.segments`](#artifactsegments) | artifact_segments | 读取 | 列出原件当前抽取层的全部段落：anchor（引用写 art_…#anchor）、单元、文本、可信度档（不产生读取记录）。 |
| [`artifact.snapshot`](#artifactsnapshot) | artifact_snapshot | 写入 | 为 PPTX / DOCX / Excel 生成页面快照（用本机 Office 或 LibreOffice 转成 PDF），工作台据此显示与原件一致的版式。 |
| [`artifact.verify_extraction`](#artifactverify_extraction) | — | 仅人（工作台/命令行） | 人确认抽取的文字与原件一致（逐单元或整份）。确认只针对当前那一版抽取。 |
| [`artifact.view`](#artifactview) | artifact_view | 读取 | 看原件某个单元的图像（PDF 页、PPT 页快照、图片），用于识别图片内容或对照原件复核抽取的文字； 给 anchor 时只看那一段（公式块）的裁切图。 |
| [`capture.log`](#capturelog) | capture_log | 写入 | 记一条过程事件（只追加）。对设备等对象的操作请先调用 constraints_check。条件只记当下能确定的，事后不能补写。 |
| [`constraints.check`](#constraintscheck) | constraints_check | 写入 | 对某对象动手前必须调用：列出与它相关的有效约束、决定和指令，并留下"已检查"的记录。 |
| [`data.export`](#dataexport) | — | 维护（工作台/命令行） | 导出为 JSONL + blobs + Markdown 页面（用于备份和大版本迁移）。 |
| [`data.import`](#dataimport) | — | 维护（工作台/命令行） | 从导出目录导入到空的工作区。 |
| [`data.import_v1`](#dataimport_v1) | — | 维护（工作台/命令行） | 从旧版 burrowl 数据目录导入到空的工作区（只读旧目录）。旧记录的完整字段保存在 data.v1 中。 |
| [`decision.dismiss`](#decisiondismiss) | — | 仅人（工作台/命令行） | 关闭一条待决策项，不做处理。 |
| [`decision.list`](#decisionlist) | decision_list | 读取 | 待决策列表（按影响范围排序）：术语连接、待复核、需重新综合、操作前未检查约束、传播超限。 |
| [`edge.add`](#edgeadd) | edge_add | 写入 | 在关系图中加一条 AI 推断的边（未复核）。人确认后，可能矛盾、可能替代会写回判断层。 |
| [`edge.list`](#edgelist) | edge_list | 读取 | 列出关系图的边；给 node_id 时只列与它相连的边。 |
| [`entity.list`](#entitylist) | entity_list | 读取 | 列出实体。 |
| [`entity.upsert`](#entityupsert) | entity_upsert | 写入 | 建立或取回一个实体（图的节点）。同类同名只有一个。 |
| [`entries.list`](#entrieslist) | entries_list | 读取 | 按类型、判断类型、作者、依据来源、对象浏览账本中的条目（按时间倒序）。 |
| [`entry.expand`](#entryexpand) | entry_expand | 读取 | 展开背景：来源（原件）或条件（日志、事实记录）→ 同一来源的前后内容 → 涉及的对象 → 引用了它的判断（解读，探索模式下隐藏）。 |
| [`entry.get`](#entryget) | entry_get | 读取 | 按 ID 取任意条目，附地位坐标、指出和指入的关系。 |
| [`extraction.backfill`](#extractionbackfill) | — | 维护（工作台/命令行） | 给还没有抽取层的原件补上抽取（升级后执行一次）：PDF / PPTX / DOCX 自动抽取，图片与音视频登记单元。 |
| [`extraction.status`](#extractionstatus) | extraction_status | 读取 | 抽取与引用的状态检查：未抽取或失败的原件、待抽取的图片页、未读先引、引用未确认的识别文本、待复核的判断。 |
| [`framework.review`](#frameworkreview) | — | 仅人（工作台/命令行） | 复核框架页或边。复核结论写回判断层成为一条新判断。 |
| [`graph.view`](#graphview) | graph_view | 读取 | 关系图的节点和边。node_types：artifact/record/read/judgment/page/entity；categories：evidence/support/conflict/supersede/structure/derived/mention/association。 |
| [`index.health`](#indexhealth) | index_health | 读取 | 检索索引是否覆盖全部原件、事实记录、判断和框架页；缺了用 index.rebuild 重建。 |
| [`index.rebuild`](#indexrebuild) | — | 维护（工作台/命令行） | 从账本和框架整库重建全文索引。 |
| [`judgment.amend`](#judgmentamend) | — | 仅人（工作台/命令行） | 人工修改入口：更正、撤回判断，标记原件有缺陷，或退役原件（不再单独出现，内容不变；撤回退役记录即恢复）。 底层写一条新判断指向原条目，原条目不变。 |
| [`judgment.write`](#judgmentwrite) | judgment_write | 写入 | 写一条判断（只追加）。写入时可信度由系统根据依据推出。认为别的判断不对时，写 opposes 关系，不能更正或撤回。 |
| [`object.view`](#objectview) | object_view | 读取 | 对象页：关于这个对象的全部条目，约束在前，其次有争议的结论，其余按类型和时间；不含自动日志。 |
| [`page.get`](#pageget) | page_get | 读取 | 读框架页的某个版本，附输入清单和其中已被替代的输入。 |
| [`page.list`](#pagelist) | page_list | 读取 | 列出框架页；freshness=inputs_changed 可列出需要重新综合的页面。 |
| [`page.write`](#pagewrite) | page_write | 写入 | 写框架页的新版本（实体页、概念页、综合页、非文本原件的描述）。AI 写的页面进入待复核列表。 |
| [`record.promote`](#recordpromote) | record_promote | 写入 | 把过程事件或原件片段升级为事实记录：对象、条件、方法、结果（逐字）、边界。条件不能补写，缺失的写进 gaps。 |
| [`search`](#search) | search | 读取 | 检索。结果带地位坐标，逐级排序；相关的有效约束列在最前；被替代的排在最后并带标注。 |
| [`server.info`](#serverinfo) | server_info | 读取 | 工作台进程的运行版本、已安装版本（是否需要重启）、进程号与启动时间。 |
| [`server.restart`](#serverrestart) | — | 仅人（工作台/命令行） | 重启工作台：新进程接管同一网址并加载已安装的新版本。命令行请用 burrowl restart。 |
| [`server.stop`](#serverstop) | — | 仅人（工作台/命令行） | 停止工作台。之后用 burrowl start 或开始菜单重新打开。 |
| [`session.events`](#sessionevents) | session_events | 读取 | 列出一个会话的过程日志（默认当前会话）。 |
| [`settings.check_engine`](#settingscheck_engine) | — | 仅人（工作台/命令行） | 测试能否连上外部阅读引擎（ONLYOFFICE Docs 的 /healthcheck）。 |
| [`settings.get`](#settingsget) | settings_get | 读取 | 当前数据目录的抽取方式、阅读模式的默认阅读器与索引方式设置，以及本机可用的页面快照转换器。 |
| [`settings.set`](#settingsset) | — | 仅人（工作台/命令行） | 修改当前数据目录的设置。抽取设置只影响以后的抽取（已有的抽取不变，可在原件页重新抽取）；阅读器设置立即生效。 |
| [`stats.overview`](#statsoverview) | stats_overview | 读取 | 工作区计数：判断的地位分布、框架页的时效与复核、待决策、agent 运行。 |
| [`system.status`](#systemstatus) | system_status | 读取 | 工作区概况：各类条目数量、待决策数、输入已变化的框架页数，以及当前调用者身份。 |
| [`term.decide`](#termdecide) | — | 仅人（工作台/命令行） | 人决定术语连接：写回判断层并加入别名表。new_entity 形如 {kind, name}。 |
| [`term.link`](#termlink) | term_link | 写入 | 把一个叫法连到实体：确定的直接连；只有一个候选的建未复核的边；拿不准的进入待决策列表。 |
| [`timeline`](#timeline) | timeline | 读取 | 按对象列出全部条目，按时间排序（历史类查询）。 |
| [`workspace.add`](#workspaceadd) | — | 仅人（工作台/命令行） | 登记一个数据目录；目录还不是 burrowl 数据目录时，需要 create=true 才新建。 |
| [`workspace.list`](#workspacelist) | workspace_list | 读取 | 已登记的数据目录（名称、路径、是否默认），以及本次调用连接的是哪一个。 |
| [`workspace.remove`](#workspaceremove) | — | 仅人（工作台/命令行） | 从登记表移除一个数据目录（不删除目录里的任何数据，之后可以重新登记）。默认目录不能移除。 |
| [`workspace.set_default`](#workspaceset_default) | — | 仅人（工作台/命令行） | 设为默认数据目录：工作台不带 ?db= 时打开它，不带 --data 的 MCP 与命令行也连接它。 |

## activity.recent

最近的关键操作：登记原件、写判断（含更正撤回与复核）、事实记录、框架页新版本、agent 运行。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | integer |  | `40` |  |

## agent.cancel

停止正在运行的 agent。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `run_id` | string | 是 |  |  |

## agent.list

列出已配置的 agent 命令，以及本机是否找得到它们。

无参数。

## agent.output

读取 agent 运行的输出（从第 offset 行开始）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `run_id` | string | 是 |  |  |
| `offset` | integer |  | `0` |  |

## agent.runs

列出最近的 agent 运行。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | integer |  | `50` |  |

## agent.start

在本机启动一个 agent CLI 处理任务；它通过 MCP 回到本工作区读写，输出结束后登记为对话原件。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `agent` | string | 是 |  |  |
| `prompt` | string | 是 |  |  |
| `cwd` | string（可空） |  | `None` |  |
| `preamble` | boolean |  | `True` |  |

## artifact.check

检查外部原件（只登记路径和指纹的那类）是否还与登记时一致：changed 内容已变化，missing 原位置找不到。 只读文件，不写账本；发现变化后请把新文件登记为新版本（artifact_register 的 version_of）。

无参数。

## artifact.check_status

上次原件检查的时间与结果、有问题的原件，以及定时检查是否开启。不重新检查。

无参数。

## artifact.extract

抽取或补充原件的可读文本（原件本身不变，抽取单独留痕）。图片、图片页、视频默认不抽取：先用 artifact_view 看， 再用 method=ai 提交。文本变化后，引用了旧文本的判断进入待复核。公式块可以用 blocks 补充 LaTeX （先用 artifact_view 带 anchor 看公式的裁切图）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `method` | string |  | `'auto'` | auto 用内置抽取器（重新）抽取 PDF/PPTX/DOCX / ai 提交 AI 识别的文本 / ocr 提交 OCR 工具的结果 / manual 人工转写（只有人） |
| `units` | string[]（可空） |  | `None` | auto 时只重新抽取这些单元（如 p3）；省略为整份 |
| `content` | object[]（可空） |  | `None` | ai/ocr/manual：[{unit, text}]；视频的 text 写成 "[00:01:23] 文字" 一行一块 |
| `blocks` | object[]（可空） |  | `None` | ai/ocr/manual：给公式块补充 LaTeX，[{anchor, latex}]（anchor 如 p3-4，latex 不加 $）；不改块的文字与锚点。与 content 二选一 |
| `model` | string（可空） |  | `None` | method=ai 时写明模型 |
| `note` | string |  | `''` |  |

## artifact.extraction_history

一个单元的全部抽取记录（新的在前）：方法、可信度档、抽取者、是否确认。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `unit` | string | 是 |  |  |

## artifact.layer

原件的抽取层：格式、单元清单（页、幻灯片、嵌入图片…）、每个单元的状态、方法、可信度档、是否已确认、快照。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |

## artifact.read

读原件（当前抽取层）的一段并留下读取记录。判断引用时写返回的 cite_as（原件段落 art_…#p3-2），不必引用读取记录。 返回 notice 时说明这些段落来自 OCR / AI 识别、尚未确认，引用前请用 artifact_view 对照原件。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `locator` | string（可空） |  | `None` | 省略读全部；段落 seg-3 / p3-2；单元 p3；单元范围 p3:p5；旧写法 seg:N-M |

## artifact.register

登记原件（只记原文与可核对的元数据，不写总结）。同内容幂等；新版本用 version_of 指向旧版本。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `kind` | string | 是 |  | file/conversation/literature/dataset/image/log |
| `source_class` | string | 是 |  | local 本地实证（本项目内执行、测量或直接观察）/ external 外部报告 / inferred 推断 |
| `path` | string（可空） |  | `None` |  |
| `text` | string（可空） |  | `None` |  |
| `title` | string（可空） |  | `None` |  |
| `storage` | string |  | `'managed'` | managed 复制保存 / referenced 只登记路径和指纹 |
| `external_tier` | string（可空） |  | `None` | peer_reviewed/preprint/vendor/web |
| `version_of` | string（可空） |  | `None` |  |
| `metadata` | object（可空） |  | `None` |  |
| `objects` | string[]（可空） |  | `None` |  |

## artifact.segment_stats

原件每个段落被读过几次、被哪些判断引用（按结论、过程、规定分组）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |

## artifact.segments

列出原件当前抽取层的全部段落：anchor（引用写 art_…#anchor）、单元、文本、可信度档（不产生读取记录）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |

## artifact.snapshot

为 PPTX / DOCX / Excel 生成页面快照（用本机 Office 或 LibreOffice 转成 PDF），工作台据此显示与原件一致的版式。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `force` | boolean |  | `False` |  |

## artifact.verify_extraction

人确认抽取的文字与原件一致（逐单元或整份）。确认只针对当前那一版抽取。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `units` | string[]（可空） |  | `None` | 要确认的单元；省略为全部有文本的单元 |
| `note` | string |  | `''` |  |

## artifact.view

看原件某个单元的图像（PDF 页、PPT 页快照、图片），用于识别图片内容或对照原件复核抽取的文字； 给 anchor 时只看那一段（公式块）的裁切图。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `unit` | string |  | `''` | 单元：PDF/PPT 的页 p3、图片 img、嵌入图片 img2 |
| `anchor` | string（可空） |  | `None` | 段落锚点（如 p3-4）：只看这一块在原件上的裁切图，用于识别公式 |

## capture.log

记一条过程事件（只追加）。对设备等对象的操作请先调用 constraints_check。条件只记当下能确定的，事后不能补写。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `op_name` | string | 是 |  | 操作名，如 exec.shell、measure.pressure |
| `input` | object（可空） |  | `None` |  |
| `output` | string（可空） |  | `None` |  |
| `conditions` | object（可空） |  | `None` |  |
| `objects` | string[]（可空） |  | `None` |  |
| `source_class` | string |  | `'local'` | local 本地实证（默认）/ inferred 推断（如对话消息） |

## constraints.check

对某对象动手前必须调用：列出与它相关的有效约束、决定和指令，并留下"已检查"的记录。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `objects` | string[] | 是 |  |  |

## data.export

导出为 JSONL + blobs + Markdown 页面（用于备份和大版本迁移）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `target` | string | 是 |  |  |

## data.import

从导出目录导入到空的工作区。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `source` | string | 是 |  |  |

## data.import_v1

从旧版 burrowl 数据目录导入到空的工作区（只读旧目录）。旧记录的完整字段保存在 data.v1 中。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `source` | string | 是 |  | 旧版 burrowl 数据目录（含 .burrowl/） |

## decision.dismiss

关闭一条待决策项，不做处理。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `decision_id` | string | 是 |  |  |
| `reason` | string | 是 |  |  |

## decision.list

待决策列表（按影响范围排序）：术语连接、待复核、需重新综合、操作前未检查约束、传播超限。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `status` | string（可空） |  | `'open'` |  |
| `kind` | string（可空） |  | `None` |  |

## edge.add

在关系图中加一条 AI 推断的边（未复核）。人确认后，可能矛盾、可能替代会写回判断层。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `rel` | string | 是 |  | may_contradict/may_supersede/similar/analogy/related |
| `src_id` | string | 是 |  |  |
| `dst_id` | string | 是 |  |  |
| `reason` | string | 是 |  |  |
| `inputs` | string[]（可空） |  | `None` |  |

## edge.list

列出关系图的边；给 node_id 时只列与它相连的边。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `node_id` | string（可空） |  | `None` |  |
| `rel` | string（可空） |  | `None` |  |
| `review` | string（可空） |  | `None` |  |

## entity.list

列出实体。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `kind` | string（可空） |  | `None` |  |

## entity.upsert

建立或取回一个实体（图的节点）。同类同名只有一个。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `kind` | string | 是 |  | device/system/material/person/concept/method/term |
| `name` | string | 是 |  |  |
| `description` | string（可空） |  | `None` |  |

## entries.list

按类型、判断类型、作者、依据来源、对象浏览账本中的条目（按时间倒序）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `kind` | string |  | `'judgment'` | artifact/event/record/read/judgment |
| `judgment_kind` | string（可空） |  | `None` | conclusion/process/normative，或 system（复核、更正、撤回、原件缺陷） |
| `author_kind` | string（可空） |  | `None` |  |
| `source_class` | string（可空） |  | `None` |  |
| `object` | string（可空） |  | `None` |  |
| `query` | string（可空） |  | `None` |  |
| `include_retired` | boolean |  | `False` | 原件列表是否包含已退役的原件 |
| `limit` | integer |  | `50` |  |
| `offset` | integer |  | `0` |  |

## entry.expand

展开背景：来源（原件）或条件（日志、事实记录）→ 同一来源的前后内容 → 涉及的对象 → 引用了它的判断（解读，探索模式下隐藏）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | 是 |  | 条目 ID；原件段落写成 art_…#p3-2 或 art_…#seg-N |
| `mode` | string |  | `'reuse'` |  |

## entry.get

按 ID 取任意条目，附地位坐标、指出和指入的关系。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | 是 |  |  |

## extraction.backfill

给还没有抽取层的原件补上抽取（升级后执行一次）：PDF / PPTX / DOCX 自动抽取，图片与音视频登记单元。

无参数。

## extraction.status

抽取与引用的状态检查：未抽取或失败的原件、待抽取的图片页、未读先引、引用未确认的识别文本、待复核的判断。

无参数。

## framework.review

复核框架页或边。复核结论写回判断层成为一条新判断。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `item_id` | string | 是 |  |  |
| `verdict` | string | 是 |  | confirm / reject |
| `reason` | string | 是 |  |  |
| `cites` | string[]（可空） |  | `None` |  |

## graph.view

关系图的节点和边。node_types：artifact/record/read/judgment/page/entity；categories：evidence/support/conflict/supersede/structure/derived/mention/association。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `center` | string（可空） |  | `None` |  |
| `hops` | integer |  | `2` |  |
| `node_types` | string[]（可空） |  | `None` |  |
| `categories` | string[]（可空） |  | `None` |  |
| `hide_superseded` | boolean |  | `False` |  |
| `limit` | integer |  | `300` |  |

## index.health

检索索引是否覆盖全部原件、事实记录、判断和框架页；缺了用 index.rebuild 重建。

无参数。

## index.rebuild

从账本和框架整库重建全文索引。

无参数。

## judgment.amend

人工修改入口：更正、撤回判断，标记原件有缺陷，或退役原件（不再单独出现，内容不变；撤回退役记录即恢复）。 底层写一条新判断指向原条目，原条目不变。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `mode` | string | 是 |  | correction 更正 / retraction 撤回 / defect 原件有缺陷 / retirement 原件退役 |
| `target` | string | 是 |  |  |
| `reason` | string | 是 |  |  |
| `cites` | string[]（可空） |  | `None` |  |

## judgment.write

写一条判断（只追加）。写入时可信度由系统根据依据推出。认为别的判断不对时，写 opposes 关系，不能更正或撤回。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `kind` | string | 是 |  | conclusion 结论（关于对象的陈述，可作依据）/ process 过程（提问、尝试、停下的路线、目的；不能作为结论的依据）/ normative 规定（约束、决定、指令） |
| `text` | string | 是 |  | 写全对象和条件，不用指代词，不写「显然」「关键在于」等措辞 |
| `cites` | string[]（可空） |  | `None` | 依据：原件段落 art_…#p3-2（推荐，取 artifact_read 返回的 cite_as）、原件、事实记录、读取记录或判断的 ID；不能是框架页 |
| `objects` | string[]（可空） |  | `None` |  |
| `conditions` | string（可空） |  | `None` |  |
| `relations` | object[]（可空） |  | `None` | 与其他判断的关系 [{rel, target, condition?}]，rel 取 supports/opposes/depends_on/answers/targets/coexists_under |
| `external_author` | string（可空） |  | `None` | 摘录文献论断时填原作者 |
| `revises` | string（可空） |  | `None` |  |
| `revise_reason` | string（可空） |  | `None` |  |
| `local_observation` | boolean |  | `False` | 人亲自看到或测到（只有人能勾选） |
| `reopen_condition` | string（可空） |  | `None` | 过程内容：停下的路线在什么条件下值得重新打开 |

## object.view

对象页：关于这个对象的全部条目，约束在前，其次有争议的结论，其余按类型和时间；不含自动日志。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `object` | string | 是 |  | 实体 ID（ent_…）或对象名 |

## page.get

读框架页的某个版本，附输入清单和其中已被替代的输入。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `page` | string | 是 |  | pg_… 或 pg_…@版本号 |

## page.list

列出框架页；freshness=inputs_changed 可列出需要重新综合的页面。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `type` | string（可空） |  | `None` |  |
| `freshness` | string（可空） |  | `None` |  |

## page.write

写框架页的新版本（实体页、概念页、综合页、非文本原件的描述）。AI 写的页面进入待复核列表。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `type` | string | 是 |  | entity/concept/synthesis/description |
| `title` | string | 是 |  |  |
| `body` | string | 是 |  | Markdown 正文；引用写成 [[ID]] |
| `inputs` | string[]（可空） |  | `None` | 输入清单：所依据的原件、判断、页面版本（pg_…@N） |
| `slug` | string（可空） |  | `None` |  |
| `summary` | string（可空） |  | `None` |  |
| `subject_id` | string（可空） |  | `None` |  |

## record.promote

把过程事件或原件片段升级为事实记录：对象、条件、方法、结果（逐字）、边界。条件不能补写，缺失的写进 gaps。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `event_id` | string（可空） |  | `None` |  |
| `artifact_id` | string（可空） |  | `None` |  |
| `locator` | string（可空） |  | `None` |  |
| `objects` | string[]（可空） |  | `None` |  |
| `method` | string（可空） |  | `None` |  |
| `result` | string（可空） |  | `None` |  |
| `boundary` | string |  | `'complete'` |  |
| `gaps` | string[]（可空） |  | `None` |  |
| `conditions` | object（可空） |  | `None` |  |
| `reason` | string |  | `''` |  |

## search

检索。结果带地位坐标，逐级排序；相关的有效约束列在最前；被替代的排在最后并带标注。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 |  |  |
| `layers` | string[]（可空） |  | `None` | original/judgment/framework |
| `objects` | string[]（可空） |  | `None` |  |
| `mode` | string |  | `'reuse'` | reuse 复用 / explore 探索（不给框架页，默认也不给过程内容） |
| `include_log` | boolean |  | `False` |  |
| `include_process` | boolean（可空） |  | `None` | 是否返回过程内容；省略时复用模式返回、探索模式不返回 |
| `include_retired` | boolean |  | `False` | 是否返回已退役的原件（排在最后） |
| `limit` | integer |  | `20` |  |

## server.info

工作台进程的运行版本、已安装版本（是否需要重启）、进程号与启动时间。

无参数。

## server.restart

重启工作台：新进程接管同一网址并加载已安装的新版本。命令行请用 burrowl restart。

无参数。

## server.stop

停止工作台。之后用 burrowl start 或开始菜单重新打开。

无参数。

## session.events

列出一个会话的过程日志（默认当前会话）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `session_id` | string（可空） |  | `None` |  |

## settings.check_engine

测试能否连上外部阅读引擎（ONLYOFFICE Docs 的 /healthcheck）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `url` | string（可空） |  | `None` | 引擎地址；省略时用设置里的 ONLYOFFICE 地址 |

## settings.get

当前数据目录的抽取方式、阅读模式的默认阅读器与索引方式设置，以及本机可用的页面快照转换器。

无参数。

## settings.set

修改当前数据目录的设置。抽取设置只影响以后的抽取（已有的抽取不变，可在原件页重新抽取）；阅读器设置立即生效。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `values` | object | 是 |  | 如 {"extraction.pdf": "off"} |

## stats.overview

工作区计数：判断的地位分布、框架页的时效与复核、待决策、agent 运行。

无参数。

## system.status

工作区概况：各类条目数量、待决策数、输入已变化的框架页数，以及当前调用者身份。

无参数。

## term.decide

人决定术语连接：写回判断层并加入别名表。new_entity 形如 {kind, name}。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `decision_id` | string | 是 |  |  |
| `entity_id` | string（可空） |  | `None` |  |
| `new_entity` | object（可空） |  | `None` |  |
| `note` | string |  | `''` |  |

## term.link

把一个叫法连到实体：确定的直接连；只有一个候选的建未复核的边；拿不准的进入待决策列表。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `term` | string | 是 |  |  |
| `source_id` | string（可空） |  | `None` |  |
| `excerpt` | string（可空） |  | `None` |  |
| `proposed_entity_id` | string（可空） |  | `None` |  |

## timeline

按对象列出全部条目，按时间排序（历史类查询）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `object` | string | 是 |  |  |

## workspace.add

登记一个数据目录；目录还不是 burrowl 数据目录时，需要 create=true 才新建。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `path` | string | 是 |  | 数据目录的绝对路径 |
| `name` | string（可空） |  | `None` | 显示名称（用在网址 ?db= 里）；默认取目录名 |
| `make_default` | boolean |  | `False` |  |
| `create` | boolean |  | `False` | 目录里还没有 burrowl 数据时是否新建 |

## workspace.list

已登记的数据目录（名称、路径、是否默认），以及本次调用连接的是哪一个。

无参数。

## workspace.remove

从登记表移除一个数据目录（不删除目录里的任何数据，之后可以重新登记）。默认目录不能移除。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  | 数据目录名称或路径 |

## workspace.set_default

设为默认数据目录：工作台不带 ?db= 时打开它，不带 --data 的 MCP 与命令行也连接它。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | string | 是 |  | 数据目录名称或路径 |
