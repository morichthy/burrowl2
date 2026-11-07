# 03 阅读模式（全屏）、可更换的阅读器与公式

| 项 | 内容 |
|---|---|
| 状态 | 已实现：第一批 2.0.0a12（2026-11-07），第二批 2.0.0a13（2026-11-08）。ONLYOFFICE 只用模拟接口验证过，未在真实引擎上实测（§6 未决 3）。实现时的修订见 §3 末的"实现修订" |
| 关系 | 在[设计稿 02](02-faithful-view-and-retirement.md) 的原样显示与段落标记（D-02、D-05、D-06、D-08）之上，加一个全屏的阅读模式，并把各格式的显示从页面代码里拆成可更换的阅读器；补上 02 留下的已知差距"行间公式的分式仍可能拆成几块"和 02 D-10 中"公式密集的论文以后按需接入" |
| 适用范围 | `frontend/src/reader/`（新：阅读模式外壳、阅读器契约、注册表、设置）、`frontend/src/viewers/`（新：各阅读器适配器，与工作台代码隔离）、`frontend/vendor/`（新：必须改源码时的第三方补丁）、`frontend/src/pages/Faithful.tsx` / `Artifact.tsx` / `Entries.tsx` / `Graph.tsx` / `Settings.tsx`、`frontend/package.json`；后端 `services/pdf_layout.py` / `services/extractors.py`（公式块、表格原件）、`services/extraction.py`（块补充、区域裁切图）、`services/workspace.py`（`viewer.*` 设置）、`interfaces/http.py`、`interfaces/ops.py`；Skill 与 MCP 说明 |
| 维护方式 | 每完成一个任务更新 §7；决定有变化时先改 §2 并在 DEVELOPMENT_HISTORY 补记，再改代码 |

决定写作 `D-xx`，任务写作 `T-xx`，验收写作 `AC-xx`；代码注释与提交信息引用"设计稿 03 D-xx"。

## 1. 背景（2026-11-07）

1. **没有全屏**：条目页、原件页、关系图都嵌在工作台的页面框架里，长文档和大图只能在一块不大的区域里看。
2. **PDF 原样视图是"逐页卡片"**：适合在条目页里看标注，不适合连续阅读；没有目录、查找、缩放档位、文内链接。
3. **各格式各自一套显示，且写死在页面代码里**：PDF 用 PDF.js 画布，Word 用 docx-preview，PPT 用快照图片，Excel 没有原样显示，Markdown 用 react-markdown；标注逻辑在每种显示里各写一遍，换一个更好的显示库就要改页面。
4. **公式**：pypdfium2 的文字层里公式是一串按字形位置排列的字符，结构丢失；行间公式没有单独的块类型；"文字""对照"视图看不出原来的公式；判断、框架页里的 `$…$` 不渲染。

## 2. 调研：有没有一个能显示所有格式的开源阅读器（2026-11-07）

| 类型 | 代表 | 格式覆盖 | 标注能力 | 许可证 | 结论 |
|---|---|---|---|---|---|
| 浏览器内的 PDF 阅读器 | PDF.js 阅读器组件（`pdfjs-dist/web/pdf_viewer.mjs`）、EmbedPDF | 只有 PDF | PDF.js 有注释编辑器，但写回 PDF 文件 | Apache-2.0；MIT | 显示 PDF 和 Office 快照 PDF 的最佳选择 |
| 研究用阅读器 | Zotero reader | PDF、EPUB、网页快照 | 高亮、批注、侧栏，完善 | 以仓库 COPYING 为准（Zotero 整体 AGPL-3.0） | 不覆盖 Office；注释模型与 Zotero 客户端耦合 |
| 浏览器内的单格式库 | docx-preview（Word）、SheetJS CE（读 Excel）、pptxviewjs 等（PPT） | 各一种 | 无，渲染成 DOM 或画布，标注需自己叠加 | Apache-2.0；Apache-2.0；MIT（其他 PPT 库许可证未核实） | Word、Excel 可用；浏览器端 PPT 渲染还原度不如 Office 快照 |
| 浏览器内的 Office 套件 | Univer | 表格成熟，文档、幻灯片较新 | 有批注 | Apache-2.0，但 xlsx 导入导出在 Pro 版 | 开源部分不能直接打开 xlsx |
| 服务端 Office 引擎 | ONLYOFFICE Docs、Collabora Online（LibreOffice 内核） | Word、Excel、PPT、PDF 全部原生显示，还原度最高 | 有批注与只读模式 API | AGPL-3.0；MPL-2.0 | 体积数百 MB 到 GB、需单独进程（Docker 或安装包）；只能作为可选的外部引擎 |
| 服务端万能预览 | kkFileView（Java） | Office、PDF、OFD、CAD、Markdown、压缩包等 | 无，转成 PDF / HTML / 图片显示 | 未核实（以仓库 LICENSE 为准） | 需要 Java 与 LibreOffice；只能作为外部引擎 |
| 商业 SDK | Apryse WebViewer、Nutrient | 全部格式，注释完善 | 完善 | 商业许可 | 不考虑 |

结论：**没有一个开源、可离线打包、又覆盖 PDF / Word / Excel / PPT / Markdown 的浏览器阅读器**。覆盖全格式且还原度高的只有服务端 Office 引擎（ONLYOFFICE、Collabora），它们太重，不能作为默认。所以采用"**统一的阅读模式外壳 + 可更换的阅读器适配器 + 一份标注契约**"：默认用轻量的内置阅读器，装了 Office 引擎的用户可以在设置里换成它。

## 3. 决定

### 阅读模式与阅读器框架

| 编号 | 决定 | 理由 |
|---|---|---|
| D-01 | **新增"阅读模式"**：独立路由 `#/read/{artifact_id}`（可带 `#p3-2` 锚点），只有阅读器本身。进入时请求浏览器全屏，浏览器不允许或按 Esc 后仍铺满窗口；"退出阅读"回到进入前的页面。入口：原件页、条目页的"阅读"按钮，判断与读取记录里的段落引用 | 阅读需要整块屏幕；独立路由可以收藏、可以和条目页并排 |
| D-02 | **外壳与阅读器分开**：外壳（`frontend/src/reader/`）负责全屏、工具栏的公共部分（退出、视图切换、标注开关）、右侧栏（段落、引用、目录）、对照与文字视图、锚点跳转；阅读器（`frontend/src/viewers/<名称>/`）只负责把一种或几种格式原样显示出来，并按契约显示标注 | 换阅读器不影响侧栏、对照、引用这些 burrowl 自己的功能；标注逻辑不再每种格式写一遍 |
| D-03 | **阅读器契约**（`reader/contract.ts`）：<br>① 声明：名称、支持的格式、许可证、是否需要外部服务、能力（`paged` 分页 / `flow` 连续流、`boxes` 能按坐标标注、`text` 能按文字定位、`native_annotations` 有自己的批注界面、`find` 查找、`outline` 目录）。<br>② 输入：原件来源（字节、快照 PDF、页面图像、单元清单，由外壳通过 `api.ts` 提供，阅读器不直接调后端）和标注数据（每段的锚点、单元、`box`、文字、状态：被引用 / 被读过 / 低可信度 / 公式）。<br>③ 方法：`mount`、`unmount`、`scrollTo(anchor)`、`setMarks(marks, visible)`、`setOptions(options)`。<br>④ 事件：`onSegmentClick(anchor)`、`onLocation(unit)`（当前看到第几页、哪张表）、`onSelection(text, anchors)` | 契约是数据进、事件出，阅读器拿不到账本写入能力；能力声明让外壳知道哪些功能可用（例如没有 `find` 就隐藏查找框） |
| D-04 | **标注按阅读器的能力落地，三种方式**：<br>① `boxes`：在阅读器给出的页面容器上叠加设计稿 02 D-05 的段落框（PDF.js、快照 PDF、图片）；<br>② `text`：在渲染出的 DOM 里按文字依次对应段落，给对应元素加样式（docx-preview、Markdown、表格，沿用 02 D-08 的实现修订）；<br>③ `native_annotations`：把标注转成阅读器自己的只读批注或高亮显示（ONLYOFFICE、Collabora 的批注 API），复用它的批注侧栏和高亮外观。<br>三种方式都**只显示、不写回**：原件文件永远不变，标注数据只在账本与抽取层里 | 用户希望复用原工具的批注功能：能复用的是它的显示与交互，数据仍归 burrowl；写进原件会破坏"原件如实"（不变式） |
| D-05 | **第三方代码与工作台代码隔离**：<br>① 适配器只能 import `reader/contract.ts` 和它自己用到的第三方库，不能 import 工作台的页面、`api.ts`、`labels.ts`；工作台只通过 `reader/registry.ts` 使用阅读器。用 vitest 里的导入检查（与后端 import-linter 同样的思路）强制。<br>② 优先只用第三方库的公开 API；必须改源码时，把改动做成补丁放在 `frontend/vendor/<库名>/`（记上游版本、补丁文件、许可证原文、改动理由），构建时应用，不直接改 `node_modules`，也不把改过的源码混进 `src/`。<br>③ 每个适配器一个目录、一份 `README.md`（来源、版本、许可证、能力、已知限制） | 升级或替换第三方库时影响范围清楚；许可证义务（保留声明、AGPL 的源码提供义务等）集中在一处核对 |
| D-06 | **对照与文字视图由外壳提供，对所有阅读器通用**：对照是"左边阅读器 + 右边抽取块"，靠 `onLocation` 同步到同一页或同一张表，悬停靠 `setMarks` 互相高亮，每单元可"确认这一单元"（`artifact.verify_extraction`）；文字是连续的文字流，标题按层级排版，公式按 D-15 显示 | 抽取文字是 burrowl 的数据，不应依赖某个阅读器 |
| D-07 | **关系图与判断条目也能全屏**：关系图面板加"全屏"按钮，筛选与图例收成浮层，进入、退出、窗口变化时重算大小并适配视图，Esc 退出。判断、框架页条目的"阅读"打开宽版排版：正文居中，右侧是它的引用，点引用在阅读模式中打开原件 | 关系图节点多时最需要大屏；判断条目的阅读主要是正文和依据并排 |

### 内置阅读器（随安装包，离线可用）

| 编号 | 决定 | 理由 |
|---|---|---|
| D-08 | **`pdfjs`：PDF 与所有快照 PDF**。用 PDF.js 自带的阅读器组件（`PDFViewer`、`EventBus`、`PDFLinkService`、`PDFFindController`，Firefox 内置阅读器同一套，已是现有依赖）：连续滚动（页间只有细缝）、懒渲染、缩放档位、单页与双页、目录、文内链接、查找；标注方式 `boxes`。PDF.js 自己的注释编辑器（会把注释写进 PDF）关闭 | 最成熟；Office 快照本来就是 PDF，放进同一个阅读器就有了连续滚动、查找和坐标标注 |
| D-09 | **Word**：默认用快照 PDF 走 `pdfjs`（逐页与 Office 一致）；没有快照时用 `docx-preview`（连续展开，标注方式 `text`） | 有 Office / LibreOffice 时快照还原度最高；没有时 docx-preview 比自建版式好 |
| D-10 | **PPT**：用快照 PDF 走 `pdfjs`，块已有 `box`；没有快照时显示"生成快照"（`artifact.snapshot`）。浏览器端 PPT 渲染库（pptxviewjs 等）作为以后可加的适配器，不在本稿 | 浏览器端 PPT 库都较新，还原度不如快照 |
| D-11 | **Excel / CSV**：新增内置阅读器 `sheet`，用 SheetJS CE（Apache-2.0）在浏览器里解析，显示为带工作表标签、冻结表头、列宽与合并单元格的只读表格（大表虚拟滚动）；标注方式 `text`（按单元格区域）。后端同时补 xlsx / csv 的抽取：单元是工作表，块是按空行分开的表格区域，锚点如 `art_…#s2-1`，`box` 改记单元格范围（如 `A1:F20`）。要求格式完全一致时用快照 PDF | 表格的价值在于行列结构，转成 PDF 会丢；目前 xlsx 既不能看也不能引用 |
| D-12 | **Markdown、纯文本、代码、JSON**：`markdown` 阅读器（react-markdown + remark-gfm + KaTeX + 代码高亮），按标题生成目录，标注方式 `text`；纯文本与代码保留原样换行。**图片**：可缩放拖动的 `image` 阅读器；**音视频**：原生播放器 + 时间戳文字，点一行跳到对应时刻 | 这些格式浏览器本身就能原样显示，不需要第三方阅读器 |

### 外部阅读引擎（可选，不随安装包）

| 编号 | 决定 | 理由 |
|---|---|---|
| D-13 | **为服务端 Office 引擎留适配器**：`onlyoffice`（ONLYOFFICE Docs，只读查看模式）与 `collabora`（Collabora Online），覆盖 Word、Excel、PPT、PDF，标注方式 `native_annotations`。引擎由用户自己安装和运行（Docker 或官方安装包），在设置里填地址；burrowl 不打包、不启动它们。引擎通过一个带一次性令牌、只读、只限这份原件的地址取文件；地址只给本机（`127.0.0.1`）或用户在设置里填写的主机。第一版只实现 `onlyoffice` 的只读显示与把标注转成批注，`collabora` 和 kkFileView 列在 §6 未决 | 这是唯一能做到"各种 Office 格式原生显示 + 复用原工具批注界面"的开源路线；作为独立进程通过网络调用，不把 AGPL 代码并进 burrowl；不装也不影响默认功能 |

### 设置

| 编号 | 决定 | 理由 |
|---|---|---|
| D-14 | **设置页新增"阅读"一节**，分两类保存：<br>① 数据目录设置（沿用 `settings.get` / `settings.set`，只能由人改）：每种格式的默认阅读器（如 `viewer.docx = snapshot-pdfjs \| docx-preview \| onlyoffice`），外部引擎地址与是否启用。选了外部引擎但连不上时，自动退回内置阅读器并提示。<br>② 个人偏好（只存在这台浏览器的 localStorage）：默认视图（原样 / 对照 / 文字）、滚动方式（连续 / 单页）、默认缩放、单页或双页、默认显示哪些标注、侧栏默认展开的标签、深色模式下是否反色显示页面、进入阅读模式时是否请求全屏。<br>阅读模式工具栏上可以临时换阅读器（只影响这一次） | 用哪个阅读器、连哪个外部引擎是这台机器和这份数据的配置；缩放、侧栏这类只是个人习惯，不值得进数据目录 |

### 公式

| 编号 | 决定 | 理由 |
|---|---|---|
| D-15 | **抽取时识别行间公式块，不加模型**：在 02 D-04 的按位置分段之后，字体名属于数学字体（CMMI、CMSY、CMEX、MSAM、MSBM、Symbol、Cambria Math、STIX Two Math、Latin Modern Math、名字带 Math 的字体）的字符占多数、或数学符号占比高的独立行，标为块类型 `formula`；上下相邻、横向重叠的公式行（分式、多行对齐）合成一个块。段落里夹着的行内公式不拆块，块上记 `math = true`。升 `EXTRACTOR_VERSION` 到 3，重建与旧引用按 02 D-07 处理 | 绝大多数论文 PDF 用数学字体排公式，按字体判断零依赖、可解释；合块后引用能落在整条公式上 |
| D-16 | **公式先显示原件的样子**：在文字、对照视图和段落详情里，`formula` 块默认显示原件上这一块的裁切图（服务端按 `box` 渲染，`/api/artifact/{id}/page/{n}.png?clip=x,y,w,h`），抽取出的原始字符折叠在下面；有 LaTeX 时用 KaTeX 渲染，保留"看原件"切换。`math = true` 的段落旁有"看原件这段" | 没有模型时最可靠的公式显示就是原件本身 |
| D-17 | **LaTeX 作为块补充提交，不改文字与编号**：`artifact.extract` 增加 `blocks` 参数 `[{anchor, latex}]`（只用于 `formula` 块）。追加一条抽取记录，方法写 `ai`（写明 `model`）或 `ocr`（写明工具与版本，如 Docling + CodeFormula），可信度档与未确认标记沿用设计稿 01；块的检索文字、锚点、指纹不变，已有引用不进待复核。人在对照视图确认。burrowl-read 写明做法：`artifact_view` 看裁切图 → 识别 → 提交 `blocks` | LaTeX 是对原件的转写，不是新内容；不改编号才不打扰已有引用 |
| D-18 | **公式识别模型不打包**：Docling（MIT，CodeFormulaV2 权重为 CDLA-Permissive-2.0）、pix2tex 等作为可选外部工具，运行后经 D-17 提交 | 与 02 D-10 一致，离线安装包不因模型变大 |
| D-19 | **前端用 KaTeX 渲染 LaTeX**：`katex`、`remark-math`、`rehype-katex`（MIT），字体随构建打包。用于公式块，以及判断、框架页、Markdown 原件里的 `$…$`、`$$…$$` | 快、无运行时依赖、可离线 |

### 实现修订（2026-11-07 开发第一批时）

| 编号 | 修订 | 原因 |
|---|---|---|
| D-09 | Word 的默认阅读器改为 `docx-preview`，快照 PDF（`pdfjs-snapshot`）作为可选 | Word 快照上没有段落位置，默认用快照就看不到段落标记；需要逐页一致时在设置里换 |
| D-03 | 阅读器以 React 组件实现契约（`ViewerProps`），由注册表懒加载；句柄（`ViewerHandle`）在 `onReady` 里交给外壳 | 工作台本身是 React；懒加载让不用的阅读器不进首屏 |
| D-08 | PDF.js 阅读器组件从 `globalThis.pdfjsLib` 取核心库，先挂上再动态加载 `pdf_viewer.mjs`；容器宽度变化时按"适合宽度 / 整页"重算缩放（组件自己不会） | 实测切换到对照视图后页面仍按原宽度显示 |
| D-19 | KaTeX 提前在第一批接入：Markdown 原件、文本原件页、判断与框架页正文（`RefText`）里的 `$…$`、`$$…$$` | 体积小、与公式显示同一批更好验收；LaTeX 块补充（D-17）仍在第二批 |
| D-15 | 除设计中的规则外：含 4 个以上汉字或 3 个以上长英文单词的行不算公式行；位置上紧挨着的公式块再合并一次，但已有编号 `(n)` 的公式不再与下一条合并；编号夹在分式的分子分母之间时（按顶边排序），分母仍并入公式 | 在 Adam、中文报告两份 PDF 上看公式块后调整 |
| D-17 | LaTeX 补充不另设记录类型：复制该单元当前的 content，只在公式块上加 `latex` 与 `latex_source`（方法、可信度档、提交者）；单元的可信度档不变；人确认单元时一并确认 LaTeX；重新抽取时文字相同的公式块保留 LaTeX；`artifact_view` 增加 `anchor` 参数，只返回那一块的裁切图；工作台的公式块上可以"交给 AI 识别"或由人"填写 LaTeX"（method=manual） | `extractions.kind` 有 CHECK 约束，新类型要重建表；这样写段落文字与指纹都不变 |
| D-11 | Excel 用 openpyxl 抽取（新增后端依赖，MIT），`data_only` 取文件里保存的计算结果；块每 50 行切开；单个工作表最多抽取 20 万个单元格；`.xlsm` 按 xlsx 处理；Excel 也能生成页面快照（Excel 或 LibreOffice）。新增 `FORMAT_VERSION_SINCE`：`EXTRACTOR_VERSION` 升到 4 只为新增 Excel，已有的 PDF 不重建 | 不升各格式各自的版本号，补抽会把所有 PDF 再抽一遍 |
| D-13 | 社区版只读模式没有加批注的接口，段落标注只在外壳侧栏列出（§6 未决 3 的退路）；JWT 由后端签名，密钥不进浏览器；取文件地址不带工作台 token，改用只对一份原件、10 分钟有效、只在内存里的令牌；设置页加"测试连接"（`settings.check_engine`，只能由人用） | 引擎会把文件地址写进日志，不能放长期有效的凭据 |
| D-05 | 缩略图（第一批未做）在第二批补上：服务端渲染的小图，PDF 与快照阅读器可用，点击翻页（`ViewerHandle.goToPage`） | — |

### 放弃的方案

| 方案 | 不选的原因 |
|---|---|
| 以 Zotero reader 为整个阅读模式的基础 | 不覆盖 Office 与表格；许可证需核对；注释模型与 Zotero 客户端耦合，改造面大 |
| 默认用 ONLYOFFICE / Collabora 显示全部格式 | 数百 MB 到 GB、需要单独进程或 Docker，离线安装包无法承受；改为可选外部引擎（D-13） |
| 复用阅读器的注释并写回原件（如 PDF.js 注释编辑器） | 原件不可变；burrowl 的"标注"是账本数据（引用、读取、可信度）的显示，不是对文件的修改 |
| Fork 第三方阅读器、直接改它的源码 | 升级要合并，许可证义务分散；改为公开 API 优先，必要时 `vendor/` 补丁（D-05） |
| 把 Excel 也转成快照 PDF 显示 | 丢掉行列结构，表格无法按区域引用 |

## 4. 阅读模式的样子

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ← 退出阅读  Adam: A Method…  PDF · 15 页  [原样|对照|文字]  − 125% +  🔍  [标注 ●]  阅读器：PDF.js ▾ ☰ │
├────┬───────────────────────────────────────────────────────────────┬─────────────────────────┤
│缩略│            第 1 页（连续滚动，页与页之间只有细缝）              │ [段落] [引用] [目录]     │
│ 图 │  ┌───────────────────────────┐ ← 被引用                        │ 第 2 页                  │
│ ▢  │  │ Algorithm 1: Adam …        │                                │  #p2-3 Require: α …  ●2  │
│ ▢  │  └───────────────────────────┘                                │  #p2-7 [公式裁切图]       │
└────┴───────────────────────────────────────────────────────────────┴─────────────────────────┘
```

Excel（`sheet` 阅读器）：

```
│ [Sheet1] [测量数据] [汇总]                                          │ [段落] [引用]        │
│    A        B        C   ┌──────────── 被引用：#s2-1（A1:F20）─┐   │  #s2-1 A1:F20  ●1    │
│ 1  日期     温度     …   │                                      │   │                      │
```

设置页"阅读"一节：

```
默认阅读器（本数据目录）  PDF [PDF.js ▾]  Word [快照→PDF.js ▾]  PPT [快照→PDF.js ▾]  Excel [表格 ▾]
外部引擎                  ONLYOFFICE 地址 [http://127.0.0.1:8080   ] [测试连接]  □ 启用
个人偏好（本浏览器）      默认视图 [原样 ▾]  滚动 [连续 ▾]  缩放 [适合宽度 ▾]  □ 双页  ☑ 显示被引用 ☑ 显示被读过 …
```

## 5. 对不变式与影响表的影响

- **账本只追加不变**：阅读模式只读；LaTeX 补充、xlsx 抽取都是抽取层的新抽取记录；外部引擎拿到的是只读地址。
- **框架不作依据、可信度由系统推出不变**：AI 或外部工具提交的 LaTeX 沿用设计稿 01 的可信度档与"未确认"。
- **只能由人做**：`settings.set`（阅读器与外部引擎设置）、`artifact.verify_extraction` 仍只能由人做，不出现在 MCP 中。MCP 的 `artifact_extract` 多一个 `blocks` 参数。
- **新依赖**：前端 `katex`、`remark-math`、`rehype-katex`（MIT）、SheetJS CE（Apache-2.0，官方从自己的 CDN 发布，打包方式实现时核对）；PDF.js 阅读器组件已在 `pdfjs-dist` 中。后端读 xlsx 需要 `openpyxl`（MIT）。离线包预计增加 2–3 MB，实现时核对。外部引擎不是依赖。
- **新的 HTTP 地址**：快照 PDF 字节 `/api/artifact/{id}/snapshot/bytes`；区域裁切 `clip` 参数；给外部引擎的一次性只读地址（令牌只对一份原件、有效期短）。
- **落盘格式**：块增加可选字段（`kind = formula`、`math`、`latex`、表格的单元格范围），新增 xlsx 单元类型；旧抽取层照常可读；预计不升 `FORMAT_VERSION`，开发时按 STORE 行核对导出导入。
- **需要更新的文档**：ARCHITECTURE（WEB、EXT、HTTP 行，新增前端阅读器隔离规则；已知差距）、CORE（阅读模式、阅读器契约、抽取流程）、GLOSSARY（阅读模式、阅读器、标注契约、公式块、块补充）、DEVELOPMENT_HISTORY、README（阅读模式、设置、外部引擎的安装说明）、`skills/burrowl-read`、ops 参考、`labels.ts`、每个适配器的 README。

## 6. 未决

1. **在阅读器里划选文字直接写判断**：`onSelection` 已在契约里，选中文字对应到段落锚点后，可以"引用这段写判断"。这是新的写入入口，本稿只做到"复制引用写法"，写判断留到下一份设计稿。
2. **Collabora Online、kkFileView 适配器**：前者许可证合适（MPL-2.0）但主要在 Linux / Docker 上运行；后者需要 Java，许可证未核实。等有用户需要时再做。
3. **ONLYOFFICE 的令牌与只读**：已按"只显示原件，标注只在侧栏"实现（实现修订 D-13）。还没有在真实的 ONLYOFFICE Docs 上实测（本机 Docker Desktop 没有运行，镜像数 GB，需要用户同意后再装）；只用模拟的 `/healthcheck` 与 `api.js` 验证了签名配置、脚本加载与一次性取文件。
4. 字体规则在 Word 导出的 PDF（Cambria Math）和扫描 PDF 上的效果；扫描 PDF 只能整页由 AI 识别（02 §5 未决 2）。
5. 段落里的行内公式是否允许提交整段带 LaTeX 的文字（会改变检索文字）：本稿不允许。
6. 原件页现有的"逐页卡片"视图是否改成同一套阅读器的嵌入版：本稿保留，实现后若差别不大再合并。

## 7. 任务与验收

| 编号 | 任务 | 验收 |
|---|---|---|
| T-01 | 阅读模式外壳、路由、全屏、入口（D-01、D-02） | AC-01：从原件页、条目页、段落引用都能进入；Esc 后仍铺满窗口；带锚点进入时滚到对应段落并闪烁 |
| T-02 | 阅读器契约、注册表、导入隔离检查、适配器 README（D-03、D-05） | AC-02：适配器 import 工作台模块时测试失败；外壳按能力声明隐藏不支持的功能 |
| T-03 | `pdfjs` 阅读器（D-08），快照 PDF 地址；Word、PPT 走快照（D-09、D-10） | AC-03：Adam 连续滚动、缩放、双页、目录、链接、查找可用；有快照的 PPTX、DOCX 在同一阅读器显示；无快照的 DOCX 退到 docx-preview；断网可用 |
| T-04 | 三种标注方式与侧栏（D-04、D-05） | AC-04：PDF 框、docx-preview 文字对应与 `artifact.segment_stats` 一致；关掉标注后无叠加；侧栏点段落跳转 |
| T-05 | 对照与文字视图（D-06） | AC-05：各阅读器下对照都能按单元同步、悬停互亮、逐单元确认 |
| T-06 | `sheet` 阅读器与 xlsx / csv 抽取（D-11） | AC-06：样例 xlsx 多工作表、合并单元格显示正确；表格区域可读可引用，锚点稳定；大表滚动不卡 |
| T-07 | `markdown`、`image`、音视频阅读器（D-12） | AC-07：Markdown 目录、公式、代码高亮正确；图片缩放拖动；视频点时间戳跳转 |
| T-08 | 设置"阅读"一节（D-14） | AC-08：换默认阅读器后阅读模式立即使用；外部引擎连不上时退回内置并提示；个人偏好只影响本浏览器 |
| T-09 | `onlyoffice` 适配器（D-13），一次性只读地址 | AC-09：装了 ONLYOFFICE Docs 的环境里，DOCX、XLSX、PPTX 原生显示，标注以只读批注出现；令牌过期或换原件时取不到文件；未安装时不影响其他功能 |
| T-10 | 关系图全屏与判断条目宽版（D-07） | AC-10：关系图全屏后铺满并适配，退出后恢复 |
| T-11 | 公式块（D-15）、裁切图（D-16），`EXTRACTOR_VERSION` = 3 | AC-11：Adam 的行间公式各为一个 `formula` 块；正文不被误标；文字与对照视图显示裁切图 |
| T-12 | 块补充 `blocks`（D-17）、KaTeX（D-19） | AC-12：AI 经 MCP 提交 LaTeX 后以 KaTeX 显示、标未确认；锚点与检索文字不变；判断正文 `$…$` 正确渲染 |
| T-13 | 文档、Skill、MCP 说明、ops 参考（§5） | AC-13：`tests/test_docs.py` 通过 |
| T-14 | 全量测试、临时 `--root` 试装、提交与安装 | AC-14：后端与前端测试通过；正式安装后在 trial 上实测（含你的 Chrome 全屏） |

建议分两批交付：第一批 T-01–T-05、T-07、T-08（不含外部引擎部分）、T-10、T-11、T-13、T-14（阅读模式与公式显示可用）；第二批 T-06、T-09、T-12（新格式、外部引擎、LaTeX 补充）。

## 8. 进度记录

- 2026-11-07：第一稿写成（只做 PDF 阅读器）。
- 2026-11-07：按用户意见改为第二稿：多格式调研（§2），改为"外壳 + 可更换的阅读器适配器 + 标注契约"，加入 Excel、外部 Office 引擎、阅读设置、第三方代码隔离；待用户确认。
- 2026-11-07：用户确认，开发第一批（2.0.0a12）：
  - T-01、T-02 外壳与契约：`frontend/src/reader/`（`Reader.tsx`、`contract.ts`、`registry.ts`、`marks.ts`、`prefs.ts`、`open.ts`）；隔离检查 `reader/isolation.test.ts`、标注与选阅读器 `reader/marks.test.ts`。入口：原件页工具栏、条目页、正文里原件段落旁的 ⛶。
  - T-03 阅读器：`viewers/pdfjs`（PDF 与快照 PDF）、`viewers/docx-preview`、`viewers/markdown`、`viewers/image`、`viewers/media`，各带 README；后端 `/api/artifact/{id}/snapshot/bytes`。
  - T-04、T-05 标注、侧栏、对照与文字视图：在 trial 数据副本上实测——Adam 带锚点 `#p2-2` 进入时滚到第 2 页并画出被读过的框，点框后侧栏显示引用写法与读取记录；对照视图右侧随左侧翻页同步；PPT 快照、Word（docx-preview）、文本、判断宽版均能显示；375 px 宽度下可用。
  - T-07 文本 / Markdown（KaTeX）、图片、音视频阅读器；音视频与图片未在真实原件上实测（trial 里没有这两类原件）。
  - T-08 设置页"阅读"：默认阅读器（`viewer.<格式>`，`settings.set` 只能由人改）与个人偏好；外部引擎部分在第二批。
  - T-10 关系图全屏：实测铺满、筛选与详情成为浮层。
  - T-11 公式块与裁切图：`EXTRACTOR_VERSION = 3`；`tests/test_extraction.py` 的 `test_pdf_layout_detects_display_formulas`、`test_pdf_layout_marks_inline_math_paragraphs`，裁切图在 `test_artifact_file_endpoint`。Adam 中 73 个、中文报告中 60 个公式块；大公式偶尔仍拆成两三块。
  - 未做：浏览器全屏（Fullscreen API）在内置浏览器里不能验证，需在用户 Chrome 里看；缩略图侧栏（D-05 中"左侧可收起页面缩略图"）未做，留到第二批。
- 2026-11-08：用户要求完成第二批（2.0.0a13）：
  - T-06 Excel：`extractors.extract_xlsx`、`sheet_blocks`；`viewers/sheet`（SheetJS CE 0.20.3）；原件页按工作表显示表格块；Excel 快照（本机 Excel 实测 3 页、约 7.5 秒）。测试 `test_xlsx_sheets_become_units_and_regions_become_table_blocks`、`test_sheet_blocks_and_column_names`、`test_extractor_upgrade_only_rebuilds_changed_formats`。在 trial 副本上实测：带锚点进入时跳到被读过的区域并加底色，合并单元格、工作表标签正常。
  - T-12 LaTeX 块补充：`extraction.submit_latex`、`_carry_latex`、`artifact.view(anchor)`；前端 `FormulaView`（KaTeX、来源与确认标记、对照原件、交给 AI、人工填写）。测试 `test_latex_supplement_keeps_text_anchor_and_citations`、`test_artifact_view_anchor_returns_block_crop`。在 trial 副本上：AI 提交的式 (1) 与人工填写的式 (2)(3) 都正确排版，标出"AI 识别 · 未确认"与"人工转写"。
  - T-09 ONLYOFFICE：`interfaces/engines.py`（HS256 签名、一次性令牌、连接测试），`/api/artifact/{id}/engine/onlyoffice`、`/engine-file/{令牌}`，设置项 `viewer.onlyoffice_*`，`viewers/onlyoffice`。测试 `test_jwt_signature_is_hs256`、`test_onlyoffice_settings_config_and_one_time_file_url`；用模拟引擎在浏览器里走通：设置页测试连接成功，阅读模式切到 ONLYOFFICE 后拿到 `mode=view`、带签名的配置，引擎凭令牌取回完整文件。**未在真实 ONLYOFFICE Docs 上实测。**
  - 缩略图（第一批遗留）：阅读模式工具栏 ▤，PDF 与快照阅读器可用。
