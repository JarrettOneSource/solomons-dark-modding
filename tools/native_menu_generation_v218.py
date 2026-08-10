#!/usr/bin/env python3
"""Settlement v2.18 path-local generation metadata contracts."""

from __future__ import annotations

import copy
import json
import math
from collections import Counter
from typing import Any


SETTLEMENT_SPEC = "2.18"
DISABLED_GENERATION_STOP = (
    "landed-vs-settled generation changed without an authorized differing member"
)
WINDOW_GENERATION_STOP = (
    "Settlement v2.18 path-local generation changed within a settled window"
)
SEMANTIC_MIRROR_STOP = (
    "Settlement v2.18 semantic generation is not the layout-generation mirror"
)
PAIRED_GENERATION_STOP = (
    "Settlement v2.18 paired instances disagree on path-local generation metadata"
)
RECORDED_GENERATION_STOP = (
    "Settlement v2.18 fixture generation is not its measured path-local value"
)
CORE_GENERATION_STOP = (
    "Settlement v2.18 generation exclusion requires an exact semantic core and relative sequence"
)
ADDITIONAL_FIELD_STOP = (
    "Settlement v2.18 generation exclusion found another differing field"
)
BOUND_ENDPOINT_STOP = (
    "Settlement v2.18 generation exclusion found a nonmatching bound endpoint"
)


class NativeMenuGenerationV218Error(RuntimeError):
    """One exact v2.18 generation-metadata precondition is false."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def semantic_member(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in {"id", "draw_order", "draw_order_semantics"}
    }


def _elements(layout: dict[str, Any], label: str) -> list[dict[str, Any]]:
    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements or not all(
        isinstance(element, dict) for element in elements
    ):
        raise NativeMenuGenerationV218Error(
            f"{CORE_GENERATION_STOP}: {label} has no real member census"
        )
    return elements


def _draw_order(element: dict[str, Any], label: str) -> float:
    value = element.get("draw_order")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise NativeMenuGenerationV218Error(
            f"{CORE_GENERATION_STOP}: {label} member has no finite draw order"
        )
    return float(value)


def semantic_core(layout: dict[str, Any], label: str) -> dict[str, Any]:
    elements = _elements(layout, label)
    ordered = sorted(
        elements,
        key=lambda element: (
            _draw_order(element, label),
            canonical_bytes(semantic_member(element)),
            str(element.get("id", "")),
        ),
    )
    signatures = [canonical_bytes(semantic_member(element)) for element in ordered]
    return {
        "screen_id": layout.get("screen_id"),
        "screen_title": layout.get("screen_title"),
        "semantic_multiset": Counter(signatures),
        "relative_sequence": signatures,
    }


def compare_semantic_cores(
    expected: dict[str, Any], observed: dict[str, Any], *, label: str
) -> dict[str, Any]:
    expected_core = semantic_core(expected, f"{label} expected")
    observed_core = semantic_core(observed, f"{label} observed")
    differing_fields = sorted(
        field
        for field in ("screen_id", "screen_title")
        if expected_core[field] != observed_core[field]
    )
    multiset_equal = (
        expected_core["semantic_multiset"] == observed_core["semantic_multiset"]
    )
    sequence_equal = (
        expected_core["relative_sequence"] == observed_core["relative_sequence"]
    )
    return {
        "label": label,
        "differing_fields": differing_fields,
        "semantic_multiset_equal": multiset_equal,
        "relative_sequence_equal": sequence_equal,
        "zero_residual": multiset_equal,
        "exact": not differing_fields and multiset_equal and sequence_equal,
        "member_count": len(expected_core["relative_sequence"]),
    }


def require_semantic_core_identity(
    expected: dict[str, Any], observed: dict[str, Any], *, label: str
) -> dict[str, Any]:
    comparison = compare_semantic_cores(expected, observed, label=label)
    if comparison["differing_fields"]:
        raise NativeMenuGenerationV218Error(
            f"{ADDITIONAL_FIELD_STOP}: {comparison['differing_fields']}"
        )
    if (
        not comparison["semantic_multiset_equal"]
        or not comparison["relative_sequence_equal"]
        or not comparison["zero_residual"]
    ):
        raise NativeMenuGenerationV218Error(CORE_GENERATION_STOP)
    return comparison


def _sample_clock(samples: list[dict[str, Any]], label: str) -> int:
    if len(samples) < 40:
        raise NativeMenuGenerationV218Error(
            f"{WINDOW_GENERATION_STOP}: {label} has fewer than 40 samples"
        )
    elapsed: list[int] = []
    for sample in samples:
        value = sample.get("elapsed_milliseconds")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise NativeMenuGenerationV218Error(
                f"{WINDOW_GENERATION_STOP}: {label} has no numeric sample clock"
            )
        elapsed.append(int(value))
    if elapsed != sorted(elapsed) or len(set(elapsed)) != len(elapsed):
        raise NativeMenuGenerationV218Error(
            f"{WINDOW_GENERATION_STOP}: {label} sample clock is not monotonic"
        )
    span = elapsed[-1] - elapsed[0]
    if span < 2_000:
        raise NativeMenuGenerationV218Error(
            f"{WINDOW_GENERATION_STOP}: {label} spans less than two seconds"
        )
    return span


def measure_generation_window(
    samples: list[dict[str, Any]], label: str
) -> dict[str, Any]:
    span = _sample_clock(samples, label)
    layout_generations: set[int] = set()
    semantic_generations: set[int] = set()
    for sample in samples:
        payload = sample.get("payload")
        layout_generation = payload.get("generation") if isinstance(payload, dict) else None
        semantic_generation = sample.get("semantic_generation")
        if (
            isinstance(layout_generation, bool)
            or not isinstance(layout_generation, int)
            or isinstance(semantic_generation, bool)
            or not isinstance(semantic_generation, int)
        ):
            raise NativeMenuGenerationV218Error(
                f"{SEMANTIC_MIRROR_STOP}: {label} has no integer generation pair"
            )
        if semantic_generation != layout_generation:
            raise NativeMenuGenerationV218Error(
                f"{SEMANTIC_MIRROR_STOP}: {label} records {semantic_generation} != {layout_generation}"
            )
        layout_generations.add(layout_generation)
        semantic_generations.add(semantic_generation)
    if len(layout_generations) != 1 or len(semantic_generations) != 1:
        raise NativeMenuGenerationV218Error(
            f"{WINDOW_GENERATION_STOP}: {label} records multiple generation values"
        )
    generation = next(iter(layout_generations))
    return {
        "generation": generation,
        "semantic_generation": generation,
        "sample_count": len(samples),
        "stable_span_milliseconds": span,
        "window_constant": True,
        "semantic_mirror": True,
    }


def validate_paired_route_generation(
    primary_samples: list[dict[str, Any]],
    confirmation_samples: list[dict[str, Any]],
    recorded_generation: Any,
    *,
    label: str,
) -> dict[str, Any]:
    primary = measure_generation_window(primary_samples, f"{label} primary")
    confirmation = measure_generation_window(
        confirmation_samples, f"{label} confirmation"
    )
    if primary["generation"] != confirmation["generation"]:
        raise NativeMenuGenerationV218Error(
            f"{PAIRED_GENERATION_STOP}: {label} records "
            f"{primary['generation']} != {confirmation['generation']}"
        )
    if (
        isinstance(recorded_generation, bool)
        or not isinstance(recorded_generation, int)
        or recorded_generation != primary["generation"]
    ):
        raise NativeMenuGenerationV218Error(
            f"{RECORDED_GENERATION_STOP}: {label} fixture records "
            f"{recorded_generation!r}, measured {primary['generation']}"
        )
    return {
        "settlement_spec": SETTLEMENT_SPEC,
        "field_scope": ["generation", "semantic_generation"],
        "recorded_generation": recorded_generation,
        "primary": primary,
        "confirmation": confirmation,
        "paired_same_route": True,
    }


def authorize_cross_path_generation(
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    paired_generation: dict[str, Any],
    bound_endpoints: list[dict[str, Any]],
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    landed_generation = landed_layout.get("generation")
    settled_generation = settled_layout.get("generation")
    if landed_generation == settled_generation:
        raise NativeMenuGenerationV218Error(
            "Settlement v2.18 generation exclusion was invoked without a generation difference"
        )
    if not enabled:
        raise NativeMenuGenerationV218Error(DISABLED_GENERATION_STOP)
    comparison = require_semantic_core_identity(
        landed_layout, settled_layout, label="landed-vs-settled"
    )
    if (
        paired_generation.get("settlement_spec") != SETTLEMENT_SPEC
        or paired_generation.get("field_scope")
        != ["generation", "semantic_generation"]
        or paired_generation.get("recorded_generation") != settled_generation
        or paired_generation.get("paired_same_route") is not True
        or paired_generation.get("primary", {}).get("generation")
        != settled_generation
        or paired_generation.get("confirmation", {}).get("generation")
        != settled_generation
    ):
        raise NativeMenuGenerationV218Error(PAIRED_GENERATION_STOP)
    if not isinstance(bound_endpoints, list) or not bound_endpoints:
        raise NativeMenuGenerationV218Error(BOUND_ENDPOINT_STOP)
    for endpoint in bound_endpoints:
        if (
            not isinstance(endpoint, dict)
            or endpoint.get("exact") is not True
            or endpoint.get("semantic_multiset_equal") is not True
            or endpoint.get("relative_sequence_equal") is not True
            or endpoint.get("zero_residual") is not True
        ):
            raise NativeMenuGenerationV218Error(BOUND_ENDPOINT_STOP)
    return {
        "schema": "solomon-dark-native-menu-path-local-generation-v218",
        "settlement_spec": SETTLEMENT_SPEC,
        "field_scope": ["generation", "semantic_generation"],
        "reason": "absolute_generation_is_capture_path_local_nonvisual_bookkeeping",
        "landed_generation": landed_generation,
        "settled_generation": settled_generation,
        "semantic_core": comparison,
        "paired_generation": copy.deepcopy(paired_generation),
        "bound_endpoint_count": len(bound_endpoints),
        "bound_endpoints": copy.deepcopy(bound_endpoints),
        "no_other_field_excluded": True,
    }
