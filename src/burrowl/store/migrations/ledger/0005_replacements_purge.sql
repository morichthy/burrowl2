-- 设计稿 07：原件的替换与删除。
-- replacements：人给已退役或已删除的原件指定替代原件（只追加）。old_id 不设外键：旧原件可能已经删除。
-- data：reason。退役时填写的 retirements.data.replaced_by 同样算替换（JudgmentService.replacement_of）。
CREATE TABLE replacements (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  old_id TEXT NOT NULL,
  new_id TEXT NOT NULL REFERENCES artifacts(id),
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_replacements_old ON replacements(old_id, created_at);
CREATE TRIGGER replacements_no_update BEFORE UPDATE ON replacements BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;

-- purge_gate：删除原件的唯一通道（D-05）。不是账本表：只在删除事务内写入、并在同一事务内清空，
-- 所以删除之后不留任何关于被删条目的记录。各账本表的禁止删除触发器只放行出现在这里的行。
CREATE TABLE purge_gate (id TEXT PRIMARY KEY);

DROP TRIGGER artifacts_no_delete;
CREATE TRIGGER artifacts_no_delete BEFORE DELETE ON artifacts WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
DROP TRIGGER events_no_delete;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
DROP TRIGGER records_no_delete;
CREATE TRIGGER records_no_delete BEFORE DELETE ON records WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
DROP TRIGGER reads_no_delete;
CREATE TRIGGER reads_no_delete BEFORE DELETE ON reads WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
DROP TRIGGER judgments_no_delete;
CREATE TRIGGER judgments_no_delete BEFORE DELETE ON judgments WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
DROP TRIGGER links_no_delete;
CREATE TRIGGER links_no_delete BEFORE DELETE ON links WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
DROP TRIGGER entry_objects_no_delete;
CREATE TRIGGER entry_objects_no_delete BEFORE DELETE ON entry_objects WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.entry_id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
DROP TRIGGER extractions_no_delete;
CREATE TRIGGER extractions_no_delete BEFORE DELETE ON extractions WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
DROP TRIGGER reviews_no_delete;
CREATE TRIGGER reviews_no_delete BEFORE DELETE ON reviews WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
DROP TRIGGER retirements_no_delete;
CREATE TRIGGER retirements_no_delete BEFORE DELETE ON retirements WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER replacements_no_delete BEFORE DELETE ON replacements WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
