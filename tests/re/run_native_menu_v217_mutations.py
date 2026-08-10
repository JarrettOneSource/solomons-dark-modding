#!/usr/bin/env python3
"""Run the data-bound Settlement v2.17 mutation table with transcripts."""

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

from tools.native_menu_semantic_dialog_composite import (  # noqa: E402
    DECOMPOSITION_RESIDUE_REASON,
    DIALOG_REFERENCE_REASON,
    LEGACY_PROVENANCE_REASON,
    OVERLAY_HYGIENE_STOP,
    PAINT_ORDER_REASON,
    SURFACE_AGREEMENT_STOP,
    NativeMenuSemanticDialogCompositeError,
    canonical_bytes,
    classify_semantic_dialog_composite,
    validate_composite_record,
    validate_qualified_beta_paint_order,
    validate_qualified_beta_supersession,
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"v2.17 mutation input {path} is not a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fixture_receipt(path: Path, fixture: str) -> dict[str, Any]:
    return {"fixture": fixture, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
    except NativeMenuSemanticDialogCompositeError as error:
        return str(error)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    candidate = args.candidate_root.resolve()
    output = args.output_directory.resolve()
    composite_path = (
        candidate / "menu-dialog-composites/beta-notice-first-boot.json"
    )
    picker_path = candidate / "menu-layouts/control-scheme-picker.json"
    beta_path = candidate / "menu-layouts/beta-notice.json"
    overlay_path = candidate / "menu-overlay-reference.json"
    landed_beta_path = repo / "tests/fixtures/webgame/menu-layouts/beta-notice.json"
    paint_path = (
        repo
        / "tests/fixtures/webgame/native-menu-beta-notice-paint-order-v217.json"
    )
    supersession_path = (
        repo
        / "tests/fixtures/webgame/native-menu-beta-notice-supersession-v217.json"
    )
    named_paths = (
        composite_path,
        picker_path,
        beta_path,
        overlay_path,
        landed_beta_path,
        paint_path,
        supersession_path,
    )
    if any(not path.is_file() for path in named_paths):
        raise RuntimeError("v2.17 mutation sweep did not reach every named witness")

    composite = _read(composite_path)
    picker = _read(picker_path)["layout"]
    beta_fixture = _read(beta_path)
    beta = beta_fixture["layout"]
    overlay = _read(overlay_path)
    landed_beta = _read(landed_beta_path)
    paint = _read(paint_path)
    supersession = _read(supersession_path)
    landed_receipt = _fixture_receipt(
        landed_beta_path, "menu-layouts/beta-notice.json"
    )
    candidate_receipt = _fixture_receipt(
        beta_path, "menu-layouts/beta-notice.json"
    )

    def baseline() -> dict[str, Any]:
        classification = validate_composite_record(
            copy.deepcopy(composite),
            copy.deepcopy(picker),
            copy.deepcopy(overlay),
            copy.deepcopy(beta),
        )
        validate_qualified_beta_paint_order(
            copy.deepcopy(beta), copy.deepcopy(paint)
        )
        correction = validate_qualified_beta_supersession(
            copy.deepcopy(supersession),
            landed_fixture_receipt=copy.deepcopy(landed_receipt),
            candidate_fixture_receipt=copy.deepcopy(candidate_receipt),
            candidate_fixture=copy.deepcopy(beta_fixture),
        )
        return {
            "composite_classification": classification["classification"],
            "composite_member_count": classification["composite_member_count"],
            "dialog_member_count": classification["dialog_member_count"],
            "qualified_beta_member_count": len(beta["elements"]),
            "beta_supersession_status": correction["status"],
            "composite_sha256": _sha256(composite_path),
            "paint_contract_sha256": _sha256(paint_path),
            "supersession_contract_sha256": _sha256(supersession_path),
        }

    expected_baseline = baseline()

    def dialog_reference_mutation() -> str:
        mutated = copy.deepcopy(composite)
        entries = mutated["composite"]["dialog_semantic_multiset"]["entries"]
        art = next(
            entry for entry in entries if entry.get("payload", {}).get("kind") == "art"
        )
        art["payload"]["art_id"] = "UI.v217_mutated_dialog"
        entries.sort(key=lambda entry: canonical_bytes(entry["payload"]))
        return _error(
            lambda: validate_composite_record(mutated, picker, overlay, beta)
        )

    def disabled_model_mutation() -> str:
        observations = copy.deepcopy(composite["composite"]["observations"])
        surface = _error(
            lambda: classify_semantic_dialog_composite(
                observations,
                picker,
                overlay,
                beta,
                model_enabled=False,
                disabled_guard="surface_agreement",
            )
        )
        hygiene = _error(
            lambda: classify_semantic_dialog_composite(
                observations,
                picker,
                overlay,
                beta,
                model_enabled=False,
                disabled_guard="overlay_hygiene",
            )
        )
        return f"surface={surface}\noverlay={hygiene}"

    def residue_mutation() -> str:
        mutated = copy.deepcopy(composite)
        residue = copy.deepcopy(picker["elements"][0])
        residue["id"] = "control_scheme_picker.text.v217_residue.1"
        residue["text"] = "V217 RESIDUE"
        for observation in mutated["composite"]["observations"]:
            observation["settled_payload"]["elements"].append(
                copy.deepcopy(residue)
            )
        return _error(
            lambda: validate_composite_record(mutated, picker, overlay, beta)
        )

    def legacy_mutation() -> str:
        return _error(
            lambda: validate_qualified_beta_supersession(
                supersession,
                landed_fixture_receipt=landed_receipt,
                candidate_fixture_receipt=candidate_receipt,
                candidate_fixture=landed_beta,
            )
        )

    def paint_mutation() -> str:
        mutated = copy.deepcopy(beta)
        mutated["elements"][0]["rect"][0] += 1
        return _error(
            lambda: validate_qualified_beta_paint_order(mutated, paint)
        )

    cases: list[tuple[str, str, Callable[[], str]]] = [
        (
            "dialog_multiset_differs_from_reference",
            DIALOG_REFERENCE_REASON,
            dialog_reference_mutation,
        ),
        (
            "composite_disabled_reproduces_both_production_stops",
            f"surface={SURFACE_AGREEMENT_STOP}\noverlay={OVERLAY_HYGIENE_STOP}",
            disabled_model_mutation,
        ),
        (
            "decomposition_residue_member",
            DECOMPOSITION_RESIDUE_REASON,
            residue_mutation,
        ),
        (
            "legacy_core_unqualified_under_any_tag",
            LEGACY_PROVENANCE_REASON,
            legacy_mutation,
        ),
        (
            "rederived_paint_order_tampered_core",
            PAINT_ORDER_REASON,
            paint_mutation,
        ),
    ]
    results: list[dict[str, Any]] = []
    for index, (case_id, expected, mutate) in enumerate(cases, 1):
        cleared_before_baseline = _clear_contract_bytecode(repo)
        green_before = baseline()
        cleared_before_mutation = _clear_contract_bytecode(repo)
        actual = mutate()
        if actual != expected:
            raise RuntimeError(
                f"v2.17 mutation '{case_id}' did not trip its exact named claim: {actual!r}"
            )
        cleared_before_restore = _clear_contract_bytecode(repo)
        green_after = baseline()
        if green_before != expected_baseline or green_after != expected_baseline:
            raise RuntimeError(
                f"v2.17 mutation '{case_id}' did not restore its exact green baseline"
            )
        transcript = {
            "schema": "solomon-dark-menufix-v217-mutation-transcript-v1",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "green_baseline_before": green_before,
            "cleared_before_baseline": cleared_before_baseline,
            "mutation_expected_message": expected,
            "mutation_actual_message": actual,
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
                "expected_message": expected,
                "status": "green-trip-green",
            }
        )

    summary = {
        "schema": "solomon-dark-menufix-v217-mutation-table-v1",
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
