#!/usr/bin/env python3
"""Run the data-bound Settlement v2.16 mutation table with transcripts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.native_menu_multi_state_path_core import (  # noqa: E402
    DISABLED_RESOLVER_STOP,
    SETTINGS_LAYOUT_ID,
    resolve_settings_path_dependent_cores,
)
from tools.resolve_native_menu_ambient_campaign import (  # noqa: E402
    collect_extended,
    collect_navigation,
    collect_nonsemantic_overlays,
    collect_standalones,
    read_object,
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _baseline(
    observations: list[dict[str, Any]],
    evidence_root: Path,
    asset_manifest: dict[str, Any],
) -> dict[str, Any]:
    result = resolve_settings_path_dependent_cores(
        copy.deepcopy(observations),
        evidence_root=evidence_root,
        asset_manifest=asset_manifest,
    )
    summary = {
        "settlement_spec": result["settlement_spec"],
        "state_order": result["state_order"],
        "bindings": result["bindings"],
        "states": [
            {
                "state_id": state_id,
                "measured_element_count": state["measured_element_count"],
                "structural_core_element_count": state[
                    "structural_core_element_count"
                ],
                "structural_core_sha256": state["structural_core_sha256"],
            }
            for state_id, state in result["states"].items()
        ],
    }
    summary["contract_sha256"] = hashlib.sha256(_canonical(summary)).hexdigest()
    return summary


def _replace_bound_endpoint_with_base(
    observations: list[dict[str, Any]],
) -> None:
    base = next(
        observation
        for observation in observations
        if observation["label"]
        == "standalone:game-settings-gameplay:primary"
    )
    target = next(
        observation
        for observation in observations
        if observation["label"]
        == "edge:performance_to_settings:destination:primary"
    )
    target["samples"] = copy.deepcopy(base["samples"])


def _append_synthetic_fourth_state(
    observations: list[dict[str, Any]],
) -> None:
    synthetic = copy.deepcopy(
        next(
            observation
            for observation in observations
            if observation["label"]
            == "standalone:game-settings-gameplay:primary"
        )
    )
    synthetic["label"] = "edge:synthetic_fourth:destination:primary"
    synthetic["instance"] = "menufx-v216-synthetic"
    synthetic["process_id"] = 216
    observations.append(synthetic)


def _disabled(
    observations: list[dict[str, Any]],
    evidence_root: Path,
    asset_manifest: dict[str, Any],
) -> None:
    resolve_settings_path_dependent_cores(
        observations,
        evidence_root=evidence_root,
        asset_manifest=asset_manifest,
        enabled=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--primary-navigation", type=Path, required=True)
    parser.add_argument("--confirmation-navigation", type=Path, required=True)
    parser.add_argument("--asset-manifest", type=Path, required=True)
    parser.add_argument(
        "--motion-observation-root", type=Path, action="append", required=True
    )
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    fixtures, observations = collect_standalones(
        args.repo_root,
        args.candidate_root,
        args.evidence_root,
        [args.candidate_root],
    )
    overlays = collect_nonsemantic_overlays(
        args.repo_root, args.candidate_root, args.evidence_root
    )
    collect_navigation(
        args.repo_root,
        args.primary_navigation,
        args.confirmation_navigation,
        args.evidence_root,
        fixtures,
        observations,
        overlays,
    )
    for motion_root in args.motion_observation_root:
        collect_extended(
            args.repo_root,
            motion_root,
            args.evidence_root,
            fixtures,
            observations,
        )
    settings = observations[SETTINGS_LAYOUT_ID]
    asset_manifest = read_object(args.asset_manifest)
    baseline = _baseline(settings, args.evidence_root, asset_manifest)

    cases: list[
        tuple[
            str,
            str,
            Callable[[list[dict[str, Any]]], None] | None,
            bool,
        ]
    ] = [
        (
            "bound_endpoint_wrong_core",
            "state 'performance_retained' changed its measured element census",
            _replace_bound_endpoint_with_base,
            False,
        ),
        (
            "path_binding_disabled_reproduces_original_stop",
            DISABLED_RESOLVER_STOP,
            None,
            True,
        ),
        (
            "synthetic_fourth_state",
            "endpoint binding census changed or a fourth state appeared",
            _append_synthetic_fourth_state,
            False,
        ),
    ]
    results: list[dict[str, Any]] = []
    for index, (case_id, expected, mutation, disabled) in enumerate(cases, 1):
        pre = _baseline(settings, args.evidence_root, asset_manifest)
        mutated = copy.deepcopy(settings)
        if mutation is not None:
            mutation(mutated)
        try:
            if disabled:
                _disabled(mutated, args.evidence_root, asset_manifest)
            else:
                resolve_settings_path_dependent_cores(
                    mutated,
                    evidence_root=args.evidence_root,
                    asset_manifest=asset_manifest,
                )
        except Exception as error:  # The transcript pins the exact named claim.
            actual = str(error)
        else:
            actual = ""
        if expected not in actual:
            raise RuntimeError(
                f"v2.16 mutation '{case_id}' did not trip its named claim: {actual!r}"
            )
        post = _baseline(settings, args.evidence_root, asset_manifest)
        if pre != baseline or post != baseline:
            raise RuntimeError(
                f"v2.16 mutation '{case_id}' did not restore its exact green baseline"
            )
        transcript = {
            "schema": "solomon-dark-menufix-v216-mutation-transcript-v1",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "green_baseline_before": pre,
            "mutation_expected_message": expected,
            "mutation_actual_message": actual,
            "named_claim_tripped": True,
            "green_baseline_after_restore": post,
        }
        transcript_path = args.output_directory / (
            f"{index:02d}-{case_id}.json"
        )
        _write(transcript_path, transcript)
        results.append(
            {
                "case_id": case_id,
                "transcript": str(transcript_path),
                "expected_message": expected,
                "status": "green-trip-green",
            }
        )

    summary = {
        "schema": "solomon-dark-menufix-v216-mutation-table-v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": len(results),
        "green_baseline": baseline,
        "cases": results,
    }
    _write(args.output_directory / "mutation-table.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
