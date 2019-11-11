-- noinspection SqlResolveForFile

-- iid, index_version, generation
CREATE VIEW IF NOT EXISTS "require_items_without_require_version_view" AS
SELECT main_details_t.owner_iid AS iid,
    main_details_t.detail_value AS index_version,
    min(main_details_t.generation) AS generation
FROM index_item_detail_t AS main_details_t
    JOIN index_item_t AS main_item_t
    ON main_item_t.iid=main_details_t.owner_iid
    AND main_item_t.from_require=1
    LEFT JOIN index_item_detail_t AS no_require_version_t
    ON no_require_version_t.detail_name='require_version'
    AND main_details_t.owner_iid=no_require_version_t.owner_iid
WHERE main_details_t.detail_name='version'
    AND no_require_version_t.detail_value ISNULL
    AND main_details_t.os_is_active=1
GROUP BY (main_details_t.owner_iid);

-- view of items from require.yaml that do not have a require_guid field
CREATE VIEW IF NOT EXISTS "require_items_without_require_guid_view" AS
SELECT
    main_details_t.owner_iid       AS iid,
    main_details_t.detail_value    AS index_guid,
    min(main_details_t.generation) AS generation
FROM index_item_detail_t AS main_details_t
    JOIN index_item_t AS main_item_t
        ON main_item_t.iid = main_details_t.owner_iid
           AND main_item_t.from_require = 1
    LEFT JOIN index_item_detail_t AS no_guid_version_t
        ON no_guid_version_t.detail_name = 'require_guid'
        AND main_details_t.owner_iid=no_guid_version_t.owner_iid
WHERE main_details_t.detail_name='guid'
AND no_guid_version_t.detail_value ISNULL
AND main_details_t.os_is_active=1
GROUP BY (main_details_t.owner_iid);

-- the final report-versions view
CREATE VIEW IF NOT EXISTS "report_versions_view" AS
    SELECT
          coalesce(remote.owner_iid, "_") AS owner_iid,
          coalesce(item_guid.detail_value, "_") AS guid,
          coalesce(item_name.detail_value, "_") AS name,
          coalesce(require_version.detail_value, "_") AS 'require_version',
          coalesce(remote.detail_value, "_") AS 'remote_version',
          coalesce(secondary_guid.detail_value, item_guid.detail_value, "_") AS 'secondary_guid',
          min(remote.generation) AS generation
    FROM index_item_detail_t AS remote

    LEFT  JOIN index_item_detail_t as require_version
        ON  require_version.detail_name = 'require_version'
        AND require_version.owner_iid=remote.owner_iid
        AND require_version.os_is_active=1
    LEFT JOIN index_item_detail_t as item_guid
        ON  item_guid.detail_name = 'guid'
        AND item_guid.owner_iid=remote.owner_iid
        AND item_guid.os_is_active=1
    LEFT JOIN index_item_detail_t as item_name
        ON  item_name.detail_name = 'name'
        AND item_name.owner_iid=remote.owner_iid
        AND item_name.os_is_active=1
    LEFT JOIN index_item_detail_t as secondary_guid
        ON  secondary_guid.detail_name = 'guid'
        AND secondary_guid.owner_iid=remote.owner_iid
        AND secondary_guid._id > item_guid._id
        AND secondary_guid.os_is_active=1
    WHERE
        remote.detail_name = 'version'
        AND remote.os_is_active=1
    GROUP BY remote.owner_iid;

CREATE VIEW IF NOT EXISTS "iids_to_install_sources_view" AS
SELECT iid_to_svn_item_t.iid, svn_item_t.path
FROM iid_to_svn_item_t, svn_item_t
WHERE
    iid_to_svn_item_t.svn_id=svn_item_t._id;

CREATE VIEW IF NOT EXISTS "versions_view" AS
SELECT version_t.owner_iid AS iid, version_t.detail_value AS version, min(version_t.generation) AS generation
FROM index_item_detail_t AS version_t
WHERE version_t.detail_name='version'
GROUP BY version_t.owner_iid;
