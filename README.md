# biibaa

Open source improvement opportunity tracker. Pulls advisory + popularity data
and emits ranked Markdown briefs of low-effort, high-impact contribution
targets. See [SPEC.md](SPEC.md) for the full design.

## MVP scope

This first cut implements a vertical slice of the spec — enough to deliver the
acceptance criteria of producing 20 actionable contribution briefs across all
three opportunity axes (vulnerability, bloat, perf).

| Spec area | MVP | Follow-up |
|---|---|---|
| Sources | GHSA REST (unpatched-only) + npm bulk downloads + e18e module-replacements + ecosyste.ms dependents | OSV bulk, NVD, replacements.fyi, OSO BigQuery |
| Storage | In-memory + Markdown out | Parquet raw landing → DuckDB warehouse |
| Modeling | Python pipeline | SQLMesh staging → marts |
| Scoring axes | Vulnerability + bloat + perf | Measured bytes-saved per replacement, benchmark deltas |
| Effort signal | Heuristic (version-bump = drop-in; e18e effort bands) | Codemod registry, breaking-change taxonomy |
| Output | One brief per project, top-N with axis quota | Persisted opportunity history, state transitions |

## Quickstart

```sh
uv sync
uv run biibaa run --top 20
```

Briefs land in `data/briefs/<ecosystem>/<project>/<yyyy-mm-dd>.md` (e.g. `data/briefs/npm/react__react/2026-04-27.md`).

## Configuration

Copy `env.sample` to `.env` (gitignored) and fill in what you need.

- `GITHUB_TOKEN` — required for non-trivial runs (REST rate limits bite
  fast). Falls back to `gh auth token` if the `gh` CLI is logged in.
- `OSO_API_KEY` — optional. With the `pyoso` extra installed
  (`uv sync --extra pyoso`), enables the tiered dependents source backed
  by OSO's `sboms_v0` join. Without it, ecosyste.ms is the sole backend.
- TLS / proxy vars (`BIIBAA_INSECURE_TLS`, `SSL_CERT_FILE`,
  `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`, `HTTPS_PROXY`,
  `HTTP_PROXY`) — see [Behind a MITM proxy](#behind-a-mitm-proxy) below.

## What you'll see

**Every brief points at one specific repo a contributor can PR.**

1. **Unpatched CVE briefs** — the repo is the source repo of the vulnerable
   package (from GHSA `source_code_location`). Contribution: write the
   upstream patch.
2. **Bloat / perf replacement briefs** — the repo is a popular **dependent**
   of an e18e-flagged package (discovered via ecosyste.ms fan-out).
   Contribution: PR the dependent to swap the dep for the recommended
   target / native API.

We deliberately exclude:
- Already-patched CVEs (bumping a fixed version is dependabot's job).
- "Self-deprecation" briefs for replacement candidates (PR'ing `isarray`'s
  own repo to advise people to drop it is not the contribution we want;
  PR'ing `react-redux` to drop its `isarray` dep is).

## Layout

```
src/biibaa/
  domain/           # Pydantic v2 types: Project, Advisory, Opportunity, Brief
  ports/            # Protocol classes for sources
  adapters/         # github_advisories, npm_downloads (bulk), e18e
  pipeline/         # Ingest → score → render orchestration
  briefs/           # Jinja brief template + renderer
  cli/              # Typer entry: `biibaa run`
tests/              # pytest unit + adapter tests
```

## Behind a MITM proxy

`src/biibaa/adapters/_http.py` honors `SSL_CERT_FILE` /
`NODE_EXTRA_CA_CERTS` and falls back to permissive verification when a
loopback HTTPS_PROXY is detected (e.g. `ccli net start`). Set
`BIIBAA_INSECURE_TLS=1` to force-disable cert verification.

## Tests

```sh
uv run pytest
```
