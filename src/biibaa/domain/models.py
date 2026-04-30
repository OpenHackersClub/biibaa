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
    last_pr_merged_at: datetime | None = None
    archived: bool = False
    has_benchmarks: bool | None = None
    bench_signal: str | None = None


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
    repo_url: str | None = None
    # True when another package in the same GHSA already has a
    # `first_patched_version`. Signals that the upstream project has shipped
    # a fix (typically under a renamed/scoped successor package), so a
    # contributor PR would be redundant.
    has_patched_sibling: bool = False


class Replacement(_Frozen):
    id: str
    from_purl: str
    to_purls: list[str]
    axis: ReplacementAxis
    effort: EffortBand
    evidence: dict[str, str | int | float] = Field(default_factory=dict)


class DependencyLocation(_Frozen):
    """Where a flagged dependency is declared in the dependent's source.

    `file` is the repo-relative path (e.g. `package.json` or
    `packages/foo/package.json`). `line` is 1-based; `None` when we know
    the file but not the exact line (monorepo workspaces parsed from
    `pnpm-lock.yaml`, where we'd have to fetch each workspace's
    `package.json` to find the line). `url` is a permalink pinned to a
    commit SHA so the link doesn't rot when HEAD moves.
    """

    file: str
    line: int | None = None
    url: str


class Opportunity(_Frozen):
    id: str
    kind: OpportunityKind
    project: Project
    advisory: Advisory | None = None
    replacement: Replacement | None = None
    dependency_locations: list[DependencyLocation] = Field(default_factory=list)
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
            if self.advisory.fixed_versions:
                fixed = self.advisory.fixed_versions[0]
                return (
                    f"fix(deps): bump {self.project.name} to {fixed} "
                    f"({self.advisory.id})"
                )
            # Unpatched — the contribution is to write the upstream fix.
            return f"fix: address {self.advisory.id} in {self.project.name}"
        if self.replacement and self.kind in ("dep-replacement", "perf-replacement"):
            from_name = self.replacement.from_purl.removeprefix("pkg:npm/")
            target = self.replacement.to_purls[0].split("/")[-1].lstrip("<").rstrip(">")
            scope = "perf" if self.kind == "perf-replacement" else "deps"
            if target == "native":
                return f"{scope}: drop {from_name} dep (use native API)"
            return f"{scope}(deps): replace {from_name} with {target}"
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
