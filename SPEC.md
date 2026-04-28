# biibaa — Open Source Improvement Opportunity Tracker

> Data engineering pipeline that surfaces low-effort, high-impact improvements to open source projects across **vulnerabilities**, **dependency weight**, and **performance**, then emits triage briefs.

> **Status (2026-04-28)** — MVP is built end-to-end (`biibaa run` produces ranked briefs at
> `data/briefs/<ecosystem>/<project>/<yyyy-mm-dd>.md`) and a static Astro site renders them.
> Sources, storage, scoring, and pipeline sections below tag each item ✅ **built**, ⚠️ **partial**, or
> ❌ **deferred**. SQLMesh / DuckDB warehouse (§8, §9) is deferred — current pipeline is in-memory
> Python. See [README.md](README.md) for the operator-facing summary and the open issues for the
> follow-up backlog.

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

| Source | Purpose | Refresh | Auth | Access | Status |
|---|---|---|---|---|---|
| **GitHub Security Advisories** (REST) | CVE/GHSA records, CVSS, fixed versions, source repo | per run | PAT (gh CLI fallback) | `api.github.com/advisories` | ✅ built (`adapters/github_advisories.py`) |
| **GitHub repo (GraphQL + raw)** | `isArchived`, last-merged-PR, HEAD `package.json`, `pnpm-lock.yaml` | per run | PAT | GraphQL + `raw.githubusercontent.com` | ✅ built (`adapters/github_repo.py`) |
| **e18e module-replacements** | curated replacement candidates (preferred / native / micro-utilities) | per run | none | `raw.githubusercontent.com/e18e/module-replacements` | ✅ built (`adapters/e18e.py`) |
| **npm downloads API** | weekly download count (popularity signal) | per run | none | `api.npmjs.org/downloads/...` (bulk + per-package) | ✅ built (`adapters/npm_downloads.py`) |
| **npm registry** | `latest` dist-tag for outdated-advisory filter | per run | none | `registry.npmjs.org` | ✅ built (`adapters/npm_registry.py`) |
| **ecosyste.ms** | dependents fan-out (fallback) | per run | none | `packages.ecosyste.ms/api/v1/...` | ✅ built (`adapters/ecosyste_ms.py`) |
| **Open Source Observer** (`pyoso`) | dependents fan-out (primary, GitHub-repo ranked by stars via `sboms_v0` ⋈ `repositories_v0`) | per run | `OSO_API_KEY` + `[pyoso]` extra | `pyoso.Client` | ✅ built (`adapters/pyoso_dependents.py`) |
| **OSV.dev** bulk | multi-ecosystem vulnerability DB | daily bulk | none | bulk zip + REST | ❌ deferred |
| **NVD CVE** | CVSS scores, references | daily incremental | optional API key | REST | ❌ deferred |
| **replacements.fyi** | per-package replacements with weight savings | weekly | none | site scrape / data export | ❌ deferred |
| **npmjs.com/browse/depended/`<pkg>`** | top dependents per package (fan-out via HTML scrape) | weekly per seed | none | HTML scrape | ❌ deferred — superseded by ecosyste.ms + pyoso |

### 3.1 Source notes

- **GHSA REST** is the MVP advisory source — filterable per-request (ecosystem + severity), structured JSON, and works without auth at low volume. The pipeline pulls only `first_patched_version is null` records by default: bumping a fixed version is dependabot's job; the contribution opportunity is to *write* the upstream patch.
- **GitHub repo GraphQL** is the project-context layer: archived state and last-merged-PR drive the confidence axis. The same module also fetches HEAD `package.json` (and `pnpm-lock.yaml` for monorepos) to verify that fan-out hits actually have the flagged package as a *direct* dep — OSO's `sboms_v0` is lockfile-derived, so a transitive-only hit would otherwise pollute the triage set.
- **e18e** is the curated replacement source. Manifests `preferred.json`, `native.json`, `micro-utilities.json` map from-package → replacement-id; `replacements` resolves each id to a target module (or `<native>` for built-in API). Replacements with no actionable target are skipped.
- **npm downloads** powers the popularity log-norm in §6.1 and ranks which e18e mappings to fan out from (cap via `--fanout-top-n`).
- **npm registry** drops GHSA records whose affected range no longer covers `latest` — GHSA frequently leaves `first_patched_version` null after a project moves past the affected range without backporting.
- **Dependents fan-out** is tiered: pyoso (primary, GitHub repos with star ranks) → ecosyste.ms (fallback, npm package names with repo URLs) → SQLite cache (`data/dependents_cache.sqlite`) keyed by `(system, name, iso_week)`. Both backends are wrapped in a circuit breaker because hot packages (`lodash`, `debug`, `axios`, …) reliably 500 on ecosyste.ms.
- **OSV / NVD / replacements.fyi / npm browse** — listed as deferred. OSV would replace GHSA REST as the primary advisory source for breadth; NVD adds CVSS where OSV is weak; replacements.fyi adds bytes-saved metadata to e18e mappings.

### 3.2 Source precedence on conflict

- Vulnerability data (current): **GHSA REST only**. Future: **OSV > GHSA > NVD**.
- Replacement data: **e18e** (replacements.fyi deferred).
- Dependents fan-out: **pyoso > ecosyste.ms** (selected at runtime by `adapters/dependents_factory.py` based on `OSO_API_KEY` + `[pyoso]` extra).
- Popularity: composite (see scoring §6), no single winner.

## 4. Domain model

### 4.1 Project (aggregate root)

- `purl` — canonical id, [package URL](https://github.com/package-url/purl-spec) format (e.g. `pkg:npm/express`)
- `ecosystem` — npm | pypi | go | rubygems | crates | maven | …
- `name`, `repo_url`, `homepage`
- `stars`, `downloads_weekly`, `dependents` — raw popularity signals (composite computed in scoring §6)
- `last_release_at`, `last_commit_at`, `last_pr_merged_at` — recency signals; `last_pr_merged_at` drives the confidence axis (§6.3)
- `archived: bool`
- `has_benchmarks: bool | None`, `bench_signal: str | None` — populated for replacement-driven projects from HEAD `package.json` (script names containing `bench`, `vitest|jest … bench` patterns, or known bench devDeps); `None` means we didn't check, surfaced in the brief frontmatter

### 4.2 Advisory (entity, references Project)

- `id` — GHSA id (`GHSA-…`, `CVE-…`)
- `severity` — CVSS v3 / v4 score (`cvss`) + qualitative band (`severity`)
- `affected_versions` — string range (GHSA `vulnerable_version_range`)
- `fixed_versions` — list of fixed versions; **empty when unpatched** (the pipeline filters to unpatched-only by default — see §3.1)
- `summary`, `refs[]`, `published_at`
- `repo_url` — source repo of the vulnerable package, used to point unpatched-vuln briefs at a concrete PR target

### 4.3 Replacement (entity, references Project)

- `from_purl: purl`
- `to_purls: purl[]` — sometimes multiple candidates; `pkg:npm/<native>` for native-API replacements
- `axis: bloat | perf | maintenance | security` — only `bloat` and `perf` emitted today (e18e manifests don't surface the other two)
- `evidence` — `{source, manifest, ids}` for e18e citations; bytes-saved metadata is deferred until replacements.fyi is wired up
- `effort: drop-in | minor-migration | codemod-available | rewrite`

### 4.4 Opportunity (entity)

The unit of work surfaced to humans. One per `(project, axis, finding)`.

- `kind: vulnerability-fix | dep-replacement | perf-replacement`
- `project: Project`
- `payload: Advisory | Replacement`
- `impact: 0..100`
- `effort: 0..100` (high = easy)
- `score: number`
- `dedupe_key` — for upserts across runs (`{project.purl}|{advisory.id}` or `{project.purl}|{replacement.id}`)
- `state: new | acknowledged | resolved | rejected | duplicate` — type declared but **no cross-run persistence yet**; every run currently starts from `new`
- `first_seen_at`, `last_seen_at`

### 4.5 Brief (aggregate)

- One per project per run, bundling top N opportunities
- Markdown output: project context, ranked opportunities, suggested PR titles, citations

### 4.6 Domain events

`OpportunityDiscovered`, `OpportunityScored`, `BriefGenerated` — ❌ deferred. The current pipeline is a single in-process function; events would only be useful once we have cross-run state to drive (e.g. `state` transitions in §4.4).

## 5. Pipeline

### 5.1 Today (MVP, in-memory Python — see `pipeline/run.py`)

```
GHSA REST ─┐
e18e ──────┼──► aggregate by project ──► score ──► axis-quota top-N ──► render
deps fan-out ─┘                                  (replacement quota = top_n // 3)
```

1. **Fetch advisories** — `GithubAdvisorySource.fetch()` (unpatched-only by default).
2. **Drop outdated unpatched** — `_drop_outdated_unpatched` consults `NpmRegistrySource.latest_versions` and the affected range to discard advisories whose `latest` is no longer affected.
3. **Fetch replacements** — `E18eReplacementsSource.fetch()` for npm.
4. **Fan-out dependents** — `_fan_out_dependents` ranks e18e mappings by from-package weekly downloads, takes the top `--fanout-top-n`, and pulls `--dependents-per-replacement` dependents each via `build_dependents_source()` (pyoso primary → ecosyste.ms fallback → SQLite cache). Results are filtered against each dependent's HEAD `package.json` / `pnpm-lock.yaml` to drop transitive-only matches; `*NOT_JS*` (no JS manifest at root) hits are dropped, `*MONOREPO*` hits without a parseable lockfile are kept (fail open).
5. **Hydrate projects** — bulk weekly downloads, GitHub repo meta (`is_archived`, `last_merged_pr_at`), and bench info (replacement-driven projects only, free cache hit).
6. **Eligibility filter** — drop archived repos and packages below `--min-weekly-downloads` (default 50K).
7. **Score** — vuln + replacement opportunities per project (§6); cap per-project at `max_opps_per_project=6`; head opportunity defines the project's score.
8. **Axis-quota top-N** — `_select_with_axis_quota` reserves at least `top_n // 3` slots for replacement-led briefs so vuln-heavy ranking doesn't starve them; spillover refills the other axis.
9. **Render** — Jinja2 Markdown body + YAML frontmatter (`schema: biibaa-brief/1`); written to `data/briefs/<ecosystem>/<slug>/<yyyy-mm-dd>.md`.

The whole pipeline runs in-process. There is no `data/raw/` landing today.

### 5.2 Aspirational (deferred — SQLMesh + DuckDB)

```
sources → ingest (raw landing) → normalize (canonical model) → score → brief
```

1. **Ingest** — adapter per source pulls raw payloads. Stored as Parquet/JSON under `data/raw/<source>/<yyyy-mm-dd>/`. Idempotent per `(source, date)`.
2. **Normalize** — SQLMesh staging models read raw Parquet via DuckDB's `read_parquet`, decode into typed staging tables; intermediate models apply source precedence (§3.2) and dedupe. Time-partitioned raw inputs map to `INCREMENTAL_BY_TIME_RANGE` models keyed on the ingest date.
3. **Fan-out** — for each flagged package, enumerate top-K dependents to expand the candidate set.
4. **Score** — apply heuristics (§6). Materialize `opportunities` table.
5. **Brief** — pick top-N projects by aggregate score; render Markdown briefs.

Each step would be idempotent and replayable from raw. Status: ❌ deferred, see [Issues](#13-suggested-issues).

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

| Disqualifier | Status |
|---|---|
| Project archived | ✅ built (`pipeline.run._is_eligible`) |
| Below weekly-downloads floor (`--min-weekly-downloads`, default 50K) | ✅ built (added beyond SPEC) |
| Replacement target unmaintained / archived | ✅ built (effort table; archived disqualifier covers downstream) |
| Outdated GHSA whose `latest` is no longer affected | ✅ built (`_drop_outdated_unpatched`) |
| Fan-out hit with no JS manifest at repo root | ✅ built (`NOT_JS_SENTINEL`) |
| Fan-out hit where flagged package is only transitive | ✅ built (`fetch_direct_deps` against `package.json` / `pnpm-lock.yaml`) |
| No commit in 24 months → drop unless vuln severity ≥ 9 | ❌ deferred |
| Replacement target itself flagged on OSV → drop | ❌ deferred |
| Existing open PR proposing the same fix → de-prioritize, link instead | ❌ deferred |
| Maintainers declined the change (WONTFIX) → drop, `state: rejected` | ❌ deferred (needs cross-run state) |

## 7. Brief format

Briefs are emitted as `---\n<yaml frontmatter>\n---\n\n<markdown body>` (`schema: biibaa-brief/1`) so the static-site renderer (`site/`) can build cards/listings/filters from structured metadata without parsing the body. The body is plain Markdown for direct reading.

### 7.1 Frontmatter (canonical)

```yaml
---
schema: biibaa-brief/1
title: react-redux
slug: reduxjs__react-redux
date: 2026-04-27
run_at: 2026-04-27T10:14:33+00:00
project:
  purl: pkg:github/reduxjs/react-redux
  name: reduxjs/react-redux
  ecosystem: npm
  repo_url: https://github.com/reduxjs/react-redux
  downloads_weekly: 8420000
  archived: false
score:
  total: 87.4
  impact: 92.1
  effort: 75.0
  confidence: 100
maintainer_activity:
  label: last PR merged 3d ago
  last_pr_merged_at: 2026-04-25T17:01:09+00:00
benchmarks:
  has: true
  signal: script:bench
opportunities:
  count: 4
  kinds: [dep-replacement, vulnerability-fix]
  top_kind: vulnerability-fix
tags: [bench, npm, unpatched, vuln]
citations:
  - {type: advisory, id: GHSA-xxxx-xxxx-xxxx, url: https://github.com/advisories/GHSA-xxxx-xxxx-xxxx}
  - {type: e18e-replacement, id: micro-utilities.json, url: https://github.com/e18e/module-replacements/blob/main/manifests/micro-utilities.json}
---
```

### 7.2 Body

```md
# react-redux — 2026-04-27 Improvement Brief

**Repo**: [github.com/reduxjs/react-redux](https://github.com/reduxjs/react-redux)

## Top opportunities

### 1. [vulnerability-fix] GHSA-xxxx-xxxx-xxxx
- **Severity**: high · CVSS 7.5
- **Summary**: …
- **Affected**: `<1.2.3`
- **Fix**: _no upstream patch — contribute one_ at https://github.com/example/pkg
- **Evidence**: [GHSA-xxxx-xxxx-xxxx](https://github.com/advisories/GHSA-xxxx-xxxx-xxxx)
- **Effort score**: 20 / 100 (high = easy)
- **Impact score**: 78 / 100
- **Suggested PR**: `fix: address GHSA-xxxx-xxxx-xxxx in pkg`

### 2. [dep-replacement] isarray → <native>
- **Axis**: bloat
- **Replace**: `isarray` → `<native>`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest `native.json`
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 60 / 100
- **Suggested PR**: `deps: drop isarray dep (use native API)`
```

## 8. Storage

### 8.1 Today (MVP)

```
data/
  briefs/<ecosystem>/<project>/<yyyy-mm-dd>.md   # frontmatter + body
  dependents_cache.sqlite                         # tiered fan-out cache, key (system, name, iso_week)
```

The MVP runs entirely in memory. There is no persistent warehouse; each `biibaa run` re-fetches sources (subject to the SQLite cache for dependents fan-out) and re-renders briefs.

### 8.2 Aspirational (deferred — DuckDB + Parquet)

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

Core tables (planned):

- `projects (purl PK, ecosystem, name, repo_url, stars, downloads_weekly, dependents, last_release_at, archived)`
- `advisories (id PK, project_purl FK, severity, cvss, summary, fixed_versions JSON, refs JSON)`
- `replacements (id PK, from_purl, to_purl, axis, effort, evidence JSON)`
- `dependents (parent_purl, child_purl, rank)` — fan-out edge list
- `opportunities (id PK, project_purl, kind, payload_id, impact, effort, score, dedupe_key, state, first_seen_at, last_seen_at)`
- `briefs (id PK, run_at, project_purl, path, score)`

DuckDB chosen for: zero-ops, columnar joins across millions of `advisories × projects × dependents`, Parquet-native, fast local SQL exploration. Revisit when multi-user is real.

## 9. Architecture

### 9.0 Today (MVP)

**Stack**: Python 3.12+ end-to-end. uv-managed venv. Hexagonal layout (ports + adapters). No SQLMesh / no DuckDB yet — see §9.A for the deferred slice and §13 for the issue list.

### 9.1 Aspirational

**Stack**: Python 3.12+ for ingest and orchestration; **SQLMesh** (with the DuckDB engine adapter) for transformation, modeling, audits, and incremental scheduling; DuckDB as the warehouse.

Rationale: data engineering work — API ingestion, Parquet/columnar transforms, SQL modeling — is where Python's tooling is strongest. SQLMesh fits this project specifically:

- **Interval-based incrementals** (`INCREMENTAL_BY_TIME_RANGE`) match our `data/raw/<source>/<date>/` layout directly — no hand-rolled `is_incremental()` filters or partition columns.
- **`plan` / `apply` workflow** lets us preview affected rows before materializing scoring-formula changes — important when heuristic weights evolve.
- **Virtual data environments** give free dev/prod isolation against a single DuckDB file via shadow views.
- **Audits** (vs dbt's tests) are first-class blocking checks tied to model materialization.
- **Native Python models** sit inside the DAG — useful if any transform later needs a Python library (e.g. fuzzy package-name matching).

This is a deliberate departure from the TypeScript/Effect-TS preference in `arch-taste.md`: that guidance targets application services. Any future UI/CLI surface for browsing briefs may still be TS.

### 9.2 Hexagonal split (Python — built today)

- `domain/` — Pydantic v2 models (`Project`, `Advisory`, `Replacement`, `Opportunity`, `Brief`); pure
- `ports/` — `Protocol` classes (`DependentsSource`)
- `adapters/` — `github_advisories.py`, `github_repo.py`, `e18e.py`, `npm_downloads.py`, `npm_registry.py`, `ecosyste_ms.py`, `pyoso_dependents.py`, `dependents_factory.py`, `dependents_tiered.py`, `dependents_cache.py`, `_circuit.py`, `_http.py`, `_semver.py`
- `pipeline/run.py` — orchestrator (~500 lines)
- `briefs/render.py` + `templates/brief.md.j2` — Jinja Markdown body + structured YAML frontmatter
- `cli/main.py` — Typer entry: `biibaa run`, `biibaa version`
- `scoring.py` — popularity / severity / effort / confidence / final blend

### 9.3 Project layout (today)

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
    scoring.py
  site/                           # Astro + Tailwind v4 SSG (briefs renderer, Cloudflare Pages)
  tests/                          # pytest + pytest-httpx unit + adapter tests
  data/                           # gitignored; created at runtime
    briefs/<ecosystem>/<project>/<yyyy-mm-dd>.md
    dependents_cache.sqlite
  .github/workflows/deploy-site.yml
```

### 9.A Layers (deferred — SQLMesh + DuckDB)

| Layer | Tool | Responsibility | Status |
|---|---|---|---|
| **Ingest** | Python (httpx, pydantic v2) | Pull from sources; land raw Parquet/JSON in `data/raw/<source>/<date>/` | ⚠️ partial — adapters built, but no Parquet landing |
| **Staging** | SQLMesh `INCREMENTAL_BY_TIME_RANGE` models (`read_parquet`) | Decode raw → typed staging tables; one staging model per source, partitioned by ingest date | ❌ deferred |
| **Intermediate** | SQLMesh `VIEW` / `INCREMENTAL` models | Source-precedence resolution, joins, dedupe | ❌ deferred |
| **Marts** | SQLMesh `FULL` or `INCREMENTAL` models | `projects`, `advisories`, `replacements`, `dependents`, `opportunities` | ❌ deferred |
| **Score** | SQLMesh SQL + macros | Apply popularity + severity + effort heuristics; materialize `opportunities` | ❌ deferred (lives in `scoring.py` today) |
| **Audits** | SQLMesh audits | `not_null`, `unique_values`, `relationships`, custom (e.g. `score_in_range`) | ❌ deferred |
| **Brief** | Python + Jinja2 | Read `opportunities` from DuckDB; render Markdown | ✅ built (reads in-memory, not DuckDB) |
| **CLI** | Python (Typer) | `biibaa ingest <source>`, `biibaa run`, `biibaa brief`, `biibaa show <project>` | ⚠️ partial — `run` + `version` only; `ingest`/`brief`/`show` deferred |

### 9.4 Tooling (today)

- **uv** — package + lockfile + virtualenv management
- **ruff** — lint + format (CI not yet wired beyond `ruff check`)
- **mypy** — declared in dev deps; not enforced in CI
- **pytest** + **pytest-httpx** — adapter unit tests with fixture-recorded HTTP responses (✅ broad coverage)
- **Pydantic v2** — domain types and adapter response decoding
- **Astro 5 + Tailwind v4** (`site/`) — static site renderer for briefs
- **SQLMesh audits / tests** — ❌ deferred along with the warehouse

## 10. Operations

### 10.1 Today

- **Schedule**: local CLI only — `uv run biibaa run --top 20`. No cron yet for the pipeline.
- **CI**: `.github/workflows/deploy-site.yml` builds `site/` and deploys to Cloudflare Pages on every push to `main` (paths: `site/**`, `data/briefs/**`).
- **Idempotency**: same-day `biibaa run` re-fetches sources and overwrites the day's `data/briefs/<eco>/<slug>/<date>.md` deterministically. Dependents fan-out is cached weekly in `data/dependents_cache.sqlite`. No cross-run opportunity state.
- **Observability**: `structlog` for ingest. Key events: `pipeline.start`, `pipeline.advisories_fetched`, `advisory.outdated_filter`, `fanout.dependents`, `fanout.direct_deps_filter`, `pipeline.eligibility_filter`, `pipeline.briefs_selected`, `pipeline.done`.
- **Rate limiting**: per-source budgets — GitHub: 5000/hr w/ PAT (GHSA REST + GraphQL + raw `package.json`/lockfile fetches); npm bulk-downloads: 128 packages/request, 0.5s between batches, exponential backoff on 429; ecosyste.ms + pyoso both wrapped in `_circuit.CircuitBreaker` (3 failures → 5-minute open, fall through to fallback / `[]`).
- **TLS / proxy**: `_http.make_client` honors `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`; auto-disables verification when `HTTPS_PROXY` points at a loopback (e.g. `ccli net start`); `BIIBAA_INSECURE_TLS=1` forces it off.

### 10.2 Aspirational

- **Schedule**: GitHub Actions daily cron on the pipeline. `sqlmesh plan` gates merges to `main` so heuristic changes are reviewed against a row-level diff.
- **Idempotency**: SQLMesh interval state tracks which dates each model has processed, so re-runs are no-ops; opportunity dedupe via `dedupe_key` in marts.
- **Observability**: SQLMesh run history co-located in `warehouse.duckdb`, queryable for trend analysis.

## 11. CLI reference

```sh
uv run biibaa run [OPTIONS]
uv run biibaa version
```

### `biibaa run`

| Flag | Default | Purpose |
|---|---|---|
| `--out` | `data/briefs` | Brief output directory (per-ecosystem subdirs are created underneath). |
| `--top` | `20` | Number of briefs to render. |
| `--ecosystem` | `npm` | Ecosystem to ingest (only `npm` is wired today). |
| `--advisory-limit` | `400` | Max advisories to ingest from GHSA. |
| `--fanout-top-n` | `40` | Cap how many e18e mappings (ranked by from-package weekly downloads) to fan out from. |
| `--dependents-per-replacement` | `5` | Top-K dependents pulled per fanned-out replacement. |
| `--min-weekly-downloads` | `50000` | Drop projects below this floor. |
| `-v` / `--verbose` | off | Debug-level structlog output. |

Subcommands listed in earlier drafts (`biibaa ingest <source>`, `biibaa brief`, `biibaa show <project>`) are not implemented — `run` is the single end-to-end entry today.

## 12. Static site (`site/`)

Astro 5 + Tailwind v4 + a content collection whose schema mirrors `briefs/render.py:_build_frontmatter` (`schema: biibaa-brief/1`). Reads briefs straight from `../data/briefs/`, builds a static bundle in `site/dist/`, deploys to Cloudflare Pages via `.github/workflows/deploy-site.yml` on every push to `main` that touches `site/**` or `data/briefs/**`. See `site/README.md` for first-time wiring of the `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` secrets.

## 13. Suggested issues

The MVP intentionally cuts most of §8 (warehouse) and §9.A (SQLMesh) to ship a working brief renderer. The follow-up backlog is tracked as separate issues — see the [drift summary](.tmp/drift-2026-04-28.md) and the issues board for the canonical list.

## 14. Open questions

1. **Project universe** — long tail of every package, or seed with watchlist (top 1k npm by dependents) and expand via fan-out?
2. **Reachability** — attempt static reachability analysis ("is the vulnerable code path actually called?") or treat any direct dep as reachable enough? High value, expensive.
3. **Opportunity identity** — `(project, kind, payload_id)` natural key, or content hash? Matters for tracking state across runs.
4. **Brief audience** — for upstream maintainers (terse, PR-oriented) or for an internal triage queue (detailed, rationale-heavy)? Affects template.
5. **Multi-language scope** — npm-only first, or polyglot from day one? OSV is language-agnostic but popularity signals differ per ecosystem.
6. **Fan-out depth** — for npm dependents, take only direct dependents (depth=1) or recurse to depth=2+? Recursion explodes the candidate set fast.
