# sheet 阅读器

| 项 | 内容 |
|---|---|
| 来源 | [SheetJS Community Edition](https://git.sheetjs.com/sheetjs/sheetjs)（npm 上的 `xlsx` 包已停止更新，按官方说明从 `cdn.sheetjs.com` 安装） |
| 版本 | 0.20.3（`frontend/package.json` 里写的是官方 CDN 的 tgz 地址） |
| 许可证 | Apache-2.0 |
| 显示的格式 | Excel（.xlsx / .xlsm）；CSV、TSV 文本原件 |
| 能力 | 连续流、按单元格范围标注（text）：Excel 抽取块的 `range`（如 `A1:F20`）被引用、被读过时加底色 |
| 改动 | 不改源码；表格界面（列标、行号、冻结表头、工作表标签、虚拟滚动）是本目录自写的 |
| 已知限制 | 只读，不显示单元格格式（字体、颜色、边框）、图表、图片、条件格式；最多显示 200 列；公式显示文件里保存的计算结果，悬停看公式；要求逐页一致时用页面快照（Office / LibreOffice 转出的 PDF）或 ONLYOFFICE；CSV 的段落是文本段，不在表格上标注 |
