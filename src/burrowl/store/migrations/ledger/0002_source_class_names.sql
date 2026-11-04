-- D-14：依据来源改名 executed → local（本地实证）、discussion → inferred（推断）。
-- SQLite 不能修改 CHECK 约束，所以重建 artifacts 表并按新名字复制已有行。
-- 只在没有其他表引用 artifacts 的行时才能执行（DROP TABLE 会做一次隐式删除并检查外键）；
-- 2.0.0a4 之前没有真实数据写入，满足这个条件。以后的迁移不得再改已有取值的含义（I8）。
CREATE TABLE artifacts_v2 (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_class TEXT NOT NULL CHECK (source_class IN ('local','external','inferred')),
  sha256 TEXT NOT NULL,
  storage TEXT NOT NULL CHECK (storage IN ('managed','referenced')),
  uri TEXT,
  version_of TEXT REFERENCES artifacts(id),
  captured_by TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
INSERT INTO artifacts_v2
  SELECT id, created_at, kind,
         CASE source_class WHEN 'executed' THEN 'local' WHEN 'discussion' THEN 'inferred' ELSE source_class END,
         sha256, storage, uri, version_of, captured_by, session_id, data
  FROM artifacts;
DROP TRIGGER artifacts_no_update;
DROP TRIGGER artifacts_no_delete;
DROP TABLE artifacts;
ALTER TABLE artifacts_v2 RENAME TO artifacts;
CREATE INDEX idx_artifacts_sha ON artifacts(sha256);
CREATE INDEX idx_artifacts_version_of ON artifacts(version_of);
CREATE TRIGGER artifacts_no_update BEFORE UPDATE ON artifacts BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER artifacts_no_delete BEFORE DELETE ON artifacts BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
