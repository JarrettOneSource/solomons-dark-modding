#!/usr/bin/env python3
"""Exact evidence-of-era supersession for three Dark Cloud public-tab rows."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


SCHEMA = "solomon-dark-native-menu-dark-cloud-item-row-supersession-v1"
PUBLIC_LAYOUT_MEMBER_IDS = {
    "dark-cloud-browser": "dark_cloud_browser.text.item_1.1",
    "dark-cloud-recent": "dark_cloud_recent.text.item_1.1",
    "dark-cloud-online-levels": "dark_cloud_online_levels.text.item_1.1",
}
CONTROL_LAYOUT = "dark-cloud-my-levels"
CONTROL_MEMBER_ID = "dark_cloud_my_levels.text.item_1.1"
FORBIDDEN = [
    "text_filter",
    "candidate_member_removal",
    "dark_cloud_my_levels_removal",
    "another_layout",
    "another_member_id",
    "another_semantic_payload",
]

CONTRACT_SCOPE_STOP = (
    "v2.19 Dark Cloud public-tab Item 1 supersession contract changed its "
    "exact three-layout scope"
)
EXACT_MEMBER_STOP = (
    "v2.19 Dark Cloud public-tab Item 1 supersession exact landed-era "
    "member or qualified settled core differs"
)
CONTROL_ROW_STOP = (
    "v2.19 Dark Cloud public-tab Item 1 supersession must not remove the "
    "settled My Levels Item 1 row"
)
WRONG_SCOPE_STOP = (
    "v2.19 Dark Cloud public-tab Item 1 supersession does not authorize "
    "another layout or member"
)


class DarkCloudItemRowSupersessionError(ValueError):
    """The exact evidence-of-era record does not authorize this difference."""


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


def _receipt_is_exact(recorded: Any, actual: Any) -> bool:
    return isinstance(recorded, dict) and isinstance(actual, dict) and {
        "sha256": actual.get("sha256"),
        "bytes": actual.get("bytes"),
    } == {
        "sha256": recorded.get("sha256"),
        "bytes": recorded.get("bytes"),
    }


def _valid_receipt(value: Any, expected_keys: set[str]) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == expected_keys
        and isinstance(value.get("path"), str)
        and bool(value["path"])
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
        and not isinstance(value.get("bytes"), bool)
        and isinstance(value.get("bytes"), int)
        and value["bytes"] > 0
    )


def _valid_pair(value: Any, expected_item_count: int) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "profile_state_identity_sha256",
        "primary",
        "confirmation",
        "settled_item_row_count",
    }:
        return False
    identity = value.get("profile_state_identity_sha256")
    if (
        not isinstance(identity, str)
        or len(identity) != 64
        or value.get("settled_item_row_count") != expected_item_count
    ):
        return False
    for role in ("primary", "confirmation"):
        observation = value.get(role)
        if (
            not isinstance(observation, dict)
            or observation.get("settled_sample_count", 0) < 40
            or observation.get("settled_span_milliseconds", 0) < 2_000
            or observation.get("population_item_row_counts")
            != [expected_item_count]
            or observation.get("settled_item_row_counts")
            != [expected_item_count]
        ):
            return False
    return True


def _validate_member(value: Any, expected_id: str) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "semantic_sha256",
        "payload",
    }:
        return False
    payload = value.get("payload")
    return (
        value.get("id") == expected_id
        and isinstance(payload, dict)
        and payload.get("id") == expected_id
        and payload.get("text") == "Item 1"
        and value.get("semantic_sha256") == semantic_sha256(payload)
    )


def require_contract(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate the complete bounded contract and return entries by layout."""
    if set(contract) != {
        "schema",
        "settlement_spec",
        "class",
        "affected_layouts",
        "control_layout",
        "source_audit",
        "promoter_stop",
        "landed_era_capture_identity",
        "diagnostic_role",
        "forbidden",
        "derivation",
    } or (
        contract.get("schema") != SCHEMA
        or contract.get("settlement_spec") != "2.19"
        or contract.get("class")
        != "evidence_of_era_exact_member_supersession"
        or contract.get("forbidden") != FORBIDDEN
    ):
        raise DarkCloudItemRowSupersessionError(CONTRACT_SCOPE_STOP)

    entries = contract.get("affected_layouts")
    if not isinstance(entries, list) or len(entries) != len(PUBLIC_LAYOUT_MEMBER_IDS):
        raise DarkCloudItemRowSupersessionError(CONTRACT_SCOPE_STOP)
    by_layout: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "layout_id",
            "screen_id",
            "superseded_landed_fixture",
            "superseding_candidate_fixture",
            "superseded_member",
            "fresh_pair",
        }:
            raise DarkCloudItemRowSupersessionError(CONTRACT_SCOPE_STOP)
        layout_id = entry.get("layout_id")
        if (
            layout_id not in PUBLIC_LAYOUT_MEMBER_IDS
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
            or not _validate_member(
                entry.get("superseded_member"),
                PUBLIC_LAYOUT_MEMBER_IDS.get(layout_id, ""),
            )
            or not _valid_pair(entry.get("fresh_pair"), 0)
        ):
            raise DarkCloudItemRowSupersessionError(CONTRACT_SCOPE_STOP)
        by_layout[layout_id] = entry
    if set(by_layout) != set(PUBLIC_LAYOUT_MEMBER_IDS):
        raise DarkCloudItemRowSupersessionError(CONTRACT_SCOPE_STOP)

    control = contract.get("control_layout")
    if not isinstance(control, dict) or set(control) != {
        "layout_id",
        "screen_id",
        "landed_fixture",
        "candidate_fixture",
        "retained_member",
        "fresh_pair",
    } or (
        control.get("layout_id") != CONTROL_LAYOUT
        or control.get("screen_id") != CONTROL_LAYOUT.replace("-", "_")
        or not _valid_receipt(
            control.get("landed_fixture"), {"path", "sha256", "bytes"}
        )
        or not _valid_receipt(
            control.get("candidate_fixture"), {"path", "sha256", "bytes"}
        )
        or not _validate_member(control.get("retained_member"), CONTROL_MEMBER_ID)
        or not _valid_pair(control.get("fresh_pair"), 1)
    ):
        raise DarkCloudItemRowSupersessionError(CONTRACT_SCOPE_STOP)

    for field in ("source_audit", "promoter_stop"):
        if not _valid_receipt(contract.get(field), {"path", "sha256", "bytes"}):
            raise DarkCloudItemRowSupersessionError(CONTRACT_SCOPE_STOP)
    era = contract.get("landed_era_capture_identity")
    if not isinstance(era, dict) or set(era) != {
        "instance",
        "process_id",
        "profile_state_provenance_present",
    } or (
        not isinstance(era.get("instance"), str)
        or not era["instance"]
        or isinstance(era.get("process_id"), bool)
        or not isinstance(era.get("process_id"), int)
        or era["process_id"] <= 0
        or era.get("profile_state_provenance_present") is not False
    ):
        raise DarkCloudItemRowSupersessionError(CONTRACT_SCOPE_STOP)
    return by_layout


def validate_control_layout(
    layout_id: str,
    settled_layout: dict[str, Any],
    contract: dict[str, Any],
    candidate_fixture_receipt: dict[str, Any] | None,
) -> None:
    """Keep the reproduced My Levels row as a positive, exact control."""
    require_contract(contract)
    if layout_id != CONTROL_LAYOUT:
        return
    control = contract["control_layout"]
    rows = [
        element
        for element in settled_layout.get("elements", [])
        if isinstance(element, dict) and element.get("text") == "Item 1"
    ]
    retained = control["retained_member"]
    if (
        len(rows) != 1
        or rows[0] != retained["payload"]
        or semantic_sha256(rows[0]) != retained["semantic_sha256"]
        or not _receipt_is_exact(
            control["candidate_fixture"], candidate_fixture_receipt
        )
    ):
        raise DarkCloudItemRowSupersessionError(CONTROL_ROW_STOP)


def consume_exact_landed_residual(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    residual: list[dict[str, Any]],
    contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Consume only the exact authorized landed member; never alter a candidate."""
    by_layout = require_contract(contract)
    expected = by_layout.get(layout_id)
    item_residuals = [
        element
        for element in residual
        if isinstance(element, dict)
        and (
            element.get("text") == "Item 1"
            or str(element.get("id", "")).endswith(".text.item_1.1")
        )
    ]
    if expected is None:
        if item_residuals:
            raise DarkCloudItemRowSupersessionError(WRONG_SCOPE_STOP)
        return None, residual

    member = expected["superseded_member"]
    exact = [element for element in residual if element == member["payload"]]
    if not exact:
        return None, residual
    settled_rows = [
        element
        for element in settled_layout.get("elements", [])
        if isinstance(element, dict) and element.get("text") == "Item 1"
    ]
    if (
        len(exact) != 1
        or len(item_residuals) != 1
        or settled_rows
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
        or not _receipt_is_exact(
            expected["superseded_landed_fixture"], landed_fixture_receipt
        )
        or not _receipt_is_exact(
            expected["superseding_candidate_fixture"], candidate_fixture_receipt
        )
    ):
        raise DarkCloudItemRowSupersessionError(EXACT_MEMBER_STOP)

    remaining = residual.copy()
    remaining.remove(exact[0])
    return {
        "schema": "solomon-dark-native-menu-dark-cloud-item-row-disposition-v1",
        "layout_id": layout_id,
        "member_id": member["id"],
        "semantic_sha256": member["semantic_sha256"],
        "reason": "unprovenanced_landed_era_list_or_cache_state",
        "candidate_member_removed": False,
        "fresh_pair": copy.deepcopy(expected["fresh_pair"]),
        "source_audit": copy.deepcopy(contract["source_audit"]),
    }, remaining
