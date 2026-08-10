#!/usr/bin/env python3
"""Exact landed-era browser chrome supersession for four Dark Cloud tabs."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Any


SCHEMA = "solomon-dark-native-menu-dark-cloud-browser-chrome-supersession-v1"
LAYOUTS = (
    "dark-cloud-browser",
    "dark-cloud-recent",
    "dark-cloud-online-levels",
    "dark-cloud-my-levels",
)
EXPECTED_OVERLAY_COUNT = 15
EXPECTED_BROWSER_CHROME_MULTIPLICITIES = {
    "ControlPanel.0": 4,
    "ControlPanel.18": 2,
    "ControlPanel.8": 1,
    "UI.17": 4,
    "UI.18": 2,
}
EXPECTED_BROWSER_CHROME_COUNT = sum(EXPECTED_BROWSER_CHROME_MULTIPLICITIES.values())
EXPECTED_RESIDUAL_COUNT = EXPECTED_OVERLAY_COUNT + EXPECTED_BROWSER_CHROME_COUNT
FORBIDDEN = [
    "candidate_member_removal",
    "fresh_member_filter",
    "partial_residual_application",
    "count_tolerance",
    "another_layout",
    "v2_4_overlay_gate_change",
]

CONTRACT_SCOPE_STOP = (
    "v2.19 Dark Cloud browser-chrome era supersession contract changed its "
    "exact four-layout scope"
)
EXACT_RESIDUAL_STOP = (
    "v2.19 Dark Cloud browser-chrome era supersession exact 28-draw landed "
    "residual differs"
)
FRESH_MEMBER_STOP = (
    "v2.19 Dark Cloud browser-chrome era supersession never strips a fresh "
    "settled member"
)
WRONG_SCOPE_STOP = (
    "v2.19 Dark Cloud browser-chrome era supersession does not authorize "
    "another layout"
)


class DarkCloudBrowserChromeSupersessionError(ValueError):
    """The exact landed-era record does not authorize this residual."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def semantic_payload(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in {"id", "draw_order", "draw_order_semantics"}
    }


def semantic_sha256(element: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(semantic_payload(element))).hexdigest()


def semantic_multiset(elements: list[dict[str, Any]]) -> Counter[str]:
    return Counter(semantic_sha256(element) for element in elements)


def multiset_sha256(counter: Counter[str]) -> str:
    return hashlib.sha256(
        canonical_bytes(
            [
                {"semantic_sha256": digest, "count": counter[digest]}
                for digest in sorted(counter)
            ]
        )
    ).hexdigest()


def audit_multiset_sha256(elements: list[dict[str, Any]]) -> str:
    """Reproduce the accepted post-Item audit's raw-semantic multiset hash."""
    counter = Counter(canonical_bytes(semantic_payload(element)) for element in elements)
    return hashlib.sha256(
        canonical_bytes(
            [
                {"semantic_sha256": payload.hex(), "count": counter[payload]}
                for payload in sorted(counter)
            ]
        )
    ).hexdigest()


def _valid_receipt(value: Any, fields: set[str]) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == fields
        and isinstance(value.get("path"), str)
        and bool(value["path"])
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
        and not isinstance(value.get("bytes"), bool)
        and isinstance(value.get("bytes"), int)
        and value["bytes"] > 0
    )


def _receipt_matches(recorded: Any, actual: Any) -> bool:
    return isinstance(recorded, dict) and isinstance(actual, dict) and {
        "sha256": recorded.get("sha256"),
        "bytes": recorded.get("bytes"),
    } == {
        "sha256": actual.get("sha256"),
        "bytes": actual.get("bytes"),
    }


def _validate_residual_member(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "captured_id",
        "semantic_sha256",
        "classification",
        "payload",
    }:
        return False
    payload = value.get("payload")
    classification = value.get("classification")
    return (
        isinstance(payload, dict)
        and payload.get("id") == value.get("captured_id")
        and payload.get("kind") == "art"
        and not payload.get("text")
        and not payload.get("action_id")
        and classification in {"beta_dialog_overlay", "browser_chrome_era"}
        and value.get("semantic_sha256") == semantic_sha256(payload)
    )


def require_contract(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate the complete bounded record and return entries by layout."""
    if set(contract) != {
        "schema",
        "settlement_spec",
        "class",
        "affected_layouts",
        "source_audit",
        "item_row_contract",
        "overlay_reference",
        "landed_era_capture_identity",
        "mechanistic_split",
        "application",
        "forbidden",
        "derivation",
    } or (
        contract.get("schema") != SCHEMA
        or contract.get("settlement_spec") != "2.19"
        or contract.get("class") != "exact_landed_era_residual_supersession"
        or contract.get("forbidden") != FORBIDDEN
    ):
        raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)
    for field in ("source_audit", "item_row_contract", "overlay_reference"):
        if not _valid_receipt(contract.get(field), {"path", "sha256", "bytes"}):
            raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)

    era = contract.get("landed_era_capture_identity")
    if not isinstance(era, dict) or set(era) != {
        "instance",
        "process_id",
        "profile_state_provenance_present",
        "layout_generations",
    } or (
        era.get("instance") != "men-title"
        or era.get("process_id") != 16140
        or era.get("profile_state_provenance_present") is not False
        or not isinstance(era.get("layout_generations"), dict)
        or set(era["layout_generations"]) != set(LAYOUTS)
    ):
        raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)

    split = contract.get("mechanistic_split")
    if not isinstance(split, dict) or set(split) != {
        "total_residual_count",
        "beta_dialog_overlay_count",
        "browser_chrome_era_count",
        "browser_chrome_art_id_multiplicities",
        "browser_chrome_semantic_multiset_sha256",
        "v2_4_overlay_gate_unchanged",
    } or (
        split.get("total_residual_count") != EXPECTED_RESIDUAL_COUNT
        or split.get("beta_dialog_overlay_count") != EXPECTED_OVERLAY_COUNT
        or split.get("browser_chrome_era_count")
        != EXPECTED_BROWSER_CHROME_COUNT
        or split.get("browser_chrome_art_id_multiplicities")
        != EXPECTED_BROWSER_CHROME_MULTIPLICITIES
        or split.get("v2_4_overlay_gate_unchanged") is not True
        or not isinstance(split.get("browser_chrome_semantic_multiset_sha256"), str)
        or len(split["browser_chrome_semantic_multiset_sha256"]) != 64
    ):
        raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)

    entries = contract.get("affected_layouts")
    if not isinstance(entries, list) or len(entries) != len(LAYOUTS):
        raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)
    by_layout: dict[str, dict[str, Any]] = {}
    common_counter: Counter[str] | None = None
    common_browser_counter: Counter[str] | None = None
    common_browser_audit_sha256: str | None = None
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "layout_id",
            "screen_id",
            "superseded_landed_fixture",
            "superseding_candidate_fixture",
            "residual_semantic_multiset_sha256",
            "residual_members",
            "fresh_pair",
        }:
            raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)
        layout_id = entry.get("layout_id")
        members = entry.get("residual_members")
        if (
            layout_id not in LAYOUTS
            or layout_id in by_layout
            or entry.get("screen_id") != layout_id.replace("-", "_")
            or not _valid_receipt(
                entry.get("superseded_landed_fixture"),
                {"path", "sha256", "bytes", "generation", "element_count"},
            )
            or not _valid_receipt(
                entry.get("superseding_candidate_fixture"),
                {
                    "path",
                    "sha256",
                    "bytes",
                    "generation",
                    "element_count",
                    "structural_core_sha256",
                },
            )
            or not isinstance(members, list)
            or len(members) != EXPECTED_RESIDUAL_COUNT
            or not all(_validate_residual_member(member) for member in members)
        ):
            raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)
        overlay_members = [
            member
            for member in members
            if member["classification"] == "beta_dialog_overlay"
        ]
        browser_members = [
            member
            for member in members
            if member["classification"] == "browser_chrome_era"
        ]
        browser_multiplicities = Counter(
            str(member["payload"].get("art_id")) for member in browser_members
        )
        counter = Counter(member["semantic_sha256"] for member in members)
        browser_counter = Counter(
            member["semantic_sha256"] for member in browser_members
        )
        browser_audit_sha256 = audit_multiset_sha256(
            [member["payload"] for member in browser_members]
        )
        if (
            len(overlay_members) != EXPECTED_OVERLAY_COUNT
            or len(browser_members) != EXPECTED_BROWSER_CHROME_COUNT
            or dict(browser_multiplicities) != EXPECTED_BROWSER_CHROME_MULTIPLICITIES
            or entry.get("residual_semantic_multiset_sha256")
            != multiset_sha256(counter)
            or not isinstance(entry.get("fresh_pair"), dict)
            or entry["fresh_pair"].get("all_residual_members_absent") is not True
            or common_counter is not None
            and counter != common_counter
            or common_browser_counter is not None
            and browser_counter != common_browser_counter
            or common_browser_audit_sha256 is not None
            and browser_audit_sha256 != common_browser_audit_sha256
        ):
            raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)
        common_counter = counter
        common_browser_counter = browser_counter
        common_browser_audit_sha256 = browser_audit_sha256
        by_layout[layout_id] = entry
    if (
        set(by_layout) != set(LAYOUTS)
        or common_browser_counter is None
        or common_browser_audit_sha256 is None
    ):
        raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)
    if common_browser_audit_sha256 != split[
        "browser_chrome_semantic_multiset_sha256"
    ]:
        raise DarkCloudBrowserChromeSupersessionError(CONTRACT_SCOPE_STOP)
    return by_layout


def consume_exact_landed_residual(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    residual: list[dict[str, Any]],
    contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Consume only an exact pinned landed residual; never edit settled data."""
    by_layout = require_contract(contract)
    expected = by_layout.get(layout_id)
    actual_counter = semantic_multiset(residual)
    common_expected = semantic_multiset(
        [member["payload"] for member in next(iter(by_layout.values()))["residual_members"]]
    )
    if expected is None:
        if actual_counter == common_expected:
            raise DarkCloudBrowserChromeSupersessionError(WRONG_SCOPE_STOP)
        return None, residual

    expected_members = expected["residual_members"]
    expected_counter = Counter(
        member["semantic_sha256"] for member in expected_members
    )
    settled_counter = semantic_multiset(
        [
            element
            for element in settled_layout.get("elements", [])
            if isinstance(element, dict)
        ]
    )
    if any(settled_counter[digest] for digest in expected_counter):
        raise DarkCloudBrowserChromeSupersessionError(FRESH_MEMBER_STOP)
    if (
        len(residual) != EXPECTED_RESIDUAL_COUNT
        or actual_counter != expected_counter
        or multiset_sha256(actual_counter)
        != expected["residual_semantic_multiset_sha256"]
        or landed_layout.get("screen_id") != expected["screen_id"]
        or settled_layout.get("screen_id") != expected["screen_id"]
        or landed_layout.get("generation")
        != expected["superseded_landed_fixture"]["generation"]
        or len(landed_layout.get("elements", []))
        != expected["superseded_landed_fixture"]["element_count"]
        or settled_layout.get("generation")
        != expected["superseding_candidate_fixture"]["generation"]
        or len(settled_layout.get("elements", []))
        != expected["superseding_candidate_fixture"]["element_count"]
        or settled_layout.get("structural_core_sha256")
        != expected["superseding_candidate_fixture"]["structural_core_sha256"]
        or not _receipt_matches(
            expected["superseded_landed_fixture"], landed_fixture_receipt
        )
        or not _receipt_matches(
            expected["superseding_candidate_fixture"], candidate_fixture_receipt
        )
    ):
        raise DarkCloudBrowserChromeSupersessionError(EXACT_RESIDUAL_STOP)

    overlay = [
        member
        for member in expected_members
        if member["classification"] == "beta_dialog_overlay"
    ]
    browser = [
        member
        for member in expected_members
        if member["classification"] == "browser_chrome_era"
    ]
    return {
        "schema": "solomon-dark-native-menu-dark-cloud-browser-chrome-disposition-v1",
        "layout_id": layout_id,
        "residual_count": EXPECTED_RESIDUAL_COUNT,
        "residual_semantic_multiset_sha256": expected[
            "residual_semantic_multiset_sha256"
        ],
        "beta_dialog_overlay_members": copy.deepcopy(overlay),
        "browser_chrome_era_members": copy.deepcopy(browser),
        "candidate_member_removed": False,
        "v2_4_overlay_gate_unchanged": True,
        "source_audit": copy.deepcopy(contract["source_audit"]),
    }, []
