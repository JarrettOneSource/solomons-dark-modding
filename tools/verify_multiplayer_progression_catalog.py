#!/usr/bin/env python3
"""Catalog every native wizard progression row and verify it on both peers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import compare_book_rows, query_progression_snapshot
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    stop_games,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parent.parent
SKILL_CONFIG_DIR = ROOT / "runtime" / "stage" / "data" / "wizardskills"
DEFAULT_OUTPUT = ROOT / "runtime" / "multiplayer_native_progression_catalog.json"
STRUCTURAL_TAIL_COUNT = 3
ROOT_UNLOCK_COUNT = 8


def read_string_setting(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*\"([^\"]*)\"", text)
    return match.group(1).strip() if match else ""


def read_int_setting(text: str, key: str) -> int | None:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*(-?\d+)\s*;", text)
    return int(match.group(1)) if match else None


def normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def display_name(stem: str) -> str:
    if stem == "health_up":
        return "HEALTH UP"
    if stem == "mana_up":
        return "MANA UP"
    return " ".join(part.capitalize() for part in stem.split("_"))


def load_skill_configs() -> list[dict[str, Any]]:
    if not SKILL_CONFIG_DIR.is_dir():
        raise VerifyFailure(f"wizard skill config directory is missing: {SKILL_CONFIG_DIR}")
    configs: list[dict[str, Any]] = []
    for path in sorted(SKILL_CONFIG_DIR.glob("*.cfg")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        configs.append(
            {
                "skill_file": path.name,
                "skill_name": display_name(path.stem),
                "quick_description": read_string_setting(text, "mQDescription"),
                "description": read_string_setting(text, "mDescription"),
                "cap_level": read_int_setting(text, "mCapLevel"),
                "max_level": read_int_setting(text, "mMaxLevel"),
            }
        )
    if not configs:
        raise VerifyFailure("no wizard skill configs were found")
    return configs


def build_text_index(configs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for config in configs:
        for field in ("quick_description", "description"):
            key = normalized_text(str(config[field]))
            if key:
                index.setdefault(key, []).append(config)
    return index


def wait_for_catalog_views(timeout: float) -> dict[str, dict[str, Any]]:
    view_specs = (
        ("host_local", HOST_PIPE, None),
        ("host_remote_client", HOST_PIPE, CLIENT_ID),
        ("client_local", CLIENT_PIPE, None),
        ("client_remote_host", CLIENT_PIPE, HOST_ID),
    )
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, Any]] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = {
                label: query_progression_snapshot(
                    pipe_name,
                    participant_id=participant_id,
                    include_native_text=True,
                    timeout=8.0,
                )
                for label, pipe_name, participant_id in view_specs
            }
            last_error = ""
        except (VerifyFailure, subprocess.TimeoutExpired) as exc:
            last_error = str(exc)
            time.sleep(0.25)
            continue
        ready = True
        for snapshot in last.values():
            native = snapshot["native"]
            entries = native["entries"]
            if (
                not snapshot["available"]
                or native["entry_count"] <= STRUCTURAL_TAIL_COUNT
                or len(entries) != native["entry_count"]
            ):
                ready = False
                break
            real_count = native["entry_count"] - STRUCTURAL_TAIL_COUNT
            if any(
                not entries[index].get("native_text")
                for index in range(ROOT_UNLOCK_COUNT, real_count)
            ):
                ready = False
                break
            if compare_book_rows(entries, snapshot["ledger"]["entries"]):
                ready = False
                break
        if ready:
            return last
        time.sleep(0.25)
    detail = f"; last_error={last_error}" if last_error else ""
    raise VerifyFailure(f"native progression catalog views did not become ready: {last}{detail}")


def build_and_verify_catalog(
    views: dict[str, dict[str, Any]],
    configs: list[dict[str, Any]],
) -> dict[str, Any]:
    canonical = views["host_local"]
    native = canonical["native"]
    entry_count = int(native["entry_count"])
    real_count = entry_count - STRUCTURAL_TAIL_COUNT
    if real_count != len(configs):
        raise VerifyFailure(
            f"native/config skill cardinality mismatch: native={real_count} configs={len(configs)}"
        )

    text_index = build_text_index(configs)

    def matching_configs(entry: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = [str(entry.get("native_text") or "")]
        candidates.extend(str(value) for value in entry.get("native_text_candidates", []))
        matches_by_file: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            for config in text_index.get(normalized_text(candidate), []):
                matches_by_file[str(config["skill_file"])] = config
        return list(matches_by_file.values())

    catalog: list[dict[str, Any]] = []
    matched_files: list[str] = []
    for entry_index in range(real_count):
        entry = native["entries"][entry_index]
        native_text = str(entry.get("native_text") or "")
        matches = matching_configs(entry)
        if len(matches) != 1:
            raise VerifyFailure(
                f"native row {entry_index} text did not map to exactly one config: "
                f"text={native_text!r} "
                f"candidates={entry.get('native_text_candidates', [])!r} "
                f"matches={[item['skill_file'] for item in matches]}"
            )
        config = matches[0]
        matched_files.append(str(config["skill_file"]))
        declared_max = config["max_level"]
        if declared_max is not None and int(entry["statbook_max_level"]) != declared_max:
            raise VerifyFailure(
                f"native/config max level mismatch for row {entry_index} "
                f"({config['skill_file']}): native={entry['statbook_max_level']} "
                f"config={declared_max}"
            )
        catalog.append(
            {
                "entry_index": entry_index,
                "internal_id": int(entry["internal_id"]),
                "category": int(entry["category"]),
                "initial_active": int(entry["active"]),
                "initial_visible": int(entry["visible"]),
                "native_max_level": int(entry["statbook_max_level"]),
                **config,
                "native_text": native_text,
                "native_text_candidates": entry.get("native_text_candidates", []),
            }
        )

    expected_files = sorted(str(config["skill_file"]) for config in configs)
    if sorted(matched_files) != expected_files or len(set(matched_files)) != len(matched_files):
        missing = sorted(set(expected_files) - set(matched_files))
        duplicate = sorted(
            file_name
            for file_name in set(matched_files)
            if matched_files.count(file_name) > 1
        )
        raise VerifyFailure(
            f"native catalog is not a bijection over configs: missing={missing} duplicate={duplicate}"
        )

    parity: dict[str, Any] = {}
    canonical_rows = canonical["native"]["entries"]
    canonical_files = {
        row["entry_index"]: row["skill_file"]
        for row in catalog
    }
    owner_view_by_label = {
        "host_local": "host_local",
        "client_remote_host": "host_local",
        "client_local": "client_local",
        "host_remote_client": "client_local",
    }
    for label, snapshot in views.items():
        native_rows = snapshot["native"]["entries"]
        ledger_rows = snapshot["ledger"]["entries"]
        owner_label = owner_view_by_label.get(label, label)
        owner_rows = views.get(owner_label, snapshot)["native"]["entries"]
        native_mismatches = compare_book_rows(owner_rows, native_rows)
        ledger_mismatches = compare_book_rows(native_rows, ledger_rows)
        catalog_metadata_mismatches = []
        for index in range(entry_count):
            expected = canonical_rows.get(index, {})
            actual = native_rows.get(index, {})
            fields = (
                "internal_id",
                "category",
                "statbook_max_level",
            )
            differences = {
                field: {
                    "expected": expected.get(field),
                    "actual": actual.get(field),
                }
                for field in fields
                if expected.get(field) != actual.get(field)
            }
            if differences:
                catalog_metadata_mismatches.append(
                    {"entry_index": index, "fields": differences}
                )
        mapping_mismatches = [
            {
                "entry_index": index,
                "expected": canonical_files[index],
                "actual": [
                    item["skill_file"]
                    for item in matching_configs(native_rows.get(index, {}))
                ],
            }
            for index in range(real_count)
            if [
                item["skill_file"]
                for item in matching_configs(native_rows.get(index, {}))
            ] != [canonical_files[index]]
        ]
        parity[label] = {
            "owner_view": owner_label,
            "native_mismatches": native_mismatches,
            "ledger_mismatches": ledger_mismatches,
            "catalog_metadata_mismatches": catalog_metadata_mismatches,
            "mapping_mismatches": mapping_mismatches,
            "native_entry_count": snapshot["native"]["entry_count"],
            "ledger_entry_count": snapshot["ledger"]["entry_count"],
        }
        if (
            native_mismatches
            or ledger_mismatches
            or catalog_metadata_mismatches
            or mapping_mismatches
        ):
            raise VerifyFailure(f"progression catalog parity failed for {label}: {parity[label]}")

    structural_tail: list[dict[str, Any]] = []
    for entry_index in range(real_count, entry_count):
        entry = canonical_rows[entry_index]
        normalized = {
            "entry_index": entry_index,
            "internal_id": int(entry["internal_id"]),
            "active": int(entry["active"]),
            "visible": int(entry["visible"]),
            "category": int(entry["category"]),
            "statbook_max_level": int(entry["statbook_max_level"]),
        }
        if normalized["category"] != 0 or normalized["statbook_max_level"] != 0:
            raise VerifyFailure(f"structural tail row was not normalized: {normalized}")
        structural_tail.append(normalized)

    return {
        "config_count": len(configs),
        "native_entry_count": entry_count,
        "real_skill_row_count": real_count,
        "structural_tail_count": STRUCTURAL_TAIL_COUNT,
        "catalog": catalog,
        "structural_tail": structural_tail,
        "parity": parity,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output: dict[str, Any] = {"ok": False}
    try:
        configs = load_skill_configs()
        stop_games()
        output["launch"] = launch_pair()
        disable_bots()
        output["hub_ready"] = {
            "host_observes_client": wait_for_remote(
                HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub", timeout=args.timeout
            ),
            "client_observes_host": wait_for_remote(
                CLIENT_PIPE, HOST_ID, HOST_NAME, "hub", timeout=args.timeout
            ),
        }
        views = wait_for_catalog_views(args.timeout)
        output["progression_catalog"] = build_and_verify_catalog(views, configs)
        output["ok"] = True
    except (VerifyFailure, subprocess.TimeoutExpired) as exc:
        output["error"] = str(exc)
    finally:
        if not args.keep_open:
            stop_games()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json or not output["ok"]:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        result = output["progression_catalog"]
        print(
            "native progression catalog ok: "
            f"skills={result['real_skill_row_count']} "
            f"entries={result['native_entry_count']} "
            f"views={len(result['parity'])} "
            f"output={args.output}"
        )
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
