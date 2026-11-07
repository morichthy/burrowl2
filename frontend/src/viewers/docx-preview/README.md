# docx-preview 阅读器

| 项 | 内容 |
|---|---|
| 来源 | [docx-preview](https://github.com/VolodymyrBaydalka/docxjs) |
| 版本 | 0.4.1（见 `frontend/package.json`） |
| 许可证 | Apache-2.0 |
| 显示的格式 | DOCX（连续展开，不分页） |
| 能力 | 连续流、按文字定位标注（text） |
| 改动 | 不改源码，只用 `renderAsync` |
| 已知限制 | 版式是浏览器排版的近似（分页、浮动对象、复杂表格可能与 Word 不同）；要求逐页一致时在设置里把 Word 的默认阅读器换成"页面快照（PDF.js）"；段落按文字对应，抽取块与渲染元素对不上的段落不画标记 |
