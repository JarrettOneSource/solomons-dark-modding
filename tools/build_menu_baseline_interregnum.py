#!/usr/bin/env python3
"""Initialize immutable menu snapshots and refresh pending shellfix hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


EXPECTED_LAYOUT_COUNT = 28
CORRECTIVE = "shellfix task #101"


class BaselineBuildError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_names(repo: Path) -> list[str]:
    golden = json.loads(
        (repo / "tests/fixtures/webgame/menu-goldens.json").read_text(
            encoding="utf-8"
        )
    )
    names = sorted(
        str(entry["fixture"])
        for entry in golden.get("layouts", [])
        if isinstance(entry, dict)
    )
    if len(names) != EXPECTED_LAYOUT_COUNT or len(set(names)) != len(names):
        raise BaselineBuildError(
            "menu baseline initialization did not reach exactly 28 unique layouts"
        )
    if "menu-layouts/main-menu-root.json" not in names:
        raise BaselineBuildError(
            "menu baseline initialization did not reach main-menu-root witness"
        )
    return names


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build(repo: Path, initialize: bool) -> dict[str, Any]:
    fixture_root = repo / "tests/fixtures/webgame"
    snapshot_root = repo / "webgame-contracts/baseline-snapshots"
    manifest_path = repo / "webgame-contracts/menu-baseline.json"
    names = _fixture_names(repo)
    baseline_entries: list[dict[str, Any]] = []
    pending_entries: list[dict[str, Any]] = []
    for fixture in names:
        source = fixture_root / fixture
        snapshot = snapshot_root / fixture
        if not source.is_file():
            raise BaselineBuildError(
                f"menu baseline source fixture is missing: {fixture}"
            )
        if initialize:
            if snapshot.exists() and snapshot.read_bytes() != source.read_bytes():
                raise BaselineBuildError(
                    f"immutable menu baseline snapshot already differs: {fixture}"
                )
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            if not snapshot.exists():
                shutil.copyfile(source, snapshot)
        if not snapshot.is_file():
            raise BaselineBuildError(
                f"menu baseline snapshot is absent: {fixture}"
            )
        baseline_entries.append(
            {
                "fixture": fixture,
                "snapshot": snapshot.relative_to(repo).as_posix(),
                "sha256": _sha256(snapshot),
                "bytes": snapshot.stat().st_size,
                "corrective": CORRECTIVE,
            }
        )
        pending_entries.append(
            {
                "fixture": fixture,
                "sha256": _sha256(source),
                "bytes": source.stat().st_size,
                "corrective": CORRECTIVE,
            }
        )
    manifest = {
        "schema": "solomon-dark-menu-baseline-v1",
        "corrective": CORRECTIVE,
        "baseline_snapshot_count": len(baseline_entries),
        "pending_shellfix_count": len(pending_entries),
        "baseline_snapshots": baseline_entries,
        "pending_shellfix": pending_entries,
    }
    _write_json(manifest_path, manifest)
    visual_path = repo / "webgame-contracts/menu-visual-gate.json"
    visual = json.loads(visual_path.read_text(encoding="utf-8"))
    if visual.get("schema") == "solomon-dark-menu-visual-gate-v1":
        reviewed_pass = list(visual.get("reviewed_pass_fixtures", []))
        reviewed_divergent = list(visual.get("reviewed_divergent_fixtures", []))
    elif visual.get("schema") == "solomon-dark-menu-visual-gate-v2":
        reviewed_pass = [
            entry["fixture"] for entry in visual.get("reviewed_pass_snapshots", [])
        ]
        reviewed_divergent = [
            entry["fixture"]
            for entry in visual.get("reviewed_divergent_snapshots", [])
        ]
    else:
        raise BaselineBuildError("menu visual gate schema is not recognized")
    if (
        len(reviewed_pass) != 18
        or len(reviewed_divergent) != 10
        or set(reviewed_pass) | set(reviewed_divergent) != set(names)
        or set(reviewed_pass) & set(reviewed_divergent)
    ):
        raise BaselineBuildError(
            "menu visual review no longer partitions the exact 28-layout census"
        )
    baseline_by_fixture = {
        entry["fixture"]: entry for entry in baseline_entries
    }
    pending_by_fixture = {
        entry["fixture"]: entry for entry in pending_entries
    }

    def reviewed_entry(fixture: str) -> dict[str, Any]:
        return {
            "fixture": fixture,
            "baseline_snapshot_sha256": baseline_by_fixture[fixture]["sha256"],
            "corrective": CORRECTIVE,
        }

    visual_v2 = {
        "schema": "solomon-dark-menu-visual-gate-v2",
        "pixel_rule": visual["pixel_rule"],
        "reviewed_pass_snapshots": [
            reviewed_entry(fixture) for fixture in reviewed_pass
        ],
        "reviewed_divergent_snapshots": [
            reviewed_entry(fixture) for fixture in reviewed_divergent
        ],
        "pending_shellfix": [
            {
                "fixture": fixture,
                "settled_fixture_sha256": pending_by_fixture[fixture]["sha256"],
                "corrective": CORRECTIVE,
            }
            for fixture in names
        ],
    }
    _write_json(visual_path, visual_v2)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--initialize", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = build(args.repo_root.resolve(), args.initialize)
    except (BaselineBuildError, OSError, ValueError, KeyError) as error:
        print(f"STOP: {error}")
        return 2
    print(
        json.dumps(
            {
                "success": True,
                "baseline_snapshot_count": result["baseline_snapshot_count"],
                "pending_shellfix_count": result["pending_shellfix_count"],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
