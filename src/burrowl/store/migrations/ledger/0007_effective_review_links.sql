-- 人撤销复核后，原记录和写回关系仍留在账本，日常查询只读有效关系。
CREATE INDEX idx_reviews_revoked_link ON reviews(json_extract(data, '$.revoked_link_id'))
  WHERE json_extract(data, '$.revoked_link_id') IS NOT NULL;

CREATE VIEW effective_links AS
SELECT l.* FROM links l
WHERE l.rel NOT IN ('opposes', 'supersedes') OR NOT EXISTS (
  SELECT 1 FROM reviews r
  WHERE json_extract(r.data, '$.revoked_link_id') IS NOT NULL
    AND json_extract(r.data, '$.revoked_link_id') = l.id
);
