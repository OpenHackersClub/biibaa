#!/usr/bin/env python3
"""
oso_bigquery_probe.py — Probe the OSO BigQuery dataset.

Queries `oso_production.sboms_v0` joined to `repositories_v0` for a sample
of high-star repos that depend on a curated set of npm packages. Demonstrates
the fan-out replacement for ecosyste.ms.

Prerequisites
-------------
1. Subscribe to the OSO production dataset on BigQuery:
   https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/87806073973/locations/us/dataExchanges/open_source_observer_190181416ae/listings/oso_data_pipeline_190187c6517
   Create the linked dataset as `oso_production` in your GCP project.

2. Install dependencies:
   pip install google-cloud-bigquery pandas pyarrow

3. Authenticate (choose one):
   a) Service account:
      export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   b) Application Default Credentials (interactive):
      gcloud auth application-default login

4. Set your GCP project ID:
   export OSO_BQ_PROJECT=my-gcp-project

Usage
-----
   python scripts/oso_bigquery_probe.py
"""

import os
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GCP_PROJECT = os.environ.get("OSO_BQ_PROJECT", "")
if not GCP_PROJECT:
    print("ERROR: set OSO_BQ_PROJECT env var to your GCP project ID", file=sys.stderr)
    sys.exit(1)

# Sample packages to probe — these are known to 500 on ecosyste.ms
PROBE_PACKAGES = ["lodash", "chalk", "debug", "axios", "moment"]

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------
# This query:
#   1. Looks up all GitHub repos in OSO's sboms_v0 that depend on the probed
#      npm packages.
#   2. Joins repositories_v0 to get star count, last-push date, fork flag.
#   3. Filters to repos active in the last 2 years and not forks.
#   4. Returns the top 5 results per package by star count.
#
# Table identifiers follow the pattern:
#   `<YOUR_GCP_PROJECT>.oso_production.<table_name>`
SQL = f"""
WITH dependents AS (
  SELECT
    s.package_artifact_name                                         AS npm_package,
    s.dependent_artifact_namespace                                  AS gh_org,
    s.dependent_artifact_name                                       AS gh_repo,
    CONCAT('https://github.com/',
           s.dependent_artifact_namespace, '/',
           s.dependent_artifact_name)                               AS repo_url,
    r.star_count,
    r.updated_at,
    DATE_DIFF(CURRENT_DATE(), DATE(r.updated_at), DAY)              AS days_since_last_push,
    r.is_fork,
    ROW_NUMBER() OVER (
      PARTITION BY s.package_artifact_name
      ORDER BY r.star_count DESC
    )                                                               AS rank_within_package
  FROM `{GCP_PROJECT}.oso_production.sboms_v0` AS s
  JOIN `{GCP_PROJECT}.oso_production.repositories_v0` AS r
    ON s.dependent_artifact_id = r.artifact_id
  WHERE
    s.package_artifact_source = 'NPM'
    AND s.package_artifact_name IN UNNEST(@packages)
    AND r.is_fork = FALSE
    AND r.updated_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 730 DAY)
)
SELECT
  npm_package,
  gh_org,
  gh_repo,
  repo_url,
  star_count,
  days_since_last_push
FROM dependents
WHERE rank_within_package <= 5
ORDER BY npm_package, rank_within_package
"""

# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        from google.cloud import bigquery
    except ImportError:
        print(
            "ERROR: google-cloud-bigquery not installed.\n"
            "Run: pip install google-cloud-bigquery pandas pyarrow",
            file=sys.stderr,
        )
        sys.exit(1)

    client = bigquery.Client(project=GCP_PROJECT)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("packages", "STRING", PROBE_PACKAGES),
        ]
    )

    print(f"Running probe against project '{GCP_PROJECT}'...")
    print(f"Packages: {PROBE_PACKAGES}\n")
    print("SQL (abbreviated):")
    print("  SELECT npm_package, gh_org, gh_repo, star_count, days_since_last_push")
    print("  FROM oso_production.sboms_v0 JOIN oso_production.repositories_v0 ...")
    print()

    query_job = client.query(SQL, job_config=job_config)
    rows = list(query_job.result())

    if not rows:
        print("No results returned. Check that sboms_v0 and repositories_v0 exist in")
        print(f"your linked dataset '{GCP_PROJECT}.oso_production'.")
        return

    # Print results grouped by package
    current_pkg = None
    for row in rows:
        if row.npm_package != current_pkg:
            current_pkg = row.npm_package
            print(f"--- npm: {current_pkg} ---")
        print(
            f"  {row.gh_org}/{row.gh_repo}"
            f"  stars={row.star_count}"
            f"  days_since_push={row.days_since_last_push}"
            f"  {row.repo_url}"
        )
    print(f"\nTotal rows: {len(rows)}")


if __name__ == "__main__":
    main()
