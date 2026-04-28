# biibaa — Open Source Improvement Opportunity Tracker

> Data engineering pipeline that surfaces low-effort, high-impact improvements to open source projects across **vulnerabilities**, **dependency weight**, and **performance**, then emits triage briefs.

## 1. Mission

Continuously rank improvement opportunities in open source projects across three axes:

1. **Vulnerability** — known CVEs / advisories with available fixes
2. **Dependency weight** — replaceable bloat (e18e, replacements.fyi)
3. **Performance** — measurable wins from known-faster alternatives

Output: deduplicated, ranked **briefs** (Markdown) — one per project — that humans triage and turn into PRs/issues.

## 2. Non-goals

- Not a vulnerability scanner — we read existing data, don't generate it
- Not an SBOM tool — we may consume SBOMs but don't produce them
- Not auto-PR — humans triage; we just rank and brief
- Not real-time — daily/weekly cadence is fine
- Not multi-user (yet) — local-first single operator

## 3. Data sources

| Source | Purpose | Refresh | Auth | Access |
|---|---|---|---|---|
| **OSV.dev** | vulnerability DB (multi-ecosystem) | daily bulk | none | bulk zip + REST |
| **NVD CVE** | CVSS scores, references | daily incremental | optional API key | REST |
| **GitHub** | repo metadata, security advisories, existing PRs/issues | on-demand | PAT/App | REST + GraphQL |
| **e18e** | curated replacement candidates | weekly | none | GitHub repo pull |
| **replacements.fyi** | per-package replacements with weight savings | weekly | none | site scrape / data export |
| **npmjs.com/browse/depended/`<pkg>`** | top dependents per package — fan-out from a hot package to its consumers | weekly per seed | none | HTML scrape |

### 3.1 Source notes

- **OSV** is the primary advisory source; ecosystem and version-range coverage is broad. Bulk zips at `https://osv-vulnerabilities.storage.googleapis.com/<ecosystem>/all.zip`.
- **NVD** complements OSV with CVSS metadata where OSV's severity is weak. Rate-limited; use API key.
- **GitHub** is our project-context layer: stars, archived state, primary language, existing security advisories, and crucially **whether a PR is already open** for the same finding (dedupe).
- **e18e** is a curated quality signal — small, opinionated, high-trust. Source likely `e18e/community` repo.
- **replacements.fyi** offers structured `from → to` mappings with size/perf evidence; treat as canonical for replacement metadata.
- **npm dependents browse** (`https://www.npmjs.com/browse/depended/<pkg>`) is **fan-out**: given a flagged package (vulnerable, heavy, or replaced), enumerate top dependents to widen the triage set. Also a popularity proxy. HTML-only; respect rate limits, cache aggressively.

### 3.2 Source precedence on conflict

- Vulnerability data: **OSV > GitHub Security Advisories > NVD**
- Replacement data: **e18e > replacements.fyi**
- Popularity: composite (see scoring §6), no single winner

## 4. Domain model

### 4.1 Project (aggregate root)

- `purl` — canonical id, [package URL](https://github.com/package-url/purl-spec) format (e.g. `pkg:npm/express`)
- `ecosystem` — npm | pypi | go | rubygems | crates | maven | …
- `name`, `repoUrl`, `homepage`
- `popularity` — composite signal (stars + downloads + dependents)
- `lastReleaseAt`, `lastCommitAt`
- `archived: boolean`

### 4.2 Advisory (entity, references Project)

- `id` — OSV id (`GHSA-…`, `CVE-…`)
- `severity` — CVSS v3 score + qualitative band
- `affectedVersions`, `fixedVersions` (version-range JSON)
- `summary`, `references[]`

### 4.3 Replacement (entity, references Project)

- `from: purl`
- `to: purl[]` — sometimes multiple candidates
- `axis: bloat | perf | maintenance | security`
- `evidence` — bytes saved, benchmark link, e18e/replacements.fyi citation
- `effort: drop-in | minor-migration | codemod-available | rewrite`

### 4.4 Opportunity (entity)

The unit of work surfaced to humans. One per `(project, axis, finding)`.

- `kind: vulnerability-fix | dep-replacement | perf-replacement`
- `project: Project`
- `payload: Advisory | Replacement`
- `impact: 0..100`
- `effort: 0..100` (high = easy)
- `score: number`
- `dedupeKey` — for upserts across runs
- `state: new | acknowledged | resolved | rejected | duplicate`
- `firstSeenAt`, `lastSeenAt`

### 4.5 Brief (aggregate)

- One per project per run, bundling top N opportunities
- Markdown output: project context, ranked opportunities, suggested PR titles, citations

### 4.6 Domain events

`OpportunityDiscovered`, `OpportunityScored`, `BriefGenerated`

## 5. Pipeline

```
sources → ingest (raw landing) → normalize (canonical model) → score → brief
```

1. **Ingest** — adapter per source pulls raw payloads. Stored as Parquet/JSON under `data/raw/<source>/<yyyy-mm-dd>/`. Idempotent per `(source, date)`.
2. **Normalize** — SQLMesh staging models read raw Parquet via DuckDB's `read_parquet`, decode into typed staging tables; intermediate models apply source precedence (§3.2) and dedupe. Time-partitioned raw inputs map to `INCREMENTAL_BY_TIME_RANGE` models keyed on the ingest date.
3. **Fan-out** — for each flagged package, enumerate top-K dependents via npm browse (and ecosyste.ms when extending) to expand the candidate set.
4. **Score** — apply heuristics (§6). Materialize `opportunities` table.
5. **Brief** — pick top-N projects by aggregate score; render Markdown briefs to `data/briefs/<ecosystem>/<project>/<yyyy-mm-dd>.md`.

Each step is idempotent and replayable from raw.

## 6. Scoring — "low-hanging fruit, high impact"

### 6.1 Impact (0..100)

`impact = popularity_norm × severity_norm`

#### Popularity (0..100)

Two primary signals, log-normalized and blended:

| Signal | Source | Why |
|---|---|---|
| **Weekly downloads** (ecosystem-native) | `api.npmjs.org/downloads/point/last-week/<pkg>` for npm; PyPI BigQuery for Python; equivalents per ecosystem | Behavioral — actual install traffic, the most direct proxy for "how much code in the wild runs this" |
| **GitHub stars** | GitHub repo metadata | Attentional — community signal; cheap; resilient when downloads are gameable or unavailable (e.g. internal forks) |

Optional tiebreakers: dependents count (npm browse / ecosyste.ms), most-recent-release recency.

```
pop = 100 × ( w_d × log10(1 + downloads_weekly) / log10(1 + DOWNLOADS_REF)
            + w_s × log10(1 + stars)            / log10(1 + STARS_REF) )
```

with default weights `w_d = 0.7`, `w_s = 0.3` (downloads dominate because they reflect runtime exposure), and reference caps `DOWNLOADS_REF = 100M/wk`, `STARS_REF = 100k` to flatten the long tail. Clipped to `[0, 100]`.

Per-ecosystem `DOWNLOADS_REF` is calibrated separately — npm and PyPI scales differ by an order of magnitude. Stored in config, not hardcoded.

#### Severity (0..100) by axis

- `vulnerability-fix`: `CVSS / 10 × 100`
- `dep-replacement`: bytes-saved or install-time-saved, normalized to a per-ecosystem reference
- `perf-replacement`: benchmark delta from source, normalized

### 6.2 Effort (0..100, high = easy)

| Effort signal | Score |
|---|---|
| Drop-in API-compatible | 95 |
| Minor migration (rename imports, ESM-only) | 70 |
| Codemod available | 60 |
| Deep rewrite | 20 |
| Replacement target unmaintained / archived | **disqualify** |

### 6.3 Confidence (0..100)

Predicts whether a drive-by PR will land. Driven by the upstream repo's most-recently-merged PR timestamp (GitHub GraphQL `repository.pullRequests(states:MERGED, orderBy:UPDATED_AT)`). Decay: 100 if merged ≤14 days ago, linear to 0 by 365 days. Unknown ⇒ 30 (mild penalty so unreachable repos don't crowd out reachable ones).

### 6.4 Final

`score = 0.6 × impact + 0.25 × effort + 0.15 × confidence`

### 6.5 Disqualifiers

- Project archived or no commit in 24 months → drop unless vuln severity ≥ 9
- Replacement target itself flagged on OSV → drop
- Existing open PR in repo proposing the same fix → de-prioritize, link instead
- Project's own maintainers have explicitly declined the change (label / closed PR with WONTFIX) → drop, remember in `state: rejected`

## 7. Brief format

```md
# <project> — <yyyy-mm-dd> Improvement Brief

**Ecosystem**: npm
**Popularity**: ★ 12,400 · 2.1M downloads/wk · 8,201 dependents
**Score**: 87 (impact 92, effort 75)

## Top opportunities

### 1. [vuln] CVE-2024-XXXX — RCE in transitive `tar` <6.2.1
- **Severity**: 9.8 critical
- **Fix**: bump `tar` to 6.2.1 (drop-in)
- **Evidence**: OSV GHSA-…
- **Suggested PR**: "fix(deps): bump tar to 6.2.1 (CVE-2024-XXXX)"

### 2. [bloat] Replace `moment` with `date-fns`
- **Saves**: ~290 KB minified, no runtime change
- **Evidence**: replacements.fyi · e18e curated
- **Effort**: codemod available
- **Suggested PR**: "perf(deps): replace moment with date-fns"

## Citations
- OSV: …
- replacements.fyi: …
- npm dependents (fan-out): https://www.npmjs.com/browse/depended/tar
```

## 8. Storage (DuckDB, local-first)

```
data/
  raw/                              # immutable Parquet/JSON from each source
    osv/2026-04-26/*.parquet
    nvd/2026-04-26/*.parquet
    github/<owner>/<repo>.json
    e18e/2026-04-26/*.parquet
    replacements-fyi/2026-04-26/*.parquet
    npm-depended/<pkg>/2026-04-26.json
  warehouse.duckdb                  # canonical tables + views
  briefs/<project>/2026-04-26.md
```

### 8.1 Core tables

- `projects (purl PK, ecosystem, name, repo_url, stars, downloads_weekly, dependents, last_release_at, archived)`
- `advisories (id PK, project_purl FK, severity, cvss, summary, fixed_versions JSON, refs JSON)`
- `replacements (id PK, from_purl, to_purl, axis, effort, evidence JSON)`
- `dependents (parent_purl, child_purl, rank)` — from npm browse fan-out
- `opportunities (id PK, project_purl, kind, payload_id, impact, effort, score, dedupe_key, state, first_seen_at, last_seen_at)`
- `briefs (id PK, run_at, project_purl, path, score)`

DuckDB chosen for: zero-ops, columnar joins across millions of `advisories × projects × dependents`, Parquet-native, fast local SQL exploration. Revisit when multi-user is real.

## 9. Architecture (deferred — see scaffold step)

**Stack**: Python 3.12+ for ingest and orchestration; **SQLMesh** (with the DuckDB engine adapter) for transformation, modeling, audits, and incremental scheduling; DuckDB as the warehouse.

Rationale: data engineering work — API ingestion, Parquet/columnar transforms, SQL modeling — is where Python's tooling is strongest. SQLMesh fits this project specifically:

- **Interval-based incrementals** (`INCREMENTAL_BY_TIME_RANGE`) match our `data/raw/<source>/<date>/` layout directly — no hand-rolled `is_incremental()` filters or partition columns.
- **`plan` / `apply` workflow** lets us preview affected rows before materializing scoring-formula changes — important when heuristic weights evolve.
- **Virtual data environments** give free dev/prod isolation against a single DuckDB file via shadow views.
- **Audits** (vs dbt's tests) are first-class blocking checks tied to model materialization.
- **Native Python models** sit inside the DAG — useful if any transform later needs a Python library (e.g. fuzzy package-name matching).

This is a deliberate departure from the TypeScript/Effect-TS preference in `arch-taste.md`: that guidance targets application services. Any future UI/CLI surface for browsing briefs may still be TS.

### 9.1 Layers

| Layer | Tool | Responsibility |
|---|---|---|
| **Ingest** | Python (httpx, pydantic v2) | Pull from sources; land raw Parquet/JSON in `data/raw/<source>/<date>/` |
| **Staging** | SQLMesh `INCREMENTAL_BY_TIME_RANGE` models (`read_parquet`) | Decode raw → typed staging tables; one staging model per source, partitioned by ingest date |
| **Intermediate** | SQLMesh `VIEW` / `INCREMENTAL` models | Source-precedence resolution, joins, dedupe |
| **Marts** | SQLMesh `FULL` or `INCREMENTAL` models | `projects`, `advisories`, `replacements`, `dependents`, `opportunities` |
| **Score** | SQLMesh SQL + macros | Apply popularity + severity + effort heuristics; materialize `opportunities` |
| **Audits** | SQLMesh audits | `not_null`, `unique_values`, `relationships`, custom (e.g. `score_in_range`) |
| **Brief** | Python + Jinja2 | Read `opportunities` from DuckDB; render Markdown to `data/briefs/<ecosystem>/<project>/<date>.md` |
| **CLI** | Python (Typer) | `biibaa ingest <source>`, `biibaa run`, `biibaa brief`, `biibaa show <project>` |

### 9.2 Hexagonal split (Python)

- `domain/` — Pydantic v2 models (`Project`, `Advisory`, `Replacement`, `Opportunity`, `Brief`); pure
- `ports/` — `Protocol` classes (`SourceClient`, `WarehouseWriter`)
- `adapters/` — per-source: `osv.py`, `nvd.py`, `github.py`, `e18e.py`, `replacements_fyi.py`, `npm_dependents.py`, `npm_downloads.py`, `github_stars.py`
- `pipeline/` — ingest orchestration; thin (heavy lifting lives in SQLMesh)
- `briefs/` — Jinja templates + render
- `cli/` — Typer commands

### 9.3 Project layout

```
biibaa/
  pyproject.toml                  # uv-managed
  src/biibaa/
    domain/
    ports/
    adapters/
    pipeline/
    briefs/
    cli/
  sqlmesh/
    config.yaml                   # DuckDB gateway → data/warehouse.duckdb; state in same file
    models/
      staging/
        stg_osv.sql               # INCREMENTAL_BY_TIME_RANGE on @start_ds / @end_ds
        stg_nvd.sql
        stg_github.sql
        stg_e18e.sql
        stg_replacements_fyi.sql
        stg_npm_dependents.sql
        stg_npm_downloads.sql
      intermediate/
        int_advisories_unified.sql
        int_replacements_unified.sql
        int_project_popularity.sql
      marts/
        projects.sql
        advisories.sql
        replacements.sql
        dependents.sql
        opportunities.sql
    macros/
      score_popularity.sql        # @DEF macros for log-norm popularity
      score_severity.sql
      score_effort.sql
    audits/
      score_in_range.sql          # custom audit: score ∈ [0, 100]
      no_archived_active_opps.sql # custom audit: no opportunities on archived projects
    tests/                        # SQLMesh model unit tests (synthetic input → expected output)
  tests/                          # pytest unit + integration
  data/                           # gitignored; created at runtime
    raw/
    warehouse.duckdb              # both warehouse data and SQLMesh state
    briefs/
```

### 9.4 Tooling

- **uv** — package + lockfile + virtualenv management
- **ruff** — lint + format
- **mypy** — type-check `src/biibaa/`
- **pytest** + **pytest-httpx** — adapter unit tests with fixture-recorded HTTP responses
- **SQLMesh audits** + **SQLMesh tests** — schema + data assertions on every mart, plus model-level unit tests with declarative input/output fixtures
- **Pydantic v2** — domain types and adapter response decoding (analogue to Effect Schema)

## 10. Operations

- **Schedule**: local CLI for now (`uv run biibaa ingest && sqlmesh run`); later GitHub Actions daily cron. `sqlmesh plan` gates merges to `main` so heuristic changes are reviewed against a row-level diff.
- **Idempotency**: Python ingest writes date-partitioned dirs; SQLMesh interval state tracks which dates each model has processed, so re-runs are no-ops; opportunity dedupe via `dedupe_key` in marts
- **Observability**: `structlog` for ingest; SQLMesh stores run history and intervals in its state DB (co-located in `warehouse.duckdb`), queryable for trend analysis
- **Rate limiting**: per-source budget (NVD: 50 req/30s w/ key; npm browse: ≤1 req/s; GitHub: 5000/hr w/ PAT)

## 11. Open questions

1. **Project universe** — long tail of every package, or seed with watchlist (top 1k npm by dependents) and expand via fan-out?
2. **Reachability** — attempt static reachability analysis ("is the vulnerable code path actually called?") or treat any direct dep as reachable enough? High value, expensive.
3. **Opportunity identity** — `(project, kind, payload_id)` natural key, or content hash? Matters for tracking state across runs.
4. **Brief audience** — for upstream maintainers (terse, PR-oriented) or for an internal triage queue (detailed, rationale-heavy)? Affects template.
5. **Multi-language scope** — npm-only first, or polyglot from day one? OSV is language-agnostic but popularity signals differ per ecosystem.
6. **Fan-out depth** — for npm dependents, take only direct dependents (depth=1) or recurse to depth=2+? Recursion explodes the candidate set fast.

---

**Next step after sign-off**: scaffold the Python project (`uv init`) + SQLMesh project (`sqlmesh init duckdb`), then TDD `domain` + `adapters/osv.py` to deliver the end-to-end happy path: OSV → raw Parquet → SQLMesh staging → `opportunities` mart → Markdown brief.
