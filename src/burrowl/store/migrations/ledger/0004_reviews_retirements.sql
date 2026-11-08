-- 设计稿 04 D-18：复核是被复核条目的变更历史，不是新条目。每行一次复核或"请人复核"，只追加。
-- target_kind：page 框架页 / edge 边 / judgment 判断 / artifact 原件（原件只记"请人复核"，抽取确认仍在 extractions）。
-- verdict：confirm 确认 / reject 驳回 / unsure 拿不准（只有 AI）/ request 请人复核。
-- method：human 人 / ai AI。data：reason、cites（补充的依据）、local_observation、model、target_version、link_id、note。
CREATE TABLE reviews (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  target_id TEXT NOT NULL,
  target_kind TEXT NOT NULL CHECK (target_kind IN ('page','edge','judgment','artifact')),
  verdict TEXT NOT NULL CHECK (verdict IN ('confirm','reject','unsure','request')),
  method TEXT NOT NULL CHECK (method IN ('human','ai')),
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_reviews_target ON reviews(target_id, created_at);
CREATE TRIGGER reviews_no_update BEFORE UPDATE ON reviews BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER reviews_no_delete BEFORE DELETE ON reviews BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;

-- 原件退役不再写成判断（2.0.0a14，用户决定）：退役与恢复是原件的状态历史，只追加。
-- action：retire 退役 / restore 恢复。data：reason、replaced_by（替代它的原件，可空）。
-- 2.0.0a13 及以前写成 retirement 判断的退役照常有效，与本表按时间合并计算当前状态。
CREATE TABLE retirements (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  action TEXT NOT NULL CHECK (action IN ('retire','restore')),
  actor_id TEXT NOT NULL,
  session_id TEXT,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_retirements_artifact ON retirements(artifact_id, created_at);
CREATE TRIGGER retirements_no_update BEFORE UPDATE ON retirements BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER retirements_no_delete BEFORE DELETE ON retirements BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
