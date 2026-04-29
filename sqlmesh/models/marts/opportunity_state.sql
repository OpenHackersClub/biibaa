MODEL (
  name marts.opportunity_state,
  kind FULL,
  cron '@daily',
  grain dedupe_key,
  audits (
    not_null(columns := (dedupe_key, kind, project_purl, first_seen_at, last_seen_at, state)),
    unique_values(columns := (dedupe_key))
  )
);

-- Cross-run lifecycle for each opportunity. ``first_seen_at`` and
-- ``last_seen_at`` are derived by aggregating over historical staging
-- partitions: the staging tables are INCREMENTAL_BY_TIME_RANGE on
-- ``ingest_date``, so MIN/MAX naturally span every run. ``state`` is a
-- placeholder column for the lifecycle state machine
-- (new | acknowledged | resolved | rejected | duplicate); v0 leaves
-- everything as ``new`` until manual transitions are wired up.
WITH advisory_lifecycle AS (
  SELECT
    project_purl,
    id,
    MIN(ingest_date) AS first_seen,
    MAX(ingest_date) AS last_seen,
    COUNT(DISTINCT ingest_date) AS partition_count
  FROM staging.advisories
  GROUP BY project_purl, id
)
SELECT
  o.dedupe_key                                  AS dedupe_key,
  o.kind                                        AS kind,
  o.project_purl                                AS project_purl,
  CAST(alh.first_seen AS TIMESTAMP)             AS first_seen_at,
  CAST(alh.last_seen AS TIMESTAMP)              AS last_seen_at,
  alh.partition_count                           AS partition_count,
  'new'::TEXT                                   AS state,
  CURRENT_TIMESTAMP                             AS computed_at
FROM marts.opportunities o
LEFT JOIN advisory_lifecycle alh
  ON alh.project_purl = o.project_purl
 AND alh.id = o.id;
