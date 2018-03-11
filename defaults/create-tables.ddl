
CREATE TABLE active_operating_systems_t
(
  _id INTEGER PRIMARY KEY,
	name TEXT UNIQUE,
	os_is_active BOOLEAN DEFAULT 0
);

CREATE TABLE config_var_t
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	name TEXT UNIQUE,
	raw_value TEXT,
	resolved_value TEXT
);

CREATE TABLE require_translate_t
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	iid TEXT,
	require_by TEXT,
	status INTEGER,
	UNIQUE (iid, require_by)
);

CREATE TABLE found_installed_binaries_t
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	path TEXT,
	name TEXT,
	version TEXT,
	guid TEXT,
	iid TEXT
);


CREATE TABLE svn_item_t
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


CREATE TABLE iid_to_svn_item_t
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	iid TEXT,
	svn_id INTEGER,
 FOREIGN KEY(iid) REFERENCES index_item_t(iid) ON DELETE CASCADE,
 FOREIGN KEY(svn_id) REFERENCES svn_item_t(_id)
);

CREATE TABLE index_item_t
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	iid TEXT UNIQUE,
	inherit_resolved  BOOLEAN DEFAULT 0,
	from_index        BOOLEAN DEFAULT 0,
	from_require      BOOLEAN DEFAULT 0,
	install_status    INTEGER DEFAULT 0,
	ignore            INTEGER DEFAULT 0,
	direct_sync       INTEGER DEFAULT 0
);

CREATE TABLE index_item_detail_t
(
  _id INTEGER PRIMARY KEY AUTOINCREMENT,
	original_iid TEXT,
	owner_iid TEXT,
	os_id INTEGER,
	detail_name TEXT,
	detail_value TEXT,
	generation INTEGER DEFAULT 0,
	tag TEXT,
	os_is_active INTEGER DEFAULT 0,
	UNIQUE (original_iid, owner_iid, os_id, detail_name, detail_value, generation),
  FOREIGN KEY(original_iid) REFERENCES index_item_t(iid) ON DELETE CASCADE,
  FOREIGN KEY(owner_iid) REFERENCES index_item_t(iid) ON DELETE CASCADE,
  FOREIGN KEY(os_id) REFERENCES active_operating_systems_t(_id)
);
