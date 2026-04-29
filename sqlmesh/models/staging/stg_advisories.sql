MODEL (
  name staging.advisories,
  kind INCREMENTAL_BY_TIME_RANGE (
    time_column ingest_date
  ),
  start '2026-01-01',
  cron '@daily',
  grain (id, ingest_date),
  audits (
    not_null(columns := (id, project_purl, ingest_date)),
    unique_values(columns := (id, ingest_date))
  )
);

SELECT
  id::TEXT                         AS id,
  project_purl::TEXT               AS project_purl,
  severity::TEXT                   AS severity,
  cvss::DOUBLE                     AS cvss,
  summary::TEXT                    AS summary,
  affected_versions::TEXT          AS affected_versions,
  fixed_versions::TEXT[]           AS fixed_versions,
  refs::TEXT[]                     AS refs,
  published_at::TIMESTAMP          AS published_at,
  repo_url::TEXT                   AS repo_url,
  ingest_date::DATE                AS ingest_date
FROM READ_PARQUET(@VAR('raw_root') || '/advisories/dt=*/*.parquet')
WHERE ingest_date BETWEEN @start_date AND @end_date;
