#!/usr/bin/env python3
"""Audit the unauthorized Dark Cloud login-settings screen-title difference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_generation_v219 import derive_pair_core_equality


class AuditError(RuntimeError):
    """A required title, pair, endpoint, or no-write witness is absent."""


PROFILE_IDENTITY = (
    "0539412d5c91207d5b225e86f79795d260fe7b73b8d9a1c29166bd09b445e372"
)
PROMOTER_STOP = (
    "STOP: standalone dark-cloud-login-settings: landed-vs-settled mismatch "
    "outside authorized classes: layout field 'screen_title' differs"
)
FLOAT_SHA256 = (
    "04b13d45611ee2c67dac2a73ff8572e7f948516eb6c05411686b609b970d9665"
)
ENDPOINTS = {
    ("dark_cloud_to_login_settings", "after"),
    ("dark_cloud_login_to_browser", "before"),
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise AuditError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def receipt(path: Path, root: Path | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": (
            resolved.relative_to(root.resolve()).as_posix()
            if root is not None
            else str(resolved)
        ),
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def receipt_matches(recorded: Any, path: Path) -> bool:
    return isinstance(recorded, dict) and {
        "sha256": recorded.get("sha256"),
        "bytes": recorded.get("bytes"),
    } == {
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def trace_summary(
    trace: dict[str, Any], label: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    samples = trace.get("settled_window_samples")
    header = trace.get("header")
    if (
        not isinstance(samples, list)
        or len(samples) < 40
        or not all(isinstance(sample, dict) for sample in samples)
        or not isinstance(header, dict)
    ):
        raise AuditError(f"{label} has no real 40-sample settled window")
    payloads = [sample.get("payload") for sample in samples]
    if not all(isinstance(payload, dict) for payload in payloads):
        raise AuditError(f"{label} contains a sample without payload")
    titles = {payload.get("screen_title") for payload in payloads}
    screens = {payload.get("screen_id") for payload in payloads}
    surfaces = {sample.get("semantic_surface") for sample in samples}
    generations = {payload.get("generation") for payload in payloads}
    element_counts = {len(payload.get("elements", [])) for payload in payloads}
    elapsed = [sample.get("elapsed_milliseconds") for sample in samples]
    if (
        titles != {"Dark Cloud Browser"}
        or screens != {"dark_cloud_login_settings"}
        or surfaces != {"dark_cloud_login_settings"}
        or len(generations) != 1
        or element_counts != {77}
        or not all(isinstance(value, (int, float)) for value in elapsed)
        or elapsed[-1] - elapsed[0] < 2_000
        or header.get("source", {}).get("profile_state_identity_sha256")
        != PROFILE_IDENTITY
    ):
        raise AuditError(f"{label} does not reproduce the settled title state")
    return samples, {
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "sample_count": len(samples),
        "stable_span_milliseconds": elapsed[-1] - elapsed[0],
        "semantic_surface": next(iter(surfaces)),
        "screen_id": next(iter(screens)),
        "screen_title": next(iter(titles)),
        "generation": next(iter(generations)),
        "element_count": next(iter(element_counts)),
        "profile_state_identity_sha256": PROFILE_IDENTITY,
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--navigation", type=Path, required=True)
    parser.add_argument("--promoter-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    candidate_root = args.candidate_root.resolve()
    evidence_root = args.evidence_root.resolve()
    landed_path = (
        repo_root
        / "tests/fixtures/webgame/menu-layouts/dark-cloud-login-settings.json"
    )
    baseline_path = (
        repo_root
        / "webgame-contracts/baseline-snapshots/menu-layouts/dark-cloud-login-settings.json"
    )
    candidate_path = candidate_root / "menu-layouts/dark-cloud-login-settings.json"
    if landed_path.read_bytes() != baseline_path.read_bytes():
        raise AuditError("Dark Cloud login-settings landed fixture changed during dry promotion")
    landed = read_object(landed_path)
    candidate = read_object(candidate_path)
    landed_layout = landed.get("layout")
    candidate_layout = candidate.get("layout")
    candidate_header = candidate.get("header")
    if not all(
        isinstance(value, dict)
        for value in (landed_layout, candidate_layout, candidate_header)
    ):
        raise AuditError("Dark Cloud login-settings fixture has no header/layout")
    if (
        landed_layout.get("screen_id") != "dark_cloud_login_settings"
        or landed_layout.get("screen_title") != ""
        or candidate_layout.get("screen_id") != "dark_cloud_login_settings"
        or candidate_layout.get("screen_title") != "Dark Cloud Browser"
        or len(candidate_layout.get("elements", [])) != 77
        or candidate_header.get("source", {}).get(
            "profile_state_identity_sha256"
        )
        != PROFILE_IDENTITY
    ):
        raise AuditError("Dark Cloud login-settings title finding changed")

    primary_path = (
        candidate_root
        / "menu-settlement-traces"
        / candidate_header["raw_recording"]["evidence_filename"]
    )
    confirmation_path = (
        candidate_root
        / "menu-animation-confirmations"
        / candidate_header["animation_confirmation"]["evidence_filename"]
    )
    if not receipt_matches(candidate_header["raw_recording"], primary_path):
        raise AuditError("Dark Cloud login-settings primary trace receipt is false")
    if not receipt_matches(
        candidate_header["animation_confirmation"], confirmation_path
    ):
        raise AuditError("Dark Cloud login-settings confirmation trace receipt is false")
    primary_trace = read_object(primary_path)
    confirmation_trace = read_object(confirmation_path)
    primary_samples, primary = trace_summary(primary_trace, "primary title trace")
    confirmation_samples, confirmation = trace_summary(
        confirmation_trace, "confirmation title trace"
    )
    if (primary["instance"], primary["process_id"]) == (
        confirmation["instance"],
        confirmation["process_id"],
    ):
        raise AuditError("Dark Cloud login-settings title lacks two fresh instances")
    pair_core = derive_pair_core_equality(
        primary_samples,
        confirmation_samples,
        candidate_layout,
        label="standalone dark-cloud-login-settings title audit",
        bound_endpoints=[
            "dark_cloud_to_login_settings.after",
            "dark_cloud_login_to_browser.before",
        ],
        bound_endpoint_census_complete=True,
    )
    if pair_core.get("core_equal") is not True or pair_core.get("zero_residual") is not True:
        raise AuditError("Dark Cloud login-settings pair core differs outside generation")

    navigation = read_object(args.navigation.resolve())
    observed_endpoints: list[dict[str, Any]] = []
    for edge in navigation.get("edges", []):
        if not isinstance(edge, dict):
            continue
        for side in ("before", "after"):
            if (edge.get("id"), side) not in ENDPOINTS:
                continue
            endpoint = edge.get(side)
            if (
                not isinstance(endpoint, dict)
                or endpoint.get("layout_id") != "dark-cloud-login-settings"
                or endpoint.get("semantic_surface") != "dark_cloud_login_settings"
                or endpoint.get("tagged_screen") != "dark_cloud_login_settings"
                or endpoint.get("layout") != candidate_layout
                or endpoint.get("element_count") != 77
                or endpoint.get("layout", {}).get("screen_title")
                != "Dark Cloud Browser"
            ):
                raise AuditError(
                    f"Dark Cloud login-settings endpoint {edge.get('id')}.{side} differs"
                )
            observed_endpoints.append(
                {
                    "edge_id": edge["id"],
                    "side": side,
                    "trigger": edge.get("trigger"),
                    "semantic_surface": endpoint["semantic_surface"],
                    "tagged_screen": endpoint["tagged_screen"],
                    "layout_generation": endpoint.get("layout_generation"),
                    "element_count": endpoint["element_count"],
                    "screen_title": endpoint["layout"]["screen_title"],
                    "structural_core_sha256": endpoint["layout"].get(
                        "structural_core_sha256"
                    ),
                    "frame_sha256": endpoint.get("frame_sha256"),
                }
            )
    if {(value["edge_id"], value["side"]) for value in observed_endpoints} != ENDPOINTS:
        raise AuditError("Dark Cloud login-settings endpoint sweep is incomplete")

    promoter_log = args.promoter_log.resolve()
    promoter_result = read_object(promoter_log)
    if promoter_result != {"success": False, "error": PROMOTER_STOP}:
        raise AuditError("Dark Cloud login-settings promoter STOP changed")
    float_path = repo_root / "tests/fixtures/webgame/float-rng-goldens.json"
    if file_sha256(float_path) != FLOAT_SHA256:
        raise AuditError("float-RNG fixture changed during menu promotion")

    audit = {
        "schema": "solomon-dark-native-menu-dark-cloud-login-title-stop-audit-v1",
        "status": "QUESTION",
        "finding": "settled Dark Cloud login-settings screen_title differs from landed",
        "layout_id": "dark-cloud-login-settings",
        "screen_id": "dark_cloud_login_settings",
        "landed_fixture": receipt(landed_path, repo_root),
        "baseline_snapshot": receipt(baseline_path, repo_root),
        "candidate_fixture": receipt(candidate_path, evidence_root),
        "landed_screen_title": "",
        "settled_screen_title": "Dark Cloud Browser",
        "settled_element_count": 77,
        "settled_structural_core_sha256": candidate_layout.get(
            "structural_core_sha256"
        ),
        "paired_settlement": {
            "profile_state_identity_sha256": PROFILE_IDENTITY,
            "primary": {**primary, "recording": receipt(primary_path, evidence_root)},
            "confirmation": {
                **confirmation,
                "recording": receipt(confirmation_path, evidence_root),
            },
            "core_equality": pair_core,
        },
        "navigation_endpoints": sorted(
            observed_endpoints, key=lambda value: (value["edge_id"], value["side"])
        ),
        "promoter_stop": receipt(promoter_log, evidence_root),
        "promoter_stop_message": PROMOTER_STOP,
        "candidate_applied": False,
        "landed_fixture_untouched": True,
        "float_rng_fixture": {
            **receipt(float_path, repo_root),
            "sealed_sha256": FLOAT_SHA256,
            "untouched": True,
        },
    }
    atomic_json(args.output.resolve(), audit)
    print(json.dumps(audit, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
