#!/usr/bin/env python3
"""Derive and attach one Settlement v2.1 landed population override."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_settlement_v2 import (
    SettlementV2Error,
    build_population_phase_override,
    structural_layout_bytes,
)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SettlementV2Error(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomically(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def relative_evidence_path(path: Path, evidence_root: Path) -> str:
    try:
        return path.resolve().relative_to(evidence_root.resolve()).as_posix()
    except ValueError as error:
        raise SettlementV2Error(
            f"population trace {path} is outside evidence root {evidence_root}"
        ) from error


def unique_edge(navigation: dict[str, Any], edge_id: str) -> dict[str, Any]:
    edges = navigation.get("edges")
    if not isinstance(edges, list):
        raise SettlementV2Error("population navigation has no edge list")
    matches = [edge for edge in edges if edge.get("id") == edge_id]
    if len(matches) != 1:
        raise SettlementV2Error(
            f"population edge {edge_id!r} is absent or ambiguous: {len(matches)} matches"
        )
    edge = matches[0]
    if not isinstance(edge, dict):
        raise SettlementV2Error(f"population edge {edge_id!r} is not an object")
    return edge


def destination_trace(
    navigation_path: Path,
    edge_id: str,
    expected_layout: dict[str, Any],
    expected_source: dict[str, Any],
    expected_label: str,
    evidence_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    navigation = read_object(navigation_path)
    if navigation.get("schema") != "solomon-dark-native-menu-navigation-v2":
        raise SettlementV2Error(
            f"{navigation_path} is not a Settlement v2 navigation recording"
        )
    edge = unique_edge(navigation, edge_id)
    header = edge.get("header")
    after = edge.get("after")
    if not isinstance(header, dict) or not isinstance(after, dict):
        raise SettlementV2Error(f"population edge {edge_id!r} has no live endpoint")
    if header.get("source") != expected_source:
        raise SettlementV2Error(
            f"population edge {edge_id!r} changed machine-derived provenance"
        )
    if after.get("tagged_screen") != expected_label:
        raise SettlementV2Error(
            f"population edge {edge_id!r} reaches {after.get('tagged_screen')!r}, "
            f"not {expected_label!r}"
        )
    after_layout = after.get("layout")
    if not isinstance(after_layout, dict):
        raise SettlementV2Error(
            f"population edge {edge_id!r} has no settled destination layout"
        )
    if structural_layout_bytes(after_layout) != structural_layout_bytes(
        expected_layout
    ):
        raise SettlementV2Error(
            f"population edge {edge_id!r} destination does not canonically "
            "match its standalone"
        )
    trace = after.get("settlement_trace")
    if not isinstance(trace, dict):
        raise SettlementV2Error(
            f"population edge {edge_id!r} has no destination settlement trace"
        )
    reference = {
        "evidence_path": relative_evidence_path(navigation_path, evidence_root),
        "sha256": file_sha256(navigation_path),
        "bytes": navigation_path.stat().st_size,
        "edge_id": edge_id,
        "side": "destination",
    }
    return trace, reference


def attach(
    repo_root: Path,
    primary_path: Path,
    confirmation_evidence_path: Path,
    primary_navigation_path: Path,
    primary_edge_id: str,
    confirmation_navigation_path: Path,
    confirmation_edge_id: str,
    evidence_root: Path,
) -> None:
    primary = read_object(primary_path)
    confirmation_evidence = read_object(confirmation_evidence_path)
    if primary.get("schema") != "solomon-dark-native-menu-layout-v2":
        raise SettlementV2Error("primary fixture does not use Settlement v2")
    if (
        confirmation_evidence.get("schema")
        != "solomon-dark-native-menu-animation-confirmation-v2"
    ):
        raise SettlementV2Error("confirmation evidence does not use Settlement v2")
    header = primary.get("header")
    layout = primary.get("layout")
    confirmation_header = confirmation_evidence.get("header")
    confirmation_layout = confirmation_evidence.get("confirmation_layout")
    if not all(
        isinstance(value, dict)
        for value in (header, layout, confirmation_header, confirmation_layout)
    ):
        raise SettlementV2Error("override inputs have incomplete fixture objects")
    if "landed_population_override" in header:
        raise SettlementV2Error(
            "primary fixture already has a landed override; refusing ambiguity"
        )
    animation_confirmation = header.get("animation_confirmation")
    if not isinstance(animation_confirmation, dict):
        raise SettlementV2Error(
            "primary fixture needs its fresh animation confirmation before override"
        )
    if (
        animation_confirmation.get("sha256")
        != file_sha256(confirmation_evidence_path)
        or animation_confirmation.get("bytes")
        != confirmation_evidence_path.stat().st_size
    ):
        raise SettlementV2Error(
            "primary fixture does not name the supplied confirmation evidence"
        )

    landed_path = (
        repo_root
        / "tests/fixtures/webgame/menu-layouts"
        / primary_path.name
    )
    if not landed_path.is_file():
        raise SettlementV2Error(
            f"no unique landed standalone exists for {primary_path.name}"
        )
    landed = read_object(landed_path)
    landed_layout = landed.get("layout")
    if not isinstance(landed_layout, dict):
        raise SettlementV2Error(f"landed fixture {landed_path} has no layout")

    primary_trace, primary_reference = destination_trace(
        primary_navigation_path,
        primary_edge_id,
        layout,
        header["source"],
        header["label"],
        evidence_root,
    )
    confirmation_trace, confirmation_reference = destination_trace(
        confirmation_navigation_path,
        confirmation_edge_id,
        confirmation_layout,
        confirmation_header["source"],
        confirmation_header["label"],
        evidence_root,
    )
    override = build_population_phase_override(
        landed_layout,
        layout,
        confirmation_layout,
        primary_trace,
        confirmation_trace,
    )
    override["primary_population_trace"] = {
        **primary_reference,
        **override["primary_population_trace"],
    }
    override["confirmation_population_trace"] = {
        **confirmation_reference,
        **override["confirmation_population_trace"],
    }
    header["landed_population_override"] = override
    write_atomically(primary_path, primary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--confirmation-evidence", type=Path, required=True)
    parser.add_argument("--primary-navigation", type=Path, required=True)
    parser.add_argument("--primary-edge-id", required=True)
    parser.add_argument("--confirmation-navigation", type=Path, required=True)
    parser.add_argument("--confirmation-edge-id", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        attach(
            args.repo_root.resolve(),
            args.primary.resolve(),
            args.confirmation_evidence.resolve(),
            args.primary_navigation.resolve(),
            args.primary_edge_id,
            args.confirmation_navigation.resolve(),
            args.confirmation_edge_id,
            args.evidence_root.resolve(),
        )
    except (KeyError, OSError, SettlementV2Error) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(
        json.dumps(
            {
                "success": True,
                "primary": str(args.primary.resolve()),
                "landed_override": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
