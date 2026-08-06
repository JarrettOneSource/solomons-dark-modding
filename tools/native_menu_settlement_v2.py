#!/usr/bin/env python3
"""Canonical Settlement v2 classification for native menu recordings."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


MINIMUM_SAMPLES = 40
MINIMUM_SPAN_MILLISECONDS = 2_000
MAXIMUM_ANIMATED_FRACTION = 0.30

_GEOMETRY_FIELDS = {"rect", "unclipped_rect"}
_ANIMATION_FIXTURE_FIELDS = {
    "animated_geometry",
    "anchor_rect",
    "anchor_unclipped_rect",
    "envelope",
}
_NON_STRUCTURAL_LAYOUT_FIELDS = {
    "captured_at_milliseconds",
    "animated_element_ids",
}


class SettlementV2Error(ValueError):
    """A recording does not satisfy the Settlement v2 contract."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _element_id(element: dict[str, Any]) -> str:
    value = element.get("id")
    if not isinstance(value, str) or not value:
        raise SettlementV2Error(
            "structural settlement contract: every sampled element needs a non-empty id"
        )
    return value


def _elements_by_id(
    payload: dict[str, Any],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    elements = payload.get("elements")
    if not isinstance(elements, list) or not elements:
        raise SettlementV2Error(
            "structural settlement contract: the sampled layout reached no elements"
        )
    order: list[str] = []
    indexed: dict[str, dict[str, Any]] = {}
    for raw_element in elements:
        if not isinstance(raw_element, dict):
            raise SettlementV2Error(
                "structural settlement contract: sampled elements must be objects"
            )
        element_id = _element_id(raw_element)
        if element_id in indexed:
            raise SettlementV2Error(
                "structural settlement contract: duplicate sampled element id "
                f"'{element_id}' is ambiguous"
            )
        order.append(element_id)
        indexed[element_id] = raw_element
    return order, indexed


def _canonical_element_key(element: dict[str, Any]) -> tuple[float, str]:
    element_id = _element_id(element)
    draw_order = element.get("draw_order")
    if (
        isinstance(draw_order, bool)
        or not isinstance(draw_order, (int, float))
        or not math.isfinite(float(draw_order))
    ):
        raise SettlementV2Error(
            "canonical structural comparison: element "
            f"'{element_id}' has no finite numeric draw_order"
        )
    return float(draw_order), element_id


def _canonical_elements(elements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(elements, key=_canonical_element_key)


def _non_geometry_element(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in _GEOMETRY_FIELDS
        and key not in _ANIMATION_FIXTURE_FIELDS
    }


def non_geometry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: copy.deepcopy(value)
        for key, value in payload.items()
        if key not in _NON_STRUCTURAL_LAYOUT_FIELDS and key != "elements"
    }
    _, indexed = _elements_by_id(payload)
    result["elements"] = _canonical_elements(
        _non_geometry_element(element) for element in indexed.values()
    )
    return result


def non_geometry_sha256(payload: dict[str, Any]) -> str:
    return sha256_json(non_geometry_payload(payload))


def _finite_rect(
    element: dict[str, Any], field: str, element_id: str
) -> tuple[float, float, float, float]:
    value = element.get(field)
    if not isinstance(value, list) or len(value) != 4:
        raise SettlementV2Error(
            f"structural settlement contract: element '{element_id}' has no "
            f"four-number {field}"
        )
    result: list[float] = []
    for coordinate in value:
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise SettlementV2Error(
                f"structural settlement contract: element '{element_id}' has "
                f"non-numeric {field} geometry"
            )
        number = float(coordinate)
        if not math.isfinite(number):
            raise SettlementV2Error(
                f"structural settlement contract: element '{element_id}' has "
                f"non-finite {field} geometry"
            )
        result.append(number)
    return tuple(result)  # type: ignore[return-value]


def _geometry_signature(element: dict[str, Any], element_id: str) -> tuple[Any, ...]:
    return (
        _finite_rect(element, "rect", element_id),
        _finite_rect(element, "unclipped_rect", element_id),
    )


def _geometry_envelope(
    rectangles: Iterable[tuple[float, float, float, float]],
) -> dict[str, float]:
    samples = list(rectangles)
    xs = [rect[0] for rect in samples]
    ys = [rect[1] for rect in samples]
    widths = [rect[2] - rect[0] for rect in samples]
    heights = [rect[3] - rect[1] for rect in samples]
    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
        "min_width": min(widths),
        "max_width": max(widths),
        "min_height": min(heights),
        "max_height": max(heights),
    }


def _first_difference(left: Any, right: Any, prefix: str = "") -> str:
    if type(left) is not type(right):
        return prefix or "value"
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                return path
            difference = _first_difference(left[key], right[key], path)
            if difference:
                return difference
        return ""
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{prefix}.membership" if prefix else "membership"
        for index, (left_value, right_value) in enumerate(zip(left, right)):
            path = f"{prefix}[{index}]"
            difference = _first_difference(left_value, right_value, path)
            if difference:
                return difference
        return ""
    return "" if left == right else (prefix or "value")


def _assert_non_geometry_stable(
    anchor_payload: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    anchor_order, anchor_elements = _elements_by_id(anchor_payload)
    order, elements = _elements_by_id(payload)
    if set(order) != set(anchor_order):
        raise SettlementV2Error(
            "structural settlement guardrail: element membership varied "
            "within the settled window"
        )

    anchor_top = {
        key: value
        for key, value in anchor_payload.items()
        if key not in _NON_STRUCTURAL_LAYOUT_FIELDS and key != "elements"
    }
    top = {
        key: value
        for key, value in payload.items()
        if key not in _NON_STRUCTURAL_LAYOUT_FIELDS and key != "elements"
    }
    if canonical_bytes(anchor_top) != canonical_bytes(top):
        field = _first_difference(anchor_top, top)
        raise SettlementV2Error(
            "structural settlement guardrail: layout field "
            f"'{field}' varied within the settled window"
        )

    for element_id in anchor_order:
        anchor_core = _non_geometry_element(anchor_elements[element_id])
        core = _non_geometry_element(elements[element_id])
        if canonical_bytes(anchor_core) != canonical_bytes(core):
            field = _first_difference(anchor_core, core)
            raise SettlementV2Error(
                "animated classification guardrail: element "
                f"'{element_id}' field '{field}' varied; non-geometry changes "
                "are instability, not animation"
            )


def structural_layout(
    layout: dict[str, Any],
    animated_element_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    if animated_element_ids is None:
        raw_ids = layout.get("animated_element_ids", [])
        if not isinstance(raw_ids, list) or not all(
            isinstance(value, str) for value in raw_ids
        ):
            raise SettlementV2Error(
                "structural layout contract: animated_element_ids must be a string list"
            )
        animated = set(raw_ids)
    else:
        animated = set(animated_element_ids)

    result = {
        key: copy.deepcopy(value)
        for key, value in layout.items()
        if key not in _NON_STRUCTURAL_LAYOUT_FIELDS and key != "elements"
    }
    order, indexed = _elements_by_id(layout)
    if not animated.issubset(indexed):
        missing = sorted(animated - set(indexed))
        raise SettlementV2Error(
            "structural layout contract: animated ids do not resolve uniquely: "
            + ", ".join(missing)
        )
    elements: list[dict[str, Any]] = []
    for element_id in order:
        element = {
            key: copy.deepcopy(value)
            for key, value in indexed[element_id].items()
            if key not in _ANIMATION_FIXTURE_FIELDS
        }
        if element_id in animated:
            element.pop("rect", None)
            element.pop("unclipped_rect", None)
        elements.append(element)
    result["elements"] = elements
    return result


def canonical_structural_layout(
    layout: dict[str, Any],
    animated_element_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return structural data with only element-list order canonicalized.

    Native hook traversal order is instance-arbitrary.  The fixture retains
    its captured order, while comparisons sort by the explicit draw contract
    and use the native element id only as a deterministic tie-breaker.
    """
    result = structural_layout(layout, animated_element_ids)
    elements = result.get("elements")
    if not isinstance(elements, list):
        raise SettlementV2Error(
            "canonical structural comparison: layout has no element list"
        )
    result["elements"] = _canonical_elements(elements)
    return result


def structural_layout_bytes(
    layout: dict[str, Any],
    animated_element_ids: Iterable[str] | None = None,
) -> bytes:
    return canonical_bytes(
        canonical_structural_layout(layout, animated_element_ids)
    )


def canonical_structural_sha256(
    layout: dict[str, Any],
    animated_element_ids: Iterable[str] | None = None,
) -> str:
    return hashlib.sha256(
        structural_layout_bytes(layout, animated_element_ids)
    ).hexdigest()


def structural_differences(
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    animated_element_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Enumerate every structural field/member changed from landed truth."""
    landed = structural_layout(landed_layout, animated_element_ids)
    settled = structural_layout(settled_layout, animated_element_ids)
    landed_elements = landed.pop("elements")
    settled_elements = settled.pop("elements")
    differences: list[dict[str, Any]] = []

    for field in sorted(set(landed) | set(settled)):
        landed_value = landed.get(field)
        settled_value = settled.get(field)
        if field not in landed or field not in settled or landed_value != settled_value:
            differences.append(
                {
                    "kind": "layout_field",
                    "field": field,
                    "landed_value": copy.deepcopy(landed_value),
                    "settled_value": copy.deepcopy(settled_value),
                }
            )

    landed_by_id = {_element_id(element): element for element in landed_elements}
    settled_by_id = {_element_id(element): element for element in settled_elements}
    landed_ids = set(landed_by_id)
    settled_ids = set(settled_by_id)
    for element in _canonical_elements(
        landed_by_id[element_id] for element_id in landed_ids - settled_ids
    ):
        differences.append(
            {
                "kind": "landed_only_element",
                "element_id": _element_id(element),
                "landed_value": copy.deepcopy(element),
                "settled_value": None,
            }
        )
    for element in _canonical_elements(
        settled_by_id[element_id] for element_id in settled_ids - landed_ids
    ):
        differences.append(
            {
                "kind": "settled_only_element",
                "element_id": _element_id(element),
                "landed_value": None,
                "settled_value": copy.deepcopy(element),
            }
        )
    shared_ids = landed_ids & settled_ids
    for element in _canonical_elements(
        settled_by_id[element_id] for element_id in shared_ids
    ):
        element_id = _element_id(element)
        landed_element = landed_by_id[element_id]
        settled_element = settled_by_id[element_id]
        for field in sorted(set(landed_element) | set(settled_element)):
            landed_value = landed_element.get(field)
            settled_value = settled_element.get(field)
            if (
                field not in landed_element
                or field not in settled_element
                or landed_value != settled_value
            ):
                differences.append(
                    {
                        "kind": "element_field",
                        "element_id": element_id,
                        "field": field,
                        "landed_value": copy.deepcopy(landed_value),
                        "settled_value": copy.deepcopy(settled_value),
                    }
                )
    return differences


def _shape_layout(
    anchor_payload: dict[str, Any],
    animated_ids: list[str],
    geometries: dict[str, list[tuple[Any, ...]]],
    captured_at_milliseconds: int,
) -> dict[str, Any]:
    layout = {
        key: copy.deepcopy(value)
        for key, value in anchor_payload.items()
        if key not in _NON_STRUCTURAL_LAYOUT_FIELDS and key != "elements"
    }
    layout["captured_at_milliseconds"] = captured_at_milliseconds
    layout["animated_element_ids"] = list(animated_ids)
    animated = set(animated_ids)
    order, indexed = _elements_by_id(anchor_payload)
    elements: list[dict[str, Any]] = []
    for element_id in order:
        source = indexed[element_id]
        if element_id not in animated:
            elements.append(copy.deepcopy(source))
            continue
        element = _non_geometry_element(source)
        element["animated_geometry"] = True
        element["anchor_rect"] = copy.deepcopy(source["rect"])
        element["anchor_unclipped_rect"] = copy.deepcopy(
            source["unclipped_rect"]
        )
        rects = [geometry[0] for geometry in geometries[element_id]]
        unclipped = [geometry[1] for geometry in geometries[element_id]]
        element["envelope"] = {
            "sample_count": len(rects),
            "rect": _geometry_envelope(rects),
            "unclipped_rect": _geometry_envelope(unclipped),
        }
        elements.append(element)
    layout["elements"] = elements
    return layout


def classify_window(
    samples: list[dict[str, Any]],
    *,
    minimum_samples: int = MINIMUM_SAMPLES,
    minimum_span_milliseconds: int = MINIMUM_SPAN_MILLISECONDS,
    maximum_animated_fraction: float = MAXIMUM_ANIMATED_FRACTION,
) -> dict[str, Any]:
    if len(samples) < minimum_samples:
        raise SettlementV2Error(
            f"structural settlement contract: window has {len(samples)} samples; "
            f"at least {minimum_samples} are required"
        )
    elapsed = [int(sample["elapsed_milliseconds"]) for sample in samples]
    if elapsed != sorted(elapsed):
        raise SettlementV2Error(
            "structural settlement contract: sample clocks are not monotonic"
        )
    stable_span = elapsed[-1] - elapsed[0]
    if stable_span < minimum_span_milliseconds:
        raise SettlementV2Error(
            f"structural settlement contract: window spans {stable_span} ms; "
            f"at least {minimum_span_milliseconds} ms are required"
        )

    payloads = [sample.get("payload") for sample in samples]
    if not all(isinstance(payload, dict) for payload in payloads):
        raise SettlementV2Error(
            "structural settlement contract: every sample needs an object payload"
        )
    typed_payloads: list[dict[str, Any]] = payloads  # type: ignore[assignment]
    anchor_payload = typed_payloads[0]
    anchor_order, _ = _elements_by_id(anchor_payload)
    for payload in typed_payloads[1:]:
        _assert_non_geometry_stable(anchor_payload, payload)

    geometries: dict[str, list[tuple[Any, ...]]] = {
        element_id: [] for element_id in anchor_order
    }
    for payload in typed_payloads:
        _, indexed = _elements_by_id(payload)
        for element_id in anchor_order:
            geometries[element_id].append(
                _geometry_signature(indexed[element_id], element_id)
            )
    animated_ids = [
        element_id
        for element_id in anchor_order
        if len(set(geometries[element_id])) > 1
    ]
    animated_fraction = len(animated_ids) / len(anchor_order)
    if animated_fraction > maximum_animated_fraction:
        screen = str(anchor_payload.get("screen_id", "unknown"))
        raise SettlementV2Error(
            "animated geometry cap exceeded: "
            f"{len(animated_ids)}/{len(anchor_order)} elements "
            f"({animated_fraction:.1%}) exceeds 30% for '{screen}'"
        )

    captured_at = int(samples[0].get("captured_at_milliseconds", elapsed[0]))
    layout = _shape_layout(
        anchor_payload,
        animated_ids,
        geometries,
        captured_at,
    )
    structural = structural_layout(layout, animated_ids)
    return {
        "settlement_spec": "2.1",
        "criterion": (
            "at least 40 consecutive samples spanning at least 2 seconds with "
            "byte-identical structural payloads and an identical measured "
            "animated element-id set"
        ),
        "structural_element_order": "draw_order_then_element_id",
        "settle_latency_milliseconds": elapsed[-1],
        "stable_span_milliseconds": stable_span,
        "consecutive_structural_samples": len(samples),
        "animated_id_set_sample_count": len(samples),
        "animated_element_ids": animated_ids,
        "animated_element_count": len(animated_ids),
        "element_count": len(anchor_order),
        "animated_fraction": animated_fraction,
        "structural_sha256": sha256_json(structural),
        "layout": layout,
    }


def find_settled_window(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        raise SettlementV2Error(
            "structural settlement contract: capture contained no samples"
        )
    phase_sha = ""
    phase_start = 0
    for index, sample in enumerate(samples):
        payload = sample.get("payload")
        if not isinstance(payload, dict):
            raise SettlementV2Error(
                "structural settlement contract: every sample needs an object payload"
            )
        current_sha = non_geometry_sha256(payload)
        if current_sha != phase_sha:
            phase_sha = current_sha
            phase_start = index
        window = samples[phase_start : index + 1]
        if len(window) < MINIMUM_SAMPLES:
            continue
        span = (
            int(window[-1]["elapsed_milliseconds"])
            - int(window[0]["elapsed_milliseconds"])
        )
        if span < MINIMUM_SPAN_MILLISECONDS:
            continue
        result = classify_window(window)
        result["stable_start_index"] = phase_start
        result["stable_end_index"] = index
        result["total_semantic_samples"] = index + 1
        return result
    raise SettlementV2Error(
        "capture never reached 40 consecutive structurally byte-identical "
        "samples with one measured animated ID set spanning at least 2 seconds; "
        f"samples={len(samples)}"
    )


def validate_declared_settlement(
    layout: dict[str, Any], samples: list[dict[str, Any]]
) -> dict[str, Any]:
    declared = layout.get("animated_element_ids")
    if not isinstance(declared, list) or not all(
        isinstance(value, str) for value in declared
    ):
        raise SettlementV2Error(
            "animated classification contract: layout has no measured animated id list"
        )
    if len(declared) != len(set(declared)):
        raise SettlementV2Error(
            "animated classification contract: duplicate animated ids are ambiguous"
        )
    classified = classify_window(samples)
    measured = classified["animated_element_ids"]
    undeclared = [value for value in measured if value not in declared]
    if undeclared:
        raise SettlementV2Error(
            "structural settlement contract: non-animated element "
            f"'{undeclared[0]}' varied rect/unclipped_rect"
        )
    false_declarations = [value for value in declared if value not in measured]
    if false_declarations:
        raise SettlementV2Error(
            "animated classification contract: element "
            f"'{false_declarations[0]}' was declared animated without measured "
            "geometry variation"
        )
    expected_layout = classified["layout"]
    expected_layout["captured_at_milliseconds"] = layout.get(
        "captured_at_milliseconds"
    )
    if canonical_bytes(layout) != canonical_bytes(expected_layout):
        difference = _first_difference(expected_layout, layout)
        raise SettlementV2Error(
            "animated fixture contract: measured anchor/envelope disagrees at "
            f"'{difference}'"
        )
    return classified


def assert_confirmation_matches(
    primary_layout: dict[str, Any], confirmation_layout: dict[str, Any]
) -> None:
    primary_ids = primary_layout.get("animated_element_ids", [])
    confirmation_ids = confirmation_layout.get("animated_element_ids", [])
    if (
        not isinstance(primary_ids, list)
        or not isinstance(confirmation_ids, list)
        or not all(isinstance(value, str) and value for value in primary_ids)
        or not all(isinstance(value, str) and value for value in confirmation_ids)
        or len(primary_ids) != len(set(primary_ids))
        or len(confirmation_ids) != len(set(confirmation_ids))
    ):
        raise SettlementV2Error(
            "animated ID confirmation mismatch: fresh captures need unique "
            "non-empty animated element ids"
        )
    if set(primary_ids) != set(confirmation_ids):
        raise SettlementV2Error(
            "animated ID confirmation mismatch: fresh captures classified "
            f"primary={primary_ids} confirmation={confirmation_ids}"
        )


def assert_canonical_structure_matches(
    primary_layout: dict[str, Any], confirmation_layout: dict[str, Any]
) -> None:
    """Require v2.1 cross-instance structure without contracting list position."""
    try:
        assert_confirmation_matches(primary_layout, confirmation_layout)
        primary_ids = primary_layout.get("animated_element_ids", [])
        confirmation_ids = confirmation_layout.get("animated_element_ids", [])
        primary_bytes = structural_layout_bytes(primary_layout, primary_ids)
        confirmation_bytes = structural_layout_bytes(
            confirmation_layout,
            confirmation_ids,
        )
    except SettlementV2Error as error:
        raise SettlementV2Error(
            "landed population override requires second-instance canonical "
            f"structural agreement: {error}"
        ) from error
    if primary_bytes != confirmation_bytes:
        raise SettlementV2Error(
            "landed population override requires second-instance canonical "
            "structural agreement"
        )


def _trace_payloads(
    trace: dict[str, Any], label: str
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    polled_phases = trace.get("structural_phases")
    high_cadence_phases = trace.get("high_cadence_structural_phases", [])
    samples = trace.get("settled_window_samples")
    if not isinstance(polled_phases, list) or not polled_phases:
        raise SettlementV2Error(
            f"landed population override: {label} trace has no population phases"
        )
    if not isinstance(high_cadence_phases, list):
        raise SettlementV2Error(
            "landed population override: "
            f"{label} high-cadence population phases are not a list"
        )
    phases = [*high_cadence_phases, *polled_phases]
    if not isinstance(samples, list) or len(samples) < MINIMUM_SAMPLES:
        raise SettlementV2Error(
            f"landed population override: {label} trace has no 40-sample "
            "settled window"
        )
    phase_payloads: list[dict[str, Any]] = []
    for index, phase in enumerate(phases):
        payload = phase.get("payload") if isinstance(phase, dict) else None
        if not isinstance(payload, dict):
            raise SettlementV2Error(
                "landed population override: "
                f"{label} population phase {index} has no payload"
            )
        phase_payloads.append(payload)
    settled_payloads: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        payload = sample.get("payload") if isinstance(sample, dict) else None
        if not isinstance(payload, dict):
            raise SettlementV2Error(
                "landed population override: "
                f"{label} settled sample {index} has no payload"
            )
        settled_payloads.append(payload)
    return phase_payloads, settled_payloads, phases


def _element_for_id(
    payload: dict[str, Any], element_id: str
) -> dict[str, Any] | None:
    _, indexed = _elements_by_id(payload)
    return indexed.get(element_id)


def _population_witness_indexes(
    difference: dict[str, Any], phase_payloads: list[dict[str, Any]]
) -> list[int]:
    kind = difference["kind"]
    landed_value = difference.get("landed_value")
    witnesses: list[int] = []
    for index, payload in enumerate(phase_payloads):
        if kind == "layout_field":
            field = difference["field"]
            matched = field in payload and payload[field] == landed_value
        elif kind == "landed_only_element":
            matched = _element_for_id(payload, difference["element_id"]) is not None
        elif kind == "element_field":
            element = _element_for_id(payload, difference["element_id"])
            field = difference["field"]
            matched = (
                isinstance(element, dict)
                and field in element
                and element[field] == landed_value
            )
        else:
            matched = False
        if matched:
            witnesses.append(index)
    return witnesses


def _landed_difference_in_settled_payload(
    difference: dict[str, Any], payload: dict[str, Any]
) -> bool:
    kind = difference["kind"]
    landed_value = difference.get("landed_value")
    if kind == "layout_field":
        field = difference["field"]
        return field in payload and payload[field] == landed_value
    if kind == "landed_only_element":
        return _element_for_id(payload, difference["element_id"]) is not None
    if kind == "element_field":
        element = _element_for_id(payload, difference["element_id"])
        field = difference["field"]
        return (
            isinstance(element, dict)
            and field in element
            and element[field] == landed_value
        )
    return False


def _difference_label(difference: dict[str, Any]) -> str:
    if difference["kind"] == "layout_field":
        return f"layout field '{difference['field']}'"
    if difference["kind"] == "element_field":
        return (
            f"element '{difference['element_id']}' field "
            f"'{difference['field']}'"
        )
    return f"differing member '{difference['element_id']}'"


def _population_trace_summary(
    trace: dict[str, Any],
    phase_payloads: list[dict[str, Any]],
    phases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "element_count_trace": [
            len(payload.get("elements", [])) for payload in phase_payloads
        ],
        "generation_trace": [payload.get("generation") for payload in phase_payloads],
        "phase_observations": [
            phase.get("observations") if isinstance(phase, dict) else None
            for phase in phases
        ],
        "settled_sample_count": len(trace["settled_window_samples"]),
    }


def build_population_phase_override(
    landed_layout: dict[str, Any],
    primary_layout: dict[str, Any],
    confirmation_layout: dict[str, Any],
    primary_trace: dict[str, Any],
    confirmation_trace: dict[str, Any],
) -> dict[str, Any]:
    """Derive and validate the narrow Settlement v2.1 landed override."""
    assert_canonical_structure_matches(primary_layout, confirmation_layout)
    primary_ids = primary_layout.get("animated_element_ids", [])
    differences = structural_differences(
        landed_layout,
        primary_layout,
        primary_ids,
    )
    if not differences:
        raise SettlementV2Error(
            "landed population override: candidate already matches landed structure"
        )
    landed_generation = landed_layout.get("generation")
    settled_generation = primary_layout.get("generation")
    if landed_generation == settled_generation:
        raise SettlementV2Error(
            "landed population override: landed and settled generations do not differ"
        )
    if not any(
        difference["kind"] == "layout_field"
        and difference["field"] == "generation"
        for difference in differences
    ):
        raise SettlementV2Error(
            "landed population override: generation mismatch was not enumerated"
        )

    primary_phases, primary_settled, primary_phase_entries = _trace_payloads(
        primary_trace,
        "primary",
    )
    confirmation_phases, confirmation_settled, confirmation_phase_entries = (
        _trace_payloads(
        confirmation_trace,
        "confirmation",
        )
    )
    proven_differences: list[dict[str, Any]] = []
    for difference in differences:
        if difference["kind"] == "settled_only_element":
            raise SettlementV2Error(
                "landed population override: settled-only member "
                f"'{difference['element_id']}' is not a vanishing population member"
            )
        label = _difference_label(difference)
        if any(
            _landed_difference_in_settled_payload(difference, payload)
            for payload in (*primary_settled, *confirmation_settled)
        ):
            raise SettlementV2Error(
                f"landed population override rejected: {label} is present "
                "in a settled window"
            )
        primary_witnesses = _population_witness_indexes(
            difference,
            primary_phases,
        )
        confirmation_witnesses = _population_witness_indexes(
            difference,
            confirmation_phases,
        )
        if not primary_witnesses or not confirmation_witnesses:
            raise SettlementV2Error(
                "landed population override lacks two-instance population "
                f"proof for {label}"
            )
        proof = copy.deepcopy(difference)
        proof["primary_population_phase_indexes"] = primary_witnesses
        proof["confirmation_population_phase_indexes"] = confirmation_witnesses
        proof["primary_settled_absence_samples"] = len(primary_settled)
        proof["confirmation_settled_absence_samples"] = len(
            confirmation_settled
        )
        proven_differences.append(proof)

    validate_declared_settlement(
        primary_layout,
        primary_trace["settled_window_samples"],
    )
    validate_declared_settlement(
        confirmation_layout,
        confirmation_trace["settled_window_samples"],
    )

    primary_elements = primary_layout.get("elements", [])
    landed_elements = landed_layout.get("elements", [])
    return {
        "rule": "Settlement v2.1 landed population-phase override",
        "canonical_order": "draw_order_then_element_id",
        "landed_generation": landed_generation,
        "landed_element_count": len(landed_elements),
        "settled_generation": settled_generation,
        "settled_element_count": len(primary_elements),
        "canonical_structural_sha256": canonical_structural_sha256(
            primary_layout,
            primary_ids,
        ),
        "confirmation_canonical_structural_sha256": canonical_structural_sha256(
            confirmation_layout,
            confirmation_layout.get("animated_element_ids", []),
        ),
        "structural_differences": proven_differences,
        "primary_population_trace": _population_trace_summary(
            primary_trace,
            primary_phases,
            primary_phase_entries,
        ),
        "confirmation_population_trace": _population_trace_summary(
            confirmation_trace,
            confirmation_phases,
            confirmation_phase_entries,
        ),
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _classify_command(input_path: Path, output_path: Path) -> None:
    samples = _read_json(input_path)
    if not isinstance(samples, list):
        raise SettlementV2Error("classifier input must be a JSON sample list")
    _write_json(output_path, classify_window(samples))


def _find_command(input_path: Path, output_path: Path) -> None:
    samples = _read_json(input_path)
    if not isinstance(samples, list):
        raise SettlementV2Error("classifier input must be a JSON sample list")
    _write_json(output_path, find_settled_window(samples))


def _summarize_layout_command(input_path: Path, output_path: Path) -> None:
    layout = _read_json(input_path)
    if not isinstance(layout, dict):
        raise SettlementV2Error("layout summary input must be a JSON object")
    raw_ids = layout.get("animated_element_ids", [])
    if not isinstance(raw_ids, list) or not all(
        isinstance(value, str) for value in raw_ids
    ):
        raise SettlementV2Error(
            "layout summary input has no measured animated element-id list"
        )
    _write_json(
        output_path,
        {
            "animated_element_ids": raw_ids,
            "structural_sha256": hashlib.sha256(
                structural_layout_bytes(layout, raw_ids)
            ).hexdigest(),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    classify_parser = subparsers.add_parser("classify")
    classify_parser.add_argument("--input", type=Path, required=True)
    classify_parser.add_argument("--output", type=Path, required=True)
    find_parser = subparsers.add_parser("find")
    find_parser.add_argument("--input", type=Path, required=True)
    find_parser.add_argument("--output", type=Path, required=True)
    summary_parser = subparsers.add_parser("summarize-layout")
    summary_parser.add_argument("--input", type=Path, required=True)
    summary_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "classify":
            _classify_command(args.input, args.output)
        elif args.command == "find":
            _find_command(args.input, args.output)
        elif args.command == "summarize-layout":
            _summarize_layout_command(args.input, args.output)
    except SettlementV2Error as error:
        parser.exit(2, f"STOP: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
