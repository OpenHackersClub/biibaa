MODEL (
  name staging.projects,
  kind INCREMENTAL_BY_TIME_RANGE (
    time_column ingest_date
  ),
  start '2026-01-01',
  cron '@daily',
  grain (purl, ingest_date),
  audits (
    not_null(columns := (purl, ecosystem, name, ingest_date))
  )
);

SELECT
  purl::TEXT                  AS purl,
  ecosystem::TEXT             AS ecosystem,
  name::TEXT                  AS name,
  repo_url::TEXT              AS repo_url,
  homepage::TEXT              AS homepage,
  stars::BIGINT               AS stars,
  downloads_weekly::BIGINT    AS downloads_weekly,
  dependents::BIGINT          AS dependents,
  last_release_at::TIMESTAMP  AS last_release_at,
  last_commit_at::TIMESTAMP   AS last_commit_at,
  archived::BOOLEAN           AS archived,
  has_benchmarks::BOOLEAN     AS has_benchmarks,
  ingest_date::DATE           AS ingest_date
FROM READ_PARQUET(@VAR('raw_root') || '/projects/dt=*/*.parquet')
WHERE ingest_date BETWEEN @start_date AND @end_date;
