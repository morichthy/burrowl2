-- 账本基线（2.1.0，设计稿 10）。2.0.x 的数据目录不兼容，由打开时的结构检查拒绝（D-03）。
-- 只追加：触发器拒绝 UPDATE 与 DELETE；删除原件只能经 purge_gate 放行（设计稿 07 D-05）。
--
-- 条目（原件、过程日志、事实记录、读取记录、判断）ID 稳定，版本写 `@n`（D-01）：
-- 每一版是 *_versions 表里的一行，主键 (id, version)。同名视图（artifacts、judgments……）只给每个条目的最新版，
-- 即当前版。写入只经 store/ledger.py 写基表。

CREATE TABLE artifact_versions (
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_class TEXT NOT NULL CHECK (source_class IN ('local','external','inferred')),
  sha256 TEXT NOT NULL,
  storage TEXT NOT NULL CHECK (storage IN ('managed','referenced')),
  uri TEXT,
  captured_by TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (id, version)
);
CREATE INDEX idx_artifact_versions_sha ON artifact_versions(sha256);

CREATE TABLE event_versions (
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  actor_id TEXT NOT NULL,
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','ai','system')),
  op TEXT NOT NULL,
  objects TEXT NOT NULL DEFAULT '[]',
  data TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (id, version)
);
CREATE INDEX idx_event_versions_session ON event_versions(session_id, seq);

CREATE TABLE record_versions (
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  event_id TEXT,
  artifact_id TEXT,
  objects TEXT NOT NULL DEFAULT '[]',
  boundary TEXT NOT NULL CHECK (boundary IN ('complete','truncated','partial','restricted')),
  promoted_by TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  CHECK (event_id IS NOT NULL OR artifact_id IS NOT NULL),
  PRIMARY KEY (id, version)
);

CREATE TABLE read_versions (
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  artifact_version INTEGER NOT NULL DEFAULT 1,
  artifact_sha256 TEXT NOT NULL,
  locator TEXT NOT NULL,
  session_id TEXT,
  actor_id TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (id, version)
);
CREATE INDEX idx_read_versions_artifact ON read_versions(artifact_id);

-- 判断只存事实（D-05）：data 里是 text、conditions、reopen_condition、external_author、local_observation、
-- change_reason、inspection_finding。可信度、提示一律读取时推出（services/coordinates.py）。
CREATE TABLE judgment_versions (
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('conclusion','process','normative')),
  author_id TEXT NOT NULL,
  author_kind TEXT NOT NULL CHECK (author_kind IN ('human','ai','system')),
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (id, version)
);
CREATE INDEX idx_judgment_versions_kind ON judgment_versions(kind);

CREATE VIEW artifacts AS SELECT * FROM artifact_versions v
  WHERE version = (SELECT MAX(version) FROM artifact_versions WHERE id = v.id);
CREATE VIEW events AS SELECT * FROM event_versions v
  WHERE version = (SELECT MAX(version) FROM event_versions WHERE id = v.id);
CREATE VIEW records AS SELECT * FROM record_versions v
  WHERE version = (SELECT MAX(version) FROM record_versions WHERE id = v.id);
CREATE VIEW reads AS SELECT * FROM read_versions v
  WHERE version = (SELECT MAX(version) FROM read_versions WHERE id = v.id);
CREATE VIEW judgments AS SELECT * FROM judgment_versions v
  WHERE version = (SELECT MAX(version) FROM judgment_versions WHERE id = v.id);

-- 条目涉及的对象名（写的人给出的名称，不是条目，D-07）；随版本存放，新版本沿用上一版
CREATE TABLE entry_objects (
  entry_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  object TEXT NOT NULL,
  PRIMARY KEY (entry_id, version, object)
);
CREATE INDEX idx_entry_objects_object ON entry_objects(object);

-- 关系（D-07）：主语—谓词—宾语，一条一行。两端固定到版本；宾语可带段落锚点。
-- predicate 取 core/vocab.py 的核心谓词，或 relates + label（自由谓词，D-09）。
-- qualifiers：condition、reason、所引段落的指纹等限定；args：多元关系的其他角色（D-11，第一版不启用）。
CREATE TABLE relations (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  predicate TEXT NOT NULL,
  label TEXT,
  subject_id TEXT NOT NULL,
  subject_version INTEGER,
  object_id TEXT NOT NULL,
  object_version INTEGER,
  object_anchor TEXT NOT NULL DEFAULT '',
  asserted_by TEXT NOT NULL,
  session_id TEXT,
  qualifiers TEXT NOT NULL DEFAULT '{}',
  args TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_relations_subject ON relations(subject_id, subject_version);
CREATE INDEX idx_relations_object ON relations(object_id, predicate);
CREATE INDEX idx_relations_label ON relations(predicate, label);

-- 人的处置记在版本上（D-04）：withdraw 撤回 / unwithdraw 取消撤回 / defect 标缺陷 / undefect 取消缺陷 /
-- retire 退役 / restore 取消退役。data：reason、replaced_by（退役原件时指定的替代原件）。
CREATE TABLE version_states (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  entry_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('withdraw','unwithdraw','defect','undefect','retire','restore')),
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_version_states_entry ON version_states(entry_id, version);

-- 设计稿 01 D-10：抽取层属于原件。kind：manifest / content / verification / snapshot。
CREATE TABLE extractions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('manifest','content','verification','snapshot')),
  unit TEXT NOT NULL DEFAULT '',
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_extractions_artifact ON extractions(artifact_id, kind, unit, created_at);

-- 复核（设计稿 04 D-18）：被复核条目某一版的变更历史。target_kind：page / edge / judgment / artifact；
-- verdict：confirm / reject / unsure / request；method：human / ai。
-- data：reason、cites、local_observation、model、revoked_rel_id、note。
CREATE TABLE reviews (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  target_id TEXT NOT NULL,
  target_version INTEGER,
  target_kind TEXT NOT NULL CHECK (target_kind IN ('page','edge','judgment','artifact')),
  verdict TEXT NOT NULL CHECK (verdict IN ('confirm','reject','unsure','request')),
  method TEXT NOT NULL CHECK (method IN ('human','ai')),
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_reviews_target ON reviews(target_id, created_at);
CREATE INDEX idx_reviews_revoked_rel ON reviews(json_extract(data, '$.revoked_rel_id'))
  WHERE json_extract(data, '$.revoked_rel_id') IS NOT NULL;

-- 设计稿 07 D-03：人给已退役或已删除的原件指定替代原件。old_id 不设外键：旧原件可能已经删除。
CREATE TABLE replacements (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  old_id TEXT NOT NULL,
  new_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_replacements_old ON replacements(old_id, created_at);

-- 设计稿 08 D-30：原件的外发标记。policy：no_outbound / outbound。
CREATE TABLE artifact_policies (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  policy TEXT NOT NULL CHECK (policy IN ('no_outbound','outbound')),
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_artifact_policies_artifact ON artifact_policies(artifact_id, created_at);

-- 人撤销复核后，复核写回的关系仍留在账本，日常查询只读有效关系。_row 是写入顺序（视图没有 rowid）
CREATE VIEW effective_relations AS
SELECT r.rowid AS _row, r.* FROM relations r
WHERE r.predicate NOT IN ('opposes', 'supersedes') OR NOT EXISTS (
  SELECT 1 FROM reviews v WHERE json_extract(v.data, '$.revoked_rel_id') = r.id
);

-- purge_gate：删除原件的唯一通道（设计稿 07 D-05）。只在删除事务内写入并清空，不留被删条目的记录。
CREATE TABLE purge_gate (id TEXT PRIMARY KEY);

CREATE TRIGGER artifact_versions_no_update BEFORE UPDATE ON artifact_versions BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER artifact_versions_no_delete BEFORE DELETE ON artifact_versions WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER event_versions_no_update BEFORE UPDATE ON event_versions BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER event_versions_no_delete BEFORE DELETE ON event_versions WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER record_versions_no_update BEFORE UPDATE ON record_versions BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER record_versions_no_delete BEFORE DELETE ON record_versions WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER read_versions_no_update BEFORE UPDATE ON read_versions BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER read_versions_no_delete BEFORE DELETE ON read_versions WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER judgment_versions_no_update BEFORE UPDATE ON judgment_versions BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER judgment_versions_no_delete BEFORE DELETE ON judgment_versions WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER entry_objects_no_update BEFORE UPDATE ON entry_objects BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER entry_objects_no_delete BEFORE DELETE ON entry_objects WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.entry_id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER relations_no_update BEFORE UPDATE ON relations BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER relations_no_delete BEFORE DELETE ON relations WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER version_states_no_update BEFORE UPDATE ON version_states BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER version_states_no_delete BEFORE DELETE ON version_states WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER extractions_no_update BEFORE UPDATE ON extractions BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER extractions_no_delete BEFORE DELETE ON extractions WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER reviews_no_update BEFORE UPDATE ON reviews BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER reviews_no_delete BEFORE DELETE ON reviews WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER replacements_no_update BEFORE UPDATE ON replacements BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER replacements_no_delete BEFORE DELETE ON replacements WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER artifact_policies_no_update BEFORE UPDATE ON artifact_policies BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER artifact_policies_no_delete BEFORE DELETE ON artifact_policies WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
