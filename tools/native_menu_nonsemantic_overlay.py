#!/usr/bin/env python3
"""Settlement v2.15 non-semantic overlay classification and validation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


OVERLAY_SCHEMA = "solomon-dark-native-menu-nonsemantic-overlay-v1"
OVERLAY_SETTLEMENT_SPEC = "2.15"
TAG_DISAGREEMENT_REASON = (
    "native-menu capture surface agreement rejected: operator tag "
    "'dark_cloud_settings' does not equal machine-classified surface 'main_menu' "
    "through capture surface 'dark_cloud_settings'."
)
TAG_AGREEMENT_CLASSIFICATION_REASON = (
    "non-semantic overlay classification requires operator/machine tag disagreement"
)
SEMANTIC_MEMBER_REASON = (
    "non-semantic overlay record must declare zero semantic members of its own"
)
UNDERLYING_AGREEMENT_REASON = (
    "non-semantic overlay underlying surface text/action agreement failed"
)
VISUAL_DIFFERENCE_REASON = (
    "non-semantic overlay player-visible frame does not differ from the accepted "
    "underlying surface visual"
)


class NativeMenuNonSemanticOverlayError(RuntimeError):
    """The proposed state does not satisfy the bounded v2.15 overlay seam."""


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _lower_sha256(value: object, consequence: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise NativeMenuNonSemanticOverlayError(
            f"{consequence}: receipt is not a lowercase SHA-256"
        )
    return value


def _receipt(value: object, consequence: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NativeMenuNonSemanticOverlayError(
            f"{consequence}: evidence receipt is absent"
        )
    path = value.get("evidence_path")
    size = value.get("bytes")
    if not isinstance(path, str) or not path or path.startswith(("/", "\\")):
        raise NativeMenuNonSemanticOverlayError(
            f"{consequence}: evidence receipt path is not campaign-relative"
        )
    _lower_sha256(value.get("sha256"), consequence)
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise NativeMenuNonSemanticOverlayError(
            f"{consequence}: evidence receipt has no positive byte count"
        )
    return value


def classify_nonsemantic_overlay(
    pair: dict[str, Any], *, seam_enabled: bool = True
) -> dict[str, Any]:
    """Classify one two-instance observation pair under v2.15.

    The input contains only machine-measured facts.  It intentionally has no
    operator-provenance inputs and cannot manufacture source identity.
    """

    observations = pair.get("observations")
    if not isinstance(observations, list) or len(observations) != 2:
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay classification requires exactly two fresh instances"
        )
    roles: set[str] = set()
    identities: set[tuple[str, int]] = set()
    profile_identities: set[str] = set()
    machine_surfaces: set[str] = set()
    operator_tags: set[str] = set()
    payload_hashes: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            raise NativeMenuNonSemanticOverlayError(
                "non-semantic overlay observation is not an object"
            )
        role = observation.get("role")
        instance = observation.get("instance")
        process_id = observation.get("process_id")
        operator_tag = observation.get("operator_tag")
        machine_surface = observation.get("machine_surface")
        sample_count = observation.get("settled_sample_count")
        stable_span = observation.get("stable_span_milliseconds")
        if role not in {"primary", "confirmation"}:
            raise NativeMenuNonSemanticOverlayError(
                "non-semantic overlay pair lost primary/confirmation roles"
            )
        if (
            not isinstance(instance, str)
            or not instance
            or not isinstance(process_id, int)
            or isinstance(process_id, bool)
            or process_id <= 0
        ):
            raise NativeMenuNonSemanticOverlayError(
                "non-semantic overlay pair has no exact process identity"
            )
        if not isinstance(operator_tag, str) or not operator_tag:
            raise NativeMenuNonSemanticOverlayError(
                "non-semantic overlay observation has no operator tag"
            )
        if not isinstance(machine_surface, str) or not machine_surface:
            raise NativeMenuNonSemanticOverlayError(
                "non-semantic overlay observation has no machine surface"
            )
        if operator_tag == machine_surface:
            raise NativeMenuNonSemanticOverlayError(
                TAG_AGREEMENT_CLASSIFICATION_REASON
            )
        if sample_count < 40 or stable_span < 2000:
            raise NativeMenuNonSemanticOverlayError(
                "non-semantic overlay underlying surface did not meet the settle window"
            )
        profile_identity = _lower_sha256(
            observation.get("profile_state_identity_sha256"),
            "non-semantic overlay profile-state provenance",
        )
        payload_hash = _lower_sha256(
            observation.get("text_action_payload_sha256"),
            UNDERLYING_AGREEMENT_REASON,
        )
        _receipt(
            observation.get("recording"),
            "non-semantic overlay settled recording",
        )
        _receipt(observation.get("gate_transcript"), TAG_DISAGREEMENT_REASON)
        frame = observation.get("player_visible_frame")
        if not isinstance(frame, dict):
            raise NativeMenuNonSemanticOverlayError(
                "non-semantic overlay has no player-visible frame comparison"
            )
        _receipt(frame.get("overlay"), "non-semantic overlay visible frame")
        _receipt(
            frame.get("accepted_underlying_surface"),
            "non-semantic overlay accepted underlying visual",
        )
        if (
            frame.get("differs") is not True
            or not isinstance(frame.get("differing_pixel_count"), int)
            or frame["differing_pixel_count"] <= 0
        ):
            raise NativeMenuNonSemanticOverlayError(VISUAL_DIFFERENCE_REASON)
        roles.add(role)
        identities.add((instance, process_id))
        profile_identities.add(profile_identity)
        machine_surfaces.add(machine_surface)
        operator_tags.add(operator_tag)
        payload_hashes.add(payload_hash)
    if not seam_enabled:
        operator_tag = next(iter(operator_tags))
        machine_surface = next(iter(machine_surfaces))
        raise NativeMenuNonSemanticOverlayError(
            "native-menu capture surface agreement rejected: operator tag "
            f"'{operator_tag}' does not equal machine-classified surface "
            f"'{machine_surface}' through capture surface '{operator_tag}'."
        )
    if roles != {"primary", "confirmation"} or len(identities) != 2:
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay confirmation did not use an independent fresh instance"
        )
    if len(profile_identities) != 1:
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay pair changed profile-state identity"
        )
    if len(machine_surfaces) != 1 or len(operator_tags) != 1:
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay pair disagrees on surface classification"
        )
    if len(payload_hashes) != 1:
        raise NativeMenuNonSemanticOverlayError(UNDERLYING_AGREEMENT_REASON)
    return {
        "classification": "non_semantic_overlay",
        "operator_tag": next(iter(operator_tags)),
        "underlying_surface_id": next(iter(machine_surfaces)),
        "profile_state_identity_sha256": next(iter(profile_identities)),
        "text_action_payload_sha256": next(iter(payload_hashes)),
        "independent_instance_count": 2,
    }


def validate_overlay_record(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("schema") != OVERLAY_SCHEMA:
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay record schema is not recognized"
        )
    if record.get("settlement_spec") != OVERLAY_SETTLEMENT_SPEC:
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay record is not bound to Settlement v2.15"
        )
    if record.get("overlay_id") != "dark_cloud_settings_credentials":
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay authorization is scoped to Dark Cloud credentials"
        )
    overlay = record.get("overlay")
    if not isinstance(overlay, dict):
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay record has no overlay payload"
        )
    if (
        overlay.get("members_semantically_observable") is not False
        or overlay.get("semantic_member_count") != 0
        or overlay.get("semantic_members") != []
    ):
        raise NativeMenuNonSemanticOverlayError(SEMANTIC_MEMBER_REASON)
    classification = classify_nonsemantic_overlay(
        {"observations": overlay.get("observations")}
    )
    recorded_classification = overlay.get("classification")
    if not isinstance(recorded_classification, dict) or any(
        recorded_classification.get(field) != value
        for field, value in classification.items()
    ):
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay record carries a false classification receipt"
        )
    activation = overlay.get("activation")
    if not isinstance(activation, dict):
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay record has no measured activating control"
        )
    control = activation.get("measured_control")
    if (
        activation.get("edge_id") != "settings_to_dark_cloud_settings"
        or activation.get("trigger") != "login_info_modify_click"
        or activation.get("evidence_only") is not True
        or activation.get("typed_into_credentials") is not False
        or activation.get("durable_dark_cloud_state_mutated") is not False
        or not isinstance(control, dict)
        or control.get("text") != "DARK CLOUD SETTINGS"
        or control.get("click_point") != [1050.0, 495.0]
    ):
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay activating control is not the measured MODIFY route"
        )
    underlay = overlay.get("semantic_underlay_binding")
    if not isinstance(underlay, dict):
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay lost its gate-agreeing semantic underlay binding"
        )
    if (
        underlay.get("screen_id") != "dark_cloud_settings"
        or underlay.get("operator_machine_tag_agreement") is not True
        or underlay.get("route")
        != "pause -> game settings -> measured MODIFY -> credentials overlay"
        or underlay.get("layout_fixture")
        != "menu-overlay-underlays/dark-cloud-settings.json"
    ):
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay semantic underlay binding changed route or identity"
        )
    _receipt(underlay.get("primary_fixture"), "semantic underlay fixture")
    _receipt(underlay.get("primary_trace"), "semantic underlay primary trace")
    _receipt(underlay.get("confirmation"), "semantic underlay confirmation")
    route_receipts = underlay.get("route_receipts")
    if not isinstance(route_receipts, list) or len(route_receipts) != 2:
        raise NativeMenuNonSemanticOverlayError(
            "semantic underlay route did not reach both fresh instances"
        )
    for receipt in route_receipts:
        _receipt(receipt, "semantic underlay route receipt")
    _lower_sha256(
        underlay.get("primary_structural_sha256"),
        "semantic underlay primary structural binding",
    )
    _lower_sha256(
        underlay.get("confirmation_structural_sha256"),
        "semantic underlay confirmation structural binding",
    )
    if underlay.get("bound_endpoints") != [
        "settings_to_dark_cloud_settings.after",
        "dark_cloud_settings_to_settings.before",
    ]:
        raise NativeMenuNonSemanticOverlayError(
            "semantic underlay binding no longer covers both overlay endpoints"
        )
    supersession = overlay.get("supersession")
    if not isinstance(supersession, dict):
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay record has no retired screen-fixture receipt"
        )
    _receipt(
        supersession.get("retired_landed_screen_fixture"),
        "non-semantic overlay retired fixture",
    )
    if (
        supersession.get("retired_element_count") != 31
        or supersession.get("replacement_kind") != "overlay_record"
    ):
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay did not retire the exact mischaracterized screen"
        )
    motion = overlay.get("motion_witness_disposition")
    if (
        not isinstance(motion, dict)
        or motion.get("element_id") != "dark_cloud_settings.art.ui_28.1"
        or motion.get("disposition")
        != "retired_with_nonsemantic_screen_fixture"
    ):
        raise NativeMenuNonSemanticOverlayError(
            "non-semantic overlay left a vestigial UI.28 screen-motion witness"
        )
    return classification
