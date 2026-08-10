#!/usr/bin/env python3
"""Run the seven green-trip-green Settlement v2.22 mutations."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from derive_native_menu_final_disposition_v222 import (
    DerivationError,
    _class_b_semantics,
    _project_landed,
    _without_class_b,
    build,
)
from native_menu_final_disposition_v222 import (
    BASE_SEQUENCE_STOP,
    SEQUENCE_COMPARISON_STOP,
    SEQUENCE_MEMBERSHIP_STOP,
    SEQUENCE_REPRODUCTION_STOP,
    SEQUENCE_SCOPE_STOP,
    VACUITY_EDGE_STOP,
    VACUITY_SCOPE_STOP,
    FinalDispositionV222Error,
    authorize_named_endpoint_vacuity,
    authorize_relative_sequence,
    require_contract,
)
from native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    diagnose_landed_layout,
)


ORIGINAL_FIRST_STOP = (
    "STOP: standalone dark-cloud-login-settings: " + BASE_SEQUENCE_STOP
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"v2.22 mutation input is not an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_receipt(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def clear_bytecode(repo: Path) -> list[str]:
    cleared: list[str] = []
    for relative in ("tests/__pycache__", "tests/re/__pycache__", "tools/__pycache__"):
        path = repo / relative
        if path.is_dir():
            shutil.rmtree(path)
        cleared.append(relative)
    return cleared


def sequence_inputs(
    repo: Path,
    evidence: Path,
    contract_v221: dict[str, Any],
    layout_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Path, Path]:
    landed_path = repo / f"tests/fixtures/webgame/menu-layouts/{layout_id}.json"
    candidate_path = (
        evidence
        / f"raw-v9/candidates/candidate-v214-profile-final/menu-layouts/{layout_id}.json"
    )
    landed = read_object(landed_path)["layout"]["elements"]
    candidate = read_object(candidate_path)["layout"]["elements"]
    class_b = _class_b_semantics(layout_id, contract_v221)
    settled = _without_class_b(candidate, class_b, f"{layout_id} mutation baseline")
    projected = _project_landed(landed, settled, f"{layout_id} mutation landed")
    return projected, settled, landed_path, candidate_path


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    evidence = args.evidence_root.resolve()
    output = args.output_directory.resolve()
    contract_path = (
        repo / "tests/fixtures/webgame/native-menu-final-disposition-v222.json"
    )
    contract = read_object(contract_path)
    contract_v221_path = (
        repo / "tests/fixtures/webgame/native-menu-census-era-disposition-v221.json"
    )
    contract_v221 = read_object(contract_v221_path)
    census_path = (
        evidence
        / "raw-v9/profile-select-new-game-edge/landed-difference-census-final-v221.json"
    )
    candidate_root = (
        evidence / "raw-v9/candidates/candidate-v214-profile-final"
    )
    navigation_path = (
        evidence
        / "raw-v9/profile-select-new-game-edge/merged-v219/navigation-resolved-v219-40-edges.json"
    )
    navigation = read_object(navigation_path)
    overlay_reference = read_object(candidate_root / "menu-overlay-reference.json")

    sequence_cache = {
        layout_id: sequence_inputs(repo, evidence, contract_v221, layout_id)
        for layout_id in (
            "dark-cloud-login-settings",
            "game-settings-dark-cloud",
        )
    }

    def green_baseline() -> str:
        view = require_contract(copy.deepcopy(contract))
        for layout_id, (landed, settled, landed_path, candidate_path) in sequence_cache.items():
            result = authorize_relative_sequence(
                layout_id,
                copy.deepcopy(landed),
                copy.deepcopy(settled),
                copy.deepcopy(contract),
                file_receipt(landed_path),
                file_receipt(candidate_path),
            )
            if result is None or result.get("layout_id") != layout_id:
                raise RuntimeError(f"v2.22 green sequence baseline missed {layout_id}")
        for layout_id in view["endpoint_vacuity"]:
            core_sha256 = view["endpoint_vacuity"][layout_id][
                "structural_core_sha256"
            ]
            result = authorize_named_endpoint_vacuity(
                layout_id,
                navigation,
                copy.deepcopy(contract),
                core_sha256,
            )
            if result.get("native_inbound_edge_count") != 0:
                raise RuntimeError(f"v2.22 green vacuity baseline missed {layout_id}")
        return "GREEN: exact two sequence records and closed three-layout vacuity set\n"

    cases: list[tuple[str, str, str, Callable[[], None]]] = []

    def permuted_settled_sequence() -> None:
        landed, settled, landed_path, candidate_path = sequence_cache[
            "dark-cloud-login-settings"
        ]
        mutated = copy.deepcopy(settled)
        mutated[0], mutated[1] = mutated[1], mutated[0]
        authorize_relative_sequence(
            "dark-cloud-login-settings",
            copy.deepcopy(landed),
            mutated,
            copy.deepcopy(contract),
            file_receipt(landed_path),
            file_receipt(candidate_path),
        )

    cases.append(
        (
            "sequence_settled_identity_permutation_trips",
            "permute the qualified settled sequence while preserving membership",
            SEQUENCE_COMPARISON_STOP,
            permuted_settled_sequence,
        )
    )

    def injected_membership_delta() -> None:
        census = read_object(census_path)
        rows = census["unclassified_differences"]
        rows[-2] = {
            "layout_id": "dark-cloud-login-settings",
            "difference": {
                "difference_type": "landed_only_member",
                "element_id": "scratch.membership.delta",
            },
        }
        build(
            repo,
            evidence,
            census_path,
            candidate_root,
            navigation_path,
            contract_v221_path,
            census_override=census,
        )

    cases.append(
        (
            "sequence_generator_refuses_membership_delta",
            "replace one generation row with a landed-only member on a sequence layout",
            SEQUENCE_MEMBERSHIP_STOP,
            injected_membership_delta,
        )
    )

    def wrong_sequence_layout_scope() -> None:
        landed, settled, landed_path, candidate_path = sequence_cache[
            "dark-cloud-login-settings"
        ]
        authorize_relative_sequence(
            "dark-cloud-options",
            copy.deepcopy(landed),
            copy.deepcopy(settled),
            copy.deepcopy(contract),
            file_receipt(landed_path),
            file_receipt(candidate_path),
        )

    cases.append(
        (
            "sequence_supersession_rejects_other_layout",
            "claim the exact order difference for an unlisted layout",
            SEQUENCE_SCOPE_STOP,
            wrong_sequence_layout_scope,
        )
    )

    def reproduction_disagreement() -> None:
        expected = require_contract(contract)["sequences"][
            "dark-cloud-login-settings"
        ]["settled_sequence_sha256"]
        build(
            repo,
            evidence,
            census_path,
            candidate_root,
            navigation_path,
            contract_v221_path,
            occurrence_sequence_overrides={
                "dark-cloud-login-settings": {
                    ("standalone", "", ""): expected,
                    (
                        "transition_source",
                        "dark_cloud_login_to_browser",
                        "before",
                    ): "f" * 64,
                }
            },
        )

    cases.append(
        (
            "sequence_generator_refuses_occurrence_disagreement",
            "make the transition-source occurrence disagree with the pinned settled sequence",
            SEQUENCE_REPRODUCTION_STOP,
            reproduction_disagreement,
        )
    )

    def vacuity_with_inbound_edge() -> None:
        mutated = copy.deepcopy(navigation)
        mutated["edges"].append(
            {
                "id": "scratch_inbound_map_picker",
                "after": {"layout_id": "map-picker"},
            }
        )
        authorize_named_endpoint_vacuity(
            "map-picker",
            mutated,
            copy.deepcopy(contract),
            require_contract(contract)["endpoint_vacuity"]["map-picker"][
                "structural_core_sha256"
            ],
        )

    cases.append(
        (
            "endpoint_vacuity_rejects_existing_inbound_edge",
            "add a native inbound edge to map-picker",
            VACUITY_EDGE_STOP,
            vacuity_with_inbound_edge,
        )
    )

    def vacuity_outside_closed_set() -> None:
        authorize_named_endpoint_vacuity(
            "loading-screen",
            navigation,
            copy.deepcopy(contract),
            "0" * 64,
        )

    cases.append(
        (
            "endpoint_vacuity_rejects_layout_outside_named_three",
            "claim vacuity for an edge-free layout outside the closed set",
            VACUITY_SCOPE_STOP,
            vacuity_outside_closed_set,
        )
    )

    def sequence_authorization_disabled() -> None:
        layout_id = "dark-cloud-login-settings"
        landed_path = repo / f"tests/fixtures/webgame/menu-layouts/{layout_id}.json"
        candidate_path = candidate_root / f"menu-layouts/{layout_id}.json"
        try:
            diagnose_landed_layout(
                layout_id,
                read_object(landed_path)["layout"],
                read_object(candidate_path)["layout"],
                read_object(
                    candidate_root
                    / f"menu-settlement-traces/{layout_id}.settlement.json"
                ),
                read_object(
                    candidate_root
                    / f"menu-animation-confirmations/{layout_id}.confirmation.json"
                ),
                copy.deepcopy(overlay_reference),
                dark_cloud_login_title_contract=read_object(
                    repo
                    / "tests/fixtures/webgame/native-menu-dark-cloud-login-title-v220.json"
                ),
                landed_fixture_receipt=file_receipt(landed_path),
                candidate_fixture_receipt=file_receipt(candidate_path),
                census_era_contract=copy.deepcopy(contract_v221),
                final_disposition_contract=copy.deepcopy(contract),
                sequence_supersession_enabled=False,
            )
        except LandedDiagnosisError as error:
            raise LandedDiagnosisError(f"STOP: standalone {layout_id}: {error}") from error

    cases.append(
        (
            "sequence_supersessions_disabled_reproduce_first_stop",
            "disable only the two exact sequence supersessions on the first production layout",
            ORIGINAL_FIRST_STOP,
            sequence_authorization_disabled,
        )
    )

    rows: list[dict[str, Any]] = []
    for name, edit, expected, mutation in cases:
        case_directory = output / name
        before_cleared = clear_bytecode(repo)
        before = green_baseline()
        atomic_text(case_directory / "green-before.log", before)
        mutation_cleared = clear_bytecode(repo)
        try:
            mutation()
        except (FinalDispositionV222Error, DerivationError, LandedDiagnosisError) as error:
            message = str(error)
        else:
            raise RuntimeError(f"v2.22 mutation failed to trip: {name}")
        if expected not in message:
            raise RuntimeError(
                f"v2.22 mutation {name} tripped a neighboring claim: {message!r}"
            )
        atomic_text(case_directory / "trip.log", f"TRIP: {message}\n")
        restore_cleared = clear_bytecode(repo)
        restored = green_baseline()
        atomic_text(case_directory / "restored-green.log", restored)
        rows.append(
            {
                "case": name,
                "edit": edit,
                "expected_named_reason": expected,
                "actual_trip_message": message,
                "green_before": True,
                "tripped": True,
                "restored_green": True,
                "bytecode_cleared": {
                    "green_before": before_cleared,
                    "mutation": mutation_cleared,
                    "restored_green": restore_cleared,
                },
                "transcripts": {
                    "green_before": f"{name}/green-before.log",
                    "trip": f"{name}/trip.log",
                    "restored_green": f"{name}/restored-green.log",
                },
            }
        )

    table = {
        "schema": "solomon-dark-native-menu-v222-mutation-table-v1",
        "settlement_spec": "2.22",
        "contract": {
            "repo_relative_path": contract_path.relative_to(repo).as_posix(),
            **file_receipt(contract_path),
        },
        "case_count": len(rows),
        "passed_count": sum(
            row["green_before"] and row["tripped"] and row["restored_green"]
            for row in rows
        ),
        "all_passed": all(
            row["green_before"] and row["tripped"] and row["restored_green"]
            for row in rows
        ),
        "rows": rows,
    }
    atomic_json(output / "v222-mutation-table.json", table)
    print(json.dumps({key: table[key] for key in ("case_count", "passed_count", "all_passed")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
