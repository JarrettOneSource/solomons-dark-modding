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
    NativeMenuProfileStateError,
    load_profile_state_baseline,
    validate_capture_profile_state,
)
from native_menu_browser_tab import (
    NativeMenuBrowserTabError,
    validate_browser_tab,
)


class GoldenBuildError(RuntimeError):
    """The candidate corpus is incomplete, ambiguous, or internally divergent."""


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
    return fixture, {
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


def standalone_settled_pair(
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
    if canonical_bytes(header.get("source")) != canonical_bytes(
        confirmation_header.get("source")
    ):
        raise GoldenBuildError(f"{path} confirmation changed native provenance")
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
    )
    return {
        field: copy.deepcopy(value.get(field))
        for field in fields
        if field in value
    }


def capture_session(header: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": header.get("label"),
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "source": copy.deepcopy(header.get("source")),
        "profile_state": copy.deepcopy(header.get("profile_state")),
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
        fixture_root / "menu-layouts", 28, "main-menu-root"
    )
    transition_paths = unique_json_files(
        fixture_root / "menu-transition-layouts", 2, "hub_new_game"
    )
    if set(transition_paths) != {"hub_new_game", "hub_resumed"}:
        raise GoldenBuildError(
            "path-dependent core contract: transition fixture census is not the "
            "two authorized Hub layouts"
        )
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
            if layout_id in {"hub_new_game", "hub_resumed"}
            else wrappers
        ).append(wrapper)
        observed = parse_capture_time(fixture["header"], str(path))
        latest_capture = observed if latest_capture is None else max(latest_capture, observed)
        sessions.append(capture_session(fixture["header"]))
    if len(fixtures) != 30 or latest_capture is None:
        raise GoldenBuildError(
            "aggregate fixture sweep did not reach 28 menus plus two Hub layouts"
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
            layout_paths["beta-notice"],
            fixture_root,
            fixtures["beta-notice"],
        )
        main_primary, main_confirmation = standalone_settled_pair(
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
    expected_edge_ids = {
        edge.get("id") for edge in landed_edges if isinstance(edge, dict)
    }
    if len(expected_edge_ids) != len(landed_edges) or set(raw_by_id) != expected_edge_ids:
        raise GoldenBuildError(
            "resolved capture changed controller-traversal edge expectations"
        )

    edges: list[dict[str, Any]] = []
    for edge_id in [edge["id"] for edge in landed_edges]:
        raw = raw_by_id[edge_id]
        header = raw.get("header")
        before_raw = raw.get("before")
        after_raw = raw.get("after")
        if not all(isinstance(value, dict) for value in (header, before_raw, after_raw)):
            raise GoldenBuildError(f"navigation edge {edge_id} is incomplete")
        source_provenance(header, f"navigation edge {edge_id}")
        try:
            validate_capture_profile_state(
                repo_root=repo_root,
                header=header,
                label=f"navigation edge {edge_id}",
                evidence_root=None,
            )
        except NativeMenuProfileStateError as error:
            raise GoldenBuildError(str(error)) from error
        before = endpoint(before_raw, edge_id, "source")
        after = endpoint(after_raw, edge_id, "destination")
        header_tab_receipts = header.get("browser_tab_verification")
        for side, observed in (("source", before), ("destination", after)):
            layout_id = observed["layout_id"]
            if layout_id not in fixtures:
                raise GoldenBuildError(
                    f"navigation edge {edge_id} {side} does not resolve one standalone"
                )
            if canonical_bytes(observed["layout"]) != canonical_bytes(
                fixtures[layout_id]["layout"]
            ):
                raise GoldenBuildError(
                    f"navigation edge {edge_id} {side} does not byte-equal "
                    f"standalone '{layout_id}'"
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
        destination_layout_id = after["layout_id"]
        destination_fixture = (
            f"menu-transition-layouts/{destination_layout_id}.json"
            if destination_layout_id in transition_paths
            else f"menu-layouts/{destination_layout_id}.json"
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
                "destination_layout_fixture": destination_fixture,
                "dispatch_result": raw.get("dispatch_result"),
                "before": before,
                "after": after,
                "observed_at_utc": observed_at,
            }
        )

    unique_sessions: dict[bytes, dict[str, Any]] = {}
    for session in sessions:
        key = canonical_bytes(session)
        unique_sessions.setdefault(key, session)
    try:
        profile_baseline = load_profile_state_baseline(repo_root)
    except NativeMenuProfileStateError as error:
        raise GoldenBuildError(str(error)) from error
    golden = {
        "schema": "solomon-dark-menu-goldens-v3",
        "header": {
            "campaign": "menufix",
            "gap": "G11",
            "generated_from_live_capture_at_utc": latest_capture.isoformat(),
            "capture_method": (
                "Settlement v2.9 reproduced structural cores, animated families, "
                "choice slots, and canonical "
                "relative draw order, measured ambient lifecycle and motion "
                "envelopes, native Sprite/text hooks, live D3D9 frames, "
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
            "screen_count": len(wrappers),
            "edge_count": len(edges),
            "sessions": list(unique_sessions.values()),
        },
        "screen_census": sorted(layout_paths),
        "layouts": sorted(wrappers, key=lambda wrapper: wrapper["fixture"]),
        "transition_endpoint_layouts": transition_wrappers,
        "navigation_graph": {
            "capture_method": navigation.get("header", {}).get("capture_method"),
            "edges": edges,
        },
    }
    write_object(output_path, golden)
    return {
        "success": True,
        "output": str(output_path),
        "screen_count": len(wrappers),
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
