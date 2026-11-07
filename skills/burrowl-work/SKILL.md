---
name: burrowl-work
description: 在研究、实验或工业排查中需要留痕时使用：登记原件、记录操作与测量、读原件、写判断（结论、过程、规定）。简单问答、读源码或配置不要使用。
---

# 记录工作

先读同目录上一级的 RULES.md（公共规则）。

## 流程

1. **开工前**：用 `search` 查已有的原件、判断和约束。要动的对象先 `constraints_check`。
2. **拿到材料**：
   - 用 `artifact_register` 登记，`source_class` 按实情填写：
     - 在本项目内执行、测量或直接观察得到的是 `local`（本地实证）；
     - 文献、厂商资料、网页是 `external`，并填 `external_tier`；
     - 对话、讨论、AI 生成的是 `inferred`（推断）。
   - 大文件用 `storage="referenced"`，只登记路径和指纹。
   - 只记原文和可核对的元数据，不写总结。
   - PDF、PPT、Word 登记时自动抽取文字；不要再把抽取的文字另外登记成一份原件。
   - 图片、扫描页、视频默认不抽取。需要其中的内容时：`artifact_view(artifact_id, unit)` 看图像，照原样转写后用 `artifact_extract(method="ai", model=<你的模型>, content=[{unit, text}])` 提交。只转写看到的内容，不总结、不补充；视频写成 `[00:01:23] 文字` 一行一段。
3. **做操作或测量**：用 `capture_log` 记下操作名、输入、输出和当下能确定的条件，`objects` 填设备编号等对象。
4. **要引用原件内容**：先用 `artifact_read` 读那一段（`locator` 写段落 `p3-2`、整页 `p3` 或旧写法 `seg:N`），然后在 `cites` 里写返回的 `cite_as`。返回 `notice` 时说明这些段落来自识别，引用前对照原件。
5. **要把一条日志或一段原件作为事实使用**：用 `record_promote` 升级为事实记录，填写对象、方法和边界。条件缺失的写进 `gaps`。
6. **形成判断**：用 `judgment_write`。
   - `kind` 只有三种：
     - `conclusion` 结论：关于对象的陈述，引用依据，写清对象和条件；
     - `process` 过程：要回答的问题（问法中的预设不当作事实）、做过的尝试、这条路线为什么停下（重开条件写在 `reopen_condition`）、执行的目的；
     - `normative` 规定：约束、决定、指令。
   - 结论的依据不能是过程内容；回答某个提问时，用 `relations: [{rel: "answers", target: <提问的 ID>}]`。
   - 与已有判断的关系写在 `relations` 里，可选 `supports`、`opposes`、`answers`、`depends_on`、`coexists_under`。其中 `coexists_under` 必须写 `condition`。
7. **改写自己的判断**：用 `revises` 指向旧判断，并在 `revise_reason` 中说明原因。别人的判断不能改写。

## 结束时

把这次工作中值得复用的判断写成独立的条目，未解决的部分写成过程内容（提问），停下的路线写明停止原因和重开条件。不要写总结性的"主线"，那属于框架页（见 burrowl-consolidate）。
