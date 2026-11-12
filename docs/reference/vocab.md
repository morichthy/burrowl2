# 词表

由 `tools/gen_reference.py` 从 `src/burrowl/core/vocab.py` 生成，不要手改（设计稿 10 D-16）。坐标四组按显示顺序：地位（综合程度 × 依据来源）→ 类型 → 现状 → 说明。

## 综合程度 layer

| 取值 | 中文 |
|---|---|
| `original` | 原件 |
| `judgment` | 判断 |
| `framework` | 框架 |

## 依据来源 sources

| 取值 | 中文 |
|---|---|
| `local` | 本地实证 |
| `external:peer_reviewed` | 外部报告（同行评议） |
| `external:preprint` | 外部报告（预印本） |
| `external:vendor` | 外部报告（厂商资料） |
| `external:web` | 外部报告（网页） |
| `external` | 外部报告 |
| `inferred` | 推断 |

## 类型 kind

| 取值 | 中文 |
|---|---|
| `artifact` | 原件 |
| `event` | 过程日志 |
| `record` | 事实记录 |
| `read` | 读取记录 |
| `conclusion` | 结论 |
| `process` | 过程 |
| `normative` | 规定 |
| `entity` | 实体页 |
| `concept` | 概念页 |
| `synthesis` | 综合页 |
| `description` | 描述页 |
| `edge` | 关联边 |

## 有效性 state.validity

| 取值 | 中文 |
|---|---|
| `current` | 当前有效 |
| `replaced` | 被替代 |
| `withdrawn` | 已撤回 |
| `retired` | 已退役 |
| `lapsed` | 依据失效 |

## 复核 state.review

| 取值 | 中文 |
|---|---|
| `none` | 未复核 |
| `ai_confirmed` | AI 已复核 |
| `ai_flagged` | AI 认为有问题 |
| `ai_unsure` | AI 拿不准 |
| `human_confirmed` | 人已复核 |
| `human_rejected` | 人驳回 |

## 作者 notes.author

| 取值 | 中文 |
|---|---|
| `human` | 人 |
| `ai` | AI |
| `system` | 系统 |

## 谓词

核心谓词由系统依赖其含义；核心谓词都不合适时用 `relates` 加自由标签（D-09）。

| 谓词 | 说法 | 反向说法 | 类别 | 来源 | 谁能写 | 作为依据 | 参与依据来源 |
|---|---|---|---|---|---|---|---|
| `cites` | 依据 | 被依据 | 证据流 | judgment | human、ai、system | 是 | 是 |
| `supports` | 佐证 | 被佐证 | 证据流 | judgment | human、ai | 是 |  |
| `opposes` | 反驳 | 被反驳 | 证据流 | judgment | human、ai |  |  |
| `coexists_under` | 条件并存 | 条件并存 | 立场与结构 | judgment | human、ai |  |  |
| `answers` | 回答 | 被回答 | 立场与结构 | judgment | human、ai |  |  |
| `targets` | 针对 | 被针对 | 立场与结构 | judgment | human、ai |  |  |
| `supersedes` | 替代 | 被替代 | 替代 | judgment | human |  |  |
| `consumed` | 用到 | 被用到 | 过程 | mechanical | human、ai、system |  |  |
| `produced` | 产出 | 产出自 | 过程 | mechanical | human、ai、system |  |  |
| `relates` | 关系 | 关系 | 自由标签（系统不赋予含义） | judgment | human、ai |  |  |
| `may_contradict` | 可能矛盾 | 可能矛盾 | 框架推断（不作为依据） | framework | — |  |  |
| `may_supersede` | 可能替代 | 可能被替代 | 框架推断（不作为依据） | framework | — |  |  |
| `similar` | 相似 | 相似 | 框架推断（不作为依据） | framework | — |  |  |
| `analogy` | 类比 | 类比 | 框架推断（不作为依据） | framework | — |  |  |
| `related` | 相关 | 相关 | 框架推断（不作为依据） | framework | — |  |  |
| `mentions` | 提及 | 被提及 | 框架推断（不作为依据） | framework | — |  |  |
| `about` | 关于 | 相关条目 | 框架推断（不作为依据） | framework | — |  |  |
| `derived_from` | 综合自 | 被综合进 | 框架推断（不作为依据） | framework | — |  |  |
| `subject_of` | 是……的主题 | 主题 | 框架推断（不作为依据） | framework | — |  |  |

## 标记

每个标记带出处 via（造成它的关系与另一端，D-14）。

| 标记 | 组 | 中文 | 严重度 | 推出规则 |
|---|---|---|---|---|
| `corroborated` | 现状 | 被佐证 | info | 有入边 supports；出处带佐证方与它的依据来源 |
| `opposed` | 现状 | 被反驳 | warn | 有入边 opposes |
| `basis_changed` | 现状 | 依据有变化 | warn | 出边 cites 所指版本已不是当前版、被撤回，或所引段落的指纹对不上；出处带当前版 |
| `basis_lapsed` | 现状 | 部分依据已失效 | warn | 出边 cites 所指原件已退役或已删除；全部失效时有效性为依据失效 |
| `defective` | 现状 | 本版有缺陷 | warn | 人在本版标了缺陷 |
| `inputs_changed` | 现状 | 输入已变化 | warn | 框架页的输入有变化 |
| `unchecked` | 现状 | 未核查 | info | 框架页尚未核查 |
| `recognition_unverified` | 说明 | 依据含未确认的识别 | warn | 出边 cites 所指段落来自未经人确认的 OCR / AI 识别（含公式 LaTeX） |
| `conditions_unstated` | 说明 | 转述但没写条件 | warn | 有原作者的结论没有写条件 |
| `scope_unclear` | 说明 | 适用范围未明 | warn | 写的人声明了 scope_unclear（适用范围尚不清晰，条件里写明哪些清楚、哪些不清楚） |
| `basis_incomplete` | 说明 | 依据边界不完整 | info | 所引事实记录的边界不完整，或所引判断依据不完整 |
| `no_basis` | 说明 | 结论没有依据 | warn | 结论没有出边 cites |
| `local_observation` | 说明 | 人标了本地实证 | info | 人写判断时勾了本地实证 |
| `local_roots` | 说明 | 本地依据的独立来源 | info | 本地实证依据来自互不相同的原件与会话，计数 |
