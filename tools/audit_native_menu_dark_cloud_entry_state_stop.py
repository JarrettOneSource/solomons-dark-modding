#!/usr/bin/env python3
"""Audit the fail-closed Dark Cloud entry-tab traversal finding."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


LAYOUT_IDS = (
    "dark-cloud-browser",
    "dark-cloud-recent",
    "dark-cloud-online-levels",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def file_receipt(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Dark Cloud entry audit expected an object in {path}")
    return value


def elements(layout: dict[str, Any], label: str) -> list[dict[str, Any]]:
    values = layout.get("elements")
    if not isinstance(values, list) or not values:
        raise ValueError(f"Dark Cloud entry audit reached no {label} elements")
    if not all(isinstance(value, dict) for value in values):
        raise ValueError(f"Dark Cloud entry audit reached malformed {label} elements")
    return values


def semantic_payload(
    element: dict[str, Any], *, omit_geometry: bool = False
) -> dict[str, Any]:
    omitted = {"id", "draw_order", "draw_order_semantics"}
    if omit_geometry:
        omitted.update({"rect", "unclipped_rect"})
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in omitted
    }


def semantic_multiset(
    layout: dict[str, Any], *, omit_geometry: bool = False
) -> Counter[bytes]:
    return Counter(
        canonical_bytes(semantic_payload(value, omit_geometry=omit_geometry))
        for value in elements(layout, "layout")
    )


def multiset_receipt(values: Counter[bytes]) -> dict[str, Any]:
    serializable = [
        {
            "semantic_payload": json.loads(payload.decode("utf-8")),
            "count": count,
        }
        for payload, count in sorted(values.items())
    ]
    return {
        "member_count": sum(values.values()),
        "distinct_member_count": len(values),
        "sha256": hashlib.sha256(canonical_bytes(serializable)).hexdigest(),
    }


def unique_edge(navigation: dict[str, Any], edge_id: str) -> dict[str, Any]:
    edges = navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise ValueError("Dark Cloud entry audit reached no navigation edges")
    matches = [
        value
        for value in edges
        if isinstance(value, dict) and value.get("id") == edge_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Dark Cloud entry audit found {len(matches)} {edge_id!r} edges"
        )
    return matches[0]


def endpoint_summary(endpoint: dict[str, Any]) -> dict[str, Any]:
    layout = endpoint.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("Dark Cloud entry audit reached an endpoint without layout")
    return {
        "layout_id": endpoint.get("layout_id"),
        "semantic_surface": endpoint.get("semantic_surface"),
        "tagged_screen": endpoint.get("tagged_screen"),
        "layout_generation": endpoint.get("layout_generation"),
        "element_count": endpoint.get("element_count"),
        "frame_sha256": endpoint.get("frame_sha256"),
        "semantic_multiset": multiset_receipt(semantic_multiset(layout)),
    }


def layout_from_fixture(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = read_json(path)
    layout = fixture.get("layout")
    header = fixture.get("header")
    if not isinstance(layout, dict) or not isinstance(header, dict):
        raise ValueError(f"Dark Cloud entry audit found malformed fixture {path}")
    return layout, header


def unique_doc_clause(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    matches = [
        (index + 1, line.strip())
        for index, line in enumerate(lines)
        if "browser opens **on the Online Levels tab**" in line
    ]
    if len(matches) != 1:
        raise ValueError(
            "Dark Cloud entry audit did not find one Online Levels entry contract"
        )
    return {"line": matches[0][0], "text": matches[0][1]}


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--structural-audit", type=Path, required=True)
    parser.add_argument("--promoter-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    navigation_path = args.navigation_recording.resolve()
    structural_audit_path = args.structural_audit.resolve()
    promoter_log_path = args.promoter_log.resolve()

    candidate_layouts: dict[str, dict[str, Any]] = {}
    candidate_headers: dict[str, dict[str, Any]] = {}
    landed_layouts: dict[str, dict[str, Any]] = {}
    candidate_receipts: dict[str, dict[str, Any]] = {}
    landed_receipts: dict[str, dict[str, Any]] = {}
    for layout_id in LAYOUT_IDS:
        candidate_path = candidate_root / "menu-layouts" / f"{layout_id}.json"
        landed_path = (
            repo / "tests/fixtures/webgame/menu-layouts" / f"{layout_id}.json"
        )
        candidate_layouts[layout_id], candidate_headers[layout_id] = (
            layout_from_fixture(candidate_path)
        )
        landed_layouts[layout_id], _ = layout_from_fixture(landed_path)
        candidate_receipts[layout_id] = file_receipt(candidate_path)
        landed_receipts[layout_id] = file_receipt(landed_path)

    candidate_sets = {
        key: semantic_multiset(value)
        for key, value in candidate_layouts.items()
    }
    candidate_geometry_free_sets = {
        key: semantic_multiset(value, omit_geometry=True)
        for key, value in candidate_layouts.items()
    }
    landed_sets = {
        key: semantic_multiset(value) for key, value in landed_layouts.items()
    }

    navigation = read_json(navigation_path)
    main_edge = unique_edge(navigation, "main_to_dark_cloud")
    recent_edge = unique_edge(navigation, "dark_cloud_to_recent")
    online_edge = unique_edge(navigation, "dark_cloud_recent_to_online")
    endpoints = {
        "main_to_dark_cloud.after": main_edge.get("after"),
        "dark_cloud_to_recent.before": recent_edge.get("before"),
        "dark_cloud_to_recent.after": recent_edge.get("after"),
        "dark_cloud_recent_to_online.before": online_edge.get("before"),
        "dark_cloud_recent_to_online.after": online_edge.get("after"),
    }
    if not all(isinstance(value, dict) for value in endpoints.values()):
        raise ValueError("Dark Cloud entry audit reached a missing endpoint")
    endpoint_sets = {
        key: semantic_multiset(value["layout"])
        for key, value in endpoints.items()
    }

    browser = candidate_sets["dark-cloud-browser"]
    recent = candidate_sets["dark-cloud-recent"]
    online = candidate_sets["dark-cloud-online-levels"]
    main_after = endpoint_sets["main_to_dark_cloud.after"]
    recent_before = endpoint_sets["dark_cloud_to_recent.before"]
    recent_after = endpoint_sets["dark_cloud_to_recent.after"]
    online_after = endpoint_sets["dark_cloud_recent_to_online.after"]
    main_after_summary = endpoint_summary(endpoints["main_to_dark_cloud.after"])
    recent_before_summary = endpoint_summary(
        endpoints["dark_cloud_to_recent.before"]
    )
    recent_after_summary = endpoint_summary(
        endpoints["dark_cloud_to_recent.after"]
    )
    online_after_summary = endpoint_summary(
        endpoints["dark_cloud_recent_to_online.after"]
    )

    required_facts = {
        "landed_browser_equals_landed_online": (
            landed_sets["dark-cloud-browser"]
            == landed_sets["dark-cloud-online-levels"]
        ),
        "settled_browser_equals_settled_recent": browser == recent,
        "settled_browser_differs_from_settled_online": browser != online,
        "settled_browser_and_online_differ_only_in_geometry": (
            candidate_geometry_free_sets["dark-cloud-browser"]
            == candidate_geometry_free_sets["dark-cloud-online-levels"]
        ),
        "main_entry_endpoint_equals_browser": main_after == browser,
        "main_entry_endpoint_equals_recent": main_after == recent,
        "main_entry_endpoint_differs_from_online": main_after != online,
        "recent_edge_before_equals_browser": recent_before == browser,
        "recent_edge_before_equals_after": recent_before == recent_after,
        "recent_edge_after_equals_recent": recent_after == recent,
        "recent_edge_frame_is_unchanged": (
            recent_before_summary["frame_sha256"]
            == recent_after_summary["frame_sha256"]
        ),
        "online_action_changes_semantics": recent_after != online_after,
        "online_action_changes_frame": (
            recent_after_summary["frame_sha256"]
            != online_after_summary["frame_sha256"]
        ),
    }
    if not all(required_facts.values()):
        failed = [key for key, value in required_facts.items() if not value]
        raise ValueError(
            "Dark Cloud entry audit did not reproduce its path-state finding: "
            + ", ".join(failed)
        )

    structural_audit = read_json(structural_audit_path)
    if structural_audit.get("layout_id") != "dark-cloud-browser":
        raise ValueError("Dark Cloud entry audit received the wrong structural audit")
    geometry_change_count = (
        structural_audit.get("comparison", {}).get(
            "geometry_only_changed_member_count"
        )
    )
    if not isinstance(geometry_change_count, int) or geometry_change_count <= 0:
        raise ValueError("Dark Cloud entry audit lost its geometry-change census")

    documentation_path = (
        repo / "docs/reverse-engineering/native-menus-and-boot.md"
    )
    result = {
        "schema": "solomon-dark-native-menu-dark-cloud-entry-state-stop-audit-v1",
        "status": "QUESTION",
        "finding": "dark_cloud_entry_is_already_recent_selected",
        "inputs": {
            "candidate_fixtures": candidate_receipts,
            "landed_fixtures": landed_receipts,
            "navigation_recording": file_receipt(navigation_path),
            "structural_stop_audit": file_receipt(structural_audit_path),
            "promoter_log": file_receipt(promoter_log_path),
            "navigation_contract_document": file_receipt(documentation_path),
        },
        "documentation_contract": unique_doc_clause(documentation_path),
        "candidate_layouts": {
            layout_id: {
                "generation": candidate_layouts[layout_id].get("generation"),
                "screen_id": candidate_layouts[layout_id].get("screen_id"),
                "settlement": candidate_headers[layout_id].get("settlement"),
                "semantic_multiset": multiset_receipt(candidate_sets[layout_id]),
                "geometry_free_semantic_multiset": multiset_receipt(
                    candidate_geometry_free_sets[layout_id]
                ),
            }
            for layout_id in LAYOUT_IDS
        },
        "navigation_endpoints": {
            key: endpoint_summary(value) for key, value in endpoints.items()
        },
        "required_facts": required_facts,
        "geometry_only_changed_member_count": geometry_change_count,
        "mechanism": (
            "the main-menu entry endpoint already has the exact settled Recent-tab "
            "semantic multiset and frame; activating Recent therefore leaves both "
            "the semantic multiset and frame unchanged, while activating Online "
            "Levels changes both"
        ),
        "guardrail": (
            "the generic dark_cloud_browser surface classifier cannot distinguish "
            "the selected tab; the settled capture is valid but its operator layout "
            "tag contradicts the documented entry-state contract"
        ),
        "decision_required": (
            "ATC must choose whether entry is reset and recaptured as Online Levels "
            "or authorize a durable/path-qualified browser entry layout; promotion "
            "remains stopped"
        ),
    }
    write_object(args.output.resolve(), result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
