"""End-to-end pipeline: ingest → score → brief.

This is the MVP path. The full SPEC §5 pipeline (raw Parquet → SQLMesh staging
→ marts → briefs) lands in follow-up PRs. For now we do everything in-memory
and write briefs directly to disk.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import structlog

from biibaa.adapters.github_advisories import GithubAdvisorySource
from biibaa.adapters.npm_downloads import NpmDownloadsSource
from biibaa.briefs.render import write_brief
from biibaa.domain import Advisory, Brief, Opportunity, Project
from biibaa.scoring import effort_score, final_score, impact, popularity, severity_score

log = structlog.get_logger(__name__)


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
    # pkg:npm/<name>  or  pkg:npm/@scope%2Fname  — we keep the raw URL-ish form here
    return purl.removeprefix("pkg:npm/")


def _project_from(purl: str, ecosystem: str, downloads: int | None) -> Project:
    return Project(
        purl=purl,
        ecosystem=ecosystem,  # type: ignore[arg-type]
        name=_project_name_from_purl(purl),
        downloads_weekly=downloads,
    )


def _opportunity_from(
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


def run(
    *,
    output_dir: Path,
    top_n: int = 20,
    ecosystem: str = "npm",
    advisory_limit: int = 400,
) -> list[Path]:
    """Pull advisories, score, render top-N briefs. Returns brief paths."""
    run_at = datetime.now(UTC)
    log.info("pipeline.start", ecosystem=ecosystem, top_n=top_n)

    advisory_src = GithubAdvisorySource()
    downloads_src = NpmDownloadsSource()

    advisories: list[Advisory] = list(
        advisory_src.fetch(ecosystem=ecosystem, limit=advisory_limit)
    )
    log.info("pipeline.advisories_fetched", count=len(advisories))

    # Group by project — one brief per project, opportunities sorted within.
    by_project: dict[str, list[Advisory]] = defaultdict(list)
    for adv in advisories:
        by_project[adv.project_purl].append(adv)

    # Hydrate downloads per package.
    projects: dict[str, Project] = {}
    for purl in by_project:
        name = _project_name_from_purl(purl)
        downloads = downloads_src.weekly_downloads(package=name)
        projects[purl] = _project_from(purl, ecosystem, downloads)

    # Build opportunities and per-project briefs.
    briefs: list[Brief] = []
    max_opps_per_project = 5
    for purl, advs in by_project.items():
        project = projects[purl]
        # Dedupe: same advisory id can appear once per affected version range.
        # Keep the entry with the highest fix version (latest line covered).
        unique: dict[str, Advisory] = {}
        for a in advs:
            existing = unique.get(a.id)
            if existing is None or _max_fix(a) > _max_fix(existing):
                unique[a.id] = a
        opps = sorted(
            (
                _opportunity_from(advisory=a, project=project, run_at=run_at)
                for a in unique.values()
            ),
            key=lambda o: o.score,
            reverse=True,
        )[:max_opps_per_project]
        if not opps:
            continue
        # Brief-level scores: max opp score (the headline opportunity)
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
    top = briefs[:top_n]
    log.info("pipeline.briefs_selected", total=len(briefs), top=len(top))

    out_dir = output_dir / run_at.strftime("%Y-%m-%d")
    paths: list[Path] = []
    for brief in top:
        paths.append(write_brief(brief, out_dir))

    advisory_src.close()
    downloads_src.close()
    log.info("pipeline.done", out_dir=str(out_dir), count=len(paths))
    return paths
