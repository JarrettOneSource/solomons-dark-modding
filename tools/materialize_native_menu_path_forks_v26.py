#!/usr/bin/env python3
"""Materialize the authorized Hub path fork from recorded campaign evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


class PathForkError(RuntimeError):
    """The recorded evidence does not prove the authorized v2.6 fork."""


FORK_POLICIES = {
    "hub_new_game": {
        "parent_screen_id": "hub",
        "path_qualifier": "new_game",
        "selector": "entry_path:create_discipline_to_hub;session_state:new_game",
        "audit_labels": (
            "edge:create_discipline_to_hub:destination:primary",
            "edge:create_discipline_to_hub:destination:confirmation",
        ),
    },
    "hub_resumed": {
        "parent_screen_id": "hub",
        "path_qualifier": "resumed",
        "selector": "session_state:resumed_run",
        "audit_labels": (
            "standalone:hub:primary",
            "standalone:hub:confirmation",
        ),
    },
}


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise PathForkError(f"{path} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = evidence_root.resolve()
    if not resolved.is_relative_to(root):
        raise PathForkError(f"fork evidence escapes the campaign root: {path}")
    return {
        "evidence_path": resolved.relative_to(root).as_posix(),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def file_receipt(path: Path) -> dict[str, Any]:
    return {
        "evidence_filename": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def copy_atomically(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".menufix.tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def one_edge(path: Path) -> dict[str, Any]:
    recording = read_object(path)
    edges = recording.get("edges")
    if (
        recording.get("schema") != "solomon-dark-native-menu-navigation-v2"
        or not isinstance(edges, list)
        or len(edges) != 1
        or not isinstance(edges[0], dict)
        or edges[0].get("id") != "create_discipline_to_hub"
    ):
        raise PathForkError(
            f"{path} is not the exact create_discipline_to_hub recording"
        )
    return edges[0]


def validate_endpoint(edge: dict[str, Any], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    header = edge.get("header")
    endpoint = edge.get("after")
    if not isinstance(header, dict) or not isinstance(endpoint, dict):
        raise PathForkError(f"{label} Hub endpoint is incomplete")
    trace = endpoint.get("settlement_trace")
    settlement = endpoint.get("settlement")
    layout = endpoint.get("layout")
    samples = trace.get("settled_window_samples") if isinstance(trace, dict) else None
    if (
        not isinstance(settlement, dict)
        or settlement.get("consecutive_structural_samples", 0) < 40
        or settlement.get("stable_span_milliseconds", 0) < 2_000
        or not isinstance(layout, dict)
        or layout.get("screen_id") != "hub"
        or not isinstance(samples, list)
        or len(samples) < 40
    ):
        raise PathForkError(
            f"path-dependent core contract: {label} Hub endpoint did not settle"
        )
    for sample in samples:
        payload = sample.get("payload") if isinstance(sample, dict) else None
        if not isinstance(payload, dict) or payload.get("screen_id") != "hub":
            raise PathForkError(
                f"path-dependent core contract: {label} window changed parent screen"
            )
    source = header.get("source")
    if not isinstance(source, dict):
        raise PathForkError(f"{label} has no machine-derived provenance")
    for field, length in (
        ("base_commit_sha", 40),
        ("source_tree_sha", 40),
        ("game_executable_sha256", 64),
        ("loader_dll_sha256", 64),
        ("profile_state_identity_sha256", 64),
    ):
        value = source.get(field)
        if (
            not isinstance(value, str)
            or len(value) != length
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise PathForkError(
                f"{label} has invalid machine-derived provenance field '{field}'"
            )
    if not isinstance(header.get("profile_state"), dict):
        raise PathForkError(f"{label} has no machine-derived profile-state receipt")
    return header, endpoint


def validate_audit(audit: dict[str, Any]) -> dict[str, int]:
    observations = audit.get("observations")
    if (
        audit.get("schema")
        != "solomon-dark-menufix-hub-path-dependent-core-stop-v1"
        or not isinstance(observations, list)
        or not observations
    ):
        raise PathForkError("path-dependent core contract: fork audit is absent")
    by_label = {
        observation.get("label"): observation
        for observation in observations
        if isinstance(observation, dict)
        and isinstance(observation.get("label"), str)
    }
    if len(by_label) != len(observations):
        raise PathForkError(
            "path-dependent core contract: fork audit labels are absent or ambiguous"
        )
    counts: dict[str, int] = {}
    identities: set[tuple[str, int]] = set()
    for layout_id, policy in FORK_POLICIES.items():
        witnessed_counts: set[int] = set()
        for label in policy["audit_labels"]:
            observation = by_label.get(label)
            if not isinstance(observation, dict):
                raise PathForkError(
                    f"path-dependent core contract: fork audit lost witness '{label}'"
                )
            count = observation.get("minimum_element_count")
            identity = (observation.get("instance"), observation.get("process_id"))
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count <= 0
                or observation.get("peak_element_count") != count
                or observation.get("sample_count", 0) < 40
                or observation.get("stable_span_milliseconds", 0) < 2_000
                or observation.get("non_full_presence_members") != []
                or not isinstance(identity[0], str)
                or isinstance(identity[1], bool)
                or not isinstance(identity[1], int)
            ):
                raise PathForkError(
                    f"path-dependent core contract: witness '{label}' did not settle"
                )
            witnessed_counts.add(count)
            identities.add(identity)
        if len(witnessed_counts) != 1:
            raise PathForkError(
                f"path-dependent core contract: '{layout_id}' instances disagree"
            )
        counts[layout_id] = witnessed_counts.pop()
    if len(identities) != 4:
        raise PathForkError(
            "path-dependent core contract: fork lacks four fresh instance witnesses"
        )
    if len(set(counts.values())) != len(counts):
        raise PathForkError(
            "path-dependent core contract: authorized Hub states do not differ in census"
        )
    return counts


def capture_header(edge_header: dict[str, Any], label: str) -> dict[str, Any]:
    return {
        "label": label,
        "instance": edge_header["instance"],
        "process_id": edge_header["process_id"],
        "source": copy.deepcopy(edge_header["source"]),
        "profile_state": copy.deepcopy(edge_header["profile_state"]),
        "recorded_live": True,
        "captured_at_utc": edge_header["captured_at_utc"],
        "capture_method": edge_header["capture_method"],
    }


def make_trace(
    edge_header: dict[str, Any], endpoint: dict[str, Any], label: str
) -> dict[str, Any]:
    trace = endpoint["settlement_trace"]
    result = {
        "schema": "solomon-dark-native-menu-settlement-trace-v2",
        "header": capture_header(edge_header, label),
        "settlement": copy.deepcopy(endpoint["settlement"]),
        "structural_phases": copy.deepcopy(trace["structural_phases"]),
        "settled_window_samples": copy.deepcopy(trace["settled_window_samples"]),
    }
    if "high_cadence_sample_count" in trace:
        result["high_cadence_sample_count"] = trace["high_cadence_sample_count"]
    if "high_cadence_structural_phases" in trace:
        result["high_cadence_structural_phases"] = copy.deepcopy(
            trace["high_cadence_structural_phases"]
        )
    return result


def make_confirmation(
    edge_header: dict[str, Any], endpoint: dict[str, Any], label: str
) -> dict[str, Any]:
    trace = endpoint["settlement_trace"]
    return {
        "schema": "solomon-dark-native-menu-animation-confirmation-v4",
        "header": capture_header(edge_header, label),
        "settlement": copy.deepcopy(endpoint["settlement"]),
        "animated_element_ids": copy.deepcopy(endpoint["animated_element_ids"]),
        "raw_primary_animated_element_ids": [],
        "raw_sets_match_noncontractual": True,
        "requires_campaign_resolution": True,
        "structural_sha256": endpoint["settlement"]["structural_sha256"],
        "confirmation_layout": copy.deepcopy(endpoint["layout"]),
        "structural_phases": copy.deepcopy(trace["structural_phases"]),
        "settled_window_samples": copy.deepcopy(trace["settled_window_samples"]),
    }


def fork_metadata(
    layout_id: str, count: int, audit_receipt: dict[str, Any]
) -> dict[str, Any]:
    policy = FORK_POLICIES[layout_id]
    return {
        "parent_screen_id": policy["parent_screen_id"],
        "path_qualifier": policy["path_qualifier"],
        "selector": policy["selector"],
        "measured_settled_element_count": count,
        "fork_decision": copy.deepcopy(audit_receipt),
    }


def materialize(
    candidate_root: Path,
    evidence_root: Path,
    primary_navigation_path: Path,
    confirmation_navigation_path: Path,
    fork_audit_path: Path,
    primary_reference_path: Path,
) -> dict[str, Any]:
    audit_receipt = evidence_receipt(fork_audit_path, evidence_root)
    counts = validate_audit(read_object(fork_audit_path))
    primary_header, primary_endpoint = validate_endpoint(
        one_edge(primary_navigation_path), "primary"
    )
    confirmation_header, confirmation_endpoint = validate_endpoint(
        one_edge(confirmation_navigation_path), "confirmation"
    )
    if (
        primary_header["instance"],
        primary_header["process_id"],
    ) == (
        confirmation_header["instance"],
        confirmation_header["process_id"],
    ):
        raise PathForkError(
            "path-dependent core contract: new-game Hub pair reused one instance"
        )
    if (
        primary_endpoint["settlement"]["element_count"]
        != counts["hub_new_game"]
        or confirmation_endpoint["settlement"]["element_count"]
        != counts["hub_new_game"]
    ):
        raise PathForkError(
            "path-dependent core contract: new-game Hub pair disagrees with fork audit"
        )

    menu_root = candidate_root / "menu-layouts"
    transition_root = candidate_root / "menu-transition-layouts"
    trace_root = candidate_root / "menu-settlement-traces"
    confirmation_root = candidate_root / "menu-animation-confirmations"
    reference_root = candidate_root / "menu-reference-captures"
    original_fixture_path = menu_root / "hub.json"
    resumed_fixture_path = transition_root / "hub_resumed.json"
    if original_fixture_path.is_file():
        resumed = read_object(original_fixture_path)
    elif resumed_fixture_path.is_file():
        resumed = read_object(resumed_fixture_path)
    else:
        raise PathForkError("path-dependent core contract: Hub baseline is absent")
    original_trace_path = trace_root / "hub.settlement.json"
    resumed_trace_path = trace_root / "hub_resumed.settlement.json"
    original_confirmation_path = confirmation_root / "hub.confirmation.json"
    resumed_confirmation_path = confirmation_root / "hub_resumed.confirmation.json"
    original_reference_path = reference_root / "hub.png"
    resumed_reference_path = reference_root / "hub_resumed.png"

    resumed_trace = read_object(
        original_trace_path if original_trace_path.is_file() else resumed_trace_path
    )
    resumed_confirmation = read_object(
        original_confirmation_path
        if original_confirmation_path.is_file()
        else resumed_confirmation_path
    )
    resumed_reference_source = (
        original_reference_path
        if original_reference_path.is_file()
        else resumed_reference_path
    )
    resumed["header"]["label"] = "hub_resumed"
    resumed["header"]["path_dependent_core"] = fork_metadata(
        "hub_resumed", counts["hub_resumed"], audit_receipt
    )
    resumed_trace["header"]["label"] = "hub_resumed"
    resumed_confirmation["header"]["label"] = "hub_resumed"
    write_object(resumed_trace_path, resumed_trace)
    write_object(resumed_confirmation_path, resumed_confirmation)
    copy_atomically(resumed_reference_source, resumed_reference_path)
    resumed["header"]["raw_recording"] = file_receipt(resumed_trace_path)
    resumed["header"]["reference_capture"] = (
        "../menu-reference-captures/hub_resumed.png"
    )
    resumed_confirmation_receipt = file_receipt(resumed_confirmation_path)
    resumed_confirmation_receipt.update(
        {
            "instance": resumed_confirmation["header"]["instance"],
            "process_id": resumed_confirmation["header"]["process_id"],
            "source": copy.deepcopy(resumed_confirmation["header"]["source"]),
            "profile_state": copy.deepcopy(
                resumed_confirmation["header"]["profile_state"]
            ),
            "confirmation_structural_sha256": resumed_confirmation[
                "structural_sha256"
            ],
            "animated_element_ids_sha256": hashlib.sha256(b"[]").hexdigest(),
            "raw_primary_animated_element_ids": copy.deepcopy(
                resumed_confirmation.get("raw_primary_animated_element_ids", [])
            ),
            "raw_confirmation_animated_element_ids": copy.deepcopy(
                resumed_confirmation.get("animated_element_ids", [])
            ),
            "raw_sets_match_noncontractual": resumed_confirmation.get(
                "raw_sets_match_noncontractual"
            ),
            "requires_campaign_resolution": True,
        }
    )
    resumed["header"]["animation_confirmation"] = resumed_confirmation_receipt
    write_object(resumed_fixture_path, resumed)

    new_trace_path = trace_root / "hub_new_game.settlement.json"
    new_confirmation_path = confirmation_root / "hub_new_game.confirmation.json"
    new_reference_path = reference_root / "hub_new_game.png"
    new_trace = make_trace(primary_header, primary_endpoint, "hub_new_game")
    new_confirmation = make_confirmation(
        confirmation_header, confirmation_endpoint, "hub_new_game"
    )
    write_object(new_trace_path, new_trace)
    write_object(new_confirmation_path, new_confirmation)
    copy_atomically(primary_reference_path, new_reference_path)
    new_fixture = {
        "schema": "solomon-dark-native-menu-layout-v2",
        "header": {
            **capture_header(primary_header, "hub_new_game"),
            "settlement": copy.deepcopy(primary_endpoint["settlement"]),
            "raw_recording": file_receipt(new_trace_path),
            "reference_capture": "../menu-reference-captures/hub_new_game.png",
            "animation_confirmation": {
                **file_receipt(new_confirmation_path),
                "instance": confirmation_header["instance"],
                "process_id": confirmation_header["process_id"],
                "source": copy.deepcopy(confirmation_header["source"]),
                "profile_state": copy.deepcopy(
                    confirmation_header["profile_state"]
                ),
                "confirmation_structural_sha256": confirmation_endpoint[
                    "settlement"
                ]["structural_sha256"],
                "animated_element_ids_sha256": hashlib.sha256(b"[]").hexdigest(),
                "raw_primary_animated_element_ids": [],
                "raw_confirmation_animated_element_ids": [],
                "raw_sets_match_noncontractual": True,
                "requires_campaign_resolution": True,
            },
            "path_dependent_core": fork_metadata(
                "hub_new_game", counts["hub_new_game"], audit_receipt
            ),
        },
        "layout": copy.deepcopy(primary_endpoint["layout"]),
    }
    new_fixture_path = transition_root / "hub_new_game.json"
    write_object(new_fixture_path, new_fixture)

    for obsolete in (
        original_fixture_path,
        original_trace_path,
        original_confirmation_path,
        original_reference_path,
    ):
        if obsolete.is_file():
            obsolete.unlink()
    return {
        "success": True,
        "settlement_spec": "2.6",
        "fork_decision": audit_receipt,
        "layouts": {
            "hub_new_game": {
                "fixture": str(new_fixture_path),
                "measured_settled_element_count": counts["hub_new_game"],
            },
            "hub_resumed": {
                "fixture": str(resumed_fixture_path),
                "measured_settled_element_count": counts["hub_resumed"],
            },
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--primary-navigation", required=True, type=Path)
    parser.add_argument("--confirmation-navigation", required=True, type=Path)
    parser.add_argument("--fork-audit", required=True, type=Path)
    parser.add_argument("--primary-reference", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = materialize(
            args.candidate_root.resolve(),
            args.evidence_root.resolve(),
            args.primary_navigation.resolve(),
            args.confirmation_navigation.resolve(),
            args.fork_audit.resolve(),
            args.primary_reference.resolve(),
        )
    except (KeyError, OSError, PathForkError, TypeError, ValueError) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
