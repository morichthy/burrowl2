# 按影响选择验证

本页规定测试强度，不规定开发流程。根据改动的重要性、范围和失败后果选择检查，并把选择理由写进本次摘要。

## 测试在哪里

| 层 | 位置 | 内容 | 命令 |
|---|---|---|---|
| 存储 | `tests/test_store.py` | 只追加触发器、迁移幂等、格式版本 | `uv run pytest tests/test_store.py` |
| 服务 | `tests/test_artifacts.py`、`test_judgments.py`、`test_framework.py`、`test_retrieval.py`、`test_overview.py`、`test_import_v1.py` | 在临时数据目录上测行为与拒绝边界 | `uv run pytest` |
| 接口与安装 | `tests/test_interfaces.py`、`test_install.py` | 三个入口一致、身份规则、MCP 可见性、agent 运行器、导出导入、Skill 升级、旧版参数兼容 | 同上 |
| 文档一致性 | `tests/test_docs.py` | 链接、影响表覆盖、Skill 工具名、参数参考是否过期 | 同上 |
| 前端 | `frontend/src/*.test.tsx` | 地位坐标、引用链接、筛选条、路由 | `npm --prefix frontend test` |
| 静态检查 | — | 代码风格、分层依赖、前端类型 | `uv run ruff check src tests tools packaging`、`uv run lint-imports`、`npm --prefix frontend run build` |
| 打包 | `packaging/build.py` | 离线包构建与包内自检 | `uv run python packaging/build.py`；试装加 `--install --root <临时目录>` |

## 按改动选择

| 改动 | 至少要做 |
|---|---|
| 纯文档 | `uv run pytest tests/test_docs.py` |
| 局部、低风险 | 受影响模块的测试 + ruff |
| 跨模块、改了取值、状态或操作 | 全部 pytest + lint-imports + 前端构建与测试；改了操作还要重新生成参数参考 |
| 改了存储（表、列、迁移） | 全部 pytest；用一份旧数据目录（或导出目录）实测能打开、能导入 |
| 改了安装、启动器、服务控制 | 打包 + 试装到临时根目录 + `start / restart / stop / status` + 用旧版登记参数拉起 MCP |
| 改了 Skill 或 agent 调用方式 | 软件检查之外，用真实 agent 跑一次对应场景，结果单独报告 |
| 发布 | 以上全部，加上浏览器里逐页检查（含手机宽度） |

## 不能省略的检查

改到相关代码时，下列行为必须有测试覆盖，而且测试仍然通过：

- **只追加**：账本各表执行 UPDATE / DELETE 必须失败（注意：空表上的 DELETE 不会触发触发器，测试前每张表都要有行）。
- **框架不能作为依据**：`cites` 和正文 `[[ID]]` 都要拒绝。
- **可信度由系统推出**：混合来源列出全部来源；只有全部依据为本地实证才算 `all_local`；规定不参与真假排序；AI 不能勾选本地实证。
- **判断类型**：只接受结论、过程、规定；系统记录只能由人工操作生成；过程内容不能作为结论的依据；探索模式默认不返回过程内容。
- **迁移**：改取值的迁移要有"旧库升级后取值正确、触发器仍在"的测试（参考 `test_migration_0002_renames_source_classes`）。
- **身份**：MCP 入口是 AI；AI 不能更正、撤回、复核、决定术语；user / admin 操作不在 MCP 工具列表中。
- **传播**：新判断、更正、撤回、新版本都会让下游标为"输入已变化"；有传递上限；只降不升。
- **检索**：排序逐级比较；约束在最前；被替代的排在最后；旧版本的索引行不返回；过程日志不进默认检索。
- **导入**：旧目录在导入前后的指纹一致；只能导入到空工作区。
- **安装**：试装不能改用户 PATH、`BURROWL_ROOT` 和开始菜单快捷方式（2026-11-05 事故，见 DEVELOPMENT_HISTORY H-07）。

## 写测试的原则

- 从用户可观察的行为、状态转换、拒绝与失败、兼容边界出发，不只匹配实现文本。
- 真实发生过的故障要固化成测试。
- 不为了通过而放宽断言；预期行为变了，在测试里写明理由。
- 软件测试、真实 AI 场景、人工验收、科学结论分开报告。
