#!/usr/bin/env python3
"""Resolve a complete native-menu campaign under Settlement v2.9."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

if __package__:
    from .native_menu_ambient_lifecycle import (
        AmbientLifecycleError,
        SETTLEMENT_SPEC,
        canonical_bytes,
        classify_ambient_window,
        resolve_ambient_lifecycle,
        sha256_json,
    )
    from .native_menu_profile_state import (
        FRESH_BASELINE_ID,
        NativeMenuProfileStateError,
        assert_navigation_baseline_allowed,
        load_hub_binding_contract,
        required_baseline_for_layout,
        resolve_navigation_profile_binding,
        validate_exact_hub_layout_pair,
        validate_capture_profile_state,
    )
    from .native_menu_browser_tab import (
        NativeMenuBrowserTabError,
        validate_browser_tab,
    )
else:
    from native_menu_ambient_lifecycle import (  # type: ignore[no-redef]
        AmbientLifecycleError,
        SETTLEMENT_SPEC,
        canonical_bytes,
        classify_ambient_window,
        resolve_ambient_lifecycle,
        sha256_json,
    )
    from native_menu_profile_state import (  # type: ignore[no-redef]
        FRESH_BASELINE_ID,
        NativeMenuProfileStateError,
        assert_navigation_baseline_allowed,
        load_hub_binding_contract,
        required_baseline_for_layout,
        resolve_navigation_profile_binding,
        validate_exact_hub_layout_pair,
        validate_capture_profile_state,
    )
    from native_menu_browser_tab import (  # type: ignore[no-redef]
        NativeMenuBrowserTabError,
        validate_browser_tab,
    )


class CampaignResolutionError(RuntimeError):
    """The campaign inputs do not prove one unambiguous v2.9 result."""


NAVIGATION_ENDPOINT_LAYOUT_IDS = {
    ("main_to_settings", "after"): "game-settings-title",
    ("settings_to_main", "before"): "game-settings-title",
    ("dark_cloud_menu_to_settings", "after"): "game-settings-dark-cloud",
    ("dark_cloud_settings_done", "before"): "game-settings-dark-cloud",
    ("settings_to_hub", "before"): "game-settings-gameplay",
    ("pause_to_game_settings", "after"): "game-settings-gameplay",
    ("settings_to_controls", "before"): "game-settings-title",
    ("controls_to_settings", "after"): "game-settings-title",
    ("settings_to_performance", "before"): "game-settings-gameplay",
    ("performance_to_settings", "after"): "game-settings-gameplay",
    ("settings_to_dark_cloud_settings", "before"): "game-settings-gameplay",
    ("dark_cloud_settings_to_settings", "after"): "game-settings-gameplay",
    ("hub_to_pause", "before"): "hub_resumed",
    ("pause_to_hub_resume", "after"): "hub_resumed",
    ("profile_select_resume_to_hub", "after"): "hub_resumed",
    ("settings_to_hub", "after"): "hub_resumed",
}

PATH_DEPENDENT_CORE_LAYOUTS = {
    "hub_pristine_second_new_game": {
        "parent_screen_id": "hub",
        "path_qualifier": "pristine_second_new_game",
        "selector": (
            "profile_baseline:pristine_fresh_install;entry_path:"
            "first_run_hub_to_main_then_new_game_create_to_hub;same_process"
        ),
        "required_baseline_id": "pristine_fresh_install",
    },
    "hub_new_game": {
        "parent_screen_id": "hub",
        "path_qualifier": "new_game_derived_two_action",
        "selector": (
            "profile_baseline:hub_new_game_two_action_v213;entry_path:"
            "direct_new_game_create_to_hub"
        ),
        "required_baseline_id": "hub_new_game_two_action_v213",
    },
    "hub_resumed": {
        "parent_screen_id": "hub",
        "path_qualifier": "resumed",
        "selector": "session_state:resumed_run",
        "required_baseline_id": "pristine_fresh_install",
    },
}

PATH_DEPENDENT_CORE_ENDPOINTS = {
    ("create_discipline_to_hub", "after"): "hub_pristine_second_new_game",
    ("hub_to_pause", "before"): "hub_resumed",
    ("pause_to_hub_resume", "after"): "hub_resumed",
    ("profile_select_resume_to_hub", "after"): "hub_resumed",
    ("settings_to_hub", "after"): "hub_resumed",
}

PATH_DEPENDENT_BASELINE_ALIASES = {
    "hub_resumed": (
        "hub.json",
        "hub.confirmation.json",
        "hub-primary.baseline.json",
        "hub-confirmation.baseline.json",
    ),
}

RUNTIME_PROVENANCE_FIELDS = (
    "game_executable_sha256",
    "loader_dll_sha256",
)
NAVIGATION_GAME_PROVENANCE_FIELD = "game_executable_sha256"

CHOICE_SLOT_RULING_EVIDENCE = {
    "choice_core_stop_audit": (
        "raw-final/diagnostics/skill-picker-v27-choice-core-stop-audit.json"
    ),
    "choice_core_resolver_transcript": (
        "raw-final/diagnostics/skill-picker-v27-choice-core-full-resolver-stop.log"
    ),
    "choice_core_stop_manifest": (
        "raw-final/diagnostics/skill-picker-v27-choice-core-stop-manifest.json"
    ),
}


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise CampaignResolutionError(f"{path} is not a JSON object")
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
        raise CampaignResolutionError(
            f"evidence path escapes the campaign root: {path}"
        )
    return {
        "evidence_path": resolved.relative_to(root).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def choice_slot_ruling_receipts(
    evidence_root: Path,
) -> dict[str, dict[str, Any]]:
    root = evidence_root.resolve()
    receipts: dict[str, dict[str, Any]] = {}
    for label, relative in CHOICE_SLOT_RULING_EVIDENCE.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise CampaignResolutionError(
                "choice-slot provenance contract: accepted ruling evidence "
                f"'{relative}' is absent"
            )
        receipts[label] = evidence_receipt(path, root)
    if set(receipts) != set(CHOICE_SLOT_RULING_EVIDENCE):
        raise CampaignResolutionError(
            "choice-slot provenance contract: diagnostic receipt census is incomplete"
        )
    return receipts


def resolve_unique_evidence(
    evidence_root: Path, adjacent: Path, filename: str
) -> Path:
    if not filename:
        raise CampaignResolutionError("evidence lookup received an empty filename")
    conventional = (adjacent / filename).resolve()
    if conventional.is_file():
        return conventional
    candidates = {
        path.resolve() for path in evidence_root.rglob(filename) if path.is_file()
    }
    if len(candidates) != 1:
        raise CampaignResolutionError(
            f"evidence lookup for {filename!r} is absent or ambiguous: "
            f"{sorted(str(path) for path in candidates)}"
        )
    return candidates.pop()


def validate_receipt(path: Path, receipt: dict[str, Any], label: str) -> None:
    if path.stat().st_size != receipt.get("bytes"):
        raise CampaignResolutionError(f"{label} records a false evidence byte count")
    if file_sha256(path) != receipt.get("sha256"):
        raise CampaignResolutionError(f"{label} records a false evidence SHA-256")


def resolve_exact_evidence_receipt(
    evidence_root: Path, receipt: object, label: str
) -> Path:
    if not isinstance(receipt, dict):
        raise CampaignResolutionError(f"{label} has no exact evidence receipt")
    relative = receipt.get("evidence_path")
    if not isinstance(relative, str) or not relative:
        raise CampaignResolutionError(f"{label} receipt has no evidence path")
    root = evidence_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise CampaignResolutionError(
            f"{label} receipt resolves outside the evidence root or is absent"
        )
    validate_receipt(path, receipt, label)
    return path


def resolve_baseline_evidence(
    observation_root: Path,
    receipt: dict[str, Any],
    label: str,
) -> tuple[Path, dict[str, Any]]:
    recorded_sha256 = receipt.get("sha256")
    recorded_bytes = receipt.get("bytes")
    selector = receipt.get("selector")
    if (
        not isinstance(recorded_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", recorded_sha256)
        or isinstance(recorded_bytes, bool)
        or not isinstance(recorded_bytes, int)
        or recorded_bytes <= 0
        or not isinstance(selector, dict)
        or not isinstance(selector.get("schema"), str)
    ):
        raise CampaignResolutionError(
            f"{label} baseline receipt is incomplete or malformed"
        )

    examined = 0
    matches: list[Path] = []
    for path in sorted(observation_root.rglob("*.json")):
        if not path.is_file():
            continue
        examined += 1
        if path.stat().st_size != recorded_bytes:
            continue
        if file_sha256(path) == recorded_sha256:
            matches.append(path.resolve())
    if examined == 0:
        raise CampaignResolutionError(
            f"{label} baseline evidence sweep reached no JSON content"
        )
    if len(matches) != 1:
        raise CampaignResolutionError(
            "extended observation baseline receipt does not resolve exactly "
            f"one byte-identical evidence file for {label}: "
            f"{[str(path) for path in matches]}"
        )

    baseline_path = matches[0]
    validate_receipt(baseline_path, receipt, label + " baseline")
    baseline_recording = read_object(baseline_path)
    if baseline_recording.get("schema") != selector["schema"]:
        raise CampaignResolutionError(
            f"{label} baseline selector does not match the byte-identical recording"
        )
    return baseline_path, baseline_recording


def write_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _source(header: dict[str, Any], label: str) -> dict[str, Any]:
    source = header.get("source")
    if not isinstance(source, dict):
        raise CampaignResolutionError(
            f"{label} has no machine-derived source provenance"
        )
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
            raise CampaignResolutionError(
                f"{label} has invalid machine-derived provenance field '{field}'"
            )
    return source


def _assert_runtime_provenance_matches(
    observed: dict[str, Any],
    reference: dict[str, Any],
    label: str,
) -> None:
    for field in RUNTIME_PROVENANCE_FIELDS:
        if observed[field] != reference[field]:
            raise CampaignResolutionError(
                f"{label} changed runtime provenance field '{field}'"
            )


def _assert_game_executable_matches(
    observed: dict[str, Any],
    reference: dict[str, Any],
    label: str,
) -> None:
    field = NAVIGATION_GAME_PROVENANCE_FIELD
    if observed[field] != reference[field]:
        raise CampaignResolutionError(
            f"{label} changed game executable provenance field '{field}'"
        )


def _identity(header: dict[str, Any], label: str) -> tuple[str, int]:
    instance = header.get("instance")
    process_id = header.get("process_id")
    if (
        not isinstance(instance, str)
        or not instance
        or isinstance(process_id, bool)
        or not isinstance(process_id, int)
        or process_id <= 0
    ):
        raise CampaignResolutionError(
            f"{label} has no exact fresh-instance/process identity"
        )
    return instance, process_id


def _settled_samples(trace: dict[str, Any], label: str) -> list[dict[str, Any]]:
    samples = trace.get("settled_window_samples")
    if not isinstance(samples, list) or not samples:
        raise CampaignResolutionError(f"{label} has no settled-window samples")
    if not all(isinstance(sample, dict) for sample in samples):
        raise CampaignResolutionError(
            f"{label} settled window contains a non-object sample"
        )
    return samples


def _screen_id(samples: list[dict[str, Any]], label: str) -> str:
    payload = samples[0].get("payload")
    screen_id = payload.get("screen_id") if isinstance(payload, dict) else None
    if not isinstance(screen_id, str) or not screen_id:
        raise CampaignResolutionError(f"{label} has no sampled native screen id")
    return screen_id


def _recording_screen_id(recording: dict[str, Any], label: str) -> str:
    layout = recording.get("layout")
    if isinstance(layout, dict):
        screen_id = layout.get("screen_id")
        if isinstance(screen_id, str) and screen_id:
            return screen_id
    return _screen_id(_settled_samples(recording, label), label)


def _observation(
    header: dict[str, Any],
    samples: list[dict[str, Any]],
    evidence: dict[str, Any],
    label: str,
    *,
    kind: str = "settled_window",
    corroboration_anchor: bool = True,
) -> dict[str, Any]:
    instance, process_id = _identity(header, label)
    try:
        if kind == "settled_window":
            classify_ambient_window(samples, label=label)
    except AmbientLifecycleError as error:
        raise CampaignResolutionError(f"{label}: {error}") from error
    return {
        "label": label,
        "kind": kind,
        "instance": instance,
        "process_id": process_id,
        "corroboration_anchor": bool(
            corroboration_anchor and kind == "settled_window"
        ),
        "samples": samples,
        "evidence": evidence,
    }


def _logical_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _resolve_layout_id(
    repo_root: Path,
    logical_name: str,
    native_screen_id: str,
    fixtures: dict[str, dict[str, Any]],
    edge_id: str,
    endpoint_key: str,
    baseline_id: str,
) -> tuple[str, bool]:
    logical_candidates = [
        layout_id
        for layout_id, record in fixtures.items()
        if _logical_key(layout_id) == _logical_key(logical_name)
    ]
    if len(logical_candidates) > 1:
        raise CampaignResolutionError(
            f"navigation endpoint '{logical_name}' has ambiguous logical fixtures: "
            f"{sorted(logical_candidates)}"
        )
    used_explicit_mapping = False
    if len(logical_candidates) == 1:
        layout_id = logical_candidates[0]
    else:
        native_candidates = [
            layout_id
            for layout_id, record in fixtures.items()
            if record["native_screen_id"] == native_screen_id
        ]
        if len(native_candidates) == 1:
            layout_id = native_candidates[0]
        else:
            try:
                profile_layout_id = resolve_navigation_profile_binding(
                    repo_root,
                    edge_id=edge_id,
                    endpoint=endpoint_key,
                    baseline_id=baseline_id,
                )
            except NativeMenuProfileStateError as error:
                raise CampaignResolutionError(str(error)) from error
            mapping_key = (edge_id, endpoint_key)
            layout_id = profile_layout_id or NAVIGATION_ENDPOINT_LAYOUT_IDS.get(
                mapping_key, ""
            )
            if not layout_id:
                raise CampaignResolutionError(
                    f"navigation endpoint '{logical_name}' screen "
                    f"'{native_screen_id}' is ambiguous without explicit route "
                    f"mapping for edge '{edge_id}' side '{endpoint_key}': "
                    f"{sorted(native_candidates)}"
                )
            used_explicit_mapping = True

    record = fixtures.get(layout_id)
    if record is None:
        raise CampaignResolutionError(
            f"navigation endpoint route maps to absent fixture '{layout_id}'"
        )
    if record["native_screen_id"] != native_screen_id:
        raise CampaignResolutionError(
            f"navigation endpoint route maps '{logical_name}' to '{layout_id}', "
            f"but its native screen is '{record['native_screen_id']}' instead of "
            f"'{native_screen_id}'"
        )
    return layout_id, used_explicit_mapping


def _validate_profile_state(
    repo_root: Path,
    evidence_root: Path,
    header: dict[str, Any],
    label: str,
    *,
    required_baseline_id: str | None = None,
    binding_label: str | None = None,
) -> dict[str, Any]:
    try:
        return validate_capture_profile_state(
            repo_root=repo_root,
            header=header,
            label=label,
            evidence_root=evidence_root,
            required_baseline_id=required_baseline_id,
            binding_label=binding_label,
        )
    except NativeMenuProfileStateError as error:
        raise CampaignResolutionError(str(error)) from error


def _validate_browser_tab(
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
        raise CampaignResolutionError(str(error)) from error


def collect_standalones(
    repo_root: Path, candidate_root: Path, evidence_root: Path
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    paths = sorted((candidate_root / "menu-layouts").glob("*.json"))
    paths += sorted((candidate_root / "menu-transition-layouts").glob("*.json"))
    if not paths:
        raise CampaignResolutionError(
            "standalone fixture sweep reached no candidate content"
        )
    fixtures: dict[str, dict[str, Any]] = {}
    observations: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        layout_id = path.stem
        fixture = read_object(path)
        if fixture.get("schema") not in {
            "solomon-dark-native-menu-layout-v2",
            "solomon-dark-native-menu-layout-v3",
        }:
            raise CampaignResolutionError(f"{path} is not a native-menu layout")
        header = fixture.get("header")
        if not isinstance(header, dict):
            raise CampaignResolutionError(f"{path} has no capture header")
        profile_state = _validate_profile_state(
            repo_root,
            evidence_root,
            header,
            str(path),
            required_baseline_id=required_baseline_for_layout(
                repo_root, layout_id
            ),
            binding_label=f"layout '{layout_id}'",
        )
        source = _source(header, str(path))
        raw_receipt = header.get("settlement_trace", header.get("raw_recording"))
        if not isinstance(raw_receipt, dict):
            raise CampaignResolutionError(f"{path} has no raw settlement receipt")
        raw_path = resolve_unique_evidence(
            evidence_root,
            candidate_root / "menu-settlement-traces",
            str(raw_receipt.get("evidence_filename", "")),
        )
        validate_receipt(raw_path, raw_receipt, str(path))
        raw_trace = read_object(raw_path)
        raw_header = raw_trace.get("header")
        if not isinstance(raw_header, dict):
            raise CampaignResolutionError(f"{raw_path} has no capture header")
        _validate_profile_state(
            repo_root,
            evidence_root,
            raw_header,
            str(raw_path),
            required_baseline_id=profile_state["baseline_id"],
            binding_label=f"layout '{layout_id}' raw settlement",
        )
        primary_samples = _settled_samples(raw_trace, str(raw_path))
        primary_payload = primary_samples[0].get("payload")
        if not isinstance(primary_payload, dict):
            raise CampaignResolutionError(
                f"{raw_path} first settled sample has no payload"
            )
        primary_screen_tag = _screen_id(primary_samples, str(raw_path))
        _validate_browser_tab(
            primary_screen_tag,
            primary_payload,
            header.get("browser_tab_verification"),
            str(path),
        )
        _validate_browser_tab(
            primary_screen_tag,
            primary_payload,
            raw_header.get("browser_tab_verification"),
            str(raw_path),
        )
        if layout_id in fixtures:
            raise CampaignResolutionError(
                f"standalone fixture id '{layout_id}' is ambiguous"
            )
        native_screen_id = _screen_id(primary_samples, str(raw_path))

        fork_policy = PATH_DEPENDENT_CORE_LAYOUTS.get(layout_id)
        fork_metadata = header.get("path_dependent_core")
        if fork_policy is not None:
            if not isinstance(fork_metadata, dict):
                raise CampaignResolutionError(
                    f"path-dependent core contract: '{layout_id}' has no fork provenance"
                )
            for field, expected in fork_policy.items():
                if fork_metadata.get(field) != expected:
                    raise CampaignResolutionError(
                        "path-dependent core contract: "
                        f"'{layout_id}' changed its deterministic {field}"
                    )
            if native_screen_id != fork_policy["parent_screen_id"]:
                raise CampaignResolutionError(
                    "path-dependent core contract: "
                    f"'{layout_id}' no longer records its parent screen"
                )
            fork_decision_path = resolve_exact_evidence_receipt(
                evidence_root,
                fork_metadata.get("fork_decision"),
                f"path-dependent core {layout_id} fork decision",
            )
            fork_decision_receipt = evidence_receipt(
                fork_decision_path, evidence_root
            )
        elif native_screen_id == "hub":
            raise CampaignResolutionError(
                "path-dependent core contract: unqualified Hub fixture is forbidden"
            )
        else:
            if fork_metadata is not None:
                raise CampaignResolutionError(
                    "path-dependent core contract: non-fork layout carries fork provenance"
                )
            fork_decision_receipt = None

        confirmation_receipt = header.get("animation_confirmation")
        if not isinstance(confirmation_receipt, dict):
            raise CampaignResolutionError(
                f"{path} has no independent fresh-instance confirmation"
            )
        confirmation_path = resolve_unique_evidence(
            evidence_root,
            candidate_root / "menu-animation-confirmations",
            str(confirmation_receipt.get("evidence_filename", "")),
        )
        validate_receipt(
            confirmation_path, confirmation_receipt, f"{path} confirmation"
        )
        confirmation = read_object(confirmation_path)
        confirmation_header = confirmation.get("header")
        if not isinstance(confirmation_header, dict):
            raise CampaignResolutionError(
                f"{confirmation_path} has no confirmation header"
            )
        confirmation_samples = _settled_samples(
            confirmation, str(confirmation_path)
        )
        confirmation_payload = confirmation_samples[0].get("payload")
        if not isinstance(confirmation_payload, dict):
            raise CampaignResolutionError(
                f"{confirmation_path} first settled sample has no payload"
            )
        _validate_browser_tab(
            _screen_id(confirmation_samples, str(confirmation_path)),
            confirmation_payload,
            confirmation_header.get("browser_tab_verification"),
            str(confirmation_path),
        )
        confirmation_profile_state = _validate_profile_state(
            repo_root,
            evidence_root,
            confirmation_header,
            str(confirmation_path),
            required_baseline_id=profile_state["baseline_id"],
            binding_label=f"layout '{layout_id}' confirmation",
        )
        if confirmation_profile_state["baseline_id"] != profile_state["baseline_id"]:
            raise CampaignResolutionError(
                f"{path} confirmation changed profile-state baseline"
            )
        if profile_state["baseline_id"] != FRESH_BASELINE_ID and {
            profile_state["witness_role"],
            confirmation_profile_state["witness_role"],
        } != {"primary", "confirmation"}:
            raise CampaignResolutionError(
                f"{path} derived confirmation did not use both pinned witness roles"
            )
        if _screen_id(confirmation_samples, str(confirmation_path)) != native_screen_id:
            raise CampaignResolutionError(f"{path} confirmation changed native screen")
        confirmation_source = _source(
            confirmation_header, str(confirmation_path)
        )
        _assert_runtime_provenance_matches(
            confirmation_source,
            source,
            f"{path} confirmation",
        )
        for field in ("base_commit_sha", "source_tree_sha"):
            if confirmation_source[field] != source[field]:
                raise CampaignResolutionError(
                    f"{path} confirmation changed provenance field '{field}'"
                )
        primary_identity = _identity(header, str(path))
        confirmation_identity = _identity(
            confirmation_header, str(confirmation_path)
        )
        if primary_identity == confirmation_identity:
            raise CampaignResolutionError(
                f"{path} confirmation did not use an independent fresh instance"
            )
        primary_observation = _observation(
            header,
            primary_samples,
            evidence_receipt(raw_path, evidence_root),
            f"standalone:{layout_id}:primary",
        )
        confirmation_observation = _observation(
            confirmation_header,
            confirmation_samples,
            evidence_receipt(confirmation_path, evidence_root),
            f"standalone:{layout_id}:confirmation",
        )
        fixtures[layout_id] = {
            "path": path,
            "value": fixture,
            "header": header,
            "source": source,
            "native_screen_id": native_screen_id,
            "primary_observation": primary_observation,
            "confirmation_observation": confirmation_observation,
            "confirmation_path": confirmation_path,
            "fork_decision_receipt": fork_decision_receipt,
            "profile_state": profile_state,
        }
        observations[layout_id] = [
            primary_observation,
            confirmation_observation,
        ]
    return fixtures, observations


def collect_navigation(
    repo_root: Path,
    primary_path: Path,
    confirmation_path: Path,
    evidence_root: Path,
    fixtures: dict[str, dict[str, Any]],
    observations: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
    recordings = {
        "primary": read_object(primary_path),
        "confirmation": read_object(confirmation_path),
    }
    paths = {"primary": primary_path, "confirmation": confirmation_path}
    by_label: dict[str, dict[str, dict[str, Any]]] = {}
    for label, recording in recordings.items():
        if recording.get("schema") != "solomon-dark-native-menu-navigation-v2":
            raise CampaignResolutionError(
                f"{label} navigation schema is not recognized"
            )
        edges = recording.get("edges")
        if not isinstance(edges, list) or not edges:
            raise CampaignResolutionError(f"{label} navigation has no edges")
        edge_map = {
            str(edge.get("id")): edge
            for edge in edges
            if isinstance(edge, dict) and isinstance(edge.get("id"), str)
        }
        if len(edge_map) != len(edges):
            raise CampaignResolutionError(
                f"{label} navigation edge ids are absent or ambiguous"
            )
        by_label[label] = edge_map
    if set(by_label["primary"]) != set(by_label["confirmation"]):
        raise CampaignResolutionError(
            "primary and confirmation navigation edge censuses differ"
        )

    endpoint_layouts: dict[tuple[str, str], str] = {}
    explicit_layout_ids: set[tuple[str, str]] = set()
    for edge_id in sorted(by_label["primary"]):
        for side, endpoint_key, logical_field in (
            ("source", "before", "source"),
            ("destination", "after", "destination"),
        ):
            resolved_ids: set[str] = set()
            for label in ("primary", "confirmation"):
                edge = by_label[label][edge_id]
                header = edge.get("header")
                endpoint = edge.get(endpoint_key)
                if not isinstance(header, dict) or not isinstance(endpoint, dict):
                    raise CampaignResolutionError(
                        f"edge {edge_id} {label} {side} is incomplete"
                    )
                profile_state = _validate_profile_state(
                    repo_root,
                    evidence_root,
                    header,
                    f"edge {edge_id} {label}",
                )
                try:
                    assert_navigation_baseline_allowed(
                        repo_root,
                        edge_id=edge_id,
                        baseline_id=profile_state["baseline_id"],
                    )
                except NativeMenuProfileStateError as error:
                    raise CampaignResolutionError(str(error)) from error
                _source(header, f"edge {edge_id} {label}")
                trace = endpoint.get("settlement_trace")
                if not isinstance(trace, dict):
                    raise CampaignResolutionError(
                        f"edge {edge_id} {label} {side} has no settlement trace"
                    )
                samples = _settled_samples(
                    trace, f"edge {edge_id} {label} {side}"
                )
                native_screen_id = _screen_id(
                    samples, f"edge {edge_id} {label} {side}"
                )
                endpoint_payload = samples[0].get("payload")
                if not isinstance(endpoint_payload, dict):
                    raise CampaignResolutionError(
                        f"edge {edge_id} {label} {side} has no sampled payload"
                    )
                header_tab_receipts = header.get("browser_tab_verification")
                header_tab_receipt = (
                    header_tab_receipts.get(side)
                    if isinstance(header_tab_receipts, dict)
                    else None
                )
                if endpoint.get("browser_tab_verification") != header_tab_receipt:
                    raise CampaignResolutionError(
                        f"edge {edge_id} {label} {side} browser-tab receipts disagree"
                    )
                _validate_browser_tab(
                    native_screen_id,
                    endpoint_payload,
                    endpoint.get("browser_tab_verification"),
                    f"edge {edge_id} {label} {side}",
                )
                logical_name = edge.get(logical_field)
                if not isinstance(logical_name, str) or not logical_name:
                    raise CampaignResolutionError(
                        f"edge {edge_id} has no logical {side} screen name"
                    )
                layout_id, used_explicit_mapping = _resolve_layout_id(
                    repo_root,
                    logical_name,
                    native_screen_id,
                    fixtures,
                    edge_id,
                    endpoint_key,
                    profile_state["baseline_id"],
                )
                if used_explicit_mapping:
                    explicit_layout_ids.add((edge_id, endpoint_key))
                _assert_game_executable_matches(
                    _source(header, str(paths[label])),
                    fixtures[layout_id]["source"],
                    f"edge {edge_id} {label} {side}",
                )
                resolved_ids.add(layout_id)
                observations[layout_id].append(
                    _observation(
                        header,
                        samples,
                        evidence_receipt(paths[label], evidence_root),
                        f"edge:{edge_id}:{side}:{label}",
                        corroboration_anchor=False,
                    )
                )
            if len(resolved_ids) != 1:
                raise CampaignResolutionError(
                    f"edge {edge_id} independent {side} captures resolve different layouts"
                )
            endpoint_layouts[(edge_id, endpoint_key)] = resolved_ids.pop()
    applicable_explicit_layout_ids = {
        key
        for key in NAVIGATION_ENDPOINT_LAYOUT_IDS
        if key[0] in by_label["primary"]
    } | {
        key
        for key in PATH_DEPENDENT_CORE_ENDPOINTS
        if key[0] in by_label["primary"]
    }
    if explicit_layout_ids != applicable_explicit_layout_ids:
        raise CampaignResolutionError(
            "explicit navigation layout mapping census changed: "
            f"missing={sorted(applicable_explicit_layout_ids - explicit_layout_ids)} "
            f"unexpected={sorted(explicit_layout_ids - applicable_explicit_layout_ids)}"
        )
    return recordings["primary"], endpoint_layouts


def build_extended_baseline_filename_map(
    fixtures: dict[str, dict[str, Any]],
) -> dict[str, str]:
    filename_layout_candidates: dict[str, set[str]] = {}
    for layout_id, record in fixtures.items():
        for filename in (
            record["path"].name,
            record["confirmation_path"].name,
            f"{layout_id}-primary.baseline.json",
            f"{layout_id}-confirmation.baseline.json",
            *PATH_DEPENDENT_BASELINE_ALIASES.get(layout_id, ()),
        ):
            filename_layout_candidates.setdefault(filename, set()).add(layout_id)
    ambiguous_filenames = {
        filename: sorted(layout_ids)
        for filename, layout_ids in filename_layout_candidates.items()
        if len(layout_ids) != 1
    }
    if ambiguous_filenames:
        raise CampaignResolutionError(
            "extended baseline filename map is ambiguous: "
            f"{ambiguous_filenames}"
        )
    return {
        filename: next(iter(layout_ids))
        for filename, layout_ids in filename_layout_candidates.items()
    }


def collect_extended(
    repo_root: Path,
    observation_root: Path,
    evidence_root: Path,
    fixtures: dict[str, dict[str, Any]],
    observations: dict[str, list[dict[str, Any]]],
) -> int:
    if not observation_root.exists():
        return 0
    layout_by_filename = build_extended_baseline_filename_map(fixtures)
    count = 0
    witnessed: set[tuple[str, int, str]] = set()
    for path in sorted(observation_root.rglob("*.json")):
        value = read_object(path)
        if value.get("schema") != (
            "solomon-dark-native-menu-motion-capability-observation-v1"
        ):
            continue
        header = value.get("header")
        samples = value.get("samples")
        if not isinstance(header, dict) or not isinstance(samples, list):
            raise CampaignResolutionError(f"extended observation {path} is incomplete")
        _validate_profile_state(
            repo_root, evidence_root, header, f"extended observation {path}"
        )
        instance, process_id = _identity(header, str(path))
        motion_source = _source(header, str(path))
        baseline = header.get("baseline")
        if not isinstance(baseline, dict):
            raise CampaignResolutionError(
                f"extended observation {path} has no baseline receipt"
            )
        baseline_path, baseline_recording = resolve_baseline_evidence(
            observation_root,
            baseline,
            str(path),
        )
        baseline_header = baseline_recording.get("header")
        if not isinstance(baseline_header, dict):
            raise CampaignResolutionError(
                f"extended observation {path} baseline has no capture header"
            )
        baseline_source = _source(baseline_header, str(baseline_path))
        if canonical_bytes(baseline_source) != canonical_bytes(motion_source):
            raise CampaignResolutionError(
                f"extended observation {path} baseline provenance does not "
                "match the motion observation"
            )
        if _identity(baseline_header, str(baseline_path)) != (
            instance,
            process_id,
        ):
            raise CampaignResolutionError(
                f"extended observation {path} baseline identity does not match "
                "the motion observation"
            )
        filename = baseline.get("evidence_filename")
        selector = baseline.get("selector")
        if not isinstance(filename, str) or not isinstance(selector, dict):
            raise CampaignResolutionError(
                f"extended observation {path} baseline is incomplete"
            )
        schema = selector.get("schema")
        if schema in {
            "solomon-dark-native-menu-layout-v2",
            "solomon-dark-native-menu-layout-v3",
            "solomon-dark-native-menu-animation-confirmation-v2",
            "solomon-dark-native-menu-animation-confirmation-v3",
            "solomon-dark-native-menu-animation-confirmation-v4",
        }:
            layout_id = layout_by_filename.get(filename)
        else:
            layout_id = None
        if schema in {
            "solomon-dark-native-menu-animation-confirmation-v2",
            "solomon-dark-native-menu-animation-confirmation-v3",
            "solomon-dark-native-menu-animation-confirmation-v4",
        } and not filename.endswith((".confirmation.json", "-confirmation.baseline.json")):
            raise CampaignResolutionError(
                f"extended observation {path} confirmation baseline filename "
                "does not identify a confirmation recording"
            )
        if layout_id is None:
            screen = header.get("label")
            matching = [
                candidate
                for candidate, record in fixtures.items()
                if record["native_screen_id"] == screen
            ]
            if len(matching) != 1:
                raise CampaignResolutionError(
                    f"extended observation {path} does not resolve one screen"
                )
            layout_id = matching[0]
        sampled_screen = _screen_id(samples, str(path))
        baseline_screen = _recording_screen_id(
            baseline_recording, str(baseline_path)
        )
        if baseline_screen != sampled_screen:
            raise CampaignResolutionError(
                f"extended observation {path} baseline screen '{baseline_screen}' "
                f"does not match sampled screen '{sampled_screen}'"
            )
        fixture_source = fixtures[layout_id]["source"]
        _assert_runtime_provenance_matches(
            motion_source,
            fixture_source,
            f"extended observation {path} baseline",
        )
        witness = (instance, process_id, layout_id)
        if witness in witnessed:
            raise CampaignResolutionError(
                f"extended observation identity is ambiguous: {witness}"
            )
        witnessed.add(witness)
        observation = _observation(
            header,
            samples,
            evidence_receipt(path, evidence_root),
            f"extended:{layout_id}:{instance}:{process_id}",
            kind="extended_observation",
        )
        observation["baseline_evidence"] = evidence_receipt(
            baseline_path, evidence_root
        )
        observations[layout_id].append(observation)
        count += 1
    return count


def collect_supplemental_standalones(
    repo_root: Path,
    manifest_path: Path | None,
    evidence_root: Path,
    fixtures: dict[str, dict[str, Any]],
    observations: dict[str, list[dict[str, Any]]],
) -> int:
    if manifest_path is None:
        return 0
    root = evidence_root.resolve()
    resolved_manifest = manifest_path.resolve()
    if not resolved_manifest.is_relative_to(root) or not resolved_manifest.is_file():
        raise CampaignResolutionError(
            "supplemental settled-pair manifest escapes the evidence root or is absent"
        )
    manifest = read_object(resolved_manifest)
    if manifest.get("schema") != (
        "solomon-dark-native-menu-supplemental-settled-pairs-v1"
    ):
        raise CampaignResolutionError(
            "supplemental settled-pair manifest schema is not recognized"
        )
    pairs = manifest.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise CampaignResolutionError(
            "supplemental settled-pair sweep reached no historical pair witness"
        )
    pair_ids: set[str] = set()
    historical_identities: set[tuple[str, int, str]] = set()
    count = 0
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            raise CampaignResolutionError(
                f"supplemental settled pair {index} is not an object"
            )
        pair_id = pair.get("pair_id")
        layout_id = pair.get("layout_id")
        if not isinstance(pair_id, str) or not pair_id or pair_id in pair_ids:
            raise CampaignResolutionError(
                "supplemental settled-pair ids are absent or ambiguous"
            )
        pair_ids.add(pair_id)
        if not isinstance(layout_id, str) or layout_id not in fixtures:
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' names an absent layout"
            )
        fixture_path = resolve_exact_evidence_receipt(
            root, pair.get("primary_fixture"), f"supplemental pair {pair_id} fixture"
        )
        trace_path = resolve_exact_evidence_receipt(
            root, pair.get("primary_trace"), f"supplemental pair {pair_id} trace"
        )
        confirmation_path = resolve_exact_evidence_receipt(
            root,
            pair.get("confirmation"),
            f"supplemental pair {pair_id} confirmation",
        )
        historical_fixture = read_object(fixture_path)
        if historical_fixture.get("schema") not in {
            "solomon-dark-native-menu-layout-v2",
            "solomon-dark-native-menu-layout-v3",
        }:
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' fixture schema is not recognized"
            )
        header = historical_fixture.get("header")
        if not isinstance(header, dict):
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' fixture has no header"
            )
        _validate_profile_state(
            repo_root,
            evidence_root,
            header,
            f"supplemental pair {pair_id} fixture",
        )
        raw_receipt = header.get("settlement_trace", header.get("raw_recording"))
        confirmation_receipt = header.get("animation_confirmation")
        if not isinstance(raw_receipt, dict) or not isinstance(
            confirmation_receipt, dict
        ):
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' fixture lost its recording receipts"
            )
        validate_receipt(trace_path, raw_receipt, f"supplemental pair {pair_id} trace")
        validate_receipt(
            confirmation_path,
            confirmation_receipt,
            f"supplemental pair {pair_id} confirmation",
        )
        if raw_receipt.get("evidence_filename") != trace_path.name or (
            confirmation_receipt.get("evidence_filename") != confirmation_path.name
        ):
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' fixture receipts name different files"
            )
        trace = read_object(trace_path)
        confirmation = read_object(confirmation_path)
        confirmation_header = confirmation.get("header")
        if not isinstance(confirmation_header, dict):
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' confirmation has no header"
            )
        _validate_profile_state(
            repo_root,
            evidence_root,
            confirmation_header,
            f"supplemental pair {pair_id} confirmation",
        )
        primary_samples = _settled_samples(trace, str(trace_path))
        confirmation_samples = _settled_samples(
            confirmation, str(confirmation_path)
        )
        expected_screen = fixtures[layout_id]["native_screen_id"]
        if (
            _screen_id(primary_samples, str(trace_path)) != expected_screen
            or _screen_id(confirmation_samples, str(confirmation_path))
            != expected_screen
        ):
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' changed native screen"
            )
        historical_source = _source(header, str(fixture_path))
        confirmation_source = _source(confirmation_header, str(confirmation_path))
        if canonical_bytes(historical_source) != canonical_bytes(confirmation_source):
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' changed provenance between instances"
            )
        _assert_game_executable_matches(
            historical_source,
            fixtures[layout_id]["source"],
            f"supplemental pair {pair_id}",
        )
        primary_identity = _identity(header, str(fixture_path))
        confirmation_identity = _identity(confirmation_header, str(confirmation_path))
        if primary_identity == confirmation_identity:
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' did not use independent instances"
            )
        existing = {
            (observation["instance"], observation["process_id"], layout_id)
            for observation in observations[layout_id]
        }
        candidate_identities = {
            (*primary_identity, layout_id),
            (*confirmation_identity, layout_id),
        }
        if candidate_identities & (existing | historical_identities):
            raise CampaignResolutionError(
                f"supplemental pair '{pair_id}' repeats an existing capture identity"
            )
        historical_identities.update(candidate_identities)
        observations[layout_id].extend(
            [
                _observation(
                    header,
                    primary_samples,
                    evidence_receipt(trace_path, root),
                    f"supplemental:{pair_id}:primary",
                    corroboration_anchor=False,
                ),
                _observation(
                    confirmation_header,
                    confirmation_samples,
                    evidence_receipt(confirmation_path, root),
                    f"supplemental:{pair_id}:confirmation",
                    corroboration_anchor=False,
                ),
            ]
        )
        count += 1
    return count


def resolved_layout(resolution: dict[str, Any]) -> dict[str, Any]:
    layout = copy.deepcopy(resolution["structural_core"])
    for field in (
        "settlement_spec",
        "structural_core_sha256",
        "structural_core_element_count",
        "animated_element_ids",
        "animated_family_ids",
        "choice_slot_ids",
        "choice_slots",
        "visibility_cycling_element_ids",
        "ambient_persistent_element_ids",
        "classification_map",
        "ambient_family_art_ids",
        "ambient_members",
        "ephemeral_family",
        "ambient_semantic_member_count",
        "peak_element_count",
        "ambient_fraction",
    ):
        layout[field] = copy.deepcopy(resolution[field])
    return layout


def validate_path_dependent_core_forks(
    fixtures: dict[str, dict[str, Any]],
    resolutions: dict[str, dict[str, Any]],
    endpoint_layouts: dict[tuple[str, str], str],
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Prove the exact v2.6-v2.13 Hub fork and baseline-qualified routes."""

    root = repo_root or Path(__file__).resolve().parents[1]
    try:
        binding_contract = load_hub_binding_contract(root)["value"]
    except NativeMenuProfileStateError as error:
        raise CampaignResolutionError(str(error)) from error
    expected_layouts = set(binding_contract["layouts"])
    if expected_layouts != set(PATH_DEPENDENT_CORE_LAYOUTS):
        raise CampaignResolutionError(
            "path-dependent core contract: code and generated Hub layout registries disagree"
        )
    reached_layouts = {
        layout_id
        for layout_id, record in fixtures.items()
        if record["native_screen_id"] == "hub"
    }
    if reached_layouts != expected_layouts:
        raise CampaignResolutionError(
            "path-dependent core contract: Hub variant census changed: "
            f"expected={sorted(expected_layouts)} observed={sorted(reached_layouts)}"
        )

    observed_bindings = {
        key: endpoint_layouts.get(key) for key in PATH_DEPENDENT_CORE_ENDPOINTS
    }
    if observed_bindings != PATH_DEPENDENT_CORE_ENDPOINTS:
        raise CampaignResolutionError(
            "path-dependent core contract: one or more Hub navigation endpoints "
            f"remain ambiguous: {observed_bindings}"
        )
    unexpected_hub_endpoints = sorted(
        key
        for key, layout_id in endpoint_layouts.items()
        if layout_id in expected_layouts and key not in PATH_DEPENDENT_CORE_ENDPOINTS
    )
    if unexpected_hub_endpoints:
        raise CampaignResolutionError(
            "path-dependent core contract: Hub navigation endpoint lacks a "
            f"declared selector: {unexpected_hub_endpoints}"
        )

    counts: dict[str, int] = {}
    audit_rows: list[dict[str, Any]] = []
    for layout_id, policy in PATH_DEPENDENT_CORE_LAYOUTS.items():
        resolution = resolutions.get(layout_id)
        record = fixtures[layout_id]
        metadata = record["header"].get("path_dependent_core")
        if not isinstance(resolution, dict) or not isinstance(metadata, dict):
            raise CampaignResolutionError(
                f"path-dependent core contract: '{layout_id}' was not resolved"
            )
        settled_count = resolution.get("peak_element_count")
        expected_count = metadata.get("measured_settled_element_count")
        if (
            isinstance(settled_count, bool)
            or not isinstance(settled_count, int)
            or settled_count <= 0
            or expected_count != settled_count
        ):
            raise CampaignResolutionError(
                "path-dependent core contract: "
                f"'{layout_id}' no longer reproduces its measured element census"
            )
        counts[layout_id] = settled_count
        receipt = record.get("fork_decision_receipt")
        if not isinstance(receipt, dict):
            raise CampaignResolutionError(
                f"path-dependent core contract: '{layout_id}' lost its fork audit receipt"
            )
        contract_layout = binding_contract["layouts"][layout_id]
        if any(
            metadata.get(field) != contract_layout.get(field)
            for field in (
                "parent_screen_id",
                "path_qualifier",
                "selector",
                "required_baseline_id",
                "measured_settled_element_count",
            )
        ):
            raise CampaignResolutionError(
                f"path-dependent core contract: '{layout_id}' changed its exact v2.13 selector"
            )
        if receipt != contract_layout.get("fork_decision"):
            raise CampaignResolutionError(
                f"path-dependent core contract: '{layout_id}' changed its authorized STOP receipt"
            )
        if "resolved_semantic_multiset_sha256" in contract_layout:
            primary_payload = record["primary_observation"]["samples"][0].get(
                "payload"
            )
            confirmation_payload = record["confirmation_observation"][
                "samples"
            ][0].get("payload")
            if not isinstance(primary_payload, dict) or not isinstance(
                confirmation_payload, dict
            ):
                raise CampaignResolutionError(
                    f"path-dependent core contract: '{layout_id}' lost settled payloads"
                )
            try:
                validate_exact_hub_layout_pair(
                    root,
                    layout_id=layout_id,
                    primary_layout=primary_payload,
                    confirmation_layout=confirmation_payload,
                    baseline_id=contract_layout["required_baseline_id"],
                )
            except NativeMenuProfileStateError as error:
                raise CampaignResolutionError(str(error)) from error
        audit_rows.append(
            {
                "layout_id": layout_id,
                **copy.deepcopy(policy),
                "settled_element_count": settled_count,
                "structural_core_element_count": resolution[
                    "structural_core_element_count"
                ],
                "structural_core_sha256": resolution["structural_core_sha256"],
                "fork_decision": copy.deepcopy(receipt),
                "required_baseline_id": contract_layout[
                    "required_baseline_id"
                ],
                "bound_navigation_endpoints": [
                    {
                        "edge_id": binding["edge_id"],
                        "endpoint": binding["endpoint"],
                        "required_baseline_id": binding[
                            "required_baseline_id"
                        ],
                    }
                    for binding in binding_contract["bindings"]
                    if binding["layout_id"] == layout_id
                ],
            }
        )
    if len(set(counts.values())) != len(counts):
        raise CampaignResolutionError(
            "path-dependent core contract: Hub variants do not differ in element census"
        )
    return audit_rows


def settlement_summary(
    observation: dict[str, Any], resolution: dict[str, Any]
) -> dict[str, Any]:
    classified = classify_ambient_window(
        observation["samples"], label=observation["label"]
    )
    return {
        "settlement_spec": SETTLEMENT_SPEC,
        "criterion": classified["criterion"],
        "settle_latency_milliseconds": classified[
            "settle_latency_milliseconds"
        ],
        "stable_span_milliseconds": classified["stable_span_milliseconds"],
        "consecutive_structural_samples": classified[
            "consecutive_structural_samples"
        ],
        "minimum_element_count": classified["minimum_element_count"],
        "peak_element_count": classified["element_count"],
        "raw_window_structural_sha256": classified["structural_sha256"],
        "resolved_structural_core_sha256": resolution[
            "structural_core_sha256"
        ],
        "resolved_classification_map_sha256": sha256_json(
            resolution["classification_map"]
        ),
        "ambient_fraction": resolution["ambient_fraction"],
    }


def resolve_campaign(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    primary_navigation_path: Path,
    confirmation_navigation_path: Path,
    motion_observation_root: Path,
    resolved_navigation_output: Path,
    audit_output: Path,
    apply: bool,
    verify: bool = False,
    supplemental_pair_manifest: Path | None = None,
    asset_manifest_path: Path | None = None,
) -> dict[str, Any]:
    if apply and verify:
        raise CampaignResolutionError(
            "ambient campaign cannot apply and verify simultaneously"
        )
    evidence_resolved = evidence_root.resolve()
    motion_resolved = motion_observation_root.resolve()
    if not motion_resolved.is_relative_to(evidence_resolved):
        raise CampaignResolutionError(
            "motion observation directory escapes the evidence root"
        )
    asset_manifest: dict[str, Any] | None = None
    asset_manifest_receipt: dict[str, Any] | None = None
    if asset_manifest_path is not None:
        manifest_resolved = asset_manifest_path.resolve()
        if not manifest_resolved.is_relative_to(evidence_resolved):
            raise CampaignResolutionError(
                "choice-slot asset manifest escapes the evidence root"
            )
        if not manifest_resolved.is_file():
            raise CampaignResolutionError(
                "choice-slot asset manifest is absent"
            )
        asset_manifest = read_object(manifest_resolved)
        if (
            asset_manifest.get("schema")
            != "solomon-dark-web-asset-manifest-v1"
            or not isinstance(asset_manifest.get("entries"), dict)
            or not asset_manifest["entries"]
        ):
            raise CampaignResolutionError(
                "choice-slot asset manifest does not contain the machine-built "
                "renderer sprite entries"
            )
        asset_manifest_receipt = evidence_receipt(
            manifest_resolved, evidence_resolved
        )
    fixtures, observations = collect_standalones(
        repo_root, candidate_root, evidence_root
    )
    primary_navigation, endpoint_layouts = collect_navigation(
        repo_root,
        primary_navigation_path,
        confirmation_navigation_path,
        evidence_root,
        fixtures,
        observations,
    )
    extended_count = collect_extended(
        repo_root,
        motion_observation_root,
        evidence_root,
        fixtures,
        observations,
    )
    supplemental_pair_count = collect_supplemental_standalones(
        repo_root,
        supplemental_pair_manifest,
        evidence_root,
        fixtures,
        observations,
    )

    resolutions: dict[str, dict[str, Any]] = {}
    layouts: dict[str, dict[str, Any]] = {}
    screen_audit: list[dict[str, Any]] = []
    for layout_id in sorted(fixtures):
        reached = observations.get(layout_id)
        if not reached:
            raise CampaignResolutionError(
                f"standalone fixture '{layout_id}' was never reached"
            )
        try:
            resolution = resolve_ambient_lifecycle(
                reached, asset_manifest=asset_manifest
            )
        except AmbientLifecycleError as error:
            raise CampaignResolutionError(
                f"STOP: screen '{layout_id}': {error}"
            ) from error
        resolutions[layout_id] = resolution
        layouts[layout_id] = resolved_layout(resolution)
        screen_audit.append(
            {
                "layout_id": layout_id,
                "native_screen_id": fixtures[layout_id]["native_screen_id"],
                "settled_observation_count": sum(
                    observation["kind"] == "settled_window"
                    for observation in reached
                ),
                "extended_observation_count": sum(
                    observation["kind"] == "extended_observation"
                    for observation in reached
                ),
                "extended_baseline_receipt_count": sum(
                    "baseline_evidence" in observation
                    for observation in reached
                ),
                "supplemental_settled_observation_count": sum(
                    observation["label"].startswith("supplemental:")
                    for observation in reached
                ),
                "structural_core_element_count": resolution[
                    "structural_core_element_count"
                ],
                "structural_core_sha256": resolution[
                    "structural_core_sha256"
                ],
                "animated_element_ids": resolution["animated_element_ids"],
                "animated_family_ids": resolution["animated_family_ids"],
                "choice_slot_ids": resolution["choice_slot_ids"],
                "choice_slots": copy.deepcopy(resolution["choice_slots"]),
                "ambient_family_art_ids": resolution[
                    "ambient_family_art_ids"
                ],
                "ambient_fraction": resolution["ambient_fraction"],
            }
        )

    choice_layout_ids = sorted(
        layout_id
        for layout_id, resolution in resolutions.items()
        if resolution["choice_slot_ids"]
    )
    if choice_layout_ids and choice_layout_ids != ["skill-picker"]:
        raise CampaignResolutionError(
            "choice-slot scope contract: only the measured skill-picker residual "
            f"is authorized, not {choice_layout_ids}"
        )
    if choice_layout_ids and asset_manifest_receipt is None:
        raise CampaignResolutionError(
            "choice-slot provenance contract: resolved slots have no hashed "
            "asset-manifest receipt"
        )
    ruling_receipts = (
        choice_slot_ruling_receipts(evidence_resolved)
        if choice_layout_ids
        else {}
    )

    path_dependent_core_audit = (
        validate_path_dependent_core_forks(
            fixtures, resolutions, endpoint_layouts, repo_root
        )
        if any(record["native_screen_id"] == "hub" for record in fixtures.values())
        else []
    )

    candidate_updates: dict[Path, dict[str, Any]] = {}
    for layout_id, record in fixtures.items():
        fixture = copy.deepcopy(record["value"])
        fixture["schema"] = "solomon-dark-native-menu-layout-v3"
        fixture_profile_state = fixture["header"].get("profile_state")
        if not isinstance(fixture_profile_state, dict):
            raise CampaignResolutionError(
                f"standalone '{layout_id}' lost profile-state provenance during resolution"
            )
        fixture_profile_state["baseline_id"] = record["profile_state"][
            "baseline_id"
        ]
        fixture_profile_state["binding_contract"] = {
            "repo_relative_path": (
                "tests/fixtures/webgame/native-menu-hub-bindings-v213.json"
            ),
            "sha256": record["profile_state"][
                "binding_contract_sha256"
            ],
            "bytes": record["profile_state"]["binding_contract_bytes"],
        }
        witness_role = record["profile_state"]["witness_role"]
        if witness_role is not None:
            fixture_profile_state["derivation_witness_role"] = witness_role
        fixture["header"]["profile_state_binding"] = {
            "baseline_id": record["profile_state"]["baseline_id"],
            "layout_id": layout_id,
            "edge_id": "",
            "derivation_witness_role": witness_role or "",
        }
        fixture["layout"] = copy.deepcopy(layouts[layout_id])
        fixture["header"]["settlement"] = settlement_summary(
            record["primary_observation"], resolutions[layout_id]
        )
        fixture["header"]["ambient_lifecycle"] = {
            "resolution_sha256": sha256_json(resolutions[layout_id]),
            "independent_instances": sorted(
                {
                    (
                        observation["instance"],
                        observation["process_id"],
                    )
                    for observation in observations[layout_id]
                    if observation["kind"] == "settled_window"
                }
            ),
            "observation_receipts": [
                copy.deepcopy(observation["evidence"])
                for observation in observations[layout_id]
            ],
            "extended_observation_baseline_receipts": [
                copy.deepcopy(observation["baseline_evidence"])
                for observation in observations[layout_id]
                if "baseline_evidence" in observation
            ],
        }
        if layout_id in choice_layout_ids:
            fixture["header"]["choice_slots"] = {
                "settlement_spec": SETTLEMENT_SPEC,
                "promotion": (
                    "reused_stopped_settled_windows_rederived_under_v2.8"
                ),
                "asset_manifest": copy.deepcopy(asset_manifest_receipt),
                "diagnostic_receipts": copy.deepcopy(ruling_receipts),
                "choice_slot_ids": copy.deepcopy(
                    resolutions[layout_id]["choice_slot_ids"]
                ),
            }
        candidate_updates[record["path"]] = fixture

    resolved_navigation = copy.deepcopy(primary_navigation)
    edge_by_id = {
        str(edge.get("id")): edge
        for edge in resolved_navigation.get("edges", [])
        if isinstance(edge, dict)
    }
    if len(edge_by_id) != len(resolved_navigation.get("edges", [])):
        raise CampaignResolutionError("resolved navigation edge ids are ambiguous")
    for edge_id, edge in edge_by_id.items():
        edge_header = edge.get("header")
        if not isinstance(edge_header, dict):
            raise CampaignResolutionError(
                f"resolved edge '{edge_id}' has no capture header"
            )
        edge_profile = _validate_profile_state(
            repo_root,
            evidence_root,
            edge_header,
            f"resolved edge {edge_id}",
        )
        try:
            assert_navigation_baseline_allowed(
                repo_root,
                edge_id=edge_id,
                baseline_id=edge_profile["baseline_id"],
            )
        except NativeMenuProfileStateError as error:
            raise CampaignResolutionError(str(error)) from error
        profile_payload = edge_header.get("profile_state")
        if not isinstance(profile_payload, dict):
            raise CampaignResolutionError(
                f"resolved edge '{edge_id}' lost profile-state provenance"
            )
        profile_payload["baseline_id"] = edge_profile["baseline_id"]
        profile_payload["binding_contract"] = {
            "repo_relative_path": (
                "tests/fixtures/webgame/native-menu-hub-bindings-v213.json"
            ),
            "sha256": edge_profile["binding_contract_sha256"],
            "bytes": edge_profile["binding_contract_bytes"],
        }
        if edge_profile["witness_role"] is not None:
            profile_payload["derivation_witness_role"] = edge_profile[
                "witness_role"
            ]
        edge_header["profile_state_binding"] = {
            "baseline_id": edge_profile["baseline_id"],
            "layout_id": "",
            "edge_id": edge_id,
            "derivation_witness_role": edge_profile["witness_role"] or "",
        }
    for (edge_id, endpoint_key), layout_id in endpoint_layouts.items():
        edge = edge_by_id[edge_id]
        endpoint = edge[endpoint_key]
        label = "source" if endpoint_key == "before" else "destination"
        matching_observations = [
            observation
            for observation in observations[layout_id]
            if observation["label"] == f"edge:{edge_id}:{label}:primary"
        ]
        if len(matching_observations) != 1:
            raise CampaignResolutionError(
                f"edge {edge_id} {label} primary observation is absent or ambiguous"
            )
        endpoint["layout"] = copy.deepcopy(layouts[layout_id])
        endpoint["settlement"] = settlement_summary(
            matching_observations[0], resolutions[layout_id]
        )
        endpoint["animated_element_ids"] = copy.deepcopy(
            resolutions[layout_id]["animated_element_ids"]
        )
        endpoint["choice_slot_ids"] = copy.deepcopy(
            resolutions[layout_id]["choice_slot_ids"]
        )
        endpoint["element_count"] = resolutions[layout_id][
            "structural_core_element_count"
        ]
        endpoint["layout_id"] = layout_id
        if layout_id in PATH_DEPENDENT_CORE_LAYOUTS:
            endpoint["path_dependent_core"] = {
                **copy.deepcopy(PATH_DEPENDENT_CORE_LAYOUTS[layout_id]),
                "edge_id": edge_id,
                "endpoint": endpoint_key,
                "fork_decision": copy.deepcopy(
                    fixtures[layout_id]["fork_decision_receipt"]
                ),
            }
    for edge in edge_by_id.values():
        edge["header"]["settlement"] = {
            "source": copy.deepcopy(edge["before"]["settlement"]),
            "destination": copy.deepcopy(edge["after"]["settlement"]),
        }
    resolved_navigation.setdefault("header", {})["ambient_lifecycle_resolution"] = {
        "settlement_spec": SETTLEMENT_SPEC,
        "primary_raw_recording": evidence_receipt(
            primary_navigation_path, evidence_root
        ),
        "confirmation_raw_recording": evidence_receipt(
            confirmation_navigation_path, evidence_root
        ),
        "motion_observation_directory": motion_resolved.relative_to(
            evidence_resolved
        ).as_posix(),
        "screen_count": len(resolutions),
        "path_dependent_core": copy.deepcopy(path_dependent_core_audit),
        "choice_slot_asset_manifest": copy.deepcopy(asset_manifest_receipt),
        "choice_slot_ruling_receipts": copy.deepcopy(ruling_receipts),
        "choice_slot_layout_ids": choice_layout_ids,
        **(
            {
                "supplemental_settled_pair_manifest": evidence_receipt(
                    supplemental_pair_manifest, evidence_root
                )
            }
            if supplemental_pair_manifest is not None
            else {}
        ),
    }

    audit = {
        "schema": "solomon-dark-native-menu-ambient-lifecycle-audit-v1",
        "settlement_spec": SETTLEMENT_SPEC,
        "applied": apply,
        "standalone_fixture_count": len(fixtures),
        "navigation_edge_count": len(edge_by_id),
        "settled_observation_count": sum(
            observation["kind"] == "settled_window"
            for reached in observations.values()
            for observation in reached
        ),
        "extended_observation_count": extended_count,
        "supplemental_settled_pair_count": supplemental_pair_count,
        "extended_baseline_receipt_count": sum(
            "baseline_evidence" in observation
            for reached in observations.values()
            for observation in reached
        ),
        "screens": screen_audit,
        "path_dependent_core": path_dependent_core_audit,
        "choice_slot_asset_manifest": copy.deepcopy(asset_manifest_receipt),
        "choice_slot_ruling_receipts": copy.deepcopy(ruling_receipts),
        "choice_slot_layout_ids": choice_layout_ids,
        "outputs": {
            "resolved_navigation": str(resolved_navigation_output),
            "candidate_fixtures": [str(path) for path in sorted(candidate_updates)],
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
                raise CampaignResolutionError(
                f"resolved candidate {path} is not the machine-derived v2.9 result"
                )
        if not resolved_navigation_output.is_file() or canonical_bytes(
            read_object(resolved_navigation_output)
        ) != canonical_bytes(resolved_navigation):
            raise CampaignResolutionError(
                "resolved navigation is not the machine-derived v2.9 result"
            )
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--primary-navigation", type=Path, required=True)
    parser.add_argument("--confirmation-navigation", type=Path, required=True)
    parser.add_argument("--motion-observation-root", type=Path, required=True)
    parser.add_argument("--asset-manifest", type=Path, required=True)
    parser.add_argument("--supplemental-settled-pair-manifest", type=Path)
    parser.add_argument("--resolved-navigation-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = resolve_campaign(
            args.repo_root.resolve(),
            args.candidate_root.resolve(),
            args.evidence_root.resolve(),
            args.primary_navigation.resolve(),
            args.confirmation_navigation.resolve(),
            args.motion_observation_root.resolve(),
            args.resolved_navigation_output.resolve(),
            args.audit_output.resolve(),
            args.apply,
            args.verify,
            (
                args.supplemental_settled_pair_manifest.resolve()
                if args.supplemental_settled_pair_manifest is not None
                else None
            ),
            args.asset_manifest.resolve(),
        )
    except CampaignResolutionError as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps({"success": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
