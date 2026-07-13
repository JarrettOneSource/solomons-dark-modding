#!/usr/bin/env python3
"""Verify native Fireball Embers fragments for either multiplayer owner."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from cast_state_probe import read_runtime_layout_offset
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    parse_int_text,
    stop_games,
)
from verify_multiplayer_fireball_explode_effect_sync import (
    build_manual_pair,
    cast_fireball_pair,
    launch_pair_ready,
    target_step_summary,
    wait_for_client_target_upgrade,
    wait_for_host_target_upgrade,
)
from verify_multiplayer_level_up_offer_sync import query_progression_entry
from verify_multiplayer_primary_kill_stress import cleanup_live_enemies, parse_float, values
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    Direction,
    HOST_LOG,
    detect_instance_pids,
)


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_fireball_embers_effect_sync.json"
TARGET_SKILL_FILE = "embers.cfg"
EMBERS_OPTION_ID = 17
EMBER_PROJECTILE_TYPE = 0x7D6
EXPECTED_LEVEL_ONE_FRAGMENTS = 4
MAX_FIREBALL_IMPACT_ATTEMPTS = 3
EMBER_FRAGMENT_FACTORY = read_runtime_layout_offset("fire_ember_fragment_factory")
# The secondary target is only a geometry witness here. Fragment creation is
# counted at the native object factory, so keep it away from the impact point.
SECONDARY_OFFSET = (96.0, 0.0)


class FireballImpactMiss(VerifyFailure):
    """The native Fireball cast completed but missed the pinned test target."""


def arm_fragment_trace(pipe_name: str, trace_name: str) -> dict[str, str]:
    escaped_name = json.dumps(trace_name)
    return values(
        pipe_name,
        f"""
pcall(sd.debug.untrace_function, {EMBER_FRAGMENT_FACTORY})
sd.debug.clear_trace_hits({escaped_name})
local ok = sd.debug.trace_function({EMBER_FRAGMENT_FACTORY}, {escaped_name})
print('ok=' .. tostring(ok))
print('error=' .. tostring(sd.debug.get_last_error and sd.debug.get_last_error() or ''))
""",
    )


def sample_fragment_trace(pipe_name: str, trace_name: str) -> dict[str, str]:
    escaped_name = json.dumps(trace_name)
    return values(
        pipe_name,
        f"""
local expected_type = {EMBER_PROJECTILE_TYPE}
local hits = sd.debug.get_trace_hits and sd.debug.get_trace_hits({escaped_name}) or {{}}
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local fragment_count = 0
emit('factory_call_count', #hits)
for index, hit in ipairs(hits) do
  local type_id = tonumber(hit.arg0) or -1
  if type_id == expected_type then fragment_count = fragment_count + 1 end
  if index <= 16 then
    emit('hit.' .. tostring(index) .. '.type_id', type_id)
    emit('hit.' .. tostring(index) .. '.thread_id', hit.thread_id or 0)
    emit('hit.' .. tostring(index) .. '.ret', hit.ret or 0)
  end
end
emit('fragment_type', expected_type)
emit('fragment_count', fragment_count)
""",
    )


def clear_fragment_trace(pipe_name: str, trace_name: str) -> dict[str, str]:
    escaped_name = json.dumps(trace_name)
    return values(
        pipe_name,
        f"""
pcall(sd.debug.untrace_function, {EMBER_FRAGMENT_FACTORY})
sd.debug.clear_trace_hits({escaped_name})
print('ok=true')
""",
    )


def configure_observer_native_embers_suppression(
    pipe_name: str,
    owner_participant_id: int,
    *,
    enabled: bool,
) -> dict[str, str]:
    return values(
        pipe_name,
        f"""
local owner_id = {owner_participant_id}
local option_id = {EMBERS_OPTION_ID}
local enabled = {'true' if enabled else 'false'}
local function emit(k, v) print(k .. '=' .. tostring(v)) end
local function find_entry()
  local participant = sd.bots and sd.bots.get_participant_state and
                      sd.bots.get_participant_state(owner_id) or nil
  local progression = participant and
                      tonumber(participant.progression_runtime_state_address) or 0
  if progression == 0 then return 0 end
  local table_base_offset =
      sd.debug.layout_offset('standalone_wizard_progression_table_base')
  local table_count_offset =
      sd.debug.layout_offset('standalone_wizard_progression_table_count')
  local entry_stride =
      sd.debug.layout_offset('standalone_wizard_progression_entry_stride')
  local table_address =
      tonumber(sd.debug.read_u32(progression + table_base_offset)) or 0
  local table_count =
      tonumber(sd.debug.read_i32(progression + table_count_offset)) or 0
  if table_address == 0 or table_count <= option_id then return 0 end
  return table_address + (option_id * entry_stride)
end
local function force_baseline_embers()
  if not _G.__sdmod_force_observer_native_embers_off then return end
  local entry = find_entry()
  if entry == 0 then return end
  local active_offset =
      sd.debug.layout_offset('standalone_wizard_progression_active_flag')
  sd.debug.write_u16(entry + active_offset, 0)
end
local entry = find_entry()
local active_offset =
    sd.debug.layout_offset('standalone_wizard_progression_active_flag')
if enabled then
  if entry ~= 0 then
    _G.__sdmod_force_observer_native_embers_saved_active =
        tonumber(sd.debug.read_u16(entry + active_offset)) or 0
  end
  _G.__sdmod_force_observer_native_embers_off = true
  if not _G.__sdmod_force_observer_native_embers_registered then
    sd.events.on('runtime.tick', force_baseline_embers)
    _G.__sdmod_force_observer_native_embers_registered = true
  end
  force_baseline_embers()
else
  _G.__sdmod_force_observer_native_embers_off = false
  local saved =
      tonumber(_G.__sdmod_force_observer_native_embers_saved_active) or 0
  if entry ~= 0 then sd.debug.write_u16(entry + active_offset, saved) end
end
emit('entry', entry)
emit('enabled', _G.__sdmod_force_observer_native_embers_off == true)
emit('registered', _G.__sdmod_force_observer_native_embers_registered == true)
emit('active', entry ~= 0 and sd.debug.read_u16(entry + active_offset) or -1)
emit('saved_active', _G.__sdmod_force_observer_native_embers_saved_active or -1)
""",
    )


def query_replicated_ember_sync(
    pipe_name: str,
    owner_participant_id: int,
) -> dict[str, str]:
    return values(
        pipe_name,
        f"""
local owner_id = {owner_participant_id}
local ember_type = {EMBER_PROJECTILE_TYPE}
local root = sd.world.get_replicated_spell_effects and
             sd.world.get_replicated_spell_effects() or nil
local function emit(k, v) print(k .. '=' .. tostring(v)) end
if root == nil then
  emit('available', false)
  return
end
emit('available', true)
local native_ember_count = 0
for _, native_effect in ipairs(root.native_effects or {{}}) do
  if tonumber(native_effect.native_type_id) == ember_type then
    native_ember_count = native_ember_count + 1
    if native_ember_count <= 8 then
      local prefix = 'native.' .. tostring(native_ember_count) .. '.'
      emit(prefix .. 'actor', native_effect.actor_address or 0)
      emit(prefix .. 'slot', native_effect.actor_slot or -999)
      emit(prefix .. 'x', native_effect.x or 0)
      emit(prefix .. 'y', native_effect.y or 0)
      emit(prefix .. 'created_ms', native_effect.created_ms or 0)
    end
  end
end
emit('native.ember_count', native_ember_count)
local snapshot_ember_count = 0
local snapshot_active_count = 0
local snapshot_terminal_count = 0
local snapshot_transform_count = 0
local snapshot_motion_count = 0
local snapshot_runtime_count = 0
local snapshot_found = false
local detail_index = 0
for _, snapshot in ipairs(root.snapshots or {{}}) do
  if tonumber(snapshot.owner_participant_id) == owner_id then
    snapshot_found = true
    emit('snapshot.sequence', snapshot.sequence or 0)
    emit('snapshot.run_nonce', snapshot.run_nonce or 0)
    emit('snapshot.effect_total_count', snapshot.effect_total_count or 0)
    emit('snapshot.truncated', snapshot.truncated or false)
    for _, effect in ipairs(snapshot.effects or {{}}) do
      if tonumber(effect.native_type_id) == ember_type then
        snapshot_ember_count = snapshot_ember_count + 1
        if effect.active then snapshot_active_count = snapshot_active_count + 1 end
        if effect.terminal then snapshot_terminal_count = snapshot_terminal_count + 1 end
        if effect.transform_valid then snapshot_transform_count = snapshot_transform_count + 1 end
        if effect.motion_valid then snapshot_motion_count = snapshot_motion_count + 1 end
        if effect.ember_runtime_valid then snapshot_runtime_count = snapshot_runtime_count + 1 end
        detail_index = detail_index + 1
        if detail_index <= 8 then
          local prefix = 'effect.' .. tostring(detail_index) .. '.'
          emit(prefix .. 'serial', effect.effect_serial or 0)
          emit(prefix .. 'cast_sequence', effect.cast_sequence or 0)
          emit(prefix .. 'ordinal', effect.effect_ordinal or 0)
          emit(prefix .. 'active', effect.active or false)
          emit(prefix .. 'terminal', effect.terminal or false)
          emit(prefix .. 'x', effect.position_x or 0)
          emit(prefix .. 'y', effect.position_y or 0)
          emit(prefix .. 'motion_x', effect.motion_x or 0)
          emit(prefix .. 'motion_y', effect.motion_y or 0)
          emit(prefix .. 'lifetime', effect.ember_lifetime or 0)
          emit(prefix .. 'variant', effect.ember_variant or 0)
          emit(prefix .. 'frame_interval', effect.ember_frame_interval or 0)
        end
      end
    end
  end
end
emit('snapshot.found', snapshot_found)
emit('snapshot.ember_count', snapshot_ember_count)
emit('snapshot.active_count', snapshot_active_count)
emit('snapshot.terminal_count', snapshot_terminal_count)
emit('snapshot.transform_count', snapshot_transform_count)
emit('snapshot.motion_count', snapshot_motion_count)
emit('snapshot.ember_runtime_count', snapshot_runtime_count)

local apply = root.apply or {{}}
emit('apply.valid', apply.valid or false)
emit('apply.reconcile_revision', apply.reconcile_revision or 0)
emit('apply.effect_count', apply.effect_count or 0)
emit('apply.matched_effect_count', apply.matched_effect_count or 0)
emit('apply.matched_ember_effect_count', apply.matched_ember_effect_count or 0)
emit('apply.created_ember_effect_count', apply.created_ember_effect_count or 0)
emit('apply.terminal_effect_count', apply.terminal_effect_count or 0)
emit('apply.max_matched_effect_count', apply.max_matched_effect_count or 0)
emit('apply.max_matched_ember_effect_count', apply.max_matched_ember_effect_count or 0)
emit('apply.cumulative_transform_write_count', apply.cumulative_transform_write_count or 0)
emit('apply.cumulative_motion_write_count', apply.cumulative_motion_write_count or 0)
emit('apply.cumulative_ember_runtime_write_count', apply.cumulative_ember_runtime_write_count or 0)
emit('apply.cumulative_ember_create_count', apply.cumulative_ember_create_count or 0)
emit('apply.cumulative_terminal_write_count', apply.cumulative_terminal_write_count or 0)
local binding_count = 0
local matched_binding_count = 0
local max_position_error = 0
for _, binding in ipairs(apply.bindings or {{}}) do
  if tonumber(binding.owner_participant_id) == owner_id and
     tonumber(binding.native_type_id) == ember_type then
    binding_count = binding_count + 1
    if binding.matched then matched_binding_count = matched_binding_count + 1 end
    local error_value = tonumber(binding.position_error) or 0
    if error_value > max_position_error then max_position_error = error_value end
    if binding_count <= 8 then
      local prefix = 'binding.' .. tostring(binding_count) .. '.'
      emit(prefix .. 'serial', binding.effect_serial or 0)
      emit(prefix .. 'ordinal', binding.effect_ordinal or 0)
      emit(prefix .. 'actor', binding.local_actor_address or 0)
      emit(prefix .. 'owner_gameplay_slot', binding.owner_gameplay_slot or -999)
      emit(prefix .. 'owner_actor_slot', binding.owner_actor_slot or -999)
      emit(prefix .. 'local_actor_slot', binding.local_actor_slot or -999)
      emit(prefix .. 'matched', binding.matched or false)
      emit(prefix .. 'active', binding.active or false)
      emit(prefix .. 'terminal', binding.terminal or false)
      emit(prefix .. 'authoritative_x', binding.authoritative_x or 0)
      emit(prefix .. 'authoritative_y', binding.authoritative_y or 0)
      emit(prefix .. 'local_x', binding.local_x or 0)
      emit(prefix .. 'local_y', binding.local_y or 0)
      emit(prefix .. 'position_error', binding.position_error or 0)
    end
  end
end
emit('binding.ember_count', binding_count)
emit('binding.matched_count', matched_binding_count)
emit('binding.max_position_error', max_position_error)
""",
    )


def ember_sync_score(sample: dict[str, str]) -> tuple[int, int, int, int]:
    return (
        parse_int_text(sample.get("apply.max_matched_ember_effect_count"), 0),
        parse_int_text(sample.get("apply.cumulative_ember_runtime_write_count"), 0),
        parse_int_text(sample.get("snapshot.ember_count"), 0),
        parse_int_text(sample.get("binding.matched_count"), 0),
    )


def wait_for_replicated_ember_sync(
    pipe_name: str,
    owner_participant_id: int,
    *,
    timeout: float,
    required: bool,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    attempts: list[dict[str, str]] = []
    best: dict[str, str] = {}
    while time.monotonic() < deadline:
        sample = query_replicated_ember_sync(pipe_name, owner_participant_id)
        attempts.append(sample)
        if not best or ember_sync_score(sample) > ember_sync_score(best):
            best = sample
        ready = (
            parse_int_text(sample.get("snapshot.ember_count"), 0)
            >= EXPECTED_LEVEL_ONE_FRAGMENTS
            and parse_int_text(sample.get("snapshot.transform_count"), 0)
            >= EXPECTED_LEVEL_ONE_FRAGMENTS
            and parse_int_text(sample.get("snapshot.motion_count"), 0)
            >= EXPECTED_LEVEL_ONE_FRAGMENTS
            and parse_int_text(sample.get("snapshot.ember_runtime_count"), 0)
            >= EXPECTED_LEVEL_ONE_FRAGMENTS
            and parse_int_text(sample.get("apply.max_matched_ember_effect_count"), 0)
            >= EXPECTED_LEVEL_ONE_FRAGMENTS
            and parse_int_text(sample.get("apply.cumulative_transform_write_count"), 0) > 0
            and parse_int_text(sample.get("apply.cumulative_motion_write_count"), 0) > 0
            and parse_int_text(sample.get("apply.cumulative_ember_runtime_write_count"), 0) > 0
            and (
                parse_int_text(sample.get("binding.matched_count"), 0)
                + parse_int_text(sample.get("snapshot.terminal_count"), 0)
            ) >= EXPECTED_LEVEL_ONE_FRAGMENTS
            and parse_float(sample.get("binding.max_position_error"), 9999.0) <= 0.05
        )
        if ready:
            return {
                "ok": True,
                "best": sample,
                "last": sample,
                "attempt_count": len(attempts),
            }
        time.sleep(0.04)

    result = {
        "ok": False,
        "best": best,
        "last": attempts[-1] if attempts else {},
        "attempt_count": len(attempts),
    }
    if required:
        raise VerifyFailure(
            "observer did not bind/synchronize four owner-authored Ember runtime states: "
            f"{result}"
        )
    return result


def wait_for_replicated_ember_terminal(
    pipe_name: str,
    owner_participant_id: int,
    *,
    timeout: float = 4.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    best: dict[str, str] = {}
    attempts = 0
    terminal_serials: set[int] = set()
    while time.monotonic() < deadline:
        sample = query_replicated_ember_sync(pipe_name, owner_participant_id)
        attempts += 1
        for index in range(1, EXPECTED_LEVEL_ONE_FRAGMENTS + 1):
            if sample.get(f"effect.{index}.terminal") == "true":
                serial = parse_int_text(sample.get(f"effect.{index}.serial"), 0)
                if serial > 0:
                    terminal_serials.add(serial)
        # Count distinct owner-authored Ember serials. Aggregate apply/write
        # counts can include a Fireball or repeat writes to one child and do
        # not prove complete lifecycle convergence.
        if len(terminal_serials) >= EXPECTED_LEVEL_ONE_FRAGMENTS:
            return {
                "ok": True,
                "sample": sample,
                "terminal_serials": sorted(terminal_serials),
                "attempt_count": attempts,
            }
        if not best or ember_sync_score(sample) >= ember_sync_score(best):
            best = sample
        time.sleep(0.05)
    raise VerifyFailure(
        "observer never received/applied terminal Ember lifecycle state: "
        f"terminal_serials={sorted(terminal_serials)} best={best} attempts={attempts}"
    )


def run_fragment_phase(
    direction: Direction,
    phase: str,
    *,
    force_observer_materialization: bool = False,
) -> dict[str, Any]:
    cleanup = cleanup_live_enemies()
    pair = build_manual_pair(direction, *SECONDARY_OFFSET)
    trace_names = {
        "owner": f"fireball_embers.{direction.name}.{phase}.owner",
        "observer": f"fireball_embers.{direction.name}.{phase}.observer",
    }
    arms = {
        "owner": arm_fragment_trace(direction.source_pipe, trace_names["owner"]),
        "observer": arm_fragment_trace(direction.receiver_pipe, trace_names["observer"]),
    }
    bad_arms = {side: result for side, result in arms.items() if result.get("ok") != "true"}
    if bad_arms:
        for side, pipe_name in (
            ("owner", direction.source_pipe),
            ("observer", direction.receiver_pipe),
        ):
            try:
                clear_fragment_trace(pipe_name, trace_names[side])
            except Exception:
                pass
        raise VerifyFailure(f"{direction.name} {phase}: failed to arm Ember factory traces: {bad_arms}")

    cast: dict[str, Any] | None = None
    cast_error: Exception | None = None
    samples: dict[str, dict[str, str]] = {}
    clears: dict[str, dict[str, str]] = {}
    effect_sync: dict[str, Any] = {}
    suppression: dict[str, Any] = {}
    pre_materialization = query_replicated_ember_sync(
        direction.receiver_pipe,
        direction.source_id,
    )

    def configure_suppression() -> dict[str, str] | None:
        if not force_observer_materialization:
            return None
        arm = configure_observer_native_embers_suppression(
            direction.receiver_pipe,
            direction.source_id,
            enabled=True,
        )
        suppression["arm"] = arm
        if arm.get("entry") in (None, "0") or arm.get("active") != "0":
            raise VerifyFailure(
                f"{direction.name} {phase}: could not suppress observer native Embers: {arm}"
            )
        return arm

    def capture_effect_sync() -> dict[str, Any]:
        nonlocal effect_sync
        effect_sync = wait_for_replicated_ember_sync(
            direction.receiver_pipe,
            direction.source_id,
            timeout=2.0 if phase != "baseline" else 0.35,
            required=phase != "baseline",
        )
        return effect_sync

    try:
        cast = cast_fireball_pair(
            direction,
            pair,
            f"fireball_embers.{direction.name}.{phase}",
            before_source_cast=configure_suppression,
            after_source_cast=capture_effect_sync,
        )
    except Exception as exc:
        cast_error = exc
    finally:
        if force_observer_materialization:
            try:
                suppression["clear"] = configure_observer_native_embers_suppression(
                    direction.receiver_pipe,
                    direction.source_id,
                    enabled=False,
                )
            except Exception as exc:
                suppression["clear"] = {"error": str(exc)}
        for side, pipe_name in (
            ("owner", direction.source_pipe),
            ("observer", direction.receiver_pipe),
        ):
            try:
                samples[side] = sample_fragment_trace(pipe_name, trace_names[side])
            except Exception as exc:
                samples[side] = {"error": str(exc)}
            try:
                clears[side] = clear_fragment_trace(pipe_name, trace_names[side])
            except Exception as exc:
                clears[side] = {"error": str(exc)}

    if cast_error is not None:
        raise VerifyFailure(
            f"{direction.name} {phase}: Fireball cast failed: {cast_error}; traces={samples}"
        ) from cast_error
    assert cast is not None
    if not cast["damage"]["primary_damaged"]:
        raise FireballImpactMiss(
            f"{direction.name} {phase}: Fireball never reached its primary target: "
            f"lane={pair['lane']} prepare={cast['prepare']} "
            f"damage={cast['damage']} impact_trace={cast['impact_trace']['sample']} "
            f"factory_traces={samples}"
        )
    if not cast.get("replicated_cast_delivery", {}).get("ok"):
        raise VerifyFailure(
            f"{direction.name} {phase}: cast did not execute natively on owner and observer: "
            f"{cast.get('replicated_cast_delivery')}"
        )

    counts = {
        side: parse_int_text(sample.get("fragment_count"), -1)
        for side, sample in samples.items()
    }
    terminal_sync = (
        wait_for_replicated_ember_terminal(
            direction.receiver_pipe,
            direction.source_id,
        )
        if phase != "baseline"
        else {"ok": True, "not_applicable": True}
    )
    post_materialization = query_replicated_ember_sync(
        direction.receiver_pipe,
        direction.source_id,
    )
    materialized_count = max(
        0,
        parse_int_text(
            post_materialization.get("apply.cumulative_ember_create_count"),
            0,
        )
        - parse_int_text(
            pre_materialization.get("apply.cumulative_ember_create_count"),
            0,
        ),
    )
    return {
        "cleanup": cleanup,
        "pair": pair,
        "cast": cast,
        "trace": {
            "address": f"0x{EMBER_FRAGMENT_FACTORY:08X}",
            "fragment_type": f"0x{EMBER_PROJECTILE_TYPE:X}",
            "names": trace_names,
            "arm": arms,
            "sample": samples,
            "clear": clears,
            "fragment_counts": counts,
        },
        "network_effect_sync": {
            "capture": effect_sync,
            "terminal": terminal_sync,
            "materialized_count": materialized_count,
            "pre_materialization": pre_materialization,
            "post_materialization": post_materialization,
        },
        "observer_native_embers_suppression": suppression,
    }


def run_fragment_phase_with_impact_retry(
    direction: Direction,
    phase: str,
    *,
    force_observer_materialization: bool = False,
) -> dict[str, Any]:
    misses: list[str] = []
    for attempt in range(1, MAX_FIREBALL_IMPACT_ATTEMPTS + 1):
        try:
            result = run_fragment_phase(
                direction,
                phase,
                force_observer_materialization=force_observer_materialization,
            )
            result["impact_attempt_count"] = attempt
            result["impact_retry_misses"] = misses
            return result
        except FireballImpactMiss as exc:
            misses.append(str(exc))
            if attempt == MAX_FIREBALL_IMPACT_ATTEMPTS:
                raise VerifyFailure(
                    f"{direction.name} {phase}: native Fireball missed the pinned "
                    f"target in all {MAX_FIREBALL_IMPACT_ATTEMPTS} attempts: {misses}"
                ) from exc
            time.sleep(0.2)

    raise AssertionError("unreachable Fireball impact retry state")


def direction_for_owner(owner: str, pids: dict[str, int]) -> Direction:
    if owner == "host":
        return Direction(
            "host_to_client_fireball_embers",
            HOST_ID,
            HOST_NAME,
            HOST_PIPE,
            HOST_LOG,
            pids["host"],
            CLIENT_PIPE,
            CLIENT_LOG,
        )
    return Direction(
        "client_to_host_fireball_embers",
        CLIENT_ID,
        CLIENT_NAME,
        CLIENT_PIPE,
        CLIENT_LOG,
        pids["client"],
        HOST_PIPE,
        HOST_LOG,
    )


def progression_views(direction: Direction) -> dict[str, dict[str, Any]]:
    return {
        "owner": query_progression_entry(
            direction.source_pipe,
            option_id=EMBERS_OPTION_ID,
        ),
        "observer": query_progression_entry(
            direction.receiver_pipe,
            option_id=EMBERS_OPTION_ID,
            participant_id=direction.source_id,
        ),
    }


def run_verifier(timeout: float, *, owner: str = "client") -> dict[str, Any]:
    output: dict[str, Any] = {
        "ok": False,
        "owner": owner,
        "native_path": {
            "fragment_factory": f"0x{EMBER_FRAGMENT_FACTORY:08X}",
            "fragment_type": f"0x{EMBER_PROJECTILE_TYPE:X}",
            "expected_level_one_fragments": EXPECTED_LEVEL_ONE_FRAGMENTS,
            "reverse_engineered_impact_dispatch": "0x00642BF0",
        },
    }
    startup = launch_pair_ready(timeout)
    output["startup"] = {"attempt": startup["attempt"]}
    output["launch"] = startup["launch"]
    output["hub_ready"] = startup["hub_ready"]
    output["run_entry"] = startup["run_entry"]
    output["run_ready"] = startup["run_ready"]
    output["manual_combat"] = startup["manual_combat"]

    direction = direction_for_owner(owner, detect_instance_pids())
    output["pre_upgrade_progression"] = progression_views(direction)
    output["baseline"] = run_fragment_phase_with_impact_retry(direction, "baseline")
    baseline_counts = output["baseline"]["trace"]["fragment_counts"]
    if baseline_counts != {"owner": 0, "observer": 0}:
        raise VerifyFailure(
            f"baseline Fireball unexpectedly created Ember projectiles: {baseline_counts}"
        )

    output["upgrade"] = (
        wait_for_host_target_upgrade(
            timeout,
            target_skill_file=TARGET_SKILL_FILE,
        )
        if owner == "host"
        else wait_for_client_target_upgrade(
            timeout,
            target_skill_file=TARGET_SKILL_FILE,
        )
    )
    step_record = output["upgrade"]["step_record"]
    selected_option = step_record["offer"]["enriched_options"][
        step_record["offer"]["selected_option_index"] - 1
    ]
    output["upgrade_result_summary"] = {
        "selected_option_id": step_record["offer"]["selected_option_id"],
        "selected_option_index": step_record["offer"]["selected_option_index"],
        "selected_skill_file": selected_option["skill_file"],
        "step": target_step_summary(step_record),
    }
    if step_record["offer"]["selected_option_id"] != EMBERS_OPTION_ID:
        raise VerifyFailure(f"Embers selection used the wrong native entry: {step_record}")

    output["post_upgrade_progression"] = progression_views(direction)
    for side, entry in output["post_upgrade_progression"].items():
        if entry["active"] < 1 or entry["visible"] < 1:
            raise VerifyFailure(f"{side} did not expose active native Embers entry 17: {entry}")

    output["upgraded"] = run_fragment_phase_with_impact_retry(direction, "upgraded")
    upgraded_counts = output["upgraded"]["trace"]["fragment_counts"]
    expected_counts = {
        "owner": EXPECTED_LEVEL_ONE_FRAGMENTS,
        "observer": EXPECTED_LEVEL_ONE_FRAGMENTS,
    }
    if upgraded_counts != expected_counts:
        raise VerifyFailure(
            "upgraded Fireball did not create exactly four native Ember projectiles "
            f"on owner and observer: expected={expected_counts} actual={upgraded_counts}"
        )

    upgraded_effect_sync = output["upgraded"]["network_effect_sync"]
    if not upgraded_effect_sync["capture"].get("ok"):
        raise VerifyFailure(
            f"owner-authored Ember runtime state never converged: {upgraded_effect_sync}"
        )
    if not upgraded_effect_sync["terminal"].get("ok"):
        raise VerifyFailure(
            f"owner-authored Ember terminal state never converged: {upgraded_effect_sync}"
        )

    output["forced_materialization"] = run_fragment_phase_with_impact_retry(
        direction,
        "forced_materialization",
        force_observer_materialization=True,
    )
    forced_counts = output["forced_materialization"]["trace"]["fragment_counts"]
    forced_sync = output["forced_materialization"]["network_effect_sync"]
    if forced_counts != expected_counts:
        raise VerifyFailure(
            "observer fallback did not preserve four Ember objects while native "
            f"observer Embers were suppressed: expected={expected_counts} actual={forced_counts}"
        )
    if forced_sync["materialized_count"] < EXPECTED_LEVEL_ONE_FRAGMENTS:
        raise VerifyFailure(
            "observer did not materialize all four missing owner-authored Embers: "
            f"{forced_sync}"
        )

    output["behavior_transition"] = {
        "baseline_fragment_counts": baseline_counts,
        "upgraded_fragment_counts": upgraded_counts,
        "expected_level_one_fragments": EXPECTED_LEVEL_ONE_FRAGMENTS,
        "network_effect_sync": {
            "transform": True,
            "motion": True,
            "ember_runtime": True,
            "terminal": True,
            "max_position_error": parse_float(
                upgraded_effect_sync["capture"]["best"].get(
                    "binding.max_position_error"
                ),
                9999.0,
            ),
            "forced_materialization_count": forced_sync["materialized_count"],
        },
        "ok": True,
    }
    output["ok"] = True
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--owner", choices=("host", "client"), default="client")
    parser.add_argument("--output", type=Path, default=RUNTIME_OUTPUT)
    args = parser.parse_args()

    try:
        result = run_verifier(args.timeout, owner=args.owner)
    except Exception as exc:
        result = {"ok": False, "owner": args.owner, "error": str(exc)}
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        stop_games()
        return 1

    result["output"] = str(args.output)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    stop_games()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
