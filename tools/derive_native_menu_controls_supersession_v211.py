#!/usr/bin/env python3
"""Derive the exact Controls-only v2.11 structural supersession contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from native_menu_landed_diagnosis_v25 import _signature, canonical_bytes
from promote_native_menu_recapture import (
    file_sha256,
    read_json,
    validate_settlement_fixture_v25,
)


CONTRACT_SCHEMA = "solomon-dark-native-menu-controls-core-supersession-v211"
STRUCTURAL_AUDIT_SCHEMA = (
    "solomon-dark-native-menu-controls-post-v210-stop-audit-v1"
)
TITLE_AUDIT_SCHEMA = "solomon-dark-native-menu-controls-screen-title-stop-audit-v1"


def receipt(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"contract input escapes its declared root: {resolved}")
    return {
        "path": resolved.relative_to(resolved_root).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def committed_receipt(repo_root: Path, relative_path: Path) -> dict[str, Any]:
    relative = relative_path.as_posix()
    try:
        content = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"HEAD:{relative}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise ValueError(
            f"committed v2.11 source is absent: {relative}"
        ) from error
    return {
        "path": relative,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }


def assert_receipt(
    recorded: Any, path: Path, label: str
) -> None:
    if not isinstance(recorded, dict):
        raise ValueError(f"{label} audit receipt is absent")
    expected = {
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }
    if {
        "sha256": recorded.get("sha256"),
        "bytes": recorded.get("bytes"),
    } != expected:
        raise ValueError(f"{label} audit receipt does not match its file")


def elements(layout: dict[str, Any], label: str) -> list[dict[str, Any]]:
    values = layout.get("elements")
    if not isinstance(values, list) or not values or not all(
        isinstance(value, dict) for value in values
    ):
        raise ValueError(f"{label} has no unambiguous semantic member census")
    return values


def semantic_counter(layout: dict[str, Any], label: str) -> Counter[str]:
    return Counter(
        hashlib.sha256(_signature(element)).hexdigest()
        for element in elements(layout, label)
    )


def counter_entries(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"semantic_sha256": semantic_sha256, "count": counter[semantic_sha256]}
        for semantic_sha256 in sorted(counter)
    ]


def counter_digest(counter: Counter[str]) -> str:
    return hashlib.sha256(canonical_bytes(counter_entries(counter))).hexdigest()


def audit_counter(values: Any, label: str) -> Counter[str]:
    if not isinstance(values, list):
        raise ValueError(f"{label} is not an array")
    result: Counter[str] = Counter()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"{label} contains a non-object witness")
        semantic_sha256 = value.get("semantic_sha256")
        count = value.get("count")
        if (
            not isinstance(semantic_sha256, str)
            or len(semantic_sha256) != 64
            or any(character not in "0123456789abcdef" for character in semantic_sha256)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
        ):
            raise ValueError(f"{label} contains an invalid semantic witness")
        result[semantic_sha256] += count
    return result


def overlay_counter(reference: dict[str, Any]) -> Counter[str]:
    values = reference.get("overlay_semantic_draw_multiset")
    if not isinstance(values, list) or not values:
        raise ValueError("derived overlay reference has no semantic draw multiset")
    result: Counter[str] = Counter()
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("payload"), dict):
            raise ValueError("derived overlay reference contains a malformed draw")
        count = value.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("derived overlay reference contains an invalid draw count")
        result[hashlib.sha256(canonical_bytes(value["payload"])).hexdigest()] += count
    return result


def settled_identity(
    samples: list[dict[str, Any]], header: dict[str, Any], label: str
) -> dict[str, Any]:
    if len(samples) < 40:
        raise ValueError(f"{label} has fewer than 40 settled samples")
    surfaces: set[Any] = set()
    tagged_screens: set[Any] = set()
    screen_titles: set[Any] = set()
    semantic_generations: set[Any] = set()
    layout_generations: set[Any] = set()
    for sample in samples:
        payload = sample.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(f"{label} contains a sample without payload")
        surfaces.add(sample.get("semantic_surface"))
        semantic_generations.add(sample.get("semantic_generation"))
        tagged_screens.add(payload.get("screen_id"))
        screen_titles.add(payload.get("screen_title"))
        layout_generations.add(payload.get("generation"))
    if (
        surfaces != {"controls"}
        or tagged_screens != {"controls"}
        or screen_titles != {"Wizard Controls"}
        or len(semantic_generations) != 1
        or len(layout_generations) != 1
    ):
        raise ValueError(f"{label} is not one classifier-agreed Controls state")
    return {
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "sample_count": len(samples),
        "stable_span_milliseconds": (
            samples[-1].get("elapsed_milliseconds", 0)
            - samples[0].get("elapsed_milliseconds", 0)
        ),
        "semantic_surface": next(iter(surfaces)),
        "operator_tagged_screen": next(iter(tagged_screens)),
        "screen_title": next(iter(screen_titles)),
        "semantic_generation": next(iter(semantic_generations)),
        "layout_generation": next(iter(layout_generations)),
    }


def controls_endpoints(
    navigation: dict[str, Any], settled_layout: dict[str, Any]
) -> list[dict[str, Any]]:
    edges = navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise ValueError("v2.11 derivation reached no resolved navigation edges")
    expected = {
        ("settings_to_controls", "after", "customize_keyboard_click"),
        ("controls_to_settings", "before", "back_button_click"),
    }
    result: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for side in ("before", "after"):
            endpoint = edge.get(side)
            if not isinstance(endpoint, dict) or endpoint.get("layout_id") != "controls":
                continue
            identity = (edge.get("id"), side, edge.get("trigger"))
            if identity not in expected:
                raise ValueError(f"v2.11 found an unauthorized Controls endpoint: {identity}")
            if canonical_bytes(endpoint.get("layout")) != canonical_bytes(
                settled_layout
            ):
                raise ValueError(
                    f"v2.11 Controls endpoint {identity} does not equal its standalone"
                )
            result.append(
                {
                    "edge_id": identity[0],
                    "side": side,
                    "trigger": identity[2],
                    "semantic_surface": endpoint.get("semantic_surface"),
                    "tagged_screen": endpoint.get("tagged_screen"),
                    "layout_generation": endpoint.get("layout_generation"),
                    "element_count": endpoint.get("element_count"),
                    "frame_sha256": endpoint.get("frame_sha256"),
                }
            )
    observed = {
        (value["edge_id"], value["side"], value["trigger"]) for value in result
    }
    if observed != expected or len(result) != len(expected):
        raise ValueError(
            "v2.11 derivation did not reach exactly both regenerated Controls endpoints"
        )
    return sorted(result, key=lambda value: (value["edge_id"], value["side"]))


def build_contract(
    repo_root: Path,
    evidence_root: Path,
    candidate_root: Path,
    structural_audit_path: Path,
    title_audit_path: Path,
    navigation_path: Path,
) -> dict[str, Any]:
    landed_path = repo_root / "tests/fixtures/webgame/menu-layouts/controls.json"
    landed_snapshot_relative = Path(
        "webgame-contracts/baseline-snapshots/menu-layouts/controls.json"
    )
    candidate_path = candidate_root / "menu-layouts/controls.json"
    overlay_path = candidate_root / "menu-overlay-reference.json"
    structural_audit = read_json(structural_audit_path)
    title_audit = read_json(title_audit_path)
    if (
        structural_audit.get("schema") != STRUCTURAL_AUDIT_SCHEMA
        or structural_audit.get("status") != "QUESTION"
        or structural_audit.get("finding")
        != "valid_settled_controls_structural_core_not_covered_by_landed_diagnosis"
    ):
        raise ValueError("v2.11 structural audit does not prove the accepted STOP")
    if (
        title_audit.get("schema") != TITLE_AUDIT_SCHEMA
        or title_audit.get("finding")
        != "two_instance_settled_controls_title_differs_from_landed_empty_title"
        or title_audit.get("promotion_status") != "STOP"
        or title_audit.get("landed", {}).get("screen_title") != ""
        or title_audit.get("settled_candidate", {}).get("screen_title")
        != "Wizard Controls"
    ):
        raise ValueError("v2.11 title audit does not prove the accepted title defect")

    audit_inputs = structural_audit.get("inputs")
    if not isinstance(audit_inputs, dict):
        raise ValueError("v2.11 structural audit has no input receipts")
    for name, path in (
        ("landed_fixture", landed_path),
        ("candidate_fixture", candidate_path),
        ("overlay_reference", overlay_path),
        ("navigation_recording", navigation_path),
    ):
        assert_receipt(audit_inputs.get(name), path, f"v2.11 {name}")
    snapshot_receipt = committed_receipt(repo_root, landed_snapshot_relative)
    if snapshot_receipt["sha256"] != file_sha256(landed_path) or snapshot_receipt[
        "bytes"
    ] != landed_path.stat().st_size:
        raise ValueError(
            "v2.11 superseded Controls input is not preserved byte-exact in "
            "the shellfix baseline snapshot"
        )

    landed_fixture = read_json(landed_path)
    candidate_fixture = read_json(candidate_path)
    record = validate_settlement_fixture_v25(
        repo_root, evidence_root, candidate_path, candidate_fixture
    )
    landed_layout = landed_fixture.get("layout")
    settled_layout = record.get("layout")
    if not isinstance(landed_layout, dict) or not isinstance(settled_layout, dict):
        raise ValueError("v2.11 compared fixture has no layout payload")
    if (
        landed_layout.get("screen_id") != "controls"
        or settled_layout.get("screen_id") != "controls"
    ):
        raise ValueError("v2.11 compared fixture names another screen")

    landed = semantic_counter(landed_layout, "landed Controls")
    settled = semantic_counter(settled_layout, "settled Controls")
    common = landed & settled
    landed_only = landed - settled
    settled_only = settled - landed
    audit_diff = structural_audit.get("semantic_core_diff")
    if not isinstance(audit_diff, dict):
        raise ValueError("v2.11 structural audit has no semantic diff")
    if (
        audit_counter(
            audit_diff.get("landed_members_missing_from_settled"),
            "v2.11 landed-only audit",
        )
        != landed_only
        or audit_counter(
            audit_diff.get("settled_members_missing_from_landed"),
            "v2.11 settled-only audit",
        )
        != settled_only
        or audit_diff.get("common_semantic_member_count") != sum(common.values())
        or audit_diff.get("multiset_arithmetic_closed") is not True
    ):
        raise ValueError("v2.11 structural audit does not reproduce both multisets")

    overlay = overlay_counter(read_json(overlay_path))
    if overlay - landed_only:
        raise ValueError("v2.11 landed-only core omits a derived session-bleed draw")
    stale = landed_only - overlay
    if sum(overlay.values()) + sum(stale.values()) != sum(landed_only.values()):
        raise ValueError("v2.11 session-bleed plus stale-art arithmetic does not close")
    landed_text_count = sum(
        1 for element in elements(landed_layout, "landed Controls") if element.get("text")
    )
    if landed_text_count != 0:
        raise ValueError("v2.11 landed Controls unexpectedly contains text semantics")

    primary_header = record.get("header")
    confirmation_header = record.get("confirmation_trace", {}).get("header")
    if not isinstance(primary_header, dict) or not isinstance(
        confirmation_header, dict
    ):
        raise ValueError("v2.11 paired Controls evidence has no machine headers")
    primary = settled_identity(
        record["primary_samples"], primary_header, "v2.11 primary Controls"
    )
    confirmation = settled_identity(
        record["confirmation_samples"],
        confirmation_header,
        "v2.11 confirmation Controls",
    )
    if (primary["instance"], primary["process_id"]) == (
        confirmation["instance"],
        confirmation["process_id"],
    ):
        raise ValueError("v2.11 Controls confirmation reused the primary identity")

    navigation = read_json(navigation_path)
    endpoint_records = controls_endpoints(navigation, settled_layout)
    structural_audit_receipt = receipt(structural_audit_path, evidence_root)
    title_audit_receipt = receipt(title_audit_path, evidence_root)
    return {
        "schema": CONTRACT_SCHEMA,
        "settlement_spec": "2.11",
        "layout_id": "controls",
        "screen_id": "controls",
        "superseded_landed_fixture": {
            **snapshot_receipt,
            "generation": landed_layout.get("generation"),
            "semantic_member_count": sum(landed.values()),
            "semantic_multiset_sha256": counter_digest(landed),
            "semantic_multiset": counter_entries(landed),
        },
        "superseding_candidate_fixture": {
            **receipt(candidate_path, evidence_root),
            "generation": settled_layout.get("generation"),
            "semantic_member_count": sum(settled.values()),
            "semantic_multiset_sha256": counter_digest(settled),
            "semantic_multiset": counter_entries(settled),
            "structural_core_sha256": settled_layout.get(
                "structural_core_sha256"
            ),
        },
        "source_audits": {
            "title": title_audit_receipt,
            "structural_core": structural_audit_receipt,
        },
        "paired_settlement": {
            "primary": primary,
            "confirmation": confirmation,
            "primary_trace": receipt(record["primary_trace_path"], evidence_root),
            "confirmation_trace": receipt(
                record["confirmation_trace_path"], evidence_root
            ),
            "two_independent_instances": True,
            "classifier_and_tag_agree": True,
        },
        "navigation_endpoints": endpoint_records,
        "justification": {
            "common_semantic_member_count": sum(common.values()),
            "landed_only_semantic_member_count": sum(landed_only.values()),
            "landed_only_session_bleed": counter_entries(overlay),
            "landed_only_stale_art": counter_entries(stale),
            "landed_text_member_count": landed_text_count,
            "settled_only_semantic_member_count": sum(settled_only.values()),
            "settled_only_semantic_multiset": counter_entries(settled_only),
            "multiset_arithmetic_closed": True,
        },
        "forbidden": [
            "general_settled_only_member_tolerance",
            "count_or_class_based_acceptance",
            "another_layout",
            "another_candidate_content",
        ],
        "derivation": (
            "exact Controls-only supersession derived from the sealed title and "
            "structural STOP audits, byte-pinned landed/candidate fixtures, "
            "two classifier-agreed instances, and both regenerated endpoints"
        ),
    }


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--structural-audit", type=Path, required=True)
    parser.add_argument("--title-audit", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = build_contract(
        args.repo_root.resolve(),
        args.evidence_root.resolve(),
        args.candidate_root.resolve(),
        args.structural_audit.resolve(),
        args.title_audit.resolve(),
        args.navigation_recording.resolve(),
    )
    write_object(args.output.resolve(), contract)
    print(json.dumps(contract, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
