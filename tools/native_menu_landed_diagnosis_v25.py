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


def _project_core_members(
    landed_layout: dict[str, Any], settled_layout: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    landed = _ordered(_elements(landed_layout, "landed layout"), "landed layout")
    settled_core = _elements(settled_layout, "settled structural core")
    remaining = Counter(_signature(element) for element in settled_core)
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
    return projected, residual


def project_structural_core(
    landed_layout: dict[str, Any], settled_layout: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the matched landed core and every unmatched landed member."""
    projected, residual = _project_core_members(landed_layout, settled_layout)
    settled_core = _elements(settled_layout, "settled structural core")
    expected_sequence = [_signature(element) for element in settled_core]
    projected_sequence = [_signature(element) for element in projected]
    if projected_sequence != expected_sequence:
        raise LandedDiagnosisError(
            "landed-vs-settled structural core mismatch: core relative draw sequence differs"
        )
    return projected, residual


def _lcs_indexes(
    left: list[bytes], right: list[bytes]
) -> tuple[set[int], set[int]]:
    lengths = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for left_index in range(len(left) - 1, -1, -1):
        for right_index in range(len(right) - 1, -1, -1):
            lengths[left_index][right_index] = (
                1 + lengths[left_index + 1][right_index + 1]
                if left[left_index] == right[right_index]
                else max(
                    lengths[left_index + 1][right_index],
                    lengths[left_index][right_index + 1],
                )
            )
    left_indexes: set[int] = set()
    right_indexes: set[int] = set()
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        if left[left_index] == right[right_index]:
            left_indexes.add(left_index)
            right_indexes.add(right_index)
            left_index += 1
            right_index += 1
        elif lengths[left_index + 1][right_index] >= lengths[left_index][right_index + 1]:
            left_index += 1
        else:
            right_index += 1
    return left_indexes, right_indexes


def _require_v29_order_contract(
    contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, int]:
    if contract.get("schema") != "solomon-dark-native-menu-beta-notice-order-v29":
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: generated contract schema is invalid"
        )
    if (
        contract.get("layout_id") != "beta-notice"
        or contract.get("screen_id") != "beta_notice"
    ):
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: contract names another layout"
        )
    members = contract.get("moved_members")
    core_count = contract.get("core_member_count")
    lcs_count = contract.get("longest_common_subsequence_count")
    if (
        not isinstance(members, list)
        or len(members) != 3
        or not all(isinstance(member, dict) for member in members)
        or isinstance(core_count, bool)
        or not isinstance(core_count, int)
        or isinstance(lcs_count, bool)
        or not isinstance(lcs_count, int)
        or core_count != lcs_count + len(members)
    ):
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: generated contract census is invalid"
        )
    required_member_fields = {
        "art_id",
        "rect",
        "semantic_sha256",
        "landed_relative_core_index",
        "settled_relative_core_index",
        "native_paint_order",
        "overlay_reference_member",
    }
    if any(required_member_fields - set(member) for member in members):
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: generated member identity is incomplete"
        )
    semantic_hashes = [member["semantic_sha256"] for member in members]
    if len(set(semantic_hashes)) != len(members) or not all(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
        for value in semantic_hashes
    ):
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: semantic identities are ambiguous"
        )
    return members, core_count, lcs_count


def _v29_beta_notice_order_projection(
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    overlay_reference: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """Project one core and apply only the generated beta-notice v2.9 rule."""
    if settled_layout.get("screen_id") != "beta_notice":
        projected, residual = project_structural_core(landed_layout, settled_layout)
        return projected, residual, None

    members, core_count, lcs_count = _require_v29_order_contract(contract)
    settled_core = _elements(settled_layout, "settled structural core")
    contract_hashes = {member["semantic_sha256"] for member in members}
    settled_hashes = [hashlib.sha256(_signature(element)).hexdigest() for element in settled_core]
    if len(settled_core) != core_count or any(
        settled_hashes.count(semantic_hash) != 1 for semantic_hash in contract_hashes
    ):
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: exact core set identity failed"
        )
    try:
        projected, residual = _project_core_members(landed_layout, settled_layout)
    except LandedDiagnosisError as error:
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: exact core set identity failed"
        ) from error
    if len(projected) != core_count:
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: exact core set identity failed"
        )

    projected_signatures = [_signature(element) for element in projected]
    settled_signatures = [_signature(element) for element in settled_core]
    if Counter(projected_signatures) != Counter(settled_signatures):
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: exact core set identity failed"
        )
    projected_hashes = [hashlib.sha256(value).hexdigest() for value in projected_signatures]
    landed_indexes = [projected_hashes.index(member["semantic_sha256"]) for member in members]
    settled_indexes = [settled_hashes.index(member["semantic_sha256"]) for member in members]
    expected_landed_indexes = [member["landed_relative_core_index"] for member in members]
    expected_settled_indexes = [member["settled_relative_core_index"] for member in members]
    final_indexes = list(range(core_count - len(members), core_count))
    if landed_indexes != expected_landed_indexes or settled_indexes != expected_settled_indexes:
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: bounded landed-to-settled positions differ"
        )
    if settled_indexes != final_indexes:
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: exempt trio is not the final structural core group"
        )

    overlay = _overlay_counter(overlay_reference)
    ordered_members: list[dict[str, Any]] = []
    for member, landed_index, settled_index in zip(
        members, landed_indexes, settled_indexes, strict=True
    ):
        landed_element = projected[landed_index]
        settled_element = settled_core[settled_index]
        if (
            member.get("overlay_reference_member") is not True
            or overlay[_signature(landed_element)] <= 0
            or landed_element.get("art_id") != member.get("art_id")
            or landed_element.get("rect") != member.get("rect")
            or _signature(landed_element) != _signature(settled_element)
        ):
            raise LandedDiagnosisError(
                "v2.9 beta-notice paint-order correction: exempt trio identity or overlay membership differs"
            )
        ordered_members.append(
            {
                "art_id": member["art_id"],
                "rect": copy.deepcopy(member["rect"]),
                "semantic_sha256": member["semantic_sha256"],
                "landed_relative_core_index": landed_index,
                "settled_relative_core_index": settled_index,
                "native_paint_order": member["native_paint_order"],
                "overlay_reference_member": True,
            }
        )

    remaining_projected = [
        signature
        for index, signature in enumerate(projected_signatures)
        if index not in set(landed_indexes)
    ]
    remaining_settled = [
        signature
        for index, signature in enumerate(settled_signatures)
        if index not in set(settled_indexes)
    ]
    if remaining_projected != remaining_settled:
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: a non-exempt core member moved"
        )
    kept_projected, kept_settled = _lcs_indexes(
        projected_signatures, settled_signatures
    )
    if len(kept_projected) != lcs_count or len(kept_settled) != lcs_count:
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: remaining-core LCS is not the generated witness"
        )
    moved_projected = {
        index for index in range(core_count) if index not in kept_projected
    }
    moved_settled = {
        index for index in range(core_count) if index not in kept_settled
    }
    if moved_projected != set(landed_indexes) or moved_settled != set(settled_indexes):
        raise LandedDiagnosisError(
            "v2.9 beta-notice paint-order correction: moved set is not exactly the exempt trio"
        )

    return projected, residual, {
        "schema": "solomon-dark-native-menu-core-order-correction-v29",
        "layout_id": "beta-notice",
        "reason": "landed_hook_enumeration_order_superseded_by_native_paint_order",
        "core_member_count": core_count,
        "longest_common_subsequence_count": lcs_count,
        "moved_members": ordered_members,
        "paint_truth": copy.deepcopy(contract.get("paint_truth")),
        "source_stop_audit": copy.deepcopy(contract.get("source_stop_audit")),
    }


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
    if classification in {"animated", "animated_family"}:
        # The landed value is one arbitrary old motion frame.  v2.3 pins the
        # newly measured anchor and union envelope, but does not require that
        # the old frame happened to fall inside the new observation interval.
        return True
    if _rect_inside(landed.get("rect"), envelope.get("rect")) and _rect_inside(
        landed.get("unclipped_rect"), envelope.get("unclipped_rect")
    ):
        return True
    family_envelope = member.get("union_spatial_envelope")
    return (
        isinstance(family_envelope, dict)
        and _rect_inside(landed.get("rect"), family_envelope.get("rect"))
        and _rect_inside(
            landed.get("unclipped_rect"),
            family_envelope.get("unclipped_rect"),
        )
    )


def _ambient_family_match(
    landed: dict[str, Any], member: dict[str, Any]
) -> bool:
    class_members = member.get("class_members")
    if not isinstance(class_members, list) or not class_members:
        raise LandedDiagnosisError(
            f"settled ambient member '{member.get('id')}' has no class records"
        )
    if not all(isinstance(value, dict) for value in class_members):
        raise LandedDiagnosisError(
            f"settled ambient member '{member.get('id')}' has a malformed class record"
        )
    classes = {
        str(class_member.get("classification"))
        for class_member in class_members
    }
    ignored = {"rect", "unclipped_rect"}
    if classes & {"visibility_cycling", "ephemeral"}:
        ignored.add("visible")
    landed_static = {
        key: value for key, value in _semantic(landed).items() if key not in ignored
    }
    anchor_statics: set[bytes] = set()
    for class_member in class_members:
        anchor = class_member.get("anchor_payload")
        if not isinstance(anchor, dict):
            raise LandedDiagnosisError(
                f"settled ambient member '{member.get('id')}' has no anchor payload"
            )
        anchor_statics.add(
            canonical_bytes(
                {
                    key: value
                    for key, value in anchor.items()
                    if key not in ignored
                }
            )
        )
    if len(anchor_statics) != 1 or canonical_bytes(landed_static) not in anchor_statics:
        return False
    if "animated" in classes or "animated_family" in classes:
        # v2.3: an old frozen frame need not lie inside a later finite motion
        # window.  The member-level class union still pins every non-varying
        # field, including visibility unless cycling was actually measured.
        return True
    family_envelope = member.get("union_spatial_envelope")
    return (
        isinstance(family_envelope, dict)
        and _rect_inside(landed.get("rect"), family_envelope.get("rect"))
        and _rect_inside(
            landed.get("unclipped_rect"),
            family_envelope.get("unclipped_rect"),
        )
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
            if not any(candidate is member for candidate, _ in candidates) and (
                _ambient_family_match(element, member)
            ):
                candidates.extend(
                    (member, class_member)
                    for class_member in class_members
                    if isinstance(class_member, dict)
                )
        candidate_ids = {str(member.get("id")) for member, _ in candidates}
        if len(candidate_ids) > 1:
            exact_candidates = [
                (member, class_member)
                for member, class_member in candidates
                if isinstance(class_member.get("anchor_payload"), dict)
                and _semantic(element) == class_member["anchor_payload"]
            ]
            exact_ids = {
                str(member.get("id")) for member, _ in exact_candidates
            }
            if len(exact_ids) == 1:
                candidates = exact_candidates
                candidate_ids = exact_ids
            else:
                enveloped_candidates = [
                    (member, class_member)
                    for member, class_member in candidates
                    if isinstance(class_member.get("union_spatial_envelope"), dict)
                    and _rect_inside(
                        element.get("rect"),
                        class_member["union_spatial_envelope"].get("rect"),
                    )
                    and _rect_inside(
                        element.get("unclipped_rect"),
                        class_member["union_spatial_envelope"].get(
                            "unclipped_rect"
                        ),
                    )
                ]
                enveloped_ids = {
                    str(member.get("id"))
                    for member, _ in enveloped_candidates
                }
                if len(enveloped_ids) == 1:
                    candidates = enveloped_candidates
                    candidate_ids = enveloped_ids
                else:
                    raise LandedDiagnosisError(
                        "landed ambient lookup is ambiguous after exact-anchor "
                        "and unique-envelope resolution for element "
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
        if set(classes) <= {"animated", "animated_family"}:
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
    order_override_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    for field in ("screen_id", "screen_title"):
        if landed_layout.get(field) != settled_layout.get(field):
            raise LandedDiagnosisError(
                f"landed-vs-settled mismatch outside authorized classes: layout field '{field}' differs"
            )
    if order_override_contract is None:
        projected, residual = project_structural_core(landed_layout, settled_layout)
        order_correction = None
    else:
        projected, residual, order_correction = _v29_beta_notice_order_projection(
            landed_layout,
            settled_layout,
            overlay_reference,
            order_override_contract,
        )
    lifecycle, animation, unmatched = match_ambient_members(residual, settled_layout)
    population, after_population, population_proof = match_population_members(
        unmatched,
        landed_layout.get("generation"),
        settled_layout.get("generation"),
        primary_trace,
        confirmation_trace,
    )
    overlay, residual_after_overlay = match_overlay_members(
        after_population, overlay_reference
    )
    if residual_after_overlay:
        element = residual_after_overlay[0]
        raise LandedDiagnosisError(
            "landed-vs-settled mismatch survives ambient, population, overlay, "
            f"and animation diagnosis: '{element.get('id')}' / "
            f"'{element.get('art_id') or element.get('action_id') or element.get('text')}'"
        )
    corrected = bool(
        lifecycle or population or overlay or animation or order_correction
    )
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
        "core_order_correction": order_correction,
        "all_differing_members_enumerated": True,
    }
