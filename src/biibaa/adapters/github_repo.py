"""GitHub repo activity adapter — fetches the most-recently-merged PR
timestamp and the repo's archived flag via the v4 GraphQL API. Both signals
are pulled in one query and cached together so `last_merged_pr_at` and
`is_archived` callers share a single round-trip per repo.

- `last_merged_pr_at` feeds the confidence axis (a repo whose maintainers
  merged something last week is far more likely to merge a drive-by
  contribution than one frozen for two years).
- `is_archived` is a hard disqualifier — archived repos won't accept PRs.
- `fetch_direct_deps` reads the repo's HEAD `package.json` so the pipeline
  can drop dependents that only pull in a flagged package transitively
  (OSO's `sboms_v0` is lockfile-derived and includes the full tree).
- `bench_info` derives a yes/no benchmark signal from the same cached
  `package.json` (zero extra HTTP) — repos with benchmarks are the easiest
  triage targets for perf-replacement briefs."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

import httpx
import structlog
import yaml

from biibaa.adapters._http import make_client

log = structlog.get_logger(__name__)

GRAPHQL_URL = "https://api.github.com/graphql"

# Sentinel returned by fetch_direct_deps for monorepo roots when no
# lockfile is available — enumerating every workspace's package.json
# multiplies API cost and risks dropping legit dependents, so callers
# treat this as "verified, don't filter". Preferred path is to parse
# `pnpm-lock.yaml` instead, which lists direct deps for every workspace
# in a single HTTP fetch.
MONOREPO_SENTINEL = "*MONOREPO*"

# Sentinel returned when the repo has no JS manifest of any kind at root
# (no package.json, no pnpm-lock.yaml / yarn.lock / package-lock.json).
# OSO's sboms_v0 surfaces such repos when JS lives in a sub-tree, but a
# transitive hit four levels deep under tooling isn't a contribution
# opportunity for the root project — callers drop these candidates.
NOT_JS_SENTINEL = "*NOT_JS*"

# Lockfiles whose presence at root proves the repo treats JS as a top-level
# concern. Used by fetch_direct_deps to distinguish "not a JS project at
# root" (drop) from "transient fetch error" (fail open).
_ROOT_LOCKFILES: tuple[str, ...] = (
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
)

# Workspace dependency sections in `pnpm-lock.yaml` `importers.<path>` whose
# keys are direct deps of that workspace's `package.json`.
_PNPM_DEP_SECTIONS: tuple[str, ...] = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)

# Bench libraries we trust as a signal that the repo has runnable benchmarks.
# Conservative on purpose — vitest/jest are bench-capable but their bench
# command is opt-in. Their devDep presence alone is too noisy; the
# vitest/jest bench case is handled via _BENCH_CMD_PATTERNS below instead.
_BENCH_DEV_DEPS: tuple[str, ...] = (
    "tinybench",
    "mitata",
    "benchmark",
    "cronometro",
)

# Catches `scripts.<key>` whose VALUE invokes vitest/jest in bench mode but
# whose NAME doesn't contain "bench" (e.g. `"test:perf": "vitest bench src/"`).
# The `[^&|;]*` guard stops matching at shell command separators, so
# `"build && vitest && bench-something"` does NOT match — vitest there isn't
# the thing running bench.
_BENCH_CMD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bvitest\s+[^&|;]*bench", re.IGNORECASE),
    re.compile(r"\bjest\s+[^&|;]*bench", re.IGNORECASE),
)

_QUERY = """
query RepoMeta($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    isArchived
    defaultBranchRef {
      target { oid }
    }
    pullRequests(states: MERGED, orderBy: {field: UPDATED_AT, direction: DESC}, first: 1) {
      nodes { mergedAt }
    }
  }
}
"""


@dataclass(frozen=True)
class RepoMeta:
    last_merged_pr_at: datetime | None
    is_archived: bool
    head_sha: str | None = None


@dataclass(frozen=True)
class DepLocation:
    """Adapter-level location record (no permalink — pipeline builds the URL
    once it has the repo + sha + file). `line` is 1-based or None."""

    file: str
    line: int | None = None

_REPO_RE = re.compile(r"https?://github\.com/([^/]+)/([^/?#]+?)(?:\.git)?/?$")


def _parse_repo_url(url: str) -> tuple[str, str] | None:
    m = _REPO_RE.match(url.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def _resolve_token(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    if env := os.environ.get("GITHUB_TOKEN"):
        return env
    try:
        out = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


class GithubRepoSource:
    name = "github_repo"

    def __init__(
        self, *, token: str | None = None, client: httpx.Client | None = None
    ) -> None:
        self._token = _resolve_token(token)
        self._client = client or make_client(timeout=15.0)
        self._cache: dict[tuple[str, str], RepoMeta | None] = {}
        # Caches the parsed package.json so fetch_direct_deps and bench_info
        # share a single HTTP round-trip per repo. None = fetch/parse failed.
        self._pkg_cache: dict[tuple[str, str], dict | None] = {}
        # Raw text of the same package.json — kept alongside the parsed dict
        # so fetch_dependency_locations can find the line where each dep is
        # declared without a second fetch.
        self._pkg_text_cache: dict[tuple[str, str], str | None] = {}
        # Tracks whether package.json was definitively absent (404) vs failed
        # for some other reason (parse error, network blip). Lets the
        # transitive-filter distinguish "not a JS project" from "transient".
        self._pkg_missing: dict[tuple[str, str], bool] = {}
        # Caches the union of direct-dep names across all workspaces parsed
        # from `pnpm-lock.yaml`. None = fetch or parse failed (caller falls
        # back to MONOREPO_SENTINEL).
        self._lockfile_cache: dict[tuple[str, str], set[str] | None] = {}
        # Per-name workspace paths from the same lockfile parse, e.g.
        # `{"lodash": ["packages/api", "packages/web"]}`. Populated lazily
        # alongside `_lockfile_cache`.
        self._lockfile_locations_cache: dict[
            tuple[str, str], dict[str, list[str]] | None
        ] = {}
        # Caches whether ANY root lockfile exists. None = couldn't tell
        # (transient error). True/False are definitive.
        self._has_root_lockfile_cache: dict[tuple[str, str], bool | None] = {}

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def fetch_meta(self, *, repo_url: str) -> RepoMeta | None:
        parsed = _parse_repo_url(repo_url)
        if not parsed:
            return None
        if parsed in self._cache:
            return self._cache[parsed]
        owner, name = parsed
        try:
            r = self._client.post(
                GRAPHQL_URL,
                json={"query": _QUERY, "variables": {"owner": owner, "name": name}},
                headers=self._headers(),
            )
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            log.warning("github_repo.fetch_failed", repo=repo_url, error=str(e))
            self._cache[parsed] = None
            return None

        if payload.get("errors"):
            log.warning(
                "github_repo.graphql_errors", repo=repo_url, errors=payload["errors"]
            )
            self._cache[parsed] = None
            return None

        repo = ((payload.get("data") or {}).get("repository")) or {}
        nodes = repo.get("pullRequests", {}).get("nodes") or []
        merged_at: datetime | None = None
        if nodes and nodes[0].get("mergedAt"):
            merged_at = datetime.fromisoformat(
                nodes[0]["mergedAt"].replace("Z", "+00:00")
            )
        head_sha: str | None = None
        if (target := (repo.get("defaultBranchRef") or {}).get("target")):
            head_sha = target.get("oid")
        meta = RepoMeta(
            last_merged_pr_at=merged_at,
            is_archived=bool(repo.get("isArchived")),
            head_sha=head_sha,
        )
        self._cache[parsed] = meta
        return meta

    def last_merged_pr_at(self, *, repo_url: str) -> datetime | None:
        meta = self.fetch_meta(repo_url=repo_url)
        return meta.last_merged_pr_at if meta else None

    def is_archived(self, *, repo_url: str) -> bool:
        meta = self.fetch_meta(repo_url=repo_url)
        # Unknown / unreachable repos are NOT treated as archived — better to
        # over-include than silently drop a project on a transient API blip.
        return bool(meta and meta.is_archived)

    def _fetch_pkg_json(self, *, repo_url: str) -> dict | None:
        """Fetch + parse the repo's HEAD package.json, cached per repo.

        Returns the parsed JSON object, or None on any failure (parse error,
        404, network error, non-object payload). Sets `self._pkg_missing`
        when the failure is a definitive 404 so callers can distinguish
        "no package.json at root" from "transient fetch error".
        """
        parsed = _parse_repo_url(repo_url)
        if not parsed:
            return None
        if parsed in self._pkg_cache:
            return self._pkg_cache[parsed]
        owner, name = parsed
        url = f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/package.json"
        try:
            r = self._client.get(url, headers=self._headers())
            if r.status_code == 404:
                self._pkg_cache[parsed] = None
                self._pkg_text_cache[parsed] = None
                self._pkg_missing[parsed] = True
                return None
            r.raise_for_status()
            text = r.text
            payload = json.loads(text)
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as e:
            log.warning(
                "github_repo.fetch_pkg_failed",
                repo=repo_url,
                error=str(e),
            )
            self._pkg_cache[parsed] = None
            self._pkg_text_cache[parsed] = None
            self._pkg_missing[parsed] = False
            return None
        if not isinstance(payload, dict):
            self._pkg_cache[parsed] = None
            self._pkg_text_cache[parsed] = None
            self._pkg_missing[parsed] = False
            return None
        self._pkg_cache[parsed] = payload
        self._pkg_text_cache[parsed] = text
        self._pkg_missing[parsed] = False
        return payload

    def _has_any_root_lockfile(self, *, owner: str, name: str) -> bool | None:
        """Return True/False if at least one root JS lockfile exists/none, or
        None if we can't tell (transient error).

        Uses HEAD requests so we don't pay the body cost — we only care about
        existence. Caches the result per repo.
        """
        key = (owner, name)
        if key in self._has_root_lockfile_cache:
            return self._has_root_lockfile_cache[key]
        any_unknown = False
        for lf in _ROOT_LOCKFILES:
            url = f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/{lf}"
            try:
                r = self._client.head(url, headers=self._headers())
            except httpx.HTTPError:
                any_unknown = True
                continue
            if r.status_code == 200:
                self._has_root_lockfile_cache[key] = True
                return True
            if r.status_code != 404:
                any_unknown = True
        result: bool | None = None if any_unknown else False
        self._has_root_lockfile_cache[key] = result
        return result

    def _fetch_pnpm_lockfile_deps(self, *, repo_url: str) -> set[str] | None:
        """Parse `pnpm-lock.yaml` and return the union of direct-dep names
        across every workspace's `importers.<path>` entry.

        pnpm's `importers` map is keyed by workspace path; under each entry
        the `dependencies` / `devDependencies` / `optionalDependencies` /
        `peerDependencies` maps mirror the workspace's `package.json` —
        their keys are exactly the directly-declared deps. Transitive deps
        live under the separate top-level `packages` map and are excluded.

        Returns `None` if the lockfile is missing, unparseable, or empty.
        """
        parsed = _parse_repo_url(repo_url)
        if not parsed:
            return None
        if parsed in self._lockfile_cache:
            return self._lockfile_cache[parsed]
        owner, name = parsed
        url = f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/pnpm-lock.yaml"
        try:
            r = self._client.get(url, headers=self._headers())
            r.raise_for_status()
            doc = yaml.safe_load(r.text)
        except (httpx.HTTPError, yaml.YAMLError) as e:
            log.warning("github_repo.fetch_lockfile_failed", repo=repo_url, error=str(e))
            self._lockfile_cache[parsed] = None
            return None
        if not isinstance(doc, dict):
            self._lockfile_cache[parsed] = None
            self._lockfile_locations_cache[parsed] = None
            return None
        importers = doc.get("importers")
        if not isinstance(importers, dict):
            self._lockfile_cache[parsed] = None
            self._lockfile_locations_cache[parsed] = None
            return None
        names: set[str] = set()
        per_name: dict[str, list[str]] = {}
        for ws_path, imp in importers.items():
            if not isinstance(imp, dict):
                continue
            for section in _PNPM_DEP_SECTIONS:
                m = imp.get(section)
                if isinstance(m, dict):
                    for dep_name in m:
                        names.add(dep_name)
                        per_name.setdefault(dep_name, []).append(str(ws_path))
        if not names:
            self._lockfile_cache[parsed] = None
            self._lockfile_locations_cache[parsed] = None
            return None
        self._lockfile_cache[parsed] = names
        self._lockfile_locations_cache[parsed] = per_name
        return names

    def fetch_direct_deps(self, *, repo_url: str) -> set[str] | None:
        """Return the set of names listed in `dependencies`+`devDependencies`
        of the repo's HEAD `package.json`.

        Returns `None` on transient failure (parse error, network error) so
        callers can treat the result as "unknown — don't filter". When the
        package.json is definitively absent (404) AND no JS lockfile exists
        at root, returns `{NOT_JS_SENTINEL}` — the repo isn't a JS project
        at root, so a SBOM-derived dependent hit there is almost certainly
        transitive and should be dropped. For monorepo roots (a non-empty
        `workspaces` field), tries `pnpm-lock.yaml` first — its `importers`
        map gives every workspace's direct deps in one HTTP fetch, which
        lets the fan-out filter drop transitive-only hits from
        lockfile-derived SBOMs (e.g. an iOS-tooling dep four levels deep
        under Expo). Falls back to `{MONOREPO_SENTINEL}` when the lockfile
        is absent or unparseable so callers still treat the repo as
        "verified, don't filter".
        """
        parsed = _parse_repo_url(repo_url)
        if not parsed:
            return None
        payload = self._fetch_pkg_json(repo_url=repo_url)
        if payload is None:
            # Distinguish "no package.json at root" (404) from transient
            # errors. Only the 404 case is worth probing further.
            if not self._pkg_missing.get(parsed, False):
                return None
            owner, name = parsed
            has_lockfile = self._has_any_root_lockfile(owner=owner, name=name)
            if has_lockfile is False:
                return {NOT_JS_SENTINEL}
            # has_lockfile True (a lockfile exists despite no package.json)
            # or None (couldn't tell) — fail open.
            return None

        # Monorepo detection: `workspaces` may be an array or an object with
        # a `packages` array (Yarn/Lerna style). Either form means this is a
        # monorepo root.
        ws = payload.get("workspaces")
        is_monorepo = (isinstance(ws, list) and bool(ws)) or (
            isinstance(ws, dict)
            and isinstance(ws.get("packages"), list)
            and bool(ws["packages"])
        )
        if is_monorepo:
            lockfile_deps = self._fetch_pnpm_lockfile_deps(repo_url=repo_url)
            if lockfile_deps is not None:
                return lockfile_deps
            return {MONOREPO_SENTINEL}

        deps = payload.get("dependencies")
        dev_deps = payload.get("devDependencies")
        names: set[str] = set()
        if isinstance(deps, dict):
            names |= set(deps.keys())
        if isinstance(dev_deps, dict):
            names |= set(dev_deps.keys())
        return names

    def fetch_dependency_locations(
        self, *, repo_url: str, names: set[str]
    ) -> dict[str, list[DepLocation]]:
        """Return per-name source locations of those deps in the dependent.

        Single-package repos: one `DepLocation(file="package.json", line=N)`
        per requested name (when found). Line is the 1-based line in the
        repo's HEAD `package.json` where `"<name>":` is declared under
        `dependencies` / `devDependencies` / `optionalDependencies` /
        `peerDependencies`.

        Monorepos with a parseable `pnpm-lock.yaml`: one DepLocation per
        workspace whose `package.json` declares the dep. `line` is `None`
        because resolving the per-workspace line would cost an extra HTTP
        fetch per workspace.

        Names not found in the dependent are absent from the result. Repos
        without a parseable manifest return `{}`. The pipeline pairs this
        with the repo's HEAD SHA to build pinned permalinks for the brief.
        """
        parsed = _parse_repo_url(repo_url)
        if not parsed:
            return {}
        payload = self._fetch_pkg_json(repo_url=repo_url)
        if payload is None:
            return {}

        ws = payload.get("workspaces")
        is_monorepo = (isinstance(ws, list) and bool(ws)) or (
            isinstance(ws, dict)
            and isinstance(ws.get("packages"), list)
            and bool(ws["packages"])
        )
        if is_monorepo:
            self._fetch_pnpm_lockfile_deps(repo_url=repo_url)
            per_name = self._lockfile_locations_cache.get(parsed) or {}
            out: dict[str, list[DepLocation]] = {}
            for name in names:
                paths = per_name.get(name)
                if not paths:
                    continue
                # Workspace paths are relative; normalize "" / "." to the
                # repo-root package.json. Otherwise append `/package.json`.
                seen: set[str] = set()
                locs: list[DepLocation] = []
                for p in paths:
                    file = (
                        "package.json"
                        if p in ("", ".")
                        else f"{p.rstrip('/')}/package.json"
                    )
                    if file in seen:
                        continue
                    seen.add(file)
                    locs.append(DepLocation(file=file, line=None))
                if locs:
                    out[name] = locs
            return out

        text = self._pkg_text_cache.get(parsed)
        if not text:
            return {}
        return _scan_package_json_lines(text, names)

    def bench_info(self, *, repo_url: str) -> tuple[bool, str | None]:
        """Detect runnable-benchmark signals in the repo's HEAD package.json.

        Cheap heuristic — no AST, no execution. Reuses the same cached
        `package.json` as `fetch_direct_deps`, so callers that have already
        fan-out-filtered against direct deps pay zero extra HTTP for this.

        Returns `(has_benchmarks, signal)`. `signal` is a short label like
        `"script:bench"` or `"devDep:tinybench"` for the brief render.
        Returns `(False, None)` when unreachable or no signal found.
        """
        payload = self._fetch_pkg_json(repo_url=repo_url)
        if payload is None:
            return (False, None)
        scripts = payload.get("scripts")
        if isinstance(scripts, dict):
            # 1. Script NAME contains "bench" — most direct signal.
            for script_name in scripts:
                if isinstance(script_name, str) and "bench" in script_name.lower():
                    return (True, f"script:{script_name}")
            # 2. Script VALUE invokes vitest/jest in bench mode. Catches the
            #    common case where the script name is generic ("test:perf",
            #    "ci") but the command body runs vitest's bench feature.
            for script_name, script_value in scripts.items():
                if not isinstance(script_name, str) or not isinstance(
                    script_value, str
                ):
                    continue
                for pat in _BENCH_CMD_PATTERNS:
                    if pat.search(script_value):
                        return (True, f"script-cmd:{script_name}")
        # 3. Known bench-only devDep — independent of any script.
        for field in ("devDependencies", "dependencies"):
            section = payload.get(field)
            if isinstance(section, dict):
                for lib in _BENCH_DEV_DEPS:
                    if lib in section:
                        return (True, f"devDep:{lib}")
        return (False, None)

    def close(self) -> None:
        self._client.close()


# Sections we consider "directly declared" — same set as the lockfile parser
# above. Restricting the line scan to these blocks avoids false positives
# from `resolutions`, `overrides`, or string values elsewhere in the file.
_PKG_DEP_SECTION_RE = re.compile(
    r'^\s*"(?P<section>dependencies|devDependencies|optionalDependencies|peerDependencies)"\s*:\s*\{',
    re.MULTILINE,
)


def _scan_package_json_lines(
    text: str, names: set[str]
) -> dict[str, list["DepLocation"]]:
    """Find the line where each requested name is declared in `text`.

    Walks the file once, tracking when we're inside a dependency section
    (dependencies / devDependencies / optionalDependencies /
    peerDependencies). Inside a section, the first key matching `names` at
    that section's depth is recorded. Only the first occurrence per name is
    kept — duplicate declarations across sections are unusual and the
    reviewer can find others by reading the file.
    """
    found: dict[str, list[DepLocation]] = {}
    if not names:
        return found
    in_section: str | None = None
    section_depth = 0
    depth = 0
    key_re = re.compile(r'^\s*"([^"]+)"\s*:')
    for i, line in enumerate(text.splitlines(), start=1):
        if in_section is None:
            if (m := _PKG_DEP_SECTION_RE.match(line)):
                in_section = m.group("section")
                section_depth = line.count("{") - line.count("}")
                depth = section_depth
            continue
        if depth == section_depth and (m := key_re.match(line)):
            key = m.group(1)
            if key in names and key not in found:
                found[key] = [DepLocation(file="package.json", line=i)]
        depth += line.count("{") - line.count("}")
        if depth < section_depth:
            in_section = None
            section_depth = 0
    return found
