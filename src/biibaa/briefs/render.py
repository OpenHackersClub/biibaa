"""Render Brief aggregates to Markdown using Jinja2."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from biibaa.domain import Brief

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_brief(brief: Brief) -> str:
    template = _env.get_template("brief.md.j2")
    return template.render(
        project=brief.project,
        run_at=brief.run_at,
        score=brief.score,
        impact=brief.impact,
        effort=brief.effort,
        opportunities=brief.opportunities,
    )


def write_brief(brief: Brief, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{brief.slug}.md"
    path.write_text(render_brief(brief))
    return path
