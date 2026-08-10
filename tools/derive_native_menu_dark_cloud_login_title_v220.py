#!/usr/bin/env python3
"""Derive the exact v2.20 Dark Cloud login title correction contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any


class TitleCorrectionBuildError(RuntimeError):
    """The accepted evidence no longer derives the bounded correction."""


LAYOUT_ID = "dark-cloud-login-settings"
SCREEN_ID = "dark_cloud_login_settings"
FIELD = "screen_title"
LANDED_VALUE = ""
SETTLED_VALUE = "Dark Cloud Browser"
AUDIT_RELATIVE = Path(
    "raw-v9/profile-select-new-game-edge/dark-cloud-login-title-stop-audit.json"
)
CANDIDATE_RELATIVE = Path(
    "raw-v9/candidates/candidate-v214-profile-final/menu-layouts/"
    "dark-cloud-login-settings.json"
)
LANDED_RELATIVE = Path(
    "tests/fixtures/webgame/menu-layouts/dark-cloud-login-settings.json"
)
BASELINE_RELATIVE = Path(
    "webgame-contracts/baseline-snapshots/menu-layouts/"
    "dark-cloud-login-settings.json"
)
EXPECTED_ENDPOINTS = {
    ("dark_cloud_to_login_settings", "after", "dark_cloud_browser.login"),
    ("dark_cloud_login_to_browser", "before", "done_button_click"),
}


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise TitleCorrectionBuildError(f"{label} is not readable JSON: {error}") from error
    if not isinstance(value, dict):
        raise TitleCorrectionBuildError(f"{label} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def receipt(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TitleCorrectionBuildError(f"v2.20 source file is absent: {path}")
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def evidence_receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = evidence_root.resolve()
    if not resolved.is_relative_to(root):
        raise TitleCorrectionBuildError("v2.20 evidence path escapes the campaign root")
    return {
        "evidence_path": resolved.relative_to(root).as_posix(),
        **receipt(resolved),
    }


def repo_receipt(path: Path, repo_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = repo_root.resolve()
    if not resolved.is_relative_to(root):
        raise TitleCorrectionBuildError("v2.20 repository path escapes the clone")
    return {
        "repo_relative_path": resolved.relative_to(root).as_posix(),
        **receipt(resolved),
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def trace_receipt(
    evidence_root: Path,
    audit_recording: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    path_value = audit_recording.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise TitleCorrectionBuildError(f"v2.20 {label} trace path is absent")
    path = (evidence_root / path_value).resolve()
    observed = evidence_receipt(path, evidence_root)
    if {
        "sha256": observed["sha256"],
        "bytes": observed["bytes"],
    } != {
        "sha256": audit_recording.get("sha256"),
        "bytes": audit_recording.get("bytes"),
    }:
        raise TitleCorrectionBuildError(f"v2.20 {label} trace receipt is false")
    return observed


def build(
    repo_root: Path,
    evidence_root: Path,
    candidate_root: Path,
    navigation_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    audit_path = evidence_root / AUDIT_RELATIVE
    candidate_path = candidate_root / "menu-layouts/dark-cloud-login-settings.json"
    expected_candidate_path = evidence_root / CANDIDATE_RELATIVE
    if candidate_path.resolve() != expected_candidate_path.resolve():
        raise TitleCorrectionBuildError(
            "v2.20 candidate root does not name the accepted qualified corpus"
        )
    landed_path = repo_root / LANDED_RELATIVE
    baseline_path = repo_root / BASELINE_RELATIVE
    audit = read_object(audit_path, "v2.20 source STOP audit")
    landed = read_object(landed_path, "v2.20 landed fixture")
    baseline = read_object(baseline_path, "v2.20 baseline snapshot")
    candidate = read_object(candidate_path, "v2.20 settled candidate")
    navigation = read_object(navigation_path, "v2.20 resolved navigation")

    landed_layout = landed.get("layout")
    candidate_layout = candidate.get("layout")
    candidate_header = candidate.get("header")
    if (
        not isinstance(landed_layout, dict)
        or not isinstance(candidate_layout, dict)
        or not isinstance(candidate_header, dict)
        or baseline != landed
        or landed_layout.get("screen_id") != SCREEN_ID
        or candidate_layout.get("screen_id") != SCREEN_ID
        or landed_layout.get(FIELD) != LANDED_VALUE
        or candidate_layout.get(FIELD) != SETTLED_VALUE
    ):
        raise TitleCorrectionBuildError(
            "v2.20 exact landed/candidate title identity no longer reproduces"
        )
    source = candidate_header.get("source")
    profile_state = candidate_header.get("profile_state")
    profile_identity = (
        profile_state.get("profile_state_identity_sha256")
        if isinstance(profile_state, dict)
        else None
    )
    if (
        not isinstance(source, dict)
        or not isinstance(profile_identity, str)
        or len(profile_identity) != 64
        or source.get("profile_state_identity_sha256") != profile_identity
    ):
        raise TitleCorrectionBuildError(
            "v2.20 candidate lost machine-derived profile provenance"
        )

    audit_receipt = evidence_receipt(audit_path, evidence_root)
    landed_receipt = repo_receipt(landed_path, repo_root)
    baseline_receipt = repo_receipt(baseline_path, repo_root)
    candidate_receipt = evidence_receipt(candidate_path, evidence_root)
    if (
        audit.get("schema")
        != "solomon-dark-native-menu-dark-cloud-login-title-stop-audit-v1"
        or audit.get("status") != "QUESTION"
        or audit.get("layout_id") != LAYOUT_ID
        or audit.get("screen_id") != SCREEN_ID
        or audit.get("landed_screen_title") != LANDED_VALUE
        or audit.get("settled_screen_title") != SETTLED_VALUE
        or audit.get("candidate_applied") is not False
        or audit.get("landed_fixture")
        != {"path": landed_receipt["repo_relative_path"], **receipt(landed_path)}
        or audit.get("baseline_snapshot")
        != {"path": baseline_receipt["repo_relative_path"], **receipt(baseline_path)}
        or audit.get("candidate_fixture")
        != {"path": candidate_receipt["evidence_path"], **receipt(candidate_path)}
    ):
        raise TitleCorrectionBuildError(
            "v2.20 accepted STOP audit does not match its source files"
        )

    paired = audit.get("paired_settlement")
    if not isinstance(paired, dict) or paired.get(
        "profile_state_identity_sha256"
    ) != profile_identity:
        raise TitleCorrectionBuildError("v2.20 paired settlement identity changed")
    trace_records: dict[str, dict[str, Any]] = {}
    for role in ("primary", "confirmation"):
        observation = paired.get(role)
        if (
            not isinstance(observation, dict)
            or observation.get("sample_count") != 40
            or observation.get("stable_span_milliseconds", 0) < 2_000
            or observation.get("semantic_surface") != SCREEN_ID
            or observation.get("screen_id") != SCREEN_ID
            or observation.get("screen_title") != SETTLED_VALUE
            or observation.get("element_count")
            != len(candidate_layout.get("elements", []))
            or observation.get("profile_state_identity_sha256") != profile_identity
            or not isinstance(observation.get("recording"), dict)
        ):
            raise TitleCorrectionBuildError(
                f"v2.20 {role} settlement no longer proves the exact title"
            )
        trace_records[role] = {
            "instance": observation.get("instance"),
            "process_id": observation.get("process_id"),
            "sample_count": observation.get("sample_count"),
            "stable_span_milliseconds": observation.get(
                "stable_span_milliseconds"
            ),
            "measured_generation": observation.get("generation"),
            "recording": trace_receipt(
                evidence_root, observation["recording"], role
            ),
        }
    if (
        (trace_records["primary"]["instance"], trace_records["primary"]["process_id"])
        == (
            trace_records["confirmation"]["instance"],
            trace_records["confirmation"]["process_id"],
        )
        or paired.get("core_equality", {}).get("core_equal") is not True
        or paired.get("core_equality", {}).get("zero_residual") is not True
    ):
        raise TitleCorrectionBuildError(
            "v2.20 title did not reproduce in two exact-core instances"
        )

    edges = navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise TitleCorrectionBuildError("v2.20 endpoint sweep reached no edges")
    endpoints: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for side in ("before", "after"):
            endpoint = edge.get(side)
            if not isinstance(endpoint, dict) or endpoint.get("layout_id") != LAYOUT_ID:
                continue
            identity = (str(edge.get("id")), side, str(edge.get("trigger")))
            if identity in identities:
                raise TitleCorrectionBuildError("v2.20 endpoint lookup is ambiguous")
            identities.add(identity)
            layout = endpoint.get("layout")
            if (
                not isinstance(layout, dict)
                or layout.get(FIELD) != SETTLED_VALUE
                or layout.get("structural_core_sha256")
                != candidate_layout.get("structural_core_sha256")
                or len(layout.get("elements", []))
                != len(candidate_layout.get("elements", []))
            ):
                raise TitleCorrectionBuildError(
                    f"v2.20 endpoint {identity} does not bind the settled title core"
                )
            endpoints.append(
                {
                    "edge_id": identity[0],
                    "side": side,
                    "trigger": identity[2],
                    "semantic_surface": endpoint.get("semantic_surface"),
                    "tagged_screen": endpoint.get("tagged_screen"),
                    "layout_generation": endpoint.get("layout_generation"),
                    "element_count": endpoint.get("element_count"),
                    "screen_title": layout.get(FIELD),
                    "structural_core_sha256": layout.get(
                        "structural_core_sha256"
                    ),
                    "frame_sha256": endpoint.get("frame_sha256"),
                }
            )
    if identities != EXPECTED_ENDPOINTS:
        raise TitleCorrectionBuildError(
            "v2.20 endpoint sweep did not reach both exact bound endpoints"
        )
    endpoints.sort(key=lambda value: (value["edge_id"], value["side"]))
    if endpoints != audit.get("navigation_endpoints"):
        raise TitleCorrectionBuildError(
            "v2.20 endpoint receipts differ from the accepted audit"
        )

    promoter_stop = audit.get("promoter_stop")
    if not isinstance(promoter_stop, dict):
        raise TitleCorrectionBuildError("v2.20 source promoter STOP is absent")
    stop_receipt = trace_receipt(evidence_root, promoter_stop, "promoter STOP")
    contract = {
        "schema": "solomon-dark-native-menu-dark-cloud-login-title-v220",
        "settlement_spec": "2.20",
        "layout_id": LAYOUT_ID,
        "screen_id": SCREEN_ID,
        "field": FIELD,
        "landed_value": LANDED_VALUE,
        "settled_value": SETTLED_VALUE,
        "landed_fixture": landed_receipt,
        "baseline_snapshot": baseline_receipt,
        "superseding_candidate": {
            **candidate_receipt,
            "element_count": len(candidate_layout["elements"]),
            "structural_core_sha256": candidate_layout.get(
                "structural_core_sha256"
            ),
        },
        "source_stop_audit": audit_receipt,
        "source_promoter_stop": {
            **stop_receipt,
            "message": audit.get("promoter_stop_message"),
        },
        "source_provenance": copy.deepcopy(source),
        "profile_state_identity_sha256": profile_identity,
        "paired_settlement": {
            **trace_records,
            "core_equality": copy.deepcopy(paired.get("core_equality")),
        },
        "bound_endpoints": endpoints,
        "authorization": (
            "exactly one field on exactly dark-cloud-login-settings: "
            "layout.screen_title empty to Dark Cloud Browser"
        ),
        "forbidden": [
            "title tolerance",
            "another layout",
            "another field",
            "another settled title value",
            "candidate rewriting",
        ],
        "derivation": {
            "tool": "tools/derive_native_menu_dark_cloud_login_title_v220.py",
            "tool_sha256": sha256_file(Path(__file__).resolve()),
            "method": (
                "machine-derived from the committed landed fixture, byte-identical "
                "baseline snapshot, qualified candidate, two settled traces, and "
                "both measured navigation bindings"
            ),
        },
    }
    atomic_json(output_path, contract)
    return {
        "success": True,
        "output": str(output_path),
        "sha256": sha256_file(output_path),
        "bytes": output_path.stat().st_size,
        "endpoint_count": len(endpoints),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = build(
            args.repo_root.resolve(),
            args.evidence_root.resolve(),
            args.candidate_root.resolve(),
            args.navigation_recording.resolve(),
            args.output.resolve(),
        )
    except (KeyError, OSError, TypeError, ValueError, TitleCorrectionBuildError) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
