---
name: burrowl-work
description: 在研究、实验或工业排查中需要留痕时使用：登记原件、记录操作与测量、读原件、写判断（观察、论断、提问、停止原因）。简单问答、读源码或配置不要使用。
---

# 记录工作

先读同目录上一级的 RULES.md（公共规则）。

## 流程

1. **开工前**：用 `search` 查已有的原件、判断和约束。要动的对象先 `constraints_check`。
2. **拿到材料**：
   - 用 `artifact_register` 登记，`source_class` 按实情填写：
     - 自己跑出来的是 `executed`；
     - 文献、厂商资料是 `external`，并填 `external_tier`；
     - 对话、讨论是 `discussion`。
   - 大文件用 `storage="referenced"`，只登记路径和指纹。
   - 只记原文和可核对的元数据，不写总结。
3. **做操作或测量**：用 `capture_log` 记下操作名、输入、输出和当下能确定的条件，`objects` 填设备编号等对象。
4. **要引用原件内容**：先用 `artifact_read` 读那一段，然后引用返回的读取记录 ID。
5. **要把一条日志或一段原件作为事实使用**：用 `record_promote` 升级为事实记录，填写对象、方法和边界。条件缺失的写进 `gaps`。
6. **形成判断**：用 `judgment_write`。
   - `kind` 的取值：
     - `claim`：论断；
     - `observation`：观察；
     - `question`：要回答的问题，问法中的预设不当作事实；
     - `stop_reason`：这条路线为什么停下、什么条件下值得重新打开；
     - `purpose`：执行的目的。
   - 引用依据，写清对象和条件。
   - 与已有判断的关系写在 `relations` 里，可选 `supports`、`opposes`、`answers`、`depends_on`、`coexists_under`。其中 `coexists_under` 必须写 `condition`。
7. **改写自己的判断**：用 `revises` 指向旧判断，并在 `revise_reason` 中说明原因。别人的判断不能改写。

## 结束时

把这次工作中值得复用的判断写成独立的条目，未解决的部分写成 `question`。不要写总结性的"主线"，那属于框架页（见 burrowl-consolidate）。
