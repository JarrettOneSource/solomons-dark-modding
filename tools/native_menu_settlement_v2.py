#!/usr/bin/env python3
"""Canonical Settlement v2 classification for native menu recordings."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

if __package__:
    from .native_menu_ambient_lifecycle import (
        AmbientLifecycleError,
        classify_ambient_extended_observation,
        classify_ambient_window,
        find_ambient_settled_window,
        resolve_ambient_lifecycle,
    )
    from .native_menu_overlay_v25 import (
        OVERLAY_REFERENCE_SCHEMA as OVERLAY_REFERENCE_SCHEMA_V25,
        OverlayV25Error,
        assert_overlay_hygiene as assert_overlay_hygiene_v25,
    )
else:
    from native_menu_ambient_lifecycle import (  # type: ignore[no-redef]
        AmbientLifecycleError,
        classify_ambient_extended_observation,
        classify_ambient_window,
        find_ambient_settled_window,
        resolve_ambient_lifecycle,
    )
    from native_menu_overlay_v25 import (  # type: ignore[no-redef]
        OVERLAY_REFERENCE_SCHEMA as OVERLAY_REFERENCE_SCHEMA_V25,
        OverlayV25Error,
        assert_overlay_hygiene as assert_overlay_hygiene_v25,
    )


MINIMUM_SAMPLES = 40
MINIMUM_SPAN_MILLISECONDS = 2_000
MAXIMUM_ANIMATED_FRACTION = 0.30
EXTENDED_OBSERVATION_MINIMUM_MILLISECONDS = 60_000
EXTENDED_OBSERVATION_SETTLE_SPAN_MULTIPLIER = 10
EXTENDED_OBSERVATION_MINIMUM_SAMPLES = 200
SETTLEMENT_SPEC = "2.5"
OVERLAY_REFERENCE_SCHEMA = "solomon-dark-native-menu-overlay-reference-v2"
_INTENTIONAL_OVERLAY_SCREEN_IDS = {"beta_notice"}

_GEOMETRY_FIELDS = {"rect", "unclipped_rect"}
_COMPACT_POPULATION_ELEMENT_FIELDS = (
    "id",
    "kind",
    "text",
    "action_id",
    "art_id",
    "font_id",
    "text_style",
    "visible",
    "interactive",
    "draw_order",
    "rect",
    "unclipped_rect",
)
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


def element_art_id_suffix(element: dict[str, Any]) -> str:
    """Return the draw-unique suffix after the screen-local `.art.` prefix."""
    element_id = _element_id(element)
    if element.get("kind") != "art" or ".art." not in element_id:
        raise SettlementV2Error(
            "overlay reference contract: element "
            f"'{element_id}' is not a screen-tagged art draw"
        )
    suffix = element_id.split(".art.", 1)[1]
    if not suffix:
        raise SettlementV2Error(
            "overlay reference contract: element "
            f"'{element_id}' has an empty art-ID suffix"
        )
    return suffix


def _overlay_semantic_payload(element: dict[str, Any]) -> dict[str, Any]:
    """Return draw semantics independent of screen-local positional bookkeeping.

    Element IDs and absolute draw orders are assigned in the context of the
    underlying screen.  Every other captured field, including both geometry
    fields, identifies the draw itself.  Draw order and ordinal IDs are
    regenerated and checked after semantic multiset subtraction.
    """
    element_id = _element_id(element)
    if element.get("kind") != "art":
        raise SettlementV2Error(
            "overlay reference contract: semantic overlay member "
            f"'{element_id}' is not an art draw"
        )
    _finite_rect(element, "rect", element_id)
    _finite_rect(element, "unclipped_rect", element_id)
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in {"id", "draw_order"}
        and key not in _ANIMATION_FIXTURE_FIELDS
    }


def _semantic_multiset_entries(
    elements: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload_by_signature: dict[bytes, dict[str, Any]] = {}
    counts: Counter[bytes] = Counter()
    for element in elements:
        payload = _overlay_semantic_payload(element)
        signature = canonical_bytes(payload)
        payload_by_signature.setdefault(signature, payload)
        counts[signature] += 1
    return [
        {
            "count": counts[signature],
            "payload": payload_by_signature[signature],
        }
        for signature in sorted(counts)
    ]


def _validated_overlay_counter(
    reference: dict[str, Any],
) -> Counter[bytes]:
    if reference.get("schema") != OVERLAY_REFERENCE_SCHEMA:
        raise SettlementV2Error(
            "overlay reference contract: reference schema is not recognized"
        )
    entries = reference.get("overlay_semantic_draw_multiset")
    if not isinstance(entries, list) or not entries:
        raise SettlementV2Error(
            "overlay reference contract: semantic draw multiset is absent"
        )
    counter: Counter[bytes] = Counter()
    previous_signature: bytes | None = None
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SettlementV2Error(
                "overlay reference contract: semantic draw multiset entry "
                f"{index} is not an object"
            )
        count = entry.get("count")
        payload = entry.get("payload")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
            or not isinstance(payload, dict)
            or not payload
        ):
            raise SettlementV2Error(
                "overlay reference contract: semantic draw multiset entry "
                f"{index} has no positive count and payload"
            )
        if "id" in payload or "draw_order" in payload:
            raise SettlementV2Error(
                "overlay reference contract: semantic draw identity contains "
                "screen-local id or draw_order bookkeeping"
            )
        if payload.get("kind") != "art":
            raise SettlementV2Error(
                "overlay reference contract: semantic draw multiset contains "
                "a non-art member"
            )
        signature = canonical_bytes(payload)
        if previous_signature is not None and signature <= previous_signature:
            raise SettlementV2Error(
                "overlay reference contract: semantic draw multiset is not "
                "strictly canonical and duplicate-free"
            )
        previous_signature = signature
        counter[signature] = count
    return counter


def validate_overlay_reference(reference: dict[str, Any]) -> Counter[bytes]:
    if reference.get("schema") != OVERLAY_REFERENCE_SCHEMA:
        raise SettlementV2Error(
            "overlay reference contract: reference schema is not recognized"
        )
    counter = _validated_overlay_counter(reference)
    elements = reference.get("overlay_only_art_elements")
    if not isinstance(elements, list) or not all(
        isinstance(value, dict) for value in elements
    ):
        raise SettlementV2Error(
            "overlay reference contract: overlay-only art elements are absent"
        )
    measured = _semantic_multiset_entries(elements)
    if canonical_bytes(measured) != canonical_bytes(
        reference["overlay_semantic_draw_multiset"]
    ):
        raise SettlementV2Error(
            "overlay reference contract: recorded semantic multiset does not "
            "equal the overlay-only art draw evidence"
        )
    header = reference.get("header")
    if not isinstance(header, dict):
        raise SettlementV2Error(
            "overlay reference contract: reference header is absent"
        )
    for label in ("overlay_capture", "clean_capture"):
        capture = header.get(label)
        if (
            not isinstance(capture, dict)
            or not isinstance(capture.get("evidence_path"), str)
            or not capture["evidence_path"]
            or not isinstance(capture.get("bytes"), int)
            or capture["bytes"] <= 0
            or not isinstance(capture.get("sha256"), str)
            or len(capture["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in capture["sha256"])
        ):
            raise SettlementV2Error(
                f"overlay reference contract: {label} evidence receipt is incomplete"
            )
    if sum(counter.values()) != len(elements):
        raise SettlementV2Error(
            "overlay reference contract: semantic multiset census does not "
            "equal the overlay-only art draw evidence"
        )
    return counter


def derive_overlay_reference(
    overlay_layout: dict[str, Any], clean_layout: dict[str, Any]
) -> dict[str, Any]:
    """Derive the independently captured overlay semantic draw multiset."""
    _, clean_by_id = _elements_by_id(clean_layout)
    _, overlay_by_id = _elements_by_id(overlay_layout)
    clean_counter: Counter[bytes] = Counter(
        canonical_bytes(_overlay_semantic_payload(element))
        for element in clean_by_id.values()
        if element.get("kind") == "art"
    )
    overlay_groups: dict[bytes, list[dict[str, Any]]] = {}
    for element in overlay_by_id.values():
        if element.get("kind") != "art":
            continue
        signature = canonical_bytes(_overlay_semantic_payload(element))
        overlay_groups.setdefault(signature, []).append(element)
    overlay_counter = Counter(
        {signature: len(elements) for signature, elements in overlay_groups.items()}
    )
    clean_only = clean_counter - overlay_counter
    if clean_only:
        raise SettlementV2Error(
            "overlay reference contract: pre-dismissal capture lost clean-screen "
            "draw semantics"
        )
    difference = overlay_counter - clean_counter
    overlay_only: list[dict[str, Any]] = []
    for signature in sorted(difference):
        candidates = _canonical_elements(overlay_groups[signature])
        overlay_only.extend(
            copy.deepcopy(element)
            for element in candidates[: difference[signature]]
        )
    overlay_only = _canonical_elements(overlay_only)
    if not overlay_only:
        raise SettlementV2Error(
            "overlay reference contract: pre-dismissal capture has no "
            "overlay-only art draws"
        )
    return {
        "overlay_semantic_draw_multiset": _semantic_multiset_entries(
            overlay_only
        ),
        "overlay_only_art_elements": overlay_only,
    }


def _layout_semantic_counter(layout: dict[str, Any]) -> Counter[bytes]:
    _, elements = _elements_by_id(layout)
    signatures: list[bytes] = []
    for element in elements.values():
        if element.get("kind") != "art":
            continue
        semantic_element = copy.deepcopy(element)
        if semantic_element.get("animated_geometry") is True:
            semantic_element["rect"] = copy.deepcopy(
                semantic_element.get("anchor_rect")
            )
            semantic_element["unclipped_rect"] = copy.deepcopy(
                semantic_element.get("anchor_unclipped_rect")
            )
        signatures.append(
            canonical_bytes(_overlay_semantic_payload(semantic_element))
        )
    return Counter(signatures)


def overlay_semantic_multiset_is_present(
    layout: dict[str, Any], reference: dict[str, Any]
) -> bool:
    required = validate_overlay_reference(reference)
    observed = _layout_semantic_counter(layout)
    return all(observed[signature] >= count for signature, count in required.items())


def assert_overlay_hygiene(
    layout: dict[str, Any], reference: dict[str, Any]
) -> None:
    screen_id = str(layout.get("screen_id", ""))
    if (
        screen_id not in _INTENTIONAL_OVERLAY_SCREEN_IDS
        and overlay_semantic_multiset_is_present(layout, reference)
    ):
        raise SettlementV2Error(
            "overlay hygiene contract: non-overlay screen "
            f"'{screen_id}' contains the complete beta-dialog semantic multiset"
        )


def assert_overlay_sample_hygiene(
    samples: list[dict[str, Any]], reference: dict[str, Any]
) -> None:
    if not samples:
        raise SettlementV2Error(
            "overlay hygiene contract: sample sweep reached no capture payloads"
        )
    for index, sample in enumerate(samples):
        payload = sample.get("payload") if isinstance(sample, dict) else None
        if not isinstance(payload, dict):
            raise SettlementV2Error(
                "overlay hygiene contract: sample "
                f"{index} has no semantic payload"
            )
        try:
            assert_overlay_hygiene(payload, reference)
        except SettlementV2Error as error:
            raise SettlementV2Error(
                f"overlay hygiene contract: sample {index} is contaminated: {error}"
            ) from error


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


def _motion_events(
    samples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive every exact inter-sample rect change from measured payloads."""
    if not samples:
        raise SettlementV2Error(
            "motion capability recorder defect: observation contains no samples"
        )
    payloads = [sample.get("payload") for sample in samples]
    if not all(isinstance(payload, dict) for payload in payloads):
        raise SettlementV2Error(
            "motion capability recorder defect: every observation sample needs a payload"
        )
    typed_payloads: list[dict[str, Any]] = payloads  # type: ignore[assignment]
    anchor = typed_payloads[0]
    anchor_order, _ = _elements_by_id(anchor)
    for payload in typed_payloads[1:]:
        _assert_non_geometry_stable(anchor, payload)

    events: list[dict[str, Any]] = []
    _, previous = _elements_by_id(anchor)
    for sample_index, (sample, payload) in enumerate(
        zip(samples[1:], typed_payloads[1:]), start=1
    ):
        _, current = _elements_by_id(payload)
        for element_id in anchor_order:
            previous_rect = _finite_rect(previous[element_id], "rect", element_id)
            current_rect = _finite_rect(current[element_id], "rect", element_id)
            previous_unclipped = _finite_rect(
                previous[element_id], "unclipped_rect", element_id
            )
            current_unclipped = _finite_rect(
                current[element_id], "unclipped_rect", element_id
            )
            if (
                previous_rect == current_rect
                and previous_unclipped == current_unclipped
            ):
                continue
            events.append(
                {
                    "sample_index": sample_index,
                    "elapsed_milliseconds": int(sample["elapsed_milliseconds"]),
                    "element_id": element_id,
                    "rect_delta": [
                        current_rect[index] - previous_rect[index]
                        for index in range(4)
                    ],
                    "unclipped_rect_delta": [
                        current_unclipped[index] - previous_unclipped[index]
                        for index in range(4)
                    ],
                }
            )
        previous = current
    return events


def classify_extended_observation(
    samples: list[dict[str, Any]],
    *,
    required_span_milliseconds: int,
    minimum_samples: int = EXTENDED_OBSERVATION_MINIMUM_SAMPLES,
) -> dict[str, Any]:
    """Validate and summarize one v2.3 corroboration observation."""
    minimum_span = max(
        EXTENDED_OBSERVATION_MINIMUM_MILLISECONDS,
        int(required_span_milliseconds),
    )
    if len(samples) < minimum_samples:
        raise SettlementV2Error(
            "motion capability corroboration contract: extended observation has "
            f"{len(samples)} samples; at least {minimum_samples} are required"
        )
    elapsed = [int(sample["elapsed_milliseconds"]) for sample in samples]
    if elapsed != sorted(elapsed):
        raise SettlementV2Error(
            "motion capability corroboration contract: sample clocks are not monotonic"
        )
    span = elapsed[-1] - elapsed[0]
    if span < minimum_span:
        raise SettlementV2Error(
            "motion capability corroboration contract: extended observation spans "
            f"{span} ms; at least {minimum_span} ms are required"
        )
    events = _motion_events(samples)
    moving_ids = sorted({event["element_id"] for event in events})
    return {
        "required_span_milliseconds": minimum_span,
        "observed_span_milliseconds": span,
        "sample_count": len(samples),
        "motion_event_count": len(events),
        "moving_element_ids": moving_ids,
        "motion_events": events,
    }


def _observation_identity(observation: dict[str, Any], label: str) -> tuple[str, int]:
    instance = observation.get("instance")
    process_id = observation.get("process_id")
    if (
        not isinstance(instance, str)
        or not instance
        or isinstance(process_id, bool)
        or not isinstance(process_id, int)
        or process_id <= 0
    ):
        raise SettlementV2Error(
            f"motion capability recorder defect: {label} has no exact instance/process identity"
        )
    return instance, process_id


def _observation_evidence(
    observation: dict[str, Any], label: str
) -> dict[str, Any]:
    evidence = observation.get("evidence")
    if not isinstance(evidence, dict):
        raise SettlementV2Error(
            f"motion capability recorder defect: {label} has no evidence receipt"
        )
    path = evidence.get("evidence_path")
    sha256 = evidence.get("sha256")
    size = evidence.get("bytes")
    if (
        not isinstance(path, str)
        or not path
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 0
    ):
        raise SettlementV2Error(
            f"motion capability recorder defect: {label} evidence receipt is incomplete"
        )
    return copy.deepcopy(evidence)


def _raw_observation(
    observation: dict[str, Any], label: str
) -> dict[str, Any]:
    samples = observation.get("samples")
    layout = observation.get("layout")
    settlement = observation.get("settlement")
    if (
        not isinstance(samples, list)
        or not isinstance(layout, dict)
        or not isinstance(settlement, dict)
    ):
        raise SettlementV2Error(
            f"motion capability recorder defect: {label} lacks its raw window"
        )
    classified = validate_declared_settlement(layout, samples)
    if settlement.get("structural_sha256") != classified["structural_sha256"]:
        raise SettlementV2Error(
            f"motion capability recorder defect: {label} records a false raw structural hash"
        )
    instance, process_id = _observation_identity(observation, label)
    pair_id = observation.get("pair_id")
    if not isinstance(pair_id, str) or not pair_id:
        raise SettlementV2Error(
            f"motion capability recorder defect: {label} has no independent-pair id"
        )
    return {
        "label": label,
        "pair_id": pair_id,
        "instance": instance,
        "process_id": process_id,
        "evidence": _observation_evidence(observation, label),
        "samples": samples,
        "layout": layout,
        "settlement": settlement,
        "classification": classified,
    }


def resolve_motion_capability(
    observations: list[dict[str, Any]],
    extended_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve screen-member animation from every valid campaign observation.

    A single measured rect change proves capability.  A raw stationary window
    never disproves it.  When independent raw windows disagree, the stationary
    instance must carry the long corroboration observation required by v2.3.
    """
    if len(observations) < 2:
        raise SettlementV2Error(
            "motion capability resolution requires at least two independent observations"
        )
    raw = [
        _raw_observation(observation, f"observation[{index}]")
        for index, observation in enumerate(observations)
    ]
    identities = [(value["instance"], value["process_id"]) for value in raw]
    if len(set(identities)) < 2:
        raise SettlementV2Error(
            "motion capability resolution requires two independent fresh instances"
        )

    screen_ids = {
        str(value["samples"][0]["payload"].get("screen_id", "")) for value in raw
    }
    if len(screen_ids) != 1 or not next(iter(screen_ids)):
        raise SettlementV2Error(
            "motion capability resolution cannot mix or omit screen identities"
        )
    screen_id = next(iter(screen_ids))
    raw_id_sets = [
        set(value["classification"]["animated_element_ids"]) for value in raw
    ]
    pairs: dict[str, list[tuple[dict[str, Any], set[str]]]] = {}
    for value, measured in zip(raw, raw_id_sets):
        pairs.setdefault(value["pair_id"], []).append((value, measured))
    for pair_id, members in pairs.items():
        if len(members) != 2 or len(
            {(value["instance"], value["process_id"]) for value, _ in members}
        ) != 2:
            raise SettlementV2Error(
                "motion capability resolution requires pair "
                f"'{pair_id}' to contain exactly two fresh instances"
            )

    extended: list[dict[str, Any]] = []
    for index, observation in enumerate(extended_observations):
        label = f"extended_observation[{index}]"
        samples = observation.get("samples")
        if not isinstance(samples, list) or not samples:
            raise SettlementV2Error(
                f"motion capability recorder defect: {label} lacks samples"
            )
        instance, process_id = _observation_identity(observation, label)
        matching_raw = [
            value
            for value in raw
            if (value["instance"], value["process_id"]) == (instance, process_id)
        ]
        if len(matching_raw) != 1:
            raise SettlementV2Error(
                "motion capability corroboration contract: extended observation "
                f"{label} does not resolve one exact stationary instance"
            )
        required_span = max(
            EXTENDED_OBSERVATION_MINIMUM_MILLISECONDS,
            EXTENDED_OBSERVATION_SETTLE_SPAN_MULTIPLIER
            * int(matching_raw[0]["settlement"]["stable_span_milliseconds"]),
        )
        summary = classify_extended_observation(
            samples,
            required_span_milliseconds=required_span,
        )
        extended_screen = str(samples[0]["payload"].get("screen_id", ""))
        if extended_screen != screen_id:
            raise SettlementV2Error(
                "motion capability corroboration contract: extended observation "
                f"changed screen from '{screen_id}' to '{extended_screen}'"
            )
        _assert_non_geometry_stable(
            raw[0]["samples"][0]["payload"], samples[0]["payload"]
        )
        extended.append(
            {
                "label": label,
                "instance": instance,
                "process_id": process_id,
                "evidence": _observation_evidence(observation, label),
                "samples": samples,
                "summary": summary,
            }
        )

    all_measured_sets = [*raw_id_sets]
    all_measured_sets.extend(
        set(value["summary"]["moving_element_ids"]) for value in extended
    )
    resolved_ids = sorted(set().union(*all_measured_sets))
    disputed_ids = sorted(
        set().union(
            *(
                first_ids.symmetric_difference(second_ids)
                for (_, first_ids), (_, second_ids) in pairs.values()
            )
        )
    )
    for pair_id, members in pairs.items():
        pair_disputed = members[0][1].symmetric_difference(members[1][1])
        for element_id in sorted(pair_disputed):
            for value, measured in members:
                if element_id in measured:
                    continue
                corroborations = [
                    item
                    for item in extended
                    if (item["instance"], item["process_id"])
                    == (value["instance"], value["process_id"])
                ]
                if len(corroborations) != 1:
                    raise SettlementV2Error(
                        "motion capability resolution requires extended observation "
                        f"evidence for stationary member '{element_id}' in pair "
                        f"'{pair_id}' on instance '{value['instance']}' PID "
                        f"{value['process_id']}"
                    )

    motion_evidence: list[dict[str, Any]] = []
    for element_id in resolved_ids:
        witnesses: list[dict[str, Any]] = []
        for value in raw:
            events = [
                event
                for event in _motion_events(value["samples"])
                if event["element_id"] == element_id
            ]
            if events:
                witnesses.append(
                    {
                        "kind": "settled_window",
                        "instance": value["instance"],
                        "process_id": value["process_id"],
                        "motion_event_count": len(events),
                        "first_event": copy.deepcopy(events[0]),
                        "evidence": copy.deepcopy(value["evidence"]),
                    }
                )
        for value in extended:
            events = [
                event
                for event in value["summary"]["motion_events"]
                if event["element_id"] == element_id
            ]
            if events:
                witnesses.append(
                    {
                        "kind": "extended_observation",
                        "instance": value["instance"],
                        "process_id": value["process_id"],
                        "motion_event_count": len(events),
                        "first_event": copy.deepcopy(events[0]),
                        "evidence": copy.deepcopy(value["evidence"]),
                    }
                )
        if not witnesses:
            raise SettlementV2Error(
                "motion capability recorder defect: phantom animated classification "
                f"for '{element_id}' has no varying recorded samples"
            )
        motion_evidence.append(
            {"element_id": element_id, "witnesses": witnesses}
        )

    anchor_payload = raw[0]["samples"][0]["payload"]
    anchor_order, _ = _elements_by_id(anchor_payload)
    animated_fraction = len(resolved_ids) / len(anchor_order)
    if animated_fraction > MAXIMUM_ANIMATED_FRACTION:
        raise SettlementV2Error(
            "resolved animated geometry cap exceeded: "
            f"{len(resolved_ids)}/{len(anchor_order)} elements "
            f"({animated_fraction:.1%}) exceeds 30% for '{screen_id}'"
        )

    for value in raw[1:]:
        _assert_non_geometry_stable(
            anchor_payload, value["samples"][0]["payload"]
        )
    expected_structure = structural_layout_bytes(anchor_payload, resolved_ids)
    for value in raw[1:]:
        if structural_layout_bytes(
            value["samples"][0]["payload"], resolved_ids
        ) != expected_structure:
            raise SettlementV2Error(
                "motion capability resolution found cross-instance disagreement "
                "outside resolved animated geometry"
            )
    for value in extended:
        if structural_layout_bytes(
            value["samples"][0]["payload"], resolved_ids
        ) != expected_structure:
            raise SettlementV2Error(
                "motion capability corroboration found disagreement outside "
                "resolved animated geometry"
            )
    for value in raw:
        measured = set(value["classification"]["animated_element_ids"])
        unexpected = measured - set(resolved_ids)
        if unexpected:
            element_id = sorted(unexpected)[0]
            raise SettlementV2Error(
                "future motion drift: member "
                f"'{element_id}' was pinned stationary by the resolved screen contract"
            )

    geometries: dict[str, list[tuple[Any, ...]]] = {
        element_id: [] for element_id in anchor_order
    }
    all_sample_groups = [value["samples"] for value in raw] + [
        value["samples"] for value in extended
    ]
    for samples in all_sample_groups:
        for sample in samples:
            _, indexed = _elements_by_id(sample["payload"])
            for element_id in anchor_order:
                geometries[element_id].append(
                    _geometry_signature(indexed[element_id], element_id)
                )

    resolved_observations: list[dict[str, Any]] = []
    for value in raw:
        first_sample = value["samples"][0]
        layout = _shape_layout(
            first_sample["payload"],
            resolved_ids,
            geometries,
            int(
                first_sample.get(
                    "captured_at_milliseconds",
                    first_sample["elapsed_milliseconds"],
                )
            ),
        )
        settlement = copy.deepcopy(value["settlement"])
        settlement.update(
            {
                "settlement_spec": SETTLEMENT_SPEC,
                "criterion": (
                    "at least 40 consecutive structurally byte-identical samples "
                    "over at least 2 seconds; screen-member motion capability is "
                    "the union of every measured rect change"
                ),
                "raw_window_animated_element_ids": value["classification"][
                    "animated_element_ids"
                ],
                "animated_element_ids": resolved_ids,
                "animated_element_count": len(resolved_ids),
                "animated_fraction": animated_fraction,
                "structural_sha256": canonical_structural_sha256(
                    layout, resolved_ids
                ),
                "motion_envelope_sample_count": len(
                    geometries[resolved_ids[0]]
                )
                if resolved_ids
                else sum(len(samples) for samples in all_sample_groups),
            }
        )
        resolved_observations.append(
            {"layout": layout, "settlement": settlement}
        )

    proof = {
        "rule": "Settlement v2.3 screen-member motion capability",
        "screen_id": screen_id,
        "resolved_animated_element_ids": resolved_ids,
        "disputed_element_ids": disputed_ids,
        "raw_observations": [
            {
                "instance": value["instance"],
                "process_id": value["process_id"],
                "pair_id": value["pair_id"],
                "animated_element_ids": value["classification"][
                    "animated_element_ids"
                ],
                "sample_count": len(value["samples"]),
                "stable_span_milliseconds": value["classification"][
                    "stable_span_milliseconds"
                ],
                "motion_event_count": len(_motion_events(value["samples"])),
                "evidence": copy.deepcopy(value["evidence"]),
            }
            for value in raw
        ],
        "extended_observations": [
            {
                "instance": value["instance"],
                "process_id": value["process_id"],
                **{
                    key: copy.deepcopy(value["summary"][key])
                    for key in (
                        "required_span_milliseconds",
                        "observed_span_milliseconds",
                        "sample_count",
                        "motion_event_count",
                        "moving_element_ids",
                    )
                },
                "evidence": copy.deepcopy(value["evidence"]),
            }
            for value in extended
        ],
        "motion_evidence": motion_evidence,
        "envelope_sample_count": (
            len(geometries[resolved_ids[0]])
            if resolved_ids
            else sum(len(samples) for samples in all_sample_groups)
        ),
    }
    return {"resolution": proof, "observations": resolved_observations}


def validate_resolved_motion_capability(
    resolution: dict[str, Any],
    observations: list[dict[str, Any]],
    extended_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Re-derive a declared v2.3 proof and reject phantom or stale claims."""
    expected = resolve_motion_capability(observations, extended_observations)
    declared_ids = resolution.get("resolved_animated_element_ids")
    expected_ids = expected["resolution"]["resolved_animated_element_ids"]
    if isinstance(declared_ids, list):
        phantom = sorted(set(declared_ids) - set(expected_ids))
        if phantom:
            raise SettlementV2Error(
                "motion capability recorder defect: phantom animated classification "
                f"for '{phantom[0]}' has no varying recorded samples"
            )
        future = sorted(set(expected_ids) - set(declared_ids))
        if future:
            raise SettlementV2Error(
                "future motion drift: member "
                f"'{future[0]}' was pinned stationary by the resolved screen contract"
            )
    if canonical_bytes(resolution) != canonical_bytes(expected["resolution"]):
        difference = _first_difference(expected["resolution"], resolution)
        raise SettlementV2Error(
            "motion capability resolution proof was not machine-derived; "
            f"first difference is '{difference}'"
        )
    return expected


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
        "settlement_spec": SETTLEMENT_SPEC,
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
        encoding = phase.get("payload_encoding")
        if encoding == "structural-element-arrays-v1":
            compact_elements = payload.get("elements")
            if not isinstance(compact_elements, list):
                raise SettlementV2Error(
                    "landed population override: "
                    f"{label} compact phase {index} has no elements"
                )
            expanded_elements: list[dict[str, Any]] = []
            for element_index, compact in enumerate(compact_elements):
                if (
                    not isinstance(compact, list)
                    or len(compact) != len(_COMPACT_POPULATION_ELEMENT_FIELDS)
                ):
                    raise SettlementV2Error(
                        "landed population override: "
                        f"{label} compact phase {index} element "
                        f"{element_index} has the wrong field census"
                    )
                expanded_elements.append(
                    dict(zip(_COMPACT_POPULATION_ELEMENT_FIELDS, compact))
                )
            payload = {
                **copy.deepcopy(payload),
                "elements": expanded_elements,
            }
        elif encoding is not None:
            raise SettlementV2Error(
                "landed population override: "
                f"{label} phase {index} uses unknown payload encoding "
                f"{encoding!r}"
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


def _slugify_element_token(value: Any) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return token or "element"


def _reordinalization_key(element: dict[str, Any]) -> tuple[float, bytes, str]:
    draw_order, element_id = _canonical_element_key(element)
    remainder = {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in {"id", "draw_order"}
        and key not in _ANIMATION_FIXTURE_FIELDS
    }
    return draw_order, canonical_bytes(remainder), element_id


def deterministic_reordinalized_layout(
    layout: dict[str, Any],
    animated_element_ids: Iterable[str] | None = None,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    """Normalize positional art bookkeeping without treating it as identity."""
    if animated_element_ids is None:
        raw_animated = layout.get("animated_element_ids", [])
    else:
        raw_animated = list(animated_element_ids)
    if not isinstance(raw_animated, list) or not all(
        isinstance(value, str) for value in raw_animated
    ):
        raise SettlementV2Error(
            "overlay reordinalization contract: animated ids are not a string list"
        )
    animated = set(raw_animated)
    order, indexed = _elements_by_id(layout)
    if not animated.issubset(indexed):
        raise SettlementV2Error(
            "overlay reordinalization contract: animated member lookup is ambiguous"
        )
    result = copy.deepcopy(layout)
    elements = [copy.deepcopy(indexed[element_id]) for element_id in order]
    elements.sort(key=_reordinalization_key)
    screen_token = _slugify_element_token(layout.get("screen_id", ""))
    counts: Counter[str] = Counter()
    normalized_animated: list[str] = []
    proof: list[dict[str, Any]] = []
    art_order = 0
    for element in elements:
        if element.get("kind") != "art":
            continue
        art_order += 1
        old_id = _element_id(element)
        art_id = element.get("art_id")
        if not isinstance(art_id, str) or not art_id:
            raise SettlementV2Error(
                "overlay reordinalization contract: art member "
                f"'{old_id}' has no art_id"
            )
        base = f"{screen_token}.art.{_slugify_element_token(art_id)}"
        counts[base] += 1
        new_id = f"{base}.{counts[base]}"
        old_draw_order = element.get("draw_order")
        element["id"] = new_id
        element["draw_order"] = art_order
        if old_id in animated:
            normalized_animated.append(new_id)
        proof.append(
            {
                "captured_element_id": old_id,
                "captured_draw_order": old_draw_order,
                "normalized_element_id": new_id,
                "normalized_draw_order": art_order,
            }
        )
    result["elements"] = elements
    if "animated_element_ids" in result:
        result["animated_element_ids"] = sorted(normalized_animated)
    return result, sorted(normalized_animated), proof


def assert_deterministic_reordinalization(
    captured_layout: dict[str, Any],
    captured_animated_element_ids: Iterable[str],
    normalized_layout: dict[str, Any],
    normalized_animated_element_ids: list[str],
    proof: list[dict[str, Any]],
) -> None:
    """Prove that normalized ordinals are the pure positional function we claim."""
    captured_animated = set(captured_animated_element_ids)
    captured_order, captured_by_id = _elements_by_id(captured_layout)
    expected_elements = [
        copy.deepcopy(captured_by_id[element_id]) for element_id in captured_order
    ]
    expected_elements.sort(key=_reordinalization_key)
    _, normalized_by_id = _elements_by_id(normalized_layout)
    expected_proof: list[dict[str, Any]] = []
    expected_animated: list[str] = []
    counts: Counter[str] = Counter()
    art_order = 0
    screen_token = _slugify_element_token(captured_layout.get("screen_id", ""))
    for element in expected_elements:
        if element.get("kind") != "art":
            continue
        art_order += 1
        captured_id = _element_id(element)
        art_id = element.get("art_id")
        if not isinstance(art_id, str) or not art_id:
            raise SettlementV2Error(
                "overlay reordinalization contract: captured art member "
                f"'{captured_id}' has no art_id"
            )
        base = f"{screen_token}.art.{_slugify_element_token(art_id)}"
        counts[base] += 1
        normalized_id = f"{base}.{counts[base]}"
        normalized = normalized_by_id.get(normalized_id)
        if normalized is None or normalized.get("draw_order") != art_order:
            raise SettlementV2Error(
                "landed overlay override: deterministic reordinalization produced "
                f"a noncanonical survivor ordinal for '{captured_id}'"
            )
        expected_payload = copy.deepcopy(element)
        expected_payload["id"] = normalized_id
        expected_payload["draw_order"] = art_order
        if canonical_bytes(normalized) != canonical_bytes(expected_payload):
            raise SettlementV2Error(
                "landed overlay override: deterministic reordinalization changed "
                f"a survivor field outside positional bookkeeping for '{captured_id}'"
            )
        if captured_id in captured_animated:
            expected_animated.append(normalized_id)
        expected_proof.append(
            {
                "captured_element_id": captured_id,
                "captured_draw_order": element.get("draw_order"),
                "normalized_element_id": normalized_id,
                "normalized_draw_order": art_order,
            }
        )
    if proof != expected_proof or sorted(normalized_animated_element_ids) != sorted(
        expected_animated
    ):
        raise SettlementV2Error(
            "landed overlay override: deterministic reordinalization proof does "
            "not describe its canonical survivor ordinals"
        )


def _subtract_overlay_semantic_multiset(
    landed_layout: dict[str, Any],
    overlay_reference: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    required = validate_overlay_reference(overlay_reference)
    _, landed_by_id = _elements_by_id(landed_layout)
    groups: dict[bytes, list[dict[str, Any]]] = {}
    for element in landed_by_id.values():
        if element.get("kind") != "art":
            continue
        signature = canonical_bytes(_overlay_semantic_payload(element))
        groups.setdefault(signature, []).append(element)
    removed_ids: set[str] = set()
    removed: list[dict[str, Any]] = []
    for signature, count in required.items():
        candidates = sorted(groups.get(signature, []), key=_reordinalization_key)
        if len(candidates) < count:
            raise SettlementV2Error(
                "landed overlay override: semantic-multiset difference does "
                "not contain the complete overlay reference"
            )
        if len(candidates) > count:
            raise SettlementV2Error(
                "landed overlay override: semantic-multiset subtraction is "
                "ambiguous for duplicate draw semantics"
            )
        for element in candidates:
            removed_ids.add(_element_id(element))
            removed.append(copy.deepcopy(element))
    survivors = [
        copy.deepcopy(element)
        for element_id, element in landed_by_id.items()
        if element_id not in removed_ids
    ]
    if len(removed) != sum(required.values()):
        raise SettlementV2Error(
            "landed overlay override: semantic-multiset subtraction removed "
            "the wrong draw census"
        )
    return survivors, _canonical_elements(removed)


def build_overlay_contamination_override(
    landed_layout: dict[str, Any],
    primary_layout: dict[str, Any],
    confirmation_layout: dict[str, Any],
    primary_trace: dict[str, Any],
    confirmation_trace: dict[str, Any],
    overlay_reference: dict[str, Any],
) -> dict[str, Any]:
    """Derive the narrow Settlement v2.4 beta-overlay correction."""
    assert_canonical_structure_matches(primary_layout, confirmation_layout)
    reference_counter = validate_overlay_reference(overlay_reference)
    primary_ids = primary_layout.get("animated_element_ids", [])
    confirmation_ids = confirmation_layout.get("animated_element_ids", [])
    differences = structural_differences(
        landed_layout,
        primary_layout,
        primary_ids,
    )
    if not differences:
        raise SettlementV2Error(
            "landed overlay override: candidate already matches landed structure"
        )
    generation_differences = [
        difference
        for difference in differences
        if difference["kind"] == "layout_field"
        and difference.get("field") == "generation"
    ]
    if len(generation_differences) != 1:
        raise SettlementV2Error(
            "landed overlay override: exactly one generation difference is required"
        )

    primary_phases, primary_settled, primary_phase_entries = _trace_payloads(
        primary_trace,
        "primary",
    )
    confirmation_phases, confirmation_settled, confirmation_phase_entries = (
        _trace_payloads(confirmation_trace, "confirmation")
    )
    absence_payloads = (
        *primary_phases,
        *confirmation_phases,
        *primary_settled,
        *confirmation_settled,
    )
    if any(
        overlay_semantic_multiset_is_present(payload, overlay_reference)
        for payload in absence_payloads
    ):
        raise SettlementV2Error(
            "landed overlay override: complete overlay semantic multiset "
            "appears in a fresh population phase or settled window"
        )

    generation_difference = generation_differences[0]
    primary_generation_witnesses = _population_witness_indexes(
        generation_difference,
        primary_phases,
    )
    confirmation_generation_witnesses = _population_witness_indexes(
        generation_difference,
        confirmation_phases,
    )
    if not primary_generation_witnesses or not confirmation_generation_witnesses:
        raise SettlementV2Error(
            "landed overlay override: generation difference lacks "
            "two-instance population witnesses"
        )

    survivors, removed = _subtract_overlay_semantic_multiset(
        landed_layout,
        overlay_reference,
    )
    corrected = copy.deepcopy(landed_layout)
    corrected["generation"] = primary_layout.get("generation")
    corrected["elements"] = survivors
    normalized_corrected, corrected_ids, corrected_reordinalization = (
        deterministic_reordinalized_layout(corrected, primary_ids)
    )
    normalized_primary, normalized_primary_ids, primary_reordinalization = (
        deterministic_reordinalized_layout(primary_layout, primary_ids)
    )
    normalized_confirmation, normalized_confirmation_ids, confirmation_reordinalization = (
        deterministic_reordinalized_layout(confirmation_layout, confirmation_ids)
    )
    for captured, captured_ids, normalized, normalized_ids, proof in (
        (
            corrected,
            primary_ids,
            normalized_corrected,
            corrected_ids,
            corrected_reordinalization,
        ),
        (
            primary_layout,
            primary_ids,
            normalized_primary,
            normalized_primary_ids,
            primary_reordinalization,
        ),
        (
            confirmation_layout,
            confirmation_ids,
            normalized_confirmation,
            normalized_confirmation_ids,
            confirmation_reordinalization,
        ),
    ):
        assert_deterministic_reordinalization(
            captured,
            captured_ids,
            normalized,
            normalized_ids,
            proof,
        )
    corrected_bytes = structural_layout_bytes(
        normalized_corrected,
        corrected_ids,
    )
    primary_bytes = structural_layout_bytes(
        normalized_primary,
        normalized_primary_ids,
    )
    confirmation_bytes = structural_layout_bytes(
        normalized_confirmation,
        normalized_confirmation_ids,
    )
    if corrected_bytes != primary_bytes:
        difference = _first_difference(
            canonical_structural_layout(
                normalized_primary,
                normalized_primary_ids,
            ),
            canonical_structural_layout(
                normalized_corrected,
                corrected_ids,
            ),
        )
        raise SettlementV2Error(
            "landed overlay override: semantic-multiset difference leaves "
            f"residual draws or fields after deterministic reordinalization at '{difference}'"
        )
    if primary_bytes != confirmation_bytes:
        raise SettlementV2Error(
            "landed overlay override: independent settled instances disagree "
            "after deterministic reordinalization"
        )

    validate_declared_settlement(
        primary_layout,
        primary_trace["settled_window_samples"],
    )
    validate_declared_settlement(
        confirmation_layout,
        confirmation_trace["settled_window_samples"],
    )
    _, landed_by_id = _elements_by_id(landed_layout)
    _, settled_by_id = _elements_by_id(primary_layout)
    multiset_entries = overlay_reference["overlay_semantic_draw_multiset"]
    return {
        "rule": "Settlement v2.4 landed beta-overlay semantic-multiset override",
        "canonical_order": "draw_order_then_remaining_fields",
        "ordinal_identity": "screen_local_positional_bookkeeping",
        "landed_generation": landed_layout.get("generation"),
        "landed_element_count": len(landed_by_id),
        "settled_generation": primary_layout.get("generation"),
        "settled_element_count": len(settled_by_id),
        "canonical_structural_sha256": canonical_structural_sha256(
            primary_layout,
            primary_ids,
        ),
        "confirmation_canonical_structural_sha256": (
            canonical_structural_sha256(confirmation_layout, confirmation_ids)
        ),
        "overlay_semantic_draw_count": sum(reference_counter.values()),
        "overlay_semantic_multiset_sha256": sha256_json(multiset_entries),
        "removed_overlay_draws": [
            {
                "landed_element_id": _element_id(element),
                "landed_draw_order": element.get("draw_order"),
                "semantic_draw_sha256": sha256_json(
                    _overlay_semantic_payload(element)
                ),
            }
            for element in removed
        ],
        "overlay_absence": {
            "primary_population_phases": len(primary_phases),
            "confirmation_population_phases": len(confirmation_phases),
            "primary_settled_samples": len(primary_settled),
            "confirmation_settled_samples": len(confirmation_settled),
        },
        "generation_population_witnesses": {
            "primary_phase_indexes": primary_generation_witnesses,
            "confirmation_phase_indexes": confirmation_generation_witnesses,
        },
        "deterministic_reordinalization": {
            "algorithm": "art_draw_order_then_remaining_fields_per_art_id",
            "corrected_landed": corrected_reordinalization,
            "settled_primary": primary_reordinalization,
            "settled_confirmation": confirmation_reordinalization,
        },
        "reordinalized_structural_sha256": hashlib.sha256(
            primary_bytes
        ).hexdigest(),
        "structural_differences": copy.deepcopy(differences),
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
    _write_json(output_path, classify_ambient_window(samples))


def _find_command(input_path: Path, output_path: Path) -> None:
    samples = _read_json(input_path)
    if not isinstance(samples, list):
        raise SettlementV2Error("classifier input must be a JSON sample list")
    _write_json(output_path, find_ambient_settled_window(samples))


def _classify_pair_command(input_path: Path, output_path: Path) -> None:
    value = _read_json(input_path)
    if not isinstance(value, dict) or not isinstance(
        value.get("observations"), list
    ):
        raise SettlementV2Error(
            "ambient pair classifier input must contain an observations list"
        )
    _write_json(
        output_path,
        resolve_ambient_lifecycle(value["observations"]),
    )


def _classify_extended_command(
    input_path: Path, output_path: Path, required_span_milliseconds: int
) -> None:
    samples = _read_json(input_path)
    if not isinstance(samples, list):
        raise SettlementV2Error(
            "extended observation classifier input must be a JSON sample list"
        )
    _write_json(
        output_path,
        classify_ambient_extended_observation(
            samples,
            required_span_milliseconds=required_span_milliseconds,
        ),
    )


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


def _check_overlay_command(layout_path: Path, reference_path: Path) -> None:
    layout = _read_json(layout_path)
    reference = _read_json(reference_path)
    if not isinstance(layout, dict):
        raise SettlementV2Error("overlay hygiene layout input must be an object")
    if not isinstance(reference, dict):
        raise SettlementV2Error("overlay hygiene reference input must be an object")
    if reference.get("schema") == OVERLAY_REFERENCE_SCHEMA_V25:
        assert_overlay_hygiene_v25(layout, reference)
    else:
        assert_overlay_hygiene(layout, reference)


def _check_overlay_samples_command(
    input_path: Path, reference_path: Path
) -> None:
    samples = _read_json(input_path)
    reference = _read_json(reference_path)
    if not isinstance(samples, list):
        raise SettlementV2Error("overlay hygiene sample input must be a list")
    if not isinstance(reference, dict):
        raise SettlementV2Error("overlay hygiene reference input must be an object")
    if reference.get("schema") == OVERLAY_REFERENCE_SCHEMA_V25:
        if not samples:
            raise SettlementV2Error(
                "overlay hygiene contract: sample sweep reached no capture payloads"
            )
        for index, sample in enumerate(samples):
            payload = sample.get("payload") if isinstance(sample, dict) else None
            if not isinstance(payload, dict):
                raise SettlementV2Error(
                    f"overlay hygiene contract: sample {index} has no semantic payload"
                )
            try:
                assert_overlay_hygiene_v25(payload, reference)
            except OverlayV25Error as error:
                raise SettlementV2Error(
                    f"overlay hygiene contract: sample {index} is contaminated: {error}"
                ) from error
    else:
        assert_overlay_sample_hygiene(samples, reference)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    classify_parser = subparsers.add_parser("classify")
    classify_parser.add_argument("--input", type=Path, required=True)
    classify_parser.add_argument("--output", type=Path, required=True)
    find_parser = subparsers.add_parser("find")
    find_parser.add_argument("--input", type=Path, required=True)
    find_parser.add_argument("--output", type=Path, required=True)
    pair_parser = subparsers.add_parser("classify-pair")
    pair_parser.add_argument("--input", type=Path, required=True)
    pair_parser.add_argument("--output", type=Path, required=True)
    extended_parser = subparsers.add_parser("classify-extended")
    extended_parser.add_argument("--input", type=Path, required=True)
    extended_parser.add_argument("--output", type=Path, required=True)
    extended_parser.add_argument(
        "--required-span-milliseconds", type=int, required=True
    )
    summary_parser = subparsers.add_parser("summarize-layout")
    summary_parser.add_argument("--input", type=Path, required=True)
    summary_parser.add_argument("--output", type=Path, required=True)
    overlay_parser = subparsers.add_parser("check-overlay")
    overlay_parser.add_argument("--layout", type=Path, required=True)
    overlay_parser.add_argument("--reference", type=Path, required=True)
    overlay_samples_parser = subparsers.add_parser("check-overlay-samples")
    overlay_samples_parser.add_argument("--input", type=Path, required=True)
    overlay_samples_parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "classify":
            _classify_command(args.input, args.output)
        elif args.command == "find":
            _find_command(args.input, args.output)
        elif args.command == "classify-pair":
            _classify_pair_command(args.input, args.output)
        elif args.command == "classify-extended":
            _classify_extended_command(
                args.input,
                args.output,
                args.required_span_milliseconds,
            )
        elif args.command == "summarize-layout":
            _summarize_layout_command(args.input, args.output)
        elif args.command == "check-overlay":
            _check_overlay_command(args.layout, args.reference)
        elif args.command == "check-overlay-samples":
            _check_overlay_samples_command(args.input, args.reference)
    except (SettlementV2Error, AmbientLifecycleError, OverlayV25Error) as error:
        parser.exit(2, f"STOP: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
