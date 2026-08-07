#!/usr/bin/env python3
"""Attach one independently recorded Settlement v2 animation confirmation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

if __package__:
    from .native_menu_ambient_lifecycle import (
        AmbientLifecycleError,
        classify_ambient_window,
    )
    from .native_menu_settlement_v2 import SettlementV2Error, canonical_bytes
else:
    from native_menu_ambient_lifecycle import (
        AmbientLifecycleError,
        classify_ambient_window,
    )
    from native_menu_settlement_v2 import SettlementV2Error, canonical_bytes


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SettlementV2Error(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_settlement_trace(
    fixture_path: Path,
    fixture_header: dict[str, Any],
    evidence_root: Path,
    label: str,
) -> tuple[Path, dict[str, Any]]:
    receipt = fixture_header.get(
        "settlement_trace", fixture_header.get("raw_recording")
    )
    if not isinstance(receipt, dict):
        raise SettlementV2Error(f"{label} fixture has no settlement trace receipt")
    filename = receipt.get("evidence_filename")
    if not isinstance(filename, str) or not filename:
        raise SettlementV2Error(f"{label} settlement trace filename is absent")
    candidates = {
        path.resolve()
        for path in (
            fixture_path.parent / filename,
            *evidence_root.rglob(filename),
        )
        if path.is_file()
    }
    if len(candidates) != 1:
        raise SettlementV2Error(
            f"{label} settlement trace is absent or ambiguous: "
            + ", ".join(sorted(str(path) for path in candidates))
        )
    path = candidates.pop()
    if path.stat().st_size != receipt.get("bytes") or file_sha256(path) != receipt.get(
        "sha256"
    ):
        raise SettlementV2Error(f"{label} settlement trace receipt is false")
    trace = read_object(path)
    samples = trace.get("settled_window_samples")
    if not isinstance(samples, list) or len(samples) < 40:
        raise SettlementV2Error(
            f"{label} settlement trace reached fewer than 40 samples"
        )
    return path, trace


def validate_recorded_window(
    fixture: dict[str, Any],
    trace: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    samples = trace.get("settled_window_samples")
    if not isinstance(samples, list):
        raise SettlementV2Error(f"{label} settlement trace has no sample window")
    try:
        classification = classify_ambient_window(samples, label=label)
    except AmbientLifecycleError as error:
        raise SettlementV2Error(
            f"{label} settlement trace does not reclassify under v2.9: {error}"
        ) from error
    layout = fixture.get("layout")
    header = fixture.get("header")
    if not isinstance(layout, dict) or not isinstance(header, dict):
        raise SettlementV2Error(f"{label} fixture has no header/layout")
    if canonical_bytes(classification["layout"]) != canonical_bytes(layout):
        raise SettlementV2Error(
            f"{label} fixture layout is not derived from its settlement trace"
        )
    settlement = header.get("settlement")
    if (
        not isinstance(settlement, dict)
        or settlement.get("structural_sha256")
        != classification["structural_sha256"]
    ):
        raise SettlementV2Error(
            f"{label} fixture records a false v2.9 window structural hash"
        )
    return classification


def write_atomically(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def attach(
    primary_path: Path,
    confirmation_path: Path,
    evidence_path: Path,
    evidence_root: Path,
) -> None:
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
    primary_ids = primary["layout"].get("animated_element_ids")
    confirmation_ids = confirmation["layout"].get("animated_element_ids")
    if (
        not isinstance(primary_ids, list)
        or not isinstance(confirmation_ids, list)
        or not all(isinstance(value, str) and value for value in primary_ids)
        or not all(isinstance(value, str) and value for value in confirmation_ids)
        or len(primary_ids) != len(set(primary_ids))
        or len(confirmation_ids) != len(set(confirmation_ids))
    ):
        raise SettlementV2Error(
            "raw animation confirmation needs unique non-empty measured IDs"
        )
    raw_sets_match = set(primary_ids) == set(confirmation_ids)
    primary_trace_path, primary_trace = resolve_settlement_trace(
        primary_path, primary_header, evidence_root, "primary"
    )
    confirmation_trace_path, confirmation_trace = resolve_settlement_trace(
        confirmation_path, confirmation_header, evidence_root, "confirmation"
    )
    validate_recorded_window(primary, primary_trace, "primary")
    confirmation_classification = validate_recorded_window(
        confirmation, confirmation_trace, "confirmation"
    )
    confirmation_structural_sha = confirmation_classification[
        "structural_sha256"
    ]
    if evidence_path.exists():
        raise SettlementV2Error(
            f"confirmation evidence already exists at {evidence_path}; refusing ambiguity"
        )

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    confirmation_evidence = {
        "schema": "solomon-dark-native-menu-animation-confirmation-v4",
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
            "settlement_trace": {
                "evidence_filename": confirmation_trace_path.name,
                "sha256": file_sha256(confirmation_trace_path),
                "bytes": confirmation_trace_path.stat().st_size,
            },
            "primary_settlement_trace": {
                "evidence_filename": primary_trace_path.name,
                "sha256": file_sha256(primary_trace_path),
                "bytes": primary_trace_path.stat().st_size,
            },
        },
        "settlement": confirmation_header["settlement"],
        "animated_element_ids": confirmation["layout"]["animated_element_ids"],
        "raw_primary_animated_element_ids": primary_ids,
        "raw_sets_match": raw_sets_match,
        "requires_extended_observation": not raw_sets_match,
        "structural_sha256": confirmation_structural_sha,
        "confirmation_layout": confirmation["layout"],
        "structural_phases": confirmation_trace.get("structural_phases", []),
        "settled_window_samples": confirmation_trace["settled_window_samples"],
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
            canonical_bytes(sorted(ids))
        ).hexdigest(),
        "raw_primary_animated_element_ids": primary_ids,
        "raw_confirmation_animated_element_ids": confirmation_ids,
        "raw_sets_match": raw_sets_match,
        "requires_extended_observation": not raw_sets_match,
    }
    write_atomically(primary_path, primary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        attach(
            args.primary.resolve(),
            args.confirmation.resolve(),
            args.evidence_output.resolve(),
            args.evidence_root.resolve(),
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
