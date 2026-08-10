#!/usr/bin/env python3
"""Settlement v2.19 instance-local generation and pair-core contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from typing import Any

if __package__:
    from .native_menu_generation_v218 import (
        ADDITIONAL_FIELD_STOP,
        BOUND_ENDPOINT_STOP,
        CORE_GENERATION_STOP,
        DISABLED_GENERATION_STOP,
        RECORDED_GENERATION_STOP,
        NativeMenuGenerationV218Error,
        measure_generation_window,
        require_semantic_core_identity,
    )
else:
    from native_menu_generation_v218 import (  # type: ignore[no-redef]
        ADDITIONAL_FIELD_STOP,
        BOUND_ENDPOINT_STOP,
        CORE_GENERATION_STOP,
        DISABLED_GENERATION_STOP,
        RECORDED_GENERATION_STOP,
        NativeMenuGenerationV218Error,
        measure_generation_window,
        require_semantic_core_identity,
    )


SETTLEMENT_SPEC = "2.19"
PAIR_CORE_STOP = (
    "Settlement v2.19 generation exclusion requires a machine-proven exact "
    "paired semantic core and relative sequence"
)
PAIR_RECEIPT_STOP = (
    "Settlement v2.19 paired-core receipt does not derive from both settled traces"
)
V218_DISABLED_CORPUS_STOP = (
    "Settlement v2.18 paired instances disagree on path-local generation metadata: "
    "edge dark_cloud_login_to_browser before; standalone pairs 10/30 disagree; "
    "navigation layout endpoints 24/76 disagree"
)


class NativeMenuGenerationV219Error(RuntimeError):
    """One exact v2.19 generation/core precondition is false."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


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
        raise NativeMenuGenerationV219Error(
            f"{PAIR_CORE_STOP}: {label} reached no structural members"
        )
    return elements


def _draw_order(element: dict[str, Any], label: str) -> float:
    value = element.get("draw_order")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise NativeMenuGenerationV219Error(
            f"{PAIR_CORE_STOP}: {label} member has no finite draw order"
        )
    return float(value)


def _ordered_elements(layout: dict[str, Any], label: str) -> list[dict[str, Any]]:
    return sorted(
        _elements(layout, label),
        key=lambda element: (
            _draw_order(element, label),
            canonical_bytes(semantic_member(element)),
            str(element.get("id", "")),
        ),
    )


def _counter_entries(counter: Counter[bytes]) -> list[dict[str, Any]]:
    return [
        {
            "semantic_payload": json.loads(signature.decode("utf-8")),
            "count": count,
        }
        for signature, count in sorted(counter.items())
        if count
    ]


def _expected_core(layout: dict[str, Any], label: str) -> dict[str, Any]:
    ordered = _ordered_elements(layout, label)
    sequence = [canonical_bytes(semantic_member(element)) for element in ordered]
    counter = Counter(sequence)
    return {
        "sequence": sequence,
        "counter": counter,
        "member_count": len(sequence),
        "member_multiset_sha256": sha256_json(_counter_entries(counter)),
        "relative_sequence_sha256": sha256_json(
            [json.loads(signature.decode("utf-8")) for signature in sequence]
        ),
    }


def _project_sample_core(
    sample: dict[str, Any],
    expected_layout: dict[str, Any],
    expected: dict[str, Any],
    *,
    label: str,
) -> list[bytes]:
    payload = sample.get("payload")
    if not isinstance(payload, dict):
        raise NativeMenuGenerationV219Error(
            f"{PAIR_CORE_STOP}: {label} sample has no payload"
        )
    for field in ("screen_id", "screen_title", "capture_method"):
        if payload.get(field) != expected_layout.get(field):
            raise NativeMenuGenerationV219Error(
                f"{PAIR_CORE_STOP}: {label} differs in non-generation field '{field}'"
            )
    if sample.get("semantic_surface") != payload.get("screen_id"):
        raise NativeMenuGenerationV219Error(
            f"{PAIR_CORE_STOP}: {label} semantic surface differs from its payload"
        )
    remaining = expected["counter"].copy()
    sequence: list[bytes] = []
    for element in _ordered_elements(payload, label):
        signature = canonical_bytes(semantic_member(element))
        if remaining[signature] <= 0:
            continue
        sequence.append(signature)
        remaining[signature] -= 1
    if any(remaining.values()) or sequence != expected["sequence"]:
        raise NativeMenuGenerationV219Error(PAIR_CORE_STOP)
    return sequence


def _measure_instance_core(
    samples: list[dict[str, Any]],
    expected_layout: dict[str, Any],
    expected: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    generation = measure_generation_window(samples, label)
    sequences = [
        _project_sample_core(
            sample,
            expected_layout,
            expected,
            label=f"{label} sample {index}",
        )
        for index, sample in enumerate(samples)
    ]
    if not sequences:
        raise NativeMenuGenerationV219Error(
            f"{PAIR_CORE_STOP}: {label} reached no real samples"
        )
    sequence_hashes = {
        sha256_json(
            [json.loads(signature.decode("utf-8")) for signature in sequence]
        )
        for sequence in sequences
    }
    if sequence_hashes != {expected["relative_sequence_sha256"]}:
        raise NativeMenuGenerationV219Error(PAIR_CORE_STOP)
    return {
        **generation,
        "member_count": expected["member_count"],
        "member_multiset_sha256": expected["member_multiset_sha256"],
        "relative_sequence_sha256": expected["relative_sequence_sha256"],
        "all_samples_project_exactly": True,
    }


def derive_pair_core_equality(
    primary_samples: list[dict[str, Any]],
    confirmation_samples: list[dict[str, Any]],
    expected_layout: dict[str, Any],
    *,
    label: str,
    bound_endpoints: list[str],
    bound_endpoint_census_complete: bool,
) -> dict[str, Any]:
    if not isinstance(bound_endpoints, list) or not all(
        isinstance(value, str) and value for value in bound_endpoints
    ):
        raise NativeMenuGenerationV219Error(BOUND_ENDPOINT_STOP)
    if len(bound_endpoints) != len(set(bound_endpoints)):
        raise NativeMenuGenerationV219Error(BOUND_ENDPOINT_STOP)
    if bound_endpoint_census_complete is not True:
        raise NativeMenuGenerationV219Error(BOUND_ENDPOINT_STOP)
    expected = _expected_core(expected_layout, f"{label} expected core")
    try:
        primary = _measure_instance_core(
            primary_samples,
            expected_layout,
            expected,
            label=f"{label} primary",
        )
        confirmation = _measure_instance_core(
            confirmation_samples,
            expected_layout,
            expected,
            label=f"{label} confirmation",
        )
    except NativeMenuGenerationV218Error as error:
        raise NativeMenuGenerationV219Error(str(error)) from error
    core_equal = (
        primary["member_multiset_sha256"]
        == confirmation["member_multiset_sha256"]
        == expected["member_multiset_sha256"]
        and primary["relative_sequence_sha256"]
        == confirmation["relative_sequence_sha256"]
        == expected["relative_sequence_sha256"]
    )
    if not core_equal:
        raise NativeMenuGenerationV219Error(PAIR_CORE_STOP)
    return {
        "schema": "solomon-dark-native-menu-paired-core-equality-v219",
        "settlement_spec": SETTLEMENT_SPEC,
        "label": label,
        "expected_core": {
            "member_count": expected["member_count"],
            "member_multiset_sha256": expected["member_multiset_sha256"],
            "relative_sequence_sha256": expected["relative_sequence_sha256"],
        },
        "primary": primary,
        "confirmation": confirmation,
        "generation_values_may_differ": True,
        "generation_excluded_field_scope": [
            "generation",
            "semantic_generation",
        ],
        "core_equal": True,
        "zero_residual": True,
        "bound_endpoints": copy.deepcopy(bound_endpoints),
        "bound_endpoint_census_complete": True,
        "verdict": "exact_core_generation_instance_local",
    }


def validate_instance_local_generation_pair(
    primary_samples: list[dict[str, Any]],
    confirmation_samples: list[dict[str, Any]],
    recorded_generation: Any,
    paired_core_equality: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    try:
        primary = measure_generation_window(primary_samples, f"{label} primary")
        confirmation = measure_generation_window(
            confirmation_samples, f"{label} confirmation"
        )
    except NativeMenuGenerationV218Error as error:
        raise NativeMenuGenerationV219Error(str(error)) from error
    if (
        isinstance(recorded_generation, bool)
        or not isinstance(recorded_generation, int)
        or recorded_generation != primary["generation"]
    ):
        raise NativeMenuGenerationV219Error(
            f"{RECORDED_GENERATION_STOP}: {label} fixture records "
            f"{recorded_generation!r}, measured {primary['generation']}"
        )
    if (
        not isinstance(paired_core_equality, dict)
        or paired_core_equality.get("schema")
        != "solomon-dark-native-menu-paired-core-equality-v219"
        or paired_core_equality.get("settlement_spec") != SETTLEMENT_SPEC
        or paired_core_equality.get("core_equal") is not True
        or paired_core_equality.get("zero_residual") is not True
        or paired_core_equality.get("bound_endpoint_census_complete") is not True
        or paired_core_equality.get("primary", {}).get("generation")
        != primary["generation"]
        or paired_core_equality.get("confirmation", {}).get("generation")
        != confirmation["generation"]
    ):
        raise NativeMenuGenerationV219Error(PAIR_RECEIPT_STOP)
    expected = paired_core_equality.get("expected_core", {})
    if (
        paired_core_equality.get("primary", {}).get("member_multiset_sha256")
        != paired_core_equality.get("confirmation", {}).get(
            "member_multiset_sha256"
        )
        or paired_core_equality.get("primary", {}).get(
            "relative_sequence_sha256"
        )
        != paired_core_equality.get("confirmation", {}).get(
            "relative_sequence_sha256"
        )
        or paired_core_equality.get("primary", {}).get("member_multiset_sha256")
        != expected.get("member_multiset_sha256")
        or paired_core_equality.get("primary", {}).get(
            "relative_sequence_sha256"
        )
        != expected.get("relative_sequence_sha256")
    ):
        raise NativeMenuGenerationV219Error(PAIR_CORE_STOP)
    return {
        "settlement_spec": SETTLEMENT_SPEC,
        "field_scope": ["generation", "semantic_generation"],
        "recorded_generation": recorded_generation,
        "primary": primary,
        "confirmation": confirmation,
        "paired_same_route_generation_required": False,
        "paired_core_equality": copy.deepcopy(paired_core_equality),
        "instance_local_generation": True,
    }


def authorize_cross_path_generation(
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    instance_local_generation: dict[str, Any],
    bound_endpoints: list[dict[str, Any]],
    *,
    enabled: bool = True,
    allow_empty_bound_endpoints: bool = False,
) -> dict[str, Any]:
    landed_generation = landed_layout.get("generation")
    settled_generation = settled_layout.get("generation")
    if landed_generation == settled_generation:
        raise NativeMenuGenerationV219Error(
            "Settlement v2.19 generation exclusion was invoked without a generation difference"
        )
    if not enabled:
        raise NativeMenuGenerationV219Error(DISABLED_GENERATION_STOP)
    try:
        comparison = require_semantic_core_identity(
            landed_layout, settled_layout, label="landed-vs-settled"
        )
    except NativeMenuGenerationV218Error as error:
        message = str(error)
        if message.startswith(ADDITIONAL_FIELD_STOP) or message == CORE_GENERATION_STOP:
            raise NativeMenuGenerationV219Error(message) from error
        raise
    pair_core = instance_local_generation.get("paired_core_equality", {})
    if (
        instance_local_generation.get("settlement_spec") != SETTLEMENT_SPEC
        or instance_local_generation.get("field_scope")
        != ["generation", "semantic_generation"]
        or instance_local_generation.get("recorded_generation")
        != settled_generation
        or instance_local_generation.get("instance_local_generation") is not True
        or pair_core.get("core_equal") is not True
        or pair_core.get("zero_residual") is not True
    ):
        raise NativeMenuGenerationV219Error(PAIR_RECEIPT_STOP)
    if not isinstance(bound_endpoints, list) or (
        not bound_endpoints and not allow_empty_bound_endpoints
    ):
        raise NativeMenuGenerationV219Error(BOUND_ENDPOINT_STOP)
    for endpoint in bound_endpoints:
        if (
            not isinstance(endpoint, dict)
            or endpoint.get("exact") is not True
            or endpoint.get("semantic_multiset_equal") is not True
            or endpoint.get("relative_sequence_equal") is not True
            or endpoint.get("zero_residual") is not True
        ):
            raise NativeMenuGenerationV219Error(BOUND_ENDPOINT_STOP)
    return {
        "schema": "solomon-dark-native-menu-instance-local-generation-v219",
        "settlement_spec": SETTLEMENT_SPEC,
        "field_scope": ["generation", "semantic_generation"],
        "reason": "absolute_generation_is_instance_local_nonvisual_bookkeeping",
        "landed_generation": landed_generation,
        "settled_generation": settled_generation,
        "semantic_core": comparison,
        "instance_local_generation": copy.deepcopy(instance_local_generation),
        "bound_endpoint_count": len(bound_endpoints),
        "bound_endpoints": copy.deepcopy(bound_endpoints),
        "empty_bound_endpoints_vacuous": (
            not bound_endpoints and allow_empty_bound_endpoints
        ),
        "no_other_field_excluded": True,
    }
