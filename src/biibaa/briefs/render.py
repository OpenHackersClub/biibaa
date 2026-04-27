"""Render Brief aggregates to Markdown using Jinja2."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from biibaa.domain import Brief
from biibaa.scoring import confidence

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _maintainer_activity(brief: Brief) -> tuple[str, float]:
    last_pr = brief.project.last_pr_merged_at
    conf = confidence(last_pr_merged_at=last_pr, now=brief.run_at)
    if last_pr is None:
        return "unknown", conf
    days = (brief.run_at - last_pr).total_seconds() / 86400.0
    return f"last PR merged {int(days)}d ago", conf


def render_brief(brief: Brief) -> str:
    template = _env.get_template("brief.md.j2")
    activity_label, confidence_value = _maintainer_activity(brief)
    return template.render(
        project=brief.project,
        run_at=brief.run_at,
        score=brief.score,
        impact=brief.impact,
        effort=brief.effort,
        confidence_value=confidence_value,
        activity_label=activity_label,
        opportunities=brief.opportunities,
    )


def write_brief(brief: Brief, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{brief.run_at.strftime('%Y-%m-%d')}.md"
    path.write_text(render_brief(brief))
    return path
