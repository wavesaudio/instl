CREATE TABLE ChangeLog
(
_id INTEGER PRIMARY KEY NOT NULL,
time DATETIME default (datetime('now','localtime')),
owner_iid TEXT,
detail_name TEXT,
detail_value TEXT,
os_id INTEGER,
old_active INTEGER,
new_active INTEGER,
log_text TEXT
);

CREATE TRIGGER IF NOT EXISTS log_adjust_active_os_for_details
AFTER UPDATE OF active ON IndexItemDetailRow
BEGIN
    INSERT INTO ChangeLog (owner_iid, detail_name, detail_value, os_id, old_active, new_active)
    VALUES (OLD.owner_iid, OLD.detail_name, OLD.detail_value, OLD.os_id,  OLD.active,  NEW.active);
END;
