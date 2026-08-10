#!/usr/bin/env python3
"""Append the paired profile-select New Game capture to the G11 graph."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


EDGE_ID = "profile_select_new_game_to_create"
PROFILE_IDENTITY = (
    "0539412d5c91207d5b225e86f79795d260fe7b73b8d9a1c29166bd09b445e372"
)


class ImportError(RuntimeError):
    """The new edge or its target graph is incomplete or ambiguous."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImportError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ImportError(f"{path} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = evidence_root.resolve()
    if not resolved.is_relative_to(root):
        raise ImportError(f"receipt escapes evidence root: {resolved}")
    return {
        "evidence_path": resolved.relative_to(root).as_posix(),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def one_edge(recording: dict[str, Any], label: str) -> dict[str, Any]:
    if recording.get("schema") != "solomon-dark-native-menu-navigation-v2":
        raise ImportError(f"{label} edge recording has the wrong schema")
    edges = recording.get("edges")
    if not isinstance(edges, list) or len(edges) != 1:
        raise ImportError(f"{label} edge recording does not contain one edge")
    edge = edges[0]
    if not isinstance(edge, dict):
        raise ImportError(f"{label} edge is not an object")
    if (
        edge.get("id") != EDGE_ID
        or edge.get("source") != "profile_save_select"
        or edge.get("destination") != "create_element"
        or edge.get("action_id") != "main_menu.new_game"
        or edge.get("trigger") != "new_game_click"
    ):
        raise ImportError(f"{label} edge identity or measured destination changed")
    header = edge.get("header")
    if not isinstance(header, dict):
        raise ImportError(f"{label} edge has no header")
    source = header.get("source")
    profile = header.get("profile_state")
    binding = header.get("profile_state_binding")
    if (
        not isinstance(source, dict)
        or source.get("profile_state_identity_sha256") != PROFILE_IDENTITY
        or not isinstance(profile, dict)
        or profile.get("profile_state_identity_sha256") != PROFILE_IDENTITY
        or profile.get("baseline_id") != "pristine_fresh_install"
        or not isinstance(binding, dict)
        or binding.get("baseline_id") != "pristine_fresh_install"
        or binding.get("edge_id") != EDGE_ID
    ):
        raise ImportError(f"{label} edge lost its pristine per-binding provenance")
    for side, screen in (("before", "profile_save_select"), ("after", "create_element")):
        endpoint = edge.get(side)
        if not isinstance(endpoint, dict):
            raise ImportError(f"{label} edge has no {side} endpoint")
        if (
            endpoint.get("semantic_surface") != screen
            or endpoint.get("machine_classified_surface") != screen
            or endpoint.get("tagged_screen") != screen
        ):
            raise ImportError(f"{label} edge {side} failed classifier/tag agreement")
        settlement = endpoint.get("settlement")
        trace = endpoint.get("settlement_trace")
        samples = trace.get("settled_window_samples") if isinstance(trace, dict) else None
        if (
            not isinstance(settlement, dict)
            or settlement.get("consecutive_structural_samples", 0) < 40
            or settlement.get("stable_span_milliseconds", 0) < 2_000
            or not isinstance(samples, list)
            or len(samples) < 40
        ):
            raise ImportError(f"{label} edge {side} did not settle")
        generations = {
            sample.get("payload", {}).get("generation")
            for sample in samples
            if isinstance(sample, dict) and isinstance(sample.get("payload"), dict)
        }
        if len(generations) != 1:
            raise ImportError(f"{label} edge {side} changed generation mid-window")
    return edge


def old_graph(recording: dict[str, Any], label: str) -> None:
    if recording.get("schema") != "solomon-dark-native-menu-navigation-v2":
        raise ImportError(f"{label} graph has the wrong schema")
    edges = recording.get("edges")
    if not isinstance(edges, list) or len(edges) != 39:
        raise ImportError(f"{label} graph did not reach the exact 39-edge baseline")
    edge_ids = [edge.get("id") for edge in edges if isinstance(edge, dict)]
    if len(edge_ids) != 39 or len(set(edge_ids)) != 39:
        raise ImportError(f"{label} graph edge ids are absent or ambiguous")
    if EDGE_ID in edge_ids:
        raise ImportError(f"{label} graph already contains the chartered edge")


def copy_receipt(source: Path, destination_root: Path) -> Path:
    if not source.is_file():
        raise ImportError(f"profile-state receipt is absent: {source}")
    destination = destination_root / source.name
    if destination.exists():
        if (
            destination.stat().st_size != source.stat().st_size
            or sha256_file(destination) != sha256_file(source)
        ):
            raise ImportError(f"profile-state receipt basename is ambiguous: {source.name}")
        return destination
    shutil.copyfile(source, destination)
    return destination


def merge_role(
    old_path: Path,
    edge_path: Path,
    output_path: Path,
    label: str,
) -> dict[str, Any]:
    old = read_object(old_path)
    new = read_object(edge_path)
    old_graph(old, label)
    edge = one_edge(new, label)
    old["edges"].append(edge)
    if len(old["edges"]) != 40:
        raise ImportError(f"{label} graph did not gain exactly one edge")
    old_header = old.get("header")
    new_header = new.get("header")
    old_sessions = old_header.get("sessions") if isinstance(old_header, dict) else None
    new_sessions = new_header.get("sessions") if isinstance(new_header, dict) else None
    if (
        not isinstance(old_sessions, list)
        or not old_sessions
        or not isinstance(new_sessions, list)
        or len(new_sessions) != 1
    ):
        raise ImportError(f"{label} session provenance is incomplete")
    old_sessions.append(new_sessions[0])
    old_header["chartered_addition"] = {
        "edge_id": EDGE_ID,
        "source": "profile_save_select",
        "destination": "create_element",
        "measurement": "paired pristine route; destination machine-classified",
        "old_navigation_edge_count": 39,
        "new_navigation_edge_count": 40,
    }
    atomic_json(output_path, old)
    return {
        "input_graph": old_path,
        "edge_recording": edge_path,
        "output_graph": output_path,
        "instance": edge["header"].get("instance"),
        "process_id": edge["header"].get("process_id"),
        "source_generation": edge["before"].get("layout_generation"),
        "destination_generation": edge["after"].get("layout_generation"),
        "source_sample_count": edge["before"]["settlement"].get(
            "consecutive_structural_samples"
        ),
        "destination_sample_count": edge["after"]["settlement"].get(
            "consecutive_structural_samples"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--old-primary", type=Path, required=True)
    parser.add_argument("--old-confirmation", type=Path, required=True)
    parser.add_argument("--edge-primary", type=Path, required=True)
    parser.add_argument("--edge-confirmation", type=Path, required=True)
    parser.add_argument("--old-profile-receipts", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    evidence = args.evidence_root.resolve()
    output_root = args.output_root.resolve()
    if not output_root.is_relative_to(evidence):
        raise ImportError("output root escapes the campaign evidence root")
    output_root.mkdir(parents=True, exist_ok=True)
    profile_root = output_root / "navigation-v219-profile-state-receipts"
    profile_root.mkdir(exist_ok=True)

    old_receipts = sorted(args.old_profile_receipts.resolve().glob("*.json"))
    if len(old_receipts) != 5:
        raise ImportError("old graph did not expose its exact five profile receipts")
    copied = [copy_receipt(path, profile_root) for path in old_receipts]
    role_inputs = {
        "primary": (args.old_primary.resolve(), args.edge_primary.resolve()),
        "confirmation": (
            args.old_confirmation.resolve(),
            args.edge_confirmation.resolve(),
        ),
    }
    results: dict[str, Any] = {}
    identities: set[tuple[Any, Any]] = set()
    for label, (old_path, edge_path) in role_inputs.items():
        edge_recording = read_object(edge_path)
        edge = one_edge(edge_recording, label)
        identities.add((edge["header"].get("instance"), edge["header"].get("process_id")))
        receipt_name = edge["header"]["profile_state"]["launch_receipt"][
            "evidence_filename"
        ]
        source_receipts = list(edge_path.parent.glob(f"**/{receipt_name}"))
        if len(source_receipts) != 1:
            raise ImportError(
                f"{label} new-edge profile receipt is absent or ambiguous"
            )
        copied.append(copy_receipt(source_receipts[0], profile_root))
        output_path = output_root / f"navigation-{label}-v219-40-edges.json"
        results[label] = merge_role(
            old_path, edge_path, output_path, label
        )
    if len(identities) != 2:
        raise ImportError("new edge pair does not use two independent instances")

    audit_path = output_root / "profile-select-new-game-edge-import-audit.json"
    audit = {
        "schema": "solomon-dark-native-menu-profile-new-game-edge-import-v1",
        "status": "PROVEN",
        "edge_id": EDGE_ID,
        "profile_state_identity_sha256": PROFILE_IDENTITY,
        "old_navigation_edge_count": 39,
        "new_navigation_edge_count": 40,
        "exactly_one_edge_added": True,
        "destination_measured_not_assumed": "create_element",
        "roles": {
            label: {
                **{
                    key: value
                    for key, value in result.items()
                    if key not in {"input_graph", "edge_recording", "output_graph"}
                },
                "input_graph": receipt(result["input_graph"], evidence),
                "edge_recording": receipt(result["edge_recording"], evidence),
                "output_graph": receipt(result["output_graph"], evidence),
            }
            for label, result in results.items()
        },
        "profile_state_receipts": [
            receipt(path, evidence) for path in sorted(set(copied))
        ],
        "profile_state_receipt_count": len(set(copied)),
        "candidate_applied": False,
    }
    atomic_json(audit_path, audit)
    print(json.dumps({"audit": receipt(audit_path, evidence)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
