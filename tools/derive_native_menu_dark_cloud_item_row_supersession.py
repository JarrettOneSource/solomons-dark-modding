#!/usr/bin/env python3
"""Derive the exact Dark Cloud public-tab Item 1 supersession contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_dark_cloud_item_row_supersession import semantic_sha256
from native_menu_profile_state import (
    FRESH_BASELINE_ID,
    load_profile_state_baseline,
    validate_capture_profile_state,
)


SCHEMA = "solomon-dark-native-menu-dark-cloud-item-row-supersession-v1"
AUDIT_SCHEMA = "solomon-dark-native-menu-dark-cloud-item-row-stop-audit-v1"
PUBLIC_LAYOUTS = (
    "dark-cloud-browser",
    "dark-cloud-recent",
    "dark-cloud-online-levels",
)
CONTROL_LAYOUT = "dark-cloud-my-levels"
ITEM_TEXT = "Item 1"


class DerivationError(RuntimeError):
    """A required exact evidence witness is absent or ambiguous."""


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


def file_receipt(path: Path, root: Path, *, field: str = "path") -> dict[str, Any]:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise DerivationError(f"receipt target escapes its root: {resolved}")
    return {
        field: resolved.relative_to(resolved_root).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def item_rows(layout: dict[str, Any]) -> list[dict[str, Any]]:
    elements = layout.get("elements")
    if not isinstance(elements, list) or not all(
        isinstance(element, dict) for element in elements
    ):
        raise DerivationError("Item 1 derivation reached no real member census")
    return [element for element in elements if element.get("text") == ITEM_TEXT]


def match_audit_receipt(recorded: Any, path: Path, label: str) -> None:
    if not isinstance(recorded, dict) or {
        "sha256": recorded.get("sha256"),
        "bytes": recorded.get("bytes"),
    } != {
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }:
        raise DerivationError(f"{label} audit receipt does not match its file")


def build_contract(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    audit_path: Path,
) -> dict[str, Any]:
    audit = read_object(audit_path)
    if (
        audit.get("schema") != AUDIT_SCHEMA
        or audit.get("status") != "QUESTION"
        or audit.get("affected_layouts") != list(PUBLIC_LAYOUTS)
        or audit.get("control_layout") != CONTROL_LAYOUT
        or audit.get("candidate_applied") is not False
    ):
        raise DerivationError("accepted Item 1 audit changed scope or status")
    baseline = load_profile_state_baseline(repo_root)
    if audit.get("profile_state_identity_sha256") != baseline["identity"]:
        raise DerivationError("Item 1 audit changed the pristine profile identity")

    layouts: list[dict[str, Any]] = []
    old_capture_identities: set[tuple[Any, Any]] = set()
    for layout_id in PUBLIC_LAYOUTS:
        audit_layout = audit.get("layouts", {}).get(layout_id)
        if not isinstance(audit_layout, dict):
            raise DerivationError(f"Item 1 audit missed layout '{layout_id}'")
        snapshot_path = (
            repo_root
            / f"webgame-contracts/baseline-snapshots/menu-layouts/{layout_id}.json"
        )
        landed_path = repo_root / f"tests/fixtures/webgame/menu-layouts/{layout_id}.json"
        candidate_path = candidate_root / f"menu-layouts/{layout_id}.json"
        if snapshot_path.read_bytes() != landed_path.read_bytes():
            raise DerivationError(
                f"{layout_id} historical fixture is not byte-exact in its baseline snapshot"
            )
        match_audit_receipt(
            audit_layout.get("landed", {}).get("fixture"),
            landed_path,
            f"{layout_id} landed fixture",
        )
        match_audit_receipt(
            audit_layout.get("settled", {}).get("fixture"),
            candidate_path,
            f"{layout_id} settled fixture",
        )
        landed_fixture = read_object(snapshot_path)
        candidate_fixture = read_object(candidate_path)
        landed_layout = landed_fixture.get("layout")
        candidate_layout = candidate_fixture.get("layout")
        header = candidate_fixture.get("header")
        if not all(
            isinstance(value, dict)
            for value in (landed_layout, candidate_layout, header)
        ):
            raise DerivationError(f"{layout_id} fixture has no header/layout")
        try:
            profile = validate_capture_profile_state(
                repo_root=repo_root,
                header=header,
                label=f"{layout_id} Item 1 supersession",
                evidence_root=None,
                required_baseline_id=FRESH_BASELINE_ID,
                binding_label=f"layout '{layout_id}'",
            )
        except RuntimeError as error:
            raise DerivationError(str(error)) from error
        if profile["identity"] != baseline["identity"]:
            raise DerivationError(f"{layout_id} changed the pristine profile identity")
        landed_rows = item_rows(landed_layout)
        settled_rows = item_rows(candidate_layout)
        if len(landed_rows) != 1 or settled_rows:
            raise DerivationError(
                f"{layout_id} no longer has exactly one landed and zero settled Item 1 rows"
            )
        expected_id = layout_id.replace("-", "_") + ".text.item_1.1"
        row = landed_rows[0]
        if row.get("id") != expected_id:
            raise DerivationError(f"{layout_id} Item 1 member identity changed")
        primary = audit_layout["settled"].get("primary")
        confirmation = audit_layout["settled"].get("confirmation")
        for role, observation in (("primary", primary), ("confirmation", confirmation)):
            if (
                not isinstance(observation, dict)
                or observation.get("population_item_row_counts") != [0]
                or observation.get("settled_item_row_counts") != [0]
                or observation.get("settled_sample_count", 0) < 40
                or observation.get("settled_span_milliseconds", 0) < 2_000
            ):
                raise DerivationError(
                    f"{layout_id} {role} no longer proves zero Item 1 rows"
                )
        old_capture_identities.add(
            (
                audit_layout["landed"].get("instance"),
                audit_layout["landed"].get("process_id"),
            )
        )
        layouts.append(
            {
                "layout_id": layout_id,
                "screen_id": layout_id.replace("-", "_"),
                "superseded_landed_fixture": {
                    **file_receipt(snapshot_path, repo_root),
                    "generation": landed_layout.get("generation"),
                    "element_count": len(landed_layout["elements"]),
                },
                "superseding_candidate_fixture": {
                    **file_receipt(candidate_path, evidence_root),
                    "generation": candidate_layout.get("generation"),
                    "element_count": len(candidate_layout["elements"]),
                    "structural_core_sha256": candidate_layout.get(
                        "structural_core_sha256"
                    ),
                },
                "superseded_member": {
                    "id": row["id"],
                    "semantic_sha256": semantic_sha256(row),
                    "payload": copy.deepcopy(row),
                },
                "fresh_pair": {
                    "profile_state_identity_sha256": profile["identity"],
                    "primary": copy.deepcopy(primary),
                    "confirmation": copy.deepcopy(confirmation),
                    "settled_item_row_count": 0,
                },
            }
        )
    if old_capture_identities != {("men-title", 16140)}:
        raise DerivationError("Item 1 landed-era captures no longer share one identity")

    control_audit = audit.get("layouts", {}).get(CONTROL_LAYOUT)
    control_snapshot = (
        repo_root
        / f"webgame-contracts/baseline-snapshots/menu-layouts/{CONTROL_LAYOUT}.json"
    )
    control_candidate = candidate_root / f"menu-layouts/{CONTROL_LAYOUT}.json"
    if not isinstance(control_audit, dict):
        raise DerivationError("Item 1 audit lost the My Levels control")
    match_audit_receipt(
        control_audit.get("landed", {}).get("fixture"),
        repo_root / f"tests/fixtures/webgame/menu-layouts/{CONTROL_LAYOUT}.json",
        "My Levels landed fixture",
    )
    match_audit_receipt(
        control_audit.get("settled", {}).get("fixture"),
        control_candidate,
        "My Levels settled fixture",
    )
    control_landed_fixture = read_object(control_snapshot)
    control_candidate_fixture = read_object(control_candidate)
    control_landed = control_landed_fixture["layout"]
    control_settled = control_candidate_fixture["layout"]
    landed_control_rows = item_rows(control_landed)
    settled_control_rows = item_rows(control_settled)
    if len(landed_control_rows) != 1 or len(settled_control_rows) != 1:
        raise DerivationError("My Levels no longer retains exactly one Item 1 row")
    for role in ("primary", "confirmation"):
        observation = control_audit["settled"].get(role)
        if (
            not isinstance(observation, dict)
            or observation.get("population_item_row_counts") != [1]
            or observation.get("settled_item_row_counts") != [1]
        ):
            raise DerivationError(
                f"My Levels {role} no longer proves the retained Item 1 row"
            )

    promoter = audit.get("promoter_stop", {}).get("transcript")
    promoter_path = evidence_root / "raw-v9/dark-cloud-item-row-question/promoter-dark-cloud-item-row-stop.log"
    match_audit_receipt(promoter, promoter_path, "Item 1 promoter STOP")
    return {
        "schema": SCHEMA,
        "settlement_spec": "2.19",
        "class": "evidence_of_era_exact_member_supersession",
        "affected_layouts": layouts,
        "control_layout": {
            "layout_id": CONTROL_LAYOUT,
            "screen_id": "dark_cloud_my_levels",
            "landed_fixture": file_receipt(control_snapshot, repo_root),
            "candidate_fixture": file_receipt(control_candidate, evidence_root),
            "retained_member": {
                "id": settled_control_rows[0]["id"],
                "semantic_sha256": semantic_sha256(settled_control_rows[0]),
                "payload": copy.deepcopy(settled_control_rows[0]),
            },
            "fresh_pair": {
                "profile_state_identity_sha256": baseline["identity"],
                "primary": copy.deepcopy(control_audit["settled"]["primary"]),
                "confirmation": copy.deepcopy(
                    control_audit["settled"]["confirmation"]
                ),
                "settled_item_row_count": 1,
            },
        },
        "source_audit": file_receipt(audit_path, evidence_root),
        "promoter_stop": file_receipt(promoter_path, evidence_root),
        "landed_era_capture_identity": {
            "instance": "men-title",
            "process_id": 16140,
            "profile_state_provenance_present": False,
        },
        "diagnostic_role": (
            "documentation-only My Levels to Browser read-only tab switch; "
            "outcome never changes this exact supersession"
        ),
        "forbidden": [
            "text_filter",
            "candidate_member_removal",
            "dark_cloud_my_levels_removal",
            "another_layout",
            "another_member_id",
            "another_semantic_payload",
        ],
        "derivation": (
            "exactly three unprovenance'd landed-era Item 1 members are "
            "superseded by two-instance pristine zero-row captures; My Levels "
            "retains its independently reproduced row"
        ),
    }


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = build_contract(
        args.repo_root.resolve(),
        args.candidate_root.resolve(),
        args.evidence_root.resolve(),
        args.audit.resolve(),
    )
    write_object(args.output.resolve(), contract)
    print(json.dumps(contract, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
