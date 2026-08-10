#!/usr/bin/env python3
"""Derive the exact four-layout Dark Cloud browser-chrome era record."""

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
    EXPECTED_BROWSER_CHROME_COUNT,
    EXPECTED_BROWSER_CHROME_MULTIPLICITIES,
    EXPECTED_OVERLAY_COUNT,
    EXPECTED_RESIDUAL_COUNT,
    FORBIDDEN,
    LAYOUTS,
    SCHEMA,
    audit_multiset_sha256,
    multiset_sha256,
    require_contract,
    semantic_multiset,
    semantic_sha256,
)
from native_menu_dark_cloud_item_row_supersession import (
    consume_exact_landed_residual as consume_item_row,
    require_contract as require_item_contract,
)
from native_menu_landed_diagnosis_v25 import (
    _overlay_counter,
    _population_evidence,
    _signature,
    canonical_bytes,
    match_ambient_members,
    match_overlay_members,
    match_population_members,
    project_structural_core,
)
from native_menu_overlay_v25 import overlay_draw_payload


class DerivationError(RuntimeError):
    """The accepted audit does not derive the exact bounded record."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise DerivationError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise DerivationError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    base = root.resolve()
    if not resolved.is_relative_to(base):
        raise DerivationError(f"receipt target escapes root: {resolved}")
    return {
        "path": resolved.relative_to(base).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def fixture_receipt(path: Path, root: Path, layout: dict[str, Any]) -> dict[str, Any]:
    value = receipt(path, root)
    value.update(
        generation=layout.get("generation"),
        element_count=len(layout.get("elements", [])),
    )
    return value


def candidate_receipt(
    path: Path, root: Path, layout: dict[str, Any]
) -> dict[str, Any]:
    value = fixture_receipt(path, root, layout)
    value["structural_core_sha256"] = layout.get("structural_core_sha256")
    return value


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def trace_absence(
    trace: dict[str, Any], residual: list[dict[str, Any]], label: str
) -> dict[str, Any]:
    evidence = _population_evidence(trace, label)
    signatures = Counter(_signature(element) for element in residual)
    for signature, expected_count in signatures.items():
        if expected_count <= 0:
            raise DerivationError(f"{label} contains an invalid residual counter")
        if any(
            counter[signature]
            for counter in (*evidence["phase_counters"], *evidence["settled_counters"])
        ):
            raise DerivationError(f"{label} contains a pinned landed-era member")
    header = trace.get("header")
    if not isinstance(header, dict):
        raise DerivationError(f"{label} has no machine-derived capture identity")
    return {
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "population_element_counts": evidence["element_count_trace"],
        "population_generations": evidence["generation_trace"],
        "settled_sample_count": evidence["settled_sample_count"],
        "all_residual_members_absent": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    candidate = args.candidate_root.resolve()
    evidence = args.evidence_root.resolve()
    audit_path = args.source_audit.resolve()
    audit = read_object(audit_path)
    if (
        audit.get("status") != "QUESTION"
        or audit.get("candidate_applied") is not False
        or audit.get("cross_layout", {}).get("unclassified_member_count")
        != EXPECTED_BROWSER_CHROME_COUNT
        or audit.get("cross_layout", {}).get(
            "overlay_reference_submultiset_match_count"
        )
        != EXPECTED_OVERLAY_COUNT
    ):
        raise DerivationError("accepted post-Item audit no longer has its exact census")

    item_contract_path = (
        repo
        / "tests/fixtures/webgame/native-menu-dark-cloud-item-row-supersession-v219.json"
    )
    item_contract = read_object(item_contract_path)
    require_item_contract(item_contract)
    overlay_path = candidate / "menu-overlay-reference.json"
    overlay = read_object(overlay_path)
    available_overlay = _overlay_counter(overlay)
    audit_by_layout = {
        entry.get("layout_id"): entry
        for entry in audit.get("layouts", [])
        if isinstance(entry, dict)
    }
    if set(audit_by_layout) != set(LAYOUTS):
        raise DerivationError("accepted post-Item audit has an ambiguous layout census")

    entries: list[dict[str, Any]] = []
    browser_multisets: list[str] = []
    total_multisets: list[Counter[str]] = []
    era_generations: dict[str, int] = {}
    for layout_id in LAYOUTS:
        landed_path = (
            repo
            / f"webgame-contracts/baseline-snapshots/menu-layouts/{layout_id}.json"
        )
        current_path = repo / f"tests/fixtures/webgame/menu-layouts/{layout_id}.json"
        candidate_path = candidate / f"menu-layouts/{layout_id}.json"
        if landed_path.read_bytes() != current_path.read_bytes():
            raise DerivationError(f"{layout_id} landed fixture changed before derivation")
        landed_fixture = read_object(landed_path)
        candidate_fixture = read_object(candidate_path)
        landed = landed_fixture.get("layout")
        settled = candidate_fixture.get("layout")
        if not isinstance(landed, dict) or not isinstance(settled, dict):
            raise DerivationError(f"{layout_id} has no comparable layout")
        primary_path = candidate / f"menu-settlement-traces/{layout_id}.settlement.json"
        confirmation_path = (
            candidate
            / f"menu-animation-confirmations/{layout_id}.confirmation.json"
        )
        primary = read_object(primary_path)
        confirmation = read_object(confirmation_path)
        _, residual = project_structural_core(landed, settled)
        _, _, unmatched = match_ambient_members(residual, settled)
        _, after_population, _ = match_population_members(
            unmatched,
            landed.get("generation"),
            settled.get("generation"),
            primary,
            confirmation,
        )
        _, after_item = consume_item_row(
            layout_id,
            landed,
            settled,
            after_population,
            item_contract,
            {"sha256": file_sha256(landed_path), "bytes": landed_path.stat().st_size},
            {
                "sha256": file_sha256(candidate_path),
                "bytes": candidate_path.stat().st_size,
            },
        )
        if len(after_item) != EXPECTED_RESIDUAL_COUNT:
            raise DerivationError(f"{layout_id} residual is not exactly 28 draws")
        overlay_gate_match, overlay_gate_residual = match_overlay_members(
            after_item, overlay
        )
        if overlay_gate_match or overlay_gate_residual != after_item:
            raise DerivationError(f"{layout_id} unexpectedly passes the v2.4 gate")

        remaining_overlay = available_overlay.copy()
        member_records: list[dict[str, Any]] = []
        browser_members: list[dict[str, Any]] = []
        overlay_count = 0
        for element in after_item:
            signature = canonical_bytes(overlay_draw_payload(element))
            if remaining_overlay[signature] > 0:
                remaining_overlay[signature] -= 1
                classification = "beta_dialog_overlay"
                overlay_count += 1
            else:
                classification = "browser_chrome_era"
                browser_members.append(element)
            member_records.append(
                {
                    "captured_id": element["id"],
                    "semantic_sha256": semantic_sha256(element),
                    "classification": classification,
                    "payload": copy.deepcopy(element),
                }
            )
        if any(remaining_overlay.values()) or overlay_count != EXPECTED_OVERLAY_COUNT:
            raise DerivationError(f"{layout_id} does not contain the complete overlay")
        browser_multiplicities = Counter(
            str(element.get("art_id")) for element in browser_members
        )
        if dict(browser_multiplicities) != EXPECTED_BROWSER_CHROME_MULTIPLICITIES:
            raise DerivationError(f"{layout_id} browser-chrome multiplicities changed")
        browser_audit_sha = audit_multiset_sha256(browser_members)
        if browser_audit_sha != audit_by_layout[layout_id].get(
            "unclassified_semantic_multiset_sha256"
        ):
            raise DerivationError(f"{layout_id} no longer reproduces audit f66bc15e")
        browser_multisets.append(browser_audit_sha)
        total_counter = semantic_multiset(after_item)
        total_multisets.append(total_counter)
        primary_absence = trace_absence(primary, after_item, f"{layout_id} primary")
        confirmation_absence = trace_absence(
            confirmation, after_item, f"{layout_id} confirmation"
        )
        if (
            primary_absence["instance"] == confirmation_absence["instance"]
            and primary_absence["process_id"] == confirmation_absence["process_id"]
        ):
            raise DerivationError(f"{layout_id} pair is not independent")
        entries.append(
            {
                "layout_id": layout_id,
                "screen_id": layout_id.replace("-", "_"),
                "superseded_landed_fixture": fixture_receipt(
                    landed_path, repo, landed
                ),
                "superseding_candidate_fixture": candidate_receipt(
                    candidate_path, evidence, settled
                ),
                "residual_semantic_multiset_sha256": multiset_sha256(total_counter),
                "residual_members": member_records,
                "fresh_pair": {
                    "primary": {
                        **primary_absence,
                        "trace": receipt(primary_path, evidence),
                    },
                    "confirmation": {
                        **confirmation_absence,
                        "trace": receipt(confirmation_path, evidence),
                    },
                    "all_residual_members_absent": True,
                },
            }
        )
        era_generations[layout_id] = int(landed["generation"])

    if len(set(browser_multisets)) != 1 or not all(
        counter == total_multisets[0] for counter in total_multisets[1:]
    ):
        raise DerivationError("the four layouts do not share exact residual semantics")
    era_identity = audit_by_layout[LAYOUTS[0]].get("landed_capture_identity")
    if not all(
        entry.get("landed_capture_identity") == era_identity
        for entry in audit_by_layout.values()
    ):
        raise DerivationError("the four layouts do not share the pinned era identity")

    contract = {
        "schema": SCHEMA,
        "settlement_spec": "2.19",
        "class": "exact_landed_era_residual_supersession",
        "affected_layouts": entries,
        "source_audit": receipt(audit_path, evidence),
        "item_row_contract": receipt(item_contract_path, repo),
        "overlay_reference": receipt(overlay_path, evidence),
        "landed_era_capture_identity": {
            **era_identity,
            "layout_generations": era_generations,
        },
        "mechanistic_split": {
            "total_residual_count": EXPECTED_RESIDUAL_COUNT,
            "beta_dialog_overlay_count": EXPECTED_OVERLAY_COUNT,
            "browser_chrome_era_count": EXPECTED_BROWSER_CHROME_COUNT,
            "browser_chrome_art_id_multiplicities": (
                EXPECTED_BROWSER_CHROME_MULTIPLICITIES
            ),
            "browser_chrome_semantic_multiset_sha256": browser_multisets[0],
            "v2_4_overlay_gate_unchanged": True,
        },
        "application": {
            "side": "landed_residual_only",
            "mode": "all_or_nothing_per_layout",
            "candidate_member_removed": False,
            "fresh_member_presence": "stop_not_filter",
        },
        "forbidden": FORBIDDEN,
        "derivation": {
            "machine_derived": True,
            "canonical_member_identity": "semantic_payload_excluding_synthetic_id_and_absolute_draw_order",
            "unclassified_audit_sha256": browser_multisets[0],
            "candidate_applied_during_derivation": False,
        },
    }
    require_contract(contract)
    write_object(args.output.resolve(), contract)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "sha256": file_sha256(args.output.resolve()),
                "bytes": args.output.resolve().stat().st_size,
                "layout_count": len(entries),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
