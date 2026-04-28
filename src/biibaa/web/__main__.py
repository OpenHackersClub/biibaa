"""Entry point: `python -m biibaa.web`."""

from __future__ import annotations

import os
from pathlib import Path

from biibaa.web.app import serve

if __name__ in {"__main__", "__mp_main__"}:
    serve(
        briefs_dir=Path(os.environ.get("BIIBAA_BRIEFS_DIR", "data/briefs")),
        host=os.environ.get("BIIBAA_WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("BIIBAA_WEB_PORT", "8080")),
    )
