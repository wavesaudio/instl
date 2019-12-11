
CREATE TABLE short_index_t
(
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    iid TEXT,
    name TEXT,
    version_mac TEXT,
    version_win TEXT,
    guid_1 TEXT,
    guid_2 TEXT
);

CREATE TRIGGER IF NOT EXISTS add_mac_version_trigger
AFTER INSERT ON short_index_t
BEGIN
    UPDATE short_index_t
    SET version_mac  = (
    SELECT index_item_detail_t.detail_value AS version_mac
        FROM index_item_detail_t
        WHERE index_item_detail_t.detail_name == "version"
        AND index_item_detail_t.os_id IN (0, 1, 2, 3)
        AND index_item_detail_t.owner_iid == NEW.iid
        ORDER BY index_item_detail_t.generation ASC
        LIMIT 1)
    WHERE short_index_t.iid == NEW.iid;

    UPDATE short_index_t
    SET version_win  = (

    SELECT index_item_detail_t.detail_value AS version_win
        FROM index_item_detail_t
        WHERE index_item_detail_t.detail_name == "version"
        AND index_item_detail_t.os_id IN (0, 4, 5, 6)
        AND index_item_detail_t.owner_iid == NEW.iid
        ORDER BY index_item_detail_t.generation ASC
        LIMIT 1)
    WHERE short_index_t.iid == NEW.iid;
END;


INSERT INTO short_index_t(iid, name)
SELECT index_item_t.iid, index_item_detail_t.detail_value
FROM index_item_t, index_item_detail_t
WHERE index_item_t.iid == index_item_detail_t.owner_iid
AND index_item_detail_t.detail_name == "name";
