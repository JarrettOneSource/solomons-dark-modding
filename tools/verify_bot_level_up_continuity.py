#!/usr/bin/env python3
"""Verify a hosted Lua teammate keeps fighting through the owner's level-up."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools._real_flow_e2e.evidence import write_json, write_manifest  # noqa: E402
from tools._real_flow_e2e.runtime import LuaPipe, effective_wave_index  # noqa: E402
from tools._real_flow_e2e.windows import (  # noqa: E402
    BOT_PLAY_TEAM_ROSTER,
    PowerShell,
    assert_ports_free,
    port_inventory,
    windows_path,
    windows_processes,
)
from tools.verify_bot_play_for_me_solo import (  # noqa: E402
    _copy_runtime_artifacts,
    _exact_process,
    _git_sha,
    _launch,
    _ledger_process_id,
    _request_until_true,
    _stage_package,
    _stop_exact_process,
    _wait_live_wave,
    _wait_run_loading_started,
    _wait_run_ready,
    _wait_scene,
    _write_initial_settings,
)
from tools.verify_local_multiplayer_sync import parse_key_values  # noqa: E402
from tools.verify_real_flow_e2e import (  # noqa: E402
    BOT_MOD_ID,
    _drain_damage_observations,
    _reset_damage_observations,
    _udp_exclusion_inventory,
)


class BotLevelUpContinuityFailure(RuntimeError):
    """The owner level-up wedged or invalidated the Lua teammate."""


BOUNDARY_CURRENT_MP = 10.0
BOUNDARY_MAX_MP = 100.0


BOT_PROBE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local root = rawget(_G, "bot_brain_debug") or {}
local brain = type(root.bots) == "table" and root.bots[1] or {}
local bots = sd.bots.list() or {}
local handle = bots[1]
local participant_id = handle and tonumber(handle:participant_id()) or
  tonumber(brain.participant_id) or 0
local snapshot = participant_id > 0 and
  sd.bots.get_participant_state(participant_id) or {}
local choices = participant_id > 0 and
  sd.bots.get_skill_choices(participant_id) or {}
local runtime = sd.runtime.get_multiplayer_state() or {}
local owner_participant_id = 0
for _, participant in ipairs(runtime.participants or {}) do
  if participant.is_owner == true and
      tostring(participant.controller_kind or "") ~= "LuaBrain" then
    owner_participant_id = tonumber(participant.participant_id) or 0
    break
  end
end
local offer = runtime.active_level_up_offer or {}
local wait = runtime.level_up_wait_status or {}
local shared_pause = runtime.shared_gameplay_pause_status or {}
local scene = sd.world.get_scene() or {}
local player = sd.player.get_state() or {}
local progression = tonumber(snapshot.progression_runtime_state_address) or 0
local nonlocal_offset = sd.debug.layout_offset(
  "progression_nonlocal_mode_flag")
local picker_offset = sd.debug.layout_offset(
  "progression_local_skill_picker_screen")
emit("scene", scene.name or scene.kind or "")
emit("scene.pending_level_kind", scene.pending_level_kind or -1)
emit("simulation_tick_count", root.simulation_tick_count or 0)
emit("clock_now_ms", root.clock_now_ms or 0)
emit("bot.count", #bots)
emit("bot.participant_id", participant_id)
emit("bot.level", snapshot.level or
  (snapshot.profile and snapshot.profile.level) or 0)
emit("bot.progression", progression)
emit("bot.nonlocal_mode", progression ~= 0 and
  sd.debug.read_u8(progression + nonlocal_offset) or -1)
emit("bot.picker_screen", progression ~= 0 and
  sd.debug.read_u32(progression + picker_offset) or -1)
emit("bot.choice_pending", choices.pending or false)
emit("bot.choice_generation", choices.generation or 0)
emit("bot.choice_count", type(choices.options) == "table" and
  #choices.options or 0)
emit("bot.mana_reserve_active", snapshot.mana_reserve_active or false)
for _, key in ipairs({
  "active",
  "mode",
  "think_count",
  "move_issued",
  "move_accepted",
  "cast_issued",
  "cast_accepted",
  "skill_choices_accepted",
  "mana_sample_valid",
  "mana_cast_hold",
  "mana_hold_start_count",
  "mana_hold_end_count",
  "hp",
  "max_hp",
  "hp_ratio",
  "flee_transition_count",
  "mp",
  "max_mp",
  "mp_ratio",
  "live_enemy_count",
  "target_network_actor_id",
  "target_distance",
  "last_error",
}) do
  emit("brain." .. key, brain[key])
end
emit("owner.participant_id", owner_participant_id)
emit("owner.level", player.level or 0)
emit("owner.xp", player.xp or 0)
emit("owner.progression", player.progression_address or 0)
emit("offer.valid", offer.valid or false)
emit("offer.id", offer.offer_id or 0)
emit("offer.target", offer.target_participant_id or 0)
emit("offer.level", offer.level or 0)
emit("offer.option_count", offer.option_count or 0)
emit("offer.selection_submitted", offer.selection_submitted or false)
emit("wait.valid", wait.valid or false)
emit("wait.pause_active", wait.pause_active or false)
emit("wait.waiting_count", wait.waiting_count or 0)
emit("shared_pause.valid", shared_pause.valid or false)
emit("shared_pause.pause_active", shared_pause.pause_active or false)
"""


def _integer(values: dict[str, str], key: str, default: int = 0) -> int:
    text = str(values.get(key, default)).strip()
    try:
        return int(text, 0)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return default


def _number(values: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _boolean(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").casefold() == "true"


def _stage_reproducer_package(
    package_root: Path,
    evidence_root: Path,
) -> Path:
    destination = _stage_package(package_root, evidence_root)
    shutil.copytree(
        ROOT / "config",
        destination / "config",
        dirs_exist_ok=True,
    )
    shutil.copytree(
        ROOT / "assets",
        destination / "assets",
        dirs_exist_ok=True,
    )
    (destination / "solomon-dark-multiplayer.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "product": "Solomon Darker",
                "version": "isolated-verifier",
                "defaultEnabledMods": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def _probe(pipe: LuaPipe) -> dict[str, Any]:
    values = parse_key_values(
        pipe.execute(f"-- sdmod-exec-target: {BOT_MOD_ID}\n{BOT_PROBE_LUA}")
    )
    integer_keys = {
        "scene.pending_level_kind",
        "simulation_tick_count",
        "clock_now_ms",
        "bot.count",
        "bot.participant_id",
        "bot.level",
        "bot.progression",
        "bot.nonlocal_mode",
        "bot.picker_screen",
        "bot.choice_generation",
        "bot.choice_count",
        "brain.think_count",
        "brain.move_issued",
        "brain.move_accepted",
        "brain.cast_issued",
        "brain.cast_accepted",
        "brain.skill_choices_accepted",
        "brain.mana_hold_start_count",
        "brain.mana_hold_end_count",
        "brain.flee_transition_count",
        "brain.live_enemy_count",
        "brain.target_network_actor_id",
        "owner.participant_id",
        "owner.level",
        "owner.xp",
        "owner.progression",
        "offer.id",
        "offer.target",
        "offer.level",
        "offer.option_count",
        "wait.waiting_count",
    }
    number_keys = {
        "brain.hp",
        "brain.max_hp",
        "brain.hp_ratio",
        "brain.mp",
        "brain.max_mp",
        "brain.mp_ratio",
        "brain.target_distance",
    }
    boolean_keys = {
        "bot.choice_pending",
        "bot.mana_reserve_active",
        "brain.active",
        "brain.mana_sample_valid",
        "brain.mana_cast_hold",
        "offer.valid",
        "offer.selection_submitted",
        "wait.valid",
        "wait.pause_active",
        "shared_pause.valid",
        "shared_pause.pause_active",
    }
    normalized: dict[str, Any] = dict(values)
    for key in integer_keys:
        normalized[key] = _integer(values, key)
    for key in number_keys:
        normalized[key] = _number(values, key, math.nan)
    for key in boolean_keys:
        normalized[key] = _boolean(values, key)
    return normalized


def _wait_for(
    pipe: LuaPipe,
    predicate: Any,
    *,
    timeout: float,
    label: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _probe(pipe)
        if predicate(last):
            return last
        time.sleep(0.1)
    raise BotLevelUpContinuityFailure(f"{label} timed out: {last}")


def _force_owner_and_bot_level_up(
    pipe: LuaPipe,
    target_level: int,
    target_experience: int,
) -> dict[str, str]:
    output = pipe.execute(
        f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local player = sd.player.get_state() or {{}}
local scene_before = sd.world.get_scene() or {{}}
local bot_ok = sd.bots.debug_sync_level_up({{
  level = {target_level},
  experience = {target_experience},
  source_progression_address = player.progression_address,
}})
local scene_after_bot = sd.world.get_scene() or {{}}
local offer_ok = sd.runtime.debug_publish_level_up_offer({{
  level = {target_level},
  experience = {target_experience},
  target_self = true,
}})
local scene_after_owner = sd.world.get_scene() or {{}}
emit("bot_sync", bot_ok)
emit("owner_offer", offer_ok)
emit("pending.before", scene_before.pending_level_kind or -1)
emit("pending.after_bot", scene_after_bot.pending_level_kind or -1)
emit("pending.after_owner", scene_after_owner.pending_level_kind or -1)
"""
    )
    values = parse_key_values(output)
    if values.get("bot_sync") != "true" or values.get("owner_offer") != "true":
        raise BotLevelUpContinuityFailure(
            f"forced owner/bot level-up was rejected: {values}"
        )
    return values


def _choose_owner_offer(pipe: LuaPipe, offer_id: int) -> dict[str, str]:
    values = parse_key_values(
        pipe.execute(
            f"""
local ok, result = pcall(sd.runtime.choose_level_up_option, {{
  offer_id = {offer_id},
  option_index = 1,
}})
print("pcall_ok=" .. tostring(ok))
print("result=" .. tostring(result))
"""
        )
    )
    if values.get("pcall_ok") != "true" or values.get("result") != "true":
        raise BotLevelUpContinuityFailure(
            f"owner level-up choice was rejected: {values}"
        )
    return values


def _set_bot_mana(
    pipe: LuaPipe,
    progression_address: int,
    current: float,
    maximum: float,
) -> dict[str, str]:
    values = parse_key_values(
        pipe.execute(
                f"""
local progression = {progression_address}
local mp = sd.debug.layout_offset("progression_mp")
local max_mp = sd.debug.layout_offset("progression_max_mp")
local wrote_mp = progression ~= 0 and
  sd.debug.write_float(progression + mp, {current}) or false
local wrote_max = progression ~= 0 and
  sd.debug.write_float(progression + max_mp, {maximum}) or false
print("wrote_mp=" .. tostring(wrote_mp))
print("wrote_max=" .. tostring(wrote_max))
print("progression=" .. tostring(progression))
"""
        )
    )
    if values.get("wrote_mp") != "true" or values.get("wrote_max") != "true":
        raise BotLevelUpContinuityFailure(f"could not prime bot mana: {values}")
    return values


def _protect_participants(pipe: LuaPipe, bot_id: int) -> dict[str, str]:
    values = parse_key_values(
        pipe.execute(
            f"""
local function protect(progression)
  progression = tonumber(progression) or 0
  if progression == 0 then
    return false
  end
  local hp = sd.debug.layout_offset("progression_hp")
  local max_hp = sd.debug.layout_offset("progression_max_hp")
  return sd.debug.write_float(progression + max_hp, 50000.0) and
    sd.debug.write_float(progression + hp, 50000.0)
end
local player = sd.player.get_state() or {{}}
local bot = sd.bots.get_participant_state({bot_id}) or {{}}
print("owner=" .. tostring(protect(player.progression_address)))
print("bot=" .. tostring(protect(
  bot.progression_runtime_state_address)))
"""
        )
    )
    if values.get("owner") != "true" or values.get("bot") != "true":
        raise BotLevelUpContinuityFailure(
            f"could not protect live participants: {values}"
        )
    return values


def _respawn_bot_roster(pipe: LuaPipe) -> dict[str, str]:
    values = parse_key_values(
        pipe.execute(
            f"""-- sdmod-exec-target: {BOT_MOD_ID}
local result = sd.__settings_invoke_action(
  "{BOT_MOD_ID}",
  "respawn_bot")
print("ok=" .. tostring(result.ok))
print("error=" .. tostring(result.error or ""))
"""
        )
    )
    if values.get("ok") != "true":
        raise BotLevelUpContinuityFailure(
            f"could not materialize the roster in the stock arena: {values}"
        )
    return values


def _sample_combat(
    pipe: LuaPipe,
    *,
    bot_id: int,
    baseline_casts: int,
    baseline_ticks: int,
    timeout: float,
    stop_on_continuity: bool,
) -> dict[str, Any]:
    enemy_rows: list[dict[str, Any]] = []
    player_rows: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = pipe.state()
        probe = _probe(pipe)
        _drain_damage_observations(
            pipe,
            enemy_rows,
            player_rows,
            target_mod_id=BOT_MOD_ID,
        )
        samples.append(
            {
                "utcNanoseconds": time.time_ns(),
                "wave": effective_wave_index(state),
                "enemyCount": len(state["nativeEnemies"]),
                "probe": probe,
                "botDamageEdges": len(
                    [
                        row
                        for row in enemy_rows
                        if row["sourceParticipantId"] == bot_id
                        and row["damage"] > 0.0
                    ]
                ),
            }
        )
        continuity_observed = (
            probe["brain.cast_accepted"] >= baseline_casts + 2
            and probe["simulation_tick_count"] > baseline_ticks
            and any(
                row["sourceParticipantId"] == bot_id and row["damage"] > 0.0
                for row in enemy_rows
            )
        )
        if stop_on_continuity and continuity_observed:
            return {
                "ok": True,
                "samples": samples,
                "enemyRows": enemy_rows,
                "playerRows": player_rows,
                "final": probe,
            }
        time.sleep(0.25)
    final = samples[-1]["probe"] if samples else {}
    continuity_observed = (
        int(final.get("brain.cast_accepted", 0)) >= baseline_casts + 2
        and int(final.get("simulation_tick_count", 0)) > baseline_ticks
        and any(
            row["sourceParticipantId"] == bot_id and row["damage"] > 0.0
            for row in enemy_rows
        )
    )
    return {
        "ok": continuity_observed,
        "samples": samples,
        "enemyRows": enemy_rows,
        "playerRows": player_rows,
        "final": final,
    }


def _wedge_observed(
    observation: dict[str, Any],
    *,
    baseline_casts: int,
    baseline_ticks: int,
) -> bool:
    samples = observation["samples"]
    if not samples:
        return False
    probes = [row["probe"] for row in samples]
    return (
        any(row["brain.mana_cast_hold"] for row in probes)
        and all(not row["bot.mana_reserve_active"] for row in probes)
        and int(probes[-1]["brain.cast_accepted"]) == baseline_casts
        and int(probes[-1]["simulation_tick_count"]) > baseline_ticks
        and int(probes[-1]["brain.think_count"])
        > int(probes[0]["brain.think_count"])
        and int(probes[-1]["brain.live_enemy_count"]) > 0
        and float(probes[-1]["brain.mp"]) <= 10.001
    )


def _run_live(args: argparse.Namespace, result: dict[str, Any]) -> None:
    ps = PowerShell(ROOT)
    ports = {args.local_port, args.unused_remote_port}
    result["udpExclusions"] = _udp_exclusion_inventory(ps, ports)
    assert_ports_free(ps, ports)
    write_json(
        args.evidence_root / "safety" / "before.json",
        {
            "utcNanoseconds": time.time_ns(),
            "reservedPorts": port_inventory(ps, ports),
            "processes": [asdict(row) for row in windows_processes(ps)],
        },
    )

    bundle_root = _stage_reproducer_package(
        args.package_root,
        args.evidence_root,
    )
    runtime_root = args.evidence_root / "staging" / "runtime"
    settings_path = _write_initial_settings(
        args.evidence_root,
        "skirmisher",
        BOT_PLAY_TEAM_ROSTER[:1],
    )
    ledger = args.evidence_root / "safety" / "process-ledger.json"
    expected_executable = windows_path(
        runtime_root / "instances" / args.instance / "stage" / "SolomonDark.exe"
    )
    process_id = 0
    primary_error: BaseException | None = None
    try:
        launch = _launch(
            bundle_root=bundle_root,
            runtime_root=runtime_root,
            game_directory=args.game_directory,
            settings_path=settings_path,
            evidence_root=args.evidence_root,
            instance=args.instance,
            local_port=args.local_port,
            unused_remote_port=args.unused_remote_port,
            element="air",
            discipline="mind",
            max_participants=2,
            participant_id=args.participant_id,
        )
        result["launch"] = launch
        if launch.get("audioDisabled") is not True:
            raise BotLevelUpContinuityFailure("isolated launch did not disable audio")
        process_id = int(launch["processId"])
        result["ownedProcess"] = _exact_process(ps, process_id, expected_executable)
        pipe = LuaPipe(ROOT, str(launch["luaPipe"]))
        result["hub"] = _wait_scene(pipe, "hub", 45.0)
        result["runSeed"] = _request_until_true(
            pipe,
            f"sd.rng.set_seed({args.run_seed}) == {args.run_seed}",
            timeout=10.0,
            label="deterministic run seed",
        )
        result["startRun"] = _request_until_true(
            pipe,
            "sd.hub.start_match()",
            timeout=30.0,
            label="stock hosted Start Match request",
        )
        result["runLoadingStarted"] = _wait_run_loading_started(pipe, 20.0)
        result["runMaterialized"] = _wait_scene(pipe, "testrun", 45.0)
        result["runReady"] = _wait_run_ready(pipe, 45.0)
        result["waveStart"] = _request_until_true(
            pipe,
            "sd.gameplay.start_waves()",
            timeout=20.0,
            label="stock wave start request",
        )
        result["liveWave"] = _wait_live_wave(pipe, 30.0)
        result["rosterRespawn"] = _respawn_bot_roster(pipe)
        ready = _wait_for(
            pipe,
            lambda row: (
                row["bot.count"] == 1
                and row["bot.participant_id"] > 0
                and row["bot.progression"] > 0
                and row["brain.active"]
                and row["brain.live_enemy_count"] > 0
            ),
            timeout=30.0,
            label="one active Lua teammate",
        )
        bot_id = int(ready["bot.participant_id"])
        time.sleep(1.0)
        ready = _wait_for(
            pipe,
            lambda row: (
                row["bot.participant_id"] == bot_id
                and row["bot.progression"] > 0
                and row["brain.active"]
            ),
            timeout=10.0,
            label="stable Lua teammate materialization",
        )
        result["botReady"] = ready
        result["survivalProtection"] = _protect_participants(pipe, bot_id)
        result["manaPrime"] = _set_bot_mana(
            pipe,
            int(ready["bot.progression"]),
            args.bot_mana,
            args.bot_mana,
        )
        result["damageResetBeforeBaseline"] = _reset_damage_observations(
            pipe,
            target_mod_id=BOT_MOD_ID,
        )
        baseline = _sample_combat(
            pipe,
            bot_id=bot_id,
            baseline_casts=int(ready["brain.cast_accepted"]) - 2,
            baseline_ticks=int(ready["simulation_tick_count"]) - 1,
            timeout=args.baseline_timeout,
            stop_on_continuity=True,
        )
        result["baselineCombat"] = baseline
        if not baseline["ok"]:
            raise BotLevelUpContinuityFailure(
                f"Lua teammate did not establish baseline combat: {baseline['final']}"
            )

        before = _probe(pipe)
        owner_progression = int(before["owner.progression"])
        if owner_progression <= 0:
            raise BotLevelUpContinuityFailure(
                f"owner progression was unavailable: {before}"
            )
        thresholds = parse_key_values(
            pipe.execute(
                f"""
local progression = {owner_progression}
local next_offset = sd.debug.layout_offset(
  "progression_next_xp_threshold")
print("next=" .. tostring(
  sd.debug.read_float(progression + next_offset)))
"""
            )
        )
        target_level = int(before["owner.level"]) + 1
        target_experience = int(math.ceil(float(thresholds["next"])))
        result["beforeLevelUp"] = before
        result["targetLevel"] = target_level
        result["targetExperience"] = target_experience
        result["damageResetBeforeLevelUp"] = _reset_damage_observations(
            pipe,
            target_mod_id=BOT_MOD_ID,
        )
        result["forceLevelUp"] = _force_owner_and_bot_level_up(
            pipe,
            target_level,
            target_experience,
        )
        offered = _wait_for(
            pipe,
            lambda row: (
                row["offer.valid"]
                and row["offer.target"] == args.participant_id
                and row["offer.option_count"] > 0
                and row["wait.pause_active"]
            ),
            timeout=10.0,
            label="owner level-up offer and wait barrier",
        )
        result["ownerOffer"] = offered
        during_choice = _wait_for(
            pipe,
            lambda row: (
                row["offer.valid"]
                and row["wait.pause_active"]
                and not row["bot.choice_pending"]
                and row["brain.skill_choices_accepted"]
                > before["brain.skill_choices_accepted"]
            ),
            timeout=10.0,
            label="participant-owned bot choice during owner picker",
        )
        time.sleep(args.choice_delay)
        during_choice = _probe(pipe)
        result["duringOwnerChoice"] = during_choice
        result["boundaryManaPrime"] = _set_bot_mana(
            pipe,
            int(during_choice["bot.progression"]),
            BOUNDARY_CURRENT_MP,
            BOUNDARY_MAX_MP,
        )
        result["ownerChoice"] = _choose_owner_offer(
            pipe,
            int(offered["offer.id"]),
        )
        cleared = _wait_for(
            pipe,
            lambda row: not row["offer.valid"] and not row["wait.pause_active"],
            timeout=10.0,
            label="owner level-up barrier clear",
        )
        result["afterOwnerChoice"] = cleared
        result["survivalProtectionAfterLevelUp"] = _protect_participants(
            pipe,
            bot_id,
        )
        baseline_casts = int(cleared["brain.cast_accepted"])
        baseline_ticks = int(cleared["simulation_tick_count"])
        post = _sample_combat(
            pipe,
            bot_id=bot_id,
            baseline_casts=baseline_casts,
            baseline_ticks=baseline_ticks,
            timeout=args.post_choice_timeout,
            stop_on_continuity=args.expect == "continuity",
        )
        result["postChoiceCombat"] = post
        if post["final"].get("bot.choice_pending"):
            raise BotLevelUpContinuityFailure(
                f"bot choice remained pending after combat resumed: {post['final']}"
            )
        if int(post["final"].get("brain.skill_choices_accepted", 0)) <= int(
            before["brain.skill_choices_accepted"]
        ):
            raise BotLevelUpContinuityFailure(
                f"bot did not accept its participant-owned choice: {post['final']}"
            )
        probes = [row["probe"] for row in post["samples"]]
        result["boundaryAssessment"] = {
            "expected": args.expect,
            "wedgeObserved": _wedge_observed(
                post,
                baseline_casts=baseline_casts,
                baseline_ticks=baseline_ticks,
            ),
            "continuityObserved": post["ok"],
            "nativeReserveObserved": any(
                row["bot.mana_reserve_active"] for row in probes
            ),
            "luaHoldObserved": any(
                row["brain.mana_cast_hold"] for row in probes
            ),
            "luaHoldCleared": bool(probes) and not bool(
                probes[-1]["brain.mana_cast_hold"]
            ),
            "nativeReserveCleared": bool(probes) and not bool(
                probes[-1]["bot.mana_reserve_active"]
            ),
            "ownerOfferCleared": not bool(post["final"].get("offer.valid")),
            "ownerBarrierCleared": not bool(
                post["final"].get("wait.pause_active")
            ),
        }
        assessment = result["boundaryAssessment"]
        if args.expect == "wedge" and not assessment["wedgeObserved"]:
            raise BotLevelUpContinuityFailure(
                "the exact 10% pre-fix mana wedge was not reproduced: "
                f"{assessment}; final={post['final']}"
            )
        if args.expect == "continuity" and not (
            assessment["continuityObserved"]
            and assessment["nativeReserveObserved"]
            and assessment["luaHoldObserved"]
            and assessment["luaHoldCleared"]
            and assessment["nativeReserveCleared"]
        ):
            raise BotLevelUpContinuityFailure(
                "the Lua teammate did not recover and fight through the exact "
                f"10% boundary: {assessment}; final={post['final']}"
            )
        result["ok"] = True
    except BaseException as exc:
        primary_error = exc
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        if process_id <= 0:
            process_id = _ledger_process_id(ledger)
        cleanup: dict[str, Any] = {}
        if process_id > 0:
            try:
                cleanup["processStop"] = _stop_exact_process(
                    ps,
                    process_id,
                    expected_executable,
                )
            except BaseException as exc:
                cleanup["processStopError"] = f"{type(exc).__name__}: {exc}"
                result["ok"] = False
        try:
            cleanup["runtimeArtifacts"] = _copy_runtime_artifacts(
                runtime_root,
                args.instance,
                args.evidence_root,
            )
        except BaseException as exc:
            cleanup["artifactError"] = f"{type(exc).__name__}: {exc}"
            result["ok"] = False
        staging_root = args.evidence_root / "staging"
        if staging_root.is_dir():
            shutil.rmtree(staging_root)
            cleanup["stagingDeleted"] = str(staging_root)
        after_ports = port_inventory(ps, ports)
        after_process = (
            [
                asdict(row)
                for row in windows_processes(ps)
                if row.pid == process_id
            ]
            if process_id > 0
            else []
        )
        write_json(
            args.evidence_root / "safety" / "after.json",
            {
                "utcNanoseconds": time.time_ns(),
                "reservedPorts": after_ports,
                "ownedProcess": after_process,
            },
        )
        if after_ports or after_process:
            cleanup["residualPorts"] = after_ports
            cleanup["residualProcess"] = after_process
            result["ok"] = False
        result["cleanup"] = cleanup
        if primary_error is None and not result["ok"]:
            result["error"] = {
                "type": "CleanupFailure",
                "message": "acceptance passed but exact cleanup failed",
            }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--game-directory", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--instance", default="botlevel-host")
    parser.add_argument("--local-port", type=int, default=52741)
    parser.add_argument("--unused-remote-port", type=int, default=52742)
    parser.add_argument("--run-seed", type=lambda value: int(value, 0), default=0xB071E5)
    parser.add_argument(
        "--participant-id",
        type=lambda value: int(value, 0),
        default=76561198120430463,
    )
    parser.add_argument("--expect", choices=("wedge", "continuity"), required=True)
    parser.add_argument("--bot-mana", type=float, default=1000.0)
    parser.add_argument("--baseline-timeout", type=float, default=30.0)
    parser.add_argument("--choice-delay", type=float, default=1.0)
    parser.add_argument("--post-choice-timeout", type=float, default=20.0)
    args = parser.parse_args()
    args.package_root = args.package_root.resolve()
    args.game_directory = args.game_directory.resolve()
    args.evidence_root = args.evidence_root.resolve()
    if args.evidence_root.exists():
        parser.error("evidence root must be new")
    if not (args.package_root / "launcher" / "SolomonDarkModLauncher.exe").is_file():
        parser.error("package root is missing the desktop launcher")
    if not (args.game_directory / "SolomonDark.exe").is_file():
        parser.error("game directory is missing SolomonDark.exe")
    if not args.instance.startswith("botlevel-"):
        parser.error("instance must use botlevel- prefix")
    if (
        args.local_port == args.unused_remote_port
        or min(args.local_port, args.unused_remote_port) < 51400
    ):
        parser.error("ports must be distinct and at or above 51400")
    return args


def main() -> int:
    args = parse_args()
    actual_sha = _git_sha()
    if actual_sha != args.expected_source_sha.lower():
        raise SystemExit(
            "source SHA changed: "
            f"expected={args.expected_source_sha.lower()} actual={actual_sha}"
        )
    args.evidence_root.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "sourceSha": actual_sha,
        "instance": args.instance,
        "ports": [args.local_port, args.unused_remote_port],
        "transportParticipantId": args.participant_id,
        "expectedOutcome": args.expect,
        "audioDisabledRequired": True,
        "forceOrder": "bot-native-sync-then-owner-offer-without-runtime-tick",
    }
    _run_live(args, result)
    write_json(args.evidence_root / "result.json", result)
    write_manifest(args.evidence_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
