#!/usr/bin/env python3
"""Validate and promote one complete settled native-menu recapture."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path, PureWindowsPath
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
    _require_v211_controls_core_contract,
    _require_v220_dark_cloud_login_title_contract,
    _v211_semantic_counter,
    diagnose_landed_layout,
    diagnosis_prereference_residual,
    enumerate_unclassified_landed_differences,
    semantic_overlay_corroboration,
)
from native_menu_generation_v219 import (
    V218_DISABLED_CORPUS_STOP,
    NativeMenuGenerationV219Error,
    derive_pair_core_equality,
    validate_instance_local_generation_pair,
)
from native_menu_generation_v218 import (
    NativeMenuGenerationV218Error,
    compare_semantic_cores as compare_generation_cores_v218,
    measure_generation_window,
)
from native_menu_census_era_v221 import (
    CensusEraV221Error,
    require_contract as require_census_era_contract,
    semantic_sha256 as semantic_sha256_v221,
    validate_dark_cloud_menu_references,
    validate_pause_equivalence,
)
from native_menu_final_disposition_v222 import (
    FinalDispositionV222Error,
    authorize_named_endpoint_vacuity,
    require_contract as require_final_disposition_v222_contract,
    sequence_sha256 as sequence_sha256_v222,
)
from native_menu_overlay_v25 import (
    OverlayV25Error,
    assert_overlay_hygiene as assert_overlay_hygiene_v25,
    derive_overlay_reference,
)
from native_menu_profile_state import (
    FRESH_BASELINE_ID,
    NativeMenuProfileStateError,
    assert_navigation_baseline_allowed,
    load_hub_binding_contract,
    load_profile_state_baseline,
    required_baseline_for_layout,
    resolve_navigation_profile_binding,
    validate_exact_hub_layout_pair,
    validate_capture_profile_state,
)
from native_menu_browser_tab import (
    NativeMenuBrowserTabError,
    resolve_browser_tab,
    validate_browser_tab,
)
from native_menu_multi_state_path_core import SETTINGS_ENDPOINT_BINDINGS
from native_menu_nonsemantic_overlay import (
    NativeMenuNonSemanticOverlayError,
    validate_overlay_record,
)
from native_menu_semantic_dialog_composite import (
    COMPOSITE_ID,
    LEGACY_PROVENANCE_REASON,
    NativeMenuSemanticDialogCompositeError,
    validate_composite_record,
    validate_qualified_beta_paint_order,
    validate_qualified_beta_supersession,
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
        if adjacent.name
        in {
            "menu-layouts",
            "menu-transition-layouts",
            "menu-overlay-underlays",
        }
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
        temporary.write_bytes(data)
    else:
        shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


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
            repo_root,
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
    git_command = ["git", "-C", str(repo_root)]
    if os.name == "nt":
        match = re.fullmatch(
            r"\\\\wsl(?:\.localhost)?\\([^\\]+)\\(.+)",
            str(repo_root),
            flags=re.IGNORECASE,
        )
        if match is not None:
            distribution, relative = match.groups()
            git_command = [
                "wsl.exe",
                "-d",
                distribution,
                "--",
                "git",
                "-C",
                "/" + relative.replace("\\", "/"),
            ]
    try:
        committed_tree = subprocess.run(
            [*git_command, "rev-parse", f"{source['base_commit_sha']}^{{tree}}"],
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
    *,
    receipt_search_roots: tuple[Path, ...] | None = None,
    required_baseline_id: str | None = None,
    binding_label: str | None = None,
) -> dict[str, Any]:
    try:
        return validate_capture_profile_state(
            repo_root=repo_root,
            header=header,
            label=label,
            evidence_root=evidence_root,
            receipt_search_roots=receipt_search_roots,
            required_baseline_id=required_baseline_id,
            binding_label=binding_label,
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
    receipt_search_roots: tuple[Path, ...],
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
        profile_state = _validate_profile_state_v25(
            repo_root,
            evidence_root,
            header,
            f"{label} edge {edge_id}",
            receipt_search_roots=receipt_search_roots,
        )
        try:
            assert_navigation_baseline_allowed(
                repo_root,
                edge_id=edge_id,
                baseline_id=profile_state["baseline_id"],
            )
        except NativeMenuProfileStateError as error:
            raise PromotionError(str(error)) from error
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
            try:
                expected_layout_id = resolve_navigation_profile_binding(
                    repo_root,
                    edge_id=edge_id,
                    endpoint=endpoint_key,
                    baseline_id=profile_state["baseline_id"],
                )
            except NativeMenuProfileStateError as error:
                raise PromotionError(str(error)) from error
            observed_layout_id = endpoint.get("layout_id")
            if expected_layout_id is not None and observed_layout_id is not None and (
                observed_layout_id != expected_layout_id
            ):
                raise PromotionError(
                    "native-menu per-binding profile-state baseline mismatch: "
                    f"{label} edge '{edge_id}' {side} resolves "
                    f"'{observed_layout_id}' instead of '{expected_layout_id}'"
                )
    if "main_to_dark_cloud" not in reached_ids:
        raise PromotionError(
            f"{label} profile-state sweep did not reach the Dark Cloud entry edge"
        )


def _navigation_profile_receipt_roots_v25(
    evidence_root: Path,
    recording_path: Path,
    recording: dict[str, Any],
    label: str,
) -> tuple[Path, ...]:
    """Resolve only the receipt directories that built this merged recording."""

    chartered_addition = recording.get("header", {}).get("chartered_addition")
    if chartered_addition is None:
        receipt_directory = "navigation-v214-profile-state-receipts"
    elif chartered_addition == {
        "edge_id": "profile_select_new_game_to_create",
        "source": "profile_save_select",
        "destination": "create_element",
        "measurement": "paired pristine route; destination machine-classified",
        "old_navigation_edge_count": 39,
        "new_navigation_edge_count": 40,
    }:
        receipt_directory = "navigation-v219-profile-state-receipts"
    else:
        raise PromotionError(
            f"{label} navigation carries an unrecognized chartered addition"
        )
    roots = {
        (recording_path.parent / receipt_directory).resolve()
    }
    replacement = recording.get("header", {}).get("navigation_edge_replacement")
    if replacement is not None:
        replacement_receipt = (
            replacement.get("replacement")
            if isinstance(replacement, dict)
            else None
        )
        if not isinstance(replacement_receipt, dict):
            raise PromotionError(
                f"{label} navigation replacement has no exact source receipt"
            )
        path_value = replacement_receipt.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise PromotionError(
                f"{label} navigation replacement source path is absent"
            )
        resolved_evidence_root = evidence_root.resolve()
        if re.fullmatch(r"[A-Za-z]:[\\/].+", path_value):
            windows_path = PureWindowsPath(path_value)
            if os.name == "nt":
                windows_root = PureWindowsPath(str(resolved_evidence_root))
                if not windows_path.is_relative_to(windows_root):
                    raise PromotionError(
                        f"{label} navigation replacement Windows path does not name the evidence root"
                    )
                replacement_path = resolved_evidence_root.joinpath(
                    *windows_path.relative_to(windows_root).parts
                ).resolve()
            else:
                root_parts = resolved_evidence_root.parts
                if (
                    len(root_parts) < 5
                    or root_parts[1] != "mnt"
                    or windows_path.drive.lower() != f"{root_parts[2]}:"
                    or tuple(part.lower() for part in windows_path.parts[1:3])
                    != tuple(part.lower() for part in root_parts[3:5])
                ):
                    raise PromotionError(
                        f"{label} navigation replacement Windows path does not name the evidence root"
                    )
                replacement_path = resolved_evidence_root.joinpath(
                    *windows_path.parts[3:]
                ).resolve()
        else:
            replacement_path = Path(path_value).resolve()
        if (
            not replacement_path.is_relative_to(resolved_evidence_root)
            or not replacement_path.is_file()
            or replacement_path.stat().st_size != replacement_receipt.get("bytes")
            or file_sha256(replacement_path) != replacement_receipt.get("sha256")
        ):
            raise PromotionError(
                f"{label} navigation replacement source receipt is false"
            )
        roots.add(
            (
                replacement_path.parent
                / f"{replacement_path.stem}..profile-state"
            ).resolve()
        )
    resolved_roots = tuple(sorted(roots))
    if not resolved_roots or any(not root.is_dir() for root in resolved_roots):
        raise PromotionError(
            f"{label} navigation receipt roots reach no real content"
        )
    return resolved_roots


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
    layout_id = fixture_path.stem
    if fixture.get("schema") != "solomon-dark-native-menu-layout-v3":
        raise PromotionError(f"{fixture_path} does not use Settlement v2.9 schema v3")
    header = fixture.get("header")
    layout = fixture.get("layout")
    if not isinstance(header, dict) or not isinstance(layout, dict):
        raise PromotionError(f"{fixture_path} has no v2.9 header/layout")
    if header.get("recorded_live") is not True:
        raise PromotionError(f"{fixture_path} is not marked as a live recording")
    source = _validate_source_v25(repo_root, header.get("source"), str(fixture_path))
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
    candidate_fixture_root = fixture_path.parent.parent
    primary_receipt_roots = (
        raw_path.parent,
        candidate_fixture_root / "menu-profile-state-receipts",
    )
    profile_state = _validate_profile_state_v25(
        repo_root,
        evidence_root,
        header,
        str(fixture_path),
        receipt_search_roots=primary_receipt_roots,
        required_baseline_id=required_baseline_for_layout(
            repo_root, layout_id
        ),
        binding_label=f"layout '{layout_id}'",
    )
    raw_header = raw_trace.get("header")
    if not isinstance(raw_header, dict):
        raise PromotionError(f"{fixture_path} primary trace has no capture header")
    _validate_profile_state_v25(
        repo_root,
        evidence_root,
        raw_header,
        f"{fixture_path} primary trace",
        receipt_search_roots=primary_receipt_roots,
        required_baseline_id=profile_state["baseline_id"],
        binding_label=f"layout '{layout_id}' primary trace",
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
    confirmation_receipt_roots = (
        confirmation_path.parent,
        candidate_fixture_root / "menu-profile-state-receipts",
    )
    confirmation_header = confirmation_trace.get("header")
    if not isinstance(confirmation_header, dict):
        raise PromotionError(f"{fixture_path} confirmation has no capture header")
    confirmation_profile_state = _validate_profile_state_v25(
        repo_root,
        evidence_root,
        confirmation_header,
        f"{fixture_path} confirmation",
        receipt_search_roots=confirmation_receipt_roots,
        required_baseline_id=profile_state["baseline_id"],
        binding_label=f"layout '{layout_id}' confirmation",
    )
    if confirmation_profile_state["baseline_id"] != profile_state["baseline_id"]:
        raise PromotionError(
            f"{fixture_path} confirmation changed profile-state baseline"
        )
    if profile_state["baseline_id"] != FRESH_BASELINE_ID and {
        profile_state["witness_role"],
        confirmation_profile_state["witness_role"],
    } != {"primary", "confirmation"}:
        raise PromotionError(
            f"{fixture_path} derived confirmation did not use both pinned witness roles"
        )
    confirmation_source = _validate_source_v25(
        repo_root,
        confirmation_header.get("source"),
        f"{fixture_path} confirmation",
    )
    for field in (
        "base_commit_sha",
        "source_tree_sha",
        "game_executable_sha256",
        "loader_dll_sha256",
    ):
        if source[field] != confirmation_source[field]:
            raise PromotionError(
                f"{fixture_path} confirmation changed capture provenance field '{field}'"
            )
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
    try:
        paired_core_equality = derive_pair_core_equality(
            primary_samples,
            confirmation_samples,
            layout,
            label=str(fixture_path),
            bound_endpoints=[],
            bound_endpoint_census_complete=True,
        )
        generation_metadata = validate_instance_local_generation_pair(
            primary_samples,
            confirmation_samples,
            layout.get("generation"),
            paired_core_equality,
            label=str(fixture_path),
        )
    except NativeMenuGenerationV219Error as error:
        raise PromotionError(str(error)) from error
    hub_contract = load_hub_binding_contract(repo_root)["value"]
    if layout_id in hub_contract["layouts"]:
        contract_layout = hub_contract["layouts"][layout_id]
        expected_count = contract_layout["measured_settled_element_count"]
        fork = header.get("path_dependent_core")
        if (
            not isinstance(fork, dict)
            or fork.get("measured_settled_element_count") != expected_count
            or settlement.get("minimum_element_count") != expected_count
            or layout.get("peak_element_count", 0) < expected_count
        ):
            raise PromotionError(
                f"v2.12/v2.13 exact Hub layout '{layout_id}' changed its settled census"
            )
        try:
            validate_exact_hub_layout_pair(
                repo_root,
                layout_id=layout_id,
                primary_layout=primary_payload,
                confirmation_layout=confirmation_payload,
                baseline_id=profile_state["baseline_id"],
            )
        except NativeMenuProfileStateError as error:
            raise PromotionError(str(error)) from error
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
        "path_local_generation": generation_metadata,
    }


def validate_semantic_underlay_v215(
    repo_root: Path,
    evidence_root: Path,
    fixture_path: Path,
    fixture: dict[str, Any],
) -> dict[str, Any]:
    header = fixture.get("header")
    layout = fixture.get("layout")
    if (
        fixture.get("schema") != "solomon-dark-native-menu-layout-v2"
        or not isinstance(header, dict)
        or not isinstance(layout, dict)
        or header.get("recorded_live") is not True
        or layout.get("screen_id") != "dark_cloud_settings"
        or not isinstance(layout.get("elements"), list)
        or len(layout["elements"]) != 16
    ):
        raise PromotionError(
            "Settlement v2.15 semantic underlay is not the exact 16-member gate-agreeing layout"
        )
    source = _validate_source_v25(
        repo_root, header.get("source"), f"{fixture_path} semantic underlay"
    )
    settlement = header.get("settlement")
    if (
        not isinstance(settlement, dict)
        or settlement.get("settlement_spec") != "2.9"
        or settlement.get("consecutive_structural_samples", 0) < 40
        or settlement.get("stable_span_milliseconds", 0) < 2_000
        or settlement.get("element_count") != 16
    ):
        raise PromotionError(
            "Settlement v2.15 semantic underlay lacks its exact settled census"
        )

    def trace(
        receipt: Any, role: str
    ) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
        if not isinstance(receipt, dict):
            raise PromotionError(
                f"Settlement v2.15 semantic underlay has no {role} receipt"
            )
        path = _receipt_path_v25(
            evidence_root,
            fixture_path.parent,
            receipt,
            f"{fixture_path} semantic underlay {role}",
        )
        recording = read_json(path)
        recording_header = recording.get("header")
        if not isinstance(recording_header, dict):
            raise PromotionError(
                f"Settlement v2.15 semantic underlay {role} has no capture header"
            )
        _validate_source_v25(
            repo_root,
            recording_header.get("source"),
            f"{fixture_path} semantic underlay {role}",
        )
        _validate_profile_state_v25(
            repo_root,
            evidence_root,
            recording_header,
            f"{fixture_path} semantic underlay {role}",
            receipt_search_roots=(
                path.parent,
                fixture_path.parent.parent / "menu-profile-state-receipts",
            ),
            required_baseline_id=FRESH_BASELINE_ID,
            binding_label="v2.15 semantic underlay",
        )
        samples = _settled_samples_v25(
            recording, f"{fixture_path} semantic underlay {role}"
        )
        for sample in samples:
            payload = sample.get("payload") if isinstance(sample, dict) else None
            if (
                sample.get("semantic_surface") != "dark_cloud_settings"
                or not isinstance(payload, dict)
                or payload.get("screen_id") != "dark_cloud_settings"
                or not isinstance(payload.get("elements"), list)
                or len(payload["elements"]) != 16
            ):
                raise PromotionError(
                    "Settlement v2.15 semantic underlay trace lost capture-time tag agreement"
                )
        return path, recording_header, samples

    primary_path, primary_header, primary_samples = trace(
        header.get("raw_recording"), "primary"
    )
    confirmation_path, confirmation_header, confirmation_samples = trace(
        header.get("animation_confirmation"), "confirmation"
    )
    if (
        (primary_header.get("instance"), primary_header.get("process_id"))
        == (
            confirmation_header.get("instance"),
            confirmation_header.get("process_id"),
        )
        or primary_header.get("source") != confirmation_header.get("source")
        or source != primary_header.get("source")
    ):
        raise PromotionError(
            "Settlement v2.15 semantic underlay did not reproduce in two exact fresh instances"
        )
    try:
        primary_generation = measure_generation_window(
            primary_samples, f"{fixture_path} semantic underlay primary"
        )
        confirmation_generation = measure_generation_window(
            confirmation_samples,
            f"{fixture_path} semantic underlay confirmation",
        )
    except NativeMenuGenerationV218Error as error:
        raise PromotionError(str(error)) from error
    if layout.get("generation") != primary_generation["generation"]:
        raise PromotionError(
            "Settlement v2.19 recorded generation receipt chain: semantic "
            "underlay fixture does not carry its primary trace's measured value"
        )
    generation_metadata = {
        "settlement_spec": "2.19",
        "endpoint_type": "typed_non_layout_semantic_underlay",
        "recorded_generation": layout["generation"],
        "primary": primary_generation,
        "confirmation": confirmation_generation,
        "paired_generation_exclusion_invoked": False,
        "reason": (
            "Settlement v2.15 qualifies this as supporting underlay evidence, "
            "not one of the 30 layouts or 78 layout endpoints"
        ),
    }
    return {
        "fixture": fixture,
        "header": header,
        "layout": layout,
        "primary_samples": primary_samples,
        "confirmation_samples": confirmation_samples,
        "primary_trace_path": primary_path,
        "confirmation_trace_path": confirmation_path,
        "instance_local_generation": generation_metadata,
    }


def _resolved_navigation_inputs_v25(
    evidence_root: Path, navigation_path: Path, navigation: dict[str, Any]
) -> tuple[Path, Path, list[Path], Path | None, Path]:
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
    relative_motions = resolution.get("motion_observation_directories")
    if relative_motions is None:
        relative_motions = [resolution.get("motion_observation_directory")]
    if (
        not isinstance(relative_motions, list)
        or not relative_motions
        or not all(
            isinstance(relative, str) and relative
            for relative in relative_motions
        )
        or len(set(relative_motions)) != len(relative_motions)
    ):
        raise PromotionError(
            "ambient lifecycle resolution lost its unambiguous motion observation directories"
        )
    root = evidence_root.resolve()
    motion_roots = [(root / relative).resolve() for relative in relative_motions]
    if any(not motion_root.is_relative_to(root) for motion_root in motion_roots):
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
    return primary, confirmation, motion_roots, supplemental, asset_manifest


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


def _validate_overlay_evidence_receipts_v215(
    repo_root: Path,
    evidence_root: Path,
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    reached: list[tuple[str, dict[str, Any]]] = []

    def walk(value: Any, field: str) -> None:
        if isinstance(value, dict):
            if {"evidence_path", "sha256", "bytes"} <= set(value):
                reached.append((field, value))
            for key, child in value.items():
                walk(child, f"{field}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{field}[{index}]")

    walk(record, "overlay_record")
    required_witnesses = {
        "overlay_record.overlay.observations[0].recording",
        "overlay_record.overlay.observations[1].recording",
        "overlay_record.overlay.semantic_underlay_binding.primary_fixture",
        "overlay_record.overlay.supersession.retired_landed_screen_fixture",
        "overlay_record.overlay.supersession.stop_audit",
    }
    reached_fields = {field for field, _ in reached}
    if not required_witnesses <= reached_fields:
        raise PromotionError(
            "Settlement v2.15 overlay receipt sweep did not reach every named witness"
        )
    validated: list[dict[str, Any]] = []
    for field, receipt in reached:
        relative = receipt.get("evidence_path")
        if not isinstance(relative, str) or not relative:
            raise PromotionError(f"{field} has no exact evidence path")
        if relative.startswith("webgame-contracts/"):
            root = repo_root.resolve()
        else:
            root = evidence_root.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise PromotionError(f"{field} evidence is absent or escapes its root")
        if (
            path.stat().st_size != receipt.get("bytes")
            or file_sha256(path) != receipt.get("sha256")
        ):
            raise PromotionError(f"{field} evidence receipt is false")
        validated.append(
            {
                "field": field,
                "evidence_path": relative,
                "sha256": receipt["sha256"],
                "bytes": receipt["bytes"],
            }
        )
    return validated


def _settings_state_layout_v216(
    record: dict[str, Any], endpoint: dict[str, Any], edge_id: str, side: str
) -> tuple[str, dict[str, Any]]:
    endpoint_key = "before" if side == "before" else "after"
    expected_state = SETTINGS_ENDPOINT_BINDINGS.get((edge_id, endpoint_key))
    if expected_state is None:
        raise PromotionError(
            "multi-state path-dependent core contract: unbound Settings navigation endpoint"
        )
    contract = endpoint.get("path_dependent_core")
    states = record.get("fixture", {}).get("path_dependent_cores")
    state = states.get(expected_state) if isinstance(states, dict) else None
    layout = state.get("layout") if isinstance(state, dict) else None
    if (
        not isinstance(contract, dict)
        or not isinstance(state, dict)
        or not isinstance(layout, dict)
        or contract.get("settlement_spec") != "2.16"
        or contract.get("parent_layout_id") != "game-settings-gameplay"
        or contract.get("edge_id") != edge_id
        or contract.get("endpoint") != endpoint_key
        or contract.get("state_id") != expected_state
        or contract.get("measured_element_count")
        != state.get("measured_element_count")
        or contract.get("structural_core_sha256")
        != state.get("structural_core_sha256")
        or endpoint.get("element_count")
        != state.get("structural_core_element_count")
        or canonical_bytes(endpoint.get("layout")) != canonical_bytes(layout)
    ):
        raise PromotionError(
            "multi-state path-dependent core contract: bound endpoint presented a different Settings core"
        )
    return expected_state, layout


def _validate_pre_promotion_baselines(
    repo_root: Path, landed_layout_entries: list[dict[str, Any]]
) -> None:
    snapshot_root = repo_root / "webgame-contracts/baseline-snapshots"
    reached: set[str] = set()
    for entry in landed_layout_entries:
        fixture = entry.get("fixture") if isinstance(entry, dict) else None
        if not isinstance(fixture, str) or fixture in reached:
            raise PromotionError(
                "shellfix baseline verification reached an absent or ambiguous landed fixture"
            )
        reached.add(fixture)
        landed = repo_root / "tests/fixtures/webgame" / fixture
        snapshot = snapshot_root / fixture
        if (
            not landed.is_file()
            or not snapshot.is_file()
            or landed.read_bytes() != snapshot.read_bytes()
        ):
            raise PromotionError(
                f"shellfix baseline snapshot does not byte-equal pre-menufix {fixture}"
            )
    if len(reached) != 28 or "menu-layouts/dark-cloud-settings.json" not in reached:
        raise PromotionError(
            "shellfix baseline verification did not reach the exact historical 28-layout census"
        )


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


def _validate_navigation_generation_v219(
    resolved_navigation: dict[str, Any],
    confirmation_navigation: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Pin each instance's counter and prove each paired endpoint core exact."""

    def edge_map(
        recording: dict[str, Any], label: str
    ) -> dict[str, dict[str, Any]]:
        edges = recording.get("edges")
        if not isinstance(edges, list) or len(edges) != 40:
            raise PromotionError(
                f"{label} v2.19 generation sweep did not reach the exact 40-edge census"
            )
        result: dict[str, dict[str, Any]] = {}
        for edge in edges:
            edge_id = edge.get("id") if isinstance(edge, dict) else None
            if not isinstance(edge_id, str) or not edge_id or edge_id in result:
                raise PromotionError(
                    f"{label} v2.19 generation sweep found an absent or ambiguous edge"
                )
            result[edge_id] = edge
        if "control_scheme_picker_to_create" not in result:
            raise PromotionError(
                f"{label} v2.19 generation sweep missed the picker witness edge"
            )
        return result

    primary_by_id = edge_map(resolved_navigation, "primary resolved navigation")
    confirmation_by_id = edge_map(
        confirmation_navigation, "confirmation raw navigation"
    )
    if set(primary_by_id) != set(confirmation_by_id):
        raise PromotionError(
            "Settlement v2.19 paired navigation generation edge census differs"
        )
    result: dict[str, dict[str, Any]] = {}
    generation_mismatches: list[str] = []
    typed_nonlayout: list[str] = []
    expected_nonlayout = {
        "dark_cloud_settings_to_settings.before",
        "settings_to_dark_cloud_settings.after",
    }
    for edge_id in sorted(primary_by_id):
        for side in ("before", "after"):
            primary = primary_by_id[edge_id].get(side)
            confirmation = confirmation_by_id[edge_id].get(side)
            if not isinstance(primary, dict) or not isinstance(confirmation, dict):
                raise PromotionError(
                    f"Settlement v2.19 edge {edge_id} {side} endpoint is absent"
                )
            endpoint_id = f"{edge_id}.{side}"
            recorded_generation = primary.get("layout_generation")
            if recorded_generation is None:
                if endpoint_id not in expected_nonlayout:
                    raise PromotionError(
                        "Settlement v2.19 generation sweep found an unclassified "
                        f"non-layout endpoint: {endpoint_id}"
                    )
                typed_nonlayout.append(endpoint_id)
                continue
            primary_trace = primary.get("settlement_trace")
            confirmation_trace = confirmation.get("settlement_trace")
            if not isinstance(primary_trace, dict) or not isinstance(
                confirmation_trace, dict
            ):
                raise PromotionError(
                    f"Settlement v2.19 edge {edge_id} {side} trace is absent"
                )
            primary_samples = _settled_samples_v25(
                primary_trace, f"edge {edge_id} {side} primary"
            )
            confirmation_samples = _settled_samples_v25(
                confirmation_trace, f"edge {edge_id} {side} confirmation"
            )
            if (
                primary.get("semantic_generation") != recorded_generation
                or confirmation.get("semantic_generation")
                != confirmation.get("layout_generation")
            ):
                raise PromotionError(
                    "Settlement v2.19 endpoint generation is not its semantic mirror: "
                    f"edge {edge_id} {side}"
                )
            layout = primary.get("layout")
            if not isinstance(layout, dict):
                raise PromotionError(
                    f"Settlement v2.19 edge {edge_id} {side} has no resolved layout"
                )
            try:
                paired_core_equality = derive_pair_core_equality(
                    primary_samples,
                    confirmation_samples,
                    layout,
                    label=f"edge {edge_id} {side}",
                    bound_endpoints=[endpoint_id],
                    bound_endpoint_census_complete=True,
                )
                receipt = validate_instance_local_generation_pair(
                    primary_samples,
                    confirmation_samples,
                    recorded_generation,
                    paired_core_equality,
                    label=f"edge {edge_id} {side}",
                )
            except NativeMenuGenerationV219Error as error:
                raise PromotionError(str(error)) from error
            if receipt["primary"]["generation"] != receipt["confirmation"][
                "generation"
            ]:
                generation_mismatches.append(endpoint_id)
            receipt.update(
                {
                    "edge_id": edge_id,
                    "side": side,
                    "layout_id": primary.get("layout_id"),
                }
            )
            result[endpoint_id] = receipt
    if len(result) != 78 or set(typed_nonlayout) != expected_nonlayout:
        raise PromotionError(
            "Settlement v2.19 generation sweep did not validate 78 layout and two typed non-layout endpoints"
        )
    return result, {
        "layout_endpoint_count": len(result),
        "typed_nonlayout_endpoints": sorted(typed_nonlayout),
        "generation_mismatch_count": len(generation_mismatches),
        "generation_mismatch_endpoints": generation_mismatches,
        "all_layout_endpoint_cores_equal": True,
    }


def _bound_generation_endpoints_v219(
    layout_id: str,
    layout: dict[str, Any],
    resolved_navigation: dict[str, Any],
    navigation_generation_receipts: dict[str, dict[str, Any]],
    semantic_dialog_composite_record: dict[str, Any],
) -> list[dict[str, Any]]:
    """Enumerate every navigation binding for one generation-only correction."""

    edges = resolved_navigation.get("edges")
    if not isinstance(edges, list) or len(edges) != 40:
        raise PromotionError(
            "Settlement v2.19 bound-endpoint sweep did not reach the exact navigation census"
        )
    bound: list[dict[str, Any]] = []
    for edge in edges:
        edge_id = edge.get("id") if isinstance(edge, dict) else None
        if not isinstance(edge_id, str):
            raise PromotionError(
                "Settlement v2.19 bound-endpoint sweep reached an unresolvable edge"
            )
        for side in ("before", "after"):
            endpoint = edge.get(side)
            if not isinstance(endpoint, dict) or endpoint.get("layout_id") != layout_id:
                continue
            endpoint_layout = endpoint.get("layout")
            if not isinstance(endpoint_layout, dict):
                raise PromotionError(
                    f"Settlement v2.19 bound endpoint {edge_id} {side} has no layout"
                )
            comparison = compare_generation_cores_v218(
                layout,
                endpoint_layout,
                label=f"{edge_id}.{side}",
            )
            generation_receipt = navigation_generation_receipts.get(
                f"{edge_id}.{side}"
            )
            generation_recorded = isinstance(
                generation_receipt, dict
            ) and generation_receipt.get("instance_local_generation") is True
            comparison.update(
                {
                    "edge_id": edge_id,
                    "side": side,
                    "layout_id": layout_id,
                    "generation_is_instance_local": generation_recorded,
                    "exact": comparison["exact"] and generation_recorded,
                }
            )
            bound.append(comparison)

    if layout_id == "control-scheme-picker":
        composite = semantic_dialog_composite_record.get("composite", {})
        composite_binding = (
            composite.get("underlay_binding", {})
            if isinstance(composite, dict)
            else {}
        )
        navigation = semantic_dialog_composite_record.get("navigation", {})
        comparison = compare_generation_cores_v218(
            layout,
            layout,
            label="beta_notice_first_boot_to_control_scheme_picker.after",
        )
        fixture_receipt = composite_binding.get("fixture")
        exact_binding = (
            composite_binding.get("layout_id") == layout_id
            and navigation.get("dismissal_edge_id")
            == "beta_notice_first_boot_to_control_scheme_picker"
            and navigation.get("destination_layout_id") == layout_id
            and isinstance(fixture_receipt, dict)
        )
        comparison.update(
            {
                "edge_id": "beta_notice_first_boot_to_control_scheme_picker",
                "side": "after",
                "layout_id": layout_id,
                "generation_is_instance_local": exact_binding,
                "exact": comparison["exact"] and exact_binding,
                "binding_kind": "dialog_composite_dismissal",
            }
        )
        bound.append(comparison)

    if layout_id == "control-scheme-picker" and not any(
        endpoint.get("edge_id") == "control_scheme_picker_to_create"
        for endpoint in bound
    ):
        raise PromotionError(
            "Settlement v2.19 bound-endpoint sweep missed the picker-to-create witness"
        )
    return bound


def _assert_generation_v219_enabled(
    records: dict[str, dict[str, Any]],
    navigation_summary: dict[str, Any],
    *,
    enabled: bool,
) -> dict[str, Any]:
    if len(records) != 30 or "control-scheme-picker" not in records:
        raise PromotionError(
            "Settlement v2.19 generation census did not reach the exact 30-layout corpus"
        )
    standalone_mismatches = sorted(
        layout_id
        for layout_id, record in records.items()
        if record.get("path_local_generation", {}).get("primary", {}).get(
            "generation"
        )
        != record.get("path_local_generation", {}).get("confirmation", {}).get(
            "generation"
        )
    )
    summary = {
        "standalone_pair_count": len(records),
        "standalone_generation_mismatch_count": len(standalone_mismatches),
        "standalone_generation_mismatch_layouts": standalone_mismatches,
        **copy.deepcopy(navigation_summary),
    }
    if not enabled:
        if (
            len(standalone_mismatches) == 10
            and navigation_summary.get("layout_endpoint_count") == 76
            and navigation_summary.get("generation_mismatch_count") == 24
            and "dark_cloud_login_to_browser.before"
            in navigation_summary.get("generation_mismatch_endpoints", [])
        ):
            raise PromotionError(V218_DISABLED_CORPUS_STOP)
        raise PromotionError(
            "Settlement v2.19 disabled replay no longer reproduces the sealed v2.18 STOP census"
        )
    summary["v219_enabled"] = True
    summary["all_pair_cores_equal"] = True
    return summary


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
            if layout_id not in required_layouts:
                continue
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
            if canonical_bytes(primary_endpoint.get("layout")) != canonical_bytes(
                required_layouts[layout_id]
            ):
                continue
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
    *,
    diagnostic_allow_equivalent: bool = False,
    class_f_witness: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    def capacity_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
        signatures = {
            signature
            for counter in (
                *evidence["phase_counters"],
                *evidence["settled_counters"],
            )
            for signature in counter
        }
        rows: list[dict[str, Any]] = []
        for signature in sorted(signatures):
            settled_max = max(
                counter[signature]
                for counter in evidence["settled_counters"]
            )
            phase_max = max(
                counter[signature] for counter in evidence["phase_counters"]
            )
            excess = max(0, phase_max - settled_max)
            if excess:
                rows.append(
                    {
                        "semantic_payload": json.loads(
                            signature.decode("utf-8")
                        ),
                        "maximum_population_excess": excess,
                    }
                )
        return rows

    def classifier_capacity_sha256(
        primary_trace: dict[str, Any], confirmation_trace: dict[str, Any]
    ) -> str:
        primary = _population_evidence(
            primary_trace, f"{layout_id} diagnostic primary"
        )
        confirmation = _population_evidence(
            confirmation_trace, f"{layout_id} diagnostic confirmation"
        )
        return hashlib.sha256(
            canonical_bytes(
                {
                    "primary_population_capacity": capacity_rows(primary),
                    "confirmation_population_capacity": capacity_rows(
                        confirmation
                    ),
                    "landed_generation_witnessed_in_primary": (
                        landed_generation in primary["generation_trace"]
                    ),
                    "landed_generation_witnessed_in_confirmation": (
                        landed_generation in confirmation["generation_trace"]
                    ),
                }
            )
        ).hexdigest()

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
    if class_f_witness is not None:
        return (
            standalone_primary,
            standalone_confirmation,
            {
                "source": "census_era_class_f_paired_population_witness",
                "generation_witness_required": True,
                "generation_counter_selection_performed": False,
                "edge_id": class_f_witness["edge_id"],
                "projected_core_sha256": class_f_witness[
                    "projected_core_sha256"
                ],
                "projected_core_element_count": class_f_witness[
                    "projected_core_element_count"
                ],
                "witness_pair": copy.deepcopy(class_f_witness["pair"]),
            },
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
        if diagnostic_allow_equivalent:
            pair, detail = qualifying_navigation[0]
            return (
                pair["primary_trace"],
                pair["confirmation_trace"],
                {
                    "source": (
                        "diagnostic_all_qualifying_navigation_endpoints"
                    ),
                    "candidate_bindings": [
                        {
                            "edge_id": candidate["edge_id"],
                            "side": candidate["side"],
                            "population_classifier_capacity_sha256": (
                                classifier_capacity_sha256(
                                    candidate["primary_trace"],
                                    candidate["confirmation_trace"],
                                )
                            ),
                        }
                        for candidate, _ in qualifying_navigation
                    ],
                    "selection_performed": False,
                    "diagnosis_convergence_required": True,
                    "production_verdict": (
                        f"{layout_id} population-witness routing is "
                        f"ambiguous: {identities}"
                    ),
                    "generation_witness_required": True,
                    **detail,
                },
            )
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
    navigation_generation_receipts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if contract.get("schema") != (
        "solomon-dark-native-menu-controls-core-supersession-v211"
    ):
        raise PromotionError("v2.11 Controls structural contract schema is invalid")
    expected_candidate = contract.get("superseding_candidate_fixture")
    if not isinstance(expected_candidate, dict):
        raise PromotionError(
            "v2.11 exact Controls source candidate receipt is absent"
        )
    try:
        _, expected_settled_counter = _require_v211_controls_core_contract(
            contract
        )
    except LandedDiagnosisError as error:
        raise PromotionError(str(error)) from error
    if (
        _v211_semantic_counter(
            record.get("layout", {}), "v2.11 qualified Controls re-emission"
        )
        != expected_settled_counter
        or record.get("layout", {}).get("structural_core_sha256")
        != expected_candidate.get("structural_core_sha256")
    ):
        raise PromotionError(
            "v2.11 exact Controls qualified re-emission does not match the "
            "authorized semantic core"
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
    source_primary = paired.get("primary")
    source_confirmation = paired.get("confirmation")
    if (
        not isinstance(source_primary, dict)
        or not isinstance(source_confirmation, dict)
        or paired.get("classifier_and_tag_agree") is not True
        or (primary["instance"], primary["process_id"])
        == (confirmation["instance"], confirmation["process_id"])
    ):
        raise PromotionError(
            "v2.11 Controls qualified re-emission did not reproduce in two "
            "classifier-agreed instances"
        )
    pair_core = record.get("path_local_generation", {}).get(
        "paired_core_equality", {}
    )
    if (
        pair_core.get("core_equal") is not True
        or pair_core.get("zero_residual") is not True
    ):
        raise PromotionError(
            "v2.11 Controls qualified re-emission lacks exact paired-core proof"
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
    if set(observed) != set(expected_by_identity):
        raise PromotionError(
            "v2.11 Controls endpoints do not reproduce both exact standalone bindings"
        )
    for identity, value in observed.items():
        endpoint_id = f"{identity[0]}.{identity[1]}"
        generation_receipt = navigation_generation_receipts.get(endpoint_id)
        if (
            value.get("semantic_surface") != "controls"
            or value.get("tagged_screen") != "controls"
            or isinstance(value.get("layout_generation"), bool)
            or not isinstance(value.get("layout_generation"), int)
            or value.get("element_count") != len(record["layout"]["elements"])
            or not isinstance(value.get("frame_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["frame_sha256"])
            or not isinstance(generation_receipt, dict)
            or generation_receipt.get("primary", {}).get("generation")
            != value.get("layout_generation")
            or generation_receipt.get("paired_core_equality", {}).get(
                "core_equal"
            )
            is not True
            or generation_receipt.get("paired_core_equality", {}).get(
                "zero_residual"
            )
            is not True
        ):
            raise PromotionError(
                f"v2.11 Controls endpoint {identity} changed its qualified "
                "standalone binding or lost its v2.19 exact-core receipt"
            )
    return {
        "source_candidate_receipt": {
            "sha256": expected_candidate.get("sha256"),
            "bytes": expected_candidate.get("bytes"),
        },
        "qualified_candidate_receipt": file_receipt(candidate_path),
        "qualified_reemission": file_receipt(candidate_path)
        != {
            "sha256": expected_candidate.get("sha256"),
            "bytes": expected_candidate.get("bytes"),
        },
        "source_paired_settlement": {
            "primary": copy.deepcopy(source_primary),
            "confirmation": copy.deepcopy(source_confirmation),
        },
        "paired_settlement": {"primary": primary, "confirmation": confirmation},
        "endpoint_count": len(observed),
        "destination_equals_standalone": True,
    }


def _validate_dark_cloud_login_title_context_v220(
    repo_root: Path,
    contract: dict[str, Any],
    record: dict[str, Any],
    candidate_path: Path,
    evidence_root: Path,
    resolved_navigation: dict[str, Any],
    navigation_generation_receipts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    try:
        _require_v220_dark_cloud_login_title_contract(contract)
    except LandedDiagnosisError as error:
        raise PromotionError(str(error)) from error

    def repo_receipt(field: str) -> Path:
        receipt = contract.get(field)
        if not isinstance(receipt, dict) or set(receipt) != {
            "repo_relative_path",
            "sha256",
            "bytes",
        }:
            raise PromotionError(
                f"v2.20 Dark Cloud login title {field.replace('_', ' ')} receipt is malformed"
            )
        relative = Path(str(receipt["repo_relative_path"]))
        root = repo_root.resolve()
        path = (root / relative).resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not path.is_relative_to(root)
            or not path.is_file()
            or file_receipt(path)
            != {"sha256": receipt.get("sha256"), "bytes": receipt.get("bytes")}
        ):
            raise PromotionError(
                f"v2.20 Dark Cloud login title {field.replace('_', ' ')} receipt is false"
            )
        return path

    landed_path = repo_receipt("landed_fixture")
    baseline_path = repo_receipt("baseline_snapshot")
    if landed_path.read_bytes() != baseline_path.read_bytes():
        raise PromotionError(
            "v2.20 Dark Cloud login title baseline no longer preserves the exact landed bytes"
        )

    expected_candidate = contract.get("superseding_candidate")
    if (
        not isinstance(expected_candidate, dict)
        or _receipt_path_v25(
            evidence_root,
            candidate_path.parent,
            expected_candidate,
            "v2.20 Dark Cloud login title candidate",
        ).resolve()
        != candidate_path.resolve()
        or expected_candidate.get("element_count")
        != len(record.get("layout", {}).get("elements", []))
        or expected_candidate.get("structural_core_sha256")
        != record.get("layout", {}).get("structural_core_sha256")
    ):
        raise PromotionError(
            "v2.20 Dark Cloud login title candidate receipt does not bind the exact settled core"
        )

    audit_path = _receipt_path_v25(
        evidence_root,
        candidate_path.parent,
        contract.get("source_stop_audit", {}),
        "v2.20 Dark Cloud login title source STOP audit",
    )
    promoter_stop_path = _receipt_path_v25(
        evidence_root,
        candidate_path.parent,
        contract.get("source_promoter_stop", {}),
        "v2.20 Dark Cloud login title source promoter STOP",
    )
    audit = read_json(audit_path)
    expected_stop = contract["source_promoter_stop"].get("message")
    if (
        audit.get("schema")
        != "solomon-dark-native-menu-dark-cloud-login-title-stop-audit-v1"
        or audit.get("status") != "QUESTION"
        or audit.get("layout_id") != contract["layout_id"]
        or audit.get("screen_id") != contract["screen_id"]
        or audit.get("landed_screen_title") != contract["landed_value"]
        or audit.get("settled_screen_title") != contract["settled_value"]
        or audit.get("candidate_applied") is not False
        or read_json(promoter_stop_path)
        != {"success": False, "error": expected_stop}
    ):
        raise PromotionError(
            "v2.20 Dark Cloud login title accepted STOP finding no longer reproduces"
        )

    header = record.get("header")
    if not isinstance(header, dict):
        raise PromotionError("v2.20 Dark Cloud login title candidate has no header")
    profile_identity = contract.get("profile_state_identity_sha256")
    if (
        header.get("source") != contract.get("source_provenance")
        or header.get("source", {}).get("profile_state_identity_sha256")
        != profile_identity
        or header.get("profile_state", {}).get(
            "profile_state_identity_sha256"
        )
        != profile_identity
    ):
        raise PromotionError(
            "v2.20 Dark Cloud login title candidate lost its pinned machine-derived provenance"
        )

    paired = contract.get("paired_settlement")
    if not isinstance(paired, dict):
        raise PromotionError(
            "v2.20 Dark Cloud login title paired-settlement receipt is absent"
        )
    roles = (
        (
            "primary",
            record.get("primary_trace_path"),
            record.get("primary_trace"),
            record.get("primary_samples"),
        ),
        (
            "confirmation",
            record.get("confirmation_trace_path"),
            record.get("confirmation_trace"),
            record.get("confirmation_samples"),
        ),
    )
    identities: list[tuple[Any, Any]] = []
    for role, observed_path, trace, samples in roles:
        expected = paired.get(role)
        if (
            not isinstance(expected, dict)
            or not isinstance(observed_path, Path)
            or _receipt_path_v25(
                evidence_root,
                candidate_path.parent,
                expected.get("recording", {}),
                f"v2.20 Dark Cloud login title {role} trace",
            ).resolve()
            != observed_path.resolve()
            or not isinstance(trace, dict)
            or not isinstance(samples, list)
            or len(samples) != expected.get("sample_count")
            or len(samples) < 40
        ):
            raise PromotionError(
                f"v2.20 Dark Cloud login title {role} trace receipt is incomplete"
            )
        trace_header = trace.get("header")
        if not isinstance(trace_header, dict):
            raise PromotionError(
                f"v2.20 Dark Cloud login title {role} trace has no capture header"
            )
        elapsed = [sample.get("elapsed_milliseconds") for sample in samples]
        payloads = [sample.get("payload") for sample in samples]
        if (
            trace_header.get("instance") != expected.get("instance")
            or trace_header.get("process_id") != expected.get("process_id")
            or trace_header.get("source") != contract.get("source_provenance")
            or not all(isinstance(value, (int, float)) for value in elapsed)
            or elapsed[-1] - elapsed[0]
            != expected.get("stable_span_milliseconds")
            or not all(isinstance(payload, dict) for payload in payloads)
            or {payload.get("screen_id") for payload in payloads}
            != {contract["screen_id"]}
            or {payload.get("screen_title") for payload in payloads}
            != {contract["settled_value"]}
            or {payload.get("generation") for payload in payloads}
            != {expected.get("measured_generation")}
        ):
            raise PromotionError(
                f"v2.20 Dark Cloud login title {role} trace does not reproduce the pinned title window"
            )
        identities.append((trace_header.get("instance"), trace_header.get("process_id")))
    if len(set(identities)) != 2:
        raise PromotionError(
            "v2.20 Dark Cloud login title evidence does not use two independent instances"
        )
    pair_core = record.get("path_local_generation", {}).get(
        "paired_core_equality", {}
    )
    expected_core = paired.get("core_equality", {}).get("expected_core")
    if (
        not isinstance(expected_core, dict)
        or pair_core.get("core_equal") is not True
        or pair_core.get("zero_residual") is not True
        or pair_core.get("expected_core") != expected_core
    ):
        raise PromotionError(
            "v2.20 Dark Cloud login title pair lost exact cross-instance core equality"
        )

    expected_endpoints = contract.get("bound_endpoints")
    expected_by_identity = {
        (entry.get("edge_id"), entry.get("side"), entry.get("trigger")): entry
        for entry in expected_endpoints
        if isinstance(entry, dict)
    }
    if len(expected_by_identity) != 2:
        raise PromotionError(
            "v2.20 Dark Cloud login title endpoint contract is absent or ambiguous"
        )
    observed: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    edges = resolved_navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise PromotionError(
            "v2.20 Dark Cloud login title endpoint audit reached no navigation edges"
        )
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for side in ("before", "after"):
            endpoint = edge.get(side)
            if (
                not isinstance(endpoint, dict)
                or endpoint.get("layout_id") != contract["layout_id"]
            ):
                continue
            identity = (edge.get("id"), side, edge.get("trigger"))
            if identity in observed:
                raise PromotionError(
                    "v2.20 Dark Cloud login title endpoint lookup is ambiguous"
                )
            layout = endpoint.get("layout")
            if canonical_bytes(layout) != canonical_bytes(record["layout"]):
                raise PromotionError(
                    f"v2.20 Dark Cloud login title endpoint {identity} does not equal its standalone"
                )
            observed[identity] = {
                "edge_id": identity[0],
                "side": side,
                "trigger": identity[2],
                "semantic_surface": endpoint.get("semantic_surface"),
                "tagged_screen": endpoint.get("tagged_screen"),
                "layout_generation": endpoint.get("layout_generation"),
                "element_count": endpoint.get("element_count"),
                "screen_title": layout.get("screen_title"),
                "structural_core_sha256": layout.get("structural_core_sha256"),
                "frame_sha256": endpoint.get("frame_sha256"),
            }
    if set(observed) != set(expected_by_identity):
        raise PromotionError(
            "v2.20 Dark Cloud login title did not reproduce both exact endpoint bindings"
        )
    for identity, endpoint in observed.items():
        endpoint_id = f"{identity[0]}.{identity[1]}"
        generation_receipt = navigation_generation_receipts.get(endpoint_id)
        if (
            endpoint != expected_by_identity[identity]
            or not isinstance(generation_receipt, dict)
            or generation_receipt.get("paired_core_equality", {}).get(
                "core_equal"
            )
            is not True
            or generation_receipt.get("paired_core_equality", {}).get(
                "zero_residual"
            )
            is not True
        ):
            raise PromotionError(
                f"v2.20 Dark Cloud login title endpoint {identity} lost its exact-core receipt"
            )
    return {
        "contract": file_receipt(
            repo_root
            / "tests/fixtures/webgame/native-menu-dark-cloud-login-title-v220.json"
        ),
        "candidate": file_receipt(candidate_path),
        "source_stop_audit": file_receipt(audit_path),
        "source_promoter_stop": file_receipt(promoter_stop_path),
        "paired_instances": [list(identity) for identity in identities],
        "endpoint_count": len(observed),
        "destination_equals_standalone": True,
    }


def _validate_census_era_context_v221(
    repo_root: Path,
    evidence_root: Path,
    contract_path: Path,
    contract: dict[str, Any],
    records: dict[str, dict[str, Any]],
    path_by_layout_id: dict[str, Path],
    landed_path_by_layout_id: dict[str, Path],
) -> dict[str, Any]:
    try:
        view = require_census_era_contract(contract)
    except CensusEraV221Error as error:
        raise PromotionError(str(error)) from error

    def evidence_path(recorded: dict[str, Any], label: str) -> Path:
        relative = recorded.get("evidence_path")
        if not isinstance(relative, str) or not relative:
            raise PromotionError(f"v2.21 {label} has no evidence path")
        path = (evidence_root / relative).resolve()
        root = evidence_root.resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise PromotionError(f"v2.21 {label} escapes or is absent")
        if file_receipt(path) != {
            "sha256": recorded.get("sha256"),
            "bytes": recorded.get("bytes"),
        }:
            raise PromotionError(f"v2.21 {label} receipt is false")
        return path

    source_census = evidence_path(contract["source_census"], "source census")
    occurrence_audit = evidence_path(
        contract["occurrence_audit"], "qualified-occurrence audit"
    )
    class_f_audit_path = evidence_path(
        contract["class_f_witnesses"]["source_audit"],
        "bounded Class-F witness audit",
    )
    class_f_audit = read_json(class_f_audit_path)
    class_f_layouts = class_f_audit.get("layouts")
    if (
        class_f_audit.get("schema")
        != "solomon-dark-native-menu-census-era-class-f-audit-v221"
        or not isinstance(class_f_layouts, dict)
        or set(class_f_layouts) != set(view["class_f"])
    ):
        raise PromotionError("v2.21 bounded Class-F audit changed scope")
    reached: set[str] = set()
    for class_name in ("class_a", "class_b"):
        for layout_id, entry in view[class_name].items():
            record = records.get(layout_id)
            candidate_path = path_by_layout_id.get(layout_id)
            landed_path = landed_path_by_layout_id.get(layout_id)
            if (
                not isinstance(record, dict)
                or not isinstance(candidate_path, Path)
                or not isinstance(landed_path, Path)
                or file_receipt(landed_path)
                != {
                    "sha256": entry["landed_fixture"]["sha256"],
                    "bytes": entry["landed_fixture"]["bytes"],
                }
                or file_receipt(candidate_path)
                != {
                    "sha256": entry["candidate_fixture"]["sha256"],
                    "bytes": entry["candidate_fixture"]["bytes"],
                }
                or file_receipt(record["primary_trace_path"])
                != {
                    "sha256": entry["primary_trace"]["sha256"],
                    "bytes": entry["primary_trace"]["bytes"],
                }
                or file_receipt(record["confirmation_trace_path"])
                != {
                    "sha256": entry["confirmation_trace"]["sha256"],
                    "bytes": entry["confirmation_trace"]["bytes"],
                }
                or record["header"].get("profile_state", {}).get(
                    "profile_state_identity_sha256"
                )
                != entry["profile_state_identity_sha256"]
            ):
                raise PromotionError(
                    f"v2.21 {class_name} receipt chain differs for {layout_id}"
                )
            reached.add(layout_id)
    if reached != set(view["class_a"]) | set(view["class_b"]):
        raise PromotionError("v2.21 receipt sweep reached no complete layout census")

    for correction in contract["field_corrections"]:
        layout_id = correction["layout_id"]
        if (
            file_receipt(landed_path_by_layout_id[layout_id])
            != {
                "sha256": correction["landed_fixture"]["sha256"],
                "bytes": correction["landed_fixture"]["bytes"],
            }
            or file_receipt(path_by_layout_id[layout_id])
            != {
                "sha256": correction["candidate_fixture"]["sha256"],
                "bytes": correction["candidate_fixture"]["bytes"],
            }
        ):
            raise PromotionError(
                f"v2.21 field correction receipt differs for {layout_id}"
            )
    class_f_receipt_fields = (
        "navigation_recording",
        "launch",
        "launch_profile_state",
        "stage_report",
        "pre_navigation_durable_census",
        "post_capture_durable_census",
        "exact_pid_disposal",
        "host_quiescence_after",
    )
    for layout_id, entry in view["class_f"].items():
        candidate_path = path_by_layout_id.get(layout_id)
        audit_entry = class_f_layouts.get(layout_id)
        if (
            not isinstance(candidate_path, Path)
            or not isinstance(audit_entry, dict)
            or file_receipt(candidate_path)
            != {
                "sha256": entry["qualified_candidate"]["sha256"],
                "bytes": entry["qualified_candidate"]["bytes"],
            }
            or audit_entry.get("status")
            != "class_f_population_witness_satisfied"
            or audit_entry.get("projected_core_sha256")
            != entry["projected_core_sha256"]
            or audit_entry.get("projected_core_element_count")
            != entry["projected_core_element_count"]
        ):
            raise PromotionError(
                f"v2.21 bounded Class-F candidate/core differs for {layout_id}"
            )
        audit_pair = audit_entry.get("pair")
        if not isinstance(audit_pair, list) or len(audit_pair) != 2:
            raise PromotionError(
                f"v2.21 bounded Class-F pair is absent for {layout_id}"
            )
        contract_pair_projection = [
            {
                key: copy.deepcopy(row[key])
                for key in (
                    "instance",
                    "process_id",
                    "measured_generation",
                    "settled_sample_count",
                    "settled_span_milliseconds",
                    "projected_core_sha256",
                    *class_f_receipt_fields,
                )
            }
            for row in audit_pair
        ]
        if canonical_bytes(contract_pair_projection) != canonical_bytes(entry["pair"]):
            raise PromotionError(
                f"v2.21 bounded Class-F audit/contract pair differs for {layout_id}"
            )
        for role_index, observation in enumerate(entry["pair"]):
            for field in class_f_receipt_fields:
                evidence_path(
                    observation[field],
                    f"Class-F {layout_id} role {role_index} {field}",
                )
    return {
        "contract": {
            "repo_relative_path": contract_path.relative_to(repo_root).as_posix(),
            **file_receipt(contract_path),
        },
        "source_census": file_receipt(source_census),
        "occurrence_audit": file_receipt(occurrence_audit),
        "class_f_witness_audit": file_receipt(class_f_audit_path),
        "class_a_layout_count": len(view["class_a"]),
        "class_b_layout_count": len(view["class_b"]),
        "choice_slot_row_count": 2,
        "field_correction_count": len(view["field_corrections"]),
        "class_f_witness_count": len(view["class_f"]),
    }


def _validate_final_disposition_context_v222(
    repo_root: Path,
    evidence_root: Path,
    contract_path: Path,
    contract: dict[str, Any],
    census_era_contract: dict[str, Any],
    records: dict[str, dict[str, Any]],
    path_by_layout_id: dict[str, Path],
    landed_path_by_layout_id: dict[str, Path],
    resolved_navigation: dict[str, Any],
    navigation_path: Path,
) -> dict[str, Any]:
    try:
        view = require_final_disposition_v222_contract(contract)
        census_view = require_census_era_contract(census_era_contract)
    except (FinalDispositionV222Error, CensusEraV221Error) as error:
        raise PromotionError(str(error)) from error

    def evidence_path(recorded: dict[str, Any], label: str) -> Path:
        relative = recorded.get("evidence_path")
        if not isinstance(relative, str) or not relative:
            raise PromotionError(f"v2.22 {label} has no evidence path")
        path = (evidence_root / relative).resolve()
        if (
            not path.is_relative_to(evidence_root.resolve())
            or not path.is_file()
            or file_receipt(path)
            != {
                "sha256": recorded.get("sha256"),
                "bytes": recorded.get("bytes"),
            }
        ):
            raise PromotionError(f"v2.22 {label} receipt is false")
        return path

    source_census = evidence_path(contract["source_census"], "source census")
    recorded_navigation = evidence_path(
        contract["resolved_navigation"], "resolved navigation"
    )
    if recorded_navigation != navigation_path.resolve():
        raise PromotionError("v2.22 promotion is using another navigation graph")

    def without_class_b(
        layout_id: str, elements: list[dict[str, Any]], label: str
    ) -> list[dict[str, Any]]:
        class_b = census_view["class_b"].get(layout_id)
        if class_b is None:
            raise PromotionError(f"v2.22 {label} has no exact Class-B basis")
        remaining = Counter(
            member["semantic_sha256"] for member in class_b["members"]
        )
        result: list[dict[str, Any]] = []
        for element in elements:
            signature = semantic_sha256_v221(element)
            if remaining[signature] > 0:
                remaining[signature] -= 1
            else:
                result.append(element)
        if any(remaining.values()):
            raise PromotionError(f"v2.22 {label} omitted a Class-B member")
        return result

    sequence_occurrence_count = 0
    for layout_id, entry in view["sequences"].items():
        record = records.get(layout_id)
        candidate_path = path_by_layout_id.get(layout_id)
        landed_path = landed_path_by_layout_id.get(layout_id)
        baseline_path = (
            repo_root
            / f"webgame-contracts/baseline-snapshots/menu-layouts/{layout_id}.json"
        )
        if (
            not isinstance(record, dict)
            or not isinstance(candidate_path, Path)
            or not isinstance(landed_path, Path)
            or file_receipt(landed_path)
            != {
                "sha256": entry["landed_fixture"]["sha256"],
                "bytes": entry["landed_fixture"]["bytes"],
            }
            or file_receipt(baseline_path)
            != {
                "sha256": entry["landed_baseline_snapshot"]["sha256"],
                "bytes": entry["landed_baseline_snapshot"]["bytes"],
            }
            or file_receipt(candidate_path)
            != {
                "sha256": entry["candidate_fixture"]["sha256"],
                "bytes": entry["candidate_fixture"]["bytes"],
            }
            or file_receipt(record["primary_trace_path"])
            != {
                "sha256": entry["primary_trace"]["sha256"],
                "bytes": entry["primary_trace"]["bytes"],
            }
            or file_receipt(record["confirmation_trace_path"])
            != {
                "sha256": entry["confirmation_trace"]["sha256"],
                "bytes": entry["confirmation_trace"]["bytes"],
            }
            or record["header"].get("profile_state", {}).get(
                "profile_state_identity_sha256"
            )
            != entry["profile_state_identity_sha256"]
        ):
            raise PromotionError(f"v2.22 sequence receipt chain differs for {layout_id}")
        candidate_elements = record["layout"].get("elements")
        if not isinstance(candidate_elements, list) or not candidate_elements:
            raise PromotionError(f"v2.22 sequence candidate is empty for {layout_id}")
        standalone_sha = sequence_sha256_v222(
            without_class_b(layout_id, candidate_elements, f"{layout_id} standalone")
        )
        transition_occurrences = [
            occurrence
            for occurrence in entry["occurrences"]
            if occurrence.get("scope") == "transition_source"
        ]
        if len(transition_occurrences) != 1:
            raise PromotionError(
                f"v2.22 transition occurrence is absent or ambiguous for {layout_id}"
            )
        occurrence = transition_occurrences[0]
        edge_matches = [
            edge
            for edge in resolved_navigation.get("edges", [])
            if isinstance(edge, dict) and edge.get("id") == occurrence.get("edge_id")
        ]
        if len(edge_matches) != 1:
            raise PromotionError(f"v2.22 sequence edge lookup is ambiguous for {layout_id}")
        endpoint = edge_matches[0].get(occurrence.get("side"))
        endpoint_layout = endpoint.get("layout") if isinstance(endpoint, dict) else None
        endpoint_elements = (
            endpoint_layout.get("elements")
            if isinstance(endpoint_layout, dict)
            else None
        )
        if (
            not isinstance(endpoint, dict)
            or endpoint.get("layout_id") != layout_id
            or not isinstance(endpoint_elements, list)
            or sequence_sha256_v222(
                without_class_b(
                    layout_id,
                    endpoint_elements,
                    f"{occurrence.get('edge_id')}.{occurrence.get('side')}",
                )
            )
            != entry["settled_sequence_sha256"]
            or standalone_sha != entry["settled_sequence_sha256"]
        ):
            raise PromotionError(
                f"v2.22 every qualified occurrence does not reproduce {layout_id}"
            )
        sequence_occurrence_count += 2

    for layout_id, entry in view["endpoint_vacuity"].items():
        record = records.get(layout_id)
        candidate_path = path_by_layout_id.get(layout_id)
        if (
            not isinstance(record, dict)
            or not isinstance(candidate_path, Path)
            or file_receipt(candidate_path)
            != {
                "sha256": entry["candidate_fixture"]["sha256"],
                "bytes": entry["candidate_fixture"]["bytes"],
            }
            or file_receipt(record["primary_trace_path"])
            != {
                "sha256": entry["primary_trace"]["sha256"],
                "bytes": entry["primary_trace"]["bytes"],
            }
            or file_receipt(record["confirmation_trace_path"])
            != {
                "sha256": entry["confirmation_trace"]["sha256"],
                "bytes": entry["confirmation_trace"]["bytes"],
            }
            or record["layout"].get("structural_core_sha256")
            != entry["structural_core_sha256"]
            or record["header"].get("profile_state", {}).get(
                "profile_state_identity_sha256"
            )
            != entry["profile_state_identity_sha256"]
        ):
            raise PromotionError(f"v2.22 vacuity receipt/core differs for {layout_id}")
        try:
            authorize_named_endpoint_vacuity(
                layout_id,
                resolved_navigation,
                contract,
                record["layout"]["structural_core_sha256"],
            )
        except FinalDispositionV222Error as error:
            raise PromotionError(str(error)) from error

    return {
        "contract": {
            "repo_relative_path": contract_path.relative_to(repo_root).as_posix(),
            **file_receipt(contract_path),
        },
        "source_census": file_receipt(source_census),
        "resolved_navigation": file_receipt(recorded_navigation),
        "sequence_supersession_count": len(view["sequences"]),
        "sequence_reproduction_occurrence_count": sequence_occurrence_count,
        "named_endpoint_vacuity_count": len(view["endpoint_vacuity"]),
        "promotion_time_graph_rechecked": True,
    }


def _fixture_receipt_v217(path: Path, fixture: str) -> dict[str, Any]:
    return {"fixture": fixture, **file_receipt(path)}


def validate_semantic_dialog_composite_v217(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    composite_path: Path,
    record: dict[str, Any],
    picker_record: dict[str, Any],
    beta_record: dict[str, Any],
    overlay_reference: dict[str, Any],
) -> dict[str, Any]:
    try:
        classification = validate_composite_record(
            record,
            picker_record["layout"],
            overlay_reference,
            beta_record["layout"],
        )
    except NativeMenuSemanticDialogCompositeError as error:
        raise PromotionError(str(error)) from error
    header = record.get("header")
    composite = record.get("composite")
    observations = composite.get("observations") if isinstance(composite, dict) else None
    if not isinstance(header, dict) or not isinstance(observations, list):
        raise PromotionError("semantic dialog composite record has no evidence header")
    for label in ("question_audit", "question_manifest"):
        receipt = header.get(label)
        if not isinstance(receipt, dict):
            raise PromotionError(
                f"semantic dialog composite has no {label.replace('_', ' ')} receipt"
            )
        _receipt_path_v25(
            evidence_root,
            composite_path.parent,
            receipt,
            f"semantic dialog composite {label}",
        )
    reference_path = candidate_root / "menu-reference-captures/beta-notice-first-boot.png"
    if header.get("reference_capture") != _fixture_receipt_v217(
        reference_path, "menu-reference-captures/beta-notice-first-boot.png"
    ):
        raise PromotionError(
            "semantic dialog composite reference capture receipt is false"
        )
    for observation in observations:
        role = observation.get("role") if isinstance(observation, dict) else None
        if role not in {"primary", "confirmation"}:
            raise PromotionError(
                "semantic dialog composite evidence role is absent or ambiguous"
            )
        recording_path = _receipt_path_v25(
            evidence_root,
            composite_path.parent,
            observation["recording"],
            f"semantic dialog composite {role} recording",
        )
        for field in (
            "observation",
            "dismissal_receipt",
            "player_visible_dialog_frame",
            "post_dismissal_underlay_frame",
        ):
            _receipt_path_v25(
                evidence_root,
                composite_path.parent,
                observation[field],
                f"semantic dialog composite {role} {field}",
            )
        _validate_source_v25(
            repo_root,
            observation.get("source"),
            f"semantic dialog composite {role}",
        )
        _validate_profile_state_v25(
            repo_root,
            evidence_root,
            {
                "source": observation.get("source"),
                "profile_state": observation.get("profile_state"),
            },
            f"semantic dialog composite {role}",
            receipt_search_roots=(recording_path.parent,),
            required_baseline_id=FRESH_BASELINE_ID,
            binding_label=f"semantic dialog composite {role}",
        )
    bindings = {
        "underlay_binding": (
            candidate_root / "menu-layouts/control-scheme-picker.json",
            "menu-layouts/control-scheme-picker.json",
        ),
        "derived_overlay_reference": (
            candidate_root / "menu-overlay-reference.json",
            "menu-overlay-reference.json",
        ),
        "qualified_beta_screen": (
            candidate_root / "menu-layouts/beta-notice.json",
            "menu-layouts/beta-notice.json",
        ),
    }
    for field, (path, fixture) in bindings.items():
        binding = composite.get(field)
        if (
            not isinstance(binding, dict)
            or binding.get("fixture") != _fixture_receipt_v217(path, fixture)
        ):
            raise PromotionError(
                f"semantic dialog composite {field.replace('_', ' ')} receipt is false"
            )
    return {
        "classification": classification,
        "record": file_receipt(composite_path),
        "reference_capture": file_receipt(reference_path),
        "validated_evidence_receipt_count": 2 + len(observations) * 5,
    }


def validate_and_promote(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    navigation_path: Path,
    dry_run: bool,
    *,
    generation_v219_enabled: bool = True,
    enumerate_all_unclassified: bool = False,
) -> dict[str, Any]:
    if enumerate_all_unclassified and not dry_run:
        raise PromotionError(
            "enumerate-all landed-difference diagnostics require --dry-run"
        )
    landed_root = repo_root / "tests/fixtures/webgame"
    landed_golden = read_json(landed_root / "menu-goldens.json")
    beta_supersession_contract = read_json(
        landed_root / "native-menu-beta-notice-supersession-v217.json"
    )
    beta_paint_order_contract = read_json(
        landed_root / "native-menu-beta-notice-paint-order-v217.json"
    )
    controls_title_contract = read_json(
        landed_root / "native-menu-controls-title-v210.json"
    )
    dark_cloud_login_title_contract = read_json(
        landed_root / "native-menu-dark-cloud-login-title-v220.json"
    )
    controls_core_contract = read_json(
        landed_root / "native-menu-controls-core-v211.json"
    )
    item_row_supersession_contract = read_json(
        landed_root / "native-menu-dark-cloud-item-row-supersession-v219.json"
    )
    browser_chrome_supersession_contract = read_json(
        landed_root
        / "native-menu-dark-cloud-browser-chrome-supersession-v219.json"
    )
    census_era_contract_path = (
        landed_root / "native-menu-census-era-disposition-v221.json"
    )
    census_era_contract = read_json(census_era_contract_path)
    try:
        census_era_view = require_census_era_contract(census_era_contract)
    except CensusEraV221Error as error:
        raise PromotionError(str(error)) from error
    final_disposition_contract_path = (
        landed_root / "native-menu-final-disposition-v222.json"
    )
    final_disposition_contract = read_json(final_disposition_contract_path)
    try:
        require_final_disposition_v222_contract(final_disposition_contract)
    except FinalDispositionV222Error as error:
        raise PromotionError(str(error)) from error
    resolved_navigation = read_json(navigation_path)
    (
        primary_navigation,
        confirmation_navigation,
        motion_roots,
        supplemental_manifest,
        asset_manifest,
    ) = _resolved_navigation_inputs_v25(
        evidence_root, navigation_path, resolved_navigation
    )
    primary_recording = read_json(primary_navigation)
    confirmation_recording = read_json(confirmation_navigation)
    _validate_navigation_profile_state_v25(
        repo_root,
        evidence_root,
        primary_recording,
        "primary navigation",
        _navigation_profile_receipt_roots_v25(
            evidence_root,
            primary_navigation,
            primary_recording,
            "primary navigation",
        ),
    )
    (
        navigation_generation_receipts,
        navigation_generation_summary,
    ) = _validate_navigation_generation_v219(
        resolved_navigation,
        confirmation_recording,
    )
    _validate_navigation_profile_state_v25(
        repo_root,
        evidence_root,
        confirmation_recording,
        "confirmation navigation",
        _navigation_profile_receipt_roots_v25(
            evidence_root,
            confirmation_navigation,
            confirmation_recording,
            "confirmation navigation",
        ),
    )
    try:
        resolve_campaign(
            repo_root,
            candidate_root,
            evidence_root,
            primary_navigation,
            confirmation_navigation,
            motion_roots[0],
            navigation_path,
            evidence_root / "ambient-resolution-verification-unused.json",
            False,
            True,
            supplemental_manifest,
            asset_manifest,
            motion_roots[1:],
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
    if "dark-cloud-settings.json" not in layout_names:
        raise PromotionError(
            "Settlement v2.15 supersession lost the exact retired Dark Cloud Settings fixture"
        )
    _validate_pre_promotion_baselines(repo_root, landed_layout_entries)
    candidate_layout_names = layout_names - {"dark-cloud-settings.json"}
    candidate_layout_paths = require_unique_files(
        candidate_root / "menu-layouts", "*.json", candidate_layout_names
    )
    candidate_transition_paths = require_unique_files(
        candidate_root / "menu-transition-layouts",
        "*.json",
        {
            "hub_new_game.json",
            "hub_pristine_second_new_game.json",
            "hub_resumed.json",
        },
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
    if len(records) != 30 or not {
        "hub_new_game",
        "hub_pristine_second_new_game",
        "hub_resumed",
    } <= set(records):
        raise PromotionError(
            "candidate standalone sweep did not reach 27 menus plus three Hub layouts"
        )
    generation_v219_census = _assert_generation_v219_enabled(
        records,
        navigation_generation_summary,
        enabled=generation_v219_enabled,
    )

    overlay_paths = require_unique_files(
        candidate_root / "menu-overlays", "*.json", {"dark-cloud-settings.json"}
    )
    underlay_paths = require_unique_files(
        candidate_root / "menu-overlay-underlays",
        "*.json",
        {"dark-cloud-settings.json"},
    )
    composite_paths = require_unique_files(
        candidate_root / "menu-dialog-composites",
        "*.json",
        {"beta-notice-first-boot.json"},
    )
    overlay_path = overlay_paths["dark-cloud-settings.json"]
    underlay_path = underlay_paths["dark-cloud-settings.json"]
    overlay_record = read_json(overlay_path)
    try:
        overlay_classification = validate_overlay_record(overlay_record)
    except NativeMenuNonSemanticOverlayError as error:
        raise PromotionError(str(error)) from error
    overlay_evidence_receipts = _validate_overlay_evidence_receipts_v215(
        repo_root, evidence_root, overlay_record
    )
    underlay_record = validate_semantic_underlay_v215(
        repo_root, evidence_root, underlay_path, read_json(underlay_path)
    )
    underlay_receipt = overlay_record["overlay"]["semantic_underlay_binding"][
        "primary_fixture"
    ]
    if (
        underlay_record["layout"].get("screen_id") != "dark_cloud_settings"
        or underlay_receipt.get("sha256") != file_sha256(underlay_path)
        or underlay_receipt.get("bytes") != underlay_path.stat().st_size
    ):
        raise PromotionError(
            "Settlement v2.15 semantic underlay does not reproduce its exact gate-agreeing fixture"
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
    census_era_context = _validate_census_era_context_v221(
        repo_root,
        evidence_root,
        census_era_contract_path,
        census_era_contract,
        records,
        path_by_layout_id,
        landed_path_by_layout_id,
    )
    final_disposition_context = _validate_final_disposition_context_v222(
        repo_root,
        evidence_root,
        final_disposition_contract_path,
        final_disposition_contract,
        census_era_contract,
        records,
        path_by_layout_id,
        landed_path_by_layout_id,
        resolved_navigation,
        navigation_path,
    )
    dark_cloud_login_title_context = (
        _validate_dark_cloud_login_title_context_v220(
            repo_root,
            dark_cloud_login_title_contract,
            records["dark-cloud-login-settings"],
            path_by_layout_id["dark-cloud-login-settings"],
            evidence_root,
            resolved_navigation,
            navigation_generation_receipts,
        )
    )
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
    composite_path = composite_paths["beta-notice-first-boot.json"]
    composite_record = read_json(composite_path)
    semantic_dialog_composite = validate_semantic_dialog_composite_v217(
        repo_root,
        candidate_root,
        evidence_root,
        composite_path,
        composite_record,
        records["control-scheme-picker"],
        records["beta-notice"],
        derived_overlay_reference,
    )
    path_local_generation_contracts = {
        layout_id: {
            "enabled": True,
            "paired_generation": copy.deepcopy(
                records[layout_id]["path_local_generation"]
            ),
            "bound_endpoints": _bound_generation_endpoints_v219(
                layout_id,
                records[layout_id]["layout"],
                resolved_navigation,
                navigation_generation_receipts,
                composite_record,
            ),
        }
        for layout_id in sorted(generation_changed_layout_ids)
    }

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

    unclassified_by_key: dict[bytes, dict[str, Any]] = {}
    unclassified_stop_messages: list[str] = []

    def evidence_receipt(path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        root = evidence_root.resolve()
        if not resolved.is_relative_to(root):
            raise PromotionError(
                f"landed-difference census evidence escapes its root: {path}"
            )
        return {
            "evidence_path": resolved.relative_to(root).as_posix(),
            **file_receipt(resolved),
        }

    def bound_endpoint_labels(layout_id: str) -> list[str]:
        labels: list[str] = []
        edges = resolved_navigation.get("edges")
        if not isinstance(edges, list) or not edges:
            raise PromotionError(
                "landed-difference census reached no navigation endpoints"
            )
        for edge in edges:
            if not isinstance(edge, dict) or not isinstance(edge.get("id"), str):
                raise PromotionError(
                    "landed-difference census found an ambiguous navigation edge"
                )
            for side in ("before", "after"):
                endpoint = edge.get(side)
                if isinstance(endpoint, dict) and endpoint.get("layout_id") == layout_id:
                    labels.append(f"{edge['id']}.{side}")
        if len(labels) != len(set(labels)):
            raise PromotionError(
                f"landed-difference census endpoint lookup is ambiguous for {layout_id}"
            )
        return sorted(labels)

    def record_unclassified(
        layout_id: str,
        differences: list[dict[str, Any]],
        *,
        occurrence: dict[str, Any],
        stop_message: str,
    ) -> None:
        if not differences:
            raise PromotionError(
                f"enumerate-all diagnostic could not resolve the claim behind: {stop_message}"
            )
        record = records[layout_id]
        receipts = {
            "landed_fixture": {
                "repo_relative_path": landed_path_by_layout_id[
                    layout_id
                ].relative_to(repo_root).as_posix(),
                **file_receipt(landed_path_by_layout_id[layout_id]),
            },
            "candidate_fixture": evidence_receipt(path_by_layout_id[layout_id]),
            "primary_trace": evidence_receipt(record["primary_trace_path"]),
            "confirmation_trace": evidence_receipt(
                record["confirmation_trace_path"]
            ),
            "profile_state_identity_sha256": record["header"]
            .get("profile_state", {})
            .get("profile_state_identity_sha256"),
            "structural_core_sha256": record["layout"].get(
                "structural_core_sha256"
            ),
            "bound_endpoints": bound_endpoint_labels(layout_id),
        }
        unclassified_stop_messages.append(stop_message)
        for difference in differences:
            key = canonical_bytes(
                {"layout_id": layout_id, "difference": difference}
            )
            entry = unclassified_by_key.get(key)
            if entry is None:
                entry = {
                    "layout_id": layout_id,
                    "difference": copy.deepcopy(difference),
                    "receipts": receipts,
                    "occurrences": [],
                }
                unclassified_by_key[key] = entry
            if occurrence not in entry["occurrences"]:
                entry["occurrences"].append(copy.deepcopy(occurrence))

    def diagnose_record(
        layout_id: str,
        primary_trace: dict[str, Any],
        confirmation_trace: dict[str, Any],
    ) -> dict[str, Any]:
        return diagnose_landed_layout(
            layout_id,
            landed_by_layout_id[layout_id],
            records[layout_id]["layout"],
            primary_trace,
            confirmation_trace,
            derived_overlay_reference,
            controls_title_contract=controls_title_contract,
            dark_cloud_login_title_contract=(
                dark_cloud_login_title_contract
            ),
            controls_core_contract=controls_core_contract,
            landed_fixture_receipt=file_receipt(
                landed_path_by_layout_id[layout_id]
            ),
            candidate_fixture_receipt=file_receipt(path_by_layout_id[layout_id]),
            path_local_generation_contract=path_local_generation_contracts.get(
                layout_id
            ),
            item_row_supersession_contract=item_row_supersession_contract,
            browser_chrome_supersession_contract=(
                browser_chrome_supersession_contract
            ),
            census_era_contract=census_era_contract,
            final_disposition_contract=final_disposition_contract,
            generation_navigation=resolved_navigation,
        )

    def enumerate_record(
        layout_id: str,
        primary_trace: dict[str, Any],
        confirmation_trace: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return enumerate_unclassified_landed_differences(
            layout_id,
            landed_by_layout_id[layout_id],
            records[layout_id]["layout"],
            primary_trace,
            confirmation_trace,
            derived_overlay_reference,
            controls_title_contract=controls_title_contract,
            dark_cloud_login_title_contract=(
                dark_cloud_login_title_contract
            ),
            controls_core_contract=controls_core_contract,
            landed_fixture_receipt=file_receipt(
                landed_path_by_layout_id[layout_id]
            ),
            candidate_fixture_receipt=file_receipt(path_by_layout_id[layout_id]),
            path_local_generation_contract=path_local_generation_contracts.get(
                layout_id
            ),
            item_row_supersession_contract=item_row_supersession_contract,
            browser_chrome_supersession_contract=(
                browser_chrome_supersession_contract
            ),
            census_era_contract=census_era_contract,
            final_disposition_contract=final_disposition_contract,
            generation_navigation=resolved_navigation,
        )

    standalone_diagnoses: dict[str, dict[str, Any]] = {}
    for layout_id in sorted(records):
        if layout_id not in landed_by_layout_id:
            fork = records[layout_id]["header"].get("path_dependent_core")
            if layout_id not in {
                "hub_new_game",
                "hub_pristine_second_new_game",
                "hub_resumed",
            } or not isinstance(
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
        if layout_id == "beta-notice":
            try:
                validate_qualified_beta_paint_order(
                    records[layout_id]["layout"], beta_paint_order_contract
                )
                standalone_diagnoses[layout_id] = (
                    validate_qualified_beta_supersession(
                        beta_supersession_contract,
                        landed_fixture_receipt=_fixture_receipt_v217(
                            landed_path_by_layout_id[layout_id],
                            "menu-layouts/beta-notice.json",
                        ),
                        candidate_fixture_receipt=_fixture_receipt_v217(
                            path_by_layout_id[layout_id],
                            "menu-layouts/beta-notice.json",
                        ),
                        candidate_fixture=records[layout_id]["fixture"],
                    )
                )
            except NativeMenuSemanticDialogCompositeError as error:
                raise PromotionError(f"STOP: standalone beta-notice: {error}") from error
            standalone_diagnoses[layout_id]["paint_order_contract"] = copy.deepcopy(
                beta_paint_order_contract
            )
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
            diagnostic_allow_equivalent=(
                enumerate_all_unclassified or layout_id == "pause-menu"
            ),
            class_f_witness=census_era_view["class_f"].get(layout_id),
        )
        if (
            population_trace_selection.get("source")
            == "diagnostic_all_qualifying_navigation_endpoints"
        ):
            candidate_outcomes: list[dict[str, Any]] = []
            first_diagnosis: dict[str, Any] | None = None
            common_differences: list[dict[str, Any]] | None = None
            outcome_keys: set[bytes] = set()
            for binding in population_trace_selection["candidate_bindings"]:
                matches = [
                    pair
                    for pair in navigation_population_pairs.get(layout_id, [])
                    if pair["edge_id"] == binding["edge_id"]
                    and pair["side"] == binding["side"]
                ]
                if len(matches) != 1:
                    raise PromotionError(
                        f"{layout_id} diagnostic population binding is absent or ambiguous"
                    )
                pair = matches[0]
                try:
                    diagnosis = diagnose_record(
                        layout_id,
                        pair["primary_trace"],
                        pair["confirmation_trace"],
                    )
                    differences: list[dict[str, Any]] = []
                    if first_diagnosis is None:
                        first_diagnosis = diagnosis
                except LandedDiagnosisError:
                    differences = enumerate_record(
                        layout_id,
                        pair["primary_trace"],
                        pair["confirmation_trace"],
                    )
                key = canonical_bytes(differences)
                outcome_keys.add(key)
                if common_differences is None:
                    common_differences = differences
                candidate_outcomes.append(
                    {
                        **copy.deepcopy(binding),
                        "unclassified_difference_count": len(differences),
                        "unclassified_differences_sha256": hashlib.sha256(
                            key
                        ).hexdigest(),
                    }
                )
            population_trace_selection["candidate_outcomes"] = candidate_outcomes
            population_trace_selection["diagnosis_converged"] = (
                len(outcome_keys) == 1
            )
            if len(outcome_keys) != 1:
                if not enumerate_all_unclassified:
                    raise PromotionError(
                        f"STOP: standalone {layout_id}: "
                        "v2.21 pause-menu population-witness equivalence did not converge exactly"
                    )
                differences = [
                    {
                        "difference_type": "diagnostic_blocker",
                        "field": "population_witness_routing",
                        "message": population_trace_selection[
                            "production_verdict"
                        ],
                        "candidate_outcomes": candidate_outcomes,
                    }
                ]
                record_unclassified(
                    layout_id,
                    differences,
                    occurrence={"scope": "standalone", "layout_id": layout_id},
                    stop_message=population_trace_selection["production_verdict"],
                )
                standalone_diagnoses[layout_id] = {
                    "status": "diagnostic_unclassified",
                    "original_stop": population_trace_selection[
                        "production_verdict"
                    ],
                    "unclassified_difference_count": 1,
                    "population_trace_selection": population_trace_selection,
                }
                continue
            if common_differences:
                stop_message = population_trace_selection["production_verdict"]
                if not enumerate_all_unclassified:
                    raise PromotionError(f"STOP: standalone {layout_id}: {stop_message}")
                record_unclassified(
                    layout_id,
                    common_differences,
                    occurrence={"scope": "standalone", "layout_id": layout_id},
                    stop_message=stop_message,
                )
                standalone_diagnoses[layout_id] = {
                    "status": "diagnostic_unclassified",
                    "original_stop": stop_message,
                    "unclassified_difference_count": len(common_differences),
                    "population_trace_selection": population_trace_selection,
                }
                continue
            if first_diagnosis is None:
                raise PromotionError(
                    f"{layout_id} diagnostic population outcomes reached no diagnosis"
                )
            if layout_id == "pause-menu":
                try:
                    population_trace_selection["proven_equivalence"] = (
                        validate_pause_equivalence(
                            census_era_contract, candidate_outcomes
                        )
                    )
                except CensusEraV221Error as error:
                    raise PromotionError(str(error)) from error
            standalone_diagnoses[layout_id] = first_diagnosis
            standalone_diagnoses[layout_id][
                "population_trace_selection"
            ] = population_trace_selection
            continue
        try:
            standalone_diagnoses[layout_id] = diagnose_record(
                layout_id,
                population_primary_trace,
                population_confirmation_trace,
            )
            standalone_diagnoses[layout_id][
                "population_trace_selection"
            ] = population_trace_selection
        except LandedDiagnosisError as error:
            stop_message = f"STOP: standalone {layout_id}: {error}"
            if not enumerate_all_unclassified:
                raise PromotionError(stop_message) from error
            differences = enumerate_record(
                layout_id,
                population_primary_trace,
                population_confirmation_trace,
            )
            record_unclassified(
                layout_id,
                differences,
                occurrence={"scope": "standalone", "layout_id": layout_id},
                stop_message=stop_message,
            )
            standalone_diagnoses[layout_id] = {
                "status": "diagnostic_unclassified",
                "original_stop": stop_message,
                "unclassified_difference_count": len(differences),
                "population_trace_selection": population_trace_selection,
            }

    standalone_diagnoses["dark-cloud-settings"] = {
        "status": "corrected_to_nonsemantic_overlay",
        "settlement_spec": "2.15",
        "retired_fixture": file_receipt(
            landed_path_by_layout_id["dark-cloud-settings"]
        ),
        "overlay_record": file_receipt(overlay_path),
        "semantic_underlay": file_receipt(underlay_path),
        "classification": copy.deepcopy(overlay_classification),
        "stop_audit": copy.deepcopy(
            overlay_record["overlay"]["supersession"]["stop_audit"]
        ),
    }

    controls_core_context = _validate_controls_context_v211(
        controls_core_contract,
        records["controls"],
        path_by_layout_id["controls"],
        evidence_root,
        resolved_navigation,
        navigation_generation_receipts,
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
        "menu-transition-layouts/hub_pristine_second_new_game.json",
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
    embedded_overlays = _aggregate_wrapper_map(
        candidate_golden.get("overlay_records"),
        {"menu-overlays/dark-cloud-settings.json"},
        "candidate embedded overlay records",
    )
    embedded_composites = _aggregate_wrapper_map(
        candidate_golden.get("semantic_dialog_composite_records"),
        {"menu-dialog-composites/beta-notice-first-boot.json"},
        "candidate embedded semantic-dialog composite records",
    )
    for fixture_name, wrapper in {**embedded, **embedded_transition}.items():
        layout_id = Path(fixture_name).stem
        fixture = records[layout_id]["fixture"]
        embedded_fixture = {
            "schema": fixture["schema"],
            "header": wrapper.get("header"),
            "layout": wrapper.get("layout"),
        }
        if "path_dependent_cores" in fixture:
            embedded_fixture["path_dependent_cores"] = wrapper.get(
                "path_dependent_cores"
            )
        if fixture != embedded_fixture:
            raise PromotionError(
                f"candidate embedded golden and standalone {fixture_name} disagree"
            )
    embedded_overlay = embedded_overlays[
        "menu-overlays/dark-cloud-settings.json"
    ]
    expected_embedded_overlay = {
        "fixture": "menu-overlays/dark-cloud-settings.json",
        "underlay_fixture": "menu-overlay-underlays/dark-cloud-settings.json",
        "overlay_id": overlay_record["overlay_id"],
        "settlement_spec": overlay_record["settlement_spec"],
        "record": overlay_record,
        "sha256": file_sha256(overlay_path),
        "bytes": overlay_path.stat().st_size,
        "underlay_sha256": file_sha256(underlay_path),
        "underlay_bytes": underlay_path.stat().st_size,
    }
    if canonical_bytes(embedded_overlay) != canonical_bytes(
        expected_embedded_overlay
    ):
        raise PromotionError(
            "candidate embedded overlay and standalone overlay record disagree"
        )
    embedded_composite = embedded_composites[
        "menu-dialog-composites/beta-notice-first-boot.json"
    ]
    composite_reference_path = (
        candidate_root / "menu-reference-captures/beta-notice-first-boot.png"
    )
    expected_embedded_composite = {
        "fixture": "menu-dialog-composites/beta-notice-first-boot.json",
        "composite_id": COMPOSITE_ID,
        "settlement_spec": "2.17",
        "record": composite_record,
        "sha256": file_sha256(composite_path),
        "bytes": composite_path.stat().st_size,
        "reference_capture": (
            "menu-reference-captures/beta-notice-first-boot.png"
        ),
        "reference_sha256": file_sha256(composite_reference_path),
    }
    if canonical_bytes(embedded_composite) != canonical_bytes(
        expected_embedded_composite
    ):
        raise PromotionError(
            "candidate embedded semantic-dialog composite disagrees with its standalone record"
        )
    header_counts = candidate_golden.get("header", {})
    if (
        header_counts.get("screen_count") != 30
        or header_counts.get("standalone_layout_count") != 27
        or header_counts.get("path_dependent_layout_count") != 3
        or header_counts.get("layout_count") != 30
        or header_counts.get("overlay_count") != 1
        or header_counts.get("semantic_dialog_composite_count") != 1
        or header_counts.get("state_count") != 32
        or header_counts.get("edge_count") != 41
        or candidate_golden.get("screen_census") != sorted(records)
        or candidate_golden.get("overlay_census")
        != ["dark_cloud_settings_credentials"]
        or candidate_golden.get("semantic_dialog_composite_census")
        != [COMPOSITE_ID]
    ):
        raise PromotionError(
            "candidate aggregate does not pin the exact 30-layout, one-overlay, "
            "one-dialog-composite, 32-state/41-edge census"
        )
    try:
        dark_cloud_menu_reference_context = validate_dark_cloud_menu_references(
            candidate_golden, resolved_navigation
        )
    except CensusEraV221Error as error:
        raise PromotionError(str(error)) from error

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
        profile_bindings = load_hub_binding_contract(repo_root)
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
    expected_profile_binding_receipt = {
        "fixture": "native-menu-hub-bindings-v213.json",
        "sha256": profile_bindings["sha256"],
        "bytes": profile_bindings["bytes"],
        "baseline_ids": sorted(profile_bindings["baselines"]),
        "corrective": (
            "Settlement v2.13 qualifies every layout and edge by an exact "
            "legitimate baseline"
        ),
    }
    if canonical_bytes(
        candidate_golden.get("header", {}).get("profile_state_bindings")
    ) != canonical_bytes(expected_profile_binding_receipt):
        raise PromotionError(
            "candidate aggregate records a false per-binding profile-state contract receipt"
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
    underlay_reference = underlay_record["header"].get("reference_capture")
    if (
        underlay_reference != "../menu-reference-captures/dark-cloud-settings.png"
        or "dark-cloud-settings.png" in reference_names
    ):
        raise PromotionError(
            "Settlement v2.15 semantic underlay visual reference is absent or ambiguous"
        )
    underlay_reference_path = (
        underlay_path.parent / underlay_reference
    ).resolve()
    expected_reference_root = (
        candidate_root / "menu-reference-captures"
    ).resolve()
    if (
        not underlay_reference_path.is_relative_to(expected_reference_root)
        or not underlay_reference_path.is_file()
    ):
        raise PromotionError(
            "Settlement v2.15 semantic underlay visual reference escapes its candidate root"
        )
    reference_names.add(underlay_reference_path.name)
    if composite_reference_path.name in reference_names:
        raise PromotionError(
            "semantic dialog composite visual reference is ambiguous"
        )
    reference_names.add(composite_reference_path.name)
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
    all_candidate_by_id = {
        edge.get("id"): edge for edge in candidate_edges if isinstance(edge, dict)
    }
    composite_edge_id = "beta_notice_first_boot_to_control_scheme_picker"
    chartered_edge_identity = {
        "id": "profile_select_new_game_to_create",
        "source": "profile_save_select",
        "trigger": "new_game_click",
        "action_id": "main_menu.new_game",
        "destination": "create_element",
    }
    chartered_edge_id = chartered_edge_identity["id"]
    composite_edge = all_candidate_by_id.get(composite_edge_id)
    candidate_by_id = {
        edge_id: edge
        for edge_id, edge in all_candidate_by_id.items()
        if edge_id != composite_edge_id
    }
    resolved_by_id = {
        edge.get("id"): edge for edge in resolved_edges if isinstance(edge, dict)
    }
    expected_native_edge_ids = set(old_by_id) | {chartered_edge_id}
    if (
        len(old_by_id) != len(landed_edges)
        or len(all_candidate_by_id) != len(candidate_edges)
        or chartered_edge_id in old_by_id
        or len(candidate_edges) != len(landed_edges) + 2
        or len(resolved_by_id) != len(resolved_edges)
        or set(candidate_by_id) != expected_native_edge_ids
        or set(resolved_by_id) != expected_native_edge_ids
    ):
        raise PromotionError("candidate navigation edge census is absent, duplicate, or changed")
    resolved_chartered_edge = resolved_by_id[chartered_edge_id]
    if any(
        resolved_chartered_edge.get(field) != expected
        for field, expected in chartered_edge_identity.items()
    ):
        raise PromotionError(
            "chartered profile-save-select New Game resolved edge changed its measured identity"
        )
    aggregate_chartered_edge = candidate_by_id[chartered_edge_id]
    aggregate_chartered_identity = {
        "id": chartered_edge_id,
        "screen": chartered_edge_identity["source"],
        "edge": chartered_edge_identity["trigger"],
        "trigger": chartered_edge_identity["trigger"],
        "action_id": chartered_edge_identity["action_id"],
        "destination": chartered_edge_identity["destination"],
        "destination_type": "layout",
        "destination_layout_fixture": "menu-layouts/create-element.json",
    }
    if any(
        aggregate_chartered_edge.get(field) != expected
        for field, expected in aggregate_chartered_identity.items()
    ):
        raise PromotionError(
            "chartered profile-save-select New Game aggregate edge changed its measured identity"
        )
    source_audit: list[dict[str, Any]] = []
    destination_audit: list[dict[str, Any]] = []
    if not isinstance(composite_edge, dict):
        raise PromotionError(
            "semantic dialog composite dismissal edge is absent or ambiguous"
        )
    composite_before = composite_edge.get("before")
    composite_after = composite_edge.get("after")
    if (
        composite_edge.get("action_id") != "dialog.primary"
        or composite_edge.get("destination_type") != "layout"
        or composite_edge.get("destination_layout_fixture")
        != "menu-layouts/control-scheme-picker.json"
        or not isinstance(composite_before, dict)
        or composite_before.get("type") != "dialog_composite"
        or composite_before.get("composite_id") != COMPOSITE_ID
        or composite_before.get("composite_fixture")
        != {
            "fixture": "menu-dialog-composites/beta-notice-first-boot.json",
            "sha256": file_sha256(composite_path),
            "bytes": composite_path.stat().st_size,
        }
        or not isinstance(composite_after, dict)
        or composite_after.get("layout_id") != "control-scheme-picker"
        or canonical_bytes(composite_after.get("layout"))
        != canonical_bytes(records["control-scheme-picker"]["layout"])
        or composite_after.get("frame_sha256")
        != semantic_dialog_composite["classification"][
            "post_dismissal_underlay_frame_sha256"
        ]
    ):
        raise PromotionError(
            "semantic dialog composite dismissal edge changed its measured binding"
        )
    source_audit.append(
        {
            "edge": composite_edge_id,
            "layout_id": COMPOSITE_ID,
            "diagnosis": {
                "status": "v2.17_semantic_dialog_composite",
                "record": file_receipt(composite_path),
            },
            "signature_bit_match": None,
            "frame_bit_match": True,
        }
    )
    destination_audit.append(
        {
            "edge": composite_edge_id,
            "destination_type": "layout",
            "standalone_fixture": "menu-layouts/control-scheme-picker.json",
            "path_dependent_state_id": None,
            "structural_core_sha256": records["control-scheme-picker"][
                "layout"
            ]["structural_core_sha256"],
            "classification_map_sha256": ambient_sha256_json(
                records["control-scheme-picker"]["layout"]["classification_map"]
            ),
            "settle_latency_milliseconds": composite_after["settlement"][
                "settle_latency_milliseconds"
            ],
            "old_generation": None,
            "new_generation": composite_after.get("layout_generation"),
            "old_element_count": None,
            "new_element_count": composite_after.get("element_count"),
        }
    )
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
        old_edge = old_by_id.get(edge_id)
        endpoint_kinds: dict[str, str] = {}
        endpoint_layouts: dict[str, dict[str, Any]] = {}
        endpoint_state_ids: dict[str, str | None] = {}
        for side in ("before", "after"):
            endpoint = edge.get(side)
            raw_endpoint = raw_edge.get(side)
            if not isinstance(endpoint, dict) or not isinstance(raw_endpoint, dict):
                raise PromotionError(f"edge {edge_id} {side} is incomplete")
            if raw_endpoint.get("type") == "overlay":
                expected_overlay_receipt = {
                    "candidate_relative_path": "menu-overlays/dark-cloud-settings.json",
                    "evidence_path": overlay_record["overlay"][
                        "semantic_underlay_binding"
                    ]["primary_fixture"]["evidence_path"].replace(
                        "menu-overlay-underlays", "menu-overlays"
                    ),
                    "sha256": file_sha256(overlay_path),
                    "bytes": overlay_path.stat().st_size,
                }
                observed_underlay_receipt = raw_endpoint.get(
                    "underlying_surface", {}
                ).get("fixture")
                if (
                    not isinstance(observed_underlay_receipt, dict)
                    or raw_endpoint.get("overlay_id")
                    != "dark_cloud_settings_credentials"
                    or raw_endpoint.get("members_semantically_observable") is not False
                    or raw_endpoint.get("semantic_member_count") != 0
                    or raw_endpoint.get("semantic_members") != []
                    or raw_endpoint.get("overlay_fixture") != expected_overlay_receipt
                    or observed_underlay_receipt.get("sha256")
                    != file_sha256(underlay_path)
                    or observed_underlay_receipt.get("bytes")
                    != underlay_path.stat().st_size
                    or canonical_bytes(endpoint) != canonical_bytes(raw_endpoint)
                ):
                    raise PromotionError(
                        f"Settlement v2.15 overlay endpoint {edge_id} {side} changed its exact record"
                    )
                endpoint_kinds[side] = "overlay"
                endpoint_state_ids[side] = None
                continue
            layout_id = raw_endpoint.get("layout_id")
            if not isinstance(layout_id, str) or layout_id not in records:
                raise PromotionError(f"edge {edge_id} {side} has no unique standalone layout")
            expected_layout = records[layout_id]["layout"]
            state_id: str | None = None
            if layout_id == "game-settings-gameplay":
                state_id, expected_layout = _settings_state_layout_v216(
                    records[layout_id], raw_endpoint, edge_id, side
                )
                aggregate_state_id, aggregate_layout = _settings_state_layout_v216(
                    records[layout_id], endpoint, edge_id, side
                )
                if state_id != aggregate_state_id or canonical_bytes(
                    aggregate_layout
                ) != canonical_bytes(expected_layout):
                    raise PromotionError(
                        f"aggregate edge {edge_id} {side} changed its v2.16 Settings binding"
                    )
            elif canonical_bytes(raw_endpoint.get("layout")) != canonical_bytes(
                expected_layout
            ):
                raise PromotionError(
                    f"resolved edge {edge_id} {side} does not equal standalone {layout_id}"
                )
            if canonical_bytes(endpoint.get("layout")) != canonical_bytes(
                expected_layout
            ):
                raise PromotionError(
                    f"aggregate edge {edge_id} {side} does not equal its bound layout {layout_id}"
                )
            if endpoint.get("layout_id") != layout_id:
                raise PromotionError(f"aggregate edge {edge_id} {side} changed layout identity")
            try:
                assert_overlay_hygiene_v25(expected_layout, derived_overlay_reference)
            except OverlayV25Error as error:
                raise PromotionError(f"edge {edge_id} {side}: {error}") from error
            endpoint_kinds[side] = "layout"
            endpoint_layouts[side] = expected_layout
            endpoint_state_ids[side] = state_id

        if endpoint_kinds["after"] == "overlay":
            destination_fixture = "menu-overlays/dark-cloud-settings.json"
            if (
                edge.get("destination_type") != "overlay"
                or edge.get("destination_layout_fixture") != destination_fixture
                or "destination_layout_state_id" in edge
            ):
                raise PromotionError(
                    f"edge {edge_id} overlay destination changed its typed fixture binding"
                )
            destination_audit.append(
                {
                    "edge": edge_id,
                    "destination_type": "overlay",
                    "standalone_fixture": destination_fixture,
                    "overlay_sha256": file_sha256(overlay_path),
                    "underlay_sha256": file_sha256(underlay_path),
                    "settle_latency_milliseconds": None,
                    "typed_overlay_settlement": copy.deepcopy(
                        edge["after"]["settlement"]
                    ),
                    "old_generation": (
                        old_edge["after"].get("layout_generation")
                        if old_edge is not None
                        else None
                    ),
                    "new_generation": None,
                    "old_element_count": (
                        old_edge["after"].get("element_count")
                        if old_edge is not None
                        else None
                    ),
                    "new_element_count": 0,
                }
            )
        else:
            destination_layout_id = raw_edge["after"]["layout_id"]
            destination_fixture = fixture_for_layout_id[destination_layout_id]
            destination_state_id = endpoint_state_ids["after"]
            expected_destination_type = "layout"
            if edge.get("destination_type") != expected_destination_type:
                raise PromotionError(
                    f"edge {edge_id} destination changed its layout type"
                )
            if destination_state_id is None:
                if "destination_layout_state_id" in edge:
                    raise PromotionError(
                        f"edge {edge_id} gained an unmeasured path-state binding"
                    )
            elif edge.get("destination_layout_state_id") != destination_state_id:
                raise PromotionError(
                    f"edge {edge_id} destination changed its exact v2.16 state binding"
                )
            if edge.get("destination_layout_fixture") != destination_fixture:
                raise PromotionError(
                    f"edge {edge_id} destination fixture does not derive from its bound layout"
                )
            destination_layout = endpoint_layouts["after"]
            destination_audit.append(
                {
                    "edge": edge_id,
                    "destination_type": "layout",
                    "standalone_fixture": destination_fixture,
                    "path_dependent_state_id": destination_state_id,
                    "structural_core_sha256": destination_layout[
                        "structural_core_sha256"
                    ],
                    "classification_map_sha256": ambient_sha256_json(
                        destination_layout["classification_map"]
                    ),
                    "settle_latency_milliseconds": edge["after"]["settlement"][
                        "settle_latency_milliseconds"
                    ],
                    "old_generation": (
                        old_edge["after"].get("layout_generation")
                        if old_edge is not None
                        else None
                    ),
                    "new_generation": edge["after"].get("layout_generation"),
                    "old_element_count": (
                        old_edge["after"].get("element_count")
                        if old_edge is not None
                        else None
                    ),
                    "new_element_count": edge["after"].get("element_count"),
                }
            )

        if endpoint_kinds["before"] == "overlay":
            source_layout_id = "dark_cloud_settings_credentials"
            source_diagnosis = {
                "status": "v2.15_nonsemantic_overlay_supersession",
                "retired_screen_fixture": file_receipt(
                    landed_path_by_layout_id["dark-cloud-settings"]
                ),
                "overlay_record": file_receipt(overlay_path),
                "semantic_member_count": 0,
            }
        else:
            source_layout_id = raw_edge["before"]["layout_id"]
        if (
            endpoint_kinds["before"] == "layout"
            and source_layout_id == "game-settings-gameplay"
            and endpoint_state_ids["before"] != "base"
        ):
            source_diagnosis = {
                "status": "v2.16_multi_state_path_dependent_core",
                "state_id": endpoint_state_ids["before"],
                "base_layout_diagnosis": copy.deepcopy(
                    standalone_diagnoses[source_layout_id]
                ),
                "structural_core_sha256": endpoint_layouts["before"][
                    "structural_core_sha256"
                ],
            }
        elif (
            endpoint_kinds["before"] == "layout"
            and source_layout_id == "beta-notice"
        ):
            source_diagnosis = copy.deepcopy(
                standalone_diagnoses["beta-notice"]
            )
        elif endpoint_kinds["before"] == "layout" and source_layout_id in landed_by_layout_id:
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
                diagnostic_allow_equivalent=(
                    enumerate_all_unclassified or source_layout_id == "pause-menu"
                ),
                class_f_witness=census_era_view["class_f"].get(
                    source_layout_id
                ),
            )
            if (
                population_trace_selection.get("source")
                == "diagnostic_all_qualifying_navigation_endpoints"
            ):
                standalone_selection = standalone_diagnoses[source_layout_id].get(
                    "population_trace_selection"
                )
                if (
                    not isinstance(standalone_selection, dict)
                    or standalone_selection.get("source")
                    != "diagnostic_all_qualifying_navigation_endpoints"
                    or canonical_bytes(
                        standalone_selection.get("candidate_bindings")
                    )
                    != canonical_bytes(
                        population_trace_selection.get("candidate_bindings")
                    )
                ):
                    raise PromotionError(
                        f"{source_layout_id} diagnostic population-witness "
                        "evaluation was not reused consistently at transition sources"
                    )
                source_diagnosis = copy.deepcopy(
                    standalone_diagnoses[source_layout_id]
                )
                population_trace_selection = copy.deepcopy(standalone_selection)
                if source_diagnosis.get("status") == "diagnostic_unclassified":
                    binding = population_trace_selection["candidate_bindings"][0]
                    matches = [
                        pair
                        for pair in navigation_population_pairs.get(
                            source_layout_id, []
                        )
                        if pair["edge_id"] == binding["edge_id"]
                        and pair["side"] == binding["side"]
                    ]
                    if len(matches) != 1:
                        raise PromotionError(
                            f"{source_layout_id} diagnostic population binding "
                            "is absent or ambiguous at a transition source"
                        )
                    differences = enumerate_record(
                        source_layout_id,
                        matches[0]["primary_trace"],
                        matches[0]["confirmation_trace"],
                    )
                    stop_message = (
                        f"STOP: transition source {edge_id}: "
                        f"{source_diagnosis['original_stop']}"
                    )
                    record_unclassified(
                        source_layout_id,
                        differences,
                        occurrence={
                            "scope": "transition_source",
                            "edge_id": edge_id,
                            "side": "before",
                        },
                        stop_message=stop_message,
                    )
                    source_diagnosis["original_stop"] = stop_message
            else:
                try:
                    source_diagnosis = diagnose_record(
                        source_layout_id,
                        population_primary_trace,
                        population_confirmation_trace,
                    )
                    source_diagnosis[
                        "population_trace_selection"
                    ] = population_trace_selection
                except LandedDiagnosisError as error:
                    stop_message = f"STOP: transition source {edge_id}: {error}"
                    if not enumerate_all_unclassified:
                        raise PromotionError(stop_message) from error
                    differences = enumerate_record(
                        source_layout_id,
                        population_primary_trace,
                        population_confirmation_trace,
                    )
                    record_unclassified(
                        source_layout_id,
                        differences,
                        occurrence={
                            "scope": "transition_source",
                            "edge_id": edge_id,
                            "side": "before",
                        },
                        stop_message=stop_message,
                    )
                    source_diagnosis = {
                        "status": "diagnostic_unclassified",
                        "original_stop": stop_message,
                        "unclassified_difference_count": len(differences),
                        "population_trace_selection": population_trace_selection,
                    }
        elif endpoint_kinds["before"] == "layout":
            source_diagnosis = {
                "status": "new_path_dependent_layout",
                "landed_payload": "not_embedded_in_v1_navigation_aggregate",
                "fork_decision": copy.deepcopy(
                    records[source_layout_id]["header"]["path_dependent_core"][
                        "fork_decision"
                    ]
                ),
            }
        signature_match = (
            _navigation_endpoint_signature_v25(edge["before"])
            == _navigation_endpoint_signature_v25(old_edge["before"])
            if old_edge is not None
            else None
        )
        frame_match = (
            edge["before"].get("frame_sha256")
            == old_edge["before"].get("frame_sha256")
            if old_edge is not None
            else None
        )
        if old_edge is None:
            if edge_id != chartered_edge_id:
                raise PromotionError(
                    f"navigation edge {edge_id} has no landed comparison or charter"
                )
            source_diagnosis = {
                "status": "chartered_new_edge_source_exact_standalone",
                "layout_id": source_layout_id,
                "landed_edge_comparison": "not_applicable_edge_did_not_exist",
                "standalone_diagnosis": source_diagnosis,
            }
        if source_diagnosis["status"] == "strict_structural_bit_match" and (
            not signature_match or not frame_match
        ):
            stop_message = (
                f"STOP: strict transition source {edge_id} does not bit-match "
                "its landed signature/frame"
            )
            if not enumerate_all_unclassified:
                raise PromotionError(stop_message)
            differences: list[dict[str, Any]] = []
            if not signature_match:
                differences.append(
                    {
                        "difference_type": "transition_source_field",
                        "field": "endpoint_signature",
                        "landed_value": _navigation_endpoint_signature_v25(
                            old_edge["before"]
                        ),
                        "settled_value": _navigation_endpoint_signature_v25(
                            edge["before"]
                        ),
                    }
                )
            if not frame_match:
                differences.append(
                    {
                        "difference_type": "transition_source_field",
                        "field": "frame_sha256",
                        "landed_value": old_edge["before"].get("frame_sha256"),
                        "settled_value": edge["before"].get("frame_sha256"),
                    }
                )
            record_unclassified(
                source_layout_id,
                differences,
                occurrence={
                    "scope": "transition_source",
                    "edge_id": edge_id,
                    "side": "before",
                },
                stop_message=stop_message,
            )
            source_diagnosis = {
                "status": "diagnostic_unclassified",
                "original_stop": stop_message,
                "unclassified_difference_count": len(differences),
            }
        source_audit.append(
            {
                "edge": edge_id,
                "layout_id": source_layout_id,
                "diagnosis": source_diagnosis,
                "signature_bit_match": signature_match,
                "frame_bit_match": frame_match,
            }
        )

    if enumerate_all_unclassified:
        diagnostic_population_equivalences = [
            {
                "layout_id": layout_id,
                "selection": copy.deepcopy(
                    diagnosis["population_trace_selection"]
                ),
            }
            for layout_id, diagnosis in sorted(standalone_diagnoses.items())
            if isinstance(diagnosis, dict)
            and isinstance(diagnosis.get("population_trace_selection"), dict)
            and diagnosis["population_trace_selection"].get("source")
            == "diagnostic_all_qualifying_navigation_endpoints"
        ]
        entries = sorted(
            unclassified_by_key.values(),
            key=lambda value: (
                value["layout_id"],
                str(value["difference"].get("difference_type", "")),
                str(value["difference"].get("field", "")),
                str(value["difference"].get("element_id", "")),
                str(value["difference"].get("semantic_sha256", "")),
            ),
        )
        for entry in entries:
            entry["occurrences"] = sorted(
                entry["occurrences"],
                key=lambda value: (
                    str(value.get("scope", "")),
                    str(value.get("edge_id", "")),
                    str(value.get("side", "")),
                ),
            )
        navigation_layout_endpoint_count = sum(
            1
            for edge in resolved_navigation["edges"]
            for side in ("before", "after")
            if isinstance(edge.get(side), dict)
            and edge[side].get("type") != "overlay"
        )
        return {
            "schema": "solomon-dark-native-menu-landed-difference-census-v1",
            "mode": "enumerate_all_unclassified",
            "success": True,
            "dry_run": True,
            "writes_performed": False,
            "candidate_applied": False,
            "production_behavior": "stop_at_first_unclassified_difference",
            "all_corpus_gates_completed": True,
            "authorized_v220_title_context": copy.deepcopy(
                dark_cloud_login_title_context
            ),
            "authorized_v221_census_era_context": copy.deepcopy(
                census_era_context
            ),
            "authorized_v222_final_disposition_context": copy.deepcopy(
                final_disposition_context
            ),
            "inputs": {
                "landed_aggregate": {
                    "repo_relative_path": (
                        landed_root / "menu-goldens.json"
                    ).relative_to(repo_root).as_posix(),
                    **file_receipt(landed_root / "menu-goldens.json"),
                },
                "candidate_aggregate": evidence_receipt(candidate_golden_path),
                "resolved_navigation": evidence_receipt(navigation_path),
                "derived_overlay_reference": evidence_receipt(
                    candidate_overlay_path
                ),
            },
            "census": {
                "landed_layout_count_examined": len(landed_by_layout_id),
                "qualified_standalone_count_examined": len(records),
                "native_navigation_edge_count_examined": len(resolved_by_id),
                "navigation_layout_endpoint_count_examined": (
                    navigation_layout_endpoint_count
                ),
                "unclassified_layout_count": len(
                    {entry["layout_id"] for entry in entries}
                ),
                "unclassified_difference_count": len(entries),
            },
            "first_production_stop": (
                unclassified_stop_messages[0]
                if unclassified_stop_messages
                else None
            ),
            "diagnostic_population_witness_equivalence_classes": (
                diagnostic_population_equivalences
            ),
            "unclassified_differences": entries,
        }

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
        (overlay_path, landed_root / "menu-overlays/dark-cloud-settings.json"),
        (
            underlay_path,
            landed_root / "menu-overlay-underlays/dark-cloud-settings.json",
        ),
        (
            composite_path,
            landed_root
            / "menu-dialog-composites/beta-notice-first-boot.json",
        ),
        (candidate_golden_path, landed_root / "menu-goldens.json"),
    ]
    retired_screen_path = landed_root / "menu-layouts/dark-cloud-settings.json"
    retired_v29_contract_path = (
        landed_root / "native-menu-beta-notice-order-v29.json"
    )
    if not dry_run:
        superseded_v29 = beta_paint_order_contract.get("superseded_contract")
        if (
            not isinstance(superseded_v29, dict)
            or set(superseded_v29)
            != {"evidence_path", "sha256", "bytes"}
        ):
            raise PromotionError(
                "Settlement v2.17 qualified paint-order contract lost its exact retired v2.9 receipt"
            )
        archived_v29_path = evidence_root / str(
            superseded_v29["evidence_path"]
        )
        archived_v29_receipt = evidence_receipt(archived_v29_path)
        if archived_v29_receipt != {
            "evidence_path": superseded_v29["evidence_path"],
            "sha256": superseded_v29["sha256"],
            "bytes": superseded_v29["bytes"],
        }:
            raise PromotionError(
                "Settlement v2.17 archived v2.9 contract receipt changed before retirement"
            )
        destinations_already_promoted = all(
            destination.is_file()
            and file_receipt(destination) == file_receipt(source)
            for source, destination in promotion_pairs
        )
        retired_screen_present = retired_screen_path.is_file()
        if retired_screen_present:
            if file_receipt(retired_screen_path) != standalone_diagnoses[
                "dark-cloud-settings"
            ]["retired_fixture"]:
                raise PromotionError(
                    "Settlement v2.15 refused to retire a changed Dark Cloud Settings screen fixture"
                )
        elif not destinations_already_promoted:
            raise PromotionError(
                "Settlement v2.15 retired screen is absent before an incomplete promotion transaction"
            )
        retired_v29_present = retired_v29_contract_path.is_file()
        if retired_v29_present and file_receipt(
            retired_v29_contract_path
        ) != {
            "sha256": superseded_v29["sha256"],
            "bytes": superseded_v29["bytes"],
        }:
            raise PromotionError(
                "Settlement v2.17 refused to retire a changed 34-member v2.9 contract"
            )
        for source, destination in promotion_pairs:
            atomic_copy(source, destination)
        if retired_screen_present:
            retired_screen_path.unlink()
        if retired_v29_present:
            retired_v29_contract_path.unlink()
        try:
            build_menu_baseline(repo_root, False)
        except BaselineBuildError as error:
            raise PromotionError(
                f"promoted fixtures could not refresh the shellfix baseline receipts: {error}"
            ) from error

    corrected = {
        layout_id: diagnosis
        for layout_id, diagnosis in standalone_diagnoses.items()
        if diagnosis["status"]
        in {"corrected", "corrected_to_nonsemantic_overlay"}
    }
    return {
        "success": True,
        "dry_run": dry_run,
        "settlement_spec": "2.22",
        "census_era_disposition_v221": census_era_context,
        "final_four_disposition_v222": final_disposition_context,
        "dark_cloud_menu_screen_id_references_v221": (
            dark_cloud_menu_reference_context
        ),
        "dark_cloud_login_title_correction_v220": (
            dark_cloud_login_title_context
        ),
        "controls_core_supersession": controls_core_context,
        "standalone_count": len(records),
        "standalone_diagnoses": standalone_diagnoses,
        "nonsemantic_overlay": {
            "overlay_id": overlay_record["overlay_id"],
            "record": file_receipt(overlay_path),
            "semantic_underlay": file_receipt(underlay_path),
            "validated_evidence_receipt_count": len(
                overlay_evidence_receipts
            ),
        },
        "semantic_dialog_composite": semantic_dialog_composite,
        "instance_local_generation_v219": generation_v219_census,
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
        "retired_files": [
            str(retired_screen_path),
            str(retired_v29_contract_path),
        ],
        "shellfix_pending_fixture_count": 29,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--enumerate-all-unclassified-output",
        type=Path,
        help=(
            "write a no-promotion census of every unclassified landed-vs-settled "
            "difference; requires --dry-run"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        evidence_root = args.evidence_root.resolve()
        result = validate_and_promote(
            args.repo_root.resolve(),
            args.candidate_root.resolve(),
            evidence_root,
            args.navigation_recording.resolve(),
            args.dry_run,
            enumerate_all_unclassified=(
                args.enumerate_all_unclassified_output is not None
            ),
        )
        if args.enumerate_all_unclassified_output is not None:
            output = args.enumerate_all_unclassified_output.resolve()
            if not output.is_relative_to(evidence_root):
                raise PromotionError(
                    "landed-difference census output escapes the evidence root"
                )
            atomic_write_json(output, result)
    except PromotionError as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    if args.enumerate_all_unclassified_output is not None:
        print(
            json.dumps(
                {
                    "success": True,
                    "mode": result["mode"],
                    "audit_output": str(output),
                    "audit_receipt": file_receipt(output),
                    "census": result["census"],
                    "first_production_stop": result["first_production_stop"],
                },
                indent=2,
            )
        )
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
