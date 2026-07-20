#!/usr/bin/env python3
"""Shared native-contact harness for multiplayer staff stat behavior tests."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    HOST_PIPE,
    VerifyFailure,
    parse_int_text,
    place_player,
    query,
)
from verify_multiplayer_primary_kill_stress import (
    COMBAT_STATE_LUA,
    ENABLE_PRELUDE_LUA,
    PLAYER_HEADING_EAST,
    START_WAVES_LUA,
    clear_gameplay_mouse_left,
    configure_enemy,
    find_target,
    parse_float,
    query_run_enemy_by_network_id,
    set_manual_spawner_test_mode,
    values,
)
from verify_multiplayer_rush_behavior_sync import (
    configure_native_movement_drive,
    query_native_movement_drive,
)
from verify_real_input_spell_cast_sync import Direction


ROOT = Path(__file__).resolve().parent.parent
PHYSICAL_WAVE = ROOT / "tests/fixtures/waves/physical_stat_test.txt"

NATIVE_APPLY_DAMAGE = 0x0063E7D0
STAFF_EFFECT_DAMAGE_RETURN = 0x0053C269

ARENA_PARK_X = 1050.0
ARENA_PARK_Y = 1050.0
ARENA_PARK_STEP = 70.0
ARENA_PARK_COLUMNS = 5
SOURCE_START_X = 500.0
SOURCE_START_Y = 350.0
OBSERVER_START_X = 1000.0
OBSERVER_START_Y = 800.0
TARGET_APPROACH_DISTANCE = 150.0
TARGET_HP = 100000.0


ARENA_ARM_LUA = r"""
local function emit(key, value)
  if value == nil then value = '<nil>' end
  print(key .. '=' .. tostring(value))
end
_G.__sdmod_staff_natural_arena = {
  active = true,
  actors = {},
  index_by_actor = {},
  seeded = {},
  positions = {},
  park_x = __PARK_X__,
  park_y = __PARK_Y__,
  park_step = __PARK_STEP__,
  park_columns = __PARK_COLUMNS__,
}
if not _G.__sdmod_staff_natural_arena_registered then
  sd.events.on('runtime.tick', function()
    local arena = _G.__sdmod_staff_natural_arena
    if type(arena) ~= 'table' or not arena.active then return end
    local x_offset = sd.debug.layout_offset('actor_position_x')
    local y_offset = sd.debug.layout_offset('actor_position_y')
    local target_offset = sd.debug.layout_offset('actor_current_target_actor')
    for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
      local address = tonumber(actor.actor_address) or 0
      if address ~= 0 and actor.tracked_enemy and not actor.dead then
        local index = arena.index_by_actor[address]
        if index == nil then
          index = #arena.actors + 1
          arena.actors[index] = address
          arena.index_by_actor[address] = index
        end
        if not arena.seeded[address] then
          sd.gameplay.set_run_enemy_health(address, __TARGET_HP__, __TARGET_HP__)
          arena.seeded[address] = true
        end
        local requested = arena.positions[index]
        local x, y
        if type(requested) == 'table' then
          x = tonumber(requested.x) or arena.park_x
          y = tonumber(requested.y) or arena.park_y
        else
          local park_index = index - 1
          x = arena.park_x + (park_index % arena.park_columns) * arena.park_step
          y = arena.park_y + math.floor(park_index / arena.park_columns) * arena.park_step
        end
        if x_offset ~= nil then sd.debug.write_float(address + x_offset, x) end
        if y_offset ~= nil then sd.debug.write_float(address + y_offset, y) end
        if target_offset ~= nil then sd.debug.write_ptr(address + target_offset, 0) end
      end
    end
  end)
  _G.__sdmod_staff_natural_arena_registered = true
end
emit('registered', _G.__sdmod_staff_natural_arena_registered)
"""


@dataclass(frozen=True)
class StaffTarget:
    index: int
    x: float
    y: float
    network_id: int
    host_actor: int
    client_actor: int

    def actor_for_pipe(self, pipe_name: str) -> int:
        return self.host_actor if pipe_name == HOST_PIPE else self.client_actor


def arm_natural_staff_arena() -> dict[str, str]:
    result = values(
        HOST_PIPE,
        ARENA_ARM_LUA
        .replace("__PARK_X__", f"{ARENA_PARK_X:.3f}")
        .replace("__PARK_Y__", f"{ARENA_PARK_Y:.3f}")
        .replace("__PARK_STEP__", f"{ARENA_PARK_STEP:.3f}")
        .replace("__PARK_COLUMNS__", str(ARENA_PARK_COLUMNS))
        .replace("__TARGET_HP__", f"{TARGET_HP:.3f}"),
    )
    if result.get("registered") != "true":
        raise VerifyFailure(f"failed to arm natural staff arena: {result}")
    return result


def query_natural_staff_arena() -> dict[str, str]:
    return values(
        HOST_PIPE,
        r"""
local function emit(key, value)
  if value == nil then value = '<nil>' end
  print(key .. '=' .. tostring(value))
end
local arena = _G.__sdmod_staff_natural_arena or {actors={}}
local live = {}
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  local address = tonumber(actor.actor_address) or 0
  if address ~= 0 and actor.tracked_enemy and not actor.dead then live[address] = actor end
end
emit('actor_count', #(arena.actors or {}))
for index, address in ipairs(arena.actors or {}) do
  local actor = live[address]
  local prefix = 'actor.' .. tostring(index) .. '.'
  emit(prefix .. 'address', address)
  emit(prefix .. 'live', actor ~= nil)
  emit(prefix .. 'hp', actor and actor.hp or -1)
  emit(prefix .. 'x', actor and actor.x or 0)
  emit(prefix .. 'y', actor and actor.y or 0)
end
""",
    )


def wait_for_natural_staff_actors(
    minimum: int = 3,
    timeout: float = 8.0,
) -> list[int]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_natural_staff_arena()
        actor_count = parse_int_text(last.get("actor_count"), 0)
        actors = [
            parse_int_text(last.get(f"actor.{index}.address"), 0)
            for index in range(1, actor_count + 1)
            if last.get(f"actor.{index}.live") == "true"
        ]
        if len(actors) >= minimum and all(actor != 0 for actor in actors[:minimum]):
            return actors
        time.sleep(0.05)
    raise VerifyFailure(
        f"natural staff arena did not expose {minimum} live stock enemies: {last}"
    )


def set_natural_staff_layout(positions: Iterable[tuple[float, float]]) -> dict[str, str]:
    rows = [
        f"{{x={float(x):.6f},y={float(y):.6f}}}"
        for x, y in positions
    ]
    table = "{" + ",".join(rows) + "}"
    result = values(
        HOST_PIPE,
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local arena = _G.__sdmod_staff_natural_arena
emit('valid', type(arena) == 'table')
if type(arena) == 'table' then
  arena.positions = {table}
  emit('position_count', #arena.positions)
else
  emit('position_count', 0)
end
""",
    )
    if result.get("valid") != "true":
        raise VerifyFailure(f"natural staff arena is unavailable: {result}")
    return result


def deactivate_natural_staff_arena() -> dict[str, str]:
    return values(
        HOST_PIPE,
        "local a=_G.__sdmod_staff_natural_arena; if a then a.active=false end; print('ok=true')",
    )


def start_natural_staff_waves(minimum_actors: int = 3) -> dict[str, Any]:
    manual_mode = {
        "host": set_manual_spawner_test_mode(HOST_PIPE, False),
        "client": set_manual_spawner_test_mode(CLIENT_PIPE, False),
    }
    for label, state in manual_mode.items():
        if state.get("ok") != "true" or state.get("active") != "false":
            raise VerifyFailure(f"failed to enable retail waves on {label}: {state}")
    combat_before = values(HOST_PIPE, COMBAT_STATE_LUA)
    stock_wave_already_active = (
        combat_before.get("active") == "true"
        and (
            parse_int_text(combat_before.get("wave_index"), 0) != 0
            or parse_int_text(combat_before.get("wave_counter"), 0)
            != 999999999
        )
    )
    if stock_wave_already_active:
        return {
            "manual_mode": manual_mode,
            "combat_before": combat_before,
            "already_active": True,
            "prelude": None,
            "start": None,
            "actors": wait_for_natural_staff_actors(minimum_actors),
        }
    prelude = values(HOST_PIPE, ENABLE_PRELUDE_LUA)
    start = values(HOST_PIPE, START_WAVES_LUA)
    if prelude.get("ok") != "true" or start.get("ok") != "true":
        raise VerifyFailure(
            f"failed to start natural staff wave: prelude={prelude} start={start}"
        )
    actors = wait_for_natural_staff_actors(minimum_actors)
    return {
        "manual_mode": manual_mode,
        "combat_before": combat_before,
        "already_active": False,
        "prelude": prelude,
        "start": start,
        "actors": actors,
    }


def park_natural_staff_targets() -> dict[str, str]:
    return set_natural_staff_layout(())


def place_staff_participants(direction: Direction, settle_seconds: float = 1.5) -> dict[str, Any]:
    park_natural_staff_targets()
    if direction.source_pipe == HOST_PIPE:
        source_place = place_player(
            HOST_PIPE,
            SOURCE_START_X,
            SOURCE_START_Y,
            PLAYER_HEADING_EAST,
        )
        observer_place = place_player(
            CLIENT_PIPE,
            OBSERVER_START_X,
            OBSERVER_START_Y,
            180.0,
        )
    else:
        source_place = place_player(
            CLIENT_PIPE,
            SOURCE_START_X,
            SOURCE_START_Y,
            PLAYER_HEADING_EAST,
        )
        observer_place = place_player(
            HOST_PIPE,
            OBSERVER_START_X,
            OBSERVER_START_Y,
            180.0,
        )
    clear_gameplay_mouse_left(HOST_PIPE)
    clear_gameplay_mouse_left(CLIENT_PIPE)
    time.sleep(settle_seconds)
    source = query(direction.source_pipe)
    source_x = parse_float(source.get("player.x"), math.nan)
    source_y = parse_float(source.get("player.y"), math.nan)
    source_actor = parse_int_text(source.get("player.actor"), 0)
    if not math.isfinite(source_x) or not math.isfinite(source_y) or source_actor == 0:
        raise VerifyFailure(
            f"{direction.name} native staff source did not settle: {source}"
        )
    return {
        "source_place": source_place,
        "observer_place": observer_place,
        "source": source,
        "source_actor": source_actor,
        "source_x": source_x,
        "source_y": source_y,
    }


def configure_natural_staff_targets(
    actor_addresses: list[int],
    positions: list[tuple[float, float]],
    *,
    hp: float = TARGET_HP,
    timeout: float = 10.0,
) -> list[StaffTarget]:
    if not positions or len(actor_addresses) < len(positions):
        raise VerifyFailure(
            f"natural staff target layout is incomplete: actors={actor_addresses} positions={positions}"
        )
    # Resolve identities while the arena still keeps stock actors at distinct
    # parking coordinates.  Looking them up after clustering can assign the
    # same nearest snapshot to more than one local actor.
    arena = query_natural_staff_arena()
    actor_count = parse_int_text(arena.get("actor_count"), 0)
    parked_by_actor = {
        parse_int_text(arena.get(f"actor.{index}.address"), 0): (
            parse_float(arena.get(f"actor.{index}.x"), math.nan),
            parse_float(arena.get(f"actor.{index}.y"), math.nan),
        )
        for index in range(1, actor_count + 1)
        if arena.get(f"actor.{index}.live") == "true"
    }
    network_ids: list[int] = []
    selected_actor_addresses: list[int] = []
    claimed_network_ids: set[int] = set()
    identity_diagnostics: list[dict[str, Any]] = []
    for candidate_index, host_actor in enumerate(actor_addresses, start=1):
        parked = parked_by_actor.get(host_actor, (math.nan, math.nan))
        if not all(math.isfinite(value) for value in parked):
            raise VerifyFailure(
                "natural staff actor lacks a parked identity: "
                f"candidate_index={candidate_index} actor={host_actor} arena={arena}"
            )
        host = find_target(
            HOST_PIPE,
            parked[0],
            parked[1],
            timeout=timeout,
            require_local_binding=False,
        )
        network_id = parse_int_text(host.get("network_id"), 0)
        diagnostic = {
            "candidate_index": candidate_index,
            "host_actor": host_actor,
            "parked": parked,
            "network_id": network_id,
            "host": host,
        }
        identity_diagnostics.append(diagnostic)
        if network_id == 0 or network_id in claimed_network_ids:
            diagnostic["selected"] = False
            continue
        claimed_network_ids.add(network_id)
        network_ids.append(network_id)
        selected_actor_addresses.append(host_actor)
        diagnostic["selected"] = True
        if len(selected_actor_addresses) == len(positions):
            break
    if len(selected_actor_addresses) != len(positions):
        raise VerifyFailure(
            "natural staff target layout lacks enough authoritative network "
            f"identities: required={len(positions)} selected="
            f"{len(selected_actor_addresses)} diagnostics={identity_diagnostics}"
        )

    set_natural_staff_layout(positions)
    configured = [
        configure_enemy(selected_actor_addresses[index], x, y, hp)
        for index, (x, y) in enumerate(positions)
    ]
    if any(item.get("ok") != "true" for item in configured):
        raise VerifyFailure(f"natural staff target configuration failed: {configured}")

    targets: list[StaffTarget] = []
    for index, ((x, y), host_actor, network_id) in enumerate(
        zip(positions, selected_actor_addresses, network_ids),
        start=1,
    ):
        client = find_target(
            CLIENT_PIPE,
            x,
            y,
            network_id=network_id,
            timeout=timeout,
            require_local_binding=True,
        )
        client_actor = parse_int_text(client.get("local.actor_address"), 0)
        if client_actor == 0:
            raise VerifyFailure(
                f"natural staff target lacks client binding: index={index} client={client}"
            )
        client_rebind = values(
            CLIENT_PIPE,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local ok, err = sd.world.rebind_actor({client_actor})
emit('ok', ok)
emit('error', err or '')
""",
        )
        if client_rebind.get("ok") != "true":
            raise VerifyFailure(
                f"natural staff target client spatial rebind failed: "
                f"index={index} actor={client_actor} result={client_rebind}"
            )
        targets.append(
            StaffTarget(
                index=index,
                x=x,
                y=y,
                network_id=network_id,
                host_actor=host_actor,
                client_actor=client_actor,
            )
        )
    return targets


def run_native_staff_resolver_trial(
    direction: Direction,
    actor_addresses: list[int],
    label: str,
    *,
    variant: int = 0,
    target_offsets: tuple[tuple[float, float], ...] = ((50.0, 0.0),),
) -> dict[str, Any]:
    """Queue the stock staff effect resolver and verify authoritative damage.

    This deliberately isolates staff effect semantics from the separate
    collision/chance/action gate.  Address 0x53B9F0 is the stock animation
    event resolver: it performs the native nearby-target scan, reads Enchant
    Staff's ``mDamage``, applies damage, and dispatches variants 0..4.  The
    loader executes it only after the Lua callback returns so native effect
    allocation cannot re-enter the active Lua execution frame.
    """

    if variant < 0 or variant > 4:
        raise VerifyFailure(f"staff effect variant is outside 0..4: {variant}")
    placement = place_staff_participants(direction)
    source_actor = int(placement["source_actor"])
    source_x = float(placement["source_x"])
    source_y = float(placement["source_y"])
    positions = [
        (source_x + offset_x, source_y + offset_y)
        for offset_x, offset_y in target_offsets
    ]
    targets = configure_natural_staff_targets(actor_addresses, positions)
    before = wait_for_target_parity(targets)
    local_targets = [target.actor_for_pipe(direction.source_pipe) for target in targets]
    point_blank_target = values(
        direction.source_pipe,
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local actor = {local_targets[0]}
local x_offset = sd.debug.layout_offset('actor_position_x')
local y_offset = sd.debug.layout_offset('actor_position_y')
emit('x', sd.debug.read_float(actor + x_offset))
emit('y', sd.debug.read_float(actor + y_offset))
local ok, err = sd.world.rebind_actor(actor)
emit('rebind', ok)
emit('rebind_error', err or '')
""",
    )
    target_local_x = parse_float(point_blank_target.get("x"), math.nan)
    target_local_y = parse_float(point_blank_target.get("y"), math.nan)
    if (
        not math.isfinite(target_local_x)
        or not math.isfinite(target_local_y)
        or point_blank_target.get("rebind") != "true"
    ):
        raise VerifyFailure(
            f"{direction.name} {label} point-blank target setup failed: {point_blank_target}"
        )
    point_blank_placement = place_player(
        direction.source_pipe,
        target_local_x - 5.0,
        target_local_y,
        PLAYER_HEADING_EAST,
    )
    clear_gameplay_mouse_left(direction.source_pipe)
    local_target_table = "{" + ",".join(str(target) for target in local_targets) + "}"
    trace_name = f"staff_resolver_damage_{direction.name}_{label}_{variant}"
    trace_arm = arm_native_damage_trace(direction.source_pipe, trace_name)
    call = values(
        direction.source_pipe,
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local targets = {local_target_table}
local hp_offset = sd.debug.layout_offset('enemy_current_hp')
local x_offset = sd.debug.layout_offset('actor_position_x')
local y_offset = sd.debug.layout_offset('actor_position_y')
local heading_offset = sd.debug.layout_offset('actor_heading')
local live_target_x = sd.debug.read_float(targets[1] + x_offset)
local live_target_y = sd.debug.read_float(targets[1] + y_offset)
emit('source_write_x', sd.debug.write_float({source_actor} + x_offset, live_target_x - 5.0))
emit('source_write_y', sd.debug.write_float({source_actor} + y_offset, live_target_y))
emit('source_write_heading', sd.debug.write_float({source_actor} + heading_offset, {PLAYER_HEADING_EAST}))
local source_rebind_ok, source_rebind_error = sd.world.rebind_actor({source_actor})
emit('source_rebind', source_rebind_ok)
emit('source_rebind_error', source_rebind_error or '')
local hp_before = {{}}
for index, target in ipairs(targets) do
  hp_before[index] = sd.debug.read_float(target + hp_offset)
  emit('target.' .. tostring(index) .. '.hp_before', hp_before[index])
end
emit('resolved_damage_return', sd.debug.resolve_game_address({STAFF_EFFECT_DAMAGE_RETURN}))
local queued, queue_error, request_serial =
  sd.debug.queue_native_staff_effect_probe(
    {source_actor}, {local_targets[0]}, {variant})
emit('queued', queued)
emit('request_serial', request_serial or 0)
emit('error', queue_error or '')
""",
    )
    request_serial = parse_int_text(call.get("request_serial"), 0)
    if call.get("queued") != "true" or request_serial == 0:
        raise VerifyFailure(
            f"{direction.name} {label} native staff resolver did not queue: {call}"
        )
    if any(
        call.get(key) != "true"
        for key in (
            "source_write_x",
            "source_write_y",
            "source_write_heading",
            "source_rebind",
        )
    ):
        raise VerifyFailure(
            f"{direction.name} {label} atomic point-blank placement failed: {call}"
        )
    probe_result: dict[str, str] = {}
    probe_deadline = time.monotonic() + 10.0
    while time.monotonic() < probe_deadline:
        probe_result = values(
            direction.source_pipe,
            f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local completed, success, hp_before, hp_after, probe_error =
  sd.debug.get_native_staff_effect_probe_result({request_serial})
emit('completed', completed)
emit('success', success)
emit('hp_before', hp_before)
emit('hp_after', hp_after)
emit('error', probe_error or '')
""",
        )
        if probe_result.get("completed") == "true":
            break
        time.sleep(0.02)
    if (
        probe_result.get("completed") != "true"
        or probe_result.get("success") != "true"
    ):
        raise VerifyFailure(
            f"{direction.name} {label} native staff resolver failed: "
            f"queue={call} result={probe_result}"
        )
    immediate = values(
        direction.source_pipe,
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local targets = {local_target_table}
local hp_offset = sd.debug.layout_offset('enemy_current_hp')
for index, target in ipairs(targets) do
  emit('target.' .. tostring(index) .. '.hp_after', sd.debug.read_float(target + hp_offset))
end
""",
    )
    call["probe_completed"] = probe_result["completed"]
    call["probe_success"] = probe_result["success"]
    call["probe_error"] = probe_result.get("error", "")
    for index in range(1, len(local_targets) + 1):
        if index == 1:
            hp_before = parse_float(probe_result.get("hp_before"), math.nan)
            hp_after = parse_float(probe_result.get("hp_after"), math.nan)
            call[f"target.{index}.hp_before"] = probe_result.get(
                "hp_before", "<nil>"
            )
            call[f"target.{index}.hp_after"] = probe_result.get(
                "hp_after", "<nil>"
            )
        else:
            hp_before = parse_float(
                call.get(f"target.{index}.hp_before"), math.nan
            )
            hp_after = parse_float(
                immediate.get(f"target.{index}.hp_after"), math.nan
            )
            call[f"target.{index}.hp_after"] = immediate.get(
                f"target.{index}.hp_after", "<nil>"
            )
        call[f"target.{index}.damage"] = str(hp_before - hp_after)
    clear_gameplay_mouse_left(direction.source_pipe)
    time.sleep(0.35)
    damage_trace = finish_native_damage_trace(
        direction.source_pipe,
        trace_name,
        local_targets,
    )
    after = wait_for_target_parity(targets)

    final_damages: list[float] = []
    resolver_hit_counts: list[int] = []
    damage_per_hit: list[float] = []
    immediate_damages = [
        parse_float(call.get(f"target.{index}.damage"), math.nan)
        for index in range(1, len(local_targets) + 1)
    ]
    resolved_damage_return = parse_int_text(call.get("resolved_damage_return"), 0)
    for index, (before_row, after_row, local_target) in enumerate(
        zip(before, after, local_targets)
    ):
        before_hp = parse_float(before_row["host"].get("hp"), math.nan)
        after_hp = parse_float(after_row["host"].get("hp"), math.nan)
        damage = before_hp - after_hp
        hits = int(
            damage_trace["target_return_hit_counts"]
            .get(str(local_target), {})
            .get(str(resolved_damage_return), 0)
        )
        final_damages.append(damage)
        resolver_hit_counts.append(hits)
        immediate_damage = immediate_damages[index]
        damage_per_hit.append(immediate_damage / hits if hits > 0 else math.nan)

    if resolved_damage_return not in damage_trace["return_addresses"]:
        raise VerifyFailure(
            f"{direction.name} {label} did not use the stock staff damage callsite: {damage_trace}"
        )
    if (
        not immediate_damages
        or immediate_damages[0] <= 0.0
        or not final_damages
        or final_damages[0] <= 0.0
        or resolver_hit_counts[0] <= 0
    ):
        raise VerifyFailure(
            f"{direction.name} {label} stock staff resolver dealt no primary damage: "
            f"immediate={immediate_damages} final={final_damages} "
            f"hits={resolver_hit_counts} trace={damage_trace}"
        )
    return {
        "direction": direction.name,
        "label": label,
        "variant": variant,
        "placement": placement,
        "positions": positions,
        "targets": [target.__dict__ for target in targets],
        "before": before,
        "point_blank_target": point_blank_target,
        "point_blank_placement": point_blank_placement,
        "trace_arm": trace_arm,
        "call": call,
        "damage_trace": damage_trace,
        "after": after,
        "resolved_damage_return": resolved_damage_return,
        "immediate_damages": immediate_damages,
        "final_damages": final_damages,
        "resolver_hit_counts": resolver_hit_counts,
        "damage_per_hit": damage_per_hit,
        "primary_damage": immediate_damages[0],
        "primary_final_damage": final_damages[0],
        "primary_hit_count": resolver_hit_counts[0],
        "primary_damage_per_hit": damage_per_hit[0],
        "owner_after": query(direction.source_pipe),
    }


def target_views(targets: list[StaffTarget]) -> list[dict[str, Any]]:
    return [
        {
            "network_id": target.network_id,
            "host": query_run_enemy_by_network_id(HOST_PIPE, target.network_id),
            "client": query_run_enemy_by_network_id(CLIENT_PIPE, target.network_id),
            "client_snapshot": values(
                CLIENT_PIPE,
                f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local wanted = tonumber('{target.network_id}') or 0
local replicated = sd.world.get_replicated_actors and sd.world.get_replicated_actors() or nil
local found = nil
for _, actor in ipairs(replicated and replicated.actors or {{}}) do
  if (tonumber(actor.network_actor_id) or 0) == wanted then found = actor break end
end
emit('found', found ~= nil)
emit('x', found and found.x or 0)
emit('y', found and found.y or 0)
emit('hp', found and found.hp or 0)
emit('max_hp', found and found.max_hp or 0)
emit('dead', found and found.dead or false)
""",
            ),
        }
        for target in targets
    ]


def wait_for_target_parity(
    targets: list[StaffTarget],
    timeout: float = 8.0,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last = target_views(targets)
        converged = True
        for target, row in zip(targets, last):
            host_x = parse_float(row["host"].get("x"), math.nan)
            host_y = parse_float(row["host"].get("y"), math.nan)
            client_x = parse_float(row["client"].get("x"), math.nan)
            client_y = parse_float(row["client"].get("y"), math.nan)
            snapshot_x = parse_float(row["client_snapshot"].get("x"), math.nan)
            snapshot_y = parse_float(row["client_snapshot"].get("y"), math.nan)
            host_hp = parse_float(row["host"].get("hp"), math.nan)
            client_hp = parse_float(row["client"].get("hp"), math.nan)
            snapshot_hp = parse_float(row["client_snapshot"].get("hp"), math.nan)
            converged = converged and (
                row["host"].get("found") == "true"
                and row["client"].get("found") == "true"
                and row["client_snapshot"].get("found") == "true"
                and all(
                    math.isfinite(value)
                    for value in (
                        host_x,
                        host_y,
                        client_x,
                        client_y,
                        snapshot_x,
                        snapshot_y,
                        host_hp,
                        client_hp,
                        snapshot_hp,
                    )
                )
                and abs(host_hp - client_hp) <= 0.25
                and abs(host_hp - snapshot_hp) <= 0.25
                and math.hypot(host_x - target.x, host_y - target.y) <= 32.0
                and math.hypot(client_x - target.x, client_y - target.y) <= 32.0
                and math.hypot(snapshot_x - target.x, snapshot_y - target.y) <= 32.0
                and math.hypot(host_x - client_x, host_y - client_y) <= 32.0
                and math.hypot(host_x - snapshot_x, host_y - snapshot_y) <= 32.0
            )
        if converged:
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"natural staff target parity timed out: {last}")


def prepare_staff_targeting(
    direction: Direction,
    source_actor: int,
    target: StaffTarget,
) -> dict[str, str]:
    local_target = target.actor_for_pipe(direction.source_pipe)
    result = values(
        direction.source_pipe,
        f"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local actor = tonumber('{source_actor}') or 0
local target = tonumber('{local_target}') or 0
local function offset(name) return sd.debug.layout_offset(name) end
emit('actor', actor)
emit('target', target)
emit('heading', sd.debug.write_float(actor + offset('actor_heading'), {PLAYER_HEADING_EAST}))
emit('aim_x', sd.debug.write_float(actor + offset('actor_aim_target_x'), {target.x:.6f}))
emit('aim_y', sd.debug.write_float(actor + offset('actor_aim_target_y'), {target.y:.6f}))
emit('target_write', sd.debug.write_ptr(actor + offset('actor_current_target_actor'), target))
emit('bucket_write', sd.debug.write_i32(actor + offset('actor_current_target_bucket_delta'), 0))
""",
    )
    if any(
        result.get(key) != "true"
        for key in ("heading", "aim_x", "aim_y", "target_write", "bucket_write")
    ):
        raise VerifyFailure(f"{direction.name} staff targeting failed: {result}")
    return result


def arm_native_damage_trace(pipe_name: str, name: str) -> dict[str, str]:
    result = values(
        pipe_name,
        f"""
local function emit(key, value)
  if value == nil then value = '<nil>' end
  print(key .. '=' .. tostring(value))
end
pcall(sd.debug.untrace_function, {NATIVE_APPLY_DAMAGE})
sd.debug.clear_trace_hits('{name}')
local ok, traced = pcall(sd.debug.trace_function, {NATIVE_APPLY_DAMAGE}, '{name}')
emit('pcall_ok', ok)
emit('trace_ok', ok and traced == true)
emit('error', sd.debug.get_last_error and sd.debug.get_last_error() or '')
""",
    )
    if result.get("trace_ok") != "true":
        raise VerifyFailure(f"failed to arm native staff damage trace: {result}")
    return result


def finish_native_damage_trace(
    pipe_name: str,
    name: str,
    local_targets: list[int],
) -> dict[str, Any]:
    target_csv = ",".join(str(target) for target in local_targets)
    raw = values(
        pipe_name,
        f"""
local function emit(key, value)
  if value == nil then value = '<nil>' end
  print(key .. '=' .. tostring(value))
end
local targets = {{}}
for token in string.gmatch('{target_csv}', '[^,]+') do targets[tonumber(token) or 0] = true end
local hits = sd.debug.get_trace_hits('{name}')
if type(hits) ~= 'table' then hits = {{}} end
local matched = 0
local returns = {{}}
local counts = {{}}
local return_counts = {{}}
for _, hit in ipairs(hits) do
  local target = tonumber(hit.arg0) or 0
  if targets[target] then
    matched = matched + 1
    counts[target] = (counts[target] or 0) + 1
    local return_address = tonumber(hit.ret) or 0
    returns[return_address] = true
    return_counts[target] = return_counts[target] or {{}}
    return_counts[target][return_address] =
      (return_counts[target][return_address] or 0) + 1
  end
end
local return_list = {{}}
for value in pairs(returns) do return_list[#return_list + 1] = value end
table.sort(return_list)
emit('total_hits', #hits)
emit('matched_hits', matched)
emit('return_addresses', table.concat(return_list, ','))
for target, count in pairs(counts) do
  emit('target.' .. tostring(target), count)
  for return_address, return_count in pairs(return_counts[target] or {{}}) do
    emit(
      'target.' .. tostring(target) .. '.return.' .. tostring(return_address),
      return_count)
  end
end
local ok, result = pcall(sd.debug.untrace_function, {NATIVE_APPLY_DAMAGE})
emit('untrace_pcall', ok)
emit('untrace_result', result)
""",
    )

    def parse_csv(key: str) -> list[int]:
        return [int(token) for token in raw.get(key, "").split(",") if token.strip()]

    return_addresses = parse_csv("return_addresses")
    return {
        "total_hits": parse_int_text(raw.get("total_hits"), 0),
        "matched_hits": parse_int_text(raw.get("matched_hits"), 0),
        "return_addresses": return_addresses,
        "target_hit_counts": {
            str(target): parse_int_text(raw.get(f"target.{target}"), 0)
            for target in local_targets
        },
        "target_return_hit_counts": {
            str(target): {
                str(return_address): parse_int_text(
                    raw.get(f"target.{target}.return.{return_address}"),
                    0,
                )
                for return_address in return_addresses
            }
            for target in local_targets
        },
        "raw": raw,
    }


def wait_for_movement_drive(pipe_name: str, timeout: float = 10.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_native_movement_drive(pipe_name)
        if last.get("cleared") == "true":
            if last.get("error"):
                raise VerifyFailure(f"native staff movement drive failed: {last}")
            return last
        time.sleep(0.08)
    raise VerifyFailure(f"native staff movement drive timed out: {last}")


def run_native_staff_contact_trial(
    direction: Direction,
    actor_addresses: list[int],
    label: str,
    *,
    target_offsets: tuple[tuple[float, float], ...] = ((0.0, 0.0),),
    movement_ticks: int = 120,
) -> dict[str, Any]:
    placement = place_staff_participants(direction)
    source_x = float(placement["source_x"])
    source_y = float(placement["source_y"])
    positions = [
        (
            source_x + TARGET_APPROACH_DISTANCE + offset_x,
            source_y + offset_y,
        )
        for offset_x, offset_y in target_offsets
    ]
    targets = configure_natural_staff_targets(actor_addresses, positions)
    before = wait_for_target_parity(targets)
    targeting = prepare_staff_targeting(
        direction,
        int(placement["source_actor"]),
        targets[0],
    )
    trace_name = f"staff_damage_{direction.name}_{label}"
    trace_arm = arm_native_damage_trace(direction.source_pipe, trace_name)
    drive_start = configure_native_movement_drive(direction.source_pipe, movement_ticks)
    drive_end = wait_for_movement_drive(direction.source_pipe)
    time.sleep(0.4)
    local_targets = [target.actor_for_pipe(direction.source_pipe) for target in targets]
    damage_trace = finish_native_damage_trace(
        direction.source_pipe,
        trace_name,
        local_targets,
    )
    after = wait_for_target_parity(targets)

    damages: list[float] = []
    hit_counts: list[int] = []
    damage_per_hit: list[float] = []
    for target, before_row, after_row, local_target in zip(
        targets,
        before,
        after,
        local_targets,
    ):
        before_hp = parse_float(before_row["host"].get("hp"), math.nan)
        after_hp = parse_float(after_row["host"].get("hp"), math.nan)
        damage = before_hp - after_hp
        hits = int(damage_trace["target_hit_counts"].get(str(local_target), 0))
        damages.append(damage)
        hit_counts.append(hits)
        damage_per_hit.append(damage / hits if hits > 0 else math.nan)

    if not damages or damages[0] <= 0.0 or hit_counts[0] <= 0:
        raise VerifyFailure(
            f"{direction.name} {label} produced no native primary staff contact: "
            f"damages={damages} hits={hit_counts} trace={damage_trace}"
        )
    return {
        "direction": direction.name,
        "label": label,
        "placement": placement,
        "positions": positions,
        "targets": [target.__dict__ for target in targets],
        "before": before,
        "targeting": targeting,
        "trace_arm": trace_arm,
        "drive_start": drive_start,
        "drive_end": drive_end,
        "damage_trace": damage_trace,
        "after": after,
        "damages": damages,
        "hit_counts": hit_counts,
        "damage_per_hit": damage_per_hit,
        "primary_damage": damages[0],
        "primary_hit_count": hit_counts[0],
        "primary_damage_per_hit": damage_per_hit[0],
        "owner_after": query(direction.source_pipe),
    }
