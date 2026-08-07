#!/usr/bin/env python3
"""Import paired native-loader/loading recordings under Settlement v2.9."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image

if __package__:
    from .native_menu_ambient_lifecycle import (
        AmbientLifecycleError,
        canonical_bytes,
        find_ambient_settled_window,
    )
    from .native_menu_overlay_v25 import (
        OVERLAY_REFERENCE_SCHEMA as OVERLAY_REFERENCE_SCHEMA_V25,
        OverlayV25Error,
        assert_overlay_hygiene as assert_overlay_hygiene_v25,
    )
    from .native_menu_settlement_v2 import (
        OVERLAY_REFERENCE_SCHEMA as OVERLAY_REFERENCE_SCHEMA_V24,
        SettlementV2Error,
        assert_overlay_sample_hygiene as assert_overlay_sample_hygiene_v24,
    )
else:
    from native_menu_ambient_lifecycle import (  # type: ignore[no-redef]
        AmbientLifecycleError,
        canonical_bytes,
        find_ambient_settled_window,
    )
    from native_menu_overlay_v25 import (  # type: ignore[no-redef]
        OVERLAY_REFERENCE_SCHEMA as OVERLAY_REFERENCE_SCHEMA_V25,
        OverlayV25Error,
        assert_overlay_hygiene as assert_overlay_hygiene_v25,
    )
    from native_menu_settlement_v2 import (  # type: ignore[no-redef]
        OVERLAY_REFERENCE_SCHEMA as OVERLAY_REFERENCE_SCHEMA_V24,
        SettlementV2Error,
        assert_overlay_sample_hygiene as assert_overlay_sample_hygiene_v24,
    )


class SpecialImportError(RuntimeError):
    """A special recording or its independently captured pair is invalid."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise SpecialImportError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise SpecialImportError(f"{path} is not a JSON object")
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


def git_text(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        diagnostic = (result.stderr or result.stdout).strip()
        raise SpecialImportError(
            f"could not derive special-capture Git provenance: {diagnostic}"
        )
    return result.stdout.strip()


def derive_git_provenance(repo_root: Path) -> dict[str, str]:
    commit = git_text(repo_root, "rev-parse", "HEAD")
    tree = git_text(repo_root, "rev-parse", "HEAD^{tree}")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None or re.fullmatch(
        r"[0-9a-f]{40}", tree
    ) is None:
        raise SpecialImportError(
            "special-capture Git provenance was not a full lowercase SHA"
        )
    dirty = git_text(repo_root, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise SpecialImportError(
            "special-capture import requires a clean tracked tree so "
            "base_commit_sha describes the recorder"
        )
    return {"base_commit_sha": commit, "source_tree_sha": tree}


def normalize_instance(value: Any, label: str) -> str:
    instance = re.sub(
        r"^SolomonDarkModLoader_LuaExec_", "", str(value), flags=re.IGNORECASE
    )
    if re.fullmatch(r"menufx-[A-Za-z0-9._-]+", instance) is None:
        raise SpecialImportError(
            f"{label} instance '{instance}' is outside the authorized menufx-* group"
        )
    return instance


def positive_process_id(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SpecialImportError(f"{label} has no exact positive process id")
    return value


def derive_binary_source(
    repo_root: Path,
    instance: str,
    git_provenance: dict[str, str],
) -> dict[str, str]:
    instance_root = repo_root / "runtime" / "instances" / instance.lower()
    executable = instance_root / "stage" / "SolomonDark.exe"
    loader = repo_root / "dist" / "launcher" / "SolomonDarkModLoader.dll"
    compatibility_path = (
        instance_root / "stage" / ".sdmod" / "multiplayer-compatibility.json"
    )
    for label, path in (
        ("staged game executable", executable),
        ("launcher-side loader DLL", loader),
        ("staged compatibility receipt", compatibility_path),
    ):
        if not path.is_file():
            raise SpecialImportError(f"{label} is missing for '{instance}': {path}")
    game_hash = sha256_file(executable)
    loader_hash = sha256_file(loader)
    compatibility = read_object(compatibility_path).get("compatibility")
    if not isinstance(compatibility, dict):
        raise SpecialImportError(
            f"staged compatibility receipt is incomplete for '{instance}'"
        )
    game_entry = compatibility.get("gameExecutable")
    loader_entry = compatibility.get("loader")
    if (
        not isinstance(game_entry, dict)
        or not isinstance(loader_entry, dict)
        or game_entry.get("sha256") != game_hash
        or loader_entry.get("sha256") != loader_hash
    ):
        raise SpecialImportError(
            "staged compatibility receipt does not identify the exact game and "
            f"launcher-side loader for '{instance}'"
        )
    return {
        **git_provenance,
        "capture_tree": "exact committed tree at base_commit_sha",
        "game_executable_sha256": game_hash,
        "loader_dll_sha256": loader_hash,
    }


def source_receipt(path: Path) -> dict[str, Any]:
    return {
        "evidence_filename": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def captured_at_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def optional(value: dict[str, Any], key: str, default: Any = "") -> Any:
    result = value.get(key, default)
    return default if result is None else result


def standardize_loader(
    recording: dict[str, Any], label: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if recording.get("schema") != "solomon-dark-native-loader-capture-v1":
        raise SpecialImportError(f"{label} loader capture schema is not recognized")
    raw_samples = recording.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise SpecialImportError(f"{label} loader capture contains no samples")
    samples: list[dict[str, Any]] = []
    for sample_index, sample in enumerate(raw_samples):
        if not isinstance(sample, dict):
            raise SpecialImportError(
                f"{label} loader sample {sample_index} is not an object"
            )
        raw_elements = sample.get("elements")
        if not isinstance(raw_elements, list) or not raw_elements:
            raise SpecialImportError(
                f"{label} loader sample {sample_index} contains no elements"
            )
        elements: list[dict[str, Any]] = []
        for element_index, element in enumerate(raw_elements, start=1):
            if not isinstance(element, dict):
                raise SpecialImportError(
                    f"{label} loader sample {sample_index} has a non-object element"
                )
            art_id = str(element.get("art_id", ""))
            if not art_id:
                raise SpecialImportError(
                    f"{label} loader sample {sample_index} has art without art_id"
                )
            token = re.sub(r"[^a-z0-9]+", "_", art_id.lower()).strip("_")
            elements.append(
                {
                    "id": f"native_loader.art.{token}.{element_index}",
                    "kind": "art",
                    "text": "",
                    "action_id": "",
                    "art_id": art_id,
                    "font_id": "",
                    "text_style": str(element.get("draw_kind", "")),
                    "visible": True,
                    "interactive": False,
                    "draw_order": element_index,
                    "rect": copy.deepcopy(element.get("rect")),
                    "unclipped_rect": copy.deepcopy(element.get("unclipped_rect")),
                }
            )
        elapsed = int(sample["elapsed_milliseconds"])
        samples.append(
            {
                "elapsed_milliseconds": elapsed,
                "captured_at_milliseconds": elapsed,
                "semantic_surface": "native_loader",
                "semantic_generation": 1,
                "payload": {
                    "generation": 1,
                    "screen_id": "native_loader",
                    "screen_title": "Raptisoft loader",
                    "capture_method": str(recording.get("capture_method", "")),
                    "progress_numerator": int(sample["numerator"]),
                    "progress_denominator": int(sample["denominator"]),
                    "progress": float(sample["progress"]),
                    "complete": bool(sample["complete"]),
                    "elements": elements,
                },
            }
        )
    metadata = {
        "instance": normalize_instance(recording.get("instance"), label),
        "process_id": positive_process_id(recording.get("process_id"), label),
        "capture_method": str(recording.get("capture_method", "")),
        "recorded_settlement": recording.get("settlement"),
        "raw_samples": raw_samples,
    }
    return samples, metadata


def standardize_loading(
    recording: dict[str, Any], label: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if recording.get("schema") != "solomon-dark-native-loading-capture-v1":
        raise SpecialImportError(f"{label} loading capture schema is not recognized")
    header = recording.get("header")
    raw_samples = recording.get("samples")
    if not isinstance(header, dict) or not isinstance(raw_samples, list) or not raw_samples:
        raise SpecialImportError(f"{label} loading capture is incomplete")
    capture_method = str(header.get("capture_method", ""))
    samples: list[dict[str, Any]] = []
    for sample_index, sample in enumerate(raw_samples):
        layout = sample.get("layout") if isinstance(sample, dict) else None
        if not isinstance(layout, dict):
            raise SpecialImportError(
                f"{label} loading sample {sample_index} has no layout"
            )
        raw_elements = layout.get("elements")
        if not isinstance(raw_elements, list) or not raw_elements:
            raise SpecialImportError(
                f"{label} loading sample {sample_index} contains no elements"
            )
        elements: list[dict[str, Any]] = []
        for element_index, element in enumerate(raw_elements, start=1):
            if not isinstance(element, dict):
                raise SpecialImportError(
                    f"{label} loading sample {sample_index} has a non-object element"
                )
            entry = {
                "id": f"loading.{element.get('id', element_index)}",
                "kind": str(element.get("kind", "")),
                "text": str(optional(element, "text")),
                "action_id": "",
                "art_id": str(optional(element, "art_id")),
                "font_id": str(optional(element, "font")),
                "text_style": str(element.get("kind", "")),
                "visible": True,
                "interactive": False,
                "draw_order": element_index,
                "rect": copy.deepcopy(element.get("rect")),
                "unclipped_rect": copy.deepcopy(element.get("rect")),
            }
            for field in (
                "color",
                "color_top",
                "color_bottom",
                "source_size",
                "font_height",
                "font_weight",
                "scale",
            ):
                if field in element and element[field] is not None:
                    entry[field] = copy.deepcopy(element[field])
            elements.append(entry)
        elapsed = int(sample["elapsed_milliseconds"])
        sequence = int(layout["sequence"])
        samples.append(
            {
                "elapsed_milliseconds": elapsed,
                "captured_at_milliseconds": elapsed,
                "semantic_surface": "loading_screen",
                "semantic_generation": sequence,
                "payload": {
                    "generation": sequence,
                    "screen_id": "loading_screen",
                    "screen_title": str(optional(raw_elements[-1], "text")),
                    "capture_method": capture_method,
                    "stage_id": str(layout["stage_id"]),
                    "progress": float(layout["progress"]),
                    "viewport": copy.deepcopy(layout.get("viewport")),
                    "source_crop": copy.deepcopy(layout.get("source_crop")),
                    "elements": elements,
                },
            }
        )
    metadata = {
        "instance": normalize_instance(header.get("instance"), label),
        "process_id": positive_process_id(header.get("pid"), label),
        "capture_method": capture_method,
        "recorded_settlement": recording.get("settlement"),
        "raw_samples": raw_samples,
    }
    return samples, metadata


def assert_overlay_sample_hygiene(
    samples: list[dict[str, Any]], reference: dict[str, Any], label: str
) -> None:
    schema = reference.get("schema")
    try:
        if schema == OVERLAY_REFERENCE_SCHEMA_V24:
            assert_overlay_sample_hygiene_v24(samples, reference)
        elif schema == OVERLAY_REFERENCE_SCHEMA_V25:
            if not samples:
                raise SpecialImportError(
                    f"{label} overlay hygiene reached no capture samples"
                )
            for index, sample in enumerate(samples):
                payload = sample.get("payload")
                if not isinstance(payload, dict):
                    raise SpecialImportError(
                        f"{label} overlay sample {index} has no payload"
                    )
                assert_overlay_hygiene_v25(payload, reference)
        else:
            raise SpecialImportError(
                f"{label} overlay reference schema is not recognized"
            )
    except (SettlementV2Error, OverlayV25Error) as error:
        raise SpecialImportError(f"{label} sample-stream overlay hygiene: {error}") from error


def settlement_summary(classification: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "settlement_spec",
        "criterion",
        "structural_element_order",
        "settle_latency_milliseconds",
        "stable_span_milliseconds",
        "consecutive_structural_samples",
        "animated_id_set_sample_count",
        "total_semantic_samples",
        "structural_sha256",
        "animated_element_ids",
        "visibility_cycling_element_ids",
        "ephemeral_art_ids",
        "animated_element_count",
        "minimum_element_count",
        "element_count",
        "animated_fraction",
        "stable_start_index",
        "stable_end_index",
        "window_classification",
    )
    return {
        field: copy.deepcopy(classification[field])
        for field in fields
        if field in classification
    }


def validate_recorded_settlement(
    recorded: Any, computed: dict[str, Any], label: str
) -> None:
    if not isinstance(recorded, dict) or recorded.get("settled") is not True:
        raise SpecialImportError(f"{label} raw recorder did not report settlement")
    comparisons = {
        "settle_latency_milliseconds": computed["settle_latency_milliseconds"],
        "stable_span_milliseconds": computed["stable_span_milliseconds"],
        "consecutive_structural_samples": computed["consecutive_structural_samples"],
        "total_semantic_samples": computed["total_semantic_samples"],
    }
    for field, expected in comparisons.items():
        if recorded.get(field) != expected:
            raise SpecialImportError(
                f"{label} recorder settlement field '{field}' does not match "
                "its reclassified sample trail"
            )


def settled_samples(
    samples: list[dict[str, Any]], classification: dict[str, Any], label: str
) -> list[dict[str, Any]]:
    start = classification.get("stable_start_index")
    end = classification.get("stable_end_index")
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start < 0
        or end < start
        or end >= len(samples)
    ):
        raise SpecialImportError(f"{label} classifier returned an invalid window")
    result = copy.deepcopy(samples[start : end + 1])
    if len(result) < 40:
        raise SpecialImportError(f"{label} settled window contains fewer than 40 samples")
    return result


def reference_frame(
    capture_path: Path,
    raw_samples: list[Any],
    classification: dict[str, Any],
    label: str,
) -> Path:
    start = int(classification["stable_start_index"])
    end = int(classification["stable_end_index"])
    candidates: list[str] = []
    for raw in raw_samples[start : end + 1]:
        if isinstance(raw, dict):
            value = raw.get("reference_capture")
            if isinstance(value, str) and value.strip():
                candidates.append(value)
    if len(candidates) != 1:
        raise SpecialImportError(
            f"{label} settled window contains {len(candidates)} reference frames; "
            "exactly one is required"
        )
    path = (capture_path.parent / candidates[0]).resolve()
    if not path.is_file():
        raise SpecialImportError(f"{label} reference frame is missing: {path}")
    return path


def capture_header(
    *,
    label: str,
    capture_path: Path,
    frame_path: Path,
    metadata: dict[str, Any],
    source: dict[str, str],
    settlement: dict[str, Any],
    reference_capture: str | None,
) -> dict[str, Any]:
    header = {
        "label": label,
        "instance": metadata["instance"],
        "process_id": metadata["process_id"],
        "source": copy.deepcopy(source),
        "recorded_live": True,
        "captured_at_utc": captured_at_utc(capture_path),
        "capture_method": metadata["capture_method"],
        "settlement": copy.deepcopy(settlement),
        "raw_recording": {
            **source_receipt(capture_path),
            "frame_sha256": sha256_file(frame_path),
        },
    }
    if reference_capture is not None:
        header["reference_capture"] = reference_capture
    return header


def assert_independent_pair(
    primary: dict[str, Any], confirmation: dict[str, Any], label: str
) -> None:
    if primary["instance"] == confirmation["instance"]:
        raise SpecialImportError(
            f"{label} confirmation did not use a different fresh instance"
        )
    if primary["process_id"] == confirmation["process_id"]:
        raise SpecialImportError(
            f"{label} confirmation reused the primary exact process"
        )
    if canonical_bytes(primary["source"]) != canonical_bytes(confirmation["source"]):
        raise SpecialImportError(
            f"{label} fresh instances do not share commit/tree/binary provenance"
        )


def convert_reference(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".menufix.tmp")
    try:
        with Image.open(source) as image:
            image.save(temporary, format="PNG")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_trace(
    path: Path,
    label: str,
    source_path: Path,
    window: list[dict[str, Any]],
) -> dict[str, Any]:
    value = {
        "schema": "solomon-dark-native-menu-settlement-trace-v3",
        "header": {
            "label": label,
            "settlement_spec": "2.9",
            "source_recording": source_receipt(source_path),
        },
        "structural_phases": [],
        "settled_window_samples": copy.deepcopy(window),
    }
    write_object(path, value)
    return source_receipt(path)


def confirmation_value(
    *,
    label: str,
    primary_classification: dict[str, Any],
    confirmation_classification: dict[str, Any],
    confirmation_header: dict[str, Any],
    frame_path: Path,
    window: list[dict[str, Any]],
) -> dict[str, Any]:
    primary_ids = list(primary_classification.get("animated_element_ids", []))
    confirmation_ids = list(
        confirmation_classification.get("animated_element_ids", [])
    )
    header = copy.deepcopy(confirmation_header)
    header["frame"] = source_receipt(frame_path)
    return {
        "schema": "solomon-dark-native-menu-animation-confirmation-v4",
        "header": header,
        "settlement": settlement_summary(confirmation_classification),
        "animated_element_ids": confirmation_ids,
        "raw_primary_animated_element_ids": primary_ids,
        "raw_sets_match_noncontractual": sorted(primary_ids) == sorted(confirmation_ids),
        "requires_campaign_resolution": True,
        "structural_sha256": confirmation_classification["structural_sha256"],
        "confirmation_layout": copy.deepcopy(confirmation_classification["layout"]),
        "structural_phases": [],
        "settled_window_samples": copy.deepcopy(window),
    }


def import_surface(
    *,
    repo_root: Path,
    output_root: Path,
    overlay_reference: dict[str, Any],
    git_provenance: dict[str, str],
    label: str,
    fixture_stem: str,
    primary_path: Path,
    confirmation_path: Path,
    standardize: Callable[
        [dict[str, Any], str], tuple[list[dict[str, Any]], dict[str, Any]]
    ],
) -> list[str]:
    primary_recording = read_object(primary_path)
    confirmation_recording = read_object(confirmation_path)
    primary_samples, primary_metadata = standardize(
        primary_recording, f"{label} primary"
    )
    confirmation_samples, confirmation_metadata = standardize(
        confirmation_recording, f"{label} confirmation"
    )
    assert_overlay_sample_hygiene(primary_samples, overlay_reference, f"{label} primary")
    assert_overlay_sample_hygiene(
        confirmation_samples, overlay_reference, f"{label} confirmation"
    )
    primary_classification = find_ambient_settled_window(primary_samples)
    confirmation_classification = find_ambient_settled_window(confirmation_samples)
    validate_recorded_settlement(
        primary_metadata["recorded_settlement"],
        primary_classification,
        f"{label} primary",
    )
    validate_recorded_settlement(
        confirmation_metadata["recorded_settlement"],
        confirmation_classification,
        f"{label} confirmation",
    )
    primary_window = settled_samples(
        primary_samples, primary_classification, f"{label} primary"
    )
    confirmation_window = settled_samples(
        confirmation_samples, confirmation_classification, f"{label} confirmation"
    )
    primary_frame = reference_frame(
        primary_path,
        primary_metadata["raw_samples"],
        primary_classification,
        f"{label} primary",
    )
    confirmation_frame = reference_frame(
        confirmation_path,
        confirmation_metadata["raw_samples"],
        confirmation_classification,
        f"{label} confirmation",
    )
    primary_source = derive_binary_source(
        repo_root, primary_metadata["instance"], git_provenance
    )
    confirmation_source = derive_binary_source(
        repo_root, confirmation_metadata["instance"], git_provenance
    )
    reference_name = f"{fixture_stem}.png"
    primary_header = capture_header(
        label=label,
        capture_path=primary_path,
        frame_path=primary_frame,
        metadata=primary_metadata,
        source=primary_source,
        settlement=settlement_summary(primary_classification),
        reference_capture=f"../menu-reference-captures/{reference_name}",
    )
    confirmation_header = capture_header(
        label=label,
        capture_path=confirmation_path,
        frame_path=confirmation_frame,
        metadata=confirmation_metadata,
        source=confirmation_source,
        settlement=settlement_summary(confirmation_classification),
        reference_capture=None,
    )
    assert_independent_pair(primary_header, confirmation_header, label)

    reference_path = output_root / "menu-reference-captures" / reference_name
    convert_reference(primary_frame, reference_path)
    trace_path = output_root / "menu-settlement-traces" / f"{fixture_stem}.settlement.json"
    primary_header["settlement_trace"] = write_trace(
        trace_path, label, primary_path, primary_window
    )

    confirmation = confirmation_value(
        label=label,
        primary_classification=primary_classification,
        confirmation_classification=confirmation_classification,
        confirmation_header=confirmation_header,
        frame_path=confirmation_frame,
        window=confirmation_window,
    )
    confirmation_output = (
        output_root
        / "menu-animation-confirmations"
        / f"{fixture_stem}.confirmation.json"
    )
    write_object(confirmation_output, confirmation)
    primary_header["animation_confirmation"] = {
        **source_receipt(confirmation_output),
        "instance": confirmation_header["instance"],
        "process_id": confirmation_header["process_id"],
        "source": copy.deepcopy(confirmation_header["source"]),
        "confirmation_structural_sha256": confirmation_classification[
            "structural_sha256"
        ],
        "raw_primary_animated_element_ids": list(
            primary_classification.get("animated_element_ids", [])
        ),
        "raw_confirmation_animated_element_ids": list(
            confirmation_classification.get("animated_element_ids", [])
        ),
        "raw_sets_match_noncontractual": confirmation[
            "raw_sets_match_noncontractual"
        ],
        "requires_campaign_resolution": True,
    }
    fixture = {
        "schema": "solomon-dark-native-menu-layout-v2",
        "header": primary_header,
        "layout": copy.deepcopy(primary_classification["layout"]),
    }
    fixture_output = output_root / "menu-layouts" / f"{fixture_stem}.json"
    write_object(fixture_output, fixture)
    return [
        str(fixture_output),
        str(confirmation_output),
        str(trace_path),
        str(reference_path),
    ]


def import_all(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    output_root = args.output_root.resolve()
    expected_relative_paths = {
        Path("menu-layouts/native-loader.json"),
        Path("menu-animation-confirmations/native-loader.confirmation.json"),
        Path("menu-settlement-traces/native-loader.settlement.json"),
        Path("menu-reference-captures/native-loader.png"),
        Path("menu-layouts/loading-screen.json"),
        Path("menu-animation-confirmations/loading-screen.confirmation.json"),
        Path("menu-settlement-traces/loading-screen.settlement.json"),
        Path("menu-reference-captures/loading-screen.png"),
    }
    collisions = sorted(
        str(relative)
        for relative in expected_relative_paths
        if (output_root / relative).exists()
    )
    if collisions:
        raise SpecialImportError(
            "special-capture output is ambiguous because targets already exist: "
            + ", ".join(collisions)
        )
    overlay_path = (
        repo_root / "tests" / "fixtures" / "webgame" / "menu-overlay-reference.json"
    )
    overlay_reference = read_object(overlay_path)
    git_provenance = derive_git_provenance(repo_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="menufix-special-import-", dir=output_root.parent
    ) as temporary:
        staging_root = Path(temporary)
        staged_outputs = import_surface(
            repo_root=repo_root,
            output_root=staging_root,
            overlay_reference=overlay_reference,
            git_provenance=git_provenance,
            label="native_loader",
            fixture_stem="native-loader",
            primary_path=args.loader_primary.resolve(),
            confirmation_path=args.loader_confirmation.resolve(),
            standardize=standardize_loader,
        )
        staged_outputs.extend(
            import_surface(
                repo_root=repo_root,
                output_root=staging_root,
                overlay_reference=overlay_reference,
                git_provenance=git_provenance,
                label="loading_screen",
                fixture_stem="loading-screen",
                primary_path=args.loading_primary.resolve(),
                confirmation_path=args.loading_confirmation.resolve(),
                standardize=standardize_loading,
            )
        )
        observed_relative_paths = {
            Path(path).relative_to(staging_root) for path in staged_outputs
        }
        if observed_relative_paths != expected_relative_paths:
            raise SpecialImportError(
                "special-capture staged output census is incomplete or ambiguous"
            )
        outputs: list[str] = []
        for relative in sorted(expected_relative_paths):
            source = staging_root / relative
            destination = output_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            outputs.append(str(destination))
    return {
        "success": True,
        "settlement_spec": "2.9",
        "paired_surface_count": 2,
        "outputs": outputs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--loader-primary", type=Path, required=True)
    parser.add_argument("--loader-confirmation", type=Path, required=True)
    parser.add_argument("--loading-primary", type=Path, required=True)
    parser.add_argument("--loading-confirmation", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = import_all(args)
    except (
        AmbientLifecycleError,
        OSError,
        SpecialImportError,
        TypeError,
        ValueError,
    ) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
