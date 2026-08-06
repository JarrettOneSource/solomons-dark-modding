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
    order, indexed = _elements_by_id(payload)
    result["elements"] = [
        _non_geometry_element(indexed[element_id]) for element_id in order
    ]
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
    if order != anchor_order:
        raise SettlementV2Error(
            "structural settlement guardrail: element membership or ordering "
            "varied within the settled window"
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


def structural_layout_bytes(
    layout: dict[str, Any],
    animated_element_ids: Iterable[str] | None = None,
) -> bytes:
    return canonical_bytes(structural_layout(layout, animated_element_ids))


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
        "criterion": (
            "at least 40 consecutive samples spanning at least 2 seconds with "
            "byte-identical structural payloads and an identical measured "
            "animated element-id set"
        ),
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
    if primary_ids != confirmation_ids:
        raise SettlementV2Error(
            "animated ID confirmation mismatch: fresh captures classified "
            f"primary={primary_ids} confirmation={confirmation_ids}"
        )
    if structural_layout_bytes(primary_layout, primary_ids) != (
        structural_layout_bytes(confirmation_layout, confirmation_ids)
    ):
        raise SettlementV2Error(
            "fresh confirmation structural mismatch: animation-independent "
            "menu structure did not reproduce"
        )


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
