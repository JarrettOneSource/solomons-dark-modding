#!/usr/bin/env python3
"""Validate and promote one complete settled native-menu recapture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


class PromotionError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PromotionError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_layout(layout: dict[str, Any]) -> bytes:
    semantic = {
        key: value
        for key, value in layout.items()
        if key not in {"captured_at_milliseconds", "elapsed_milliseconds"}
    }
    return json.dumps(
        semantic,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def require_unique_files(root: Path, pattern: str, expected: set[str]) -> dict[str, Path]:
    paths = list(root.glob(pattern))
    names = [path.name for path in paths]
    if len(names) != len(set(names)):
        raise PromotionError(f"ambiguous duplicate candidates under {root}: {names}")
    actual = set(names)
    if actual != expected:
        raise PromotionError(
            f"candidate census drifted under {root}: "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    return {path.name: path for path in paths}


def resolve_evidence_file(
    evidence_root: Path,
    fixture_path: Path,
    filename: str,
) -> Path:
    candidates = {
        candidate.resolve()
        for candidate in (
            fixture_path.parent / filename,
            *evidence_root.rglob(filename),
        )
        if candidate.is_file()
    }
    if len(candidates) != 1:
        raise PromotionError(
            f"raw evidence lookup for {filename!r} is ambiguous or absent: "
            f"{sorted(str(path) for path in candidates)}"
        )
    return candidates.pop()


def validate_raw_recording(
    evidence_root: Path,
    fixture_path: Path,
    header: dict[str, Any],
) -> None:
    raw = header.get("raw_recording")
    if not isinstance(raw, dict):
        raise PromotionError(f"{fixture_path} has no raw_recording provenance")
    filename = raw.get("evidence_filename")
    if not isinstance(filename, str) or not filename:
        raise PromotionError(f"{fixture_path} has no raw evidence filename")
    evidence = resolve_evidence_file(evidence_root, fixture_path, filename)
    if evidence.stat().st_size != raw.get("bytes"):
        raise PromotionError(f"{fixture_path} raw evidence byte count is false")
    if file_sha256(evidence) != raw.get("sha256"):
        raise PromotionError(f"{fixture_path} raw evidence hash is false")


def endpoint_source_signature(endpoint: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "semantic_surface",
        "semantic_generation",
        "tagged_screen",
        "layout_generation",
        "element_count",
        "capture_method",
        "frame_sha256",
    )
    return {field: endpoint.get(field) for field in fields}


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".menufix.tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, destination)


def validate_and_promote(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    navigation_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    landed_root = repo_root / "tests/fixtures/webgame"
    landed_golden = read_json(landed_root / "menu-goldens.json")
    candidate_golden_path = candidate_root / "menu-goldens.json"
    candidate_golden = read_json(candidate_golden_path)

    layout_names = {
        Path(entry["fixture"]).name for entry in landed_golden["layouts"]
    }
    candidate_layouts = require_unique_files(
        candidate_root / "menu-layouts",
        "*.json",
        layout_names,
    )
    candidate_transition_layouts = require_unique_files(
        candidate_root / "menu-transition-layouts",
        "*.json",
        {"hub.json"},
    )
    reference_names = {
        Path(entry["reference_capture"]).name
        for entry in candidate_golden["layouts"]
    } | {
        Path(entry["reference_capture"]).name
        for entry in candidate_golden["transition_endpoint_layouts"]
    }
    candidate_references = require_unique_files(
        candidate_root / "menu-reference-captures",
        "*.png",
        reference_names,
    )

    landed_by_name = {
        Path(entry["fixture"]).name: entry
        for entry in landed_golden["layouts"]
    }
    standalone_results: list[dict[str, Any]] = []
    for name in sorted(layout_names):
        candidate_fixture = read_json(candidate_layouts[name])
        landed_entry = landed_by_name[name]
        if semantic_layout(candidate_fixture["layout"]) != semantic_layout(
            landed_entry["layout"]
        ):
            raise PromotionError(
                f"STOP: standalone {name} does not bit-match its landed semantic payload"
            )
        validate_raw_recording(
            evidence_root,
            candidate_layouts[name],
            candidate_fixture["header"],
        )
        standalone_results.append(
            {
                "layout": name,
                "semantic_bit_match": True,
                "settle_latency_milliseconds": candidate_fixture["header"][
                    "settlement"
                ]["settle_latency_milliseconds"],
            }
        )

    hub_fixture = read_json(candidate_transition_layouts["hub.json"])
    validate_raw_recording(
        evidence_root,
        candidate_transition_layouts["hub.json"],
        hub_fixture["header"],
    )

    raw = candidate_golden["header"]["raw_recording"]
    if raw["bytes"] != navigation_path.stat().st_size:
        raise PromotionError("candidate golden records a false navigation byte count")
    if raw["sha256"] != file_sha256(navigation_path):
        raise PromotionError("candidate golden records a false navigation hash")

    old_edges = {
        edge["id"]: edge
        for edge in landed_golden["navigation_graph"]["edges"]
    }
    candidate_edges = candidate_golden["navigation_graph"]["edges"]
    candidate_ids = [edge["id"] for edge in candidate_edges]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise PromotionError("candidate golden contains ambiguous duplicate edge IDs")
    if set(candidate_ids) != set(old_edges):
        raise PromotionError(
            "candidate edge census differs from the landed navigation graph"
        )
    candidate_standalones = {
        entry["fixture"]: entry
        for entry in (
            *candidate_golden["layouts"],
            *candidate_golden["transition_endpoint_layouts"],
        )
    }
    destination_changes: list[dict[str, Any]] = []
    for edge in candidate_edges:
        edge_id = edge["id"]
        landed = old_edges[edge_id]
        if endpoint_source_signature(edge["before"]) != endpoint_source_signature(
            landed["before"]
        ):
            raise PromotionError(
                f"STOP: transition source {edge_id} does not bit-match the landed "
                "generation/elements/method/frame payload"
            )
        fixture_name = edge.get("destination_layout_fixture")
        if fixture_name not in candidate_standalones:
            raise PromotionError(
                f"STOP: transition destination {edge_id} has no unique standalone"
            )
        if semantic_layout(edge["after"]["layout"]) != semantic_layout(
            candidate_standalones[fixture_name]["layout"]
        ):
            raise PromotionError(
                f"STOP: transition destination {edge_id} does not byte-match "
                f"{fixture_name}"
            )
        old_after = endpoint_source_signature(landed["after"])
        new_after = endpoint_source_signature(edge["after"])
        if old_after != new_after:
            destination_changes.append(
                {
                    "edge": edge_id,
                    "old": old_after,
                    "new": new_after,
                    "settle_latency_milliseconds": edge["after"]["settlement"][
                        "settle_latency_milliseconds"
                    ],
                    "standalone_fixture": fixture_name,
                }
            )

    embedded = {
        Path(entry["fixture"]).name: entry for entry in candidate_golden["layouts"]
    }
    for name, path in candidate_layouts.items():
        fixture = read_json(path)
        if fixture != {
            "schema": fixture["schema"],
            "header": embedded[name]["header"],
            "layout": embedded[name]["layout"],
        }:
            raise PromotionError(
                f"candidate embedded golden and standalone {name} disagree"
            )

    promotion_pairs: list[tuple[Path, Path]] = []
    for name, source in candidate_layouts.items():
        promotion_pairs.append((source, landed_root / "menu-layouts" / name))
    for name, source in candidate_transition_layouts.items():
        promotion_pairs.append(
            (source, landed_root / "menu-transition-layouts" / name)
        )
    for name, source in candidate_references.items():
        promotion_pairs.append(
            (source, landed_root / "menu-reference-captures" / name)
        )
    promotion_pairs.append((candidate_golden_path, landed_root / "menu-goldens.json"))

    if not dry_run:
        for source, destination in promotion_pairs:
            atomic_copy(source, destination)

    return {
        "success": True,
        "dry_run": dry_run,
        "standalones": standalone_results,
        "hub_settle_latency_milliseconds": hub_fixture["header"]["settlement"][
            "settle_latency_milliseconds"
        ],
        "transition_sources_bit_match": len(candidate_edges),
        "transition_destinations_match_standalones": len(candidate_edges),
        "destination_changes": destination_changes,
        "promoted_files": [str(destination) for _, destination in promotion_pairs],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate_and_promote(
            args.repo_root.resolve(),
            args.candidate_root.resolve(),
            args.evidence_root.resolve(),
            args.navigation_recording.resolve(),
            args.dry_run,
        )
    except PromotionError as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
