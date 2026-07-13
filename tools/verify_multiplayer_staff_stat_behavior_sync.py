#!/usr/bin/env python3
"""Verify native Enchant Staff and Fortunate Flailing behavior both ways."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import (
    query_progression_snapshot,
    query_ranked_numeric_stat,
)
from multiplayer_staff_behavior_harness import (
    PHYSICAL_WAVE,
    arm_natural_staff_arena,
    run_native_staff_resolver_trial,
    start_natural_staff_waves,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    VerifyFailure,
    stop_games,
)
from verify_multiplayer_all_stat_sync import load_stat_contract_values
from verify_multiplayer_all_upgrade_sync import (
    build_and_verify_catalog,
    enable_quiet_progression_test_mode,
    load_skill_configs,
    new_crash_artifacts,
    wait_for_catalog_views,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_battle_siege_behavior_sync import max_stat_for_target
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    Direction,
    detect_instance_pids,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_staff_stat_behavior_sync.json"
ENCHANT_STAFF_ROW = 65
FORTUNATE_FLAILING_ROW = 71
FORTUNATE_VARIANTS = (1, 2, 3, 4)
CLUSTER_OFFSETS = ((50.0, 0.0),)


def direction_for_owner(owner: str, pids: dict[str, int]) -> Direction:
    if owner == "host":
        return Direction(
            "host_owned",
            HOST_ID,
            "Host Player",
            HOST_PIPE,
            HOST_LOG,
            pids["host"],
            CLIENT_PIPE,
            CLIENT_LOG,
        )
    return Direction(
        "client_owned",
        CLIENT_ID,
        "Client Player",
        CLIENT_PIPE,
        CLIENT_LOG,
        pids["client"],
        HOST_PIPE,
        HOST_LOG,
    )


def max_stats(
    directions: tuple[Direction, ...],
    catalog: list[dict[str, Any]],
    row: int,
    initial_by_target: dict[int, dict[str, Any]],
    contract_values: dict[int, dict[str, float]],
    timeout: float,
) -> dict[str, Any]:
    return {
        direction.name: max_stat_for_target(
            catalog,
            row,
            direction.source_id,
            initial_by_target,
            contract_values,
            timeout,
        )
        for direction in directions
    }


def verify_enchant_contracts(
    baseline: dict[str, dict[str, Any]],
    enchanted: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    contracts: dict[str, Any] = {}
    for direction_name in ("host_owned", "client_owned"):
        baseline_trial = baseline[direction_name]
        enchanted_trial = enchanted[direction_name]
        baseline_damage = float(baseline_trial["primary_damage_per_hit"])
        enchanted_damage = float(enchanted_trial["primary_damage_per_hit"])
        if not math.isfinite(baseline_damage) or baseline_damage <= 0.0:
            raise VerifyFailure(
                f"{direction_name} stock baseline staff damage is invalid: {baseline_damage}"
            )
        if not math.isfinite(enchanted_damage) or enchanted_damage <= baseline_damage * 4.0:
            raise VerifyFailure(
                f"{direction_name} max Enchant Staff did not materially improve the stock resolver: "
                f"baseline={baseline_damage} enchanted={enchanted_damage}"
            )
        contracts[direction_name] = {
            "baseline_damage_per_hit": baseline_damage,
            "enchanted_damage_per_hit": enchanted_damage,
            "ratio": enchanted_damage / baseline_damage,
            "baseline_return_addresses": baseline_trial["damage_trace"]["return_addresses"],
            "enchanted_return_addresses": enchanted_trial["damage_trace"]["return_addresses"],
        }
    return contracts


def verify_fortunate_contracts(
    chance_parity: dict[str, Any],
    variants: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    contracts: dict[str, Any] = {}
    for direction_name in ("host_owned", "client_owned"):
        exercised: set[int] = set()
        variant_damage: dict[str, float] = {}
        for variant in FORTUNATE_VARIANTS:
            trial = variants[direction_name][str(variant)]
            if int(trial["variant"]) != variant or trial["primary_damage"] <= 0.0:
                raise VerifyFailure(
                    f"{direction_name} Fortunate variant {variant} did not resolve damage: {trial}"
                )
            exercised.add(variant)
            variant_damage[str(variant)] = float(trial["primary_damage"])
        if exercised != set(FORTUNATE_VARIANTS):
            raise VerifyFailure(
                f"{direction_name} Fortunate variant matrix is incomplete: {sorted(exercised)}"
            )
        contracts[direction_name] = {
            "chance_property": "mChance",
            "chance_value": 100.0,
            "variants": sorted(exercised),
            "damage": variant_damage,
        }
    return {
        "directions": contracts,
        "chance_parity_mismatches": chance_parity["mismatches"],
    }


def verify_ranked_property_views(
    row: int,
    property_name: str,
    expected_rank: int,
    expected_value: float,
) -> dict[str, Any]:
    locations = {
        "host_owner": (HOST_PIPE, None),
        "client_observes_host": (CLIENT_PIPE, HOST_ID),
        "client_owner": (CLIENT_PIPE, None),
        "host_observes_client": (HOST_PIPE, CLIENT_ID),
    }
    views = {
        label: query_ranked_numeric_stat(
            pipe_name,
            row,
            property_name,
            participant_id=participant_id,
        )
        for label, (pipe_name, participant_id) in locations.items()
    }
    mismatches: list[dict[str, Any]] = []
    for label, view in views.items():
        if not view["available"] or not view["property_found"]:
            mismatches.append({"view": label, "reason": "property_unavailable", "actual": view})
            continue
        if int(view["rank"]) != expected_rank:
            mismatches.append(
                {
                    "view": label,
                    "field": "rank",
                    "actual": view["rank"],
                    "expected": expected_rank,
                }
            )
        if not math.isclose(
            float(view["value"]),
            expected_value,
            rel_tol=0.0,
            abs_tol=0.001,
        ):
            mismatches.append(
                {
                    "view": label,
                    "field": "value",
                    "actual": view["value"],
                    "expected": expected_value,
                }
            )
    if mismatches:
        raise VerifyFailure(
            f"ranked property parity failed row={row} property={property_name}: {mismatches}"
        )
    return {"views": views, "mismatches": mismatches}


def run_fortunate_variant_with_retries(
    direction: Direction,
    actor_addresses: list[int],
    variant: int,
    *,
    attempts: int = 3,
) -> dict[str, Any]:
    """Retry only the stock resolver's transient zero-damage contact miss."""

    prior_errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            result = run_native_staff_resolver_trial(
                direction,
                actor_addresses,
                f"fortunate_variant_{variant}",
                variant=variant,
                target_offsets=CLUSTER_OFFSETS,
            )
            result["attempt"] = attempt
            result["prior_zero_damage_errors"] = prior_errors
            return result
        except VerifyFailure as exc:
            message = str(exc)
            if "stock staff resolver dealt no primary damage" not in message:
                raise
            prior_errors.append(message)
            if attempt < attempts:
                # Let the retail hit gate and contact cache age out before
                # rebuilding the same exact point-blank layout.
                time.sleep(1.25)
    raise VerifyFailure(
        f"{direction.name} Fortunate variant {variant} repeatedly dealt zero damage: "
        f"{prior_errors}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        startup = launch_pair_ready(
            args.timeout,
            god_mode=True,
            manual_combat=False,
            wave_override=PHYSICAL_WAVE,
        )
        output["launch"] = startup["launch"]
        output["startup"] = {"attempt": startup["attempt"]}
        output["quiet_progression_test_mode"] = enable_quiet_progression_test_mode()
        output["post_run_progression_ready"] = wait_for_post_run_progression_ready(
            args.timeout
        )
        catalog_result = build_and_verify_catalog(
            wait_for_catalog_views(args.timeout),
            load_skill_configs(),
        )
        catalog = catalog_result["catalog"]
        contract_values = load_stat_contract_values(catalog)
        initial_by_target = {
            HOST_ID: query_progression_snapshot(HOST_PIPE),
            CLIENT_ID: query_progression_snapshot(CLIENT_PIPE),
        }
        pids = detect_instance_pids()
        directions = tuple(
            direction_for_owner(owner, pids) for owner in ("client", "host")
        )

        output["arena_arm"] = arm_natural_staff_arena()
        output["waves"] = start_natural_staff_waves(minimum_actors=1)
        actor_addresses = [int(value) for value in output["waves"]["actors"]]

        output["baseline_resolver"] = {
            direction.name: run_native_staff_resolver_trial(
                direction,
                actor_addresses,
                "baseline",
                variant=0,
                target_offsets=CLUSTER_OFFSETS,
            )
            for direction in directions
        }
        output["enchant_staff_upgrades"] = max_stats(
            directions,
            catalog,
            ENCHANT_STAFF_ROW,
            initial_by_target,
            contract_values,
            args.timeout,
        )
        output["enchant_damage_property_parity"] = verify_ranked_property_views(
            ENCHANT_STAFF_ROW,
            "mDamage",
            15,
            36.0,
        )
        output["enchanted_resolver"] = {
            direction.name: run_native_staff_resolver_trial(
                direction,
                actor_addresses,
                "enchant_staff_max",
                variant=0,
                target_offsets=CLUSTER_OFFSETS,
            )
            for direction in directions
        }
        output["enchant_contracts"] = verify_enchant_contracts(
            output["baseline_resolver"],
            output["enchanted_resolver"],
        )
        output["fortunate_flailing_upgrades"] = max_stats(
            directions,
            catalog,
            FORTUNATE_FLAILING_ROW,
            initial_by_target,
            contract_values,
            args.timeout,
        )
        output["fortunate_chance_parity"] = verify_ranked_property_views(
            FORTUNATE_FLAILING_ROW,
            "mChance",
            9,
            100.0,
        )
        output["fortunate_variants"] = {
            direction.name: {
                str(variant): run_fortunate_variant_with_retries(
                    direction,
                    actor_addresses,
                    variant,
                )
                for variant in FORTUNATE_VARIANTS
            }
            for direction in directions
        }
        output["fortunate_contracts"] = verify_fortunate_contracts(
            output["fortunate_chance_parity"],
            output["fortunate_variants"],
        )
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                f"new crash artifacts appeared during staff behavior test: "
                f"{output['new_crash_artifacts']}"
            )
        output["ok"] = True
        return_code = 0
    except Exception as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if not args.keep_open:
            stop_games()

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "enchant_contracts": output.get("enchant_contracts"),
                "fortunate_contracts": output.get("fortunate_contracts"),
                "new_crash_artifacts": output.get("new_crash_artifacts", []),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
