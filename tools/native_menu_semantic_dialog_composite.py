#!/usr/bin/env python3
"""Settlement v2.17 semantic-dialog composite classification.

The native member hook reports the screen below a dialog as the semantic
surface.  A dialog composite therefore has two independently measured parts:
the qualified underlay core and the dialog contribution obtained by exact
semantic-multiset subtraction.  Synthetic member ordinals and absolute draw
orders are bookkeeping and never participate in the subtraction.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from typing import Any, Iterable


COMPOSITE_SCHEMA = "solomon-dark-native-menu-semantic-dialog-composite-v1"
COMPOSITE_SETTLEMENT_SPEC = "2.17"
COMPOSITE_ID = "beta_notice_first_boot"
UNDERLAY_LAYOUT_ID = "control-scheme-picker"
UNDERLAY_SCREEN_ID = "control_scheme_picker"
OPERATOR_TAG = "beta_notice"
CAPTURE_SURFACE = "dialog"
DISMISSAL_ACTION_ID = "dialog.primary"

SURFACE_AGREEMENT_STOP = (
    "STOP: native-menu capture surface agreement rejected: operator tag "
    "'beta_notice' does not equal machine-classified surface "
    "'control_scheme_picker' through capture surface 'dialog'."
)
OVERLAY_HYGIENE_STOP = (
    "overlay hygiene contract: non-overlay screen contains the complete "
    "derived beta-dialog semantic multiset"
)
DIALOG_REFERENCE_REASON = (
    "semantic dialog composite dialog multiset differs from the derived reference"
)
DECOMPOSITION_RESIDUE_REASON = (
    "semantic dialog composite decomposition leaves a residual member"
)
FRAME_AGREEMENT_REASON = (
    "semantic dialog composite frames did not reproduce bit-exactly across instances"
)
LEGACY_PROVENANCE_REASON = (
    "semantic dialog composite legacy beta-notice core has unqualified provenance"
)
PAINT_ORDER_REASON = (
    "semantic dialog composite qualified beta-notice paint-order contract differs"
)


class NativeMenuSemanticDialogCompositeError(RuntimeError):
    """One measured v2.17 precondition or exact record claim is false."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def semantic_member(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in {"id", "draw_order", "draw_order_semantics"}
    }


def semantic_counter(elements: Iterable[dict[str, Any]]) -> Counter[bytes]:
    return Counter(canonical_bytes(semantic_member(element)) for element in elements)


def counter_entries(counter: Counter[bytes]) -> list[dict[str, Any]]:
    return [
        {
            "count": counter[signature],
            "payload": json.loads(signature.decode("utf-8")),
        }
        for signature in sorted(counter)
        if counter[signature] > 0
    ]


def counter_from_entries(
    entries: object, consequence: str
) -> Counter[bytes]:
    if not isinstance(entries, list) or not entries:
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: semantic multiset is absent"
        )
    result: Counter[bytes] = Counter()
    previous: bytes | None = None
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise NativeMenuSemanticDialogCompositeError(
                f"{consequence}: entry {index} is not an object"
            )
        count = entry.get("count")
        payload = entry.get("payload")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
            or not isinstance(payload, dict)
        ):
            raise NativeMenuSemanticDialogCompositeError(
                f"{consequence}: entry {index} is incomplete"
            )
        signature = canonical_bytes(payload)
        if previous is not None and signature <= previous:
            raise NativeMenuSemanticDialogCompositeError(
                f"{consequence}: semantic multiset is not canonical"
            )
        previous = signature
        result[signature] = count
    return result


def _elements(layout: object, consequence: str) -> list[dict[str, Any]]:
    if not isinstance(layout, dict):
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: layout is absent"
        )
    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements or not all(
        isinstance(element, dict) for element in elements
    ):
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: layout reached no semantic members"
        )
    return elements


def _lower_sha256(value: object, consequence: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: receipt is not a lowercase SHA-256"
        )
    return value


def _evidence_receipt(value: object, consequence: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: evidence receipt is absent"
        )
    path = value.get("evidence_path")
    size = value.get("bytes")
    if (
        not isinstance(path, str)
        or not path
        or path.startswith(("/", "\\"))
        or ".." in path.replace("\\", "/").split("/")
    ):
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: evidence path is not campaign-relative"
        )
    _lower_sha256(value.get("sha256"), consequence)
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: evidence receipt has no positive byte count"
        )
    return value


def _fixture_receipt(value: object, consequence: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: committed fixture receipt is absent"
        )
    fixture = value.get("fixture")
    size = value.get("bytes")
    if (
        not isinstance(fixture, str)
        or not fixture
        or fixture.startswith(("/", "\\"))
        or ".." in fixture.replace("\\", "/").split("/")
    ):
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: committed fixture path is invalid"
        )
    _lower_sha256(value.get("sha256"), consequence)
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise NativeMenuSemanticDialogCompositeError(
            f"{consequence}: committed fixture byte count is invalid"
        )
    return value


def _overlay_reference_counter(reference: dict[str, Any]) -> Counter[bytes]:
    entries = reference.get("overlay_semantic_draw_multiset")
    return counter_from_entries(entries, DIALOG_REFERENCE_REASON)


def _qualified_dismissal_action(
    qualified_beta_layout: dict[str, Any],
) -> dict[str, Any]:
    matches = [
        element
        for element in _elements(
            qualified_beta_layout,
            "semantic dialog composite qualified beta-notice action binding",
        )
        if element.get("action_id") == DISMISSAL_ACTION_ID
        and element.get("interactive") is True
        and element.get("visible") is True
    ]
    if len(matches) != 1:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite dismissal action is absent or ambiguous"
        )
    return matches[0]


def _classify_observations(
    observations: object,
) -> tuple[list[dict[str, Any]], Counter[bytes]]:
    if not isinstance(observations, list) or len(observations) != 2:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite requires exactly two fresh instances"
        )
    roles: set[str] = set()
    identities: set[tuple[str, int]] = set()
    profile_identities: set[str] = set()
    payload_counters: list[Counter[bytes]] = []
    visible_frames: set[str] = set()
    dismissal_frames: set[str] = set()
    delta_bounding_boxes: set[bytes] = set()
    delta_pixel_counts: set[int] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            raise NativeMenuSemanticDialogCompositeError(
                "semantic dialog composite observation is not an object"
            )
        role = observation.get("role")
        instance = observation.get("instance")
        process_id = observation.get("process_id")
        if role not in {"primary", "confirmation"}:
            raise NativeMenuSemanticDialogCompositeError(
                "semantic dialog composite lost primary/confirmation roles"
            )
        if (
            not isinstance(instance, str)
            or not instance
            or isinstance(process_id, bool)
            or not isinstance(process_id, int)
            or process_id <= 0
        ):
            raise NativeMenuSemanticDialogCompositeError(
                "semantic dialog composite has no exact process identity"
            )
        if (
            observation.get("operator_tag") != OPERATOR_TAG
            or observation.get("capture_surface") != CAPTURE_SURFACE
            or observation.get("machine_classified_surface")
            != UNDERLAY_SCREEN_ID
            or observation.get("gate_result") != SURFACE_AGREEMENT_STOP
        ):
            raise NativeMenuSemanticDialogCompositeError(
                "semantic dialog composite did not reproduce the exact surface-agreement rejection"
            )
        if (
            observation.get("settled_sample_count", 0) < 40
            or observation.get("stable_span_milliseconds", 0) < 2_000
        ):
            raise NativeMenuSemanticDialogCompositeError(
                "semantic dialog composite did not retain a forty-sample two-second window"
            )
        profile_identities.add(
            _lower_sha256(
                observation.get("profile_state_identity_sha256"),
                "semantic dialog composite profile-state provenance",
            )
        )
        _evidence_receipt(
            observation.get("recording"),
            "semantic dialog composite settled recording",
        )
        visible = _evidence_receipt(
            observation.get("player_visible_dialog_frame"),
            "semantic dialog composite player-visible frame",
        )
        dismissed = _evidence_receipt(
            observation.get("post_dismissal_underlay_frame"),
            "semantic dialog composite post-dismissal frame",
        )
        delta = observation.get("pixel_delta")
        if (
            not isinstance(delta, dict)
            or not isinstance(delta.get("bounding_box"), list)
            or len(delta["bounding_box"]) != 4
            or isinstance(delta.get("differing_pixel_count"), bool)
            or not isinstance(delta.get("differing_pixel_count"), int)
            or delta["differing_pixel_count"] <= 0
        ):
            raise NativeMenuSemanticDialogCompositeError(
                "semantic dialog composite has no measured player-visible pixel delta"
            )
        payload = observation.get("settled_payload")
        if not isinstance(payload, dict) or payload.get("screen_id") != UNDERLAY_SCREEN_ID:
            raise NativeMenuSemanticDialogCompositeError(
                "semantic dialog composite settled payload changed its machine underlay"
            )
        payload_counters.append(
            semantic_counter(
                _elements(payload, "semantic dialog composite settled payload")
            )
        )
        roles.add(role)
        identities.add((instance, process_id))
        visible_frames.add(visible["sha256"])
        dismissal_frames.add(dismissed["sha256"])
        delta_bounding_boxes.add(canonical_bytes(delta["bounding_box"]))
        delta_pixel_counts.add(delta["differing_pixel_count"])
    if roles != {"primary", "confirmation"} or len(identities) != 2:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite confirmation reused an instance"
        )
    if len(profile_identities) != 1:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite pair changed profile-state identity"
        )
    if payload_counters[0] != payload_counters[1]:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite canonical member multisets differ across instances"
        )
    if (
        len(visible_frames) != 1
        or len(dismissal_frames) != 1
        or len(delta_bounding_boxes) != 1
        or len(delta_pixel_counts) != 1
    ):
        raise NativeMenuSemanticDialogCompositeError(FRAME_AGREEMENT_REASON)
    return observations, payload_counters[0]


def classify_semantic_dialog_composite(
    observations: object,
    underlay_layout: dict[str, Any],
    overlay_reference: dict[str, Any],
    qualified_beta_layout: dict[str, Any],
    *,
    model_enabled: bool = True,
    disabled_guard: str = "surface_agreement",
) -> dict[str, Any]:
    """Classify the one authorized pristine beta-dialog composite."""

    if not model_enabled:
        if disabled_guard == "overlay_hygiene":
            raise NativeMenuSemanticDialogCompositeError(OVERLAY_HYGIENE_STOP)
        raise NativeMenuSemanticDialogCompositeError(SURFACE_AGREEMENT_STOP)
    pair, full = _classify_observations(observations)
    if (
        underlay_layout.get("screen_id") != UNDERLAY_SCREEN_ID
        or qualified_beta_layout.get("screen_id") != OPERATOR_TAG
    ):
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite is scoped only to beta over control-scheme picker"
        )
    underlay = semantic_counter(
        _elements(underlay_layout, "semantic dialog composite qualified underlay")
    )
    missing_underlay = underlay - full
    if missing_underlay:
        raise NativeMenuSemanticDialogCompositeError(DECOMPOSITION_RESIDUE_REASON)
    dialog = full - underlay
    if full != underlay + dialog:
        raise NativeMenuSemanticDialogCompositeError(DECOMPOSITION_RESIDUE_REASON)
    overlay = _overlay_reference_counter(overlay_reference)
    dialog_art = Counter(
        signature
        for signature, count in dialog.items()
        for _ in range(count)
        if json.loads(signature.decode("utf-8")).get("kind") == "art"
    )
    if dialog_art != overlay:
        raise NativeMenuSemanticDialogCompositeError(DIALOG_REFERENCE_REASON)
    dialog_non_art = [
        json.loads(signature.decode("utf-8"))
        for signature, count in dialog.items()
        for _ in range(count)
        if json.loads(signature.decode("utf-8")).get("kind") != "art"
    ]
    if not dialog_non_art or any(
        member.get("kind") != "text"
        or not member.get("text")
        or member.get("action_id")
        or member.get("interactive") is not False
        for member in dialog_non_art
    ):
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite dialog remainder is not pure measured text"
        )
    action_member = _qualified_dismissal_action(qualified_beta_layout)
    plate_matches = [
        json.loads(signature.decode("utf-8"))
        for signature, count in overlay.items()
        for _ in range(count)
        if json.loads(signature.decode("utf-8")).get("art_id") == "UI.101"
    ]
    if len(plate_matches) != 1:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite dismissal plate is absent or ambiguous"
        )
    primary = next(value for value in pair if value["role"] == "primary")
    return {
        "classification": "semantic_dialog_composite",
        "composite_id": COMPOSITE_ID,
        "operator_tag": OPERATOR_TAG,
        "capture_surface": CAPTURE_SURFACE,
        "underlay_surface_id": UNDERLAY_SCREEN_ID,
        "profile_state_identity_sha256": primary[
            "profile_state_identity_sha256"
        ],
        "independent_instance_count": 2,
        "composite_member_count": sum(full.values()),
        "underlay_member_count": sum(underlay.values()),
        "dialog_member_count": sum(dialog.values()),
        "dialog_art_member_count": sum(dialog_art.values()),
        "dialog_text_member_count": len(dialog_non_art),
        "full_semantic_multiset_sha256": canonical_sha256(
            counter_entries(full)
        ),
        "underlay_semantic_multiset_sha256": canonical_sha256(
            counter_entries(underlay)
        ),
        "dialog_semantic_multiset_sha256": canonical_sha256(
            counter_entries(dialog)
        ),
        "dialog_semantic_multiset": counter_entries(dialog),
        "dismissal": {
            "action_id": DISMISSAL_ACTION_ID,
            "measured_plate_payload": plate_matches[0],
            "qualified_action_member": semantic_member(action_member),
        },
        "player_visible_dialog_frame_sha256": primary[
            "player_visible_dialog_frame"
        ]["sha256"],
        "post_dismissal_underlay_frame_sha256": primary[
            "post_dismissal_underlay_frame"
        ]["sha256"],
        "pixel_delta": copy.deepcopy(primary["pixel_delta"]),
    }


def validate_composite_record(
    record: dict[str, Any],
    underlay_layout: dict[str, Any],
    overlay_reference: dict[str, Any],
    qualified_beta_layout: dict[str, Any],
) -> dict[str, Any]:
    if record.get("schema") != COMPOSITE_SCHEMA:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite record schema is not recognized"
        )
    if record.get("settlement_spec") != COMPOSITE_SETTLEMENT_SPEC:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite record is not bound to Settlement v2.17"
        )
    if record.get("composite_id") != COMPOSITE_ID:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite authorization names another state"
        )
    composite = record.get("composite")
    if not isinstance(composite, dict):
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite record has no composite payload"
        )
    observations = composite.get("observations")
    derived = classify_semantic_dialog_composite(
        observations,
        underlay_layout,
        overlay_reference,
        qualified_beta_layout,
    )
    recorded_dialog = composite.get("dialog_semantic_multiset")
    if not isinstance(recorded_dialog, dict):
        raise NativeMenuSemanticDialogCompositeError(DIALOG_REFERENCE_REASON)
    recorded_counter = counter_from_entries(
        recorded_dialog.get("entries"), DIALOG_REFERENCE_REASON
    )
    recorded_art = Counter(
        signature
        for signature, count in recorded_counter.items()
        for _ in range(count)
        if json.loads(signature.decode("utf-8")).get("kind") == "art"
    )
    if recorded_art != _overlay_reference_counter(overlay_reference):
        raise NativeMenuSemanticDialogCompositeError(DIALOG_REFERENCE_REASON)
    observed_full = semantic_counter(
        _elements(
            observations[0].get("settled_payload"),
            "semantic dialog composite recorded observation",
        )
    )
    underlay = semantic_counter(
        _elements(underlay_layout, "semantic dialog composite recorded underlay")
    )
    if observed_full != underlay + recorded_counter:
        raise NativeMenuSemanticDialogCompositeError(DECOMPOSITION_RESIDUE_REASON)
    if (
        recorded_counter
        != counter_from_entries(
            derived["dialog_semantic_multiset"], DIALOG_REFERENCE_REASON
        )
        or recorded_dialog.get("member_count") != sum(recorded_counter.values())
        or recorded_dialog.get("semantic_multiset_sha256")
        != canonical_sha256(counter_entries(recorded_counter))
    ):
        raise NativeMenuSemanticDialogCompositeError(DIALOG_REFERENCE_REASON)
    classification = composite.get("classification")
    expected_classification = {
        key: copy.deepcopy(value)
        for key, value in derived.items()
        if key not in {"dialog_semantic_multiset", "dismissal", "pixel_delta"}
    }
    if classification != expected_classification:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite record carries a false classification receipt"
        )
    underlay_binding = composite.get("underlay_binding")
    dialog_reference = composite.get("derived_overlay_reference")
    qualified_beta = composite.get("qualified_beta_screen")
    if (
        not isinstance(underlay_binding, dict)
        or underlay_binding.get("layout_id") != UNDERLAY_LAYOUT_ID
        or underlay_binding.get("screen_id") != UNDERLAY_SCREEN_ID
        or underlay_binding.get("member_count") != derived["underlay_member_count"]
        or not isinstance(dialog_reference, dict)
        or not isinstance(qualified_beta, dict)
    ):
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite underlay or dialog binding changed identity"
        )
    _fixture_receipt(
        underlay_binding.get("fixture"),
        "semantic dialog composite underlay fixture",
    )
    _fixture_receipt(
        dialog_reference.get("fixture"),
        "semantic dialog composite overlay reference",
    )
    _fixture_receipt(
        qualified_beta.get("fixture"),
        "semantic dialog composite qualified beta screen",
    )
    dismissal = composite.get("dismissal")
    if (
        not isinstance(dismissal, dict)
        or dismissal.get("action_id") != DISMISSAL_ACTION_ID
        or dismissal.get("measured_plate_payload")
        != derived["dismissal"]["measured_plate_payload"]
        or dismissal.get("qualified_action_member")
        != derived["dismissal"]["qualified_action_member"]
        or dismissal.get("pixel_delta") != derived["pixel_delta"]
    ):
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite dismissal control or pixel delta changed"
        )
    navigation = record.get("navigation")
    if (
        not isinstance(navigation, dict)
        or navigation.get("type") != "dialog_composite"
        or navigation.get("entry_state_id") != COMPOSITE_ID
        or navigation.get("dismissal_edge_id")
        != "beta_notice_first_boot_to_control_scheme_picker"
        or navigation.get("action_id") != DISMISSAL_ACTION_ID
        or navigation.get("destination_layout_id") != UNDERLAY_LAYOUT_ID
        or navigation.get("destination_surface_id") != UNDERLAY_SCREEN_ID
    ):
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite navigation binding changed"
        )
    return derived


def validate_qualified_beta_paint_order(
    layout: dict[str, Any], contract: dict[str, Any]
) -> None:
    if (
        contract.get("schema")
        != "solomon-dark-native-menu-beta-notice-paint-order-v217"
        or contract.get("layout_id") != "beta-notice"
        or contract.get("screen_id") != OPERATOR_TAG
        or contract.get("core_member_count") != len(_elements(layout, PAINT_ORDER_REASON))
    ):
        raise NativeMenuSemanticDialogCompositeError(PAINT_ORDER_REASON)
    elements = _elements(layout, PAINT_ORDER_REASON)
    semantic_hashes = [canonical_sha256(semantic_member(element)) for element in elements]
    expected_hashes = contract.get("ordered_semantic_sha256")
    final_group = contract.get("final_paint_group")
    if (
        semantic_hashes != expected_hashes
        or not isinstance(final_group, list)
        or len(final_group) != 3
        or [member.get("relative_core_index") for member in final_group]
        != list(range(len(elements) - 3, len(elements)))
        or [member.get("semantic_sha256") for member in final_group]
        != semantic_hashes[-3:]
    ):
        raise NativeMenuSemanticDialogCompositeError(PAINT_ORDER_REASON)


def validate_qualified_beta_supersession(
    contract: dict[str, Any],
    *,
    landed_fixture_receipt: dict[str, Any],
    candidate_fixture_receipt: dict[str, Any],
    candidate_fixture: dict[str, Any],
) -> dict[str, Any]:
    """Validate the exact Controls-style v2.17 beta screen supersession."""

    if (
        contract.get("schema")
        != "solomon-dark-native-menu-beta-notice-supersession-v217"
        or contract.get("settlement_spec") != COMPOSITE_SETTLEMENT_SPEC
        or contract.get("layout_id") != "beta-notice"
        or contract.get("screen_id") != OPERATOR_TAG
    ):
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite beta-notice supersession changed scope"
        )
    header = candidate_fixture.get("header")
    layout = candidate_fixture.get("layout")
    profile = header.get("profile_state") if isinstance(header, dict) else None
    source = header.get("source") if isinstance(header, dict) else None
    if (
        not isinstance(header, dict)
        or not isinstance(layout, dict)
        or not isinstance(profile, dict)
        or not isinstance(source, dict)
        or profile.get("baseline_id") != "pristine_fresh_install"
        or profile.get("durable_file_count") != 0
        or profile.get("profile_state_identity_sha256")
        != source.get("profile_state_identity_sha256")
    ):
        raise NativeMenuSemanticDialogCompositeError(LEGACY_PROVENANCE_REASON)
    expected_landed = contract.get("retired_landed_fixture")
    expected_candidate = contract.get("superseding_qualified_fixture")
    if expected_landed != landed_fixture_receipt:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite beta-notice supersession landed receipt differs"
        )
    if expected_candidate != candidate_fixture_receipt:
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite beta-notice supersession candidate receipt differs"
        )
    elements = _elements(layout, "semantic dialog composite qualified beta screen")
    hashes = sorted(canonical_sha256(semantic_member(element)) for element in elements)
    if (
        contract.get("superseding_core_member_count") != len(elements)
        or contract.get("superseding_semantic_sha256_multiset") != hashes
        or contract.get("superseding_semantic_multiset_sha256")
        != canonical_sha256(hashes)
    ):
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite exact qualified beta-notice core differs"
        )
    qualified_pair = contract.get("qualified_pair")
    if (
        not isinstance(qualified_pair, dict)
        or qualified_pair.get("profile_state_identity_sha256")
        != profile.get("profile_state_identity_sha256")
        or qualified_pair.get("route")
        != "pause_menu.leave_game -> beta_notice"
    ):
        raise NativeMenuSemanticDialogCompositeError(
            "semantic dialog composite qualified beta-notice pair lost its route or baseline"
        )
    return {
        "status": "corrected",
        "settlement_spec": COMPOSITE_SETTLEMENT_SPEC,
        "reason": "qualified_pause_entry_supersedes_unqualified_legacy_underlay_capture",
        "retired_landed_fixture": copy.deepcopy(expected_landed),
        "superseding_qualified_fixture": copy.deepcopy(expected_candidate),
        "new_structural_core_element_count": len(elements),
        "source_audit": copy.deepcopy(contract.get("source_audit")),
        "legacy_core_disposition": contract.get("legacy_core_disposition"),
    }
