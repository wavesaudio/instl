
DROP TABLE IF EXISTS short_index_t;
DROP TRIGGER IF EXISTS add_mac_version_trigger;
DROP INDEX IF EXISTS ix_short_index_t_iid;

CREATE TABLE short_index_t
(
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    iid TEXT,
    name TEXT,
    version_mac TEXT,
    version_win TEXT,
    install_guid TEXT,
    remove_guid TEXT,
    FOREIGN KEY(iid) REFERENCES index_item_t(iid)
);
-- having both FOREIGN KEY and UNIQUE INDEX on short_index_t.iid was measured to improve insert and select time
CREATE UNIQUE INDEX ix_short_index_t_iid ON short_index_t (iid);

CREATE TRIGGER IF NOT EXISTS add_iid_ro_short_index_t_trigger
AFTER INSERT ON short_index_t
BEGIN
    -- get the name of the iid
    UPDATE short_index_t
    SET name  = (
    SELECT index_item_detail_t.detail_value AS name
        FROM index_item_detail_t
        WHERE index_item_detail_t.detail_name == 'name'
        AND index_item_detail_t.original_iid == NEW.iid
        ORDER BY index_item_detail_t.generation ASC
        LIMIT 1)
    WHERE short_index_t.iid == NEW.iid;

    -- get the version for Mac (could be version common to Mac and Win)
    UPDATE short_index_t
    SET version_mac  = (
    SELECT index_item_detail_t.detail_value AS version_mac
        FROM index_item_detail_t
        WHERE index_item_detail_t.detail_name == "version"
        AND index_item_detail_t.os_id IN (SELECT _id FROM active_operating_systems_t WHERE (_id == 0 OR name LIKE "Mac%"))
        AND index_item_detail_t.owner_iid == NEW.iid
        ORDER BY index_item_detail_t.generation ASC
        LIMIT 1)
    WHERE short_index_t.iid == NEW.iid;

    -- get the version for Win (could be version common to Mac and Win)
    UPDATE short_index_t
    SET version_win  = (
    SELECT index_item_detail_t.detail_value AS version_win
        FROM index_item_detail_t
        WHERE index_item_detail_t.detail_name == "version"
        AND index_item_detail_t.os_id IN (SELECT _id FROM active_operating_systems_t WHERE (_id == 0 OR name LIKE "Win%"))
        AND index_item_detail_t.owner_iid == NEW.iid
        ORDER BY index_item_detail_t.generation ASC
        LIMIT 1)
    WHERE short_index_t.iid == NEW.iid;

    -- get the "original" guid - not inherited
    UPDATE short_index_t
    SET install_guid  = (
    SELECT index_item_detail_t.detail_value AS guid_1
        FROM index_item_detail_t
        WHERE index_item_detail_t.detail_name == "guid"
        AND index_item_detail_t.original_iid == NEW.iid
        ORDER BY index_item_detail_t.generation ASC
        LIMIT 1)
    WHERE short_index_t.iid == NEW.iid;

    -- get the "inherited" guid - this should be the uninstall guid
    UPDATE short_index_t
    SET remove_guid  = (
    SELECT index_item_detail_t.detail_value AS guid_2
        FROM index_item_detail_t
        WHERE index_item_detail_t.detail_name == "guid"
        AND index_item_detail_t.owner_iid == NEW.iid
        ORDER BY index_item_detail_t.generation DESC
        LIMIT 1)
    WHERE short_index_t.iid == NEW.iid;
END;

-- insert all iids from index_item_t, this will activate the trigger
INSERT INTO short_index_t(iid)
SELECT index_item_t.iid
FROM index_item_t;
