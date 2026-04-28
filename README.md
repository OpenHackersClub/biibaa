# biibaa

![biibaa](site/biibaa.png)

> Beavers are keystone engineers, transforming simple waterways into thriving wetland ecosystems that sustain biodiversity and climate resilience.

Open source improvement opportunity tracker. Pulls advisory + popularity data
and emits ranked Markdown briefs of low-effort, high-impact contribution
targets. See [SPEC.md](SPEC.md) for the full design.

**Live site:** [biibaa.pages.dev](https://biibaa.pages.dev)

## What BiiBaa can do

BiiBaa runs a pipeline that ingests advisory and replacement data, scores
projects by contribution leverage, and writes ranked Markdown briefs.

- **Vulnerability source** — GHSA REST, unpatched advisories only
- **Replacement source** — e18e `module-replacements` (preferred, native, and micro-utility manifests)
- **Popularity** — npm bulk downloads + GitHub stars (log-normalised)
- **Dependents fan-out** — tiered: pyoso `sboms_v0` → ecosyste.ms fallback → SQLite weekly cache
- **Project context** — GitHub GraphQL (`isArchived`, last-merged-PR) + `package.json` / `pnpm-lock.yaml` for direct-dep verification
- **Filtering** — drops already-patched CVEs, transitive-only hits, non-JS roots, archived repos, and projects below the weekly-downloads floor
- **Scoring** — vulnerability + bloat + perf axes with a confidence modifier (last-merged-PR decay)
- **Effort signal** — heuristic bands (version-bump = drop-in; e18e effort tiers)
- **Output** — one brief per project, top-N ranked, with `top_n // 3` slots reserved for replacement-led briefs
- **Storage** — in-memory pipeline, Markdown briefs with YAML frontmatter, SQLite dependents cache
- **Renderer** — Astro 5 + Tailwind v4 static site deployed to Cloudflare Pages
- **Schedule** — `biibaa run` locally; CI deploys the site on push to `main`

## Quickstart

```sh
uv sync
uv run biibaa run --top 20
```

Briefs land in `data/briefs/<ecosystem>/<project>/<yyyy-mm-dd>.md` (e.g. `data/briefs/npm/reduxjs__react-redux/2026-04-27.md`). Each file is a Markdown body with structured YAML frontmatter (`schema: biibaa-brief/1`) consumable by the static site.

### CLI flags

| Flag | Default | Purpose |
|---|---|---|
| `--out` | `data/briefs` | Brief output dir |
| `--top` | `20` | Number of briefs to render |
| `--ecosystem` | `npm` | Only `npm` wired today |
| `--advisory-limit` | `400` | Max GHSA advisories to ingest |
| `--fanout-top-n` | `40` | Cap how many e18e mappings to fan out from |
| `--dependents-per-replacement` | `5` | Top-K dependents pulled per replacement |
| `--min-weekly-downloads` | `50000` | Drop projects below this floor |
| `-v` / `--verbose` | off | Debug logs |

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
  domain/           # Pydantic v2 types: Project, Advisory, Replacement, Opportunity, Brief
  ports/            # Protocol classes (DependentsSource)
  adapters/         # github_advisories, github_repo, npm_downloads, npm_registry,
                    # e18e, ecosyste_ms, pyoso_dependents, dependents_factory,
                    # dependents_tiered, dependents_cache, _circuit, _http, _semver
  pipeline/         # Ingest → fan-out → score → render orchestration
  briefs/           # Jinja brief template + renderer (YAML frontmatter + Markdown body)
  cli/              # Typer entry: `biibaa run`, `biibaa version`
  scoring.py        # Popularity / severity / effort / confidence / final blend
site/               # Astro 5 + Tailwind v4 static site (Cloudflare Pages)
tests/              # pytest + pytest-httpx unit + adapter tests
data/
  briefs/<eco>/<slug>/<date>.md
  dependents_cache.sqlite
.github/workflows/deploy-site.yml
```

## Site

`site/` is an Astro static site that renders the briefs for triage, deployed at [biibaa.pages.dev](https://biibaa.pages.dev). CI builds and deploys it on every push to `main` (paths: `site/**`, `data/briefs/**`). See [`site/README.md`](site/README.md) for first-time wiring of the `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` repo secrets.

```sh
cd site
npm install
npm run dev      # http://localhost:4321
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

## Spec

[SPEC.md](SPEC.md) is the design doc; sections are tagged ✅ built / ⚠️ partial / ❌ deferred so it tracks reality. SQLMesh + DuckDB warehouse (§8.2, §9.A) and the full subcommand surface (`ingest`, `brief`, `show`) are deferred — see the issues board for the follow-up backlog.
