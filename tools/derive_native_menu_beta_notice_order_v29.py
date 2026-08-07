#!/usr/bin/env python3
"""Derive the bounded v2.9 beta-notice order contract from sealed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


PREVIEW_SOURCE_COMMIT = "b3eafc6c4ebccd574f534796203c7c7bea702280"
PREVIEW_SOURCE_PATH = "webgame/client/ambient-title-data.json"


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preview_blob(repo_root: Path) -> bytes:
    process = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "show",
            f"{PREVIEW_SOURCE_COMMIT}:{PREVIEW_SOURCE_PATH}",
        ],
        check=True,
        capture_output=True,
    )
    if not process.stdout:
        raise ValueError("v2.9 preview paint source is empty")
    return process.stdout


def paint_key(art_id: str, rect: list[Any]) -> str:
    if len(rect) != 4 or not all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in rect
    ):
        raise ValueError("v2.9 moved member has no four-number rectangle")
    return f"{art_id}|" + ",".join(f"{float(value):.1f}" for value in rect)


def build_contract(repo_root: Path, audit_path: Path) -> dict[str, Any]:
    audit = read_object(audit_path)
    if (
        audit.get("schema")
        != "solomon-dark-native-menu-landed-core-order-stop-audit-v1"
        or audit.get("layout_id") != "beta-notice"
        or audit.get("semantic_members_missing_from_landed") != 0
        or audit.get("all_moved_members_belong_to_derived_overlay_reference")
        is not True
    ):
        raise ValueError("sealed v2.9 STOP audit does not prove the bounded claim")
    moved = audit.get("moved_core_members")
    lcs_count = audit.get("longest_common_subsequence_count")
    moved_count = audit.get("moved_core_member_count")
    if (
        not isinstance(moved, list)
        or not moved
        or moved_count != len(moved)
        or isinstance(lcs_count, bool)
        or not isinstance(lcs_count, int)
    ):
        raise ValueError("sealed v2.9 STOP audit has no unambiguous moved-member census")

    blob = preview_blob(repo_root)
    preview = json.loads(blob.decode("utf-8"))
    if not isinstance(preview, dict):
        raise ValueError("v2.9 preview paint source is not an object")
    static_order = preview.get("staticOrder")
    provenance = preview.get("_provenance")
    if not isinstance(static_order, dict) or not static_order:
        raise ValueError("v2.9 preview paint source has no static-order census")
    if not isinstance(provenance, dict):
        raise ValueError("v2.9 preview paint source has no provenance")

    members: list[dict[str, Any]] = []
    for item in moved:
        if not isinstance(item, dict):
            raise ValueError("v2.9 STOP audit moved-member entry is not an object")
        art_id = item.get("art_id")
        rect = item.get("rect")
        if not isinstance(art_id, str) or not isinstance(rect, list):
            raise ValueError("v2.9 STOP audit moved-member identity is incomplete")
        key = paint_key(art_id, rect)
        native_paint_order = static_order.get(key)
        if isinstance(native_paint_order, bool) or not isinstance(
            native_paint_order, int
        ):
            raise ValueError(
                f"v2.9 preview paint source does not identify moved member {key}"
            )
        semantic_sha256 = item.get("semantic_sha256")
        if (
            not isinstance(semantic_sha256, str)
            or len(semantic_sha256) != 64
        ):
            raise ValueError("v2.9 STOP audit moved-member semantic hash is invalid")
        members.append(
            {
                "art_id": art_id,
                "rect": rect,
                "unclipped_rect": item.get("unclipped_rect"),
                "semantic_sha256": semantic_sha256,
                "landed_relative_core_index": item.get("relative_core_index"),
                "settled_relative_core_index": item.get(
                    "settled_relative_core_index"
                ),
                "captured_draw_order": item.get("captured_draw_order"),
                "native_paint_order": native_paint_order,
                "overlay_reference_member": item.get(
                    "overlay_reference_member"
                ),
            }
        )

    members.sort(key=lambda item: item["landed_relative_core_index"])
    core_count = lcs_count + len(members)
    landed_indexes = [item["landed_relative_core_index"] for item in members]
    settled_indexes = [item["settled_relative_core_index"] for item in members]
    paint_orders = [item["native_paint_order"] for item in members]
    if landed_indexes != list(range(landed_indexes[0], landed_indexes[0] + len(members))):
        raise ValueError("v2.9 landed moved-member positions are not contiguous")
    if settled_indexes != list(range(core_count - len(members), core_count)):
        raise ValueError("v2.9 settled moved-member positions are not final")
    if paint_orders != sorted(paint_orders) or paint_orders[-1] != max(
        value for value in static_order.values() if isinstance(value, int)
    ):
        raise ValueError("v2.9 settled moved-member sequence is not final native paint order")

    return {
        "schema": "solomon-dark-native-menu-beta-notice-order-v29",
        "layout_id": "beta-notice",
        "screen_id": "beta_notice",
        "core_member_count": core_count,
        "longest_common_subsequence_count": lcs_count,
        "moved_members": members,
        "source_stop_audit": {
            "evidence_filename": audit_path.name,
            "sha256": file_sha256(audit_path),
            "bytes": audit_path.stat().st_size,
        },
        "paint_truth": {
            "repository_path": PREVIEW_SOURCE_PATH,
            "introducing_commit": PREVIEW_SOURCE_COMMIT,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "provenance_sha256": hashlib.sha256(
                canonical_bytes(provenance)
            ).hexdigest(),
            "method": provenance.get("method"),
        },
        "derivation": (
            "sealed v2.8 STOP audit moved-member identities joined by art_id and "
            "exact rect to the provenance-pinned native static paint-order table"
        ),
    }


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--stop-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = build_contract(args.repo_root.resolve(), args.stop_audit.resolve())
    write_object(args.output.resolve(), contract)
    print(json.dumps(contract, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
