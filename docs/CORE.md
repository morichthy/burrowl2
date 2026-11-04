# 核心功能与代码导读

本页给人和开发 AI 看：用几页纸讲清楚每个功能块做什么、核心流程怎样走、代码从哪里读起。

- 不展开参数，参数见 [ops 参考](reference/ops.md)，由代码生成。
- 模块影响与状态归属只维护在 [ARCHITECTURE](../ARCHITECTURE.md)。
- 术语见 [GLOSSARY](GLOSSARY.md)。

核对日期：2026-11-05，对应版本 2.0.0a3。

## 一句话模型

内容分三列：

| 列      | 是什么                       | 能否作为依据         |
| ------ | ------------------------- | -------------- |
| **原件** | 原文如实：文件、对话、过程日志、事实记录、读取记录 | 能              |
| **判断** | 当时谁、依据什么、认为了什么            | 能，可信度由系统根据依据推出 |
| **框架** | 实体页、综合页、关系图               | 永远不能，可以再生      |

依据来源是另一个轴：**本地实证**（本项目内执行、测量或直接观察）、**外部报告**、**推断**，彼此没有固定高低。

判断只有三种类型：**结论**（可以作为依据）、**过程**（提问、尝试、停下的路线；是重新综合框架的依据，但不能作为结论的依据）、**规定**（约束、决定、指令）。复核、更正、撤回、原件缺陷是系统记录。

原件和判断只追加。"现在该信什么"由框架回答。依据变了，下游的框架被标为"输入已变化"。

## 功能块

| 块 | 输入 → 输出 | 关键规则 | 代码 |
|---|---|---|---|
| F1 过程捕获 | 操作、输出、当下条件 → 过程事件 | 只追加；不进默认检索；对有约束的对象操作前没检查约束，会生成待决策 | `services/capture.py` |
| F2 原件 | 文件或文本 → 原件 + 分段索引 | 同内容幂等；大文件只登记路径和指纹；新版本用 `version_of` 指向旧版本，并把变化传播下去 | `services/artifacts.py`、`index/segment.py` |
| F3 读取与事实记录 | 原件片段 / 过程事件 → 读取记录 / 事实记录 | 读取记录写明读的是哪份、哪个版本、哪一段；事实记录的条件不能补写，结果必须逐字取自原文 | `services/artifacts.py`（`read`、`promote`） |
| F4 判断 | 正文 + 依据 + 关系 → 判断 | 拒绝把框架当依据；可信度由系统推出；人才能更正、撤回、标记原件缺陷；改写自己的判断用 `revises` | `services/judgments.py`、`core/model.py` |
| F5 框架 | 正文 + 输入清单 → 页面新版本、AI 推断的边 | 实体页和概念页有建页门槛；AI 写的进入待复核；人的复核写回判断层 | `services/framework.py` |
| F6 传播 | 新判断、更正、新版本 → 框架条目时效下降 | 只降不升；最多 8 跳、1000 个，超出的标为"未核查" | `services/propagation.py` |
| F7 术语连接 | 叫法 → 实体 | 分三档：确定、较有把握、拿不准；按结构条件判断，不看 AI 自报的把握；人的决定加入别名表 | `services/linking.py` |
| F8 检索 | 查询 → 带地位坐标的结果 | 约束排最前；逐级排序，不打分；被替代的排最后；探索模式不返回框架 | `services/retrieval.py`、`index/fts.py` |
| F9 工作台与 agent | 人的操作 → 同一套操作；agent CLI → 对话原件 | 工作台只调用操作；agent 用本次运行的身份通过 MCP 回来读写 | `interfaces/http.py`、`services/agents.py`、`frontend/` |
| 汇总 | 账本 + 框架 → 首页计数、条目浏览、关系图 | 只读，不改变排序和地位规则 | `services/overview.py` |
| 迁移 | 导出目录 / 旧版数据目录 → 新工作区 | 只导入到空工作区；旧目录只读 | `services/portability.py`、`services/import_v1.py` |

## 核心流程（伪代码）

**写一条判断**（`JudgmentService.write`）：

```
如果 kind 只能由人写，而调用者不是人      → 拒绝
依据 = cites ∪ 正文里的 [[ID]]
对每条依据：是框架条目                    → 拒绝（FRAMEWORK_NOT_EVIDENCE）
            否则归纳出 {来源类型, 外部细分, 依据是否完整}（原件有缺陷 → 不完整）
可信度 = derive_credibility(依据, 作者类型, kind)
         └ 没有依据：人勾选"本地实证"的记为本地实证（AI 不能勾选）；规定不参与真假排序；其余记为推断
如果是结论：依据或 depends_on / supports 的目标里有过程内容 → 拒绝（PROCESS_NOT_EVIDENCE）
写入 judgments、links(used 与各关系)；如果改写自己的旧判断，加 wasRevisionOf
写索引；传播：依据、关系目标、旧判断，以及同对象的框架条目 → 标为"输入已变化"
如果出现"显然""关键在于"这类框架性措辞，给警告（不拒绝）
```

**传播**（`Propagation.propagate`）：

```
受影响 = 以这些条目为输入、且用的是当前版本的框架条目 ∪ 主题对象相同的页面
逐层：标为"输入已变化"（已被替代的不动），再找以它们为输入的框架条目
超过 8 层或 1000 个 → 剩下的标为"未核查"，并生成一条待决策
重写页面 → 时效回到"有效"，关闭对应的"需重新综合"
```

**检索**（`RetrievalService.search`）：

```
FTS5 命中（不足 3 个字时用 LIKE）→ 框架页只保留当前版本，去掉被驳回的
精确标识（例如设备编号）→ 把带有该对象的条目也加入（不含过程日志）
每条加上地位坐标 → 按条件过滤对象
排序：依据来源（本地实证 > 外部报告细分 > 推断）→ 列（原件 > 判断 > 框架）→ 复核与反对 → 相关度
未被替代的在前，被替代的在后；相关对象的有效约束单列在最前
```

**一次 agent 运行**（`AgentService.start`）：

```
人在工作台提交任务 → 生成 runs/<id>/mcp.json（身份 ai:<agent>:<run_id>、本次会话）
→ 按命令模板启动子进程 → 逐行读取输出（工作台用 SSE 显示）
→ 结束后把整段输出登记为对话原件（来源记为"推断"）
```

## 怎样读这份代码

建议按这个顺序读，大约一个小时能看懂主干：

1. **`core/model.py`**（约 100 行）：全部取值和两条核心规则 `derive_credibility`、`rank_key`。读懂这里，就知道系统怎样判断"可信"和"先后"。
2. **`store/migrations/*/0001_init.sql`**：三份存储的表结构。账本表都带有拒绝修改的触发器。
3. **`services/workspace.py`**：组合根。看清数据目录里有什么、各服务怎样装配。
4. **`services/judgments.py`**：最核心的写入路径。依据校验、可信度、人工修改都在这里。
5. **`services/propagation.py`**：60 行，看变化怎样只在框架层传播。
6. **`services/retrieval.py`**：地位坐标和排序怎样用在检索上。
7. **`interfaces/registry.py` → `interfaces/ops.py`**：一个操作写一次，三个入口都能用；`effect` 决定谁能调用。
8. **`interfaces/runtime.py`**：身份怎样由入口决定。
9. 其余的按需读：
   - 原件和分段：`services/artifacts.py`、`index/`；
   - 框架和复核：`services/framework.py`；
   - 工作台：`frontend/src/App.tsx` 和 `pages/`；
   - 安装：`interfaces/install.py`、`packaging/`。

**跟一个请求走一遍**：工作台里点"撤回"

```
frontend/src/pages/Entries.tsx  Amend → call("judgment.amend")
interfaces/http.py              POST /api/ops/judgment.amend，身份 = 人
interfaces/registry.py          call()：校验参数，effect=user（MCP 入口会被拒绝）
interfaces/ops.py               judgment_amend → ws.judgments.amend
services/judgments.py           require_human → write(kind="retraction", relations=[retracts → 原判断])
store/ledger.py                 insert（原判断不变）
services/propagation.py         引用了原判断的综合页 → 输入已变化，并生成"需重新综合"待决策
```

**测试也是说明书**：`tests/` 中每个文件对应一块功能，测试名就是规则，例如 `test_ai_cannot_correct_or_retract`。想知道某条规则的确切含义，先找对应的测试。
