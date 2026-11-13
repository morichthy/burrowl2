-- 判断的标题是条目的标签，不是内容：人采用或改标题不产生新版本、不传播变化。
-- 每次改一行，同一条判断取最后一行；title 为空字符串表示清掉标题。版本里（data.title）的标题仍然保留，
-- 没有这里的记录时沿用它。做法同 artifact_policies：只追加，删除只对 purge_gate 放行。
CREATE TABLE judgment_titles (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  judgment_id TEXT NOT NULL,
  title TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_judgment_titles_judgment ON judgment_titles(judgment_id, created_at);

CREATE TRIGGER judgment_titles_no_update BEFORE UPDATE ON judgment_titles BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER judgment_titles_no_delete BEFORE DELETE ON judgment_titles WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
