from __future__ import annotations

import logging
from pathlib import Path

import structlog
import typer

from biibaa.pipeline.run import run as run_pipeline

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
    top_n: int = typer.Option(20, "--top", help="Number of briefs to render"),
    ecosystem: str = typer.Option("npm", "--ecosystem"),
    advisory_limit: int = typer.Option(
        400, "--advisory-limit", help="Max advisories to ingest"
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
    )
    typer.echo(f"Generated {len(paths)} briefs:")
    for p in paths:
        typer.echo(f"  {p}")


@app.command()
def serve(
    briefs_dir: Path = typer.Option(
        Path("data/briefs"), "--briefs-dir", help="Directory of generated briefs"
    ),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
    show: bool = typer.Option(False, "--show", help="Open the app in the default browser"),
) -> None:
    """Launch the NiceGUI triage webapp for sorting/filtering briefs."""
    from biibaa.web.app import serve as serve_app

    serve_app(briefs_dir=briefs_dir, host=host, port=port, show=show)


@app.command()
def version() -> None:
    """Print the installed biibaa version."""
    from biibaa import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
