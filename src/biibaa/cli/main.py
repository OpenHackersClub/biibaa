from __future__ import annotations

import logging
from pathlib import Path

import structlog
import typer
from dotenv import load_dotenv

from biibaa.pipeline.run import run as run_pipeline

load_dotenv()

app = typer.Typer(help="biibaa — open source improvement opportunity tracker")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


@app.command()
def run(
    output_dir: Path = typer.Option(
        Path("data/briefs"), "--out", help="Brief output directory"
    ),
    top_n: int = typer.Option(1000, "--top", help="Number of briefs to render"),
    ecosystem: str = typer.Option("npm", "--ecosystem"),
    advisory_limit: int = typer.Option(
        2000, "--advisory-limit", help="Max advisories to ingest"
    ),
    fanout_top_n: int = typer.Option(
        647, "--fanout-top-n", help="Number of e18e replacements to fan out from"
    ),
    dependents_per_replacement: int = typer.Option(
        30, "--dependents-per-replacement", help="Top-K dependents per replacement"
    ),
    min_weekly_downloads: int = typer.Option(
        50_000, "--min-weekly-downloads", help="Drop projects below this floor"
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Ingest advisories, score, and render top-N improvement briefs."""
    _configure_logging(verbose)
    paths = run_pipeline(
        output_dir=output_dir,
        top_n=top_n,
        ecosystem=ecosystem,
        advisory_limit=advisory_limit,
        fanout_top_n=fanout_top_n,
        dependents_per_replacement=dependents_per_replacement,
        min_weekly_downloads=min_weekly_downloads,
    )
    typer.echo(f"Generated {len(paths)} briefs:")
    for p in paths:
        typer.echo(f"  {p}")


@app.command()
def version() -> None:
    """Print the installed biibaa version."""
    from biibaa import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
