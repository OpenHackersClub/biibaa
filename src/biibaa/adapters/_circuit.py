"""In-process circuit breaker.

Wraps a callable. After `failure_threshold` consecutive failures the breaker
opens — subsequent calls return `fallback` immediately without invoking the
underlying callable. After `reset_after` seconds the breaker half-opens and
the next call probes; success closes it, failure re-opens for another window.

Failures are detected via the supplied `is_failure` predicate over the result
(default: any exception, or a falsy/empty list result). Useful for adapters
where the underlying call swallows errors and returns `[]` on its own (the
ecosyste.ms adapter does this) — we treat the empty result as the failure
signal so the breaker can still open on a hot 500-ing endpoint.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _State:
    consecutive_failures: int = 0
    opened_at: float | None = None


class CircuitBreaker[T]:
    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int = 3,
        reset_after_seconds: float = 60.0,
        treat_empty_as_failure: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self._threshold = failure_threshold
        self._reset_after = reset_after_seconds
        self._treat_empty = treat_empty_as_failure
        self._clock = clock
        self._state = _State()

    @property
    def is_open(self) -> bool:
        if self._state.opened_at is None:
            return False
        # Half-open: let the next call through to probe.
        return (self._clock() - self._state.opened_at) < self._reset_after

    def call(self, fn: Callable[[], T], *, fallback: T) -> T:
        if self.is_open:
            return fallback
        try:
            result = fn()
        except Exception:
            self._record_failure()
            return fallback
        if self._treat_empty and _is_empty(result):
            self._record_failure()
            return result
        self._record_success()
        return result

    def _record_failure(self) -> None:
        self._state.consecutive_failures += 1
        if self._state.consecutive_failures >= self._threshold:
            self._state.opened_at = self._clock()

    def _record_success(self) -> None:
        self._state = _State()


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    try:
        return len(value) == 0  # type: ignore[arg-type]
    except TypeError:
        return False
