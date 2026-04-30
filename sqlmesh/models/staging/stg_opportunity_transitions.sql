MODEL (
  name staging.opportunity_transitions,
  kind INCREMENTAL_BY_TIME_RANGE (
    time_column ingest_date
  ),
  start '2026-01-01',
  cron '@daily',
  grain (dedupe_key, transitioned_at, ingest_date),
  audits (
    not_null(columns := (dedupe_key, to_state, transitioned_at, ingest_date)),
    valid_to_state
  )
);

SELECT
  dedupe_key::TEXT          AS dedupe_key,
  to_state::TEXT            AS to_state,
  transitioned_at::TIMESTAMP AS transitioned_at,
  actor::TEXT               AS actor,
  reason::TEXT              AS reason,
  ingest_date::DATE         AS ingest_date
FROM READ_PARQUET(@VAR('raw_root') || '/opportunity_transitions/dt=*/*.parquet')
WHERE ingest_date BETWEEN @start_date AND @end_date;
