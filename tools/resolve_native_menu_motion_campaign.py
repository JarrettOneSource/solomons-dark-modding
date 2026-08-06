#!/usr/bin/env python3
"""Resolve v2.3 motion capability across one Settlement v2.4 menu campaign."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

if __package__:
    from .native_menu_settlement_v2 import (
        SettlementV2Error,
        canonical_bytes,
        classify_window,
        resolve_motion_capability,
        structural_layout_bytes,
    )
else:
    from native_menu_settlement_v2 import (
        SettlementV2Error,
        canonical_bytes,
        classify_window,
        resolve_motion_capability,
        structural_layout_bytes,
    )


class ResolutionError(RuntimeError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ResolutionError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = evidence_root.resolve()
    if not resolved.is_relative_to(root):
        raise ResolutionError(f"evidence path escapes the campaign root: {path}")
    return {
        "evidence_path": resolved.relative_to(root).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def resolve_unique_evidence(
    evidence_root: Path,
    adjacent: Path,
    filename: str,
) -> Path:
    if not filename:
        raise ResolutionError("evidence lookup received an empty filename")
    candidates = {
        path.resolve()
        for path in (adjacent / filename, *evidence_root.rglob(filename))
        if path.is_file()
    }
    if len(candidates) != 1:
        raise ResolutionError(
            f"evidence lookup for {filename!r} is absent or ambiguous: "
            f"{sorted(str(path) for path in candidates)}"
        )
    return candidates.pop()


def validate_receipt(path: Path, receipt: dict[str, Any], label: str) -> None:
    if path.stat().st_size != receipt.get("bytes"):
        raise ResolutionError(f"{label} records a false evidence byte count")
    if file_sha256(path) != receipt.get("sha256"):
        raise ResolutionError(f"{label} records a false evidence SHA-256")


def write_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _source_bytes(header: dict[str, Any]) -> bytes:
    source = header.get("source")
    if not isinstance(source, dict):
        raise ResolutionError("capture header has no machine-derived source provenance")
    return canonical_bytes(source)


def _observation(
    *,
    layout_id: str,
    pair_id: str,
    header: dict[str, Any],
    layout: dict[str, Any],
    settlement: dict[str, Any],
    samples: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "layout_id": layout_id,
        "pair_id": pair_id,
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "evidence": evidence,
        "layout": layout,
        "settlement": settlement,
        "samples": samples,
    }


def _screen_id(layout: dict[str, Any], label: str) -> str:
    screen_id = layout.get("screen_id")
    if not isinstance(screen_id, str) or not screen_id:
        raise ResolutionError(f"{label} has no native screen id")
    return screen_id


def _settled_samples(trace: dict[str, Any], label: str) -> list[dict[str, Any]]:
    samples = trace.get("settled_window_samples")
    if not isinstance(samples, list) or not samples:
        raise ResolutionError(f"{label} has no settled-window samples")
    if not all(isinstance(sample, dict) for sample in samples):
        raise ResolutionError(f"{label} settled window contains a non-object sample")
    return samples


def collect_standalones(
    candidate_root: Path,
    evidence_root: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    dict[int, tuple[str, Path]],
]:
    fixture_paths = sorted((candidate_root / "menu-layouts").glob("*.json"))
    fixture_paths += sorted(
        (candidate_root / "menu-transition-layouts").glob("*.json")
    )
    if not fixture_paths:
        raise ResolutionError("standalone sweep reached no candidate fixtures")
    fixtures: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    targets: dict[int, tuple[str, Path]] = {}
    for fixture_path in fixture_paths:
        fixture = read_object(fixture_path)
        if fixture.get("schema") != "solomon-dark-native-menu-layout-v2":
            raise ResolutionError(f"{fixture_path} is not a menu layout fixture")
        header = fixture.get("header")
        layout = fixture.get("layout")
        if not isinstance(header, dict) or not isinstance(layout, dict):
            raise ResolutionError(f"{fixture_path} has no header/layout")
        screen_id = _screen_id(layout, str(fixture_path))
        layout_id = fixture_path.stem
        if layout_id in fixtures:
            raise ResolutionError(
                f"standalone layout '{layout_id}' is ambiguous between fixtures"
            )
        raw_receipt = header.get("settlement_trace", header.get("raw_recording"))
        if not isinstance(raw_receipt, dict):
            raise ResolutionError(f"{fixture_path} has no raw recording receipt")
        raw_path = resolve_unique_evidence(
            evidence_root,
            fixture_path.parent,
            str(raw_receipt.get("evidence_filename", "")),
        )
        validate_receipt(raw_path, raw_receipt, str(fixture_path))
        raw_trace = read_object(raw_path)
        samples = _settled_samples(raw_trace, str(raw_path))
        try:
            primary_classification = classify_window(samples)
        except SettlementV2Error as error:
            raise ResolutionError(f"{raw_path}: {error}") from error

        confirmation_receipt = header.get("animation_confirmation")
        if not isinstance(confirmation_receipt, dict):
            raise ResolutionError(
                f"{fixture_path} has no independent animation confirmation"
            )
        confirmation_path = resolve_unique_evidence(
            evidence_root,
            fixture_path.parent,
            str(confirmation_receipt.get("evidence_filename", "")),
        )
        validate_receipt(
            confirmation_path, confirmation_receipt, f"{fixture_path} confirmation"
        )
        confirmation = read_object(confirmation_path)
        if confirmation.get("schema") not in {
            "solomon-dark-native-menu-animation-confirmation-v2",
            "solomon-dark-native-menu-animation-confirmation-v3",
        }:
            raise ResolutionError(
                f"{confirmation_path} is not an animation confirmation"
            )
        confirmation_header = confirmation.get("header")
        confirmation_layout = confirmation.get("confirmation_layout")
        confirmation_settlement = confirmation.get("settlement")
        if not all(
            isinstance(value, dict)
            for value in (
                confirmation_header,
                confirmation_layout,
                confirmation_settlement,
            )
        ):
            raise ResolutionError(f"{confirmation_path} is incomplete")
        if _screen_id(confirmation_layout, str(confirmation_path)) != screen_id:
            raise ResolutionError(f"{fixture_path} confirmation changed screen")
        if _source_bytes(header) != _source_bytes(confirmation_header):
            raise ResolutionError(f"{fixture_path} confirmation changed provenance")
        confirmation_samples = _settled_samples(
            confirmation, str(confirmation_path)
        )
        pair_id = f"standalone:{layout_id}"
        primary_index = len(observations)
        observations.append(
            _observation(
                layout_id=layout_id,
                pair_id=pair_id,
                header=header,
                layout=primary_classification["layout"],
                settlement={
                    key: copy.deepcopy(value)
                    for key, value in primary_classification.items()
                    if key != "layout"
                },
                samples=samples,
                evidence=evidence_receipt(raw_path, evidence_root),
            )
        )
        confirmation_index = len(observations)
        observations.append(
            _observation(
                layout_id=layout_id,
                pair_id=pair_id,
                header=confirmation_header,
                layout=confirmation_layout,
                settlement=confirmation_settlement,
                samples=confirmation_samples,
                evidence=evidence_receipt(confirmation_path, evidence_root),
            )
        )
        fixtures[layout_id] = {
            "path": fixture_path,
            "value": fixture,
            "confirmation": confirmation,
            "native_screen_id": screen_id,
            "raw_primary_layout": primary_classification["layout"],
            "confirmation_path": confirmation_path,
            "primary_index": primary_index,
            "confirmation_index": confirmation_index,
        }
        targets[primary_index] = ("standalone_primary", fixture_path)
        targets[confirmation_index] = ("standalone_confirmation", confirmation_path)
    return fixtures, observations, targets


def collect_navigation(
    primary_path: Path,
    confirmation_path: Path,
    evidence_root: Path,
    fixtures: dict[str, dict[str, Any]],
    observations: list[dict[str, Any]],
    targets: dict[int, tuple[str, Path]],
) -> tuple[dict[str, Any], dict[str, Any], dict[int, tuple[str, str, str]]]:
    primary = read_object(primary_path)
    confirmation = read_object(confirmation_path)
    for label, value in (("primary", primary), ("confirmation", confirmation)):
        if value.get("schema") != "solomon-dark-native-menu-navigation-v2":
            raise ResolutionError(f"{label} navigation schema is not recognized")
    primary_edges = primary.get("edges")
    confirmation_edges = confirmation.get("edges")
    if not isinstance(primary_edges, list) or not isinstance(confirmation_edges, list):
        raise ResolutionError("navigation recording has no edge list")
    primary_by_id = {edge.get("id"): edge for edge in primary_edges if isinstance(edge, dict)}
    confirmation_by_id = {
        edge.get("id"): edge for edge in confirmation_edges if isinstance(edge, dict)
    }
    if (
        len(primary_by_id) != len(primary_edges)
        or len(confirmation_by_id) != len(confirmation_edges)
        or set(primary_by_id) != set(confirmation_by_id)
        or not primary_by_id
    ):
        raise ResolutionError(
            "primary/confirmation navigation edge census is absent or ambiguous"
        )
    navigation_targets: dict[int, tuple[str, str, str]] = {}
    receipts = {
        "primary": evidence_receipt(primary_path, evidence_root),
        "confirmation": evidence_receipt(confirmation_path, evidence_root),
    }
    for edge_id in sorted(primary_by_id):
        primary_edge = primary_by_id[edge_id]
        confirmation_edge = confirmation_by_id[edge_id]
        primary_header = primary_edge.get("header")
        confirmation_header = confirmation_edge.get("header")
        if not isinstance(primary_header, dict) or not isinstance(
            confirmation_header, dict
        ):
            raise ResolutionError(f"edge {edge_id} has no capture headers")
        if _source_bytes(primary_header) != _source_bytes(confirmation_header):
            raise ResolutionError(f"edge {edge_id} confirmation changed provenance")
        for side, endpoint_key in (("source", "before"), ("destination", "after")):
            pair_id = f"edge:{edge_id}:{side}"
            for capture_label, edge, header in (
                ("primary", primary_edge, primary_header),
                ("confirmation", confirmation_edge, confirmation_header),
            ):
                endpoint = edge.get(endpoint_key)
                if not isinstance(endpoint, dict):
                    raise ResolutionError(
                        f"edge {edge_id} {capture_label} {side} is absent"
                    )
                layout = endpoint.get("layout")
                settlement = endpoint.get("settlement")
                trace = endpoint.get("settlement_trace")
                if not all(
                    isinstance(value, dict)
                    for value in (layout, settlement, trace)
                ):
                    raise ResolutionError(
                        f"edge {edge_id} {capture_label} {side} is incomplete"
                    )
                samples = _settled_samples(
                    trace, f"edge {edge_id} {capture_label} {side}"
                )
                try:
                    classification = classify_window(samples)
                except SettlementV2Error as error:
                    raise ResolutionError(
                        f"edge {edge_id} {capture_label} {side}: {error}"
                    ) from error
                endpoint_layout = classification["layout"]
                endpoint_ids = set(endpoint_layout["animated_element_ids"])
                layout_matches: list[str] = []
                for layout_id, fixture_record in fixtures.items():
                    standalone_layout = fixture_record["raw_primary_layout"]
                    if standalone_layout.get("screen_id") != endpoint_layout.get(
                        "screen_id"
                    ):
                        continue
                    comparison_ids = endpoint_ids | set(
                        standalone_layout.get("animated_element_ids", [])
                    )
                    try:
                        matches = structural_layout_bytes(
                            endpoint_layout, comparison_ids
                        ) == structural_layout_bytes(
                            standalone_layout, comparison_ids
                        )
                    except SettlementV2Error:
                        matches = False
                    if matches:
                        layout_matches.append(layout_id)
                if len(layout_matches) != 1:
                    raise ResolutionError(
                        f"edge {edge_id} {capture_label} {side} does not resolve "
                        f"one standalone layout: {layout_matches}"
                    )
                layout_id = layout_matches[0]
                index = len(observations)
                observations.append(
                    _observation(
                        layout_id=layout_id,
                        pair_id=pair_id,
                        header=header,
                        layout=classification["layout"],
                        settlement={
                            key: copy.deepcopy(value)
                            for key, value in classification.items()
                            if key != "layout"
                        },
                        samples=samples,
                        evidence=receipts[capture_label],
                    )
                )
                targets[index] = (
                    f"navigation_{capture_label}_{side}",
                    primary_path if capture_label == "primary" else confirmation_path,
                )
                navigation_targets[index] = (capture_label, str(edge_id), endpoint_key)
    return primary, confirmation, navigation_targets


def collect_extended(
    observation_root: Path, evidence_root: Path
) -> list[dict[str, Any]]:
    if not observation_root.exists():
        return []
    result: list[dict[str, Any]] = []
    seen_identities: set[tuple[str, int, str]] = set()
    for path in sorted(observation_root.rglob("*.json")):
        value = read_object(path)
        if value.get("schema") != (
            "solomon-dark-native-menu-motion-capability-observation-v1"
        ):
            continue
        header = value.get("header")
        samples = value.get("samples")
        if not isinstance(header, dict) or not isinstance(samples, list) or not samples:
            raise ResolutionError(f"extended observation {path} is incomplete")
        label = header.get("label")
        instance = header.get("instance")
        process_id = header.get("process_id")
        if (
            not isinstance(label, str)
            or not label
            or not isinstance(instance, str)
            or not instance
            or isinstance(process_id, bool)
            or not isinstance(process_id, int)
            or process_id <= 0
        ):
            raise ResolutionError(
                f"extended observation {path} has no exact screen/process identity"
            )
        identity = (instance, process_id, label)
        if identity in seen_identities:
            raise ResolutionError(
                f"extended observation identity is ambiguous: {identity}"
            )
        seen_identities.add(identity)
        result.append(
            {
                "screen_id": label,
                "instance": instance,
                "process_id": process_id,
                "baseline": copy.deepcopy(header.get("baseline")),
                "samples": samples,
                "evidence": evidence_receipt(path, evidence_root),
            }
        )
    return result


def resolve_campaign(
    candidate_root: Path,
    evidence_root: Path,
    primary_navigation_path: Path,
    confirmation_navigation_path: Path,
    motion_observation_root: Path,
    resolved_navigation_output: Path,
    audit_output: Path,
    apply: bool,
    verify: bool = False,
) -> dict[str, Any]:
    if apply and verify:
        raise ResolutionError("motion campaign cannot apply and verify simultaneously")
    fixtures, observations, targets = collect_standalones(
        candidate_root, evidence_root
    )
    primary_navigation, _, navigation_targets = collect_navigation(
        primary_navigation_path,
        confirmation_navigation_path,
        evidence_root,
        fixtures,
        observations,
        targets,
    )
    extended = collect_extended(motion_observation_root, evidence_root)

    observations_by_screen: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, observation in enumerate(observations):
        _screen_id(observation["layout"], f"observation {index}")
        layout_id = observation.get("layout_id")
        if not isinstance(layout_id, str) or layout_id not in fixtures:
            raise ResolutionError(
                f"observation {index} does not resolve a candidate layout"
            )
        observations_by_screen.setdefault(layout_id, []).append((index, observation))
    if set(fixtures) - set(observations_by_screen):
        raise ResolutionError("standalone sweep produced an unreachable screen")
    extended_by_screen: dict[str, list[dict[str, Any]]] = {}
    fixture_name_to_layout = {
        record["path"].name: layout_id for layout_id, record in fixtures.items()
    }
    confirmation_name_to_layout = {
        record["confirmation_path"].name: layout_id
        for layout_id, record in fixtures.items()
    }
    navigation_layout_by_selector: dict[tuple[str, str, str, int], str] = {}
    for index, (_, edge_id, endpoint_key) in navigation_targets.items():
        observation = observations[index]
        side = "source" if endpoint_key == "before" else "destination"
        navigation_layout_by_selector[
            (
                edge_id,
                side,
                str(observation["instance"]),
                int(observation["process_id"]),
            )
        ] = str(observation["layout_id"])
    for observation in extended:
        baseline = observation.get("baseline")
        if not isinstance(baseline, dict):
            raise ResolutionError("extended observation lost its baseline selector")
        selector = baseline.get("selector")
        filename = baseline.get("evidence_filename")
        if not isinstance(selector, dict) or not isinstance(filename, str):
            raise ResolutionError("extended observation baseline is incomplete")
        schema = selector.get("schema")
        layout_id: str | None = None
        if schema == "solomon-dark-native-menu-layout-v2":
            layout_id = fixture_name_to_layout.get(filename)
        elif schema in {
            "solomon-dark-native-menu-animation-confirmation-v2",
            "solomon-dark-native-menu-animation-confirmation-v3",
        }:
            layout_id = confirmation_name_to_layout.get(filename)
        elif schema == "solomon-dark-native-menu-navigation-v2":
            layout_id = navigation_layout_by_selector.get(
                (
                    str(selector.get("edge_id", "")),
                    str(selector.get("edge_side", "")),
                    str(observation["instance"]),
                    int(observation["process_id"]),
                )
            )
        if layout_id is None:
            raise ResolutionError(
                "extended observation baseline does not resolve one campaign layout"
            )
        if fixtures[layout_id]["native_screen_id"] != observation["screen_id"]:
            raise ResolutionError(
                f"extended observation for {layout_id} changed native screen identity"
            )
        extended_by_screen.setdefault(layout_id, []).append(observation)

    resolved_by_index: dict[int, dict[str, Any]] = {}
    proofs: dict[str, dict[str, Any]] = {}
    screen_audit: list[dict[str, Any]] = []
    for screen_id in sorted(observations_by_screen):
        indexed = observations_by_screen[screen_id]
        try:
            resolved = resolve_motion_capability(
                [observation for _, observation in indexed],
                extended_by_screen.get(screen_id, []),
            )
        except SettlementV2Error as error:
            raise ResolutionError(f"STOP: screen '{screen_id}': {error}") from error
        proof = resolved["resolution"]
        proof["layout_id"] = screen_id
        proofs[screen_id] = proof
        for (global_index, _), normalized in zip(
            indexed, resolved["observations"]
        ):
            resolved_by_index[global_index] = normalized
        screen_audit.append(
            {
                "layout_id": screen_id,
                "native_screen_id": proof["screen_id"],
                "observation_count": len(indexed),
                "resolved_animated_element_ids": proof[
                    "resolved_animated_element_ids"
                ],
                "disputed_element_ids": proof["disputed_element_ids"],
                "extended_observation_count": len(
                    proof["extended_observations"]
                ),
                "envelope_sample_count": proof["envelope_sample_count"],
            }
        )
    if len(resolved_by_index) != len(observations):
        raise ResolutionError("motion resolver did not reach every campaign observation")

    candidate_updates: dict[Path, dict[str, Any]] = {}
    for screen_id, record in fixtures.items():
        fixture = copy.deepcopy(record["value"])
        primary_normalized = resolved_by_index[record["primary_index"]]
        confirmation_normalized = resolved_by_index[record["confirmation_index"]]
        fixture["layout"] = primary_normalized["layout"]
        fixture["header"]["settlement"] = primary_normalized["settlement"]
        fixture["header"]["motion_capability"] = proofs[screen_id]
        confirmation_header = fixture["header"]["animation_confirmation"]
        confirmation_header.setdefault(
            "raw_confirmation_structural_sha256",
            confirmation_header.get("confirmation_structural_sha256"),
        )
        confirmation_header.setdefault(
            "raw_confirmation_animated_element_ids_sha256",
            confirmation_header.get("animated_element_ids_sha256"),
        )
        confirmation_header["confirmation_structural_sha256"] = (
            confirmation_normalized["settlement"]["structural_sha256"]
        )
        resolved_ids = proofs[screen_id]["resolved_animated_element_ids"]
        confirmation_header["animated_element_ids_sha256"] = hashlib.sha256(
            canonical_bytes(sorted(resolved_ids))
        ).hexdigest()
        confirmation_header["motion_capability_resolved"] = True
        candidate_updates[record["path"]] = fixture

    resolved_navigation = copy.deepcopy(primary_navigation)
    resolved_edges = {
        edge.get("id"): edge
        for edge in resolved_navigation.get("edges", [])
        if isinstance(edge, dict)
    }
    if len(resolved_edges) != len(resolved_navigation.get("edges", [])):
        raise ResolutionError("resolved navigation edge IDs are ambiguous")
    for index, (capture_label, edge_id, endpoint_key) in navigation_targets.items():
        if capture_label != "primary":
            continue
        endpoint = resolved_edges[edge_id][endpoint_key]
        normalized = resolved_by_index[index]
        endpoint["layout"] = normalized["layout"]
        endpoint["settlement"] = normalized["settlement"]
        endpoint["animated_element_ids"] = normalized["layout"][
            "animated_element_ids"
        ]
        endpoint["element_count"] = len(normalized["layout"]["elements"])
        layout_id = str(observations[index]["layout_id"])
        endpoint["motion_capability"] = proofs[layout_id]
    for edge in resolved_navigation["edges"]:
        edge["header"]["settlement"] = {
            "source": edge["before"]["settlement"],
            "destination": edge["after"]["settlement"],
        }
        edge["header"]["motion_capability"] = {
            "source": edge["before"]["motion_capability"],
            "destination": edge["after"]["motion_capability"],
        }
    resolved_navigation.setdefault("header", {})[
        "motion_capability_resolution"
    ] = {
                "settlement_spec": "2.4",
        "primary_raw_recording": evidence_receipt(
            primary_navigation_path, evidence_root
        ),
        "confirmation_raw_recording": evidence_receipt(
            confirmation_navigation_path, evidence_root
        ),
        "motion_observation_directory": (
            motion_observation_root.resolve()
            .relative_to(evidence_root.resolve())
            .as_posix()
        ),
        "screen_count": len(proofs),
    }

    audit = {
        "schema": "solomon-dark-native-menu-motion-capability-audit-v1",
            "settlement_spec": "2.4",
        "applied": apply,
        "standalone_fixture_count": len(fixtures),
        "raw_observation_count": len(observations),
        "extended_observation_count": len(extended),
        "screens": screen_audit,
        "outputs": {
            "resolved_navigation": str(resolved_navigation_output),
            "candidate_fixtures": [
                str(path) for path in sorted(candidate_updates)
            ],
        },
    }
    if apply:
        for path, value in candidate_updates.items():
            write_atomically(path, value)
        write_atomically(resolved_navigation_output, resolved_navigation)
        write_atomically(audit_output, audit)
    if verify:
        for path, expected in candidate_updates.items():
            if canonical_bytes(read_object(path)) != canonical_bytes(expected):
                raise ResolutionError(
                f"resolved candidate {path} is not the machine-derived v2.4 result"
                )
        if not resolved_navigation_output.is_file() or canonical_bytes(
            read_object(resolved_navigation_output)
        ) != canonical_bytes(resolved_navigation):
            raise ResolutionError(
            "resolved navigation is not the machine-derived v2.4 result"
            )
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--primary-navigation", type=Path, required=True)
    parser.add_argument("--confirmation-navigation", type=Path, required=True)
    parser.add_argument("--motion-observation-root", type=Path, required=True)
    parser.add_argument("--resolved-navigation-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = resolve_campaign(
            args.candidate_root.resolve(),
            args.evidence_root.resolve(),
            args.primary_navigation.resolve(),
            args.confirmation_navigation.resolve(),
            args.motion_observation_root.resolve(),
            args.resolved_navigation_output.resolve(),
            args.audit_output.resolve(),
            args.apply,
            args.verify,
        )
    except ResolutionError as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps({"success": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
