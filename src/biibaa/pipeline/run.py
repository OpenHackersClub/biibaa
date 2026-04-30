"""End-to-end pipeline: ingest → fan-out → score → brief.

Each emitted brief points at one specific repo a contributor can PR:
- Vuln briefs name the source repo of the vulnerable package
  (`Advisory.repo_url`, from GHSA `source_code_location`).
- Replacement briefs name the *dependent* project that still uses the
  flagged package — discovered via ecosyste.ms fan-out — not the
  flagged package itself. PRing isarray to "deprecate yourself" is
  pointless; PRing a popular consumer to drop isarray for the native
  API is the actual contribution.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog

from biibaa.adapters._semver import is_version_in_range
from biibaa.adapters.dependents_factory import build_dependents_source
from biibaa.adapters.e18e import E18eReplacementsSource
from biibaa.adapters.github_advisories import GithubAdvisorySource
from biibaa.adapters.github_repo import (
    MONOREPO_SENTINEL,
    NOT_JS_SENTINEL,
    DepLocation,
    GithubRepoSource,
)
from biibaa.adapters.npm_downloads import NpmDownloadsSource
from biibaa.adapters.npm_registry import NpmRegistrySource
from biibaa.briefs.render import write_brief
from biibaa.domain import (
    Advisory,
    Brief,
    DependencyLocation,
    Opportunity,
    Project,
    Replacement,
)
from biibaa.ports.dependents import Dependent, DependentsSource
from biibaa.scoring import (
    REPLACEMENT_EFFORT_SCORE,
    confidence,
    effort_score,
    final_score,
    impact,
    popularity,
    replacement_effort_score,
    replacement_severity,
    severity_score,
)

log = structlog.get_logger(__name__)


@dataclass
class _ProjectFindings:
    advisories: list[Advisory] = field(default_factory=list)
    replacements: list[Replacement] = field(default_factory=list)
    repo_url: str | None = None
    # Per-replacement.from_purl → adapter-level locations within the
    # dependent's repo. Built during fan-out (one call per dependent
    # reusing the cached package.json text), then converted to
    # `DependencyLocation` records with pinned-SHA URLs at opportunity
    # construction time.
    locations_by_from_purl: dict[str, list[DepLocation]] = field(default_factory=dict)


def _project_name_from_purl(purl: str) -> str:
    # Pyoso dependents arrive as `pkg:github/owner/repo`; ecosyste.ms as
    # `pkg:npm/name`. Strip whichever prefix matches so slugs and download
    # lookups use the canonical short form.
    return purl.removeprefix("pkg:npm/").removeprefix("pkg:github/")


def _project_from(
    purl: str,
    ecosystem: str,
    downloads: int | None,
    repo_url: str | None,
    *,
    last_pr_merged_at: datetime | None = None,
    archived: bool = False,
    has_benchmarks: bool | None = None,
    bench_signal: str | None = None,
) -> Project:
    return Project(
        purl=purl,
        ecosystem=ecosystem,  # type: ignore[arg-type]
        name=_project_name_from_purl(purl),
        downloads_weekly=downloads,
        repo_url=repo_url,
        last_pr_merged_at=last_pr_merged_at,
        archived=archived,
        has_benchmarks=has_benchmarks,
        bench_signal=bench_signal,
    )


def _is_eligible(project: Project, *, min_weekly_downloads: int) -> bool:
    """Drop archived repos and packages below the weekly-downloads floor.

    Unknown downloads (None) pass through — better to over-include than to
    silently drop a project on a transient npm registry hiccup.
    """
    if project.archived:
        return False
    return not (
        project.downloads_weekly is not None
        and project.downloads_weekly < min_weekly_downloads
    )


def _vuln_opportunity(
    *, advisory: Advisory, project: Project, run_at: datetime
) -> Opportunity:
    pop = popularity(downloads_weekly=project.downloads_weekly, stars=project.stars)
    sev = severity_score(cvss=advisory.cvss)
    eff = effort_score(
        fixed_versions=advisory.fixed_versions, advisory_summary=advisory.summary
    )
    imp = impact(pop=pop, sev=sev)
    conf = confidence(last_pr_merged_at=project.last_pr_merged_at, now=run_at)
    score = final_score(impact_value=imp, effort_value=eff, confidence_value=conf)
    return Opportunity(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{project.purl}|{advisory.id}")),
        kind="vulnerability-fix",
        project=project,
        advisory=advisory,
        impact=imp,
        effort=eff,
        score=score,
        dedupe_key=f"{project.purl}|{advisory.id}",
        first_seen_at=run_at,
        last_seen_at=run_at,
    )


def _build_dependency_locations(
    *,
    repo_url: str | None,
    head_sha: str | None,
    locations: list[DepLocation],
) -> list[DependencyLocation]:
    """Convert adapter-level locations into pinned-SHA permalinks.

    Falls back to `HEAD` when the SHA is unknown (e.g. GraphQL miss). Repos
    without a known repo_url get no locations — we have no base for the
    permalink. Empty list when there are no input locations.
    """
    if not repo_url or not locations:
        return []
    base = repo_url.rstrip("/")
    ref = head_sha or "HEAD"
    out: list[DependencyLocation] = []
    for loc in locations:
        url = f"{base}/blob/{ref}/{loc.file}"
        if loc.line is not None:
            url = f"{url}#L{loc.line}"
        out.append(DependencyLocation(file=loc.file, line=loc.line, url=url))
    return out


def _replacement_opportunity(
    *,
    replacement: Replacement,
    project: Project,
    run_at: datetime,
    head_sha: str | None,
    locations: list[DepLocation],
) -> Opportunity:
    pop = popularity(downloads_weekly=project.downloads_weekly, stars=project.stars)
    is_native = any("<native>" in p for p in replacement.to_purls)
    sev = replacement_severity(axis=replacement.axis, native=is_native)
    eff = replacement_effort_score(band=replacement.effort)
    imp = impact(pop=pop, sev=sev)
    conf = confidence(last_pr_merged_at=project.last_pr_merged_at, now=run_at)
    score = final_score(impact_value=imp, effort_value=eff, confidence_value=conf)
    kind = "perf-replacement" if replacement.axis == "perf" else "dep-replacement"
    dep_locations = _build_dependency_locations(
        repo_url=project.repo_url, head_sha=head_sha, locations=locations
    )
    return Opportunity(
        id=str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{project.purl}|{replacement.id}")
        ),
        kind=kind,
        project=project,
        replacement=replacement,
        dependency_locations=dep_locations,
        impact=imp,
        effort=eff,
        score=score,
        dedupe_key=f"{project.purl}|{replacement.id}",
        first_seen_at=run_at,
        last_seen_at=run_at,
    )


def _dedupe_advisories(advs: list[Advisory]) -> list[Advisory]:
    """Same GHSA id can appear once per affected version range — keep the first."""
    unique: dict[str, Advisory] = {}
    for a in advs:
        unique.setdefault(a.id, a)
    return list(unique.values())


def _drop_outdated_unpatched(
    advisories: list[Advisory], registry: NpmRegistrySource
) -> list[Advisory]:
    """Drop unpatched advisories whose affected range no longer covers `latest`.

    GHSA frequently leaves `first_patched_version` null after a project moves
    past the affected range without backporting a fix. Those records aren't
    a contribution opportunity — users who upgrade are no longer exposed.
    """
    purls = sorted(
        {a.project_purl for a in advisories if a.affected_versions}
    )
    names = [_project_name_from_purl(p) for p in purls]
    latest_by_name = registry.latest_versions(packages=names)

    kept: list[Advisory] = []
    dropped = 0
    for a in advisories:
        if not a.affected_versions:
            kept.append(a)
            continue
        latest = latest_by_name.get(_project_name_from_purl(a.project_purl))
        if latest is None:
            kept.append(a)
            continue
        in_range = is_version_in_range(latest, a.affected_versions)
        if in_range is False:
            log.info(
                "advisory.dropped_outdated",
                ghsa=a.id,
                purl=a.project_purl,
                latest=latest,
                range=a.affected_versions,
            )
            dropped += 1
            continue
        kept.append(a)
    log.info("advisory.outdated_filter", kept=len(kept), dropped=dropped)
    return kept


def _drop_when_sibling_patched(advisories: list[Advisory]) -> list[Advisory]:
    """Drop unpatched advisories whose GHSA has a patched sibling package.

    GHSA records often pair an abandoned package (e.g. `xmldom`) with a
    renamed/scoped successor (`@xmldom/xmldom`) that ships the fix. Both
    point at the same upstream repo, so a contributor PR to that repo is
    redundant — the work is already done.
    """
    kept: list[Advisory] = []
    dropped = 0
    for a in advisories:
        if a.has_patched_sibling:
            log.info(
                "advisory.dropped_sibling_patched",
                ghsa=a.id,
                purl=a.project_purl,
            )
            dropped += 1
            continue
        kept.append(a)
    log.info("advisory.sibling_patched_filter", kept=len(kept), dropped=dropped)
    return kept


def _dedupe_replacements(reps: list[Replacement]) -> list[Replacement]:
    """Same from_purl can appear in multiple manifests — keep the easiest effort."""
    by_from: dict[str, Replacement] = {}
    for r in reps:
        prev = by_from.get(r.from_purl)
        if (
            prev is None
            or REPLACEMENT_EFFORT_SCORE.get(r.effort, 0)
            > REPLACEMENT_EFFORT_SCORE.get(prev.effort, 0)
        ):
            by_from[r.from_purl] = r
    return list(by_from.values())


def _select_with_axis_quota(
    briefs: list[Brief], *, top_n: int, replacement_quota: int
) -> list[Brief]:
    """Pick top-N briefs honoring a minimum quota for replacement-led briefs."""
    vuln_briefs = [b for b in briefs if b.opportunities[0].kind == "vulnerability-fix"]
    repl_briefs = [b for b in briefs if b.opportunities[0].kind != "vulnerability-fix"]
    repl_take = min(replacement_quota, len(repl_briefs))
    vuln_take = top_n - repl_take
    if vuln_take > len(vuln_briefs):
        spillover = vuln_take - len(vuln_briefs)
        vuln_take = len(vuln_briefs)
        repl_take = min(repl_take + spillover, len(repl_briefs))
    chosen = vuln_briefs[:vuln_take] + repl_briefs[:repl_take]
    chosen.sort(key=lambda b: b.score, reverse=True)
    return chosen


def _fan_out_dependents(
    *,
    replacements: list[Replacement],
    eco_src: DependentsSource,
    downloads_src: NpmDownloadsSource,
    fanout_top_n: int,
    dependents_per_replacement: int,
    repo_src: GithubRepoSource | None = None,
) -> tuple[
    list[tuple[Replacement, Dependent]],
    dict[tuple[str, str], list[DepLocation]],
]:
    """For the most-popular replacement candidates, pull top dependents.

    `fanout_top_n` caps how many e18e mappings we fan out from (ranked by
    the from-package's weekly downloads). Without this cap the API
    budget is too large.

    When `repo_src` is provided, candidates are verified against each
    dependent's HEAD `package.json` so we drop hits that only have the
    flagged package as a *transitive* dep (OSO's `sboms_v0` is
    lockfile-derived and includes the full tree).
    """
    deduped = _dedupe_replacements(replacements)

    # Rank from_pkgs by weekly downloads to pick which to fan out from.
    from_names = [_project_name_from_purl(r.from_purl) for r in deduped]
    bulk = downloads_src.weekly_downloads_bulk(packages=from_names)
    ranked = sorted(
        deduped,
        key=lambda r: bulk.get(_project_name_from_purl(r.from_purl)) or 0,
        reverse=True,
    )[:fanout_top_n]

    candidates: list[tuple[Replacement, Dependent]] = []
    for r in ranked:
        name = _project_name_from_purl(r.from_purl)
        deps = eco_src.fetch_dependents(package=name, top_k=dependents_per_replacement)
        log.info("fanout.dependents", from_pkg=name, count=len(deps))
        for d in deps:
            candidates.append((r, d))

    locations: dict[tuple[str, str], list[DepLocation]] = {}
    if repo_src is None:
        return candidates, locations

    out: list[tuple[Replacement, Dependent]] = []
    kept = dropped = unknown = monorepo = not_js = 0
    for rep, dep in candidates:
        from_name = _project_name_from_purl(rep.from_purl)
        if not dep.repo_url:
            # No repo URL — can't verify, keep it.
            unknown += 1
            kept += 1
            out.append((rep, dep))
            continue
        direct = repo_src.fetch_direct_deps(repo_url=dep.repo_url)
        if direct is None:
            unknown += 1
            kept += 1
            out.append((rep, dep))
            continue
        if NOT_JS_SENTINEL in direct:
            log.info(
                "fanout.dropped_not_js_at_root",
                from_pkg=from_name,
                dependent=dep.name,
                repo_url=dep.repo_url,
            )
            not_js += 1
            dropped += 1
            continue
        if MONOREPO_SENTINEL in direct:
            monorepo += 1
            kept += 1
            out.append((rep, dep))
            continue
        if from_name in direct:
            kept += 1
            out.append((rep, dep))
            # Reuse the cached package.json text / lockfile parse to grab
            # source locations now — once we leave this loop we'd otherwise
            # have to rediscover which (rep, dep) pairs are paired up.
            found = repo_src.fetch_dependency_locations(
                repo_url=dep.repo_url, names={from_name}
            )
            if locs := found.get(from_name):
                locations[(dep.purl, rep.from_purl)] = locs
            continue
        log.info(
            "fanout.dropped_transitive_only",
            from_pkg=from_name,
            dependent=dep.name,
            repo_url=dep.repo_url,
        )
        dropped += 1
    log.info(
        "fanout.direct_deps_filter",
        kept=kept,
        dropped=dropped,
        unknown=unknown,
        monorepo=monorepo,
        not_js=not_js,
    )
    return out, locations


def run(
    *,
    output_dir: Path,
    top_n: int = 20,
    ecosystem: str = "npm",
    advisory_limit: int = 400,
    include_replacements: bool = True,
    max_opps_per_project: int = 6,
    fanout_top_n: int = 40,
    dependents_per_replacement: int = 5,
    min_weekly_downloads: int = 50_000,
    land_raw: bool = False,
    raw_root: Path | None = None,
) -> list[Path]:
    """Pull advisories + replacement-fan-outs, score, render top-N briefs."""
    run_at = datetime.now(UTC)
    log.info("pipeline.start", ecosystem=ecosystem, top_n=top_n)

    advisory_src = GithubAdvisorySource()
    downloads_src = NpmDownloadsSource()
    registry_src = NpmRegistrySource() if ecosystem == "npm" else None
    e18e_src = E18eReplacementsSource() if include_replacements else None
    eco_src: DependentsSource | None = (
        build_dependents_source() if include_replacements else None
    )
    repo_src = GithubRepoSource()

    advisories: list[Advisory] = list(
        advisory_src.fetch(ecosystem=ecosystem, limit=advisory_limit)
    )
    log.info("pipeline.advisories_fetched", count=len(advisories))
    advisories = _drop_when_sibling_patched(advisories)
    if registry_src:
        advisories = _drop_outdated_unpatched(advisories, registry_src)

    replacements: list[Replacement] = []
    if e18e_src:
        replacements = list(e18e_src.fetch())
        log.info("pipeline.replacements_fetched", count=len(replacements))

    fanouts: list[tuple[Replacement, Dependent]] = []
    fanout_locations: dict[tuple[str, str], list[DepLocation]] = {}
    if eco_src and replacements:
        fanouts, fanout_locations = _fan_out_dependents(
            replacements=replacements,
            eco_src=eco_src,
            downloads_src=downloads_src,
            fanout_top_n=fanout_top_n,
            dependents_per_replacement=dependents_per_replacement,
            repo_src=repo_src,
        )
        log.info("pipeline.fanouts_built", count=len(fanouts))

    # Aggregate by project.  Vuln projects keyed by package purl; replacement
    # projects keyed by *dependent* purl.
    by_project: dict[str, _ProjectFindings] = defaultdict(_ProjectFindings)
    for a in advisories:
        f = by_project[a.project_purl]
        f.advisories.append(a)
        if a.repo_url and not f.repo_url:
            f.repo_url = a.repo_url
    for rep, dep in fanouts:
        f = by_project[dep.purl]
        f.replacements.append(rep)
        if dep.repo_url and not f.repo_url:
            f.repo_url = dep.repo_url
        if locs := fanout_locations.get((dep.purl, rep.from_purl)):
            f.locations_by_from_purl.setdefault(rep.from_purl, locs)

    # Hydrate weekly downloads for every project we'll render.
    package_names = [_project_name_from_purl(p) for p in by_project]
    bulk_downloads = downloads_src.weekly_downloads_bulk(packages=package_names)

    projects: dict[str, Project] = {}
    head_shas: dict[str, str | None] = {}
    for purl, findings in by_project.items():
        name = _project_name_from_purl(purl)
        meta = (
            repo_src.fetch_meta(repo_url=findings.repo_url)
            if findings.repo_url
            else None
        )
        head_shas[purl] = meta.head_sha if meta else None
        # Only read bench info for replacement-driven projects: fan-out has
        # already fetched their package.json so this is a free cache hit.
        # Skipping vuln-only projects keeps the HTTP budget unchanged.
        has_bench: bool | None = None
        bench_signal: str | None = None
        if findings.repo_url and findings.replacements:
            has_bench, bench_signal = repo_src.bench_info(repo_url=findings.repo_url)
        projects[purl] = _project_from(
            purl,
            ecosystem,
            bulk_downloads.get(name),
            findings.repo_url,
            last_pr_merged_at=meta.last_merged_pr_at if meta else None,
            archived=meta.is_archived if meta else False,
            has_benchmarks=has_bench,
            bench_signal=bench_signal,
        )

    skipped = sum(
        1
        for p in projects.values()
        if not _is_eligible(p, min_weekly_downloads=min_weekly_downloads)
    )
    log.info(
        "pipeline.eligibility_filter",
        kept=len(projects) - skipped,
        skipped=skipped,
        min_weekly_downloads=min_weekly_downloads,
    )

    # Land raw Parquet *before* eligibility / scoring filters so the warehouse
    # holds the full source-of-truth snapshot — downstream SQLMesh marts can
    # re-derive eligibility without forcing another ingest pass.
    if land_raw:
        from biibaa.warehouse import (
            land_advisories,
            land_dependents,
            land_projects,
            land_replacements,
        )

        target_root = raw_root or Path("data/raw")
        land_advisories(advisories, raw_root=target_root)
        land_projects(projects.values(), raw_root=target_root)
        land_replacements(replacements, raw_root=target_root)
        # Dependents fan-out keyed by the *source* package (rep.from_purl);
        # one rep can surface multiple dependents and one source can have
        # multiple replacement targets, so dedupe per (parent, dependent).
        fan_out: dict[str, list[Dependent]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        for rep, dep in fanouts:
            key = (rep.from_purl, dep.purl)
            if key in seen:
                continue
            seen.add(key)
            fan_out[rep.from_purl].append(dep)
        land_dependents(fan_out, raw_root=target_root)

    # Build opportunities + briefs.
    briefs: list[Brief] = []
    for purl, findings in by_project.items():
        project = projects[purl]
        if not _is_eligible(project, min_weekly_downloads=min_weekly_downloads):
            continue
        opps: list[Opportunity] = []
        for adv in _dedupe_advisories(findings.advisories):
            opps.append(_vuln_opportunity(advisory=adv, project=project, run_at=run_at))
        # Per-dependent: dedupe replacements by from_purl so the same swap
        # only appears once even if the dependent showed up in two manifests.
        head_sha = head_shas.get(purl)
        for rep in _dedupe_replacements(findings.replacements):
            opps.append(
                _replacement_opportunity(
                    replacement=rep,
                    project=project,
                    run_at=run_at,
                    head_sha=head_sha,
                    locations=findings.locations_by_from_purl.get(rep.from_purl, []),
                )
            )

        if not opps:
            continue
        opps.sort(key=lambda o: o.score, reverse=True)
        opps = opps[:max_opps_per_project]
        head = opps[0]
        briefs.append(
            Brief(
                project=project,
                run_at=run_at,
                score=head.score,
                impact=head.impact,
                effort=head.effort,
                opportunities=opps,
            )
        )

    briefs.sort(key=lambda b: b.score, reverse=True)
    top = _select_with_axis_quota(briefs, top_n=top_n, replacement_quota=top_n // 3)
    log.info(
        "pipeline.briefs_selected",
        total=len(briefs),
        top=len(top),
        vuln=sum(1 for b in top if b.opportunities[0].kind == "vulnerability-fix"),
        replacement=sum(
            1 for b in top if b.opportunities[0].kind != "vulnerability-fix"
        ),
    )

    paths: list[Path] = []
    for brief in top:
        paths.append(write_brief(brief, output_dir / brief.project.ecosystem))

    # Sweep stale briefs: any *.md in this ecosystem's dir that we didn't
    # write this run is from a project no longer eligible (or no longer in
    # the top-N). Without this step the on-disk set would only ever grow.
    eco_dir = output_dir / ecosystem
    if eco_dir.is_dir():
        kept = {p.resolve() for p in paths}
        removed = 0
        for stale in eco_dir.glob("*.md"):
            if stale.resolve() not in kept:
                stale.unlink()
                removed += 1
        if removed:
            log.info("pipeline.briefs_swept", removed=removed, ecosystem=ecosystem)

    advisory_src.close()
    downloads_src.close()
    if registry_src:
        registry_src.close()
    repo_src.close()
    if e18e_src:
        e18e_src.close()
    if eco_src:
        eco_src.close()
    log.info("pipeline.done", output_dir=str(output_dir), count=len(paths))
    return paths
