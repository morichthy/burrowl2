---
name: burrowl-dev-check
description: 修改 burrowl 本身（代码、Skill、文档、前端、打包、安装）时使用：按影响定位模块与文档，选择验证强度，完成文档维护闭环。用 burrowl 做研究或排查时不要使用。
---

# burrowl 开发检查

本 Skill 只规定开发需要的定位、验证和维护要求，不规定实现方法。规则的权威来源是 [DOCUMENTATION_MAINTENANCE](../../../docs/DOCUMENTATION_MAINTENANCE.md) 和 [TESTING](../../../docs/TESTING.md)，这里不重复。

## 开发前

1. 在 [ARCHITECTURE](../../../ARCHITECTURE.md) 的**模块影响表**里找到要改的模块。把"改动时一并检查"一列逐项列进本次计划，追踪实际调用者。
2. 对照 ARCHITECTURE 的**不变式** I1–I12，确认这次改动会不会碰到其中某一条。会碰到的，先向用户说明。
3. 查 [DEVELOPMENT_HISTORY](../../../docs/DEVELOPMENT_HISTORY.md) 里相关的决定和事故。讨论全局方案前，完整阅读这份文档。
4. 新增状态、表、文件或依赖前，先说清楚四件事：归哪个模块、谁维护、能否再生、谁消费。
5. 设计类改动先给出方案，等用户明确同意后再写代码。

## 开发中

- 存储只新增迁移文件，不改旧的迁移文件。账本新表要加禁止修改的触发器。
- 改了操作：运行 `uv run python tools/gen_reference.py`，检查 `skills/` 和前端的调用。
- 改了取值（判断类型、关系、状态）：同步 `frontend/src/labels.ts`、`docs/GLOSSARY.md`、`skills/RULES.md`。
- 试装一律加 `--install --root <临时目录>`；动用户的 PATH、环境变量、安装目录、客户端配置前，先确认。

## 验证

按 [TESTING](../../../docs/TESTING.md) 的"按改动选择"挑检查项。常用命令：

```
uv run pytest
uv run ruff check src tests tools packaging
uv run lint-imports
npm --prefix frontend run build && npm --prefix frontend test
```

`tests/test_docs.py` 会检查四件事：文档链接、影响表是否覆盖全部源文件、Skill 中的工具名、参数参考是否过期。它失败时，说明文档没跟上代码。

## 开发后：文档闭环

按 DOCUMENTATION_MAINTENANCE 的"改了什么 → 维护哪里"表格更新文档，只改受影响的部分。新的取舍、被放弃的方案、事故，按编号追加到 DEVELOPMENT_HISTORY。

## 报告

- 改了什么；跑了哪些检查、结果如何；哪些没跑，原因是什么。
- 每份相关文档的处置：**已修改 / 已核对无需修改 / 延期（原因）**。
- 软件测试、真实 AI 场景、人工验收分开报告；不为了通过测试而放宽断言。
