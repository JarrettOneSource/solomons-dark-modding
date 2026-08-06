#!/usr/bin/env python3
"""Derive the beta-dialog overlay semantic multiset from live captures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_settlement_v2 import (
    OVERLAY_REFERENCE_SCHEMA,
    SettlementV2Error,
    derive_overlay_reference,
    validate_overlay_reference,
)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SettlementV2Error(f"{path} is not a JSON object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved_root = evidence_root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise SettlementV2Error(
            f"overlay reference input {resolved_path} escapes {resolved_root}"
        )
    return {
        "evidence_path": resolved_path.relative_to(resolved_root).as_posix(),
        "sha256": sha256(resolved_path),
        "bytes": resolved_path.stat().st_size,
    }


def build_reference(
    overlay_path: Path,
    clean_path: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    overlay_fixture = read_object(overlay_path)
    clean_fixture = read_object(clean_path)
    if (
        overlay_fixture.get("schema") != "solomon-dark-native-menu-layout-v2"
        or clean_fixture.get("schema") != "solomon-dark-native-menu-layout-v2"
    ):
        raise SettlementV2Error(
            "overlay reference inputs must be live native-menu layout fixtures"
        )
    overlay_header = overlay_fixture.get("header")
    clean_header = clean_fixture.get("header")
    overlay_layout = overlay_fixture.get("layout")
    clean_layout = clean_fixture.get("layout")
    if not all(
        isinstance(value, dict)
        for value in (
            overlay_header,
            clean_header,
            overlay_layout,
            clean_layout,
        )
    ):
        raise SettlementV2Error("overlay reference inputs are incomplete")
    overlay_source = overlay_header.get("source")
    clean_source = clean_header.get("source")
    if not isinstance(overlay_source, dict) or not isinstance(clean_source, dict):
        raise SettlementV2Error(
            "overlay reference captures have no machine-derived provenance"
        )
    binary_fields = ("game_executable_sha256", "loader_dll_sha256")
    if any(
        overlay_source.get(field) != clean_source.get(field)
        for field in binary_fields
    ):
        raise SettlementV2Error(
            "overlay reference captures do not share exact native binary provenance"
        )
    if overlay_header.get("label") != clean_header.get("label"):
        raise SettlementV2Error(
            "overlay reference captures do not identify the same underlying screen"
        )
    derived = derive_overlay_reference(overlay_layout, clean_layout)
    reference = {
        "schema": OVERLAY_REFERENCE_SCHEMA,
        "header": {
            "derivation": (
                "art draws present in the segregated pre-dismissal capture "
                "and absent from the settled post-dismissal capture of the "
                "same exact underlying screen"
            ),
            "underlying_screen": overlay_header.get("label"),
            "native_binary_provenance": {
                field: overlay_source[field] for field in binary_fields
            },
            "overlay_capture": evidence_receipt(
                overlay_path,
                evidence_root,
            ),
            "clean_capture": evidence_receipt(
                clean_path,
                evidence_root,
            ),
        },
        **derived,
    }
    validate_overlay_reference(reference)
    return reference


def write_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay-capture", type=Path, required=True)
    parser.add_argument("--clean-capture", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        reference = build_reference(
            args.overlay_capture.resolve(),
            args.clean_capture.resolve(),
            args.evidence_root.resolve(),
        )
        write_atomically(args.output.resolve(), reference)
    except (OSError, SettlementV2Error, ValueError) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(
        json.dumps(
            {
                "success": True,
                "output": str(args.output.resolve()),
                "semantic_draw_count": sum(
                    entry["count"]
                    for entry in reference["overlay_semantic_draw_multiset"]
                ),
                "sha256": sha256(args.output.resolve()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
