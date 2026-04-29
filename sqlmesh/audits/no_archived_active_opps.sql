AUDIT (
  name no_archived_active_opps
);

-- Returns rows iff an opportunity references a project whose *latest* staging
-- record is archived. The mart's WHERE clause already filters these out — this
-- audit is the contract: if anyone refactors the join, the filter survives or
-- the plan fails.
WITH latest_projects AS (
  SELECT
    purl,
    archived,
    ROW_NUMBER() OVER (PARTITION BY purl ORDER BY ingest_date DESC) AS rn
  FROM staging.projects
)
SELECT o.id
FROM @this_model AS o
JOIN latest_projects AS p
  ON p.purl = o.project_purl
 AND p.rn = 1
WHERE p.archived = TRUE;
