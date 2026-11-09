---
name: burrowl-inspect
description: 定期巡检时使用：作为巡检员领取巡检包、读原件、提交巡检发现；或作为复核员对巡检发现做二次检查。收到"用 inspection_get 领取巡检包 insp_…"之类的提示时使用。
---

# 定期巡检

先读同目录上一级的 RULES.md（公共规则）。巡检检查近期研究里原件与结论是否冲突、是否遗漏、条目是否符合记录规则，并从"检索命中却没人读""和近期结论相关却没人读"的段落里抽样阅读。巡检包由系统在本机按规则准备，你只负责读和判断。

每条巡检发现就是一项待决策：不能被引用，也不写回判断层。你不能更正、撤回判断，也不要在巡检中写判断；需要改的由人处理。

## 巡检员

1. `inspection_get(inspection_id, role="inspector")` 领取任务。每个任务有：
   - `check`：疑似冲突 / 依据变化后仍被引用 / 相邻段落未读 / 与规则不符 / 探索样本；
   - `question`：要回答的问题；`detail`：规则检查看到了什么（只说明"这里可疑"）；
   - `targets`：针对的判断，用 `entry_get` 看；`read`：要读的原件段落。
   - `guidelines`：人定的巡检原则，按它工作（它不会放宽下面的规则）。
2. 逐个任务：用 `artifact_read(artifact_id, locator=段落锚点)` 读 `read` 里的段落，需要时多读前后文。
3. 每个任务都用 `inspection_submit` 提交一次：
   - 没有问题：`outcome="clear"`；
   - 有问题：`outcome="issue"`，`summary` 写清对象、条件、哪里冲突或遗漏；`cites` 只能是**本会话读过的**原件段落、事实记录或判断，不能是框架页；`suggestion` 选一个处置建议（oppose / amend / read_more / contradict_edge / review / none）；
   - `model` 写你的模型名。
4. 提交的发现进入人的待决策列表，等复核员和人处理；不会自动改动或标记你针对的判断。
5. `human_only` 的任务含有人标为不外发的原件：你读不到它的原文（会得到 `NOT_OUTBOUND`），只看能看到的部分，不要设法绕过。
6. 不能针对本会话自己写的判断提交发现（会被拒绝）。

## 复核员

1. `inspection_get(inspection_id, role="reviewer", finding_ids=…)` 领取还没被复核员看过的发现。
2. 对每条发现：自己用 `artifact_read` 读它 `cites` 里的原件段落（确认前必须读过），需要时读更多上下文和 `targets` 里的判断。
3. `review_ai_submit(item_id="dec_…", verdict, reason, model, cites)`（item_id 是发现的待决策编号，`inspection_get` 返回的 `id`）：
   - `confirm`：发现成立；`reject`：不成立，附你读过的依据；`unsure`：拿不准。
   - 一条发现只由复核员看一次；不能复核本会话提交的发现；经人转交（离线贴回）的发现不能 `confirm`。
4. 只对发现本身交意见；发现针对的判断由人决定是否复核、更正或撤回。
5. 最后由人在工作台采纳、驳回或忽略；你不处理。
