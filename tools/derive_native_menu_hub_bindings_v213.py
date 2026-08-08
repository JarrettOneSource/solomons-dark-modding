#!/usr/bin/env python3
"""Derive the exact Settlement v2.12/v2.13 Hub binding contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from native_menu_profile_state import (
    BASELINE_REPO_PATH,
    compute_profile_state_identity,
    hub_resolved_semantic_multiset,
    load_profile_state_baseline,
)


SCHEMA = "solomon-dark-native-menu-hub-bindings-v213"
DERIVED_BASELINE_ID = "hub_new_game_two_action_v213"
FRESH_BASELINE_ID = "pristine_fresh_install"
CONTRACT_REPO_PATH = Path(
    "tests/fixtures/webgame/native-menu-hub-bindings-v213.json"
)
CASE_A_AUDIT = Path("raw-v9/hub-restart-v212/hub-v213-case-a-audit.json")
V212_AUDIT = Path("raw-v9/diagnostics/hub-profile-path-v26-question-audit.json")
V26_AUDIT = Path(
    "raw-v9/raw-final/diagnostics/hub-path-dependent-core-stop-audit.json"
)
HISTORICAL_NEW_GAME = Path(
    "raw-v9/candidates/candidate-v29/menu-transition-layouts/hub_new_game.json"
)
HISTORICAL_RESUMED = Path(
    "raw-v9/candidates/candidate-v29/menu-transition-layouts/hub_resumed.json"
)


class HubBindingDerivationError(RuntimeError):
    """Live evidence does not prove the exact authorized Hub boundary."""


def read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise HubBindingDerivationError(f"{label} is not readable JSON: {error}") from error
    if not isinstance(value, dict):
        raise HubBindingDerivationError(f"{label} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evidence_receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = evidence_root.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise HubBindingDerivationError(
            f"Hub binding evidence is absent or escapes the evidence root: {path}"
        )
    return {
        "evidence_path": resolved.relative_to(root).as_posix(),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def receipt_state(receipt: dict[str, Any], label: str) -> dict[str, Any]:
    files = receipt.get("files")
    if not isinstance(files, list) or not files:
        raise HubBindingDerivationError(
            f"{label} is not a non-empty, independently derived profile receipt"
        )
    state = {
        "baseline_mode": receipt.get("baseline_mode"),
        "source_sandbox_excluded": receipt.get("source_sandbox_excluded"),
        "retail_appdata_seeded": receipt.get("retail_appdata_seeded"),
        "files": files,
    }
    identity = receipt.get("profile_state_identity_sha256")
    if (
        receipt.get("schema") != "solomon-dark-native-menu-profile-state-v1"
        or state["baseline_mode"] != "persistent_profile"
        or state["source_sandbox_excluded"] is not False
        or state["retail_appdata_seeded"] is not False
        or not isinstance(identity, str)
        or compute_profile_state_identity(state) != identity
    ):
        raise HubBindingDerivationError(
            f"{label} records a false derived profile-state identity"
        )
    return {"identity": identity, "files": files}


def resolved_multiset(layout: dict[str, Any], label: str) -> dict[str, Any]:
    try:
        receipt = hub_resolved_semantic_multiset(layout)
    except Exception as error:
        raise HubBindingDerivationError(f"{label}: {error}") from error
    return receipt


def fixture_layout(path: Path, label: str) -> dict[str, Any]:
    fixture = read_object(path, label)
    layout = fixture.get("layout")
    if not isinstance(layout, dict) or layout.get("screen_id") != "hub":
        raise HubBindingDerivationError(f"{label} is not a Hub layout fixture")
    return layout


def observation_layout(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    observation = read_object(path, label)
    receipt = observation.get("receipt")
    layout = observation.get("layout")
    samples = observation.get("settlement_trace", {}).get("settled_window_samples")
    if (
        not isinstance(receipt, dict)
        or not isinstance(layout, dict)
        or layout.get("screen_id") != "hub"
        or not isinstance(samples, list)
        or len(samples) < 40
        or receipt.get("settlement", {}).get("stable_span_milliseconds", 0) < 2_000
    ):
        raise HubBindingDerivationError(f"{label} is not a settled Hub observation")
    return layout, receipt


def one_input_receipt(audit: dict[str, Any], path: Path) -> dict[str, Any]:
    def campaign_relative(value: str | Path) -> str:
        normalized = str(value).replace("\\", "/")
        marker = "/raw-v9/"
        index = normalized.casefold().find(marker)
        if index < 0:
            raise HubBindingDerivationError(
                f"v2.13 audit input is outside raw-v9: {value}"
            )
        return normalized[index + 1 :].casefold()

    target = campaign_relative(path)
    matches = [
        row
        for row in audit.get("inputs", [])
        if isinstance(row, dict)
        and isinstance(row.get("path"), str)
        and campaign_relative(row["path"]) == target
    ]
    if len(matches) != 1:
        raise HubBindingDerivationError(
            f"v2.13 Case A audit has no unique receipt for {path}"
        )
    row = matches[0]
    if row.get("sha256") != sha256_file(path) or row.get("bytes") != path.stat().st_size:
        raise HubBindingDerivationError(
            f"v2.13 Case A audit records a false receipt for {path}"
        )
    return row


def derive(repo_root: Path, evidence_root: Path) -> dict[str, Any]:
    evidence_root = evidence_root.resolve()
    baseline = load_profile_state_baseline(repo_root)
    case_a_path = evidence_root / CASE_A_AUDIT
    case_a = read_object(case_a_path, "v2.13 Case A audit")
    if (
        case_a.get("schema") != "solomon-dark-hub-v213-case-a-audit-v2"
        or case_a.get("decision") != "CASE_A"
        or case_a.get("cross_instance_confirmation", {}).get(
            "historical_hub_new_game_equal"
        )
        is not True
        or case_a.get("cross_instance_confirmation", {}).get(
            "isolated_two_field_replay_equal"
        )
        is not True
    ):
        raise HubBindingDerivationError(
            "v2.13 Case A audit does not prove the authorized two-action derivation"
        )

    primary_observation = evidence_root / (
        "raw-v9/menufx-v9p16/annalist-derivation/relaunch-two-action-1/"
        "direct-new-game-route/restart-05-hub.observation.json"
    )
    confirmation_observation = evidence_root / (
        "raw-v9/menufx-v9p17/annalist-derivation/relaunch-two-action-1/"
        "direct-new-game-route/restart-05-hub.observation.json"
    )
    pristine_observations = [
        evidence_root
        / f"raw-v9/hub-restart-v212/{instance}/restart/restart-05-hub.observation.json"
        for instance in ("menufx-v9p16", "menufx-v9p17")
    ]
    derived_observations = [primary_observation, confirmation_observation]

    pristine_values = [
        resolved_multiset(observation_layout(path, str(path))[0], str(path))
        for path in pristine_observations
    ]
    derived_values = [
        resolved_multiset(observation_layout(path, str(path))[0], str(path))
        for path in derived_observations
    ]
    if any(value != pristine_values[0] for value in pristine_values[1:]) or any(
        value != derived_values[0] for value in derived_values[1:]
    ):
        raise HubBindingDerivationError(
            "Hub v2.12/v2.13 independent instances do not agree canonically"
        )
    v212_exact = pristine_values[0]
    v213_exact = derived_values[0]
    v212_count = v212_exact["element_count"]
    v212_hash = v212_exact["resolved_semantic_multiset_sha256"]
    v213_count = v213_exact["element_count"]
    v213_hash = v213_exact["resolved_semantic_multiset_sha256"]
    boundary = case_a.get("v212_boundary", {})
    confirmation = case_a.get("cross_instance_confirmation", {})
    if (
        boundary.get("pristine_second_new_game_element_count") != v212_count
        or boundary.get("resolved_semantic_multiset_sha256") != v212_hash
        or confirmation.get("element_count") != v213_count
        or confirmation.get("resolved_semantic_multiset_sha256") != v213_hash
    ):
        raise HubBindingDerivationError(
            "Hub v2.12/v2.13 audit does not match the re-derived settled multisets"
        )

    historical_new_game_path = evidence_root / HISTORICAL_NEW_GAME
    historical_exact = resolved_multiset(
        fixture_layout(historical_new_game_path, "historical hub_new_game"),
        "historical hub_new_game",
    )
    if historical_exact != v213_exact:
        raise HubBindingDerivationError(
            "v2.13 content-vindication consequence: derived Hub no longer equals "
            "the retained historical hub_new_game multiset"
        )

    witness_specs = (
        ("primary", "menufx-v9p16"),
        ("confirmation", "menufx-v9p17"),
    )
    audit_identities = confirmation.get("launch_profile_state_identity_sha256")
    if not isinstance(audit_identities, dict):
        raise HubBindingDerivationError("v2.13 audit lost profile identities")
    witnesses: list[dict[str, Any]] = []
    for role, instance in witness_specs:
        profile_path = evidence_root / (
            f"raw-v9/hub-restart-v212/profile-state-v213/{instance}/"
            f"{instance}.derived-profile-state.json"
        )
        profile = read_object(profile_path, f"{instance} derived profile receipt")
        state = receipt_state(profile, f"{instance} derived profile receipt")
        if audit_identities.get(instance) != state["identity"]:
            raise HubBindingDerivationError(
                f"v2.13 audit and copied {instance} profile receipt disagree"
            )
        action_path = evidence_root / (
            f"raw-v9/{instance}/annalist-derivation/"
            + (
                "potionguy-action-proof/potionguy-action.json"
                if instance == "menufx-v9p16"
                else "potionguy-derived-run1/potionguy-action-proof/"
                "potionguy-action.json"
            )
        )
        completion_path = evidence_root / (
            f"raw-v9/{instance}/annalist-derivation/"
            + (
                "two-action-completion/derived-baseline-completion.json"
                if instance == "menufx-v9p16"
                else "potionguy-derived-run1/two-action-completion/"
                "derived-baseline-completion.json"
            )
        )
        observation_path = (
            primary_observation if role == "primary" else confirmation_observation
        )
        for audited_path in (action_path, completion_path, observation_path):
            one_input_receipt(case_a, audited_path)
        witnesses.append(
            {
                "role": role,
                "instance": instance,
                "profile_state_identity_sha256": state["identity"],
                "profile_state_receipt": evidence_receipt(
                    profile_path, evidence_root
                ),
                "potionguy_action_receipt": evidence_receipt(
                    action_path, evidence_root
                ),
                "clean_completion_receipt": evidence_receipt(
                    completion_path, evidence_root
                ),
                "settled_hub_observation": evidence_receipt(
                    observation_path, evidence_root
                ),
                "durable_file_count": len(state["files"]),
            }
        )
    identities = [row["profile_state_identity_sha256"] for row in witnesses]
    if len(identities) != len(set(identities)):
        raise HubBindingDerivationError(
            "v2.13 baseline witnesses are not independent exact profile identities"
        )

    resumed_path = evidence_root / HISTORICAL_RESUMED
    resumed_fixture = read_object(resumed_path, "historical hub_resumed")
    resumed_header = resumed_fixture.get("header")
    resumed_layout = resumed_fixture.get("layout")
    if not isinstance(resumed_header, dict) or not isinstance(resumed_layout, dict):
        raise HubBindingDerivationError("historical hub_resumed is incomplete")
    resumed_count = resumed_header.get("path_dependent_core", {}).get(
        "measured_settled_element_count"
    )
    if not isinstance(resumed_count, int) or resumed_count <= 0:
        raise HubBindingDerivationError("historical hub_resumed lost its measured census")

    case_a_receipt = evidence_receipt(case_a_path, evidence_root)
    fresh_fixture_path = (repo_root / BASELINE_REPO_PATH).resolve()
    contract = {
        "schema": SCHEMA,
        "settlement_spec": "2.13",
        "governing_rule": (
            "Hub path variants are exact data-bound layouts selected only by "
            "an exact pinned profile baseline and deterministic entry path"
        ),
        "baseline_legitimacy": {
            "copied_profile_state_forbidden": True,
            "allowed_construction": [
                "pristine_fresh_install",
                "documented_deterministic_receipted_in_game_derivation",
            ],
        },
        "baselines": {
            FRESH_BASELINE_ID: {
                "kind": "pristine_fresh_install",
                "profile_state_identity_sha256": baseline["identity"],
                "fixture": {
                    "repo_relative_path": BASELINE_REPO_PATH.as_posix(),
                    "sha256": sha256_file(fresh_fixture_path),
                    "bytes": fresh_fixture_path.stat().st_size,
                },
            },
            DERIVED_BASELINE_ID: {
                "kind": "documented_deterministic_receipted_in_game_derivation",
                "parent_baseline_id": FRESH_BASELINE_ID,
                "case_a_audit": case_a_receipt,
                "procedure": case_a.get("diagnosed_mechanism", {}).get(
                    "documented_in_game_derivation"
                ),
                "required_profile_fields": case_a.get(
                    "diagnosed_mechanism", {}
                ).get("minimum_durable_variables"),
                "witnesses": witnesses,
            },
        },
        "layouts": {
            "hub_resumed": {
                "parent_screen_id": "hub",
                "path_qualifier": "resumed",
                "selector": "session_state:resumed_run",
                "required_baseline_id": FRESH_BASELINE_ID,
                "measured_settled_element_count": resumed_count,
                "resolved_layout_sha256": canonical_sha256(resumed_layout),
                "fork_decision": evidence_receipt(
                    evidence_root / V26_AUDIT, evidence_root
                ),
            },
            "hub_pristine_second_new_game": {
                "parent_screen_id": "hub",
                "path_qualifier": "pristine_second_new_game",
                "selector": (
                    "profile_baseline:pristine_fresh_install;entry_path:"
                    "first_run_hub_to_main_then_new_game_create_to_hub;same_process"
                ),
                "required_baseline_id": FRESH_BASELINE_ID,
                "measured_settled_element_count": v212_count,
                "resolved_semantic_multiset_sha256": v212_hash,
                "resolved_semantic_multiset": v212_exact[
                    "resolved_semantic_multiset"
                ],
                "fork_decision": evidence_receipt(
                    evidence_root / V212_AUDIT, evidence_root
                ),
                "case_a_confirmation": case_a_receipt,
            },
            "hub_new_game": {
                "parent_screen_id": "hub",
                "path_qualifier": "new_game_derived_two_action",
                "selector": (
                    "profile_baseline:hub_new_game_two_action_v213;entry_path:"
                    "direct_new_game_create_to_hub"
                ),
                "required_baseline_id": DERIVED_BASELINE_ID,
                "measured_settled_element_count": v213_count,
                "resolved_semantic_multiset_sha256": v213_hash,
                "resolved_semantic_multiset": v213_exact[
                    "resolved_semantic_multiset"
                ],
                "fork_decision": case_a_receipt,
                "content_vindication": evidence_receipt(
                    historical_new_game_path, evidence_root
                ),
            },
        },
        "bindings": [
            {
                "edge_id": "create_discipline_to_hub",
                "endpoint": "after",
                "required_baseline_id": FRESH_BASELINE_ID,
                "layout_id": "hub_pristine_second_new_game",
            },
            {
                "edge_id": "create_discipline_to_hub",
                "endpoint": "after",
                "required_baseline_id": DERIVED_BASELINE_ID,
                "layout_id": "hub_new_game",
            },
            *[
                {
                    "edge_id": edge_id,
                    "endpoint": endpoint,
                    "required_baseline_id": FRESH_BASELINE_ID,
                    "layout_id": "hub_resumed",
                }
                for edge_id, endpoint in (
                    ("hub_to_pause", "before"),
                    ("pause_to_hub_resume", "after"),
                    ("profile_select_resume_to_hub", "after"),
                    ("settings_to_hub", "after"),
                )
            ],
        ],
        "explicitly_forbidden": [
            "count_or_class_based_acceptance",
            "copied_install_profile_baseline",
            "hub_layout_without_exact_path_and_baseline_binding",
            "v212_multiset_on_hub_new_game_or_hub_resumed",
            "v213_supersession_outside_hub_new_game",
        ],
    }
    if not isinstance(
        contract["baselines"][DERIVED_BASELINE_ID]["procedure"], list
    ) or not isinstance(
        contract["baselines"][DERIVED_BASELINE_ID]["required_profile_fields"],
        list,
    ):
        raise HubBindingDerivationError(
            "v2.13 audit does not enumerate its procedure and durable fields"
        )
    return contract


def write_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".menufix.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output = (
        args.output.resolve()
        if args.output is not None
        else (repo_root / CONTRACT_REPO_PATH).resolve()
    )
    try:
        expected = derive(repo_root, args.evidence_root.resolve())
        if args.verify:
            actual = read_object(output, "committed v2.13 Hub binding contract")
            if actual != expected:
                raise HubBindingDerivationError(
                    "committed v2.13 Hub binding contract is not evidence-derived"
                )
        else:
            write_atomically(output, expected)
    except (HubBindingDerivationError, OSError, TypeError, ValueError) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(
        json.dumps(
            {
                "success": True,
                "output": str(output),
                "sha256": sha256_file(output),
                "bytes": output.stat().st_size,
                "layout_count": len(expected["layouts"]),
                "binding_count": len(expected["bindings"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
