#!/usr/bin/env python3
"""Run the data-bound Settlement v2.18 mutation table with transcripts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.native_menu_generation_v218 import (  # noqa: E402
    ADDITIONAL_FIELD_STOP,
    CORE_GENERATION_STOP,
    DISABLED_GENERATION_STOP,
    PAIRED_GENERATION_STOP,
    WINDOW_GENERATION_STOP,
    NativeMenuGenerationV218Error,
    authorize_cross_path_generation,
    compare_semantic_cores,
    measure_generation_window,
    require_semantic_core_identity,
    validate_paired_route_generation,
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"v2.18 mutation input {path} is not a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _clear_contract_bytecode(repo: Path) -> list[str]:
    cleared: list[str] = []
    for relative in (
        "tests/__pycache__",
        "tests/re/__pycache__",
        "tools/__pycache__",
    ):
        directory = repo / relative
        if directory.is_dir():
            shutil.rmtree(directory)
        cleared.append(relative)
    return cleared


def _error(call: Callable[[], Any]) -> str:
    try:
        call()
    except NativeMenuGenerationV218Error as error:
        return str(error)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--resolved-navigation", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    candidate = args.candidate_root.resolve()
    output = args.output_directory.resolve()
    landed_path = (
        repo / "tests/fixtures/webgame/menu-layouts/control-scheme-picker.json"
    )
    candidate_path = candidate / "menu-layouts/control-scheme-picker.json"
    named_paths = (
        landed_path,
        candidate_path,
        candidate / "menu-settlement-traces/control-scheme-picker.settlement.json",
        candidate
        / "menu-animation-confirmations/control-scheme-picker.confirmation.json",
        args.resolved_navigation.resolve(),
    )
    if any(not path.is_file() for path in named_paths):
        raise RuntimeError("v2.18 mutation sweep missed a named picker witness")

    landed = _read(landed_path)["layout"]
    settled = _read(candidate_path)["layout"]
    primary_samples = _read(named_paths[2])["settled_window_samples"]
    confirmation_samples = _read(named_paths[3])["settled_window_samples"]
    navigation = _read(named_paths[4])
    edges = navigation.get("edges")
    if not isinstance(edges, list) or len(edges) != 39:
        raise RuntimeError("v2.18 mutation sweep missed the exact edge census")
    picker_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("id") == "control_scheme_picker_to_create"
    ]
    if len(picker_edges) != 1:
        raise RuntimeError("v2.18 mutation sweep found an ambiguous picker edge")
    endpoint = picker_edges[0].get("before")
    if not isinstance(endpoint, dict):
        raise RuntimeError("v2.18 mutation sweep missed the picker source endpoint")

    def paired() -> dict[str, Any]:
        return validate_paired_route_generation(
            copy.deepcopy(primary_samples),
            copy.deepcopy(confirmation_samples),
            settled["generation"],
            label="control-scheme-picker",
        )

    def bound_endpoint() -> dict[str, Any]:
        comparison = compare_semantic_cores(
            settled,
            endpoint["layout"],
            label="control_scheme_picker_to_create.before",
        )
        generation_equal = (
            endpoint.get("layout_generation") == settled.get("generation")
        )
        comparison.update(
            {
                "edge_id": "control_scheme_picker_to_create",
                "side": "before",
                "generation_equal": generation_equal,
                "exact": comparison["exact"] and generation_equal,
            }
        )
        return comparison

    def baseline() -> dict[str, Any]:
        result = authorize_cross_path_generation(
            copy.deepcopy(landed),
            copy.deepcopy(settled),
            paired(),
            [bound_endpoint()],
        )
        return {
            "schema": result["schema"],
            "landed_generation": result["landed_generation"],
            "settled_generation": result["settled_generation"],
            "member_count": result["semantic_core"]["member_count"],
            "bound_endpoint_count": result["bound_endpoint_count"],
            "landed_fixture_sha256": _sha256(landed_path),
            "candidate_fixture_sha256": _sha256(candidate_path),
            "primary_trace_sha256": _sha256(named_paths[2]),
            "confirmation_trace_sha256": _sha256(named_paths[3]),
        }

    expected_baseline = baseline()

    def disabled() -> str:
        return _error(
            lambda: authorize_cross_path_generation(
                landed,
                settled,
                paired(),
                [bound_endpoint()],
                enabled=False,
            )
        )

    def semantic_core_changed_with_equal_generation() -> str:
        expected = copy.deepcopy(settled)
        observed = copy.deepcopy(settled)
        expected["generation"] = observed["generation"]
        observed["elements"][0]["rect"][0] += 1
        return _error(
            lambda: require_semantic_core_identity(
                expected, observed, label="equal-generation scratch candidate"
            )
        )

    def generation_plus_another_field() -> str:
        mutated = copy.deepcopy(settled)
        mutated["screen_title"] = "V2.18 MUTATED TITLE"
        return _error(
            lambda: authorize_cross_path_generation(
                landed, mutated, paired(), [bound_endpoint()]
            )
        )

    def paired_disagreement() -> str:
        mutated = copy.deepcopy(confirmation_samples)
        for sample in mutated:
            sample["payload"]["generation"] += 1
            sample["semantic_generation"] += 1
        return _error(
            lambda: validate_paired_route_generation(
                primary_samples,
                mutated,
                settled["generation"],
                label="control-scheme-picker",
            )
        )

    def mid_window_change() -> str:
        mutated = copy.deepcopy(primary_samples)
        mutated[-1]["payload"]["generation"] += 1
        mutated[-1]["semantic_generation"] += 1
        return _error(
            lambda: measure_generation_window(
                mutated, "control-scheme-picker primary"
            )
        )

    cases: list[tuple[str, str, Callable[[], str]]] = [
        (
            "v218_disabled_reproduces_exact_original_stop",
            DISABLED_GENERATION_STOP,
            disabled,
        ),
        (
            "semantic_core_difference_with_equal_generation",
            CORE_GENERATION_STOP,
            semantic_core_changed_with_equal_generation,
        ),
        (
            "generation_difference_plus_other_field",
            f"{ADDITIONAL_FIELD_STOP}: ['screen_title']",
            generation_plus_another_field,
        ),
        (
            "paired_instances_disagree_on_generation",
            (
                f"{PAIRED_GENERATION_STOP}: control-scheme-picker "
                "records 1 != 2"
            ),
            paired_disagreement,
        ),
        (
            "mid_window_generation_change",
            (
                f"{WINDOW_GENERATION_STOP}: control-scheme-picker primary "
                "records multiple generation values"
            ),
            mid_window_change,
        ),
    ]
    results: list[dict[str, Any]] = []
    for index, (case_id, expected_message, mutation) in enumerate(cases, 1):
        cleared_before_baseline = _clear_contract_bytecode(repo)
        green_before = baseline()
        cleared_before_mutation = _clear_contract_bytecode(repo)
        actual_message = mutation()
        if actual_message != expected_message:
            raise RuntimeError(
                f"v2.18 mutation '{case_id}' did not trip its exact named claim: "
                f"{actual_message!r}"
            )
        cleared_before_restore = _clear_contract_bytecode(repo)
        green_after = baseline()
        if green_before != expected_baseline or green_after != expected_baseline:
            raise RuntimeError(
                f"v2.18 mutation '{case_id}' did not restore its exact green baseline"
            )
        transcript = {
            "schema": "solomon-dark-menufix-v218-mutation-transcript-v1",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "green_baseline_before": green_before,
            "cleared_before_baseline": cleared_before_baseline,
            "mutation_expected_message": expected_message,
            "mutation_actual_message": actual_message,
            "named_claim_tripped": True,
            "cleared_before_mutation": cleared_before_mutation,
            "green_baseline_after_restore": green_after,
            "cleared_before_restore": cleared_before_restore,
        }
        transcript_path = output / f"{index:02d}-{case_id}.json"
        _write(transcript_path, transcript)
        results.append(
            {
                "case_id": case_id,
                "transcript": str(transcript_path),
                "expected_message": expected_message,
                "status": "green-trip-green",
            }
        )

    summary = {
        "schema": "solomon-dark-menufix-v218-mutation-table-v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": len(results),
        "green_baseline": expected_baseline,
        "cases": results,
    }
    _write(output / "mutation-table.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
