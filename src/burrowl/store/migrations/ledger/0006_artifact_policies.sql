-- 设计稿 08 D-30：原件的外发标记是人的决定，只追加，按时间取最后一条（做法同 retirements）。
-- policy：no_outbound 不外发 / outbound 恢复可外发。data：reason。
CREATE TABLE artifact_policies (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  policy TEXT NOT NULL CHECK (policy IN ('no_outbound','outbound')),
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_artifact_policies_artifact ON artifact_policies(artifact_id, created_at);
CREATE TRIGGER artifact_policies_no_update BEFORE UPDATE ON artifact_policies BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
-- 删除原件（设计稿 07 D-05）经 purge_gate 放行，与其他账本表相同
CREATE TRIGGER artifact_policies_no_delete BEFORE DELETE ON artifact_policies WHEN NOT EXISTS (SELECT 1 FROM purge_gate WHERE id = OLD.id) BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
