#!/usr/bin/env python3
"""Record live native animation frames and directional attachment points.

The recorder owns one rendered solo process, settles the structural actor set,
captures contiguous native render frames, and calls the retail cast-glyph
emitter for its heading sweep. Source and binary provenance are always read by
the recorder; there are no command-line provenance overrides.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import extract_bundles  # noqa: E402
import record_enemy_behavior_goldens as enemy_goldens  # noqa: E402
import record_native_sim_goldens as native_goldens  # noqa: E402
from record_enemy_behavior_goldens import (  # noqa: E402
    retire_priming_enemies,
    spawn_enemy,
    start_stock_match,
)
from record_native_sim_goldens import (  # noqa: E402
    CaptureFailure,
    OwnedSoloSession,
    discover_capture_lane,
    local_path_from_windows,
    place_player,
    require,
    source_revision,
)
from verify_player_health_death_sync import set_local_player_vitals  # noqa: E402
import verify_local_multiplayer_sync as local_sync  # noqa: E402


INSTANCE = "anm-g4"
PORTS = (52331, 52332)
PARTICIPANT_ID = "0x2000000000004A41"
MOD_ID = "bot.brain"
RUNTIME_ROOT = ROOT / "runtime" / "animre-live"
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
GAME_BINARY = GAME_DIRECTORY / "SolomonDark.exe"
CLOTHES_BUNDLE = GAME_DIRECTORY / "images" / "Clothes.bundle"
LOADER = ROOT / "bin" / "Release" / "Win32" / "SolomonDarkModLoader.dll"
STAGED_LOADER = ROOT / "dist" / "launcher" / "SolomonDarkModLoader.dll"
DEFAULT_OUTPUT = (
    ROOT / "tests" / "fixtures" / "webgame" / "animation-goldens.json"
)
DEFAULT_RAW_ROOT = Path("/mnt/d/codex-evidence/animre-20260805/live")

FIXED_TICK_MS = 10
FLOAT_EPSILON = 1.0e-4
SCREEN_EPSILON = 0.001
SETTLE_SAMPLE_FLOOR = 40
SETTLE_SECONDS_FLOOR = 2.0

SKELETON_SCENARIOS = (
    {"name": "skeleton", "type_id": 0x3E9, "capture_frames": 160},
    {"name": "skeleton_archer", "type_id": 0x3EA, "capture_frames": 260},
    {"name": "skeleton_mage", "type_id": 0x3EB, "capture_frames": 300},
)

ATTACK_MARKERS = {
    0x0E: {"active": (4.0,), "end": (7.0,)},
    0x0F: {"active": (9.0,), "end": (24.0,)},
    0x10: {"active": (2.0,), "end": (12.0,)},
    0x11: {"active": (13.0,), "end": (16.0,)},
    0x12: {"active": (25.0, 31.0), "end": (41.0, 47.0)},
}


def parse_unique_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        require(key not in values, f"Lua reply repeated key {key!r}")
        values[key] = value
    return values


def windows_sha256(path: Path) -> str:
    command = (
        "(Get-FileHash -Algorithm SHA256 -LiteralPath "
        f"'{local_sync.path_for_powershell(path).replace("'", "''")}').Hash"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30.0,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"Windows Get-FileHash failed for {path}: {completed.stderr.strip()}",
    )
    digest = completed.stdout.strip().lower()
    require(
        len(digest) == 64 and all(character in "0123456789abcdef" for character in digest),
        f"Windows Get-FileHash returned an invalid SHA-256 for {path}",
    )
    return digest


def configure_shared_recorders() -> None:
    native_goldens.RUNTIME_ROOT = RUNTIME_ROOT
    native_goldens.GAME_DIRECTORY = GAME_DIRECTORY
    native_goldens.GAME_BINARY = GAME_BINARY
    enemy_goldens.RUNTIME_ROOT = RUNTIME_ROOT
    enemy_goldens.GAME_DIRECTORY = GAME_DIRECTORY
    enemy_goldens.GAME_BINARY = GAME_BINARY


def wait_until(
    session: OwnedSoloSession,
    description: str,
    query: Callable[[], dict[str, str]],
    predicate: Callable[[dict[str, str]], bool],
    *,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = query()
            if predicate(last):
                return last
        except (subprocess.TimeoutExpired, local_sync.VerifyFailure) as error:
            session.assert_wait_target_runnable(description)
            last_error = str(error)
        time.sleep(0.05)
    detail = f" last_error={last_error}" if last_error else ""
    raise CaptureFailure(f"{description} did not become ready: {last}{detail}")


def structural_actor_signature(session: OwnedSoloSession) -> str:
    text = session.lua(
        """
local rows = {}
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if actor.tracked_enemy == true then
    rows[#rows + 1] = table.concat({
    tostring(actor.actor_address or 0),
    tostring(actor.object_type_id or 0),
      tostring(actor.vtable_address or 0),
      tostring(actor.owner_address or 0),
      tostring(actor.actor_slot or -1),
      tostring(actor.world_slot or -1),
      tostring(actor.dead == true)
    }, ':')
  end
end
table.sort(rows)
local player = sd.player.get_state()
local scene = sd.world.get_scene() or {}
print('signature=' .. table.concat({
  tostring(scene.kind or scene.name or ''),
  tostring(player and player.actor_address or 0),
  table.concat(rows, ',')
}, '|'))
"""
    )
    values = parse_unique_values(text)
    signature = values.get("signature", "")
    require(signature != "", "structural settle probe returned no actor signature")
    return signature


def tracked_enemy_present(session: OwnedSoloSession, actor_address: int) -> bool:
    values = parse_unique_values(
        session.lua(
            f"""
local found = 0
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  if actor.tracked_enemy and tonumber(actor.actor_address) == {actor_address} then
    found = found + 1
  end
end
print('found=' .. tostring(found))
"""
        )
    )
    require(
        values.get("found") in {"0", "1"},
        f"enemy-presence probe found an ambiguous actor-address match: {values}",
    )
    return values["found"] == "1"


def retire_enemy_if_present(
    session: OwnedSoloSession,
    actor_address: int,
) -> dict[str, Any]:
    if not tracked_enemy_present(session, actor_address):
        return {"requested": False, "already_absent": True}
    values = parse_unique_values(
        session.lua(
            f"""
local ok, exception = sd.world.trigger_enemy_death({actor_address})
print('ok=' .. tostring(ok))
print('exception=' .. tostring(exception or 0))
"""
        )
    )
    require(
        values.get("ok") == "true",
        f"combat-witness retirement failed for actor {actor_address}: {values}",
    )
    wait_until(
        session,
        f"combat-witness actor {actor_address} retirement",
        lambda: {"present": str(tracked_enemy_present(session, actor_address)).lower()},
        lambda current: current.get("present") == "false",
        timeout=15.0,
    )
    return {"requested": True, "already_absent": False}


def settle_actor_surface(session: OwnedSoloSession, label: str) -> dict[str, Any]:
    captures: list[dict[str, Any]] = []
    prior_signature = ""
    for independent_capture in range(2):
        started = time.monotonic()
        stable_started = started
        stable_samples = 0
        signature = ""
        signature_changes: list[str] = []
        while time.monotonic() - started < 20.0:
            session.assert_wait_target_runnable(f"{label} structural settle")
            current = structural_actor_signature(session)
            now = time.monotonic()
            if current != signature:
                signature = current
                stable_samples = 1
                stable_started = now
                signature_changes.append(current)
                signature_changes = signature_changes[-8:]
            else:
                stable_samples += 1
            stable_seconds = now - stable_started
            if (
                stable_samples >= SETTLE_SAMPLE_FLOOR
                and stable_seconds >= SETTLE_SECONDS_FLOOR
            ):
                captures.append(
                    {
                        "capture": independent_capture + 1,
                        "stable_samples": stable_samples,
                        "stable_seconds": round(stable_seconds, 6),
                        "settle_latency_seconds": round(now - started, 6),
                        "structural_signature_sha256": hashlib.sha256(
                            signature.encode("utf-8")
                        ).hexdigest(),
                        "animated_element_set": [],
                        "animated_element_reason": (
                            "the actor structural payload covers address, type, vtable, owner, "
                            "actor/world slots, and terminal membership; target sprite/action "
                            "motion is intentionally captured only after this gate"
                        ),
                    }
                )
                break
            time.sleep(0.055)
        else:
            raise CaptureFailure(
                f"{label} actor surface never settled for 40 samples spanning 2 seconds; "
                f"recent signatures={signature_changes}"
            )
        if independent_capture == 0:
            prior_signature = signature
        else:
            require(
                signature == prior_signature,
                f"{label} structural payload did not reproduce across independent settles",
            )
    return {
        "rule": "40 consecutive byte-identical structural samples spanning at least 2 seconds",
        "captures": captures,
    }


def quiet_initial_arena(session: OwnedSoloSession) -> dict[str, Any]:
    mode = parse_unique_values(
        session.lua(
            """
local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(true)
print('ok=' .. tostring(ok))
print('active=' .. tostring(active))
"""
        )
    )
    require(
        mode == {"ok": "true", "active": "true"},
        f"initial arena manual-spawner isolation failed: {mode}",
    )
    retirement = parse_unique_values(
        session.lua(
            """
local requested = 0
local failed = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if actor.tracked_enemy and not actor.dead then
    local ok = sd.world.trigger_enemy_death(actor.actor_address)
    if ok then requested = requested + 1 else failed = failed + 1 end
  end
end
print('requested=' .. tostring(requested))
print('failed=' .. tostring(failed))
"""
        )
    )
    require(
        retirement.get("failed") == "0",
        f"initial arena enemy retirement failed: {retirement}",
    )
    settled = wait_until(
        session,
        "initial arena enemy retirement",
        lambda: parse_unique_values(
            session.lua(
                """
local tracked = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if actor.tracked_enemy then tracked = tracked + 1 end
end
print('tracked=' .. tostring(tracked))
"""
            )
        ),
        lambda current: current.get("tracked") == "0",
        timeout=20.0,
    )
    return {"manual_mode": mode, "retirement": retirement, "settled": settled}


def scene_status(session: OwnedSoloSession) -> dict[str, str]:
    return parse_unique_values(
        session.lua(
            """
local s = sd.debug.get_native_scene_capture_status() or {}
print('state=' .. tostring(s.state or 'missing'))
print('error=' .. tostring(s.error_message or ''))
print('requested=' .. tostring(s.requested_frame_count or 0))
print('captured=' .. tostring(s.captured_frame_count or 0))
print('label=' .. tostring(s.label or ''))
"""
        )
    )


def capture_sequence(
    session: OwnedSoloSession,
    raw_directory: Path,
    label: str,
    frame_count: int,
    action_lua: str = "",
    *,
    action_after_captured_frames: int = 0,
    arm_action_lua: str = "",
) -> list[dict[str, Any]]:
    require(
        0 <= action_after_captured_frames < frame_count,
        f"native frame sequence {label} has an invalid delayed-action frame",
    )
    arm_text = session.lua(
        f"""
local queued, err = sd.debug.queue_native_scene_capture_sequence('{label}', {frame_count})
print('queued=' .. tostring(queued))
print('error=' .. tostring(err or ''))
if queued and {str(bool(arm_action_lua)).lower()} then
  local arm_ok, arm_result = pcall(function()
{arm_action_lua}
    return true
  end)
  print('arm_action_ok=' .. tostring(arm_ok and arm_result == true))
  print('arm_action_error=' .. tostring(arm_ok and '' or arm_result))
end
if queued and {str(action_after_captured_frames == 0).lower()} then
  local action_ok, action_result = pcall(function()
{action_lua}
    return true
  end)
  print('action_ok=' .. tostring(action_ok and action_result == true))
  print('action_error=' .. tostring(action_ok and '' or action_result))
end
"""
    )
    armed = parse_unique_values(arm_text)
    require(
        armed.get("queued") == "true",
        f"native frame sequence {label} was rejected: {armed}",
    )
    if arm_action_lua:
        require(
            armed.get("arm_action_ok") == "true",
            f"native frame sequence {label} arm action failed: {armed}",
        )
    if action_after_captured_frames == 0:
        require(
            armed.get("action_ok") == "true",
            f"native frame sequence {label} action failed: {armed}",
        )
    else:
        delayed_status = wait_until(
            session,
            f"native frame sequence {label} delayed action",
            lambda: scene_status(session),
            lambda current: current.get("state") == "failed"
            or int(current.get("captured", "0")) >= action_after_captured_frames,
            timeout=10.0,
        )
        require(
            delayed_status.get("state") != "failed",
            f"native frame sequence {label} broke before its delayed action: {delayed_status.get('error', '')}",
        )
        action_text = session.lua(
            f"""
local action_ok, action_result = pcall(function()
{action_lua}
  return true
end)
print('action_ok=' .. tostring(action_ok and action_result == true))
print('action_error=' .. tostring(action_ok and '' or action_result))
"""
        )
        action = parse_unique_values(action_text)
        require(
            action.get("action_ok") == "true",
            f"native frame sequence {label} delayed action failed: {action}",
        )
    status = wait_until(
        session,
        f"native frame sequence {label}",
        lambda: scene_status(session),
        lambda current: current.get("state") in {"complete", "failed"},
        timeout=max(30.0, frame_count / 30.0 + 20.0),
    )
    require(
        status.get("state") != "failed",
        f"native frame sequence {label} is broken, not busy: {status.get('error', '')}",
    )
    require(
        int(status.get("requested", "0")) == frame_count
        and int(status.get("captured", "0")) == frame_count,
        f"native frame sequence {label} completed without every requested frame",
    )

    expected = [
        raw_directory / f"{label}-frame-{index:04d}.json"
        for index in range(frame_count)
    ]
    if frame_count == 1:
        expected = [raw_directory / f"{label}.json"]
    missing = [path.name for path in expected if not path.is_file()]
    require(not missing, f"native frame sequence {label} omitted exact outputs: {missing}")
    frames = [json.loads(path.read_text(encoding="utf-8")) for path in expected]
    require(
        len(frames) == frame_count and frames[0].get("render_sequence_index") == 0,
        f"native frame sequence {label} produced no first render-frame witness",
    )
    require(
        frames[-1].get("render_sequence_index") == frame_count - 1,
        f"native frame sequence {label} did not reach its requested last frame",
    )
    return frames


def parse_bundle_points() -> tuple[list[extract_bundles.SpriteRecord], bytes]:
    require(CLOTHES_BUNDLE.is_file(), f"missing Clothes.bundle: {CLOTHES_BUNDLE}")
    records, groups = extract_bundles.parse_bundle(CLOTHES_BUNDLE)
    require(not groups, "Clothes.bundle unexpectedly parsed as an auxiliary glyph bundle")
    require(len(records) == 3724, "Clothes.bundle no longer has the observed 3724 records")
    return records, CLOTHES_BUNDLE.read_bytes()


def sprite_point(
    records: list[extract_bundles.SpriteRecord],
    bundle: bytes,
    record_index: int,
    point_index: int,
) -> tuple[float, float]:
    require(0 <= record_index < len(records), f"sprite record {record_index} is unavailable")
    record = records[record_index]
    require(
        point_index < record.point_count,
        f"sprite record {record_index} has no point {point_index}",
    )
    return struct.unpack_from(
        "<2f",
        bundle,
        record.offset + extract_bundles.COMMON_HEADER_SIZE
        + point_index * extract_bundles.POINT_SIZE,
    )


def capture_emitter_sweep(
    session: OwnedSoloSession,
    records: list[extract_bundles.SpriteRecord],
    bundle: bytes,
) -> dict[str, Any]:
    text = session.lua(
        """
local player = assert(sd.player.get_state())
local actor = assert(tonumber(player.actor_address))
local heading_offset = assert(sd.debug.layout_offset('actor_heading'))
local phase_offset = assert(sd.debug.layout_offset('actor_render_advance_phase'))
local original_heading = assert(sd.debug.read_float(actor + heading_offset))
local original_phase = assert(sd.debug.read_float(actor + phase_offset))
assert(sd.debug.write_float(actor + phase_offset, 7.0))
for facing=0,23 do
  local heading = facing * 15.0
  assert(sd.debug.write_float(actor + heading_offset, heading))
  local sample = assert(sd.debug.observe_native_cast_glyph_emitter())
  print(table.concat({
    'E', facing, string.format('%.9f', heading),
    tostring(sample.status or ''), tostring(sample.error or ''),
    tostring(sample.tick or 0), string.format('%.9f', sample.heading or -999),
    string.format('%.9f', sample.render_phase or -999),
    string.format('%.9f', sample.actor_x or 0),
    string.format('%.9f', sample.actor_y or 0),
    string.format('%.9f', sample.emitter_x or 0),
    string.format('%.9f', sample.emitter_y or 0),
    tostring(sample.weapon_type or -1),
    tostring(sample.attachment_address or 0),
    tostring(sample.attachment_type or 0),
    tostring(sample.resolver_preferred_address or 0)
  }, '|'))
end
assert(sd.debug.write_float(actor + heading_offset, 359.0))
local wrap = assert(sd.debug.observe_native_cast_glyph_emitter())
print(table.concat({
  'W', string.format('%.9f', wrap.heading or -999),
  string.format('%.9f', wrap.actor_x or 0),
  string.format('%.9f', wrap.actor_y or 0),
  string.format('%.9f', wrap.emitter_x or 0),
  string.format('%.9f', wrap.emitter_y or 0)
}, '|'))
assert(sd.debug.write_float(actor + phase_offset, 0.0))
assert(sd.debug.write_float(actor + heading_offset, 285.0))
local first = assert(sd.debug.observe_native_cast_glyph_emitter())
print(table.concat({
  'K0', string.format('%.9f', first.actor_x or 0),
  string.format('%.9f', first.actor_y or 0),
  string.format('%.9f', first.emitter_x or 0),
  string.format('%.9f', first.emitter_y or 0)
}, '|'))
assert(sd.debug.write_float(actor + heading_offset, original_heading))
assert(sd.debug.write_float(actor + phase_offset, original_phase))
"""
    )
    observed: list[dict[str, Any]] = []
    wrap: dict[str, Any] | None = None
    bank_zero: dict[str, Any] | None = None
    for line in text.splitlines():
        fields = line.split("|")
        if fields[0] == "E":
            require(len(fields) == 16, f"malformed emitter observation: {line}")
            facing = int(fields[1])
            actor = (float(fields[8]), float(fields[9]))
            emitter = (float(fields[10]), float(fields[11]))
            point = sprite_point(records, bundle, 3244 + 24 * 7 + facing, 1)
            residual = (
                emitter[0] - actor[0] - point[0],
                emitter[1] - actor[1] - point[1],
            )
            require(fields[3] == "complete", f"native emitter facing {facing} failed: {fields[4]}")
            require(abs(float(fields[6]) - float(fields[2])) <= FLOAT_EPSILON, f"native emitter did not observe forced heading for facing {facing}")
            require(abs(float(fields[7]) - 7.0) <= FLOAT_EPSILON, f"native emitter did not observe bank phase 7 for facing {facing}")
            require(max(abs(residual[0]), abs(residual[1])) <= FLOAT_EPSILON, f"native emitter facing {facing} disagrees with Clothes point {3244 + 24 * 7 + facing}")
            observed.append(
                {
                    "facing": facing,
                    "status": "observed",
                    "derived_only": False,
                    "forced_heading_degrees": float(fields[2]),
                    "observed_heading_degrees": float(fields[6]),
                    "tick": int(fields[5]),
                    "pose_bank": 7,
                    "sprite_record": 3244 + 24 * 7 + facing,
                    "point_index": 1,
                    "asset_point": [point[0], point[1]],
                    "actor_position": [actor[0], actor[1]],
                    "native_emitter_position": [emitter[0], emitter[1]],
                    "asset_match_residual": [residual[0], residual[1]],
                    "weapon_type": int(fields[12]),
                    "attachment_address": int(fields[13]),
                    "attachment_object_type": int(fields[14]),
                    "retail_resolver_preferred_address": f"0x{int(fields[15]):08X}",
                }
            )
        elif fields[0] == "W":
            require(len(fields) == 6, f"malformed emitter wrap observation: {line}")
            wrap = {
                "heading_degrees": float(fields[1]),
                "actor_position": [float(fields[2]), float(fields[3])],
                "native_emitter_position": [float(fields[4]), float(fields[5])],
            }
        elif fields[0] == "K0":
            require(len(fields) == 5, f"malformed emitter bank-zero observation: {line}")
            point = sprite_point(records, bundle, 3244 + 19, 1)
            actor = (float(fields[1]), float(fields[2]))
            emitter = (float(fields[3]), float(fields[4]))
            residual = (
                emitter[0] - actor[0] - point[0],
                emitter[1] - actor[1] - point[1],
            )
            require(max(abs(residual[0]), abs(residual[1])) <= FLOAT_EPSILON, "native emitter phase zero did not select staff bank zero facing 19")
            bank_zero = {
                "facing": 19,
                "pose_bank": 0,
                "sprite_record": 3263,
                "point_index": 1,
                "asset_point": [point[0], point[1]],
                "actor_position": [actor[0], actor[1]],
                "native_emitter_position": [emitter[0], emitter[1]],
                "asset_match_residual": [residual[0], residual[1]],
            }
    require(
        [row["facing"] for row in observed] == list(range(24)),
        "emitter sweep did not independently observe every facing 0 through 23",
    )
    require(wrap is not None, "emitter sweep omitted the heading-359 wrap witness")
    require(bank_zero is not None, "emitter sweep omitted the phase-zero bank witness")
    wrap_point = sprite_point(records, bundle, 3244 + 24 * 7, 1)
    wrap_residual = (
        wrap["native_emitter_position"][0] - wrap["actor_position"][0] - wrap_point[0],
        wrap["native_emitter_position"][1] - wrap["actor_position"][1] - wrap_point[1],
    )
    require(max(abs(wrap_residual[0]), abs(wrap_residual[1])) <= FLOAT_EPSILON, "native emitter heading 359 did not wrap to observed facing zero")
    wrap["observed_facing"] = 0
    wrap["asset_match_residual"] = [wrap_residual[0], wrap_residual[1]]
    return {
        "formula_under_test": "facing = ((int)heading + 7) / 15; if facing >= 24 then facing -= 24",
        "observation_method": "forced actor heading followed by a synchronous call through retail 0x0053B830; output then matched to Clothes.bundle point 1",
        "facings": observed,
        "wrap_observation": wrap,
        "bank_zero_reference": bank_zero,
    }


def relevant_draws(frame: dict[str, Any], actor_address: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for draw in frame.get("draws", []):
        transform = draw.get("world_transform") or {}
        owner = transform.get("object") or {}
        if int(owner.get("address", 0)) != actor_address:
            continue
        sprite = draw.get("sprite") or {}
        if sprite.get("index") is None:
            continue
        sprite_index = int(sprite["index"])
        atlas = str(sprite.get("atlas") or "")
        attachment_transform = (
            atlas == "Clothes"
            and (
                460 <= sprite_index <= 867
                or 3244 <= sprite_index <= 3723
            )
        )
        rows.append(
            {
                "draw_order": draw.get("draw_order"),
                "atlas": atlas,
                "sprite_index": sprite_index,
                "caller": draw.get("caller"),
                "transform_kind": transform.get("kind"),
                "submitted_position": transform.get("submitted_position"),
                "attachment_matrix": (
                    transform.get("matrix") if attachment_transform else None
                ),
                "tint": draw.get("tint"),
                "lighting_scalar": draw.get("lighting_scalar"),
                "visible": draw.get("visible"),
            }
        )
    return rows


def arm_magic_shield_hit_witness(session: OwnedSoloSession) -> dict[str, Any]:
    values = parse_unique_values(
        session.lua(
            """
local player = assert(sd.player.get_state())
local actor = assert(tonumber(player.actor_address))
local remaining = assert(sd.debug.layout_offset('actor_magic_shield_absorb_remaining'))
local capacity = assert(sd.debug.layout_offset('actor_magic_shield_absorb_capacity'))
local explosion = assert(sd.debug.layout_offset('actor_magic_shield_explosion_fraction'))
local flash = assert(sd.debug.layout_offset('actor_magic_shield_hit_flash'))
assert(sd.debug.write_float(actor + remaining, 1000000.0))
assert(sd.debug.write_float(actor + capacity, 1000000.0))
assert(sd.debug.write_float(actor + explosion, 0.0))
assert(sd.debug.write_float(actor + flash, 0.0))
local observed = assert(sd.player.get_state())
print('remaining=' .. tostring(observed.magic_shield_absorb_remaining or 0))
print('capacity=' .. tostring(observed.magic_shield_absorb_capacity or 0))
print('explosion=' .. tostring(observed.magic_shield_explosion_fraction or 0))
print('flash=' .. tostring(observed.magic_shield_hit_flash or 0))
"""
        )
    )
    require(
        set(values) == {"remaining", "capacity", "explosion", "flash"},
        f"Magic Shield hit witness precondition returned an incomplete or extra field set: {values}",
    )
    observed = {key: float(value) for key, value in values.items()}
    require(
        observed
        == {
            "remaining": 1000000.0,
            "capacity": 1000000.0,
            "explosion": 0.0,
            "flash": 0.0,
        },
        f"Magic Shield hit witness precondition did not read back exactly: {observed}",
    )
    return {
        "method": (
            "existing typed-write probe seeds only shield capacity; a stock "
            "Skeleton hit drives the retail +0x1D0 pulse"
        ),
        "readback": observed,
    }


def raw_field(actor: dict[str, Any], offset: int, kind: str) -> int | float:
    base = int(actor["presentation_window_offset"])
    data = bytes.fromhex(actor["presentation_bytes"])
    relative = offset - base
    formats = {"u8": "<B", "i32": "<i", "u32": "<I", "f32": "<f"}
    size = struct.calcsize(formats[kind])
    require(0 <= relative <= len(data) - size, f"presentation field 0x{offset:X} fell outside the captured actor window")
    return struct.unpack_from(formats[kind], data, relative)[0]


def distill_player_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    first_tick: int | None = None
    for frame in frames:
        player = frame.get("player_animation")
        if player is None:
            rows.append(
                {
                    "render_frame": frame["render_sequence_index"],
                    "tick": None,
                    "actor_present": False,
                    "sprites": [],
                }
            )
            continue
        tick = int(player["tick"])
        if first_tick is None:
            first_tick = tick
        actor_address = int(player["actor_address"])
        sprites = relevant_draws(frame, actor_address)
        rows.append(
            {
                "render_frame": frame["render_sequence_index"],
                "tick": tick,
                "tick_from_capture_start": tick - first_tick,
                "render_observed_ms": frame["render_observed_ms"],
                "actor_present": True,
                "position": player["position"],
                "heading": player["heading"],
                "hp": player["hp"],
                "movement_intent": player["movement_intent"],
                "anim_drive_state": player["anim_drive_state"],
                "animation_duration_ticks": player["animation_duration_ticks"],
                "render_frame_state": player["render_frame_state"],
                "selection_state_id": player["resolved_animation_state_id"],
                "walk_cycle": [
                    player["walk_cycle_primary"],
                    player["walk_cycle_secondary"],
                ],
                "stride": player["render_drive_stride"],
                "pose_rate": player["render_advance_rate"],
                "pose_phase": player["render_advance_phase"],
                "pose_bank": math.trunc(float(player["render_advance_phase"])),
                "weapon_type": player["render_weapon_type"],
                "magic_shield_absorb_remaining": player[
                    "magic_shield_absorb_remaining"
                ],
                "magic_shield_absorb_capacity": player[
                    "magic_shield_absorb_capacity"
                ],
                "magic_shield_hit_flash": player[
                    "magic_shield_hit_flash"
                ],
                "sprites": sprites,
            }
        )
    require(rows and any(row["actor_present"] for row in rows), "player frame distillation reached no live player witness")
    return rows


def distill_player_fixed_ticks(
    frames: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    first_tick: int | None = None
    for frame in frames:
        samples = frame.get("player_fixed_tick_animation")
        require(
            isinstance(samples, list),
            "native scene frame omitted its fixed-tick player animation lane",
        )
        for player in samples:
            tick = int(player["tick"])
            if first_tick is None:
                first_tick = tick
            rows.append(
                {
                    "sample_kind": "native_player_fixed_tick",
                    "fixed_tick_frame": len(rows),
                    "render_frame": frame["render_sequence_index"],
                    "render_frame_after_tick": frame["render_sequence_index"],
                    "tick": tick,
                    "tick_from_capture_start": tick - first_tick,
                    "tick_observed_ms": player["tick_observed_ms"],
                    "actor_present": True,
                    "position": player["position"],
                    "heading": player["heading"],
                    "hp": player["hp"],
                    "movement_intent": player["movement_intent"],
                    "anim_drive_state": player["anim_drive_state"],
                    "animation_duration_ticks": player[
                        "animation_duration_ticks"
                    ],
                    "render_frame_state": player["render_frame_state"],
                    "selection_state_id": player[
                        "resolved_animation_state_id"
                    ],
                    "walk_cycle": [
                        player["walk_cycle_primary"],
                        player["walk_cycle_secondary"],
                    ],
                    "stride": player["render_drive_stride"],
                    "pose_rate": player["render_advance_rate"],
                    "pose_phase": player["render_advance_phase"],
                    "pose_bank": math.trunc(
                        float(player["render_advance_phase"])
                    ),
                    "weapon_type": player["render_weapon_type"],
                    "magic_shield_absorb_remaining": player[
                        "magic_shield_absorb_remaining"
                    ],
                    "magic_shield_absorb_capacity": player[
                        "magic_shield_absorb_capacity"
                    ],
                    "magic_shield_hit_flash": player[
                        "magic_shield_hit_flash"
                    ],
                    "action_count": player["action_count"],
                    "action_id": player["action_id"],
                    "action_progress": player["action_progress"],
                    "sprites": [],
                }
            )
    require(rows, "fixed-tick player animation lane reached no live tick witness")
    ticks = [int(row["tick"]) for row in rows]
    require(
        all(right == left + 1 for left, right in zip(ticks, ticks[1:])),
        "fixed-tick player animation lane skipped or duplicated a simulation tick",
    )
    return rows


def distill_enemy_frames(
    frames: list[dict[str, Any]],
    actor_address: int,
    *,
    death_transition: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    first_tick: int | None = None
    prior_position: tuple[float, float] | None = None
    prior_progress = 0.0
    actor_witnessed = False
    for frame in frames:
        player = frame.get("player_animation") or {}
        tick = int(player.get("tick", 0))
        if first_tick is None and tick:
            first_tick = tick
        matches = [
            actor for actor in frame.get("tracked_enemy_animation", [])
            if int(actor.get("actor_address", 0)) == actor_address
        ]
        require(len(matches) <= 1, "native enemy frame contained duplicate actor-address candidates")
        if not matches:
            terminal = death_transition and actor_witnessed
            death_draws: list[dict[str, Any]] = []
            if terminal and prior_position is not None:
                for draw in frame.get("draws", []):
                    sprite = draw.get("sprite") or {}
                    transform = draw.get("world_transform") or {}
                    position = transform.get("submitted_position")
                    if (
                        sprite.get("atlas") not in {"BadGuys", "DeadHawg"}
                        or not isinstance(position, list)
                        or len(position) != 2
                        or math.dist(
                            (float(position[0]), float(position[1])), prior_position
                        ) > 96.0
                    ):
                        continue
                    death_draws.append(
                        {
                            "draw_order": draw.get("draw_order"),
                            "atlas": sprite.get("atlas"),
                            "sprite_index": sprite.get("index"),
                            "caller": draw.get("caller"),
                            "submitted_position": position,
                            "tint": draw.get("tint"),
                            "lighting_scalar": draw.get("lighting_scalar"),
                        }
                    )
            rows.append(
                {
                    "render_frame": frame["render_sequence_index"],
                    "tick": tick or None,
                    "actor_present": False,
                    "presentation_state": "death" if terminal else "absent",
                    "terminal_actor_retired": terminal,
                    "sprites": death_draws,
                }
            )
            continue
        actor = matches[0]
        actor_witnessed = True
        position = (float(actor["position"][0]), float(actor["position"][1]))
        displacement = 0.0 if prior_position is None else math.dist(position, prior_position)
        action_id = int(actor["action_id"])
        progress = float(actor["action_progress"])
        state = "walk" if displacement > FLOAT_EPSILON else "idle"
        marker = ATTACK_MARKERS.get(action_id)
        if marker is not None:
            state = "attack_windup"
            if any(prior_progress < threshold <= progress for threshold in marker["active"]):
                state = "attack_active"
            elif progress >= min(marker["active"]):
                state = "attack_recovery"
        if actor.get("dead"):
            state = "death"
        rows.append(
            {
                "render_frame": frame["render_sequence_index"],
                "tick": tick or None,
                "tick_from_capture_start": (tick - first_tick) if tick and first_tick else 0,
                "render_observed_ms": frame["render_observed_ms"],
                "actor_present": True,
                "actor_address": actor_address,
                "type_id": actor["type_id"],
                "position": actor["position"],
                "heading": actor["heading"],
                "hp": actor["hp"],
                "dead": actor["dead"],
                "action_available": actor["action_available"],
                "action_id": action_id,
                "action_progress": progress,
                "presentation_state": state,
                "presentation_fields": {
                    "phase_0x134_u32": raw_field(actor, 0x134, "u32"),
                    "phase_0x140_f32": raw_field(actor, 0x140, "f32"),
                    "gait_phase_0x144_f32": raw_field(actor, 0x144, "f32"),
                    "body_gait_phase_0x148_f32": raw_field(actor, 0x148, "f32"),
                    "body_gait_divisor_0x14c_f32": raw_field(actor, 0x14C, "f32"),
                    "body_selector_0x150_f32": raw_field(actor, 0x150, "f32"),
                    "body_gait_mirror_0x158_f32": raw_field(actor, 0x158, "f32"),
                    "pose_0x210_f32": raw_field(actor, 0x210, "f32"),
                    "pose_0x214_f32": raw_field(actor, 0x214, "f32"),
                    "pose_0x218_f32": raw_field(actor, 0x218, "f32"),
                    "pose_0x220_u32": raw_field(actor, 0x220, "u32"),
                    "head_facing_offset_0x224_i32": raw_field(actor, 0x224, "i32"),
                    # Retained for compatibility with the sealed v1 fixture.
                    "pose_0x224_f32": raw_field(actor, 0x224, "f32"),
                    "pose_0x228_f32": raw_field(actor, 0x228, "f32"),
                    "pose_0x230_u8": raw_field(actor, 0x230, "u8"),
                    "pose_0x231_u8": raw_field(actor, 0x231, "u8"),
                    "pose_0x233_u8": raw_field(actor, 0x233, "u8"),
                    "pose_0x234_f32": raw_field(actor, 0x234, "f32"),
                },
                "sprites": relevant_draws(frame, actor_address),
            }
        )
        prior_position = position
        prior_progress = progress if action_id else 0.0
    require(rows and any(row["actor_present"] for row in rows), "enemy frame distillation reached no tracked actor witness")
    return rows


def transition_edges(rows: list[dict[str, Any]], state_key: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    prior = "absent"
    prior_position: tuple[float, float] | None = None
    for row in rows:
        if not row.get("actor_present"):
            current = str(row.get("presentation_state", "absent"))
        elif state_key in {"wizard", "wizard_hit"}:
            if (
                state_key == "wizard_hit"
                and float(row.get("magic_shield_hit_flash", 0.0)) > 0.0
            ):
                current = "hit_overlay"
            elif int(row.get("anim_drive_state", 0)) != 0:
                duration = int(row.get("animation_duration_ticks", 0))
                current = "death_delay" if duration <= 150 else f"death_frame_{min((duration - 150) // 3, 3)}"
            elif int(row.get("action_count", 0)) > 0 and int(
                row.get("action_id", 0)
            ) == 3:
                current = f"cast_pose_{int(row.get('pose_bank', 0))}"
            elif int(row.get("pose_bank", 0)) != 0:
                current = f"pose_bank_{int(row['pose_bank'])}"
            elif (
                prior_position is not None
                and math.dist(
                    tuple(float(value) for value in row.get("position", [0, 0])),
                    prior_position,
                ) > FLOAT_EPSILON
            ):
                current = "walk"
            else:
                current = "idle"
        else:
            current = str(row.get("presentation_state", "unknown"))
        row["presentation_state"] = current
        if current != prior:
            edges.append(
                {
                    "render_frame": row["render_frame"],
                    "tick": row.get("tick"),
                    "from": prior,
                    "to": current,
                }
            )
            prior = current
        if row.get("actor_present") and "position" in row:
            prior_position = tuple(float(value) for value in row["position"])
    require(edges, f"{state_key} transition extraction reached no state witness")
    return edges


def capture_header(
    source: dict[str, Any],
    launch: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    return {
        "instance": INSTANCE,
        "source_commit_sha": source["commit_sha"],
        "source_tree_sha": source["tree_sha"],
        "worktree_dirty_at_capture_start": source["worktree_dirty"],
        "game_binary_sha256": windows_sha256(GAME_BINARY),
        "loader_sha256": windows_sha256(LOADER),
        "staged_loader_sha256": windows_sha256(STAGED_LOADER),
        "capture_method": method,
        "process_id": int(launch["processId"]),
        "executable_path": launch["executablePath"],
        "fixed_tick_ms": FIXED_TICK_MS,
        "epsilon": {
            "world_units": FLOAT_EPSILON,
            "screen_pixels": SCREEN_EPSILON,
            "justification": (
                "native positions and attachment points are float32/x87 values; 1e-4 "
                "world units exceeds representation noise while staying below observed "
                "motion, and 0.001 screen pixels matches the native scene serializer"
            ),
        },
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    args = parser.parse_args()

    configure_shared_recorders()
    source = source_revision()
    require(GAME_BINARY.is_file(), f"missing game binary: {GAME_BINARY}")
    require(LOADER.is_file(), f"missing Release loader: {LOADER}")
    require(STAGED_LOADER.is_file(), f"missing staged Release loader: {STAGED_LOADER}")
    require(
        windows_sha256(LOADER) == windows_sha256(STAGED_LOADER),
        "staged launcher loader does not match the Release build",
    )
    records, bundle = parse_bundle_points()

    run_stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    raw_directory = args.raw_root / run_stamp
    raw_directory.mkdir(parents=True, exist_ok=False)
    os.environ["SDMOD_NATIVE_SCENE_CAPTURE_DIRECTORY"] = str(raw_directory)
    wsl_env_entries = [
        entry for entry in os.environ.get("WSLENV", "").split(":") if entry
    ]
    capture_env_entry = "SDMOD_NATIVE_SCENE_CAPTURE_DIRECTORY/p"
    if capture_env_entry not in wsl_env_entries:
        wsl_env_entries.append(capture_env_entry)
    os.environ["WSLENV"] = ":".join(wsl_env_entries)

    session = OwnedSoloSession(
        instance=INSTANCE,
        ports=PORTS,
        mod_id=MOD_ID,
        participant_id=PARTICIPANT_ID,
        test_blank_boneyard=False,
        headless=False,
    )
    launch: dict[str, Any] | None = None
    cleanup: list[dict[str, Any]] = []
    document: dict[str, Any] | None = None
    try:
        launch = session.launch()
        session.wait_for_pipe()
        session.wait_for_scene("hub")
        stock_match = start_stock_match(session)
        lane = discover_capture_lane(session)
        quiet_setup = quiet_initial_arena(session)
        settle_initial = settle_actor_surface(session, "initial arena")
        header = capture_header(
            source,
            launch,
            "contiguous native Region render captures with per-frame fixed-tick snapshots",
        )

        emitter = capture_emitter_sweep(session, records, bundle)
        emitter["header"] = capture_header(
            source,
            launch,
            "forced heading plus synchronous call-through to retail cast emitter 0x0053B830",
        )

        set_local_player_vitals(
            session.pipe_name, 5000.0, 5000.0, mp=5000.0, max_mp=5000.0
        )

        idle_raw = capture_sequence(session, raw_directory, "wizard-idle", 30)
        walk_raw = capture_sequence(
            session,
            raw_directory,
            "wizard-walk",
            100,
            """    assert(sd.input.set_native_control_allowance_frames(120))
    assert(sd.input.hold_movement_frames(1.0, 0.0, 12))""",
        )
        place_player(session, lane["free_x"], lane["free_y"])
        cast_target, cast_target_spawner = spawn_enemy(
            session,
            type_id=0x3E9,
            x=lane["free_x"] + 120.0,
            y=lane["free_y"],
        )
        cast_target_address = int(cast_target["actor_address"])
        cast_target_priming_retirement = retire_priming_enemies(
            session, cast_target_address
        )
        cast_target_settle = settle_actor_surface(
            session, "wizard cast target"
        )
        cast_raw: list[dict[str, Any]] | None = None
        cast_attempts: list[dict[str, Any]] = []
        for attempt in range(1, 9):
            candidate = capture_sequence(
                session,
                raw_directory,
                f"wizard-cast-attempt-{attempt}",
                100,
                f"""    if sd.input.clear_mouse_left ~= nil then
      assert(sd.input.clear_mouse_left())
    end
    local player = assert(sd.player.get_state())
    local actor = assert(tonumber(player.actor_address))
    local target = {cast_target_address}
    local target_x = assert(sd.debug.read_float(target + assert(sd.debug.layout_offset('actor_position_x'))))
    local target_y = assert(sd.debug.read_float(target + assert(sd.debug.layout_offset('actor_position_y'))))
    assert(sd.debug.write_float(actor + assert(sd.debug.layout_offset('actor_heading')), 90.0))
    assert(sd.debug.write_float(actor + assert(sd.debug.layout_offset('actor_aim_target_x')), target_x))
    assert(sd.debug.write_float(actor + assert(sd.debug.layout_offset('actor_aim_target_y')), target_y))
    assert(sd.debug.write_u32(actor + assert(sd.debug.layout_offset('actor_aim_target_aux0')), 0))
    assert(sd.debug.write_u32(actor + assert(sd.debug.layout_offset('actor_aim_target_aux1')), 0))
    assert(sd.input.set_native_control_allowance_frames(180))
    assert(sd.input.hold_mouse_left_frames(24))
    assert(sd.input.pin_manual_primary_target(target))""",
            )
            candidate_fixed_ticks = distill_player_fixed_ticks(candidate)
            candidate_banks = [
                int(row["pose_bank"])
                for row in candidate_fixed_ticks
                if int(row["action_count"]) > 0
                and int(row["action_id"]) == 3
            ]
            cast_attempts.append(
                {
                    "attempt": attempt,
                    "action_id": 3,
                    "observed_pose_banks": list(dict.fromkeys(candidate_banks)),
                }
            )
            if {1, 8, 7} <= set(candidate_banks):
                cast_raw = candidate
                break
        require(
            cast_raw is not None,
            f"eight target-pinned stock casts did not expose the complete 1,8,7 pose branch: {cast_attempts}",
        )
        cast_target_retirement = retire_enemy_if_present(
            session, cast_target_address
        )
        wizard_captures = []
        for name, raw in (
            ("idle", idle_raw),
            ("idle_walk_idle", walk_raw),
            ("idle_cast_idle", cast_raw),
        ):
            rows = distill_player_frames(raw)
            fixed_tick_rows = distill_player_fixed_ticks(raw)
            transitions = transition_edges(fixed_tick_rows, "wizard")
            observed_states = [edge["to"] for edge in transitions]
            if name == "idle_walk_idle":
                require(
                    "walk" in observed_states and observed_states[-1] == "idle",
                    "wizard locomotion capture omitted walk or its return to idle",
                )
            if name == "idle_cast_idle":
                action_rows = [
                    row
                    for row in fixed_tick_rows
                    if int(row["action_count"]) > 0
                    and int(row["action_id"]) == 3
                ]
                action_banks = [
                    int(row["pose_bank"])
                    for row in action_rows
                ]
                require(
                    action_banks
                    and {0, 1, 8, 7} <= set(action_banks)
                    and set(action_banks).issubset({0, 1, 7, 8}),
                    f"wizard StaffCast1 action did not observe exactly the retail pose banks 0, 1, 8, and 7: {sorted(set(action_banks))}",
                )
                require(
                    [state for state in observed_states if state.startswith("cast_")]
                    == [
                        "cast_pose_0",
                        "cast_pose_1",
                        "cast_pose_8",
                        "cast_pose_7",
                    ]
                    and observed_states[-1] == "idle",
                    f"wizard StaffCast1 capture omitted its ordered pose transition and return to idle: {observed_states}",
                )
            capture = {
                "name": name,
                "header": header,
                "camera_reference": raw[0]["camera"],
                "frames": rows,
                "fixed_tick_frames": fixed_tick_rows,
                "transitions": transitions,
                "attempts": cast_attempts if name == "idle_cast_idle" else None,
            }
            if name == "idle_cast_idle":
                capture["settle_gate"] = cast_target_settle
                capture["target_receipt"] = {
                    "actor_address": cast_target_address,
                    "type_id": cast_target["type_id"],
                    "request_id": cast_target["request_id"],
                    "stock_spawner_address_observed": cast_target_spawner[
                        "observed_spawner_address"
                    ],
                    "priming_retirement": cast_target_priming_retirement,
                    "capture_retirement": cast_target_retirement,
                }
            wizard_captures.append(capture)

        skeleton_captures: list[dict[str, Any]] = []
        wizard_hit_capture: dict[str, Any] | None = None
        target_id = int(PARTICIPANT_ID, 0)
        for scenario in SKELETON_SCENARIOS:
            place_player(session, lane["free_x"] + 30.0, lane["free_y"])
            set_local_player_vitals(session.pipe_name, 5000.0, 5000.0)
            enemy, spawner = spawn_enemy(
                session,
                type_id=int(scenario["type_id"]),
                x=lane["free_x"] - 80.0,
                y=lane["free_y"],
            )
            retirement = retire_priming_enemies(
                session, int(enemy["actor_address"])
            )
            settle = settle_actor_surface(session, str(scenario["name"]))
            hit_precondition = None
            if scenario["name"] == "skeleton":
                hit_precondition = arm_magic_shield_hit_witness(session)
                hit_precondition["escape_after_render_frames"] = 4
                hit_precondition["escape_position"] = [
                    lane["boundary_start_x"],
                    lane["boundary_start_y"],
                ]
            combat_raw = capture_sequence(
                session,
                raw_directory,
                f"{scenario['name']}-combat",
                int(scenario["capture_frames"]),
                (
                    f"""    local player = assert(sd.player.get_state())
    local actor = assert(tonumber(player.actor_address))
    assert(sd.debug.write_float(
      actor + assert(sd.debug.layout_offset('actor_position_x')),
      {lane["boundary_start_x"]:.9f}))
    assert(sd.debug.write_float(
      actor + assert(sd.debug.layout_offset('actor_position_y')),
      {lane["boundary_start_y"]:.9f}))
    local rebind_ok, rebind_error = sd.world.rebind_actor(actor)
    assert(rebind_ok, 'player rebind failed: ' .. tostring(rebind_error or ''))"""
                    if scenario["name"] == "skeleton"
                    else ""
                ),
                action_after_captured_frames=(
                    4 if scenario["name"] == "skeleton" else 0
                ),
            )
            actor_address = int(enemy["actor_address"])
            combat_rows = distill_enemy_frames(combat_raw, actor_address)
            combat_states = {
                str(row["presentation_state"])
                for row in combat_rows
                if row.get("actor_present")
            }
            require(
                {"attack_windup", "attack_active", "attack_recovery"}
                <= combat_states,
                f"{scenario['name']} combat capture omitted an attack presentation state: {sorted(combat_states)}",
            )
            if scenario["name"] == "skeleton":
                hit_rows = distill_player_frames(combat_raw)
                hit_fixed_ticks = distill_player_fixed_ticks(combat_raw)
                hit_transitions = transition_edges(
                    hit_fixed_ticks, "wizard_hit"
                )
                hit_states = [edge["to"] for edge in hit_transitions]
                require(
                    "hit_overlay" in hit_states
                    and any(
                        edge["from"] == "hit_overlay"
                        and edge["to"] == "idle"
                        for edge in hit_transitions
                    ),
                    f"stock Skeleton damage did not expose the wizard hit-overlay entry and exit: {hit_transitions}",
                )
                positive_flash = [
                    float(row["magic_shield_hit_flash"])
                    for row in hit_fixed_ticks
                    if float(row["magic_shield_hit_flash"]) > 0.0
                ]
                require(
                    positive_flash
                    and max(positive_flash) >= 1.94
                    and min(positive_flash) <= 0.051,
                    "wizard hit-overlay capture did not span the native shield pulse decay",
                )
                wizard_hit_capture = {
                    "name": "idle_hit_overlay_idle",
                    "trigger": hit_precondition,
                    "header": header,
                    "camera_reference": combat_raw[0]["camera"],
                    "frames": hit_rows,
                    "fixed_tick_frames": hit_fixed_ticks,
                    "transitions": hit_transitions,
                }

            combat_retirement = retire_enemy_if_present(session, actor_address)
            death_enemy, death_spawner = spawn_enemy(
                session,
                type_id=int(scenario["type_id"]),
                x=lane["free_x"] - 80.0,
                y=lane["free_y"],
            )
            death_actor_address = int(death_enemy["actor_address"])
            retire_priming_enemies(session, death_actor_address)
            death_settle = settle_actor_surface(
                session, f"{scenario['name']} death witness"
            )
            require(
                tracked_enemy_present(session, death_actor_address),
                f"{scenario['name']} death witness was gone before the sequence could arm",
            )
            death_raw = capture_sequence(
                session,
                raw_directory,
                f"{scenario['name']}-death",
                140,
                f"""    local ok, exception = sd.world.trigger_enemy_death({death_actor_address})
    assert(ok, 'enemy death trigger failed: ' .. tostring(exception or 0))""",
                action_after_captured_frames=8,
            )
            death_rows = distill_enemy_frames(
                death_raw,
                death_actor_address,
                death_transition=True,
            )
            require(
                any(row.get("presentation_state") == "death" for row in death_rows),
                f"{scenario['name']} death capture omitted the live terminal presentation edge",
            )
            combined = combat_rows + [
                {**row, "render_frame": row["render_frame"] + len(combat_rows)}
                for row in death_rows
            ]
            skeleton_captures.append(
                {
                    "name": scenario["name"],
                    "type_id": scenario["type_id"],
                    "target_participant_id": target_id,
                    "header": header,
                    "camera_reference": combat_raw[0]["camera"],
                    "settle_gate": settle,
                    "spawn_receipt": {
                        "type_id": enemy["type_id"],
                        "request_id": enemy["request_id"],
                        "stock_spawner_address_observed": spawner[
                            "observed_spawner_address"
                        ],
                        "priming_retirement": retirement,
                        "combat_witness_retirement": combat_retirement,
                        "death_witness": {
                            "actor_address": death_actor_address,
                            "type_id": death_enemy["type_id"],
                            "request_id": death_enemy["request_id"],
                            "stock_spawner_address_observed": death_spawner[
                                "observed_spawner_address"
                            ],
                            "settle_gate": death_settle,
                        },
                    },
                    "frames": combined,
                    "transitions": transition_edges(combined, "enemy"),
                }
            )

        require(
            wizard_hit_capture is not None,
            "wizard state coverage omitted the live hit-overlay capture",
        )
        wizard_captures.append(wizard_hit_capture)

        death_raw = capture_sequence(
            session,
            raw_directory,
            "wizard-cast-death-interrupt",
            220,
            """    local player = assert(sd.player.get_state())
    local actor = assert(tonumber(player.actor_address))
            local progression = assert(tonumber(player.progression_address))
    assert(sd.debug.write_float(
      progression + assert(sd.debug.layout_offset('progression_hp')), -50.0))
    assert(sd.debug.write_u8(
      actor + assert(sd.debug.layout_offset('actor_animation_drive_state_byte')), 1))
    assert(sd.debug.write_i32(
      actor + assert(sd.debug.layout_offset('actor_animation_move_duration_ticks')), 0))""",
            action_after_captured_frames=6,
            arm_action_lua="""    if sd.input.clear_mouse_left ~= nil then
      assert(sd.input.clear_mouse_left())
    end
    local player = assert(sd.player.get_state())
    local actor = assert(tonumber(player.actor_address))
    local x = assert(sd.debug.read_float(actor + assert(sd.debug.layout_offset('actor_position_x'))))
    local y = assert(sd.debug.read_float(actor + assert(sd.debug.layout_offset('actor_position_y'))))
    assert(sd.debug.write_float(actor + assert(sd.debug.layout_offset('actor_heading')), 90.0))
    assert(sd.debug.write_float(actor + assert(sd.debug.layout_offset('actor_aim_target_x')), x + 320.0))
    assert(sd.debug.write_float(actor + assert(sd.debug.layout_offset('actor_aim_target_y')), y))
    assert(sd.input.set_native_control_allowance_frames(180))
    assert(sd.input.hold_mouse_left_frames(24))""",
        )
        death_rows = distill_player_frames(death_raw)
        death_fixed_tick_rows = distill_player_fixed_ticks(death_raw)
        death_transitions = transition_edges(
            death_fixed_tick_rows, "wizard"
        )
        death_states = [edge["to"] for edge in death_transitions]
        require(
            all(f"death_frame_{index}" in death_states for index in range(4)),
            f"wizard death capture omitted a retail corpse frame: {death_states}",
        )
        require(
            any(
                str(edge["from"]).startswith("cast_pose_")
                and edge["to"] == "death_delay"
                for edge in death_transitions
            ),
            f"wizard death capture did not prove that death interrupts a queued cast: {death_transitions}",
        )
        wizard_captures.append(
            {
                "name": "cast_death_interrupt_frames",
                "trigger": "stock Staff Cast 1 is queued through native input; after six observed render frames the existing typed-write probe makes HP lethal and seeds retail +0x160=1/+0x1BC=0; native fixed ticks interrupt the cast and advance the terminal timeline",
                "header": header,
                "camera_reference": death_raw[0]["camera"],
                "frames": death_rows,
                "fixed_tick_frames": death_fixed_tick_rows,
                "transitions": death_transitions,
            }
        )

        cleanup = session.close()
        document = {
            "schema": "solomon-dark-animation-goldens-v1",
            "header": header,
            "tick_graph": {
                "fixed_tick_ms": FIXED_TICK_MS,
                "render_rule": "one capture per native Region render; render frames sample the latest completed state and may skip fixed-tick poses",
                "fixed_tick_rule": "the additive observation lane records every local Player fixed tick while each render sequence is armed",
            },
            "settle_gate": settle_initial,
            "stock_match": stock_match,
            "quiet_arena_setup": quiet_setup,
            "capture_lane": lane,
            "wizard": wizard_captures,
            "skeleton_family": skeleton_captures,
            "cast_glyph_emitter": emitter,
            "cleanup": cleanup,
        }
    finally:
        if session.process_ids:
            cleanup = session.close()

    require(document is not None, "animation capture produced no golden document")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, indent=2, sort_keys=False) + "\n"
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    raw_fixture = raw_directory / "animation-goldens.json"
    raw_fixture.write_text(encoded, encoding="utf-8", newline="\n")
    print(f"wrote={args.output}")
    print(f"raw_evidence={raw_directory}")
    print(f"frames={sum(len(item['frames']) for item in document['wizard']) + sum(len(item['frames']) for item in document['skeleton_family'])}")
    print(f"sha256={hashlib.sha256(encoded.encode('utf-8')).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
