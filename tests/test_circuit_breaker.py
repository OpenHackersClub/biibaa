"""CircuitBreaker contract tests."""

from __future__ import annotations

from biibaa.adapters._circuit import CircuitBreaker


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_opens_after_consecutive_failures() -> None:
    clock = _Clock()
    cb = CircuitBreaker[list[int]](
        name="t", failure_threshold=2, reset_after_seconds=10, clock=clock
    )
    assert cb.call(lambda: [], fallback=[]) == []  # 1st empty -> failure
    assert cb.call(lambda: [], fallback=[]) == []  # 2nd empty -> opens
    assert cb.is_open is True

    calls = {"n": 0}

    def underlying() -> list[int]:
        calls["n"] += 1
        return [1, 2, 3]

    # Open: underlying must NOT be called.
    assert cb.call(underlying, fallback=[]) == []
    assert calls["n"] == 0


def test_half_open_then_close_on_success() -> None:
    clock = _Clock()
    cb = CircuitBreaker[list[int]](
        name="t", failure_threshold=1, reset_after_seconds=10, clock=clock
    )
    cb.call(lambda: [], fallback=[])  # opens
    assert cb.is_open is True

    clock.t = 11  # past reset window
    assert cb.is_open is False
    assert cb.call(lambda: [42], fallback=[]) == [42]
    # Subsequent failure should not immediately re-open (threshold=1, but
    # state was reset on success).
    assert cb.is_open is False


def test_exception_counts_as_failure() -> None:
    cb = CircuitBreaker[list[int]](name="t", failure_threshold=1)

    def boom() -> list[int]:
        raise RuntimeError("nope")

    assert cb.call(boom, fallback=[99]) == [99]
    assert cb.is_open is True
