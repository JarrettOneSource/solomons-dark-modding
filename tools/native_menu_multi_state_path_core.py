#!/usr/bin/env python3
"""Settlement v2.16 multi-state path-dependent structural cores.

This module is intentionally data-bound to the measured
``game-settings-gameplay`` accretion finding.  It removes only the two
authorized retained heading members while resolving the screen-wide motion
capability, then reconstructs and pins each observed structural core from the
unmodified settled samples.  It is not a general membership tolerance.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

if __package__:
    from .native_menu_ambient_lifecycle import (
        AmbientLifecycleError,
        _normalized_core,
        _semantic_payload,
        _sorted_elements,
        canonical_bytes,
        resolve_ambient_lifecycle,
        sha256_json,
    )
else:
    from native_menu_ambient_lifecycle import (  # type: ignore[no-redef]
        AmbientLifecycleError,
        _normalized_core,
        _semantic_payload,
        _sorted_elements,
        canonical_bytes,
        resolve_ambient_lifecycle,
        sha256_json,
    )


class MultiStatePathCoreError(ValueError):
    """The measured v2.16 Settings state contract does not reproduce."""


SETTINGS_LAYOUT_ID = "game-settings-gameplay"
SETTINGS_PARENT_SCREEN_ID = "settings"
SETTINGS_QUESTION_RECEIPT = {
    "evidence_path": (
        "raw-v9/motion-v215/final-rerun3/"
        "settings-path-dependent-core-question-manifest.json"
    ),
    "sha256": "4d1708d1cbb49a69eb63aeb049ee4b404772a789aa8a058b3c4486a8a1fd0c7c",
    "bytes": 4154,
}
SETTINGS_AUDIT_RECEIPT = {
    "evidence_path": (
        "raw-v9/motion-v215/final-rerun3/"
        "game-settings-cross-observation-stop-audit-v2.json"
    ),
    "sha256": "74f125e8faca4624446907747fdad07250c788290d60fde95a3b91ddd81829a7",
    "bytes": 117524,
}
DISABLED_RESOLVER_STOP = (
    "cross-instance structural core inequality: non-ambient full-presence "
    "member 'DARK CLOUD SETTINGS' differs or is missing in observation 2"
)

SETTINGS_STATE_ORDER = (
    "base",
    "performance_retained",
    "performance_dark_cloud_retained",
)
SETTINGS_STATE_RETAINED_HEADINGS = {
    "base": (),
    "performance_retained": ("TWEAK PERFORMANCE",),
    "performance_dark_cloud_retained": (
        "TWEAK PERFORMANCE",
        "DARK CLOUD SETTINGS",
    ),
}
SETTINGS_ENDPOINT_BINDINGS = {
    ("pause_to_game_settings", "after"): "base",
    ("settings_to_performance", "before"): "base",
    ("performance_to_settings", "after"): "performance_retained",
    (
        "settings_to_dark_cloud_settings",
        "before",
    ): "performance_retained",
    (
        "dark_cloud_settings_to_settings",
        "after",
    ): "performance_dark_cloud_retained",
    ("settings_to_hub", "before"): "performance_dark_cloud_retained",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_receipted_json(
    evidence_root: Path, receipt: dict[str, Any], label: str
) -> tuple[Path, dict[str, Any]]:
    root = evidence_root.resolve()
    relative = receipt.get("evidence_path")
    if not isinstance(relative, str) or not relative:
        raise MultiStatePathCoreError(
            f"multi-state path-dependent core contract: {label} has no path"
        )
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise MultiStatePathCoreError(
            f"multi-state path-dependent core contract: {label} is absent"
        )
    if path.stat().st_size != receipt.get("bytes") or _sha256(path) != receipt.get(
        "sha256"
    ):
        raise MultiStatePathCoreError(
            f"multi-state path-dependent core contract: {label} receipt changed"
        )
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise MultiStatePathCoreError(
            f"multi-state path-dependent core contract: {label} is not an object"
        )
    return path, value


def _receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    return {
        "evidence_path": path.resolve().relative_to(evidence_root.resolve()).as_posix(),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _state_label(edge_id: str, endpoint: str, role: str) -> str:
    side = "source" if endpoint == "before" else "destination"
    return f"edge:{edge_id}:{side}:{role}"


def _expected_state_labels() -> dict[str, set[str]]:
    labels = {state_id: set() for state_id in SETTINGS_STATE_ORDER}
    labels["base"].update(
        {
            f"standalone:{SETTINGS_LAYOUT_ID}:primary",
            f"standalone:{SETTINGS_LAYOUT_ID}:confirmation",
        }
    )
    for (edge_id, endpoint), state_id in SETTINGS_ENDPOINT_BINDINGS.items():
        labels[state_id].update(
            _state_label(edge_id, endpoint, role)
            for role in ("primary", "confirmation")
        )
    return labels


def _load_measurement_contract(evidence_root: Path) -> dict[str, Any]:
    question_path, question = _read_receipted_json(
        evidence_root, SETTINGS_QUESTION_RECEIPT, "v2.16 question manifest"
    )
    audit_path, audit = _read_receipted_json(
        evidence_root, SETTINGS_AUDIT_RECEIPT, "v2.16 cross-observation audit"
    )
    if (
        question.get("schema")
        != "solomon-dark-native-menu-settings-path-question-v1"
        or question.get("candidate_applied_to_landed_fixtures") is not False
        or audit.get("layout_id") != SETTINGS_LAYOUT_ID
        or audit.get("candidate_applied") is not False
    ):
        raise MultiStatePathCoreError(
            "multi-state path-dependent core contract: accepted STOP evidence changed scope"
        )
    audit_receipt = question.get("receipts", {}).get("audit")
    if audit_receipt != SETTINGS_AUDIT_RECEIPT:
        raise MultiStatePathCoreError(
            "multi-state path-dependent core contract: question and audit receipts disagree"
        )
    retained_payloads: dict[str, dict[str, Any]] = {}
    structural_states = audit.get("structural_states")
    if not isinstance(structural_states, list) or not structural_states:
        raise MultiStatePathCoreError(
            "multi-state path-dependent core contract: audit reached no structural states"
        )
    authorized_heading_texts = {
        heading
        for headings in SETTINGS_STATE_RETAINED_HEADINGS.values()
        for heading in headings
    }
    retained_payload_candidates: dict[str, dict[bytes, dict[str, Any]]] = {
        heading: {} for heading in authorized_heading_texts
    }
    for structural_state in structural_states:
        if not isinstance(structural_state, dict):
            continue
        difference = structural_state.get("difference_from_primary_standalone")
        if not isinstance(difference, dict):
            continue
        additions = difference.get("observation_only")
        if not isinstance(additions, list):
            continue
        for addition in additions:
            if not isinstance(addition, dict):
                continue
            text = addition.get("text")
            if text not in authorized_heading_texts:
                continue
            signature = canonical_bytes(addition)
            retained_payload_candidates[str(text)][signature] = copy.deepcopy(
                addition
            )
    for heading, candidates in retained_payload_candidates.items():
        if len(candidates) != 1:
            raise MultiStatePathCoreError(
                "multi-state path-dependent core contract: audit does not enumerate "
                f"one exact retained payload for '{heading}'"
            )
        retained_payloads[heading] = next(iter(candidates.values()))

    raw_states = question.get("path_states")
    if not isinstance(raw_states, list) or len(raw_states) != len(
        SETTINGS_STATE_ORDER
    ):
        raise MultiStatePathCoreError(
            "multi-state path-dependent core contract: measured Settings state census changed"
        )

    expected_labels = _expected_state_labels()
    states: dict[str, dict[str, Any]] = {}
    previous_headings: set[str] = set()
    previous_count: int | None = None
    for state_id, raw in zip(SETTINGS_STATE_ORDER, raw_states, strict=True):
        if not isinstance(raw, dict):
            raise MultiStatePathCoreError(
                "multi-state path-dependent core contract: measured state is not an object"
            )
        headings = set(raw.get("retained_heading_texts", []))
        expected_headings = set(SETTINGS_STATE_RETAINED_HEADINGS[state_id])
        labels = set(raw.get("labels", []))
        count = raw.get("element_count")
        if headings != expected_headings or labels != expected_labels[state_id]:
            raise MultiStatePathCoreError(
                f"multi-state path-dependent core contract: state '{state_id}' changed its measured labels or retention set"
            )
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise MultiStatePathCoreError(
                f"multi-state path-dependent core contract: state '{state_id}' has no measured census"
            )
        if previous_count is not None and (
            count != previous_count + 1
            or not previous_headings < headings
            or len(headings - previous_headings) != 1
        ):
            raise MultiStatePathCoreError(
                "multi-state path-dependent core contract: measured accretion order changed"
            )
        previous_count = count
        previous_headings = headings
        states[state_id] = {
            "state_id": state_id,
            "retained_heading_texts": list(
                SETTINGS_STATE_RETAINED_HEADINGS[state_id]
            ),
            "measured_element_count": count,
            "observation_labels": sorted(labels),
        }
    return {
        "states": states,
        "retained_payloads": retained_payloads,
        "question_receipt": _receipt(question_path, evidence_root),
        "audit_receipt": _receipt(audit_path, evidence_root),
    }


def _raw_semantic_payload(element: dict[str, Any]) -> dict[str, Any]:
    payload = _semantic_payload(element)
    payload.pop("draw_order_semantics", None)
    return payload


def _heading_elements(
    sample: dict[str, Any], retained_signatures: set[bytes]
) -> list[dict[str, Any]]:
    payload = sample.get("payload")
    if not isinstance(payload, dict):
        raise MultiStatePathCoreError(
            "multi-state path-dependent core contract: observation sample has no payload"
        )
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise MultiStatePathCoreError(
            "multi-state path-dependent core contract: observation sample has no members"
        )
    return [
        element
        for element in elements
        if isinstance(element, dict)
        and canonical_bytes(_raw_semantic_payload(element))
        in retained_signatures
    ]


def _project_observations_to_base(
    observations: list[dict[str, Any]],
    label_to_state: dict[str, str],
    measured_states: dict[str, dict[str, Any]],
    retained_payloads: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[bytes, dict[str, Any]]]]:
    retained_signature_by_text = {
        heading: canonical_bytes(payload)
        for heading, payload in retained_payloads.items()
    }
    retained_signatures = set(retained_signature_by_text.values())
    heading_payloads: dict[str, dict[bytes, dict[str, Any]]] = {
        heading: {} for heading in retained_payloads
    }
    projected: list[dict[str, Any]] = []
    for observation in observations:
        label = observation.get("label")
        kind = observation.get("kind", "settled_window")
        state_id = label_to_state.get(str(label))
        if kind == "settled_window" and state_id is None:
            raise MultiStatePathCoreError(
                "multi-state path-dependent core contract: unbound Settings endpoint or synthetic fourth state"
            )
        if kind == "extended_observation" and state_id is None:
            raw_samples = observation.get("samples")
            if not isinstance(raw_samples, list) or not raw_samples:
                raise MultiStatePathCoreError(
                    "multi-state path-dependent core contract: extended observation has no samples"
                )
            measured_heading_sets = {
                frozenset(
                    str(element.get("text"))
                    for element in _heading_elements(sample, retained_signatures)
                )
                for sample in raw_samples
            }
            matching_states = [
                candidate_state_id
                for candidate_state_id, state in measured_states.items()
                if measured_heading_sets
                == {frozenset(state["retained_heading_texts"])}
            ]
            if len(matching_states) != 1:
                raise MultiStatePathCoreError(
                    "multi-state path-dependent core contract: extended observation does not measure exactly one authorized state"
                )
            state_id = matching_states[0]
        expected_headings = (
            set(measured_states[state_id]["retained_heading_texts"])
            if state_id is not None
            else set()
        )
        expected_count = (
            measured_states[state_id]["measured_element_count"]
            if state_id is not None
            else None
        )
        projected_observation = copy.deepcopy(observation)
        projected_samples = projected_observation.get("samples")
        if not isinstance(projected_samples, list):
            raise MultiStatePathCoreError(
                "multi-state path-dependent core contract: observation has no samples"
            )
        for sample in projected_samples:
            payload = sample.get("payload") if isinstance(sample, dict) else None
            elements = payload.get("elements") if isinstance(payload, dict) else None
            if not isinstance(elements, list):
                raise MultiStatePathCoreError(
                    "multi-state path-dependent core contract: sampled layout has no members"
                )
            if expected_count is not None and len(elements) != expected_count:
                raise MultiStatePathCoreError(
                    f"multi-state path-dependent core contract: state '{state_id}' changed its measured element census"
                )
            retained = _heading_elements(sample, retained_signatures)
            retained_counter = Counter(
                element.get("text") for element in retained
            )
            if retained_counter != Counter(expected_headings):
                raise MultiStatePathCoreError(
                    "multi-state path-dependent core contract: state "
                    f"'{state_id or 'capability'}' observation '{label}' has an "
                    "extra or missing retained heading: "
                    f"expected={sorted(expected_headings)} "
                    f"observed={sorted(retained_counter.elements())}"
                )
            for element in retained:
                if (
                    element.get("kind") == "control"
                    or element.get("action_id")
                    or element.get("interactive") is True
                ):
                    raise MultiStatePathCoreError(
                        "multi-state path-dependent core contract: retained member became interactive"
                    )
                heading = str(element["text"])
                signature = canonical_bytes(_raw_semantic_payload(element))
                heading_payloads[heading][signature] = copy.deepcopy(element)
            payload["elements"] = [
                element for element in elements if element not in retained
            ]
        projected.append(projected_observation)
    for heading, payloads in heading_payloads.items():
        if len(payloads) != 1:
            raise MultiStatePathCoreError(
                "multi-state path-dependent core contract: retained member "
                f"'{heading}' changed a payload or geometry field"
            )
    return projected, heading_payloads


def _state_structural_sequence(
    observations: list[dict[str, Any]],
    expected_headings: set[str],
    measured_count: int,
    base_sequence: list[bytes],
    ambient_art_ids: set[str],
    retained_signature_by_text: dict[str, bytes],
) -> tuple[list[bytes], dict[bytes, dict[str, Any]], int]:
    reference: list[bytes] | None = None
    payload_by_signature: dict[bytes, dict[str, Any]] = {}
    residual_counts: set[int] = set()
    for observation in observations:
        for sample in observation["samples"]:
            payload = sample["payload"]
            elements = payload["elements"]
            if len(elements) != measured_count:
                raise MultiStatePathCoreError(
                    "multi-state path-dependent core contract: bound observation changed census"
                )
            remaining_base = Counter(base_sequence)
            sequence: list[bytes] = []
            projected_base: list[bytes] = []
            observed_headings: Counter[str] = Counter()
            residual_count = 0
            for element in _sorted_elements(payload):
                semantic = _raw_semantic_payload(element)
                signature = canonical_bytes(semantic)
                text = element.get("text")
                if remaining_base[signature] > 0:
                    remaining_base[signature] -= 1
                    projected_base.append(signature)
                    sequence.append(signature)
                    payload_by_signature[signature] = semantic
                elif (
                    text in expected_headings
                    and signature == retained_signature_by_text[str(text)]
                ):
                    observed_headings[str(text)] += 1
                    sequence.append(signature)
                    payload_by_signature[signature] = semantic
                else:
                    residual_count += 1
                    if (
                        element.get("kind") != "art"
                        or element.get("text")
                        or element.get("action_id")
                        or element.get("interactive") is True
                        or element.get("art_id") not in ambient_art_ids
                    ):
                        token = (
                            element.get("text")
                            or element.get("action_id")
                            or element.get("art_id")
                            or element.get("kind")
                        )
                        raise MultiStatePathCoreError(
                            "multi-state path-dependent core contract: extra retained "
                            f"member '{token}' is outside the enumerated set"
                        )
            if any(remaining_base.values()) or projected_base != base_sequence:
                raise MultiStatePathCoreError(
                    "multi-state path-dependent core contract: a non-retained member, geometry, or payload field differs between cores"
                )
            if observed_headings != Counter(expected_headings):
                raise MultiStatePathCoreError(
                    "multi-state path-dependent core contract: retained heading multiset changed"
                )
            if reference is None:
                reference = sequence
            elif sequence != reference:
                raise MultiStatePathCoreError(
                    "multi-state path-dependent core contract: bound observations do not reproduce one exact core"
                )
            residual_counts.add(residual_count)
    if reference is None or len(residual_counts) != 1:
        raise MultiStatePathCoreError(
            "multi-state path-dependent core contract: state has no exact reproduced samples"
        )
    return reference, payload_by_signature, residual_counts.pop()


def resolve_settings_path_dependent_cores(
    observations: list[dict[str, Any]],
    *,
    evidence_root: Path,
    asset_manifest: dict[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Resolve and validate the exact v2.16 Settings accretion states."""

    if not enabled:
        # This deliberate mutation seam must continue to reproduce the exact
        # pre-v2.16 fail-closed resolver finding.
        return resolve_ambient_lifecycle(
            observations, asset_manifest=asset_manifest
        )

    contract = _load_measurement_contract(evidence_root)
    measured_states = contract["states"]
    label_to_state = {
        label: state_id
        for state_id, state in measured_states.items()
        for label in state["observation_labels"]
    }
    observed_settled_labels = {
        str(observation.get("label"))
        for observation in observations
        if observation.get("kind", "settled_window") == "settled_window"
    }
    if observed_settled_labels != set(label_to_state):
        raise MultiStatePathCoreError(
            "multi-state path-dependent core contract: endpoint binding census changed or a fourth state appeared"
        )

    retained_payloads = contract["retained_payloads"]
    retained_signature_by_text = {
        heading: canonical_bytes(payload)
        for heading, payload in retained_payloads.items()
    }
    projected, _ = _project_observations_to_base(
        observations, label_to_state, measured_states, retained_payloads
    )
    try:
        base_resolution = resolve_ambient_lifecycle(
            projected, asset_manifest=asset_manifest
        )
    except AmbientLifecycleError as error:
        raise MultiStatePathCoreError(str(error)) from error

    base_sequence = [
        canonical_bytes(_raw_semantic_payload(element))
        for element in base_resolution["structural_core"]["elements"]
    ]
    ambient_art_ids = {
        str(member.get("art_id"))
        for member in base_resolution["ambient_members"]
        if member.get("art_id")
    }
    states: dict[str, dict[str, Any]] = {}
    prior_sequence = base_sequence
    accretion_order: list[dict[str, Any]] = []
    for state_id in SETTINGS_STATE_ORDER:
        state_contract = measured_states[state_id]
        state_observations = [
            observation
            for observation in observations
            if label_to_state.get(str(observation.get("label"))) == state_id
        ]
        identities = {
            (observation.get("instance"), observation.get("process_id"))
            for observation in state_observations
        }
        if len(identities) < 2:
            raise MultiStatePathCoreError(
                f"multi-state path-dependent core contract: state '{state_id}' lacks two fresh instances"
            )
        sequence, payloads, residual_count = _state_structural_sequence(
            state_observations,
            set(state_contract["retained_heading_texts"]),
            state_contract["measured_element_count"],
            base_sequence,
            ambient_art_ids,
            retained_signature_by_text,
        )
        elements, _ = _normalized_core(
            SETTINGS_PARENT_SCREEN_ID, sequence, payloads
        )
        core_layout = copy.deepcopy(base_resolution["structural_core"])
        core_layout["elements"] = elements
        core_hash = sha256_json(core_layout)
        state_resolution = copy.deepcopy(base_resolution)
        state_resolution["structural_core"] = core_layout
        state_resolution["structural_core_sha256"] = core_hash
        state_resolution["structural_core_element_count"] = len(elements)
        state_resolution["peak_element_count"] = state_contract[
            "measured_element_count"
        ]
        state_resolution["ambient_fraction"] = (
            base_resolution["ambient_semantic_member_count"]
            / state_contract["measured_element_count"]
        )
        added = Counter(sequence) - Counter(prior_sequence)
        if state_id != "base":
            if sum(added.values()) != 1:
                raise MultiStatePathCoreError(
                    "multi-state path-dependent core contract: measured accretion did not add exactly one member"
                )
            added_signature = next(iter(added))
            added_payload = payloads[added_signature]
            accretion_order.append(
                {
                    "step": len(accretion_order) + 1,
                    "state_id": state_id,
                    "retained_text": added_payload.get("text"),
                    "semantic_sha256": hashlib.sha256(added_signature).hexdigest(),
                }
            )
        prior_sequence = sequence
        states[state_id] = {
            **copy.deepcopy(state_contract),
            "structural_core_sha256": core_hash,
            "structural_core_element_count": len(elements),
            "ambient_member_count": residual_count,
            "resolution": state_resolution,
            "observation_receipts": [
                copy.deepcopy(observation.get("evidence"))
                for observation in state_observations
            ],
        }

    bindings = [
        {
            "binding": "standalone",
            "layout_id": SETTINGS_LAYOUT_ID,
            "state_id": "base",
        },
        *[
            {
                "binding": "navigation_endpoint",
                "edge_id": edge_id,
                "endpoint": endpoint,
                "state_id": state_id,
            }
            for (edge_id, endpoint), state_id in SETTINGS_ENDPOINT_BINDINGS.items()
        ],
    ]
    return {
        "settlement_spec": "2.16",
        "layout_id": SETTINGS_LAYOUT_ID,
        "parent_screen_id": SETTINGS_PARENT_SCREEN_ID,
        "selector": "deterministic_navigation_history_retained_heading_accretion",
        "retained_member_guardrail": "exact_text_membership_and_payload",
        "states": states,
        "state_order": list(SETTINGS_STATE_ORDER),
        "accretion_order": accretion_order,
        "bindings": bindings,
        "question_manifest": contract["question_receipt"],
        "cross_observation_audit": contract["audit_receipt"],
    }


def state_layout(result: dict[str, Any], state_id: str) -> dict[str, Any]:
    """Return one resolved layout while refusing an unknown state."""

    state = result.get("states", {}).get(state_id)
    if not isinstance(state, dict) or not isinstance(state.get("resolution"), dict):
        raise MultiStatePathCoreError(
            f"multi-state path-dependent core contract: unknown state '{state_id}'"
        )
    resolution = state["resolution"]
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
