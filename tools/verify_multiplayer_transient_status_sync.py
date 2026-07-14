#!/usr/bin/env python3
"""Verify exact-native transient Poisoned status synchronization both ways."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiplayer_transient_status_harness import (
    TRANSIENT_POISONED,
    TRANSIENT_SNAPSHOT_VALID,
    clear_local_native_poison_status,
    inject_native_poison_status,
    query_poison_status,
    wait_for_poison_state,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    stop_games,
)
from verify_multiplayer_all_upgrade_sync import new_crash_artifacts
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_player_health_death_sync import set_local_player_vitals


OUTPUT = ROOT / "runtime/multiplayer_transient_status_sync.json"
POISON_DURATION_TICKS = 1200
POISON_DAMAGE_PER_TICK = 0.125


@dataclass(frozen=True)
class Direction:
    name: str
    participant_id: int
    other_participant_id: int
    owner_pipe: str
    observer_pipe: str


DIRECTIONS = (
    Direction("host_owned", HOST_ID, CLIENT_ID, HOST_PIPE, CLIENT_PIPE),
    Direction("client_owned", CLIENT_ID, HOST_ID, CLIENT_PIPE, HOST_PIPE),
)


def assert_clear(snapshot: dict[str, Any], label: str) -> None:
    if snapshot["runtime_flags"] & TRANSIENT_POISONED:
        raise VerifyFailure(f"{label} retained protocol Poisoned: {snapshot}")
    if snapshot["native_flags"] & TRANSIENT_POISONED:
        raise VerifyFailure(f"{label} retained native Poisoned: {snapshot}")
    if snapshot["poison_count"] != 0:
        raise VerifyFailure(f"{label} retained native poison modifiers: {snapshot}")


def wait_for_owner_damage(
    direction: Direction,
    *,
    hp_before: float,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_owner: dict[str, Any] = {}
    last_observer: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_owner = query_poison_status(direction.owner_pipe)
        last_observer = query_poison_status(
            direction.observer_pipe,
            participant_id=direction.participant_id,
        )
        if (
            last_owner["hp"] < hp_before - 0.01
            and math.isclose(last_observer["hp"], last_owner["hp"], abs_tol=0.2)
        ):
            return last_owner, last_observer
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name} stock poison damage did not remain owner-authoritative: "
        f"before={hp_before} owner={last_owner} observer={last_observer}"
    )


def run_direction(direction: Direction, timeout: float) -> dict[str, Any]:
    owner_before = wait_for_poison_state(
        direction.owner_pipe,
        participant_id=None,
        poisoned=False,
        timeout=timeout,
    )
    observer_before = wait_for_poison_state(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        poisoned=False,
        timeout=timeout,
    )
    unrelated_before = query_poison_status(direction.observer_pipe)
    assert_clear(unrelated_before, f"{direction.name} unrelated local participant before")

    injection = inject_native_poison_status(
        direction.owner_pipe,
        duration_ticks=POISON_DURATION_TICKS,
        damage_per_tick=POISON_DAMAGE_PER_TICK,
        source_slot=0,
        label=direction.name,
    )
    owner_active = wait_for_poison_state(
        direction.owner_pipe,
        participant_id=None,
        poisoned=True,
        timeout=timeout,
    )
    observer_active = wait_for_poison_state(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        poisoned=True,
        timeout=timeout,
    )

    expected_flags = TRANSIENT_SNAPSHOT_VALID | TRANSIENT_POISONED
    if owner_active["runtime_flags"] != expected_flags:
        raise VerifyFailure(
            f"{direction.name} owner protocol flags were not canonical: {owner_active}"
        )
    if observer_active["runtime_flags"] != expected_flags:
        raise VerifyFailure(
            f"{direction.name} observer protocol flags were not canonical: {observer_active}"
        )
    if observer_active["replicated_flags"] != expected_flags:
        raise VerifyFailure(
            f"{direction.name} bot snapshot lost replicated Poisoned: {observer_active}"
        )
    if observer_active["poison_count"] != 1:
        raise VerifyFailure(
            f"{direction.name} observer materialized duplicate poison modifiers: "
            f"{observer_active}"
        )
    if observer_active["control_refs"] != 1:
        raise VerifyFailure(
            f"{direction.name} observer poison smart pointer leaked a reference: "
            f"{observer_active}"
        )
    if not math.isclose(observer_active["damage_per_tick"], 0.0, abs_tol=1e-7):
        raise VerifyFailure(
            f"{direction.name} observer poison clone could apply duplicate damage: "
            f"{observer_active}"
        )
    if observer_active["source_slot"] != 1:
        raise VerifyFailure(
            f"{direction.name} observer poison clone lost visual-only source marker: "
            f"{observer_active}"
        )
    if owner_active["control_refs"] != 1:
        raise VerifyFailure(
            f"{direction.name} injected owner poison smart pointer is imbalanced: "
            f"{owner_active}"
        )
    if not math.isclose(
        owner_active["damage_per_tick"],
        POISON_DAMAGE_PER_TICK,
        abs_tol=1e-6,
    ):
        raise VerifyFailure(
            f"{direction.name} owner poison lost stock damage behavior: {owner_active}"
        )
    if abs(observer_active["native_ticks"] - observer_active["runtime_ticks"]) > 30:
        raise VerifyFailure(
            f"{direction.name} observer native duration drifted from protocol: "
            f"{observer_active}"
        )

    # Remote gameplay-slot actors do not run the owner's modifier countdown.
    # Reconciliation therefore advances the inert visual clone in bounded
    # <=20-tick steps. Observe beyond one full tolerance window.
    time.sleep(0.75)
    owner_damaged, observer_damaged = wait_for_owner_damage(
        direction,
        hp_before=owner_before["hp"],
        timeout=min(timeout, 8.0),
    )
    if owner_damaged["modifier_ticks"] >= owner_active["modifier_ticks"]:
        raise VerifyFailure(
            f"{direction.name} owner poison duration did not advance: "
            f"active={owner_active} later={owner_damaged}"
        )
    if observer_damaged["modifier_ticks"] >= observer_active["modifier_ticks"]:
        raise VerifyFailure(
            f"{direction.name} observer poison duration did not advance: "
            f"active={observer_active} later={observer_damaged}"
        )
    if not math.isclose(observer_damaged["damage_per_tick"], 0.0, abs_tol=1e-7):
        raise VerifyFailure(
            f"{direction.name} observer poison became damaging after reconciliation: "
            f"{observer_damaged}"
        )
    unrelated_active = query_poison_status(direction.observer_pipe)
    assert_clear(unrelated_active, f"{direction.name} unrelated local participant active")

    cleared = clear_local_native_poison_status(direction.owner_pipe)
    owner_cleared = wait_for_poison_state(
        direction.owner_pipe,
        participant_id=None,
        poisoned=False,
        timeout=timeout,
    )
    observer_cleared = wait_for_poison_state(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        poisoned=False,
        timeout=timeout,
    )
    unrelated_cleared = query_poison_status(direction.observer_pipe)
    assert_clear(unrelated_cleared, f"{direction.name} unrelated local participant cleared")

    return {
        "owner_before": owner_before,
        "observer_before": observer_before,
        "injection": injection,
        "owner_active": owner_active,
        "observer_active": observer_active,
        "owner_damaged": owner_damaged,
        "observer_damaged": observer_damaged,
        "owner_hp_delta": owner_before["hp"] - owner_damaged["hp"],
        "clear_request": cleared,
        "owner_cleared": owner_cleared,
        "observer_cleared": observer_cleared,
    }


def run_host_mirror_owner_correction(timeout: float) -> dict[str, Any]:
    """Prove host-side native status hits are transferred to the client owner."""

    direction = DIRECTIONS[1]
    owner_before = wait_for_poison_state(
        direction.owner_pipe,
        participant_id=None,
        poisoned=False,
        timeout=timeout,
    )
    mirror_before = wait_for_poison_state(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        poisoned=False,
        timeout=timeout,
    )
    resources = set_local_player_vitals(direction.owner_pipe, 1000.0, 1000.0)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        owner_before = query_poison_status(direction.owner_pipe)
        mirror_before = query_poison_status(
            direction.observer_pipe,
            participant_id=direction.participant_id,
        )
        if (
            owner_before["hp"] >= 999.0
            and math.isclose(mirror_before["hp"], owner_before["hp"], abs_tol=0.2)
        ):
            break
        time.sleep(0.05)
    else:
        raise VerifyFailure(
            "client owner health did not settle on its host mirror before poison "
            f"correction trial: owner={owner_before} mirror={mirror_before}"
        )

    injection = inject_native_poison_status(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        duration_ticks=POISON_DURATION_TICKS,
        damage_per_tick=POISON_DAMAGE_PER_TICK,
        source_slot=0,
        label="client_host_mirror_authority",
    )
    owner_active = wait_for_poison_state(
        direction.owner_pipe,
        participant_id=None,
        poisoned=True,
        timeout=timeout,
    )
    mirror_active = wait_for_poison_state(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        poisoned=True,
        timeout=timeout,
    )
    if not math.isclose(
        owner_active["damage_per_tick"],
        POISON_DAMAGE_PER_TICK,
        abs_tol=1e-6,
    ) or owner_active["source_slot"] != 0:
        raise VerifyFailure(
            "client owner correction lost authoritative poison behavior: "
            f"{owner_active}"
        )
    if (
        not math.isclose(mirror_active["damage_per_tick"], 0.0, abs_tol=1e-7)
        or mirror_active["source_slot"] != 1
    ):
        raise VerifyFailure(
            "host mirror correction was not converted to one inert observer clone: "
            f"{mirror_active}"
        )
    if abs(owner_active["modifier_ticks"] - injection["duration_after_apply"]) > 30:
        raise VerifyFailure(
            "client owner correction changed the host-transformed poison duration: "
            f"injection={injection} owner={owner_active}"
        )

    owner_damaged, mirror_damaged = wait_for_owner_damage(
        direction,
        hp_before=owner_before["hp"],
        timeout=min(timeout, 8.0),
    )
    cleared = clear_local_native_poison_status(direction.owner_pipe)
    owner_cleared = wait_for_poison_state(
        direction.owner_pipe,
        participant_id=None,
        poisoned=False,
        timeout=timeout,
    )
    mirror_cleared = wait_for_poison_state(
        direction.observer_pipe,
        participant_id=direction.participant_id,
        poisoned=False,
        timeout=timeout,
    )
    unrelated_host = query_poison_status(direction.observer_pipe)
    assert_clear(unrelated_host, "host local participant after mirror correction")
    return {
        "resources": resources,
        "owner_before": owner_before,
        "mirror_before": mirror_before,
        "injection": injection,
        "owner_active": owner_active,
        "mirror_active": mirror_active,
        "owner_damaged": owner_damaged,
        "mirror_damaged": mirror_damaged,
        "owner_hp_delta": owner_before["hp"] - owner_damaged["hp"],
        "clear_request": cleared,
        "owner_cleared": owner_cleared,
        "mirror_cleared": mirror_cleared,
    }


def compact_direction(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "owner_hp_delta": result["owner_hp_delta"],
        "owner_active_ticks": result["owner_active"]["modifier_ticks"],
        "observer_active_ticks": result["observer_active"]["modifier_ticks"],
        "observer_damage_per_tick": result["observer_active"]["damage_per_tick"],
        "owner_cleared_count": result["owner_cleared"]["poison_count"],
        "observer_cleared_count": result["observer_cleared"]["poison_count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        output["startup"] = launch_pair_ready(
            args.timeout,
            god_mode=False,
            manual_combat=False,
            prearm_manual_spawner=True,
        )
        output["directions"] = {
            direction.name: run_direction(direction, args.timeout)
            for direction in DIRECTIONS
        }
        output["host_mirror_owner_correction"] = run_host_mirror_owner_correction(
            args.timeout
        )
        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts during transient-status test: {crashes}")
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, OSError) as exc:
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

    print(json.dumps({
        "ok": output.get("ok", False),
        "error": output.get("error"),
        "directions": {
            name: compact_direction(result)
            for name, result in output.get("directions", {}).items()
        },
        "host_mirror_owner_correction": {
            "owner_hp_delta": output.get("host_mirror_owner_correction", {}).get(
                "owner_hp_delta"
            ),
            "owner_active_ticks": output.get(
                "host_mirror_owner_correction", {}
            ).get("owner_active", {}).get("modifier_ticks"),
            "mirror_damage_per_tick": output.get(
                "host_mirror_owner_correction", {}
            ).get("mirror_active", {}).get("damage_per_tick"),
            "owner_cleared_count": output.get(
                "host_mirror_owner_correction", {}
            ).get("owner_cleared", {}).get("poison_count"),
            "mirror_cleared_count": output.get(
                "host_mirror_owner_correction", {}
            ).get("mirror_cleared", {}).get("poison_count"),
        },
        "new_crash_artifacts": output.get("new_crash_artifacts", []),
        "output": str(args.output),
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
