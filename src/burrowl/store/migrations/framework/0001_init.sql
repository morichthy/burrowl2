-- 框架：可再生、可修改；页面改写一律新增版本（DESIGN §2）。
CREATE TABLE entities (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  user_marked INTEGER NOT NULL DEFAULT 0,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX idx_entities_name ON entities(kind, name);

CREATE TABLE aliases (
  alias TEXT NOT NULL,
  entity_id TEXT NOT NULL REFERENCES entities(id),
  decided_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (alias, entity_id)
);

CREATE TABLE pages (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  type TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  subject_id TEXT,
  head_version INTEGER NOT NULL,
  freshness TEXT NOT NULL DEFAULT 'valid',
  review TEXT NOT NULL DEFAULT 'ai_generated',
  data TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE page_versions (
  page_id TEXT NOT NULL REFERENCES pages(id),
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  author_id TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (page_id, version)
);
CREATE TRIGGER page_versions_no_update BEFORE UPDATE ON page_versions BEGIN SELECT RAISE(ABORT, 'page versions are append-only'); END;

CREATE TABLE edges (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  rel TEXT NOT NULL,
  src_id TEXT NOT NULL,
  dst_id TEXT NOT NULL,
  origin TEXT NOT NULL,
  review TEXT NOT NULL DEFAULT 'ai_generated',
  freshness TEXT NOT NULL DEFAULT 'valid',
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_edges_src ON edges(src_id);
CREATE INDEX idx_edges_dst ON edges(dst_id);
CREATE UNIQUE INDEX idx_edges_unique ON edges(rel, src_id, dst_id, origin);

-- 派生输入清单：直接指向不可变单元及其版本（草图 §11.4）；按 input_id 反查受影响的框架条目
CREATE TABLE derivation_inputs (
  derived_kind TEXT NOT NULL,
  derived_id TEXT NOT NULL,
  derived_version INTEGER NOT NULL,
  input_id TEXT NOT NULL,
  PRIMARY KEY (derived_kind, derived_id, derived_version, input_id)
);
CREATE INDEX idx_derivation_inputs_input ON derivation_inputs(input_id);

CREATE TABLE decisions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  subject_id TEXT,
  impact INTEGER NOT NULL DEFAULT 0,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_decisions_open ON decisions(status, impact);

CREATE TABLE agent_runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  agent TEXT NOT NULL,
  status TEXT NOT NULL,
  session_id TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}'
);
