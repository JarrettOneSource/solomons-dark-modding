#!/usr/bin/env python3
"""Run the data-bound Settlement v2.19 mutation table with transcripts."""

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
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.native_menu_generation_v218 import (  # noqa: E402
    RECORDED_GENERATION_STOP,
    WINDOW_GENERATION_STOP,
    compare_semantic_cores,
)
from tools.native_menu_generation_v219 import (  # noqa: E402
    PAIR_CORE_STOP,
    V218_DISABLED_CORPUS_STOP,
    NativeMenuGenerationV219Error,
    authorize_cross_path_generation,
    derive_pair_core_equality,
    validate_instance_local_generation_pair,
)
from tools.promote_native_menu_recapture import (  # noqa: E402
    PromotionError,
    _assert_generation_v219_enabled,
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"v2.19 mutation input {path} is not a JSON object")
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
    except (NativeMenuGenerationV219Error, PromotionError) as error:
        return str(error)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--resolved-navigation", type=Path, required=True)
    parser.add_argument("--v218-stop-audit", type=Path, required=True)
    parser.add_argument("--v219-core-audit", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    candidate = args.candidate_root.resolve()
    output = args.output_directory.resolve()
    landed_path = (
        repo / "tests/fixtures/webgame/menu-layouts/control-scheme-picker.json"
    )
    candidate_path = candidate / "menu-layouts/control-scheme-picker.json"
    primary_path = (
        candidate
        / "menu-settlement-traces/control-scheme-picker.settlement.json"
    )
    confirmation_path = (
        candidate
        / "menu-animation-confirmations/control-scheme-picker.confirmation.json"
    )
    named_paths = (
        landed_path,
        candidate_path,
        primary_path,
        confirmation_path,
        args.resolved_navigation.resolve(),
        args.v218_stop_audit.resolve(),
        args.v219_core_audit.resolve(),
    )
    if any(not path.is_file() for path in named_paths):
        raise RuntimeError("v2.19 mutation sweep missed a named witness")

    landed = _read(landed_path)["layout"]
    settled = _read(candidate_path)["layout"]
    primary_samples = _read(primary_path)["settled_window_samples"]
    confirmation_samples = _read(confirmation_path)["settled_window_samples"]
    navigation = _read(args.resolved_navigation.resolve())
    stop = _read(args.v218_stop_audit.resolve())
    core_audit = _read(args.v219_core_audit.resolve())
    picker_edges = [
        edge
        for edge in navigation.get("edges", [])
        if isinstance(edge, dict)
        and edge.get("id") == "control_scheme_picker_to_create"
    ]
    if len(picker_edges) != 1 or not isinstance(
        picker_edges[0].get("before"), dict
    ):
        raise RuntimeError("v2.19 mutation sweep found an ambiguous picker edge")
    endpoint = picker_edges[0]["before"]

    mismatch_by_layout = {
        value["layout_id"]: value
        for value in stop["standalone_census"]["mismatches"]
    }
    matching_layouts = stop["standalone_census"]["matching_layout_ids"]
    if len(mismatch_by_layout) != 10 or len(matching_layouts) != 20:
        raise RuntimeError("v2.19 mutation sweep lost the exact standalone census")
    census_records: dict[str, dict[str, Any]] = {
        layout_id: {
            "path_local_generation": {
                "primary": {"generation": 0},
                "confirmation": {"generation": 0},
            }
        }
        for layout_id in matching_layouts
    }
    for layout_id, mismatch in mismatch_by_layout.items():
        census_records[layout_id] = {
            "path_local_generation": {
                "primary": {"generation": mismatch["primary"]["generation"]},
                "confirmation": {
                    "generation": mismatch["confirmation"]["generation"]
                },
            }
        }
    endpoint_mismatches = [
        f"{value['edge_id']}.{value['side']}"
        for value in stop["navigation_census"]["mismatches"]
    ]
    navigation_summary = {
        "layout_endpoint_count": stop["navigation_census"][
            "layout_endpoint_count"
        ],
        "typed_nonlayout_endpoints": stop["navigation_census"][
            "typed_nonlayout_endpoints"
        ],
        "generation_mismatch_count": len(endpoint_mismatches),
        "generation_mismatch_endpoints": endpoint_mismatches,
        "all_layout_endpoint_cores_equal": True,
    }

    def picker_core(
        primary: list[dict[str, Any]] | None = None,
        confirmation: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return derive_pair_core_equality(
            copy.deepcopy(primary if primary is not None else primary_samples),
            copy.deepcopy(
                confirmation
                if confirmation is not None
                else confirmation_samples
            ),
            copy.deepcopy(settled),
            label="control-scheme-picker",
            bound_endpoints=["control_scheme_picker_to_create.before"],
            bound_endpoint_census_complete=True,
        )

    def pair() -> dict[str, Any]:
        return validate_instance_local_generation_pair(
            copy.deepcopy(primary_samples),
            copy.deepcopy(confirmation_samples),
            settled["generation"],
            picker_core(),
            label="control-scheme-picker",
        )

    def bound_endpoint() -> dict[str, Any]:
        comparison = compare_semantic_cores(
            settled,
            endpoint["layout"],
            label="control_scheme_picker_to_create.before",
        )
        comparison.update(
            {
                "edge_id": "control_scheme_picker_to_create",
                "side": "before",
                "exact": comparison["exact"],
            }
        )
        return comparison

    def baseline() -> dict[str, Any]:
        if (
            core_audit.get("pair_count") != 34
            or core_audit.get("pass_count") != 34
            or core_audit.get("fail_count") != 0
            or core_audit.get("all_pairs_core_equal") is not True
            or core_audit.get("all_pairs_zero_residual") is not True
        ):
            raise RuntimeError("v2.19 baseline core audit is not 34/34 exact")
        correction = authorize_cross_path_generation(
            copy.deepcopy(landed),
            copy.deepcopy(settled),
            pair(),
            [bound_endpoint()],
        )
        census = _assert_generation_v219_enabled(
            census_records, navigation_summary, enabled=True
        )
        return {
            "correction_schema": correction["schema"],
            "picker_primary_generation": pair()["primary"]["generation"],
            "picker_confirmation_generation": pair()["confirmation"][
                "generation"
            ],
            "core_audit_pair_count": core_audit["pair_count"],
            "core_audit_sha256": _sha256(args.v219_core_audit.resolve()),
            "standalone_generation_mismatch_count": census[
                "standalone_generation_mismatch_count"
            ],
            "navigation_generation_mismatch_count": census[
                "generation_mismatch_count"
            ],
            "landed_fixture_sha256": _sha256(landed_path),
            "candidate_fixture_sha256": _sha256(candidate_path),
        }

    expected_baseline = baseline()

    def disabled_v219() -> str:
        return _error(
            lambda: _assert_generation_v219_enabled(
                census_records, navigation_summary, enabled=False
            )
        )

    def changed_core(*, differing_generation: bool) -> str:
        mutated = copy.deepcopy(confirmation_samples)
        for sample in mutated:
            if differing_generation:
                sample["payload"]["generation"] += 1
                sample["semantic_generation"] += 1
            sample["payload"]["elements"][0]["rect"][0] += 1
        return _error(lambda: picker_core(confirmation=mutated))

    def mid_window_generation() -> str:
        mutated = copy.deepcopy(confirmation_samples)
        mutated[-1]["payload"]["generation"] += 1
        mutated[-1]["semantic_generation"] += 1
        return _error(lambda: picker_core(confirmation=mutated))

    def hand_edited_recorded_generation() -> str:
        return _error(
            lambda: validate_instance_local_generation_pair(
                primary_samples,
                confirmation_samples,
                settled["generation"] + 1,
                picker_core(),
                label="control-scheme-picker",
            )
        )

    cases: list[tuple[str, str, Callable[[], str]]] = [
        (
            "v219_disabled_reproduces_full_v218_corpus_stop",
            V218_DISABLED_CORPUS_STOP,
            disabled_v219,
        ),
        (
            "equal_generation_pair_with_core_difference",
            PAIR_CORE_STOP,
            lambda: changed_core(differing_generation=False),
        ),
        (
            "generation_difference_with_core_difference",
            PAIR_CORE_STOP,
            lambda: changed_core(differing_generation=True),
        ),
        (
            "mid_window_generation_change",
            (
                f"{WINDOW_GENERATION_STOP}: control-scheme-picker confirmation "
                "records multiple generation values"
            ),
            mid_window_generation,
        ),
        (
            "hand_edited_fixture_generation",
            (
                f"{RECORDED_GENERATION_STOP}: control-scheme-picker fixture "
                "records 2, measured 1"
            ),
            hand_edited_recorded_generation,
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
                f"v2.19 mutation '{case_id}' did not trip its exact named claim: "
                f"{actual_message!r}"
            )
        cleared_before_restore = _clear_contract_bytecode(repo)
        green_after = baseline()
        if green_before != expected_baseline or green_after != expected_baseline:
            raise RuntimeError(
                f"v2.19 mutation '{case_id}' did not restore its exact green baseline"
            )
        transcript = {
            "schema": "solomon-dark-menufix-v219-mutation-transcript-v1",
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
        "schema": "solomon-dark-menufix-v219-mutation-table-v1",
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
