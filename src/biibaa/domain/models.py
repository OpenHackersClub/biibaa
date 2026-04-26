from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Ecosystem = Literal["npm", "pypi", "go", "rubygems", "crates", "maven"]
OpportunityKind = Literal["vulnerability-fix", "dep-replacement", "perf-replacement"]
EffortBand = Literal["drop-in", "minor-migration", "codemod-available", "rewrite"]
ReplacementAxis = Literal["bloat", "perf", "maintenance", "security"]
OpportunityState = Literal["new", "acknowledged", "resolved", "rejected", "duplicate"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Project(_Frozen):
    purl: str
    ecosystem: Ecosystem
    name: str
    repo_url: str | None = None
    homepage: str | None = None
    stars: int | None = None
    downloads_weekly: int | None = None
    dependents: int | None = None
    last_release_at: datetime | None = None
    last_commit_at: datetime | None = None
    archived: bool = False


class Advisory(_Frozen):
    id: str
    project_purl: str
    severity: str | None = None
    cvss: float | None = None
    summary: str
    affected_versions: str | None = None
    fixed_versions: list[str] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)
    published_at: datetime | None = None


class Replacement(_Frozen):
    id: str
    from_purl: str
    to_purls: list[str]
    axis: ReplacementAxis
    effort: EffortBand
    evidence: dict[str, str | int | float] = Field(default_factory=dict)


class Opportunity(_Frozen):
    id: str
    kind: OpportunityKind
    project: Project
    advisory: Advisory | None = None
    replacement: Replacement | None = None
    impact: float
    effort: float
    score: float
    dedupe_key: str
    state: OpportunityState = "new"
    first_seen_at: datetime
    last_seen_at: datetime

    @property
    def suggested_pr_title(self) -> str:
        if self.kind == "vulnerability-fix" and self.advisory:
            fixed = self.advisory.fixed_versions[0] if self.advisory.fixed_versions else "fixed"
            return (
                f"fix(deps): bump {self.project.name} to {fixed} "
                f"({self.advisory.id})"
            )
        if self.kind == "dep-replacement" and self.replacement:
            target = self.replacement.to_purls[0].split("/")[-1]
            return f"perf(deps): replace {self.project.name} with {target}"
        return f"chore({self.project.name}): improvement opportunity"


class Brief(_Frozen):
    project: Project
    run_at: datetime
    score: float
    impact: float
    effort: float
    opportunities: list[Opportunity]

    @property
    def slug(self) -> str:
        return self.project.name.replace("/", "__").replace("@", "")
