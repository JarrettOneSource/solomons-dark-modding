#!/usr/bin/env python3
"""Verify multiplayer player animation, low-mana casting, and element cast sync."""

from __future__ import annotations

import json
import math
import re
import time
import argparse
from dataclasses import dataclass
from pathlib import Path

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    stop_games,
    wait_for_remote,
)
from verify_player_health_death_sync import query_remote_participant
from verify_multiplayer_primary_kill_stress import enable_manual_stock_spawner_combat
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    HOST_LOG,
    Direction,
    count_lines,
    detect_instance_pids,
    ensure_testrun,
    log_after,
    parse_local_pressed_sequences,
    parse_phase_counts,
    parse_remote_prep_sequences,
    parse_remote_queue_sequences,
    parse_remote_settle_sequences,
    read_log,
    sustain_pair_vitals,
    wait_for_source_cast,
)
from multiplayer_telemetry import MultiplayerTelemetryRecorder


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "multiplayer_animation_mana_elements.json"
TELEMETRY_PATH = ROOT / "runtime" / "multiplayer_animation_mana_elements_telemetry.jsonl"
TELEMETRY: MultiplayerTelemetryRecorder | None = None
PROJECTILE_TYPES = (0x7D3, 0x7D4, 0x7D5)
FIRE_TAP_FRAMES = 2
TAP_FRAMES = 12
HOLD_FRAMES = 170
ELEMENT_IDS = {
    "fire": 0,
    "water": 1,
    "earth": 2,
    "air": 3,
    "ether": 4,
}
ANIMATION_FLOAT_TOLERANCE = 0.04
ANIMATION_HISTORY_SECONDS = 0.55
ANIMATION_MATCH_SAMPLE_COUNT = 3
CAST_FACING_TOLERANCE_DEGREES = 2.0
CAST_FACING_MATCH_SAMPLE_COUNT = 2
ANIMATION_MATCH_TOLERANCES = {
    "walk_cycle_primary": 0.18,
    "walk_cycle_secondary": 0.18,
    "render_drive_stride": 0.12,
    "render_advance_rate": 0.18,
    "render_advance_phase": 0.18,
    "render_drive_overlay_alpha": 0.12,
    "render_drive_move_blend": 0.18,
}


@dataclass(frozen=True)
class ElementSpec:
    element: str
    presentation: str
    mode: str
    projectile_type: int | None = None
    frames: int = TAP_FRAMES

    @property
    def preset(self) -> str:
        return f"map_create_{self.element}_mind_hub"


ELEMENTS = (
    ElementSpec("fire", "fireball", "projectile", 0x7D4, FIRE_TAP_FRAMES),
    ElementSpec("earth", "earth_boulder", "projectile", 0x7D5, HOLD_FRAMES),
    ElementSpec("ether", "ether_projectile", "projectile", 0x7D3, TAP_FRAMES),
    ElementSpec("water", "frost_continuous", "continuous", None, HOLD_FRAMES),
    ElementSpec("air", "lightning_continuous", "continuous", None, HOLD_FRAMES),
)
ELEMENT_BY_NAME = {spec.element: spec for spec in ELEMENTS}


def record_telemetry(label: str, **extra: object) -> None:
    if TELEMETRY is not None:
        TELEMETRY.record(label, **extra)


def sample_telemetry_window(label: str, *, duration: float, interval: float = 0.2, **extra: object) -> None:
    if TELEMETRY is not None:
        TELEMETRY.sample_window(label, duration=duration, interval=interval, **extra)


def parse_int(value: object, default: int = -1) -> int:
    try:
        if value is None:
            return default
        return int(str(value), 0)
    except (TypeError, ValueError):
        return default


def values(pipe_name: str, code: str, timeout: float = 5.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def wait_for_remote_profile(
    observer_pipe: str,
    participant_id: int,
    participant_name: str,
    expected_element_id: int,
    scene_label: str,
    timeout: float = 15.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_remote_participant(observer_pipe, participant_id)
        if (
            last.get("available") == "true"
            and parse_int(last.get("profile.element_id")) == expected_element_id
        ):
            return last
        time.sleep(0.25)
    raise VerifyFailure(
        f"{scene_label}: remote profile for {participant_name} did not settle to "
        f"element_id={expected_element_id}; last={last}"
    )


def wait_for_element_profile_sync(spec: ElementSpec, scene_label: str) -> dict[str, dict[str, str]]:
    expected_element_id = ELEMENT_IDS[spec.element]
    return {
        "host_observes_client": wait_for_remote_profile(
            HOST_PIPE,
            CLIENT_ID,
            CLIENT_NAME,
            expected_element_id,
            scene_label,
        ),
        "client_observes_host": wait_for_remote_profile(
            CLIENT_PIPE,
            HOST_ID,
            HOST_NAME,
            expected_element_id,
            scene_label,
        ),
    }


def launch_element_pair(spec: ElementSpec) -> dict[str, object]:
    record_telemetry("element.launch.start", element=spec.element, preset=spec.preset)
    launch = launch_pair(preset=spec.preset)
    record_telemetry("element.launch.ready", element=spec.element, launch=launch)
    pids = detect_instance_pids()
    wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
    wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")
    hub_profiles = wait_for_element_profile_sync(spec, "hub")
    record_telemetry("element.hub.ready", element=spec.element, pids=pids)
    run_entry = ensure_testrun()
    record_telemetry("element.run_entry.dispatched", element=spec.element, run_entry=run_entry)
    wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
    wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")
    run_profiles = wait_for_element_profile_sync(spec, "testrun")
    record_telemetry("element.run.ready", element=spec.element)
    disable_bots()
    combat = enable_manual_stock_spawner_combat()
    vitals = sustain_pair_vitals()
    record_telemetry("element.vitals.sustained", element=spec.element)
    record_telemetry("element.combat.started", element=spec.element, combat=combat)
    vitals_after_combat = sustain_pair_vitals()
    record_telemetry("element.combat.vitals_sustained", element=spec.element)
    return {
        "launch": launch,
        "pids": pids,
        "hub_profiles": hub_profiles,
        "run_entry": run_entry,
        "run_profiles": run_profiles,
        "vitals": vitals,
        "combat": combat,
        "vitals_after_combat": vitals_after_combat,
    }


def projectile_sample(pipe_name: str) -> dict[str, object]:
    code = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local counts = {}
local addresses = {}
for _, type_id in ipairs({0x7D3, 0x7D4, 0x7D5}) do
  counts[type_id] = 0
  addresses[type_id] = {}
end
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  if counts[type_id] ~= nil then
    counts[type_id] = counts[type_id] + 1
    table.insert(addresses[type_id], tostring(actor.actor_address or 0))
  end
end
for _, type_id in ipairs({0x7D3, 0x7D4, 0x7D5}) do
  emit(string.format("type_0x%X_count", type_id), counts[type_id])
  emit(string.format("type_0x%X_addresses", type_id), table.concat(addresses[type_id], ","))
end
"""
    raw = values(pipe_name, code, timeout=4.0)
    parsed: dict[str, object] = {"raw": raw}
    for type_id in PROJECTILE_TYPES:
        key = f"type_0x{type_id:X}"
        addresses = {
            item
            for item in raw.get(f"{key}_addresses", "").split(",")
            if item and item != "0"
        }
        parsed[f"{key}_count"] = int(float(raw.get(f"{key}_count", "0") or "0"))
        parsed[f"{key}_addresses"] = sorted(addresses)
    return parsed


def sample_projectiles(pipe_name: str, duration: float) -> dict[str, object]:
    deadline = time.monotonic() + duration
    max_counts = {type_id: 0 for type_id in PROJECTILE_TYPES}
    addresses = {type_id: set[str]() for type_id in PROJECTILE_TYPES}
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        last = projectile_sample(pipe_name)
        for type_id in PROJECTILE_TYPES:
            key = f"type_0x{type_id:X}"
            max_counts[type_id] = max(max_counts[type_id], int(last[f"{key}_count"]))
            addresses[type_id].update(last[f"{key}_addresses"])
        time.sleep(0.05)
    return {
        "max_counts": {f"0x{type_id:X}": count for type_id, count in max_counts.items()},
        "addresses": {f"0x{type_id:X}": sorted(items) for type_id, items in addresses.items()},
        "last": last,
    }


def set_player_mana(pipe_name: str, mp: float, max_mp: float) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local progression = tonumber(player.progression_address) or 0
if progression == 0 then
  progression = tonumber(sd.debug.read_ptr(player.actor_address + sd.debug.layout_offset("actor_progression_runtime_state"))) or 0
end
if progression == 0 then
  error("player progression unavailable")
end
local omp = sd.debug.layout_offset("progression_mp")
local omaxmp = sd.debug.layout_offset("progression_max_mp")
emit("before.mp", player.mp or 0)
emit("before.max_mp", player.max_mp or 0)
emit("write.max_mp", sd.debug.write_float(progression + omaxmp, {max_mp}))
emit("write.mp", sd.debug.write_float(progression + omp, {mp}))
local after = sd.player.get_state()
emit("after.mp", after and after.mp or -1)
emit("after.max_mp", after and after.max_mp or -1)
"""
    result = values(pipe_name, code)
    if result.get("write.max_mp") != "true" or result.get("write.mp") != "true":
        raise VerifyFailure(f"failed to set player mana on {pipe_name}: {result}")
    return result


def clear_local_cast_state(direction: Direction) -> dict[str, str]:
    result = values(
        direction.source_pipe,
        "print('cleared=' .. tostring(sd.input.clear_local_cast_state()))",
        timeout=5.0,
    )
    if result.get("cleared") != "true":
        raise VerifyFailure(f"{direction.name}: failed to clear local cast state: {result}")
    time.sleep(0.25)
    return result


def queue_deterministic_primary(direction: Direction, frames: int) -> dict[str, str]:
    if frames <= 0:
        raise VerifyFailure(f"{direction.name}: frames must be positive")
    result = values(
        direction.source_pipe,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local actor = tonumber(player.actor_address) or 0
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local oaimx = sd.debug.layout_offset("actor_aim_target_x")
local oaimy = sd.debug.layout_offset("actor_aim_target_y")
local oaux0 = sd.debug.layout_offset("actor_aim_target_aux0")
local oaux1 = sd.debug.layout_offset("actor_aim_target_aux1")
local x = sd.debug.read_float(actor + ox)
local y = sd.debug.read_float(actor + oy)
emit("write.heading", sd.debug.write_float(actor + oh, 90.0))
emit("write.aim_x", sd.debug.write_float(actor + oaimx, x + 320.0))
emit("write.aim_y", sd.debug.write_float(actor + oaimy, y))
emit("write.aux0", sd.debug.write_u32(actor + oaux0, 0))
emit("write.aux1", sd.debug.write_u32(actor + oaux1, 0))
emit("expected_heading", 90.0)
emit("mouse_left_frames", sd.input.hold_mouse_left_frames({frames}))
""",
        timeout=5.0,
    )
    required = (
        "write.heading",
        "write.aim_x",
        "write.aim_y",
        "write.aux0",
        "write.aux1",
        "mouse_left_frames",
    )
    if any(result.get(key) != "true" for key in required):
        raise VerifyFailure(f"{direction.name}: failed to aim and queue primary cast: {result}")
    return result


def read_proxy_animation(observer_pipe: str, participant_id: int) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local bot = sd.bots.get_participant_state({participant_id})
if bot == nil or bot.actor_address == nil or bot.actor_address == 0 then
  emit("available", false)
  return
end
local actor = tonumber(bot.actor_address) or 0
local od = sd.debug.layout_offset("actor_animation_drive_state_byte")
local ow1 = sd.debug.layout_offset("actor_walk_cycle_primary")
local ow2 = sd.debug.layout_offset("actor_walk_cycle_secondary")
local os = sd.debug.layout_offset("actor_render_drive_stride_scale")
local orate = sd.debug.layout_offset("actor_render_advance_rate")
local ophase = sd.debug.layout_offset("actor_render_advance_phase")
local oo = sd.debug.layout_offset("actor_render_drive_overlay_alpha")
local ob = sd.debug.layout_offset("actor_render_drive_move_blend")
local oh = sd.debug.layout_offset("actor_heading")
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oaimx = sd.debug.layout_offset("actor_aim_target_x")
local oaimy = sd.debug.layout_offset("actor_aim_target_y")
emit("available", true)
emit("actor", actor)
emit("x", sd.debug.read_float(actor + ox) or 0)
emit("y", sd.debug.read_float(actor + oy) or 0)
emit("heading", bot.heading or 0)
emit("actor_heading", sd.debug.read_float(actor + oh) or 0)
emit("aim_x", sd.debug.read_float(actor + oaimx) or 0)
emit("aim_y", sd.debug.read_float(actor + oaimy) or 0)
emit("drive_word", sd.debug.read_u32(actor + od) or 0)
emit("walk_cycle_primary", sd.debug.read_float(actor + ow1) or 0)
emit("walk_cycle_secondary", sd.debug.read_float(actor + ow2) or 0)
emit("render_drive_stride", sd.debug.read_float(actor + os) or 0)
emit("render_advance_rate", sd.debug.read_float(actor + orate) or 0)
emit("render_advance_phase", sd.debug.read_float(actor + ophase) or 0)
emit("render_drive_overlay_alpha", sd.debug.read_float(actor + oo) or 0)
emit("render_drive_move_blend", sd.debug.read_float(actor + ob) or 0)
emit("cast_active", bot.cast_active or false)
emit("anim_drive_state", bot.anim_drive_state or 0)
emit("hp", bot.hp or 0)
emit("max_hp", bot.max_hp or 0)
emit("mp", bot.mp or 0)
emit("max_mp", bot.max_mp or 0)
"""
    return values(observer_pipe, code)


def read_owner_animation(pipe_name: str) -> dict[str, str]:
    code = f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil or player.actor_address == nil or player.actor_address == 0 then
  error("player actor unavailable")
end
local actor = tonumber(player.actor_address) or 0
emit("available", true)
emit("actor", actor)
emit("drive_word", player.anim_drive_state_word or 0)
emit("walk_cycle_primary", player.walk_cycle_primary or 0)
emit("walk_cycle_secondary", player.walk_cycle_secondary or 0)
emit("render_drive_stride", player.render_drive_stride or 0)
emit("render_advance_rate", player.render_advance_rate or 0)
emit("render_advance_phase", player.render_advance_phase or 0)
emit("render_drive_overlay_alpha", player.render_drive_overlay_alpha or 0)
emit("render_drive_move_blend", player.render_drive_move_blend or 0)
emit("anim_drive_state", player.anim_drive_state or 0)
emit("hp", player.hp or 0)
emit("mp", player.mp or 0)
"""
    return values(pipe_name, code, timeout=4.0)


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def heading_error(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def cast_facing_sample(
    proxy: dict[str, str],
    expected_heading: float,
) -> dict[str, float | bool]:
    proxy_x = number(proxy, "x", float("nan"))
    proxy_y = number(proxy, "y", float("nan"))
    proxy_aim_x = number(proxy, "aim_x", float("nan"))
    proxy_aim_y = number(proxy, "aim_y", float("nan"))
    proxy_aim_heading = (
        math.degrees(math.atan2(proxy_aim_y - proxy_y, proxy_aim_x - proxy_x))
        + 90.0
    ) % 360.0
    proxy_actor_heading = number(proxy, "actor_heading", float("nan"))
    proxy_snapshot_heading = number(proxy, "heading", float("nan"))
    errors = {
        "proxy_actor_to_expected": heading_error(
            proxy_actor_heading,
            expected_heading,
        ),
        "proxy_aim_to_expected": heading_error(
            proxy_aim_heading,
            expected_heading,
        ),
        "proxy_snapshot_to_expected": heading_error(
            proxy_snapshot_heading,
            expected_heading,
        ),
    }
    return {
        "matched": all(
            math.isfinite(error)
            and error <= CAST_FACING_TOLERANCE_DEGREES
            for error in errors.values()
        ),
        "expected_heading": expected_heading,
        "proxy_aim_heading": proxy_aim_heading,
        "proxy_actor_heading": proxy_actor_heading,
        "proxy_snapshot_heading": proxy_snapshot_heading,
        **errors,
    }


def animation_proxy_within_owner_history(
    source_history: list[tuple[float, dict[str, str]]],
    proxy: dict[str, str],
) -> tuple[bool, dict[str, dict[str, float]]]:
    envelope: dict[str, dict[str, float]] = {}
    if not source_history or proxy.get("available") != "true":
        return False, envelope
    for key, tolerance in ANIMATION_MATCH_TOLERANCES.items():
        actual = number(proxy, key, float("nan"))
        values = [
            number(owner, key, float("nan"))
            for _, owner in source_history
            if owner.get("available") == "true"
        ]
        values = [value for value in values if math.isfinite(value)]
        if not values or not math.isfinite(actual):
            return False, envelope
        low = min(values)
        high = max(values)
        envelope[key] = {
            "actual": actual,
            "low": low,
            "high": high,
            "tolerance": tolerance,
        }
        if actual < low - tolerance or actual > high + tolerance:
            return False, envelope
    return True, envelope


def verify_animation_field_replication(direction: Direction) -> dict[str, object]:
    source_history: list[tuple[float, dict[str, str]]] = []
    proxy_samples: list[dict[str, str]] = []
    matches: list[dict[str, object]] = []
    source_variation = {key: [] for key in ANIMATION_MATCH_TOLERANCES}
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        owner = read_owner_animation(direction.source_pipe)
        proxy = read_proxy_animation(direction.receiver_pipe, direction.source_id)
        source_history.append((now, owner))
        proxy_samples.append(proxy)
        for key in ANIMATION_MATCH_TOLERANCES:
            source_variation[key].append(number(owner, key, 0.0))
        source_history = [
            item for item in source_history
            if now - item[0] <= ANIMATION_HISTORY_SECONDS
        ]
        matched, envelope = animation_proxy_within_owner_history(source_history, proxy)
        if matched:
            matches.append({"envelope": envelope, "proxy": proxy})
        if len(matches) >= ANIMATION_MATCH_SAMPLE_COUNT:
            return {
                "mode": "non_cast_presentation",
                "matches": len(matches),
                "last_match": matches[-1],
                "source_variation": {
                    key: (max(values) - min(values)) if values else 0.0
                    for key, values in source_variation.items()
                },
            }
        time.sleep(0.05)
    variation_summary = {
        key: (max(values) - min(values)) if values else 0.0
        for key, values in source_variation.items()
    }
    raise VerifyFailure(
        f"{direction.name}: proxy animation fields did not track owner sampled state; "
        f"matches={len(matches)} variation={variation_summary} "
        f"last_source={source_history[-1][1] if source_history else {}} "
        f"last_proxy={proxy_samples[-1] if proxy_samples else {}}"
    )


def verify_cast_log_flow(
    direction: Direction,
    source_offset: int,
    receiver_offset: int,
    *,
    require_held: bool,
    require_remote_release: bool = False,
) -> dict[str, object]:
    required = {"pressed": 1, "released": 1}
    if require_held:
        required["held"] = 1
    source_log, phase_counts, native_hook_count = wait_for_source_cast(
        direction,
        source_offset,
        required,
        timeout=6.0,
    )
    native_sequences = parse_local_pressed_sequences(source_log, direction.source_id)
    expected_sequences = set(native_sequences)
    receiver_deadline = time.monotonic() + 8.0
    receiver_log = ""
    remote_queue_sequences: list[int] = []
    remote_prep_sequences: list[int] = []
    remote_settle_sequences: list[int] = []
    remote_release_sequences: list[int] = []
    while time.monotonic() < receiver_deadline:
        receiver_log = log_after(direction.receiver_log, receiver_offset)
        remote_queue_sequences = parse_remote_queue_sequences(
            receiver_log,
            direction.source_id,
        )
        remote_prep_sequences = parse_remote_prep_sequences(
            receiver_log,
            direction.source_id,
        )
        remote_settle_sequences = parse_remote_settle_sequences(
            receiver_log,
            direction.source_id,
            observed_only=False,
        )
        remote_release_sequences = [
            int(sequence)
            for sequence in re.findall(
                rf"Multiplayer remote cast input release\. participant_id={direction.source_id} "
                rf"cast_sequence=(\d+) skill_id=\d+",
                receiver_log,
            )
        ]
        queue_ready = bool(expected_sequences.intersection(remote_queue_sequences))
        prep_ready = bool(expected_sequences.intersection(remote_prep_sequences))
        release_ready = (
            not require_remote_release
            or expected_sequences.issubset(set(remote_release_sequences))
        )
        if queue_ready and prep_ready and release_ready:
            break
        if count_lines(receiver_log, "remote_input_timeout"):
            break
        time.sleep(0.05)
    local_targetless_sequences: list[int] = []
    local_marker = (
        f"Multiplayer local cast sent. participant_id={direction.source_id} "
    )
    for line in source_log.splitlines():
        if (
            local_marker not in line
            or "kind=primary" not in line
            or "secondary_slot=-1" not in line
            or "phase=pressed" not in line
            or "target_network_actor_id=0" not in line
        ):
            continue
        sequence_match = re.search(r"cast_sequence=(\d+)", line)
        if sequence_match:
            local_targetless_sequences.append(int(sequence_match.group(1)))

    remote_targetless_queue_sequences: list[int] = []
    remote_marker = (
        f"Multiplayer remote cast queued. participant_id={direction.source_id} "
    )
    for line in receiver_log.splitlines():
        if (
            remote_marker not in line
            or "phase=pressed" not in line
            or "target_network_actor_id=0" not in line
            or "target_actor=0x0" not in line
            or "target_source=none" not in line
        ):
            continue
        sequence_match = re.search(r"cast_sequence=(\d+)", line)
        if sequence_match:
            remote_targetless_queue_sequences.append(
                int(sequence_match.group(1))
            )
    timeout_count = count_lines(receiver_log, "remote_input_timeout")
    if native_hook_count < 1 or not native_sequences:
        raise VerifyFailure(f"{direction.name}: no native cast hook/sequence observed")
    if not set(native_sequences).intersection(remote_queue_sequences):
        raise VerifyFailure(
            f"{direction.name}: remote queue did not include local sequence; "
            f"native={native_sequences} queue={remote_queue_sequences}"
        )
    if not set(native_sequences).intersection(remote_prep_sequences):
        raise VerifyFailure(
            f"{direction.name}: remote prep did not include local sequence; "
            f"native={native_sequences} prep={remote_prep_sequences}"
        )
    if require_remote_release and not expected_sequences.issubset(
        set(remote_release_sequences)
    ):
        raise VerifyFailure(
            f"{direction.name}: remote release did not include local sequence; "
            f"native={native_sequences} release={remote_release_sequences}"
        )
    if timeout_count:
        raise VerifyFailure(f"{direction.name}: remote cast timed out count={timeout_count}")
    if len(native_sequences) != 1:
        raise VerifyFailure(
            f"{direction.name}: one local input produced {len(native_sequences)} cast sequences; "
            f"sequences={native_sequences} phase_counts={phase_counts}"
        )
    return {
        "phase_counts": phase_counts,
        "native_hook_count": native_hook_count,
        "native_sequences": native_sequences,
        "remote_queue_sequences": remote_queue_sequences,
        "remote_prep_sequences": remote_prep_sequences,
        "remote_settle_sequences": remote_settle_sequences,
        "remote_release_sequences": remote_release_sequences,
        "local_targetless_sequences": local_targetless_sequences,
        "remote_targetless_queue_sequences": remote_targetless_queue_sequences,
        "timeout_count": timeout_count,
    }


def parse_remote_projectile_spawn_sequences(
    log_text: str,
    source_id: int,
    expected_type: int,
) -> list[int]:
    sequences: list[int] = []
    marker = f"[bots] cast complete ("
    expected_type_text = f"0x{expected_type:X}"
    for line in log_text.splitlines():
        if (
            marker not in line
            or f"bot_id={source_id}" not in line
            or "remote_input_controlled=1" not in line
        ):
            continue
        match = re.search(r"remote_cast_sequence=(\d+)", line)
        if not match:
            continue
        no_handle_projectile_observed = (
            "remote_projectile_observed=1" in line
            and f"remote_projectile_expected_type={expected_type_text}" in line
        )
        live_handle_projectile_observed = f"obj_type={expected_type_text}" in line
        if no_handle_projectile_observed or live_handle_projectile_observed:
            sequences.append(int(match.group(1)))
    return sequences


def wait_for_remote_projectile_spawn_sequences(
    direction: Direction,
    receiver_offset: int,
    expected_sequences: list[int],
    expected_type: int,
    timeout: float,
) -> list[int]:
    expected = set(expected_sequences)
    deadline = time.monotonic() + timeout
    observed: list[int] = []
    while time.monotonic() < deadline:
        receiver_log = log_after(direction.receiver_log, receiver_offset)
        observed = parse_remote_projectile_spawn_sequences(
            receiver_log,
            direction.source_id,
            expected_type,
        )
        if expected.issubset(set(observed)):
            return observed
        if count_lines(receiver_log, "remote_input_timeout"):
            break
        time.sleep(0.05)
    return observed


def verify_projectile_cast(direction: Direction, spec: ElementSpec) -> dict[str, object]:
    assert spec.projectile_type is not None
    record_telemetry(
        "cast.projectile.before",
        element=spec.element,
        presentation=spec.presentation,
        direction=direction.name,
        projectile_type=f"0x{spec.projectile_type:X}",
    )
    input_attempts: list[dict[str, object]] = []
    for input_attempt in range(1, 3):
        pre_clear = clear_local_cast_state(direction)
        source_offset = len(read_log(direction.source_log))
        receiver_offset = len(read_log(direction.receiver_log))
        before = sample_projectiles(direction.receiver_pipe, duration=0.2)
        queue_result = queue_deterministic_primary(direction, spec.frames)
        sample_telemetry_window(
            "cast.projectile.after_input",
            duration=0.6,
            interval=0.2,
            element=spec.element,
            direction=direction.name,
            input_attempt=input_attempt,
        )
        observed = sample_projectiles(direction.receiver_pipe, duration=3.0)
        try:
            flow = verify_cast_log_flow(
                direction,
                source_offset,
                receiver_offset,
                require_held=spec.frames > TAP_FRAMES,
            )
        except VerifyFailure as exc:
            input_attempts.append({
                "attempt": input_attempt,
                "queue_result": queue_result,
                "error": str(exc),
            })
            if (
                spec.frames <= TAP_FRAMES
                or "source cast did not reach native hook/phases" not in str(exc)
            ):
                raise
            continue
        input_attempts.append({
            "attempt": input_attempt,
            "queue_result": queue_result,
            "armed": True,
        })
        break
    else:
        raise VerifyFailure(
            f"{direction.name} {spec.presentation}: long primary input did not produce "
            f"the required held phase: attempts={input_attempts}"
        )
    type_key = f"0x{spec.projectile_type:X}"
    runtime_observed_sequences = wait_for_remote_projectile_spawn_sequences(
        direction,
        receiver_offset,
        flow["native_sequences"],
        spec.projectile_type,
        timeout=8.0,
    )
    missing_runtime_projectiles = sorted(
        set(flow["native_sequences"]) - set(runtime_observed_sequences)
    )
    if missing_runtime_projectiles:
        record_telemetry(
            "cast.projectile.failure",
            element=spec.element,
            presentation=spec.presentation,
            direction=direction.name,
            missing_runtime_projectiles=missing_runtime_projectiles,
            runtime_observed_sequences=runtime_observed_sequences,
            flow=flow,
        )
        raise VerifyFailure(
            f"{direction.name} {spec.presentation}: remote runtime did not observe expected "
            f"projectile type {type_key} for sequence(s) {missing_runtime_projectiles}; "
            f"runtime_observed={runtime_observed_sequences} sample_before={before} "
            f"sample_observed={observed} flow={flow}"
        )
    before_addresses = set(before["addresses"][type_key])
    observed_addresses = set(observed["addresses"][type_key])
    before_count = int(before["max_counts"][type_key])
    observed_count = int(observed["max_counts"][type_key])
    record_telemetry(
        "cast.projectile.after",
        element=spec.element,
        presentation=spec.presentation,
        direction=direction.name,
        flow=flow,
        runtime_observed_sequences=runtime_observed_sequences,
    )
    return {
        "pre_clear": pre_clear,
        "queue_result": queue_result,
        "input_attempts": input_attempts,
        "flow": flow,
        "before": before,
        "observed": observed,
        "projectile_type": type_key,
        "runtime_observed_sequences": runtime_observed_sequences,
        "new_addresses": sorted(observed_addresses - before_addresses),
        "sample_observed_projectile": (
            observed_count > before_count or bool(observed_addresses - before_addresses)
        ),
    }


def verify_continuous_cast(direction: Direction, spec: ElementSpec) -> dict[str, object]:
    record_telemetry(
        "cast.continuous.before",
        element=spec.element,
        presentation=spec.presentation,
        direction=direction.name,
    )
    input_attempts: list[dict[str, object]] = []
    for input_attempt in range(1, 3):
        pre_clear = clear_local_cast_state(direction)
        source_offset = len(read_log(direction.source_log))
        receiver_offset = len(read_log(direction.receiver_log))
        queue_result = queue_deterministic_primary(direction, spec.frames)
        active_seen = False
        anim_seen = False
        samples: list[dict[str, str]] = []
        facing_samples: list[dict[str, float | bool]] = []
        matching_facing_samples: list[dict[str, float | bool]] = []
        expected_heading = float(queue_result["expected_heading"])
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            proxy = read_proxy_animation(direction.receiver_pipe, direction.source_id)
            samples.append(proxy)
            proxy_cast_active = proxy.get("cast_active") == "true"
            active_seen = active_seen or proxy_cast_active
            if proxy_cast_active:
                facing = cast_facing_sample(proxy, expected_heading)
                facing_samples.append(facing)
                if bool(facing["matched"]):
                    matching_facing_samples.append(facing)
            try:
                anim_seen = (
                    anim_seen
                    or int(float(proxy.get("anim_drive_state", "0"))) != 0
                    or abs(float(proxy.get("render_advance_phase", "0") or 0.0)) > 0.001
                    or abs(float(proxy.get("render_drive_move_blend", "0") or 0.0)) > 0.001
                    or abs(float(proxy.get("render_drive_overlay_alpha", "0") or 0.0)) > 0.001
                )
            except ValueError:
                pass
            time.sleep(0.05)
        record_telemetry(
            "cast.continuous.after_input",
            element=spec.element,
            presentation=spec.presentation,
            direction=direction.name,
            input_attempt=input_attempt,
            active_seen=active_seen,
            anim_seen=anim_seen,
        )
        try:
            flow = verify_cast_log_flow(
                direction,
                source_offset,
                receiver_offset,
                require_held=True,
                require_remote_release=True,
            )
        except VerifyFailure as exc:
            input_attempts.append({
                "attempt": input_attempt,
                "queue_result": queue_result,
                "error": str(exc),
            })
            if "source cast did not reach native hook/phases" not in str(exc):
                raise
            continue
        input_attempts.append({
            "attempt": input_attempt,
            "queue_result": queue_result,
            "armed": True,
        })
        break
    else:
        raise VerifyFailure(
            f"{direction.name} {spec.presentation}: long primary input did not produce "
            f"the required held phase: attempts={input_attempts}"
        )
    if not active_seen and not anim_seen:
        record_telemetry(
            "cast.continuous.failure",
            element=spec.element,
            presentation=spec.presentation,
            direction=direction.name,
            flow=flow,
            last_proxy=samples[-1] if samples else {},
        )
        raise VerifyFailure(
            f"{direction.name} {spec.presentation}: continuous remote cast never became active; "
            f"last={samples[-1] if samples else {}} flow={flow}"
        )
    if len(matching_facing_samples) < CAST_FACING_MATCH_SAMPLE_COUNT:
        raise VerifyFailure(
            f"{direction.name} {spec.presentation}: remote actor did not face "
            "the owner's live cast direction; "
            f"matches={len(matching_facing_samples)} "
            f"samples={facing_samples[-8:]} flow={flow}"
        )
    receiver_log = log_after(direction.receiver_log, receiver_offset)
    if f"native mana depleted. bot_id={direction.source_id}" in receiver_log:
        raise VerifyFailure(
            f"{direction.name} {spec.presentation}: remote proxy hit native mana depleted stop"
        )
    return {
        "pre_clear": pre_clear,
        "queue_result": queue_result,
        "input_attempts": input_attempts,
        "flow": flow,
        "active_seen": active_seen,
        "anim_seen": anim_seen,
        "cast_facing": {
            "active_samples": len(facing_samples),
            "matching_samples": len(matching_facing_samples),
            "tolerance_degrees": CAST_FACING_TOLERANCE_DEGREES,
            "last_match": matching_facing_samples[-1],
        },
        "last_proxy": samples[-1] if samples else {},
    }


def verify_low_mana_remote_cast(direction: Direction, spec: ElementSpec) -> dict[str, object]:
    record_telemetry("cast.low_mana.before", direction=direction.name)
    mana_write = set_player_mana(direction.source_pipe, 0.0, 100.0)
    pre_clear = clear_local_cast_state(direction)
    source_offset = len(read_log(direction.source_log))
    receiver_offset = len(read_log(direction.receiver_log))
    queue_result = queue_deterministic_primary(direction, spec.frames)
    time.sleep(0.6)
    remote_mid = query_remote_participant(direction.receiver_pipe, direction.source_id)
    record_telemetry("cast.low_mana.mid", direction=direction.name, remote_mid=remote_mid)
    flow = verify_cast_log_flow(
        direction,
        source_offset,
        receiver_offset,
        require_held=spec.frames > TAP_FRAMES,
    )
    receiver_log = log_after(direction.receiver_log, receiver_offset)
    try:
        hp = float(remote_mid.get("hp", "nan"))
        anim_drive = int(float(remote_mid.get("anim_drive_state", "0")))
    except ValueError as exc:
        raise VerifyFailure(f"{direction.name}: invalid low-mana remote sample {remote_mid}") from exc
    if not math.isfinite(hp) or hp <= 0.0:
        raise VerifyFailure(f"{direction.name}: low-mana remote proxy looked dead: {remote_mid}")
    if anim_drive == 1:
        raise VerifyFailure(f"{direction.name}: low-mana remote proxy entered corpse drive state: {remote_mid}")
    if f"native mana depleted. bot_id={direction.source_id}" in receiver_log:
        record_telemetry("cast.low_mana.failure", direction=direction.name, remote_mid=remote_mid)
        raise VerifyFailure(f"{direction.name}: low-mana remote proxy triggered native mana depleted stop")
    record_telemetry("cast.low_mana.after", direction=direction.name, flow=flow)
    return {
        "pre_clear": pre_clear,
        "mana_write": mana_write,
        "queue_result": queue_result,
        "remote_mid": remote_mid,
        "flow": flow,
        "frames": spec.frames,
    }


def verify_element(spec: ElementSpec) -> dict[str, object]:
    record_telemetry("element.start", element=spec.element, preset=spec.preset)
    result: dict[str, object] = {
        "element": spec.element,
        "presentation": spec.presentation,
        "mode": spec.mode,
        "preset": spec.preset,
    }
    result["setup"] = launch_element_pair(spec)
    pids = result["setup"]["pids"]
    directions = [
        Direction("host_to_client", HOST_ID, HOST_NAME, HOST_PIPE, HOST_LOG, pids["host"], CLIENT_PIPE, CLIENT_LOG),
        Direction("client_to_host", CLIENT_ID, CLIENT_NAME, CLIENT_PIPE, CLIENT_LOG, pids["client"], HOST_PIPE, HOST_LOG),
    ]
    for direction in directions:
        record_telemetry("direction.start", element=spec.element, direction=direction.name)
        result[f"{direction.name}_vitals"] = sustain_pair_vitals()
        record_telemetry("direction.vitals_sustained", element=spec.element, direction=direction.name)
        if spec.element == "fire":
            result[f"{direction.name}_animation"] = verify_animation_field_replication(direction)
            record_telemetry("direction.animation_verified", element=spec.element, direction=direction.name)
        if spec.mode == "projectile":
            result[f"{direction.name}_cast"] = verify_projectile_cast(direction, spec)
        else:
            result[f"{direction.name}_cast"] = verify_continuous_cast(direction, spec)
        if spec.element == "fire":
            result[f"{direction.name}_low_mana"] = verify_low_mana_remote_cast(direction, spec)
        time.sleep(0.8)
        record_telemetry("direction.done", element=spec.element, direction=direction.name)
    record_telemetry("element.done", element=spec.element)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--elements",
        default=",".join(spec.element for spec in ELEMENTS),
        help="Comma-separated element list to verify. Defaults to the full matrix.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


def selected_elements(raw: str) -> tuple[ElementSpec, ...]:
    names = [name.strip() for name in raw.split(",") if name.strip()]
    if not names:
        raise VerifyFailure("--elements must name at least one element")
    unknown = [name for name in names if name not in ELEMENT_BY_NAME]
    if unknown:
        known = ", ".join(sorted(ELEMENT_BY_NAME))
        raise VerifyFailure(f"unknown element(s) for --elements: {', '.join(unknown)}; expected one of {known}")
    return tuple(ELEMENT_BY_NAME[name] for name in names)


def main() -> int:
    global TELEMETRY
    args = parse_args()
    specs = selected_elements(args.elements)
    TELEMETRY = MultiplayerTelemetryRecorder(TELEMETRY_PATH)
    result: dict[str, object] = {"ok": False, "elements": [], "selected_elements": [spec.element for spec in specs]}
    record_telemetry(
        "harness.start",
        telemetry_path=str(TELEMETRY_PATH),
        selected_elements=[spec.element for spec in specs],
    )
    try:
        for spec in specs:
            try:
                result["elements"].append(verify_element(spec))
            finally:
                record_telemetry("element.cleanup", element=spec.element)
                stop_games()
        result["ok"] = True
        result["telemetry_path"] = str(TELEMETRY_PATH)
        record_telemetry("harness.success")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        result["telemetry_path"] = str(TELEMETRY_PATH)
        record_telemetry("harness.failure", error=str(exc))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
