MODEL (
  name staging.replacements,
  kind INCREMENTAL_BY_TIME_RANGE (
    time_column ingest_date
  ),
  start '2026-01-01',
  cron '@daily',
  grain (id, from_purl, ingest_date),
  audits (
    not_null(columns := (id, from_purl, axis, effort, ingest_date)),
    unique_combination_of_columns(columns := (id, from_purl, ingest_date))
  )
);

SELECT
  id::TEXT                AS id,
  from_purl::TEXT         AS from_purl,
  to_purls::TEXT[]        AS to_purls,
  axis::TEXT              AS axis,
  effort::TEXT            AS effort,
  evidence_json::TEXT     AS evidence_json,
  ingest_date::DATE       AS ingest_date
FROM READ_PARQUET(@VAR('raw_root') || '/replacements/dt=*/*.parquet')
WHERE ingest_date BETWEEN @start_date AND @end_date;
