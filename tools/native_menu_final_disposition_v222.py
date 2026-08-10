#!/usr/bin/env python3
"""Exact disposition of the four residual Settlement v2.21 census rows."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Any, Iterable


SCHEMA = "solomon-dark-native-menu-final-disposition-v222"
SETTLEMENT_SPEC = "2.22"
SEALED_FINAL_CENSUS_SHA256 = (
    "b6adf78aa2cadb671e8a6d337db5de0cc4cf1478928b4250e365f1f8d7d276b0"
)
PROFILE_STATE_IDENTITY_SHA256 = (
    "0539412d5c91207d5b225e86f79795d260fe7b73b8d9a1c29166bd09b445e372"
)
SEQUENCE_LAYOUTS = {
    "dark-cloud-login-settings": {
        "landed": "2f4458671a24bfbc92c236b1591830ad63a2017bc7e405d2f699f68ca0523208",
        "settled": "b83540ff1787240367d20d3e1d3227179358fca26b25ca09f5d4e0833fec8e64",
        "moved_count": 52,
        "moved_sha256": "acd690aa4bf2033c107ef6645fd6323d87c92f77ca7ec7cd41fcfc91e2bb78ae",
        "transition_source": "dark_cloud_login_to_browser.before",
    },
    "game-settings-dark-cloud": {
        "landed": "41ab26a57b11b14a3ad122df328950c8fdb018ad04d6e6cd9443c46820e539ef",
        "settled": "904d97527491795384e851e0229c718868a28631efc96d34528f285f5f7e46bb",
        "moved_count": 53,
        "moved_sha256": "fedaedb133c5716aa3156237ce3bade57d0829521cba51eb112da3e19a2845df",
        "transition_source": "dark_cloud_settings_done.before",
    },
}
NAMED_ENDPOINT_VACUITY = {
    "game-over": "ac246326112f8fcdf6e5b3478ebdf43f755b390d1120241d13f7f77b4c09f2dd",
    "map-picker": "341ca06e22b93ca5c6842378d6c0a572111488399597546082368c532b9941e2",
    "skill-picker": "fb4fa855f9f0b2ea82d2661d0ca252846f3c0e9f48926965b30a8a183efc576c",
}

BASE_SEQUENCE_STOP = (
    "landed-vs-settled structural core mismatch: core relative draw sequence differs"
)
SEQUENCE_COMPARISON_STOP = (
    "v2.22 exact relative-sequence supersession differs from the pinned settled order"
)
SEQUENCE_MEMBERSHIP_STOP = (
    "v2.22 relative-sequence supersession found a membership delta"
)
SEQUENCE_SCOPE_STOP = (
    "v2.22 relative-sequence supersession escaped the two named layouts"
)
SEQUENCE_REPRODUCTION_STOP = (
    "v2.22 relative-sequence supersession is not reproduced by every qualified occurrence"
)
VACUITY_EDGE_STOP = (
    "v2.22 named endpoint-vacuity layout has a native inbound edge"
)
VACUITY_SCOPE_STOP = (
    "v2.22 endpoint vacuity escaped the closed game-over/map-picker/skill-picker set"
)
VACUITY_CORE_STOP = (
    "v2.22 named endpoint-vacuity standalone core differs from its exact pair"
)
CONTRACT_SCOPE_STOP = (
    "v2.22 final four-row disposition changed its exact sealed scope"
)


class FinalDispositionV222Error(ValueError):
    """The sealed four-row ruling does not authorize the requested comparison."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def semantic_payload(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in {"id", "draw_order", "draw_order_semantics"}
    }


def semantic_sequence(elements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [semantic_payload(element) for element in elements]


def sequence_sha256(elements: Iterable[dict[str, Any]]) -> str:
    return sha256_json(semantic_sequence(elements))


def _sequence_tokens(elements: Iterable[dict[str, Any]]) -> list[tuple[bytes, int]]:
    occurrences: Counter[bytes] = Counter()
    tokens: list[tuple[bytes, int]] = []
    for element in elements:
        semantic = canonical_bytes(semantic_payload(element))
        occurrences[semantic] += 1
        tokens.append((semantic, occurrences[semantic]))
    return tokens


def moved_members(
    landed_elements: Iterable[dict[str, Any]],
    settled_elements: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    landed_tokens = _sequence_tokens(landed_elements)
    settled_tokens = _sequence_tokens(settled_elements)
    landed_positions = {token: index for index, token in enumerate(landed_tokens)}
    settled_positions = {token: index for index, token in enumerate(settled_tokens)}
    moved: list[dict[str, Any]] = []
    for token in sorted(
        set(landed_positions) & set(settled_positions),
        key=lambda value: (value[0], value[1]),
    ):
        landed_index = landed_positions[token]
        settled_index = settled_positions[token]
        if landed_index != settled_index:
            moved.append(
                {
                    "semantic_sha256": hashlib.sha256(token[0]).hexdigest(),
                    "occurrence": token[1],
                    "landed_index": landed_index,
                    "settled_index": settled_index,
                }
            )
    return moved


def _receipt(value: Any, *, repository: bool | None = None) -> bool:
    if not isinstance(value, dict):
        return False
    path_keys = {"repo_relative_path", "evidence_path"} & set(value)
    if len(path_keys) != 1:
        return False
    if repository is True and path_keys != {"repo_relative_path"}:
        return False
    if repository is False and path_keys != {"evidence_path"}:
        return False
    path_key = next(iter(path_keys))
    return (
        set(value) == {path_key, "sha256", "bytes"}
        and isinstance(value[path_key], str)
        and bool(value[path_key])
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
        and not isinstance(value.get("bytes"), bool)
        and isinstance(value.get("bytes"), int)
        and value["bytes"] > 0
    )


def receipt_matches(recorded: Any, actual: Any) -> bool:
    return isinstance(recorded, dict) and isinstance(actual, dict) and {
        "sha256": recorded.get("sha256"),
        "bytes": recorded.get("bytes"),
    } == {
        "sha256": actual.get("sha256"),
        "bytes": actual.get("bytes"),
    }


def _moved_member(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value)
        == {"semantic_sha256", "occurrence", "landed_index", "settled_index"}
        and isinstance(value.get("semantic_sha256"), str)
        and len(value["semantic_sha256"]) == 64
        and all(
            not isinstance(value.get(field), bool)
            and isinstance(value.get(field), int)
            and value[field] >= (1 if field == "occurrence" else 0)
            for field in ("occurrence", "landed_index", "settled_index")
        )
    )


def require_contract(contract: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "settlement_spec",
        "class",
        "source_census",
        "resolved_navigation",
        "sequence_supersessions",
        "endpoint_vacuity",
        "application",
        "forbidden",
        "derivation",
    }
    if (
        not isinstance(contract, dict)
        or set(contract) != required
        or contract.get("schema") != SCHEMA
        or contract.get("settlement_spec") != SETTLEMENT_SPEC
        or contract.get("class") != "sealed_final_four_exact_disposition"
        or not _receipt(contract.get("source_census"), repository=False)
        or contract["source_census"].get("sha256")
        != SEALED_FINAL_CENSUS_SHA256
        or not _receipt(contract.get("resolved_navigation"), repository=False)
        or contract.get("forbidden")
        != [
            "general_order_tolerance",
            "sequence_rewrite",
            "membership_delta",
            "property_based_endpoint_vacuity",
            "generation_counter_edit",
        ]
    ):
        raise FinalDispositionV222Error(CONTRACT_SCOPE_STOP)

    records = contract.get("sequence_supersessions")
    if not isinstance(records, list) or len(records) != len(SEQUENCE_LAYOUTS):
        raise FinalDispositionV222Error(CONTRACT_SCOPE_STOP)
    by_layout = {
        record.get("layout_id"): record
        for record in records
        if isinstance(record, dict)
    }
    if set(by_layout) != set(SEQUENCE_LAYOUTS):
        raise FinalDispositionV222Error(SEQUENCE_SCOPE_STOP)
    record_keys = {
        "layout_id",
        "source_census_sha256",
        "landed_sequence_sha256",
        "settled_sequence_sha256",
        "moved_members",
        "membership_delta",
        "occurrences",
        "landed_fixture",
        "landed_baseline_snapshot",
        "candidate_fixture",
        "primary_trace",
        "confirmation_trace",
        "profile_state_identity_sha256",
    }
    for layout_id, expected in SEQUENCE_LAYOUTS.items():
        record = by_layout[layout_id]
        moved = record.get("moved_members")
        occurrences = record.get("occurrences")
        if (
            set(record) != record_keys
            or record.get("source_census_sha256")
            != SEALED_FINAL_CENSUS_SHA256
            or record.get("landed_sequence_sha256") != expected["landed"]
            or record.get("settled_sequence_sha256") != expected["settled"]
            or not isinstance(moved, list)
            or len(moved) != expected["moved_count"]
            or not all(_moved_member(member) for member in moved)
            or len(
                {
                    (member["semantic_sha256"], member["occurrence"])
                    for member in moved
                }
            )
            != len(moved)
            or sha256_json(moved) != expected["moved_sha256"]
            or record.get("membership_delta")
            != {"landed_only_member_count": 0, "settled_only_member_count": 0}
            or not _receipt(record.get("landed_fixture"), repository=True)
            or not _receipt(
                record.get("landed_baseline_snapshot"), repository=True
            )
            or not _receipt(record.get("candidate_fixture"), repository=False)
            or not _receipt(record.get("primary_trace"), repository=False)
            or not _receipt(record.get("confirmation_trace"), repository=False)
            or record.get("profile_state_identity_sha256")
            != PROFILE_STATE_IDENTITY_SHA256
            or not isinstance(occurrences, list)
            or len(occurrences) != 2
        ):
            raise FinalDispositionV222Error(CONTRACT_SCOPE_STOP)
        occurrence_keys = {
            (
                occurrence.get("scope"),
                occurrence.get("edge_id", ""),
                occurrence.get("side", ""),
            )
            for occurrence in occurrences
            if isinstance(occurrence, dict)
            and set(occurrence)
            <= {"scope", "layout_id", "edge_id", "side", "sequence_sha256"}
            and occurrence.get("sequence_sha256") == expected["settled"]
        }
        edge_id, side = str(expected["transition_source"]).split(".", 1)
        if occurrence_keys != {
            ("standalone", "", ""),
            ("transition_source", edge_id, side),
        }:
            raise FinalDispositionV222Error(SEQUENCE_REPRODUCTION_STOP)

    vacuity = contract.get("endpoint_vacuity")
    vacuity_records = vacuity.get("records") if isinstance(vacuity, dict) else None
    if (
        not isinstance(vacuity, dict)
        or set(vacuity)
        != {"named_layout_ids", "records", "promotion_time_recheck_required"}
        or set(vacuity.get("named_layout_ids", [])) != set(NAMED_ENDPOINT_VACUITY)
        or vacuity.get("promotion_time_recheck_required") is not True
        or not isinstance(vacuity_records, list)
        or len(vacuity_records) != len(NAMED_ENDPOINT_VACUITY)
    ):
        raise FinalDispositionV222Error(VACUITY_SCOPE_STOP)
    by_vacuity = {
        record.get("layout_id"): record
        for record in vacuity_records
        if isinstance(record, dict)
    }
    if set(by_vacuity) != set(NAMED_ENDPOINT_VACUITY):
        raise FinalDispositionV222Error(VACUITY_SCOPE_STOP)
    for layout_id, core_sha256 in NAMED_ENDPOINT_VACUITY.items():
        record = by_vacuity[layout_id]
        if (
            set(record)
            != {
                "layout_id",
                "structural_core_sha256",
                "candidate_fixture",
                "primary_trace",
                "confirmation_trace",
                "profile_state_identity_sha256",
                "native_inbound_edge_count",
                "paired_standalone_required",
            }
            or record.get("structural_core_sha256") != core_sha256
            or not _receipt(record.get("candidate_fixture"), repository=False)
            or not _receipt(record.get("primary_trace"), repository=False)
            or not _receipt(record.get("confirmation_trace"), repository=False)
            or record.get("profile_state_identity_sha256")
            != PROFILE_STATE_IDENTITY_SHA256
            or record.get("native_inbound_edge_count") != 0
            or record.get("paired_standalone_required") is not True
        ):
            raise FinalDispositionV222Error(VACUITY_SCOPE_STOP)

    derivation = contract.get("derivation")
    if (
        contract.get("application")
        != {
            "sequence_supersession_count": 2,
            "moved_member_count": 105,
            "named_endpoint_vacuity_count": 3,
            "candidate_sequence_rewrite": False,
            "generation_counter_rewrite": False,
        }
        or not isinstance(derivation, dict)
        or set(derivation)
        != {
            "tool",
            "tool_sha256",
            "tool_bytes",
            "mutation_tool",
            "mutation_tool_sha256",
            "mutation_tool_bytes",
            "source_row_count",
            "writes_only_contract",
        }
        or derivation.get("tool")
        != "tools/derive_native_menu_final_disposition_v222.py"
        or derivation.get("mutation_tool")
        != "tools/run_native_menu_v222_mutations.py"
        or derivation.get("source_row_count") != 4
        or derivation.get("writes_only_contract") is not True
        or any(
            not isinstance(derivation.get(field), str)
            or len(derivation[field]) != 64
            for field in ("tool_sha256", "mutation_tool_sha256")
        )
        or any(
            isinstance(derivation.get(field), bool)
            or not isinstance(derivation.get(field), int)
            or derivation[field] <= 0
            for field in ("tool_bytes", "mutation_tool_bytes")
        )
    ):
        raise FinalDispositionV222Error(CONTRACT_SCOPE_STOP)
    return {
        "sequences": by_layout,
        "endpoint_vacuity": by_vacuity,
    }


def attest_sequence_derivation(
    sequence_row: dict[str, Any],
    all_rows: list[dict[str, Any]],
    observed_occurrence_sequences: dict[tuple[str, str, str], str],
) -> None:
    layout_id = sequence_row.get("layout_id")
    expected = SEQUENCE_LAYOUTS.get(layout_id)
    difference = sequence_row.get("difference")
    if expected is None or not isinstance(difference, dict):
        raise FinalDispositionV222Error(SEQUENCE_SCOPE_STOP)
    if any(
        row is not sequence_row
        and row.get("layout_id") == layout_id
        and isinstance(row.get("difference"), dict)
        and row["difference"].get("difference_type")
        in {"landed_only_member", "settled_only_member"}
        for row in all_rows
        if isinstance(row, dict)
    ):
        raise FinalDispositionV222Error(SEQUENCE_MEMBERSHIP_STOP)
    moved = difference.get("moved_members")
    if (
        difference.get("difference_type") != "layout_field"
        or difference.get("field") != "relative_draw_sequence"
        or difference.get("landed_sha256") != expected["landed"]
        or difference.get("settled_sha256") != expected["settled"]
        or not isinstance(moved, list)
        or len(moved) != expected["moved_count"]
        or sha256_json(moved) != expected["moved_sha256"]
    ):
        raise FinalDispositionV222Error(CONTRACT_SCOPE_STOP)
    edge_id, side = str(expected["transition_source"]).split(".", 1)
    expected_occurrences = {
        ("standalone", "", ""),
        ("transition_source", edge_id, side),
    }
    row_occurrences = {
        (
            occurrence.get("scope"),
            occurrence.get("edge_id", ""),
            occurrence.get("side", ""),
        )
        for occurrence in sequence_row.get("occurrences", [])
        if isinstance(occurrence, dict)
    }
    if (
        row_occurrences != expected_occurrences
        or set(observed_occurrence_sequences) != expected_occurrences
        or set(observed_occurrence_sequences.values()) != {expected["settled"]}
    ):
        raise FinalDispositionV222Error(SEQUENCE_REPRODUCTION_STOP)


def authorize_relative_sequence(
    layout_id: str,
    landed_elements: list[dict[str, Any]],
    settled_elements: list[dict[str, Any]],
    contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
    *,
    enabled: bool = True,
) -> dict[str, Any] | None:
    landed_sha = sequence_sha256(landed_elements)
    settled_sha = sequence_sha256(settled_elements)
    if landed_sha == settled_sha:
        return None
    if not enabled:
        raise FinalDispositionV222Error(BASE_SEQUENCE_STOP)
    view = require_contract(contract)
    record = view["sequences"].get(layout_id)
    if record is None:
        raise FinalDispositionV222Error(SEQUENCE_SCOPE_STOP)
    if Counter(map(canonical_bytes, semantic_sequence(landed_elements))) != Counter(
        map(canonical_bytes, semantic_sequence(settled_elements))
    ):
        raise FinalDispositionV222Error(SEQUENCE_MEMBERSHIP_STOP)
    actual_moved = moved_members(landed_elements, settled_elements)
    if (
        landed_sha != record["landed_sequence_sha256"]
        or settled_sha != record["settled_sequence_sha256"]
        or actual_moved != record["moved_members"]
        or not receipt_matches(record["landed_fixture"], landed_fixture_receipt)
        or not receipt_matches(record["candidate_fixture"], candidate_fixture_receipt)
    ):
        raise FinalDispositionV222Error(SEQUENCE_COMPARISON_STOP)
    return {
        "schema": "solomon-dark-native-menu-relative-sequence-supersession-v222",
        "layout_id": layout_id,
        "landed_sequence_sha256": landed_sha,
        "settled_sequence_sha256": settled_sha,
        "moved_member_count": len(actual_moved),
        "membership_delta": copy.deepcopy(record["membership_delta"]),
        "candidate_sequence_rewrite": False,
        "all_qualified_occurrences_reproduced": True,
    }


def authorize_named_endpoint_vacuity(
    layout_id: str,
    navigation: dict[str, Any],
    contract: dict[str, Any],
    structural_core_sha256: str,
) -> dict[str, Any]:
    view = require_contract(contract)
    record = view["endpoint_vacuity"].get(layout_id)
    if record is None:
        raise FinalDispositionV222Error(VACUITY_SCOPE_STOP)
    if structural_core_sha256 != record["structural_core_sha256"]:
        raise FinalDispositionV222Error(VACUITY_CORE_STOP)
    edges = navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise FinalDispositionV222Error(VACUITY_EDGE_STOP)
    inbound = [
        edge.get("id")
        for edge in edges
        if isinstance(edge, dict)
        and isinstance(edge.get("after"), dict)
        and edge["after"].get("layout_id") == layout_id
    ]
    if inbound:
        raise FinalDispositionV222Error(VACUITY_EDGE_STOP)
    return {
        "schema": "solomon-dark-native-menu-endpoint-vacuity-v222",
        "layout_id": layout_id,
        "native_inbound_edge_count": 0,
        "structural_core_sha256": record["structural_core_sha256"],
        "paired_standalone_required": True,
        "promotion_time_graph_rechecked": True,
    }
