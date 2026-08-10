#!/usr/bin/env python3
"""Audit the unclassified landed Item 1 row on pristine Dark Cloud tabs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from native_menu_landed_diagnosis_v25 import _signature, canonical_bytes
from native_menu_profile_state import FRESH_BASELINE_ID, load_profile_state_baseline


PUBLIC_TABS = (
    "dark-cloud-browser",
    "dark-cloud-recent",
    "dark-cloud-online-levels",
)
MY_LEVELS = "dark-cloud-my-levels"
ITEM_TEXT = "Item 1"


class AuditError(RuntimeError):
    """One claimed Dark Cloud row witness is absent or ambiguous."""


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


def receipt(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
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


def read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8")


def semantic_multiset_sha256(layout: dict[str, Any]) -> str:
    counter = Counter(
        hashlib.sha256(_signature(element)).hexdigest()
        for element in layout.get("elements", [])
        if isinstance(element, dict)
    )
    entries = [
        {"semantic_sha256": key, "count": counter[key]}
        for key in sorted(counter)
    ]
    return hashlib.sha256(canonical_bytes(entries)).hexdigest()


def item_rows(layout: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        element
        for element in layout.get("elements", [])
        if isinstance(element, dict) and element.get("text") == ITEM_TEXT
    ]


def recording_from_receipt(
    candidate_root: Path,
    directory: str,
    recorded: Any,
    label: str,
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(recorded, dict):
        raise AuditError(f"{label} has no recording receipt")
    filename = recorded.get("evidence_filename")
    if not isinstance(filename, str) or not filename:
        raise AuditError(f"{label} recording receipt has no filename")
    path = (candidate_root / directory / filename).resolve()
    root = (candidate_root / directory).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AuditError(f"{label} recording is absent or escapes its root")
    if (
        recorded.get("sha256") != file_sha256(path)
        or recorded.get("bytes") != path.stat().st_size
    ):
        raise AuditError(f"{label} recording receipt is false")
    return path, read_object(path)


def sample_payloads(recording: dict[str, Any], label: str) -> dict[str, Any]:
    phases = recording.get("structural_phases")
    settled = recording.get("settled_window_samples")
    if (
        not isinstance(phases, list)
        or not phases
        or not isinstance(settled, list)
        or len(settled) < 40
    ):
        raise AuditError(f"{label} did not reach population plus 40 settled samples")
    phase_payloads = [
        phase.get("payload") if isinstance(phase, dict) else None
        for phase in phases
    ]
    settled_payloads = [
        sample.get("payload") if isinstance(sample, dict) else None
        for sample in settled
    ]
    if not all(isinstance(value, dict) for value in (*phase_payloads, *settled_payloads)):
        raise AuditError(f"{label} contains a sample without payload")
    elapsed = [sample.get("elapsed_milliseconds") for sample in settled]
    if not all(isinstance(value, (int, float)) for value in elapsed):
        raise AuditError(f"{label} settled window has no measured span")
    return {
        "population_phase_count": len(phase_payloads),
        "population_element_counts": [
            len(value["elements"]) for value in phase_payloads
        ],
        "population_generations": [value.get("generation") for value in phase_payloads],
        "population_item_row_counts": [len(item_rows(value)) for value in phase_payloads],
        "settled_sample_count": len(settled_payloads),
        "settled_span_milliseconds": elapsed[-1] - elapsed[0],
        "settled_generations": sorted(
            {value.get("generation") for value in settled_payloads}
        ),
        "settled_element_counts": sorted(
            {len(value["elements"]) for value in settled_payloads}
        ),
        "settled_item_row_counts": sorted(
            {len(item_rows(value)) for value in settled_payloads}
        ),
    }


def layout_audit(
    repo_root: Path, candidate_root: Path, layout_id: str
) -> dict[str, Any]:
    landed_path = repo_root / f"tests/fixtures/webgame/menu-layouts/{layout_id}.json"
    candidate_path = candidate_root / f"menu-layouts/{layout_id}.json"
    landed_fixture = read_object(landed_path)
    candidate_fixture = read_object(candidate_path)
    landed = landed_fixture.get("layout")
    candidate = candidate_fixture.get("layout")
    header = candidate_fixture.get("header")
    if not all(isinstance(value, dict) for value in (landed, candidate, header)):
        raise AuditError(f"{layout_id} fixture has no header/layout")
    profile = header.get("profile_state")
    baseline = load_profile_state_baseline(repo_root)
    if (
        not isinstance(profile, dict)
        or profile.get("baseline_id") != FRESH_BASELINE_ID
        or profile.get("profile_state_identity_sha256") != baseline["identity"]
    ):
        raise AuditError(f"{layout_id} candidate is not bound to fresh_install")
    primary_path, primary = recording_from_receipt(
        candidate_root,
        "menu-settlement-traces",
        header.get("settlement_trace", header.get("raw_recording")),
        f"{layout_id} primary",
    )
    confirmation_path, confirmation = recording_from_receipt(
        candidate_root,
        "menu-animation-confirmations",
        header.get("animation_confirmation"),
        f"{layout_id} confirmation",
    )
    return {
        "layout_id": layout_id,
        "landed": {
            "fixture": receipt(landed_path),
            "generation": landed.get("generation"),
            "element_count": len(landed.get("elements", [])),
            "semantic_multiset_sha256": semantic_multiset_sha256(landed),
            "item_rows": item_rows(landed),
            "instance": landed_fixture.get("header", {}).get("instance"),
            "process_id": landed_fixture.get("header", {}).get("process_id"),
            "captured_at_utc": landed_fixture.get("header", {}).get("captured_at_utc"),
            "profile_state_provenance_present": isinstance(
                landed_fixture.get("header", {}).get("profile_state"), dict
            ),
        },
        "settled": {
            "fixture": receipt(candidate_path),
            "generation": candidate.get("generation"),
            "element_count": len(candidate.get("elements", [])),
            "semantic_multiset_sha256": semantic_multiset_sha256(candidate),
            "item_rows": item_rows(candidate),
            "profile_state_identity_sha256": profile.get(
                "profile_state_identity_sha256"
            ),
            "primary": {
                "recording": receipt(primary_path),
                **sample_payloads(primary, f"{layout_id} primary"),
            },
            "confirmation": {
                "recording": receipt(confirmation_path),
                **sample_payloads(confirmation, f"{layout_id} confirmation"),
            },
        },
    }


def navigation_audit(path: Path) -> list[dict[str, Any]]:
    navigation = read_object(path)
    required = (
        "main_to_dark_cloud",
        "dark_cloud_to_recent",
        "dark_cloud_recent_to_online",
        "dark_cloud_online_to_my_levels",
    )
    by_id = {
        edge.get("id"): edge
        for edge in navigation.get("edges", [])
        if isinstance(edge, dict) and isinstance(edge.get("id"), str)
    }
    if any(edge_id not in by_id for edge_id in required):
        raise AuditError("Dark Cloud navigation audit missed a named edge")
    result: list[dict[str, Any]] = []
    for edge_id in required:
        edge = by_id[edge_id]
        endpoints: dict[str, Any] = {}
        for side in ("before", "after"):
            endpoint = edge.get(side)
            layout = endpoint.get("layout") if isinstance(endpoint, dict) else None
            if not isinstance(layout, dict):
                raise AuditError(f"{edge_id}.{side} has no measured layout")
            endpoints[side] = {
                "layout_id": endpoint.get("layout_id"),
                "generation": endpoint.get("layout_generation"),
                "element_count": len(layout.get("elements", [])),
                "item_row_count": len(item_rows(layout)),
                "frame_sha256": endpoint.get("frame_sha256"),
            }
        result.append({"edge_id": edge_id, **endpoints})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--resolved-navigation", type=Path, required=True)
    parser.add_argument("--promoter-stop-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    candidate = args.candidate_root.resolve()
    audits = {
        layout_id: layout_audit(repo, candidate, layout_id)
        for layout_id in (*PUBLIC_TABS, MY_LEVELS)
    }
    baseline = load_profile_state_baseline(repo)
    for layout_id in PUBLIC_TABS:
        audit = audits[layout_id]
        if (
            len(audit["landed"]["item_rows"]) != 1
            or audit["settled"]["item_rows"]
            or audit["settled"]["primary"]["population_item_row_counts"] != [0]
            or audit["settled"]["confirmation"]["population_item_row_counts"] != [0]
            or audit["settled"]["primary"]["settled_item_row_counts"] != [0]
            or audit["settled"]["confirmation"]["settled_item_row_counts"] != [0]
        ):
            raise AuditError(f"{layout_id} Item 1 residual no longer reproduces")
    my_levels = audits[MY_LEVELS]
    if (
        len(my_levels["landed"]["item_rows"]) != 1
        or len(my_levels["settled"]["item_rows"]) != 1
        or my_levels["settled"]["primary"]["settled_item_row_counts"] != [1]
        or my_levels["settled"]["confirmation"]["settled_item_row_counts"] != [1]
    ):
        raise AuditError("My Levels Item 1 control witness no longer reproduces")
    stop_text = read_text_auto(args.promoter_stop_log.resolve())
    expected_stop = (
        "STOP: standalone dark-cloud-browser: landed-vs-settled mismatch "
        "survives ambient, population, overlay, and animation diagnosis: "
        "'dark_cloud_browser.text.item_1.1' / 'Item 1'"
    )
    if expected_stop not in stop_text:
        raise AuditError("promoter transcript lost the exact Item 1 STOP")
    result = {
        "schema": "solomon-dark-native-menu-dark-cloud-item-row-stop-audit-v1",
        "status": "QUESTION",
        "finding": (
            "landed public-tab fixtures contain one unclassified Item 1 text "
            "row absent from both fresh population traces and settled windows"
        ),
        "profile_state_identity_sha256": baseline["identity"],
        "affected_layouts": list(PUBLIC_TABS),
        "control_layout": MY_LEVELS,
        "layouts": audits,
        "navigation": {
            "recording": receipt(args.resolved_navigation.resolve()),
            "entry_chain": navigation_audit(args.resolved_navigation.resolve()),
        },
        "promoter_stop": {
            "reason": expected_stop,
            "transcript": receipt(args.promoter_stop_log.resolve()),
        },
        "classification": {
            "ambient_lifecycle": "rejected_text_members_cannot_be_ambient",
            "population_v21": "rejected_absent_from_both_population_traces",
            "overlay_v24": "rejected_text_is_not_an_overlay_draw",
            "animation": "rejected_text_member_has_no_authorized_variance",
            "v219_generation": "irrelevant_non_generation_semantic_difference",
            "verdict": "requires_bounded_ATC_ruling_before_promotion",
        },
        "candidate_applied": False,
    }
    write_object(args.output.resolve(), result)
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
