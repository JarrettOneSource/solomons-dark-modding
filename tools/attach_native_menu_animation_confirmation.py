#!/usr/bin/env python3
"""Attach one independently recorded Settlement v2 animation confirmation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_settlement_v2 import (
    SettlementV2Error,
    assert_confirmation_matches,
    canonical_bytes,
    structural_layout_bytes,
)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SettlementV2Error(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_atomically(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def attach(primary_path: Path, confirmation_path: Path, evidence_path: Path) -> None:
    primary = read_object(primary_path)
    confirmation = read_object(confirmation_path)
    if primary.get("schema") != "solomon-dark-native-menu-layout-v2":
        raise SettlementV2Error("primary fixture does not use Settlement v2")
    if confirmation.get("schema") != "solomon-dark-native-menu-layout-v2":
        raise SettlementV2Error("confirmation fixture does not use Settlement v2")
    primary_header = primary["header"]
    confirmation_header = confirmation["header"]
    if "animation_confirmation" in primary_header:
        raise SettlementV2Error(
            "primary fixture already names an animation confirmation; refusing ambiguity"
        )
    if primary_header["label"] != confirmation_header["label"]:
        raise SettlementV2Error("confirmation label differs from the primary fixture")
    if primary_header["instance"] == confirmation_header["instance"]:
        raise SettlementV2Error(
            "animated-ID confirmation must come from a different fresh instance"
        )
    if primary_header["process_id"] == confirmation_header["process_id"]:
        raise SettlementV2Error(
            "animated-ID confirmation must come from a different exact process"
        )
    if primary_header["source"] != confirmation_header["source"]:
        raise SettlementV2Error(
            "animated-ID confirmation must use the same machine-derived provenance"
        )
    assert_confirmation_matches(primary["layout"], confirmation["layout"])
    primary_structural_sha = hashlib.sha256(
        structural_layout_bytes(primary["layout"])
    ).hexdigest()
    confirmation_structural_sha = hashlib.sha256(
        structural_layout_bytes(confirmation["layout"])
    ).hexdigest()
    if primary_structural_sha != primary_header["settlement"]["structural_sha256"]:
        raise SettlementV2Error("primary fixture records a false structural hash")
    if (
        confirmation_structural_sha
        != confirmation_header["settlement"]["structural_sha256"]
    ):
        raise SettlementV2Error("confirmation fixture records a false structural hash")
    if evidence_path.exists():
        raise SettlementV2Error(
            f"confirmation evidence already exists at {evidence_path}; refusing ambiguity"
        )

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    confirmation_evidence = {
        "schema": "solomon-dark-native-menu-animation-confirmation-v2",
        "header": {
            "label": confirmation_header["label"],
            "instance": confirmation_header["instance"],
            "process_id": confirmation_header["process_id"],
            "source": confirmation_header["source"],
            "recorded_live": True,
            "captured_at_utc": confirmation_header["captured_at_utc"],
            "capture_method": confirmation_header["capture_method"],
            "confirmation_fixture": {
                "evidence_filename": confirmation_path.name,
                "sha256": file_sha256(confirmation_path),
                "bytes": confirmation_path.stat().st_size,
                "raw_recording": confirmation_header["raw_recording"],
            },
        },
        "settlement": confirmation_header["settlement"],
        "animated_element_ids": confirmation["layout"]["animated_element_ids"],
        "structural_sha256": confirmation_structural_sha,
        "confirmation_layout": confirmation["layout"],
    }
    write_atomically(evidence_path, confirmation_evidence)

    ids = confirmation["layout"]["animated_element_ids"]
    primary_header["animation_confirmation"] = {
        "evidence_filename": evidence_path.name,
        "sha256": file_sha256(evidence_path),
        "bytes": evidence_path.stat().st_size,
        "instance": confirmation_header["instance"],
        "process_id": confirmation_header["process_id"],
        "source": confirmation_header["source"],
        "confirmation_structural_sha256": confirmation_structural_sha,
        "animated_element_ids_sha256": hashlib.sha256(
            canonical_bytes(ids)
        ).hexdigest(),
    }
    write_atomically(primary_path, primary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        attach(
            args.primary.resolve(),
            args.confirmation.resolve(),
            args.evidence_output.resolve(),
        )
    except (KeyError, SettlementV2Error) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(
        json.dumps(
            {
                "success": True,
                "primary": str(args.primary.resolve()),
                "confirmation": str(args.confirmation.resolve()),
                "evidence": str(args.evidence_output.resolve()),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
