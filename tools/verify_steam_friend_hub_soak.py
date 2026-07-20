#!/usr/bin/env python3
"""Soak shared-hub actor lifecycle over a genuine Steam friend pair."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import probe_hub_npc_presentation_sync as presentation
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_hub_soak.json"


def hub_records(
    values: dict[str, str],
    prefix: str,
) -> list[dict[str, str]]:
    return [
        record
        for record in presentation.parse_indexed(values, prefix)
        if presentation.HUB_NPC_TYPE_MIN
        <= presentation.parse_int(record.get("type"))
        <= presentation.HUB_NPC_TYPE_MAX
    ]


def capture(pair: SteamFriendActivePair, timeout: float) -> dict[str, Any]:
    # Capture both processes near the same stock frame. Animation phase aging
    # itself uses only the client's sampled/received clock pair because
    # GetTickCount64 epochs are process-local under Proton.
    with ThreadPoolExecutor(max_workers=2) as executor:
        host_future = executor.submit(
            pair.lua,
            HOST_ENDPOINT,
            presentation.LUA_CAPTURE,
            timeout,
        )
        client_future = executor.submit(
            pair.lua,
            CLIENT_ENDPOINT,
            presentation.LUA_CAPTURE,
            timeout,
        )
        host_values = parse_key_values(host_future.result())
        client_values = parse_key_values(client_future.result())
    comparison = presentation.compare_host_to_client(
        host_values,
        client_values,
    )
    summary = comparison["summary"]

    # Stock Students retire and respawn independently on each machine. Their
    # wire IDs identify host presentation snapshots, while each client binds as
    # many of those snapshots as its own stock Student pool currently exposes.
    # Persistent named NPCs still require exact one-to-one convergence.
    latest_authoritative = hub_records(client_values, "repactor")
    applied_authoritative = hub_records(client_values, "applyactor")
    bindings = [
        binding
        for binding in hub_records(client_values, "binding")
        if binding.get("matched") == "true"
        and binding.get("parked") != "true"
        and binding.get("removed") != "true"
    ]
    local_actors = hub_records(client_values, "actor")

    latest_authoritative_ids = [
        presentation.parse_int(actor.get("network_id"))
        for actor in latest_authoritative
        if presentation.parse_int(actor.get("network_id")) != 0
    ]
    applied_authoritative_ids = [
        presentation.parse_int(actor.get("network_id"))
        for actor in applied_authoritative
        if presentation.parse_int(actor.get("network_id")) != 0
    ]
    binding_ids = [
        presentation.parse_int(binding.get("network_id"))
        for binding in bindings
        if presentation.parse_int(binding.get("network_id")) != 0
    ]
    binding_addresses = [
        presentation.parse_int(binding.get("address"))
        for binding in bindings
        if presentation.parse_int(binding.get("address")) != 0
    ]
    local_addresses = [
        presentation.parse_int(actor.get("address"))
        for actor in local_actors
        if presentation.parse_int(actor.get("address")) != 0
    ]
    latest_authoritative_id_set = set(latest_authoritative_ids)
    applied_authoritative_id_set = set(applied_authoritative_ids)
    binding_id_set = set(binding_ids)
    binding_address_set = set(binding_addresses)
    local_address_set = set(local_addresses)
    applied_authoritative_named_ids = {
        presentation.parse_int(actor.get("network_id"))
        for actor in applied_authoritative
        if presentation.parse_int(actor.get("type"))
        != presentation.STUDENT_TYPE_ID
    }
    applied_authoritative_student_ids = (
        applied_authoritative_id_set - applied_authoritative_named_ids
    )
    binding_named_ids = {
        presentation.parse_int(binding.get("network_id"))
        for binding in bindings
        if presentation.parse_int(binding.get("type"))
        != presentation.STUDENT_TYPE_ID
    }
    binding_student_ids = binding_id_set - binding_named_ids
    local_named_addresses = {
        presentation.parse_int(actor.get("address"))
        for actor in local_actors
        if presentation.parse_int(actor.get("type"))
        != presentation.STUDENT_TYPE_ID
    }
    local_student_addresses = local_address_set - local_named_addresses
    bound_named_addresses = {
        presentation.parse_int(binding.get("address"))
        for binding in bindings
        if presentation.parse_int(binding.get("type"))
        != presentation.STUDENT_TYPE_ID
    }
    bound_student_addresses = binding_address_set - bound_named_addresses

    return {
        "host_scene": host_values.get("scene.name", ""),
        "client_scene": client_values.get("scene.name", ""),
        "snapshot_valid": client_values.get("replicated.valid") == "true",
        "apply_valid": client_values.get("replicated.apply_valid") == "true",
        "apply_actors_available": bool(
            summary["client_apply_actors_available"]
        ),
        "apply_presentation_available": bool(
            summary["client_apply_presentation_available"]
        ),
        "presentation_clock_valid": bool(
            summary["client_presentation_clock_valid"]
        ),
        "presentation_age_ms": int(summary["client_presentation_age_ms"]),
        "snapshot_sequence": presentation.parse_int(
            client_values.get("replicated.sequence")
        ),
        "snapshot_actor_count": presentation.parse_int(
            client_values.get("replicated.actor_count")
        ),
        "snapshot_total_count": presentation.parse_int(
            client_values.get("replicated.total_count")
        ),
        "latest_authoritative_ids": sorted(latest_authoritative_id_set),
        "latest_authoritative_actor_count": len(latest_authoritative_ids),
        "unique_latest_authoritative_actor_count": len(
            latest_authoritative_id_set
        ),
        "applied_authoritative_actor_count": len(applied_authoritative_ids),
        "unique_applied_authoritative_actor_count": len(
            applied_authoritative_id_set
        ),
        "applied_authoritative_named_actor_count": len(
            applied_authoritative_named_ids
        ),
        "applied_authoritative_student_actor_count": len(
            applied_authoritative_student_ids
        ),
        "matched_binding_count": len(binding_ids),
        "unique_binding_id_count": len(binding_id_set),
        "unique_binding_address_count": len(binding_address_set),
        "matched_named_binding_count": len(binding_named_ids),
        "matched_student_binding_count": len(binding_student_ids),
        "local_actor_count": len(local_addresses),
        "unique_local_actor_count": len(local_address_set),
        "local_named_actor_count": len(local_named_addresses),
        "local_student_actor_count": len(local_student_addresses),
        "missing_binding_ids": sorted(
            applied_authoritative_id_set - binding_id_set
        ),
        "missing_named_binding_ids": sorted(
            applied_authoritative_named_ids - binding_named_ids
        ),
        "missing_student_binding_ids": sorted(
            applied_authoritative_student_ids - binding_student_ids
        ),
        "stale_binding_ids": sorted(
            binding_id_set - applied_authoritative_id_set
        ),
        "stale_named_binding_ids": sorted(
            binding_named_ids - applied_authoritative_named_ids
        ),
        "stale_student_binding_ids": sorted(
            binding_student_ids - applied_authoritative_student_ids
        ),
        "unbound_local_actor_count": len(
            local_address_set - binding_address_set
        ),
        "unbound_local_named_actor_count": len(
            local_named_addresses - bound_named_addresses
        ),
        "unbound_local_student_actor_count": len(
            local_student_addresses - bound_student_addresses
        ),
        "apply_local_actor_count": presentation.parse_int(
            client_values.get("replicated.local_actor_count")
        ),
        "apply_matched_actor_count": presentation.parse_int(
            client_values.get("replicated.matched_actor_count")
        ),
        "created_actor_count": presentation.parse_int(
            client_values.get("replicated.created_actor_count")
        ),
        "created_actor_total_count": presentation.parse_int(
            client_values.get("replicated.created_actor_total_count")
        ),
        "removed_actor_count": presentation.parse_int(
            client_values.get("replicated.removed_actor_count")
        ),
        "removed_actor_total_count": presentation.parse_int(
            client_values.get("replicated.removed_actor_total_count")
        ),
        "failed_remove_actor_count": presentation.parse_int(
            client_values.get("replicated.failed_remove_actor_count")
        ),
        "failed_remove_actor_total_count": presentation.parse_int(
            client_values.get("replicated.failed_remove_actor_total_count")
        ),
        "compared_total": int(summary["compared_total"]),
        "student_compared": int(summary["student_compared"]),
        "student_variant_mismatches": int(
            summary["student_variant_primary_mismatches"]
        ),
        "student_color_mismatches": int(
            summary["student_color_mismatches"]
        ),
        "student_book_palette_mismatches": int(
            summary["student_book_palette_mismatches"]
        ),
        "student_book_palette_count_mismatches": int(
            summary["student_book_palette_snapshot_count_mismatches"]
        ),
        "named_compared": int(summary["named_compared"]),
        "named_drive_phase_out_of_tolerance": int(
            summary["named_drive_phase_out_of_tolerance"]
        ),
    }


def convergence_errors(sample: dict[str, Any]) -> list[str]:
    latest_count = int(sample["latest_authoritative_actor_count"])
    applied_count = int(sample["applied_authoritative_actor_count"])
    errors: list[str] = []
    if sample["host_scene"] != "hub" or sample["client_scene"] != "hub":
        errors.append("both participants must remain in the shared hub")
    if not sample["snapshot_valid"] or not sample["apply_valid"]:
        errors.append("replicated hub snapshot/apply state is invalid")
    if not sample["apply_actors_available"]:
        errors.append("applied hub actor source is unavailable")
    if not sample["apply_presentation_available"]:
        errors.append("applied hub presentation source is unavailable")
    if not sample["presentation_clock_valid"]:
        errors.append("replicated hub presentation clock order is invalid")
    if latest_count <= 0 or applied_count <= 0:
        errors.append("latest or applied authoritative hub actor set is empty")
    if sample["snapshot_actor_count"] != latest_count:
        errors.append("snapshot actor count differs from authoritative IDs")
    if sample["snapshot_total_count"] != latest_count:
        errors.append("snapshot total count differs from authoritative IDs")
    if sample["unique_latest_authoritative_actor_count"] != latest_count:
        errors.append("latest authoritative hub actor IDs are not unique")
    if sample["unique_applied_authoritative_actor_count"] != applied_count:
        errors.append("applied authoritative hub actor IDs are not unique")
    if sample["unique_binding_id_count"] != sample["matched_binding_count"]:
        errors.append("matched hub binding IDs are not unique")
    if sample["unique_binding_address_count"] != sample["matched_binding_count"]:
        errors.append("multiple hub IDs share a local actor")
    if sample["unique_local_actor_count"] != sample["local_actor_count"]:
        errors.append("local hub actor addresses are not unique")
    if (
        sample["applied_authoritative_named_actor_count"] <= 0
        or sample["applied_authoritative_student_actor_count"] <= 0
        or sample["local_student_actor_count"] <= 0
    ):
        errors.append("named-NPC or Student lifecycle coverage is empty")
    if (
        sample["matched_named_binding_count"]
        != sample["applied_authoritative_named_actor_count"]
        or sample["local_named_actor_count"]
        != sample["applied_authoritative_named_actor_count"]
    ):
        errors.append("persistent named hub NPCs did not converge one-to-one")
    if sample["missing_named_binding_ids"]:
        errors.append("authoritative named hub NPC IDs are missing bindings")
    if sample["matched_student_binding_count"] <= 0:
        errors.append("no stock local Student is bound for presentation sync")
    if sample["matched_student_binding_count"] > min(
        sample["applied_authoritative_student_actor_count"],
        sample["local_student_actor_count"],
    ):
        errors.append("Student bindings exceed a stock actor population")
    if sample["stale_binding_ids"]:
        errors.append("retired hub IDs remain bound")
    if sample["unbound_local_named_actor_count"] != 0:
        errors.append("a persistent named hub NPC remains unbound")
    if sample["apply_local_actor_count"] != sample["local_actor_count"]:
        errors.append("apply pass observed the wrong local hub population")
    if sample["apply_matched_actor_count"] != sample["matched_binding_count"]:
        errors.append("apply pass and published hub bindings disagree")
    if sample["created_actor_count"] != 0 or sample["removed_actor_count"] != 0:
        errors.append("multiplayer structurally mutated a stock hub actor")
    if sample["failed_remove_actor_count"] != 0:
        errors.append("hub actor removal failed in the latest apply pass")
    if sample["compared_total"] != sample["matched_binding_count"]:
        errors.append("presentation comparison did not cover every bound hub actor")
    if sample["student_compared"] != sample["matched_student_binding_count"]:
        errors.append("Student presentation comparison missed a bound stock actor")
    if (
        sample["named_compared"]
        != sample["applied_authoritative_named_actor_count"]
    ):
        errors.append("named-NPC presentation comparison is incomplete")
    if any(
        int(sample[field]) != 0
        for field in (
            "student_variant_mismatches",
            "student_color_mismatches",
            "student_book_palette_mismatches",
            "student_book_palette_count_mismatches",
            "named_drive_phase_out_of_tolerance",
        )
    ):
        errors.append("hub NPC presentation state diverged")
    return errors


def wait_for_convergence(
    pair: SteamFriendActivePair,
    lua_timeout: float,
    convergence_timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + convergence_timeout
    attempts: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        sample = capture(pair, lua_timeout)
        errors = convergence_errors(sample)
        attempts.append(
            {
                "snapshot_sequence": sample["snapshot_sequence"],
                "errors": errors,
            }
        )
        if not errors:
            sample["convergence_attempts"] = attempts
            return sample
        time.sleep(0.1)
    raise VerifyFailure(
        "hub state did not self-correct before the convergence deadline: "
        + json.dumps(attempts[-1] if attempts else {}, sort_keys=True)
    )


def run(
    pair: SteamFriendActivePair,
    duration: float,
    interval: float,
    lua_timeout: float,
    convergence_timeout: float,
) -> dict[str, Any]:
    discovered = pair.discover()
    if (
        discovered["host"]["scene"] != "hub"
        or discovered["client"]["scene"] != "hub"
    ):
        raise VerifyFailure(
            f"Steam friend pair is not in the shared hub: {discovered}"
        )

    started = time.monotonic()
    deadline = started + duration
    next_sample_at = started
    samples: list[dict[str, Any]] = []
    observed_ids: set[int] = set()
    retired_ids: set[int] = set()
    previous_ids: set[int] | None = None
    lifecycle_change_count = 0

    while not samples or time.monotonic() < deadline:
        sample = wait_for_convergence(
            pair,
            lua_timeout,
            convergence_timeout,
        )
        current_ids = set(sample.pop("latest_authoritative_ids"))
        if retired_ids & current_ids:
            raise VerifyFailure(
                "a retired hub network actor ID was reused in the same scene"
            )

        born_ids = current_ids - (previous_ids or set())
        retired_now = (
            previous_ids - current_ids
            if previous_ids is not None
            else set()
        )
        if previous_ids is not None and (born_ids or retired_now):
            lifecycle_change_count += 1
        retired_ids.update(retired_now)
        observed_ids.update(current_ids)
        sample["born_actor_count"] = len(born_ids)
        sample["retired_actor_count"] = len(retired_now)
        sample["elapsed_seconds"] = round(
            time.monotonic() - started,
            3,
        )
        samples.append(sample)
        previous_ids = current_ids

        next_sample_at += interval
        remaining = min(
            next_sample_at,
            deadline,
        ) - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    created_totals = [
        int(sample["created_actor_total_count"])
        for sample in samples
    ]
    removed_totals = [
        int(sample["removed_actor_total_count"])
        for sample in samples
    ]
    failed_remove_totals = [
        int(sample["failed_remove_actor_total_count"])
        for sample in samples
    ]
    for label, totals in (
        ("created", created_totals),
        ("removed", removed_totals),
        ("failed-remove", failed_remove_totals),
    ):
        if any(later < earlier for earlier, later in zip(totals, totals[1:])):
            raise VerifyFailure(
                f"{label} hub actor total regressed during one scene epoch"
            )
    if failed_remove_totals[-1] != failed_remove_totals[0]:
        raise VerifyFailure(
            "at least one hub actor removal failed during the soak"
        )
    if created_totals[-1] != created_totals[0]:
        raise VerifyFailure(
            "multiplayer factory-created a stock hub actor during the soak"
        )
    if removed_totals[-1] != removed_totals[0]:
        raise VerifyFailure(
            "multiplayer unregistered a stock hub actor during the soak"
        )
    if lifecycle_change_count == 0:
        raise VerifyFailure(
            "the soak observed no stock hub actor lifecycle replacement"
        )

    final_pair = pair.discover()
    if (
        final_pair["host"]["scene"] != "hub"
        or final_pair["client"]["scene"] != "hub"
    ):
        raise VerifyFailure("Steam pair stopped responding in the shared hub")

    aggregate = {
        "sample_count": len(samples),
        "duration_seconds": round(time.monotonic() - started, 3),
        "lifecycle_change_count": lifecycle_change_count,
        "unique_authoritative_actor_count": len(observed_ids),
        "retired_authoritative_actor_count": len(retired_ids),
        "maximum_live_actor_count": max(
            int(sample["latest_authoritative_actor_count"])
            for sample in samples
        ),
        "maximum_convergence_attempts": max(
            len(sample["convergence_attempts"])
            for sample in samples
        ),
        "created_actor_total_delta": created_totals[-1] - created_totals[0],
        "removed_actor_total_delta": removed_totals[-1] - removed_totals[0],
        "failed_remove_actor_total_delta": (
            failed_remove_totals[-1] - failed_remove_totals[0]
        ),
        "final_pair_responsive": True,
    }
    return {
        "ok": True,
        "transport": "steam_friend",
        "same_machine": PAIR_BACKEND == "wsl",
        "pair": discovered,
        "aggregate": aggregate,
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--lua-timeout", type=float, default=12.0)
    parser.add_argument("--convergence-timeout", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("--duration must be positive")
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.convergence_timeout <= 0:
        parser.error("--convergence-timeout must be positive")

    pair = SteamFriendActivePair()
    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        result = run(
            pair,
            args.duration,
            args.interval,
            args.lua_timeout,
            args.convergence_timeout,
        )
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
    finally:
        pair.close()
        result = pair.redact(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": result.get("ok", False),
                    "error": result.get("error"),
                    "aggregate": result.get("aggregate"),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    sys.exit(main())
