CREATE TABLE ConfigVar
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT UNIQUE,
	raw_value TEXT,
	resolved_value TEXT
);

CREATE TABLE FoundOnDiskItemRow
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	path TEXT,
	name TEXT,
	version TEXT,
	guid TEXT,
	iid TEXT
);

CREATE TABLE svnitem
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	path TEXT,
	flags TEXT,
	revision INTEGER,
	checksum TEXT,
	size INTEGER,
	url TEXT,
	fileFlag BOOLEAN,
	wtarFlag INTEGER,
	leaf TEXT,
	parent TEXT,
	level INTEGER,
	required BOOLEAN,
	need_download BOOLEAN,
	download_path TEXT,
	download_root TEXT,
	extra_props TEXT
);

CREATE TABLE IIDToSVNItem
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	iid TEXT,
	svn_id INTEGER,
 FOREIGN KEY(iid) REFERENCES IndexItemRow(iid) ON DELETE CASCADE,
 FOREIGN KEY(svn_id) REFERENCES svnitem(_id)
);

CREATE TABLE IndexItemDetailOperatingSystem
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT UNIQUE,
	os_is_active BOOLEAN
);

CREATE TABLE IndexItemRow
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	iid TEXT UNIQUE,
	inherit_resolved BOOLEAN,
	from_index BOOLEAN,
	from_require BOOLEAN,
	install_status INTEGER,
	ignore INTEGER,
	direct_sync INTEGER
);

CREATE TABLE IndexItemDetailRow
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	original_iid TEXT,
	owner_iid TEXT,
	os_id INTEGER,
	detail_name TEXT,
	detail_value TEXT,
	generation INTEGER,
	tag TEXT,
	os_is_active INTEGER,
	UNIQUE (original_iid, owner_iid, os_id, detail_name, detail_value, generation),
  FOREIGN KEY(original_iid) REFERENCES IndexItemRow(iid) ON DELETE CASCADE,
  FOREIGN KEY(os_id) REFERENCES IndexItemDetailOperatingSystem(_id)
);

CREATE TABLE IndexRequireTranslate
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	iid TEXT,
	require_by TEXT,
	status INTEGER,
	UNIQUE (iid, require_by)
);
