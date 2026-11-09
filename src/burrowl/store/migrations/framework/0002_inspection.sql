-- 设计稿 07：定期巡检。巡检包是框架内容（可以丢弃、不能作为依据），按需修改状态。
-- 巡检发现不单独建表：每条就是一项待决策（decisions.kind = 'finding'，设计稿 07 §9）。
-- inspections：一期巡检包。status：ready 准备好 / running 巡检中 / done 巡检完成 / closed 已关闭。
-- data：scope（since、until、judgments）、tasks（巡检任务）、samples（探索样本）、runs（各次运行）、claims（领取的会话）。
CREATE TABLE inspections (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  period INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready',
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_inspections_created ON inspections(created_at);
