---
name: burrowl-inspect
description: 定期巡检时使用：作为巡检员领取巡检包、读原件、提交巡检发现；或作为复核员对巡检发现做二次检查。收到"用 inspection_get 领取巡检包 insp_…"之类的提示时使用。
---

# 定期巡检

先读同目录上一级的 RULES.md（公共规则）。巡检检查近期研究里原件与结论是否冲突、是否遗漏、条目是否符合记录规则，并从"检索命中却没人读""和近期结论相关却没人读"的段落里抽样阅读。巡检包由系统在本机按规则准备，你只负责读和判断。

每条巡检发现是一项待决策。巡检会话禁止写判断，巡检输出留在运行日志。复核员确认后可提出有价值的修改意见，由人确认是否写入判断层。

## 巡检员

1. `inspection_get(inspection_id, role="inspector")` 领取任务。每个任务有：
   - `check`：疑似冲突 / 依据变化后仍被引用 / 相邻段落未读 / 与规则不符 / 经验未收录 / 高依赖的外部论断 / 页面体检 / 判断未进综合页 / 要点体检 / 跨来源可能矛盾 / 闲置要点 / 重复要点 / 孤立的外部结论 / 探索样本；
   - `question`：要回答的问题；`detail`：规则检查看到了什么（只说明"这里可疑"）；
   - `targets`：针对的判断（经验未收录是操作日志），用 `entry_get` 看；`read`：要读的原件段落。
   - `guidelines`：人定的巡检原则，按它工作（它不会放宽下面的规则）。
2. 逐个任务：用 `artifact_read(artifact_id, locator=段落锚点)` 读 `read` 里的段落，需要时多读前后文。
3. 每个任务都用 `inspection_submit` 提交一次：
   - 没有问题：`outcome="clear"`；
   - 有问题：`outcome="issue"`，`summary` 写清对象、条件、哪里冲突或遗漏；`cites` 只能是**本会话读过的**原件段落、事实记录或判断，不能是框架页；`suggestion` 选一个处置建议（oppose / amend / read_more / contradict_edge / capture / verify_local / refresh_page / merge_pages / consolidate / review / rewrite_point / to_point / none）；
   - 经验未收录：看操作日志的输入输出、读产出的原件；只有确有可复用的结论、经验、停下的路线或应遵守的规定时交 issue，`suggestion="capture"`，`summary` 写清是什么、在什么条件下，`cites` 写操作日志或读过的段落；例行操作交 clear；
   - 高依赖的外部论断：这条结论只有外部报告或推断作依据，却被多条判断或多份页面依赖。读它引用的原文，核对转述是否如实、条件是否写清（原文没说明的应写"原文未说明"）；值得在本地验证时交 issue，`suggestion="verify_local"`，`summary` 写清建议验证什么、在什么条件下；转述如实、条件清楚又不值得本地验证时交 clear；
   - 页面体检：`targets` 是页面。先用 `page_get` 读页面，再读 `read` 里的原件段落：页面里的结论性句子是否如实反映依据、与其他页面有没有互相矛盾、`detail.problems` 里规则报出的问题是否成立。页面只是线索，`cites` 填页面输入里的判断或你读过的原件段落。需要重新综合交 issue，`suggestion="refresh_page"`；两页该合并时 `suggestion="merge_pages"`；页面没有问题交 clear；
   - 要点体检：`targets` 是要点。先用 `point_get` 读要点，再读 `read` 里的原件段落：转述是否忠实、条件是否只写了原文给出的、用到的术语有没有引用定义、有没有"直接依据"、单独读能不能看懂（没有「该方法」「本文」，标题写出了对象）；需要改写交 issue，`suggestion="rewrite_point"`，`summary` 写清要改什么；没问题交 clear；
   - 跨来源可能矛盾：`targets` 是两条来自不同来源、对象相同的论断（要点或结论），规则只按字面看出相反或数值不同（`detail.reason`）。读两边的原文：真冲突或条件不同时交 issue，`suggestion="contradict_edge"`，或建议写一条使用约束（`suggestion="capture"`），`summary` 写清两边的条件差在哪；只是表述不同交 clear；
   - 闲置要点：`targets` 是一条很久没被检索用到、没进综合页、也没有关联的要点，`detail.similar` 是相近的要点。用 `point_get` 读它：有相近的就交 issue，`suggestion="merge_points"`，`summary` 写并进哪一条；没有导航或复用价值交 issue，`suggestion="archive_point"`；仍有价值交 clear；
   - 重复要点：`targets` 是字面很像的两条要点。读两条：同一件事交 issue，`suggestion="merge_points"`，`summary` 写保留哪一条；不是同一件事交 clear；
   - 孤立的外部结论：这条结论只转述外部材料，没有和别的来源建立关系，也没被引用。读它引用的原文：它只是为了好找而写的话交 issue，`suggestion="to_point"`（由人决定撤回并改写成要点）；它其实回答了一个问题或带着读的人的判断时交 clear；
   - 判断未进综合页：`targets` 是没被任何页面吸收的结论或约束，`detail.candidate_pages` 是候选页面。读 `read` 里的段落后判断：该并进哪一页、还是值得新写一页（交 issue，`suggestion="consolidate"`，`summary` 写清并进哪一页或新页回答什么问题）；例行、单点、不需要进页面的交 clear；
   - `model` 写你的模型名。
4. 提交的发现进入人的待决策列表，等复核员和人处理；不会自动改动或标记你针对的判断。
5. `human_only` 的任务含有人标为不外发的原件：你读不到它的原文（会得到 `NOT_OUTBOUND`），只看能看到的部分，不要设法绕过。
6. 不能针对本会话自己写的判断提交发现（会被拒绝）。

## 复核员

1. `inspection_get(inspection_id, role="reviewer", finding_ids=…)` 领取待复核发现。省略发现编号时只返回还没被复核员看过的发现。收到再次复核任务时，按任务中的编号领取指定发现，已有意见会保留在历史中。
2. 对每条发现：自己用 `artifact_read` 读它 `cites` 里的原件段落（确认前必须读过），需要时读更多上下文和 `targets` 里的判断。
3. `review_ai_submit(item_id="dec_…", verdict, reason, model, cites)`（item_id 是发现的待决策编号，`inspection_get` 返回的 `id`）：
   - `confirm`：发现成立；`reject`：不成立，附你读过的依据；`unsure`：拿不准。
   - 一条发现只由复核员看一次；不能复核本会话提交的发现；经人转交（离线贴回）的发现不能 `confirm`。
4. 只对发现本身交意见。确认发现且确有值得收录的修改时，填写 `proposed_change`，附自己核对过的依据。意见留在待决策中，由人确认新增或更正。
   - `proposed_kind` 写拟写判断的类型：`conclusion` 结论（默认）、`thought` 思路（写了重开条件时记为停下的路线，否则记为尝试）、`constraint` 约束（记为行动约束）；`proposed_conditions` 写条件；思路可用 `proposed_reopen_condition` 写重开条件。人采纳时可以改标签。
   - 结论的依据不能是思路；拟写内容要能独立理解（对象写全称、条件写清、术语展开并说明定义出自哪一段），不写框架性措辞。人采纳时可以改类型，也可以在工作台"更正"里补条件、适用范围和关系的说明。
   - 看一条判断时留意：用到的量和术语有没有在正文里展开、定义有没有引用原文段落；`conditions` 为空或写不清；依据只引了整个原件而不是具体段落；关系没有 `why` 说明。这些写进发现的 `summary`，由人决定要不要更正。
5. 最后由人在工作台采纳、驳回或忽略；你不处理。
