"""Static contracts for the native Boneyard container and committed fixture."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from static_re_contract_support import ROOT, StaticReTestFailure


sys.path.insert(0, str(ROOT / "tools"))
import inspect_boneyard  # noqa: E402


FIXTURE = ROOT / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
EXPECTED_SHA256 = "7c7d23f2fbfcdf73b5bb7f4af0f836cc9d199997fe9c7dd38183c7659b6d949d"


def test_flat_boneyard_fixture_matches_native_syncbuffer_envelope() -> str:
    data = FIXTURE.read_bytes()
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != EXPECTED_SHA256:
        raise StaticReTestFailure(
            f"flat Boneyard fixture changed: expected={EXPECTED_SHA256} actual={actual_sha256}"
        )

    parsed = inspect_boneyard.parse_boneyard(data, str(FIXTURE))
    summary = inspect_boneyard.summarize(parsed)
    if summary["syncBuffer"] != {
        "chunks": 7721,
        "maxDepth": 9,
        "namedBuffers": 0,
    }:
        raise StaticReTestFailure(
            f"flat Boneyard SyncBuffer shape changed: {summary['syncBuffer']}"
        )
    if summary["arenaSections"] != 13 or len(summary["regionLayoutSections"]) != 14:
        raise StaticReTestFailure("flat Boneyard native Arena/RegionLayout envelope changed")

    sections = summary["regionLayoutSections"]
    if any(
        sections[index]["objectManager"]["count"] != 0
        for index in inspect_boneyard.OBJECT_MANAGER_SECTIONS - {13}
    ):
        raise StaticReTestFailure("flat editor fixture unexpectedly contains placed objects")
    if sections[11].get("recordCount") != 0:
        raise StaticReTestFailure("flat editor fixture unexpectedly contains sprite placements")
    if sections[13]["objectManager"] != {
        "count": 1,
        "types": [{"id": 6006, "name": "TimeLine", "count": 1}],
    }:
        raise StaticReTestFailure("flat editor fixture lost its stock default TimeLine")
    return "stock-created flat Boneyard has the exact native SyncBuffer and RegionLayout envelope"


def test_boneyard_parser_rejects_empty_truncated_and_trailing_files() -> str:
    valid = FIXTURE.read_bytes()
    invalid_cases = {
        "empty": b"",
        "truncated": valid[:-1],
        "trailing": valid + b"\0",
        "wrong root child count": valid[:4] + b"\x02\0\0\0" + valid[8:],
    }
    accepted: list[str] = []
    for name, payload in invalid_cases.items():
        try:
            inspect_boneyard.parse_boneyard(payload, name)
        except inspect_boneyard.BoneyardFormatError:
            continue
        accepted.append(name)
    if accepted:
        raise StaticReTestFailure(
            "Boneyard parser accepted invalid cases: " + ", ".join(accepted)
        )
    return "Boneyard parser rejects empty, truncated, trailing, and malformed envelopes"
