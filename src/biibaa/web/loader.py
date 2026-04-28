"""Load briefs from disk for the triage webapp.

Each brief is a Markdown file with YAML frontmatter (see
`src/biibaa/briefs/render.py` for the schema). We parse the frontmatter into a
dict suitable for table rendering and keep the body for a detail pane.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DELIM = "---"


@dataclass(frozen=True, slots=True)
class BriefRow:
    path: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def slug(self) -> str:
        return self.frontmatter.get("slug") or self.path.parent.name

    @property
    def date(self) -> str:
        return self.frontmatter.get("date") or ""


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith(_DELIM):
        return {}, text
    parts = text.split(f"\n{_DELIM}\n", 1)
    if len(parts) != 2:
        return {}, text
    head = parts[0].removeprefix(_DELIM).lstrip("\n")
    fm = yaml.safe_load(head) or {}
    if not isinstance(fm, dict):
        return {}, text
    return fm, parts[1].lstrip("\n")


def load_briefs(briefs_dir: Path) -> list[BriefRow]:
    rows: list[BriefRow] = []
    for path in sorted(briefs_dir.rglob("*.md")):
        text = path.read_text()
        fm, body = _split_frontmatter(text)
        rows.append(BriefRow(path=path, frontmatter=fm, body=body))
    return rows


def latest_per_slug(rows: list[BriefRow]) -> list[BriefRow]:
    by_slug: dict[str, BriefRow] = {}
    for r in rows:
        existing = by_slug.get(r.slug)
        if existing is None or r.date > existing.date:
            by_slug[r.slug] = r
    return sorted(by_slug.values(), key=lambda r: r.slug)
