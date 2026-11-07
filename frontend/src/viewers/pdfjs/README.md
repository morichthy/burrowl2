# pdfjs 阅读器

| 项 | 内容 |
|---|---|
| 来源 | [PDF.js](https://github.com/mozilla/pdf.js) 的阅读器组件 `pdfjs-dist/web/pdf_viewer.mjs`（`PDFViewer`、`EventBus`、`PDFLinkService`、`PDFFindController`） |
| 版本 | `pdfjs-dist` 6.4.299（见 `frontend/package.json`；核心库与阅读器组件版本必须一致，PDF.js 启动时会检查） |
| 许可证 | Apache-2.0 |
| 显示的格式 | `pdfjs`：PDF；`pdfjs-snapshot`：PPTX / DOCX 的页面快照 PDF |
| 能力 | 分页、坐标标注（boxes）、查找、目录（PDF 自带的 outline）、缩放、单页 / 连续滚动、双页 |
| 改动 | 不改源码，只用公开 API；CMap、标准字体等资源随前端构建复制到 `web/pdfjs/`（`vite.config.ts`），离线可用 |
| 已知限制 | PDF.js 的注释编辑器关闭（它会把注释写进 PDF，原件不能改）；Word 快照上没有段落位置，只显示原样不画框；表单只显示不可填 |
