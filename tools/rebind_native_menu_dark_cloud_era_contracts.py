#!/usr/bin/env python3
"""Rebind exact Dark Cloud era contracts to a qualified resolver re-emission."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from native_menu_dark_cloud_browser_chrome_supersession import (
    require_contract as require_chrome_contract,
    semantic_sha256 as chrome_semantic_sha256,
)
from native_menu_dark_cloud_item_row_supersession import (
    CONTROL_LAYOUT,
    PUBLIC_LAYOUT_MEMBER_IDS,
    require_contract as require_item_contract,
    semantic_sha256 as item_semantic_sha256,
)


class RebindError(RuntimeError):
    """The current candidate is not an exact qualified re-emission."""


LAYOUTS = (
    "dark-cloud-browser",
    "dark-cloud-recent",
    "dark-cloud-online-levels",
    "dark-cloud-my-levels",
)
PROFILE_IDENTITY = (
    "0539412d5c91207d5b225e86f79795d260fe7b73b8d9a1c29166bd09b445e372"
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise RebindError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise RebindError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def receipt(path: Path, recorded_path: str | None = None) -> dict[str, Any]:
    result = {
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }
    if recorded_path is not None:
        return {"path": recorded_path, **result}
    return result


def receipt_matches(recorded: Any, actual: Any) -> bool:
    return isinstance(recorded, dict) and isinstance(actual, dict) and {
        "sha256": recorded.get("sha256"),
        "bytes": recorded.get("bytes"),
    } == {
        "sha256": actual.get("sha256"),
        "bytes": actual.get("bytes"),
    }


def semantic_multiset_sha256(layout: dict[str, Any]) -> str:
    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements or not all(
        isinstance(element, dict) for element in elements
    ):
        raise RebindError("qualified Dark Cloud re-emission reached no element census")
    counter = Counter(item_semantic_sha256(element) for element in elements)
    entries = [
        {"semantic_sha256": digest, "count": counter[digest]}
        for digest in sorted(counter)
    ]
    return hashlib.sha256(canonical_bytes(entries)).hexdigest()


def trace_receipt(header: dict[str, Any], role: str) -> dict[str, Any]:
    value = (
        header.get("raw_recording")
        if role == "primary"
        else header.get("animation_confirmation")
    )
    if not isinstance(value, dict):
        raise RebindError(f"qualified Dark Cloud re-emission lost its {role} trace")
    return {"sha256": value.get("sha256"), "bytes": value.get("bytes")}


def audit_layout_map(audit: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    values = audit.get("layouts")
    if isinstance(values, dict):
        result = {
            key: value for key, value in values.items() if isinstance(value, dict)
        }
    elif isinstance(values, list):
        result = {
            value.get("layout_id"): value
            for value in values
            if isinstance(value, dict) and isinstance(value.get("layout_id"), str)
        }
    else:
        result = {}
    if set(result) != set(LAYOUTS):
        raise RebindError(f"{label} did not reach the exact four-layout census")
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def build_rebind(
    candidate_root: Path,
    item_contract_path: Path,
    chrome_contract_path: Path,
    item_audit_path: Path,
    chrome_audit_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    item_contract = read_object(item_contract_path)
    chrome_contract = read_object(chrome_contract_path)
    require_item_contract(item_contract)
    require_chrome_contract(chrome_contract)
    item_audit = read_object(item_audit_path)
    chrome_audit = read_object(chrome_audit_path)
    if (
        item_audit.get("schema")
        != "solomon-dark-native-menu-dark-cloud-item-row-stop-audit-v1"
        or item_audit.get("status") != "QUESTION"
        or item_audit.get("candidate_applied") is not False
        or chrome_audit.get("schema")
        != "solomon-dark-native-menu-dark-cloud-post-item-stop-audit-v1"
        or chrome_audit.get("status") != "QUESTION"
        or chrome_audit.get("candidate_applied") is not False
    ):
        raise RebindError("qualified Dark Cloud re-emission source audits changed scope")
    if not receipt_matches(item_contract["source_audit"], receipt(item_audit_path)):
        raise RebindError("qualified Dark Cloud re-emission Item-row audit receipt is false")
    if not receipt_matches(chrome_contract["source_audit"], receipt(chrome_audit_path)):
        raise RebindError("qualified Dark Cloud re-emission chrome audit receipt is false")

    item_by_layout = {
        entry["layout_id"]: entry for entry in item_contract["affected_layouts"]
    }
    item_by_layout[CONTROL_LAYOUT] = item_contract["control_layout"]
    chrome_by_layout = {
        entry["layout_id"]: entry for entry in chrome_contract["affected_layouts"]
    }
    item_audits = audit_layout_map(item_audit, "Item-row source audit")
    chrome_audits = audit_layout_map(chrome_audit, "chrome source audit")
    rows: list[dict[str, Any]] = []

    for layout_id in LAYOUTS:
        fixture_path = candidate_root / "menu-layouts" / f"{layout_id}.json"
        fixture = read_object(fixture_path)
        header = fixture.get("header")
        layout = fixture.get("layout")
        if not isinstance(header, dict) or not isinstance(layout, dict):
            raise RebindError(
                f"qualified Dark Cloud re-emission {layout_id} has no header/layout"
            )
        source_settled = item_audits[layout_id].get("settled")
        if not isinstance(source_settled, dict):
            raise RebindError(
                f"qualified Dark Cloud re-emission {layout_id} lost Item-row source data"
            )
        chrome_source = chrome_audits[layout_id]
        source_fixture = source_settled.get("fixture")
        source_chrome_fixture = chrome_source.get("candidate_fixture")
        item_entry = item_by_layout[layout_id]
        item_candidate = (
            item_entry.get("candidate_fixture")
            if layout_id == CONTROL_LAYOUT
            else item_entry.get("superseding_candidate_fixture")
        )
        chrome_candidate = chrome_by_layout[layout_id].get(
            "superseding_candidate_fixture"
        )
        if (
            not receipt_matches(item_candidate, source_fixture)
            or not receipt_matches(chrome_candidate, source_chrome_fixture)
        ):
            raise RebindError(
                f"qualified Dark Cloud re-emission {layout_id} source fixture receipt changed"
            )
        expected_generation = source_settled.get("generation")
        expected_count = source_settled.get("element_count")
        expected_semantic = source_settled.get("semantic_multiset_sha256")
        if (
            layout.get("generation") != expected_generation
            or len(layout.get("elements", [])) != expected_count
            or semantic_multiset_sha256(layout) != expected_semantic
            or layout.get("generation") != chrome_source.get("settled_generation")
            or len(layout.get("elements", []))
            != chrome_source.get("settled_structural_core_element_count")
            or header.get("source", {}).get("profile_state_identity_sha256")
            != PROFILE_IDENTITY
        ):
            raise RebindError(
                f"qualified Dark Cloud re-emission {layout_id} semantic core differs"
            )
        expected_core = chrome_candidate.get("structural_core_sha256")
        if layout.get("structural_core_sha256") != expected_core:
            raise RebindError(
                f"qualified Dark Cloud re-emission {layout_id} structural-core hash differs"
            )
        for role in ("primary", "confirmation"):
            expected_trace = source_settled.get(role, {}).get("recording")
            if not receipt_matches(expected_trace, trace_receipt(header, role)):
                raise RebindError(
                    f"qualified Dark Cloud re-emission {layout_id} {role} trace differs"
                )
        item_rows = [
            element
            for element in layout["elements"]
            if isinstance(element, dict) and element.get("text") == "Item 1"
        ]
        expected_rows = 1 if layout_id == CONTROL_LAYOUT else 0
        if len(item_rows) != expected_rows:
            raise RebindError(
                f"qualified Dark Cloud re-emission {layout_id} Item 1 disposition differs"
            )
        if layout_id == CONTROL_LAYOUT and item_rows[0] != item_entry[
            "retained_member"
        ]["payload"]:
            raise RebindError(
                "qualified Dark Cloud re-emission My Levels retained row differs"
            )

        current_receipt = receipt(fixture_path, item_candidate["path"])
        old_item_receipt = copy.deepcopy(item_candidate)
        old_chrome_receipt = copy.deepcopy(chrome_candidate)
        for target in (item_candidate, chrome_candidate):
            target["sha256"] = current_receipt["sha256"]
            target["bytes"] = current_receipt["bytes"]
        rows.append(
            {
                "layout_id": layout_id,
                "source_candidate_receipt": {
                    "sha256": old_item_receipt["sha256"],
                    "bytes": old_item_receipt["bytes"],
                },
                "source_chrome_receipt": {
                    "sha256": old_chrome_receipt["sha256"],
                    "bytes": old_chrome_receipt["bytes"],
                },
                "qualified_candidate_receipt": current_receipt,
                "generation": layout["generation"],
                "element_count": len(layout["elements"]),
                "semantic_multiset_sha256": expected_semantic,
                "structural_core_sha256": expected_core,
                "profile_state_identity_sha256": PROFILE_IDENTITY,
                "primary_trace_reproduced": True,
                "confirmation_trace_reproduced": True,
            }
        )

    overlay_path = candidate_root / "menu-overlay-reference.json"
    overlay = read_object(overlay_path)
    old_overlay_receipt = copy.deepcopy(chrome_contract["overlay_reference"])
    if not receipt_matches(old_overlay_receipt, chrome_audit.get("overlay_reference")):
        raise RebindError("qualified Dark Cloud re-emission source overlay receipt differs")
    overlay_values = overlay.get("overlay_semantic_draw_multiset")
    if not isinstance(overlay_values, list) or not overlay_values:
        raise RebindError("qualified Dark Cloud re-emission overlay has no real draws")
    actual_overlay: Counter[str] = Counter()
    for value in overlay_values:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("payload"), dict)
            or isinstance(value.get("count"), bool)
            or not isinstance(value.get("count"), int)
            or value["count"] <= 0
        ):
            raise RebindError("qualified Dark Cloud re-emission overlay draw is malformed")
        actual_overlay[chrome_semantic_sha256(value["payload"])] += value["count"]
    source_overlay = Counter(
        member["semantic_sha256"]
        for member in chrome_by_layout[LAYOUTS[0]]["residual_members"]
        if member["classification"] == "beta_dialog_overlay"
    )
    if actual_overlay != source_overlay or sum(actual_overlay.values()) != 15:
        raise RebindError(
            "qualified Dark Cloud re-emission overlay semantic multiset differs"
        )
    current_overlay_receipt = receipt(
        overlay_path, chrome_contract["overlay_reference"]["path"]
    )
    chrome_contract["overlay_reference"].update(
        {
            "sha256": current_overlay_receipt["sha256"],
            "bytes": current_overlay_receipt["bytes"],
        }
    )

    old_item_contract_receipt = receipt(item_contract_path)
    if not receipt_matches(
        chrome_contract["item_row_contract"], old_item_contract_receipt
    ):
        raise RebindError("qualified Dark Cloud re-emission Item-row contract receipt differs")
    audit = {
        "schema": "solomon-dark-native-menu-dark-cloud-era-qualified-reemission-v1",
        "status": "PASS",
        "candidate_applied": False,
        "reason": (
            "Settlement resolver re-emitted only observation receipts after the "
            "chartered 40th edge; exact semantic cores and source traces reproduced"
        ),
        "layout_count": len(rows),
        "layouts": rows,
        "overlay_reference": {
            "source_receipt": old_overlay_receipt,
            "qualified_receipt": current_overlay_receipt,
            "semantic_draw_count": sum(actual_overlay.values()),
            "semantic_multiset_reproduced": True,
        },
        "item_contract_source_receipt": old_item_contract_receipt,
        "no_candidate_member_removed": True,
        "no_authorization_scope_changed": True,
    }
    return item_contract, chrome_contract, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--item-contract", type=Path, required=True)
    parser.add_argument("--chrome-contract", type=Path, required=True)
    parser.add_argument("--item-audit", type=Path, required=True)
    parser.add_argument("--chrome-audit", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    item, chrome, audit = build_rebind(
        args.candidate_root.resolve(),
        args.item_contract.resolve(),
        args.chrome_contract.resolve(),
        args.item_audit.resolve(),
        args.chrome_audit.resolve(),
    )
    if args.apply:
        atomic_json(args.item_contract.resolve(), item)
        chrome["item_row_contract"].update(receipt(args.item_contract.resolve()))
        atomic_json(args.chrome_contract.resolve(), chrome)
    audit["candidate_applied"] = bool(args.apply)
    audit["item_contract_qualified_receipt"] = (
        receipt(args.item_contract.resolve()) if args.apply else None
    )
    audit["chrome_contract_qualified_receipt"] = (
        receipt(args.chrome_contract.resolve()) if args.apply else None
    )
    atomic_json(args.audit_output.resolve(), audit)
    print(json.dumps(audit, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
