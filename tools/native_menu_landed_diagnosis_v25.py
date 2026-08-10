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
    from .native_menu_dark_cloud_browser_chrome_supersession import (
        DarkCloudBrowserChromeSupersessionError,
        consume_exact_landed_residual as consume_exact_browser_chrome_residual,
    )
    from .native_menu_dark_cloud_item_row_supersession import (
        DarkCloudItemRowSupersessionError,
        consume_exact_landed_residual,
        validate_control_layout,
    )
    from .native_menu_generation_v219 import (
        NativeMenuGenerationV219Error,
        authorize_cross_path_generation,
    )
    from .native_menu_census_era_v221 import (
        CensusEraV221Error,
        consume_choice_slot_rows,
        consume_class_a_residual,
        diagnose_field_corrections,
        game_over_endpoint_precondition_is_vacuous,
        normalized_generation_pair,
        require_class_f_witness,
        require_contract as require_census_era_contract,
        split_class_b_additions,
    )
    from .native_menu_final_disposition_v222 import (
        NAMED_ENDPOINT_VACUITY,
        FinalDispositionV222Error,
        authorize_named_endpoint_vacuity,
        authorize_relative_sequence,
    )
    from .native_menu_overlay_v25 import (
        OverlayV25Error,
        overlay_draw_payload,
    )
    from .native_menu_settlement_v2 import (
        SettlementV2Error,
        _trace_payloads,
    )
else:
    from native_menu_dark_cloud_browser_chrome_supersession import (  # type: ignore[no-redef]
        DarkCloudBrowserChromeSupersessionError,
        consume_exact_landed_residual as consume_exact_browser_chrome_residual,
    )
    from native_menu_dark_cloud_item_row_supersession import (  # type: ignore[no-redef]
        DarkCloudItemRowSupersessionError,
        consume_exact_landed_residual,
        validate_control_layout,
    )
    from native_menu_generation_v219 import (  # type: ignore[no-redef]
        NativeMenuGenerationV219Error,
        authorize_cross_path_generation,
    )
    from native_menu_census_era_v221 import (  # type: ignore[no-redef]
        CensusEraV221Error,
        consume_choice_slot_rows,
        consume_class_a_residual,
        diagnose_field_corrections,
        game_over_endpoint_precondition_is_vacuous,
        normalized_generation_pair,
        require_class_f_witness,
        require_contract as require_census_era_contract,
        split_class_b_additions,
    )
    from native_menu_final_disposition_v222 import (  # type: ignore[no-redef]
        NAMED_ENDPOINT_VACUITY,
        FinalDispositionV222Error,
        authorize_named_endpoint_vacuity,
        authorize_relative_sequence,
    )
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


V210_CONTROLS_TITLE_CONTRACT_SCHEMA = (
    "solomon-dark-native-menu-controls-title-v210"
)
V211_CONTROLS_CORE_CONTRACT_SCHEMA = (
    "solomon-dark-native-menu-controls-core-supersession-v211"
)
V211_STRUCTURAL_MISMATCH = (
    "landed-vs-settled structural core mismatch: exact v2.11 Controls "
    "supersession semantic multiset differs"
)
V211_WRONG_LAYOUT = (
    "landed-vs-settled structural core mismatch: v2.11 Controls "
    "supersession claimed by another layout"
)
V220_DARK_CLOUD_LOGIN_TITLE_CONTRACT_SCHEMA = (
    "solomon-dark-native-menu-dark-cloud-login-title-v220"
)
TITLE_MISMATCH = (
    "landed-vs-settled mismatch outside authorized classes: layout field "
    "'screen_title' differs"
)


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


def _project_structural_core_v222(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    final_disposition_contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
    *,
    sequence_supersession_enabled: bool,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any] | None,
]:
    if not final_disposition_contract:
        projected, residual = project_structural_core(
            landed_layout, settled_layout
        )
        return projected, residual, None
    projected, residual = _project_core_members(landed_layout, settled_layout)
    settled_core = _elements(settled_layout, "settled structural core")
    try:
        supersession = authorize_relative_sequence(
            layout_id,
            projected,
            settled_core,
            final_disposition_contract,
            landed_fixture_receipt,
            candidate_fixture_receipt,
            enabled=sequence_supersession_enabled,
        )
    except FinalDispositionV222Error as error:
        raise LandedDiagnosisError(str(error)) from error
    return projected, residual, supersession


def _allow_empty_bound_endpoints(
    layout_id: str,
    settled_layout: dict[str, Any],
    navigation: dict[str, Any],
    final_disposition_contract: dict[str, Any],
) -> bool:
    if layout_id not in NAMED_ENDPOINT_VACUITY:
        return False
    if not final_disposition_contract:
        if layout_id != "game-over":
            return False
        try:
            return game_over_endpoint_precondition_is_vacuous(
                layout_id, navigation
            )
        except CensusEraV221Error as error:
            raise LandedDiagnosisError(str(error)) from error
    try:
        authorize_named_endpoint_vacuity(
            layout_id,
            navigation,
            final_disposition_contract,
            str(settled_layout.get("structural_core_sha256", "")),
        )
    except FinalDispositionV222Error as error:
        raise LandedDiagnosisError(str(error)) from error
    return True


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
    if not residual:
        return [], [], {
            "population_trace_evaluation": "not_required_for_zero_residual",
            "settled_residual_member_count": 0,
        }
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


def _v211_semantic_counter(
    layout: dict[str, Any], label: str
) -> Counter[str]:
    return Counter(
        hashlib.sha256(_signature(element)).hexdigest()
        for element in _elements(layout, label)
    )


def _v211_counter_entries(
    counter: Counter[str], label: str
) -> list[dict[str, Any]]:
    if any(
        not isinstance(key, str)
        or len(key) != 64
        or any(character not in "0123456789abcdef" for character in key)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count <= 0
        for key, count in counter.items()
    ):
        raise LandedDiagnosisError(
            f"v2.11 Controls structural supersession: {label} is malformed"
        )
    return [
        {"semantic_sha256": key, "count": counter[key]}
        for key in sorted(counter)
    ]


def _v211_counter_from_entries(
    values: Any, label: str
) -> Counter[str]:
    if not isinstance(values, list) or not values:
        raise LandedDiagnosisError(
            f"v2.11 Controls structural supersession: {label} is absent"
        )
    result: Counter[str] = Counter()
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "semantic_sha256",
            "count",
        }:
            raise LandedDiagnosisError(
                f"v2.11 Controls structural supersession: {label} gained "
                "an unreviewed field"
            )
        key = value.get("semantic_sha256")
        count = value.get("count")
        candidate = Counter({key: count}) if isinstance(key, str) else Counter()
        if not candidate or _v211_counter_entries(candidate, label) != [value]:
            raise LandedDiagnosisError(
                f"v2.11 Controls structural supersession: {label} is malformed"
            )
        result[key] += count
    if _v211_counter_entries(result, label) != values:
        raise LandedDiagnosisError(
            f"v2.11 Controls structural supersession: {label} is not canonical"
        )
    return result


def _v211_counter_digest(counter: Counter[str]) -> str:
    return sha256_json(_v211_counter_entries(counter, "semantic multiset"))


def _require_v211_controls_core_contract(
    contract: dict[str, Any],
) -> tuple[Counter[str], Counter[str]]:
    expected_top_level = {
        "schema",
        "settlement_spec",
        "layout_id",
        "screen_id",
        "superseded_landed_fixture",
        "superseding_candidate_fixture",
        "source_audits",
        "paired_settlement",
        "navigation_endpoints",
        "justification",
        "forbidden",
        "derivation",
    }
    if set(contract) != expected_top_level:
        raise LandedDiagnosisError(
            "v2.11 Controls structural supersession: generated contract "
            "gained an unreviewed scope"
        )
    if (
        contract.get("schema") != V211_CONTROLS_CORE_CONTRACT_SCHEMA
        or contract.get("settlement_spec") != "2.11"
        or contract.get("layout_id") != "controls"
        or contract.get("screen_id") != "controls"
        or contract.get("forbidden")
        != [
            "general_settled_only_member_tolerance",
            "count_or_class_based_acceptance",
            "another_layout",
            "another_candidate_content",
        ]
    ):
        raise LandedDiagnosisError(
            "v2.11 Controls structural supersession: generated contract "
            "changed its exact Controls-only scope"
        )

    landed = contract.get("superseded_landed_fixture")
    settled = contract.get("superseding_candidate_fixture")
    if not isinstance(landed, dict) or set(landed) != {
        "path",
        "sha256",
        "bytes",
        "generation",
        "semantic_member_count",
        "semantic_multiset_sha256",
        "semantic_multiset",
    }:
        raise LandedDiagnosisError(
            "v2.11 Controls structural supersession: superseded fixture "
            "receipt or multiset is not exact"
        )
    if not isinstance(settled, dict) or set(settled) != {
        "path",
        "sha256",
        "bytes",
        "generation",
        "semantic_member_count",
        "semantic_multiset_sha256",
        "semantic_multiset",
        "structural_core_sha256",
    }:
        raise LandedDiagnosisError(
            "v2.11 Controls structural supersession: superseding fixture "
            "receipt or multiset is not exact"
        )
    if landed.get("path") != (
        "webgame-contracts/baseline-snapshots/menu-layouts/controls.json"
    ) or settled.get("path") != (
        "candidates/candidate-v29/menu-layouts/controls.json"
    ):
        raise LandedDiagnosisError(
            "v2.11 Controls structural supersession: fixture receipts name "
            "unreviewed paths"
        )
    landed_counter = _v211_counter_from_entries(
        landed.get("semantic_multiset"), "superseded semantic multiset"
    )
    settled_counter = _v211_counter_from_entries(
        settled.get("semantic_multiset"), "superseding semantic multiset"
    )
    for value, counter, label in (
        (landed, landed_counter, "superseded fixture"),
        (settled, settled_counter, "superseding fixture"),
    ):
        if (
            value.get("semantic_member_count") != sum(counter.values())
            or value.get("semantic_multiset_sha256")
            != _v211_counter_digest(counter)
            or not isinstance(value.get("sha256"), str)
            or len(value["sha256"]) != 64
            or isinstance(value.get("bytes"), bool)
            or not isinstance(value.get("bytes"), int)
            or value["bytes"] <= 0
        ):
            raise LandedDiagnosisError(
                f"v2.11 Controls structural supersession: {label} exact "
                "receipt does not close"
            )

    if contract.get("source_audits") != {
        "title": {
            "path": "raw-v9/diagnostics/controls-screen-title-stop-audit.json",
            "sha256": (
                "0377809414de5a1e5d0b8af01baaf1ee8221c5e586e81d7dfda95f18d1da703f"
            ),
            "bytes": 5456,
        },
        "structural_core": {
            "path": "raw-v9/diagnostics/controls-post-v210-structural-stop-audit.json",
            "sha256": (
                "22fc8f3061a0f0577bf805ab1ddf750416744bc0097405187321b9feeae148f1"
            ),
            "bytes": 63660,
        },
    }:
        raise LandedDiagnosisError(
            "v2.11 Controls structural supersession: accepted STOP audit "
            "receipts changed"
        )

    common = landed_counter & settled_counter
    landed_only = landed_counter - settled_counter
    settled_only = settled_counter - landed_counter
    justification = contract.get("justification")
    if not isinstance(justification, dict) or set(justification) != {
        "common_semantic_member_count",
        "landed_only_semantic_member_count",
        "landed_only_session_bleed",
        "landed_only_stale_art",
        "landed_text_member_count",
        "settled_only_semantic_member_count",
        "settled_only_semantic_multiset",
        "multiset_arithmetic_closed",
    }:
        raise LandedDiagnosisError(
            "v2.11 Controls structural supersession: justification gained "
            "an unreviewed class"
        )
    bleed = _v211_counter_from_entries(
        justification.get("landed_only_session_bleed"),
        "session-bleed semantic multiset",
    )
    stale = _v211_counter_from_entries(
        justification.get("landed_only_stale_art"),
        "stale-art semantic multiset",
    )
    if (
        justification.get("common_semantic_member_count")
        != sum(common.values())
        or justification.get("landed_only_semantic_member_count")
        != sum(landed_only.values())
        or bleed + stale != landed_only
        or justification.get("landed_text_member_count") != 0
        or justification.get("settled_only_semantic_member_count")
        != sum(settled_only.values())
        or _v211_counter_from_entries(
            justification.get("settled_only_semantic_multiset"),
            "settled-only semantic multiset",
        )
        != settled_only
        or justification.get("multiset_arithmetic_closed") is not True
    ):
        raise LandedDiagnosisError(
            "v2.11 Controls structural supersession: accepted structural "
            "audit arithmetic no longer closes"
        )
    return landed_counter, settled_counter


def _v211_receipt_matches(recorded: dict[str, Any], actual: Any) -> bool:
    return isinstance(actual, dict) and {
        "sha256": actual.get("sha256"),
        "bytes": actual.get("bytes"),
    } == {
        "sha256": recorded.get("sha256"),
        "bytes": recorded.get("bytes"),
    }


def _diagnose_structural_core_v211(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not contract:
        return None
    landed_counter, settled_counter = _require_v211_controls_core_contract(contract)
    recorded_landed = contract["superseded_landed_fixture"]
    recorded_candidate = contract["superseding_candidate_fixture"]
    if not _v211_receipt_matches(recorded_landed, landed_fixture_receipt):
        return None
    if (
        layout_id != contract["layout_id"]
        or landed_layout.get("screen_id") != contract["screen_id"]
        or settled_layout.get("screen_id") != contract["screen_id"]
    ):
        raise LandedDiagnosisError(V211_WRONG_LAYOUT)
    if (
        _v211_semantic_counter(landed_layout, "v2.11 landed Controls")
        != landed_counter
        or _v211_semantic_counter(settled_layout, "v2.11 settled Controls")
        != settled_counter
        or settled_layout.get("structural_core_sha256")
        != recorded_candidate.get("structural_core_sha256")
    ):
        raise LandedDiagnosisError(V211_STRUCTURAL_MISMATCH)
    source_candidate_receipt_reproduced = _v211_receipt_matches(
        recorded_candidate, candidate_fixture_receipt
    )
    return {
        "schema": "solomon-dark-native-menu-structural-core-supersession-v211",
        "layout_id": layout_id,
        "superseded_semantic_multiset_sha256": recorded_landed[
            "semantic_multiset_sha256"
        ],
        "superseding_semantic_multiset_sha256": recorded_candidate[
            "semantic_multiset_sha256"
        ],
        "reason": "landed_controls_capture_is_session_bleed_plus_stale_art_without_text",
        "source_audits": copy.deepcopy(contract["source_audits"]),
        "source_candidate_receipt": {
            "sha256": recorded_candidate["sha256"],
            "bytes": recorded_candidate["bytes"],
        },
        "qualified_candidate_receipt": copy.deepcopy(candidate_fixture_receipt),
        "qualified_reemission": not source_candidate_receipt_reproduced,
        "reemission_rule": (
            "later profile-state provenance may re-emit only the exact pinned "
            "semantic multiset and structural-core hash"
        ),
        "general_tolerance": False,
    }


def _require_v210_controls_title_contract(
    contract: dict[str, Any],
) -> dict[str, Any]:
    expected = {
        "schema": V210_CONTROLS_TITLE_CONTRACT_SCHEMA,
        "settlement_spec": "2.10",
        "layout_id": "controls",
        "screen_id": "controls",
        "field": "screen_title",
        "landed_value": "",
        "settled_value": "Wizard Controls",
    }
    if set(contract) != {*expected, "source_stop_audit", "derivation"}:
        raise LandedDiagnosisError(
            "v2.10 Controls screen-title correction: generated contract "
            "gained an unreviewed scope"
        )
    for field, value in expected.items():
        if contract.get(field) != value:
            raise LandedDiagnosisError(
                "v2.10 Controls screen-title correction: generated contract "
                f"changed its exact {field!r} scope"
            )
    source_stop_audit = contract.get("source_stop_audit")
    if not isinstance(source_stop_audit, dict):
        raise LandedDiagnosisError(
            "v2.10 Controls screen-title correction: source STOP audit is absent"
        )
    if source_stop_audit != {
        "evidence_filename": "controls-screen-title-stop-audit.json",
        "sha256": (
            "0377809414de5a1e5d0b8af01baaf1ee8221c5e586e81d7dfda95f18d1da703f"
        ),
        "bytes": 5456,
    }:
        raise LandedDiagnosisError(
            "v2.10 Controls screen-title correction: source STOP audit receipt "
            "does not match the accepted finding"
        )
    return source_stop_audit


def _require_v220_dark_cloud_login_title_contract(
    contract: dict[str, Any],
) -> None:
    expected = {
        "schema": V220_DARK_CLOUD_LOGIN_TITLE_CONTRACT_SCHEMA,
        "settlement_spec": "2.20",
        "layout_id": "dark-cloud-login-settings",
        "screen_id": "dark_cloud_login_settings",
        "field": "screen_title",
        "landed_value": "",
        "settled_value": "Dark Cloud Browser",
    }
    required_fields = {
        *expected,
        "landed_fixture",
        "baseline_snapshot",
        "superseding_candidate",
        "source_stop_audit",
        "source_promoter_stop",
        "source_provenance",
        "profile_state_identity_sha256",
        "paired_settlement",
        "bound_endpoints",
        "authorization",
        "forbidden",
        "derivation",
    }
    if set(contract) != required_fields or any(
        contract.get(field) != value for field, value in expected.items()
    ):
        raise LandedDiagnosisError(TITLE_MISMATCH)
    if (
        not isinstance(contract.get("landed_fixture"), dict)
        or not isinstance(contract.get("baseline_snapshot"), dict)
        or not isinstance(contract.get("superseding_candidate"), dict)
        or not isinstance(contract.get("source_stop_audit"), dict)
        or not isinstance(contract.get("source_promoter_stop"), dict)
        or not isinstance(contract.get("source_provenance"), dict)
        or not isinstance(contract.get("paired_settlement"), dict)
        or not isinstance(contract.get("bound_endpoints"), list)
        or len(contract["bound_endpoints"]) != 2
        or contract.get("forbidden")
        != [
            "title tolerance",
            "another layout",
            "another field",
            "another settled title value",
            "candidate rewriting",
        ]
    ):
        raise LandedDiagnosisError(TITLE_MISMATCH)


def _v220_receipt_matches(
    recorded: dict[str, Any], observed: dict[str, Any] | None
) -> bool:
    return isinstance(observed, dict) and {
        field: recorded.get(field) for field in ("sha256", "bytes")
    } == {field: observed.get(field) for field in ("sha256", "bytes")}


def diagnose_dark_cloud_login_title_v220(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if landed_layout.get("screen_title") == settled_layout.get("screen_title"):
        return None
    if not contract:
        raise LandedDiagnosisError(TITLE_MISMATCH)
    _require_v220_dark_cloud_login_title_contract(contract)
    if (
        layout_id != contract["layout_id"]
        or landed_layout.get("screen_id") != contract["screen_id"]
        or settled_layout.get("screen_id") != contract["screen_id"]
        or landed_layout.get("screen_title") != contract["landed_value"]
        or settled_layout.get("screen_title") != contract["settled_value"]
        or not _v220_receipt_matches(
            contract["landed_fixture"], landed_fixture_receipt
        )
        or not _v220_receipt_matches(
            contract["superseding_candidate"], candidate_fixture_receipt
        )
    ):
        raise LandedDiagnosisError(TITLE_MISMATCH)
    return {
        "schema": "solomon-dark-native-menu-screen-title-correction-v220",
        "settlement_spec": "2.20",
        "layout_id": layout_id,
        "field": "screen_title",
        "old_value": contract["landed_value"],
        "new_value": contract["settled_value"],
        "reason": "landed_dark_cloud_login_capture_omitted_live_title",
        "source_stop_audit": copy.deepcopy(contract["source_stop_audit"]),
        "bound_endpoints": copy.deepcopy(contract["bound_endpoints"]),
        "general_tolerance": False,
    }


def _diagnose_layout_identity_v210(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    controls_title_contract: dict[str, Any],
    dark_cloud_login_title_contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if landed_layout.get("screen_id") != settled_layout.get("screen_id"):
        raise LandedDiagnosisError(
            "landed-vs-settled mismatch outside authorized classes: layout "
            "field 'screen_id' differs"
        )
    landed_title = landed_layout.get("screen_title")
    settled_title = settled_layout.get("screen_title")
    if landed_title == settled_title:
        return None

    if layout_id == "dark-cloud-login-settings":
        return diagnose_dark_cloud_login_title_v220(
            layout_id,
            landed_layout,
            settled_layout,
            dark_cloud_login_title_contract,
            landed_fixture_receipt,
            candidate_fixture_receipt,
        )

    if not controls_title_contract:
        raise LandedDiagnosisError(TITLE_MISMATCH)
    source_stop_audit = _require_v210_controls_title_contract(
        controls_title_contract
    )
    if (
        layout_id != controls_title_contract["layout_id"]
        or landed_layout.get("screen_id") != controls_title_contract["screen_id"]
        or landed_title != controls_title_contract["landed_value"]
        or settled_title != controls_title_contract["settled_value"]
    ):
        raise LandedDiagnosisError(TITLE_MISMATCH)
    return {
        "schema": "solomon-dark-native-menu-screen-title-correction-v210",
        "layout_id": layout_id,
        "field": "screen_title",
        "old_value": landed_title,
        "new_value": settled_title,
        "reason": "landed_stale_controls_capture_omitted_live_title",
        "source_stop_audit": copy.deepcopy(source_stop_audit),
    }


def _difference_member(
    difference_type: str,
    element: dict[str, Any],
) -> dict[str, Any]:
    semantic = _semantic(element)
    return {
        "difference_type": difference_type,
        "element_id": element.get("id"),
        "witness": (
            element.get("action_id")
            or element.get("art_id")
            or element.get("text")
        ),
        "semantic_sha256": hashlib.sha256(canonical_bytes(semantic)).hexdigest(),
        "semantic_payload": semantic,
    }


def _sequence_tokens(
    sequence: list[bytes],
) -> list[tuple[bytes, int]]:
    occurrences: Counter[bytes] = Counter()
    tokens: list[tuple[bytes, int]] = []
    for signature in sequence:
        occurrences[signature] += 1
        tokens.append((signature, occurrences[signature]))
    return tokens


def _relative_sequence_difference(
    projected: list[dict[str, Any]],
    settled: list[dict[str, Any]],
) -> dict[str, Any]:
    landed_sequence = [_signature(element) for element in projected]
    settled_sequence = [_signature(element) for element in settled]
    landed_tokens = _sequence_tokens(landed_sequence)
    settled_tokens = _sequence_tokens(settled_sequence)
    landed_positions = {token: index for index, token in enumerate(landed_tokens)}
    settled_positions = {token: index for index, token in enumerate(settled_tokens)}
    moved: list[dict[str, Any]] = []
    for token in sorted(
        set(landed_positions) & set(settled_positions),
        key=lambda value: (value[0], value[1]),
    ):
        landed_index = landed_positions[token]
        settled_index = settled_positions[token]
        if landed_index == settled_index:
            continue
        moved.append(
            {
                "semantic_sha256": hashlib.sha256(token[0]).hexdigest(),
                "occurrence": token[1],
                "landed_index": landed_index,
                "settled_index": settled_index,
            }
        )
    return {
        "difference_type": "layout_field",
        "field": "relative_draw_sequence",
        "landed_sha256": sha256_json(
            [json.loads(signature.decode("utf-8")) for signature in landed_sequence]
        ),
        "settled_sha256": sha256_json(
            [json.loads(signature.decode("utf-8")) for signature in settled_sequence]
        ),
        "moved_members": moved,
    }


def _enumerate_unclassified_members(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    primary_trace: dict[str, Any],
    confirmation_trace: dict[str, Any],
    overlay_reference: dict[str, Any],
    *,
    controls_core_contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
    item_row_supersession_contract: dict[str, Any],
    browser_chrome_supersession_contract: dict[str, Any],
    census_era_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    try:
        structural_supersession = _diagnose_structural_core_v211(
            layout_id,
            landed_layout,
            settled_layout,
            controls_core_contract,
            landed_fixture_receipt,
            candidate_fixture_receipt,
        )
    except LandedDiagnosisError as error:
        structural_supersession = None
        differences.append(
            {
                "difference_type": "authorization_contract_failure",
                "field": "structural_core",
                "message": str(error),
            }
        )
    if structural_supersession is not None:
        return differences

    landed = _ordered(_elements(landed_layout, "landed layout"), "landed layout")
    settled = _elements(settled_layout, "settled structural core")
    try:
        _, settled = split_class_b_additions(
            layout_id,
            settled,
            census_era_contract,
            landed_fixture_receipt,
            candidate_fixture_receipt,
        )
    except CensusEraV221Error as error:
        differences.append(
            {
                "difference_type": "authorization_contract_failure",
                "field": "census_era_class_b",
                "message": str(error),
            }
        )
    remaining = Counter(_signature(element) for element in settled)
    projected: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    for element in landed:
        signature = _signature(element)
        if remaining[signature] > 0:
            remaining[signature] -= 1
            projected.append(element)
        else:
            residual.append(element)

    missing = remaining.copy()
    for element in settled:
        signature = _signature(element)
        if missing[signature] <= 0:
            continue
        differences.append(_difference_member("settled_only_member", element))
        missing[signature] -= 1

    if not any(remaining.values()) and [
        _signature(element) for element in projected
    ] != [_signature(element) for element in settled]:
        differences.append(_relative_sequence_difference(projected, settled))

    try:
        _, residual = consume_choice_slot_rows(
            layout_id, residual, census_era_contract
        )
        _, residual = consume_class_a_residual(
            layout_id,
            residual,
            census_era_contract,
            landed_fixture_receipt,
            candidate_fixture_receipt,
        )
    except CensusEraV221Error as error:
        differences.append(
            {
                "difference_type": "authorization_contract_failure",
                "field": "census_era_class_a",
                "message": str(error),
            }
        )
    lifecycle, animation, unmatched = match_ambient_members(residual, settled_layout)
    del lifecycle, animation
    population, after_population, _ = match_population_members(
        unmatched,
        landed_layout.get("generation"),
        settled_layout.get("generation"),
        primary_trace,
        confirmation_trace,
    )
    del population
    if item_row_supersession_contract:
        try:
            _, after_population = consume_exact_landed_residual(
                layout_id,
                landed_layout,
                settled_layout,
                after_population,
                item_row_supersession_contract,
                landed_fixture_receipt,
                candidate_fixture_receipt,
            )
        except DarkCloudItemRowSupersessionError as error:
            differences.append(
                {
                    "difference_type": "authorization_contract_failure",
                    "field": "dark_cloud_item_row_supersession",
                    "message": str(error),
                }
            )
    if browser_chrome_supersession_contract:
        try:
            _, after_population = consume_exact_browser_chrome_residual(
                layout_id,
                landed_layout,
                settled_layout,
                after_population,
                browser_chrome_supersession_contract,
                landed_fixture_receipt,
                candidate_fixture_receipt,
            )
        except DarkCloudBrowserChromeSupersessionError as error:
            differences.append(
                {
                    "difference_type": "authorization_contract_failure",
                    "field": "dark_cloud_browser_chrome_supersession",
                    "message": str(error),
                }
            )
    _, residual_after_overlay = match_overlay_members(
        after_population, overlay_reference
    )
    differences.extend(
        _difference_member("landed_only_member", element)
        for element in residual_after_overlay
    )
    return differences


def enumerate_unclassified_landed_differences(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    primary_trace: dict[str, Any],
    confirmation_trace: dict[str, Any],
    overlay_reference: dict[str, Any],
    controls_title_contract: dict[str, Any] | None = None,
    dark_cloud_login_title_contract: dict[str, Any] | None = None,
    controls_core_contract: dict[str, Any] | None = None,
    landed_fixture_receipt: dict[str, Any] | None = None,
    candidate_fixture_receipt: dict[str, Any] | None = None,
    path_local_generation_contract: dict[str, Any] | None = None,
    item_row_supersession_contract: dict[str, Any] | None = None,
    browser_chrome_supersession_contract: dict[str, Any] | None = None,
    census_era_contract: dict[str, Any] | None = None,
    final_disposition_contract: dict[str, Any] | None = None,
    sequence_supersession_enabled: bool = True,
    generation_navigation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Enumerate every unauthorized landed/candidate difference without writes."""
    controls_title_contract = controls_title_contract or {}
    dark_cloud_login_title_contract = dark_cloud_login_title_contract or {}
    controls_core_contract = controls_core_contract or {}
    item_row_supersession_contract = item_row_supersession_contract or {}
    browser_chrome_supersession_contract = (
        browser_chrome_supersession_contract or {}
    )
    census_era_contract = census_era_contract or {}
    final_disposition_contract = final_disposition_contract or {}
    census_field_keys: set[tuple[str, str]] = set()
    if census_era_contract:
        try:
            census_field_keys = set(
                require_census_era_contract(census_era_contract)[
                    "field_corrections"
                ]
            )
        except CensusEraV221Error:
            census_field_keys = set()
    normalized_landed = copy.deepcopy(landed_layout)
    normalized_settled = copy.deepcopy(settled_layout)
    differences: list[dict[str, Any]] = []

    title_authorized = False
    if landed_layout.get("screen_title") != settled_layout.get("screen_title"):
        try:
            title_authorized = _diagnose_layout_identity_v210(
                layout_id,
                landed_layout,
                settled_layout,
                controls_title_contract,
                dark_cloud_login_title_contract,
                landed_fixture_receipt,
                candidate_fixture_receipt,
            ) is not None
        except LandedDiagnosisError:
            title_authorized = False

    for field in ("screen_id", "screen_title"):
        landed_value = landed_layout.get(field)
        settled_value = settled_layout.get(field)
        if landed_value == settled_value:
            continue
        census_authorized = (layout_id, field) in census_field_keys
        if (field != "screen_title" or not title_authorized) and not census_authorized:
            differences.append(
                {
                    "difference_type": "layout_field",
                    "field": field,
                    "landed_value": copy.deepcopy(landed_value),
                    "settled_value": copy.deepcopy(settled_value),
                }
            )
        normalized_landed[field] = copy.deepcopy(settled_value)

    try:
        diagnose_landed_layout(
            layout_id,
            normalized_landed,
            normalized_settled,
            primary_trace,
            confirmation_trace,
            overlay_reference,
            controls_title_contract={},
            dark_cloud_login_title_contract=(
                dark_cloud_login_title_contract
            ),
            controls_core_contract=controls_core_contract,
            landed_fixture_receipt=landed_fixture_receipt,
            candidate_fixture_receipt=candidate_fixture_receipt,
            path_local_generation_contract=path_local_generation_contract,
            item_row_supersession_contract=item_row_supersession_contract,
            browser_chrome_supersession_contract=(
                browser_chrome_supersession_contract
            ),
            census_era_contract=census_era_contract,
            final_disposition_contract=final_disposition_contract,
            sequence_supersession_enabled=sequence_supersession_enabled,
            generation_navigation=generation_navigation,
        )
    except LandedDiagnosisError as diagnosis_error:
        member_differences = _enumerate_unclassified_members(
            layout_id,
            normalized_landed,
            normalized_settled,
            primary_trace,
            confirmation_trace,
            overlay_reference,
            controls_core_contract=controls_core_contract,
            landed_fixture_receipt=landed_fixture_receipt,
            candidate_fixture_receipt=candidate_fixture_receipt,
            item_row_supersession_contract=item_row_supersession_contract,
            browser_chrome_supersession_contract=(
                browser_chrome_supersession_contract
            ),
            census_era_contract=census_era_contract,
        )
        differences.extend(member_differences)
        if normalized_landed.get("generation") != normalized_settled.get(
            "generation"
        ):
            contract = path_local_generation_contract or {}
            generation_landed = normalized_landed
            generation_settled = normalized_settled
            allow_empty_bound_endpoints = False
            try:
                census_view = require_census_era_contract(census_era_contract)
            except CensusEraV221Error:
                census_view = {}
            if layout_id in census_view.get("generation_layouts", set()):
                generation_landed, generation_settled = normalized_generation_pair(
                    normalized_landed, normalized_settled
                )
                if layout_id in NAMED_ENDPOINT_VACUITY:
                    try:
                        allow_empty_bound_endpoints = _allow_empty_bound_endpoints(
                            layout_id,
                            normalized_settled,
                            generation_navigation or {},
                            final_disposition_contract,
                        )
                    except LandedDiagnosisError as error:
                        differences.append(
                            {
                                "difference_type": "layout_field",
                                "field": "generation",
                                "landed_value": normalized_landed.get("generation"),
                                "settled_value": normalized_settled.get("generation"),
                                "message": str(error),
                            }
                        )
            try:
                authorize_cross_path_generation(
                    generation_landed,
                    generation_settled,
                    contract.get("paired_generation", {}),
                    contract.get("bound_endpoints", []),
                    enabled=contract.get("enabled") is True,
                    allow_empty_bound_endpoints=allow_empty_bound_endpoints,
                )
            except NativeMenuGenerationV219Error as error:
                differences.append(
                    {
                        "difference_type": "layout_field",
                        "field": "generation",
                        "landed_value": normalized_landed.get("generation"),
                        "settled_value": normalized_settled.get("generation"),
                        "message": str(error),
                    }
                )
        diagnosis_message = str(diagnosis_error)
        recorded_messages = {
            difference.get("message")
            for difference in differences
            if isinstance(difference.get("message"), str)
        }
        if not member_differences and diagnosis_message not in recorded_messages:
            differences.append(
                {
                    "difference_type": "authorization_contract_failure",
                    "field": "landed_diagnosis_guard",
                    "message": diagnosis_message,
                }
            )

    unique: dict[bytes, dict[str, Any]] = {}
    for difference in differences:
        unique.setdefault(canonical_bytes(difference), difference)
    return sorted(
        unique.values(),
        key=lambda value: (
            str(value.get("difference_type", "")),
            str(value.get("field", "")),
            str(value.get("element_id", "")),
            str(value.get("semantic_sha256", "")),
        ),
    )


def diagnose_landed_layout(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    primary_trace: dict[str, Any],
    confirmation_trace: dict[str, Any],
    overlay_reference: dict[str, Any],
    controls_title_contract: dict[str, Any] | None = None,
    dark_cloud_login_title_contract: dict[str, Any] | None = None,
    controls_core_contract: dict[str, Any] | None = None,
    landed_fixture_receipt: dict[str, Any] | None = None,
    candidate_fixture_receipt: dict[str, Any] | None = None,
    path_local_generation_contract: dict[str, Any] | None = None,
    item_row_supersession_contract: dict[str, Any] | None = None,
    browser_chrome_supersession_contract: dict[str, Any] | None = None,
    census_era_contract: dict[str, Any] | None = None,
    final_disposition_contract: dict[str, Any] | None = None,
    choice_slot_reconciliation_enabled: bool = True,
    sequence_supersession_enabled: bool = True,
    generation_navigation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(layout_id, str) or not layout_id:
        raise LandedDiagnosisError(
            "landed-vs-settled diagnosis has no unambiguous layout identity"
        )
    if controls_title_contract is None:
        controls_title_contract = {}
    if dark_cloud_login_title_contract is None:
        dark_cloud_login_title_contract = {}
    if controls_core_contract is None:
        controls_core_contract = {}
    if item_row_supersession_contract is None:
        item_row_supersession_contract = {}
    if browser_chrome_supersession_contract is None:
        browser_chrome_supersession_contract = {}
    if census_era_contract is None:
        census_era_contract = {}
    if final_disposition_contract is None:
        final_disposition_contract = {}
    census_view: dict[str, Any] = {}
    if census_era_contract:
        try:
            census_view = require_census_era_contract(census_era_contract)
        except CensusEraV221Error as error:
            raise LandedDiagnosisError(str(error)) from error
    if item_row_supersession_contract:
        try:
            validate_control_layout(
                layout_id,
                settled_layout,
                item_row_supersession_contract,
                candidate_fixture_receipt,
            )
        except DarkCloudItemRowSupersessionError as error:
            raise LandedDiagnosisError(str(error)) from error
    census_field_corrections: list[dict[str, Any]] = []
    class_f_witness = None
    if census_era_contract:
        try:
            class_f_witness = require_class_f_witness(
                layout_id, census_era_contract
            )
        except CensusEraV221Error as error:
            raise LandedDiagnosisError(str(error)) from error
    normalized_identity_landed = copy.deepcopy(landed_layout)
    if any(key[0] == layout_id for key in census_view.get("field_corrections", {})):
        try:
            census_field_corrections = diagnose_field_corrections(
                layout_id,
                landed_layout,
                settled_layout,
                census_era_contract,
                landed_fixture_receipt,
                candidate_fixture_receipt,
            )
        except CensusEraV221Error as error:
            raise LandedDiagnosisError(str(error)) from error
        for correction in census_field_corrections:
            normalized_identity_landed[correction["field"]] = correction["new_value"]
    screen_title_correction = _diagnose_layout_identity_v210(
        layout_id,
        normalized_identity_landed,
        settled_layout,
        controls_title_contract,
        dark_cloud_login_title_contract,
        landed_fixture_receipt,
        candidate_fixture_receipt,
    )
    structural_core_supersession = _diagnose_structural_core_v211(
        layout_id,
        landed_layout,
        settled_layout,
        controls_core_contract,
        landed_fixture_receipt,
        candidate_fixture_receipt,
    )
    census_class_b_adoption = None
    relative_sequence_supersession = None
    if structural_core_supersession is not None:
        projected = _elements(settled_layout, "settled structural core")
        residual: list[dict[str, Any]] = []
    else:
        settled_for_projection = copy.deepcopy(settled_layout)
        try:
            (
                census_class_b_adoption,
                settled_for_projection["elements"],
            ) = split_class_b_additions(
                layout_id,
                _elements(settled_layout, "settled structural core"),
                census_era_contract,
                landed_fixture_receipt,
                candidate_fixture_receipt,
            )
        except CensusEraV221Error as error:
            raise LandedDiagnosisError(str(error)) from error
        (
            projected,
            residual,
            relative_sequence_supersession,
        ) = _project_structural_core_v222(
            layout_id,
            landed_layout,
            settled_for_projection,
            final_disposition_contract,
            landed_fixture_receipt,
            candidate_fixture_receipt,
            sequence_supersession_enabled=sequence_supersession_enabled,
        )
    if structural_core_supersession is not None:
        lifecycle: list[dict[str, Any]] = []
        animation: list[dict[str, Any]] = []
        population: list[dict[str, Any]] = []
        overlay: list[dict[str, Any]] = []
        choice_slot_reconciliation = None
        census_class_a_supersession = None
        population_proof = {
            "structural_core_supersession": "exact_v211_controls_contract"
        }
        residual_after_overlay: list[dict[str, Any]] = []
    else:
        try:
            choice_slot_reconciliation, residual = consume_choice_slot_rows(
                layout_id,
                residual,
                census_era_contract,
                enabled=choice_slot_reconciliation_enabled,
            )
            census_class_a_supersession, residual = consume_class_a_residual(
                layout_id,
                residual,
                census_era_contract,
                landed_fixture_receipt,
                candidate_fixture_receipt,
            )
        except CensusEraV221Error as error:
            raise LandedDiagnosisError(str(error)) from error
        lifecycle, animation, unmatched = match_ambient_members(
            residual, settled_layout
        )
        population, after_population, population_proof = match_population_members(
            unmatched,
            landed_layout.get("generation"),
            settled_layout.get("generation"),
            primary_trace,
            confirmation_trace,
        )
        item_row_supersession = None
        if item_row_supersession_contract:
            try:
                (
                    item_row_supersession,
                    after_population,
                ) = consume_exact_landed_residual(
                    layout_id,
                    landed_layout,
                    settled_layout,
                    after_population,
                    item_row_supersession_contract,
                    landed_fixture_receipt,
                    candidate_fixture_receipt,
                )
            except DarkCloudItemRowSupersessionError as error:
                raise LandedDiagnosisError(str(error)) from error
        browser_chrome_supersession = None
        if browser_chrome_supersession_contract:
            try:
                (
                    browser_chrome_supersession,
                    after_population,
                ) = consume_exact_browser_chrome_residual(
                    layout_id,
                    landed_layout,
                    settled_layout,
                    after_population,
                    browser_chrome_supersession_contract,
                    landed_fixture_receipt,
                    candidate_fixture_receipt,
                )
            except DarkCloudBrowserChromeSupersessionError as error:
                raise LandedDiagnosisError(str(error)) from error
        overlay, residual_after_overlay = match_overlay_members(
            after_population, overlay_reference
        )
    if structural_core_supersession is not None:
        item_row_supersession = None
        browser_chrome_supersession = None
    if residual_after_overlay:
        element = residual_after_overlay[0]
        raise LandedDiagnosisError(
            "landed-vs-settled mismatch survives ambient, population, overlay, "
            f"and animation diagnosis: '{element.get('id')}' / "
            f"'{element.get('art_id') or element.get('action_id') or element.get('text')}'"
        )
    corrected = bool(
        lifecycle
        or population
        or overlay
        or animation
        or screen_title_correction
        or census_field_corrections
        or structural_core_supersession
        or choice_slot_reconciliation
        or census_class_a_supersession
        or census_class_b_adoption
        or item_row_supersession
        or browser_chrome_supersession
        or relative_sequence_supersession
    )
    generation_metadata_correction = None
    generation_changed = landed_layout.get("generation") != settled_layout.get(
        "generation"
    )
    census_generation = layout_id in census_view.get("generation_layouts", set())
    if generation_changed and (not corrected or census_generation):
        contract = path_local_generation_contract or {}
        generation_landed = landed_layout
        generation_settled = settled_layout
        allow_empty_bound_endpoints = False
        if census_generation:
            generation_landed, generation_settled = normalized_generation_pair(
                landed_layout, settled_layout
            )
            if layout_id in NAMED_ENDPOINT_VACUITY:
                allow_empty_bound_endpoints = _allow_empty_bound_endpoints(
                    layout_id,
                    settled_layout,
                    generation_navigation or {},
                    final_disposition_contract,
                )
        try:
            generation_metadata_correction = authorize_cross_path_generation(
                generation_landed,
                generation_settled,
                contract.get("paired_generation", {}),
                contract.get("bound_endpoints", []),
                enabled=contract.get("enabled") is True,
                allow_empty_bound_endpoints=allow_empty_bound_endpoints,
            )
        except NativeMenuGenerationV219Error as error:
            raise LandedDiagnosisError(str(error)) from error
        corrected = True
    if (
        overlay
        and landed_layout.get("generation")
        != settled_layout.get("generation")
        and not population_proof.get(
            "generation_difference_witnessed_in_both_traces"
        )
        and class_f_witness is None
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
        "screen_title_correction": screen_title_correction,
        "census_field_corrections": census_field_corrections,
        "structural_core_supersession": structural_core_supersession,
        "choice_slot_reconciliation_v221": choice_slot_reconciliation,
        "census_class_a_supersession_v221": census_class_a_supersession,
        "census_class_b_adoption_v221": census_class_b_adoption,
        "census_class_f_population_witness_v221": class_f_witness,
        "relative_sequence_supersession_v222": relative_sequence_supersession,
        "dark_cloud_item_row_supersession": item_row_supersession,
        "dark_cloud_browser_chrome_supersession": browser_chrome_supersession,
        "path_local_generation_correction": generation_metadata_correction,
        "all_differing_members_enumerated": True,
    }
