#!/usr/bin/env python3
"""Diagnose landed G11 snapshots against Settlement v2.5 truth.

Synthetic element ordinals and absolute draw orders are deliberately excluded.
Every remaining landed-only semantic draw must resolve, in order, to the
ambient-lifecycle, population, beta-overlay, or rect-animation correction.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from typing import Any, Iterable

if __package__:
    from .native_menu_overlay_v25 import (
        OverlayV25Error,
        overlay_draw_payload,
    )
    from .native_menu_settlement_v2 import (
        SettlementV2Error,
        _trace_payloads,
    )
else:
    from native_menu_overlay_v25 import (  # type: ignore[no-redef]
        OverlayV25Error,
        overlay_draw_payload,
    )
    from native_menu_settlement_v2 import (  # type: ignore[no-redef]
        SettlementV2Error,
        _trace_payloads,
    )


class LandedDiagnosisError(ValueError):
    """A landed mismatch does not satisfy an authorized correction path."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _semantic(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in {"id", "draw_order", "draw_order_semantics"}
    }


def _signature(element: dict[str, Any]) -> bytes:
    return canonical_bytes(_semantic(element))


def _elements(layout: dict[str, Any], label: str) -> list[dict[str, Any]]:
    values = layout.get("elements")
    if not isinstance(values, list) or not values:
        raise LandedDiagnosisError(f"{label} contains no element census")
    if not all(isinstance(value, dict) for value in values):
        raise LandedDiagnosisError(f"{label} contains a non-object element")
    ids = [value.get("id") for value in values]
    if not all(isinstance(value, str) and value for value in ids):
        raise LandedDiagnosisError(f"{label} contains an element without identity")
    if len(ids) != len(set(ids)):
        raise LandedDiagnosisError(f"{label} contains ambiguous duplicate element ids")
    return values


def _draw_order(element: dict[str, Any], label: str) -> float:
    value = element.get("draw_order")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise LandedDiagnosisError(
            f"{label} element '{element.get('id')}' has no finite draw order"
        )
    return float(value)


def _ordered(elements: Iterable[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    return sorted(
        elements,
        key=lambda element: (
            _draw_order(element, label),
            _signature(element),
            str(element.get("id")),
        ),
    )


def project_structural_core(
    landed_layout: dict[str, Any], settled_layout: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the matched landed core and every unmatched landed member."""
    landed = _ordered(_elements(landed_layout, "landed layout"), "landed layout")
    settled_core = _elements(settled_layout, "settled structural core")
    expected_sequence = [_signature(element) for element in settled_core]
    remaining = Counter(expected_sequence)
    projected: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    for element in landed:
        signature = _signature(element)
        if remaining[signature] > 0:
            remaining[signature] -= 1
            projected.append(element)
        else:
            residual.append(element)
    if any(remaining.values()):
        missing = next(signature for signature, count in remaining.items() if count)
        payload = json.loads(missing.decode("utf-8"))
        witness = payload.get("action_id") or payload.get("art_id") or payload.get("text")
        raise LandedDiagnosisError(
            "landed-vs-settled structural core mismatch: reproduced core member "
            f"'{witness}' is missing from the landed layout"
        )
    projected_sequence = [_signature(element) for element in projected]
    if projected_sequence != expected_sequence:
        raise LandedDiagnosisError(
            "landed-vs-settled structural core mismatch: core relative draw sequence differs"
        )
    return projected, residual


def _rect_inside(rect: Any, envelope: Any) -> bool:
    if (
        not isinstance(rect, list)
        or len(rect) != 4
        or not all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            for value in rect
        )
        or not isinstance(envelope, dict)
        or any(
            not isinstance(envelope.get(field), (int, float))
            for field in (
                "min_x",
                "max_x",
                "min_y",
                "max_y",
                "min_width",
                "max_width",
                "min_height",
                "max_height",
            )
        )
    ):
        return False
    x, y, right, bottom = (float(value) for value in rect)
    width = right - x
    height = bottom - y
    return (
        envelope.get("min_x") <= x <= envelope.get("max_x")
        and envelope.get("min_y") <= y <= envelope.get("max_y")
        and envelope.get("min_width") <= width <= envelope.get("max_width")
        and envelope.get("min_height") <= height <= envelope.get("max_height")
    )


def _ambient_match(
    landed: dict[str, Any], member: dict[str, Any], class_member: dict[str, Any]
) -> bool:
    anchor = class_member.get("anchor_payload")
    envelope = class_member.get("union_spatial_envelope")
    classification = class_member.get("classification")
    if not isinstance(anchor, dict) or not isinstance(envelope, dict):
        raise LandedDiagnosisError(
            "settled ambient member lacks an anchor payload or union envelope"
        )
    ignored = {"rect", "unclipped_rect"}
    if classification in {"visibility_cycling", "ephemeral"}:
        ignored.add("visible")
    landed_semantic = _semantic(landed)
    if {
        key: value for key, value in landed_semantic.items() if key not in ignored
    } != {
        key: value for key, value in anchor.items() if key not in ignored
    }:
        return False
    return _rect_inside(landed.get("rect"), envelope.get("rect")) and _rect_inside(
        landed.get("unclipped_rect"), envelope.get("unclipped_rect")
    )


def match_ambient_members(
    residual: list[dict[str, Any]], settled_layout: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split residuals into lifecycle corrections, animation, and unmatched."""
    members = settled_layout.get("ambient_members")
    if not isinstance(members, list):
        raise LandedDiagnosisError("settled layout has no ambient member map")
    if not all(isinstance(member, dict) for member in members):
        raise LandedDiagnosisError("settled ambient member map contains a non-object")
    lifecycle: list[dict[str, Any]] = []
    animation: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    matched_counts: Counter[str] = Counter()
    member_by_id = {str(member.get("id")): member for member in members}
    if len(member_by_id) != len(members):
        raise LandedDiagnosisError("settled ambient member ids are absent or ambiguous")
    for element in residual:
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for member in members:
            class_members = member.get("class_members")
            if not isinstance(class_members, list):
                raise LandedDiagnosisError(
                    f"settled ambient member '{member.get('id')}' has no class records"
                )
            for class_member in class_members:
                if isinstance(class_member, dict) and _ambient_match(
                    element, member, class_member
                ):
                    candidates.append((member, class_member))
        candidate_ids = {str(member.get("id")) for member, _ in candidates}
        if len(candidate_ids) > 1:
            raise LandedDiagnosisError(
                "landed ambient lookup is ambiguous for element "
                f"'{element.get('id')}': {sorted(candidate_ids)}"
            )
        if not candidates:
            unmatched.append(element)
            continue
        member_id = next(iter(candidate_ids))
        member = member_by_id[member_id]
        matched_counts[member_id] += 1
        concurrency = member.get("observed_concurrency_range")
        if (
            not isinstance(concurrency, list)
            or len(concurrency) != 2
            or matched_counts[member_id] > concurrency[1]
        ):
            raise LandedDiagnosisError(
                "landed ambient correction exceeds observed concurrency for "
                f"'{member_id}'"
            )
        classes = sorted(
            {
                str(class_member.get("classification"))
                for candidate, class_member in candidates
                if str(candidate.get("id")) == member_id
            }
        )
        disposition = {
            "element_id": element["id"],
            "art_id": element.get("art_id"),
            "member_id": member_id,
            "member_classes": classes,
            "landed_rect": copy.deepcopy(element.get("rect")),
            "landed_unclipped_rect": copy.deepcopy(element.get("unclipped_rect")),
            "union_spatial_envelope": copy.deepcopy(
                member.get("union_spatial_envelope")
            ),
        }
        if set(classes) == {"animated"}:
            animation.append(disposition)
        else:
            lifecycle.append(disposition)
    return lifecycle, animation, unmatched


def _semantic_counter(layout: dict[str, Any]) -> Counter[bytes]:
    return Counter(_signature(element) for element in _elements(layout, "trace payload"))


def _population_evidence(trace: dict[str, Any], label: str) -> dict[str, Any]:
    try:
        phases, settled, raw_phases = _trace_payloads(trace, label)
    except SettlementV2Error as error:
        raise LandedDiagnosisError(str(error)) from error
    return {
        "phases": phases,
        "settled": settled,
        "phase_counters": [_semantic_counter(payload) for payload in phases],
        "settled_counters": [_semantic_counter(payload) for payload in settled],
        "element_count_trace": [len(payload["elements"]) for payload in phases],
        "generation_trace": [payload.get("generation") for payload in phases],
        "phase_observations": [
            phase.get("observations") if isinstance(phase, dict) else None
            for phase in raw_phases
        ],
        "settled_sample_count": len(settled),
    }


def match_population_members(
    residual: list[dict[str, Any]],
    landed_generation: Any,
    settled_generation: Any,
    primary_trace: dict[str, Any],
    confirmation_trace: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    primary = _population_evidence(primary_trace, "primary")
    confirmation = _population_evidence(confirmation_trace, "confirmation")
    proof = {
        "primary": {
            key: copy.deepcopy(primary[key])
            for key in (
                "element_count_trace",
                "generation_trace",
                "phase_observations",
                "settled_sample_count",
            )
        },
        "confirmation": {
            key: copy.deepcopy(confirmation[key])
            for key in (
                "element_count_trace",
                "generation_trace",
                "phase_observations",
                "settled_sample_count",
            )
        },
    }
    if landed_generation == settled_generation:
        return [], residual, proof
    generation_witnessed = all(
        landed_generation in evidence["generation_trace"]
        for evidence in (primary, confirmation)
    )
    if not generation_witnessed:
        return [], residual, proof

    residual_by_signature: dict[bytes, list[dict[str, Any]]] = defaultdict(list)
    for element in residual:
        residual_by_signature[_signature(element)].append(element)
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for signature, elements in residual_by_signature.items():
        side_witnesses: list[list[int]] = []
        side_excesses: list[int] = []
        for evidence in (primary, confirmation):
            settled_max = max(
                counter[signature] for counter in evidence["settled_counters"]
            )
            excesses = [
                max(0, counter[signature] - settled_max)
                for counter in evidence["phase_counters"]
            ]
            side_excesses.append(max(excesses, default=0))
            side_witnesses.append(
                [index for index, excess in enumerate(excesses) if excess > 0]
            )
        qualifying = min(side_excesses)
        for ordinal, element in enumerate(elements, start=1):
            if ordinal <= qualifying:
                matched.append(
                    {
                        "element_id": element["id"],
                        "art_id": element.get("art_id"),
                        "semantic_payload": _semantic(element),
                        "primary_population_phase_indexes": side_witnesses[0],
                        "confirmation_population_phase_indexes": side_witnesses[1],
                        "absent_from_primary_settled_window": True,
                        "absent_from_confirmation_settled_window": True,
                    }
                )
            else:
                unmatched.append(element)
    proof["landed_generation"] = landed_generation
    proof["settled_generation"] = settled_generation
    proof["generation_difference_witnessed_in_both_traces"] = generation_witnessed
    return matched, unmatched, proof


def _overlay_counter(reference: dict[str, Any]) -> Counter[bytes]:
    entries = reference.get("overlay_semantic_draw_multiset")
    if not isinstance(entries, list) or not entries:
        raise LandedDiagnosisError("derived overlay reference has no semantic multiset")
    counter: Counter[bytes] = Counter()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
            raise LandedDiagnosisError("derived overlay reference contains a malformed draw")
        count = entry.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise LandedDiagnosisError("derived overlay reference contains an invalid count")
        counter[canonical_bytes(entry["payload"])] += count
    return counter


def semantic_overlay_corroboration(elements: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        counter = Counter(
            canonical_bytes(overlay_draw_payload(element)) for element in elements
        )
    except OverlayV25Error as error:
        raise LandedDiagnosisError(str(error)) from error
    entries = [
        {
            "count": counter[signature],
            "payload": json.loads(signature.decode("utf-8")),
        }
        for signature in sorted(counter)
    ]
    return {
        "overlay_semantic_draw_multiset": entries,
        "overlay_semantic_draw_count": sum(counter.values()),
    }


def match_overlay_members(
    residual: list[dict[str, Any]], reference: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not residual:
        return [], []
    required = _overlay_counter(reference)
    try:
        observed = Counter(
            canonical_bytes(overlay_draw_payload(element)) for element in residual
        )
    except OverlayV25Error:
        return [], residual
    if observed != required:
        return [], residual
    return [
        {
            "element_id": element["id"],
            "art_id": element.get("art_id"),
            "semantic_payload": overlay_draw_payload(element),
        }
        for element in residual
    ], []


def diagnosis_prereference_residual(
    landed_layout: dict[str, Any], settled_layout: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Residual used only to corroborate Create/pause overlay semantics."""
    _, residual = project_structural_core(landed_layout, settled_layout)
    lifecycle, animation, unmatched = match_ambient_members(residual, settled_layout)
    removed_ids = {
        disposition["element_id"] for disposition in (*lifecycle, *animation)
    }
    if len(removed_ids) != len(lifecycle) + len(animation):
        raise LandedDiagnosisError(
            "overlay corroboration ambient matching produced duplicate dispositions"
        )
    return unmatched, [*lifecycle, *animation]


def diagnose_landed_layout(
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    primary_trace: dict[str, Any],
    confirmation_trace: dict[str, Any],
    overlay_reference: dict[str, Any],
) -> dict[str, Any]:
    for field in ("screen_id", "screen_title"):
        if landed_layout.get(field) != settled_layout.get(field):
            raise LandedDiagnosisError(
                f"landed-vs-settled mismatch outside authorized classes: layout field '{field}' differs"
            )
    projected, residual = project_structural_core(landed_layout, settled_layout)
    lifecycle, animation, unmatched = match_ambient_members(residual, settled_layout)
    population, after_population, population_proof = match_population_members(
        unmatched,
        landed_layout.get("generation"),
        settled_layout.get("generation"),
        primary_trace,
        confirmation_trace,
    )
    animation_ids = {entry["element_id"] for entry in animation}
    animation_elements = [
        element for element in residual if element["id"] in animation_ids
    ]
    animation_signatures = Counter(_signature(element) for element in animation_elements)
    overlay_input: list[dict[str, Any]] = []
    held_animation: list[dict[str, Any]] = []
    for element in after_population:
        signature = _signature(element)
        if animation_signatures[signature] > 0:
            animation_signatures[signature] -= 1
            held_animation.append(element)
        else:
            overlay_input.append(element)
    overlay, residual_after_overlay = match_overlay_members(
        overlay_input, overlay_reference
    )
    if residual_after_overlay:
        element = residual_after_overlay[0]
        raise LandedDiagnosisError(
            "landed-vs-settled mismatch survives ambient, population, overlay, "
            f"and animation diagnosis: '{element.get('id')}' / "
            f"'{element.get('art_id') or element.get('action_id') or element.get('text')}'"
        )
    if len(held_animation) != len(animation):
        raise LandedDiagnosisError(
            "landed-vs-settled animation diagnosis did not account for every measured mover"
        )
    corrected = bool(lifecycle or population or overlay or animation)
    if not corrected and landed_layout.get("generation") != settled_layout.get("generation"):
        raise LandedDiagnosisError(
            "landed-vs-settled generation changed without an authorized differing member"
        )
    if overlay and not population_proof.get(
        "generation_difference_witnessed_in_both_traces"
    ):
        raise LandedDiagnosisError(
            "overlay correction generation difference lacks both population-trace witnesses"
        )
    return {
        "status": "corrected" if corrected else "strict_structural_bit_match",
        "old_generation": landed_layout.get("generation"),
        "old_element_count": len(_elements(landed_layout, "landed layout")),
        "new_generation": settled_layout.get("generation"),
        "new_structural_core_element_count": len(
            _elements(settled_layout, "settled structural core")
        ),
        "projected_core_element_count": len(projected),
        "ordinal_identity": "positional_bookkeeping_excluded",
        "absolute_draw_order": "excluded_core_relative_sequence_asserted",
        "ambient_lifecycle_dispositions": lifecycle,
        "population_phase_dispositions": population,
        "population_proof": population_proof,
        "overlay_dispositions": overlay,
        "overlay_reference_sha256": sha256_json(overlay_reference),
        "animated_geometry_dispositions": animation,
        "all_differing_members_enumerated": True,
    }
