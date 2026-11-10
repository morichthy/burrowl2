# 操作参考

由 `tools/gen_reference.py` 从代码生成，不要手改。MCP 工具名把点换成下划线；effect 为「仅人」「维护」的操作不出现在 MCP 中。

| 操作 | MCP 工具 | effect | 说明 |
|---|---|---|---|
| [`activity.recent`](#activityrecent) | activity_recent | 读取 | 最近的关键操作：登记原件、写判断（含更正撤回与复核）、事实记录、框架页新版本、agent 运行。 |
| [`agent.cancel`](#agentcancel) | — | 仅人（工作台/命令行） | 停止正在运行的 agent。 |
| [`agent.delete`](#agentdelete) | — | 仅人（工作台/命令行） | 删除一条 agent 配置。巡检员、复核员或大模型正在使用时拒绝；已有运行记录保留。 |
| [`agent.list`](#agentlist) | agent_list | 读取 | 列出已配置的 agent 命令，以及本机是否找得到它们。 |
| [`agent.output`](#agentoutput) | agent_output | 读取 | 读取 agent 运行的输出（从第 offset 行开始）。 |
| [`agent.runs`](#agentruns) | agent_runs | 读取 | 列出最近的 agent 运行。 |
| [`agent.save_command`](#agentsave_command) | — | 仅人（工作台/命令行） | 新增、编辑或改名 agent 的完整启动命令。保存后可用于巡检、复核或大模型调用。 |
| [`agent.set_command`](#agentset_command) | — | 仅人（工作台/命令行） | 修改 agent 命令模板里的可执行文件，其余参数不变（设计稿 08 D-39）。命令不在 PATH 里时填完整路径。 |
| [`agent.start`](#agentstart) | — | 仅人（工作台/命令行） | 在本机启动一个 agent CLI 处理任务；它通过 MCP 回到本工作区读写，输出留在运行日志。 |
| [`agent.test`](#agenttest) | — | 仅人（工作台/命令行） | 测试 agent 连接：命令能否找到、能否经 MCP 调用 burrowl、身份是否正确（设计稿 08 D-26）。会真的启动一次 agent。 |
| [`artifact.check`](#artifactcheck) | artifact_check | 读取 | 检查外部原件（只登记路径和指纹的那类）是否还与登记时一致：changed 内容已变化，missing 原位置找不到。 只读文件，不写账本；发现变化后请把新文件登记为新版本（artifact_register 的 version_of）。 |
| [`artifact.check_status`](#artifactcheck_status) | artifact_check_status | 读取 | 上次原件检查的时间与结果、有问题的原件，以及定时检查是否开启。不重新检查。 |
| [`artifact.delete`](#artifactdelete) | — | 仅人（工作台/命令行） | 彻底删除一份已退役的原件及预览里列出的条目：不留任何记录，不能撤销（设计稿 07 D-04、D-05）。 |
| [`artifact.delete_preview`](#artifactdelete_preview) | artifact_delete_preview | 读取 | 删除一份已退役的原件会删掉什么（依据全部来自它的判断与事实记录等）、哪些条目保留并标为"所引原件已删除"、 哪些框架页会标为输入已变化；confirm 是执行删除时要带上的核对值（设计稿 07 D-04）。 |
| [`artifact.extract`](#artifactextract) | artifact_extract | 写入 | 抽取或补充原件的可读文本（原件本身不变，抽取单独留痕）。图片、图片页、视频默认不抽取：先用 artifact_view 看， 再用 method=ai 提交。文本变化后，引用了旧文本的判断进入待复核。公式块可以用 blocks 补充 LaTeX （先用 artifact_view 带 anchor 看公式的裁切图）。 |
| [`artifact.extraction_history`](#artifactextraction_history) | artifact_extraction_history | 读取 | 一个单元的全部抽取记录（新的在前）：方法、可信度档、抽取者、是否确认。 |
| [`artifact.layer`](#artifactlayer) | artifact_layer | 读取 | 原件的抽取层：格式、单元清单（页、幻灯片、嵌入图片…）、每个单元的状态、方法、可信度档、是否已确认、快照。 |
| [`artifact.layout_engine`](#artifactlayout_engine) | artifact_layout_engine | 写入 | 用本地版面引擎（MinerU）处理一份 PDF：给公式块补 LaTeX、给段落记下行内公式；replace 时整份替换抽取； 抽取方式为 MinerU 时，还没被引用的原件采用引擎的分段。 |
| [`artifact.policy`](#artifactpolicy) | — | 仅人（工作台/命令行） | 标记原件是否外发：不外发的原件原文不进巡检包，巡检运行里读不到（设计稿 08 D-30、D-31）。 |
| [`artifact.read`](#artifactread) | artifact_read | 写入 | 读原件（当前抽取层）的一段并留下读取记录。判断引用时写返回的 cite_as（原件段落 art_…#p3-2），不必引用读取记录。 返回 notice 时说明这些段落来自 OCR / AI 识别、尚未确认，引用前请用 artifact_view 对照原件。 |
| [`artifact.recognize_formula`](#artifactrecognize_formula) | artifact_recognize_formula | 写入 | 识别公式块的 LaTeX：结果标为模型识别（OCR 档或 AI 档），需要人确认。 |
| [`artifact.register`](#artifactregister) | artifact_register | 写入 | 登记有核对或复用价值的原件，保留原文与可核对的元数据。同内容幂等；新版本用 version_of 指向旧版本。 |
| [`artifact.replace`](#artifactreplace) | — | 仅人（工作台/命令行） | 给已退役或已删除的原件指定替代原件。引用旧原件段落的判断按段落指纹在替代原件里比对，对不上的进入待复核； 受影响的框架页标为"输入已变化"，由人交给 agent 重新综合（设计稿 07 D-03）。 |
| [`artifact.retire`](#artifactretire) | — | 仅人（工作台/命令行） | 退役原件（内容没错，只是不再单独出现在列表和检索里）或撤销退役。记为原件的状态历史，不写成判断。 |
| [`artifact.segment_stats`](#artifactsegment_stats) | artifact_segment_stats | 读取 | 原件每个段落被读过几次、被哪些判断引用（按结论、过程、规定分组）。 |
| [`artifact.segments`](#artifactsegments) | artifact_segments | 读取 | 列出原件当前抽取层的全部段落：anchor（引用写 art_…#anchor）、单元、文本、可信度档（不产生读取记录）。 |
| [`artifact.snapshot`](#artifactsnapshot) | artifact_snapshot | 写入 | 为 PPTX / DOCX / Excel 生成页面快照（用本机 Office 或 LibreOffice 转成 PDF），工作台据此显示与原件一致的版式。 |
| [`artifact.verify_extraction`](#artifactverify_extraction) | — | 仅人（工作台/命令行） | 人确认抽取的文字与原件一致（逐单元或整份）。确认只针对当前那一版抽取。 |
| [`artifact.view`](#artifactview) | artifact_view | 读取 | 看原件某个单元的图像（PDF 页、PPT 页快照、图片），用于识别图片内容或对照原件复核抽取的文字； 给 anchor 时只看那一段（公式块）的裁切图。 |
| [`capture.log`](#capturelog) | capture_log | 写入 | 记录有核对或复用价值的实际过程（只追加）。动手前先调用 constraints_check，事后不能补写条件。 |
| [`constraints.check`](#constraintscheck) | constraints_check | 写入 | 对某对象动手前必须调用：列出与它相关的有效约束、决定和指令，并留下"已检查"的记录。 |
| [`coverage.view`](#coverageview) | coverage_view | 读取 | 覆盖图：原件段落分五档（被引用 / 读过未引 / 命中未读 / 相关未读 / 冷区）。框架内容，不能作为依据； 没读过不等于有用。 |
| [`data.export`](#dataexport) | — | 维护（工作台/命令行） | 导出为 JSONL + blobs + Markdown 页面（用于备份和大版本迁移）。 |
| [`data.import`](#dataimport) | — | 维护（工作台/命令行） | 从导出目录导入到空的工作区。 |
| [`data.import_v1`](#dataimport_v1) | — | 维护（工作台/命令行） | 从旧版 burrowl 数据目录导入到空的工作区（只读旧目录）。旧记录的完整字段保存在 data.v1 中。 |
| [`decision.dismiss`](#decisiondismiss) | — | 仅人（工作台/命令行） | 关闭一条待决策项，不做处理。 |
| [`decision.list`](#decisionlist) | decision_list | 读取 | 待决策列表（按影响范围排序）：术语连接、待复核、需重新综合、操作前未检查约束、传播超限。 影响范围为 0 的是低影响项（工作台默认折叠，设计稿 04 D-07）。 |
| [`edge.add`](#edgeadd) | edge_add | 写入 | 在关系图中加一条 AI 推断的边（未复核）。人确认后，可能矛盾、可能替代会写回判断层。 |
| [`edge.list`](#edgelist) | edge_list | 读取 | 列出关系图的边；给 node_id 时只列与它相连的边。 |
| [`entity.list`](#entitylist) | entity_list | 读取 | 列出实体。 |
| [`entity.upsert`](#entityupsert) | entity_upsert | 写入 | 建立或取回一个实体（图的节点）。同类同名只有一个。 |
| [`entries.list`](#entrieslist) | entries_list | 读取 | 按类型、判断类型、作者、依据来源、对象浏览账本中的条目（按时间倒序）。 |
| [`entry.correct`](#entrycorrect) | — | 仅人（工作台/命令行） | 在同一条目下追加完整版本。文件可填路径，判断可指定新版依据；原始过程保留，核实结果单独标明。 |
| [`entry.destroy`](#entrydestroy) | — | 仅人（工作台/命令行） | 按确认指纹彻底销毁一个已退役版本。旧引用保留其指向，内容不可恢复。 |
| [`entry.destroy_preview`](#entrydestroy_preview) | — | 仅人（工作台/命令行） | 预览一个已退役版本的销毁范围，返回供人确认的指纹。 |
| [`entry.expand`](#entryexpand) | entry_expand | 读取 | 展开背景：来源（原件）或条件（日志、事实记录）→ 同一来源的前后内容 → 涉及的对象 → 引用了它的判断（解读，探索模式下隐藏）。 |
| [`entry.get`](#entryget) | entry_get | 读取 | 按原始引用 ID 取条目，附版本历史、地位坐标和关系。 |
| [`entry.labels`](#entrylabels) | — | 仅人（工作台/命令行） | 批量获取工作台显示名，按原引用返回；不可用条目的名称为空。 |
| [`entry.version_state`](#entryversion_state) | — | 仅人（工作台/命令行） | 追加版本状态：withdraw 撤回、unwithdraw 取消撤回、reactivate 重新生效、defect 标记缺陷、undefect 取消缺陷标记、retire 退役、restore 取消退役。 |
| [`extraction.ai_check`](#extractionai_check) | — | 仅人（工作台/命令行） | 把识别结果交给大模型看图核对（只有人能发起；设计稿 04 D-22、D-23）。结果为"AI 已核对"，不等于人已确认。 |
| [`extraction.backfill`](#extractionbackfill) | — | 维护（工作台/命令行） | 给还没有抽取层的原件补上抽取（升级后执行一次）：PDF / PPTX / DOCX 自动抽取，图片与音视频登记单元。 |
| [`extraction.recognitions`](#extractionrecognitions) | extraction_recognitions | 读取 | 待确认的识别：OCR / AI 识别、未经人确认的段落与公式 LaTeX，以及 AI 核对的结果（设计稿 04 D-25）。 |
| [`extraction.status`](#extractionstatus) | extraction_status | 读取 | 抽取与引用的状态检查：未抽取或失败的原件、待抽取的图片页、未读先引、引用未确认的识别文本、待复核的判断。 |
| [`finding.resolve`](#findingresolve) | — | 仅人（工作台/命令行） | 人处理一条巡检发现。普通采纳只关闭发现；明确应用复核意见时才新增结论或追加更正。 |
| [`framework.review`](#frameworkreview) | — | 仅人（工作台/命令行） | review.submit 的旧名称，参数与效果相同。 |
| [`graph.view`](#graphview) | graph_view | 读取 | 关系图的节点和边。node_types：artifact/record/read/judgment/page/entity；categories：evidence/support/conflict/supersede/structure/derived/mention/association。 |
| [`index.embed`](#indexembed) | — | 维护（工作台/命令行） | 补建检索单元的向量（工作台会在后台自动补；评测和首次升级时可以用它一次补完）。 |
| [`index.health`](#indexhealth) | index_health | 读取 | 检索索引是否覆盖全部原件、事实记录、判断和框架页（缺了用 index.rebuild 重建）、是否按当前的检索单元长度建成 （units.current；units.rebuild 是本进程里的后台重建进度），以及向量通道（已建 done / total）与重排的状态。 |
| [`index.rebuild`](#indexrebuild) | — | 维护（工作台/命令行） | 从账本和框架整库重建全文索引。后台重建逐条取锁、不先清空，进度见 index.health 的 units.rebuild。 |
| [`inspection.close`](#inspectionclose) | — | 仅人（工作台/命令行） | 关闭一期巡检（未处理的发现仍留在待决策里）。 |
| [`inspection.export`](#inspectionexport) | inspection_export | 读取 | 离线巡检包（Markdown）：任务、段落原文（不外发的原件不含原文）与要求的 JSON 回答格式。 |
| [`inspection.findings`](#inspectionfindings) | inspection_findings | 读取 | 巡检发现列表（kind=finding 的待决策项，数据里有说明、依据、针对的条目、复核员意见）。 |
| [`inspection.get`](#inspectionget) | inspection_get | 写入 | 领取巡检包：巡检员得到任务清单（要读的段落、要回答的问题），复核员得到待复核的发现。领取会记下本会话。 |
| [`inspection.guidelines`](#inspectionguidelines) | inspection_guidelines | 读取 | 当前生效的巡检原则（设置为空时是默认文本）、默认文本，以及系统强制、不能改的巡检员与复核员规则（设计稿 08 D-36）。 |
| [`inspection.import`](#inspectionimport) | — | 仅人（工作台/命令行） | 贴回离线巡检的结果：记为经人转交，没有读取记录，复核员不能确认。 |
| [`inspection.list`](#inspectionlist) | inspection_list | 读取 | 最近几期巡检包的摘要。 |
| [`inspection.prepare`](#inspectionprepare) | — | 仅人（工作台/命令行） | 现在准备巡检包：在本机做规则检查与探索抽样，不调用大模型。上一期准备好还没开跑时就地更新它。 |
| [`inspection.prompt`](#inspectionprompt) | inspection_prompt | 读取 | 给 AI 客户端的一句领取提示（巡检员或复核员）；agent 不可用时由人复制。 |
| [`inspection.start`](#inspectionstart) | — | 仅人（工作台/命令行） | 用设置里的巡检员或复核员 agent 启动一次运行（只能由人点，设计稿 08 D-01、D-02）。 |
| [`inspection.status`](#inspectionstatus) | inspection_status | 读取 | 定期巡检的概况：最近一期巡检包、是否到期、巡检员与复核员 agent 是否可用。 |
| [`inspection.submit`](#inspectionsubmit) | inspection_submit | 写入 | 巡检员提交一个任务的结果。issue 生成一条巡检发现：一项待决策，等复核员和人处理，不能被引用； 你不能更正、撤回判断，也不要写判断。 |
| [`inspection.tasks`](#inspectiontasks) | inspection_tasks | 读取 | 本期巡检的任务清单（工作台查看用，不记领取）：检查类别、规则看到了什么、针对的条目、要读的段落、是否已检查。 |
| [`judgment.amend`](#judgmentamend) | — | 仅人（工作台/命令行） | 兼容人工修改入口。更正需提供新版正文 text；撤回和缺陷只追加版本状态。 |
| [`judgment.write`](#judgmentwrite) | judgment_write | 写入 | 只收录工程、科研或其他重要、经常性工作中有长期价值的判断。只追加，可信度由依据推出。巡检会话不能写判断。 |
| [`models.check`](#modelscheck) | — | 仅人（工作台/命令行） | 测试连接：检查模型服务，或启动选中的 Agent CLI 做一次文本问答。 |
| [`models.status`](#modelsstatus) | models_status | 读取 | 本地模型与大模型的槽位（工具、地址、是否本机、是否自动运行）与本进程里最近的模型任务。 |
| [`models.stop`](#modelsstop) | — | 仅人（工作台/命令行） | 关闭 burrowl 启动的 MinerU 服务（设计稿 05 D-20）。 |
| [`object.view`](#objectview) | object_view | 读取 | 对象页：关于这个对象的全部条目，约束在前，其次有争议的结论，其余按类型和时间；不含自动日志。 |
| [`page.get`](#pageget) | page_get | 读取 | 读框架页的某个版本，附输入清单和其中已被替代的输入。 |
| [`page.list`](#pagelist) | page_list | 读取 | 列出框架页；freshness=inputs_changed 可列出需要重新综合的页面。 |
| [`page.write`](#pagewrite) | page_write | 写入 | 写框架页的新版本（实体页、概念页、综合页、非文本原件的描述）。AI 写的页面进入待复核列表。 |
| [`record.promote`](#recordpromote) | record_promote | 写入 | 把过程事件或原件片段升级为事实记录：对象、条件、方法、结果（逐字）、边界。条件不能补写，缺失的写进 gaps。 方法写到一个不知道目的的人能复现或核对：数据怎么产生、各组怎么设置、指标怎么定义，并用 cites 指向原文。 |
| [`review.ai_submit`](#reviewai_submit) | review_ai_submit | 写入 | AI 复核：对照原件层、判断层核对一个条目。结果另记一档（AI 已复核），不等于人已复核；拿不准就交 unsure。 |
| [`review.history`](#reviewhistory) | review_history | 读取 | 一个条目的复核与变更历史、当前复核状态，以及现在能否交给 AI 复核（巡检发现的待决策编号 dec_… 返回它的提交、复核员意见与处理）。 |
| [`review.request`](#reviewrequest) | review_request | 写入 | 请人复核：把条目加入待决策列表。 |
| [`review.sample`](#reviewsample) | review_sample | 读取 | 本周抽查：从 AI 生成未复核的框架页里按周固定地挑几页，供人用确认 / 驳回处理。 |
| [`review.submit`](#reviewsubmit) | — | 仅人（工作台/命令行） | 人复核一个条目。结论记为它的复核历史，不写成新判断；判断的当前地位由依据（含补充的）重新推出。 |
| [`search`](#search) | search | 读取 | 检索（关键词 + 向量，设置为重排时重排）。名次只表示相关度；每条带地位坐标与 status_note 说明可靠程度。 相关的有效约束列在最前；被替代、已退役的排在当前条目之后。每条带命中的段落（cite_as、read_as）、 未展示的命中数（more_matches）、依据（basis）和一跳关系（relations）；params 是本次用的检索参数（每条最多展示 几个命中单元等，人在设置里调整）；hints 说明结果的局限。 |
| [`search.associate`](#searchassociate) | search_associate | 读取 | 联想：从检索命中（或给定条目）出发，顺着判断关系、引用、输入清单、实体提及、共享对象、向量近邻走 1–2 跳， 找出检索没有命中但连着的条目。每条带经过的路径 via，标为"联想，非检索命中"；不是默认检索的一部分。 |
| [`search.exact`](#searchexact) | search_exact | 读取 | 字面查找：列出含有这段文字的段落（带 cite_as），按条目分组，不排序。用于设备编号、错误码、函数名、原句。 |
| [`server.info`](#serverinfo) | server_info | 读取 | 工作台进程的运行版本、已安装版本（是否需要重启）、进程号与启动时间。 |
| [`server.restart`](#serverrestart) | — | 仅人（工作台/命令行） | 重启工作台：新进程接管同一网址并加载已安装的新版本。命令行请用 burrowl restart。 |
| [`server.stop`](#serverstop) | — | 仅人（工作台/命令行） | 停止工作台。之后用 burrowl start 或开始菜单重新打开。 |
| [`session.events`](#sessionevents) | session_events | 读取 | 列出一个会话的过程日志（默认当前会话）。 |
| [`settings.check_engine`](#settingscheck_engine) | — | 仅人（工作台/命令行） | 测试能否连上外部阅读引擎（ONLYOFFICE Docs 的 /healthcheck）。 |
| [`settings.get`](#settingsget) | settings_get | 读取 | 当前数据目录的抽取方式、阅读模式的默认阅读器与索引方式设置，以及本机可用的页面快照转换器。 |
| [`settings.set`](#settingsset) | — | 仅人（工作台/命令行） | 修改当前数据目录的设置。抽取设置只影响以后的抽取（已有的抽取不变，可在原件页重新抽取）；阅读器设置立即生效； 检索参数（retrieval.*）对工作台和 AI 的下一次调用生效；检索单元长度（index.units_*）保存后在后台整库重建索引 （进度见 index.health 的 units.rebuild），向量随后在后台重算。每次修改记一条过程日志（旧值、新值，密钥不记原文）。 |
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

## agent.delete

删除一条 agent 配置。巡检员、复核员或大模型正在使用时拒绝；已有运行记录保留。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `agent` | string | 是 |  |  |

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

## agent.save_command

新增、编辑或改名 agent 的完整启动命令。保存后可用于巡检、复核或大模型调用。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `agent` | string | 是 |  |  |
| `command` | string[] | 是 |  | 可执行文件和逐项启动参数；参数中须有 {prompt}，可用 {mcp_config} |
| `cli_type` | string（可空） |  | `None` | 工作台选择的 CLI 类型；省略时沿用旧值 |
| `previous` | string（可空） |  | `None` | 改名时填原名称；巡检、复核和大模型的引用随之更新 |

## agent.set_command

修改 agent 命令模板里的可执行文件，其余参数不变（设计稿 08 D-39）。命令不在 PATH 里时填完整路径。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `agent` | string | 是 |  |  |
| `executable` | string |  | `''` | 可执行文件：命令名或完整路径；留空恢复默认 |

## agent.start

在本机启动一个 agent CLI 处理任务；它通过 MCP 回到本工作区读写，输出留在运行日志。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `agent` | string | 是 |  |  |
| `prompt` | string | 是 |  |  |
| `cwd` | string（可空） |  | `None` |  |
| `preamble` | boolean |  | `True` |  |

## agent.test

测试 agent 连接：命令能否找到、能否经 MCP 调用 burrowl、身份是否正确（设计稿 08 D-26）。会真的启动一次 agent。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `agent` | string | 是 |  |  |
| `timeout` | number |  | `180` | 最多等几秒 |

## artifact.check

检查外部原件（只登记路径和指纹的那类）是否还与登记时一致：changed 内容已变化，missing 原位置找不到。 只读文件，不写账本；发现变化后请把新文件登记为新版本（artifact_register 的 version_of）。

无参数。

## artifact.check_status

上次原件检查的时间与结果、有问题的原件，以及定时检查是否开启。不重新检查。

无参数。

## artifact.delete

彻底删除一份已退役的原件及预览里列出的条目：不留任何记录，不能撤销（设计稿 07 D-04、D-05）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `confirm` | string | 是 |  | artifact.delete_preview 返回的 confirm |

## artifact.delete_preview

删除一份已退役的原件会删掉什么（依据全部来自它的判断与事实记录等）、哪些条目保留并标为"所引原件已删除"、 哪些框架页会标为输入已变化；confirm 是执行删除时要带上的核对值（设计稿 07 D-04）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |

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

## artifact.layout_engine

用本地版面引擎（MinerU）处理一份 PDF：给公式块补 LaTeX、给段落记下行内公式；replace 时整份替换抽取； 抽取方式为 MinerU 时，还没被引用的原件采用引擎的分段。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `mode` | string（可空） |  | `None` | formulas 补公式（默认）/ formulas_only_existing 只补已有公式块 / replace 整份替换（只有人）；省略时按设置 |
| `fresh` | boolean |  | `False` | 不用缓存，重新调用引擎 |
| `wait` | boolean |  | `False` | 等任务结束再返回 |

## artifact.policy

标记原件是否外发：不外发的原件原文不进巡检包，巡检运行里读不到（设计稿 08 D-30、D-31）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `outbound` | boolean | 是 |  | false 标为不外发 / true 恢复可外发 |
| `reason` | string |  | `''` |  |

## artifact.read

读原件（当前抽取层）的一段并留下读取记录。判断引用时写返回的 cite_as（原件段落 art_…#p3-2），不必引用读取记录。 返回 notice 时说明这些段落来自 OCR / AI 识别、尚未确认，引用前请用 artifact_view 对照原件。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `locator` | string（可空） |  | `None` | 省略读全部；段落 seg-3 / p3-2；段落范围 p3-8:p3-12（检索结果的 read_as）；单元 p3；单元范围 p3:p5；旧写法 seg:N-M |

## artifact.recognize_formula

识别公式块的 LaTeX：结果标为模型识别（OCR 档或 AI 档），需要人确认。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `anchors` | string[]（可空） | 是 |  | 公式块的段落锚点，如 p3-4 |
| `engine` | string |  | `'model'` | model 本地公式模型 / llm 大模型（只有人） |
| `wait` | boolean |  | `False` |  |

## artifact.register

登记有核对或复用价值的原件，保留原文与可核对的元数据。同内容幂等；新版本用 version_of 指向旧版本。

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
| `produced_by` | string（可空） |  | `None` | 产生这份文件的过程日志 evt_…（例如运行脚本的那一条） |

## artifact.replace

给已退役或已删除的原件指定替代原件。引用旧原件段落的判断按段落指纹在替代原件里比对，对不上的进入待复核； 受影响的框架页标为"输入已变化"，由人交给 agent 重新综合（设计稿 07 D-03）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  | 已退役或已删除的原件 |
| `replacement` | string | 是 |  | 替代它的原件 art_… |
| `reason` | string | 是 |  |  |

## artifact.retire

退役原件（内容没错，只是不再单独出现在列表和检索里）或撤销退役。记为原件的状态历史，不写成判断。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string | 是 |  |  |
| `action` | string |  | `'retire'` | retire 退役 / restore 撤销退役 |
| `reason` | string |  | `''` |  |
| `replaced_by` | string（可空） |  | `None` | 替代它的原件（可空） |

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

记录有核对或复用价值的实际过程（只追加）。动手前先调用 constraints_check，事后不能补写条件。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `op_name` | string | 是 |  | 操作名，如 exec.shell、measure.pressure |
| `input` | object（可空） |  | `None` |  |
| `output` | string（可空） |  | `None` |  |
| `conditions` | object（可空） |  | `None` |  |
| `objects` | string[]（可空） |  | `None` |  |
| `source_class` | string |  | `'local'` | local 本地实证（默认）/ inferred 推断（如对话消息） |
| `inputs` | string[]（可空） |  | `None` | 这次操作用到的原件 art_…（脚本、输入数据） |
| `outputs` | string[]（可空） |  | `None` | 这次操作产出的原件 art_…（结果文件）；也可在登记时用 produced_by |

## constraints.check

对某对象动手前必须调用：列出与它相关的有效约束、决定和指令，并留下"已检查"的记录。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `objects` | string[] | 是 |  |  |

## coverage.view

覆盖图：原件段落分五档（被引用 / 读过未引 / 命中未读 / 相关未读 / 冷区）。框架内容，不能作为依据； 没读过不等于有用。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string（可空） |  | `None` | 省略时按原件、对象汇总；给出时列出这份原件每一段 |

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

待决策列表（按影响范围排序）：术语连接、待复核、需重新综合、操作前未检查约束、传播超限。 影响范围为 0 的是低影响项（工作台默认折叠，设计稿 04 D-07）。

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
| `include_retired` | boolean |  | `False` | 是否包含已退役的原件，以及依据全部失效而隐藏的判断与事实记录 |
| `limit` | integer |  | `50` |  |
| `offset` | integer |  | `0` |  |
| `scope` | string |  | `'operations'` | 过程日志：operations 操作日志（默认）/ system 系统流水（登记、读取、写判断、改设置……）/ all |
| `include_outputs` | boolean |  | `False` | 原件列表是否包含运行产物（被某条过程日志 produced 的原件） |

## entry.correct

在同一条目下追加完整版本。文件可填路径，判断可指定新版依据；原始过程保留，核实结果单独标明。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | 是 |  |  |
| `reason` | string | 是 |  |  |
| `text` | string（可空） |  | `None` |  |
| `path` | string（可空） |  | `None` |  |
| `cites` | string[]（可空） |  | `None` |  |

## entry.destroy

按确认指纹彻底销毁一个已退役版本。旧引用保留其指向，内容不可恢复。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | 是 |  |  |
| `confirm` | string | 是 |  |  |

## entry.destroy_preview

预览一个已退役版本的销毁范围，返回供人确认的指纹。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | 是 |  |  |

## entry.expand

展开背景：来源（原件）或条件（日志、事实记录）→ 同一来源的前后内容 → 涉及的对象 → 引用了它的判断（解读，探索模式下隐藏）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | 是 |  | 条目 ID；原件段落写成 art_…#p3-2 或 art_…#seg-N |
| `mode` | string |  | `'reuse'` |  |

## entry.get

按原始引用 ID 取条目，附版本历史、地位坐标和关系。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | 是 |  |  |

## entry.labels

批量获取工作台显示名，按原引用返回；不可用条目的名称为空。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `refs` | string[] | 是 |  |  |

## entry.version_state

追加版本状态：withdraw 撤回、unwithdraw 取消撤回、reactivate 重新生效、defect 标记缺陷、undefect 取消缺陷标记、retire 退役、restore 取消退役。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | 是 |  |  |
| `action` | string | 是 |  |  |
| `reason` | string | 是 |  |  |

## extraction.ai_check

把识别结果交给大模型看图核对（只有人能发起；设计稿 04 D-22、D-23）。结果为"AI 已核对"，不等于人已确认。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_ids` | string[]（可空） | 是 |  | 原件 ID |
| `anchors` | string[]（可空） |  | `None` | 只核对这些段落；省略时核对还没核对过的 |

## extraction.backfill

给还没有抽取层的原件补上抽取（升级后执行一次）：PDF / PPTX / DOCX 自动抽取，图片与音视频登记单元。

无参数。

## extraction.recognitions

待确认的识别：OCR / AI 识别、未经人确认的段落与公式 LaTeX，以及 AI 核对的结果（设计稿 04 D-25）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `artifact_id` | string（可空） |  | `None` | 省略时按原件汇总 |

## extraction.status

抽取与引用的状态检查：未抽取或失败的原件、待抽取的图片页、未读先引、引用未确认的识别文本、待复核的判断。

无参数。

## finding.resolve

人处理一条巡检发现。普通采纳只关闭发现；明确应用复核意见时才新增结论或追加更正。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `decision_id` | string | 是 |  | 巡检发现的待决策编号 dec_… |
| `action` | string | 是 |  | adopt 采纳 / reject 驳回 / ignore 忽略 |
| `reason` | string |  | `''` |  |
| `apply_change` | boolean |  | `False` | 采纳时明确将有依据的复核修改意见写入判断层 |
| `target` | string（可空） |  | `None` | 写入时要更正的目标判断；省略则新增结论 |

## framework.review

review.submit 的旧名称，参数与效果相同。

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

## index.embed

补建检索单元的向量（工作台会在后台自动补；评测和首次升级时可以用它一次补完）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | integer（可空） |  | `None` | 最多补几个检索单元；省略时补完 |

## index.health

检索索引是否覆盖全部原件、事实记录、判断和框架页（缺了用 index.rebuild 重建）、是否按当前的检索单元长度建成 （units.current；units.rebuild 是本进程里的后台重建进度），以及向量通道（已建 done / total）与重排的状态。

无参数。

## index.rebuild

从账本和框架整库重建全文索引。后台重建逐条取锁、不先清空，进度见 index.health 的 units.rebuild。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `background` | boolean |  | `False` | 在后台重建、立即返回（工作台用）；省略时等重建完再返回（命令行用） |

## inspection.close

关闭一期巡检（未处理的发现仍留在待决策里）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `inspection_id` | string | 是 |  |  |

## inspection.export

离线巡检包（Markdown）：任务、段落原文（不外发的原件不含原文）与要求的 JSON 回答格式。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `inspection_id` | string | 是 |  |  |

## inspection.findings

巡检发现列表（kind=finding 的待决策项，数据里有说明、依据、针对的条目、复核员意见）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `inspection_id` | string（可空） |  | `None` |  |
| `status` | string（可空） |  | `None` | open 待处理 / resolved 已采纳 / dismissed 已驳回或忽略 |

## inspection.get

领取巡检包：巡检员得到任务清单（要读的段落、要回答的问题），复核员得到待复核的发现。领取会记下本会话。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `inspection_id` | string | 是 |  | 巡检包编号 insp_… |
| `role` | string |  | `'inspector'` | inspector 巡检员（领取任务）/ reviewer 复核员（领取待复核的发现） |
| `finding_ids` | string[]（可空） |  | `None` | 复核员只看这些发现（待决策编号 dec_…） |

## inspection.guidelines

当前生效的巡检原则（设置为空时是默认文本）、默认文本，以及系统强制、不能改的巡检员与复核员规则（设计稿 08 D-36）。

无参数。

## inspection.import

贴回离线巡检的结果：记为经人转交，没有读取记录，复核员不能确认。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `inspection_id` | string | 是 |  |  |
| `text` | string | 是 |  | AI 输出的 JSON 数组（可以带前后的文字） |
| `model` | string | 是 |  | 给出结果的模型 |

## inspection.list

最近几期巡检包的摘要。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | integer |  | `20` |  |

## inspection.prepare

现在准备巡检包：在本机做规则检查与探索抽样，不调用大模型。上一期准备好还没开跑时就地更新它。

无参数。

## inspection.prompt

给 AI 客户端的一句领取提示（巡检员或复核员）；agent 不可用时由人复制。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `inspection_id` | string | 是 |  |  |
| `role` | string |  | `'inspector'` | inspector / reviewer |
| `finding_ids` | string[]（可空） |  | `None` |  |

## inspection.start

用设置里的巡检员或复核员 agent 启动一次运行（只能由人点，设计稿 08 D-01、D-02）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `inspection_id` | string | 是 |  |  |
| `role` | string |  | `'inspector'` | inspector 开始巡检 / reviewer 交给复核员 |
| `finding_ids` | string[]（可空） |  | `None` |  |

## inspection.status

定期巡检的概况：最近一期巡检包、是否到期、巡检员与复核员 agent 是否可用。

无参数。

## inspection.submit

巡检员提交一个任务的结果。issue 生成一条巡检发现：一项待决策，等复核员和人处理，不能被引用； 你不能更正、撤回判断，也不要写判断。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `inspection_id` | string | 是 |  |  |
| `task_id` | string | 是 |  | 任务编号，如 t3 |
| `outcome` | string | 是 |  | issue 有问题 / clear 检查过，没有问题 |
| `model` | string | 是 |  | 你的模型名 |
| `summary` | string |  | `''` | issue 时写清发现了什么：对象、条件、哪里不一致或遗漏 |
| `cites` | string[]（可空） |  | `None` | 依据：本会话读过的原件段落、事实记录或判断；不能是框架页 |
| `targets` | string[]（可空） |  | `None` | 针对哪些条目；省略时用任务的 targets |
| `suggestion` | string |  | `'review'` | oppose 写反对判断 / amend 请人更正或撤回 / read_more 补读 / contradict_edge 建可能矛盾边 / review 请人复核 / none |

## inspection.tasks

本期巡检的任务清单（工作台查看用，不记领取）：检查类别、规则看到了什么、针对的条目、要读的段落、是否已检查。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `inspection_id` | string | 是 |  | 巡检包编号 insp_… |

## judgment.amend

兼容人工修改入口。更正需提供新版正文 text；撤回和缺陷只追加版本状态。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `mode` | string | 是 |  | correction 更正 / retraction 撤回 / defect 原件有缺陷（retirement 原件退役保留给旧调用，等同 artifact.retire） |
| `target` | string | 是 |  |  |
| `reason` | string | 是 |  |  |
| `cites` | string[]（可空） |  | `None` |  |
| `text` | string（可空） |  | `None` |  |

## judgment.write

只收录工程、科研或其他重要、经常性工作中有长期价值的判断。只追加，可信度由依据推出。巡检会话不能写判断。

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

## models.check

测试连接：检查模型服务，或启动选中的 Agent CLI 做一次文本问答。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `slot` | string | 是 |  | layout / formula / llm |

## models.status

本地模型与大模型的槽位（工具、地址、是否本机、是否自动运行）与本进程里最近的模型任务。

无参数。

## models.stop

关闭 burrowl 启动的 MinerU 服务（设计稿 05 D-20）。

无参数。

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

把过程事件或原件片段升级为事实记录：对象、条件、方法、结果（逐字）、边界。条件不能补写，缺失的写进 gaps。 方法写到一个不知道目的的人能复现或核对：数据怎么产生、各组怎么设置、指标怎么定义，并用 cites 指向原文。

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
| `cites` | string[]（可空） |  | `None` | 方法中各个定义出自哪里：原件段落 art_…#p3-2（如脚本里定义指标的几行）、原件、过程日志、事实记录；不能是判断与框架 |

## review.ai_submit

AI 复核：对照原件层、判断层核对一个条目。结果另记一档（AI 已复核），不等于人已复核；拿不准就交 unsure。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `item_id` | string | 是 |  | AI 生成未复核的框架页 pg_… 或关联边 edg_…；设置允许时也可以是待复核的判断 jdg_…；复核员复核巡检发现时写它的待决策编号 dec_… |
| `verdict` | string | 是 |  | confirm 确认 / reject 有问题 / unsure 拿不准 |
| `reason` | string | 是 |  |  |
| `model` | string | 是 |  | 你的模型名，如 claude-opus-5-5 |
| `cites` | string[]（可空） |  | `None` | 依据：本会话读过的原件段落（cite_as）、事实记录、判断；不能是框架页、边、过程内容。confirm / reject 至少一条 |
| `proposed_change` | string |  | `''` | 仅巡检复核员确认发现后填写：有复用价值、可独立理解的拟写判断 |

## review.history

一个条目的复核与变更历史、当前复核状态，以及现在能否交给 AI 复核（巡检发现的待决策编号 dec_… 返回它的提交、复核员意见与处理）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `item_id` | string | 是 |  |  |

## review.request

请人复核：把条目加入待决策列表。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `item_id` | string | 是 |  | 任何条目：pg_… / edg_… / jdg_… / art_… |
| `note` | string | 是 |  | 一句话：要看什么 |

## review.sample

本周抽查：从 AI 生成未复核的框架页里按周固定地挑几页，供人用确认 / 驳回处理。

无参数。

## review.submit

人复核一个条目。结论记为它的复核历史，不写成新判断；判断的当前地位由依据（含补充的）重新推出。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `item_id` | string | 是 |  | 框架页 pg_…、边 edg_… 或判断 jdg_… |
| `verdict` | string | 是 |  | confirm 确认（判断：依据支持它）/ reject 驳回（判断：依据不支持它） |
| `reason` | string | 是 |  |  |
| `cites` | string[]（可空） |  | `None` | 补充的依据：原件段落、事实记录、判断；不能是框架 |
| `local_observation` | boolean |  | `False` | 复核判断时：人亲自看到或测到 |

## search

检索（关键词 + 向量，设置为重排时重排）。名次只表示相关度；每条带地位坐标与 status_note 说明可靠程度。 相关的有效约束列在最前；被替代、已退役的排在当前条目之后。每条带命中的段落（cite_as、read_as）、 未展示的命中数（more_matches）、依据（basis）和一跳关系（relations）；params 是本次用的检索参数（每条最多展示 几个命中单元等，人在设置里调整）；hints 说明结果的局限。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 |  |  |
| `layers` | string[]（可空） |  | `None` | original/judgment/framework |
| `objects` | string[]（可空） |  | `None` |  |
| `mode` | string |  | `'reuse'` | reuse 复用 / explore 探索（不给框架页，默认也不给过程内容） |
| `include_log` | boolean |  | `False` |  |
| `include_process` | boolean（可空） |  | `None` | 是否返回过程内容；省略时复用模式返回、探索模式不返回 |
| `include_retired` | boolean |  | `False` | 是否返回已退役的原件（排在最后） |
| `order` | string |  | `'relevance'` | relevance 按相关度（默认）/ status 按地位逐级排 |
| `limit` | integer（可空） |  | `None` | 返回几条；省略时按设置（默认 20），本次用的值见结果的 params |

## search.associate

联想：从检索命中（或给定条目）出发，顺着判断关系、引用、输入清单、实体提及、共享对象、向量近邻走 1–2 跳， 找出检索没有命中但连着的条目。每条带经过的路径 via，标为"联想，非检索命中"；不是默认检索的一部分。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `query` | string（可空） |  | `None` | 从这次检索的前 5 条出发；与 seeds 至少给一个 |
| `seeds` | string[]（可空） |  | `None` | 从这些条目出发（可写原件段落 art_…#p3-2） |
| `hops` | integer |  | `1` | 走几跳：1 或 2 |
| `mode` | string |  | `'reuse'` | reuse / explore（探索模式只走判断关系、引用、共享对象和向量近邻） |
| `include_process` | boolean（可空） |  | `None` |  |
| `include_retired` | boolean |  | `False` |  |
| `limit` | integer |  | `20` |  |

## search.exact

字面查找：列出含有这段文字的段落（带 cite_as），按条目分组，不排序。用于设备编号、错误码、函数名、原句。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `text` | string | 是 |  | 要逐字查找的文字（不分词，不区分大小写） |
| `layers` | string[]（可空） |  | `None` | original/judgment/framework |
| `mode` | string |  | `'reuse'` | reuse / explore（探索模式不给框架页，默认也不给过程内容） |
| `include_process` | boolean（可空） |  | `None` |  |
| `include_retired` | boolean |  | `False` |  |
| `limit` | integer（可空） |  | `None` | 最多几个条目；省略时按设置（默认 50） |

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

修改当前数据目录的设置。抽取设置只影响以后的抽取（已有的抽取不变，可在原件页重新抽取）；阅读器设置立即生效； 检索参数（retrieval.*）对工作台和 AI 的下一次调用生效；检索单元长度（index.units_*）保存后在后台整库重建索引 （进度见 index.health 的 units.rebuild），向量随后在后台重算。每次修改记一条过程日志（旧值、新值，密钥不记原文）。

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
