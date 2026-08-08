#!/usr/bin/env python3
"""Audit one unauthorized landed-vs-settled structural-core difference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from native_menu_landed_diagnosis_v25 import _signature, canonical_bytes
from promote_native_menu_recapture import (
    file_receipt,
    read_json,
    validate_settlement_fixture_v25,
)


def unique_landed_entry(
    aggregate: dict[str, Any], layout_id: str
) -> dict[str, Any]:
    matches = [
        entry
        for entry in aggregate.get("layouts", [])
        if isinstance(entry, dict)
        and Path(str(entry.get("fixture", ""))).stem == layout_id
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("layout"), dict):
        raise ValueError(
            f"structural STOP audit found {len(matches)} landed {layout_id!r} entries"
        )
    return matches[0]


def semantic_members(
    layout: dict[str, Any], label: str
) -> tuple[Counter[str], dict[str, list[dict[str, Any]]]]:
    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError(f"structural STOP audit reached no {label} members")
    counter: Counter[str] = Counter()
    by_digest: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for element in elements:
        if not isinstance(element, dict):
            raise ValueError(f"structural STOP audit reached malformed {label} member")
        digest = hashlib.sha256(_signature(element)).hexdigest()
        counter[digest] += 1
        by_digest[digest].append(element)
    return counter, by_digest


def counter_witnesses(
    counter: Counter[str], members: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for digest in sorted(counter):
        values = members.get(digest, [])
        if len(values) < counter[digest]:
            raise ValueError(
                "structural STOP audit cannot resolve its semantic witness multiset"
            )
        result.append(
            {
                "semantic_sha256": digest,
                "count": counter[digest],
                "members": [
                    {
                        "captured_id": value.get("id"),
                        "captured_draw_order": value.get("draw_order"),
                        "semantic_payload": json.loads(
                            _signature(value).decode("utf-8")
                        ),
                    }
                    for value in values[: counter[digest]]
                ],
            }
        )
    return result


def geometry_only_groups(
    landed_only: Counter[str],
    landed_members: dict[str, list[dict[str, Any]]],
    settled_only: Counter[str],
    settled_members: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], int, int]:
    def grouped(
        counter: Counter[str], members: dict[str, list[dict[str, Any]]]
    ) -> dict[bytes, list[dict[str, Any]]]:
        result: dict[bytes, list[dict[str, Any]]] = defaultdict(list)
        for digest, count in counter.items():
            for element in members[digest][:count]:
                payload = json.loads(_signature(element).decode("utf-8"))
                payload.pop("rect", None)
                payload.pop("unclipped_rect", None)
                result[canonical_bytes(payload)].append(element)
        return result

    old_groups = grouped(landed_only, landed_members)
    new_groups = grouped(settled_only, settled_members)
    changes: list[dict[str, Any]] = []
    matched_old = matched_new = 0
    for signature in sorted(set(old_groups) & set(new_groups)):
        old_values = old_groups[signature]
        new_values = new_groups[signature]
        if len(old_values) != len(new_values):
            continue
        matched_old += len(old_values)
        matched_new += len(new_values)
        changes.append(
            {
                "non_geometry_payload": json.loads(signature.decode("utf-8")),
                "member_count": len(old_values),
                "landed_geometry_multiset": sorted(
                    [
                        {
                            "rect": value.get("rect"),
                            "unclipped_rect": value.get("unclipped_rect"),
                        }
                        for value in old_values
                    ],
                    key=canonical_bytes,
                ),
                "settled_geometry_multiset": sorted(
                    [
                        {
                            "rect": value.get("rect"),
                            "unclipped_rect": value.get("unclipped_rect"),
                        }
                        for value in new_values
                    ],
                    key=canonical_bytes,
                ),
            }
        )
    return (
        changes,
        sum(landed_only.values()) - matched_old,
        sum(settled_only.values()) - matched_new,
    )


def settled_identity(
    samples: list[dict[str, Any]], label: str
) -> dict[str, Any]:
    if len(samples) < 40:
        raise ValueError(f"structural STOP audit {label} has fewer than 40 samples")
    surfaces: set[Any] = set()
    screen_ids: set[Any] = set()
    semantic_generations: set[Any] = set()
    layout_generations: set[Any] = set()
    structural_payloads: set[bytes] = set()
    for sample in samples:
        payload = sample.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(
                f"structural STOP audit {label} contains a sample without payload"
            )
        surfaces.add(sample.get("semantic_surface"))
        screen_ids.add(payload.get("screen_id"))
        semantic_generations.add(sample.get("semantic_generation"))
        layout_generations.add(payload.get("generation"))
        structural_payloads.add(
            canonical_bytes(
                {
                    key: value
                    for key, value in payload.items()
                    if key != "elements"
                }
            )
        )
    return {
        "sample_count": len(samples),
        "stable_span_milliseconds": (
            samples[-1].get("elapsed_milliseconds", 0)
            - samples[0].get("elapsed_milliseconds", 0)
        ),
        "semantic_surfaces": sorted(str(value) for value in surfaces),
        "screen_ids": sorted(str(value) for value in screen_ids),
        "semantic_generations": sorted(
            value for value in semantic_generations if isinstance(value, int)
        ),
        "layout_generations": sorted(
            value for value in layout_generations if isinstance(value, int)
        ),
        "non_element_payload_variant_count": len(structural_payloads),
    }


def edge_bindings(
    navigation: dict[str, Any], layout_id: str, layout: dict[str, Any]
) -> list[dict[str, Any]]:
    edges = navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise ValueError("structural STOP audit reached no resolved navigation edges")
    result: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for side in ("before", "after"):
            endpoint = edge.get(side)
            if not isinstance(endpoint, dict) or endpoint.get("layout_id") != layout_id:
                continue
            result.append(
                {
                    "edge_id": edge.get("id"),
                    "side": side,
                    "trigger": edge.get("trigger"),
                    "equals_standalone": canonical_bytes(endpoint.get("layout"))
                    == canonical_bytes(layout),
                    "semantic_surface": endpoint.get("semantic_surface"),
                    "tagged_screen": endpoint.get("tagged_screen"),
                    "layout_generation": endpoint.get("layout_generation"),
                    "element_count": endpoint.get("element_count"),
                    "frame_sha256": endpoint.get("frame_sha256"),
                }
            )
    if not result:
        raise ValueError(
            f"structural STOP audit reached no {layout_id} navigation endpoint"
        )
    if not all(value["equals_standalone"] for value in result):
        raise ValueError(
            f"structural STOP audit found a {layout_id} endpoint unequal to standalone"
        )
    return result


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
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--layout-id", required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--promoter-log", type=Path, required=True)
    parser.add_argument("--named-stop", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    evidence_root = args.evidence_root.resolve()
    candidate_root = args.candidate_root.resolve()
    aggregate_path = repo / "tests/fixtures/webgame/menu-goldens.json"
    candidate_path = candidate_root / "menu-layouts" / f"{args.layout_id}.json"
    landed_entry = unique_landed_entry(read_json(aggregate_path), args.layout_id)
    landed_layout = landed_entry["layout"]
    candidate_fixture = read_json(candidate_path)
    record = validate_settlement_fixture_v25(
        repo, evidence_root, candidate_path, candidate_fixture
    )
    settled_layout = record["layout"]
    landed_counter, landed_members = semantic_members(
        landed_layout, "landed layout"
    )
    settled_counter, settled_members = semantic_members(
        settled_layout, "settled structural core"
    )
    common = landed_counter & settled_counter
    landed_only = landed_counter - settled_counter
    settled_only = settled_counter - landed_counter
    if not settled_only:
        raise ValueError(
            "structural STOP audit found no settled-only member to explain its STOP"
        )
    (
        geometry_changes,
        landed_only_after_geometry_count,
        settled_only_after_geometry_count,
    ) = geometry_only_groups(
        landed_only,
        landed_members,
        settled_only,
        settled_members,
    )
    navigation_path = args.navigation_recording.resolve()
    bindings = edge_bindings(
        read_json(navigation_path), args.layout_id, settled_layout
    )
    primary_header = record.get("header")
    confirmation_header = record.get("confirmation_trace", {}).get("header")
    if not isinstance(primary_header, dict) or not isinstance(
        confirmation_header, dict
    ):
        raise ValueError("structural STOP audit lost paired capture headers")
    identities = [
        [primary_header.get("instance"), primary_header.get("process_id")],
        [
            confirmation_header.get("instance"),
            confirmation_header.get("process_id"),
        ],
    ]
    if identities[0] == identities[1]:
        raise ValueError("structural STOP audit reused one capture identity")

    result = {
        "schema": "solomon-dark-native-menu-structural-supersession-stop-audit-v1",
        "status": "QUESTION",
        "layout_id": args.layout_id,
        "finding": "settled_structural_core_has_unauthorized_members_absent_from_landed",
        "named_stop": args.named_stop,
        "inputs": {
            "landed_aggregate": file_receipt(aggregate_path),
            "landed_fixture": file_receipt(
                repo / "tests/fixtures/webgame" / landed_entry["fixture"]
            ),
            "candidate_fixture": file_receipt(candidate_path),
            "primary_trace": file_receipt(record["primary_trace_path"]),
            "confirmation_trace": file_receipt(
                record["confirmation_trace_path"]
            ),
            "navigation_recording": file_receipt(navigation_path),
            "promoter_log": file_receipt(args.promoter_log.resolve()),
        },
        "comparison": {
            "landed_generation": landed_layout.get("generation"),
            "landed_member_count": sum(landed_counter.values()),
            "settled_generation": settled_layout.get("generation"),
            "settled_structural_core_member_count": sum(
                settled_counter.values()
            ),
            "common_semantic_member_count": sum(common.values()),
            "landed_only_semantic_member_count": sum(landed_only.values()),
            "settled_only_semantic_member_count": sum(settled_only.values()),
            "geometry_only_changed_member_count": sum(
                value["member_count"] for value in geometry_changes
            ),
            "landed_only_after_geometry_pairing_count": (
                landed_only_after_geometry_count
            ),
            "settled_only_after_geometry_pairing_count": (
                settled_only_after_geometry_count
            ),
            "multiset_arithmetic_closed": (
                common + landed_only == landed_counter
                and common + settled_only == settled_counter
            ),
        },
        "landed_only_members": counter_witnesses(
            landed_only, landed_members
        ),
        "settled_only_members": counter_witnesses(
            settled_only, settled_members
        ),
        "geometry_only_change_groups": geometry_changes,
        "paired_settlement": {
            "identities": identities,
            "independent_instances": True,
            "primary": settled_identity(
                record["primary_samples"], "primary"
            ),
            "confirmation": settled_identity(
                record["confirmation_samples"], "confirmation"
            ),
        },
        "navigation_bindings": bindings,
        "guardrail": (
            "no settled-only structural member is authorized outside an exact "
            "data-bound amendment; promotion remains stopped"
        ),
        "decision_required": (
            "ATC must classify every difference and, if warranted, authorize "
            "an exact layout-scoped supersession"
        ),
    }
    write_object(args.output.resolve(), result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
