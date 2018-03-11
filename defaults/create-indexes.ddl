

CREATE INDEX IF NOT EXISTS ix_index_item_detail_t_original_iid ON index_item_detail_t (original_iid);
CREATE INDEX IF NOT EXISTS ix_index_item_detail_t_owner_iid ON index_item_detail_t (owner_iid);
CREATE INDEX IF NOT EXISTS ix_index_item_detail_t_detail_name ON index_item_detail_t (detail_name);
CREATE INDEX IF NOT EXISTS ix_index_item_detail_t_os_is_active ON index_item_detail_t (os_is_active);
