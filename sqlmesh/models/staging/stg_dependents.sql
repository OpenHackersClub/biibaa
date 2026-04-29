MODEL (
  name staging.dependents,
  kind INCREMENTAL_BY_TIME_RANGE (
    time_column ingest_date
  ),
  start '2026-01-01',
  cron '@daily',
  grain (parent_purl, dependent_purl, ingest_date),
  audits (
    not_null(columns := (parent_purl, dependent_purl, ingest_date)),
    unique_combination_of_columns(columns := (parent_purl, dependent_purl, ingest_date))
  )
);

SELECT
  parent_purl::TEXT                       AS parent_purl,
  dependent_purl::TEXT                    AS dependent_purl,
  dependent_name::TEXT                    AS dependent_name,
  dependent_repo_url::TEXT                AS dependent_repo_url,
  dependent_lifetime_downloads::BIGINT    AS dependent_lifetime_downloads,
  ingest_date::DATE                       AS ingest_date
FROM READ_PARQUET(@VAR('raw_root') || '/dependents/dt=*/*.parquet')
WHERE ingest_date BETWEEN @start_date AND @end_date;
