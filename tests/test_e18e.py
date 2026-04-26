"""e18e adapter contract test."""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from biibaa.adapters.e18e import RAW_BASE, E18eReplacementsSource

_PREFERRED = {
    "mappings": {
        "moment": {
            "type": "module",
            "moduleName": "moment",
            "replacements": ["luxon"],
        },
        "lodash.debounce": {
            "type": "module",
            "moduleName": "lodash.debounce",
            "replacements": ["es-toolkit"],
        },
    },
    "replacements": {
        "luxon": {"id": "luxon", "type": "documented", "replacementModule": "luxon"},
        "es-toolkit": {
            "id": "es-toolkit",
            "type": "documented",
            "replacementModule": "es-toolkit",
        },
    },
}

_NATIVE = {
    "mappings": {
        "node-fetch": {
            "type": "module",
            "moduleName": "node-fetch",
            "replacements": ["fetch-api"],
        },
    },
    "replacements": {
        "fetch-api": {"id": "fetch-api", "type": "native", "url": "https://example.com"},
    },
}

_MICRO = {"mappings": {}, "replacements": {}}


@pytest.fixture
def src(httpx_mock: HTTPXMock) -> E18eReplacementsSource:
    httpx_mock.add_response(url=f"{RAW_BASE}/preferred.json", json=_PREFERRED)
    httpx_mock.add_response(url=f"{RAW_BASE}/native.json", json=_NATIVE)
    httpx_mock.add_response(url=f"{RAW_BASE}/micro-utilities.json", json=_MICRO)
    return E18eReplacementsSource(client=httpx.Client())


def test_emits_replacement_for_documented_module(src: E18eReplacementsSource) -> None:
    out = list(src.fetch())
    moment = next(r for r in out if r.from_purl == "pkg:npm/moment")
    assert moment.to_purls == ["pkg:npm/luxon"]
    assert moment.axis == "perf"
    assert moment.effort == "minor-migration"


def test_native_replacement_marks_native_target(src: E18eReplacementsSource) -> None:
    out = list(src.fetch())
    nf = next(r for r in out if r.from_purl == "pkg:npm/node-fetch")
    assert nf.axis == "bloat"
    assert nf.effort == "drop-in"
    assert nf.to_purls == ["pkg:npm/<native>"]


def test_evidence_records_source_manifest(src: E18eReplacementsSource) -> None:
    out = list(src.fetch())
    moment = next(r for r in out if r.from_purl == "pkg:npm/moment")
    assert moment.evidence["source"] == "e18e"
    assert moment.evidence["manifest"] == "preferred.json"
