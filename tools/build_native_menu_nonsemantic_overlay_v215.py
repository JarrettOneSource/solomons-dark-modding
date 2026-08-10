#!/usr/bin/env python3
"""Build the bounded v2.15 Dark Cloud credentials overlay record."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

if __package__:
    from .native_menu_nonsemantic_overlay import (
        OVERLAY_SCHEMA,
        OVERLAY_SETTLEMENT_SPEC,
        TAG_DISAGREEMENT_REASON,
        canonical_sha256,
        classify_nonsemantic_overlay,
        validate_overlay_record,
    )
    from .native_menu_profile_state import (
        FRESH_BASELINE_ID,
        NativeMenuProfileStateError,
        validate_capture_profile_state,
    )
else:
    from native_menu_nonsemantic_overlay import (  # type: ignore[no-redef]
        OVERLAY_SCHEMA,
        OVERLAY_SETTLEMENT_SPEC,
        TAG_DISAGREEMENT_REASON,
        canonical_sha256,
        classify_nonsemantic_overlay,
        validate_overlay_record,
    )
    from native_menu_profile_state import (  # type: ignore[no-redef]
        FRESH_BASELINE_ID,
        NativeMenuProfileStateError,
        validate_capture_profile_state,
    )


class OverlayBuildError(RuntimeError):
    """The sealed v9 evidence cannot derive the exact v2.15 record."""


PRIMARY_ROOT = Path("motion-v214/dark-cloud-settings/primary")
CONFIRMATION_ROOT = Path(
    "motion-v214/dark-cloud-settings/confirmation"
)
SETTLEMENT_ROOT = Path(
    "motion-v214/dark-cloud-settings/menu-settlement-traces"
)
AUDIT_PATH = Path("dark-cloud-settings-surface-stop-audit.json")
ROUTE_LOG_ROOT = Path("recorder/profile-pinned")
OVERLAY_RELATIVE_PATH = Path("menu-overlays/dark-cloud-settings.json")
UNDERLAY_SOURCE_PATH = Path("menu-layouts/dark-cloud-settings.json")
UNDERLAY_RELATIVE_PATH = Path(
    "menu-overlay-underlays/dark-cloud-settings.json"
)
PANEL_CROP = (492, 92, 1108, 808)


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise OverlayBuildError(f"{label} is not readable JSON: {error}") from error
    if not isinstance(value, dict):
        raise OverlayBuildError(f"{label} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_text_auto(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig", errors="replace")


def receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    raw_root = evidence_root.resolve()
    if raw_root.name != "raw-v9":
        raise OverlayBuildError(
            "v2.15 overlay evidence root is not the additive raw-v9 bundle"
        )
    root = raw_root.parent
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise OverlayBuildError(f"overlay evidence escapes the campaign root: {path}")
    return {
        "evidence_path": resolved.relative_to(root).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def repo_receipt(path: Path, repo_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = repo_root.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise OverlayBuildError(f"committed overlay input escapes the repository: {path}")
    return {
        "evidence_path": resolved.relative_to(root).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def _settled_samples(recording: dict[str, Any], label: str) -> list[dict[str, Any]]:
    samples = recording.get("settled_window_samples")
    if not isinstance(samples, list) or len(samples) < 40 or not all(
        isinstance(sample, dict) for sample in samples
    ):
        raise OverlayBuildError(f"{label} did not retain forty settled samples")
    return samples


def _payload(sample: dict[str, Any], label: str) -> dict[str, Any]:
    payload = sample.get("payload")
    if not isinstance(payload, dict):
        raise OverlayBuildError(f"{label} sample has no semantic payload")
    return payload


def _surface(sample: dict[str, Any], label: str) -> str:
    values = {
        sample.get(field)
        for field in (
            "machine_classified_surface",
            "semantic_surface",
            "native_surface",
        )
        if isinstance(sample.get(field), str) and sample.get(field)
    }
    payload = _payload(sample, label)
    if isinstance(payload.get("screen_id"), str) and payload.get("screen_id"):
        values.add(payload["screen_id"])
    if len(values) != 1:
        raise OverlayBuildError(
            f"{label} does not resolve one machine-classified surface: {sorted(values)}"
        )
    return values.pop()


def _text_action_payload(payload: dict[str, Any], label: str) -> list[dict[str, Any]]:
    elements = payload.get("elements")
    if not isinstance(elements, list) or not elements or not all(
        isinstance(element, dict) for element in elements
    ):
        raise OverlayBuildError(f"{label} reached no semantic members")
    fields = (
        "kind",
        "text",
        "action_id",
        "art_id",
        "font_id",
        "text_style",
        "visible",
        "interactive",
        "rect",
        "unclipped_rect",
    )
    selected = [
        {field: element.get(field) for field in fields}
        for element in elements
        if element.get("text") or element.get("action_id")
    ]
    if not selected:
        raise OverlayBuildError(f"{label} reached no text/action payload")
    selected.sort(
        key=lambda value: json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    )
    return selected


def _settlement_fact(
    recording: dict[str, Any], samples: list[dict[str, Any]], label: str
) -> tuple[int, int]:
    settlement = recording.get("settlement")
    if not isinstance(settlement, dict):
        raise OverlayBuildError(f"{label} has no settlement result")
    sample_count = settlement.get(
        "consecutive_structural_samples", len(samples)
    )
    stable_span = settlement.get("stable_span_milliseconds")
    if (
        not isinstance(sample_count, int)
        or sample_count < 40
        or not isinstance(stable_span, int)
        or stable_span < 2000
    ):
        raise OverlayBuildError(f"{label} does not satisfy Settlement v2.15")
    return sample_count, stable_span


def _validate_profile(
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
            required_baseline_id=FRESH_BASELINE_ID,
            binding_label="Settlement v2.15 non-semantic overlay",
        )
    except NativeMenuProfileStateError as error:
        raise OverlayBuildError(str(error)) from error


def _frame_comparison(
    overlay_path: Path,
    accepted_path: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    with Image.open(overlay_path) as overlay_image, Image.open(
        accepted_path
    ) as accepted_image:
        overlay = overlay_image.convert("RGB")
        accepted = accepted_image.convert("RGB")
        if overlay.size != accepted.size or overlay.size != (1600, 900):
            raise OverlayBuildError(
                "overlay and accepted underlying frames do not share 1600x900 geometry"
            )
        overlay_crop = overlay.crop(PANEL_CROP)
        accepted_crop = accepted.crop(PANEL_CROP)
        difference = ImageChops.difference(overlay_crop, accepted_crop)
        bbox = difference.getbbox()
        differing_pixels = sum(
            pixel != (0, 0, 0) for pixel in difference.get_flattened_data()
        )
    if bbox is None or differing_pixels <= 0:
        raise OverlayBuildError(
            "player-visible overlay frame equals the accepted underlying visual"
        )
    return {
        "overlay": receipt(overlay_path, evidence_root),
        "accepted_underlying_surface": receipt(accepted_path, evidence_root),
        "comparison_crop": list(PANEL_CROP),
        "crop_difference_bbox": list(bbox),
        "differing_pixel_count": differing_pixels,
        "differs": True,
    }


def _gate_receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    text = read_text_auto(path)
    if TAG_DISAGREEMENT_REASON not in " ".join(text.split()):
        raise OverlayBuildError(
            "overlay gate transcript lost the exact classifier disagreement reason"
        )
    return receipt(path, evidence_root)


def _observation(
    *,
    role: str,
    recording_path: Path,
    recording: dict[str, Any],
    gate_path: Path,
    overlay_frame: Path,
    accepted_frame: Path,
    repo_root: Path,
    evidence_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    header = recording.get("header")
    if not isinstance(header, dict):
        raise OverlayBuildError(f"{role} overlay recording has no header")
    profile = _validate_profile(repo_root, evidence_root, header, str(recording_path))
    samples = _settled_samples(recording, str(recording_path))
    surfaces = {_surface(sample, str(recording_path)) for sample in samples}
    if surfaces != {"main_menu"}:
        raise OverlayBuildError(
            f"{role} overlay underlying surface changed: {sorted(surfaces)}"
        )
    payloads = [
        _text_action_payload(_payload(sample, str(recording_path)), str(recording_path))
        for sample in samples
    ]
    payload_hashes = {canonical_sha256(payload) for payload in payloads}
    if len(payload_hashes) != 1:
        raise OverlayBuildError(
            f"{role} overlay underlying text/action payload did not settle"
        )
    sample_count, stable_span = _settlement_fact(
        recording, samples, str(recording_path)
    )
    instance = header.get("instance")
    process_id = header.get("process_id")
    if not isinstance(instance, str) or not isinstance(process_id, int):
        raise OverlayBuildError(f"{role} overlay has no exact process identity")
    return (
        {
            "role": role,
            "instance": instance,
            "process_id": process_id,
            "operator_tag": "dark_cloud_settings",
            "machine_surface": "main_menu",
            "profile_state_identity_sha256": profile["identity"],
            "settled_sample_count": sample_count,
            "stable_span_milliseconds": stable_span,
            "text_action_member_count": len(payloads[0]),
            "text_action_payload_sha256": next(iter(payload_hashes)),
            "recording": receipt(recording_path, evidence_root),
            "gate_transcript": _gate_receipt(gate_path, evidence_root),
            "player_visible_frame": _frame_comparison(
                overlay_frame, accepted_frame, evidence_root
            ),
        },
        payloads[0],
    )


def _find_measured_control(candidate_root: Path) -> dict[str, Any]:
    fixture = read_object(
        candidate_root / "menu-layouts/game-settings-title.json",
        "title settings fixture",
    )
    layout = fixture.get("layout")
    elements = layout.get("elements") if isinstance(layout, dict) else None
    matches = [
        element
        for element in elements or []
        if isinstance(element, dict)
        and element.get("text") == "DARK CLOUD SETTINGS"
        and element.get("visible") is True
    ]
    if len(matches) != 1:
        raise OverlayBuildError(
            "overlay activation did not resolve one live-measured Dark Cloud Settings row"
        )
    element = matches[0]
    rect = element.get("rect")
    if (
        not isinstance(rect, list)
        or len(rect) != 4
        or any(not isinstance(value, (int, float)) for value in rect)
    ):
        raise OverlayBuildError("overlay activating row has no measured rect")
    point = [(rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0]
    return {
        "source_layout_id": "game-settings-title",
        "member_id": element.get("id"),
        "text": element.get("text"),
        "rect": rect,
        "click_point": point,
        "point_derivation": "center of the unique visible measured row member",
    }


def _route_receipt(path: Path, evidence_root: Path, role: str) -> dict[str, Any]:
    text = read_text_auto(path)
    required = (
        '"step":"edge:settings_to_dark_cloud_settings","status":"captured"',
        '"step":"layout:dark-cloud-settings","status":"captured"',
        '"step":"edge:dark_cloud_settings_to_settings","status":"captured"',
    )
    if any(token not in text for token in required):
        raise OverlayBuildError(
            f"{role} semantic underlay route did not capture both endpoints and layout"
        )
    return receipt(path, evidence_root)


def _validate_underlay(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    fixture_path = candidate_root / UNDERLAY_SOURCE_PATH
    if not fixture_path.is_file():
        fixture_path = candidate_root / UNDERLAY_RELATIVE_PATH
    fixture = read_object(fixture_path, "gate-agreeing dark-cloud settings underlay")
    header = fixture.get("header")
    layout = fixture.get("layout")
    if not isinstance(header, dict) or not isinstance(layout, dict):
        raise OverlayBuildError("semantic underlay fixture is incomplete")
    profile = _validate_profile(repo_root, candidate_root, header, str(fixture_path))
    if (
        header.get("label") != "dark_cloud_settings"
        or layout.get("screen_id") != "dark_cloud_settings"
        or len(layout.get("elements", [])) != 16
    ):
        raise OverlayBuildError(
            "semantic underlay fixture is not the exact gate-agreeing 16-member state"
        )
    primary_trace_receipt = header.get("raw_recording")
    confirmation_receipt = header.get("animation_confirmation")
    if not isinstance(primary_trace_receipt, dict) or not isinstance(
        confirmation_receipt, dict
    ):
        raise OverlayBuildError("semantic underlay fixture lost capture receipts")
    trace_path = candidate_root / "menu-settlement-traces" / str(
        primary_trace_receipt.get("evidence_filename")
    )
    confirmation_path = candidate_root / "menu-animation-confirmations" / str(
        confirmation_receipt.get("evidence_filename")
    )
    trace = read_object(trace_path, "semantic underlay primary trace")
    confirmation = read_object(
        confirmation_path, "semantic underlay confirmation"
    )
    for role, recording in (("primary", trace), ("confirmation", confirmation)):
        samples = _settled_samples(recording, f"semantic underlay {role}")
        surfaces = {_surface(sample, f"semantic underlay {role}") for sample in samples}
        if surfaces != {"dark_cloud_settings"}:
            raise OverlayBuildError(
                f"semantic underlay {role} did not pass machine/tag agreement"
            )
    confirmation_header = confirmation.get("header")
    if not isinstance(confirmation_header, dict):
        raise OverlayBuildError("semantic underlay confirmation has no header")
    confirmation_profile = _validate_profile(
        repo_root, candidate_root, confirmation_header, str(confirmation_path)
    )
    if profile["identity"] != confirmation_profile["identity"]:
        raise OverlayBuildError("semantic underlay instances changed profile identity")
    primary_settlement = header.get("settlement")
    primary_structural_sha256 = (
        primary_settlement.get("structural_sha256")
        if isinstance(primary_settlement, dict)
        else None
    )
    confirmation_structural_sha256 = confirmation.get("structural_sha256")
    for role, value in (
        ("primary", primary_structural_sha256),
        ("confirmation", confirmation_structural_sha256),
    ):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise OverlayBuildError(
                f"semantic underlay {role} has no structural settlement hash"
            )
    primary_route = evidence_root / ROUTE_LOG_ROOT / "v213-p24-route-final.log"
    confirmation_route = (
        evidence_root / ROUTE_LOG_ROOT / "v213-p25-route-phase1.log"
    )
    primary_fixture_receipt = receipt(fixture_path, evidence_root)
    future_path = (candidate_root / UNDERLAY_RELATIVE_PATH).resolve()
    primary_fixture_receipt["evidence_path"] = future_path.relative_to(
        evidence_root.resolve().parent
    ).as_posix()
    return {
        "screen_id": "dark_cloud_settings",
        "operator_machine_tag_agreement": True,
        "route": "pause -> game settings -> measured MODIFY -> credentials overlay",
        "layout_fixture": UNDERLAY_RELATIVE_PATH.as_posix(),
        "primary_fixture": primary_fixture_receipt,
        "primary_trace": receipt(trace_path, evidence_root),
        "confirmation": receipt(confirmation_path, evidence_root),
        "route_receipts": [
            _route_receipt(primary_route, evidence_root, "primary"),
            _route_receipt(confirmation_route, evidence_root, "confirmation"),
        ],
        "bound_endpoints": [
            "settings_to_dark_cloud_settings.after",
            "dark_cloud_settings_to_settings.before",
        ],
        "primary_instance": header.get("instance"),
        "confirmation_instance": confirmation_header.get("instance"),
        "profile_state_identity_sha256": profile["identity"],
        "raw_element_count": 16,
        "primary_structural_sha256": primary_structural_sha256,
        "confirmation_structural_sha256": confirmation_structural_sha256,
        "payload_role": (
            "route-qualified machine semantic underlay; never player-visible "
            "credentials-panel semantics"
        ),
    }


def build_record(
    repo_root: Path, candidate_root: Path, evidence_root: Path
) -> dict[str, Any]:
    primary_trace_path = (
        evidence_root
        / SETTLEMENT_ROOT
        / "unexpected-post-modify-main-menu.settlement.json"
    )
    confirmation_path = (
        evidence_root
        / CONFIRMATION_ROOT
        / "unexpected-post-modify-main-menu.confirmation.json"
    )
    primary = read_object(primary_trace_path, "primary overlay settlement")
    confirmation = read_object(confirmation_path, "confirmation overlay settlement")
    primary_observation, primary_payload = _observation(
        role="primary",
        recording_path=primary_trace_path,
        recording=primary,
        gate_path=evidence_root
        / PRIMARY_ROOT
        / "dark-cloud-settings-tag-gate-repro2.log",
        overlay_frame=evidence_root
        / PRIMARY_ROOT
        / "unexpected-post-modify-main-menu.png",
        accepted_frame=evidence_root / PRIMARY_ROOT / "route-to-main/beta-to-main.bmp",
        repo_root=repo_root,
        evidence_root=evidence_root,
    )
    confirmation_observation, confirmation_payload = _observation(
        role="confirmation",
        recording_path=confirmation_path,
        recording=confirmation,
        gate_path=evidence_root
        / CONFIRMATION_ROOT
        / "dark-cloud-settings-tag-gate-repro2.log",
        overlay_frame=evidence_root
        / CONFIRMATION_ROOT
        / "frames/unexpected-post-modify-main-menu.confirmation.bmp",
        accepted_frame=evidence_root
        / CONFIRMATION_ROOT
        / "route-to-main/beta-to-main.bmp",
        repo_root=repo_root,
        evidence_root=evidence_root,
    )
    if primary_payload != confirmation_payload:
        raise OverlayBuildError(
            "non-semantic overlay pair changed its underlying text/action payload"
        )
    observations = [primary_observation, confirmation_observation]
    classification = classify_nonsemantic_overlay({"observations": observations})
    underlay = _validate_underlay(repo_root, candidate_root, evidence_root)
    landed_path = repo_root / "tests/fixtures/webgame/menu-layouts/dark-cloud-settings.json"
    retired_snapshot_path = (
        repo_root
        / "webgame-contracts/baseline-snapshots/menu-layouts/dark-cloud-settings.json"
    )
    if (
        not retired_snapshot_path.is_file()
        or file_sha256(retired_snapshot_path) != file_sha256(landed_path)
    ):
        raise OverlayBuildError(
            "v2.15 retirement snapshot is not byte-identical to the landed fixture"
        )
    landed = read_object(landed_path, "retired landed dark-cloud settings fixture")
    landed_layout = landed.get("layout")
    if not isinstance(landed_layout, dict) or len(landed_layout.get("elements", [])) != 31:
        raise OverlayBuildError(
            "v2.15 supersession did not reach the exact landed 31-member fixture"
        )
    record = {
        "schema": OVERLAY_SCHEMA,
        "settlement_spec": OVERLAY_SETTLEMENT_SPEC,
        "overlay_id": "dark_cloud_settings_credentials",
        "overlay": {
            "classification": classification,
            "members_semantically_observable": False,
            "semantic_member_count": 0,
            "semantic_members": [],
            "observations": observations,
            "activation": {
                "edge_id": "settings_to_dark_cloud_settings",
                "trigger": "login_info_modify_click",
                "route": "main menu -> title settings -> measured MODIFY -> credentials overlay",
                "measured_control": _find_measured_control(candidate_root),
                "source_frames": [
                    receipt(
                        evidence_root
                        / PRIMARY_ROOT
                        / "route-settings-to-dark-cloud-settings.measured.source.bmp",
                        evidence_root,
                    ),
                    receipt(
                        evidence_root
                        / CONFIRMATION_ROOT
                        / "route-settings-to-dark-cloud-settings.measured.source.bmp",
                        evidence_root,
                    ),
                ],
                "evidence_only": True,
                "typed_into_credentials": False,
                "durable_dark_cloud_state_mutated": False,
            },
            "semantic_underlay_binding": underlay,
            "supersession": {
                "retired_landed_screen_fixture": repo_receipt(
                    retired_snapshot_path, repo_root
                ),
                "retired_element_count": 31,
                "replacement_kind": "overlay_record",
                "reason": (
                    "the contaminated-era fixture describes neither the settled "
                    "underlying main_menu semantics nor observable credentials-panel "
                    "members"
                ),
                "stop_audit": receipt(evidence_root / AUDIT_PATH, evidence_root),
            },
            "motion_witness_disposition": {
                "element_id": "dark_cloud_settings.art.ui_28.1",
                "disposition": "retired_with_nonsemantic_screen_fixture",
                "reason": (
                    "the member belongs to the route-qualified semantic underlay; "
                    "the credentials overlay has no observable members and its visual "
                    "truth is pinned by settled frames"
                ),
            },
            "navigation": {
                "destination_edge": "settings_to_dark_cloud_settings",
                "source_edge": "dark_cloud_settings_to_settings",
                "endpoint_type": "overlay",
            },
        },
    }
    validate_overlay_record(record)
    return record


def write_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def apply_record(candidate_root: Path, record: dict[str, Any]) -> None:
    source = candidate_root / UNDERLAY_SOURCE_PATH
    underlay = candidate_root / UNDERLAY_RELATIVE_PATH
    overlay = candidate_root / OVERLAY_RELATIVE_PATH
    if not source.is_file():
        if not underlay.is_file() or not overlay.is_file():
            raise OverlayBuildError(
                "active candidate has neither the source screen nor exact reclassified output"
            )
        write_atomically(overlay, record)
        return
    if underlay.exists() or overlay.exists():
        raise OverlayBuildError("v2.15 apply refuses a partial candidate output")
    underlay.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{underlay.name}.", suffix=".tmp", dir=underlay.parent
    )
    os.close(descriptor)
    try:
        shutil.copyfile(source, temporary_name)
        with open(temporary_name, "r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary_name, underlay)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    if file_sha256(underlay) != file_sha256(source):
        raise OverlayBuildError("semantic underlay copy changed bytes")
    write_atomically(overlay, record)
    source.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    evidence_root = args.evidence_root.resolve()
    if not candidate_root.is_relative_to(evidence_root):
        raise OverlayBuildError("candidate root escapes the evidence bundle")
    record = build_record(repo_root, candidate_root, evidence_root)
    if args.apply:
        if args.output is not None:
            raise OverlayBuildError("v2.15 apply writes only the exact candidate paths")
        apply_record(candidate_root, record)
    elif args.output is not None:
        output = args.output.resolve()
        if not output.is_relative_to(evidence_root):
            raise OverlayBuildError("overlay output escapes the evidence bundle")
        write_atomically(output, record)
    print(
        json.dumps(
            {
                "success": True,
                "applied": args.apply,
                "overlay_id": record["overlay_id"],
                "classification_sha256": canonical_sha256(
                    record["overlay"]["classification"]
                ),
                "underlay_fixture": UNDERLAY_RELATIVE_PATH.as_posix(),
                "semantic_member_count": 0,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
