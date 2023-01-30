-- noinspection SqlNoDataSourceInspectionForFile

DROP TABLE IF EXISTS "sizes_Mac_tt";
CREATE TEMP TABLE sizes_Mac_tt
(
    _id INTEGER PRIMARY KEY,
    iid TEXT UNIQUE,
    size INTEGER DEFAULT 0
);

INSERT INTO sizes_Mac_tt(iid, size)
SELECT sizes_view.iid, SUM(sizes_view.size)
FROM sizes_view
WHERE sizes_view.OS BETWEEN 0 AND 3
GROUP BY sizes_view.iid
ORDER BY iid;

//---

DROP TABLE IF EXISTS "sizes_Win_tt";
CREATE TEMP TABLE sizes_Win_tt
(
    _id INTEGER PRIMARY KEY,
    iid TEXT UNIQUE,
    size INTEGER DEFAULT 0
);

INSERT INTO sizes_Win_tt(iid, size)
SELECT sizes_view.iid, SUM(sizes_view.size)
FROM sizes_view
WHERE sizes_view.OS == 0 OR (sizes_view.OS BETWEEN 4 AND 6)
GROUP BY sizes_view.iid
ORDER BY iid;

//---

DROP TABLE IF EXISTS "sizes_Linux_tt";
CREATE TEMP TABLE sizes_Linux_tt
(
    _id INTEGER PRIMARY KEY,
    iid TEXT UNIQUE,
    size INTEGER DEFAULT 0
);

INSERT INTO sizes_Linux_tt(iid, size)
SELECT sizes_view.iid, SUM(sizes_view.size)
FROM sizes_view
WHERE sizes_view.OS == 0 OR sizes_view.OS == 7
GROUP BY sizes_view.iid
ORDER BY iid;
