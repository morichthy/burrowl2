// 页面快照阅读器（设计稿 03 D-09、D-10）：PPTX / DOCX 的快照本来就是 Office / LibreOffice 转出的 PDF，
// 交给同一个 PDF.js 阅读器显示。PPT 的块带 box、页码就是幻灯片序号，段落框照常画；Word 的块没有页内位置，只显示原样。
import { useMemo } from "react";
import type { ViewerProps } from "../../reader/contract";
import PdfjsViewer from "./index";

export default function SnapshotViewer(props: ViewerProps) {
  const { source } = props;
  const snap = useMemo(() => ({ ...source, bytes: source.snapshotBytes ?? source.bytes }), [source]);
  return <PdfjsViewer {...props} source={snap} />;
}
