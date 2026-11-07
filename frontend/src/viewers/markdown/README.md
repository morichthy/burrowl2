# markdown 阅读器

| 项 | 内容 |
|---|---|
| 来源 | [react-markdown](https://github.com/remarkjs/react-markdown)、remark-gfm、[remark-math](https://github.com/remarkjs/remark-math)、rehype-katex、[KaTeX](https://github.com/KaTeX/KaTeX) |
| 版本 | react-markdown 10.1.0、remark-gfm 4.0.1、remark-math 6.0.0、rehype-katex 7.0.1、katex 0.16.22 |
| 许可证 | 均为 MIT |
| 显示的格式 | 文本原件：Markdown（含 `$…$`、`$$…$$` 公式）、纯文本与代码、CSV / TSV（表格）、JSON（格式化） |
| 能力 | 连续流、按段落定位标注（text） |
| 改动 | 不改源码；KaTeX 字体随前端构建打包，离线可用 |
| 已知限制 | 按段落（`seg-n`）分别渲染：跨空行的 Markdown 结构（例如中间有空行的列表、代码块）会被分成几段显示；CSV 只显示前 5000 行 |
