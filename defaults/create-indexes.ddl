

CREATE INDEX IF NOT EXISTS ix_IndexItemDetailRow_original_iid ON IndexItemDetailRow (original_iid);
CREATE INDEX IF NOT EXISTS ix_IndexItemDetailRow_owner_iid ON IndexItemDetailRow (owner_iid);
CREATE INDEX IF NOT EXISTS ix_IndexItemDetailRow_detail_name ON IndexItemDetailRow (detail_name);
CREATE INDEX IF NOT EXISTS ix_IndexItemDetailRow_os_is_active ON IndexItemDetailRow (os_is_active);
