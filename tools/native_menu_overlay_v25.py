#!/usr/bin/env python3
"""Settlement v2.5 beta-dialog overlay derivation and hygiene."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Any, Iterable


OVERLAY_REFERENCE_SCHEMA = "solomon-dark-native-menu-overlay-reference-v3"


class OverlayV25Error(ValueError):
    """The derived overlay identity or a hygiene claim is false."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _core(value: dict[str, Any], label: str) -> dict[str, Any]:
    core = value.get("structural_core", value)
    if not isinstance(core, dict):
        raise OverlayV25Error(
            f"overlay reference derivation: {label} has no structural core"
        )
    elements = core.get("elements")
    if not isinstance(elements, list) or not elements:
        raise OverlayV25Error(
            f"overlay reference derivation: {label} structural core is empty"
        )
    if not all(isinstance(element, dict) for element in elements):
        raise OverlayV25Error(
            f"overlay reference derivation: {label} core contains a non-object member"
        )
    return core


def overlay_draw_payload(element: dict[str, Any]) -> dict[str, Any]:
    if element.get("kind") != "art":
        raise OverlayV25Error(
            "overlay semantic identity contract: overlay members must be art draws"
        )
    art_id = element.get("art_id")
    if not isinstance(art_id, str) or not art_id:
        raise OverlayV25Error(
            "overlay semantic identity contract: overlay art draw has no art_id"
        )
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in {"id", "draw_order", "draw_order_semantics"}
    }


def semantic_draw_counter(elements: Iterable[dict[str, Any]]) -> Counter[bytes]:
    counter: Counter[bytes] = Counter()
    for element in elements:
        if element.get("kind") != "art":
            continue
        counter[canonical_bytes(overlay_draw_payload(element))] += 1
    return counter


def _reference_counter(reference: dict[str, Any], label: str) -> Counter[bytes]:
    entries = reference.get("overlay_semantic_draw_multiset")
    if not isinstance(entries, list) or not entries:
        raise OverlayV25Error(
            f"overlay reference corroboration: {label} has no semantic draw multiset"
        )
    counter: Counter[bytes] = Counter()
    previous: bytes | None = None
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise OverlayV25Error(
                f"overlay reference corroboration: {label} entry {index} is not an object"
            )
        count = entry.get("count")
        payload = entry.get("payload")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
            or not isinstance(payload, dict)
        ):
            raise OverlayV25Error(
                f"overlay reference corroboration: {label} entry {index} is incomplete"
            )
        signature = canonical_bytes(payload)
        if previous is not None and signature <= previous:
            raise OverlayV25Error(
                f"overlay reference corroboration: {label} multiset is not canonical"
            )
        previous = signature
        counter[signature] = count
    return counter


def _entries(counter: Counter[bytes]) -> list[dict[str, Any]]:
    return [
        {
            "count": counter[signature],
            "payload": json.loads(signature.decode("utf-8")),
        }
        for signature in sorted(counter)
        if counter[signature] > 0
    ]


def derive_overlay_reference(
    beta_notice: dict[str, Any],
    main_menu_root: dict[str, Any],
    create_corroboration: dict[str, Any],
    pause_corroboration: dict[str, Any],
) -> dict[str, Any]:
    beta_core = _core(beta_notice, "beta_notice")
    main_core = _core(main_menu_root, "main_menu_root")
    beta_elements = beta_core["elements"]
    main_elements = main_core["elements"]

    beta_title = semantic_draw_counter(
        element
        for element in beta_elements
        if str(element.get("art_id", "")).startswith("Title.")
    )
    main_title = semantic_draw_counter(
        element
        for element in main_elements
        if str(element.get("art_id", "")).startswith("Title.")
    )
    missing_title = main_title - beta_title
    extra_title = beta_title - main_title
    if missing_title:
        raise OverlayV25Error(
            "overlay reference derivation: title-core member is missing from "
            "beta_notice structural core"
        )
    if extra_title:
        raise OverlayV25Error(
            "overlay reference derivation: beta_notice leaves a title-side residual"
        )

    beta_draws = semantic_draw_counter(beta_elements)
    main_draws = semantic_draw_counter(main_elements)
    main_residual = main_draws - beta_draws
    if main_residual:
        raise OverlayV25Error(
            "overlay reference derivation: main_menu_root art core does not embed "
            "completely in beta_notice"
        )
    derived = beta_draws - main_draws
    if not derived:
        raise OverlayV25Error(
            "overlay reference derivation: beta_notice minus main_menu_root is empty"
        )

    create_counter = _reference_counter(create_corroboration, "Create")
    pause_counter = _reference_counter(pause_corroboration, "pause")
    if derived != create_counter or derived != pause_counter:
        raise OverlayV25Error(
            "overlay reference corroboration: derived beta-dialog multiset does "
            "not equal the proven Create and pause correction multisets"
        )
    entries = _entries(derived)
    return {
        "schema": OVERLAY_REFERENCE_SCHEMA,
        "header": {
            "derivation": (
                "beta_notice structural art core minus embedded main_menu_root "
                "structural art core"
            ),
            "ordinal_identity": "positional_bookkeeping_excluded",
            "beta_notice_core_sha256": hashlib.sha256(
                canonical_bytes(beta_core)
            ).hexdigest(),
            "main_menu_root_core_sha256": hashlib.sha256(
                canonical_bytes(main_core)
            ).hexdigest(),
            "create_corroboration_sha256": hashlib.sha256(
                canonical_bytes(create_corroboration)
            ).hexdigest(),
            "pause_corroboration_sha256": hashlib.sha256(
                canonical_bytes(pause_corroboration)
            ).hexdigest(),
        },
        "overlay_semantic_draw_multiset": entries,
        "overlay_semantic_draw_count": sum(derived.values()),
    }


def overlay_semantic_multiset_is_present(
    layout: dict[str, Any], reference: dict[str, Any]
) -> bool:
    required = _reference_counter(reference, "hygiene reference")
    elements = layout.get("elements")
    if not isinstance(elements, list) or not all(
        isinstance(element, dict) for element in elements
    ):
        raise OverlayV25Error(
            "overlay hygiene contract: sampled layout has no element objects"
        )
    observed = semantic_draw_counter(elements)
    return not bool(required - observed)


def assert_overlay_hygiene(
    layout: dict[str, Any], reference: dict[str, Any]
) -> None:
    screen_id = layout.get("screen_id")
    if screen_id == "beta_notice":
        return
    if overlay_semantic_multiset_is_present(layout, reference):
        raise OverlayV25Error(
            "overlay hygiene contract: non-overlay screen contains the complete "
            "derived beta-dialog semantic multiset"
        )
