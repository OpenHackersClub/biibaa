# biibaa

Open source improvement opportunity tracker. Pulls advisory + popularity data
and emits ranked Markdown briefs of low-effort, high-impact contribution
targets. See [SPEC.md](SPEC.md) for the full design.

## MVP scope

This first cut implements a vertical slice of the spec — enough to deliver the
acceptance criteria of producing 20 actionable contribution briefs.

| Spec area | MVP | Follow-up |
|---|---|---|
| Sources | GHSA REST + npm downloads | OSV bulk, NVD, e18e, replacements.fyi, npm dependents fan-out |
| Storage | In-memory + Markdown out | Parquet raw landing → DuckDB warehouse |
| Modeling | Python pipeline | SQLMesh staging → marts |
| Scoring axes | Vulnerability fixes only | Bloat (e18e), perf (replacements.fyi) |
| Effort signal | Heuristic (version-bump = drop-in) | Codemod registry, breaking-change taxonomy |
| Output | One brief per project, top-N | Persisted opportunity history, state transitions |

## Quickstart

```sh
uv sync
uv run biibaa run --top 20
```

Briefs land in `data/briefs/<yyyy-mm-dd>/<project>.md`.
A pinned snapshot lives in [examples/briefs/](examples/briefs/).

## Layout

```
src/biibaa/
  domain/           # Pydantic v2 types: Project, Advisory, Opportunity, Brief
  ports/            # Protocol classes for sources
  adapters/         # github_advisories, npm_downloads
  pipeline/         # Ingest → score → render orchestration
  briefs/           # Jinja brief template + renderer
  cli/              # Typer entry: `biibaa run`
tests/              # pytest unit + adapter tests
examples/briefs/    # Snapshot of generated briefs (committed)
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
