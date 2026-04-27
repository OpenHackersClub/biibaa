"""SQLite cache for dependents lookups.

Keyed by (system, name, iso_week) — biibaa runs weekly, so this matches the
underlying refresh cadence and lets us avoid hitting BigQuery / ecosyste.ms
for the same seed twice in the same week.

Schema is intentionally tiny — one row per cache hit holding the JSON-encoded
dependents list. No migrations, no ORM. The cache is a HINT, not a system of
record — every operation swallows OS/SQLite errors and logs them, so a
disk-full or corrupted-DB condition doesn't crash a pipeline that just
needs to fall through to live queries.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import structlog

from biibaa.ports.dependents import Dependent

log = structlog.get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dependents_cache (
  system TEXT NOT NULL,
  name TEXT NOT NULL,
  iso_week TEXT NOT NULL,
  payload TEXT NOT NULL,
  written_at TEXT NOT NULL,
  PRIMARY KEY (system, name, iso_week)
)
"""


def _iso_week(now: datetime | None = None) -> str:
    n = now or datetime.now(UTC)
    y, w, _ = n.isocalendar()
    return f"{y}-W{w:02d}"


class DependentsCache:
    def __init__(
        self,
        *,
        path: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._conn: sqlite3.Connection | None = None
        self._clock = clock
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path)
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        except (sqlite3.Error, OSError) as e:
            log.warning("dependents_cache.open_failed", path=str(path), error=str(e))
            self._conn = None

    def get(self, *, system: str, name: str) -> list[Dependent] | None:
        if self._conn is None:
            return None
        try:
            cur = self._conn.execute(
                "SELECT payload FROM dependents_cache "
                "WHERE system=? AND name=? AND iso_week=?",
                (system, name, _iso_week(self._clock())),
            )
            row = cur.fetchone()
        except (sqlite3.Error, OSError) as e:
            log.warning("dependents_cache.get_failed", error=str(e))
            return None
        if row is None:
            return None
        return [Dependent(**d) for d in json.loads(row[0])]

    def put(self, *, system: str, name: str, dependents: list[Dependent]) -> None:
        if self._conn is None:
            return
        payload = json.dumps([d.__dict__ for d in dependents])
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO dependents_cache "
                "(system, name, iso_week, payload, written_at) VALUES (?, ?, ?, ?, ?)",
                (
                    system,
                    name,
                    _iso_week(self._clock()),
                    payload,
                    self._clock().isoformat(),
                ),
            )
            self._conn.commit()
        except (sqlite3.Error, OSError) as e:
            log.warning("dependents_cache.put_failed", error=str(e))

    def close(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(sqlite3.Error, OSError):
                self._conn.close()
