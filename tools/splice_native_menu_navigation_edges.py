#!/usr/bin/env python3
"""Build an auditable navigation recording from exact captured edge replacements."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "solomon-dark-native-menu-navigation-v2"


class NavigationSpliceError(RuntimeError):
    pass


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NavigationSpliceError(f"cannot read navigation recording {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise NavigationSpliceError(f"navigation recording {path} has the wrong schema")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _edge_map(recording: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    edges = recording.get("edges")
    if not isinstance(edges, list) or not edges:
        raise NavigationSpliceError(f"{label} navigation recording has no edges")
    result: dict[str, dict[str, Any]] = {}
    for edge in edges:
        if not isinstance(edge, dict) or not isinstance(edge.get("id"), str):
            raise NavigationSpliceError(f"{label} navigation has an edge without one string id")
        edge_id = edge["id"]
        if edge_id in result:
            raise NavigationSpliceError(
                f"{label} navigation edge id '{edge_id}' is ambiguous"
            )
        result[edge_id] = edge
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def splice_navigation(
    base_path: Path,
    donor_path: Path,
    output_path: Path,
    replacements: dict[str, str],
) -> dict[str, Any]:
    if not replacements:
        raise NavigationSpliceError("navigation splice has no requested edge replacements")
    if output_path.exists():
        raise NavigationSpliceError(
            f"navigation splice output already exists: {output_path}"
        )
    base = _read_object(base_path)
    donor = _read_object(donor_path)
    base_edges = _edge_map(base, "base")
    donor_edges = _edge_map(donor, "donor")
    missing_targets = sorted(set(replacements) - set(base_edges))
    missing_donors = sorted(set(replacements.values()) - set(donor_edges))
    if missing_targets or missing_donors:
        raise NavigationSpliceError(
            "navigation splice could not resolve every exact edge: "
            f"missing_targets={missing_targets} missing_donors={missing_donors}"
        )

    output = copy.deepcopy(base)
    replaced: list[dict[str, str]] = []
    output_edges: list[dict[str, Any]] = []
    for edge in output["edges"]:
        target_id = edge["id"]
        donor_id = replacements.get(target_id)
        if donor_id is None:
            output_edges.append(edge)
            continue
        replacement = copy.deepcopy(donor_edges[donor_id])
        replacement["id"] = target_id
        header = replacement.get("header")
        if not isinstance(header, dict):
            raise NavigationSpliceError(
                f"donor navigation edge '{donor_id}' has no capture header"
            )
        header["label"] = target_id
        output_edges.append(replacement)
        replaced.append({"target_edge_id": target_id, "donor_edge_id": donor_id})
    if len(replaced) != len(replacements):
        raise NavigationSpliceError(
            "navigation splice did not replace every requested edge exactly once"
        )
    output["edges"] = output_edges

    output_header = output.get("header")
    donor_header = donor.get("header")
    if not isinstance(output_header, dict) or not isinstance(donor_header, dict):
        raise NavigationSpliceError("navigation splice requires base and donor headers")
    sessions = output_header.get("sessions")
    donor_sessions = donor_header.get("sessions")
    if not isinstance(sessions, list) or not isinstance(donor_sessions, list):
        raise NavigationSpliceError("navigation splice requires explicit session lists")
    seen = {_canonical(session) for session in sessions}
    for session in donor_sessions:
        encoded = _canonical(session)
        if encoded not in seen:
            sessions.append(copy.deepcopy(session))
            seen.add(encoded)
    output_header["derived_edge_splice"] = {
        "base": {
            "filename": base_path.name,
            "sha256": _sha256(base_path),
            "bytes": base_path.stat().st_size,
        },
        "donor": {
            "filename": donor_path.name,
            "sha256": _sha256(donor_path),
            "bytes": donor_path.stat().st_size,
        },
        "replacements": replaced,
        "unchanged_edge_count": len(output_edges) - len(replaced),
    }
    _edge_map(output, "spliced")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(output, stream, indent=4, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output_path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

    return {
        "success": True,
        "output": str(output_path),
        "sha256": _sha256(output_path),
        "bytes": output_path.stat().st_size,
        "edge_count": len(output_edges),
        "replaced": replaced,
    }


def _replacement(value: str) -> tuple[str, str]:
    target, separator, donor = value.partition("=")
    if not separator or not target or not donor:
        raise argparse.ArgumentTypeError("replacement must be TARGET=DONOR")
    return target, donor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--donor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace", action="append", type=_replacement, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    replacements: dict[str, str] = {}
    for target, donor in args.replace:
        if target in replacements:
            raise SystemExit(f"STOP: duplicate replacement target '{target}'")
        replacements[target] = donor
    try:
        result = splice_navigation(
            args.base.resolve(),
            args.donor.resolve(),
            args.output.resolve(),
            replacements,
        )
    except NavigationSpliceError as error:
        print(json.dumps({"success": False, "error": f"STOP: {error}"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
