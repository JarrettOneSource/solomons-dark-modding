#!/usr/bin/env python3
"""Validate and promote one complete settled native-menu recapture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from native_menu_settlement_v2 import (
    SettlementV2Error,
    assert_overlay_hygiene,
    build_overlay_contamination_override,
    build_population_phase_override,
    canonical_bytes,
    classify_window,
    structural_layout_bytes,
    validate_declared_settlement,
    validate_overlay_reference,
)
from resolve_native_menu_motion_campaign import ResolutionError, resolve_campaign


class PromotionError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PromotionError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_unique_files(root: Path, pattern: str, expected: set[str]) -> dict[str, Path]:
    paths = list(root.glob(pattern))
    names = [path.name for path in paths]
    if len(names) != len(set(names)):
        raise PromotionError(f"ambiguous duplicate candidates under {root}: {names}")
    actual = set(names)
    if actual != expected:
        raise PromotionError(
            f"candidate census drifted under {root}: "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    return {path.name: path for path in paths}


def resolve_evidence_file(
    evidence_root: Path,
    fixture_path: Path,
    filename: str,
) -> Path:
    candidates = {
        candidate.resolve()
        for candidate in (
            fixture_path.parent / filename,
            *evidence_root.rglob(filename),
        )
        if candidate.is_file()
    }
    if len(candidates) != 1:
        raise PromotionError(
            f"raw evidence lookup for {filename!r} is ambiguous or absent: "
            f"{sorted(str(path) for path in candidates)}"
        )
    return candidates.pop()


def validate_raw_recording(
    evidence_root: Path,
    fixture_path: Path,
    header: dict[str, Any],
) -> Path:
    raw = header.get("raw_recording")
    if not isinstance(raw, dict):
        raise PromotionError(f"{fixture_path} has no raw_recording provenance")
    filename = raw.get("evidence_filename")
    if not isinstance(filename, str) or not filename:
        raise PromotionError(f"{fixture_path} has no raw evidence filename")
    evidence = resolve_evidence_file(evidence_root, fixture_path, filename)
    if evidence.stat().st_size != raw.get("bytes"):
        raise PromotionError(f"{fixture_path} raw evidence byte count is false")
    if file_sha256(evidence) != raw.get("sha256"):
        raise PromotionError(f"{fixture_path} raw evidence hash is false")
    return evidence


def animated_ids(layout: dict[str, Any]) -> list[str]:
    values = layout.get("animated_element_ids")
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise PromotionError("Settlement v2 layout has no measured animated id list")
    if len(values) != len(set(values)):
        raise PromotionError("Settlement v2 layout has ambiguous duplicate animated ids")
    return values


def structurally_matches(
    left: dict[str, Any],
    right: dict[str, Any],
    ids: list[str],
) -> bool:
    try:
        return structural_layout_bytes(left, ids) == structural_layout_bytes(
            right,
            ids,
        )
    except SettlementV2Error:
        return False


def validate_settlement_fixture(
    evidence_root: Path,
    fixture_path: Path,
    fixture: dict[str, Any],
    overlay_reference: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    if fixture.get("schema") != "solomon-dark-native-menu-layout-v2":
        raise PromotionError(f"{fixture_path} does not use the Settlement v2 schema")
    header = fixture.get("header")
    layout = fixture.get("layout")
    if not isinstance(header, dict) or not isinstance(layout, dict):
        raise PromotionError(f"{fixture_path} has no v2 header/layout")
    settlement = header.get("settlement")
    if not isinstance(settlement, dict):
        raise PromotionError(f"{fixture_path} has no Settlement v2 measurement")
    if settlement.get("settlement_spec") != "2.4":
        raise PromotionError(f"{fixture_path} does not identify Settlement v2.4")
    if settlement.get("structural_element_order") != (
        "draw_order_then_element_id"
    ):
        raise PromotionError(
            f"{fixture_path} makes raw element-list position structural"
        )
    ids = animated_ids(layout)
    if settlement.get("animated_element_ids") != ids:
        raise PromotionError(f"{fixture_path} settlement animated ids disagree with its layout")
    raw_ids = settlement.get("raw_window_animated_element_ids")
    if not isinstance(raw_ids, list) or not all(
        isinstance(value, str) for value in raw_ids
    ):
        raise PromotionError(
            f"{fixture_path} lost its raw per-window animation measurement"
        )
    motion_capability = header.get("motion_capability")
    if not isinstance(motion_capability, dict) or motion_capability.get(
        "resolved_animated_element_ids"
    ) != ids:
        raise PromotionError(
            f"{fixture_path} animated IDs are not bound to screen-level motion capability"
        )
    element_count = len(layout.get("elements", []))
    if element_count == 0:
        raise PromotionError(f"{fixture_path} reached no layout elements")
    if len(ids) / element_count > 0.30:
        raise PromotionError(f"{fixture_path} exceeds the 30 percent animated cap")
    structural_sha = hashlib.sha256(structural_layout_bytes(layout, ids)).hexdigest()
    if structural_sha != settlement.get("structural_sha256"):
        raise PromotionError(f"{fixture_path} records a false structural hash")
    if settlement.get("consecutive_structural_samples", 0) < 40:
        raise PromotionError(f"{fixture_path} lacks 40 structural samples")
    if settlement.get("animated_id_set_sample_count", 0) < 40:
        raise PromotionError(f"{fixture_path} lacks 40 identical animated-id-set samples")
    if settlement.get("stable_span_milliseconds", 0) < 2_000:
        raise PromotionError(f"{fixture_path} lacks a two-second structural window")

    raw_path = validate_raw_recording(evidence_root, fixture_path, header)
    raw_value = read_json(raw_path)
    if raw_value.get("schema") == "solomon-dark-native-menu-settlement-trace-v2":
        samples = raw_value.get("settled_window_samples")
        if not isinstance(samples, list):
            raise PromotionError(f"{fixture_path} trace has no settled sample window")
        try:
            raw_classification = classify_window(samples)
        except SettlementV2Error as error:
            raise PromotionError(f"{fixture_path}: {error}") from error
        if raw_classification["animated_element_ids"] != raw_ids:
            raise PromotionError(
                f"{fixture_path} records a false raw-window animated ID set"
            )

    confirmation = header.get("animation_confirmation")
    if not isinstance(confirmation, dict):
        raise PromotionError(f"{fixture_path} has no fresh-instance confirmation")
    confirmation_filename = confirmation.get("evidence_filename")
    if not isinstance(confirmation_filename, str) or not confirmation_filename:
        raise PromotionError(f"{fixture_path} confirmation has no evidence filename")
    confirmation_path = resolve_evidence_file(
        evidence_root,
        fixture_path,
        confirmation_filename,
    )
    if confirmation_path.stat().st_size != confirmation.get("bytes"):
        raise PromotionError(f"{fixture_path} confirmation byte count is false")
    if file_sha256(confirmation_path) != confirmation.get("sha256"):
        raise PromotionError(f"{fixture_path} confirmation hash is false")
    confirmation_value = read_json(confirmation_path)
    confirmation_layout = confirmation_value.get("confirmation_layout")
    if not isinstance(confirmation_layout, dict):
        raise PromotionError(f"{fixture_path} confirmation has no measured second layout")
    try:
        assert_overlay_hygiene(layout, overlay_reference)
        assert_overlay_hygiene(confirmation_layout, overlay_reference)
    except SettlementV2Error as error:
        raise PromotionError(f"{fixture_path}: {error}") from error
    raw_confirmation_structural_sha = hashlib.sha256(
        structural_layout_bytes(confirmation_layout)
    ).hexdigest()
    if (
        confirmation.get("raw_confirmation_structural_sha256")
        != raw_confirmation_structural_sha
    ):
        raise PromotionError(
            f"{fixture_path} confirmation records a false raw second-capture "
            "structural hash"
        )
    expected_ids_sha = hashlib.sha256(canonical_bytes(sorted(ids))).hexdigest()
    if confirmation.get("animated_element_ids_sha256") != expected_ids_sha:
        raise PromotionError(f"{fixture_path} confirmation animated-id hash is false")
    if confirmation.get("confirmation_structural_sha256") != structural_sha:
        raise PromotionError(
            f"{fixture_path} confirmation resolved structure disagrees with the primary"
        )
    if confirmation.get("instance") == header.get("instance"):
        raise PromotionError(f"{fixture_path} confirmation reused the primary instance")
    if confirmation.get("process_id") == header.get("process_id"):
        raise PromotionError(f"{fixture_path} confirmation reused the primary process")
    if confirmation.get("source") != header.get("source"):
        raise PromotionError(f"{fixture_path} confirmation used different provenance")
    return raw_path, confirmation_layout


def resolve_population_trace(
    evidence_root: Path,
    reference: dict[str, Any],
    expected_layout: dict[str, Any],
    expected_source: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    evidence_path = reference.get("evidence_path")
    if not isinstance(evidence_path, str) or not evidence_path:
        raise PromotionError(f"{label} has no exact population evidence path")
    root = evidence_root.resolve()
    path = (root / evidence_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise PromotionError(f"{label} population evidence escapes or is absent")
    if path.stat().st_size != reference.get("bytes"):
        raise PromotionError(f"{label} population evidence byte count is false")
    if file_sha256(path) != reference.get("sha256"):
        raise PromotionError(f"{label} population evidence hash is false")
    if reference.get("side") != "destination":
        raise PromotionError(f"{label} population proof is not a destination trace")
    navigation = read_json(path)
    if navigation.get("schema") != "solomon-dark-native-menu-navigation-v2":
        raise PromotionError(f"{label} population evidence is not navigation data")
    edge_id = reference.get("edge_id")
    matches = [
        edge for edge in navigation.get("edges", []) if edge.get("id") == edge_id
    ]
    if len(matches) != 1:
        raise PromotionError(
            f"{label} population edge {edge_id!r} is absent or ambiguous"
        )
    edge = matches[0]
    if edge.get("header", {}).get("source") != expected_source:
        raise PromotionError(f"{label} population evidence changed provenance")
    after = edge.get("after")
    if not isinstance(after, dict) or not isinstance(after.get("layout"), dict):
        raise PromotionError(f"{label} population edge has no destination layout")
    if structural_layout_bytes(after["layout"]) != structural_layout_bytes(
        expected_layout
    ):
        raise PromotionError(
            f"{label} population destination does not canonically match standalone"
        )
    trace = after.get("settlement_trace")
    if not isinstance(trace, dict):
        raise PromotionError(f"{label} population edge has no settlement trace")
    return trace


def validate_population_override(
    evidence_root: Path,
    fixture_path: Path,
    header: dict[str, Any],
    landed_layout: dict[str, Any],
    candidate_layout: dict[str, Any],
    confirmation_layout: dict[str, Any],
) -> dict[str, Any]:
    declared = header.get("landed_population_override")
    if not isinstance(declared, dict):
        raise PromotionError(
            f"STOP: standalone {fixture_path.name} differs from landed structure "
            "without a Settlement v2.1 population-phase override"
        )
    primary_reference = declared.get("primary_population_trace")
    confirmation_reference = declared.get("confirmation_population_trace")
    if not isinstance(primary_reference, dict) or not isinstance(
        confirmation_reference, dict
    ):
        raise PromotionError(
            f"{fixture_path} population override has no two trace references"
        )
    primary_trace = resolve_population_trace(
        evidence_root,
        primary_reference,
        candidate_layout,
        header["source"],
        f"{fixture_path}.primary",
    )
    confirmation_source = header["animation_confirmation"]["source"]
    confirmation_trace = resolve_population_trace(
        evidence_root,
        confirmation_reference,
        confirmation_layout,
        confirmation_source,
        f"{fixture_path}.confirmation",
    )
    try:
        expected = build_population_phase_override(
            landed_layout,
            candidate_layout,
            confirmation_layout,
            primary_trace,
            confirmation_trace,
        )
    except SettlementV2Error as error:
        raise PromotionError(f"{fixture_path}: {error}") from error
    reference_keys = {"evidence_path", "sha256", "bytes", "edge_id", "side"}
    expected["primary_population_trace"] = {
        **{
            key: primary_reference.get(key)
            for key in reference_keys
        },
        **expected["primary_population_trace"],
    }
    expected["confirmation_population_trace"] = {
        **{
            key: confirmation_reference.get(key)
            for key in reference_keys
        },
        **expected["confirmation_population_trace"],
    }
    if canonical_bytes(declared) != canonical_bytes(expected):
        raise PromotionError(
            f"{fixture_path} records a landed override that was not derived "
            "exactly from both population traces"
        )
    return expected


def resolve_overlay_reference(
    repo_root: Path,
    evidence_root: Path,
) -> tuple[Path, dict[str, Any]]:
    path = repo_root / "tests/fixtures/webgame/menu-overlay-reference.json"
    if not path.is_file():
        raise PromotionError("committed native-menu overlay reference is missing")
    reference = read_json(path)
    try:
        validate_overlay_reference(reference)
    except SettlementV2Error as error:
        raise PromotionError(f"{path}: {error}") from error
    root = evidence_root.resolve()
    for label in ("overlay_capture", "clean_capture"):
        receipt = reference["header"][label]
        evidence_path = (root / receipt["evidence_path"]).resolve()
        if not evidence_path.is_relative_to(root) or not evidence_path.is_file():
            raise PromotionError(f"overlay reference {label} evidence is absent")
        if evidence_path.stat().st_size != receipt["bytes"]:
            raise PromotionError(
                f"overlay reference {label} evidence byte count is false"
            )
        if file_sha256(evidence_path) != receipt["sha256"]:
            raise PromotionError(
                f"overlay reference {label} evidence hash is false"
            )
    return path, reference


def validate_overlay_override(
    evidence_root: Path,
    fixture_path: Path,
    header: dict[str, Any],
    landed_layout: dict[str, Any],
    candidate_layout: dict[str, Any],
    confirmation_layout: dict[str, Any],
    overlay_reference_path: Path,
    overlay_reference: dict[str, Any],
) -> dict[str, Any]:
    declared = header.get("landed_overlay_override")
    if not isinstance(declared, dict):
        raise PromotionError(
            f"STOP: standalone {fixture_path.name} differs from landed structure "
            "without a Settlement v2.4 overlay-contamination override"
        )
    reference_receipt = declared.get("overlay_reference")
    if not isinstance(reference_receipt, dict):
        raise PromotionError(f"{fixture_path} overlay override has no reference")
    expected_reference_receipt = {
        "fixture": "tests/fixtures/webgame/menu-overlay-reference.json",
        "sha256": file_sha256(overlay_reference_path),
        "bytes": overlay_reference_path.stat().st_size,
        "overlay_capture": overlay_reference["header"]["overlay_capture"],
        "clean_capture": overlay_reference["header"]["clean_capture"],
    }
    if canonical_bytes(reference_receipt) != canonical_bytes(
        expected_reference_receipt
    ):
        raise PromotionError(
            f"{fixture_path} overlay reference receipt is not machine-derived"
        )
    primary_reference = declared.get("primary_population_trace")
    confirmation_reference = declared.get("confirmation_population_trace")
    if not isinstance(primary_reference, dict) or not isinstance(
        confirmation_reference, dict
    ):
        raise PromotionError(
            f"{fixture_path} overlay override has no two trace references"
        )
    primary_trace = resolve_population_trace(
        evidence_root,
        primary_reference,
        candidate_layout,
        header["source"],
        f"{fixture_path}.primary",
    )
    confirmation_source = header["animation_confirmation"]["source"]
    confirmation_trace = resolve_population_trace(
        evidence_root,
        confirmation_reference,
        confirmation_layout,
        confirmation_source,
        f"{fixture_path}.confirmation",
    )
    try:
        expected = build_overlay_contamination_override(
            landed_layout,
            candidate_layout,
            confirmation_layout,
            primary_trace,
            confirmation_trace,
            overlay_reference,
        )
    except SettlementV2Error as error:
        raise PromotionError(f"{fixture_path}: {error}") from error
    reference_keys = {"evidence_path", "sha256", "bytes", "edge_id", "side"}
    expected["primary_population_trace"] = {
        **{key: primary_reference.get(key) for key in reference_keys},
        **expected["primary_population_trace"],
    }
    expected["confirmation_population_trace"] = {
        **{key: confirmation_reference.get(key) for key in reference_keys},
        **expected["confirmation_population_trace"],
    }
    expected["overlay_reference"] = expected_reference_receipt
    if canonical_bytes(declared) != canonical_bytes(expected):
        raise PromotionError(
            f"{fixture_path} records an overlay override that was not "
            "derived exactly from the reference and both fresh traces"
        )
    return expected


def endpoint_source_signature(endpoint: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "semantic_surface",
        "semantic_generation",
        "tagged_screen",
        "layout_generation",
        "element_count",
        "capture_method",
    )
    return {field: endpoint.get(field) for field in fields}


def animated_geometry_report(
    candidate_layout: dict[str, Any],
    landed_layout: dict[str, Any],
) -> list[dict[str, Any]]:
    landed_by_id = {
        element["id"]: element for element in landed_layout.get("elements", [])
    }
    report: list[dict[str, Any]] = []
    for element in candidate_layout.get("elements", []):
        if not element.get("animated_geometry"):
            continue
        element_id = element["id"]
        landed = landed_by_id.get(element_id)
        if not isinstance(landed, dict):
            raise PromotionError(
                f"STOP: animated element {element_id} was absent from the landed layout"
            )
        report.append(
            {
                "element_id": element_id,
                "landed_frozen_rect": landed.get("rect"),
                "landed_frozen_unclipped_rect": landed.get("unclipped_rect"),
                "anchor_rect": element.get("anchor_rect"),
                "anchor_unclipped_rect": element.get("anchor_unclipped_rect"),
                "envelope": element.get("envelope"),
            }
        )
    return report


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".menufix.tmp")
    if source.suffix.lower() == ".json":
        data = source.read_bytes()
        if b"\r" in data.replace(b"\r\n", b""):
            raise PromotionError(
                f"refusing ambiguous lone carriage return in {source}"
            )
        temporary.write_bytes(data.replace(b"\r\n", b"\n"))
    else:
        shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def validate_and_promote(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    navigation_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    landed_root = repo_root / "tests/fixtures/webgame"
    resolved_navigation = read_json(navigation_path)
    resolution_header = resolved_navigation.get("header", {}).get(
        "motion_capability_resolution"
    )
    if not isinstance(resolution_header, dict) or resolution_header.get(
        "settlement_spec"
    ) != "2.4":
        raise PromotionError(
            "candidate navigation has no machine-derived Settlement v2.4 resolution"
        )

    def resolution_evidence_path(field: str) -> Path:
        receipt = resolution_header.get(field)
        if not isinstance(receipt, dict):
            raise PromotionError(f"motion resolution lost {field}")
        relative = receipt.get("evidence_path")
        if not isinstance(relative, str) or not relative:
            raise PromotionError(f"motion resolution {field} has no evidence path")
        root = evidence_root.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise PromotionError(f"motion resolution {field} evidence is absent")
        if path.stat().st_size != receipt.get("bytes") or file_sha256(path) != receipt.get(
            "sha256"
        ):
            raise PromotionError(f"motion resolution {field} receipt is false")
        return path

    raw_primary_navigation = resolution_evidence_path("primary_raw_recording")
    raw_confirmation_navigation = resolution_evidence_path(
        "confirmation_raw_recording"
    )
    motion_directory = resolution_header.get("motion_observation_directory")
    if not isinstance(motion_directory, str) or not motion_directory:
        raise PromotionError("motion resolution lost its observation directory")
    motion_root = (evidence_root.resolve() / motion_directory).resolve()
    if not motion_root.is_relative_to(evidence_root.resolve()):
        raise PromotionError("motion observation directory escapes the evidence root")
    try:
        resolve_campaign(
            candidate_root,
            evidence_root,
            raw_primary_navigation,
            raw_confirmation_navigation,
            motion_root,
            navigation_path,
            evidence_root / "motion-resolution-verification-unused.json",
            False,
            True,
        )
    except (ResolutionError, SettlementV2Error) as error:
        raise PromotionError(
            f"candidate Settlement v2.4 resolution did not re-derive: {error}"
        ) from error
    overlay_reference_path, overlay_reference = resolve_overlay_reference(
        repo_root,
        evidence_root,
    )
    landed_golden = read_json(landed_root / "menu-goldens.json")
    candidate_golden_path = candidate_root / "menu-goldens.json"
    candidate_golden = read_json(candidate_golden_path)
    if candidate_golden.get("schema") != "solomon-dark-menu-goldens-v2":
        raise PromotionError("candidate aggregate does not use Settlement v2")

    layout_names = {
        Path(entry["fixture"]).name for entry in landed_golden["layouts"]
    }
    candidate_layouts = require_unique_files(
        candidate_root / "menu-layouts",
        "*.json",
        layout_names,
    )
    candidate_transition_layouts = require_unique_files(
        candidate_root / "menu-transition-layouts",
        "*.json",
        {"hub.json"},
    )
    reference_names = {
        Path(entry["reference_capture"]).name
        for entry in candidate_golden["layouts"]
    } | {
        Path(entry["reference_capture"]).name
        for entry in candidate_golden["transition_endpoint_layouts"]
    }
    candidate_references = require_unique_files(
        candidate_root / "menu-reference-captures",
        "*.png",
        reference_names,
    )

    landed_by_name = {
        Path(entry["fixture"]).name: entry
        for entry in landed_golden["layouts"]
    }
    standalone_results: list[dict[str, Any]] = []
    override_by_layout: dict[str, dict[str, Any]] = {}
    for name in sorted(layout_names):
        candidate_fixture = read_json(candidate_layouts[name])
        landed_entry = landed_by_name[name]
        _, confirmation_layout = validate_settlement_fixture(
            evidence_root,
            candidate_layouts[name],
            candidate_fixture,
            overlay_reference,
        )
        candidate_layout = candidate_fixture["layout"]
        candidate_ids = animated_ids(candidate_layout)
        structural_bit_match = structurally_matches(
            candidate_layout,
            landed_entry["layout"],
            candidate_ids,
        )
        override = None
        override_kind = None
        declared_override_fields = {
            field
            for field in (
                "landed_population_override",
                "landed_overlay_override",
            )
            if field in candidate_fixture["header"]
        }
        if structural_bit_match:
            if declared_override_fields:
                raise PromotionError(
                    f"{name} declares {sorted(declared_override_fields)} despite "
                    "matching landed structure"
                )
        else:
            if len(declared_override_fields) != 1:
                raise PromotionError(
                    f"STOP: {name} has {len(declared_override_fields)} landed "
                    "override paths; exactly one must be machine-derived"
                )
            override_kind = next(iter(declared_override_fields))
            if override_kind == "landed_population_override":
                override = validate_population_override(
                    evidence_root,
                    candidate_layouts[name],
                    candidate_fixture["header"],
                    landed_entry["layout"],
                    candidate_layout,
                    confirmation_layout,
                )
            else:
                override = validate_overlay_override(
                    evidence_root,
                    candidate_layouts[name],
                    candidate_fixture["header"],
                    landed_entry["layout"],
                    candidate_layout,
                    confirmation_layout,
                    overlay_reference_path,
                    overlay_reference,
                )
            override_by_layout[name] = {
                "kind": override_kind,
                "proof": override,
            }
        standalone_results.append(
            {
                "layout": name,
                "structural_bit_match": structural_bit_match,
                "landed_override_kind": override_kind,
                "landed_override": override,
                "animated_element_ids": candidate_ids,
                "animated_geometry": animated_geometry_report(
                    candidate_layout,
                    landed_entry["layout"],
                ),
                "settle_latency_milliseconds": candidate_fixture["header"][
                    "settlement"
                ]["settle_latency_milliseconds"],
            }
        )

    hub_fixture = read_json(candidate_transition_layouts["hub.json"])
    validate_settlement_fixture(
        evidence_root,
        candidate_transition_layouts["hub.json"],
        hub_fixture,
        overlay_reference,
    )

    raw = candidate_golden["header"]["raw_recording"]
    if raw["bytes"] != navigation_path.stat().st_size:
        raise PromotionError("candidate golden records a false navigation byte count")
    if raw["sha256"] != file_sha256(navigation_path):
        raise PromotionError("candidate golden records a false navigation hash")

    old_edges = {
        edge["id"]: edge
        for edge in landed_golden["navigation_graph"]["edges"]
    }
    candidate_edges = candidate_golden["navigation_graph"]["edges"]
    candidate_ids = [edge["id"] for edge in candidate_edges]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise PromotionError("candidate golden contains ambiguous duplicate edge IDs")
    if set(candidate_ids) != set(old_edges):
        raise PromotionError(
            "candidate edge census differs from the landed navigation graph"
        )
    candidate_standalones = {
        entry["fixture"]: entry
        for entry in (
            *candidate_golden["layouts"],
            *candidate_golden["transition_endpoint_layouts"],
        )
    }
    candidate_layout_by_name = {
        Path(entry["fixture"]).name: entry["layout"]
        for entry in candidate_golden["layouts"]
    }
    destination_changes: list[dict[str, Any]] = []
    source_overrides: list[dict[str, Any]] = []
    for edge in candidate_edges:
        edge_id = edge["id"]
        landed = old_edges[edge_id]
        before_layout = edge["before"].get("layout")
        if not isinstance(before_layout, dict):
            raise PromotionError(f"STOP: transition source {edge_id} has no v2 layout")
        try:
            assert_overlay_hygiene(before_layout, overlay_reference)
        except SettlementV2Error as error:
            raise PromotionError(f"{edge_id} source: {error}") from error
        before_ids = animated_ids(before_layout)
        source_signature_match = endpoint_source_signature(
            edge["before"]
        ) == endpoint_source_signature(landed["before"])
        source_structural_match = structurally_matches(
            before_layout,
            landed["before"]["layout"],
            before_ids,
        )
        source_frame_match = (
            bool(before_ids)
            or edge["before"].get("frame_sha256")
            == landed["before"].get("frame_sha256")
        )
        source_bit_match = (
            source_signature_match
            and source_structural_match
            and source_frame_match
        )
        if not source_bit_match:
            override_matches = [
                name
                for name in override_by_layout
                if set(before_ids)
                == set(animated_ids(candidate_layout_by_name[name]))
                and structurally_matches(
                    before_layout,
                    candidate_layout_by_name[name],
                    before_ids,
                )
            ]
            if len(override_matches) != 1:
                raise PromotionError(
                    f"STOP: transition source {edge_id} does not bit-match its "
                    "landed endpoint and has no unique approved standalone "
                    f"override: {override_matches}"
                )
            source_overrides.append(
                {
                    "edge": edge_id,
                    "standalone": override_matches[0],
                    "old": {
                        **endpoint_source_signature(landed["before"]),
                        "frame_sha256": landed["before"].get("frame_sha256"),
                    },
                    "new": {
                        **endpoint_source_signature(edge["before"]),
                        "frame_sha256": edge["before"].get("frame_sha256"),
                    },
                    "signature_bit_match": source_signature_match,
                    "structural_bit_match": source_structural_match,
                    "frame_bit_match_or_animated": source_frame_match,
                }
            )
        fixture_name = edge.get("destination_layout_fixture")
        if fixture_name not in candidate_standalones:
            raise PromotionError(
                f"STOP: transition destination {edge_id} has no unique standalone"
            )
        destination_layout = edge["after"]["layout"]
        try:
            assert_overlay_hygiene(destination_layout, overlay_reference)
        except SettlementV2Error as error:
            raise PromotionError(f"{edge_id} destination: {error}") from error
        standalone_layout = candidate_standalones[fixture_name]["layout"]
        destination_ids = animated_ids(destination_layout)
        standalone_ids = animated_ids(standalone_layout)
        if set(destination_ids) != set(standalone_ids):
            raise PromotionError(
                f"STOP: transition destination {edge_id} animated IDs "
                f"{destination_ids} do not equal {fixture_name} IDs {standalone_ids}"
            )
        if not structurally_matches(
            destination_layout,
            standalone_layout,
            destination_ids,
        ):
            raise PromotionError(
                f"STOP: transition destination {edge_id} does not structurally "
                f"byte-match {fixture_name}"
            )
        old_after = endpoint_source_signature(landed["after"])
        new_after = endpoint_source_signature(edge["after"])
        if (
            old_after != new_after
            or landed["after"].get("frame_sha256")
            != edge["after"].get("frame_sha256")
        ):
            destination_changes.append(
                {
                    "edge": edge_id,
                    "old": {
                        **old_after,
                        "frame_sha256": landed["after"].get("frame_sha256"),
                    },
                    "new": {
                        **new_after,
                        "frame_sha256": edge["after"].get("frame_sha256"),
                        "animated_element_ids": destination_ids,
                    },
                    "settle_latency_milliseconds": edge["after"]["settlement"][
                        "settle_latency_milliseconds"
                    ],
                    "standalone_fixture": fixture_name,
                }
            )

    embedded = {
        Path(entry["fixture"]).name: entry for entry in candidate_golden["layouts"]
    }
    for name, path in candidate_layouts.items():
        fixture = read_json(path)
        if fixture != {
            "schema": fixture["schema"],
            "header": embedded[name]["header"],
            "layout": embedded[name]["layout"],
        }:
            raise PromotionError(
                f"candidate embedded golden and standalone {name} disagree"
            )
    embedded_transition = {
        Path(entry["fixture"]).name: entry
        for entry in candidate_golden["transition_endpoint_layouts"]
    }
    for name, path in candidate_transition_layouts.items():
        fixture = read_json(path)
        if fixture != {
            "schema": fixture["schema"],
            "header": embedded_transition[name]["header"],
            "layout": embedded_transition[name]["layout"],
        }:
            raise PromotionError(
                f"candidate embedded golden and transition standalone {name} disagree"
            )

    promotion_pairs: list[tuple[Path, Path]] = []
    for name, source in candidate_layouts.items():
        promotion_pairs.append((source, landed_root / "menu-layouts" / name))
    for name, source in candidate_transition_layouts.items():
        promotion_pairs.append(
            (source, landed_root / "menu-transition-layouts" / name)
        )
    for name, source in candidate_references.items():
        promotion_pairs.append(
            (source, landed_root / "menu-reference-captures" / name)
        )
    promotion_pairs.append((candidate_golden_path, landed_root / "menu-goldens.json"))

    if not dry_run:
        for source, destination in promotion_pairs:
            atomic_copy(source, destination)

    return {
        "success": True,
        "dry_run": dry_run,
        "standalones": standalone_results,
        "landed_overlay_correction_count": sum(
            result["landed_override_kind"] == "landed_overlay_override"
            for result in standalone_results
        ),
        "landed_overlay_corrected_screens": [
            result["layout"]
            for result in standalone_results
            if result["landed_override_kind"] == "landed_overlay_override"
        ],
        "hub_settle_latency_milliseconds": hub_fixture["header"]["settlement"][
            "settle_latency_milliseconds"
        ],
        "transition_sources_structurally_bit_match_landed": (
            len(candidate_edges) - len(source_overrides)
        ),
        "transition_sources_structurally_match_accepted_truth": len(
            candidate_edges
        ),
        "transition_source_overrides": source_overrides,
        "transition_destinations_structurally_match_standalones": len(candidate_edges),
        "destination_changes": destination_changes,
        "promoted_files": [str(destination) for _, destination in promotion_pairs],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate_and_promote(
            args.repo_root.resolve(),
            args.candidate_root.resolve(),
            args.evidence_root.resolve(),
            args.navigation_recording.resolve(),
            args.dry_run,
        )
    except PromotionError as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
