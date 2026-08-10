#!/usr/bin/env python3
"""Measured selected-tab verification for the Dark Cloud browser family."""

from __future__ import annotations

import hashlib
import json
from typing import Any


EXPECTED_TAB_BY_SCREEN = {
    "dark_cloud_browser": "online_levels",
    "dark_cloud_recent": "recent",
    "dark_cloud_online_levels": "online_levels",
    "dark_cloud_my_levels": "my_levels",
}
TAB_ACTIONS = {
    "recent": "dark_cloud_browser.recent",
    "online_levels": "dark_cloud_browser.online_levels",
    "my_levels": "dark_cloud_browser.my_levels",
}
ENTRY_STATE_STOP = (
    "STOP: dark-cloud browser entry-state contract: the pristine "
    "dark_cloud_browser entry must select online_levels"
)


class NativeMenuBrowserTabError(RuntimeError):
    """A browser layout does not prove one expected selected tab."""


def _recorder_json_value(value: Any) -> Any:
    """Match PowerShell ConvertTo-Json's representation of integral doubles."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_recorder_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _recorder_json_value(item) for key, item in value.items()}
    return value


def _rect(element: dict[str, Any], label: str) -> list[int | float]:
    value = element.get("rect")
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in value
        )
    ):
        raise NativeMenuBrowserTabError(f"{label} has a malformed rect")
    return value


def _geometry_sha256(measurements: list[dict[str, Any]]) -> str:
    geometry_bytes = json.dumps(
        _recorder_json_value(measurements),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(geometry_bytes).hexdigest()


def _semantic_measurements(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exclude screen-local synthetic ordinals from a measured tab receipt."""
    fields = (
        "tab",
        "action_id",
        "bracket_top",
        "control_rect",
        "bracket_rects",
    )
    return [{field: item.get(field) for field in fields} for item in measurements]


def _validated_receipt_measurements(
    receipt: dict[str, Any], label: str
) -> list[dict[str, Any]]:
    measurements = receipt.get("measurements")
    member_ids = receipt.get("member_ids")
    if (
        not isinstance(measurements, list)
        or len(measurements) != len(TAB_ACTIONS)
        or not all(isinstance(item, dict) for item in measurements)
        or not isinstance(member_ids, list)
        or len(member_ids) != 6
        or not all(isinstance(item, str) and item for item in member_ids)
        or len(set(member_ids)) != 6
    ):
        raise NativeMenuBrowserTabError(
            f"{label} records a malformed capture-time browser-tab verification receipt"
        )
    bracket_ids: list[str] = []
    for measurement in measurements:
        ids = measurement.get("bracket_ids")
        if (
            not isinstance(ids, list)
            or len(ids) != 2
            or not all(isinstance(item, str) and item for item in ids)
            or not isinstance(measurement.get("control_id"), str)
            or not measurement["control_id"]
        ):
            raise NativeMenuBrowserTabError(
                f"{label} records a malformed capture-time browser-tab verification receipt"
            )
        bracket_ids.extend(ids)
    if sorted(bracket_ids) != member_ids or receipt.get(
        "geometry_sha256"
    ) != _geometry_sha256(measurements):
        raise NativeMenuBrowserTabError(
            f"{label} records a false capture-time browser-tab verification receipt"
        )
    return measurements


def resolve_browser_tab(layout: dict[str, Any], label: str) -> dict[str, Any]:
    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements:
        raise NativeMenuBrowserTabError(
            f"{label} browser tab verification reached no layout elements"
        )
    if not all(isinstance(element, dict) for element in elements):
        raise NativeMenuBrowserTabError(
            f"{label} browser tab verification reached a non-object member"
        )
    art = [
        element
        for element in elements
        if element.get("kind") == "art" and element.get("art_id") == "UI.13"
    ]
    measurements: list[dict[str, Any]] = []
    geometry_ids: list[str] = []
    for tab, action_id in TAB_ACTIONS.items():
        controls = [
            element
            for element in elements
            if element.get("kind") == "control"
            and element.get("action_id") == action_id
        ]
        if len(controls) != 1:
            raise NativeMenuBrowserTabError(
                f"{label} did not resolve exactly one '{action_id}' control"
            )
        control = controls[0]
        control_rect = _rect(control, f"{label} {action_id} control")
        left = [
            element
            for element in art
            if _rect(element, f"{label} UI.13 member")[0] == control_rect[0]
        ]
        right = [
            element
            for element in art
            if _rect(element, f"{label} UI.13 member")[2] == control_rect[2]
        ]
        if len(left) != 1 or len(right) != 1 or left[0] is right[0]:
            raise NativeMenuBrowserTabError(
                f"{label} did not resolve one measured UI.13 pair for '{action_id}'"
            )
        left_rect = _rect(left[0], f"{label} {action_id} left bracket")
        right_rect = _rect(right[0], f"{label} {action_id} right bracket")
        if left_rect[1] != right_rect[1]:
            raise NativeMenuBrowserTabError(
                f"{label} has a split vertical bracket pair for '{action_id}'"
            )
        ids = [left[0].get("id"), right[0].get("id")]
        if not all(isinstance(value, str) and value for value in ids):
            raise NativeMenuBrowserTabError(
                f"{label} measured bracket pair has no exact member ids"
            )
        geometry_ids.extend(ids)
        measurements.append(
            {
                "tab": tab,
                "action_id": action_id,
                "control_id": control.get("id"),
                "bracket_ids": ids,
                "bracket_top": left_rect[1],
                "control_rect": control_rect,
                "bracket_rects": [left_rect, right_rect],
            }
        )
    if len(geometry_ids) != 6 or len(set(geometry_ids)) != 6:
        raise NativeMenuBrowserTabError(
            f"{label} did not reach six distinct geometry-bearing bracket members"
        )
    tops = [measurement["bracket_top"] for measurement in measurements]
    minimum = min(tops)
    selected = [
        measurement for measurement in measurements if measurement["bracket_top"] == minimum
    ]
    if len(selected) != 1 or len(set(tops)) != 2:
        raise NativeMenuBrowserTabError(
            f"{label} did not resolve one selected tab from bracket geometry"
        )
    return {
        "measured_tab": selected[0]["tab"],
        "member_ids": sorted(geometry_ids),
        "geometry_sha256": _geometry_sha256(measurements),
        "measurements": measurements,
    }


def validate_browser_tab(
    *,
    screen_tag: str,
    layout: dict[str, Any],
    receipt: object,
    label: str,
) -> dict[str, Any] | None:
    expected = EXPECTED_TAB_BY_SCREEN.get(screen_tag)
    if expected is None:
        if receipt is not None:
            raise NativeMenuBrowserTabError(
                f"{label} non-browser layout carries browser-tab provenance"
            )
        return None
    measured = resolve_browser_tab(layout, label)
    if measured["measured_tab"] != expected:
        prefix = ENTRY_STATE_STOP if screen_tag == "dark_cloud_browser" else (
            "STOP: native-menu browser tab agreement rejected"
        )
        raise NativeMenuBrowserTabError(
            f"{prefix}: measured '{measured['measured_tab']}' for '{screen_tag}'"
        )
    if not isinstance(receipt, dict):
        raise NativeMenuBrowserTabError(
            f"{label} has no capture-time browser-tab verification receipt"
        )
    receipt_measurements = _validated_receipt_measurements(receipt, label)
    if (
        receipt.get("expected_tab") != expected
        or receipt.get("measured_tab") != measured["measured_tab"]
        or _semantic_measurements(receipt_measurements)
        != _semantic_measurements(measured["measurements"])
    ):
        raise NativeMenuBrowserTabError(
            f"{label} records a false capture-time browser-tab verification receipt"
        )
    return measured
