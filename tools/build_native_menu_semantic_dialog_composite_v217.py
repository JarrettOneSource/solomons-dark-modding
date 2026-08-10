#!/usr/bin/env python3
"""Derive the bounded v2.17 beta-dialog composite from sealed v9 evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

if __package__:
    from .native_menu_semantic_dialog_composite import (
        COMPOSITE_ID,
        COMPOSITE_SCHEMA,
        COMPOSITE_SETTLEMENT_SPEC,
        DISMISSAL_ACTION_ID,
        OPERATOR_TAG,
        UNDERLAY_LAYOUT_ID,
        UNDERLAY_SCREEN_ID,
        NativeMenuSemanticDialogCompositeError,
        canonical_bytes,
        canonical_sha256,
        classify_semantic_dialog_composite,
        counter_entries,
        semantic_counter,
        semantic_member,
        validate_composite_record,
        validate_qualified_beta_paint_order,
    )
else:
    from native_menu_semantic_dialog_composite import (  # type: ignore[no-redef]
        COMPOSITE_ID,
        COMPOSITE_SCHEMA,
        COMPOSITE_SETTLEMENT_SPEC,
        DISMISSAL_ACTION_ID,
        OPERATOR_TAG,
        UNDERLAY_LAYOUT_ID,
        UNDERLAY_SCREEN_ID,
        NativeMenuSemanticDialogCompositeError,
        canonical_bytes,
        canonical_sha256,
        classify_semantic_dialog_composite,
        counter_entries,
        semantic_counter,
        semantic_member,
        validate_composite_record,
        validate_qualified_beta_paint_order,
    )


class SemanticDialogCompositeBuildError(RuntimeError):
    """The sealed pair does not derive the exact authorized v2.17 records."""


QUESTION_ROOT = Path("beta-notice-path-core-question")
PRIMARY_ROOT = QUESTION_ROOT / "diagnostic2-primary"
CONFIRMATION_ROOT = QUESTION_ROOT / "diagnostic2-confirmation"
QUESTION_AUDIT = QUESTION_ROOT / "beta-notice-path-state-question-audit.json"
QUESTION_MANIFEST = QUESTION_ROOT / "beta-notice-path-state-question-manifest.json"
COMPOSITE_RELATIVE_PATH = Path(
    "menu-dialog-composites/beta-notice-first-boot.json"
)
REFERENCE_RELATIVE_PATH = Path(
    "menu-reference-captures/beta-notice-first-boot.png"
)
LEGACY_ORDER_EVIDENCE = (
    QUESTION_ROOT / "legacy-native-menu-beta-notice-order-v29.json"
)


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise SemanticDialogCompositeBuildError(
            f"{label} is not readable JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise SemanticDialogCompositeBuildError(f"{label} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".menufix.tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def evidence_receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    raw_root = evidence_root.resolve()
    campaign_root = raw_root.parent
    if raw_root.name != "raw-v9" or not resolved.is_relative_to(campaign_root):
        raise SemanticDialogCompositeBuildError(
            f"v2.17 evidence escapes the additive campaign bundle: {path}"
        )
    if not resolved.is_file():
        raise SemanticDialogCompositeBuildError(
            f"v2.17 evidence is absent: {path}"
        )
    return {
        "evidence_path": resolved.relative_to(campaign_root).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def fixture_receipt(path: Path, fixture: str) -> dict[str, Any]:
    if not path.is_file():
        raise SemanticDialogCompositeBuildError(
            f"v2.17 committed-fixture source is absent: {path}"
        )
    return {
        "fixture": fixture,
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def _settled_payload(recording: dict[str, Any], label: str) -> tuple[dict[str, Any], int, int]:
    samples = recording.get("settled_window_samples")
    settlement = recording.get("settlement")
    if (
        not isinstance(samples, list)
        or len(samples) < 40
        or not all(isinstance(sample, dict) for sample in samples)
        or not isinstance(settlement, dict)
        or settlement.get("consecutive_structural_samples", 0) < 40
        or settlement.get("stable_span_milliseconds", 0) < 2_000
    ):
        raise SemanticDialogCompositeBuildError(
            f"{label} has no forty-sample, two-second settled window"
        )
    payloads = [sample.get("payload") for sample in samples]
    if not all(isinstance(payload, dict) for payload in payloads):
        raise SemanticDialogCompositeBuildError(
            f"{label} settled window has a sample without payload"
        )
    counters = [semantic_counter(payload["elements"]) for payload in payloads]
    if any(counter != counters[0] for counter in counters[1:]):
        raise SemanticDialogCompositeBuildError(
            f"{label} semantic member multiset changed inside its settled window"
        )
    generations = {
        (
            sample.get("semantic_surface"),
            sample.get("semantic_generation"),
            sample.get("native_generation"),
            payload.get("generation"),
        )
        for sample, payload in zip(samples, payloads, strict=True)
    }
    if len(generations) != 1:
        raise SemanticDialogCompositeBuildError(
            f"{label} surface or generation changed inside its settled window"
        )
    return (
        copy.deepcopy(payloads[0]),
        len(samples),
        int(settlement["stable_span_milliseconds"]),
    )


def _pixel_delta(dialog_path: Path, underlay_path: Path) -> dict[str, Any]:
    with Image.open(dialog_path) as dialog_source, Image.open(
        underlay_path
    ) as underlay_source:
        dialog = dialog_source.convert("RGBA")
        underlay = underlay_source.convert("RGBA")
        if dialog.size != underlay.size:
            raise SemanticDialogCompositeBuildError(
                "v2.17 dialog and underlay frames changed dimensions"
            )
        difference = ImageChops.difference(dialog, underlay).convert("RGB")
        bounding_box = difference.getbbox()
        if bounding_box is None:
            raise SemanticDialogCompositeBuildError(
                "v2.17 dialog frame does not differ from its underlay"
            )
        differing = sum(
            1
            for pixel in difference.get_flattened_data()
            if pixel != (0, 0, 0)
        )
        return {
            "frame_size": list(dialog.size),
            "bounding_box": list(bounding_box),
            "differing_pixel_count": differing,
        }


def _normalize_observation(
    *,
    role: str,
    root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    trace_path = evidence_root / root / "beta-notice-overlay.settlement.json"
    observation_path = evidence_root / root / "beta-notice-overlay-observation.json"
    dismissal_path = evidence_root / root / "initial-beta-dismissal/receipt.json"
    dialog_frame = evidence_root / root / "beta-notice-overlay.bmp"
    underlay_frame = evidence_root / root / "initial-beta-dismissal/dismiss-initial-beta.bmp"
    recording = read_object(trace_path, f"v2.17 {role} recording")
    observed = read_object(observation_path, f"v2.17 {role} observation")
    dismissal = read_object(dismissal_path, f"v2.17 {role} dismissal")
    payload, sample_count, stable_span = _settled_payload(
        recording, f"v2.17 {role} recording"
    )
    header = recording.get("header")
    source = header.get("source") if isinstance(header, dict) else None
    profile = header.get("profile_state") if isinstance(header, dict) else None
    if (
        not isinstance(header, dict)
        or not isinstance(source, dict)
        or not isinstance(profile, dict)
        or source.get("profile_state_identity_sha256")
        != profile.get("profile_state_identity_sha256")
        or profile.get("baseline_id") != "pristine_fresh_install"
        or profile.get("durable_file_count") != 0
        or observed.get("gate_result") != header.get("production_gate_result")
    ):
        raise SemanticDialogCompositeBuildError(
            f"v2.17 {role} recording lost pristine machine-derived provenance"
        )
    steps = dismissal.get("steps")
    if (
        not isinstance(steps, list)
        or len(steps) != 1
        or not isinstance(steps[0], dict)
        or steps[0].get("name") != "dismiss-initial-beta"
        or steps[0].get("detail", {}).get("result")
        != "clicked_measured_top_plate"
        or dismissal.get("final_surface") != UNDERLAY_SCREEN_ID
    ):
        raise SemanticDialogCompositeBuildError(
            f"v2.17 {role} dismissal did not use the measured top plate"
        )
    return {
        "role": role,
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "source": copy.deepcopy(source),
        "profile_state": copy.deepcopy(profile),
        "captured_at_utc": header.get("captured_at_utc"),
        "profile_state_identity_sha256": profile[
            "profile_state_identity_sha256"
        ],
        "operator_tag": observed.get("operator_tag"),
        "capture_surface": observed.get("capture_surface"),
        "machine_classified_surface": observed.get(
            "machine_classified_surface"
        ),
        "gate_result": observed.get("gate_result"),
        "settled_sample_count": sample_count,
        "stable_span_milliseconds": stable_span,
        "settle_latency_milliseconds": recording["settlement"][
            "settle_latency_milliseconds"
        ],
        "semantic_generation": recording.get("semantic_generation"),
        "layout_generation": payload.get("generation"),
        "settled_payload": payload,
        "semantic_multiset_sha256": canonical_sha256(
            counter_entries(semantic_counter(payload["elements"]))
        ),
        "recording": evidence_receipt(trace_path, evidence_root),
        "observation": evidence_receipt(observation_path, evidence_root),
        "dismissal_receipt": evidence_receipt(dismissal_path, evidence_root),
        "player_visible_dialog_frame": evidence_receipt(
            dialog_frame, evidence_root
        ),
        "post_dismissal_underlay_frame": evidence_receipt(
            underlay_frame, evidence_root
        ),
        "pixel_delta": _pixel_delta(dialog_frame, underlay_frame),
        "measured_click": copy.deepcopy(steps[0]["detail"]),
    }


def _derive_paint_contract(
    qualified_beta_path: Path,
    qualified_layout: dict[str, Any],
    overlay_reference: dict[str, Any],
    legacy_contract: dict[str, Any],
    legacy_contract_receipt: dict[str, Any],
) -> dict[str, Any]:
    elements = qualified_layout.get("elements")
    legacy_members = legacy_contract.get("moved_members")
    if (
        legacy_contract.get("schema")
        != "solomon-dark-native-menu-beta-notice-order-v29"
        or not isinstance(elements, list)
        or len(elements) < 3
        or not isinstance(legacy_members, list)
        or len(legacy_members) != 3
    ):
        raise SemanticDialogCompositeBuildError(
            "v2.17 cannot re-derive the bounded v2.9 paint-order witness"
        )
    ordered_hashes = [canonical_sha256(semantic_member(element)) for element in elements]
    legacy_hashes = [member.get("semantic_sha256") for member in legacy_members]
    if ordered_hashes[-3:] != legacy_hashes:
        raise SemanticDialogCompositeBuildError(
            "v2.17 qualified beta core does not reproduce the bounded final paint group"
        )
    overlay_counter = Counter()
    for entry in overlay_reference.get("overlay_semantic_draw_multiset", []):
        signature = canonical_bytes(entry["payload"])
        overlay_counter[signature] = entry["count"]
    final_group: list[dict[str, Any]] = []
    for index, (element, legacy) in enumerate(
        zip(elements[-3:], legacy_members, strict=True), start=len(elements) - 3
    ):
        signature = canonical_bytes(semantic_member(element))
        if overlay_counter[signature] <= 0:
            raise SemanticDialogCompositeBuildError(
                "v2.17 final paint group is not inside the derived overlay reference"
            )
        final_group.append(
            {
                "relative_core_index": index,
                "art_id": element.get("art_id"),
                "rect": copy.deepcopy(element.get("rect")),
                "unclipped_rect": copy.deepcopy(element.get("unclipped_rect")),
                "semantic_sha256": ordered_hashes[index],
                "native_paint_order": legacy.get("native_paint_order"),
                "overlay_reference_member": True,
            }
        )
    return {
        "schema": "solomon-dark-native-menu-beta-notice-paint-order-v217",
        "settlement_spec": COMPOSITE_SETTLEMENT_SPEC,
        "layout_id": "beta-notice",
        "screen_id": OPERATOR_TAG,
        "core_member_count": len(elements),
        "ordered_semantic_sha256": ordered_hashes,
        "ordered_core_sha256": canonical_sha256(ordered_hashes),
        "final_paint_group": final_group,
        "qualified_fixture": fixture_receipt(
            qualified_beta_path, "menu-layouts/beta-notice.json"
        ),
        "superseded_contract": legacy_contract_receipt,
        "disposition": (
            "re-derived against the qualified 28-member pause-entry core; "
            "the obsolete 34-member landed-comparison identity is retired"
        ),
        "paint_truth": copy.deepcopy(legacy_contract.get("paint_truth")),
    }


def build(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    output_path: Path,
    supersession_contract_path: Path,
    paint_contract_path: Path,
) -> dict[str, Any]:
    picker_path = candidate_root / "menu-layouts/control-scheme-picker.json"
    beta_path = candidate_root / "menu-layouts/beta-notice.json"
    overlay_path = candidate_root / "menu-overlay-reference.json"
    picker_fixture = read_object(picker_path, "qualified picker fixture")
    beta_fixture = read_object(beta_path, "qualified beta fixture")
    overlay_reference = read_object(overlay_path, "derived overlay reference")
    picker_layout = picker_fixture.get("layout")
    beta_layout = beta_fixture.get("layout")
    if not isinstance(picker_layout, dict) or not isinstance(beta_layout, dict):
        raise SemanticDialogCompositeBuildError(
            "v2.17 qualified screen fixtures have no layouts"
        )
    observations = [
        _normalize_observation(
            role="primary", root=PRIMARY_ROOT, evidence_root=evidence_root
        ),
        _normalize_observation(
            role="confirmation",
            root=CONFIRMATION_ROOT,
            evidence_root=evidence_root,
        ),
    ]
    try:
        derived = classify_semantic_dialog_composite(
            observations, picker_layout, overlay_reference, beta_layout
        )
    except NativeMenuSemanticDialogCompositeError as error:
        raise SemanticDialogCompositeBuildError(str(error)) from error
    primary = next(value for value in observations if value["role"] == "primary")
    confirmation = next(
        value for value in observations if value["role"] == "confirmation"
    )
    if primary["source"] != confirmation["source"]:
        raise SemanticDialogCompositeBuildError(
            "v2.17 pair changed machine-derived executable/loader provenance"
        )
    if (
        primary["player_visible_dialog_frame"]["sha256"]
        != confirmation["player_visible_dialog_frame"]["sha256"]
        or primary["post_dismissal_underlay_frame"]["sha256"]
        != confirmation["post_dismissal_underlay_frame"]["sha256"]
    ):
        raise SemanticDialogCompositeBuildError(
            "v2.17 pair did not reproduce both frames bit-exactly"
        )
    primary_png = evidence_root / PRIMARY_ROOT / "beta-notice-overlay.png"
    reference_path = candidate_root / REFERENCE_RELATIVE_PATH
    _atomic_copy(primary_png, reference_path)

    audit_path = evidence_root / QUESTION_AUDIT
    manifest_path = evidence_root / QUESTION_MANIFEST
    audit_receipt = evidence_receipt(audit_path, evidence_root)
    manifest_receipt = evidence_receipt(manifest_path, evidence_root)
    dialog_entries = derived.pop("dialog_semantic_multiset")
    derived_dismissal = derived.pop("dismissal")
    pixel_delta = derived.pop("pixel_delta")
    classification = copy.deepcopy(derived)
    record = {
        "schema": COMPOSITE_SCHEMA,
        "settlement_spec": COMPOSITE_SETTLEMENT_SPEC,
        "composite_id": COMPOSITE_ID,
        "header": {
            "campaign": "menufix",
            "gap": "G11",
            "recorded_live": True,
            "source": copy.deepcopy(primary["source"]),
            "profile_state": copy.deepcopy(primary["profile_state"]),
            "captured_at_utc": primary["captured_at_utc"],
            "question_audit": audit_receipt,
            "question_manifest": manifest_receipt,
            "reference_capture": fixture_receipt(
                reference_path,
                "menu-reference-captures/beta-notice-first-boot.png",
            ),
        },
        "composite": {
            "classification": classification,
            "underlay_binding": {
                "layout_id": UNDERLAY_LAYOUT_ID,
                "screen_id": UNDERLAY_SCREEN_ID,
                "fixture": fixture_receipt(
                    picker_path, "menu-layouts/control-scheme-picker.json"
                ),
                "member_count": classification["underlay_member_count"],
                "semantic_multiset_sha256": classification[
                    "underlay_semantic_multiset_sha256"
                ],
            },
            "derived_overlay_reference": {
                "fixture": fixture_receipt(
                    overlay_path, "menu-overlay-reference.json"
                ),
                "semantic_draw_count": overlay_reference.get(
                    "overlay_semantic_draw_count"
                ),
                "corroboration": copy.deepcopy(overlay_reference.get("header")),
            },
            "qualified_beta_screen": {
                "fixture": fixture_receipt(
                    beta_path, "menu-layouts/beta-notice.json"
                ),
                "route": "pause_menu.leave_game -> beta_notice",
                "source_audit": audit_receipt,
            },
            "dialog_semantic_multiset": {
                "member_count": classification["dialog_member_count"],
                "art_member_count": classification["dialog_art_member_count"],
                "text_member_count": classification["dialog_text_member_count"],
                "semantic_multiset_sha256": classification[
                    "dialog_semantic_multiset_sha256"
                ],
                "entries": dialog_entries,
            },
            "decomposition": {
                "equation": "composite = qualified underlay + dialog multiset",
                "composite_member_count": classification[
                    "composite_member_count"
                ],
                "underlay_member_count": classification[
                    "underlay_member_count"
                ],
                "dialog_member_count": classification["dialog_member_count"],
                "residual_member_count": 0,
                "full_semantic_multiset_sha256": classification[
                    "full_semantic_multiset_sha256"
                ],
            },
            "observations": observations,
            "frames": {
                "player_visible_dialog_sha256": classification[
                    "player_visible_dialog_frame_sha256"
                ],
                "post_dismissal_underlay_sha256": classification[
                    "post_dismissal_underlay_frame_sha256"
                ],
                "cross_instance_bit_equal": True,
            },
            "dismissal": {
                **derived_dismissal,
                "measured_member_id": primary["measured_click"].get(
                    "element_id"
                ),
                "measured_rect": copy.deepcopy(
                    primary["measured_click"].get("rect")
                ),
                "measured_client_point": copy.deepcopy(
                    primary["measured_click"].get("client_point")
                ),
                "action_measurement_source": (
                    "unique visible interactive dialog.primary member in the "
                    "qualified pause-entry beta_notice screen"
                ),
                "pixel_delta": pixel_delta,
                "evidence_only_interaction": True,
            },
        },
        "navigation": {
            "type": "dialog_composite",
            "entry_state_id": COMPOSITE_ID,
            "entry_selector": "pristine fresh process launch",
            "dismissal_edge_id": (
                "beta_notice_first_boot_to_control_scheme_picker"
            ),
            "trigger": "dialog_primary",
            "action_id": DISMISSAL_ACTION_ID,
            "destination_layout_id": UNDERLAY_LAYOUT_ID,
            "destination_surface_id": UNDERLAY_SCREEN_ID,
            "destination_fixture": "menu-layouts/control-scheme-picker.json",
        },
    }
    try:
        validate_composite_record(
            record, picker_layout, overlay_reference, beta_layout
        )
    except NativeMenuSemanticDialogCompositeError as error:
        raise SemanticDialogCompositeBuildError(str(error)) from error
    _atomic_json(output_path, record)

    legacy_evidence_path = evidence_root / LEGACY_ORDER_EVIDENCE
    if not legacy_evidence_path.is_file():
        raise SemanticDialogCompositeBuildError(
            "v2.17 re-derivation lost the sealed legacy v2.9 evidence witness"
        )
    legacy_contract = read_object(
        legacy_evidence_path, "archived legacy v2.9 paint contract"
    )
    paint_contract = _derive_paint_contract(
        beta_path,
        beta_layout,
        overlay_reference,
        legacy_contract,
        evidence_receipt(legacy_evidence_path, evidence_root),
    )
    try:
        validate_qualified_beta_paint_order(beta_layout, paint_contract)
    except NativeMenuSemanticDialogCompositeError as error:
        raise SemanticDialogCompositeBuildError(str(error)) from error
    _atomic_json(paint_contract_path, paint_contract)

    landed_beta_path = repo_root / "tests/fixtures/webgame/menu-layouts/beta-notice.json"
    landed_beta = read_object(landed_beta_path, "landed beta-notice fixture")
    landed_layout = landed_beta.get("layout")
    if not isinstance(landed_layout, dict):
        raise SemanticDialogCompositeBuildError(
            "landed beta-notice fixture has no structural payload"
        )
    semantic_hashes = sorted(
        canonical_sha256(semantic_member(element))
        for element in beta_layout["elements"]
    )
    supersession = {
        "schema": "solomon-dark-native-menu-beta-notice-supersession-v217",
        "settlement_spec": COMPOSITE_SETTLEMENT_SPEC,
        "layout_id": "beta-notice",
        "screen_id": OPERATOR_TAG,
        "retired_landed_fixture": fixture_receipt(
            landed_beta_path, "menu-layouts/beta-notice.json"
        ),
        "retired_landed_element_count": len(landed_layout.get("elements", [])),
        "superseding_qualified_fixture": fixture_receipt(
            beta_path, "menu-layouts/beta-notice.json"
        ),
        "superseding_core_member_count": len(beta_layout["elements"]),
        "superseding_semantic_sha256_multiset": semantic_hashes,
        "superseding_semantic_multiset_sha256": canonical_sha256(
            semantic_hashes
        ),
        "qualified_pair": {
            "profile_state_identity_sha256": primary[
                "profile_state_identity_sha256"
            ],
            "route": "pause_menu.leave_game -> beta_notice",
            "primary_trace": copy.deepcopy(
                read_object(audit_path, "v2.17 question audit")[
                    "qualified_pause_entry"
                ]["primary_trace"]
            ),
            "confirmation": copy.deepcopy(
                read_object(audit_path, "v2.17 question audit")[
                    "qualified_pause_entry"
                ]["confirmation"]
            ),
        },
        "source_audit": audit_receipt,
        "source_question_manifest": manifest_receipt,
        "legacy_core_disposition": (
            "retired evidence-of-era only; unqualified provenance and "
            "main-menu underlay contamination"
        ),
        "authorization_scope": (
            "exact qualified pause-entry beta-notice core only; no general "
            "landed-vs-settled tolerance"
        ),
    }
    _atomic_json(supersession_contract_path, supersession)
    return {
        "success": True,
        "composite": fixture_receipt(
            output_path, COMPOSITE_RELATIVE_PATH.as_posix()
        ),
        "reference_capture": fixture_receipt(
            reference_path, REFERENCE_RELATIVE_PATH.as_posix()
        ),
        "supersession_contract": fixture_receipt(
            supersession_contract_path,
            "native-menu-beta-notice-supersession-v217.json",
        ),
        "paint_order_contract": fixture_receipt(
            paint_contract_path,
            "native-menu-beta-notice-paint-order-v217.json",
        ),
        "state_count_delta": 1,
        "edge_count_delta": 1,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--supersession-contract-output", type=Path, required=True
    )
    parser.add_argument("--paint-contract-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = build(
            args.repo_root.resolve(),
            args.candidate_root.resolve(),
            args.evidence_root.resolve(),
            args.output.resolve(),
            args.supersession_contract_output.resolve(),
            args.paint_contract_output.resolve(),
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        NativeMenuSemanticDialogCompositeError,
        SemanticDialogCompositeBuildError,
    ) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
