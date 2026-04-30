MODEL (
  name marts.opportunity_state,
  kind FULL,
  cron '@daily',
  grain dedupe_key,
  audits (
    not_null(columns := (dedupe_key, kind, project_purl, first_seen_at, last_seen_at, state)),
    unique_values(columns := (dedupe_key)),
    valid_opportunity_state
  )
);

-- Cross-run lifecycle for each opportunity. ``first_seen_at`` and
-- ``last_seen_at`` are derived by aggregating over historical staging
-- partitions. ``state`` is the latest entry from
-- ``staging.opportunity_transitions`` for the dedupe_key, defaulting to
-- ``'new'`` when no transition has been recorded.
WITH advisory_lifecycle AS (
  SELECT
    project_purl,
    id,
    MIN(ingest_date) AS first_seen,
    MAX(ingest_date) AS last_seen,
    COUNT(DISTINCT ingest_date) AS partition_count
  FROM staging.advisories
  GROUP BY project_purl, id
),
latest_transitions AS (
  SELECT
    dedupe_key,
    to_state,
    transitioned_at,
    actor,
    reason,
    ROW_NUMBER() OVER (
      PARTITION BY dedupe_key
      ORDER BY transitioned_at DESC, ingest_date DESC
    ) AS rn
  FROM staging.opportunity_transitions
)
SELECT
  o.dedupe_key                                    AS dedupe_key,
  o.kind                                          AS kind,
  o.project_purl                                  AS project_purl,
  CAST(alh.first_seen AS TIMESTAMP)               AS first_seen_at,
  CAST(alh.last_seen AS TIMESTAMP)                AS last_seen_at,
  alh.partition_count                             AS partition_count,
  COALESCE(lt.to_state, 'new')::TEXT              AS state,
  lt.transitioned_at                              AS state_transitioned_at,
  lt.actor                                        AS state_actor,
  lt.reason                                       AS state_reason,
  CURRENT_TIMESTAMP                               AS computed_at
FROM marts.opportunities o
LEFT JOIN advisory_lifecycle alh
  ON alh.project_purl = o.project_purl
 AND alh.id = o.id
LEFT JOIN latest_transitions lt
  ON lt.dedupe_key = o.dedupe_key
 AND lt.rn = 1;
