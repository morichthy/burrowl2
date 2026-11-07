-- 设计稿 01 D-10：抽取层属于原件，不是另一条原件。只追加，触发器拒绝 UPDATE 与 DELETE。
-- kind：manifest 单元清单（PDF 的页、PPT 的页、嵌入图片等）；content 某个单元的抽取文本与版式块；
--       verification 人确认某条 content；snapshot 页面快照（Office/LibreOffice 转成的 PDF，只用于显示）。
-- 当前抽取层 = 每个单元最新的一条 content；正文较短，存在 data 里，嵌入图片与快照 PDF 存 blobs。
CREATE TABLE extractions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  artifact_sha256 TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('manifest','content','verification','snapshot')),
  unit TEXT NOT NULL DEFAULT '',
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_extractions_artifact ON extractions(artifact_id, kind, unit, created_at);
CREATE TRIGGER extractions_no_update BEFORE UPDATE ON extractions BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER extractions_no_delete BEFORE DELETE ON extractions BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
