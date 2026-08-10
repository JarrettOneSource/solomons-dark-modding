#!/usr/bin/env python3
"""Build the G11 aggregate only from resolved Settlement v2.9 artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from native_menu_overlay_v25 import (
    OVERLAY_REFERENCE_SCHEMA,
    OverlayV25Error,
    assert_overlay_hygiene,
    derive_overlay_reference,
)
from native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    diagnosis_prereference_residual,
    semantic_overlay_corroboration,
)
from native_menu_ambient_lifecycle import (
    AmbientLifecycleError,
    reproduce_standalone_structural_core,
)
from native_menu_profile_state import (
    FRESH_BASELINE_ID,
    NativeMenuProfileStateError,
    assert_navigation_baseline_allowed,
    load_hub_binding_contract,
    load_profile_state_baseline,
    required_baseline_for_layout,
    resolve_navigation_profile_binding,
    validate_capture_profile_state,
)
from native_menu_browser_tab import (
    NativeMenuBrowserTabError,
    validate_browser_tab,
)
from native_menu_multi_state_path_core import SETTINGS_ENDPOINT_BINDINGS
from native_menu_nonsemantic_overlay import (
    NativeMenuNonSemanticOverlayError,
    validate_overlay_record,
)
from native_menu_semantic_dialog_composite import (
    COMPOSITE_ID,
    NativeMenuSemanticDialogCompositeError,
    validate_composite_record,
)


class GoldenBuildError(RuntimeError):
    """The candidate corpus is incomplete, ambiguous, or internally divergent."""


CHARTERED_PROFILE_NEW_GAME_EDGE = {
    "id": "profile_select_new_game_to_create",
    "source": "profile_save_select",
    "trigger": "new_game_click",
    "action_id": "main_menu.new_game",
    "destination": "create_element",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise GoldenBuildError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise GoldenBuildError(f"{path} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def unique_json_files(root: Path, expected_count: int, witness: str) -> dict[str, Path]:
    paths = sorted(root.glob("*.json"))
    result = {path.stem: path for path in paths}
    if len(paths) != len(result):
        raise GoldenBuildError(f"fixture lookup under {root} is ambiguous")
    if len(result) != expected_count or witness not in result:
        raise GoldenBuildError(
            f"fixture census under {root} did not reach {expected_count} unique "
            f"records including '{witness}'"
        )
    return result


def source_provenance(header: dict[str, Any], label: str) -> dict[str, Any]:
    source = header.get("source")
    if not isinstance(source, dict):
        raise GoldenBuildError(f"{label} has no machine-derived source provenance")
    requirements = {
        "base_commit_sha": 40,
        "source_tree_sha": 40,
        "game_executable_sha256": 64,
        "loader_dll_sha256": 64,
        "profile_state_identity_sha256": 64,
    }
    for field, length in requirements.items():
        value = source.get(field)
        if (
            not isinstance(value, str)
            or len(value) != length
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise GoldenBuildError(
                f"{label} has invalid machine-derived provenance field '{field}'"
            )
    return source


def reference_receipt(
    fixture_path: Path,
    fixture: dict[str, Any],
    fixture_root: Path,
) -> tuple[str, str]:
    header = fixture["header"]
    relative = header.get("reference_capture")
    if not isinstance(relative, str) or not relative:
        raise GoldenBuildError(f"{fixture_path} has no reference capture")
    path = (fixture_path.parent / relative).resolve()
    reference_root = (fixture_root / "menu-reference-captures").resolve()
    if not path.is_relative_to(reference_root) or not path.is_file():
        raise GoldenBuildError(
            f"{fixture_path} reference capture is absent or escapes its fixture root"
        )
    return f"menu-reference-captures/{path.name}", sha256_file(path)


def validate_fixture(
    repo_root: Path, path: Path, fixture_root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = read_object(path)
    if fixture.get("schema") != "solomon-dark-native-menu-layout-v3":
        raise GoldenBuildError(f"{path} does not use Settlement v2.9 schema v3")
    header = fixture.get("header")
    layout = fixture.get("layout")
    if not isinstance(header, dict) or not isinstance(layout, dict):
        raise GoldenBuildError(f"{path} has no capture header/layout")
    source_provenance(header, str(path))
    try:
        validate_capture_profile_state(
            repo_root=repo_root,
            header=header,
            label=str(path),
            evidence_root=None,
            required_baseline_id=required_baseline_for_layout(
                repo_root, path.stem
            ),
            binding_label=f"layout '{path.stem}'",
        )
    except NativeMenuProfileStateError as error:
        raise GoldenBuildError(str(error)) from error
    try:
        validate_browser_tab(
            screen_tag=str(layout.get("screen_id", "")),
            layout=layout,
            receipt=header.get("browser_tab_verification"),
            label=str(path),
        )
    except NativeMenuBrowserTabError as error:
        raise GoldenBuildError(str(error)) from error
    settlement = header.get("settlement")
    ambient = header.get("ambient_lifecycle")
    if (
        header.get("recorded_live") is not True
        or not isinstance(settlement, dict)
        or settlement.get("settlement_spec") != "2.9"
        or settlement.get("consecutive_structural_samples", 0) < 40
        or settlement.get("stable_span_milliseconds", 0) < 2_000
        or not isinstance(ambient, dict)
        or len(ambient.get("independent_instances", [])) < 2
        or layout.get("settlement_spec") != "2.9"
        or layout.get("draw_order_semantics")
        != "structural_core_relative_sequence"
        or layout.get("ambient_fraction", 1.0) > 0.40
    ):
        raise GoldenBuildError(f"{path} has incomplete Settlement v2.9 provenance")
    reference, reference_sha256 = reference_receipt(path, fixture, fixture_root)
    wrapper = {
        "fixture": (
            f"menu-transition-layouts/{path.name}"
            if path.parent.name == "menu-transition-layouts"
            else f"menu-layouts/{path.name}"
        ),
        "reference_capture": reference,
        "reference_sha256": reference_sha256,
        "header": copy.deepcopy(header),
        "layout": copy.deepcopy(layout),
    }
    if "path_dependent_cores" in fixture:
        wrapper["path_dependent_cores"] = copy.deepcopy(
            fixture["path_dependent_cores"]
        )
    return fixture, wrapper


def standalone_settled_pair(
    repo_root: Path,
    path: Path,
    fixture_root: Path,
    fixture: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    header = fixture["header"]
    raw_receipt = header.get("settlement_trace", header.get("raw_recording"))
    confirmation_receipt = header.get("animation_confirmation")
    if not isinstance(raw_receipt, dict) or not isinstance(
        confirmation_receipt, dict
    ):
        raise GoldenBuildError(
            f"{path} has no two-window standalone settlement receipts"
        )

    def recording(
        receipt: dict[str, Any], directory: str, label: str
    ) -> dict[str, Any]:
        filename = receipt.get("evidence_filename")
        if not isinstance(filename, str) or not filename:
            raise GoldenBuildError(f"{path} {label} receipt has no filename")
        evidence_path = (fixture_root / directory / filename).resolve()
        expected_root = (fixture_root / directory).resolve()
        if not evidence_path.is_relative_to(expected_root) or not evidence_path.is_file():
            raise GoldenBuildError(f"{path} {label} evidence is absent or escapes")
        if (
            evidence_path.stat().st_size != receipt.get("bytes")
            or sha256_file(evidence_path) != receipt.get("sha256")
        ):
            raise GoldenBuildError(f"{path} {label} evidence receipt is false")
        return read_object(evidence_path)

    primary = recording(
        raw_receipt, "menu-settlement-traces", "primary settlement"
    )
    confirmation = recording(
        confirmation_receipt,
        "menu-animation-confirmations",
        "fresh-instance confirmation",
    )
    confirmation_header = confirmation.get("header")
    if not isinstance(confirmation_header, dict):
        raise GoldenBuildError(f"{path} confirmation has no capture header")
    try:
        primary_profile = validate_capture_profile_state(
            repo_root=repo_root,
            header=header,
            label=str(path),
            evidence_root=None,
            required_baseline_id=required_baseline_for_layout(
                repo_root, path.stem
            ),
            binding_label=f"layout '{path.stem}'",
        )
        confirmation_profile = validate_capture_profile_state(
            repo_root=repo_root,
            header=confirmation_header,
            label=f"{path} confirmation",
            evidence_root=None,
            required_baseline_id=primary_profile["baseline_id"],
            binding_label=f"layout '{path.stem}' confirmation",
        )
    except NativeMenuProfileStateError as error:
        raise GoldenBuildError(str(error)) from error
    if confirmation_profile["baseline_id"] != primary_profile["baseline_id"]:
        raise GoldenBuildError(f"{path} confirmation changed profile baseline")
    primary_source = header.get("source")
    confirmation_source = confirmation_header.get("source")
    if not isinstance(primary_source, dict) or not isinstance(
        confirmation_source, dict
    ):
        raise GoldenBuildError(f"{path} settled pair lost source provenance")
    for field in (
        "base_commit_sha",
        "source_tree_sha",
        "game_executable_sha256",
        "loader_dll_sha256",
    ):
        if primary_source.get(field) != confirmation_source.get(field):
            raise GoldenBuildError(
                f"{path} confirmation changed native provenance field '{field}'"
            )
    primary_identity = (header.get("instance"), header.get("process_id"))
    confirmation_identity = (
        confirmation_header.get("instance"),
        confirmation_header.get("process_id"),
    )
    if primary_identity == confirmation_identity:
        raise GoldenBuildError(f"{path} confirmation reused the primary instance/PID")
    primary_samples = primary.get("settled_window_samples")
    confirmation_samples = confirmation.get("settled_window_samples")
    if (
        not isinstance(primary_samples, list)
        or not isinstance(confirmation_samples, list)
        or not all(isinstance(sample, dict) for sample in primary_samples)
        or not all(isinstance(sample, dict) for sample in confirmation_samples)
    ):
        raise GoldenBuildError(f"{path} settled pair has no sample arrays")
    return primary_samples, confirmation_samples


def parse_capture_time(header: dict[str, Any], label: str) -> datetime:
    value = header.get("captured_at_utc")
    if not isinstance(value, str) or not value:
        raise GoldenBuildError(f"{label} has no capture timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as error:
        raise GoldenBuildError(f"{label} has invalid capture timestamp {value!r}") from error


def endpoint(value: dict[str, Any], edge_id: str, side: str) -> dict[str, Any]:
    if value.get("type") == "overlay":
        overlay_id = value.get("overlay_id")
        overlay_fixture = value.get("overlay_fixture")
        settlement = value.get("settlement")
        if (
            overlay_id != "dark_cloud_settings_credentials"
            or not isinstance(overlay_fixture, dict)
            or overlay_fixture.get("candidate_relative_path")
            != "menu-overlays/dark-cloud-settings.json"
            or not isinstance(settlement, dict)
            or settlement.get("settlement_spec") != "2.15"
            or value.get("members_semantically_observable") is not False
            or value.get("semantic_member_count") != 0
            or value.get("semantic_members") != []
        ):
            raise GoldenBuildError(
                f"navigation edge {edge_id} {side} has an invalid non-semantic overlay endpoint"
            )
        frame = value.get("frame_sha256")
        if (
            not isinstance(frame, str)
            or len(frame) != 64
            or any(character not in "0123456789abcdef" for character in frame)
        ):
            raise GoldenBuildError(
                f"navigation edge {edge_id} {side} overlay has no exact frame provenance"
            )
        fields = (
            "type",
            "overlay_id",
            "overlay_fixture",
            "members_semantically_observable",
            "semantic_member_count",
            "semantic_members",
            "underlying_surface",
            "frame_sha256",
            "settlement",
        )
        return {field: copy.deepcopy(value.get(field)) for field in fields}

    layout = value.get("layout")
    settlement = value.get("settlement")
    layout_id = value.get("layout_id")
    if (
        not isinstance(layout, dict)
        or not isinstance(settlement, dict)
        or settlement.get("settlement_spec") != "2.9"
        or not isinstance(layout_id, str)
        or not layout_id
    ):
        raise GoldenBuildError(
            f"navigation edge {edge_id} {side} has no resolved v2.9 endpoint"
        )
    frame = value.get("frame_sha256")
    if (
        not isinstance(frame, str)
        or len(frame) != 64
        or any(character not in "0123456789abcdef" for character in frame)
    ):
        raise GoldenBuildError(
            f"navigation edge {edge_id} {side} has no exact frame provenance"
        )
    fields = (
        "semantic_surface",
        "machine_classified_surface",
        "semantic_generation",
        "tagged_screen",
        "layout_generation",
        "element_count",
        "capture_method",
        "frame_sha256",
        "settlement",
        "layout",
        "layout_id",
        "animated_element_ids",
        "animated_family_ids",
        "choice_slot_ids",
        "browser_tab_verification",
        "path_dependent_core",
    )
    return {
        field: copy.deepcopy(value.get(field))
        for field in fields
        if field in value
    }


def validate_settings_path_binding(
    fixture: dict[str, Any],
    observed: dict[str, Any],
    edge_id: str,
    endpoint_name: str,
) -> str:
    contract = fixture.get("header", {}).get("multi_state_path_dependent_core")
    endpoint_contract = observed.get("path_dependent_core")
    if not isinstance(contract, dict) or contract.get("settlement_spec") != "2.16":
        raise GoldenBuildError(
            "multi-state path-dependent core contract: Settings fixture has no v2.16 binding registry"
        )
    binding_map: dict[tuple[str, str], str] = {}
    reached_standalone = False
    for binding in contract.get("bindings", []):
        if not isinstance(binding, dict):
            raise GoldenBuildError(
                "multi-state path-dependent core contract: Settings binding is not an object"
            )
        if binding.get("binding") == "standalone":
            if (
                reached_standalone
                or binding.get("layout_id") != "game-settings-gameplay"
                or binding.get("state_id") != "base"
            ):
                raise GoldenBuildError(
                    "multi-state path-dependent core contract: Settings standalone binding changed"
                )
            reached_standalone = True
            continue
        key = (binding.get("edge_id"), binding.get("endpoint"))
        if (
            binding.get("binding") != "navigation_endpoint"
            or not all(isinstance(value, str) for value in key)
            or key in binding_map
            or not isinstance(binding.get("state_id"), str)
        ):
            raise GoldenBuildError(
                "multi-state path-dependent core contract: Settings endpoint binding is absent or ambiguous"
            )
        binding_map[key] = binding["state_id"]
    if not reached_standalone or binding_map != SETTINGS_ENDPOINT_BINDINGS:
        raise GoldenBuildError(
            "multi-state path-dependent core contract: Settings endpoint binding census changed or a fourth state appeared"
        )
    expected_state = binding_map.get((edge_id, endpoint_name))
    if expected_state is None:
        raise GoldenBuildError(
            "multi-state path-dependent core contract: unbound Settings navigation endpoint"
        )
    layout = observed.get("layout")
    registered_state = fixture.get("path_dependent_cores", {}).get(expected_state)
    if (
        not isinstance(registered_state, dict)
        or not isinstance(endpoint_contract, dict)
        or endpoint_contract.get("settlement_spec") != "2.16"
        or endpoint_contract.get("parent_layout_id") != "game-settings-gameplay"
        or endpoint_contract.get("edge_id") != edge_id
        or endpoint_contract.get("endpoint") != endpoint_name
        or endpoint_contract.get("state_id") != expected_state
        or not isinstance(layout, dict)
        or endpoint_contract.get("structural_core_sha256")
        != layout.get("structural_core_sha256")
        or endpoint_contract.get("measured_element_count")
        != registered_state.get("measured_element_count")
        or endpoint_contract.get("structural_core_sha256")
        != registered_state.get("structural_core_sha256")
        or observed.get("element_count")
        != registered_state.get("structural_core_element_count")
        or len(layout.get("elements", []))
        != registered_state.get("structural_core_element_count")
    ):
        raise GoldenBuildError(
            "multi-state path-dependent core contract: bound endpoint presented a different Settings core"
        )
    return expected_state


def capture_session(header: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": header.get("label"),
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "source": copy.deepcopy(header.get("source")),
        "profile_state": copy.deepcopy(header.get("profile_state")),
        "profile_state_binding": copy.deepcopy(
            header.get("profile_state_binding")
        ),
        "capture_method": header.get("capture_method"),
        "recorded_live": header.get("recorded_live"),
        "captured_at_utc": header.get("captured_at_utc"),
    }


def build(
    repo_root: Path,
    fixture_root: Path,
    navigation_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    overlay_path = fixture_root / "menu-overlay-reference.json"
    layout_paths = unique_json_files(
        fixture_root / "menu-layouts", 27, "main-menu-root"
    )
    if "dark-cloud-settings" in layout_paths:
        raise GoldenBuildError(
            "Settlement v2.15 did not retire the mischaracterized Dark Cloud Settings screen"
        )
    transition_paths = unique_json_files(
        fixture_root / "menu-transition-layouts", 3, "hub_new_game"
    )
    if set(transition_paths) != {
        "hub_new_game",
        "hub_pristine_second_new_game",
        "hub_resumed",
    }:
        raise GoldenBuildError(
            "path-dependent core contract: transition fixture census is not the "
            "three authorized Hub layouts"
        )
    overlay_record_paths = unique_json_files(
        fixture_root / "menu-overlays", 1, "dark-cloud-settings"
    )
    underlay_paths = unique_json_files(
        fixture_root / "menu-overlay-underlays", 1, "dark-cloud-settings"
    )
    composite_paths = unique_json_files(
        fixture_root / "menu-dialog-composites",
        1,
        "beta-notice-first-boot",
    )
    overlay_record_path = overlay_record_paths["dark-cloud-settings"]
    underlay_path = underlay_paths["dark-cloud-settings"]
    composite_path = composite_paths["beta-notice-first-boot"]
    overlay_record = read_object(overlay_record_path)
    try:
        validate_overlay_record(overlay_record)
    except NativeMenuNonSemanticOverlayError as error:
        raise GoldenBuildError(str(error)) from error
    recorded_underlay = overlay_record["overlay"]["semantic_underlay_binding"][
        "primary_fixture"
    ]
    if (
        recorded_underlay.get("sha256") != sha256_file(underlay_path)
        or recorded_underlay.get("bytes") != underlay_path.stat().st_size
    ):
        raise GoldenBuildError(
            "Settlement v2.15 overlay records a false semantic-underlay fixture receipt"
        )
    overlay_wrapper = {
        "fixture": "menu-overlays/dark-cloud-settings.json",
        "underlay_fixture": "menu-overlay-underlays/dark-cloud-settings.json",
        "overlay_id": overlay_record["overlay_id"],
        "settlement_spec": overlay_record["settlement_spec"],
        "record": copy.deepcopy(overlay_record),
        "sha256": sha256_file(overlay_record_path),
        "bytes": overlay_record_path.stat().st_size,
        "underlay_sha256": sha256_file(underlay_path),
        "underlay_bytes": underlay_path.stat().st_size,
    }
    fixtures: dict[str, dict[str, Any]] = {}
    wrappers: list[dict[str, Any]] = []
    transition_wrappers: list[dict[str, Any]] = []
    latest_capture: datetime | None = None
    sessions: list[dict[str, Any]] = []
    for layout_id, path in [*layout_paths.items(), *transition_paths.items()]:
        fixture, wrapper = validate_fixture(repo_root, path, fixture_root)
        if layout_id in fixtures:
            raise GoldenBuildError(f"fixture id '{layout_id}' is ambiguous")
        fixtures[layout_id] = fixture
        (
            transition_wrappers
            if layout_id in {
                "hub_new_game",
                "hub_pristine_second_new_game",
                "hub_resumed",
            }
            else wrappers
        ).append(wrapper)
        observed = parse_capture_time(fixture["header"], str(path))
        latest_capture = observed if latest_capture is None else max(latest_capture, observed)
        sessions.append(capture_session(fixture["header"]))
    if len(fixtures) != 30 or latest_capture is None:
        raise GoldenBuildError(
            "aggregate fixture sweep did not reach 27 menus plus three Hub layouts"
        )

    landed = read_object(repo_root / "tests/fixtures/webgame/menu-goldens.json")
    landed_layouts = landed.get("layouts")
    if not isinstance(landed_layouts, list) or len(landed_layouts) != 28:
        raise GoldenBuildError(
            "derived overlay reference did not reach the landed 28-layout census"
        )
    landed_by_id = {
        Path(entry["fixture"]).stem: entry["layout"]
        for entry in landed_layouts
        if isinstance(entry, dict)
        and isinstance(entry.get("fixture"), str)
        and isinstance(entry.get("layout"), dict)
    }
    overlay_witnesses = {
        "beta-notice",
        "main-menu-root",
        "create-element",
        "pause-menu",
    }
    if not overlay_witnesses <= set(fixtures) or not {
        "create-element",
        "pause-menu",
    } <= set(landed_by_id):
        raise GoldenBuildError(
            "derived overlay reference did not reach every named structural witness"
        )
    try:
        beta_primary, beta_confirmation = standalone_settled_pair(
            repo_root,
            layout_paths["beta-notice"],
            fixture_root,
            fixtures["beta-notice"],
        )
        main_primary, main_confirmation = standalone_settled_pair(
            repo_root,
            layout_paths["main-menu-root"],
            fixture_root,
            fixtures["main-menu-root"],
        )
        beta_standalone_core = reproduce_standalone_structural_core(
            beta_primary,
            beta_confirmation,
            label="beta_notice",
            authorized_ambient_family=set(
                fixtures["beta-notice"]["layout"]["ambient_family_art_ids"]
            ),
        )
        main_standalone_core = reproduce_standalone_structural_core(
            main_primary,
            main_confirmation,
            label="main_menu_root",
            authorized_ambient_family=set(
                fixtures["main-menu-root"]["layout"]["ambient_family_art_ids"]
            ),
        )
        create_residual, _ = diagnosis_prereference_residual(
            landed_by_id["create-element"], fixtures["create-element"]["layout"]
        )
        pause_residual, _ = diagnosis_prereference_residual(
            landed_by_id["pause-menu"], fixtures["pause-menu"]["layout"]
        )
        overlay = derive_overlay_reference(
            beta_standalone_core,
            main_standalone_core,
            semantic_overlay_corroboration(create_residual),
            semantic_overlay_corroboration(pause_residual),
        )
    except (
        AmbientLifecycleError,
        LandedDiagnosisError,
        OverlayV25Error,
    ) as error:
        raise GoldenBuildError(
            f"derived Settlement v2.9 overlay reference failed: {error}"
        ) from error
    if overlay.get("schema") != OVERLAY_REFERENCE_SCHEMA:
        raise GoldenBuildError(
            "derived Settlement v2.9 overlay reference has the wrong schema"
        )
    write_object(overlay_path, overlay)
    for layout_id, fixture in fixtures.items():
        try:
            assert_overlay_hygiene(fixture["layout"], overlay)
        except OverlayV25Error as error:
            raise GoldenBuildError(
                f"standalone '{layout_id}' failed derived overlay hygiene: {error}"
            ) from error

    composite_record = read_object(composite_path)
    try:
        composite_classification = validate_composite_record(
            composite_record,
            fixtures["control-scheme-picker"]["layout"],
            overlay,
            fixtures["beta-notice"]["layout"],
        )
    except NativeMenuSemanticDialogCompositeError as error:
        raise GoldenBuildError(str(error)) from error
    composite_reference = composite_record.get("header", {}).get(
        "reference_capture"
    )
    composite_reference_path = (
        fixture_root / "menu-reference-captures/beta-notice-first-boot.png"
    )
    if composite_reference != {
        "fixture": "menu-reference-captures/beta-notice-first-boot.png",
        "sha256": sha256_file(composite_reference_path),
        "bytes": composite_reference_path.stat().st_size,
    }:
        raise GoldenBuildError(
            "semantic dialog composite records a false committed visual reference"
        )
    composite_wrapper = {
        "fixture": "menu-dialog-composites/beta-notice-first-boot.json",
        "composite_id": COMPOSITE_ID,
        "settlement_spec": "2.17",
        "record": copy.deepcopy(composite_record),
        "sha256": sha256_file(composite_path),
        "bytes": composite_path.stat().st_size,
        "reference_capture": "menu-reference-captures/beta-notice-first-boot.png",
        "reference_sha256": sha256_file(composite_reference_path),
    }
    composite_capture_time = parse_capture_time(
        composite_record["header"], str(composite_path)
    )
    latest_capture = max(latest_capture, composite_capture_time)
    for observation in composite_record["composite"]["observations"]:
        sessions.append(
            {
                "label": COMPOSITE_ID,
                "instance": observation.get("instance"),
                "process_id": observation.get("process_id"),
                "source": copy.deepcopy(observation.get("source")),
                "profile_state": copy.deepcopy(
                    observation.get("profile_state")
                ),
                "capture_method": "Settlement v2.17 semantic-dialog composite",
                "recorded_live": True,
                "captured_at_utc": observation.get("captured_at_utc"),
            }
        )

    navigation = read_object(navigation_path)
    resolution = navigation.get("header", {}).get("ambient_lifecycle_resolution")
    if (
        navigation.get("schema") != "solomon-dark-native-menu-navigation-v2"
        or not isinstance(resolution, dict)
        or resolution.get("settlement_spec") != "2.9"
    ):
        raise GoldenBuildError("navigation recording has no Settlement v2.9 resolution")
    raw_edges = navigation.get("edges")
    if not isinstance(raw_edges, list) or not raw_edges:
        raise GoldenBuildError("navigation recording contains no live edges")
    raw_by_id = {
        edge.get("id"): edge for edge in raw_edges if isinstance(edge, dict)
    }
    if len(raw_by_id) != len(raw_edges) or None in raw_by_id:
        raise GoldenBuildError("navigation recording contains ambiguous edge ids")
    landed_edges = landed.get("navigation_graph", {}).get("edges")
    if not isinstance(landed_edges, list) or not landed_edges:
        raise GoldenBuildError("landed controller graph contains no edge witness")
    landed_edge_ids = {
        edge.get("id") for edge in landed_edges if isinstance(edge, dict)
    }
    if len(landed_edge_ids) != len(landed_edges):
        raise GoldenBuildError("landed controller graph has ambiguous edge ids")
    expected_edge_ids = set(landed_edge_ids)
    expected_edge_ids.add(CHARTERED_PROFILE_NEW_GAME_EDGE["id"])
    if set(raw_by_id) != expected_edge_ids:
        raise GoldenBuildError(
            "resolved capture changed controller-traversal edge expectations"
        )
    chartered_edge = raw_by_id[CHARTERED_PROFILE_NEW_GAME_EDGE["id"]]
    if any(
        chartered_edge.get(field) != expected
        for field, expected in CHARTERED_PROFILE_NEW_GAME_EDGE.items()
    ):
        raise GoldenBuildError(
            "chartered profile-save-select New Game edge identity or measured "
            "destination changed"
        )

    edges: list[dict[str, Any]] = []
    edge_order = [edge["id"] for edge in landed_edges]
    if CHARTERED_PROFILE_NEW_GAME_EDGE["id"] not in landed_edge_ids:
        edge_order.append(CHARTERED_PROFILE_NEW_GAME_EDGE["id"])
    for edge_id in edge_order:
        raw = raw_by_id[edge_id]
        header = raw.get("header")
        before_raw = raw.get("before")
        after_raw = raw.get("after")
        if not all(isinstance(value, dict) for value in (header, before_raw, after_raw)):
            raise GoldenBuildError(f"navigation edge {edge_id} is incomplete")
        source_provenance(header, f"navigation edge {edge_id}")
        try:
            edge_profile = validate_capture_profile_state(
                repo_root=repo_root,
                header=header,
                label=f"navigation edge {edge_id}",
                evidence_root=None,
            )
            assert_navigation_baseline_allowed(
                repo_root,
                edge_id=edge_id,
                baseline_id=edge_profile["baseline_id"],
            )
        except NativeMenuProfileStateError as error:
            raise GoldenBuildError(str(error)) from error
        before = endpoint(before_raw, edge_id, "source")
        after = endpoint(after_raw, edge_id, "destination")
        header_tab_receipts = header.get("browser_tab_verification")
        for side, endpoint_name, observed in (
            ("source", "before", before),
            ("destination", "after", after),
        ):
            if observed.get("type") == "overlay":
                overlay_fixture = observed["overlay_fixture"]
                if (
                    overlay_fixture.get("sha256")
                    != sha256_file(overlay_record_path)
                    or overlay_fixture.get("bytes")
                    != overlay_record_path.stat().st_size
                    or observed.get("overlay_id")
                    != overlay_record.get("overlay_id")
                ):
                    raise GoldenBuildError(
                        f"navigation edge {edge_id} {side} records a false overlay fixture"
                    )
                recorded_endpoint_underlay = observed.get(
                    "underlying_surface", {}
                ).get("fixture")
                if (
                    not isinstance(recorded_endpoint_underlay, dict)
                    or recorded_endpoint_underlay.get("sha256")
                    != sha256_file(underlay_path)
                    or recorded_endpoint_underlay.get("bytes")
                    != underlay_path.stat().st_size
                ):
                    raise GoldenBuildError(
                        f"navigation edge {edge_id} {side} records a false overlay underlay"
                    )
                if (
                    resolve_navigation_profile_binding(
                        repo_root,
                        edge_id=edge_id,
                        endpoint=endpoint_name,
                        baseline_id=edge_profile["baseline_id"],
                    )
                    is not None
                ):
                    raise GoldenBuildError(
                        f"navigation edge {edge_id} {side} overlay leaked into a screen binding"
                    )
                continue

            layout_id = observed["layout_id"]
            if layout_id not in fixtures:
                raise GoldenBuildError(
                    f"navigation edge {edge_id} {side} does not resolve one standalone"
                )
            if layout_id == "game-settings-gameplay":
                state_id = validate_settings_path_binding(
                    fixtures[layout_id], observed, edge_id, endpoint_name
                )
                if state_id == "base" and canonical_bytes(
                    observed["layout"]
                ) != canonical_bytes(fixtures[layout_id]["layout"]):
                    raise GoldenBuildError(
                        f"navigation edge {edge_id} {side} base Settings core does not byte-equal its standalone"
                    )
            elif canonical_bytes(observed["layout"]) != canonical_bytes(
                fixtures[layout_id]["layout"]
            ):
                raise GoldenBuildError(
                    f"navigation edge {edge_id} {side} does not byte-equal "
                    f"standalone '{layout_id}'"
                )
            expected_bound_layout = resolve_navigation_profile_binding(
                repo_root,
                edge_id=edge_id,
                endpoint=endpoint_name,
                baseline_id=edge_profile["baseline_id"],
            )
            if expected_bound_layout is not None and (
                layout_id != expected_bound_layout
            ):
                raise GoldenBuildError(
                    "native-menu per-binding profile-state baseline mismatch: "
                    f"edge '{edge_id}' {side} resolves '{layout_id}' instead "
                    f"of '{expected_bound_layout}'"
                )
            header_tab_receipt = (
                header_tab_receipts.get(side)
                if isinstance(header_tab_receipts, dict)
                else None
            )
            if observed.get("browser_tab_verification") != header_tab_receipt:
                raise GoldenBuildError(
                    f"navigation edge {edge_id} {side} browser-tab receipts disagree"
                )
            try:
                validate_browser_tab(
                    screen_tag=str(observed["layout"].get("screen_id", "")),
                    layout=observed["layout"],
                    receipt=observed.get("browser_tab_verification"),
                    label=f"navigation edge {edge_id} {side}",
                )
            except NativeMenuBrowserTabError as error:
                raise GoldenBuildError(str(error)) from error
            try:
                assert_overlay_hygiene(observed["layout"], overlay)
            except OverlayV25Error as error:
                raise GoldenBuildError(
                    f"navigation edge {edge_id} {side} failed derived overlay "
                    f"hygiene: {error}"
                ) from error
        if after.get("type") == "overlay":
            destination_fixture = "menu-overlays/dark-cloud-settings.json"
            destination_type = "overlay"
            destination_state_id = None
        else:
            destination_layout_id = after["layout_id"]
            destination_fixture = (
                f"menu-transition-layouts/{destination_layout_id}.json"
                if destination_layout_id in transition_paths
                else f"menu-layouts/{destination_layout_id}.json"
            )
            destination_type = "layout"
            destination_state_id = (
                after.get("path_dependent_core", {}).get("state_id")
                if destination_layout_id == "game-settings-gameplay"
                else None
            )
        observed_at = raw.get("observed_at_utc")
        if not isinstance(observed_at, str) or not observed_at:
            raise GoldenBuildError(f"navigation edge {edge_id} has no observation time")
        edges.append(
            {
                "header": copy.deepcopy(header),
                "id": edge_id,
                "screen": raw.get("source"),
                "edge": raw.get("trigger"),
                "trigger": raw.get("trigger"),
                "action_id": raw.get("action_id"),
                "destination": raw.get("destination"),
                "destination_type": destination_type,
                "destination_layout_fixture": destination_fixture,
                **(
                    {"destination_layout_state_id": destination_state_id}
                    if destination_state_id is not None
                    else {}
                ),
                "dispatch_result": raw.get("dispatch_result"),
                "before": before,
                "after": after,
                "observed_at_utc": observed_at,
            }
        )

    composite_observations = composite_record["composite"]["observations"]
    composite_primary = next(
        observation
        for observation in composite_observations
        if observation.get("role") == "primary"
    )
    picker_fixture = fixtures["control-scheme-picker"]
    picker_header = picker_fixture["header"]
    picker_layout = picker_fixture["layout"]
    composite_edge_id = "beta_notice_first_boot_to_control_scheme_picker"
    if any(edge.get("id") == composite_edge_id for edge in edges):
        raise GoldenBuildError(
            "semantic dialog composite dismissal edge identity is ambiguous"
        )
    edges.append(
        {
            "header": {
                "label": composite_edge_id,
                "instance": composite_primary["instance"],
                "process_id": composite_primary["process_id"],
                "source": copy.deepcopy(composite_primary["source"]),
                "profile_state": copy.deepcopy(
                    composite_primary["profile_state"]
                ),
                "capture_method": (
                    "Settlement v2.17 semantic-dialog composite measured "
                    "dismissal"
                ),
                "recorded_live": True,
                "captured_at_utc": composite_primary["captured_at_utc"],
            },
            "id": composite_edge_id,
            "screen": COMPOSITE_ID,
            "edge": "dialog_primary",
            "trigger": "dialog_primary",
            "action_id": "dialog.primary",
            "destination": "control_scheme_picker",
            "destination_type": "layout",
            "destination_layout_fixture": (
                "menu-layouts/control-scheme-picker.json"
            ),
            "dispatch_result": "clicked_measured_top_plate",
            "before": {
                "type": "dialog_composite",
                "composite_id": COMPOSITE_ID,
                "composite_fixture": {
                    "fixture": (
                        "menu-dialog-composites/beta-notice-first-boot.json"
                    ),
                    "sha256": sha256_file(composite_path),
                    "bytes": composite_path.stat().st_size,
                },
                "underlay_surface_id": "control_scheme_picker",
                "player_visible_frame_sha256": composite_classification[
                    "player_visible_dialog_frame_sha256"
                ],
                "settlement": {
                    "settlement_spec": "2.17",
                    "consecutive_structural_samples": composite_primary[
                        "settled_sample_count"
                    ],
                    "stable_span_milliseconds": composite_primary[
                        "stable_span_milliseconds"
                    ],
                    "settle_latency_milliseconds": composite_primary[
                        "settle_latency_milliseconds"
                    ],
                },
            },
            "after": {
                "semantic_surface": "control_scheme_picker",
                "machine_classified_surface": "control_scheme_picker",
                "semantic_generation": picker_layout["generation"],
                "tagged_screen": "control_scheme_picker",
                "layout_generation": picker_layout["generation"],
                "element_count": len(picker_layout["elements"]),
                "capture_method": picker_header["capture_method"],
                "frame_sha256": composite_classification[
                    "post_dismissal_underlay_frame_sha256"
                ],
                "settlement": copy.deepcopy(picker_header["settlement"]),
                "layout": copy.deepcopy(picker_layout),
                "layout_id": "control-scheme-picker",
                "animated_element_ids": copy.deepcopy(
                    picker_layout["animated_element_ids"]
                ),
                "animated_family_ids": copy.deepcopy(
                    picker_layout["animated_family_ids"]
                ),
                "choice_slot_ids": copy.deepcopy(
                    picker_layout["choice_slot_ids"]
                ),
                "browser_tab_verification": copy.deepcopy(
                    picker_header.get("browser_tab_verification")
                ),
            },
            "observed_at_utc": composite_primary["captured_at_utc"],
        }
    )

    unique_sessions: dict[bytes, dict[str, Any]] = {}
    for session in sessions:
        key = canonical_bytes(session)
        unique_sessions.setdefault(key, session)
    try:
        profile_baseline = load_profile_state_baseline(repo_root)
        profile_bindings = load_hub_binding_contract(repo_root)
    except NativeMenuProfileStateError as error:
        raise GoldenBuildError(str(error)) from error
    golden = {
        "schema": "solomon-dark-menu-goldens-v3",
        "header": {
            "campaign": "menufix",
            "gap": "G11",
            "generated_from_live_capture_at_utc": latest_capture.isoformat(),
            "capture_method": (
                "Settlement v2.17 reproduced structural cores, animated families, "
                "choice slots, and canonical "
                "relative draw order, measured ambient lifecycle and motion "
                "envelopes, path-dependent cores, non-semantic overlays, "
                "semantic-dialog composites, "
                "native Sprite/text hooks, live D3D9 frames, "
                "exact-process input, and independent fresh-instance confirmation"
            ),
            "raw_recording": {
                "evidence_filename": navigation_path.name,
                "sha256": sha256_file(navigation_path),
                "bytes": navigation_path.stat().st_size,
            },
            "ambient_lifecycle_resolution": copy.deepcopy(resolution),
            "overlay_reference": {
                "fixture": "menu-overlay-reference.json",
                "sha256": sha256_file(overlay_path),
                "bytes": overlay_path.stat().st_size,
            },
            "profile_state_baseline": {
                "fixture": (
                    "native-menu-profile-state-baseline.json"
                ),
                "sha256": profile_baseline["sha256"],
                "bytes": profile_baseline["bytes"],
                "profile_state_identity_sha256": profile_baseline[
                    "identity"
                ],
                "corrective": "shellfix task #101 consumes the settled corpus",
            },
            "profile_state_bindings": {
                "fixture": "native-menu-hub-bindings-v213.json",
                "sha256": profile_bindings["sha256"],
                "bytes": profile_bindings["bytes"],
                "baseline_ids": sorted(profile_bindings["baselines"]),
                "corrective": (
                    "Settlement v2.13 qualifies every layout and edge by an "
                    "exact legitimate baseline"
                ),
            },
            "screen_count": len(fixtures),
            "standalone_layout_count": len(wrappers),
            "path_dependent_layout_count": len(transition_wrappers),
            "layout_count": len(fixtures),
            "overlay_count": 1,
            "semantic_dialog_composite_count": 1,
            "state_count": len(fixtures) + 2,
            "edge_count": len(edges),
            "sessions": list(unique_sessions.values()),
        },
        "screen_census": sorted(fixtures),
        "overlay_census": [overlay_record["overlay_id"]],
        "semantic_dialog_composite_census": [COMPOSITE_ID],
        "layouts": sorted(wrappers, key=lambda wrapper: wrapper["fixture"]),
        "transition_endpoint_layouts": transition_wrappers,
        "overlay_records": [overlay_wrapper],
        "semantic_dialog_composite_records": [composite_wrapper],
        "navigation_graph": {
            "capture_method": navigation.get("header", {}).get("capture_method"),
            "edges": edges,
        },
    }
    write_object(output_path, golden)
    return {
        "success": True,
        "output": str(output_path),
        "screen_count": len(fixtures),
        "overlay_count": 1,
        "semantic_dialog_composite_count": 1,
        "state_count": len(fixtures) + 2,
        "edge_count": len(edges),
        "sha256": sha256_file(output_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = build(
            args.repo_root.resolve(),
            args.fixture_root.resolve(),
            args.navigation_recording.resolve(),
            args.output.resolve(),
        )
    except (GoldenBuildError, OSError, KeyError, TypeError, ValueError) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
