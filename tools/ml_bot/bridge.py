"""Exact-process headless game bridge for live bot-policy training."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence

from owned_process_ledger import (
    OwnedProcessError,
    register_owned_launch,
    stop_owned_process_ids,
)
import verify_local_multiplayer_sync as local_sync

from . import spec
from .compositions import TeamComposition, build_roster
from .model import BotPolicy, render_lua_weights
from .waves import start_stock_wave_episode as route_stock_wave_episode

ROOT = Path(__file__).resolve().parents[2]
# The native Lua-exec pipe rejects responses above 1 MiB. Sixteen worst-case
# finite 1333-value main rows stay below half that ceiling after JSON framing.
MAX_ROLLOUTS_PER_RESPONSE = 16
# A choice interval also carries up to sixteen 56-value option rows and a
# variable reward sequence. Drain one complete interval per response so team
# size never multiplies that payload inside one pipe frame.
MAX_CHOICE_ROLLOUTS_PER_RESPONSE = 1
POLICY_LOAD_CHUNK_BYTES = 512 * 1024
RUN_READY_STABILITY_SECONDS = 0.35
BOT_MATERIALIZATION_GRACE_SECONDS = 15.0
# One integer XP point is sufficient to prove that a confirmed stock-wave kill
# reached the learned participant through shared progression. Requiring a
# level or choice here would measure bootstrap-policy competence, not
# integration.
WAVE_INTEGRATION_MIN_EXPERIENCE_DELTA = 1
# The opt-in acceptance proof is intentionally stricter: it must observe one
# natural level transition and one pending/accepted learned choice event.
NATURAL_CHOICE_PROOF_MIN_LEVEL_DELTA = 1
NATURAL_CHOICE_PROOF_MIN_EVENT_DELTA = 1
WAVE_PROGRESSION_POLL_INTERVAL_SECONDS = 0.2
# Shared progression also levels the trainer-owned slot-0 participant. Its
# stock picker holds the simulation barrier until answered, so the headless
# harness selects the first native-valid option for that non-learned owner.
# This never enters either learned choice stream or supplies a scripted label.
TRAINING_OWNER_LEVEL_UP_RESOLVE_TIMEOUT_SECONDS = 10.0
TRAINING_OWNER_LEVEL_UP_POLL_INTERVAL_SECONDS = 0.05
PRIMARY_ENTRY_BY_ELEMENT = {
    "fire": 0x10,
    "water": 0x20,
    "earth": 0x28,
    "air": 0x18,
    "ether": 0x08,
}
TRAINING_SECONDARY_ENTRY_BY_ELEMENT = {
    "fire": 21,
    "water": 35,
    "earth": 41,
    "air": 27,
    "ether": 11,
}
SOLO_LAUNCHER = ROOT / "scripts" / "Launch-LocalSoloSession.ps1"
DEFAULT_LAUNCHER = (
    ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
)
if os.name == "nt":
    DEFAULT_GAME_DIRECTORY = Path(
        "C:/Users/User/Documents/GitHub/SB Modding/"
        "Solomon Dark/SolomonDarkAbandonware"
    )
else:
    DEFAULT_GAME_DIRECTORY = Path(
        "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
        "Solomon Dark/SolomonDarkAbandonware"
    )


class BridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RolloutRecord:
    trajectory_version: int
    episode_id: int
    participant_id: int
    simulation_tick: int
    observation: list[float]
    movement_mask: list[bool]
    target_mask: list[bool]
    ability_mask: list[bool]
    aim_mask: list[bool]
    movement_action: int
    target_action: int
    ability_action: int
    aim_action: int
    old_log_probability: float
    old_value: float
    reward: float
    done: bool


@dataclass(frozen=True)
class ChoiceRolloutRecord:
    choice_trajectory_version: int
    episode_id: int
    participant_id: int
    generation: int
    simulation_tick: int
    observation: list[float]
    option_descriptors: list[list[float]]
    option_mask: list[bool]
    selected_option: int
    old_log_probability: float
    old_value: float
    next_value: float
    duration_steps: int
    rewards: list[float]
    done: bool
    choice_mode: str
    trainable: bool
    accepted: bool


def _path_for_powershell(path: Path) -> str:
    resolved = path.resolve()
    if os.name == "nt":
        return str(resolved)
    completed = subprocess.run(
        ["wslpath", "-w", str(resolved)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    converted = completed.stdout.strip()
    if completed.returncode != 0 or not converted:
        raise BridgeError(
            f"could not convert path for PowerShell: {path}: "
            f"{completed.stderr.strip()}"
        )
    return converted


def _local_path(path: str) -> Path:
    if os.name == "nt":
        return Path(path)
    completed = subprocess.run(
        ["wslpath", "-u", path],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    converted = completed.stdout.strip()
    if completed.returncode != 0 or not converted:
        raise BridgeError(f"could not convert Windows path: {path}")
    return Path(converted)


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _lua_long_string(value: str) -> str:
    for equals_count in range(1, 17):
        equals = "=" * equals_count
        closing = f"]{equals}]"
        if closing not in value:
            return f"[{equals}[{value}{closing}"
    raise BridgeError("could not delimit policy chunk as a Lua string")


def _bits(value: str, expected: int, label: str) -> list[bool]:
    if len(value) != expected or any(bit not in "01" for bit in value):
        raise BridgeError(f"invalid {label} bit mask: {value!r}")
    return [bit == "1" for bit in value]


def _floats(value: str, expected: int, label: str) -> list[float]:
    try:
        result = [float(item) for item in value.split(",")]
    except ValueError as error:
        raise BridgeError(f"invalid {label} vector") from error
    if len(result) != expected:
        raise BridgeError(
            f"{label} vector has {len(result)} entries, expected {expected}"
        )
    if not all(math.isfinite(item) for item in result):
        raise BridgeError(f"{label} vector contains a non-finite value")
    return result


def _float_rows(value: str, expected_columns: int) -> list[list[float]]:
    if not value:
        raise BridgeError("choice option descriptors are empty")
    rows = [
        _floats(row, expected_columns, "choice option descriptor")
        for row in value.split(";")
    ]
    if len(rows) > spec.MAX_CHOICE_OPTIONS:
        raise BridgeError("choice option count exceeds the v3 bound")
    return rows


def _participant_ids(value: str) -> tuple[int, ...]:
    if not value:
        return ()
    try:
        result = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise BridgeError(
            f"invalid participant id list: {value!r}"
        ) from error
    if any(item <= 0 for item in result) or len(set(result)) != len(result):
        raise BridgeError(f"invalid participant id list: {value!r}")
    return result


def parse_rollout_output(
    output: str,
    *,
    expected_count: int,
) -> list[RolloutRecord]:
    records: list[RolloutRecord] = []
    for line in output.splitlines():
        if not line.startswith("R\t"):
            continue
        fields = line.split("\t")
        if len(fields) != 18:
            raise BridgeError(
                f"rollout frame has {len(fields)} fields"
            )
        if fields[12] not in ("0", "1"):
            raise BridgeError("rollout done flag must be 0 or 1")
        try:
            record = RolloutRecord(
                trajectory_version=int(fields[1]),
                episode_id=int(fields[2]),
                participant_id=int(fields[3]),
                simulation_tick=int(fields[4]),
                movement_action=int(fields[5]),
                target_action=int(fields[6]),
                ability_action=int(fields[7]),
                aim_action=int(fields[8]),
                old_log_probability=float(fields[9]),
                old_value=float(fields[10]),
                reward=float(fields[11]),
                done=fields[12] == "1",
                observation=_floats(
                    fields[13],
                    len(spec.OBSERVATION_NAMES),
                    "observation",
                ),
                movement_mask=_bits(
                    fields[14],
                    len(spec.MOVEMENT_ACTION_NAMES),
                    "movement",
                ),
                target_mask=_bits(
                    fields[15],
                    len(spec.TARGET_ACTION_NAMES),
                    "target",
                ),
                ability_mask=_bits(
                    fields[16],
                    len(spec.ABILITY_ACTION_NAMES),
                    "ability",
                ),
                aim_mask=_bits(
                    fields[17],
                    len(spec.AIM_ACTION_NAMES),
                    "aim",
                ),
            )
        except ValueError as error:
            raise BridgeError("rollout frame contains an invalid number") from error
        if record.trajectory_version != spec.TRAJECTORY_VERSION:
            if record.trajectory_version in (1, 2, 3):
                raise BridgeError(
                    "trajectory-v1/v2/v3 frames are incompatible with the "
                    "strict trajectory-v4 bridge"
                )
            raise BridgeError(
                "rollout trajectory version does not match trajectory-v4"
            )
        if not (
            math.isfinite(record.old_log_probability)
            and math.isfinite(record.old_value)
            and math.isfinite(record.reward)
        ):
            raise BridgeError("rollout frame contains a non-finite scalar")
        if not 0 <= record.movement_action < len(spec.MOVEMENT_ACTION_NAMES):
            raise BridgeError("rollout movement action is outside the policy head")
        if not 0 <= record.target_action < len(spec.TARGET_ACTION_NAMES):
            raise BridgeError("rollout target action is outside the policy head")
        if not 0 <= record.ability_action < len(spec.ABILITY_ACTION_NAMES):
            raise BridgeError("rollout ability action is outside the policy head")
        if not 0 <= record.aim_action < len(spec.AIM_ACTION_NAMES):
            raise BridgeError("rollout aim action is outside the policy head")
        if not record.movement_mask[record.movement_action]:
            raise BridgeError("rollout selected a masked movement action")
        if not record.target_mask[record.target_action]:
            raise BridgeError("rollout selected a masked target action")
        if not record.ability_mask[record.ability_action]:
            raise BridgeError("rollout selected a masked ability action")
        if not record.aim_mask[record.aim_action]:
            raise BridgeError("rollout selected a masked aim action")
        records.append(record)
    if len(records) != expected_count:
        raise BridgeError(
            f"drained {len(records)} rollouts, expected {expected_count}"
        )
    return records


def parse_choice_rollout_output(
    output: str,
    *,
    expected_count: int,
) -> list[ChoiceRolloutRecord]:
    records: list[ChoiceRolloutRecord] = []
    for line in output.splitlines():
        if not line.startswith("C\t"):
            continue
        fields = line.split("\t")
        if len(fields) != 19:
            raise BridgeError(
                f"choice rollout frame has {len(fields)} fields"
            )
        if any(fields[index] not in ("0", "1") for index in (11, 12, 13)):
            raise BridgeError("choice rollout flags must be 0 or 1")
        try:
            descriptors = _float_rows(
                fields[17], len(spec.OPTION_DESCRIPTOR_NAMES)
            )
            rewards = (
                []
                if fields[18] == ""
                else _floats(
                    fields[18], int(fields[10]), "choice rewards"
                )
            )
            record = ChoiceRolloutRecord(
                choice_trajectory_version=int(fields[1]),
                episode_id=int(fields[2]),
                participant_id=int(fields[3]),
                generation=int(fields[4]),
                simulation_tick=int(fields[5]),
                selected_option=int(fields[6]),
                old_log_probability=float(fields[7]),
                old_value=float(fields[8]),
                next_value=float(fields[9]),
                duration_steps=int(fields[10]),
                done=fields[11] == "1",
                trainable=fields[12] == "1",
                accepted=fields[13] == "1",
                choice_mode=fields[14],
                observation=_floats(
                    fields[15], len(spec.OBSERVATION_NAMES), "observation"
                ),
                option_mask=_bits(
                    fields[16], len(descriptors), "choice option"
                ),
                option_descriptors=descriptors,
                rewards=rewards,
            )
        except ValueError as error:
            raise BridgeError(
                "choice rollout frame contains an invalid number"
            ) from error
        if record.choice_trajectory_version != spec.CHOICE_TRAJECTORY_VERSION:
            if record.choice_trajectory_version in (1, 2, 3):
                raise BridgeError(
                    "choice trajectory-v1/v2/v3 is incompatible with the "
                    "strict choice-event-v4 bridge"
                )
            raise BridgeError("choice rollout version does not match v4")
        if record.choice_mode not in ("learned", "scripted"):
            raise BridgeError("choice rollout mode is invalid")
        if record.duration_steps < 0 or len(record.rewards) != record.duration_steps:
            raise BridgeError("choice rollout duration/reward count mismatch")
        if not all(
            math.isfinite(value)
            for value in (
                record.old_log_probability,
                record.old_value,
                record.next_value,
                *record.rewards,
            )
        ):
            raise BridgeError("choice rollout contains a non-finite scalar")
        if not 0 <= record.selected_option < len(record.option_mask):
            raise BridgeError("choice selected option is outside its offer")
        if not record.option_mask[record.selected_option]:
            raise BridgeError("choice selected a masked option")
        if record.trainable != (record.choice_mode == "learned"):
            raise BridgeError("choice trainable flag disagrees with mode")
        records.append(record)
    if len(records) != expected_count:
        raise BridgeError(
            f"drained {len(records)} choice rollouts, expected {expected_count}"
        )
    return records


GOD_MODE = r"""
local hp_offset = assert(
  sd.debug.layout_offset('progression_hp'))
local max_hp_offset = assert(
  sd.debug.layout_offset('progression_max_hp'))
local mp_offset = assert(
  sd.debug.layout_offset('progression_mp'))
local max_mp_offset = assert(
  sd.debug.layout_offset('progression_max_mp'))

local function sustain_progression(progression)
  progression = tonumber(progression) or 0
  if progression == 0 then
    return 0
  end
  local max_hp = tonumber(
    sd.debug.read_float(progression + max_hp_offset)) or 0
  local max_mp = tonumber(
    sd.debug.read_float(progression + max_mp_offset)) or 0
  if max_hp > 0 then
    sd.debug.write_float(progression + hp_offset, max_hp)
  end
  if max_mp > 0 then
    sd.debug.write_float(progression + mp_offset, max_mp)
  end
  return 1
end

local function sustain()
  local count = 0
  local player = sd.player.get_state()
  if type(player) == 'table' then
    local progression =
      tonumber(player.progression_address) or 0
    if progression == 0 then
      local actor = tonumber(player.actor_address) or 0
      local actor_offset = tonumber(
        sd.debug.layout_offset(
          'actor_progression_runtime_state')) or 0
      if actor ~= 0 and actor_offset ~= 0 then
        progression =
          tonumber(sd.debug.read_ptr(actor + actor_offset)) or 0
      end
    end
    count = count + sustain_progression(progression)
  end
  for _, bot in ipairs(sd.bots.list()) do
    local participant_id = bot:participant_id()
    local state = sd.bots.get_participant_state(participant_id)
    if type(state) == 'table' then
      count = count + sustain_progression(
        state.progression_runtime_state_address)
    end
  end
  return count
end
if not _G.__sdmod_ml_training_godmode then
  local last_tick = -10
  sd.events.on('runtime.tick', function(event)
    local tick = type(event) == 'table' and
      tonumber(event.tick_count) or 0
    if tick <= 0 or tick - last_tick >= 10 then
      last_tick = tick
      sustain()
    end
  end)
  _G.__sdmod_ml_training_godmode = true
end
print('registered=true')
print('initial_apply=' .. tostring(sustain()))
"""


STATUS = r"""
local training = assert(
  rawget(_G, 'bot_policy_training'),
  'bot policy training API is unavailable')
local status = training.status()
local debug = rawget(_G, 'bot_brain_debug') or {}
print('enabled=' .. tostring(status.enabled))
print('episode_id=' .. tostring(status.episode_id or 0))
print('capacity=' .. tostring(status.capacity or 0))
print('buffered=' .. tostring(status.buffered or 0))
print('dropped=' .. tostring(status.dropped or 0))
print('recorded=' .. tostring(status.recorded or 0))
print('choice_buffered=' .. tostring(
  status.choice_buffered or 0))
print('choice_dropped=' .. tostring(
  status.choice_dropped or 0))
print('choice_recorded=' .. tostring(
  status.choice_recorded or 0))
print('scripted_choice_excluded=' .. tostring(
  status.scripted_choice_excluded or 0))
print('generation=' .. tostring(
  status.policy and status.policy.generation or 0))
print('clock_source=' .. tostring(debug.clock_source or ''))
print('simulation_tick=' .. tostring(
  debug.simulation_tick_count or 0))
print('active_bot_count=' .. tostring(
  debug.active_bot_count or 0))
print('behavior=' .. tostring(debug.behavior or ''))
print('policy_decision_count=' .. tostring(
  debug.policy_decision_count or 0))
print('move_accepted=' .. tostring(debug.move_accepted or 0))
print('cast_accepted=' .. tostring(debug.cast_accepted or 0))
local learned_ids = {}
local learned_count = 0
local learned_skill_choices_seen = 0
local learned_skill_choices_accepted = 0
local last_skill_choice_generation = 0
local last_skill_choice_option_id = -1
for _, row in ipairs(debug.bots or {}) do
  if tostring(row.behavior or '') == 'learned' and
      (tonumber(row.participant_id) or 0) > 0 then
    learned_count = learned_count + 1
    learned_ids[#learned_ids + 1] =
      tostring(row.participant_id)
    learned_skill_choices_seen =
      learned_skill_choices_seen +
      (tonumber(row.skill_choices_seen) or 0)
    learned_skill_choices_accepted =
      learned_skill_choices_accepted +
      (tonumber(row.skill_choices_accepted) or 0)
    local generation =
      tonumber(row.skill_choice_generation) or 0
    if generation >= last_skill_choice_generation then
      last_skill_choice_generation = generation
      last_skill_choice_option_id =
        tonumber(row.skill_choice_option_id) or -1
    end
  end
end
print('learned_bot_count=' .. tostring(learned_count))
print('learned_participant_ids=' ..
  table.concat(learned_ids, ','))
print('learned_skill_choices_seen=' .. tostring(
  learned_skill_choices_seen))
print('learned_skill_choices_accepted=' .. tostring(
  learned_skill_choices_accepted))
print('last_skill_choice_generation=' .. tostring(
  last_skill_choice_generation))
print('last_skill_choice_option_id=' .. tostring(
  last_skill_choice_option_id))
local multiplayer = sd.runtime.get_multiplayer_state() or {}
local local_participant_id = 0
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.is_owner == true then
    local_participant_id =
      tonumber(participant.participant_id) or 0
    break
  end
end
local offer = multiplayer.active_level_up_offer or {}
local level_up_wait = multiplayer.level_up_wait_status or {}
print('local_participant_id=' .. tostring(local_participant_id))
print('level_up_pause_active=' .. tostring(
  level_up_wait.pause_active == true))
print('level_up_offer_valid=' .. tostring(offer.valid == true))
print('level_up_offer_submitted=' .. tostring(
  offer.selection_submitted == true))
print('level_up_offer_id=' .. tostring(offer.offer_id or 0))
print('level_up_offer_authority=' .. tostring(
  offer.authority_participant_id or 0))
print('level_up_offer_target=' .. tostring(
  offer.target_participant_id or 0))
print('level_up_offer_option_count=' .. tostring(
  offer.option_count or 0))
"""

RUN_READY_STATUS = r"""
local scene = sd.world.get_scene()
local multiplayer = sd.runtime.get_multiplayer_state() or {}
local loading = multiplayer.run_loading_barrier or {}
local handles = sd.bots.list() or {}
local debug = rawget(_G, 'bot_brain_debug') or {}
local members = {}
for _, participant in ipairs(multiplayer.participants or {}) do
  members[tonumber(participant.participant_id) or 0] =
    participant
end
local position_count = 0
local hp_count = 0
local alive_count = 0
local slot_count = 0
local member_in_run_count = 0
local member_runtime_valid_count = 0
local lua_brain_member_count = 0
local participant_ids = {}
for _, bot in ipairs(handles) do
  local participant_id =
    tonumber(bot:participant_id()) or 0
  participant_ids[#participant_ids + 1] =
    tostring(participant_id)
  local ok, x, y = pcall(function()
    return bot:position()
  end)
  if ok and tonumber(x) ~= nil and tonumber(y) ~= nil then
    position_count = position_count + 1
  end
  local hp_call_ok, hp = pcall(function()
    return bot:hp()
  end)
  local max_hp_call_ok, max_hp = pcall(function()
    return bot:max_hp()
  end)
  if hp_call_ok and tonumber(hp) ~= nil and
      max_hp_call_ok and (tonumber(max_hp) or 0) > 0 then
    hp_count = hp_count + 1
  end
  local alive_call_ok, alive = pcall(function()
    return bot:alive()
  end)
  if alive_call_ok and alive == true then
    alive_count = alive_count + 1
  end
  local slot_call_ok, slot = pcall(function()
    return bot:slot()
  end)
  slot = tonumber(slot) or -1
  if slot_call_ok and slot >= 1 then
    slot_count = slot_count + 1
  end
  local member = members[participant_id]
  if member and member.in_run == true then
    member_in_run_count = member_in_run_count + 1
  end
  if member and member.runtime_valid == true then
    member_runtime_valid_count =
      member_runtime_valid_count + 1
  end
  if member and
      tostring(member.controller_kind or '') == 'LuaBrain' then
    lua_brain_member_count = lua_brain_member_count + 1
  end
end
local learned_count = 0
local learned_ids = {}
for _, row in ipairs(debug.bots or {}) do
  if tostring(row.behavior or '') == 'learned' and
      (tonumber(row.participant_id) or 0) > 0 then
    learned_count = learned_count + 1
    learned_ids[#learned_ids + 1] =
      tostring(row.participant_id)
  end
end
print('scene=' .. tostring(
  scene and (scene.name or scene.kind) or ''))
print('session_state=' .. tostring(
  multiplayer.session_state or ''))
print('loading_active=' .. tostring(loading.active or false))
print('loading_released=' .. tostring(
  loading.released or false))
print('loading_timed_out=' .. tostring(
  loading.timed_out or false))
print('loading_run_nonce=' .. tostring(
  loading.run_nonce or 0))
print('loading_release_reason=' .. tostring(
  loading.release_reason or ''))
print('loading_expected=' .. tostring(
  loading.expected_participant_count or 0))
print('loading_ready=' .. tostring(
  loading.ready_participant_count or 0))
print('bot_count=' .. tostring(#handles))
print('bot_position_count=' .. tostring(position_count))
print('bot_hp_count=' .. tostring(hp_count))
print('bot_alive_count=' .. tostring(alive_count))
print('bot_slot_count=' .. tostring(slot_count))
print('member_in_run_count=' ..
  tostring(member_in_run_count))
print('member_runtime_valid_count=' ..
  tostring(member_runtime_valid_count))
print('lua_brain_member_count=' ..
  tostring(lua_brain_member_count))
print('participant_ids=' ..
  table.concat(participant_ids, ','))
print('learned_bot_count=' .. tostring(learned_count))
print('learned_participant_ids=' ..
  table.concat(learned_ids, ','))
"""

TRAINING_ARENA_MANAGER = r"""
local config =
  rawget(_G, '__sdmod_ml_training_arena_config') or {}
local enemy_type_id =
  tonumber(config.enemy_type_id) or 1001
local enemy_hp = tonumber(config.enemy_hp) or 750.0
local spawn_distance =
  tonumber(config.spawn_distance) or 260.0

local function live_enemy_count()
  local count = 0
  for _, actor in ipairs(sd.world.list_actors() or {}) do
    if actor.tracked_enemy == true and
        actor.dead ~= true and
        (tonumber(actor.hp) or 0) > 0.05 then
      count = count + 1
    end
  end
  return count
end

local function bot_position()
  local bot = (sd.bots.list() or {})[1]
  if bot == nil then
    return nil
  end
  local ok, x, y = pcall(function()
    return bot:position()
  end)
  if not ok then
    return nil
  end
  x, y = tonumber(x), tonumber(y)
  if x == nil or y == nil then
    return nil
  end
  return x, y
end

local manager = rawget(_G, '__sdmod_ml_training_arena')
if type(manager) ~= 'table' then
  manager = {
    pending_request_id = 0,
    spawn_count = 0,
    failed_spawn_count = 0,
    last_error = '',
    last_tick = -25,
  }
  _G.__sdmod_ml_training_arena = manager

  sd.events.on('runtime.tick', function(event)
    local tick = type(event) == 'table' and
      tonumber(event.tick_count) or 0
    if tick > 0 and tick - manager.last_tick < 25 then
      return
    end
    manager.last_tick = tick

    if manager.pending_request_id > 0 then
      local result = sd.gameplay.get_last_manual_run_enemy_spawn(
        manager.pending_request_id)
      if type(result) ~= 'table' then
        return
      end
      if result.ok == true then
        local actor = tonumber(result.actor_address) or 0
        if actor > 0 then
          sd.gameplay.set_run_enemy_health(
            actor,
            enemy_hp,
            enemy_hp)
        end
        manager.spawn_count = manager.spawn_count + 1
      else
        manager.failed_spawn_count =
          manager.failed_spawn_count + 1
        manager.last_error = tostring(result.error or '')
      end
      manager.pending_request_id = 0
    end

    if live_enemy_count() > 0 or
        manager.pending_request_id > 0 then
      return
    end
    local x, y = bot_position()
    if x == nil then
      return
    end
    local ok, spawn_error, request_id =
      sd.gameplay.spawn_manual_run_enemy({
        type_id = enemy_type_id,
        x = x + spawn_distance,
        y = y,
        freeze_on_spawn = false,
        allow_direct_arena_spawn = true,
      })
    if ok == true then
      manager.pending_request_id = tonumber(request_id) or 0
    else
      manager.failed_spawn_count =
        manager.failed_spawn_count + 1
      manager.last_error = tostring(spawn_error or '')
    end
  end)
end
print('registered=true')
print('spawn_count=' .. tostring(manager.spawn_count or 0))
print('failed_spawn_count=' ..
  tostring(manager.failed_spawn_count or 0))
print('last_error=' .. tostring(manager.last_error or ''))
"""

TRAINING_ARENA_STATUS = r"""
local live = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if actor.tracked_enemy == true and
      actor.dead ~= true and
      (tonumber(actor.hp) or 0) > 0.05 then
    live = live + 1
  end
end
print('live_enemy_count=' .. tostring(live))
local manager = rawget(_G, '__sdmod_ml_training_arena') or {}
print('pending_request_id=' ..
  tostring(manager.pending_request_id or 0))
print('spawn_count=' .. tostring(manager.spawn_count or 0))
print('failed_spawn_count=' ..
  tostring(manager.failed_spawn_count or 0))
print('last_error=' .. tostring(manager.last_error or ''))
"""


class SoloSession:
    def __init__(
        self,
        *,
        instance: str,
        game_directory: Path = DEFAULT_GAME_DIRECTORY,
        launcher_path: Path = DEFAULT_LAUNCHER,
        runtime_root: Path | None = None,
        local_port: int = 49780,
        unused_remote_port: int = 49781,
        max_participants: int,
        headless: bool = True,
        element: str = "fire",
        discipline: str = "arcane",
        boneyard_override: Path | None = None,
        multiplayer_transport: bool = True,
        weld_preference: str = "auto",
        episode_mode: str = "curriculum",
        fresh_install: bool | None = None,
    ) -> None:
        self.instance = instance
        self.game_directory = game_directory
        self.launcher_path = launcher_path
        self.runtime_root = runtime_root or ROOT / "runtime"
        self.local_port = local_port
        self.unused_remote_port = unused_remote_port
        if max_participants < 2:
            raise ValueError("max_participants must include an owner and bot")
        self.max_participants = max_participants
        self.headless = headless
        self.element = element
        self.discipline = discipline
        self.boneyard_override = boneyard_override
        self.multiplayer_transport = multiplayer_transport
        self.weld_preference = weld_preference
        if episode_mode not in {"waves", "curriculum"}:
            raise ValueError("episode_mode must be waves or curriculum")
        self.episode_mode = episode_mode
        self.fresh_install = (
            episode_mode == "curriculum"
            if fresh_install is None
            else fresh_install
        )
        if episode_mode == "waves" and self.fresh_install:
            raise ValueError(
                "waves episodes require an isolated temporary profile"
            )
        self.pipe_name = f"SolomonDarkModLoader_LuaExec_{instance}"
        self.launch_result: dict[str, Any] | None = None
        self.process_ids: list[int] = []
        self.launch_wrapper_process: subprocess.Popen[bytes] | None = None
        self.training_owner_level_up_choices: list[dict[str, int]] = []

    @property
    def stage_root(self) -> Path:
        return (
            self.runtime_root
            / "instances"
            / self.instance.lower()
            / "stage"
        )

    @property
    def settings_path(self) -> Path:
        return (
            self.stage_root
            / ".sdmod"
            / "mod-settings"
            / "bot.brain.json"
        )

    @property
    def staged_boneyard_path(self) -> Path:
        return self.stage_root / "data" / "levels" / "survival.boneyard"

    def layout_sha256(self) -> str:
        if self.launch_result is None:
            raise BridgeError("session is not launched")
        path = self.staged_boneyard_path
        if not path.is_file():
            raise BridgeError(f"staged boneyard does not exist: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        published = str(
            self.launch_result.get("stagedBoneyardSha256", "")
        ).lower()
        if published != digest:
            raise BridgeError(
                "launcher and bridge disagree on the staged boneyard hash"
            )
        if self.boneyard_override is not None:
            requested = hashlib.sha256(
                self.boneyard_override.read_bytes()
            ).hexdigest()
            published_requested = str(
                self.launch_result.get(
                    "requestedBoneyardSha256",
                    "",
                )
            ).lower()
            if published_requested != requested or digest != requested:
                raise BridgeError(
                    "requested and staged boneyard hashes do not match"
                )
        return digest

    def _rescue_partial(self, ledger_path: Path) -> None:
        if not ledger_path.is_file():
            return
        try:
            document = json.loads(
                ledger_path.read_text(encoding="utf-8-sig")
            )
            process_id = int(document.get("processId", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        if process_id <= 0:
            return
        launch = {
            "processId": process_id,
            "instance": self.instance,
            "executablePath": _path_for_powershell(
                self.stage_root / "SolomonDark.exe"
            ),
        }
        try:
            register_owned_launch(
                launch,
                validate=True,
                require_processes=False,
            )
            stop_owned_process_ids([process_id])
        except OwnedProcessError:
            pass

    def _reap_launch_wrapper(self) -> None:
        process = self.launch_wrapper_process
        self.launch_wrapper_process = None
        if process is None:
            return
        try:
            process.wait(timeout=5.0)
            return
        except subprocess.TimeoutExpired:
            process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)

    def launch(self) -> dict[str, Any]:
        if self.launch_result is not None:
            raise BridgeError("session is already launched")
        if not self.game_directory.is_dir():
            raise BridgeError(
                f"game directory does not exist: {self.game_directory}"
            )
        if not self.launcher_path.is_file():
            raise BridgeError(
                f"launcher does not exist: {self.launcher_path}"
            )
        if (
            self.boneyard_override is not None
            and not self.boneyard_override.is_file()
        ):
            raise BridgeError(
                "boneyard override does not exist: "
                f"{self.boneyard_override}"
            )
        if self.weld_preference not in {"auto", "prefer", "avoid"}:
            raise BridgeError(
                "weld preference must be auto, prefer, or avoid"
            )

        ledger_path = (
            self.runtime_root
            / f".ml-bot-launch-{self.instance}-{os.getpid()}.json"
        )
        result_path = (
            self.runtime_root
            / f".ml-bot-result-{self.instance}-{os.getpid()}.json"
        )
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        arguments = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            _path_for_powershell(SOLO_LAUNCHER),
            "-Instance",
            self.instance,
            "-Preset",
            (
                "idle"
                if self.episode_mode == "waves"
                else f"map_create_{self.element}_{self.discipline}_hub"
            ),
            "-RuntimeRoot",
            _path_for_powershell(self.runtime_root),
            "-LocalPort",
            str(self.local_port),
            "-UnusedRemotePort",
            str(self.unused_remote_port),
            "-MaxParticipants",
            str(self.max_participants),
            "-ParticipantId",
            "0x2000000000002A01",
            "-PlayerName",
            "ML Trainer",
            "-GameDirectory",
            _path_for_powershell(self.game_directory),
            "-LauncherPath",
            _path_for_powershell(self.launcher_path),
            "-ExactModIds",
            "bot.brain",
            "-ProcessIdOutputPath",
            _path_for_powershell(ledger_path),
            "-ResultOutputPath",
            _path_for_powershell(result_path),
        ]
        if self.fresh_install:
            arguments.append("-FreshInstall")
        if not self.multiplayer_transport:
            arguments.append("-DisableMultiplayerTransport")
        if self.boneyard_override is not None:
            arguments.extend(
                (
                    "-TestSurvivalBoneyardOverride",
                    _path_for_powershell(self.boneyard_override),
                )
            )
        if self.headless:
            arguments.append("-Headless")

        try:
            self.launch_wrapper_process = subprocess.Popen(
                arguments,
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 120.0
            result: Any = None
            while time.monotonic() < deadline:
                if result_path.is_file():
                    try:
                        result = json.loads(
                            result_path.read_text(
                                encoding="utf-8-sig"
                            )
                        )
                    except (
                        OSError,
                        UnicodeError,
                        json.JSONDecodeError,
                    ):
                        result = None
                    if result is not None:
                        break
                returncode = self.launch_wrapper_process.poll()
                if returncode is not None:
                    raise BridgeError(
                        "solo launch exited before publishing its "
                        f"result document (exit code {returncode})"
                    )
                time.sleep(0.05)
            if result is None:
                raise BridgeError(
                    "solo launch did not publish its result document "
                    "within 120 seconds"
                )
            if not isinstance(result, dict):
                raise BridgeError("solo launch result is not an object")
            if result.get("success") is not True:
                raise BridgeError(f"solo launch was not successful: {result}")
            identities = register_owned_launch(result)
            self.process_ids = [
                identity.process_id for identity in identities
            ]
            self.launch_result = result
            runtime_root = result.get("runtimeRoot")
            if isinstance(runtime_root, str) and runtime_root:
                self.runtime_root = _local_path(runtime_root)
            self.layout_sha256()
            return result
        except BaseException:
            if self.process_ids:
                self.close()
            else:
                self._rescue_partial(ledger_path)
                self._reap_launch_wrapper()
            raise
        finally:
            ledger_path.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)

    def close(self) -> list[dict[str, Any]]:
        process_ids = list(self.process_ids)
        self.process_ids = []
        try:
            if not process_ids:
                return []
            return stop_owned_process_ids(process_ids)
        finally:
            try:
                self._reap_launch_wrapper()
            finally:
                local_sync._kill_lua_daemon(self.pipe_name)

    def __enter__(self) -> "SoloSession":
        self.launch()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def lua(self, code: str, *, timeout: float = 15.0) -> str:
        return local_sync.lua(self.pipe_name, code, timeout=timeout)

    def wait_for_pipe(self, *, timeout: float = 45.0) -> None:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                if self.lua("return 'ready'", timeout=5.0).strip() == "ready":
                    return
            except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as error:
                last_error = str(error)
            time.sleep(0.25)
        raise BridgeError(
            f"Lua pipe {self.pipe_name} did not become ready: {last_error}"
        )

    def drive_new_game_to_hub(
        self,
        *,
        timeout: float = 75.0,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        activated: set[str] = set()
        attempts: dict[str, int] = {}
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = local_sync.parse_key_values(
                self.lua(
                    """
local scene = sd.world.get_scene() or {}
local snapshot = sd.ui.get_snapshot() or {}
print('scene=' .. tostring(scene.name or scene.kind or ''))
print('transitioning=' .. tostring(
  scene.transitioning or false))
print('surface=' .. tostring(snapshot.surface_id or ''))
print('generation=' .. tostring(snapshot.generation or 0))
for index, element in ipairs(snapshot.elements or {}) do
  if index > 16 then break end
  print('action.' .. tostring(index) .. '=' ..
    tostring(element.action_id or ''))
end
""",
                    timeout=10.0,
                )
            )
            if (
                last.get("scene") == "hub"
                and last.get("transitioning") == "false"
            ):
                return last

            actions = {
                value
                for key, value in last.items()
                if key.startswith("action.") and value
            }
            candidates = (
                ("dialog", "dialog.primary"),
                (
                    "control_scheme_picker",
                    "control_scheme_picker.select_wasd",
                ),
                ("main_menu", "main_menu.play"),
                ("main_menu", "main_menu.new_game"),
                (
                    "create",
                    f"create.select_element_{self.element}",
                ),
                (
                    "create",
                    f"create.select_discipline_{self.discipline}",
                ),
            )
            surface = last.get("surface", "")
            dispatched = False
            for expected_surface, action_id in candidates:
                if (
                    surface != expected_surface
                    or action_id not in actions
                    or action_id in activated
                ):
                    continue
                attempts[action_id] = attempts.get(action_id, 0) + 1
                if attempts[action_id] > 3:
                    raise BridgeError(
                        "fresh-game UI action did not latch after "
                        f"three attempts: {expected_surface}:{action_id}"
                    )
                values = local_sync.parse_key_values(
                    self.lua(
                        f"""
local ok, request = sd.ui.activate_action(
  {json.dumps(action_id)},
  {json.dumps(expected_surface)})
print('ok=' .. tostring(ok))
print('request_id=' .. tostring(request or 0))
""",
                        timeout=10.0,
                    )
                )
                if values.get("ok") == "true":
                    request_id = int(
                        values.get("request_id", "0")
                    )
                    dispatch_deadline = min(
                        deadline,
                        time.monotonic() + 15.0,
                    )
                    while time.monotonic() < dispatch_deadline:
                        dispatch = local_sync.parse_key_values(
                            self.lua(
                                f"""
local state = sd.ui.get_action_dispatch(
  {request_id})
print('available=' .. tostring(
  type(state) == 'table'))
print('status=' .. tostring(
  type(state) == 'table' and
  state.status or ''))
print('error=' .. tostring(
  type(state) == 'table' and
  state.error_message or ''))
""",
                                timeout=10.0,
                            )
                        )
                        status = dispatch.get("status", "")
                        if (
                            status == "completed"
                            or status.startswith("dispatched")
                        ):
                            dispatched = True
                            break
                        if status == "failed":
                            raise BridgeError(
                                "fresh-game UI action failed: "
                                f"{expected_surface}:{action_id}: "
                                f"{dispatch.get('error', '')}"
                            )
                        time.sleep(0.1)
                    if not dispatched:
                        raise BridgeError(
                            "fresh-game UI action timed out: "
                            f"{expected_surface}:{action_id}"
                        )
                    if action_id.startswith(
                        "create.select_element_"
                    ):
                        readiness_deadline = min(
                            deadline,
                            time.monotonic() + 5.0,
                        )
                        ready = False
                        while (
                            time.monotonic()
                            < readiness_deadline
                        ):
                            selection = (
                                local_sync.parse_key_values(
                                    self.lua(
                                        """
local owner = 0
local snapshot = sd.ui.get_snapshot() or {}
for _, element in ipairs(
    snapshot.elements or {}) do
  if element.surface_id == 'create' or
      element.surface_root_id == 'create' then
    owner = tonumber(
      element.surface_object_ptr) or 0
    if owner ~= 0 then break end
  end
end
local selected = owner ~= 0 and
  sd.debug.read_u32(owner + 0x1A4) or nil
local enabled = owner ~= 0 and
  sd.debug.read_u8(owner + 0x228) or nil
print('selected=' .. tostring(selected))
print('discipline_enabled=' ..
  tostring(enabled or 0))
print('ready=' .. tostring(
  selected ~= nil and
  selected ~= 4294967295 and
  (tonumber(enabled) or 0) ~= 0))
""",
                                        timeout=10.0,
                                    )
                                )
                            )
                            if selection.get("ready") == "true":
                                ready = True
                                break
                            time.sleep(0.1)
                        if not ready:
                            dispatched = False
                    if dispatched:
                        activated.add(action_id)
                break
            time.sleep(0.5 if dispatched else 0.1)
        raise BridgeError(
            f"could not drive a fresh game to the hub: {last}"
        )

    def _write_roster(
        self,
        roster: list[dict[str, str]],
    ) -> dict[str, str]:
        _atomic_write_json(
            self.settings_path,
            {
                "schemaVersion": 1,
                "values": {
                    "focus_bot_key": "NONE",
                    "kite_radius": 340,
                    "offense_enabled": True,
                    "policy_weld_preference": self.weld_preference,
                    "skill_choice_mode": "learned",
                    "roster": roster,
                    "think_profile": "standard",
                },
            },
        )
        values = local_sync.parse_key_values(
            self.lua(
                """
local result = sd.__settings_reload('bot.brain')
print('ok=' .. tostring(result.ok))
print('changed=' .. table.concat(result.changed or {}, ','))
print('error=' .. tostring(result.error or ''))
for key, message in pairs(result.entry_errors or {}) do
  print('entry_error.' .. key .. '=' .. tostring(message))
end
""",
                timeout=10.0,
            )
        )
        entry_errors = {
            key: value
            for key, value in values.items()
            if key.startswith("entry_error.")
        }
        transient_spawn = (
            set(entry_errors) == {"entry_error.roster"}
            and (
                "spawn transform unavailable"
                in entry_errors["entry_error.roster"]
            )
        )
        if (
            values.get("ok") != "true"
            and not transient_spawn
        ) or (entry_errors and not transient_spawn):
            raise BridgeError(
                f"could not apply learned bot settings: {values}"
            )
        if "roster" not in values.get("changed", "").split(","):
            raise BridgeError(
                f"learned bot roster did not change: {values}"
            )
        return values

    def write_empty_roster(self) -> dict[str, str]:
        return self._write_roster([])

    def write_learned_roster(self) -> dict[str, str]:
        return self._write_roster(
            [
                {
                    "name": "Learner",
                    "element": self.element,
                    "behavior": "learned",
                    "discipline": self.discipline,
                }
            ]
        )

    def write_composition(
        self,
        composition: TeamComposition,
    ) -> dict[str, str]:
        return self._write_roster(
            build_roster(
                composition,
                element=self.element,
                discipline=self.discipline,
            )
        )

    def wait_for_empty_roster(self, *, timeout: float = 30.0) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            try:
                last = self.status()
                if int(last.get("active_bot_count", "0")) == 0:
                    return last
            except (
                ValueError,
                local_sync.VerifyFailure,
                subprocess.TimeoutExpired,
            ):
                pass
            time.sleep(0.2)
        raise BridgeError(f"bot roster did not become empty: {last}")

    def wait_for_composition(
        self,
        *,
        expected_bot_count: int,
        expected_learned_count: int,
        timeout: float = 30.0,
    ) -> dict[str, str]:
        if expected_bot_count < 1 or expected_learned_count < 1:
            raise ValueError("expected bot counts must be positive")
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            try:
                last = self.status()
                if (
                    int(last.get("active_bot_count", "0"))
                    == expected_bot_count
                    and int(last.get("learned_bot_count", "0"))
                    == expected_learned_count
                    and len(
                        _participant_ids(
                            last.get(
                                "learned_participant_ids",
                                "",
                            )
                        )
                    )
                    == expected_learned_count
                ):
                    return last
            except (
                ValueError,
                local_sync.VerifyFailure,
                subprocess.TimeoutExpired,
            ):
                pass
            time.sleep(0.2)
        raise BridgeError(
            f"bot composition did not become ready: {last}"
        )

    def wait_for_learned_bot(
        self,
        *,
        timeout: float = 30.0,
    ) -> dict[str, str]:
        return self.wait_for_composition(
            expected_bot_count=1,
            expected_learned_count=1,
            timeout=timeout,
        )

    def wait_for_run_ready(
        self,
        *,
        expected_bot_count: int = 1,
        expected_learned_count: int = 1,
        timeout: float = 45.0,
    ) -> dict[str, str]:
        if self.launch_result is None:
            raise BridgeError("session is not launched")
        transport_enabled = bool(
            self.launch_result.get("multiplayerTransportEnabled", True)
        )
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        ready_since: float | None = None
        ready_nonce = 0
        while time.monotonic() < deadline:
            try:
                last = local_sync.parse_key_values(
                    self.lua(RUN_READY_STATUS, timeout=10.0)
                )
                expected = int(last.get("loading_expected", "0"))
                ready = int(last.get("loading_ready", "0"))
                multiplayer_lifecycle_ready = (
                    last.get("scene") == "testrun"
                    and last.get("session_state") == "in-boneyard"
                    and last.get("loading_active") == "true"
                    and last.get("loading_released") == "true"
                    and last.get("loading_timed_out") == "false"
                    and int(last.get("loading_run_nonce", "0")) > 0
                    and last.get("loading_release_reason")
                    == "all-participants-ready"
                    and expected > 0
                    and ready == expected
                    and int(
                        last.get("member_in_run_count", "0")
                    ) == expected_bot_count
                    and int(
                        last.get(
                            "member_runtime_valid_count",
                            "0",
                        )
                    ) == expected_bot_count
                    and int(
                        last.get(
                            "lua_brain_member_count",
                            "0",
                        )
                    ) == expected_bot_count
                )
                offline_lifecycle_ready = (
                    last.get("scene") == "testrun"
                    and last.get("session_state") == "not-in-game"
                    and last.get("loading_active") == "false"
                    and last.get("loading_released") == "false"
                    and last.get("loading_timed_out") == "false"
                    and int(last.get("loading_run_nonce", "0")) == 0
                    and expected == 0
                    and ready == 0
                    and int(
                        last.get("member_in_run_count", "0")
                    ) == expected_bot_count
                    and int(
                        last.get(
                            "member_runtime_valid_count",
                            "0",
                        )
                    ) == expected_bot_count
                    and int(
                        last.get(
                            "lua_brain_member_count",
                            "0",
                        )
                    ) == expected_bot_count
                )
                lifecycle_ready = (
                    multiplayer_lifecycle_ready
                    if transport_enabled
                    else offline_lifecycle_ready
                )
                if lifecycle_ready:
                    nonce = (
                        int(last["loading_run_nonce"])
                        if transport_enabled
                        else 1
                    )
                    now = time.monotonic()
                    if nonce != ready_nonce:
                        ready_nonce = nonce
                        ready_since = now
                    if (
                        ready_since is None
                        or now - ready_since
                        < RUN_READY_STABILITY_SECONDS
                    ):
                        time.sleep(0.1)
                        continue
                    bot_ready = (
                        int(last.get("bot_count", "0"))
                        == expected_bot_count
                        and int(
                            last.get("bot_position_count", "0")
                        ) == expected_bot_count
                        and int(last.get("bot_hp_count", "0"))
                        == expected_bot_count
                        and int(last.get("bot_alive_count", "0"))
                        == expected_bot_count
                        and int(last.get("bot_slot_count", "0"))
                        == expected_bot_count
                        and int(
                            last.get("learned_bot_count", "0")
                        ) == expected_learned_count
                    )
                    last["bot_ready"] = str(bot_ready).lower()
                    return last
                ready_since = None
                ready_nonce = 0
            except (
                ValueError,
                local_sync.VerifyFailure,
                subprocess.TimeoutExpired,
            ):
                pass
            time.sleep(0.1)
        raise BridgeError(f"test run did not become ready: {last}")

    def wait_for_bot_materialized(
        self,
        *,
        expected_bot_count: int = 1,
        expected_learned_count: int = 1,
        timeout: float = 45.0,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        started_at = time.monotonic()
        respawn_requested = False
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            try:
                last = local_sync.parse_key_values(
                    self.lua(RUN_READY_STATUS, timeout=10.0)
                )
                if (
                    last.get("scene") == "testrun"
                    and int(last.get("bot_count", "0"))
                    == expected_bot_count
                    and int(
                        last.get("bot_position_count", "0")
                    ) == expected_bot_count
                    and int(last.get("bot_hp_count", "0"))
                    == expected_bot_count
                    and int(last.get("bot_alive_count", "0"))
                    == expected_bot_count
                    and int(last.get("bot_slot_count", "0"))
                    == expected_bot_count
                    and int(
                        last.get("member_in_run_count", "0")
                    ) == expected_bot_count
                    and int(
                        last.get(
                            "member_runtime_valid_count",
                            "0",
                        )
                    ) == expected_bot_count
                    and int(
                        last.get(
                            "lua_brain_member_count",
                            "0",
                        )
                    ) == expected_bot_count
                    and int(
                        last.get("learned_bot_count", "0")
                    ) == expected_learned_count
                ):
                    return last
                if (
                    not respawn_requested
                    and time.monotonic() - started_at
                    >= BOT_MATERIALIZATION_GRACE_SECONDS
                ):
                    action = local_sync.parse_key_values(
                        self.lua(
                            """
local result = sd.__settings_invoke_action(
  'bot.brain',
  'respawn_bot')
print('ok=' .. tostring(result.ok))
print('error=' .. tostring(result.error or ''))
""",
                            timeout=10.0,
                        )
                    )
                    if action.get("ok") != "true":
                        raise BridgeError(
                            "could not rematerialize the learned bot: "
                            f"{action}"
                        )
                    respawn_requested = True
            except (
                ValueError,
                local_sync.VerifyFailure,
                subprocess.TimeoutExpired,
            ):
                pass
            time.sleep(0.1)
        raise BridgeError(
            f"learned bot did not materialize in the test run: {last}"
        )

    def enable_god_mode(self) -> dict[str, str]:
        values = local_sync.parse_key_values(self.lua(GOD_MODE))
        if values.get("registered") != "true":
            raise BridgeError(f"failed to register god mode: {values}")
        return values

    def set_run_seed(self, seed: int) -> dict[str, int]:
        if seed < 1 or seed > 0x3FFFFFFF:
            raise ValueError(
                "run seed must be between 1 and 0x3fffffff"
            )
        values = local_sync.parse_key_values(
            self.lua(
                f"""
local requested = {int(seed)}
local accepted = sd.rng.set_seed(requested)
local observed = sd.rng.get_seed()
print('requested_seed=' .. tostring(requested))
print('accepted_seed=' .. tostring(accepted or 0))
print('observed_seed=' .. tostring(observed or 0))
""",
                timeout=10.0,
            )
        )
        result = {
            key: int(values.get(key, "0"))
            for key in (
                "requested_seed",
                "accepted_seed",
                "observed_seed",
            )
        }
        if any(value != seed for value in result.values()):
            raise BridgeError(
                f"run seed did not round-trip exactly: {result}"
            )
        return result

    def get_run_identity(self) -> dict[str, int]:
        values = local_sync.parse_key_values(
            self.lua(
                """
local state = sd.runtime.get_multiplayer_state() or {}
local seed = tonumber(sd.rng.get_seed()) or 0
local nonce = 0
local mismatches = 0
for _, participant in ipairs(state.participants or {}) do
  if participant.in_run == true then
    local candidate = tonumber(participant.run_nonce) or 0
    if candidate > 0 then
      if nonce == 0 then
        nonce = candidate
      elseif nonce ~= candidate then
        mismatches = mismatches + 1
      end
    end
  end
end
local loading = state.run_loading_barrier or {}
if nonce == 0 then
  nonce = tonumber(loading.run_nonce) or 0
end
print('observed_seed=' .. tostring(seed))
print('run_nonce=' .. tostring(nonce))
print('nonce_mismatches=' .. tostring(mismatches))
""",
                timeout=10.0,
            )
        )
        result = {
            key: int(values.get(key, "0"))
            for key in (
                "observed_seed",
                "run_nonce",
                "nonce_mismatches",
            )
        }
        if (
            result["observed_seed"] <= 0
            or result["run_nonce"] <= 0
            or result["nonce_mismatches"] != 0
        ):
            raise BridgeError(f"run identity is invalid: {result}")
        return result

    def start_test_run(self, *, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                values = local_sync.parse_key_values(
                    self.lua(
                        """
local ok, result = pcall(sd.hub.start_testrun)
print('pcall_ok=' .. tostring(ok))
print('result=' .. tostring(result))
""",
                        timeout=8.0,
                    )
                )
                if (
                    values.get("pcall_ok") == "true"
                    and values.get("result") == "true"
                ):
                    local_sync.wait_for_scene(
                        self.pipe_name,
                        "testrun",
                        timeout=timeout,
                    )
                    return
                last_error = str(values)
            except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as error:
                last_error = str(error)
            time.sleep(0.25)
        raise BridgeError(f"could not start test run: {last_error}")

    def prepare_training_combat(
        self,
        *,
        timeout: float = 20.0,
    ) -> dict[str, str]:
        setup = local_sync.parse_key_values(
            self.lua(
                """
local combat = sd.gameplay.get_combat_state() or {}
local recover = (tonumber(combat.wave_index) or 0) > 0
local prelude_pcall_ok, prelude = pcall(function()
  if recover then
    return sd.gameplay.enable_combat_prelude({
      recover_untracked_wave = true,
    })
  end
  return sd.gameplay.enable_combat_prelude()
end)
local mode_call_ok, manual_mode =
  sd.gameplay.set_manual_enemy_spawner_test_mode(true)
print('recover_untracked_wave=' .. tostring(recover))
print('prelude_pcall_ok=' .. tostring(prelude_pcall_ok))
print('prelude=' .. tostring(prelude))
print('mode_call_ok=' .. tostring(mode_call_ok))
print('manual_mode=' .. tostring(manual_mode))
""",
                timeout=min(timeout, 10.0),
            )
        )
        if (
            setup.get("prelude_pcall_ok") != "true"
            or setup.get("prelude") != "true"
            or setup.get("mode_call_ok") != "true"
            or setup.get("manual_mode") != "true"
        ):
            raise BridgeError(
                f"could not prepare direct training combat: {setup}"
            )
        return setup

    def prime_training_progression(
        self,
        *,
        max_level_steps: int = 64,
        timeout: float = 30.0,
    ) -> dict[str, str]:
        if max_level_steps <= 0:
            raise ValueError("max_level_steps must be positive")
        try:
            primary_entry = PRIMARY_ENTRY_BY_ELEMENT[self.element]
        except KeyError as error:
            raise BridgeError(
                f"unsupported training element: {self.element}"
            ) from error

        values = local_sync.parse_key_values(
            self.lua(
                f"""
local primary_entry = {primary_entry}
local max_level_steps = {max_level_steps}
local level_offset = assert(
  sd.debug.layout_offset('progression_level'))
local next_xp_offset = assert(
  sd.debug.layout_offset('progression_next_xp_threshold'))

local handles = sd.bots.list() or {{}}
local bot = handles[1]
if bot == nil then
  print('ready=false')
  print('error=no learned bot handle')
  return
end
local participant_id = tonumber(bot:participant_id()) or 0
local bot_state = sd.bots.get_state(participant_id)
local progression = type(bot_state) == 'table' and
  tonumber(bot_state.progression_runtime_state_address) or 0
local player = sd.player.get_state()
local source_progression = type(player) == 'table' and
  tonumber(player.progression_address) or 0
if participant_id <= 0 or progression == 0 or
    source_progression == 0 then
  print('ready=false')
  print('error=training progression is not materialized')
  print('participant_id=' .. tostring(participant_id))
  print('progression=' .. tostring(progression))
  print('source_progression=' .. tostring(source_progression))
  return
end

local applied_choices = 0
local matched_primary = false
local last_error = ''
local elemental_primary = {{
  [8] = true,
  [16] = true,
  [24] = true,
  [32] = true,
  [40] = true,
}}
local function native_stats()
  local stats = sd.debug.resolve_native_primary_spell_stats(
    progression,
    primary_entry,
    primary_entry)
  if type(stats) ~= 'table' then
    return false, {{}}
  end
  local ready =
    stats.resolved == true and
    (tonumber(stats.mana_spend_cost) or 0) > 0 and
    (tonumber(stats.damage) or 0) > 0
  return ready, stats
end

local function apply_pending_choice()
  local choices = sd.bots.get_skill_choices(participant_id)
  if type(choices) ~= 'table' or
      choices.pending ~= true or
      type(choices.options) ~= 'table' or
      #choices.options == 0 then
    return false
  end
  local selected_index = nil
  for index, option in ipairs(choices.options) do
    if tonumber(option.id) == primary_entry then
      selected_index = index
      matched_primary = true
      break
    end
  end
  if selected_index == nil then
    for index, option in ipairs(choices.options) do
      if elemental_primary[tonumber(option.id)] ~= true then
        selected_index = index
        break
      end
    end
  end
  if selected_index == nil then
    last_error =
      'native choices contained only conflicting elemental primaries'
    return false
  end
  local ok, accepted = pcall(
    sd.bots.choose_skill,
    participant_id,
    selected_index,
    tonumber(choices.generation) or 0)
  if not ok or accepted ~= true then
    last_error = 'native skill choice apply failed: ' ..
      tostring(accepted)
    return false
  end
  applied_choices = applied_choices + 1
  return true
end

local ready, stats = native_stats()
local level_steps = 0
while not ready and level_steps < max_level_steps do
  apply_pending_choice()
  ready, stats = native_stats()
  if ready then
    break
  end

  local level = tonumber(
    sd.debug.read_i32(progression + level_offset)) or 0
  local next_xp = tonumber(
    sd.debug.read_float(progression + next_xp_offset)) or 0
  if level <= 0 or next_xp <= 0 or next_xp ~= next_xp then
    last_error = 'native level or next-xp is invalid'
    break
  end
  local sync_ok, synced = pcall(
    sd.bots.debug_sync_level_up,
    {{
      level = level + 1,
      experience = math.ceil(next_xp + 10.0),
      source_progression_address = source_progression,
    }})
  if not sync_ok or synced ~= true then
    last_error = 'native level-up sync failed: ' ..
      tostring(synced)
    break
  end
  level_steps = level_steps + 1
  if not apply_pending_choice() then
    last_error = last_error ~= '' and last_error or
      'native level-up produced no selectable option'
    break
  end
  ready, stats = native_stats()
end

print('ready=' .. tostring(ready))
print('participant_id=' .. tostring(participant_id))
print('primary_entry=' .. tostring(primary_entry))
print('progression=' .. tostring(progression))
print('source_progression=' .. tostring(source_progression))
print('level_steps=' .. tostring(level_steps))
print('applied_choices=' .. tostring(applied_choices))
print('matched_primary=' .. tostring(matched_primary))
print('resolved=' .. tostring(stats.resolved == true))
print('mana_spend_cost=' ..
  tostring(tonumber(stats.mana_spend_cost) or 0))
print('damage=' .. tostring(tonumber(stats.damage) or 0))
print('error=' .. tostring(
  ready and '' or
  (last_error ~= '' and last_error or
   (tostring(stats.error or '') ~= '' and
      tostring(stats.error) or
      'primary spell did not become available'))))
""",
                timeout=timeout,
            )
        )
        if (
            values.get("ready") != "true"
            or values.get("matched_primary") != "true"
            or float(values.get("mana_spend_cost", "0")) <= 0.0
            or float(values.get("damage", "0")) <= 0.0
        ):
            raise BridgeError(
                f"could not prime native training spell: {values}"
            )
        return values

    def prime_learned_progression(
        self,
        *,
        minimum_secondary_slots: int = 1,
        max_level_steps: int = 64,
        timeout: float = 30.0,
    ) -> dict[str, str]:
        if minimum_secondary_slots < 0:
            raise ValueError(
                "minimum_secondary_slots must be non-negative"
            )
        if max_level_steps <= 0:
            raise ValueError("max_level_steps must be positive")
        try:
            training_primary_entry = (
                PRIMARY_ENTRY_BY_ELEMENT[self.element]
            )
            training_secondary_entry = (
                TRAINING_SECONDARY_ENTRY_BY_ELEMENT[self.element]
            )
        except KeyError as error:
            raise BridgeError(
                f"unsupported training element: {self.element}"
            ) from error
        values = local_sync.parse_key_values(
            self.lua(
                f"""
local minimum_secondaries = {int(minimum_secondary_slots)}
local max_steps = {int(max_level_steps)}
local training_primary_entry = {training_primary_entry}
local training_secondary_entry = {training_secondary_entry}
local debug = rawget(_G, 'bot_brain_debug') or {{}}
local learned = {{}}
for _, row in ipairs(debug.bots or {{}}) do
  if tostring(row.behavior or '') == 'learned' and
      (tonumber(row.participant_id) or 0) > 0 then
    learned[#learned + 1] =
      tonumber(row.participant_id)
  end
end
table.sort(learned)

local castable_secondary = {{
  [11] = true, [12] = true, [15] = true,
  [21] = true, [23] = true, [27] = true,
  [30] = true, [35] = true, [41] = true,
  [45] = true, [46] = true, [48] = true,
  [49] = true, [50] = true, [51] = true,
  [54] = true, [72] = true, [73] = true,
  [74] = true, [76] = true, [77] = true,
  [78] = true, [79] = true,
}}
local level_offset = assert(
  sd.debug.layout_offset('progression_level'))
local next_xp_offset = assert(
  sd.debug.layout_offset('progression_next_xp_threshold'))
local table_base_offset = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_table_base'))
local table_count_offset = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_table_count'))
local table_stride = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_entry_stride'))
local active_offset = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_active_flag'))
local effective_offset = assert(
  sd.debug.layout_offset(
    'standalone_wizard_progression_entry_effective_rank'))

local function native_entry_active(participant_id, entry_id)
  local state = sd.bots.get_state(participant_id) or {{}}
  local progression =
    tonumber(state.progression_runtime_state_address) or 0
  if progression <= 0 or entry_id < 0 then
    return false
  end
  local table_address =
    tonumber(sd.debug.read_ptr(
      progression + table_base_offset)) or 0
  local table_count =
    tonumber(sd.debug.read_i32(
      progression + table_count_offset)) or 0
  if table_address <= 0 or
      entry_id >= table_count then
    return false
  end
  local active =
    tonumber(sd.debug.read_u16(
      table_address +
      entry_id * table_stride +
      active_offset)) or 0
  return active > 0
end

local profile_updates_ok = true
local function ensure_current_primary_active(participant_id)
  local state = sd.bots.get_state(participant_id) or {{}}
  local progression =
    tonumber(state.progression_runtime_state_address) or 0
  local details =
    sd.bots.get_loadout_details(participant_id) or {{}}
  local entry_id =
    tonumber((details.primary or {{}}).entry_id) or -1
  if progression <= 0 or entry_id < 0 then
    return false
  end
  local table_address =
    tonumber(sd.debug.read_ptr(
      progression + table_base_offset)) or 0
  local table_count =
    tonumber(sd.debug.read_i32(
      progression + table_count_offset)) or 0
  if table_address <= 0 or
      entry_id >= table_count then
    return false
  end
  local row =
    table_address + entry_id * table_stride
  local active =
    math.max(
      tonumber(sd.debug.read_u16(
        row + active_offset)) or 0,
      1)
  local effective =
    math.max(
      tonumber(sd.debug.read_u16(
        row + effective_offset)) or 0,
      active)
  return
    sd.debug.write_u16(
      row + active_offset,
      active) and
    sd.debug.write_u16(
      row + effective_offset,
      effective)
end

local function install_secondary(participant_id, entry_id)
  if not native_entry_active(participant_id, entry_id) then
    return false
  end
  local state = sd.bots.get_state(participant_id) or {{}}
  local profile = state.profile or {{}}
  local loadout = profile.loadout or {{}}
  local secondaries = {{}}
  local already_installed = false
  local target_slot = nil
  for slot = 1, 8 do
    secondaries[slot] =
      tonumber(
        (loadout.secondary_entry_indices or {{}})[slot]) or -1
    if secondaries[slot] == entry_id then
      already_installed = true
    elseif target_slot == nil and
        (secondaries[slot] < 0 or
         not native_entry_active(
           participant_id,
           secondaries[slot])) then
      target_slot = slot
    end
  end
  if already_installed then
    return true
  end
  if target_slot == nil then
    return false
  end
  secondaries[target_slot] = entry_id
  local updated = sd.bots.update({{
    id = participant_id,
    profile = {{
      element_id = tonumber(profile.element_id) or 0,
      discipline_id = tonumber(profile.discipline_id) or 2,
      level = tonumber(profile.level) or 1,
      experience = tonumber(profile.experience) or 0,
      loadout = {{
        primary_entry_index =
          tonumber(loadout.primary_entry_index) or -1,
        primary_combo_entry_index =
          tonumber(loadout.primary_combo_entry_index) or -1,
        secondary_entry_indices = secondaries,
      }},
    }},
  }})
  profile_updates_ok =
    updated == true and profile_updates_ok
  return updated == true
end

local function loadout_ready(participant_id)
  local details =
    sd.bots.get_loadout_details(participant_id) or {{}}
  local primary = details.primary or {{}}
  local occupied = 0
  for _, secondary in ipairs(details.secondaries or {{}}) do
    if (tonumber(secondary.entry_id) or -1) >= 0 and
        native_entry_active(
          participant_id,
          tonumber(secondary.entry_id) or -1) and
        secondary.mana_cost_resolved == true and
        (tonumber(secondary.mana_cost) or 0) > 0 then
      occupied = occupied + 1
    end
  end
  return
    primary.build_id_resolved == true and
    primary.mana_cost_resolved == true and
    primary.range_resolved == true and
    (tonumber(primary.mana_cost) or 0) > 0 and
    (tonumber(primary.range_max) or 0) > 0 and
    occupied >= minimum_secondaries,
    occupied
end

local primary_rows_ok = true
for _, participant_id in ipairs(learned) do
  primary_rows_ok =
    ensure_current_primary_active(participant_id) and
    primary_rows_ok
end

local function apply_pending(participant_id)
  local choices =
    sd.bots.get_skill_choices(participant_id) or {{}}
  if choices.pending ~= true or
      #(choices.options or {{}}) == 0 then
    return false
  end
  local selected = nil
  local details =
    sd.bots.get_loadout_details(participant_id) or {{}}
  local primary = details.primary or {{}}
  local primary_missing =
    primary.mana_cost_resolved ~= true or
    (tonumber(primary.mana_cost) or 0) <= 0
  if primary_missing then
    for index, option in ipairs(choices.options) do
      if (tonumber(option.id) or -1) ==
          training_primary_entry then
        selected = index
        break
      end
    end
  end
  if selected == nil then
    for index, option in ipairs(choices.options) do
      local option_id = tonumber(option.id) or -1
      if option_id == training_secondary_entry then
        selected = index
        break
      end
    end
  end
  if selected == nil then
    for index, option in ipairs(choices.options) do
      local option_id = tonumber(option.id) or -1
      if castable_secondary[option_id] == true then
        selected = index
        break
      end
    end
  end
  if selected == nil then
    for index, option in ipairs(choices.options) do
      if (tonumber(option.id) or -1) ~= 52 then
        selected = index
        break
      end
    end
  end
  if selected == nil then
    return false
  end
  local ok, accepted = pcall(
    sd.bots.choose_skill,
    participant_id,
    selected,
    tonumber(choices.generation) or 0)
  if ok and accepted == true then
    local option_id =
      tonumber(choices.options[selected].id) or -1
    if castable_secondary[option_id] == true then
      profile_updates_ok =
        install_secondary(participant_id, option_id) and
        profile_updates_ok
    end
  end
  return ok and accepted == true
end

local steps = 0
local choices_applied = 0
while steps < max_steps do
  local ready_count = 0
  for _, participant_id in ipairs(learned) do
    local ready = loadout_ready(participant_id)
    if ready then
      ready_count = ready_count + 1
    elseif apply_pending(participant_id) then
      choices_applied = choices_applied + 1
    end
  end
  if ready_count == #learned and #learned > 0 then
    break
  end

  local target_level = 2
  local target_xp = 100
  for _, participant_id in ipairs(learned) do
    local state = sd.bots.get_state(participant_id) or {{}}
    local progression =
      tonumber(state.progression_runtime_state_address) or 0
    if progression > 0 then
      local level = tonumber(
        sd.debug.read_i32(
          progression + level_offset)) or 1
      local next_xp = tonumber(
        sd.debug.read_float(
          progression + next_xp_offset)) or 90
      target_level = math.max(target_level, level + 1)
      target_xp =
        math.max(target_xp, math.ceil(next_xp + 10))
    end
  end
  local ok, synced = pcall(
    sd.bots.debug_sync_level_up,
    {{
      level = target_level,
      experience = target_xp,
    }})
  if not ok or synced ~= true then
    break
  end
  steps = steps + 1
  for _, participant_id in ipairs(learned) do
    if apply_pending(participant_id) then
      choices_applied = choices_applied + 1
    end
  end
end

local ready_count = 0
local minimum_observed = 999
for _, participant_id in ipairs(learned) do
  local ready, occupied = loadout_ready(participant_id)
  if ready then ready_count = ready_count + 1 end
  minimum_observed = math.min(minimum_observed, occupied)
end
if #learned == 0 then minimum_observed = 0 end
local first_details =
  learned[1] and
    (sd.bots.get_loadout_details(learned[1]) or {{}}) or {{}}
local first_primary = first_details.primary or {{}}
print('ready=' .. tostring(
  profile_updates_ok and
  primary_rows_ok and
  #learned > 0 and ready_count == #learned))
print('profile_updates_ok=' ..
  tostring(profile_updates_ok))
print('primary_rows_ok=' ..
  tostring(primary_rows_ok))
print('training_secondary_entry=' ..
  tostring(training_secondary_entry))
print('primary_build_resolved=' ..
  tostring(first_primary.build_id_resolved == true))
print('primary_mana_resolved=' ..
  tostring(first_primary.mana_cost_resolved == true))
print('primary_mana_cost=' ..
  tostring(tonumber(first_primary.mana_cost) or 0))
print('primary_range_resolved=' ..
  tostring(first_primary.range_resolved == true))
print('primary_range_max=' ..
  tostring(tonumber(first_primary.range_max) or 0))
print('learned_count=' .. tostring(#learned))
print('ready_count=' .. tostring(ready_count))
print('minimum_secondary_count=' ..
  tostring(minimum_observed))
print('level_steps=' .. tostring(steps))
print('choices_applied=' .. tostring(choices_applied))
""",
                timeout=timeout,
            )
        )
        if (
            values.get("ready") != "true"
            or int(values.get("learned_count", "0")) < 1
            or int(values.get("ready_count", "0"))
            != int(values.get("learned_count", "0"))
            or int(values.get("minimum_secondary_count", "0"))
            < minimum_secondary_slots
        ):
            raise BridgeError(
                "could not prime every learned participant: "
                f"{values}"
            )
        return values

    def start_training_arena(
        self,
        *,
        spawn_distance: float = 260.0,
        enemy_hp: float = 750.0,
        timeout: float = 20.0,
    ) -> dict[str, str]:
        if (
            not math.isfinite(spawn_distance)
            or spawn_distance <= 0.0
            or not math.isfinite(enemy_hp)
            or enemy_hp <= 0.0
        ):
            raise ValueError(
                "training arena distance and HP must be finite and positive"
            )
        source = (
            "_G.__sdmod_ml_training_arena_config = {"
            f"spawn_distance={spawn_distance:.17g},"
            f"enemy_hp={enemy_hp:.17g},"
            "enemy_type_id=1001}\n"
            + TRAINING_ARENA_MANAGER
        )
        manager = local_sync.parse_key_values(
            self.lua(source, timeout=min(timeout, 10.0))
        )
        if manager.get("registered") != "true":
            raise BridgeError(
                f"could not register the training arena manager: {manager}"
            )
        return manager

    def start_stock_wave_episode(
        self,
        observer_participant_id: int,
        *,
        timeout: float = 180.0,
    ) -> dict[str, object]:
        if self.episode_mode != "waves":
            raise BridgeError(
                "stock wave routing requires a waves episode session"
            )

        def run_values(source: str, request_timeout: float) -> dict[str, str]:
            return local_sync.parse_key_values(
                self.lua(source, timeout=request_timeout)
            )

        return route_stock_wave_episode(
            run_values,
            observer_participant_id,
            timeout=timeout,
        )

    def participant_progression(
        self,
        participant_ids: Sequence[int],
    ) -> list[dict[str, int]]:
        ids = tuple(int(value) for value in participant_ids)
        if not ids or any(value <= 0 for value in ids):
            raise ValueError("participant_ids must contain positive IDs")
        rows = ",".join(str(value) for value in ids)
        values = local_sync.parse_key_values(
            self.lua(
                f"""
local ids = {{{rows}}}
local multiplayer = sd.runtime.get_multiplayer_state() or {{}}
local runtime_by_id = {{}}
for _, row in ipairs(multiplayer.participants or {{}}) do
  runtime_by_id[tonumber(row.participant_id) or 0] = row
end
for index, id in ipairs(ids) do
  local state = sd.bots.get_participant_state(id) or {{}}
  local profile = state.profile or {{}}
  local runtime = runtime_by_id[id] or {{}}
  local choices = sd.bots.get_skill_choices(id) or {{}}
  local prefix = 'participant.' .. tostring(index) .. '.'
  print(prefix .. 'id=' .. tostring(id))
  print(prefix .. 'available=' .. tostring(
    tonumber(state.id) == id or
    tonumber(runtime.participant_id) == id))
  print(prefix .. 'level=' .. tostring(
    profile.level or runtime.level or 0))
  print(prefix .. 'experience=' ..
    tostring(profile.experience or
      runtime.experience_current or 0))
  print(prefix .. 'pending=' ..
    tostring(choices.pending == true))
  print(prefix .. 'choice_generation=' ..
    tostring(choices.generation or 0))
end
""",
                timeout=10.0,
            )
        )
        result: list[dict[str, int]] = []
        for index, participant_id in enumerate(ids, start=1):
            prefix = f"participant.{index}."
            if (
                values.get(prefix + "available") != "true"
                or int(values.get(prefix + "id", "0")) != participant_id
            ):
                raise BridgeError(
                    "participant progression is unavailable: "
                    f"id={participant_id} values={values}"
                )
            level = int(float(values.get(prefix + "level", "0")))
            experience = int(
                float(values.get(prefix + "experience", "0"))
            )
            if level <= 0 or experience < 0:
                raise BridgeError(
                    "participant progression is invalid: "
                    f"id={participant_id} level={level} "
                    f"experience={experience}"
                )
            result.append(
                {
                    "participant_id": participant_id,
                    "level": level,
                    "experience": experience,
                    "choice_pending": int(
                        values.get(prefix + "pending") == "true"
                    ),
                    "choice_generation": int(
                        float(
                            values.get(
                                prefix + "choice_generation",
                                "0",
                            )
                        )
                    ),
                }
            )
        return result

    def _wait_for_wave_progression(
        self,
        participant_ids: Sequence[int],
        before: Sequence[Mapping[str, int]],
        *,
        initial_status: Mapping[str, str],
        timeout: float,
        require_natural_choice_proof: bool,
    ) -> dict[str, object]:
        if not math.isfinite(timeout) or timeout <= 0.0:
            raise ValueError("timeout must be finite and positive")
        ids = tuple(int(value) for value in participant_ids)
        baseline = {
            int(row["participant_id"]): {
                "level": int(row["level"]),
                "experience": int(row["experience"]),
            }
            for row in before
        }
        if set(ids) != set(baseline):
            raise ValueError(
                "wave-progression baseline does not match participant IDs"
            )
        initial_seen = int(
            initial_status.get("learned_skill_choices_seen", "0")
        )
        initial_accepted = int(
            initial_status.get("learned_skill_choices_accepted", "0")
        )
        deadline = time.monotonic() + timeout
        maximum_level = {
            participant_id: baseline[participant_id]["level"]
            for participant_id in ids
        }
        maximum_experience = {
            participant_id: baseline[participant_id]["experience"]
            for participant_id in ids
        }
        last: dict[str, object] = {}
        while time.monotonic() < deadline:
            progression = self.participant_progression(ids)
            status = self.status()
            if status.get("level_up_pause_active") == "true":
                self.wait_for_training_owner_level_up_barrier(
                    timeout=min(
                        TRAINING_OWNER_LEVEL_UP_RESOLVE_TIMEOUT_SECONDS,
                        max(deadline - time.monotonic(), 0.01),
                    )
                )
                status = self.status()
            for row in progression:
                participant_id = row["participant_id"]
                maximum_level[participant_id] = max(
                    maximum_level[participant_id], row["level"]
                )
                maximum_experience[participant_id] = max(
                    maximum_experience[participant_id],
                    row["experience"],
                )
            level_delta = sum(
                maximum_level[participant_id]
                - baseline[participant_id]["level"]
                for participant_id in ids
            )
            experience_delta = sum(
                maximum_experience[participant_id]
                - baseline[participant_id]["experience"]
                for participant_id in ids
            )
            seen_delta = (
                int(status.get("learned_skill_choices_seen", "0"))
                - initial_seen
            )
            accepted_delta = (
                int(
                    status.get(
                        "learned_skill_choices_accepted",
                        "0",
                    )
                )
                - initial_accepted
            )
            last = {
                "before": list(before),
                "current": progression,
                "maximum_level": maximum_level,
                "maximum_experience": maximum_experience,
                "level_delta": level_delta,
                "experience_delta": experience_delta,
                "native_choices_seen_delta": seen_delta,
                "learned_choices_accepted_delta": accepted_delta,
            }
            integration_healthy = (
                experience_delta >=
                WAVE_INTEGRATION_MIN_EXPERIENCE_DELTA
            )
            acceptance_proven = (
                level_delta >= NATURAL_CHOICE_PROOF_MIN_LEVEL_DELTA
                and seen_delta >= NATURAL_CHOICE_PROOF_MIN_EVENT_DELTA
                and accepted_delta >= NATURAL_CHOICE_PROOF_MIN_EVENT_DELTA
            )
            if (
                acceptance_proven
                if require_natural_choice_proof
                else integration_healthy
            ):
                return last
            time.sleep(WAVE_PROGRESSION_POLL_INTERVAL_SECONDS)
        if require_natural_choice_proof:
            raise BridgeError(
                "natural-choice acceptance proof did not observe a learned "
                "level-up and accepted native choice within "
                f"{timeout:.1f}s: {last}"
            )
        raise BridgeError(
            "stock-wave integration produced no learned participant XP "
            f"within {timeout:.1f}s: {last}"
        )

    def wait_for_wave_integration(
        self,
        participant_ids: Sequence[int],
        before: Sequence[Mapping[str, int]],
        *,
        initial_status: Mapping[str, str],
        timeout: float,
    ) -> dict[str, object]:
        return self._wait_for_wave_progression(
            participant_ids,
            before,
            initial_status=initial_status,
            timeout=timeout,
            require_natural_choice_proof=False,
        )

    def wait_for_natural_choice_proof(
        self,
        participant_ids: Sequence[int],
        before: Sequence[Mapping[str, int]],
        *,
        initial_status: Mapping[str, str],
        timeout: float,
    ) -> dict[str, object]:
        return self._wait_for_wave_progression(
            participant_ids,
            before,
            initial_status=initial_status,
            timeout=timeout,
            require_natural_choice_proof=True,
        )

    def wait_for_training_enemy(
        self,
        *,
        timeout: float = 20.0,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = local_sync.parse_key_values(
                self.lua(TRAINING_ARENA_STATUS, timeout=10.0)
            )
            if int(last.get("live_enemy_count", "0")) > 0:
                return last
            if int(last.get("failed_spawn_count", "0")) > 0:
                raise BridgeError(
                    f"direct training enemy spawn failed: {last}"
                )
            time.sleep(0.1)
        raise BridgeError(
            f"direct training enemy did not materialize: {last}"
        )

    def status(self) -> dict[str, str]:
        return local_sync.parse_key_values(
            self.lua(STATUS, timeout=10.0)
        )

    def _resolve_training_owner_level_up_offer(
        self,
        status: Mapping[str, str],
    ) -> dict[str, int] | None:
        if (
            status.get("level_up_offer_valid") != "true"
            or status.get("level_up_offer_submitted") == "true"
        ):
            return None
        offer_id = int(status.get("level_up_offer_id", "0"))
        option_count = int(
            status.get("level_up_offer_option_count", "0")
        )
        local_participant_id = int(
            status.get("local_participant_id", "0")
        )
        target_participant_id = int(
            status.get("level_up_offer_target", "0")
        )
        authority_participant_id = int(
            status.get("level_up_offer_authority", "0")
        )
        if (
            offer_id <= 0
            or option_count <= 0
            or local_participant_id <= 0
            or authority_participant_id <= 0
            or target_participant_id != authority_participant_id
        ):
            raise BridgeError(
                "training owner level-up offer is malformed: "
                f"{dict(status)}"
            )
        values = local_sync.parse_key_values(
            self.lua(
                f"""
local ok, result = pcall(
  sd.runtime.choose_level_up_option,
  {{offer_id={offer_id}, option_index=1}})
print('pcall_ok=' .. tostring(ok))
print('result=' .. tostring(result))
""",
                timeout=7.5,
            )
        )
        if (
            values.get("pcall_ok") != "true"
            or values.get("result") != "true"
        ):
            raise BridgeError(
                "training owner native level-up choice failed: "
                f"offer_id={offer_id} response={values}"
            )
        record = {
            "participant_id": local_participant_id,
            "target_participant_id": target_participant_id,
            "offer_id": offer_id,
            "option_index": 1,
            "option_count": option_count,
        }
        self.training_owner_level_up_choices.append(record)
        return record

    def wait_for_training_owner_level_up_barrier(
        self,
        *,
        timeout: float = TRAINING_OWNER_LEVEL_UP_RESOLVE_TIMEOUT_SECONDS,
    ) -> list[dict[str, int]]:
        if not math.isfinite(timeout) or timeout <= 0.0:
            raise ValueError("timeout must be finite and positive")
        deadline = time.monotonic() + timeout
        resolved: list[dict[str, int]] = []
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = self.status()
            if last.get("level_up_pause_active") != "true":
                return resolved
            choice = self._resolve_training_owner_level_up_offer(last)
            if choice is not None:
                resolved.append(choice)
            time.sleep(TRAINING_OWNER_LEVEL_UP_POLL_INTERVAL_SECONDS)
        raise BridgeError(
            "training owner level-up barrier did not clear: "
            f"{last}"
        )

    def learned_participant_ids(self) -> tuple[int, ...]:
        values = self.status()
        result = _participant_ids(
            values.get("learned_participant_ids", "")
        )
        expected = int(values.get("learned_bot_count", "0"))
        if len(result) != expected or expected < 1:
            raise BridgeError(
                f"learned participant status is inconsistent: {values}"
            )
        return result

    def in_run_participant_ids(self) -> tuple[int, ...]:
        values = local_sync.parse_key_values(
            self.lua(
                """
local multiplayer = sd.runtime.get_multiplayer_state() or {}
local ids = {}
for _, row in ipairs(multiplayer.participants or {}) do
  local id = tonumber(row.participant_id) or 0
  if id > 0 and row.runtime_valid == true and row.in_run == true then
    ids[#ids + 1] = id
  end
end
table.sort(ids)
local text = {}
for index, id in ipairs(ids) do text[index] = tostring(id) end
print('participant_ids=' .. table.concat(text, ','))
""",
                timeout=10.0,
            )
        )
        result = _participant_ids(values.get("participant_ids", ""))
        if not result:
            raise BridgeError("no in-run participants are available")
        return result

    def trigger_validation_choice_event(
        self,
        participant_id: int,
        *,
        timeout: float = 15.0,
    ) -> dict[str, int]:
        """Trigger one real native level-up for an acceptance smoke.

        This deliberately uses the loader's debug-only native level-sync seam;
        it is never part of ordinary training.  The learned Lua manager still
        owns option scoring and application, and the resulting interval enters
        the normal choice-event-v4 transport.
        """
        if participant_id <= 0:
            raise ValueError("participant_id must be positive")
        if timeout <= 0.0:
            raise ValueError("timeout must be positive")
        before = self.status()
        accepted_before = int(
            before.get("learned_skill_choices_accepted", "0")
        )
        values = local_sync.parse_key_values(
            self.lua(
                f"""
local participant_id = {int(participant_id)}
local choices_before =
  sd.bots.get_skill_choices(participant_id) or {{}}
local state = sd.bots.get_state(participant_id) or {{}}
local progression =
  tonumber(state.progression_runtime_state_address) or 0
local player = sd.player.get_state() or {{}}
local source_progression =
  tonumber(player.progression_address) or 0
local level_offset = assert(
  sd.debug.layout_offset('progression_level'))
local next_xp_offset = assert(
  sd.debug.layout_offset('progression_next_xp_threshold'))
local level = progression > 0 and
  (tonumber(sd.debug.read_i32(
    progression + level_offset)) or 0) or 0
local next_xp = progression > 0 and
  (tonumber(sd.debug.read_float(
    progression + next_xp_offset)) or 0) or 0
local target_level = level + 1
local target_experience = math.ceil(next_xp + 10.0)
local accepted = choices_before.pending ~= true and
  progression > 0 and source_progression > 0 and
  level > 0 and next_xp > 0 and
  sd.bots.debug_sync_level_up({{
    level = target_level,
    experience = target_experience,
    source_progression_address = source_progression,
  }}) == true
print('accepted=' .. tostring(accepted == true))
print('pending_before=' .. tostring(
  choices_before.pending == true))
print('level_before=' .. tostring(level))
print('target_level=' .. tostring(target_level))
print('target_experience=' .. tostring(target_experience))
""",
                timeout=10.0,
            )
        )
        if values.get("accepted") != "true":
            raise BridgeError(
                "native validation level-up was rejected: "
                f"{values}"
            )
        deadline = time.monotonic() + timeout
        last = before
        while time.monotonic() < deadline:
            last = self.status()
            accepted_after = int(
                last.get("learned_skill_choices_accepted", "0")
            )
            if accepted_after > accepted_before:
                return {
                    "participant_id": participant_id,
                    "level_before": int(values["level_before"]),
                    "target_level": int(values["target_level"]),
                    "target_experience": int(
                        values["target_experience"]
                    ),
                    "accepted_before": accepted_before,
                    "accepted_after": accepted_after,
                    "generation": int(
                        last.get("last_skill_choice_generation", "0")
                    ),
                    "option_id": int(
                        last.get("last_skill_choice_option_id", "-1")
                    ),
                }
            time.sleep(0.1)
        raise BridgeError(
            "learned policy did not apply the native validation choice: "
            f"{last}"
        )

    def enable_training(
        self,
        *,
        seed: int,
        capacity: int,
    ) -> dict[str, str]:
        values = local_sync.parse_key_values(
            self.lua(
                f"""
local api = assert(rawget(_G, 'bot_policy_training'))
local status = api.enable({{
  seed={int(seed)},
  capacity={int(capacity)}
}})
print('enabled=' .. tostring(status.enabled))
print('episode_id=' .. tostring(status.episode_id))
print('capacity=' .. tostring(status.capacity))
""",
                timeout=10.0,
            )
        )
        if values.get("enabled") != "true":
            raise BridgeError(f"could not enable policy training: {values}")
        return values

    def disable_training(self) -> dict[str, str]:
        values = local_sync.parse_key_values(
            self.lua(
                """
local status = assert(
  rawget(_G, 'bot_policy_training')).disable()
print('enabled=' .. tostring(status.enabled))
print('buffered=' .. tostring(status.buffered))
""",
                timeout=10.0,
            )
        )
        if values.get("enabled") != "false":
            raise BridgeError(f"could not disable policy training: {values}")
        return values

    def finish_training_episode(self) -> dict[str, str]:
        values = local_sync.parse_key_values(
            self.lua(
                """
local status = assert(
  rawget(_G, 'bot_policy_training')).finish_episode()
print('enabled=' .. tostring(status.enabled))
print('buffered=' .. tostring(status.buffered))
print('choice_buffered=' .. tostring(status.choice_buffered))
""",
                timeout=10.0,
            )
        )
        if values.get("enabled") != "false":
            raise BridgeError(
                f"could not finish policy training episode: {values}"
            )
        return values

    def clear_training(self) -> dict[str, str]:
        return local_sync.parse_key_values(
            self.lua(
                """
local status = assert(
  rawget(_G, 'bot_policy_training')).clear()
print('buffered=' .. tostring(status.buffered))
print('dropped=' .. tostring(status.dropped))
print('recorded=' .. tostring(status.recorded))
print('choice_buffered=' .. tostring(status.choice_buffered))
print('choice_dropped=' .. tostring(status.choice_dropped))
print('choice_recorded=' .. tostring(status.choice_recorded))
""",
                timeout=10.0,
            )
        )

    def clear_main_training_stream(self) -> dict[str, str]:
        values = local_sync.parse_key_values(
            self.lua(
                """
local status = assert(
  rawget(_G, 'bot_policy_training')).clear_main()
print('enabled=' .. tostring(status.enabled))
print('buffered=' .. tostring(status.buffered))
print('recorded=' .. tostring(status.recorded))
print('choice_buffered=' .. tostring(status.choice_buffered))
print('choice_recorded=' .. tostring(status.choice_recorded))
""",
                timeout=10.0,
            )
        )
        if (
            values.get("enabled") != "true"
            or values.get("buffered") != "0"
            or values.get("recorded") != "0"
        ):
            raise BridgeError(
                f"could not reset main training stream: {values}"
            )
        return values

    def load_policy(self, policy: BotPolicy) -> int:
        source = render_lua_weights(policy)
        if not source.isascii():
            raise BridgeError("policy Lua export must be ASCII")
        chunks = [
            source[start : start + POLICY_LOAD_CHUNK_BYTES]
            for start in range(0, len(source), POLICY_LOAD_CHUNK_BYTES)
        ]
        if not chunks:
            raise BridgeError("policy Lua export is empty")
        token = f"{os.getpid()}-{time.time_ns()}"
        quoted_token = json.dumps(token)
        self.lua(
            """
_G.__sdmod_ml_policy_staging = {
  token = %s,
  parts = {},
}
print('staging=true')
""" % quoted_token,
            timeout=10.0,
        )
        try:
            for index, chunk in enumerate(chunks, start=1):
                code = """
local staging = assert(
  rawget(_G, '__sdmod_ml_policy_staging'),
  'policy staging is unavailable')
assert(staging.token == %s, 'policy staging token changed')
staging.parts[%d] = %s
print('part=%d')
""" % (
                    quoted_token,
                    index,
                    _lua_long_string(chunk),
                    index,
                )
                if len(code.encode("utf-8")) >= 1024 * 1024:
                    raise BridgeError(
                        "policy staging request exceeds the loader pipe limit"
                    )
                self.lua(code, timeout=30.0)
            code = """
local staging = assert(
  rawget(_G, '__sdmod_ml_policy_staging'),
  'policy staging is unavailable')
assert(staging.token == %s, 'policy staging token changed')
assert(#staging.parts == %d, 'policy staging is incomplete')
local source = table.concat(staging.parts)
_G.__sdmod_ml_policy_staging = nil
local loader, load_error = load(
  source,
  '@ml-bot-policy-v4-hot-reload',
  't',
  _ENV)
assert(loader, load_error)
local candidate = loader()
local result = assert(
  rawget(_G, 'bot_policy_training')).load_parameters(candidate)
print('generation=' .. tostring(result.generation))
""" % (quoted_token, len(chunks))
            values = local_sync.parse_key_values(
                self.lua(code, timeout=30.0)
            )
        except Exception:
            try:
                self.lua(
                    "_G.__sdmod_ml_policy_staging = nil",
                    timeout=10.0,
                )
            except Exception:
                pass
            raise
        try:
            generation = int(values.get("generation", "0"))
        except ValueError as error:
            raise BridgeError(
                f"policy load returned invalid generation: {values}"
            ) from error
        if generation <= 0:
            raise BridgeError(f"policy load failed: {values}")
        return generation

    def wait_for_rollouts(
        self,
        count: int,
        *,
        timeout: float,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = self.status()
            if last.get("level_up_pause_active") == "true":
                self.wait_for_training_owner_level_up_barrier(
                    timeout=min(
                        TRAINING_OWNER_LEVEL_UP_RESOLVE_TIMEOUT_SECONDS,
                        max(deadline - time.monotonic(), 0.01),
                    )
                )
                continue
            if int(last.get("buffered", "0")) >= count:
                return last
            time.sleep(0.2)
        raise BridgeError(
            f"timed out waiting for {count} rollouts: {last}"
        )

    def _drain_rollout_chunk(self, count: int) -> list[RolloutRecord]:
        if count <= 0 or count > MAX_ROLLOUTS_PER_RESPONSE:
            raise ValueError(
                "rollout chunk count must be between 1 and "
                f"{MAX_ROLLOUTS_PER_RESPONSE}"
            )
        code = f"""
local api = assert(rawget(_G, 'bot_policy_training'))
local drained = api.drain({int(count)})
for _, record in ipairs(drained.records or {{}}) do
  local observation = {{}}
  for index, value in ipairs(record.observation or {{}}) do
    observation[index] = string.format('%.17g', value)
  end
  local movement_mask = {{}}
  for index, value in ipairs(record.movement_mask or {{}}) do
    movement_mask[index] = value and '1' or '0'
  end
  local target_mask = {{}}
  for index, value in ipairs(record.target_mask or {{}}) do
    target_mask[index] = value and '1' or '0'
  end
  local ability_mask = {{}}
  for index, value in ipairs(record.ability_mask or {{}}) do
    ability_mask[index] = value and '1' or '0'
  end
  local aim_mask = {{}}
  for index, value in ipairs(record.aim_mask or {{}}) do
    aim_mask[index] = value and '1' or '0'
  end
  print(table.concat({{
    'R',
    tostring(record.trajectory_version),
    tostring(record.episode_id),
    tostring(record.participant_id),
    tostring(record.simulation_tick),
    tostring(record.movement_action),
    tostring(record.target_action),
    tostring(record.ability_action),
    tostring(record.aim_action),
    string.format('%.17g', record.old_log_probability),
    string.format('%.17g', record.old_value),
    string.format('%.17g', record.reward),
    record.done and '1' or '0',
    table.concat(observation, ','),
    table.concat(movement_mask),
    table.concat(target_mask),
    table.concat(ability_mask),
    table.concat(aim_mask)
  }}, '\\t'))
end
print('buffered=' .. tostring(
  drained.status and drained.status.buffered or 0))
"""
        output = self.lua(code, timeout=30.0)
        return parse_rollout_output(output, expected_count=count)

    def drain_rollouts(self, count: int) -> list[RolloutRecord]:
        if count <= 0:
            raise ValueError("rollout count must be positive")
        records: list[RolloutRecord] = []
        while len(records) < count:
            chunk_count = min(
                count - len(records),
                MAX_ROLLOUTS_PER_RESPONSE,
            )
            records.extend(self._drain_rollout_chunk(chunk_count))
        return records

    def wait_for_choice_rollouts(
        self,
        count: int,
        *,
        timeout: float,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = self.status()
            if int(last.get("choice_buffered", "0")) >= count:
                return last
            time.sleep(0.2)
        raise BridgeError(
            f"timed out waiting for {count} choice rollouts: {last}"
        )

    def _drain_choice_rollout_chunk(
        self,
        count: int,
    ) -> list[ChoiceRolloutRecord]:
        if count <= 0 or count > MAX_CHOICE_ROLLOUTS_PER_RESPONSE:
            raise ValueError(
                "choice rollout chunk count must be between 1 and "
                f"{MAX_CHOICE_ROLLOUTS_PER_RESPONSE}"
            )
        code = f"""
local api = assert(rawget(_G, 'bot_policy_training'))
-- Include tagged scripted events in the transport so count continues to mean
-- the exact number of buffered records consumed. The trainer partitions the
-- strict mode/trainable fields and never admits scripted rows to choice PPO.
local drained = api.drain_choices({int(count)}, true)
for _, record in ipairs(drained.records or {{}}) do
  local observation = {{}}
  for index, value in ipairs(record.observation or {{}}) do
    observation[index] = string.format('%.17g', value)
  end
  local option_mask = {{}}
  for index, value in ipairs(record.option_mask or {{}}) do
    option_mask[index] = value and '1' or '0'
  end
  local descriptors = {{}}
  for row_index, row in ipairs(record.option_descriptors or {{}}) do
    local values = {{}}
    for column, value in ipairs(row) do
      values[column] = string.format('%.17g', value)
    end
    descriptors[row_index] = table.concat(values, ',')
  end
  local rewards = {{}}
  for index, value in ipairs(record.rewards or {{}}) do
    rewards[index] = string.format('%.17g', value)
  end
  print(table.concat({{
    'C',
    tostring(record.choice_trajectory_version),
    tostring(record.episode_id),
    tostring(record.participant_id),
    tostring(record.generation),
    tostring(record.simulation_tick),
    tostring(record.selected_option),
    string.format('%.17g', record.old_log_probability),
    string.format('%.17g', record.old_value),
    string.format('%.17g', record.next_value),
    tostring(record.duration_steps),
    record.done and '1' or '0',
    record.trainable and '1' or '0',
    record.accepted and '1' or '0',
    tostring(record.choice_mode),
    table.concat(observation, ','),
    table.concat(option_mask),
    table.concat(descriptors, ';'),
    table.concat(rewards, ',')
  }}, '\t'))
end
print('choice_buffered=' .. tostring(
  drained.status and drained.status.choice_buffered or 0))
"""
        output = self.lua(code, timeout=30.0)
        return parse_choice_rollout_output(output, expected_count=count)

    def drain_choice_rollouts(
        self,
        count: int,
    ) -> list[ChoiceRolloutRecord]:
        if count <= 0:
            raise ValueError("choice rollout count must be positive")
        records: list[ChoiceRolloutRecord] = []
        while len(records) < count:
            chunk_count = min(
                count - len(records),
                MAX_CHOICE_ROLLOUTS_PER_RESPONSE,
            )
            records.extend(self._drain_choice_rollout_chunk(chunk_count))
        return records
