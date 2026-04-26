#!/usr/bin/env python3
"""
oso_bigquery_dependents.py — Fetch top npm dependents via OSO BigQuery.

This script is the proof-of-concept for replacing biibaa's ecosyste.ms
fan-out adapter with OSO BigQuery. It maps directly onto the biibaa domain:

  Input:  npm package name  (e.g. "lodash")
  Output: list of GitHub repos that depend on that package,
          enriched with star count, days-since-last-push, and repo URL —
          ready to write into biibaa's `dependents` table.

The SQL demonstrates what `src/biibaa/adapters/oso_dependents.py` would
execute once integrated into the pipeline.

Prerequisites
-------------
1. Subscribe to the OSO production dataset on BigQuery:
   https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/87806073973/locations/us/dataExchanges/open_source_observer_190181416ae/listings/oso_data_pipeline_190187c6517

2. Install dependencies:
   pip install google-cloud-bigquery pandas pyarrow

3. Authenticate:
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   # or: gcloud auth application-default login

4. Set your GCP project ID:
   export OSO_BQ_PROJECT=my-gcp-project

Usage
-----
   python scripts/oso_bigquery_dependents.py lodash
   python scripts/oso_bigquery_dependents.py chalk --limit 50
   python scripts/oso_bigquery_dependents.py debug --dry-run
"""

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 20
DEFAULT_MIN_STARS = 0
# Repos with no push in this many days are excluded (biibaa §6.4 disqualifier)
DEFAULT_MAX_DAYS_SINCE_PUSH = 730  # 2 years


# ---------------------------------------------------------------------------
# SQL template
# ---------------------------------------------------------------------------
# The query joins two OSO mart tables:
#
#   oso_production.sboms_v0
#     — reverse-dependency table: (dependent_repo → package) pairs
#     — source: OSO ingests SBOM files from GitHub repos tracked in oss-directory
#               and deps.dev PackageVersionToProject data
#     — columns used: dependent_artifact_id, dependent_artifact_namespace,
#                     dependent_artifact_name, package_artifact_source,
#                     package_artifact_name
#
#   oso_production.repositories_v0
#     — GitHub repo metadata: stars, last push, fork flag, language, licence
#     — columns used: artifact_id (join key), star_count, updated_at, is_fork
#
# The result is ordered by star_count DESC so the highest-impact repos appear
# first, matching biibaa's popularity-weighted scoring (§6.1).
def build_sql(gcp_project: str, package_name: str, limit: int, max_days_since_push: int, min_stars: int) -> str:
    return f"""
-- oso_bigquery_dependents: top GitHub repos depending on npm package '{package_name}'
--
-- Tables:
--   {gcp_project}.oso_production.sboms_v0
--     SBOM-derived reverse-dependency map. Each row = (dependent_repo, package).
--     Covers GitHub repos tracked by OSO's oss-directory that have published
--     a machine-readable dependency manifest (package.json / GitHub dep graph).
--
--   {gcp_project}.oso_production.repositories_v0
--     GitHub repo metadata. artifact_id joins to sboms_v0.dependent_artifact_id.
--
SELECT
  s.dependent_artifact_namespace                                    AS org,
  s.dependent_artifact_name                                        AS repo,
  CONCAT(
    'https://github.com/',
    s.dependent_artifact_namespace, '/',
    s.dependent_artifact_name
  )                                                                 AS repo_url,
  -- purl-style identifier, matching biibaa domain model §4.1
  CONCAT(
    'pkg:github/',
    s.dependent_artifact_namespace, '/',
    s.dependent_artifact_name
  )                                                                 AS purl,
  r.star_count,
  r.language,
  r.license_name,
  DATE(r.updated_at)                                               AS last_push_date,
  DATE_DIFF(CURRENT_DATE(), DATE(r.updated_at), DAY)               AS days_since_last_push,
  r.is_fork
FROM `{gcp_project}.oso_production.sboms_v0` AS s
JOIN `{gcp_project}.oso_production.repositories_v0` AS r
  ON s.dependent_artifact_id = r.artifact_id
WHERE
  -- filter to the npm ecosystem
  s.package_artifact_source = 'NPM'
  -- exact package name match (OSO stores names lowercase)
  AND s.package_artifact_name = LOWER(@package_name)
  -- biibaa §6.4: exclude forks (they rarely land PRs upstream)
  AND r.is_fork = FALSE
  -- biibaa §6.4: exclude repos inactive for > 2 years
  AND r.updated_at > TIMESTAMP_SUB(
    CURRENT_TIMESTAMP(), INTERVAL {max_days_since_push} DAY
  )
  -- optional star floor to reduce noise
  AND r.star_count >= {min_stars}
ORDER BY r.star_count DESC
LIMIT {limit}
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch top npm dependents via OSO BigQuery (biibaa fan-out replacement)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("package", help="npm package name, e.g. lodash")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="maximum number of dependent repos to return",
    )
    parser.add_argument(
        "--min-stars",
        type=int,
        default=DEFAULT_MIN_STARS,
        dest="min_stars",
        help="minimum star count for a dependent repo",
    )
    parser.add_argument(
        "--max-days-since-push",
        type=int,
        default=DEFAULT_MAX_DAYS_SINCE_PUSH,
        dest="max_days_since_push",
        help="exclude repos with no commit in this many days",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the SQL without executing it",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    gcp_project = os.environ.get("OSO_BQ_PROJECT", "")
    if not gcp_project and not args.dry_run:
        print("ERROR: set OSO_BQ_PROJECT env var to your GCP project ID", file=sys.stderr)
        sys.exit(1)

    sql = build_sql(
        gcp_project=gcp_project or "<YOUR_GCP_PROJECT>",
        package_name=args.package,
        limit=args.limit,
        max_days_since_push=args.max_days_since_push,
        min_stars=args.min_stars,
    )

    if args.dry_run:
        print("=== DRY RUN — SQL that would be executed ===")
        print(sql)
        return

    try:
        from google.cloud import bigquery
    except ImportError:
        print(
            "ERROR: google-cloud-bigquery not installed.\n"
            "Run: pip install google-cloud-bigquery pandas pyarrow",
            file=sys.stderr,
        )
        sys.exit(1)

    client = bigquery.Client(project=gcp_project)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("package_name", "STRING", args.package.lower()),
        ]
    )

    print(f"Fetching dependents of npm:{args.package} from OSO BigQuery...")
    print(f"  project={gcp_project}, limit={args.limit}, min_stars={args.min_stars}")
    print()

    query_job = client.query(sql, job_config=job_config)
    rows = list(query_job.result())

    if not rows:
        print(
            f"No dependents found for '{args.package}' in OSO's sboms_v0.\n"
            "This means no repos in OSO's oss-directory have published a SBOM\n"
            "that references this package, or the package name is misspelled."
        )
        return

    # Print results in a format that mirrors biibaa's `dependents` table schema:
    #   dependents(parent_purl, child_purl, rank)
    print(f"{'rank':<5} {'purl':<50} {'stars':>6}  {'days_since_push':>15}  repo_url")
    print("-" * 110)
    for i, row in enumerate(rows, start=1):
        print(
            f"{i:<5} {row.purl:<50} {row.star_count:>6}  "
            f"{row.days_since_last_push:>15}  {row.repo_url}"
        )

    print(f"\nTotal dependents returned: {len(rows)}")
    print(
        "\nNote: results cover only repos tracked by OSO's oss-directory + SBOM data.\n"
        "For full npm dependent coverage, add a deps.dev fallback:\n"
        "  SELECT Name, Version FROM bigquery-public-data.deps_dev_v1.DependentsLatest\n"
        "  WHERE System='NPM' AND Dependency.Name=@package_name"
    )


if __name__ == "__main__":
    main()
