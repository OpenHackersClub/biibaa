"""Render Brief aggregates to Markdown with YAML frontmatter.

Briefs are emitted as `---\\n<yaml>\\n---\\n\\n<body>` so a downstream
static-site generator (Astro / Eleventy / Hugo / etc.) can build cards,
listings, and filters from the structured frontmatter without having to
parse the body. The body remains plain Markdown for direct reading.

The frontmatter is the canonical source of metadata. The body is the
human-readable per-opportunity detail. Any field that the website needs
to filter or sort on lives in frontmatter; per-opportunity prose stays
in the body.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from biibaa.domain import Brief, Opportunity
from biibaa.scoring import confidence

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

_FRONTMATTER_SCHEMA = "biibaa-brief/1"


def _maintainer_activity(brief: Brief) -> tuple[str, float]:
    last_pr = brief.project.last_pr_merged_at
    conf = confidence(last_pr_merged_at=last_pr, now=brief.run_at)
    if last_pr is None:
        return "unknown", conf
    days = (brief.run_at - last_pr).total_seconds() / 86400.0
    return f"last PR merged {int(days)}d ago", conf


def _build_tags(brief: Brief) -> list[str]:
    tags: set[str] = {brief.project.ecosystem}
    kinds = {o.kind for o in brief.opportunities}
    if "vulnerability-fix" in kinds:
        tags.add("vuln")
    if "perf-replacement" in kinds:
        tags.add("perf")
    if "dep-replacement" in kinds:
        tags.add("bloat")
    if brief.project.has_benchmarks:
        tags.add("bench")
    if any(
        o.advisory and not o.advisory.fixed_versions for o in brief.opportunities
    ):
        tags.add("unpatched")
    if brief.project.archived:
        tags.add("archived")
    return sorted(tags)


def _build_citations(opportunities: list[Opportunity]) -> list[dict[str, str]]:
    """Flat citations list — what a website needs to render evidence links.

    e18e citations deep-link to the from-package's specific entry in the
    manifest (`citation_url` carries `#L<line>` when known) so reviewers
    land on the actual mapping rather than scrolling a 5k-line JSON file.
    """
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for opp in opportunities:
        if opp.advisory:
            url = f"https://github.com/advisories/{opp.advisory.id}"
            key = ("advisory", opp.advisory.id)
            if key not in seen:
                seen.add(key)
                out.append({"type": "advisory", "id": opp.advisory.id, "url": url})
        if opp.replacement:
            manifest = opp.replacement.evidence.get("manifest")
            if not isinstance(manifest, str):
                continue
            citation_url = opp.replacement.evidence.get("citation_url")
            url = (
                citation_url
                if isinstance(citation_url, str)
                else f"https://github.com/e18e/module-replacements/blob/main/manifests/{manifest}"
            )
            from_name = opp.replacement.from_purl.removeprefix("pkg:npm/")
            citation_id = f"{manifest}#{from_name}"
            key = ("e18e-replacement", citation_id)
            if key not in seen:
                seen.add(key)
                out.append(
                    {"type": "e18e-replacement", "id": citation_id, "url": url}
                )
        for loc in opp.dependency_locations:
            anchor = f"#L{loc.line}" if loc.line is not None else ""
            cid = f"{loc.file}{anchor}"
            key = ("dependency-location", cid)
            if key not in seen:
                seen.add(key)
                out.append(
                    {"type": "dependency-location", "id": cid, "url": loc.url}
                )
    return out


def _build_frontmatter(
    brief: Brief, *, activity_label: str, confidence_value: float
) -> dict[str, Any]:
    """Produce the structured frontmatter dict for one brief.

    Datetimes are emitted as ISO 8601 strings so YAML output is stable
    across SSGs (PyYAML can serialize datetime objects natively, but
    different consumers parse the resulting tag inconsistently).
    """
    project = brief.project
    last_pr = project.last_pr_merged_at
    fm: dict[str, Any] = {
        "schema": _FRONTMATTER_SCHEMA,
        "title": project.name,
        "slug": brief.slug,
        "date": brief.run_at.strftime("%Y-%m-%d"),
        "run_at": brief.run_at.isoformat(),
        "project": {
            "purl": project.purl,
            "name": project.name,
            "ecosystem": project.ecosystem,
            "repo_url": project.repo_url,
            "downloads_weekly": project.downloads_weekly,
            "archived": project.archived,
        },
        "score": {
            "total": round(brief.score, 1),
            "impact": round(brief.impact, 1),
            "effort": round(brief.effort, 1),
            "confidence": int(round(confidence_value)),
        },
        "maintainer_activity": {
            "label": activity_label,
            "last_pr_merged_at": last_pr.isoformat() if last_pr else None,
        },
    }
    # Bench section only when we know — None = unknown, omit so consumers
    # can distinguish "we checked, no bench" from "we didn't check".
    if project.has_benchmarks is not None:
        fm["benchmarks"] = {
            "has": project.has_benchmarks,
            "signal": project.bench_signal,
        }
    fm["opportunities"] = {
        "count": len(brief.opportunities),
        "kinds": sorted({o.kind for o in brief.opportunities}),
        "top_kind": brief.opportunities[0].kind if brief.opportunities else None,
    }
    fm["tags"] = _build_tags(brief)
    fm["citations"] = _build_citations(brief.opportunities)
    return fm


def _dump_frontmatter(fm: dict[str, Any]) -> str:
    body = yaml.safe_dump(
        fm,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=200,
    )
    return f"---\n{body}---\n"


def render_brief(brief: Brief) -> str:
    activity_label, confidence_value = _maintainer_activity(brief)
    frontmatter = _dump_frontmatter(
        _build_frontmatter(
            brief,
            activity_label=activity_label,
            confidence_value=confidence_value,
        )
    )
    body = _env.get_template("brief.md.j2").render(
        project=brief.project,
        run_at=brief.run_at,
        opportunities=brief.opportunities,
    )
    return f"{frontmatter}\n{body}"


def write_brief(brief: Brief, out_dir: Path) -> Path:
    """Write the brief as `<out_dir>/<slug>.md`, overwriting any prior run.

    Each project keeps a single file. The previous date-suffixed scheme
    (`<slug>/<date>.md`) accumulated stale files for projects no longer
    eligible — overwriting in place makes the on-disk set match the
    latest run's eligible-projects set.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{brief.slug}.md"
    path.write_text(render_brief(brief))
    return path
