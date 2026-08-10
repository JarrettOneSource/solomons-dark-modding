#!/usr/bin/env python3
"""Seal the bounded Item 1 probe that tripped the durable-state guard."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_profile_state import load_profile_state_baseline


SCHEMA = "solomon-dark-native-menu-item-row-carryover-guard-audit-v1"
SETTINGS_PATH = ("stage_sandbox", "settings.txt")
BEFORE_SELECTOR = b"DarkCloud.ViewingLevels=2"
AFTER_SELECTOR = b"DarkCloud.ViewingLevels=0"


class AuditError(RuntimeError):
    """The rejected diagnostic no longer proves the claimed guard trip."""


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise AuditError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    base = root.resolve()
    if not resolved.is_relative_to(base):
        raise AuditError(f"receipt target escapes evidence root: {resolved}")
    return {
        "path": resolved.relative_to(base).as_posix(),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def census_files(census: dict[str, Any], label: str) -> dict[tuple[str, str], dict[str, Any]]:
    files = census.get("files")
    if not isinstance(files, list) or not files:
        raise AuditError(f"{label} durable census reached no real files")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise AuditError(f"{label} durable census has a non-object entry")
        key = (str(entry.get("root")), str(entry.get("relative_path")))
        if key in result:
            raise AuditError(f"{label} durable census is ambiguous at {key!r}")
        result[key] = entry
    if SETTINGS_PATH not in result:
        raise AuditError(f"{label} durable census did not inspect settings.txt")
    return result


def item_rows(layout: Any) -> list[dict[str, Any]]:
    if not isinstance(layout, dict):
        raise AuditError("diagnostic endpoint has no measured layout")
    elements = layout.get("elements")
    if not isinstance(elements, list):
        raise AuditError("diagnostic endpoint layout has no element census")
    return [
        element
        for element in elements
        if isinstance(element, dict) and element.get("text") == "Item 1"
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--diagnostic-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    evidence = args.evidence_root.resolve()
    diagnostic = args.diagnostic_root.resolve()
    primary = diagnostic / "primary"
    retry = diagnostic / "primary-retry"
    confirmation = diagnostic / "confirmation"
    if confirmation.exists():
        raise AuditError("a confirmation was launched after the durable-state guard tripped")

    first_failure_path = primary / "failure.json"
    first_failure = read_object(first_failure_path)
    if first_failure.get("failure") != (
        "STOP: preparation initial surface was neither picker nor beta dialog."
    ):
        raise AuditError("the discarded first launch has an unexpected failure")

    failure_path = retry / "failure.json"
    failure = read_object(failure_path)
    expected_failure = (
        "STOP: read-only Item 1 diagnostic changed durable Dark Cloud file content."
    )
    if failure.get("failure") != expected_failure:
        raise AuditError("the durable-state guard did not emit its exact named STOP")

    before_path = retry / "before-diagnostic-durable-file-census.json"
    after_path = retry / "after-diagnostic-durable-file-census.json"
    before = read_object(before_path)
    after = read_object(after_path)
    baseline = load_profile_state_baseline(repo)
    expected_identity = baseline["identity"]
    for label, value in (("before", before), ("after", after)):
        if value.get("profile_state_identity_sha256") != expected_identity:
            raise AuditError(f"{label} census is not bound to pristine fresh_install")
    before_files = census_files(before, "before")
    after_files = census_files(after, "after")
    if before_files.keys() != after_files.keys():
        raise AuditError("durable-file membership changed during the diagnostic")
    changed = [
        key
        for key in before_files
        if (
            before_files[key].get("sha256") != after_files[key].get("sha256")
            or before_files[key].get("bytes") != after_files[key].get("bytes")
        )
    ]
    if changed != [SETTINGS_PATH]:
        raise AuditError(
            f"diagnostic durable delta is not exactly settings.txt: {changed!r}"
        )

    archived_settings_path = retry / "menufx-v9p94.post-diagnostic.settings.txt"
    archived_settings = archived_settings_path.read_bytes()
    after_settings = after_files[SETTINGS_PATH]
    before_settings = before_files[SETTINGS_PATH]
    if (
        file_sha256(archived_settings_path) != after_settings.get("sha256")
        or len(archived_settings) != after_settings.get("bytes")
    ):
        raise AuditError("archived post-diagnostic settings do not match the census")
    if archived_settings.count(AFTER_SELECTOR) != 1 or BEFORE_SELECTOR in archived_settings:
        raise AuditError("post-diagnostic settings do not contain the exact selector value 0")
    reconstructed_before = archived_settings.replace(AFTER_SELECTOR, BEFORE_SELECTOR)
    if (
        hashlib.sha256(reconstructed_before).hexdigest()
        != before_settings.get("sha256")
        or len(reconstructed_before) != before_settings.get("bytes")
    ):
        raise AuditError("the exact selector 2-to-0 rewrite does not explain the census delta")

    navigation_path = retry / "diagnostic-navigation.json"
    navigation = read_object(navigation_path)
    edges = navigation.get("edges")
    if not isinstance(edges, list) or len(edges) != 1 or not isinstance(edges[0], dict):
        raise AuditError("bounded diagnostic did not record exactly one edge")
    edge = edges[0]
    if (
        edge.get("id") != "diagnostic_my_levels_to_browser"
        or edge.get("source") != "dark_cloud_my_levels"
        or edge.get("destination") != "dark_cloud_online_levels"
        or edge.get("action_id") != "dark_cloud_browser.online_levels"
    ):
        raise AuditError("bounded diagnostic used an unexpected route")
    header = edge.get("header")
    before_endpoint = edge.get("before")
    after_endpoint = edge.get("after")
    if not all(isinstance(value, dict) for value in (header, before_endpoint, after_endpoint)):
        raise AuditError("bounded diagnostic edge has no measured endpoints")
    tabs = header.get("browser_tab_verification")
    settlement = header.get("settlement")
    if not isinstance(tabs, dict) or not isinstance(settlement, dict):
        raise AuditError("bounded diagnostic omitted tab or settlement verification")
    source_tab = tabs.get("source")
    destination_tab = tabs.get("destination")
    if (
        not isinstance(source_tab, dict)
        or source_tab.get("measured_tab") != "my_levels"
        or not isinstance(destination_tab, dict)
        or destination_tab.get("measured_tab") != "online_levels"
    ):
        raise AuditError("bounded diagnostic did not measure the claimed tabs")
    for side in ("source", "destination"):
        measured = settlement.get(side)
        if (
            not isinstance(measured, dict)
            or measured.get("consecutive_structural_samples", 0) < 40
            or measured.get("stable_span_milliseconds", 0) < 2000
        ):
            raise AuditError(f"bounded diagnostic {side} did not settle")
    source_rows = item_rows(before_endpoint.get("layout"))
    destination_rows = item_rows(after_endpoint.get("layout"))
    if len(source_rows) != 1 or destination_rows:
        raise AuditError("bounded diagnostic did not measure Item 1 disappearing")

    quiescence_path = retry / "host-quiescence-after.json"
    quiescence = read_object(quiescence_path)
    disposal_path = retry / "exact-pid-disposal.json"
    disposal = read_object(disposal_path)
    if quiescence.get("quiescent") is not True:
        raise AuditError("diagnostic exact-PID disposal left the host busy")
    disposal_before = disposal.get("before")
    if (
        not isinstance(disposal_before, dict)
        or disposal_before.get("process_id") != failure.get("process_id")
        or disposal.get("after", {}).get("exact_process_exited") is not True
    ):
        raise AuditError("diagnostic disposal receipt names the wrong PID")

    float_path = repo / "tests/fixtures/webgame/float-rng-goldens.json"
    output = {
        "schema": SCHEMA,
        "status": "QUESTION",
        "finding": (
            "the nearest read-only tab affordance produces a settled zero-row "
            "destination but intrinsically rewrites the durable tab selector"
        ),
        "authorization_boundary": {
            "ruling_limit": "no durable dark-cloud state mutation",
            "confirmation_launched": False,
            "primary_observation_accepted_as_campaign_data": False,
            "graph_or_golden_census_changed": False,
            "question": (
                "authorize the intrinsic DarkCloud.ViewingLevels 2-to-0 selector "
                "write for one confirming instance, or classify the bounded "
                "diagnostic as having no non-mutating qualifying affordance"
            ),
        },
        "discarded_first_launch": {
            "failure": first_failure,
            "receipt": receipt(first_failure_path, evidence),
            "disposal": receipt(primary / "exact-pid-disposal.json", evidence),
            "quiescence": receipt(primary / "host-quiescence-after.json", evidence),
        },
        "rejected_primary_observation": {
            "instance": failure.get("instance"),
            "process_id": failure.get("process_id"),
            "profile_state_identity_sha256": expected_identity,
            "edge_id": edge.get("id"),
            "source_tab": source_tab.get("measured_tab"),
            "destination_tab": destination_tab.get("measured_tab"),
            "source_item_row_count": len(source_rows),
            "destination_item_row_count": len(destination_rows),
            "source_frame_sha256": before_endpoint.get("frame_sha256"),
            "destination_frame_sha256": after_endpoint.get("frame_sha256"),
            "source_settlement": settlement.get("source"),
            "destination_settlement": settlement.get("destination"),
            "navigation": receipt(navigation_path, evidence),
            "failure": receipt(failure_path, evidence),
        },
        "durable_delta": {
            "changed_files": [
                {"root": SETTINGS_PATH[0], "relative_path": SETTINGS_PATH[1]}
            ],
            "before_selector": "DarkCloud.ViewingLevels=2",
            "after_selector": "DarkCloud.ViewingLevels=0",
            "before_sha256": before_settings.get("sha256"),
            "after_sha256": after_settings.get("sha256"),
            "bytes": after_settings.get("bytes"),
            "all_other_files_byte_identical": True,
            "single_same_length_rewrite_reconstructs_before_sha256": True,
            "before_census": receipt(before_path, evidence),
            "after_census": receipt(after_path, evidence),
            "archived_post_settings": receipt(archived_settings_path, evidence),
        },
        "launch_receipts": {
            "launch": receipt(retry / "launch.json", evidence),
            "profile_state": receipt(
                retry / "menufx-v9p94.native-menu-profile-state.json", evidence
            ),
            "stage_report": receipt(
                retry / "menufx-v9p94.stage-report.json", evidence
            ),
            "startup_status": receipt(
                retry / "menufx-v9p94.startup-status.json", evidence
            ),
            "loader_log": receipt(
                retry / "menufx-v9p94.solomondarkmodloader.log", evidence
            ),
            "exact_pid_disposal": receipt(disposal_path, evidence),
            "host_quiescence_after": receipt(quiescence_path, evidence),
        },
        "float_rng_fixture": {
            "path": "tests/fixtures/webgame/float-rng-goldens.json",
            "sha256": file_sha256(float_path),
            "bytes": float_path.stat().st_size,
        },
        "candidate_applied": False,
    }
    if output["float_rng_fixture"]["sha256"] != (
        "04b13d45611ee2c67dac2a73ff8572e7f948516eb6c05411686b609b970d9665"
    ):
        raise AuditError("float RNG fixture changed during the bounded diagnostic")
    write_object(args.output.resolve(), output)
    print(json.dumps(receipt(args.output.resolve(), evidence), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
