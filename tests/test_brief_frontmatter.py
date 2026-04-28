"""Brief frontmatter shape — what an SSG will read.

The frontmatter is the canonical structured metadata for a brief.
The website pipeline parses it directly to build cards, listings, and
filters; the body is "the article". Anything you'd filter or sort on in
the UI must be a frontmatter field, not body prose.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from biibaa.briefs.render import render_brief, write_brief
from biibaa.domain import Advisory, Brief, Opportunity, Project, Replacement

_RUN_AT = datetime(2026, 4, 27, 12, 34, 56, tzinfo=UTC)


def _split_frontmatter(rendered: str) -> tuple[dict, str]:
    """Parse a markdown doc with `---\\n…\\n---\\n` YAML frontmatter."""
    assert rendered.startswith("---\n"), "missing leading frontmatter delimiter"
    end = rendered.index("\n---\n", 4)
    fm = yaml.safe_load(rendered[4:end])
    body = rendered[end + len("\n---\n") :]
    return fm, body


def _project(**overrides) -> Project:
    base = dict(
        purl="pkg:npm/react-redux",
        ecosystem="npm",
        name="react-redux",
        repo_url="https://github.com/reduxjs/react-redux",
        downloads_weekly=8_000_000,
    )
    base.update(overrides)
    return Project(**base)


def _vuln_opp(project: Project, *, advisory: Advisory) -> Opportunity:
    return Opportunity(
        id="o-vuln",
        kind="vulnerability-fix",
        project=project,
        advisory=advisory,
        impact=85.0,
        effort=70.0,
        score=80.0,
        dedupe_key="dk-vuln",
        first_seen_at=_RUN_AT,
        last_seen_at=_RUN_AT,
    )


def _repl_opp(project: Project, *, replacement: Replacement, kind: str) -> Opportunity:
    return Opportunity(
        id=f"o-{replacement.id}",
        kind=kind,  # type: ignore[arg-type]
        project=project,
        replacement=replacement,
        impact=70.0,
        effort=90.0,
        score=78.0,
        dedupe_key=f"dk-{replacement.id}",
        first_seen_at=_RUN_AT,
        last_seen_at=_RUN_AT,
    )


def _brief(opportunities: list[Opportunity], project: Project) -> Brief:
    head = opportunities[0]
    return Brief(
        project=project,
        run_at=_RUN_AT,
        score=head.score,
        impact=head.impact,
        effort=head.effort,
        opportunities=opportunities,
    )


def test_frontmatter_has_canonical_top_level_fields() -> None:
    proj = _project(has_benchmarks=True, bench_signal="devDep:tinybench")
    rep = Replacement(
        id="r-moment",
        from_purl="pkg:npm/moment",
        to_purls=["pkg:npm/date-fns"],
        axis="bloat",
        effort="codemod-available",
        evidence={"manifest": "preferred.json"},
    )
    brief = _brief([_repl_opp(proj, replacement=rep, kind="dep-replacement")], proj)

    fm, _ = _split_frontmatter(render_brief(brief))

    assert fm["schema"] == "biibaa-brief/1"
    assert fm["title"] == "react-redux"
    assert fm["slug"] == "react-redux"
    assert fm["date"] == "2026-04-27"
    assert fm["run_at"].startswith("2026-04-27T12:34:56")


def test_frontmatter_project_block_mirrors_project_fields() -> None:
    proj = _project(downloads_weekly=12_000_000, archived=False)
    rep = Replacement(
        id="r1", from_purl="pkg:npm/x", to_purls=["pkg:npm/<native>"],
        axis="bloat", effort="drop-in", evidence={"manifest": "native.json"},
    )
    brief = _brief([_repl_opp(proj, replacement=rep, kind="dep-replacement")], proj)

    fm, _ = _split_frontmatter(render_brief(brief))

    assert fm["project"] == {
        "purl": "pkg:npm/react-redux",
        "name": "react-redux",
        "ecosystem": "npm",
        "repo_url": "https://github.com/reduxjs/react-redux",
        "downloads_weekly": 12_000_000,
        "archived": False,
    }


def test_frontmatter_score_block_carries_all_axes() -> None:
    proj = _project()
    rep = Replacement(
        id="r1", from_purl="pkg:npm/x", to_purls=["pkg:npm/<native>"],
        axis="bloat", effort="drop-in", evidence={"manifest": "native.json"},
    )
    brief = _brief([_repl_opp(proj, replacement=rep, kind="dep-replacement")], proj)

    fm, _ = _split_frontmatter(render_brief(brief))

    score = fm["score"]
    assert set(score.keys()) == {"total", "impact", "effort", "confidence"}
    assert score["total"] == 78.0
    assert score["impact"] == 70.0
    assert score["effort"] == 90.0


def test_frontmatter_benchmarks_block_present_when_known() -> None:
    proj = _project(has_benchmarks=True, bench_signal="devDep:tinybench")
    rep = Replacement(
        id="r1", from_purl="pkg:npm/x", to_purls=["pkg:npm/<native>"],
        axis="perf", effort="drop-in", evidence={"manifest": "perf.json"},
    )
    brief = _brief([_repl_opp(proj, replacement=rep, kind="perf-replacement")], proj)

    fm, _ = _split_frontmatter(render_brief(brief))

    assert fm["benchmarks"] == {"has": True, "signal": "devDep:tinybench"}


def test_frontmatter_benchmarks_block_omitted_when_unknown() -> None:
    """has_benchmarks=None means we didn't check — distinct from 'no bench found'."""
    proj = _project()
    rep = Replacement(
        id="r1", from_purl="pkg:npm/x", to_purls=["pkg:npm/<native>"],
        axis="bloat", effort="drop-in", evidence={"manifest": "native.json"},
    )
    brief = _brief([_repl_opp(proj, replacement=rep, kind="dep-replacement")], proj)

    fm, _ = _split_frontmatter(render_brief(brief))

    assert "benchmarks" not in fm


def test_frontmatter_tags_cover_axes_bench_and_unpatched() -> None:
    proj = _project(has_benchmarks=True, bench_signal="script:bench")
    unpatched = Advisory(
        id="GHSA-xxxx",
        project_purl=proj.purl,
        summary="RCE",
        fixed_versions=[],  # no upstream fix
    )
    rep_perf = Replacement(
        id="rp", from_purl="pkg:npm/moment", to_purls=["pkg:npm/date-fns"],
        axis="perf", effort="codemod-available", evidence={"manifest": "perf.json"},
    )
    rep_bloat = Replacement(
        id="rb", from_purl="pkg:npm/lodash.x", to_purls=["pkg:npm/<native>"],
        axis="bloat", effort="drop-in", evidence={"manifest": "native.json"},
    )
    brief = _brief(
        [
            _vuln_opp(proj, advisory=unpatched),
            _repl_opp(proj, replacement=rep_perf, kind="perf-replacement"),
            _repl_opp(proj, replacement=rep_bloat, kind="dep-replacement"),
        ],
        proj,
    )

    fm, _ = _split_frontmatter(render_brief(brief))

    tags = set(fm["tags"])
    assert {"npm", "vuln", "perf", "bloat", "bench", "unpatched"} <= tags


def test_frontmatter_citations_dedupe_advisory_and_replacement_links() -> None:
    proj = _project()
    advisory = Advisory(
        id="GHSA-1234", project_purl=proj.purl, summary="x",
        fixed_versions=["1.0.0"],
    )
    rep = Replacement(
        id="r1", from_purl="pkg:npm/x", to_purls=["pkg:npm/<native>"],
        axis="bloat", effort="drop-in", evidence={"manifest": "native.json"},
    )
    # Same advisory id appears twice; same manifest twice.
    brief = _brief(
        [
            _vuln_opp(proj, advisory=advisory),
            _vuln_opp(proj, advisory=advisory),
            _repl_opp(proj, replacement=rep, kind="dep-replacement"),
            _repl_opp(proj, replacement=rep, kind="dep-replacement"),
        ],
        proj,
    )

    fm, _ = _split_frontmatter(render_brief(brief))

    cites = fm["citations"]
    ids = [c["id"] for c in cites]
    assert ids.count("GHSA-1234") == 1
    assert ids.count("native.json") == 1
    advisory_cite = next(c for c in cites if c["id"] == "GHSA-1234")
    assert advisory_cite["type"] == "advisory"
    assert advisory_cite["url"] == "https://github.com/advisories/GHSA-1234"


def test_frontmatter_opportunities_summary_reports_kinds_and_top() -> None:
    proj = _project()
    rep_perf = Replacement(
        id="rp", from_purl="pkg:npm/x", to_purls=["pkg:npm/y"],
        axis="perf", effort="drop-in", evidence={"manifest": "perf.json"},
    )
    rep_bloat = Replacement(
        id="rb", from_purl="pkg:npm/a", to_purls=["pkg:npm/<native>"],
        axis="bloat", effort="drop-in", evidence={"manifest": "native.json"},
    )
    brief = _brief(
        [
            _repl_opp(proj, replacement=rep_perf, kind="perf-replacement"),
            _repl_opp(proj, replacement=rep_bloat, kind="dep-replacement"),
        ],
        proj,
    )

    fm, _ = _split_frontmatter(render_brief(brief))

    assert fm["opportunities"]["count"] == 2
    assert fm["opportunities"]["top_kind"] == "perf-replacement"
    assert sorted(fm["opportunities"]["kinds"]) == [
        "dep-replacement",
        "perf-replacement",
    ]


def test_body_keeps_title_repo_link_and_opportunity_cards_but_drops_metadata_bullets() -> None:
    """Body should be lean: title + repo link + per-opp cards. Bulky metadata
    (score, maintainer-activity, bench, citations) lives in frontmatter."""
    proj = _project(has_benchmarks=True, bench_signal="devDep:tinybench")
    rep = Replacement(
        id="r1", from_purl="pkg:npm/moment", to_purls=["pkg:npm/date-fns"],
        axis="bloat", effort="codemod-available", evidence={"manifest": "preferred.json"},
    )
    brief = _brief([_repl_opp(proj, replacement=rep, kind="dep-replacement")], proj)

    _, body = _split_frontmatter(render_brief(brief))

    assert "# react-redux" in body
    assert "## Top opportunities" in body
    assert "moment" in body and "date-fns" in body
    # Single repo link at the top — the most actionable navigation aid for
    # readers viewing the brief in a site / preview pane.
    assert "**Repo**: [github.com/" in body
    assert proj.repo_url in body
    # Old-format header bullets must be gone — they live in frontmatter now.
    assert "**Score**" not in body
    assert "**Maintainer activity**" not in body
    assert "**Benchmarks**" not in body
    # Citations footer was redundant with inline evidence — also gone.
    assert "## Citations" not in body


def test_body_omits_repo_link_when_repo_url_unset() -> None:
    """No repo URL → no broken link, just go straight from H1 to opportunities."""
    proj = _project(repo_url=None)
    rep = Replacement(
        id="r1", from_purl="pkg:npm/x", to_purls=["pkg:npm/<native>"],
        axis="bloat", effort="drop-in", evidence={"manifest": "native.json"},
    )
    brief = _brief([_repl_opp(proj, replacement=rep, kind="dep-replacement")], proj)

    _, body = _split_frontmatter(render_brief(brief))
    assert "**Repo**" not in body


def test_write_brief_still_writes_dated_file(tmp_path: Path) -> None:
    proj = _project()
    rep = Replacement(
        id="r1", from_purl="pkg:npm/x", to_purls=["pkg:npm/<native>"],
        axis="bloat", effort="drop-in", evidence={"manifest": "native.json"},
    )
    brief = _brief([_repl_opp(proj, replacement=rep, kind="dep-replacement")], proj)

    path = write_brief(brief, tmp_path)

    assert path.name == "2026-04-27.md"
    text = path.read_text()
    fm, body = _split_frontmatter(text)
    assert fm["slug"] == "react-redux"
    assert "## Top opportunities" in body


def test_frontmatter_maintainer_activity_handles_unknown() -> None:
    proj = _project(last_pr_merged_at=None)
    rep = Replacement(
        id="r1", from_purl="pkg:npm/x", to_purls=["pkg:npm/<native>"],
        axis="bloat", effort="drop-in", evidence={"manifest": "native.json"},
    )
    brief = _brief([_repl_opp(proj, replacement=rep, kind="dep-replacement")], proj)

    fm, _ = _split_frontmatter(render_brief(brief))

    assert fm["maintainer_activity"]["label"] == "unknown"
    assert fm["maintainer_activity"]["last_pr_merged_at"] is None
