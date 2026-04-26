"""End-to-end pipeline: ingest → score → brief.

This is the MVP path. The full SPEC §5 pipeline (raw Parquet → SQLMesh staging
→ marts → briefs) lands in follow-up PRs. For now we do everything in-memory
and write briefs directly to disk.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog

from biibaa.adapters.e18e import E18eReplacementsSource
from biibaa.adapters.github_advisories import GithubAdvisorySource
from biibaa.adapters.npm_downloads import NpmDownloadsSource
from biibaa.briefs.render import write_brief
from biibaa.domain import Advisory, Brief, Opportunity, Project, Replacement
from biibaa.scoring import (
    REPLACEMENT_EFFORT_SCORE,
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


def _max_fix(a: Advisory) -> tuple[int, ...]:
    """Sortable version tuple of the highest fixed version, for dedupe tie-breaks."""
    if not a.fixed_versions:
        return (0,)
    parts = a.fixed_versions[0].split(".")
    out: list[int] = []
    for p in parts:
        digits = "".join(ch for ch in p if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _project_name_from_purl(purl: str) -> str:
    return purl.removeprefix("pkg:npm/")


def _project_from(purl: str, ecosystem: str, downloads: int | None) -> Project:
    return Project(
        purl=purl,
        ecosystem=ecosystem,  # type: ignore[arg-type]
        name=_project_name_from_purl(purl),
        downloads_weekly=downloads,
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
    score = final_score(impact_value=imp, effort_value=eff)
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


def _replacement_opportunity(
    *, replacement: Replacement, project: Project, run_at: datetime
) -> Opportunity:
    pop = popularity(downloads_weekly=project.downloads_weekly, stars=project.stars)
    is_native = any("<native>" in p for p in replacement.to_purls)
    sev = replacement_severity(axis=replacement.axis, native=is_native)
    eff = replacement_effort_score(band=replacement.effort)
    imp = impact(pop=pop, sev=sev)
    score = final_score(impact_value=imp, effort_value=eff)
    kind = "perf-replacement" if replacement.axis == "perf" else "dep-replacement"
    return Opportunity(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, replacement.id)),
        kind=kind,
        project=project,
        replacement=replacement,
        impact=imp,
        effort=eff,
        score=score,
        dedupe_key=replacement.id,
        first_seen_at=run_at,
        last_seen_at=run_at,
    )


def _dedupe_advisories(advs: list[Advisory]) -> list[Advisory]:
    """Same GHSA id can appear once per affected version range — keep the highest fix."""
    unique: dict[str, Advisory] = {}
    for a in advs:
        existing = unique.get(a.id)
        if existing is None or _max_fix(a) > _max_fix(existing):
            unique[a.id] = a
    return list(unique.values())


def _select_with_axis_quota(
    briefs: list[Brief], *, top_n: int, replacement_quota: int
) -> list[Brief]:
    """Pick top-N briefs honoring a minimum quota for replacement-led briefs.

    Without this, vulnerability fixes (CVSS-driven severity) crowd out bloat/perf
    replacements (baseline severity). The user wants to see both kinds.
    """
    vuln_briefs = [b for b in briefs if b.opportunities[0].kind == "vulnerability-fix"]
    repl_briefs = [b for b in briefs if b.opportunities[0].kind != "vulnerability-fix"]
    repl_take = min(replacement_quota, len(repl_briefs))
    vuln_take = top_n - repl_take
    if vuln_take > len(vuln_briefs):
        # Replacement pool can backfill if we run out of vuln briefs.
        spillover = vuln_take - len(vuln_briefs)
        vuln_take = len(vuln_briefs)
        repl_take = min(repl_take + spillover, len(repl_briefs))
    chosen = vuln_briefs[:vuln_take] + repl_briefs[:repl_take]
    chosen.sort(key=lambda b: b.score, reverse=True)
    return chosen


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


def run(
    *,
    output_dir: Path,
    top_n: int = 20,
    ecosystem: str = "npm",
    advisory_limit: int = 400,
    include_replacements: bool = True,
    max_opps_per_project: int = 6,
) -> list[Path]:
    """Pull advisories + replacements, score, render top-N briefs."""
    run_at = datetime.now(UTC)
    log.info("pipeline.start", ecosystem=ecosystem, top_n=top_n)

    advisory_src = GithubAdvisorySource()
    downloads_src = NpmDownloadsSource()
    e18e_src = E18eReplacementsSource() if include_replacements else None

    advisories: list[Advisory] = list(
        advisory_src.fetch(ecosystem=ecosystem, limit=advisory_limit)
    )
    log.info("pipeline.advisories_fetched", count=len(advisories))

    replacements: list[Replacement] = []
    if e18e_src:
        replacements = list(e18e_src.fetch())
        log.info("pipeline.replacements_fetched", count=len(replacements))

    # Aggregate findings per project.
    by_project: dict[str, _ProjectFindings] = defaultdict(_ProjectFindings)
    for a in advisories:
        by_project[a.project_purl].advisories.append(a)
    for r in replacements:
        by_project[r.from_purl].replacements.append(r)

    # Hydrate popularity once per project (bulk where possible).
    package_names = [_project_name_from_purl(p) for p in by_project]
    bulk_downloads = downloads_src.weekly_downloads_bulk(packages=package_names)
    projects: dict[str, Project] = {}
    for purl in by_project:
        name = _project_name_from_purl(purl)
        projects[purl] = _project_from(purl, ecosystem, bulk_downloads.get(name))

    # Build opportunities + briefs.
    briefs: list[Brief] = []
    for purl, findings in by_project.items():
        project = projects[purl]
        opps: list[Opportunity] = []

        for adv in _dedupe_advisories(findings.advisories):
            opps.append(_vuln_opportunity(advisory=adv, project=project, run_at=run_at))
        for rep in _dedupe_replacements(findings.replacements):
            opps.append(
                _replacement_opportunity(replacement=rep, project=project, run_at=run_at)
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

    out_dir = output_dir / run_at.strftime("%Y-%m-%d")
    paths: list[Path] = []
    for brief in top:
        paths.append(write_brief(brief, out_dir))

    advisory_src.close()
    downloads_src.close()
    if e18e_src:
        e18e_src.close()
    log.info("pipeline.done", out_dir=str(out_dir), count=len(paths))
    return paths
