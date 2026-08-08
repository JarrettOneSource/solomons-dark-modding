#!/usr/bin/env python3
"""Validate and promote one complete settled native-menu recapture."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
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
from native_menu_ambient_lifecycle import (
    reproduce_standalone_structural_core,
    sha256_json as ambient_sha256_json,
)
from native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    _population_evidence,
    diagnose_landed_layout,
    diagnosis_prereference_residual,
    semantic_overlay_corroboration,
)
from native_menu_overlay_v25 import (
    OverlayV25Error,
    assert_overlay_hygiene as assert_overlay_hygiene_v25,
    derive_overlay_reference,
)
from native_menu_profile_state import (
    NativeMenuProfileStateError,
    load_profile_state_baseline,
    validate_capture_profile_state,
)
from native_menu_browser_tab import (
    NativeMenuBrowserTabError,
    resolve_browser_tab,
    validate_browser_tab,
)
from build_menu_baseline_interregnum import BaselineBuildError, build as build_menu_baseline


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


def file_receipt(path: Path) -> dict[str, Any]:
    return {"sha256": file_sha256(path), "bytes": path.stat().st_size}


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
    if Path(filename).name != filename:
        raise PromotionError(
            f"raw evidence filename must not contain a path: {filename!r}"
        )
    adjacent = fixture_path if fixture_path.is_dir() else fixture_path.parent
    candidate_root = (
        adjacent.parent
        if adjacent.name in {"menu-layouts", "menu-transition-layouts"}
        else adjacent
    )
    conventional_candidates = {
        path.resolve()
        for path in (
            adjacent / filename,
            candidate_root / filename,
            candidate_root / "menu-settlement-traces" / filename,
            candidate_root / "menu-animation-confirmations" / filename,
            candidate_root / "menu-reference-captures" / filename,
        )
        if path.is_file()
    }
    if len(conventional_candidates) == 1:
        return conventional_candidates.pop()
    if len(conventional_candidates) > 1:
        raise PromotionError(
            f"raw evidence lookup for {filename!r} is ambiguous inside its "
            f"candidate root: {sorted(str(path) for path in conventional_candidates)}"
        )
    candidates = {
        candidate.resolve()
        for candidate in evidence_root.rglob(filename)
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


def validate_and_promote_v24_legacy(
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


def _receipt_path_v25(
    evidence_root: Path,
    adjacent: Path,
    receipt: dict[str, Any],
    label: str,
) -> Path:
    relative = receipt.get("evidence_path")
    if isinstance(relative, str) and relative:
        root = evidence_root.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise PromotionError(f"{label} evidence escapes or is absent")
    else:
        filename = receipt.get("evidence_filename")
        if not isinstance(filename, str) or not filename:
            raise PromotionError(f"{label} has no evidence path or filename")
        path = resolve_evidence_file(evidence_root, adjacent, filename)
    if path.stat().st_size != receipt.get("bytes"):
        raise PromotionError(f"{label} records a false evidence byte count")
    if file_sha256(path) != receipt.get("sha256"):
        raise PromotionError(f"{label} records a false evidence SHA-256")
    return path


def _validate_source_v25(repo_root: Path, source: Any, label: str) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise PromotionError(f"{label} has no machine-derived provenance")
    required = {
        "base_commit_sha": 40,
        "source_tree_sha": 40,
        "game_executable_sha256": 64,
        "loader_dll_sha256": 64,
        "profile_state_identity_sha256": 64,
    }
    for field, length in required.items():
        value = source.get(field)
        if (
            not isinstance(value, str)
            or len(value) != length
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise PromotionError(
                f"{label} has invalid machine-derived provenance field '{field}'"
            )
    try:
        committed_tree = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-parse",
                f"{source['base_commit_sha']}^{{tree}}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as error:
        raise PromotionError(
            f"{label} base commit is not an object in the promotion repository"
        ) from error
    if committed_tree != source["source_tree_sha"]:
        raise PromotionError(
            f"{label} source tree does not belong to its machine-derived base commit"
        )
    return source


def _validate_profile_state_v25(
    repo_root: Path,
    evidence_root: Path,
    header: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    try:
        return validate_capture_profile_state(
            repo_root=repo_root,
            header=header,
            label=label,
            evidence_root=evidence_root,
        )
    except NativeMenuProfileStateError as error:
        raise PromotionError(str(error)) from error


def _validate_browser_tab_v25(
    screen_tag: str,
    layout: dict[str, Any],
    receipt: object,
    label: str,
) -> None:
    try:
        validate_browser_tab(
            screen_tag=screen_tag,
            layout=layout,
            receipt=receipt,
            label=label,
        )
    except NativeMenuBrowserTabError as error:
        raise PromotionError(str(error)) from error


def _structural_core_v25(layout: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "generation",
        "screen_id",
        "screen_title",
        "capture_method",
        "draw_order_semantics",
        "elements",
    )
    if any(field not in layout for field in fields):
        raise PromotionError("Settlement v2.9 layout has an incomplete structural core")
    return {field: copy.deepcopy(layout[field]) for field in fields}


def _validate_navigation_profile_state_v25(
    repo_root: Path,
    evidence_root: Path,
    recording: dict[str, Any],
    label: str,
) -> None:
    edges = recording.get("edges")
    if not isinstance(edges, list) or not edges:
        raise PromotionError(
            f"{label} profile-state sweep reached no navigation edges"
        )
    reached_ids: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict) or not isinstance(edge.get("id"), str):
            raise PromotionError(
                f"{label} profile-state sweep reached an unresolvable edge"
            )
        edge_id = edge["id"]
        if edge_id in reached_ids:
            raise PromotionError(
                f"{label} profile-state sweep found ambiguous edge '{edge_id}'"
            )
        reached_ids.add(edge_id)
        header = edge.get("header")
        if not isinstance(header, dict):
            raise PromotionError(
                f"{label} edge '{edge_id}' has no capture header"
            )
        _validate_profile_state_v25(
            repo_root,
            evidence_root,
            header,
            f"{label} edge {edge_id}",
        )
        header_tab_receipts = header.get("browser_tab_verification")
        for endpoint_key, side in (("before", "source"), ("after", "destination")):
            endpoint = edge.get(endpoint_key)
            if not isinstance(endpoint, dict):
                raise PromotionError(
                    f"{label} edge '{edge_id}' {side} endpoint is absent"
                )
            endpoint_layout = endpoint.get("layout")
            if not isinstance(endpoint_layout, dict) or not isinstance(
                endpoint_layout.get("screen_id"), str
            ):
                raise PromotionError(
                    f"{label} edge '{edge_id}' {side} has no screen layout"
                )
            header_tab_receipt = (
                header_tab_receipts.get(side)
                if isinstance(header_tab_receipts, dict)
                else None
            )
            if endpoint.get("browser_tab_verification") != header_tab_receipt:
                raise PromotionError(
                    f"{label} edge '{edge_id}' {side} browser-tab receipts disagree"
                )
            _validate_browser_tab_v25(
                endpoint_layout["screen_id"],
                endpoint_layout,
                endpoint.get("browser_tab_verification"),
                f"{label} edge {edge_id} {side}",
            )
    if "main_to_dark_cloud" not in reached_ids:
        raise PromotionError(
            f"{label} profile-state sweep did not reach the Dark Cloud entry edge"
        )


def _settled_samples_v25(trace: dict[str, Any], label: str) -> list[dict[str, Any]]:
    samples = trace.get("settled_window_samples")
    if (
        not isinstance(samples, list)
        or len(samples) < 40
        or not all(isinstance(sample, dict) for sample in samples)
    ):
        raise PromotionError(f"{label} has no 40-sample settled window")
    return samples


def validate_settlement_fixture_v25(
    repo_root: Path,
    evidence_root: Path,
    fixture_path: Path,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    if fixture.get("schema") != "solomon-dark-native-menu-layout-v3":
        raise PromotionError(f"{fixture_path} does not use Settlement v2.9 schema v3")
    header = fixture.get("header")
    layout = fixture.get("layout")
    if not isinstance(header, dict) or not isinstance(layout, dict):
        raise PromotionError(f"{fixture_path} has no v2.9 header/layout")
    if header.get("recorded_live") is not True:
        raise PromotionError(f"{fixture_path} is not marked as a live recording")
    source = _validate_source_v25(repo_root, header.get("source"), str(fixture_path))
    profile_state = _validate_profile_state_v25(
        repo_root, evidence_root, header, str(fixture_path)
    )
    settlement = header.get("settlement")
    if not isinstance(settlement, dict) or settlement.get("settlement_spec") != "2.9":
        raise PromotionError(f"{fixture_path} does not identify Settlement v2.9")
    if settlement.get("consecutive_structural_samples", 0) < 40:
        raise PromotionError(f"{fixture_path} lacks 40 consecutive structural samples")
    if settlement.get("stable_span_milliseconds", 0) < 2_000:
        raise PromotionError(f"{fixture_path} lacks a two-second structural window")
    if settlement.get("settle_latency_milliseconds", 0) < 2_000:
        raise PromotionError(f"{fixture_path} records an impossible settle latency")
    if layout.get("settlement_spec") != "2.9":
        raise PromotionError(f"{fixture_path} layout lost its v2.9 classification")
    core = _structural_core_v25(layout)
    core_sha256 = ambient_sha256_json(core)
    if layout.get("structural_core_sha256") != core_sha256:
        raise PromotionError(f"{fixture_path} layout records a false structural-core hash")
    if settlement.get("resolved_structural_core_sha256") != core_sha256:
        raise PromotionError(f"{fixture_path} header records a false structural-core hash")
    elements = core["elements"]
    if (
        not isinstance(elements, list)
        or not elements
        or layout.get("structural_core_element_count") != len(elements)
    ):
        raise PromotionError(f"{fixture_path} structural-core census is false")
    classification = layout.get("classification_map")
    ambient_members = layout.get("ambient_members")
    choice_slots = layout.get("choice_slots")
    choice_slot_ids = layout.get("choice_slot_ids")
    if (
        not isinstance(classification, dict)
        or not isinstance(ambient_members, list)
        or not isinstance(choice_slots, list)
        or not isinstance(choice_slot_ids, list)
    ):
        raise PromotionError(f"{fixture_path} lost its v2.9 classification maps")
    member_ids = [member.get("id") for member in ambient_members if isinstance(member, dict)]
    if len(member_ids) != len(ambient_members) or len(member_ids) != len(set(member_ids)):
        raise PromotionError(f"{fixture_path} ambient member identities are absent or ambiguous")
    declared_choice_ids = [
        slot.get("id") for slot in choice_slots if isinstance(slot, dict)
    ]
    if (
        len(declared_choice_ids) != len(choice_slots)
        or len(declared_choice_ids) != len(set(declared_choice_ids))
        or declared_choice_ids != choice_slot_ids
    ):
        raise PromotionError(
            f"{fixture_path} choice-slot identities are absent or ambiguous"
        )
    if set(classification) != set(member_ids) | set(choice_slot_ids):
        raise PromotionError(
            f"{fixture_path} member maps and classification map disagree"
        )
    allowed_classes = {
        "animated",
        "animated_family",
        "visibility_cycling",
        "ephemeral",
        "ambient_persistent",
        "choice_slot",
    }
    for member_id, classes in classification.items():
        if (
            not isinstance(classes, list)
            or not classes
            or not all(isinstance(value, str) for value in classes)
            or not set(classes) <= allowed_classes
        ):
            raise PromotionError(
                f"{fixture_path} ambient member '{member_id}' has an unauthorized class"
            )
        if member_id in choice_slot_ids and classes != ["choice_slot"]:
            raise PromotionError(
                f"{fixture_path} choice slot '{member_id}' has an unauthorized class"
            )
        if member_id in member_ids and "choice_slot" in classes:
            raise PromotionError(
                f"{fixture_path} ambient member '{member_id}' was mislabeled as a choice slot"
            )
    ambient_count = layout.get("ambient_semantic_member_count")
    peak_count = layout.get("peak_element_count")
    if (
        isinstance(ambient_count, bool)
        or not isinstance(ambient_count, int)
        or ambient_count != len(ambient_members)
        or isinstance(peak_count, bool)
        or not isinstance(peak_count, int)
        or peak_count <= 0
    ):
        raise PromotionError(f"{fixture_path} ambient/peak census is false")
    expected_fraction = ambient_count / peak_count
    if layout.get("ambient_fraction") != expected_fraction or expected_fraction > 0.40:
        raise PromotionError(f"{fixture_path} violates the 40 percent ambient cap")
    if settlement.get("ambient_fraction") != expected_fraction:
        raise PromotionError(f"{fixture_path} header records a false ambient fraction")
    lifecycle = header.get("ambient_lifecycle")
    if (
        not isinstance(lifecycle, dict)
        or not isinstance(lifecycle.get("resolution_sha256"), str)
        or len(lifecycle["resolution_sha256"]) != 64
        or not isinstance(lifecycle.get("observation_receipts"), list)
        or len(lifecycle["observation_receipts"]) < 2
        or not isinstance(lifecycle.get("independent_instances"), list)
        or len(lifecycle["independent_instances"]) < 2
    ):
        raise PromotionError(f"{fixture_path} has no two-instance v2.9 resolution receipt")

    if choice_slots:
        choice_header = header.get("choice_slots")
        if (
            not isinstance(choice_header, dict)
            or choice_header.get("settlement_spec") != "2.9"
            or choice_header.get("promotion")
            != "reused_stopped_settled_windows_rederived_under_v2.8"
            or choice_header.get("choice_slot_ids") != choice_slot_ids
        ):
            raise PromotionError(
                f"{fixture_path} choice slots lack their v2.9 promotion provenance"
            )
        _receipt_path_v25(
            evidence_root,
            fixture_path.parent,
            choice_header.get("asset_manifest", {}),
            f"{fixture_path} choice-slot asset manifest",
        )
        diagnostic_receipts = choice_header.get("diagnostic_receipts")
        expected_diagnostics = {
            "choice_core_stop_audit",
            "choice_core_resolver_transcript",
            "choice_core_stop_manifest",
        }
        if (
            not isinstance(diagnostic_receipts, dict)
            or set(diagnostic_receipts) != expected_diagnostics
        ):
            raise PromotionError(
                f"{fixture_path} choice-slot diagnostic receipt census is incomplete"
            )
        for label in sorted(expected_diagnostics):
            _receipt_path_v25(
                evidence_root,
                fixture_path.parent,
                diagnostic_receipts[label],
                f"{fixture_path} {label}",
            )
    elif "choice_slots" in header:
        raise PromotionError(
            f"{fixture_path} carries choice-slot provenance without resolved slots"
        )

    raw_receipt = header.get("settlement_trace", header.get("raw_recording"))
    if not isinstance(raw_receipt, dict):
        raise PromotionError(f"{fixture_path} has no raw settlement receipt")
    raw_path = _receipt_path_v25(
        evidence_root,
        fixture_path.parent,
        raw_receipt,
        f"{fixture_path} primary trace",
    )
    raw_trace = read_json(raw_path)
    raw_header = raw_trace.get("header")
    if not isinstance(raw_header, dict):
        raise PromotionError(f"{fixture_path} primary trace has no capture header")
    _validate_profile_state_v25(
        repo_root,
        evidence_root,
        raw_header,
        f"{fixture_path} primary trace",
    )
    primary_samples = _settled_samples_v25(raw_trace, f"{fixture_path} primary trace")
    primary_payload = primary_samples[0].get("payload")
    if not isinstance(primary_payload, dict) or not isinstance(
        primary_payload.get("screen_id"), str
    ):
        raise PromotionError(f"{fixture_path} primary trace has no screen payload")
    primary_screen_tag = primary_payload["screen_id"]
    _validate_browser_tab_v25(
        primary_screen_tag,
        primary_payload,
        header.get("browser_tab_verification"),
        str(fixture_path),
    )
    _validate_browser_tab_v25(
        primary_screen_tag,
        primary_payload,
        raw_header.get("browser_tab_verification"),
        f"{fixture_path} primary trace",
    )

    confirmation_receipt = header.get("animation_confirmation")
    if not isinstance(confirmation_receipt, dict):
        raise PromotionError(f"{fixture_path} has no fresh-instance confirmation receipt")
    confirmation_path = _receipt_path_v25(
        evidence_root,
        fixture_path.parent,
        confirmation_receipt,
        f"{fixture_path} confirmation",
    )
    confirmation_trace = read_json(confirmation_path)
    confirmation_header = confirmation_trace.get("header")
    if not isinstance(confirmation_header, dict):
        raise PromotionError(f"{fixture_path} confirmation has no capture header")
    confirmation_profile_state = _validate_profile_state_v25(
        repo_root,
        evidence_root,
        confirmation_header,
        f"{fixture_path} confirmation",
    )
    if confirmation_profile_state["identity"] != profile_state["identity"]:
        raise PromotionError(
            f"{fixture_path} confirmation changed profile-state identity"
        )
    confirmation_source = _validate_source_v25(
        repo_root,
        confirmation_header.get("source"),
        f"{fixture_path} confirmation",
    )
    if canonical_bytes(source) != canonical_bytes(confirmation_source):
        raise PromotionError(f"{fixture_path} confirmation changed capture provenance")
    primary_identity = (header.get("instance"), header.get("process_id"))
    confirmation_identity = (
        confirmation_header.get("instance"),
        confirmation_header.get("process_id"),
    )
    if (
        not isinstance(primary_identity[0], str)
        or not isinstance(primary_identity[1], int)
        or not isinstance(confirmation_identity[0], str)
        or not isinstance(confirmation_identity[1], int)
        or primary_identity == confirmation_identity
    ):
        raise PromotionError(f"{fixture_path} did not use two fresh instance/PID identities")
    confirmation_samples = _settled_samples_v25(
        confirmation_trace, f"{fixture_path} confirmation"
    )
    confirmation_payload = confirmation_samples[0].get("payload")
    if not isinstance(confirmation_payload, dict) or not isinstance(
        confirmation_payload.get("screen_id"), str
    ):
        raise PromotionError(f"{fixture_path} confirmation has no screen payload")
    _validate_browser_tab_v25(
        confirmation_payload["screen_id"],
        confirmation_payload,
        confirmation_header.get("browser_tab_verification"),
        f"{fixture_path} confirmation",
    )
    if primary_screen_tag in {
        "dark_cloud_browser",
        "dark_cloud_recent",
        "dark_cloud_online_levels",
        "dark_cloud_my_levels",
    }:
        try:
            resolve_browser_tab(layout, f"{fixture_path} resolved layout")
        except NativeMenuBrowserTabError as error:
            raise PromotionError(str(error)) from error
    return {
        "fixture": fixture,
        "header": header,
        "layout": layout,
        "primary_trace": raw_trace,
        "confirmation_trace": confirmation_trace,
        "primary_samples": primary_samples,
        "confirmation_samples": confirmation_samples,
        "primary_trace_path": raw_path,
        "confirmation_trace_path": confirmation_path,
    }


def _resolved_navigation_inputs_v25(
    evidence_root: Path, navigation_path: Path, navigation: dict[str, Any]
) -> tuple[Path, Path, Path, Path | None, Path]:
    resolution = navigation.get("header", {}).get("ambient_lifecycle_resolution")
    if not isinstance(resolution, dict) or resolution.get("settlement_spec") != "2.9":
        raise PromotionError(
            "candidate navigation has no machine-derived ambient_lifecycle_resolution for Settlement v2.9"
        )
    primary = _receipt_path_v25(
        evidence_root,
        navigation_path.parent,
        resolution.get("primary_raw_recording", {}),
        "v2.9 primary navigation",
    )
    confirmation = _receipt_path_v25(
        evidence_root,
        navigation_path.parent,
        resolution.get("confirmation_raw_recording", {}),
        "v2.9 confirmation navigation",
    )
    relative_motion = resolution.get("motion_observation_directory")
    if not isinstance(relative_motion, str) or not relative_motion:
        raise PromotionError("ambient lifecycle resolution lost its motion observation directory")
    root = evidence_root.resolve()
    motion_root = (root / relative_motion).resolve()
    if not motion_root.is_relative_to(root):
        raise PromotionError("motion observation directory escapes the evidence root")
    supplemental_receipt = resolution.get("supplemental_settled_pair_manifest")
    supplemental = (
        _receipt_path_v25(
            evidence_root,
            navigation_path.parent,
            supplemental_receipt,
            "v2.9 supplemental settled-pair manifest",
        )
        if isinstance(supplemental_receipt, dict)
        else None
    )
    asset_manifest = _receipt_path_v25(
        evidence_root,
        navigation_path.parent,
        resolution.get("choice_slot_asset_manifest", {}),
        "v2.9 choice-slot asset manifest",
    )
    return primary, confirmation, motion_root, supplemental, asset_manifest


def _aggregate_wrapper_map(
    values: Any, expected_fixtures: set[str], label: str
) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list):
        raise PromotionError(f"{label} is not an array")
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("fixture"), str):
            raise PromotionError(f"{label} contains an unresolvable fixture")
        fixture = value["fixture"]
        if fixture in result:
            raise PromotionError(f"{label} refuses ambiguous duplicate {fixture}")
        result[fixture] = value
    if set(result) != expected_fixtures:
        raise PromotionError(
            f"{label} census differs: missing={sorted(expected_fixtures - set(result))} "
            f"extra={sorted(set(result) - expected_fixtures)}"
        )
    return result


def _navigation_endpoint_signature_v25(endpoint: dict[str, Any]) -> dict[str, Any]:
    return {
        field: endpoint.get(field)
        for field in (
            "semantic_surface",
            "semantic_generation",
            "tagged_screen",
            "layout_generation",
            "element_count",
        )
    }


def _navigation_population_trace_pairs_v25(
    resolved_navigation: dict[str, Any],
    confirmation_path: Path,
    required_layouts: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    if not required_layouts:
        return {}
    confirmation_navigation = read_json(confirmation_path)

    def edge_map(recording: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
        edges = recording.get("edges")
        if not isinstance(edges, list) or not edges:
            raise PromotionError(
                f"{label} population-witness routing reached no navigation edges"
            )
        result = {
            edge.get("id"): edge
            for edge in edges
            if isinstance(edge, dict) and isinstance(edge.get("id"), str)
        }
        if len(result) != len(edges):
            raise PromotionError(
                f"{label} population-witness edge lookup is absent or ambiguous"
            )
        return result

    primary_by_id = edge_map(resolved_navigation, "primary resolved")
    confirmation_by_id = edge_map(
        confirmation_navigation, "confirmation raw"
    )
    if set(primary_by_id) != set(confirmation_by_id):
        raise PromotionError(
            "population-witness routing changed the paired navigation edge census"
        )
    result: dict[str, list[dict[str, Any]]] = {}
    for edge_id in sorted(primary_by_id):
        primary_edge = primary_by_id[edge_id]
        confirmation_edge = confirmation_by_id[edge_id]
        primary_header = primary_edge.get("header")
        confirmation_header = confirmation_edge.get("header")
        if not isinstance(primary_header, dict) or not isinstance(
            confirmation_header, dict
        ):
            raise PromotionError(
                f"edge {edge_id} population-witness headers are absent"
            )
        primary_identity = (
            primary_header.get("instance"),
            primary_header.get("process_id"),
        )
        confirmation_identity = (
            confirmation_header.get("instance"),
            confirmation_header.get("process_id"),
        )
        if (
            not isinstance(primary_identity[0], str)
            or not isinstance(primary_identity[1], int)
            or not isinstance(confirmation_identity[0], str)
            or not isinstance(confirmation_identity[1], int)
            or primary_identity == confirmation_identity
        ):
            raise PromotionError(
                f"edge {edge_id} population-witness pair is not two fresh instances"
            )
        for side in ("before", "after"):
            primary_endpoint = primary_edge.get(side)
            confirmation_endpoint = confirmation_edge.get(side)
            if not isinstance(primary_endpoint, dict) or not isinstance(
                confirmation_endpoint, dict
            ):
                raise PromotionError(
                    f"edge {edge_id} {side} population-witness endpoint is absent"
                )
            layout_id = primary_endpoint.get("layout_id")
            primary_trace = primary_endpoint.get("settlement_trace")
            confirmation_trace = confirmation_endpoint.get("settlement_trace")
            if (
                not isinstance(layout_id, str)
                or not isinstance(primary_trace, dict)
                or not isinstance(confirmation_trace, dict)
            ):
                raise PromotionError(
                    f"edge {edge_id} {side} population-witness trace is incomplete"
                )
            if layout_id not in required_layouts:
                continue
            if canonical_bytes(primary_endpoint.get("layout")) != canonical_bytes(
                required_layouts[layout_id]
            ):
                raise PromotionError(
                    f"edge {edge_id} {side} population witness does not bind "
                    f"the resolved standalone {layout_id}"
                )
            result.setdefault(layout_id, []).append(
                {
                    "edge_id": edge_id,
                    "side": side,
                    "primary_identity": list(primary_identity),
                    "confirmation_identity": list(confirmation_identity),
                    "primary_trace": primary_trace,
                    "confirmation_trace": confirmation_trace,
                }
            )
    if "create-discipline" in required_layouts and "create-discipline" not in result:
        raise PromotionError(
            "population-witness routing did not reach create-discipline"
        )
    return result


def _select_population_trace_pair_v25(
    layout_id: str,
    landed_generation: Any,
    settled_generation: Any,
    standalone_primary: dict[str, Any],
    standalone_confirmation: dict[str, Any],
    navigation_pairs: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    def qualifies(
        primary_trace: dict[str, Any], confirmation_trace: dict[str, Any], label: str
    ) -> tuple[bool, dict[str, Any]]:
        primary = _population_evidence(primary_trace, f"{label} primary")
        confirmation = _population_evidence(
            confirmation_trace, f"{label} confirmation"
        )

        def settled_generations(trace: dict[str, Any]) -> set[Any]:
            samples = trace.get("settled_window_samples")
            if not isinstance(samples, list) or not samples:
                raise PromotionError(
                    f"{label} population witness has no settled sample window"
                )
            values: set[Any] = set()
            for sample in samples:
                payload = sample.get("payload") if isinstance(sample, dict) else None
                if not isinstance(payload, dict):
                    raise PromotionError(
                        f"{label} population witness has a sample without payload"
                    )
                values.add(payload.get("generation"))
            return values

        detail = {
            "primary_generation_trace": primary["generation_trace"],
            "confirmation_generation_trace": confirmation["generation_trace"],
            "primary_settled_generations": sorted(
                settled_generations(primary_trace)
            ),
            "confirmation_settled_generations": sorted(
                settled_generations(confirmation_trace)
            ),
        }
        return (
            landed_generation in primary["generation_trace"]
            and landed_generation in confirmation["generation_trace"],
            detail,
        )

    if landed_generation == settled_generation:
        return (
            standalone_primary,
            standalone_confirmation,
            {"source": "standalone_pair", "generation_witness_required": False},
        )
    standalone_qualifies, standalone_detail = qualifies(
        standalone_primary,
        standalone_confirmation,
        f"{layout_id} standalone",
    )
    if standalone_qualifies:
        return (
            standalone_primary,
            standalone_confirmation,
            {
                "source": "standalone_pair",
                "generation_witness_required": True,
                **standalone_detail,
            },
        )
    qualifying_navigation: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for pair in navigation_pairs.get(layout_id, []):
        qualified, detail = qualifies(
            pair["primary_trace"],
            pair["confirmation_trace"],
            f"{layout_id} edge {pair['edge_id']} {pair['side']}",
        )
        if qualified:
            qualifying_navigation.append((pair, detail))
    if len(qualifying_navigation) > 1:
        identities = [
            (pair["edge_id"], pair["side"])
            for pair, _ in qualifying_navigation
        ]
        raise PromotionError(
            f"{layout_id} population-witness routing is ambiguous: {identities}"
        )
    if len(qualifying_navigation) == 1:
        pair, detail = qualifying_navigation[0]
        return (
            pair["primary_trace"],
            pair["confirmation_trace"],
            {
                "source": "paired_navigation_endpoint",
                "edge_id": pair["edge_id"],
                "side": pair["side"],
                "primary_identity": pair["primary_identity"],
                "confirmation_identity": pair["confirmation_identity"],
                "generation_witness_required": True,
                **detail,
            },
        )
    return (
        standalone_primary,
        standalone_confirmation,
        {
            "source": "standalone_pair_without_landed_generation_witness",
            "generation_witness_required": True,
            **standalone_detail,
        },
    )


def _controls_settled_identity_v211(
    samples: list[dict[str, Any]], header: dict[str, Any], label: str
) -> dict[str, Any]:
    if len(samples) < 40:
        raise PromotionError(f"v2.11 {label} has fewer than 40 settled samples")
    surfaces: set[Any] = set()
    screens: set[Any] = set()
    titles: set[Any] = set()
    semantic_generations: set[Any] = set()
    layout_generations: set[Any] = set()
    for sample in samples:
        payload = sample.get("payload")
        if not isinstance(payload, dict):
            raise PromotionError(f"v2.11 {label} contains a sample without payload")
        surfaces.add(sample.get("semantic_surface"))
        screens.add(payload.get("screen_id"))
        titles.add(payload.get("screen_title"))
        semantic_generations.add(sample.get("semantic_generation"))
        layout_generations.add(payload.get("generation"))
    if (
        surfaces != {"controls"}
        or screens != {"controls"}
        or titles != {"Wizard Controls"}
        or len(semantic_generations) != 1
        or len(layout_generations) != 1
    ):
        raise PromotionError(
            f"v2.11 {label} lost capture-time classifier/tag agreement"
        )
    return {
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "sample_count": len(samples),
        "stable_span_milliseconds": (
            samples[-1].get("elapsed_milliseconds", 0)
            - samples[0].get("elapsed_milliseconds", 0)
        ),
        "semantic_surface": "controls",
        "operator_tagged_screen": "controls",
        "screen_title": "Wizard Controls",
        "semantic_generation": next(iter(semantic_generations)),
        "layout_generation": next(iter(layout_generations)),
    }


def _validate_controls_context_v211(
    contract: dict[str, Any],
    record: dict[str, Any],
    candidate_path: Path,
    evidence_root: Path,
    resolved_navigation: dict[str, Any],
) -> dict[str, Any]:
    if contract.get("schema") != (
        "solomon-dark-native-menu-controls-core-supersession-v211"
    ):
        raise PromotionError("v2.11 Controls structural contract schema is invalid")
    expected_candidate = contract.get("superseding_candidate_fixture")
    if not isinstance(expected_candidate, dict) or file_receipt(candidate_path) != {
        "sha256": expected_candidate.get("sha256"),
        "bytes": expected_candidate.get("bytes"),
    }:
        raise PromotionError(
            "v2.11 exact Controls candidate receipt does not match the authorized core"
        )
    audits = contract.get("source_audits")
    if not isinstance(audits, dict) or set(audits) != {"title", "structural_core"}:
        raise PromotionError("v2.11 Controls source-audit census is not exact")
    for label in ("title", "structural_core"):
        recorded = audits[label]
        if not isinstance(recorded, dict) or set(recorded) != {
            "path",
            "sha256",
            "bytes",
        }:
            raise PromotionError(f"v2.11 Controls {label} audit receipt is malformed")
        relative = Path(str(recorded["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise PromotionError(f"v2.11 Controls {label} audit path escapes evidence")
        audit_path = evidence_root / relative
        if not audit_path.is_file() or file_receipt(audit_path) != {
            "sha256": recorded.get("sha256"),
            "bytes": recorded.get("bytes"),
        }:
            raise PromotionError(
                f"v2.11 Controls {label} audit receipt does not match its evidence file"
            )

    paired = contract.get("paired_settlement")
    if not isinstance(paired, dict) or paired.get("two_independent_instances") is not True:
        raise PromotionError("v2.11 Controls contract lost two-instance settlement")
    primary_header = record.get("header")
    confirmation_header = record.get("confirmation_trace", {}).get("header")
    if not isinstance(primary_header, dict) or not isinstance(
        confirmation_header, dict
    ):
        raise PromotionError("v2.11 Controls settlement headers are absent")
    primary = _controls_settled_identity_v211(
        record["primary_samples"], primary_header, "primary settlement"
    )
    confirmation = _controls_settled_identity_v211(
        record["confirmation_samples"],
        confirmation_header,
        "confirmation settlement",
    )
    if (
        primary != paired.get("primary")
        or confirmation != paired.get("confirmation")
        or paired.get("classifier_and_tag_agree") is not True
        or (primary["instance"], primary["process_id"])
        == (confirmation["instance"], confirmation["process_id"])
    ):
        raise PromotionError(
            "v2.11 Controls paired settlement does not reproduce the authorized instances"
        )

    edges = resolved_navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise PromotionError("v2.11 Controls endpoint audit reached no navigation edges")
    expected_endpoints = contract.get("navigation_endpoints")
    if not isinstance(expected_endpoints, list) or len(expected_endpoints) != 2:
        raise PromotionError("v2.11 Controls contract does not pin exactly two endpoints")
    expected_by_identity = {
        (value.get("edge_id"), value.get("side"), value.get("trigger")): value
        for value in expected_endpoints
        if isinstance(value, dict)
    }
    if len(expected_by_identity) != 2:
        raise PromotionError("v2.11 Controls endpoint identities are ambiguous")
    observed: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for side in ("before", "after"):
            endpoint = edge.get(side)
            if not isinstance(endpoint, dict) or endpoint.get("layout_id") != "controls":
                continue
            identity = (edge.get("id"), side, edge.get("trigger"))
            if identity in observed:
                raise PromotionError("v2.11 Controls endpoint lookup is ambiguous")
            if canonical_bytes(endpoint.get("layout")) != canonical_bytes(
                record["layout"]
            ):
                raise PromotionError(
                    f"v2.11 Controls endpoint {identity} does not equal its standalone"
                )
            observed[identity] = {
                "edge_id": identity[0],
                "side": side,
                "trigger": identity[2],
                "semantic_surface": endpoint.get("semantic_surface"),
                "tagged_screen": endpoint.get("tagged_screen"),
                "layout_generation": endpoint.get("layout_generation"),
                "element_count": endpoint.get("element_count"),
                "frame_sha256": endpoint.get("frame_sha256"),
            }
    if set(observed) != set(expected_by_identity) or any(
        observed[identity] != expected_by_identity[identity]
        for identity in observed
    ):
        raise PromotionError(
            "v2.11 Controls endpoints do not reproduce both exact standalone bindings"
        )
    return {
        "candidate_receipt": file_receipt(candidate_path),
        "paired_settlement": {"primary": primary, "confirmation": confirmation},
        "endpoint_count": len(observed),
        "destination_equals_standalone": True,
    }


def validate_and_promote(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    navigation_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    landed_root = repo_root / "tests/fixtures/webgame"
    landed_golden = read_json(landed_root / "menu-goldens.json")
    order_override_contract = read_json(
        landed_root / "native-menu-beta-notice-order-v29.json"
    )
    controls_title_contract = read_json(
        landed_root / "native-menu-controls-title-v210.json"
    )
    controls_core_contract = read_json(
        landed_root / "native-menu-controls-core-v211.json"
    )
    resolved_navigation = read_json(navigation_path)
    (
        primary_navigation,
        confirmation_navigation,
        motion_root,
        supplemental_manifest,
        asset_manifest,
    ) = _resolved_navigation_inputs_v25(
        evidence_root, navigation_path, resolved_navigation
    )
    _validate_navigation_profile_state_v25(
        repo_root,
        evidence_root,
        read_json(primary_navigation),
        "primary navigation",
    )
    _validate_navigation_profile_state_v25(
        repo_root,
        evidence_root,
        read_json(confirmation_navigation),
        "confirmation navigation",
    )
    try:
        resolve_campaign(
            candidate_root,
            evidence_root,
            primary_navigation,
            confirmation_navigation,
            motion_root,
            navigation_path,
            evidence_root / "ambient-resolution-verification-unused.json",
            False,
            True,
            supplemental_manifest,
            asset_manifest,
        )
    except (ResolutionError, SettlementV2Error) as error:
        raise PromotionError(
            f"candidate Settlement v2.9 campaign did not re-derive: {error}"
        ) from error

    landed_layout_entries = landed_golden.get("layouts")
    if not isinstance(landed_layout_entries, list) or len(landed_layout_entries) != 28:
        raise PromotionError("landed menu corpus no longer has the 28-layout G11 census")
    layout_names = {
        Path(entry["fixture"]).name
        for entry in landed_layout_entries
        if isinstance(entry, dict) and isinstance(entry.get("fixture"), str)
    }
    if len(layout_names) != 28 or "main-menu-root.json" not in layout_names:
        raise PromotionError("landed menu layout lookup is absent or ambiguous")
    candidate_layout_paths = require_unique_files(
        candidate_root / "menu-layouts", "*.json", layout_names
    )
    candidate_transition_paths = require_unique_files(
        candidate_root / "menu-transition-layouts",
        "*.json",
        {"hub_new_game.json", "hub_resumed.json"},
    )
    records: dict[str, dict[str, Any]] = {}
    path_by_layout_id: dict[str, Path] = {}
    for name, path in {**candidate_layout_paths, **candidate_transition_paths}.items():
        record = validate_settlement_fixture_v25(
            repo_root, evidence_root, path, read_json(path)
        )
        layout_id = path.stem
        if layout_id in records:
            raise PromotionError(f"candidate standalone id '{layout_id}' is ambiguous")
        records[layout_id] = record
        path_by_layout_id[layout_id] = path
    if len(records) != 30 or not {"hub_new_game", "hub_resumed"} <= set(records):
        raise PromotionError(
            "candidate standalone sweep did not reach 28 menus plus two Hub layouts"
        )

    landed_by_layout_id: dict[str, dict[str, Any]] = {}
    landed_path_by_layout_id: dict[str, Path] = {}
    for entry in landed_layout_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("fixture"), str):
            raise PromotionError("landed menu layout lookup contains an invalid entry")
        layout_id = Path(entry["fixture"]).stem
        layout = entry.get("layout")
        if layout_id in landed_by_layout_id or not isinstance(layout, dict):
            raise PromotionError(
                f"landed menu layout lookup is ambiguous for {layout_id!r}"
            )
        landed_by_layout_id[layout_id] = layout
        landed_path_by_layout_id[layout_id] = landed_root / entry["fixture"]
    generation_changed_layout_ids = {
        layout_id
        for layout_id in set(landed_by_layout_id) & set(records)
        if landed_by_layout_id[layout_id].get("generation")
        != records[layout_id]["layout"].get("generation")
    }
    navigation_population_pairs = _navigation_population_trace_pairs_v25(
        resolved_navigation,
        confirmation_navigation,
        {
            layout_id: records[layout_id]["layout"]
            for layout_id in generation_changed_layout_ids
        },
    )
    for witness in ("create-element", "pause-menu", "beta-notice", "main-menu-root"):
        if witness not in records or witness not in landed_by_layout_id:
            raise PromotionError(f"overlay derivation did not reach {witness} witness")
    create_residual, create_ambient = diagnosis_prereference_residual(
        landed_by_layout_id["create-element"], records["create-element"]["layout"]
    )
    pause_residual, pause_ambient = diagnosis_prereference_residual(
        landed_by_layout_id["pause-menu"], records["pause-menu"]["layout"]
    )
    create_corroboration = semantic_overlay_corroboration(create_residual)
    pause_corroboration = semantic_overlay_corroboration(pause_residual)
    try:
        beta_standalone_core = reproduce_standalone_structural_core(
            records["beta-notice"]["primary_samples"],
            records["beta-notice"]["confirmation_samples"],
            label="beta_notice",
            authorized_ambient_family=set(
                records["beta-notice"]["layout"]["ambient_family_art_ids"]
            ),
        )
        main_standalone_core = reproduce_standalone_structural_core(
            records["main-menu-root"]["primary_samples"],
            records["main-menu-root"]["confirmation_samples"],
            label="main_menu_root",
            authorized_ambient_family=set(
                records["main-menu-root"]["layout"]["ambient_family_art_ids"]
            ),
        )
        derived_overlay_reference = derive_overlay_reference(
            beta_standalone_core,
            main_standalone_core,
            create_corroboration,
            pause_corroboration,
        )
    except (OverlayV25Error, LandedDiagnosisError) as error:
        raise PromotionError(f"derived beta-dialog overlay reference: {error}") from error
    candidate_overlay_path = candidate_root / "menu-overlay-reference.json"
    if not candidate_overlay_path.is_file():
        raise PromotionError("candidate derived v2.9 overlay reference is missing")
    candidate_overlay_reference = read_json(candidate_overlay_path)
    if canonical_bytes(candidate_overlay_reference) != canonical_bytes(
        derived_overlay_reference
    ):
        raise PromotionError(
            "candidate overlay reference is not the derived beta_notice-minus-main_menu_root result"
        )

    for layout_id, record in records.items():
        try:
            assert_overlay_hygiene_v25(record["layout"], derived_overlay_reference)
            for sample in (
                *record["primary_samples"],
                *record["confirmation_samples"],
            ):
                payload = sample.get("payload")
                if not isinstance(payload, dict):
                    raise PromotionError(
                        f"{layout_id} overlay hygiene reached a sample without payload"
                    )
                assert_overlay_hygiene_v25(payload, derived_overlay_reference)
        except OverlayV25Error as error:
            raise PromotionError(f"{layout_id}: {error}") from error

    standalone_diagnoses: dict[str, dict[str, Any]] = {}
    for layout_id in sorted(records):
        if layout_id not in landed_by_layout_id:
            fork = records[layout_id]["header"].get("path_dependent_core")
            if layout_id not in {"hub_new_game", "hub_resumed"} or not isinstance(
                fork, dict
            ):
                raise PromotionError(
                    f"candidate standalone {layout_id} has no landed comparison"
                )
            standalone_diagnoses[layout_id] = {
                "status": "new_path_dependent_layout",
                "parent_screen_id": fork.get("parent_screen_id"),
                "path_qualifier": fork.get("path_qualifier"),
                "selector": fork.get("selector"),
                "fork_decision": copy.deepcopy(fork.get("fork_decision")),
            }
            continue
        (
            population_primary_trace,
            population_confirmation_trace,
            population_trace_selection,
        ) = _select_population_trace_pair_v25(
            layout_id,
            landed_by_layout_id[layout_id].get("generation"),
            records[layout_id]["layout"].get("generation"),
            records[layout_id]["primary_trace"],
            records[layout_id]["confirmation_trace"],
            navigation_population_pairs,
        )
        try:
            standalone_diagnoses[layout_id] = diagnose_landed_layout(
                layout_id,
                landed_by_layout_id[layout_id],
                records[layout_id]["layout"],
                population_primary_trace,
                population_confirmation_trace,
                derived_overlay_reference,
                order_override_contract,
                controls_title_contract,
                controls_core_contract,
                file_receipt(landed_path_by_layout_id[layout_id]),
                file_receipt(path_by_layout_id[layout_id]),
            )
            standalone_diagnoses[layout_id][
                "population_trace_selection"
            ] = population_trace_selection
        except LandedDiagnosisError as error:
            raise PromotionError(f"STOP: standalone {layout_id}: {error}") from error

    controls_core_context = _validate_controls_context_v211(
        controls_core_contract,
        records["controls"],
        path_by_layout_id["controls"],
        evidence_root,
        resolved_navigation,
    )

    candidate_golden_path = candidate_root / "menu-goldens.json"
    candidate_golden = read_json(candidate_golden_path)
    if candidate_golden.get("schema") != "solomon-dark-menu-goldens-v3":
        raise PromotionError("candidate aggregate does not use Settlement v2.9 schema v3")
    expected_layout_fixtures = {
        f"menu-layouts/{name}" for name in candidate_layout_paths
    }
    expected_transition_fixtures = {
        "menu-transition-layouts/hub_new_game.json",
        "menu-transition-layouts/hub_resumed.json",
    }
    embedded = _aggregate_wrapper_map(
        candidate_golden.get("layouts"), expected_layout_fixtures, "candidate embedded layouts"
    )
    embedded_transition = _aggregate_wrapper_map(
        candidate_golden.get("transition_endpoint_layouts"),
        expected_transition_fixtures,
        "candidate embedded transition layouts",
    )
    for fixture_name, wrapper in {**embedded, **embedded_transition}.items():
        layout_id = Path(fixture_name).stem
        fixture = records[layout_id]["fixture"]
        if fixture != {
            "schema": fixture["schema"],
            "header": wrapper.get("header"),
            "layout": wrapper.get("layout"),
        }:
            raise PromotionError(
                f"candidate embedded golden and standalone {fixture_name} disagree"
            )

    overlay_receipt = candidate_golden.get("header", {}).get("overlay_reference")
    expected_overlay_receipt = {
        "fixture": "menu-overlay-reference.json",
        "sha256": file_sha256(candidate_overlay_path),
        "bytes": candidate_overlay_path.stat().st_size,
    }
    if canonical_bytes(overlay_receipt) != canonical_bytes(expected_overlay_receipt):
        raise PromotionError("candidate aggregate records a false derived overlay receipt")
    try:
        profile_baseline = load_profile_state_baseline(repo_root)
    except NativeMenuProfileStateError as error:
        raise PromotionError(str(error)) from error
    expected_profile_baseline_receipt = {
        "fixture": "native-menu-profile-state-baseline.json",
        "sha256": profile_baseline["sha256"],
        "bytes": profile_baseline["bytes"],
        "profile_state_identity_sha256": profile_baseline["identity"],
        "corrective": "shellfix task #101 consumes the settled corpus",
    }
    if canonical_bytes(
        candidate_golden.get("header", {}).get("profile_state_baseline")
    ) != canonical_bytes(expected_profile_baseline_receipt):
        raise PromotionError(
            "candidate aggregate records a false committed profile-state baseline receipt"
        )
    navigation_receipt = candidate_golden.get("header", {}).get("raw_recording")
    if not isinstance(navigation_receipt, dict):
        raise PromotionError("candidate aggregate has no resolved-navigation receipt")
    if (
        navigation_receipt.get("sha256") != file_sha256(navigation_path)
        or navigation_receipt.get("bytes") != navigation_path.stat().st_size
    ):
        raise PromotionError("candidate aggregate records a false navigation receipt")

    all_wrappers = {**embedded, **embedded_transition}
    reference_names: set[str] = set()
    for fixture_name, wrapper in all_wrappers.items():
        reference = wrapper.get("reference_capture")
        reference_sha256 = wrapper.get("reference_sha256")
        if not isinstance(reference, str) or not isinstance(reference_sha256, str):
            raise PromotionError(f"{fixture_name} has no committed visual reference receipt")
        name = Path(reference).name
        if name in reference_names:
            raise PromotionError(f"visual reference lookup is ambiguous for {name}")
        reference_names.add(name)
        reference_path = candidate_root / "menu-reference-captures" / name
        if not reference_path.is_file() or file_sha256(reference_path) != reference_sha256:
            raise PromotionError(f"{fixture_name} visual reference hash is false")
    candidate_references = require_unique_files(
        candidate_root / "menu-reference-captures", "*.png", reference_names
    )

    landed_edges = landed_golden.get("navigation_graph", {}).get("edges")
    candidate_edges = candidate_golden.get("navigation_graph", {}).get("edges")
    resolved_edges = resolved_navigation.get("edges")
    if not all(isinstance(value, list) and value for value in (landed_edges, candidate_edges, resolved_edges)):
        raise PromotionError("navigation audit did not reach real edge content")
    old_by_id = {
        edge.get("id"): edge for edge in landed_edges if isinstance(edge, dict)
    }
    candidate_by_id = {
        edge.get("id"): edge for edge in candidate_edges if isinstance(edge, dict)
    }
    resolved_by_id = {
        edge.get("id"): edge for edge in resolved_edges if isinstance(edge, dict)
    }
    if (
        len(old_by_id) != len(landed_edges)
        or len(candidate_by_id) != len(candidate_edges)
        or len(resolved_by_id) != len(resolved_edges)
        or set(candidate_by_id) != set(old_by_id)
        or set(resolved_by_id) != set(old_by_id)
    ):
        raise PromotionError("candidate navigation edge census is absent, duplicate, or changed")
    source_audit: list[dict[str, Any]] = []
    destination_audit: list[dict[str, Any]] = []
    fixture_for_layout_id = {
        layout_id: (
            f"menu-transition-layouts/{path.name}"
            if path.parent.name == "menu-transition-layouts"
            else f"menu-layouts/{path.name}"
        )
        for layout_id, path in path_by_layout_id.items()
    }
    for edge_id in sorted(candidate_by_id):
        edge = candidate_by_id[edge_id]
        raw_edge = resolved_by_id[edge_id]
        old_edge = old_by_id[edge_id]
        for side in ("before", "after"):
            endpoint = edge.get(side)
            raw_endpoint = raw_edge.get(side)
            if not isinstance(endpoint, dict) or not isinstance(raw_endpoint, dict):
                raise PromotionError(f"edge {edge_id} {side} is incomplete")
            layout_id = raw_endpoint.get("layout_id")
            if not isinstance(layout_id, str) or layout_id not in records:
                raise PromotionError(f"edge {edge_id} {side} has no unique standalone layout")
            standalone = records[layout_id]["layout"]
            if canonical_bytes(raw_endpoint.get("layout")) != canonical_bytes(standalone):
                raise PromotionError(
                    f"resolved edge {edge_id} {side} does not equal standalone {layout_id}"
                )
            if canonical_bytes(endpoint.get("layout")) != canonical_bytes(standalone):
                raise PromotionError(
                    f"aggregate edge {edge_id} {side} does not equal standalone {layout_id}"
                )
            if endpoint.get("layout_id") != layout_id:
                raise PromotionError(f"aggregate edge {edge_id} {side} changed layout identity")
            try:
                assert_overlay_hygiene_v25(standalone, derived_overlay_reference)
            except OverlayV25Error as error:
                raise PromotionError(f"edge {edge_id} {side}: {error}") from error
        destination_layout_id = raw_edge["after"]["layout_id"]
        destination_fixture = fixture_for_layout_id[destination_layout_id]
        if edge.get("destination_layout_fixture") != destination_fixture:
            raise PromotionError(
                f"edge {edge_id} destination fixture does not derive from its standalone"
            )
        destination_audit.append(
            {
                "edge": edge_id,
                "standalone_fixture": destination_fixture,
                "structural_core_sha256": records[destination_layout_id]["layout"][
                    "structural_core_sha256"
                ],
                "classification_map_sha256": ambient_sha256_json(
                    records[destination_layout_id]["layout"]["classification_map"]
                ),
                "settle_latency_milliseconds": edge["after"]["settlement"][
                    "settle_latency_milliseconds"
                ],
                "old_generation": old_edge["after"].get("layout_generation"),
                "new_generation": edge["after"].get("layout_generation"),
                "old_element_count": old_edge["after"].get("element_count"),
                "new_element_count": edge["after"].get("element_count"),
            }
        )
        source_layout_id = raw_edge["before"]["layout_id"]
        if source_layout_id in landed_by_layout_id:
            (
                population_primary_trace,
                population_confirmation_trace,
                population_trace_selection,
            ) = _select_population_trace_pair_v25(
                source_layout_id,
                landed_by_layout_id[source_layout_id].get("generation"),
                records[source_layout_id]["layout"].get("generation"),
                records[source_layout_id]["primary_trace"],
                records[source_layout_id]["confirmation_trace"],
                navigation_population_pairs,
            )
            try:
                source_diagnosis = diagnose_landed_layout(
                    source_layout_id,
                    landed_by_layout_id[source_layout_id],
                    records[source_layout_id]["layout"],
                    population_primary_trace,
                    population_confirmation_trace,
                    derived_overlay_reference,
                    order_override_contract,
                    controls_title_contract,
                    controls_core_contract,
                    file_receipt(landed_path_by_layout_id[source_layout_id]),
                    file_receipt(path_by_layout_id[source_layout_id]),
                )
                source_diagnosis[
                    "population_trace_selection"
                ] = population_trace_selection
            except LandedDiagnosisError as error:
                raise PromotionError(
                    f"STOP: transition source {edge_id}: {error}"
                ) from error
        else:
            source_diagnosis = {
                "status": "new_path_dependent_layout",
                "landed_payload": "not_embedded_in_v1_navigation_aggregate",
                "fork_decision": copy.deepcopy(
                    records[source_layout_id]["header"]["path_dependent_core"][
                        "fork_decision"
                    ]
                ),
            }
        signature_match = _navigation_endpoint_signature_v25(
            edge["before"]
        ) == _navigation_endpoint_signature_v25(old_edge["before"])
        frame_match = edge["before"].get("frame_sha256") == old_edge["before"].get(
            "frame_sha256"
        )
        if source_diagnosis["status"] == "strict_structural_bit_match" and (
            not signature_match or not frame_match
        ):
            raise PromotionError(
                f"STOP: strict transition source {edge_id} does not bit-match its landed signature/frame"
            )
        source_audit.append(
            {
                "edge": edge_id,
                "layout_id": source_layout_id,
                "diagnosis": source_diagnosis,
                "signature_bit_match": signature_match,
                "frame_bit_match": frame_match,
            }
        )

    promotion_pairs: list[tuple[Path, Path]] = [
        *(
            (source, landed_root / "menu-layouts" / name)
            for name, source in candidate_layout_paths.items()
        ),
        *(
            (source, landed_root / "menu-transition-layouts" / name)
            for name, source in candidate_transition_paths.items()
        ),
        *(
            (source, landed_root / "menu-reference-captures" / name)
            for name, source in candidate_references.items()
        ),
        (candidate_overlay_path, landed_root / "menu-overlay-reference.json"),
        (candidate_golden_path, landed_root / "menu-goldens.json"),
    ]
    if not dry_run:
        for source, destination in promotion_pairs:
            atomic_copy(source, destination)
        try:
            build_menu_baseline(repo_root, False)
        except BaselineBuildError as error:
            raise PromotionError(
                f"promoted fixtures could not refresh the shellfix baseline receipts: {error}"
            ) from error

    corrected = {
        layout_id: diagnosis
        for layout_id, diagnosis in standalone_diagnoses.items()
        if diagnosis["status"] == "corrected"
    }
    return {
        "success": True,
        "dry_run": dry_run,
        "settlement_spec": "2.11",
        "controls_core_supersession": controls_core_context,
        "standalone_count": len(records),
        "standalone_diagnoses": standalone_diagnoses,
        "corrected_screen_count": len(corrected),
        "corrected_screens": sorted(corrected),
        "derived_overlay_reference": {
            "sha256": file_sha256(candidate_overlay_path),
            "bytes": candidate_overlay_path.stat().st_size,
            "create_prereference_ambient_dispositions": create_ambient,
            "pause_prereference_ambient_dispositions": pause_ambient,
            "semantic_draw_count": derived_overlay_reference[
                "overlay_semantic_draw_count"
            ],
        },
        "transition_source_count": len(source_audit),
        "transition_sources": source_audit,
        "transition_destination_count": len(destination_audit),
        "transition_destinations_equal_standalones": destination_audit,
        "promoted_files": [str(destination) for _, destination in promotion_pairs],
        "shellfix_pending_fixture_count": 28,
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
