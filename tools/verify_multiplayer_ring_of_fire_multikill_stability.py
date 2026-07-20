#!/usr/bin/env python3
"""Reproduce the client-owned Ring of Fire multi-kill crash against a local pair."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_PIPE,
    VerifyFailure,
    parse_key_values,
    place_player,
    stop_games,
)
from verify_multiplayer_all_upgrade_sync import (
    new_crash_artifacts,
    wait_for_post_run_progression_ready,
)
from verify_multiplayer_fireball_explode_effect_sync import launch_pair_ready
from verify_multiplayer_focus_behavior_sync import (
    Direction as SecondaryDirection,
    acquire_secondary_to_rank,
    cast_secondary_belt_slot,
    wait_for_remote_delivery,
)
from verify_multiplayer_primary_kill_stress import (
    cleanup_live_enemies,
    find_target,
    parse_int,
    spawn_one_enemy,
    wait_for_pair_transform_convergence,
    values,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    detect_instance_pids,
    read_log,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime/multiplayer_ring_of_fire_multikill_stability.json"
RING_OF_FIRE_ROW = 21
TARGET_HP = 0.75
CASTER_POSITION = (1800.0, 1750.0)
OBSERVER_POSITION = (1800.0, 2250.0)
ENEMY_OFFSETS = (
    (32.0, 0.0),
    (-32.0, 0.0),
    (0.0, 32.0),
    (0.0, -32.0),
    (22.0, 22.0),
    (-22.0, 22.0),
    (22.0, -22.0),
    (-22.0, -22.0),
)


OBJECT_MANAGER_DENSITY_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function safe_read_ptr(address)
  local ok, value = pcall(sd.debug.read_ptr, address)
  return ok and (tonumber(value) or 0) or 0
end
local function safe_read_i32(address)
  local ok, value = pcall(sd.debug.read_i32, address)
  return ok and (tonumber(value) or 0) or -1
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local actor = tonumber(player and player.actor_address or 0) or 0
local owner_offset = sd.debug.layout_offset("actor_owner")
local world = actor ~= 0 and owner_offset ~= nil and safe_read_ptr(actor + owner_offset) or 0
-- Solomon Dark's primary world ObjectManager is embedded at world+0x2C4.
-- The stock tick at 0x004022A0 dereferences every entry below count and
-- crashed at index 26 when that entry was null during the reported multi-kill.
local manager = world ~= 0 and (world + 0x2C4) or 0
local count = manager ~= 0 and safe_read_i32(manager + 0x08) or -1
local capacity = manager ~= 0 and safe_read_i32(manager + 0x0C) or -1
local list = manager ~= 0 and safe_read_ptr(manager + 0x14) or 0
local null_count = 0
local first_null = -1
local scanned = 0
if count >= 0 and count <= 4096 and list ~= 0 then
  for index = 0, count - 1 do
    scanned = scanned + 1
    if safe_read_ptr(list + index * 4) == 0 then
      null_count = null_count + 1
      if first_null < 0 then first_null = index end
    end
  end
end
emit(
  "valid",
  world ~= 0 and manager ~= 0 and count >= 0 and count <= 4096 and
    (count == 0 or list ~= 0)
)
emit("actor", string.format("0x%08X", actor))
emit("world", string.format("0x%08X", world))
emit("manager", string.format("0x%08X", manager))
emit("count", count)
emit("capacity", capacity)
emit("list", string.format("0x%08X", list))
emit("scanned", scanned)
emit("null_count", null_count)
emit("first_null", first_null)
"""


def process_state(pids: dict[str, int]) -> dict[str, bool]:
    command = "; ".join(
        f"Write-Output ('{role}=' + [bool](Get-Process -Id {pid} -ErrorAction SilentlyContinue))"
        for role, pid in pids.items()
        if role in ("host", "client")
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=8.0,
        check=False,
    )
    parsed = parse_key_values(completed.stdout)
    return {
        role: parsed.get(role, "").strip().lower() == "true"
        for role in ("host", "client")
    }


def density(pipe_name: str) -> dict[str, str]:
    return values(pipe_name, OBJECT_MANAGER_DENSITY_LUA, timeout=5.0)


def require_dense(label: str, snapshot: dict[str, str]) -> None:
    if snapshot.get("valid") != "true" or parse_int(snapshot.get("null_count"), -1) != 0:
        raise VerifyFailure(f"{label} native ObjectManager is sparse: {snapshot}")


def wait_for_accepted_cast(
    direction: SecondaryDirection,
    belt_slot: int,
    source_offset: int,
    timeout: float,
) -> dict[str, Any]:
    accepted_token = "Multiplayer local secondary cast queued from native dispatcher."
    rejected_token = "Multiplayer local secondary cast rejected by native dispatcher."
    deadline = time.monotonic() + timeout
    attempts = 0
    input_modes: list[str] = []
    while time.monotonic() < deadline:
        attempts += 1
        cast_secondary_belt_slot(
            direction,
            belt_slot,
            deadline - time.monotonic(),
        )
        input_modes.append("live_native_binding")
        time.sleep(0.12)
        current = read_log(direction.source_log)[source_offset:]
        if accepted_token in current:
            return {
                "attempts": attempts,
                "accepted_count": current.count(accepted_token),
                "rejected_count": current.count(rejected_token),
                "input_modes": input_modes,
            }
    raise VerifyFailure(
        f"client Ring of Fire cast was never accepted after {attempts} attempts"
    )


def wait_for_multikill_or_crash(
    pids: dict[str, int],
    host_log_offset: int,
    client_log_offset: int,
    timeout: float,
) -> dict[str, Any]:
    accepted_damage_token = "Multiplayer enemy damage claim accepted"
    sent_damage_token = "Multiplayer enemy damage claim sent."
    deadline = time.monotonic() + timeout
    samples: list[dict[str, Any]] = []
    best_claim_count = 0
    best_sent_count = 0
    while time.monotonic() < deadline:
        alive = process_state(pids)
        host_delta = read_log(HOST_LOG)[host_log_offset:]
        client_delta = read_log(CLIENT_LOG)[client_log_offset:]
        best_claim_count = max(best_claim_count, host_delta.count(accepted_damage_token))
        best_sent_count = max(best_sent_count, client_delta.count(sent_damage_token))
        samples.append(
            {
                "elapsed_seconds": round(timeout - max(0.0, deadline - time.monotonic()), 3),
                "alive": alive,
                "accepted_damage_claim_count": best_claim_count,
                "sent_damage_claim_count": best_sent_count,
            }
        )
        if not all(alive.values()):
            return {
                "processes_alive": alive,
                "accepted_damage_claim_count": best_claim_count,
                "sent_damage_claim_count": best_sent_count,
                "samples": samples,
            }
        if best_sent_count >= 3:
            # The reported failure occurred in the next native app tick. Leave
            # enough time for death presentation, loot suppression, and replay.
            time.sleep(1.0)
            alive = process_state(pids)
            return {
                "processes_alive": alive,
                "accepted_damage_claim_count": best_claim_count,
                "sent_damage_claim_count": best_sent_count,
                "samples": samples,
            }
        time.sleep(0.08)
    return {
        "processes_alive": process_state(pids),
        "accepted_damage_claim_count": best_claim_count,
        "sent_damage_claim_count": best_sent_count,
        "samples": samples,
    }


def run_verifier(timeout: float, result: dict[str, Any]) -> dict[str, Any]:
    started_at = time.time()
    result.update({"ok": False, "started_at": started_at})
    startup = launch_pair_ready(timeout, god_mode=False, manual_combat=True)
    result["startup"] = startup
    result["pids"] = detect_instance_pids()
    result["post_run_progression_ready"] = wait_for_post_run_progression_ready(timeout)
    result["cleanup"] = cleanup_live_enemies()

    direction = SecondaryDirection(
        name="client_owned_ring_of_fire",
        process_role="client",
        source_id=CLIENT_ID,
        source_pipe=CLIENT_PIPE,
        source_log=CLIENT_LOG,
        observer_log=HOST_LOG,
    )
    result["resources"] = set_local_player_vitals(CLIENT_PIPE, 5000.0, 5000.0)
    result["acquisition"] = acquire_secondary_to_rank(
        direction,
        RING_OF_FIRE_ROW,
        1,
        timeout,
    )
    belt_slot = int(result["acquisition"]["belt_slot"])

    result["placement"] = {
        "client": place_player(CLIENT_PIPE, *CASTER_POSITION, 90.0),
        "host": place_player(HOST_PIPE, *OBSERVER_POSITION, 90.0),
    }
    result["placement"]["convergence"] = wait_for_pair_transform_convergence(timeout=timeout)
    result["density_before_spawn"] = {
        "host": density(HOST_PIPE),
        "client": density(CLIENT_PIPE),
    }
    require_dense("host before spawn", result["density_before_spawn"]["host"])
    require_dense("client before spawn", result["density_before_spawn"]["client"])

    enemies: list[dict[str, Any]] = []
    for dx, dy in ENEMY_OFFSETS:
        x = CASTER_POSITION[0] + dx
        y = CASTER_POSITION[1] + dy
        spawned = spawn_one_enemy(x, y, setup_hp=TARGET_HP)
        network_id = parse_int(spawned["result"].get("network_actor_id"))
        if network_id == 0:
            raise VerifyFailure(f"manual enemy has no network id: {spawned}")
        spawned["network_actor_id"] = network_id
        spawned["host_ready"] = find_target(
            HOST_PIPE,
            x,
            y,
            network_id,
            timeout,
            require_local_binding=False,
        )
        spawned["client_ready"] = find_target(CLIENT_PIPE, x, y, network_id, timeout)
        enemies.append(spawned)
    result["enemies"] = enemies
    result["density_after_spawn"] = {
        "host": density(HOST_PIPE),
        "client": density(CLIENT_PIPE),
    }
    require_dense("host after spawn", result["density_after_spawn"]["host"])
    require_dense("client after spawn", result["density_after_spawn"]["client"])

    source_offset = len(read_log(CLIENT_LOG))
    observer_offset = len(read_log(HOST_LOG))
    result["cast"] = wait_for_accepted_cast(
        direction,
        belt_slot,
        source_offset,
        timeout,
    )
    result["cast"]["remote_delivery_count"] = wait_for_remote_delivery(
        direction,
        observer_offset,
        expected_count=1,
        timeout=timeout,
    )
    result["multikill"] = wait_for_multikill_or_crash(
        result["pids"],
        observer_offset,
        source_offset,
        timeout,
    )
    if result["multikill"]["sent_damage_claim_count"] < 3:
        raise VerifyFailure(
            "Ring of Fire did not exercise the reported multi-kill seam: "
            f"{result['multikill']}"
        )
    if not all(result["multikill"]["processes_alive"].values()):
        raise VerifyFailure(
            f"Ring of Fire multi-kill terminated a peer: {result['multikill']}"
        )

    suppression_token = "replicated_loot: removed unbound client loot actors."
    result["client_loot_suppression"] = {
        "event_count": read_log(CLIENT_LOG)[source_offset:].count(suppression_token),
    }

    stale_callback_token = (
        "pointer_list_delete_batch: disabled stale managed release callback."
    )
    result["stale_managed_callback_guard"] = {
        "event_count": read_log(CLIENT_LOG)[source_offset:].count(stale_callback_token),
    }
    if result["stale_managed_callback_guard"]["event_count"] < 1:
        raise VerifyFailure(
            "Ring of Fire multi-kill did not exercise the stale managed-callback seam"
        )

    result["density_after_cast"] = {
        "host": density(HOST_PIPE),
        "client": density(CLIENT_PIPE),
    }
    require_dense("host after cast", result["density_after_cast"]["host"])
    require_dense("client after cast", result["density_after_cast"]["client"])
    result["new_crash_artifacts"] = new_crash_artifacts(started_at)
    if result["new_crash_artifacts"]:
        raise VerifyFailure(
            f"new crash artifacts during Ring of Fire multi-kill: {result['new_crash_artifacts']}"
        )
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=24.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        stop_games()
        result = run_verifier(args.timeout, result)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        result["new_crash_artifacts"] = new_crash_artifacts(
            float(result.get("started_at", time.time()))
        )
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not args.keep_open:
            stop_games()

    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "new_crash_artifacts": result.get("new_crash_artifacts", []),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
