#!/usr/bin/env python3
"""Derive the controls navigation failure mechanism from sealed live records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


MAIN_TO_SETTINGS = "controls_corroboration_main_to_settings"
SETTINGS_TO_CONTROLS = "controls_corroboration_settings_to_controls"
CONTROLS_TO_SETTINGS = "controls_corroboration_controls_to_settings"
STALE_MARKER = "exact live-navigation screen tag (stale controls omitted)"
CAPTURE_API_PATH = (
    "SolomonDarkModLoader/src/debug_ui_overlay/"
    "public_api_surface_dispatch.inl"
)
TRANSITION_RECORDER_PATH = "scripts/Record-NativeMenuTransition.ps1"
ACTION_TICK_PATH = (
    "SolomonDarkModLoader/src/debug_ui_overlay/public_api_actions.inl"
)
ACTION_DISPATCH_PATH = (
    "SolomonDarkModLoader/src/debug_ui_overlay/"
    "state_and_actions_requests_and_reset.inl"
)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_receipt(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_bytes(path.read_bytes()),
    }


def git_blob(repo: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def one_edge(document: dict[str, Any], edge_id: str) -> dict[str, Any]:
    matches = [
        edge
        for edge in document.get("edges", [])
        if isinstance(edge, dict) and edge.get("id") == edge_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"controls navigation audit expected exactly one {edge_id}; "
            f"found {len(matches)}"
        )
    return matches[0]


def elements(observation: dict[str, Any], label: str) -> list[dict[str, Any]]:
    layout = observation.get("layout")
    values = layout.get("elements") if isinstance(layout, dict) else None
    if not isinstance(values, list) or not values or not all(
        isinstance(value, dict) for value in values
    ):
        raise ValueError(f"{label} reached no real layout elements")
    return values


def settled_count(observation: dict[str, Any], label: str) -> tuple[int, int]:
    settlement = observation.get("settlement")
    trace = observation.get("settlement_trace")
    samples = trace.get("settled_window_samples") if isinstance(trace, dict) else None
    if not isinstance(settlement, dict) or not isinstance(samples, list):
        raise ValueError(f"{label} has no settled-window evidence")
    count = settlement.get("consecutive_structural_samples")
    span = settlement.get("stable_span_milliseconds")
    if count != len(samples) or count < 40 or not isinstance(span, int) or span < 2000:
        raise ValueError(f"{label} did not meet the settlement floor")
    return count, span


def frame_directory(route_path: Path) -> Path:
    matches = [
        path
        for path in route_path.parent.iterdir()
        if path.is_dir()
        and path.name.startswith(route_path.stem)
        and path.name.endswith(".frames")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"controls navigation audit found ambiguous frame directories for "
            f"{route_path}: {[str(path) for path in matches]}"
        )
    return matches[0]


def frame_receipt(
    route_path: Path, edge: dict[str, Any], side: str
) -> dict[str, Any]:
    raw_frames = edge.get("header", {}).get("raw_frames", {})
    raw = raw_frames.get(side) if isinstance(raw_frames, dict) else None
    if not isinstance(raw, dict) or not isinstance(raw.get("evidence_filename"), str):
        raise ValueError(f"{edge.get('id')} {side} has no raw-frame receipt")
    path = frame_directory(route_path) / raw["evidence_filename"]
    receipt = file_receipt(path)
    if receipt["sha256"] != raw.get("sha256") or receipt["bytes"] != raw.get("bytes"):
        raise ValueError(f"{edge.get('id')} {side} raw frame does not match its receipt")
    return receipt


def click_point(dispatch_result: Any) -> tuple[float, float]:
    match = re.fullmatch(
        r"exact_owned_client_click=([-+]?[0-9]+(?:\.[0-9]+)?),"
        r"([-+]?[0-9]+(?:\.[0-9]+)?)",
        str(dispatch_result),
    )
    if match is None:
        raise ValueError("controls route does not record an exact client click")
    return float(match.group(1)), float(match.group(2))


def rect_contains(rect: Any, x: float, y: float) -> bool:
    return (
        isinstance(rect, list)
        and len(rect) == 4
        and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in rect)
        and min(rect[0], rect[2]) <= x <= max(rect[0], rect[2])
        and min(rect[1], rect[3]) <= y <= max(rect[1], rect[3])
    )


def element_witness(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: element.get(key)
        for key in (
            "id",
            "kind",
            "text",
            "action_id",
            "art_id",
            "visible",
            "interactive",
            "draw_order",
            "rect",
            "unclipped_rect",
        )
    }


def observation_witness(
    route_path: Path,
    edge: dict[str, Any],
    side: str,
) -> dict[str, Any]:
    observation = edge.get(side)
    if not isinstance(observation, dict):
        raise ValueError(f"{edge.get('id')} has no {side} observation")
    count, span = settled_count(observation, f"{edge.get('id')} {side}")
    values = elements(observation, f"{edge.get('id')} {side}")
    return {
        "semantic_surface": observation.get("semantic_surface"),
        "operator_tag": observation.get("tagged_screen"),
        "layout_generation": observation.get("layout_generation"),
        "element_count": observation.get("element_count"),
        "capture_method": observation.get("capture_method"),
        "settled_sample_count": count,
        "stable_span_milliseconds": span,
        "kind_census": dict(sorted(Counter(str(value.get("kind")) for value in values).items())),
        "art_census": dict(
            sorted(
                Counter(
                    str(value.get("art_id"))
                    for value in values
                    if value.get("art_id")
                ).items()
            )
        ),
        "text_values": [
            value.get("text") for value in values if value.get("text")
        ],
        "action_ids": [
            value.get("action_id") for value in values if value.get("action_id")
        ],
        "frame": frame_receipt(route_path, edge, side),
    }


def route_witness(route_path: Path, document: dict[str, Any]) -> dict[str, Any]:
    sessions = document.get("header", {}).get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError(f"{route_path} has no session identities")
    identities = {
        (value.get("instance"), value.get("process_id"))
        for value in sessions
        if isinstance(value, dict)
    }
    if len(identities) != 1:
        raise ValueError(f"{route_path} has ambiguous session identities")
    instance, process_id = next(iter(identities))

    main_to_settings = one_edge(document, MAIN_TO_SETTINGS)
    settings_to_controls = one_edge(document, SETTINGS_TO_CONTROLS)
    controls_to_settings = one_edge(document, CONTROLS_TO_SETTINGS)
    click_x, click_y = click_point(settings_to_controls.get("dispatch_result"))
    source = settings_to_controls["before"]
    source_elements = elements(source, f"{SETTINGS_TO_CONTROLS} before")
    hits = [
        element_witness(element)
        for element in source_elements
        if rect_contains(element.get("rect"), click_x, click_y)
    ]
    interactive_hits = [value for value in hits if value.get("interactive")]
    if interactive_hits:
        raise ValueError(
            "rejected controls click unexpectedly has a classifier-visible "
            "interactive source affordance"
        )

    witness = {
        "route": file_receipt(route_path),
        "instance": instance,
        "process_id": process_id,
        "main_to_settings_after": observation_witness(
            route_path, main_to_settings, "after"
        ),
        "main_to_settings_dispatch": {
            "trigger": main_to_settings.get("trigger"),
            "request_id_only": main_to_settings.get("dispatch_result"),
            "completion_status_recorded": False,
        },
        "settings_to_controls_before": observation_witness(
            route_path, settings_to_controls, "before"
        ),
        "settings_to_controls_dispatch": {
            "recorded_result": settings_to_controls.get("dispatch_result"),
            "client_point": [click_x, click_y],
            "classifier_visible_rect_hits": hits,
            "classifier_visible_interactive_hit_count": len(interactive_hits),
            "coordinate_provenance": (
                "operator-supplied ClientX/ClientY; the route schema contains no "
                "live-control-rect receipt"
            ),
        },
        "settings_to_controls_after": observation_witness(
            route_path, settings_to_controls, "after"
        ),
        "controls_to_settings_before": observation_witness(
            route_path, controls_to_settings, "before"
        ),
    }
    for key in (
        "main_to_settings_after",
        "settings_to_controls_before",
        "settings_to_controls_after",
        "controls_to_settings_before",
    ):
        value = witness[key]
        if value["semantic_surface"] != "main_menu" or STALE_MARKER not in value["capture_method"]:
            raise ValueError(f"{route_path} no longer reproduces {key} classifier disagreement")
    if witness["settings_to_controls_before"]["operator_tag"] != "settings":
        raise ValueError("controls source no longer reproduces the settings operator tag")
    if witness["settings_to_controls_after"]["operator_tag"] != "controls":
        raise ValueError("controls destination no longer reproduces the controls operator tag")
    if (
        witness["main_to_settings_dispatch"]["trigger"] != "main_menu.settings"
        or not str(
            witness["main_to_settings_dispatch"]["request_id_only"]
        ).isdigit()
    ):
        raise ValueError("controls route no longer reproduces its queued Settings action")
    return witness


def source_mechanism(repo: Path, commit: str) -> dict[str, Any]:
    capture_api = git_blob(repo, commit, CAPTURE_API_PATH)
    transition = git_blob(repo, commit, TRANSITION_RECORDER_PATH)
    action_tick = git_blob(repo, commit, ACTION_TICK_PATH)
    action_dispatch = git_blob(repo, commit, ACTION_DISPATCH_PATH)
    capture_text = capture_api.decode("utf-8")
    transition_text = transition.decode("utf-8")
    action_tick_text = action_tick.decode("utf-8")
    action_dispatch_text = action_dispatch.decode("utf-8")
    required_capture_tokens = (
        "const auto classification_agrees =",
        "if (!classification_agrees)",
        "std::remove_if",
        "stale controls omitted",
        "captured.screen_id = std::string(screen_id)",
    )
    missing_capture = [token for token in required_capture_tokens if token not in capture_text]
    if missing_capture:
        raise ValueError(f"capture base commit lacks mismatch-retag witnesses: {missing_capture}")
    required_transition_tokens = (
        '[string]$ExpectedSourceSurface = ""',
        '[string]$ExpectedDestinationSurface = ""',
        "[string]::IsNullOrWhiteSpace($ExpectedSourceSurface)",
        "[string]::IsNullOrWhiteSpace($ExpectedDestinationSurface)",
        "[float]$ClientX",
        "[float]$ClientY",
    )
    missing_transition = [
        token for token in required_transition_tokens if token not in transition_text
    ]
    if missing_transition:
        raise ValueError(
            f"capture base commit lacks optional-gate/click witnesses: {missing_transition}"
        )
    required_action_tick_tokens = (
        "void DispatchPendingDebugUiActionOnAppTick()",
        "DispatchPendingSemanticUiActionRequest();",
    )
    required_action_dispatch_tokens = (
        "active_semantic_ui_action_dispatch.status = \"dispatching\"",
        "const auto dispatched = ::sdmod::TryActivateDebugUiSnapshotElement",
        "StoreCompletedSemanticUiActionDispatchUnlocked",
    )
    missing_action = [
        token
        for token in required_action_tick_tokens
        if token not in action_tick_text
    ] + [
        token
        for token in required_action_dispatch_tokens
        if token not in action_dispatch_text
    ]
    if missing_action:
        raise ValueError(
            f"capture base commit lacks synchronous modal-dispatch witnesses: {missing_action}"
        )
    return {
        "base_commit_sha": commit,
        "capture_api": {
            "repository_path": CAPTURE_API_PATH,
            "blob_sha256": sha256_bytes(capture_api),
            "mechanism_tokens": list(required_capture_tokens),
        },
        "transition_recorder": {
            "repository_path": TRANSITION_RECORDER_PATH,
            "blob_sha256": sha256_bytes(transition),
            "mechanism_tokens": list(required_transition_tokens),
        },
        "app_tick_action_dispatch": {
            "tick_repository_path": ACTION_TICK_PATH,
            "tick_blob_sha256": sha256_bytes(action_tick),
            "dispatch_repository_path": ACTION_DISPATCH_PATH,
            "dispatch_blob_sha256": sha256_bytes(action_dispatch),
            "mechanism_tokens": [
                *required_action_tick_tokens,
                *required_action_dispatch_tokens,
            ],
            "interpretation": (
                "the app-tick dispatcher marks the request dispatching, calls the "
                "native activation synchronously, and records completion only after "
                "that activation returns; a nested modal can therefore render while "
                "the outer capture state remains the preceding surface"
            ),
        },
    }


def build_audit(
    repo: Path,
    capture_base_commit: str,
    primary_route_path: Path,
    confirmation_route_path: Path,
    rejected_v8_audit_path: Path,
) -> dict[str, Any]:
    primary = route_witness(primary_route_path, read_object(primary_route_path))
    confirmation = route_witness(
        confirmation_route_path, read_object(confirmation_route_path)
    )
    if (primary["instance"], primary["process_id"]) == (
        confirmation["instance"],
        confirmation["process_id"],
    ):
        raise ValueError("controls navigation diagnosis did not reach two fresh instances")
    rejected = read_object(rejected_v8_audit_path)
    if rejected.get("finding") != "controls_tag_settled_on_main_menu_surface":
        raise ValueError("v8 rejected-candidate audit no longer carries its finding")
    points = {
        tuple(primary["settings_to_controls_dispatch"]["client_point"]),
        tuple(confirmation["settings_to_controls_dispatch"]["client_point"]),
    }
    if len(points) != 1:
        raise ValueError("controls driver did not reproduce one deterministic click point")
    return {
        "schema": "solomon-dark-native-menu-controls-navigation-failure-audit-v1",
        "status": "ROOT_CAUSE_PROVEN",
        "inputs": {
            "rejected_v8_candidate_audit": file_receipt(rejected_v8_audit_path),
            "source_mechanism": source_mechanism(repo, capture_base_commit),
        },
        "fresh_instance_routes": [primary, confirmation],
        "answers": {
            "machine_classified_surface_immediately_before_customize_keyboard_click": (
                "main_menu in both fresh instances"
            ),
            "did_driver_reach_classifier_agreed_settings": False,
            "did_driver_visually_reach_settings": True,
            "rendered_settings_phase": (
                "the preceding main_to_settings after-frame visibly carried the full "
                "GAME SETTINGS panel, but the recorder already marked the payload as "
                "a classifier disagreement; the later source frame settled on the "
                "empty panel shell over main-menu content"
            ),
            "click_point_origin": (
                "a repeated operator-supplied fixed ClientX/ClientY pair; neither route "
                "records a live measured control rectangle, and the landed fixture has "
                "no CUSTOMIZE KEYBOARD control from which to derive it"
            ),
            "live_affordance_at_recorded_source": (
                "no classifier-visible interactive affordance; the point intersects "
                "only the main-menu third-button UI.101 plate and UI.54 right ornament"
            ),
            "native_click_effect": (
                "the following raw frame visibly rendered CUSTOMIZE KEYBOARD, so the "
                "native modal owner still accepted the point as its Customize control; "
                "the recorder nevertheless classified and later retained only a "
                "main-menu remnant"
            ),
        },
        "mechanism": (
            "The driver did not fail because the SETTINGS click silently did nothing, "
            "nor because a four-second delay sampled mid-transition. The native capture "
            "API explicitly converted a classifier mismatch into a stripped art/text "
            "snapshot, rewrote its screen_id to the operator label, and the transition "
            "recorder made its source/destination checks optional. The Settings action "
            "was queued through a synchronous app-tick activation path, while the route "
            "persisted only the request id rather than a completion receipt. That "
            "combination "
            "turned a stable main_menu-classified blank-shell state into 'settings', "
            "then turned the later main_menu remnant into 'controls', allowing the "
            "driver to proceed and the standalone recorder to persist the wrong surface."
        ),
        "required_fix": (
            "remove mismatch relabeling, make classifier/tag equality mandatory for "
            "standalones and both edge endpoints, and verify each classifier-confirmed "
            "destination before any subsequent navigation step"
        ),
    }


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
    parser.add_argument("--capture-base-commit", required=True)
    parser.add_argument("--primary-route", type=Path, required=True)
    parser.add_argument("--confirmation-route", type=Path, required=True)
    parser.add_argument("--rejected-v8-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = build_audit(
        args.repo_root.resolve(),
        args.capture_base_commit,
        args.primary_route.resolve(),
        args.confirmation_route.resolve(),
        args.rejected_v8_audit.resolve(),
    )
    write_object(args.output.resolve(), audit)
    print(json.dumps(audit, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
