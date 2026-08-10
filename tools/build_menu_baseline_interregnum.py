#!/usr/bin/env python3
"""Initialize immutable menu snapshots and refresh pending shellfix hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


EXPECTED_HISTORICAL_LAYOUT_COUNT = 28
EXPECTED_PENDING_STATE_COUNT = 29
CORRECTIVE = "shellfix task #101"
SHELL_GOLDEN_SNAPSHOT = "webgame-contracts/baseline-snapshots/menu-goldens.json"


class BaselineBuildError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _historical_fixture_names(repo: Path) -> list[str]:
    manifest_path = repo / "webgame-contracts/menu-baseline.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        names = sorted(
            str(entry["fixture"])
            for entry in manifest.get("baseline_snapshots", [])
            if isinstance(entry, dict)
        )
    else:
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
    if (
        len(names) != EXPECTED_HISTORICAL_LAYOUT_COUNT
        or len(set(names)) != len(names)
    ):
        raise BaselineBuildError(
            "menu baseline initialization did not reach exactly 28 unique historical layouts"
        )
    if not {
        "menu-layouts/main-menu-root.json",
        "menu-layouts/dark-cloud-settings.json",
    } <= set(names):
        raise BaselineBuildError(
            "menu baseline initialization did not reach both named historical witnesses"
        )
    return names


def _pending_fixture_names(repo: Path) -> list[str]:
    golden = json.loads(
        (repo / "tests/fixtures/webgame/menu-goldens.json").read_text(
            encoding="utf-8"
        )
    )
    names = [
        str(entry["fixture"])
        for field in (
            "layouts",
            "overlay_records",
            "semantic_dialog_composite_records",
        )
        for entry in golden.get(field, [])
        if isinstance(entry, dict) and isinstance(entry.get("fixture"), str)
    ]
    names.sort()
    if (
        len(names) != EXPECTED_PENDING_STATE_COUNT
        or len(set(names)) != len(names)
        or "menu-layouts/main-menu-root.json" not in names
    ):
        raise BaselineBuildError(
            "menu pending-shellfix census did not reach exactly 29 unique settled states"
        )
    overlay_count = sum(name.startswith("menu-overlays/") for name in names)
    if overlay_count not in {0, 1}:
        raise BaselineBuildError(
            "menu pending-shellfix census contains an unauthorized overlay count"
        )
    if overlay_count == 1 and names.count(
        "menu-overlays/dark-cloud-settings.json"
    ) != 1:
        raise BaselineBuildError(
            "menu pending-shellfix census contains an unauthorized overlay state"
        )
    if names.count(
        "menu-dialog-composites/beta-notice-first-boot.json"
    ) != 1:
        raise BaselineBuildError(
            "menu pending-shellfix census lost the authorized beta dialog composite"
        )
    return names


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _shell_golden_receipt(repo: Path) -> dict[str, Any]:
    path = repo / SHELL_GOLDEN_SNAPSHOT
    if not path.is_file():
        raise BaselineBuildError("immutable pre-menufix shell golden is absent")
    golden = json.loads(path.read_text(encoding="utf-8"))
    layouts = golden.get("layouts")
    census = golden.get("screen_census")
    edges = golden.get("navigation_graph", {}).get("edges")
    if (
        not isinstance(layouts, list)
        or len(layouts) != EXPECTED_HISTORICAL_LAYOUT_COUNT
        or not isinstance(census, list)
        or len(census) != EXPECTED_HISTORICAL_LAYOUT_COUNT
        or not isinstance(edges, list)
        or len(edges) != 39
    ):
        raise BaselineBuildError(
            "immutable shell golden lost its exact 28-layout, 39-edge census"
    )
    reached_references: set[str] = set()
    for wrapper in layouts:
        reference = (
            wrapper.get("reference_capture")
            if isinstance(wrapper, dict)
            else None
        )
        expected_sha = (
            wrapper.get("reference_sha256")
            if isinstance(wrapper, dict)
            else None
        )
        if (
            not isinstance(reference, str)
            or reference in reached_references
            or not isinstance(expected_sha, str)
        ):
            raise BaselineBuildError(
                "immutable shell golden reference lookup is absent or ambiguous"
            )
        reached_references.add(reference)
        reference_path = repo / "webgame-contracts/baseline-snapshots" / reference
        if not reference_path.is_file() or _sha256(reference_path) != expected_sha:
            raise BaselineBuildError(
                f"immutable shell reference receipt changed: {reference}"
            )
    if len(reached_references) != EXPECTED_HISTORICAL_LAYOUT_COUNT:
        raise BaselineBuildError(
            "immutable shell reference sweep did not reach all 28 captures"
        )
    return {
        "path": SHELL_GOLDEN_SNAPSHOT,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def build(repo: Path, initialize: bool) -> dict[str, Any]:
    fixture_root = repo / "tests/fixtures/webgame"
    snapshot_root = repo / "webgame-contracts/baseline-snapshots"
    manifest_path = repo / "webgame-contracts/menu-baseline.json"
    historical_names = _historical_fixture_names(repo)
    pending_names = _pending_fixture_names(repo)
    baseline_entries: list[dict[str, Any]] = []
    pending_entries: list[dict[str, Any]] = []
    for fixture in historical_names:
        source = fixture_root / fixture
        snapshot = snapshot_root / fixture
        if initialize and not source.is_file():
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
    for fixture in pending_names:
        source = fixture_root / fixture
        if not source.is_file():
            raise BaselineBuildError(
                f"menu pending-shellfix fixture is missing: {fixture}"
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
        "schema": "solomon-dark-menu-baseline-v2",
        "corrective": CORRECTIVE,
        "shell_golden_snapshot": _shell_golden_receipt(repo),
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
        or set(reviewed_pass) | set(reviewed_divergent) != set(historical_names)
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
            for fixture in pending_names
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
