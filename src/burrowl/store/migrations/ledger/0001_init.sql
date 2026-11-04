-- 账本：原件一列与判断一列。只追加，触发器拒绝 UPDATE 与 DELETE（DESIGN §2）。
CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_class TEXT NOT NULL CHECK (source_class IN ('executed','external','discussion')),
  sha256 TEXT NOT NULL,
  storage TEXT NOT NULL CHECK (storage IN ('managed','referenced')),
  uri TEXT,
  version_of TEXT REFERENCES artifacts(id),
  captured_by TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_artifacts_sha ON artifacts(sha256);
CREATE INDEX idx_artifacts_version_of ON artifacts(version_of);

CREATE TABLE events (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  actor_id TEXT NOT NULL,
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','ai','system')),
  op TEXT NOT NULL,
  objects TEXT NOT NULL DEFAULT '[]',
  data TEXT NOT NULL DEFAULT '{}',
  UNIQUE (session_id, seq)
);
CREATE INDEX idx_events_session ON events(session_id, seq);

CREATE TABLE records (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  event_id TEXT REFERENCES events(id),
  artifact_id TEXT REFERENCES artifacts(id),
  objects TEXT NOT NULL DEFAULT '[]',
  boundary TEXT NOT NULL CHECK (boundary IN ('complete','truncated','partial','restricted')),
  promoted_by TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  CHECK (event_id IS NOT NULL OR artifact_id IS NOT NULL)
);

CREATE TABLE reads (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  artifact_sha256 TEXT NOT NULL,
  locator TEXT NOT NULL,
  session_id TEXT,
  actor_id TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_reads_artifact ON reads(artifact_id);

CREATE TABLE judgments (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  author_id TEXT NOT NULL,
  author_kind TEXT NOT NULL CHECK (author_kind IN ('human','ai','system')),
  revises TEXT REFERENCES judgments(id),
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_judgments_kind ON judgments(kind);

CREATE TABLE links (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  rel TEXT NOT NULL,
  src_id TEXT NOT NULL,
  dst_id TEXT NOT NULL,
  author_id TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_links_src ON links(src_id);
CREATE INDEX idx_links_dst ON links(dst_id, rel);

-- 条目涉及的对象（实体 ID 或规范化的对象名），便于按对象过滤；与条目同时写入，也只追加
CREATE TABLE entry_objects (
  entry_id TEXT NOT NULL,
  object TEXT NOT NULL,
  PRIMARY KEY (entry_id, object)
);
CREATE INDEX idx_entry_objects_object ON entry_objects(object);

CREATE TRIGGER artifacts_no_update BEFORE UPDATE ON artifacts BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER artifacts_no_delete BEFORE DELETE ON artifacts BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER records_no_delete BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER reads_no_update BEFORE UPDATE ON reads BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER reads_no_delete BEFORE DELETE ON reads BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER judgments_no_update BEFORE UPDATE ON judgments BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER judgments_no_delete BEFORE DELETE ON judgments BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER links_no_update BEFORE UPDATE ON links BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER links_no_delete BEFORE DELETE ON links BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER entry_objects_no_update BEFORE UPDATE ON entry_objects BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER entry_objects_no_delete BEFORE DELETE ON entry_objects BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
