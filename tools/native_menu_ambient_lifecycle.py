#!/usr/bin/env python3
"""Settlement v2.5 ambient-lifecycle measurement and pair resolution.

Raw element ids and absolute draw orders are recorder bookkeeping.  This
module contracts the semantic core that independent instances reproduce and
envelopes the title-backdrop lifecycle that they do not.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SETTLEMENT_SPEC = "2.5"
MINIMUM_SAMPLES = 40
MINIMUM_SPAN_MILLISECONDS = 2_000
MAXIMUM_AMBIENT_FRACTION = 0.40
MAXIMUM_ANIMATED_FRACTION = 0.30
EXTENDED_OBSERVATION_MINIMUM_SAMPLES = 200
EXTENDED_OBSERVATION_MINIMUM_MILLISECONDS = 60_000

GEOMETRY_FIELDS = {"rect", "unclipped_rect"}
CYCLING_FIELDS = {*GEOMETRY_FIELDS, "visible"}
BOOKKEEPING_FIELDS = {"id", "draw_order"}
CAPABILITY_FIELDS = {*BOOKKEEPING_FIELDS, *GEOMETRY_FIELDS, "visible"}


class AmbientLifecycleError(ValueError):
    """A recording does not satisfy Settlement v2.5."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _slug(value: Any) -> str:
    result = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return result or "member"


def _element_id(element: dict[str, Any]) -> str:
    element_id = element.get("id")
    if not isinstance(element_id, str) or not element_id:
        raise AmbientLifecycleError(
            "ambient lifecycle recorder defect: every element needs a non-empty id"
        )
    return element_id


def _finite_draw_order(element: dict[str, Any]) -> float:
    element_id = _element_id(element)
    value = element.get("draw_order")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise AmbientLifecycleError(
            "relative draw sequence contract: element "
            f"'{element_id}' has no finite draw_order"
        )
    return float(value)


def _finite_rect(
    element: dict[str, Any], field: str
) -> tuple[float, float, float, float]:
    element_id = _element_id(element)
    value = element.get(field)
    if not isinstance(value, list) or len(value) != 4:
        raise AmbientLifecycleError(
            "ambient lifecycle recorder defect: element "
            f"'{element_id}' has no four-number {field}"
        )
    coordinates: list[float] = []
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: element "
                f"'{element_id}' has non-numeric {field}"
            )
        coordinate = float(raw)
        if not math.isfinite(coordinate):
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: element "
                f"'{element_id}' has non-finite {field}"
            )
        coordinates.append(coordinate)
    return tuple(coordinates)  # type: ignore[return-value]


def _geometry(element: dict[str, Any]) -> tuple[Any, ...]:
    return (_finite_rect(element, "rect"), _finite_rect(element, "unclipped_rect"))


def _semantic_payload(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in BOOKKEEPING_FIELDS
    }


def _capability_payload(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in CAPABILITY_FIELDS
    }


def _pure_art(element: dict[str, Any]) -> bool:
    return (
        element.get("kind") == "art"
        and element.get("text", "") == ""
        and element.get("action_id", "") == ""
        and element.get("interactive") is False
    )


def _elements_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    elements = payload.get("elements")
    if not isinstance(elements, list) or not elements:
        raise AmbientLifecycleError(
            "ambient lifecycle recorder defect: sampled layout contains no elements"
        )
    indexed: dict[str, dict[str, Any]] = {}
    for raw in elements:
        if not isinstance(raw, dict):
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: sampled element is not an object"
            )
        element_id = _element_id(raw)
        if element_id in indexed:
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: duplicate element id "
                f"'{element_id}' is ambiguous"
            )
        _finite_draw_order(raw)
        _geometry(raw)
        indexed[element_id] = raw
    return indexed


def _sample_identity(sample: dict[str, Any]) -> tuple[str, int, int, str]:
    payload = sample.get("payload")
    if not isinstance(payload, dict):
        raise AmbientLifecycleError(
            "ambient lifecycle recorder defect: sample has no semantic payload"
        )
    screen_id = payload.get("screen_id")
    layout_generation = payload.get("generation")
    if not isinstance(screen_id, str) or not screen_id:
        raise AmbientLifecycleError(
            "ambient lifecycle recorder defect: sample has no screen_id"
        )
    if isinstance(layout_generation, bool) or not isinstance(layout_generation, int):
        raise AmbientLifecycleError(
            "ambient lifecycle recorder defect: sample has no layout generation"
        )

    # The v6 raw standalone recorder did not persist these two already-probed
    # fields.  Payload fallback lets those sealed windows be reclassified while
    # all v2.5 recorders write the exact semantic values on every sample.
    semantic_surface = sample.get("semantic_surface", screen_id)
    semantic_generation = sample.get("semantic_generation", layout_generation)
    if not isinstance(semantic_surface, str):
        raise AmbientLifecycleError(
            "ambient lifecycle recorder defect: sample has no semantic surface"
        )
    if isinstance(semantic_generation, bool) or not isinstance(
        semantic_generation, int
    ):
        raise AmbientLifecycleError(
            "ambient lifecycle recorder defect: sample has no semantic generation"
        )
    return semantic_surface, semantic_generation, layout_generation, screen_id


def _validate_window_clock(
    samples: list[dict[str, Any]],
    minimum_samples: int,
    minimum_span_milliseconds: int,
) -> tuple[list[int], int]:
    if len(samples) < minimum_samples:
        raise AmbientLifecycleError(
            "ambient lifecycle settlement contract: window has "
            f"{len(samples)} samples; at least {minimum_samples} are required"
        )
    elapsed: list[int] = []
    for sample in samples:
        value = sample.get("elapsed_milliseconds")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: sample clock is not numeric"
            )
        elapsed.append(int(value))
    if elapsed != sorted(elapsed) or len(set(elapsed)) != len(elapsed):
        raise AmbientLifecycleError(
            "ambient lifecycle settlement contract: sample clocks are not strictly monotonic"
        )
    span = elapsed[-1] - elapsed[0]
    if span < minimum_span_milliseconds:
        raise AmbientLifecycleError(
            "ambient lifecycle settlement contract: window spans "
            f"{span} ms; at least {minimum_span_milliseconds} ms are required"
        )
    identities = [_sample_identity(sample) for sample in samples]
    if len(set(identities)) != 1:
        raise AmbientLifecycleError(
            "ambient lifecycle settlement contract: surface, semantic generation, "
            "layout generation, or screen changed within the candidate window"
        )
    return elapsed, span


def _field_variations(elements: list[dict[str, Any]]) -> set[str]:
    fields = set().union(*(element.keys() for element in elements))
    varied: set[str] = set()
    for field in fields - {"id"}:
        values = {canonical_bytes(element.get(field)) for element in elements}
        if len(values) > 1:
            varied.add(field)
    return varied


def _rect_envelope(
    rectangles: Iterable[tuple[float, float, float, float]],
) -> dict[str, float]:
    values = list(rectangles)
    if not values:
        raise AmbientLifecycleError(
            "ambient lifecycle recorder defect: geometry envelope has no samples"
        )
    return {
        "min_x": min(value[0] for value in values),
        "max_x": max(value[0] for value in values),
        "min_y": min(value[1] for value in values),
        "max_y": max(value[1] for value in values),
        "min_width": min(value[2] - value[0] for value in values),
        "max_width": max(value[2] - value[0] for value in values),
        "min_height": min(value[3] - value[1] for value in values),
        "max_height": max(value[3] - value[1] for value in values),
    }


def _member_events(
    presence: list[bool], present: list[tuple[int, dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    membership: list[dict[str, Any]] = []
    for index in range(1, len(presence)):
        if presence[index] == presence[index - 1]:
            continue
        membership.append(
            {
                "sample_index": index,
                "event": "spawn" if presence[index] else "despawn",
            }
        )
    visible: list[dict[str, Any]] = []
    geometry: list[dict[str, Any]] = []
    for (previous_index, previous), (index, current) in zip(present, present[1:]):
        if index != previous_index + 1:
            continue
        if current.get("visible") != previous.get("visible"):
            visible.append(
                {
                    "sample_index": index,
                    "from": previous.get("visible"),
                    "to": current.get("visible"),
                }
            )
        if _geometry(current) != _geometry(previous):
            geometry.append({"sample_index": index})
    return {"membership": membership, "visible": visible, "geometry": geometry}


def _measure_window(
    samples: list[dict[str, Any]],
    *,
    label: str,
    minimum_samples: int = MINIMUM_SAMPLES,
    minimum_span_milliseconds: int = MINIMUM_SPAN_MILLISECONDS,
) -> dict[str, Any]:
    elapsed, span = _validate_window_clock(
        samples, minimum_samples, minimum_span_milliseconds
    )
    identity = _sample_identity(samples[0])
    structural_headers = [
        {
            key: copy.deepcopy(value)
            for key, value in sample["payload"].items()
            if key != "elements"
        }
        for sample in samples
    ]
    anchor_header = canonical_bytes(structural_headers[0])
    for index, header in enumerate(structural_headers[1:], start=1):
        if canonical_bytes(header) != anchor_header:
            changed = sorted(
                key
                for key in set(structural_headers[0]) | set(header)
                if structural_headers[0].get(key) != header.get(key)
            )
            field = changed[0] if changed else "<unknown>"
            raise AmbientLifecycleError(
                "ambient lifecycle structural-core guardrail: non-element "
                f"payload field '{field}' varied at sample {index}"
            )
    indexed_samples = [_elements_by_id(sample["payload"]) for sample in samples]
    all_ids = sorted(set().union(*(set(indexed) for indexed in indexed_samples)))
    members: list[dict[str, Any]] = []
    for element_id in all_ids:
        presence = [element_id in indexed for indexed in indexed_samples]
        present = [
            (index, indexed[element_id])
            for index, indexed in enumerate(indexed_samples)
            if element_id in indexed
        ]
        elements = [element for _, element in present]
        if not elements:
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: member index resolved no observations"
            )
        varied = _field_variations(elements)
        non_bookkeeping_varied = varied - {"draw_order"}
        events = _member_events(presence, present)
        anchor = elements[0]
        art_id = anchor.get("art_id")
        kind = anchor.get("kind")

        member_class = "full_presence"
        if not all(presence):
            first_present = presence.index(True)
            one_way_spawn = (
                not presence[0]
                and all(presence[first_present:])
                and len(events["membership"]) == 1
                and events["membership"][0]["event"] == "spawn"
            )
            if not _pure_art(anchor):
                raise AmbientLifecycleError(
                    "ambient lifecycle art-only guard: membership churn on "
                    f"text/control member '{element_id}' is not classifiable"
                )
            illegal = non_bookkeeping_varied - CYCLING_FIELDS
            if illegal:
                field = sorted(illegal)[0]
                raise AmbientLifecycleError(
                    "ambient lifecycle guardrail: ephemeral member "
                    f"'{element_id}' field '{field}' varied outside lifecycle geometry"
                )
            # A one-way spawn is deliberately unresolved here.  It is not
            # called ephemeral until a paired campaign proves bidirectional
            # churn for the same art family; otherwise it remains a population
            # ramp and resolution stops.
            member_class = (
                "one_way_spawn_candidate" if one_way_spawn else "ephemeral"
            )
        elif "visible" in non_bookkeeping_varied:
            if not _pure_art(anchor):
                raise AmbientLifecycleError(
                    "ambient lifecycle art-only guard: visible variance on "
                    f"text/control member '{element_id}' is not classifiable"
                )
            illegal = non_bookkeeping_varied - CYCLING_FIELDS
            if illegal:
                field = sorted(illegal)[0]
                raise AmbientLifecycleError(
                    "ambient lifecycle guardrail: visibility-cycling member "
                    f"'{element_id}' field '{field}' varied outside visible/rect"
                )
            member_class = "visibility_cycling"
        elif non_bookkeeping_varied:
            illegal = non_bookkeeping_varied - GEOMETRY_FIELDS
            if illegal:
                field = sorted(illegal)[0]
                raise AmbientLifecycleError(
                    "ambient lifecycle guardrail: member "
                    f"'{element_id}' field '{field}' varied outside authorized classes"
                )
            member_class = "animated"

        if member_class == "animated" and not events["geometry"]:
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: phantom animated classification "
                f"for '{element_id}' has no rect variation event"
            )
        if member_class == "visibility_cycling" and not events["visible"]:
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: phantom visibility-cycling "
                f"classification for '{element_id}' has no toggle event"
            )
        if member_class in {"ephemeral", "one_way_spawn_candidate"} and not events[
            "membership"
        ]:
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: phantom ephemeral classification "
                f"for '{element_id}' has no membership event"
            )

        rects = [_finite_rect(element, "rect") for element in elements]
        unclipped = [
            _finite_rect(element, "unclipped_rect") for element in elements
        ]
        visible_true = sum(element.get("visible") is True for element in elements)
        dominant_visible = visible_true * 2 >= len(elements)
        dominant = next(
            (
                element
                for element in elements
                if bool(element.get("visible")) == dominant_visible
            ),
            anchor,
        )
        members.append(
            {
                "captured_element_id": element_id,
                "kind": kind,
                "art_id": art_id if isinstance(art_id, str) else "",
                "classification": member_class,
                "present_samples": len(elements),
                "absent_samples": len(samples) - len(elements),
                "semantic_payload": _semantic_payload(anchor),
                "semantic_signature": sha256_json(_semantic_payload(anchor)),
                "capability_payload": _capability_payload(anchor),
                "capability_signature": sha256_json(_capability_payload(anchor)),
                "dominant_phase_payload": _semantic_payload(dominant),
                "on_fraction": visible_true / len(elements),
                "events": events,
                "envelope": {
                    "sample_count": len(elements),
                    "rect": _rect_envelope(rects),
                    "unclipped_rect": _rect_envelope(unclipped),
                },
            }
        )

    return {
        "label": label,
        "identity": {
            "semantic_surface": identity[0],
            "semantic_generation": identity[1],
            "layout_generation": identity[2],
            "screen_id": identity[3],
            "identity_source": (
                "semantic_probe"
                if "semantic_surface" in samples[0]
                and "semantic_generation" in samples[0]
                else "sealed_v6_payload_fallback"
            ),
        },
        "sample_count": len(samples),
        "stable_span_milliseconds": span,
        "settle_latency_milliseconds": elapsed[-1],
        "minimum_element_count": min(len(indexed) for indexed in indexed_samples),
        "peak_element_count": max(len(indexed) for indexed in indexed_samples),
        "members": members,
        "samples": samples,
    }


def _sorted_elements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    indexed = _elements_by_id(payload)
    return sorted(
        indexed.values(),
        key=lambda element: (
            _finite_draw_order(element),
            canonical_bytes(_semantic_payload(element)),
            _element_id(element),
        ),
    )


def _member_envelope_ranges(
    member: dict[str, Any],
) -> tuple[tuple[float, float], ...]:
    ranges: list[tuple[float, float]] = []
    for field in ("rect", "unclipped_rect"):
        envelope = member["envelope"][field]
        for axis in ("x", "y", "width", "height"):
            ranges.append(
                (float(envelope[f"min_{axis}"]), float(envelope[f"max_{axis}"]))
            )
    return tuple(ranges)


def _motion_geometry_compatible(
    left: tuple[tuple[float, float], ...],
    right: tuple[tuple[float, float], ...],
) -> bool:
    for (left_min, left_max), (right_min, right_max) in zip(left, right):
        if max(left_min, right_min) > min(left_max, right_max):
            return False
    return True


def _union_member_ranges(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[tuple[float, float], ...]:
    all_ranges = [_member_envelope_ranges(member) for _, member in records]
    return tuple(
        (
            min(ranges[index][0] for ranges in all_ranges),
            max(ranges[index][1] for ranges in all_ranges),
        )
        for index in range(len(all_ranges[0]))
    )


def _varying_member_geometry_ranks(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[tuple[int, str], int]:
    by_measurement: dict[
        int, list[tuple[dict[str, Any], dict[str, Any]]]
    ] = defaultdict(list)
    for measurement, member in records:
        if member["classification"] in {"animated", "full_presence"}:
            by_measurement[id(measurement)].append((measurement, member))
    counts = {len(values) for values in by_measurement.values()}
    if len(by_measurement) < 2 or len(counts) != 1:
        return {}

    result: dict[tuple[int, str], int] = {}
    for values in by_measurement.values():
        ranked = sorted(
            values,
            key=lambda record: (
                _member_envelope_ranges(record[1])[1],
                _member_envelope_ranges(record[1])[0],
                _member_envelope_ranges(record[1])[2:],
            ),
        )
        rank_keys = [_member_envelope_ranges(member) for _, member in ranked]
        if len(rank_keys) != len(set(rank_keys)):
            raise AmbientLifecycleError(
                "varying-member identity ambiguity: geometry-rank collision "
                "within one observation"
            )
        for rank, (measurement, member) in enumerate(ranked):
            result[(id(measurement), member["captured_element_id"])] = rank
    return result


def _resolve_varying_member_keys(
    measurements: list[dict[str, Any]],
    ambient_family: set[str],
) -> tuple[dict[tuple[int, str], str], dict[str, int]]:
    by_capability: dict[
        str, list[tuple[dict[str, Any], dict[str, Any]]]
    ] = defaultdict(list)
    for measurement in measurements:
        for member in measurement["members"]:
            by_capability[member["capability_signature"]].append(
                (measurement, member)
            )

    resolved: dict[tuple[int, str], str] = {}
    cross_window_rect_events: dict[str, int] = {}
    for capability, records in sorted(by_capability.items()):
        witnesses = [
            record
            for record in records
            if record[1]["classification"] == "animated"
            and record[1]["art_id"] not in ambient_family
        ]
        geometry_ranks = _varying_member_geometry_ranks(records)
        if not witnesses:
            # Motion capability belongs to the semantic screen member, not to
            # one sampling window.  Two individually quiet windows at
            # different rectangles are themselves a measured rect event.
            # Geometry rank keeps repeated, semantically identical art draws
            # distinct without treating synthetic element ordinals as native
            # identity.
            if not geometry_ranks or len(
                {id(measurement) for measurement, _ in records}
            ) != len(measurements):
                continue
            records_by_rank: dict[
                int, list[tuple[dict[str, Any], dict[str, Any]]]
            ] = defaultdict(list)
            for measurement, member in records:
                if member["classification"] != "full_presence":
                    continue
                rank = geometry_ranks.get(
                    (id(measurement), member["captured_element_id"])
                )
                if rank is not None:
                    records_by_rank[rank].append((measurement, member))
            for rank, ranked_records in sorted(records_by_rank.items()):
                geometry_samples = {
                    _member_envelope_ranges(member)
                    for _, member in ranked_records
                }
                if len(geometry_samples) < 2:
                    continue
                fixed_payloads = {
                    canonical_bytes(
                        {
                            field: value
                            for field, value in member["semantic_payload"].items()
                            if field not in GEOMETRY_FIELDS
                        }
                    )
                    for _, member in ranked_records
                }
                if len(fixed_payloads) != 1:
                    raise AmbientLifecycleError(
                        "motion capability guardrail: cross-window member "
                        f"'{ranked_records[0][1]['captured_element_id']}' varied "
                        "outside rect/unclipped_rect"
                    )
                key = f"member:{capability}:slot:{rank + 1}"
                for measurement, member in ranked_records:
                    resolved[
                        (id(measurement), member["captured_element_id"])
                    ] = key
                cross_window_rect_events[key] = len(geometry_samples) - 1
            continue
        remaining = set(range(len(witnesses)))
        components: list[list[tuple[dict[str, Any], dict[str, Any]]]] = []
        while remaining:
            pending = [remaining.pop()]
            component_indexes: set[int] = set()
            while pending:
                index = pending.pop()
                if index in component_indexes:
                    continue
                component_indexes.add(index)
                left = _member_envelope_ranges(witnesses[index][1])
                neighbours = [
                    candidate
                    for candidate in list(remaining)
                    if _motion_geometry_compatible(
                        left, _member_envelope_ranges(witnesses[candidate][1])
                    )
                    or (
                        (
                            id(witnesses[index][0]),
                            witnesses[index][1]["captured_element_id"],
                        )
                        in geometry_ranks
                        and (
                            id(witnesses[candidate][0]),
                            witnesses[candidate][1]["captured_element_id"],
                        )
                        in geometry_ranks
                        and geometry_ranks[
                            (
                                id(witnesses[index][0]),
                                witnesses[index][1]["captured_element_id"],
                            )
                        ]
                        == geometry_ranks[
                            (
                                id(witnesses[candidate][0]),
                                witnesses[candidate][1]["captured_element_id"],
                            )
                        ]
                    )
                ]
                for candidate in neighbours:
                    remaining.remove(candidate)
                    pending.append(candidate)
            components.append([witnesses[index] for index in component_indexes])

        components.sort(key=lambda component: canonical_bytes(_union_member_ranges(component)))
        for slot, component in enumerate(components, start=1):
            component_ranges = _union_member_ranges(component)
            component_ranks = {
                geometry_ranks.get(
                    (id(measurement), member["captured_element_id"])
                )
                for measurement, member in component
                if (
                    id(measurement),
                    member["captured_element_id"],
                )
                in geometry_ranks
            }
            if len(component_ranks) > 1:
                raise AmbientLifecycleError(
                    "varying-member identity ambiguity: motion envelopes crossed "
                    "measured geometry ranks"
                )
            identities = [id(measurement) for measurement, _ in component]
            if len(identities) != len(set(identities)):
                raise AmbientLifecycleError(
                    "varying-member identity ambiguity: one observation contains "
                    f"multiple compatible witnesses for capability '{capability}'"
                )
            key = f"member:{capability}:slot:{slot}"
            for measurement, member in component:
                resolved[(id(measurement), member["captured_element_id"])] = key

            for measurement, member in records:
                record_key = (id(measurement), member["captured_element_id"])
                if record_key in resolved or member["classification"] != "full_presence":
                    continue
                matches = [
                    candidate
                    for candidate in components
                    if _motion_geometry_compatible(
                        _member_envelope_ranges(member),
                        _union_member_ranges(candidate),
                    )
                    or any(
                        geometry_ranks.get(record_key)
                        == geometry_ranks.get(
                            (
                                id(candidate_measurement),
                                candidate_member["captured_element_id"],
                            )
                        )
                        for candidate_measurement, candidate_member in candidate
                        if record_key in geometry_ranks
                    )
                ]
                if len(matches) > 1:
                    raise AmbientLifecycleError(
                        "varying-member identity ambiguity: quiet member "
                        f"'{member['captured_element_id']}' matches multiple motion slots"
                    )
                if len(matches) == 1 and matches[0] is component:
                    occupied = {
                        resolved.get((id(measurement), other["captured_element_id"]))
                        for other_measurement, other in records
                        if other_measurement is measurement
                    }
                    if key in occupied:
                        raise AmbientLifecycleError(
                            "varying-member identity ambiguity: one observation has "
                            f"two members in resolved slot '{key}'"
                        )
                    resolved[record_key] = key
    return resolved, cross_window_rect_events


def _core_counter_for_measurements(
    measurements: list[dict[str, Any]],
    ambient_family: set[str],
    varying_member_keys: dict[tuple[int, str], str],
) -> tuple[Counter[bytes], dict[bytes, dict[str, Any]]]:
    stable_counters: list[Counter[bytes]] = []
    payload_by_signature: dict[bytes, dict[str, Any]] = {}
    family_by_signature: dict[bytes, bool] = {}
    for measurement in measurements:
        counter: Counter[bytes] = Counter()
        for member in measurement["members"]:
            if member["classification"] != "full_presence":
                continue
            if (id(measurement), member["captured_element_id"]) in varying_member_keys:
                # Motion/toggle capability is asymmetric: one measured event
                # anywhere makes every quiet observation of the same semantic
                # member non-core.
                continue
            signature = canonical_bytes(member["semantic_payload"])
            counter[signature] += 1
            payload_by_signature.setdefault(
                signature, copy.deepcopy(member["semantic_payload"])
            )
            family_by_signature[signature] = member["art_id"] in ambient_family
        stable_counters.append(counter)
    if not stable_counters:
        raise AmbientLifecycleError(
            "cross-instance structural core contract: no measurements were supplied"
        )

    common = stable_counters[0].copy()
    for counter in stable_counters[1:]:
        common &= counter
    for index, counter in enumerate(stable_counters):
        residual = counter - common
        non_family = [
            signature
            for signature, count in residual.items()
            if count and not family_by_signature.get(signature, False)
        ]
        if non_family:
            payload = payload_by_signature[non_family[0]]
            label = payload.get("action_id") or payload.get("art_id") or payload.get("text")
            raise AmbientLifecycleError(
                "cross-instance structural core inequality: non-ambient full-presence "
                f"member '{label}' differs or is missing in observation {index}"
            )
    if not common:
        raise AmbientLifecycleError(
            "cross-instance structural core contract: independent instances share no core"
        )
    return common, payload_by_signature


def _project_core_sequence(
    payload: dict[str, Any], core_counter: Counter[bytes]
) -> tuple[list[bytes], dict[int, int]]:
    remaining = core_counter.copy()
    sequence: list[bytes] = []
    element_to_core_index: dict[int, int] = {}
    for element_index, element in enumerate(_sorted_elements(payload)):
        signature = canonical_bytes(_semantic_payload(element))
        if remaining[signature] <= 0:
            continue
        element_to_core_index[element_index] = len(sequence)
        sequence.append(signature)
        remaining[signature] -= 1
    if any(remaining.values()):
        raise AmbientLifecycleError(
            "relative draw sequence contract: a structural core member disappeared"
        )
    return sequence, element_to_core_index


def _normalized_core(
    screen_id: str,
    sequence: list[bytes],
    payload_by_signature: dict[bytes, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    counters: Counter[str] = Counter()
    elements: list[dict[str, Any]] = []
    ids: list[str] = []
    for relative_order, signature in enumerate(sequence):
        element = copy.deepcopy(payload_by_signature[signature])
        kind = str(element.get("kind", "member"))
        if kind == "art":
            token = element.get("art_id", "art")
        elif kind == "control":
            token = element.get("action_id") or element.get("text") or "control"
        else:
            token = element.get("text") or element.get("art_id") or kind
        base = f"{_slug(screen_id)}.{_slug(kind)}.{_slug(token)}"
        counters[base] += 1
        normalized_id = f"{base}.{counters[base]}"
        element["id"] = normalized_id
        element["draw_order"] = relative_order
        element["draw_order_semantics"] = "structural_core_relative_sequence"
        elements.append(element)
        ids.append(normalized_id)
    return elements, ids


def _union_envelope(elements: list[dict[str, Any]]) -> dict[str, Any]:
    rects = [_finite_rect(element, "rect") for element in elements]
    unclipped = [_finite_rect(element, "unclipped_rect") for element in elements]
    return {
        "sample_count": len(elements),
        "rect": _rect_envelope(rects),
        "unclipped_rect": _rect_envelope(unclipped),
    }


def _core_bands(
    measurements: list[dict[str, Any]],
    core_counter: Counter[bytes],
    core_ids: list[str],
    varying_member_keys: dict[tuple[int, str], str],
) -> dict[str, list[dict[str, str]]]:
    bands: dict[str, set[tuple[str, str]]] = defaultdict(set)
    band_witnesses: dict[str, dict[tuple[str, str], set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    band_identities: dict[
        str, dict[tuple[str, str], set[tuple[str, int]]]
    ] = defaultdict(lambda: defaultdict(set))
    for measurement in measurements:
        for sample in measurement["samples"]:
            ordered = _sorted_elements(sample["payload"])
            _, core_positions = _project_core_sequence(sample["payload"], core_counter)
            positions = sorted(core_positions)
            for index, element in enumerate(ordered):
                if index in core_positions:
                    continue
                resolved_key = varying_member_keys.get(
                    (id(measurement), _element_id(element))
                )
                art_id = element.get("art_id")
                if resolved_key is not None:
                    band_key = resolved_key
                elif not isinstance(art_id, str) or not art_id:
                    capability = sha256_json(_capability_payload(element))
                    band_key = f"member:{capability}"
                else:
                    band_key = f"art:{art_id}"
                lower = max((value for value in positions if value < index), default=None)
                upper = min((value for value in positions if value > index), default=None)
                lower_id = (
                    "bottom"
                    if lower is None
                    else core_ids[core_positions[lower]]
                )
                upper_id = "top" if upper is None else core_ids[core_positions[upper]]
                band = (lower_id, upper_id)
                bands[band_key].add(band)
                band_witnesses[band_key][band].add(measurement["label"])
                band_identities[band_key][band].add(
                    (measurement["instance"], measurement["process_id"])
                )
    result: dict[str, list[dict[str, str]]] = {}
    for key, values in sorted(bands.items()):
        for lower, upper in sorted(values):
            band = (lower, upper)
            if len(band_identities[key][band]) < 2:
                raise AmbientLifecycleError(
                    "ambient draw-band cross-instance contract: member family "
                    f"'{key}' band '{lower}->{upper}' lacks two independent "
                    "instance witnesses: "
                    f"{sorted(band_witnesses[key][band])}"
                )
        result[key] = [
            {"below": lower, "above": upper} for lower, upper in sorted(values)
        ]
    return result


def _observed_elements_for_art(
    measurements: list[dict[str, Any]], art_id: str
) -> list[dict[str, Any]]:
    return [
        element
        for measurement in measurements
        for sample in measurement["samples"]
        for element in sample["payload"]["elements"]
        if element.get("art_id") == art_id
    ]


def resolve_ambient_lifecycle(
    observations: list[dict[str, Any]],
    *,
    maximum_ambient_fraction: float = MAXIMUM_AMBIENT_FRACTION,
) -> dict[str, Any]:
    """Resolve one screen from two fresh instances and optional extensions."""
    if len(observations) < 2:
        raise AmbientLifecycleError(
            "cross-instance structural core contract: two observations are required"
        )
    measurements: list[dict[str, Any]] = []
    settled_identities: set[tuple[str, int]] = set()
    for index, observation in enumerate(observations):
        samples = observation.get("samples")
        if not isinstance(samples, list):
            raise AmbientLifecycleError(
                f"ambient lifecycle recorder defect: observation {index} has no samples"
            )
        kind = observation.get("kind", "settled_window")
        instance = observation.get("instance")
        process_id = observation.get("process_id")
        if (
            not isinstance(instance, str)
            or not instance
            or isinstance(process_id, bool)
            or not isinstance(process_id, int)
            or process_id <= 0
        ):
            raise AmbientLifecycleError(
                "ambient lifecycle recorder defect: observation has no exact instance/PID"
            )
        if kind == "extended_observation":
            minimum_samples = EXTENDED_OBSERVATION_MINIMUM_SAMPLES
            minimum_span = EXTENDED_OBSERVATION_MINIMUM_MILLISECONDS
        elif kind == "settled_window":
            minimum_samples = MINIMUM_SAMPLES
            minimum_span = MINIMUM_SPAN_MILLISECONDS
            settled_identities.add((instance, process_id))
        else:
            raise AmbientLifecycleError(
                f"ambient lifecycle recorder defect: unknown observation kind '{kind}'"
            )
        measured = _measure_window(
            samples,
            label=str(observation.get("label", f"observation[{index}]")),
            minimum_samples=minimum_samples,
            minimum_span_milliseconds=minimum_span,
        )
        measured["kind"] = kind
        measured["instance"] = instance
        measured["process_id"] = process_id
        measured["corroboration_anchor"] = bool(
            observation.get("corroboration_anchor", kind == "settled_window")
            and kind == "settled_window"
        )
        evidence = observation.get("evidence")
        if isinstance(evidence, dict):
            measured["evidence"] = copy.deepcopy(evidence)
        measurements.append(measured)
    if len(settled_identities) < 2:
        raise AmbientLifecycleError(
            "cross-instance structural core contract: two fresh settled instances are required"
        )
    screen_identities = {
        (
            measurement["identity"]["semantic_surface"],
            measurement["identity"]["screen_id"],
        )
        for measurement in measurements
    }
    if len(screen_identities) != 1:
        raise AmbientLifecycleError(
            "cross-instance structural core contract: observations do not name "
            "one semantic surface and screen"
        )

    ambient_family = {
        member["art_id"]
        for measurement in measurements
        for member in measurement["members"]
        if member["classification"]
        in {"ephemeral", "visibility_cycling", "one_way_spawn_candidate"}
        and member["art_id"]
    }
    varying_member_keys, cross_window_rect_events = _resolve_varying_member_keys(
        measurements, ambient_family
    )
    corroborations: list[dict[str, Any]] = []
    settled_measurements = [
        measurement
        for measurement in measurements
        if measurement["kind"] == "settled_window"
    ]
    corroboration_anchors = [
        measurement
        for measurement in settled_measurements
        if measurement["corroboration_anchor"]
    ]
    if len(
        {
            (measurement["instance"], measurement["process_id"])
            for measurement in corroboration_anchors
        }
    ) < 2:
        raise AmbientLifecycleError(
            "motion capability resolution requires two fresh standalone "
            "corroboration anchors"
        )
    extended_measurements = [
        measurement
        for measurement in measurements
        if measurement["kind"] == "extended_observation"
    ]
    settled_varying_keys = {
        varying_member_keys[(id(measurement), member["captured_element_id"])]
        for measurement in settled_measurements
        for member in measurement["members"]
        if (id(measurement), member["captured_element_id"])
        in varying_member_keys
    }
    for varying_key in sorted(settled_varying_keys):
        varying_records = [
            (measurement, member)
            for measurement in settled_measurements
            for member in measurement["members"]
            if varying_member_keys.get(
                (id(measurement), member["captured_element_id"])
            )
            == varying_key
        ]
        classes = {member["classification"] for _, member in varying_records}
        art_ids = {member["art_id"] for _, member in varying_records if member["art_id"]}
        cross_window_motion = varying_key in cross_window_rect_events
        if bool(art_ids & ambient_family) or not (
            cross_window_motion
            or ("animated" in classes and "full_presence" in classes)
        ):
            continue
        for quiet_measurement, quiet_member in varying_records:
            if quiet_member["classification"] != "full_presence":
                continue
            if not quiet_measurement["corroboration_anchor"]:
                continue
            matching_extensions = [
                measurement
                for measurement in extended_measurements
                if measurement["instance"] == quiet_measurement["instance"]
                and measurement["process_id"] == quiet_measurement["process_id"]
                and any(
                    varying_member_keys.get(
                        (id(measurement), member["captured_element_id"])
                    )
                    == varying_key
                    for member in measurement["members"]
                )
            ]
            if not matching_extensions:
                raise AmbientLifecycleError(
                    "motion capability resolution requires extended-observation "
                    "evidence for stationary member "
                    f"'{quiet_member['captured_element_id']}' in instance "
                    f"'{quiet_measurement['instance']}' PID "
                    f"{quiet_measurement['process_id']}"
                )
            corroborations.append(
                {
                    "resolved_member_key": varying_key,
                    "motion_witness": (
                        "cross_window_rect_variance"
                        if cross_window_motion
                        else "within_window_rect_variance"
                    ),
                    "stationary_instance": quiet_measurement["instance"],
                    "stationary_process_id": quiet_measurement["process_id"],
                    "extended_observations": [
                        measurement["label"] for measurement in matching_extensions
                    ],
                }
            )
    core_counter, payload_by_signature = _core_counter_for_measurements(
        measurements, ambient_family, varying_member_keys
    )
    reference_sequence: list[bytes] | None = None
    for measurement in measurements:
        for sample_index, sample in enumerate(measurement["samples"]):
            sequence, _ = _project_core_sequence(sample["payload"], core_counter)
            if reference_sequence is None:
                reference_sequence = sequence
            elif sequence != reference_sequence:
                raise AmbientLifecycleError(
                    "relative draw sequence contract: structural core relative-order "
                    f"flip in '{measurement['label']}' sample {sample_index}"
                )
    if reference_sequence is None:
        raise AmbientLifecycleError(
            "cross-instance structural core contract: no core sequence was observed"
        )
    identity = copy.deepcopy(measurements[0]["identity"])
    identity["semantic_generations"] = sorted(
        {measurement["identity"]["semantic_generation"] for measurement in measurements}
    )
    identity["observed_layout_generations"] = sorted(
        {measurement["identity"]["layout_generation"] for measurement in measurements}
    )
    identity["layout_generation_semantics"] = (
        "standalone primary anchor; path-local counters remain in observation evidence"
    )
    identity.pop("semantic_generation", None)
    identity.pop("identity_source", None)
    core_elements, core_ids = _normalized_core(
        identity["screen_id"], reference_sequence, payload_by_signature
    )
    bands = _core_bands(
        measurements, core_counter, core_ids, varying_member_keys
    )

    member_classes: dict[str, set[str]] = defaultdict(set)
    event_counts: dict[str, Counter[str]] = defaultdict(Counter)
    resolved_records: list[dict[str, Any]] = []
    for measurement in measurements:
        remaining_core = core_counter.copy()
        for member in measurement["members"]:
            art_id = member["art_id"]
            varying_key = varying_member_keys.get(
                (id(measurement), member["captured_element_id"])
            )
            member_key = (
                varying_key
                or art_id
                or f"member:{member['capability_signature']}"
            )
            classification = member["classification"]
            signature = canonical_bytes(member["semantic_payload"])
            in_core = (
                classification == "full_presence"
                and varying_key is None
                and remaining_core[signature] > 0
            )
            if in_core:
                remaining_core[signature] -= 1
                continue
            if classification == "one_way_spawn_candidate":
                classification = "ephemeral"
            elif classification == "full_presence" and varying_key is not None:
                # A quiet window cannot demote an animated capability measured
                # by another instance of the same semantic member.
                measured_classes = {
                    other["classification"]
                    for other_measurement in measurements
                    for other in other_measurement["members"]
                    if varying_member_keys.get(
                        (id(other_measurement), other["captured_element_id"])
                    )
                    == varying_key
                }
                if (
                    "animated" in measured_classes
                    or varying_key in cross_window_rect_events
                ):
                    classification = "animated"
                elif "visibility_cycling" in measured_classes:
                    classification = "visibility_cycling"
                else:
                    raise AmbientLifecycleError(
                        "cross-instance structural core inequality: non-family quiet "
                        f"member '{member['captured_element_id']}' has no reproduced core"
                    )
            elif classification == "full_presence" and art_id in ambient_family:
                classification = "ambient_persistent"
            elif classification == "full_presence":
                raise AmbientLifecycleError(
                    "cross-instance structural core inequality: non-family quiet "
                    f"member '{member['captured_element_id']}' has no reproduced core"
                )
            member_classes[member_key].add(classification)
            resolved_records.append(
                {
                    "measurement": measurement,
                    "member": member,
                    "member_key": member_key,
                    "classification": classification,
                }
            )
            event_counts[member_key]["spawn"] += sum(
                event["event"] == "spawn" for event in member["events"]["membership"]
            )
            event_counts[member_key]["despawn"] += sum(
                event["event"] == "despawn" for event in member["events"]["membership"]
            )
            event_counts[member_key]["visible_toggle"] += len(
                member["events"]["visible"]
            )
            event_counts[member_key]["rect_change"] += len(
                member["events"]["geometry"]
            )

    for member_key, event_count in cross_window_rect_events.items():
        event_counts[member_key]["cross_window_rect_change"] = event_count

    ephemeral_art_ids = {
        member_key
        for member_key, classes in member_classes.items()
        if "ephemeral" in classes and not member_key.startswith("member:")
    }
    total_spawn = sum(event_counts[art_id]["spawn"] for art_id in ephemeral_art_ids)
    total_despawn = sum(
        event_counts[art_id]["despawn"] for art_id in ephemeral_art_ids
    )
    if ephemeral_art_ids and (total_spawn == 0 or total_despawn == 0):
        raise AmbientLifecycleError(
            "population-versus-ephemeral guardrail: ephemeral family lacks "
            "bidirectional spawn and despawn witnesses"
        )

    def record_elements(record: dict[str, Any]) -> list[dict[str, Any]]:
        captured_id = record["member"]["captured_element_id"]
        return [
            element
            for sample in record["measurement"]["samples"]
            for element in sample["payload"]["elements"]
            if element.get("id") == captured_id
        ]

    family_entries: list[dict[str, Any]] = []
    for member_key in sorted(member_classes):
        classes = sorted(member_classes[member_key])
        events = event_counts[member_key]
        art_records = [
            record
            for record in resolved_records
            if record["member_key"] == member_key
        ]
        record_art_ids = {
            record["member"]["art_id"]
            for record in art_records
            if record["member"]["art_id"]
        }
        if len(record_art_ids) > 1:
            raise AmbientLifecycleError(
                f"varying-member identity ambiguity: '{member_key}' spans art families"
            )
        art_id = next(iter(record_art_ids), "")
        for classification in classes:
            if classification == "animated" and (
                events["rect_change"] + events["cross_window_rect_change"] == 0
            ):
                raise AmbientLifecycleError(
                    "ambient lifecycle recorder defect: phantom animated "
                    f"classification for art family '{art_id}' has zero events"
                )
            if (
                classification == "visibility_cycling"
                and events["visible_toggle"] == 0
            ):
                raise AmbientLifecycleError(
                    "ambient lifecycle recorder defect: phantom visibility-cycling "
                    f"classification for art family '{art_id}' has zero events"
                )
            if classification == "ephemeral" and (
                events["spawn"] + events["despawn"] == 0
            ):
                raise AmbientLifecycleError(
                    "ambient lifecycle recorder defect: phantom ephemeral "
                    f"classification for art family '{art_id}' has zero events"
                )
            if classification == "ambient_persistent" and art_id not in ambient_family:
                raise AmbientLifecycleError(
                    "ambient lifecycle recorder defect: ambient-persistent family "
                    f"'{art_id}' has no lifecycle capability witness"
                )
        elements = [
            element for record in art_records for element in record_elements(record)
        ]
        visible_true = sum(element.get("visible") is True for element in elements)
        per_sample_counts: list[int] = []
        for measurement in measurements:
            captured_ids = {
                record["member"]["captured_element_id"]
                for record in art_records
                if record["measurement"] is measurement
            }
            per_sample_counts.extend(
                sum(
                    element.get("id") in captured_ids
                    for element in sample["payload"]["elements"]
                )
                for sample in measurement["samples"]
            )
        class_members: list[dict[str, Any]] = []
        for classification in classes:
            class_records = [
                record
                for record in art_records
                if record["classification"] == classification
            ]
            class_elements = [
                element
                for record in class_records
                for element in record_elements(record)
            ]
            class_visible_true = sum(
                element.get("visible") is True for element in class_elements
            )
            dominant_visible = class_visible_true * 2 >= len(class_elements)
            dominant = next(
                (
                    element
                    for element in class_elements
                    if bool(element.get("visible")) == dominant_visible
                ),
                class_elements[0],
            )
            class_events: Counter[str] = Counter()
            for record in class_records:
                member_events = record["member"]["events"]
                class_events["spawn"] += sum(
                    event["event"] == "spawn"
                    for event in member_events["membership"]
                )
                class_events["despawn"] += sum(
                    event["event"] == "despawn"
                    for event in member_events["membership"]
                )
                class_events["visible_toggle"] += len(member_events["visible"])
                class_events["rect_change"] += len(member_events["geometry"])
            if classification == "animated":
                class_events["cross_window_rect_change"] = events[
                    "cross_window_rect_change"
                ]
            class_members.append(
                {
                    "classification": classification,
                    "anchor_semantics": "first_observation_first_present_sample",
                    "anchor_payload": _semantic_payload(class_elements[0]),
                    "union_spatial_envelope": _union_envelope(class_elements),
                    "on_fraction": class_visible_true / len(class_elements),
                    "dominant_visible": dominant_visible,
                    "dominant_phase_payload": _semantic_payload(dominant),
                    "events": dict(class_events),
                    "captured_member_count": len(class_records),
                }
            )
        family_entries.append(
            {
                "member_key": member_key,
                "art_id": art_id,
                "member_classes": classes,
                "draw_bands": bands[
                    member_key if member_key.startswith("member:") else f"art:{art_id}"
                ],
                "class_members": class_members,
                "union_spatial_envelope": _union_envelope(elements),
                "observed_concurrency_range": [
                    min(per_sample_counts),
                    max(per_sample_counts),
                ],
                "on_fraction": visible_true / len(elements),
                "dominant_visible": visible_true * 2 >= len(elements),
                "events": dict(events),
            }
        )

    ambient_id_counts: Counter[str] = Counter()
    for entry in family_entries:
        base = (
            f"{_slug(identity['screen_id'])}.ambient."
            f"{_slug(entry['member_key'])}"
        )
        ambient_id_counts[base] += 1
        entry["id"] = f"{base}.{ambient_id_counts[base]}"

    ambient_units = len(family_entries)
    peak_census = max(
        measurement["peak_element_count"] for measurement in measurements
    )
    ambient_fraction = ambient_units / peak_census
    if ambient_fraction > maximum_ambient_fraction:
        raise AmbientLifecycleError(
            "ambient lifecycle cap exceeded: "
            f"{ambient_units}/{peak_census} semantic members "
            f"({ambient_fraction:.1%}) exceeds 40% for '{identity['screen_id']}'"
        )

    core_layout = {
        "generation": identity["layout_generation"],
        "screen_id": identity["screen_id"],
        "screen_title": measurements[0]["samples"][0]["payload"].get(
            "screen_title", ""
        ),
        "capture_method": measurements[0]["samples"][0]["payload"].get(
            "capture_method", ""
        ),
        "draw_order_semantics": "structural_core_relative_sequence",
        "elements": core_elements,
    }
    core_hash = sha256_json(core_layout)
    ui_core_ids = [
        element["id"]
        for element in core_elements
        if element.get("kind") == "art"
        and str(element.get("art_id", "")).startswith("UI.")
    ]
    ephemeral_records = [
        record
        for record in resolved_records
        if record["classification"] == "ephemeral"
    ]
    ephemeral_elements = [
        element
        for record in ephemeral_records
        for element in record_elements(record)
    ]
    ephemeral_counts: list[int] = []
    for measurement in measurements:
        captured_ids = {
            record["member"]["captured_element_id"]
            for record in ephemeral_records
            if record["measurement"] is measurement
        }
        ephemeral_counts.extend(
            sum(
                element.get("id") in captured_ids
                for element in sample["payload"]["elements"]
            )
            for sample in measurement["samples"]
        )
    return {
        "settlement_spec": SETTLEMENT_SPEC,
        "criterion": (
            "at least 40 samples over at least 2 seconds with constant surface "
            "and generations; reproduced core is exact, ambient lifecycle is enveloped"
        ),
        "identity": copy.deepcopy(identity),
        "structural_core": core_layout,
        "structural_core_sha256": core_hash,
        "structural_core_element_count": len(core_elements),
        "ui_structural_core_element_ids": ui_core_ids,
        "ambient_family_art_ids": sorted(ambient_family),
        "classification_map": {
            entry["id"]: entry["member_classes"]
            for entry in family_entries
        },
        "animated_element_ids": [
            entry["id"]
            for entry in family_entries
            if "animated" in entry["member_classes"]
        ],
        "visibility_cycling_element_ids": [
            entry["id"]
            for entry in family_entries
            if "visibility_cycling" in entry["member_classes"]
        ],
        "ambient_persistent_element_ids": [
            entry["id"]
            for entry in family_entries
            if "ambient_persistent" in entry["member_classes"]
        ],
        "ambient_members": family_entries,
        "ephemeral_family": {
            "art_ids": sorted(ephemeral_art_ids),
            "union_spatial_envelope": (
                _union_envelope(ephemeral_elements) if ephemeral_elements else None
            ),
            "observed_concurrency_range": (
                [min(ephemeral_counts), max(ephemeral_counts)]
                if ephemeral_counts
                else [0, 0]
            ),
            "draw_bands": {
                art_id: bands[f"art:{art_id}"]
                for art_id in sorted(ephemeral_art_ids)
            },
            "spawn_event_count": total_spawn,
            "despawn_event_count": total_despawn,
            "bidirectional_churn_witnessed": bool(
                not ephemeral_art_ids or (total_spawn and total_despawn)
            ),
        },
        "ambient_semantic_member_count": ambient_units,
        "peak_element_count": peak_census,
        "ambient_fraction": ambient_fraction,
        "motion_capability_corroborations": corroborations,
        "observations": [
            {
                "label": measurement["label"],
                "kind": measurement["kind"],
                "instance": measurement["instance"],
                "process_id": measurement["process_id"],
                "corroboration_anchor": measurement["corroboration_anchor"],
                "sample_count": measurement["sample_count"],
                "stable_span_milliseconds": measurement[
                    "stable_span_milliseconds"
                ],
                "settle_latency_milliseconds": measurement[
                    "settle_latency_milliseconds"
                ],
                "minimum_element_count": measurement["minimum_element_count"],
                "peak_element_count": measurement["peak_element_count"],
                "identity_source": measurement["identity"]["identity_source"],
                **(
                    {"evidence": copy.deepcopy(measurement["evidence"])}
                    if "evidence" in measurement
                    else {}
                ),
            }
            for measurement in measurements
        ],
    }


def validate_ambient_resolution(
    declared: dict[str, Any], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    expected = resolve_ambient_lifecycle(observations)
    declared_map = declared.get("classification_map")
    if isinstance(declared_map, dict):
        expected_map = expected["classification_map"]
        for art_id, classes in declared_map.items():
            if not isinstance(classes, list):
                continue
            phantom = sorted(set(classes) - set(expected_map.get(art_id, [])))
            if phantom:
                raise AmbientLifecycleError(
                    "ambient lifecycle recorder defect: phantom ambient "
                    f"classification '{phantom[0]}' for art family '{art_id}' "
                    "has zero observed events"
                )
    if canonical_bytes(declared) != canonical_bytes(expected):
        raise AmbientLifecycleError(
            "ambient lifecycle resolution proof was not machine-derived"
        )
    return expected


def _provisional_layout(measurement: dict[str, Any]) -> dict[str, Any]:
    first_payload = measurement["samples"][0]["payload"]
    indexed = _elements_by_id(first_payload)
    members = {member["captured_element_id"]: member for member in measurement["members"]}
    elements: list[dict[str, Any]] = []
    for element in _sorted_elements(first_payload):
        element_id = _element_id(element)
        member = members[element_id]
        if member["classification"] == "ephemeral":
            continue
        shaped = copy.deepcopy(element)
        if member["classification"] == "animated":
            shaped.pop("rect", None)
            shaped.pop("unclipped_rect", None)
            shaped["animated_geometry"] = True
            shaped["anchor_rect"] = copy.deepcopy(element["rect"])
            shaped["anchor_unclipped_rect"] = copy.deepcopy(
                element["unclipped_rect"]
            )
            shaped["envelope"] = copy.deepcopy(member["envelope"])
        elif member["classification"] == "visibility_cycling":
            shaped["visibility_cycling"] = True
            shaped["dominant_phase_payload"] = copy.deepcopy(
                member["dominant_phase_payload"]
            )
            shaped["on_fraction"] = member["on_fraction"]
            shaped["toggle_events"] = copy.deepcopy(member["events"]["visible"])
            shaped["envelope"] = copy.deepcopy(member["envelope"])
        elements.append(shaped)
    return {
        key: copy.deepcopy(value)
        for key, value in first_payload.items()
        if key != "elements"
    } | {
        "captured_at_milliseconds": measurement["samples"][0].get(
            "captured_at_milliseconds",
            measurement["samples"][0]["elapsed_milliseconds"],
        ),
        "animated_element_ids": [
            member["captured_element_id"]
            for member in measurement["members"]
            if member["classification"] == "animated"
        ],
        "visibility_cycling_element_ids": [
            member["captured_element_id"]
            for member in measurement["members"]
            if member["classification"] == "visibility_cycling"
        ],
        "ephemeral_art_ids": sorted(
            {
                member["art_id"]
                for member in measurement["members"]
                if member["classification"] == "ephemeral"
            }
        ),
        "elements": elements,
    }


def classify_ambient_window(
    samples: list[dict[str, Any]],
    *,
    label: str = "window",
) -> dict[str, Any]:
    measurement = _measure_window(samples, label=label)
    layout = _provisional_layout(measurement)
    class_counts = Counter(
        member["classification"] for member in measurement["members"]
    )
    structural_projection = {
        "identity": measurement["identity"],
        "full_presence_semantics": sorted(
            member["semantic_signature"]
            for member in measurement["members"]
            if member["classification"] == "full_presence"
        ),
    }
    window_ambient_family = {
        member["art_id"]
        for member in measurement["members"]
        if member["classification"]
        in {"ephemeral", "visibility_cycling", "one_way_spawn_candidate"}
        and member["art_id"]
    }
    non_family_animated_capabilities = {
        member["capability_signature"]
        for member in measurement["members"]
        if member["classification"] == "animated"
        and member["art_id"] not in window_ambient_family
    }
    animated_count = len(non_family_animated_capabilities)
    animated_fraction = animated_count / measurement["peak_element_count"]
    if animated_fraction > MAXIMUM_ANIMATED_FRACTION:
        raise AmbientLifecycleError(
            "animated geometry cap exceeded: "
            f"{animated_count}/{measurement['peak_element_count']} elements "
            f"({animated_fraction:.1%}) exceeds 30% for "
            f"'{measurement['identity']['screen_id']}'"
        )
    return {
        "settlement_spec": SETTLEMENT_SPEC,
        "criterion": (
            "at least 40 consecutive samples spanning at least 2 seconds with "
            "constant surface/generations and every variance assigned to one "
            "measured v2.5 member class"
        ),
        "structural_element_order": "core_relative_sequence_absolute_draw_order_excluded",
        "settle_latency_milliseconds": measurement["settle_latency_milliseconds"],
        "stable_span_milliseconds": measurement["stable_span_milliseconds"],
        "consecutive_structural_samples": measurement["sample_count"],
        "animated_id_set_sample_count": measurement["sample_count"],
        "animated_element_ids": list(layout["animated_element_ids"]),
        "visibility_cycling_element_ids": list(
            layout["visibility_cycling_element_ids"]
        ),
        "ephemeral_art_ids": list(layout["ephemeral_art_ids"]),
        "animated_element_count": animated_count,
        "element_count": measurement["peak_element_count"],
        "minimum_element_count": measurement["minimum_element_count"],
        "animated_fraction": animated_fraction,
        "structural_sha256": sha256_json(structural_projection),
        "window_classification": {
            "identity": measurement["identity"],
            "class_counts": dict(class_counts),
            "members": [
                {
                    key: copy.deepcopy(member[key])
                    for key in (
                        "captured_element_id",
                        "kind",
                        "art_id",
                        "classification",
                        "present_samples",
                        "absent_samples",
                        "capability_signature",
                        "on_fraction",
                        "events",
                        "envelope",
                    )
                }
                for member in measurement["members"]
            ],
        },
        "layout": layout,
    }


def classify_ambient_extended_observation(
    samples: list[dict[str, Any]],
    *,
    required_span_milliseconds: int,
) -> dict[str, Any]:
    minimum_span = max(
        EXTENDED_OBSERVATION_MINIMUM_MILLISECONDS,
        int(required_span_milliseconds),
    )
    measurement = _measure_window(
        samples,
        label="extended_observation",
        minimum_samples=EXTENDED_OBSERVATION_MINIMUM_SAMPLES,
        minimum_span_milliseconds=minimum_span,
    )
    elapsed = [int(sample["elapsed_milliseconds"]) for sample in samples]
    motion_events: list[dict[str, Any]] = []
    lifecycle_events: list[dict[str, Any]] = []
    for member in measurement["members"]:
        element_id = member["captured_element_id"]
        art_id = member["art_id"]
        for event in member["events"]["geometry"]:
            sample_index = int(event["sample_index"])
            motion_events.append(
                {
                    "element_id": element_id,
                    "art_id": art_id,
                    "sample_index": sample_index,
                    "elapsed_milliseconds": elapsed[sample_index],
                    "delta_milliseconds": (
                        elapsed[sample_index] - elapsed[sample_index - 1]
                    ),
                }
            )
        for event_kind in ("membership", "visible"):
            for event in member["events"][event_kind]:
                sample_index = int(event["sample_index"])
                lifecycle_events.append(
                    {
                        "element_id": element_id,
                        "art_id": art_id,
                        "event_kind": event_kind,
                        "sample_index": sample_index,
                        "elapsed_milliseconds": elapsed[sample_index],
                        **{
                            key: copy.deepcopy(value)
                            for key, value in event.items()
                            if key != "sample_index"
                        },
                    }
                )
    motion_events.sort(key=lambda event: (event["sample_index"], event["element_id"]))
    lifecycle_events.sort(
        key=lambda event: (
            event["sample_index"],
            event["element_id"],
            event["event_kind"],
        )
    )
    return {
        "settlement_spec": SETTLEMENT_SPEC,
        "required_span_milliseconds": minimum_span,
        "observed_span_milliseconds": measurement["stable_span_milliseconds"],
        "sample_count": measurement["sample_count"],
        "motion_event_count": len(motion_events),
        "moving_element_ids": sorted(
            {event["element_id"] for event in motion_events}
        ),
        "motion_events": motion_events,
        "lifecycle_event_count": len(lifecycle_events),
        "lifecycle_events": lifecycle_events,
        "window_classification": {
            "identity": measurement["identity"],
            "members": [
                {
                    key: copy.deepcopy(member[key])
                    for key in (
                        "captured_element_id",
                        "kind",
                        "art_id",
                        "classification",
                        "present_samples",
                        "absent_samples",
                        "capability_signature",
                        "events",
                        "envelope",
                    )
                }
                for member in measurement["members"]
            ],
        },
    }


def find_ambient_settled_window(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        raise AmbientLifecycleError(
            "ambient lifecycle settlement contract: capture contained no samples"
        )
    last_error = ""
    for end in range(MINIMUM_SAMPLES - 1, len(samples)):
        start = end - MINIMUM_SAMPLES + 1
        while start > 0 and (
            int(samples[end]["elapsed_milliseconds"])
            - int(samples[start]["elapsed_milliseconds"])
            < MINIMUM_SPAN_MILLISECONDS
        ):
            start -= 1
        window = samples[start : end + 1]
        try:
            result = classify_ambient_window(window)
        except AmbientLifecycleError as error:
            last_error = str(error)
            continue
        window_members = result["window_classification"]["members"]
        window_ephemeral_art_ids = sorted(
            {
                member["art_id"]
                for member in window_members
                if member["classification"]
                in {"ephemeral", "one_way_spawn_candidate"}
                and member["art_id"]
            }
        )
        membership_events = [
            event
            for member in window_members
            if member["art_id"] in window_ephemeral_art_ids
            for event in member["events"]["membership"]
        ]
        if window_ephemeral_art_ids and (
            not any(event["event"] == "spawn" for event in membership_events)
            or not any(
                event["event"] == "despawn" for event in membership_events
            )
        ):
            last_error = (
                "population-versus-ephemeral settlement guardrail: membership-"
                "changing art families lack in-window bidirectional spawn and "
                f"despawn evidence: {window_ephemeral_art_ids}"
            )
            continue
        result["stable_start_index"] = start
        result["stable_end_index"] = end
        result["total_semantic_samples"] = end + 1
        return result
    raise AmbientLifecycleError(
        "capture never reached a Settlement v2.5 window; "
        f"samples={len(samples)} last_candidate='{last_error}'"
    )


def read_samples(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise AmbientLifecycleError(
            f"ambient lifecycle input '{path}' is not a JSON sample list"
        )
    return value
