# OSO BigQuery Integration Scoping

**Status**: Draft / Pre-implementation  
**Date**: 2026-04-26  
**Addresses**: ecosyste.ms 500-error gap on high-popularity npm packages

---

## Background

biibaa's current fan-out step enumerates top dependents of a flagged npm package via
ecosyste.ms, which reliably 500s on the most popular packages (debug, axios, moment,
lodash, chalk, fs-extra, etc.). These are exactly the high-signal cases: packages with
millions of weekly downloads have the largest blast radius when vulnerabilities are
unpatched. This doc scopes a replacement using the
[OSO (Open Source Observer)](https://www.opensource.observer/) BigQuery dataset.

---

## OSO BigQuery Access Model

OSO publishes its production pipeline output through BigQuery Analytics Hub as a
**linked dataset** — you subscribe once through the GCP console and the data stays
live in your own GCP project namespace. The subscription is **free to access**; you
pay only standard BigQuery on-demand query costs against bytes scanned (first 1 TB/mo
is free under GCP's free tier).

Access path:

1. Sign up for GCP at https://cloud.google.com/ (free tier is sufficient for biibaa's
   query volume).
2. Subscribe to the OSO production dataset via the Analytics Hub listing:
   https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/87806073973/locations/us/dataExchanges/open_source_observer_190181416ae/listings/oso_data_pipeline_190187c6517
3. Name the linked dataset `oso_production` inside your GCP project (call it
   `<YOUR_GCP_PROJECT>`).
4. All tables are then addressable as `` `<YOUR_GCP_PROJECT>.oso_production.<table>` ``.

**License**: CC BY-SA 4.0.  
**Auth for Python**: service-account JSON key (or Application Default Credentials via
`gcloud auth application-default login`). The `google-cloud-bigquery` PyPI package is
the standard client. No custom token exchange — standard GCP IAM.

Install:

```sh
pip install google-cloud-bigquery pandas pyarrow
```

Set credentials:

```sh
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
# or use ADC:
gcloud auth application-default login
```

---

## Relevant OSO Tables

### 1. `sboms_v0` — Dependents Fan-Out (replaces ecosyste.ms)

**Full identifier**: `` `<YOUR_GCP_PROJECT>.oso_production.sboms_v0` ``  
**biibaa concern**: dependents fan-out (§5 pipeline, "Fan-out" step; §8.1 `dependents` table)

This is the most valuable table for biibaa. OSO ingests Software Bill of Materials
(SBOM) files from GitHub repos tracked in `oss-directory` and joins them against the
`deps.dev` package graph. The result is a flat reverse-dependency table: for each
`(dependent_repo, package)` pair, one row.

| Column | Type | Notes |
|---|---|---|
| `dependent_artifact_id` | STRING | OSO-internal hash ID for the dependent repo |
| `dependent_artifact_source` | STRING | Always `"GITHUB"` for npm-tracked repos |
| `dependent_artifact_namespace` | STRING | GitHub org (e.g. `"facebook"`) |
| `dependent_artifact_name` | STRING | GitHub repo name (e.g. `"react"`) |
| `package_artifact_id` | STRING | OSO-internal hash ID for the package |
| `package_artifact_source` | STRING | e.g. `"NPM"` |
| `package_artifact_namespace` | STRING | npm scope, empty for unscoped packages |
| `package_artifact_name` | STRING | npm package name (e.g. `"lodash"`) |

The underlying lineage is:

```
stg_deps_dev__packages   (from bigquery-public-data.deps_dev_v1.PackageVersionToProject)
    → int_packages_from_deps_dev
    → int_packages__current_maintainer_only
stg_ossd__current_sbom   (SBOM files from GitHub repos in oss-directory)
    → int_sbom_from_ossd
    → int_sbom__latest_snapshot
→ int_sbom_to_packages
→ sboms_v0
```

**Scope caveat**: `sboms_v0` only covers repos that are (a) in OSO's `oss-directory`
and (b) have published a machine-readable SBOM (GitHub's dependency graph / a committed
`package.json`). This is not all of npm. However, it covers the curated high-quality
OSS universe that biibaa most wants to target, and it does not 500 on popular packages.

**Representative query** — top 20 GitHub repos depending on `lodash`:

```sql
SELECT
  dependent_artifact_namespace,
  dependent_artifact_name,
  CONCAT('https://github.com/', dependent_artifact_namespace, '/', dependent_artifact_name)
    AS repo_url
FROM `<YOUR_GCP_PROJECT>.oso_production.sboms_v0`
WHERE
  package_artifact_source = 'NPM'
  AND package_artifact_name = 'lodash'
LIMIT 20
```

---

### 2. `repositories_v0` — Repo Activity Signals (confidence scoring)

**Full identifier**: `` `<YOUR_GCP_PROJECT>.oso_production.repositories_v0` ``  
**biibaa concern**: scoring disqualifiers (§6.4) — archived flag, last push date,
star count; supplements GitHub REST calls with pre-fetched bulk data

| Column | Type | Notes |
|---|---|---|
| `artifact_id` | STRING | OSO hash ID, joinable to `sboms_v0.dependent_artifact_id` |
| `artifact_source` | STRING | `"GITHUB"` |
| `artifact_namespace` | STRING | GitHub org |
| `artifact_name` | STRING | GitHub repo name |
| `artifact_url` | STRING | Full HTTPS URL |
| `is_fork` | BOOLEAN | Fork flag |
| `star_count` | INT64 | Star count |
| `watcher_count` | INT64 | Watcher count |
| `fork_count` | INT64 | Fork count |
| `license_name` | STRING | License (e.g. `"MIT"`) |
| `language` | STRING | Primary language |
| `created_at` | TIMESTAMP | Repo creation time |
| `updated_at` | TIMESTAMP | Last push / update time |

Join pattern to enrich dependents with repo signals:

```sql
SELECT
  s.dependent_artifact_namespace AS org,
  s.dependent_artifact_name     AS repo,
  r.star_count,
  r.updated_at,
  r.is_fork,
  DATE_DIFF(CURRENT_DATE(), DATE(r.updated_at), DAY) AS days_since_push
FROM `<YOUR_GCP_PROJECT>.oso_production.sboms_v0` AS s
JOIN `<YOUR_GCP_PROJECT>.oso_production.repositories_v0` AS r
  ON s.dependent_artifact_id = r.artifact_id
WHERE
  s.package_artifact_source = 'NPM'
  AND s.package_artifact_name = 'lodash'
  AND r.updated_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)  -- active in 2yr
  AND r.is_fork = FALSE
ORDER BY r.star_count DESC
LIMIT 50
```

This single query replaces: (1) ecosyste.ms fan-out call, (2) GitHub REST calls for
`archived` / `pushed_at` / `stargazers_count` per repo.

---

### 3. `projects_v1` + `artifacts_by_project_v1` — Candidate Seeding

**Full identifiers**:
- `` `<YOUR_GCP_PROJECT>.oso_production.projects_v1` ``
- `` `<YOUR_GCP_PROJECT>.oso_production.artifacts_by_project_v1` ``

**biibaa concern**: SPEC §11 open question #1 — "seed with watchlist (top 1k npm by
dependents) and expand via fan-out". OSO's `oss-directory` tracks ~7 000 curated OSS
projects. These are the repos with the highest community attention and the most likely
targets for biibaa briefs.

| Table | Key columns |
|---|---|
| `projects_v1` | `project_id`, `project_source`, `project_name`, `display_name`, `description` |
| `artifacts_by_project_v1` | `project_id`, `artifact_id`, `artifact_source`, `artifact_namespace`, `artifact_name` |

Query to get all npm packages owned by OSO-tracked projects:

```sql
SELECT
  p.project_name,
  p.display_name,
  a.artifact_namespace,
  a.artifact_name AS npm_package
FROM `<YOUR_GCP_PROJECT>.oso_production.projects_v1` AS p
JOIN `<YOUR_GCP_PROJECT>.oso_production.artifacts_by_project_v1` AS a
  ON p.project_id = a.project_id
WHERE a.artifact_source = 'NPM'
ORDER BY p.project_name
```

This yields a ready-made seed list of npm packages whose owning repos are already
tracked by OSO — ideal for the first pass of the biibaa pipeline.

---

### 4. `key_metrics_by_project_v0` — Activity Metrics (confidence scoring)

**Full identifier**: `` `<YOUR_GCP_PROJECT>.oso_production.key_metrics_by_project_v0` ``  
**biibaa concern**: scoring — active contributors, recent commit count; supplement to
`repositories_v0.updated_at`

| Column | Type | Notes |
|---|---|---|
| `metric_id` | STRING | Join key to `metrics_v0` for human-readable name |
| `project_id` | STRING | Join key to `projects_v1` |
| `sample_date` | DATE | Date of measurement (most-recent snapshot) |
| `amount` | FLOAT64 | Metric value |

Relevant metric names (from `metrics_v0.metric_name`): `GITHUB_contributors_6_months`,
`GITHUB_commits_6_months`, `GITHUB_issues_closed_6_months`.

Query example:

```sql
SELECT
  p.project_name,
  m.metric_name,
  km.sample_date,
  km.amount
FROM `<YOUR_GCP_PROJECT>.oso_production.key_metrics_by_project_v0` AS km
JOIN `<YOUR_GCP_PROJECT>.oso_production.metrics_v0` AS m
  ON km.metric_id = m.metric_id
JOIN `<YOUR_GCP_PROJECT>.oso_production.projects_v1` AS p
  ON km.project_id = p.project_id
WHERE
  m.metric_name IN ('GITHUB_contributors_6_months', 'GITHUB_commits_6_months')
  AND p.project_name = 'lodash'
ORDER BY km.sample_date DESC
LIMIT 10
```

---

## What OSO BigQuery Does Not Cover

- **Arbitrary npm packages not in oss-directory**: `sboms_v0` only has data for the
  ~7 000 curated OSS projects. For the long tail of npm packages (the "every dependent
  of `debug`" case), OSO does not help — the direct `deps.dev` BigQuery public table
  (`bigquery-public-data.deps_dev_v1.DependentsLatest`) is the right fallback (see
  §Integration Plan below).
- **Download counts**: OSO does not replicate npm download statistics. Keep the existing
  `npm_downloads.py` adapter.
- **OSV/CVE data**: Out of scope for OSO; biibaa owns this via OSV.dev.

---

## Integration Plan

Priority order (highest value / lowest friction first):

### Phase 1 — Replace ecosyste.ms with OSO for curated repos (immediate)

Wire `sboms_v0` + `repositories_v0` into a new adapter
`src/biibaa/adapters/oso_dependents.py`. For each flagged npm package:

1. Query `sboms_v0` for dependent repos (filtered to `package_artifact_source = 'NPM'`).
2. LEFT JOIN `repositories_v0` to get `star_count`, `updated_at`, `is_fork`.
3. Apply biibaa disqualifiers (archived, no push in 24 months, forks) in the same SQL.
4. Return a list of `(org, repo, repo_url, stars, days_since_push)` tuples.

This single BigQuery query replaces one ecosyste.ms HTTP call + N GitHub REST calls.

### Phase 2 — Seed from OSO project list (next sprint)

Replace the current "seed with top-N npm packages" approach with a query against
`projects_v1` + `artifacts_by_project_v1` to get a curated list of npm packages owned
by OSO-tracked projects. This is a higher-quality seed than "top 1k by downloads"
because it starts with projects the community has already decided are worth tracking.

### Phase 3 — Long-tail fallback with deps.dev BigQuery (later)

For packages not covered by `sboms_v0` (i.e. packages whose consumers are not in
oss-directory), add a fallback that queries the public
`bigquery-public-data.deps_dev_v1.DependentsLatest` table directly. This is a large
public table (no subscription required, requester-pays on bytes scanned) that maps
every npm package to its dependents by version range. It completes the coverage that
OSO's curated subset leaves out.

```sql
-- deps.dev: top dependents of 'debug' on npm (no OSO subscription needed)
SELECT
  Name AS dependent_package,
  Version AS dependent_version,
  VersionInfo.Ordinal AS version_ordinal
FROM `bigquery-public-data.deps_dev_v1.DependentsLatest`
WHERE
  System = 'NPM'
  AND Dependency.Name = 'debug'
ORDER BY VersionInfo.Ordinal DESC
LIMIT 100
```

### Phase 4 — Activity metrics for confidence scoring (nice-to-have)

Add `key_metrics_by_project_v0` to the biibaa scoring step to enrich the `impact`
calculation with contributor and commit counts over the last 6 months. Higher recent
activity → lower effort to land a PR → higher `effort` score.

---

## Implementation Notes

- All queries should parameterize `<YOUR_GCP_PROJECT>` via an env var
  `OSO_BQ_PROJECT` (set in `.env` / `biibaa` config).
- Cache BigQuery results locally as Parquet under `data/raw/oso/<date>/` following
  the existing idempotency convention.
- Prefer the mart tables (`_v0`, `_v1`) over intermediate models (`int_*`) for
  stability; OSO versions mart models and flags breaking changes.
- `sboms_v0` is marked `kind FULL` and refreshed weekly — match biibaa's weekly cadence.
