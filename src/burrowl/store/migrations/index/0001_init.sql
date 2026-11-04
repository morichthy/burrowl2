-- 检索索引：随时可删除重建。每行记下来源条目与版本（DESIGN §3.2）。
CREATE TABLE docs (
  rowid INTEGER PRIMARY KEY,
  entry_id TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 0,
  layer TEXT NOT NULL,
  ordinal INTEGER NOT NULL DEFAULT 0,
  locator TEXT NOT NULL DEFAULT '',
  sha256 TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL
);
CREATE INDEX idx_docs_entry ON docs(entry_id, version);
CREATE VIRTUAL TABLE docs_fts USING fts5(text, content='docs', content_rowid='rowid', tokenize='trigram');
CREATE TRIGGER docs_ai AFTER INSERT ON docs BEGIN
  INSERT INTO docs_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER docs_ad AFTER DELETE ON docs BEGIN
  INSERT INTO docs_fts(docs_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
