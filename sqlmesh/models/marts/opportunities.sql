MODEL (
  name marts.opportunities,
  kind FULL,
  cron '@daily',
  grain (id),
  audits (
    not_null(columns := (id, kind, project_purl, score)),
    unique_values(columns := (id)),
    score_in_range
  )
);

WITH latest_advisories AS (
  SELECT
    id,
    project_purl,
    severity,
    cvss,
    summary,
    fixed_versions,
    published_at,
    ROW_NUMBER() OVER (PARTITION BY id ORDER BY ingest_date DESC) AS rn
  FROM staging.advisories
),
latest_projects AS (
  SELECT
    purl,
    ecosystem,
    name,
    stars,
    downloads_weekly,
    dependents,
    archived,
    ROW_NUMBER() OVER (PARTITION BY purl ORDER BY ingest_date DESC) AS rn
  FROM staging.projects
)
SELECT
  a.id                                          AS id,
  'vulnerability-fix'::TEXT                     AS kind,
  a.project_purl                                AS project_purl,
  p.ecosystem                                   AS ecosystem,
  p.name                                        AS project_name,
  a.severity                                    AS advisory_severity,
  a.cvss                                        AS advisory_cvss,
  a.summary                                     AS advisory_summary,
  a.fixed_versions                              AS advisory_fixed_versions,
  p.stars                                       AS project_stars,
  p.downloads_weekly                            AS project_downloads_weekly,
  p.dependents                                  AS project_dependents,
  @score_opportunity(a.cvss, p.dependents)      AS score,
  CURRENT_TIMESTAMP                             AS computed_at
FROM latest_advisories a
LEFT JOIN latest_projects p
  ON p.purl = a.project_purl AND p.rn = 1
WHERE a.rn = 1
  AND COALESCE(p.archived, FALSE) = FALSE;
