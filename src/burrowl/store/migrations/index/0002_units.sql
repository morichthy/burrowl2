-- 检索单元与向量缓存（设计稿 04 D-01、D-06、D-07）。索引库随时可删除重建。
-- units：相邻引用段落合并成的召回单位；anchors 是它覆盖的段落（JSON 数组），tokens 是预先切好的词。
CREATE TABLE units (
  rowid INTEGER PRIMARY KEY,
  entry_id TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 0,
  layer TEXT NOT NULL,
  ordinal INTEGER NOT NULL DEFAULT 0,
  anchors TEXT NOT NULL DEFAULT '[]',
  scopes TEXT NOT NULL DEFAULT '[]',
  context TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  tokens TEXT NOT NULL,
  key TEXT NOT NULL
);
CREATE INDEX idx_units_entry ON units(entry_id, version);
CREATE INDEX idx_units_key ON units(key);
CREATE VIRTUAL TABLE units_fts USING fts5(tokens, content='units', content_rowid='rowid', tokenize='unicode61');
CREATE TRIGGER units_ai AFTER INSERT ON units BEGIN
  INSERT INTO units_fts(rowid, tokens) VALUES (new.rowid, new.tokens);
END;
CREATE TRIGGER units_ad AFTER DELETE ON units BEGIN
  INSERT INTO units_fts(units_fts, rowid, tokens) VALUES ('delete', old.rowid, old.tokens);
END;
-- 向量缓存：按"上下文 + 单元文本"的指纹（key）与模型指纹存放，整库重建索引时不删，内容变了自然不再被用到。
CREATE TABLE vectors (
  key TEXT NOT NULL,
  model TEXT NOT NULL,
  dim INTEGER NOT NULL,
  vec BLOB NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (key, model)
);
