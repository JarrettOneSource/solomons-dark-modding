#!/usr/bin/env python3
"""Pair the authorized My Levels-to-public-tab Item 1 diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_generation_v219 import _expected_core
from native_menu_profile_state import load_profile_state_baseline


SCHEMA = "solomon-dark-native-menu-item-row-carryover-pair-v1"
BEFORE_SELECTOR = b"DarkCloud.ViewingLevels=2"
AFTER_SELECTOR = b"DarkCloud.ViewingLevels=0"


class AuditError(RuntimeError):
    """The authorized paired diagnostic no longer proves one exact outcome."""


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


def one_edge(path: Path) -> dict[str, Any]:
    recording = read_object(path)
    edges = recording.get("edges")
    if not isinstance(edges, list) or len(edges) != 1 or not isinstance(edges[0], dict):
        raise AuditError(f"{path} does not contain exactly one measured edge")
    edge = edges[0]
    if (
        edge.get("id") != "diagnostic_my_levels_to_browser"
        or edge.get("source") != "dark_cloud_my_levels"
        or edge.get("destination") != "dark_cloud_online_levels"
        or edge.get("action_id") != "dark_cloud_browser.online_levels"
    ):
        raise AuditError(f"{path} contains an unexpected diagnostic route")
    return edge


def item_rows(endpoint: dict[str, Any]) -> list[dict[str, Any]]:
    layout = endpoint.get("layout")
    elements = layout.get("elements") if isinstance(layout, dict) else None
    if not isinstance(elements, list):
        raise AuditError("diagnostic endpoint has no measured member census")
    return [
        element
        for element in elements
        if isinstance(element, dict) and element.get("text") == "Item 1"
    ]


def core_receipt(endpoint: dict[str, Any], label: str) -> dict[str, Any]:
    layout = endpoint.get("layout")
    if not isinstance(layout, dict):
        raise AuditError(f"{label} has no measured layout")
    expected = _expected_core(layout, label)
    settlement = endpoint.get("settlement")
    if (
        not isinstance(settlement, dict)
        or settlement.get("consecutive_structural_samples", 0) < 40
        or settlement.get("stable_span_milliseconds", 0) < 2_000
    ):
        raise AuditError(f"{label} did not settle under the required window")
    return {
        "member_count": expected["member_count"],
        "member_multiset_sha256": expected["member_multiset_sha256"],
        "relative_sequence_sha256": expected["relative_sequence_sha256"],
        "recorded_structural_sha256": settlement.get("structural_sha256"),
        "generation": endpoint.get("layout_generation"),
        "sample_count": settlement.get("consecutive_structural_samples"),
        "stable_span_milliseconds": settlement.get("stable_span_milliseconds"),
        "frame_sha256": endpoint.get("frame_sha256"),
    }


def census_map(value: dict[str, Any], label: str) -> dict[tuple[str, str], dict[str, Any]]:
    files = value.get("files")
    if not isinstance(files, list) or not files:
        raise AuditError(f"{label} durable census reached no real files")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise AuditError(f"{label} durable census contains a non-object")
        key = (str(entry.get("root")), str(entry.get("relative_path")))
        if key in result:
            raise AuditError(f"{label} durable census is ambiguous at {key!r}")
        result[key] = entry
    return result


def durable_delta(
    root: Path,
    before_path: Path,
    after_path: Path,
    settings_path: Path,
    expected_identity: str,
) -> dict[str, Any]:
    before = read_object(before_path)
    after = read_object(after_path)
    if any(
        value.get("profile_state_identity_sha256") != expected_identity
        for value in (before, after)
    ):
        raise AuditError("diagnostic durable census is not bound to fresh_install")
    left = census_map(before, "before")
    right = census_map(after, "after")
    if left.keys() != right.keys():
        raise AuditError("diagnostic changed durable-file membership")
    changed = [
        key
        for key in left
        if left[key].get("sha256") != right[key].get("sha256")
        or left[key].get("bytes") != right[key].get("bytes")
    ]
    settings_key = ("stage_sandbox", "settings.txt")
    if changed != [settings_key]:
        raise AuditError("diagnostic durable delta exceeds the one selector file")
    raw = settings_path.read_bytes()
    if (
        file_sha256(settings_path) != right[settings_key].get("sha256")
        or len(raw) != right[settings_key].get("bytes")
        or raw.count(AFTER_SELECTOR) != 1
        or BEFORE_SELECTOR in raw
    ):
        raise AuditError("archived diagnostic settings are not the after-census bytes")
    reconstructed = raw.replace(AFTER_SELECTOR, BEFORE_SELECTOR)
    if (
        hashlib.sha256(reconstructed).hexdigest() != left[settings_key].get("sha256")
        or len(reconstructed) != left[settings_key].get("bytes")
    ):
        raise AuditError("selector 2-to-0 rewrite does not reconstruct before bytes")
    return {
        "changed_file_count": 1,
        "changed_file": "stage_sandbox/settings.txt",
        "before_selector": "DarkCloud.ViewingLevels=2",
        "after_selector": "DarkCloud.ViewingLevels=0",
        "before_sha256": left[settings_key].get("sha256"),
        "after_sha256": right[settings_key].get("sha256"),
        "bytes": right[settings_key].get("bytes"),
        "all_other_files_byte_identical": True,
        "single_same_length_rewrite_reconstructs_before_sha256": True,
        "before_census": receipt(before_path, root),
        "after_census": receipt(after_path, root),
        "archived_post_settings": receipt(settings_path, root),
    }


def role(
    evidence: Path,
    directory: Path,
    settings_filename: str,
    expected_identity: str,
) -> dict[str, Any]:
    navigation_path = directory / "diagnostic-navigation.json"
    edge = one_edge(navigation_path)
    before = edge.get("before")
    after = edge.get("after")
    header = edge.get("header")
    if not all(isinstance(value, dict) for value in (before, after, header)):
        raise AuditError("diagnostic edge omitted a measured endpoint")
    session = header.get("source")
    if (
        not isinstance(session, dict)
        or session.get("profile_state_identity_sha256") != expected_identity
    ):
        raise AuditError("diagnostic edge has the wrong profile-state identity")
    tabs = header.get("browser_tab_verification")
    if (
        not isinstance(tabs, dict)
        or tabs.get("source", {}).get("measured_tab") != "my_levels"
        or tabs.get("destination", {}).get("measured_tab") != "online_levels"
    ):
        raise AuditError("diagnostic edge did not machine-measure both tabs")
    source_rows = item_rows(before)
    destination_rows = item_rows(after)
    if len(source_rows) != 1 or destination_rows:
        raise AuditError("diagnostic did not measure Item 1 disappearing")
    quiescence_path = directory / "host-quiescence-after.json"
    if read_object(quiescence_path).get("quiescent") is not True:
        raise AuditError("diagnostic role did not dispose its exact PID")
    launch_path = directory / "launch.json"
    launch = read_object(launch_path)
    if launch.get("profileStateIdentitySha256") != expected_identity:
        raise AuditError("diagnostic launch did not request the pinned baseline")
    return {
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "profile_state_identity_sha256": expected_identity,
        "source_item_row_count": len(source_rows),
        "destination_item_row_count": len(destination_rows),
        "source_core": core_receipt(before, f"{directory.name} source"),
        "destination_core": core_receipt(after, f"{directory.name} destination"),
        "durable_delta": durable_delta(
            evidence,
            directory / "before-diagnostic-durable-file-census.json",
            directory / "after-diagnostic-durable-file-census.json",
            directory / settings_filename,
            expected_identity,
        ),
        "navigation": receipt(navigation_path, evidence),
        "launch": receipt(launch_path, evidence),
        "exact_pid_disposal": receipt(directory / "exact-pid-disposal.json", evidence),
        "host_quiescence_after": receipt(quiescence_path, evidence),
    }


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
    expected_identity = load_profile_state_baseline(repo)["identity"]
    primary = role(
        evidence,
        diagnostic / "primary-retry",
        "menufx-v9p94.post-diagnostic.settings.txt",
        expected_identity,
    )
    confirmation = role(
        evidence,
        diagnostic / "confirmation",
        "menufx-v9p95.post-diagnostic.settings.txt",
        expected_identity,
    )
    if (
        (primary["instance"], primary["process_id"])
        == (confirmation["instance"], confirmation["process_id"])
    ):
        raise AuditError("diagnostic pair is not two independent instances")
    for endpoint in ("source_core", "destination_core"):
        for field in (
            "member_count",
            "member_multiset_sha256",
            "relative_sequence_sha256",
            "recorded_structural_sha256",
            "frame_sha256",
        ):
            if primary[endpoint][field] != confirmation[endpoint][field]:
                raise AuditError(f"diagnostic pair differs at {endpoint}.{field}")

    old_guard_path = diagnostic / "item-row-carryover-guard-audit.json"
    old_guard = read_object(old_guard_path)
    if (
        old_guard.get("status") != "QUESTION"
        or old_guard.get("authorization_boundary", {}).get(
            "primary_observation_accepted_as_campaign_data"
        )
        is not False
    ):
        raise AuditError("the archived primary guard trip no longer reproduces")
    confirmation_summary_path = diagnostic / "confirmation/role-summary.json"
    confirmation_summary = read_object(confirmation_summary_path)
    if (
        confirmation_summary.get("outcome") != "zero_item_rows"
        or confirmation_summary.get("durable_dark_cloud_state", {}).get(
            "authorized_intrinsic_selector_write"
        )
        is not True
    ):
        raise AuditError("confirmation wrapper did not admit only the selector write")

    float_path = repo / "tests/fixtures/webgame/float-rng-goldens.json"
    audit = {
        "schema": SCHEMA,
        "status": "PROVEN",
        "outcome": "public_tab_settles_without_my_levels_item_row",
        "mechanism": (
            "the shared native list control does not carry the populated My Levels "
            "row into Online Levels on the qualified route"
        ),
        "legacy_disposition": (
            "four-tab landed rows are unprovenanced era list or cache state by elimination"
        ),
        "primary": primary,
        "confirmation": confirmation,
        "cross_instance": {
            "source_core_equal": True,
            "destination_core_equal": True,
            "source_frame_bit_equal": True,
            "destination_frame_bit_equal": True,
            "source_item_row_count": 1,
            "destination_item_row_count": 0,
            "independent_instances": True,
        },
        "ruling_a": {
            "primary_re_admitted_from_complete_v9p94_receipts": True,
            "old_guard_audit": receipt(old_guard_path, evidence),
            "confirmation_role_summary": receipt(
                confirmation_summary_path, evidence
            ),
            "authorized_delta_scope": (
                "one intrinsic DarkCloud.ViewingLevels 2-to-0 rewrite in each "
                "instance-owned stage_sandbox/settings.txt"
            ),
            "no_general_durable_write_tolerance": True,
        },
        "graph_disposition": "documentation_evidence_only_not_a_golden_edge",
        "state_or_edge_census_changed": False,
        "candidate_applied": False,
        "float_rng_fixture": {
            "path": "tests/fixtures/webgame/float-rng-goldens.json",
            "sha256": file_sha256(float_path),
            "bytes": float_path.stat().st_size,
        },
    }
    if audit["float_rng_fixture"]["sha256"] != (
        "04b13d45611ee2c67dac2a73ff8572e7f948516eb6c05411686b609b970d9665"
    ):
        raise AuditError("float RNG fixture changed during the paired diagnostic")
    write_object(args.output.resolve(), audit)
    print(json.dumps(receipt(args.output.resolve(), evidence), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
