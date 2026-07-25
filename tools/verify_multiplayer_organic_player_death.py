#!/usr/bin/env python3
"""Verify player death from stock enemy damage in connected multiplayer."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable

from multiplayer_frame_capture import capture_game_backbuffer
from multiplayer_log_probe import log_after, log_position
from multiplayer_natural_defense_harness import (
    ARM_ENEMY_ARENA_LUA,
    SET_ENEMY_MODE_LUA,
)
from normal_gameplay_debug_surface_guard import (
    assert_launch_debug_surfaces_empty,
)
from spectator_product_hud_guard import (
    assert_latest_spectator_product_hud_state,
    assert_spectator_product_hud_lifecycle,
    assert_spectator_product_hud_never_visible,
    parse_spectator_product_hud_states,
    wait_for_spectator_product_hud_state,
)
from spectator_product_hud_visual import (
    inspect_spectator_product_hud_pixels,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    select_available_windows_udp_ports,
    start_testrun,
    stop_exact_game_processes,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_death_spectator_respawn import (
    _arm_death_traces,
    _disarm_death_traces,
    query_remote_death_state,
    query_spectator_state,
    query_spectator_target_death_state,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    Direction,
    clear_gameplay_mouse_left,
    queue_gameplay_mouse_left,
    wait_for_source_cast,
)


OUTPUT = ROOT / "runtime" / "multiplayer_organic_player_death.json"
SCREENSHOT_ROOT = ROOT / "runtime" / "multiplayer_organic_player_death"
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
SURVIVOR_HP = 5000.0
VICTIM_ARMING_HP = 0.1
VICTIM_MAX_HP = 50.0
CAST_HOLD_FRAMES = 3600
PRESENTATION_PHASE_SYNC_TOLERANCE_TICKS = 12.0
DEATH_PRESENTATION_SECONDS = 5.0
NATIVE_RED_SAFE_TICK = 150
NATIVE_TERMINAL_CORPSE_TICK = 159
CORPSE_POSITION_TOLERANCE = 0.25
SPECTATOR_CAMERA_TOLERANCE = 0.25
SINGLE_TARGET_SAMPLE_SECONDS = 0.8
DEAD_INPUT_SETTLE_SECONDS = 1.0
ATTACKER_STABILIZED_HP = 5000.0
VICTIM_TARGET_X = 1850.0
VICTIM_TARGET_Y = 1750.0
HOST_SURVIVOR_TARGET_X = 2350.0
PLAYER_TARGET_HEADING = 180.0
TARGET_LAYOUT_STABLE_SAMPLES = 3
TARGET_LAYOUT_STABLE_TOLERANCE = 1.0
TARGET_LAYOUT_MINIMUM_X_SEPARATION = 192.0
TARGET_LAYOUT_PLACEMENT_ATTEMPTS = 4
TARGET_LAYOUT_ATTEMPT_TIMEOUT_SECONDS = 2.0

HOST_NATIVE_TARGET_LAYOUT_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local player = sd.player and sd.player.get_state and
  sd.player.get_state() or nil
local client = sd.bots and sd.bots.get_participant_state and
  sd.bots.get_participant_state(__CLIENT_PARTICIPANT_ID__) or nil
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local host_actor = tonumber(player and player.actor_address) or 0
local client_actor = tonumber(client and client.actor_address) or 0
local function native_position(actor, offset)
  if actor == 0 or offset == nil then return 0 end
  return tonumber(sd.debug.read_float(actor + offset)) or 0
end
emit("host_actor", host_actor)
emit("host_x", native_position(host_actor, ox))
emit("host_y", native_position(host_actor, oy))
emit("client_actor", client_actor)
emit("client_x", native_position(client_actor, ox))
emit("client_y", native_position(client_actor, oy))
"""

WAVE_FIXTURES = {
    "melee": (
        ROOT / "tests" / "fixtures" / "waves"
        / "organic_death_melee_test.txt"
    ),
    "projectile": (
        ROOT / "tests" / "fixtures" / "waves"
        / "organic_death_projectile_test.txt"
    ),
    "poison": (
        ROOT / "tests" / "fixtures" / "waves"
        / "organic_death_poison_test.txt"
    ),
}
EXPECTED_BASE_ACTOR_OBJECT_TYPE = 1001
LIFECYCLE_TIMEOUT_SECONDS = {
    "melee": 18.0,
    "projectile": 18.0,
    "poison": 35.0,
}


class OrganicDeathFailure(VerifyFailure):
    """Live verifier failure that retains the evidence captured so far."""

    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


ARM_DAMAGE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
_G.__sdmod_organic_death_damage_probe = {
  events = {},
  limit = 128,
}
if not _G.__sdmod_organic_death_damage_probe_registered then
  sd.events.filter("damage.taken", function(event)
    local probe = _G.__sdmod_organic_death_damage_probe
    if type(probe) == "table" and #probe.events < probe.limit then
      probe.events[#probe.events + 1] = {
        target = tonumber(event.target_participant_id) or 0,
        source = tonumber(event.source_participant_id) or 0,
        target_actor = tonumber(event.target_actor_address) or 0,
        source_actor = tonumber(event.source_actor_address) or 0,
        flags = tonumber(event.flags) or 0,
        projectile = tonumber(event.projectile_damage) or 0,
        magic = tonumber(event.magic_damage) or 0,
        total = tonumber(event.total_damage) or 0,
      }
    end
    return nil
  end)
  _G.__sdmod_organic_death_damage_probe_registered = true
end
emit("registered", _G.__sdmod_organic_death_damage_probe_registered)
emit("count", #_G.__sdmod_organic_death_damage_probe.events)
"""


QUERY_DAMAGE_PROBE = r"""
local probe = _G.__sdmod_organic_death_damage_probe
if type(probe) ~= "table" then error("organic death damage probe unavailable") end
for index, event in ipairs(probe.events or {}) do
  print(table.concat({
    "D",
    tostring(index),
    tostring(event.target or 0),
    tostring(event.source or 0),
    tostring(event.target_actor or 0),
    tostring(event.source_actor or 0),
    tostring(event.flags or 0),
    string.format("%.6f", event.projectile or 0),
    string.format("%.6f", event.magic or 0),
    string.format("%.6f", event.total or 0),
  }, "|"))
end
"""


LIVE_ENEMY_PROBE = r"""
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    print(table.concat({
      "A",
      tostring(tonumber(actor.actor_address) or 0),
      tostring(tonumber(actor.object_type_id) or 0),
      string.format("%.6f", tonumber(actor.x) or 0),
      string.format("%.6f", tonumber(actor.y) or 0),
      string.format("%.6f", tonumber(actor.hp) or 0),
    }, "|"))
  end
end
"""


STABILIZE_SELECTED_ENEMY_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local address = __ENEMY_ACTOR_ADDRESS__
local target_hp = __TARGET_HP__
local found = false
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if tonumber(actor.actor_address) == address and actor.tracked_enemy and
      not actor.dead then
    found = true
    break
  end
end
if not found then
  emit("ok", false)
  emit("actor_address", address)
  return
end
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local progression_offset =
  sd.debug.layout_offset("actor_progression_runtime_state")
local progression_hp_offset = sd.debug.layout_offset("progression_hp")
local progression_max_hp_offset =
  sd.debug.layout_offset("progression_max_hp")
sd.debug.write_float(address + max_hp_offset, target_hp)
sd.debug.write_float(address + hp_offset, target_hp)
local progression =
  tonumber(sd.debug.read_ptr(address + progression_offset)) or 0
if progression ~= 0 then
  sd.debug.write_float(
    progression + progression_max_hp_offset, target_hp)
  sd.debug.write_float(progression + progression_hp_offset, target_hp)
end
emit("ok", true)
emit("actor_address", address)
emit("hp", target_hp)
"""


KILL_LIVE_WAVE_ENEMIES = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local attempted = 0
local accepted = 0
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local progression_offset =
  sd.debug.layout_offset("actor_progression_runtime_state")
local progression_hp_offset = sd.debug.layout_offset("progression_hp")
local progression_max_hp_offset =
  sd.debug.layout_offset("progression_max_hp")
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead and
      (tonumber(actor.hp) or 0) > 0 then
    attempted = attempted + 1
    local address = tonumber(actor.actor_address) or 0
    local max_hp = tonumber(actor.max_hp) or 1
    sd.debug.write_float(address + max_hp_offset, math.max(max_hp, 1))
    sd.debug.write_float(address + hp_offset, 0)
    local progression =
      tonumber(sd.debug.read_ptr(address + progression_offset)) or 0
    if progression ~= 0 then
      sd.debug.write_float(
        progression + progression_max_hp_offset,
        math.max(max_hp, 1))
      sd.debug.write_float(progression + progression_hp_offset, 0)
    end
    if sd.world.trigger_enemy_death(actor.actor_address) then
      accepted = accepted + 1
    end
  end
end
emit("attempted", attempted)
emit("accepted", accepted)
"""


WAVE_STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local state = assert(sd.waves.get_state())
emit("phase", state and state.phase or "")
emit("wave", state and state.wave or 0)
emit("alive", state and state.alive or 0)
"""


POISON_STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
emit("available", player ~= nil)
emit("hp", player and player.hp or 0)
emit("poison_remaining_ticks",
  player and player.poison_remaining_ticks or 0)
"""


ARM_DEAD_INPUT_WORLD_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local probe = {
  active = false,
  baseline = {},
  seen = {},
}
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 then probe.baseline[address] = true end
end
_G.__sdmod_dead_input_world_probe = probe
if not _G.__sdmod_dead_input_world_probe_registered then
  sd.events.on("runtime.tick", function()
    local current = _G.__sdmod_dead_input_world_probe
    if type(current) ~= "table" or not current.active then return end
    for _, actor in ipairs(
        sd.world.list_actors and sd.world.list_actors() or {}) do
      local address = tonumber(actor.actor_address) or 0
      if address ~= 0 and not current.baseline[address] then
        current.seen[address] = {
          object_type_id = tonumber(actor.object_type_id) or 0,
          owner_address = tonumber(actor.owner_address) or 0,
          tracked_enemy = actor.tracked_enemy == true,
        }
      end
    end
  end)
  _G.__sdmod_dead_input_world_probe_registered = true
end
probe.active = true
emit("armed", true)
local baseline_count = 0
for _ in pairs(probe.baseline) do baseline_count = baseline_count + 1 end
emit("baseline_count", baseline_count)
"""


QUERY_DEAD_INPUT_WORLD_PROBE = r"""
local probe = _G.__sdmod_dead_input_world_probe
if type(probe) ~= "table" then error("dead input world probe unavailable") end
probe.active = false
local addresses = {}
for address in pairs(probe.seen or {}) do addresses[#addresses + 1] = address end
table.sort(addresses)
print("count=" .. tostring(#addresses))
for _, address in ipairs(addresses) do
  local actor = probe.seen[address]
  print(table.concat({
    "W",
    tostring(address),
    tostring(actor.object_type_id or 0),
    tostring(actor.owner_address or 0),
    tostring(actor.tracked_enemy == true),
  }, "|"))
end
"""


RESET_DEAD_INPUT_MANA_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
emit("armed", sd.debug.reset_local_cast_observation(1))
"""


QUERY_DEAD_INPUT_MANA_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local observation = assert(sd.debug.get_local_cast_observation(1))
emit("mana_valid", observation.mana_valid)
emit("mana_spend_call_count", observation.mana_spend_call_count or 0)
emit("mana_spent_total", observation.mana_spent_total or 0)
"""


def _read_wave_fixture_enemy_token(fixture_path: Path) -> str:
    tokens: list[str] = []
    inside_group = False
    for line in fixture_path.read_text(encoding="ascii").splitlines():
        token = line.strip()
        if token == "GROUP":
            inside_group = True
            continue
        if token == "ENDWAVE":
            inside_group = False
            continue
        if inside_group and token:
            tokens.append(token)
    if len(tokens) != 1:
        raise VerifyFailure(
            "organic wave fixture must contain exactly one stock enemy token: "
            f"{fixture_path} contained {tokens}"
        )
    return tokens[0]


def _materialize_native_wave_schedule(
    *,
    retail_wave_path: Path,
    fixture_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    retail_bytes = retail_wave_path.read_bytes()
    retail_text = retail_bytes.decode("ascii")
    normalized = retail_text.replace("\r\n", "\n").replace("\r", "\n")
    record_pattern = re.compile(
        r"^WAVE[ \t]*\n(?P<body>.*?)^[ \t]*ENDWAVE[ \t]*(?:\n|$)",
        re.MULTILINE | re.DOTALL,
    )
    matches = list(record_pattern.finditer(normalized))
    if not matches:
        raise VerifyFailure(
            f"retail wave schedule has no native WAVE records: "
            f"{retail_wave_path}"
        )

    cursor = 0
    for match in matches:
        if normalized[cursor:match.start()].strip():
            raise VerifyFailure(
                "retail wave schedule contains unsupported content outside "
                f"WAVE records: {retail_wave_path}"
            )
        cursor = match.end()
    trailing_lines = {
        line.strip()
        for line in normalized[cursor:].splitlines()
        if line.strip()
    }
    if trailing_lines - {"ENDWAVE"}:
        raise VerifyFailure(
            "retail wave schedule contains trailing content outside WAVE "
            f"records: {retail_wave_path}"
        )

    enemy_token = _read_wave_fixture_enemy_token(fixture_path)
    next_graph: list[str] = []
    effective_records: list[str] = []
    for match in matches:
        next_values = re.findall(
            r"^[ \t]*NEXT:([^\n]*)$",
            match.group("body"),
            re.MULTILINE,
        )
        if len(next_values) != 1:
            raise VerifyFailure(
                "each native WAVE record must contain exactly one NEXT edge: "
                f"{retail_wave_path}"
            )
        next_value = next_values[0].strip()
        next_graph.append(next_value)
        effective_records.append(
            "\n".join(
                (
                    "WAVE",
                    f"\tNEXT:{next_value}",
                    "\tSPAWN:1",
                    "\tSPAWNDELAY:1-1",
                    "\tWAVEDELAY:100-100",
                    "\tMAXENEMIES:1",
                    "\tGROUP",
                    f"\t\t{enemy_token}",
                    "\tENDWAVE",
                    "",
                )
            )
        )

    effective_bytes = "".join(effective_records).replace(
        "\n",
        "\r\n",
    ).encode("ascii")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(effective_bytes)
    return {
        "retail_path": str(retail_wave_path.resolve()),
        "fixture_path": str(fixture_path.resolve()),
        "effective_path": str(output_path.resolve()),
        "record_count": len(matches),
        "next_graph": next_graph,
        "enemy_token": enemy_token,
        "retail_sha256": hashlib.sha256(retail_bytes).hexdigest(),
        "fixture_sha256": hashlib.sha256(
            fixture_path.read_bytes()
        ).hexdigest(),
        "effective_sha256": hashlib.sha256(effective_bytes).hexdigest(),
    }


def _parse_live_enemy_probe(
    text: str,
) -> list[dict[str, int | float]]:
    actors: list[dict[str, int | float]] = []
    for line in text.splitlines():
        if not line.startswith("A|"):
            continue
        parts = line.split("|")
        if len(parts) != 6:
            raise VerifyFailure(f"malformed live enemy record: {line!r}")
        actors.append(
            {
                "actor_address": int(parts[1]),
                "object_type_id": int(parts[2]),
                "x": float(parts[3]),
                "y": float(parts[4]),
                "hp": float(parts[5]),
            }
        )
    return actors


def _query_live_enemies(host_pipe: str) -> list[dict[str, int | float]]:
    return _parse_live_enemy_probe(lua(host_pipe, LIVE_ENEMY_PROBE))


def _select_new_wave_enemy(
    actors: list[dict[str, int | float]],
    *,
    pre_wave_actor_addresses: set[int],
) -> dict[str, int | float]:
    for actor in actors:
        actor_address = int(actor["actor_address"])
        if (
            actor_address not in pre_wave_actor_addresses
            and int(actor["object_type_id"])
                == EXPECTED_BASE_ACTOR_OBJECT_TYPE
        ):
            return {
                **actor,
                "expected_base_actor_object_type":
                    EXPECTED_BASE_ACTOR_OBJECT_TYPE,
            }
    raise VerifyFailure(
        "new native-wave enemy did not appear outside the pre-wave "
        f"Boneyard actor set: {sorted(pre_wave_actor_addresses)}"
    )


def _default_instance_prefix() -> str:
    return f"orgd-{os.getpid():x}-{uuid.uuid4().hex[:4]}"


def _death_target_positions(
    victim_role: str,
) -> dict[str, tuple[float, float]]:
    victim = (VICTIM_TARGET_X, VICTIM_TARGET_Y)
    survivor = (HOST_SURVIVOR_TARGET_X, VICTIM_TARGET_Y)
    if victim_role == "host":
        return {"host": victim, "client": survivor}
    if victim_role == "client":
        return {"host": survivor, "client": victim}
    raise ValueError(f"unsupported victim role: {victim_role}")


def _launch_log_path(
    launch: dict[str, object],
    key: str,
) -> Path:
    raw_path = launch.get(key)
    if not isinstance(raw_path, str) or not raw_path:
        raise VerifyFailure(f"pair launch omitted {key}: {launch}")
    if os.name == "nt" or raw_path.startswith("/"):
        return Path(raw_path)
    completed = subprocess.run(
        ["wslpath", "-u", raw_path],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    converted = completed.stdout.strip()
    if completed.returncode != 0 or not converted:
        raise VerifyFailure(
            f"could not convert pair-launch {key} {raw_path!r}: "
            f"{completed.stderr or completed.stdout}"
        )
    return Path(converted)


def _wait_for_host_native_target_layout(
    host_pipe: str,
    timeout: float = 6.0,
) -> dict[str, Any]:
    code = HOST_NATIVE_TARGET_LAYOUT_LUA.replace(
        "__CLIENT_PARTICIPANT_ID__",
        str(CLIENT_ID),
    )
    deadline = time.monotonic() + timeout
    stable_samples = 0
    attempts = 0
    previous: tuple[float, float, float, float] | None = None
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        values = parse_key_values(lua(host_pipe, code, timeout=5.0))
        attempts += 1
        positions = (
            float(values.get("host_x", "nan")),
            float(values.get("host_y", "nan")),
            float(values.get("client_x", "nan")),
            float(values.get("client_y", "nan")),
        )
        host_x, host_y, client_x, client_y = positions
        settled = (
            previous is not None
            and math.hypot(host_x - previous[0], host_y - previous[1])
                <= TARGET_LAYOUT_STABLE_TOLERANCE
            and math.hypot(client_x - previous[2], client_y - previous[3])
                <= TARGET_LAYOUT_STABLE_TOLERANCE
        )
        x_separation = abs(host_x - client_x)
        last = {
            **values,
            "attempts": attempts,
            "x_separation": x_separation,
        }
        if (
            int(values.get("host_actor", "0")) != 0
            and int(values.get("client_actor", "0")) != 0
            and all(math.isfinite(value) for value in positions)
            and x_separation >= TARGET_LAYOUT_MINIMUM_X_SEPARATION
            and settled
        ):
            stable_samples += 1
            if stable_samples >= TARGET_LAYOUT_STABLE_SAMPLES:
                return {
                    **last,
                    "stable_samples": stable_samples,
                    "stable_tolerance":
                        TARGET_LAYOUT_STABLE_TOLERANCE,
                    "minimum_x_separation":
                        TARGET_LAYOUT_MINIMUM_X_SEPARATION,
                }
        else:
            stable_samples = 0
        previous = positions
        time.sleep(0.05)
    raise VerifyFailure(
        "host authority did not observe separated stable death targets: "
        f"{last}"
    )


def _place_and_wait_for_death_target_layout(
    *,
    host_pipe: str,
    client_pipe: str,
    victim_role: str,
) -> dict[str, Any]:
    target_positions = _death_target_positions(victim_role)
    placement_attempts: list[dict[str, Any]] = []
    last_error = ""
    for attempt in range(1, TARGET_LAYOUT_PLACEMENT_ATTEMPTS + 1):
        placement = {
            "attempt": attempt,
            "host": place_player(
                host_pipe,
                *target_positions["host"],
                PLAYER_TARGET_HEADING,
            ),
            "client": place_player(
                client_pipe,
                *target_positions["client"],
                PLAYER_TARGET_HEADING,
            ),
        }
        placement_attempts.append(placement)
        try:
            authority = _wait_for_host_native_target_layout(
                host_pipe,
                timeout=TARGET_LAYOUT_ATTEMPT_TIMEOUT_SECONDS,
            )
        except VerifyFailure as exc:
            last_error = str(exc)
            placement["authority_error"] = last_error
            continue
        return {
            "host": placement["host"],
            "client": placement["client"],
            "host_authority": authority,
            "placement_attempts": placement_attempts,
        }
    raise VerifyFailure(
        "host-authoritative run-entry formation kept overriding the "
        f"separated death target layout: {last_error}"
    )


def _start_testrun_when_ready(host_pipe: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            start_testrun(host_pipe)
            return
        except VerifyFailure as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise VerifyFailure(
        f"host testrun request never reached spawn readiness: {last_error}"
    )


def _disable_companion_bots(pipe_names: list[str]) -> None:
    code = (
        "lua_bots_disable_tick = true; sd.bots.clear(); "
        "return tostring(sd.bots.get_count())"
    )
    for pipe_name in pipe_names:
        if lua(pipe_name, code).strip() != "0":
            raise VerifyFailure(
                f"failed to disable companion bots on {pipe_name}"
            )


def _start_waves(host_pipe: str) -> dict[str, str]:
    values = parse_key_values(
        lua(
            host_pipe,
            "print('ok=' .. tostring(sd.gameplay.start_waves()))",
        )
    )
    if values.get("ok") != "true":
        raise VerifyFailure(f"host could not start organic combat: {values}")
    return values


def _wait_for_new_wave_enemy(
    host_pipe: str,
    *,
    pre_wave_actor_addresses: set[int],
    timeout: float = 20.0,
) -> dict[str, int | float]:
    deadline = time.monotonic() + timeout
    last: list[dict[str, int | float]] = []
    while time.monotonic() < deadline:
        last = _query_live_enemies(host_pipe)
        try:
            return _select_new_wave_enemy(
                last,
                pre_wave_actor_addresses=pre_wave_actor_addresses,
            )
        except VerifyFailure:
            pass
        time.sleep(0.1)
    raise VerifyFailure(
        "stock schedule did not produce a new native-wave enemy after "
        f"excluding pre-wave addresses "
        f"{sorted(pre_wave_actor_addresses)}: {last}"
    )


def _arm_enemy_arena(
    host_pipe: str,
    target_x: float,
    target_y: float,
) -> dict[str, str]:
    code = (
        ARM_ENEMY_ARENA_LUA
        .replace("__TARGET_X__", f"{target_x:.6f}")
        .replace("__TARGET_Y__", f"{target_y:.6f}")
    )
    values = parse_key_values(lua(host_pipe, code, timeout=10.0))
    if values.get("ok") != "true":
        raise VerifyFailure(f"failed to arm organic enemy arena: {values}")
    return values


def _stabilize_enemy(
    host_pipe: str,
    *,
    enemy_actor_address: int,
) -> dict[str, str]:
    code = (
        STABILIZE_SELECTED_ENEMY_LUA
        .replace("__ENEMY_ACTOR_ADDRESS__", str(enemy_actor_address))
        .replace("__TARGET_HP__", f"{ATTACKER_STABILIZED_HP:.6f}")
    )
    values = parse_key_values(lua(host_pipe, code, timeout=10.0))
    if (
        values.get("ok") != "true"
        or int(values.get("actor_address", "0")) != enemy_actor_address
    ):
        raise VerifyFailure(
            f"failed to stabilize selected organic attacker: {values}"
        )
    return values


def _set_enemy_attack(
    host_pipe: str,
    *,
    target_x: float,
    target_y: float,
    target_participant_id: int,
    enemy_actor_address: int,
    attack_distance: float,
    timeout: float = 10.0,
) -> dict[str, str]:
    code = (
        SET_ENEMY_MODE_LUA
        .replace("__MODE__", "attack")
        .replace("__TARGET_X__", f"{target_x:.6f}")
        .replace("__TARGET_Y__", f"{target_y:.6f}")
        .replace("__ATTACK_DISTANCE__", f"{attack_distance:.6f}")
        .replace("__ENEMY_ACTOR_ADDRESS__", str(enemy_actor_address))
        .replace("__TARGET_PARTICIPANT_ID__", str(target_participant_id))
    )
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_key_values(lua(host_pipe, code, timeout=10.0))
        if (
            last.get("ok") == "true"
            and int(last.get("count", "0")) >= 1
            and int(last.get("target_actor", "0")) != 0
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"organic enemy could not target victim: {last}")


def _set_enemy_idle(host_pipe: str) -> dict[str, str]:
    code = (
        SET_ENEMY_MODE_LUA
        .replace("__MODE__", "idle")
        .replace("__TARGET_X__", "0.0")
        .replace("__TARGET_Y__", "0.0")
        .replace("__ATTACK_DISTANCE__", "0.0")
        .replace("__ENEMY_ACTOR_ADDRESS__", "0")
        .replace("__TARGET_PARTICIPANT_ID__", "0")
    )
    values = parse_key_values(lua(host_pipe, code, timeout=10.0))
    if values.get("ok") != "true":
        raise VerifyFailure(
            f"organic enemy arena could not become idle: {values}"
        )
    return values


def _wait_for_victim_damage(
    victim_pipe: str,
    *,
    baseline_hp: float,
    timeout: float,
) -> dict[str, float]:
    deadline = time.monotonic() + timeout
    minimum_hp = baseline_hp
    while time.monotonic() < deadline:
        current = query_spectator_state(victim_pipe)
        current_hp = float(current.get("hp", "0"))
        minimum_hp = min(minimum_hp, current_hp)
        if current_hp < baseline_hp - 0.01:
            return {
                "baseline_hp": baseline_hp,
                "observed_hp": current_hp,
                "damage": baseline_hp - current_hp,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        "selected new native-wave enemy did not produce a real victim HP "
        f"decrement: baseline={baseline_hp} minimum={minimum_hp}"
    )


def _parse_damage_probe(text: str) -> list[dict[str, int | float]]:
    events: list[dict[str, int | float]] = []
    for line in text.splitlines():
        if not line.startswith("D|"):
            continue
        parts = line.split("|")
        if len(parts) != 10:
            raise VerifyFailure(f"malformed damage probe record: {line!r}")
        events.append(
            {
                "index": int(parts[1]),
                "target_participant_id": int(parts[2]),
                "source_participant_id": int(parts[3]),
                "target_actor_address": int(parts[4]),
                "source_actor_address": int(parts[5]),
                "flags": int(parts[6]),
                "projectile_damage": float(parts[7]),
                "magic_damage": float(parts[8]),
                "total_damage": float(parts[9]),
            }
        )
    return events


def _parse_dead_input_world_probe(
    text: str,
) -> list[dict[str, int | bool]]:
    actors: list[dict[str, int | bool]] = []
    for line in text.splitlines():
        if not line.startswith("W|"):
            continue
        parts = line.split("|")
        if len(parts) != 5:
            raise VerifyFailure(
                f"malformed dead-input world record: {line!r}"
            )
        actors.append(
            {
                "actor_address": int(parts[1]),
                "object_type_id": int(parts[2]),
                "owner_address": int(parts[3]),
                "tracked_enemy": parts[4] == "true",
            }
        )
    return actors


def _count_log_markers(text: str, markers: tuple[str, ...]) -> int:
    return sum(text.count(marker) for marker in markers)


def _attempt_dead_gameplay_inputs(
    *,
    direction: Direction,
    victim_pipe: str,
    observer_pipe: str,
) -> dict[str, Any]:
    before = query_spectator_state(victim_pipe)
    if (
        before.get("active") != "true"
        or before.get("phase") != "Spectating"
        or int(before.get("death_drive_state", "0")) == 0
        or before.get("red_effect_active") != "false"
    ):
        raise VerifyFailure(
            "dead-input lockout requires an active dead spectator: "
            f"{_small_state(before)}"
        )

    victim_world_probe = parse_key_values(
        lua(victim_pipe, ARM_DEAD_INPUT_WORLD_PROBE)
    )
    observer_world_probe = parse_key_values(
        lua(observer_pipe, ARM_DEAD_INPUT_WORLD_PROBE)
    )
    mana_probe = parse_key_values(
        lua(victim_pipe, RESET_DEAD_INPUT_MANA_PROBE)
    )
    if (
        victim_world_probe.get("armed") != "true"
        or observer_world_probe.get("armed") != "true"
        or mana_probe.get("armed") != "true"
    ):
        raise VerifyFailure(
            "dead-input observation probes failed to arm: "
            f"victim={victim_world_probe} "
            f"observer={observer_world_probe} mana={mana_probe}"
        )

    victim_log_offset = log_position(direction.source_log)
    observer_log_offset = log_position(direction.receiver_log)
    mana_before = float(before.get("mp", "0"))
    primary_input = queue_gameplay_mouse_left(direction, 12)
    secondary_input = parse_key_values(
        lua(
            victim_pipe,
            """
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local ok, result = pcall(sd.input.press_binding, "belt_slot_1")
emit("pcall_ok", ok)
emit("result", result)
""",
        )
    )
    if (
        secondary_input.get("pcall_ok") != "true"
        or secondary_input.get("result") != "true"
    ):
        raise VerifyFailure(
            f"dead secondary input could not be attempted: {secondary_input}"
        )
    time.sleep(DEAD_INPUT_SETTLE_SECONDS)
    clear_result = clear_gameplay_mouse_left(direction)

    after = query_spectator_state(victim_pipe)
    mana_after = float(after.get("mp", "0"))
    mana_observation = parse_key_values(
        lua(victim_pipe, QUERY_DEAD_INPUT_MANA_PROBE)
    )
    victim_new_actors = _parse_dead_input_world_probe(
        lua(victim_pipe, QUERY_DEAD_INPUT_WORLD_PROBE)
    )
    observer_new_actors = _parse_dead_input_world_probe(
        lua(observer_pipe, QUERY_DEAD_INPUT_WORLD_PROBE)
    )
    victim_log_text = log_after(direction.source_log, victim_log_offset)
    observer_log_text = log_after(
        direction.receiver_log,
        observer_log_offset,
    )
    dead_input_local_cast_log_count = _count_log_markers(
        victim_log_text,
        (
            "Multiplayer local primary cast queued from native",
            "Multiplayer local secondary cast queued from native dispatcher",
            "Multiplayer local cast sent.",
            "lua_spells: queued selected input cast.",
        ),
    )
    dead_input_remote_cast_log_count = _count_log_markers(
        observer_log_text,
        (
            "Multiplayer remote cast queued.",
            "Multiplayer remote secondary cast queued.",
            "lua_spells: accepted owner-routed cast.",
        ),
    )
    dead_input_new_world_effect_actor_count = (
        len(victim_new_actors) + len(observer_new_actors)
    )
    dead_input_mana_delta = mana_after - mana_before
    mana_spend_call_count = int(
        mana_observation.get("mana_spend_call_count", "0")
    )
    mana_spent_total = float(
        mana_observation.get("mana_spent_total", "0")
    )
    dead_input_authority_rejection_matches = (
        dead_input_local_cast_log_count == 0
        and dead_input_remote_cast_log_count == 0
    )
    dead_input_lockout_matches = (
        dead_input_authority_rejection_matches
        and dead_input_new_world_effect_actor_count == 0
        and mana_spend_call_count == 0
        and abs(mana_spent_total) <= 0.001
        and after.get("active") == "true"
        and after.get("phase") == "Spectating"
        and int(after.get("death_drive_state", "0")) != 0
        and after.get("red_effect_active") == "false"
        and int(after.get("death_presentation_ticks", "0")) <= 150
    )
    evidence = {
        "dead_input_lockout_matches": dead_input_lockout_matches,
        "dead_input_authority_rejection_matches":
            dead_input_authority_rejection_matches,
        "dead_input_new_world_effect_actor_count":
            dead_input_new_world_effect_actor_count,
        "dead_input_local_cast_log_count":
            dead_input_local_cast_log_count,
        "dead_input_remote_cast_log_count":
            dead_input_remote_cast_log_count,
        "dead_input_mana_delta": dead_input_mana_delta,
        "mana_spend_call_count": mana_spend_call_count,
        "mana_spent_total": mana_spent_total,
        "victim_new_world_actors": victim_new_actors,
        "observer_new_world_actors": observer_new_actors,
        "primary_input": primary_input,
        "secondary_input": secondary_input,
        "clear_result": clear_result,
        "before": _small_state(before),
        "after": _small_state(after),
    }
    if not dead_input_lockout_matches:
        raise VerifyFailure(
            "dead participant input produced gameplay authority or world "
            f"effects: {evidence}"
        )
    return evidence


def _small_state(values: dict[str, str]) -> dict[str, str]:
    keys = (
        "active",
        "phase",
        "hp",
        "max_hp",
        "mp",
        "max_mp",
        "death_drive_state",
        "death_presentation_ticks",
        "terminal_pending",
        "terminal_countdown",
        "red_effect_active",
        "death_transition_hits",
        "staff_drop_hits",
        "presentation_active",
        "presentation_flags",
        "authoritative_death_presentation_ticks",
        "anim_drive_state",
        "grid_member_flag",
        "render_sort_bias",
        "x",
        "y",
        "target_participant_id",
        "target_name",
        "expected_target_participant_id",
        "expected_target_presentation_active",
        "expected_target_death_presentation_tick",
        "display_text",
    )
    return {key: values[key] for key in keys if key in values}


def _assert_single_target_spectator_samples(
    samples: list[dict[str, str]],
    *,
    expected_target_participant_id: int,
) -> dict[str, Any]:
    if not samples:
        raise VerifyFailure(
            "single-target spectator control trial captured no state"
        )
    invalid: list[dict[str, str]] = []
    maximum_camera_error = 0.0
    target_names: set[str] = set()
    for sample in samples:
        camera_error = math.hypot(
            float(sample.get("camera_center_x", "0"))
                - float(sample.get("target_x", "0")),
            float(sample.get("camera_center_y", "0"))
                - float(sample.get("target_y", "0")),
        )
        maximum_camera_error = max(
            maximum_camera_error,
            camera_error,
        )
        target_name = sample.get("target_name", "")
        if target_name:
            target_names.add(target_name)
        if (
            sample.get("active") != "true"
            or sample.get("phase") != "Spectating"
            or int(sample.get("target_participant_id", "0"))
                != expected_target_participant_id
            or sample.get("target_alive") != "true"
            or sample.get("camera_focus_active") != "true"
            or camera_error > SPECTATOR_CAMERA_TOLERANCE
            or "Left / Right click: next player"
                not in sample.get("display_text", "")
        ):
            invalid.append(sample)
    if invalid:
        raise VerifyFailure(
            "single-target spectator cycling blanked or migrated the "
            f"target: expected={expected_target_participant_id} "
            f"invalid={invalid[0]}"
        )
    return {
        "stable": True,
        "expected_target_participant_id":
            expected_target_participant_id,
        "sample_count": len(samples),
        "maximum_camera_error": maximum_camera_error,
        "target_names": sorted(target_names),
    }


def _exercise_single_target_spectator_controls(
    pipe_name: str,
    *,
    expected_target_participant_id: int,
) -> dict[str, Any]:
    clear_result = parse_key_values(
        lua(
            pipe_name,
            "print('left=' .. "
            "tostring(sd.input.clear_mouse_left())); "
            "print('right=' .. "
            "tostring(sd.input.clear_mouse_right()))",
        )
    )
    time.sleep(0.25)
    initial = query_spectator_state(pipe_name)
    initial_assertion = _assert_single_target_spectator_samples(
        [initial],
        expected_target_participant_id=
            expected_target_participant_id,
    )
    trials: dict[str, Any] = {}
    inputs = (
        (
            "left",
            "return tostring("
            "sd.input.click_normalized(0.5, 0.5))",
        ),
        (
            "right",
            "return tostring("
            "sd.input.hold_mouse_right_frames(1))",
        ),
    )
    for label, code in inputs:
        injected = lua(pipe_name, code)
        deadline = time.monotonic() + SINGLE_TARGET_SAMPLE_SECONDS
        samples: list[dict[str, str]] = []
        while time.monotonic() < deadline:
            samples.append(query_spectator_state(pipe_name))
            time.sleep(0.02)
        trials[label] = {
            "input_result": injected.strip(),
            "assertion": _assert_single_target_spectator_samples(
                samples,
                expected_target_participant_id=
                    expected_target_participant_id,
            ),
            "first": _small_state(samples[0]),
            "last": _small_state(samples[-1]),
        }
        parse_key_values(
            lua(
                pipe_name,
                "print('left=' .. "
                "tostring(sd.input.clear_mouse_left())); "
                "print('right=' .. "
                "tostring(sd.input.clear_mouse_right()))",
            )
        )
        time.sleep(0.25)
    return {
        "clear_result": clear_result,
        "initial": _small_state(initial),
        "initial_assertion": initial_assertion,
        "trials": trials,
        "stable": True,
    }


def _sample_lifecycle(
    *,
    victim_pipe: str,
    observer_pipe: str,
    victim_id: int,
    timeout: float,
    spectator_hold_pipe: str | None = None,
    terminal_frame_callback: Callable[[], Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    milestones: dict[str, float] = {}
    terminal_frame_callback_invoked = False
    while time.monotonic() < deadline:
        owner = query_spectator_state(victim_pipe)
        observer = query_remote_death_state(observer_pipe, victim_id)
        spectator_hold: dict[str, str] | None = None
        if spectator_hold_pipe is not None:
            spectator_hold = query_spectator_target_death_state(
                spectator_hold_pipe,
                victim_id,
            )
        elapsed = time.monotonic() - started
        sample = {
            "elapsed_seconds": round(elapsed, 6),
            "owner": _small_state(owner),
            "observer": _small_state(observer),
        }
        if spectator_hold is not None:
            sample["spectator_hold"] = _small_state(spectator_hold)
        samples.append(sample)
        owner_hp = float(owner.get("hp", "0"))
        if owner_hp <= 0.0:
            milestones.setdefault("hp_zero_seconds", elapsed)
        if float(observer.get("hp", "0")) <= 0.0:
            milestones.setdefault("observer_hp_zero_seconds", elapsed)
        if int(observer.get("death_drive_state", "0")) != 0:
            milestones.setdefault("observer_death_drive_seconds", elapsed)
        if int(owner.get("death_drive_state", "0")) != 0:
            milestones.setdefault("owner_death_drive_seconds", elapsed)
        if owner.get("phase") == "DeathPresentation":
            milestones.setdefault("presentation_seconds", elapsed)
        if (
            observer.get("presentation_active") == "true"
            and "observer_presentation_seconds" not in milestones
        ):
            milestones["observer_presentation_seconds"] = elapsed
            milestones["owner_presentation_tick_at_observer_start"] = float(
                int(owner.get("death_presentation_ticks", "0"))
            )
            milestones["observer_presentation_tick_at_start"] = float(
                int(observer.get("death_presentation_ticks", "0"))
            )
        if int(owner.get("death_transition_hits", "0")) > 0:
            milestones.setdefault("death_transition_seconds", elapsed)
        if int(owner.get("staff_drop_hits", "0")) > 0:
            milestones.setdefault("staff_drop_seconds", elapsed)
        if (
            owner.get("red_effect_active") == "true"
            and observer.get("red_effect_active") == "true"
        ):
            milestones.setdefault("red_effect_seconds", elapsed)
        if owner.get("phase") == "Spectating":
            milestones.setdefault("spectator_seconds", elapsed)
        if (
            terminal_frame_callback is not None
            and not terminal_frame_callback_invoked
            and owner.get("phase") == "DeathPresentation"
            and observer.get("presentation_active") == "true"
            and int(
                owner.get(
                    "authoritative_death_presentation_ticks",
                    "0",
                )
            )
                >= NATIVE_TERMINAL_CORPSE_TICK
            and int(
                observer.get(
                    "authoritative_death_presentation_ticks",
                    "0",
                )
            )
                >= NATIVE_TERMINAL_CORPSE_TICK
        ):
            callback_started = time.monotonic()
            terminal_frame_callback()
            callback_duration = time.monotonic() - callback_started
            # Terminal-frame evidence is captured synchronously while the
            # game continues. Do not let that verifier work consume the
            # remaining lifecycle polling budget.
            deadline += callback_duration
            terminal_frame_callback_invoked = True
            milestones["terminal_frame_callback_seconds"] = elapsed
            milestones["terminal_frame_callback_duration_seconds"] = (
                callback_duration
            )
        if (
            "spectator_seconds" in milestones
            and owner.get("red_effect_active") == "false"
            and observer.get("red_effect_active") == "false"
        ):
            milestones.setdefault("red_cleared_seconds", elapsed)
            return samples, milestones
        time.sleep(0.02)
    return samples, milestones


def _assert_lifecycle(
    lifecycle: list[dict[str, Any]],
    milestones: dict[str, float],
) -> float:
    required = (
        "hp_zero_seconds",
        "presentation_seconds",
        "observer_presentation_seconds",
        "owner_presentation_tick_at_observer_start",
        "observer_presentation_tick_at_start",
        "death_transition_seconds",
        "staff_drop_seconds",
        "red_effect_seconds",
        "spectator_seconds",
        "red_cleared_seconds",
    )
    missing = [key for key in required if key not in milestones]
    if missing:
        raise VerifyFailure(
            "organic player death lifecycle diverged before "
            f"{missing}; milestones={milestones}"
        )
    grace_seconds = (
        milestones["spectator_seconds"]
        - milestones["presentation_seconds"]
    )
    if (
        grace_seconds < DEATH_PRESENTATION_SECONDS - 0.25
        or grace_seconds > DEATH_PRESENTATION_SECONDS + 1.25
    ):
        raise VerifyFailure(
            "organic death presentation did not hold for five seconds: "
            f"{grace_seconds:.3f}s milestones={milestones}"
        )
    if (
        milestones.get("observer_death_drive_seconds", math.inf)
        + 0.08
        < milestones["presentation_seconds"]
    ):
        raise VerifyFailure(
            "observer entered the death animation before the owner "
            f"started death presentation: {milestones}"
        )
    presentation_delivery_skew = abs(
        milestones["observer_presentation_seconds"]
        - milestones["presentation_seconds"]
    )
    presentation_phase_skew = abs(
        milestones["observer_presentation_tick_at_start"]
        - milestones["owner_presentation_tick_at_observer_start"]
    )
    milestones["presentation_delivery_skew_seconds"] = (
        presentation_delivery_skew
    )
    milestones["presentation_phase_skew_ticks"] = presentation_phase_skew
    # A stalled peer cannot render while its app thread is stopped. The
    # replicated bounded clock and packet-age extrapolation are what keep the
    # first frame it can render aligned with the owner, so assert that native
    # phase directly instead of packet-observation wall time.
    if presentation_phase_skew > PRESENTATION_PHASE_SYNC_TOLERANCE_TICKS:
        raise VerifyFailure(
            "owner and observer death presentation phase diverged by "
            f"{presentation_phase_skew:.0f} ticks: {milestones}"
        )

    maximum_owner_storage_tick = max(
        int(sample["owner"].get("death_presentation_ticks", "0"))
        for sample in lifecycle
    )
    maximum_observer_storage_tick = max(
        int(sample["observer"].get("death_presentation_ticks", "0"))
        for sample in lifecycle
    )
    maximum_owner_logical_tick = max(
        int(
            sample["owner"].get(
                "authoritative_death_presentation_ticks",
                "0",
            )
        )
        for sample in lifecycle
    )
    maximum_observer_logical_tick = max(
        int(
            sample["observer"].get(
                "authoritative_death_presentation_ticks",
                "0",
            )
        )
        for sample in lifecycle
    )
    milestones["maximum_owner_storage_tick"] = float(
        maximum_owner_storage_tick
    )
    milestones["maximum_observer_storage_tick"] = float(
        maximum_observer_storage_tick
    )
    milestones["maximum_owner_presentation_tick"] = float(
        maximum_owner_logical_tick
    )
    milestones["maximum_observer_presentation_tick"] = float(
        maximum_observer_logical_tick
    )
    if (
        maximum_owner_storage_tick > NATIVE_RED_SAFE_TICK
        or maximum_observer_storage_tick > NATIVE_RED_SAFE_TICK
    ):
        raise VerifyFailure(
            "organic death native CPU death timer crossed the tick-159 "
            "side-effect boundary: "
            f"owner_storage_tick={maximum_owner_storage_tick} "
            f"observer_storage_tick={maximum_observer_storage_tick}"
        )
    if (
        maximum_owner_logical_tick < NATIVE_TERMINAL_CORPSE_TICK
        or maximum_observer_logical_tick <
            NATIVE_TERMINAL_CORPSE_TICK
    ):
        raise VerifyFailure(
            "organic death presentation did not reach the native terminal "
            "corpse frame on owner and observer: "
            f"owner_tick={maximum_owner_logical_tick} "
            f"observer_tick={maximum_observer_logical_tick}"
        )

    owner_death_samples = [
        sample
        for sample in lifecycle
        if int(sample["owner"].get("death_drive_state", "0")) != 0
        and sample["owner"].get("phase") == "DeathPresentation"
        and sample["owner"].get("presentation_active") == "true"
        and int(sample["owner"].get("death_transition_hits", "0")) > 0
    ]
    observer_death_samples = [
        sample
        for sample in lifecycle
        if int(sample["observer"].get("death_drive_state", "0")) != 0
        and sample["observer"].get("presentation_active") == "true"
        and float(sample["observer"].get("hp", "0")) <= 0.0
    ]
    if not owner_death_samples or not observer_death_samples:
        raise VerifyFailure(
            "organic death lifecycle had no per-peer corpse-position "
            "samples"
        )
    native_cpu_retirement_samples = [
        sample
        for sample in owner_death_samples
        if (
            int(sample["owner"].get("grid_member_flag", "0")) != 1
            or abs(
                float(
                    sample["owner"].get(
                        "render_sort_bias",
                        "0",
                    )
                )
            ) > 0.001
            or int(
                sample["observer"].get(
                    "grid_member_flag",
                    "0",
                )
            ) != 1
            or abs(
                float(
                    sample["observer"].get(
                        "render_sort_bias",
                        "0",
                    )
                )
            ) > 0.001
        )
    ]
    if native_cpu_retirement_samples:
        raise VerifyFailure(
            "organic death native CPU death timer crossed the tick-159 "
            "registration/render side-effect boundary: "
            f"{native_cpu_retirement_samples[0]}"
        )
    owner_reference = (
        float(owner_death_samples[0]["owner"].get("x", "0")),
        float(owner_death_samples[0]["owner"].get("y", "0")),
    )
    observer_reference = (
        float(observer_death_samples[0]["observer"].get("x", "0")),
        float(observer_death_samples[0]["observer"].get("y", "0")),
    )
    owner_corpse_max_position_delta = max(
        math.hypot(
            float(sample["owner"].get("x", "0")) - owner_reference[0],
            float(sample["owner"].get("y", "0")) - owner_reference[1],
        )
        for sample in owner_death_samples
    )
    observer_corpse_max_position_delta = max(
        math.hypot(
            float(sample["observer"].get("x", "0")) -
                observer_reference[0],
            float(sample["observer"].get("y", "0")) -
                observer_reference[1],
        )
        for sample in observer_death_samples
    )
    corpse_position_stability_matches = (
        owner_corpse_max_position_delta <= CORPSE_POSITION_TOLERANCE
        and observer_corpse_max_position_delta <=
            CORPSE_POSITION_TOLERANCE
    )
    milestones["owner_corpse_max_position_delta"] = (
        owner_corpse_max_position_delta
    )
    milestones["observer_corpse_max_position_delta"] = (
        observer_corpse_max_position_delta
    )
    milestones["corpse_position_stability_matches"] = (
        1.0 if corpse_position_stability_matches else 0.0
    )
    if not corpse_position_stability_matches:
        raise VerifyFailure(
            "organic death corpse moved during the grace window: "
            f"owner_delta={owner_corpse_max_position_delta:.3f} "
            f"observer_delta={observer_corpse_max_position_delta:.3f}"
        )

    initial_owner = lifecycle[0]["owner"]
    initial_observer = lifecycle[0]["observer"]
    final_owner = lifecycle[-1]["owner"]
    final_observer = lifecycle[-1]["observer"]
    owner_death_transition_delta = (
        int(final_owner.get("death_transition_hits", "0"))
        - int(initial_owner.get("death_transition_hits", "0"))
    )
    owner_staff_drop_delta = (
        int(final_owner.get("staff_drop_hits", "0"))
        - int(initial_owner.get("staff_drop_hits", "0"))
    )
    observer_death_transition_delta = (
        int(final_observer.get("death_transition_hits", "0"))
        - int(initial_observer.get("death_transition_hits", "0"))
    )
    observer_staff_drop_delta = (
        int(final_observer.get("staff_drop_hits", "0"))
        - int(initial_observer.get("staff_drop_hits", "0"))
    )
    milestones["owner_death_transition_delta"] = float(
        owner_death_transition_delta
    )
    milestones["owner_staff_drop_delta"] = float(owner_staff_drop_delta)
    milestones["observer_death_transition_delta"] = float(
        observer_death_transition_delta
    )
    milestones["observer_staff_drop_delta"] = float(
        observer_staff_drop_delta
    )
    if owner_death_transition_delta != 1:
        raise VerifyFailure(
            "owner organic death transition trace delta was not 1: "
            f"initial={initial_owner} final={final_owner}"
        )
    if owner_staff_drop_delta != 1:
        raise VerifyFailure(
            "owner organic staff drop trace delta was not 1: "
            f"initial={initial_owner} final={final_owner}"
        )
    if observer_death_transition_delta != 0:
        raise VerifyFailure(
            "observer executed owner-only organic death transition: "
            f"initial={initial_observer} final={final_observer}"
        )
    if observer_staff_drop_delta != 0:
        raise VerifyFailure(
            "observer executed owner-only organic staff drop: "
            f"initial={initial_observer} final={final_observer}"
        )
    return grace_seconds


def _wait_for_respawn(
    victim_pipe: str,
    *,
    timeout: float = 10.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_spectator_state(victim_pipe)
        if (
            last.get("active") == "false"
            and float(last.get("hp", "0")) > 0.0
            and int(last.get("death_drive_state", "0")) == 0
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(f"organic victim did not respawn cleanly: {last}")


def _finish_wave(host_pipe: str, timeout: float = 15.0) -> list[dict[str, str]]:
    deadline = time.monotonic() + timeout
    attempts: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        wave = parse_key_values(lua(host_pipe, WAVE_STATE_PROBE))
        if wave.get("phase") == "completed":
            return attempts
        attempts.append(
            parse_key_values(lua(host_pipe, KILL_LIVE_WAVE_ENEMIES))
        )
        time.sleep(0.1)
    raise VerifyFailure(f"organic wave did not complete: {attempts[-5:]}")


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path | None,
    launcher_path: Path | None,
    kill_type: str,
    victim_role: str,
    activity: str,
    enable_audio: bool = False,
) -> dict[str, Any]:
    fixture = WAVE_FIXTURES[kill_type]
    if game_directory is None:
        raise VerifyFailure(
            "organic player-death verification requires an explicit retail "
            "game directory so the complete native wave schedule can be "
            "materialized without touching the source"
        )
    retail_wave_path = game_directory.resolve() / "data" / "wave.txt"
    effective_wave_path = (
        SCREENSHOT_ROOT
        / instance_prefix
        / f"effective-{kill_type}-wave.txt"
    )
    wave_schedule = _materialize_native_wave_schedule(
        retail_wave_path=retail_wave_path,
        fixture_path=fixture,
        output_path=effective_wave_path,
    )
    if wave_schedule["record_count"] != 42:
        raise VerifyFailure(
            "organic acceptance expected the retail 42-record native wave "
            f"graph, got {wave_schedule['record_count']}: {retail_wave_path}"
        )
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_air_mind_hub",
        temporary_host_profile=True,
        tile_windows=False,
        test_blank_boneyard=True,
        test_wave_override=effective_wave_path,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_id=ACCEPTANCE_MOD_ID,
        use_sandbox_preset_flow=True,
        enable_audio=enable_audio,
    )
    process_ids = game_process_ids(launch)
    if len(process_ids) != 2:
        stop_exact_game_processes(launch)
        raise VerifyFailure(
            f"isolated pair did not report two process IDs: {launch}"
        )
    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    pipes = [host_pipe, client_pipe]
    if victim_role == "host":
        victim_pipe = host_pipe
        observer_pipe = client_pipe
        victim_id = HOST_ID
    else:
        victim_pipe = client_pipe
        observer_pipe = host_pipe
        victim_id = CLIENT_ID
    observer_role = "client" if victim_role == "host" else "host"
    victim_log = _launch_log_path(
        launch,
        f"{victim_role}Log",
    )
    observer_log = _launch_log_path(
        launch,
        f"{observer_role}Log",
    )
    direction = Direction(
        name=f"{victim_role}_organic_death_cast",
        source_id=victim_id,
        source_name=HOST_NAME if victim_role == "host" else CLIENT_NAME,
        source_pipe=victim_pipe,
        source_log=victim_log,
        source_pid=int(launch[f"{victim_role}ProcessId"]),
        receiver_pipe=observer_pipe,
        receiver_log=observer_log,
    )

    result: dict[str, Any] = {
        "launch": launch,
        "process_ids": process_ids,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "kill_type": kill_type,
        "victim_role": victim_role,
        "activity": activity,
        "audio_enabled": enable_audio,
        "wave_fixture": str(fixture),
        "wave_schedule": wave_schedule,
    }
    try:
        _disable_companion_bots(pipes)
        _start_testrun_when_ready(host_pipe)
        wait_for_scene(host_pipe, "testrun", 45.0)
        host_safe = set_local_player_vitals(
            host_pipe,
            SURVIVOR_HP,
            SURVIVOR_HP,
        )
        wait_for_scene(client_pipe, "testrun", 45.0)
        client_safe = set_local_player_vitals(
            client_pipe,
            SURVIVOR_HP,
            SURVIVOR_HP,
        )
        result["vitals_safe"] = {
            "host": host_safe,
            "client": client_safe,
        }
        result["relationships"] = {
            "host_observes_client": wait_for_remote(
                host_pipe,
                CLIENT_ID,
                CLIENT_NAME,
                "testrun",
                45.0,
            ),
            "client_observes_host": wait_for_remote(
                client_pipe,
                HOST_ID,
                HOST_NAME,
                "testrun",
                45.0,
            ),
        }
        result["target_layout"] = (
            _place_and_wait_for_death_target_layout(
                host_pipe=host_pipe,
                client_pipe=client_pipe,
                victim_role=victim_role,
            )
        )
        result["alive_precondition"] = {
            "host": _small_state(query_spectator_state(host_pipe)),
            "client": _small_state(query_spectator_state(client_pipe)),
        }
        for role, state in result["alive_precondition"].items():
            if (
                state.get("active") != "false"
                or float(state.get("hp", "0")) <= 0.0
                or int(state.get("death_drive_state", "0")) != 0
            ):
                raise VerifyFailure(
                    f"{role} was already dead before organic trial: {state}"
                )
        result["product_hud_alive"] = (
            assert_latest_spectator_product_hud_state(
                [victim_log, observer_log],
                context="alive",
                expected_active=False,
                expected_phase="Inactive",
                expected_registered=False,
                expected_rendered=False,
                expected_target_participant_id=0,
            )
        )
        result["diagnostic_surface_guard_alive"] = (
            assert_launch_debug_surfaces_empty(
                launch,
                roles=("host", "client"),
                context="alive",
            )
        )
        result["death_traces_armed"] = _arm_death_traces(pipes)
        result["damage_probes_armed"] = {}
        for role, pipe_name in (("host", host_pipe), ("client", client_pipe)):
            armed = parse_key_values(lua(pipe_name, ARM_DAMAGE_PROBE))
            if armed.get("registered") != "true":
                raise VerifyFailure(
                    f"{role} organic damage probe failed to arm: {armed}"
                )
            result["damage_probes_armed"][role] = armed

        pre_wave_enemies = _query_live_enemies(host_pipe)
        pre_wave_actor_addresses = {
            int(actor["actor_address"])
            for actor in pre_wave_enemies
        }
        result["pre_wave_enemies"] = pre_wave_enemies
        result["pre_wave_actor_addresses"] = sorted(
            pre_wave_actor_addresses
        )
        result["wave_start"] = _start_waves(host_pipe)
        enemy = _wait_for_new_wave_enemy(
            host_pipe,
            pre_wave_actor_addresses=pre_wave_actor_addresses,
        )
        result["enemy"] = enemy
        victim_before = query_spectator_state(victim_pipe)
        result["victim_before_attack"] = _small_state(victim_before)
        authority_layout = result["target_layout"]["host_authority"]
        host_authority_xy = (
            float(authority_layout["host_x"]),
            float(authority_layout["host_y"]),
        )
        client_authority_xy = (
            float(authority_layout["client_x"]),
            float(authority_layout["client_y"]),
        )
        authority_victim_xy = (
            host_authority_xy
            if victim_role == "host"
            else client_authority_xy
        )
        authority_survivor_xy = (
            client_authority_xy
            if victim_role == "host"
            else host_authority_xy
        )
        attack_magnitude = 64.0 if kill_type == "melee" else 240.0
        attack_distance = (
            -attack_magnitude
            if authority_survivor_xy[0] >= authority_victim_xy[0]
            else attack_magnitude
        )
        result["host_authority_attack_geometry"] = {
            "victim": authority_victim_xy,
            "survivor": authority_survivor_xy,
            "attack_distance": attack_distance,
        }
        result["enemy_arena"] = _arm_enemy_arena(
            host_pipe,
            *authority_victim_xy,
        )
        result["enemy_stabilized"] = _stabilize_enemy(
            host_pipe,
            enemy_actor_address=int(enemy["actor_address"]),
        )

        enemy_attack_kwargs = {
            "target_x": authority_victim_xy[0],
            "target_y": authority_victim_xy[1],
            "target_participant_id":
                0 if victim_role == "host" else victim_id,
            "enemy_actor_address":
                int(enemy["actor_address"]),
            "attack_distance": attack_distance,
        }
        damage_baseline = query_spectator_state(victim_pipe)
        result["enemy_attack"] = _set_enemy_attack(
            host_pipe,
            **enemy_attack_kwargs,
        )
        result["enemy_damage_observed"] = _wait_for_victim_damage(
            victim_pipe,
            baseline_hp=float(damage_baseline["hp"]),
            timeout=30.0 if kill_type == "poison" else 18.0,
        )
        if kill_type == "poison":
            result["poison_state_after_damage"] = parse_key_values(
                lua(victim_pipe, POISON_STATE_PROBE)
            )
        if activity == "casting":
            source_log_offset = log_position(victim_log)
            result["cast_input"] = queue_gameplay_mouse_left(
                direction,
                CAST_HOLD_FRAMES,
            )
            _, phase_counts, native_hook_count = wait_for_source_cast(
                direction,
                source_log_offset,
                {"pressed": 1, "held": 1},
                3.0,
            )
            result["cast_started"] = {
                "phase_counts": phase_counts,
                "native_hook_count": native_hook_count,
            }
        else:
            result["idle_input"] = parse_key_values(
                lua(
                    victim_pipe,
                    "print('cleared=' .. "
                    "tostring(sd.input.clear_mouse_left()))",
                )
            )
        result["victim_armed"] = set_local_player_vitals(
            victim_pipe,
            VICTIM_ARMING_HP,
            VICTIM_MAX_HP,
        )
        lifecycle, milestones = _sample_lifecycle(
            victim_pipe=victim_pipe,
            observer_pipe=observer_pipe,
            victim_id=victim_id,
            timeout=LIFECYCLE_TIMEOUT_SECONDS[kill_type],
        )
        result["lifecycle_samples"] = lifecycle
        result["milestones"] = milestones
        result["damage_events"] = {
            "host": _parse_damage_probe(lua(host_pipe, QUERY_DAMAGE_PROBE)),
            "client": _parse_damage_probe(lua(client_pipe, QUERY_DAMAGE_PROBE)),
        }
        try:
            result["cast_clear"] = clear_gameplay_mouse_left(direction)
        except VerifyFailure as exc:
            result["cast_clear_error"] = str(exc)

        result["grace_seconds"] = _assert_lifecycle(
            lifecycle,
            milestones,
        )
        expected_spectator_target_id = (
            CLIENT_ID if victim_role == "host" else HOST_ID
        )
        result["product_hud_spectating"] = (
            wait_for_spectator_product_hud_state(
                [victim_log],
                context="spectating",
                expected_active=True,
                expected_phase="Spectating",
                expected_registered=True,
                expected_rendered=True,
                expected_target_participant_id=
                    expected_spectator_target_id,
                timeout=5.0,
            )
        )
        result["product_hud_alive_observer"] = (
            assert_latest_spectator_product_hud_state(
                [observer_log],
                context="alive",
                expected_active=False,
                expected_phase="Inactive",
                expected_registered=False,
                expected_rendered=False,
                expected_target_participant_id=0,
            )
        )
        result["product_hud_lifecycle_before_respawn"] = (
            assert_spectator_product_hud_lifecycle(
                victim_log,
                expected_target_participant_id=
                    expected_spectator_target_id,
                require_retired=False,
            )
        )
        result["diagnostic_surface_guard_spectating"] = (
            assert_launch_debug_surfaces_empty(
                launch,
                roles=("host", "client"),
                context="spectating",
            )
        )
        result["enemy_idle_for_dead_input"] = _set_enemy_idle(host_pipe)
        time.sleep(0.25)
        result["dead_input"] = _attempt_dead_gameplay_inputs(
            direction=direction,
            victim_pipe=victim_pipe,
            observer_pipe=observer_pipe,
        )
        result["single_target_controls"] = (
            _exercise_single_target_spectator_controls(
                victim_pipe,
                expected_target_participant_id=
                    expected_spectator_target_id,
            )
        )

        screenshot_directory = SCREENSHOT_ROOT / instance_prefix
        victim_screenshot_path = (
            screenshot_directory / "victim-spectator.png"
        )
        observer_screenshot_path = (
            screenshot_directory / "observer-death-location.png"
        )
        result["screenshots"] = {
            "victim_spectator": capture_game_backbuffer(
                victim_pipe,
                victim_screenshot_path,
            ),
            "observer_death_location": capture_game_backbuffer(
                observer_pipe,
                observer_screenshot_path,
            ),
        }
        result["product_hud_pixels"] = {
            "victim_visible":
                inspect_spectator_product_hud_pixels(
                    victim_screenshot_path,
                    expected_visible=True,
                ),
            "observer_hidden":
                inspect_spectator_product_hud_pixels(
                    observer_screenshot_path,
                    expected_visible=False,
                ),
        }
        result["wave_finish"] = _finish_wave(host_pipe)
        result["respawned"] = _wait_for_respawn(victim_pipe)
        result["product_hud_respawned"] = (
            wait_for_spectator_product_hud_state(
                [victim_log],
                context="respawned",
                expected_active=False,
                expected_phase="Inactive",
                expected_registered=False,
                expected_rendered=False,
                expected_target_participant_id=0,
                timeout=5.0,
            )
        )
        result["product_hud_lifecycle"] = (
            assert_spectator_product_hud_lifecycle(
                victim_log,
                expected_target_participant_id=
                    expected_spectator_target_id,
                require_retired=True,
            )
        )
        result["product_hud_observer_never_visible"] = (
            assert_spectator_product_hud_never_visible(observer_log)
        )
        result["diagnostic_surface_guard_respawned"] = (
            assert_launch_debug_surfaces_empty(
                launch,
                roles=("host", "client"),
                context="respawned",
            )
        )
        result["product_hud_surface_states"] = {
            victim_role: parse_spectator_product_hud_states(
                victim_log.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            ),
            observer_role: parse_spectator_product_hud_states(
                observer_log.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            ),
        }
        retail_sha256_after = hashlib.sha256(
            retail_wave_path.read_bytes()
        ).hexdigest()
        result["wave_schedule"]["retail_sha256_after"] = (
            retail_sha256_after
        )
        result["wave_schedule"]["retail_unchanged"] = (
            retail_sha256_after
            == result["wave_schedule"]["retail_sha256"]
        )
        if not result["wave_schedule"]["retail_unchanged"]:
            raise VerifyFailure(
                f"retail wave source changed during isolated verification: "
                f"{retail_wave_path}"
            )
        result["ok"] = True
        return result
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        raise OrganicDeathFailure(str(exc), result) from exc
    finally:
        _disarm_death_traces(pipes)
        result["cleanup"] = stop_exact_game_processes(launch)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique launcher instance prefix (generated by default).",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=None,
        help="Retail game directory override for isolated worktrees.",
    )
    parser.add_argument(
        "--launcher-path",
        type=Path,
        default=None,
        help="Launcher build to stage.",
    )
    parser.add_argument(
        "--kill-type",
        choices=tuple(WAVE_FIXTURES),
        default="melee",
    )
    parser.add_argument(
        "--victim",
        choices=("host", "client"),
        default="host",
    )
    parser.add_argument(
        "--activity",
        choices=("idle", "casting"),
        default="idle",
    )
    parser.add_argument(
        "--enable-audio",
        action="store_true",
        help="Keep stock audio enabled for systems where silent D3D startup stalls.",
    )
    parser.add_argument("--host-port", type=int, default=None)
    parser.add_argument("--client-port", type=int, default=None)
    args = parser.parse_args()

    if (args.host_port is None) != (args.client_port is None):
        parser.error("--host-port and --client-port must be supplied together")
    ports = (
        [args.host_port, args.client_port]
        if args.host_port is not None
        else select_available_windows_udp_ports(2)
    )
    instance_prefix = args.instance_prefix or _default_instance_prefix()
    result: dict[str, Any] = {"ok": False}
    exit_code = 1
    try:
        result = run_live_verification(
            instance_prefix=instance_prefix,
            ports=[int(port) for port in ports],
            game_directory=args.game_dir,
            launcher_path=args.launcher_path,
            kill_type=args.kill_type,
            victim_role=args.victim,
            activity=args.activity,
            enable_audio=args.enable_audio,
        )
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - persist exact live evidence.
        if isinstance(exc, OrganicDeathFailure):
            result = exc.evidence
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        result["instance_prefix"] = instance_prefix
        result["kill_type"] = args.kill_type
        result["victim_role"] = args.victim
        result["activity"] = args.activity
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
                "kill_type": args.kill_type,
                "victim_role": args.victim,
                "activity": args.activity,
                "milestones": result.get("milestones"),
                "damage_events": result.get("damage_events"),
                "instance_prefix": instance_prefix,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
