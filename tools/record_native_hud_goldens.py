#!/usr/bin/env python3
"""Record the retail in-run HUD from its native screen-overlay renderer.

The recorder owns every launched process, derives source and binary provenance
itself, and refuses captures whose native HUD surface reports a terminal
failure. ``--smoke`` records one frame and one backbuffer without publishing a
fixture; the default mode records the complete G9 scenario matrix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import record_enemy_behavior_goldens as enemy_goldens  # noqa: E402
import record_native_sim_goldens as native_goldens  # noqa: E402
from multiplayer_frame_capture import capture_game_backbuffer  # noqa: E402
from record_enemy_behavior_goldens import start_stock_match  # noqa: E402
from record_native_sim_goldens import (  # noqa: E402
    CaptureFailure,
    OwnedSoloSession,
    require,
    source_revision,
)
import verify_local_multiplayer_sync as local_sync  # noqa: E402


INSTANCE = "ui-g9a"
PORTS = (52361, 52362)
PARTICIPANT_ID = "0x2000000000004909"
MOD_ID = "bot.brain"
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
GAME_BINARY = GAME_DIRECTORY / "SolomonDark.exe"
LOADER = ROOT / "bin" / "Release" / "Win32" / "SolomonDarkModLoader.dll"
STAGED_LOADER = ROOT / "dist" / "launcher" / "SolomonDarkModLoader.dll"
EVIDENCE_ROOT = Path("/mnt/d/codex-evidence/uire-20260806")
RUNTIME_ROOT = EVIDENCE_ROOT / "runtime"
DEFAULT_RAW_ROOT = EVIDENCE_ROOT / "live"
DEFAULT_CROP_ROOT = EVIDENCE_ROOT / "hud-crops"
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "webgame" / "hud-goldens.json"
SETTLE_SAMPLE_FLOOR = 40
SETTLE_SECONDS_FLOOR = 2.0
MAXIMUM_ANIMATED_FRACTION = 0.30
SETTLE_CAPTURE_FRAMES = 480
MAXIMUM_BEHAVIOR_TRACE_SAMPLES = 64
NATIVE_RESOLUTION = (1600, 900)
EARTH_BOULDER_TYPE_ID = 0x07D5
EARTH_BOULDER_CHARGE_OFFSET = 0x74


def configure_shared_recorders() -> None:
    native_goldens.RUNTIME_ROOT = RUNTIME_ROOT
    native_goldens.GAME_DIRECTORY = GAME_DIRECTORY
    native_goldens.GAME_BINARY = GAME_BINARY
    enemy_goldens.RUNTIME_ROOT = RUNTIME_ROOT
    enemy_goldens.GAME_DIRECTORY = GAME_DIRECTORY
    enemy_goldens.GAME_BINARY = GAME_BINARY


def windows_sha256(path: Path) -> str:
    command = (
        "(Get-FileHash -Algorithm SHA256 -LiteralPath "
        f"'{local_sync.path_for_powershell(path).replace(chr(39), chr(39) * 2)}').Hash"
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
        len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest),
        f"Windows Get-FileHash returned an invalid SHA-256 for {path}",
    )
    return digest


def configure_capture_environment(raw_directory: Path) -> None:
    os.environ["SDMOD_NATIVE_SCENE_CAPTURE_DIRECTORY"] = str(raw_directory)
    os.environ["SDMOD_NATIVE_SCENE_CAPTURE_SURFACE"] = "hud"
    entries = [entry for entry in os.environ.get("WSLENV", "").split(":") if entry]
    required = (
        "SDMOD_NATIVE_SCENE_CAPTURE_DIRECTORY/p",
        "SDMOD_NATIVE_SCENE_CAPTURE_SURFACE",
    )
    for entry in required:
        if entry not in entries:
            entries.append(entry)
    os.environ["WSLENV"] = ":".join(entries)


def parse_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        require(key not in values, f"Lua reply repeated key {key!r}")
        values[key] = value
    return values


def capture_status(session: OwnedSoloSession) -> dict[str, str]:
    return parse_values(
        session.lua(
            """
local status = assert(sd.debug.get_native_scene_capture_status())
for _, key in ipairs({
  'state', 'surface', 'label', 'output_path', 'error_message',
  'requested_frame_count', 'captured_frame_count', 'draw_count'
}) do
  print(key .. '=' .. tostring(status[key] or ''))
end
"""
        )
    )


def wait_for_run_presentation(
    session: OwnedSoloSession,
    *,
    timeout: float = 45.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    first_ready_at = 0.0
    first_ready_tick = 0
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        try:
            last = parse_values(
                session.lua(
                    """
local runtime = sd.runtime.get_multiplayer_state() or {}
local loading = runtime.loading_screen or {}
local scene = sd.world.get_scene() or {}
local player = sd.player.get_state() or {}
print('scene=' .. tostring(scene.name or scene.kind or ''))
print('loading_active=' .. tostring(loading.active or false))
print('loading_timed_out=' .. tostring(loading.timed_out or false))
print('tick=' .. tostring(player.local_player_tick_count or 0))
"""
                )
            )
        except Exception:
            session.assert_wait_target_runnable("run presentation")
            time.sleep(0.1)
            continue
        if last.get("loading_timed_out") == "true":
            raise CaptureFailure(
                f"run presentation is broken, not busy: loading timed out: {last}"
            )
        ready = (
            last.get("scene") == "testrun"
            and last.get("loading_active") == "false"
            and int(last.get("tick", "0")) > 0
        )
        if ready:
            tick = int(last["tick"])
            if first_ready_at == 0.0:
                first_ready_at = time.monotonic()
                first_ready_tick = tick
            elif time.monotonic() - first_ready_at >= 1.0 and tick > first_ready_tick:
                return last
        else:
            first_ready_at = 0.0
            first_ready_tick = 0
        session.assert_wait_target_runnable("run presentation")
        time.sleep(0.1)
    raise CaptureFailure(f"run presentation remained busy: {last}")


def configure_two_participant_hub_roster(
    session: OwnedSoloSession,
) -> dict[str, Any]:
    settings_path = (
        session.stage_root
        / ".sdmod"
        / "mod-settings"
        / "bot.brain.json"
    )
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_payload = {
        "schemaVersion": 1,
        "values": {
            "focus_bot_key": "NONE",
            "kite_radius": 340,
            "offense_enabled": False,
            "roster": [],
            "think_profile": "standard",
        },
    }
    temporary_path = settings_path.with_name(
        f".{settings_path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    )
    with temporary_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(settings_payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_path, settings_path)

    reloaded = session.values(
        """
local result = sd.__settings_reload('bot.brain')
print('ok=' .. tostring(result.ok))
print('changed=' .. table.concat(result.changed or {}, ','))
print('error=' .. tostring(result.error or ''))
"""
    )
    require(
        reloaded.get("ok") == "true",
        f"HUD ally roster clear did not reload: {reloaded}",
    )
    cleared = wait_for_values(
        session,
        "empty bot-brain roster",
        "print('bot_count=' .. tostring(#(sd.bots.list() or {})))",
        lambda values: int(values.get("bot_count", "-1")) == 0,
    )
    spawned = session.values(
        """
local bot, err = sd.bots.spawn({
  name = 'HUD Ally', class = 'water', discipline = 'body'
})
assert(bot ~= nil, tostring(err or 'HUD ally spawn rejected'))
_G.__uire_hud_ally = bot
print('participant_id=' .. tostring(bot:participant_id()))
print('name=HUD Ally')
"""
    )
    participant_id = int(spawned.get("participant_id", "0"))
    require(participant_id > 0, f"direct HUD ally has no participant id: {spawned}")
    materialized = wait_for_values(
        session,
        "direct HUD ally hub materialization",
        f"""
local scene = sd.world.get_scene() or {{}}
local state = sd.bots.get_participant_state({participant_id})
print('scene=' .. tostring(scene.name or scene.kind or ''))
print('materialized=' .. tostring(
  state ~= nil and state.entity_materialized == true))
print('actor_address=' .. tostring(state and state.actor_address or 0))
print('max_hp=' .. tostring(state and state.max_hp or 0))
print('participant_count=' .. tostring(#(sd.bots.list() or {{}}) + 1))
""",
        lambda values: (
            values.get("scene") == "hub"
            and values.get("materialized") == "true"
            and int(values.get("actor_address", "0")) > 0
            and float(values.get("max_hp", "0")) > 0.0
            and int(values.get("participant_count", "0")) == 2
        ),
        timeout=30.0,
    )
    return {
        "settings_path": str(settings_path),
        "settings": settings_payload,
        "reload": reloaded,
        "cleared": cleared,
        "spawned": spawned,
        "materialized": materialized,
    }


def queue_capture_sequence(
    session: OwnedSoloSession,
    raw_directory: Path,
    label: str,
    frame_count: int,
    *,
    timeout: float = 45.0,
) -> list[dict[str, Any]]:
    queued = parse_values(
        session.lua(
            f"""
local ok, err = sd.debug.queue_native_scene_capture_sequence(
  {json.dumps(label)}, {frame_count})
print('ok=' .. tostring(ok))
print('error=' .. tostring(err or ''))
"""
        )
    )
    require(queued.get("ok") == "true", f"HUD capture did not arm: {queued}")
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        try:
            last = capture_status(session)
        except Exception:
            session.assert_wait_target_runnable(f"HUD capture {label!r}")
            time.sleep(0.05)
            continue
        state = last.get("state", "")
        if state == "complete":
            break
        if state == "failed":
            raise CaptureFailure(
                f"HUD capture {label!r} is broken, not busy: "
                f"{last.get('error_message', '')}"
            )
        require(
            state in {"armed", "capturing"},
            f"HUD capture {label!r} entered unexpected state {state!r}: {last}",
        )
        session.assert_wait_target_runnable(f"HUD capture {label!r}")
        time.sleep(0.05)
    else:
        raise CaptureFailure(f"HUD capture {label!r} remained busy: {last}")

    require(last.get("surface") == "hud", f"wrong capture surface: {last}")
    require(
        int(last.get("captured_frame_count", "-1")) == frame_count,
        f"HUD capture completed an unexpected frame count: {last}",
    )
    paths = []
    for index in range(frame_count):
        stem = label if frame_count == 1 else f"{label}-frame-{index:04d}"
        paths.append(raw_directory / f"{stem}.json")
    missing = [str(path) for path in paths if not path.is_file()]
    require(not missing, f"HUD capture completed without outputs: {missing}")
    frames = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    require(
        all(frame.get("surface") == "hud" for frame in frames),
        "HUD capture outputs did not all identify the HUD surface",
    )
    return frames


def provenance_header(
    source: dict[str, Any],
    launch: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "solomon-dark-native-hud-goldens-v1",
        "recorded_live": True,
        "instance": INSTANCE,
        "ports": list(PORTS),
        "participant_id": PARTICIPANT_ID,
        "audio_disabled": True,
        "source_commit_sha": source["commit_sha"],
        "source_tree_sha": source["tree_sha"],
        "worktree_dirty_at_capture_start": source["worktree_dirty"],
        "game_binary_sha256": windows_sha256(GAME_BINARY),
        "loader_sha256": windows_sha256(LOADER),
        "staged_loader_sha256": windows_sha256(STAGED_LOADER),
        "process_id": int(launch["processId"]),
        "executable_path": launch["executablePath"],
        "capture_method": (
            "native Gameplay HUD render boundary plus exact text, Glyph/TextQuad, "
            "belt-slot, state snapshot, and D3D9 backbuffer observation"
        ),
        "native_resolution": list(NATIVE_RESOLUTION),
        "settle_contract": {
            "minimum_consecutive_samples": SETTLE_SAMPLE_FLOOR,
            "minimum_span_seconds": SETTLE_SECONDS_FLOOR,
            "maximum_animated_fraction": MAXIMUM_ANIMATED_FRACTION,
        },
        "behavior_trace_contract": {
            "maximum_retained_change_samples": MAXIMUM_BEHAVIOR_TRACE_SAMPLES,
            "preserves": ["first", "last", "every exact-text transition"],
        },
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def structural_payload(frame: dict[str, Any]) -> dict[str, Any]:
    hud = frame.get("hud_state") or {}
    draws = frame.get("draws") or []
    return {
        "surface": frame.get("surface"),
        "scene": frame.get("scene"),
        "layer_order": frame.get("layer_order"),
        "visibility": hud.get("visibility"),
        "local_dead": hud.get("local_dead"),
        "draws": [
            {
                "draw_order": draw.get("draw_order"),
                "layer": draw.get("layer"),
                "semantic_role": draw.get("semantic_role"),
                "native_phase": draw.get("native_phase"),
                "draw_kind": draw.get("draw_kind"),
                "caller": draw.get("caller"),
                "sprite": draw.get("sprite"),
                "tint": draw.get("tint"),
                "lighting_scalar": draw.get("lighting_scalar"),
                "blend": draw.get("blend"),
                "visible": draw.get("visible"),
                "sort_key": draw.get("sort_key"),
            }
            for draw in draws
        ],
        "exact_text": [
            {
                "text": text.get("text"),
                "caller": text.get("caller"),
                "first_draw_order": text.get("first_draw_order"),
                "draw_count": text.get("draw_count"),
            }
            for text in frame.get("exact_text") or []
        ],
        "strips": [
            {
                "art": strip.get("art"),
                "first_draw_order": strip.get("first_draw_order"),
                "draw_count": strip.get("draw_count"),
            }
            for strip in hud.get("strips") or []
        ],
        "slots": [
            {
                "draw_order": slot.get("draw_order"),
                "kind_id": slot.get("kind_id"),
                "selection_flag": slot.get("selection_flag"),
                "skill_id": slot.get("skill_id"),
                "item_value": slot.get("item_value"),
                "count": slot.get("count"),
                "input_slot": slot.get("input_slot"),
                "cooldown_available": slot.get("cooldown") is not None,
                "cooldown_capacity": (
                    (slot.get("cooldown") or {}).get("capacity")
                ),
            }
            for slot in hud.get("slots") or []
        ],
        "ally_bars": [
            {"glyph": row.get("glyph")}
            for row in hud.get("ally_bars") or []
        ],
    }


def geometry_payload(frame: dict[str, Any]) -> dict[str, Any]:
    hud = frame.get("hud_state") or {}
    return {
        "draws": [
            {
                "draw_order": draw.get("draw_order"),
                "resolved_screen_rect": draw.get("resolved_screen_rect"),
                "clipped_screen_rect": draw.get("clipped_screen_rect"),
            }
            for draw in frame.get("draws") or []
        ],
        "exact_text": [
            {
                "first_draw_order": text.get("first_draw_order"),
                "screen_rect": text.get("screen_rect"),
            }
            for text in frame.get("exact_text") or []
        ],
        "strips": [
            {
                "first_draw_order": strip.get("first_draw_order"),
                "x": strip.get("x"),
                "y": strip.get("y"),
                "width": strip.get("width"),
            }
            for strip in hud.get("strips") or []
        ],
        "slots": [
            {
                "input_slot": slot.get("input_slot"),
                "logical_rect": slot.get("logical_rect"),
            }
            for slot in hud.get("slots") or []
        ],
    }


def _motion_envelope(rects: list[list[float]]) -> dict[str, Any]:
    return {
        "anchor_rect": rects[0],
        "envelope": [
            min(rect[0] for rect in rects),
            min(rect[1] for rect in rects),
            max(rect[2] for rect in rects),
            max(rect[3] for rect in rects),
        ],
    }


def validate_settle_capture(
    frames: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    require(
        len(frames) >= SETTLE_SAMPLE_FLOOR,
        f"{label} settle gate examined too few real HUD frames",
    )
    require(
        any((frame.get("hud_state") or {}).get("slots") for frame in frames),
        f"{label} settle gate never reached the required retail belt witness",
    )
    digests = [canonical_sha256(structural_payload(frame)) for frame in frames]
    runs: list[tuple[int, int, str]] = []
    start = 0
    for index in range(1, len(frames) + 1):
        if index == len(frames) or digests[index] != digests[start]:
            runs.append((start, index, digests[start]))
            start = index

    accepted: tuple[int, int, str] | None = None
    for candidate in runs:
        first, end, _ = candidate
        count = end - first
        span = (
            int(frames[end - 1].get("render_observed_ms", 0))
            - int(frames[first].get("render_observed_ms", 0))
        )
        if count >= SETTLE_SAMPLE_FLOOR and span >= SETTLE_SECONDS_FLOOR * 1000:
            if accepted is None or count > accepted[1] - accepted[0]:
                accepted = candidate
    if accepted is None:
        diagnostics = [
            {
                "count": end - first,
                "span_ms": (
                    int(frames[end - 1].get("render_observed_ms", 0))
                    - int(frames[first].get("render_observed_ms", 0))
                ),
                "signature": digest,
            }
            for first, end, digest in runs
        ]
        raise CaptureFailure(
            f"{label} never structurally settled for 40 consecutive samples "
            f"over two seconds: {diagnostics}"
        )

    first, end, digest = accepted
    settled = frames[first:end]
    geometries = [geometry_payload(frame) for frame in settled]
    draw_count = len(settled[0].get("draws") or [])
    require(draw_count > 0, f"{label} settled without a real HUD draw witness")
    animated: list[dict[str, Any]] = []
    for draw_order in range(draw_count):
        rects = [
            list(geometry["draws"][draw_order]["resolved_screen_rect"])
            for geometry in geometries
        ]
        clipped = [
            list(geometry["draws"][draw_order]["clipped_screen_rect"])
            for geometry in geometries
        ]
        if any(rect != rects[0] for rect in rects[1:]) or any(
            rect != clipped[0] for rect in clipped[1:]
        ):
            animated.append(
                {
                    "draw_order": draw_order,
                    **_motion_envelope(rects),
                    "clipped": _motion_envelope(clipped),
                }
            )
    animated_fraction = len(animated) / draw_count
    require(
        animated_fraction <= MAXIMUM_ANIMATED_FRACTION,
        f"{label} animated {len(animated)}/{draw_count} HUD draws, above 30%",
    )
    return {
        "required_minimum_consecutive_samples": SETTLE_SAMPLE_FLOOR,
        "required_minimum_span_ms": int(SETTLE_SECONDS_FLOOR * 1000),
        "captured_frame_count": len(frames),
        "stable_window_start": first,
        "stable_window_end_exclusive": end,
        "stable_sample_count": len(settled),
        "stable_span_ms": (
            int(settled[-1]["render_observed_ms"])
            - int(settled[0]["render_observed_ms"])
        ),
        "first_tick": int(settled[0]["hud_state"]["simulation_tick"]),
        "last_tick": int(settled[-1]["hud_state"]["simulation_tick"]),
        "structural_signature_sha256": digest,
        "animated_draws": animated,
        "animated_fraction": animated_fraction,
        "representative_frame_index": first,
    }


def distill_frame(frame: dict[str, Any]) -> dict[str, Any]:
    hud = frame["hud_state"]
    return {
        "render_sequence_index": frame.get("render_sequence_index"),
        "render_observed_ms": frame.get("render_observed_ms"),
        "tick": hud.get("simulation_tick"),
        "camera": frame.get("camera"),
        "health": hud.get("health"),
        "mana": hud.get("mana"),
        "progression": hud.get("progression"),
        "status": hud.get("status"),
        "visibility": hud.get("visibility"),
        "local_dead": hud.get("local_dead"),
        "ally_bars": hud.get("ally_bars"),
        "strips": hud.get("strips"),
        "slots": hud.get("slots"),
        "exact_text": frame.get("exact_text"),
        "draws": [
            {
                "draw_order": draw.get("draw_order"),
                "draw_kind": draw.get("draw_kind"),
                "caller": draw.get("caller"),
                "sprite": draw.get("sprite"),
                "tint": draw.get("tint"),
                "blend": draw.get("blend"),
                "resolved_screen_rect": draw.get("resolved_screen_rect"),
                "clipped_screen_rect": draw.get("clipped_screen_rect"),
                "visible": draw.get("visible"),
            }
            for draw in frame.get("draws") or []
        ],
    }


def behavior_sample(frame: dict[str, Any]) -> dict[str, Any]:
    hud = frame["hud_state"]
    draws = frame.get("draws") or []

    def visible_strip_rect(strip: dict[str, Any]) -> list[float] | None:
        first = int(strip["first_draw_order"])
        end = first + int(strip["draw_count"])
        candidates = [
            draw.get("clipped_screen_rect")
            for draw in draws[first:end]
            if draw.get("visible") and draw.get("clipped_screen_rect") is not None
        ]
        if not candidates:
            return None
        return [
            min(float(rect[0]) for rect in candidates),
            min(float(rect[1]) for rect in candidates),
            max(float(rect[2]) for rect in candidates),
            max(float(rect[3]) for rect in candidates),
        ]

    return {
        "tick": int(hud["simulation_tick"]),
        "render_observed_ms": int(frame["render_observed_ms"]),
        "health": hud["health"],
        "mana": hud["mana"],
        "progression": hud["progression"],
        "status": hud["status"],
        "visibility": hud["visibility"],
        "local_dead": hud["local_dead"],
        "strip_widths": [
            {
                "art_id": strip["art"]["id"],
                "first_draw_order": strip["first_draw_order"],
                "width": strip["width"],
                "visible_rect": visible_strip_rect(strip),
            }
            for strip in hud.get("strips") or []
        ],
        "cooldowns": [
            {
                "input_slot": slot["input_slot"],
                "current": (slot.get("cooldown") or {}).get("current"),
                "capacity": (slot.get("cooldown") or {}).get("capacity"),
            }
            for slot in hud.get("slots") or []
            if slot.get("cooldown") is not None
        ],
        "ally_health_ratios": [
            row["health_ratio"] for row in hud.get("ally_bars") or []
        ],
        "exact_text": [
            {
                "text": text["text"],
                "screen_rect": text["screen_rect"],
            }
            for text in frame.get("exact_text") or []
        ],
    }


def changed_behavior_trace(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    previous_without_time: dict[str, Any] | None = None
    for frame in frames:
        sample = behavior_sample(frame)
        comparison = {
            key: value
            for key, value in sample.items()
            if key not in {"tick", "render_observed_ms"}
        }
        if previous_without_time != comparison:
            trace.append(sample)
            previous_without_time = comparison
    final = behavior_sample(frames[-1])
    if not trace or trace[-1]["tick"] != final["tick"]:
        trace.append(final)
    return trace


def compact_behavior_trace(
    frames: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    full_trace = changed_behavior_trace(frames)
    total = len(full_trace)
    if total <= MAXIMUM_BEHAVIOR_TRACE_SAMPLES:
        return full_trace, total, {
            "kind": "all-change-samples",
            "maximum_samples": MAXIMUM_BEHAVIOR_TRACE_SAMPLES,
        }

    required: set[int] = {0, total - 1}
    previous_text = full_trace[0]["exact_text"]
    for index, sample in enumerate(full_trace[1:], start=1):
        if sample["exact_text"] != previous_text:
            required.add(index - 1)
            required.add(index)
            previous_text = sample["exact_text"]
    require(
        len(required) <= MAXIMUM_BEHAVIOR_TRACE_SAMPLES,
        "behavior compaction would discard an exact-text transition",
    )

    target_count = MAXIMUM_BEHAVIOR_TRACE_SAMPLES
    if target_count > 1:
        for sample_index in range(target_count):
            required.add(
                round(sample_index * (total - 1) / (target_count - 1))
            )
    if len(required) > target_count:
        optional = sorted(required - {0, total - 1})
        text_transition_indices: set[int] = set()
        previous_text = full_trace[0]["exact_text"]
        for index, sample in enumerate(full_trace[1:], start=1):
            if sample["exact_text"] != previous_text:
                text_transition_indices.update({index - 1, index})
                previous_text = sample["exact_text"]
        keep = {0, total - 1, *text_transition_indices}
        optional = [index for index in optional if index not in keep]
        slots = target_count - len(keep)
        require(slots >= 0, "behavior trace text transitions exceed the compact fixture bound")
        if slots > 0 and optional:
            chosen = {
                optional[
                    round(sample_index * (len(optional) - 1) / max(slots - 1, 1))
                ]
                for sample_index in range(slots)
            }
            keep.update(chosen)
        required = keep

    selected = sorted(required)
    require(
        2 <= len(selected) <= MAXIMUM_BEHAVIOR_TRACE_SAMPLES,
        "behavior compaction produced an invalid retained-sample count",
    )
    return [full_trace[index] for index in selected], total, {
        "kind": "endpoint-text-transition-and-even-change-samples",
        "maximum_samples": MAXIMUM_BEHAVIOR_TRACE_SAMPLES,
        "retained_change_indices": selected,
    }


def wait_for_values(
    session: OwnedSoloSession,
    description: str,
    code: str,
    predicate: Any,
    *,
    timeout: float = 20.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = session.values(code)
            if predicate(last):
                return last
        except (subprocess.TimeoutExpired, local_sync.VerifyFailure) as error:
            session.assert_wait_target_runnable(description)
            last_error = str(error)
        session.assert_wait_target_runnable(description)
        time.sleep(0.05)
    raise CaptureFailure(
        f"{description} remained busy: last={last} error={last_error}"
    )


def wait_for_hud_exact_text(
    session: OwnedSoloSession,
    raw_directory: Path,
    label: str,
    text_fragment: str,
    *,
    timeout: float = 3.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    attempt = 0
    last_texts: list[str] = []
    while time.monotonic() < deadline:
        attempt += 1
        frame = queue_capture_sequence(
            session,
            raw_directory,
            f"{label}-readiness-{attempt:03d}",
            1,
            timeout=5.0,
        )[0]
        last_texts = [
            str(row.get("text", ""))
            for row in frame.get("exact_text") or []
        ]
        if any(text_fragment in text for text in last_texts):
            return {
                "attempt": attempt,
                "tick": int(frame["hud_state"]["simulation_tick"]),
                "texts": last_texts,
            }
        session.assert_wait_target_runnable(f"HUD exact-text readiness {label!r}")
    raise CaptureFailure(
        f"HUD exact-text readiness {label!r} is broken, not busy: "
        f"never observed {text_fragment!r}; last={last_texts}"
    )


def set_player_vitals(
    session: OwnedSoloSession,
    *,
    hp: float,
    max_hp: float = 50.0,
    mp: float = 100.0,
    max_mp: float = 100.0,
) -> dict[str, str]:
    written = session.values(
        f"""
local player = assert(sd.player.get_state(), 'player state unavailable')
local progression = assert(tonumber(player.progression_address))
local actor = assert(tonumber(player.actor_address))
local function write(name, value)
  return sd.debug.write_float(
    progression + assert(sd.debug.layout_offset(name)), value)
end
print('write.max_hp=' .. tostring(write('progression_max_hp', {max_hp:.9g})))
print('write.hp=' .. tostring(write('progression_hp', {hp:.9g})))
print('write.max_mp=' .. tostring(write('progression_max_mp', {max_mp:.9g})))
print('write.mp=' .. tostring(write('progression_mp', {mp:.9g})))
print('write.mana_reserve=' .. tostring(
  sd.debug.write_float(progression + 0x740, 0.0)))
print('write.magic_shield_current=' .. tostring(
  sd.debug.write_float(actor + 0x1C4, 0.0)))
print('write.magic_shield_maximum=' .. tostring(
  sd.debug.write_float(actor + 0x1C8, 0.0)))
"""
    )
    for key in (
        "write.max_hp",
        "write.hp",
        "write.max_mp",
        "write.mp",
        "write.mana_reserve",
        "write.magic_shield_current",
        "write.magic_shield_maximum",
    ):
        require(written.get(key) == "true", f"player vital write failed: {written}")
    observed = wait_for_values(
        session,
        "player vital render state",
        """
local player = assert(sd.player.get_state(), 'player state unavailable')
print('hp=' .. tostring(player.hp or -1))
print('max_hp=' .. tostring(player.max_hp or -1))
print('mp=' .. tostring(player.mp or -1))
print('max_mp=' .. tostring(player.max_mp or -1))
print('dead=' .. tostring(player.local_dead or false))
print('tick=' .. tostring(player.local_player_tick_count or 0))
""",
        lambda values: (
            math.isclose(float(values.get("hp", "nan")), hp, abs_tol=0.01)
            and math.isclose(
                float(values.get("max_hp", "nan")), max_hp, abs_tol=0.01
            )
            and math.isclose(float(values.get("mp", "nan")), mp, abs_tol=0.01)
            and int(values.get("tick", "0")) > 0
        ),
    )
    return {**written, **{f"observed.{key}": value for key, value in observed.items()}}


def set_mana_reserve(
    session: OwnedSoloSession,
    *,
    current: float,
) -> dict[str, str]:
    result = session.values(
        f"""
local player = assert(sd.player.get_state(), 'player state unavailable')
local progression = assert(tonumber(player.progression_address))
local address = progression + 0x740
print('write=' .. tostring(sd.debug.write_float(address, {current:.9g})))
print('current=' .. tostring(sd.debug.read_float(address) or -1))
print('tick=' .. tostring(player.local_player_tick_count or 0))
"""
    )
    require(
        result.get("write") == "true"
        and math.isclose(float(result.get("current", "nan")), current, abs_tol=0.01),
        f"mana reserve presentation write failed: {result}",
    )
    return result


def set_magic_shield(
    session: OwnedSoloSession,
    *,
    current: float,
    maximum: float,
) -> dict[str, str]:
    require(maximum > 0.0, f"magic-shield maximum must be positive, got {maximum}")
    require(0.0 < current <= maximum, f"invalid magic-shield state {current}/{maximum}")
    result = session.values(
        f"""
local player = assert(sd.player.get_state(), 'player state unavailable')
local actor = assert(tonumber(player.actor_address))
print('write.current=' .. tostring(
  sd.debug.write_float(actor + 0x1C4, {current:.9g})))
print('write.maximum=' .. tostring(
  sd.debug.write_float(actor + 0x1C8, {maximum:.9g})))
print('current=' .. tostring(sd.debug.read_float(actor + 0x1C4) or -1))
print('maximum=' .. tostring(sd.debug.read_float(actor + 0x1C8) or -1))
print('tick=' .. tostring(player.local_player_tick_count or 0))
"""
    )
    require(
        result.get("write.current") == "true"
        and result.get("write.maximum") == "true"
        and math.isclose(float(result.get("current", "nan")), current, abs_tol=0.01)
        and math.isclose(float(result.get("maximum", "nan")), maximum, abs_tol=0.01),
        f"magic-shield presentation write failed: {result}",
    )
    return result


def set_primary_cooldown(
    session: OwnedSoloSession,
    skill_entry_index: int,
    *,
    fraction: float = 0.80,
) -> dict[str, str]:
    require(
        0 <= skill_entry_index < 1024,
        f"invalid primary skill entry index {skill_entry_index}",
    )
    require(0.0 <= fraction <= 1.0, f"invalid cooldown fraction {fraction}")
    result = session.values(
        f"""
local player = assert(sd.player.get_state(), 'player state unavailable')
local progression = assert(tonumber(player.progression_address))
local entries = assert(tonumber(sd.debug.read_ptr(progression + 0x20)))
local count = assert(tonumber(sd.debug.read_u32(progression + 0x24)))
assert({skill_entry_index} < count, 'skill entry outside progression book')
local entry = entries + {skill_entry_index} * 0x70
local capacity = assert(tonumber(sd.debug.read_float(entry + 0x68)))
local target = capacity * {fraction:.9g}
local wrote = sd.debug.write_float(entry + 0x64, target)
print('entry=' .. tostring(entry))
print('capacity=' .. tostring(capacity))
print('target=' .. tostring(target))
print('write=' .. tostring(wrote))
"""
    )
    require(result.get("write") == "true", f"cooldown write failed: {result}")
    require(float(result.get("capacity", "0")) > 0.0, f"cooldown has no capacity: {result}")
    return result


def spawn_reward_at_player(
    session: OwnedSoloSession,
    kind: str,
    amount: int,
) -> dict[str, str]:
    result = session.values(
        f"""
local player = assert(sd.player.get_state(), 'player state unavailable')
local ok, err = sd.world.spawn_reward({{
  kind = {json.dumps(kind)},
  amount = {amount},
  x = assert(tonumber(player.x)),
  y = assert(tonumber(player.y)),
}})
print('ok=' .. tostring(ok))
print('error=' .. tostring(err or ''))
"""
    )
    require(result.get("ok") == "true", f"spawn_reward({kind}) failed: {result}")
    return result


def player_summary(session: OwnedSoloSession) -> dict[str, str]:
    return session.values(
        """
local player = assert(sd.player.get_state(), 'player state unavailable')
print('tick=' .. tostring(player.local_player_tick_count or 0))
print('hp=' .. tostring(player.hp or -1))
print('mp=' .. tostring(player.mp or -1))
print('level=' .. tostring(player.level or -1))
print('xp=' .. tostring(player.xp or -1))
print('gold=' .. tostring(player.gold or -1))
print('damage_x4=' .. tostring(player.damage_x4_remaining_ticks or 0))
print('transient_flags=' .. tostring(player.transient_status_flags or 0))
"""
    )


def stabilize_observation_arena(session: OwnedSoloSession) -> dict[str, str]:
    result = session.values(
        """
if not rawget(_G, '__uire_observation_arena_stable') then
  assert(sd.runtime.has_capability('events.filters.damage'))
  sd.events.filter('damage.taken', function(_event)
    return false
  end)
  sd.events.filter('wave.spawning', function(_event)
    return false
  end)
  _G.__uire_observation_arena_stable = true
end
print('registered=' .. tostring(_G.__uire_observation_arena_stable == true))
print('damage_capability=' .. tostring(
  sd.runtime.has_capability('events.filters.damage')))
print('wave_capability=' .. tostring(
  sd.runtime.has_capability('events.filters.wave')))
"""
    )
    require(
        result.get("registered") == "true"
        and result.get("damage_capability") == "true",
        f"observation arena guards did not register: {result}",
    )
    return result


def trigger_gold_pickup(session: OwnedSoloSession, amount: int = 25) -> dict[str, Any]:
    before = player_summary(session)
    spawn = spawn_reward_at_player(session, "gold", amount)
    target = int(float(before["gold"])) + amount
    after = wait_for_values(
        session,
        "native gold pickup",
        """
local player = assert(sd.player.get_state(), 'player state unavailable')
local loot = sd.world.get_replicated_loot() or {}
local feedback = loot.last_gold_feedback or {}
print('gold=' .. tostring(player.gold or -1))
print('feedback.valid=' .. tostring(feedback.valid or false))
print('feedback.applied=' .. tostring(feedback.applied or false))
print('feedback.amount=' .. tostring(feedback.amount or 0))
print('feedback.notification=' .. tostring(feedback.notification_applied or false))
""",
        lambda values: int(float(values.get("gold", "-1"))) >= target,
    )
    return {"before": before, "spawn": spawn, "after": after, "amount": amount}


def trigger_damage_x4(session: OwnedSoloSession) -> dict[str, Any]:
    before = player_summary(session)
    spawn = spawn_reward_at_player(session, "damage_x4", 1)
    after = wait_for_values(
        session,
        "native DamageX4 pickup",
        """
local player = assert(sd.player.get_state(), 'player state unavailable')
print('damage_x4=' .. tostring(player.damage_x4_remaining_ticks or 0))
print('transient_flags=' .. tostring(player.transient_status_flags or 0))
""",
        lambda values: (
            int(values.get("damage_x4", "0")) > 0
            and int(values.get("transient_flags", "0")) & 0x02 != 0
        ),
    )
    return {"before": before, "spawn": spawn, "after": after}


def ensure_hud_ally(session: OwnedSoloSession) -> dict[str, Any]:
    spawned = session.values(
        """
local handles = sd.bots.list() or {}
assert(#handles == 1,
  'two-participant HUD requires exactly one unambiguous bot handle')
local existing = handles[1]
_G.__uire_hud_ally = existing
local state = assert(sd.bots.get_participant_state(existing:participant_id()))
print('participant_id=' .. tostring(existing:participant_id()))
print('name=' .. tostring(state.name or ''))
print('bot_count=' .. tostring(#handles))
print('participant_count=' .. tostring(#handles + 1))
"""
    )
    participant_id = int(spawned.get("participant_id", "0"))
    require(participant_id > 0, f"HUD ally has no participant id: {spawned}")
    observed = wait_for_values(
        session,
        "HUD ally materialization",
        """
local bot = rawget(_G, '__uire_hud_ally')
print('available=' .. tostring(bot ~= nil))
print('alive=' .. tostring(bot and bot:alive() or false))
print('hp=' .. tostring(bot and bot:hp() or 0))
print('max_hp=' .. tostring(bot and bot:max_hp() or 0))
print('participant_count=' .. tostring(#(sd.bots.list() or {}) + 1))
""",
        lambda values: (
            values.get("available") == "true"
            and values.get("alive") == "true"
            and float(values.get("max_hp", "0")) > 0.0
            and int(values.get("participant_count", "0")) == 2
        ),
        timeout=180.0,
    )
    return {"spawned": spawned, "observed": observed}


def arm_earth_charge(session: OwnedSoloSession) -> dict[str, str]:
    cleared = session.values(
        "print('cleared=' .. tostring(sd.input.clear_mouse_left()))"
    )
    require(cleared.get("cleared") == "true", f"Earth charge input clear failed: {cleared}")
    wait_for_values(
        session,
        "previous Earth Boulder retirement",
        f"""
local count = 0
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  if tonumber(actor.object_type_id) == {EARTH_BOULDER_TYPE_ID} then
    count = count + 1
  end
end
print('count=' .. tostring(count))
""",
        lambda values: int(values.get("count", "-1")) == 0,
    )
    result = session.values(
        f"""
_G.__uire_charge_samples = {{}}
if not rawget(_G, '__uire_charge_sampler_registered') then
  sd.events.on('runtime.tick', function(event)
    local samples = rawget(_G, '__uire_charge_samples')
    if type(samples) ~= 'table' then return end
    local tick = tonumber(type(event) == 'table' and event.tick_count) or 0
    local best_address, best_charge = 0, -1
    for _, actor in ipairs(sd.world.list_actors() or {{}}) do
      if tonumber(actor.object_type_id) == {EARTH_BOULDER_TYPE_ID} then
        local address = tonumber(actor.actor_address) or 0
        local charge = address ~= 0 and
          tonumber(sd.debug.read_float(address + {EARTH_BOULDER_CHARGE_OFFSET})) or -1
        if charge > best_charge then
          best_address, best_charge = address, charge
        end
      end
    end
    samples[#samples + 1] = {{
      tick = tick, actor_address = best_address, charge = best_charge
    }}
  end)
  _G.__uire_charge_sampler_registered = true
end
local player = assert(sd.player.get_state(), 'player state unavailable')
local actor = assert(tonumber(player.actor_address))
local x = assert(sd.debug.read_float(
  actor + assert(sd.debug.layout_offset('actor_position_x'))))
local y = assert(sd.debug.read_float(
  actor + assert(sd.debug.layout_offset('actor_position_y'))))
assert(sd.debug.write_float(
  actor + assert(sd.debug.layout_offset('actor_heading')), 90.0))
assert(sd.debug.write_float(
  actor + assert(sd.debug.layout_offset('actor_aim_target_x')), x + 320.0))
assert(sd.debug.write_float(
  actor + assert(sd.debug.layout_offset('actor_aim_target_y')), y))
assert(sd.debug.write_u32(
  actor + assert(sd.debug.layout_offset('actor_aim_target_aux0')), 0))
assert(sd.debug.write_u32(
  actor + assert(sd.debug.layout_offset('actor_aim_target_aux1')), 0))
assert(sd.input.set_native_control_allowance_frames(900))
assert(sd.input.hold_mouse_left_frames(800))
print('armed=true')
print('sampler=true')
"""
    )
    require(result == {"armed": "true", "sampler": "true"}, f"earth charge arm failed: {result}")
    wait_for_values(
        session,
        "Earth Boulder charge actor",
        f"""
local count, best = 0, -1
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  if tonumber(actor.object_type_id) == {EARTH_BOULDER_TYPE_ID} then
    count = count + 1
    local address = tonumber(actor.actor_address) or 0
    local value = address ~= 0 and
      tonumber(sd.debug.read_float(address + {EARTH_BOULDER_CHARGE_OFFSET})) or -1
    if value > best then best = value end
  end
end
print('count=' .. tostring(count))
print('best=' .. tostring(best))
""",
        lambda values: int(values.get("count", "0")) > 0 and float(values.get("best", "-1")) > 0.0,
    )
    return result


def read_earth_charge_samples(session: OwnedSoloSession) -> list[dict[str, Any]]:
    text = session.lua(
        """
for _, sample in ipairs(rawget(_G, '__uire_charge_samples') or {}) do
  print(string.format('%d,%d,%.9g',
    tonumber(sample.tick) or 0,
    tonumber(sample.actor_address) or 0,
    tonumber(sample.charge) or -1))
end
"""
    )
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split(",")
        require(len(fields) == 3, f"invalid Earth charge sample: {line!r}")
        rows.append(
            {
                "tick": int(fields[0]),
                "actor_address": int(fields[1]),
                "charge": float(fields[2]),
            }
        )
    require(rows, "Earth charge sampler returned no real fixed-tick samples")
    require(
        any(row["actor_address"] > 0 and row["charge"] >= 0.0 for row in rows),
        "Earth charge sampler never observed the native Boulder actor",
    )
    return rows


def gain_partial_experience(session: OwnedSoloSession) -> dict[str, Any]:
    before = session.values(
        """
local player = assert(sd.player.get_state(), 'player state unavailable')
local progression = assert(tonumber(player.progression_address))
print('level=' .. tostring(player.level or -1))
print('xp=' .. tostring(player.xp or -1))
print('previous=' .. tostring(sd.debug.read_float(progression + 0x38) or -1))
print('next=' .. tostring(sd.debug.read_float(progression + 0x3C) or -1))
print('tick=' .. tostring(player.local_player_tick_count or 0))
"""
    )
    room = float(before["next"]) - float(before["xp"])
    require(room > 1.0, f"partial XP probe has no room below level-up: {before}")
    amount = room * 0.5
    queued = session.values(
        f"""
local ok, err, serial = sd.debug.queue_native_experience_gain_probe(
  {amount:.9g}, false)
print('ok=' .. tostring(ok))
print('error=' .. tostring(err or ''))
print('serial=' .. tostring(serial or 0))
"""
    )
    require(queued.get("ok") == "true", f"partial XP gain did not queue: {queued}")
    serial = int(queued.get("serial", "0"))
    require(serial > 0, f"partial XP gain returned no request serial: {queued}")
    result = wait_for_values(
        session,
        "partial native XP gain",
        f"""
local completed, success, before_xp, after_xp, seh, err =
  sd.debug.get_native_experience_gain_probe_result({serial})
local player = sd.player.get_state() or {{}}
print('completed=' .. tostring(completed))
print('success=' .. tostring(success))
print('before_xp=' .. tostring(before_xp or 0))
print('after_xp=' .. tostring(after_xp or 0))
print('seh=' .. tostring(seh or 0))
print('error=' .. tostring(err or ''))
print('level=' .. tostring(player.level or -1))
print('xp=' .. tostring(player.xp or -1))
print('tick=' .. tostring(player.local_player_tick_count or 0))
""",
        lambda values: values.get("completed") == "true",
    )
    require(result.get("success") == "true", f"partial native XP gain failed: {result}")
    require(
        int(float(result["level"])) == int(float(before["level"]))
        and float(before["xp"]) < float(result["xp"]) < float(before["next"]),
        f"partial XP probe crossed or missed the intended level interval: {before} -> {result}",
    )
    return {
        "before": before,
        "queued": queued,
        "result": result,
        "requested_amount": amount,
    }


def trigger_native_level_up(session: OwnedSoloSession) -> dict[str, Any]:
    before = session.values(
        """
local player = assert(sd.player.get_state(), 'player state unavailable')
local progression = assert(tonumber(player.progression_address))
print('level=' .. tostring(player.level or -1))
print('xp=' .. tostring(player.xp or -1))
print('next=' .. tostring(sd.debug.read_float(progression + 0x3C) or -1))
print('tick=' .. tostring(player.local_player_tick_count or 0))
"""
    )
    level_before = int(float(before["level"]))
    amount = float(before["next"]) - float(before["xp"])
    require(amount > 0.0, f"level-up threshold is not ahead of XP: {before}")
    queued = session.values(
        f"""
local ok, err, serial = sd.debug.queue_native_experience_gain_probe(
  {amount:.9g}, false)
print('ok=' .. tostring(ok))
print('error=' .. tostring(err or ''))
print('serial=' .. tostring(serial or 0))
"""
    )
    require(queued.get("ok") == "true", f"native XP gain did not queue: {queued}")
    serial = int(queued.get("serial", "0"))
    require(serial > 0, f"native XP gain returned no request serial: {queued}")
    result = wait_for_values(
        session,
        "native XP gain probe",
        f"""
local completed, success, before_xp, after_xp, seh, err =
  sd.debug.get_native_experience_gain_probe_result({serial})
local player = sd.player.get_state() or {{}}
print('completed=' .. tostring(completed))
print('success=' .. tostring(success))
print('before_xp=' .. tostring(before_xp or 0))
print('after_xp=' .. tostring(after_xp or 0))
print('seh=' .. tostring(seh or 0))
print('error=' .. tostring(err or ''))
print('level=' .. tostring(player.level or -1))
print('xp=' .. tostring(player.xp or -1))
print('tick=' .. tostring(player.local_player_tick_count or 0))
""",
        lambda values: values.get("completed") == "true",
    )
    require(result.get("success") == "true", f"native XP gain failed: {result}")
    observed = wait_for_values(
        session,
        "native level-up presentation",
        """
local player = sd.player.get_state() or {}
local progression = tonumber(player.progression_address) or 0
local pending_a = progression ~= 0 and
  (tonumber(sd.debug.read_u32(progression + 0x44)) or 0) or 0
local pending_b = progression ~= 0 and
  (tonumber(sd.debug.read_u32(progression + 0x48)) or 0) or 0
print('level=' .. tostring(player.level or -1))
print('xp=' .. tostring(player.xp or -1))
print('pending_a=' .. tostring(pending_a))
print('pending_b=' .. tostring(pending_b))
print('tick=' .. tostring(player.local_player_tick_count or 0))
""",
        lambda values: (
            int(float(values.get("level", "-1"))) > level_before
            or int(values.get("pending_a", "0"))
            + int(values.get("pending_b", "0"))
            > 0
        ),
    )
    return {
        "before": before,
        "queued": queued,
        "result": result,
        "observed": observed,
        "requested_amount": amount,
    }


def start_wave_counter(session: OwnedSoloSession) -> dict[str, Any]:
    before = session.values(
        """
local state = sd.gameplay.get_combat_state() or {}
print('wave_index=' .. tostring(state.wave_index or 0))
print('wave_counter=' .. tostring(state.wave_counter or 0))
print('active=' .. tostring(state.active or false))
"""
    )
    if (
        before.get("active") == "true"
        or int(before.get("wave_counter", "999999999")) != 999999999
    ):
        return {"before": before, "already_active": True}
    started = session.values(
        "print('ok=' .. tostring(sd.gameplay.start_waves()))"
    )
    require(started.get("ok") == "true", f"start_waves failed: {started}")
    observed = wait_for_values(
        session,
        "native wave counter",
        """
local state = sd.gameplay.get_combat_state() or {}
print('wave_index=' .. tostring(state.wave_index or 0))
print('wave_counter=' .. tostring(state.wave_counter or 0))
print('waves_started=' .. tostring(state.waves_started or false))
""",
        lambda values: (
            values.get("waves_started") == "true"
            or int(values.get("wave_index", "0")) > 0
            or int(values.get("wave_counter", "0")) > 0
        ),
        timeout=30.0,
    )
    return {"before": before, "started": started, "observed": observed}


def capture_scenario(
    session: OwnedSoloSession,
    raw_directory: Path,
    crop_root: Path,
    label: str,
    *,
    prepare: Any = None,
    prepare_each_capture: bool = True,
    observe_after_capture: Any = None,
    capture_backbuffer: bool = True,
    screenshot_text_witness: str | None = None,
) -> dict[str, Any]:
    captures: list[dict[str, Any]] = []
    preparation: list[Any] = []
    post_capture_observations: list[Any] = []
    screenshot: dict[str, Any] | None = None
    screenshot_ready_probe: dict[str, Any] | None = None
    first_frames: list[dict[str, Any]] | None = None
    for independent_index in range(2):
        if prepare is not None and (prepare_each_capture or independent_index == 0):
            preparation.append(prepare())
        if independent_index == 0 and capture_backbuffer:
            if screenshot_text_witness is not None:
                screenshot_ready_probe = wait_for_hud_exact_text(
                    session,
                    raw_directory,
                    label,
                    screenshot_text_witness,
                )
            crop_root.mkdir(parents=True, exist_ok=True)
            screenshot = capture_game_backbuffer(
                session.pipe_name,
                crop_root / f"{label}.png",
            )
        sequence_label = f"{label}-settle-{independent_index + 1}"
        frames = queue_capture_sequence(
            session,
            raw_directory,
            sequence_label,
            SETTLE_CAPTURE_FRAMES,
            timeout=60.0,
        )
        gate = validate_settle_capture(frames, sequence_label)
        representative = frames[gate["representative_frame_index"]]
        captures.append(
            {
                "settle_gate": gate,
                "representative": distill_frame(representative),
            }
        )
        if observe_after_capture is not None:
            post_capture_observations.append(observe_after_capture())
        if first_frames is None:
            first_frames = frames

    require(
        captures[0]["settle_gate"]["structural_signature_sha256"]
        == captures[1]["settle_gate"]["structural_signature_sha256"],
        f"{label} structural HUD payload did not reproduce across independent captures",
    )
    first_animated = [
        row["draw_order"]
        for row in captures[0]["settle_gate"]["animated_draws"]
    ]
    second_animated = [
        row["draw_order"]
        for row in captures[1]["settle_gate"]["animated_draws"]
    ]
    require(
        first_animated == second_animated,
        f"{label} animated HUD set did not reproduce across independent captures",
    )
    require(first_frames is not None, f"{label} capture produced no frame witness")
    behavior_trace, behavior_change_count, behavior_sample_policy = (
        compact_behavior_trace(first_frames)
    )
    return {
        "preparation": preparation,
        "post_capture_observations": post_capture_observations,
        "screenshot": screenshot,
        "screenshot_ready_probe": screenshot_ready_probe,
        "independent_captures": captures,
        "behavior_trace": behavior_trace,
        "behavior_change_count": behavior_change_count,
        "behavior_sample_policy": behavior_sample_policy,
    }


def begin_mana_refill(session: OwnedSoloSession) -> dict[str, str]:
    written = session.values(
        """
local player = assert(sd.player.get_state(), 'player state unavailable')
local progression = assert(tonumber(player.progression_address))
local wrote = sd.debug.write_float(
  progression + assert(sd.debug.layout_offset('progression_mp')), 25.0)
print('write=' .. tostring(wrote))
print('tick=' .. tostring(player.local_player_tick_count or 0))
"""
    )
    require(written.get("write") == "true", f"mana drain write failed: {written}")
    observed = wait_for_values(
        session,
        "mana drain render state",
        """
local player = assert(sd.player.get_state(), 'player state unavailable')
print('mp=' .. tostring(player.mp or -1))
print('max_mp=' .. tostring(player.max_mp or -1))
print('tick=' .. tostring(player.local_player_tick_count or 0))
""",
        lambda values: (
            25.0 <= float(values.get("mp", "nan")) <= 27.5
            and math.isclose(float(values.get("max_mp", "nan")), 100.0, abs_tol=0.01)
            and int(values.get("tick", "0")) > 0
        ),
    )
    return {**written, **{f"observed.{key}": value for key, value in observed.items()}}


def primary_skill_entry_index(scenario: dict[str, Any]) -> int:
    slots = scenario["independent_captures"][0]["representative"]["slots"]
    candidates = [
        int(slot["skill_id"])
        for slot in slots
        if int(slot["kind_id"]) == 0x1B67
        and slot.get("cooldown") is not None
    ]
    require(
        len(candidates) == 1,
        f"retail belt primary skill lookup is ambiguous: {candidates}",
    )
    return candidates[0]


def finalize_screenshot_provenance(scenario: dict[str, Any]) -> None:
    screenshot = scenario.get("screenshot")
    require(isinstance(screenshot, dict), "HUD scenario omitted its backbuffer witness")
    path = Path(str(screenshot.get("path", "")))
    require(path.is_file(), f"HUD scenario backbuffer is missing: {path}")
    screenshot["sha256"] = windows_sha256(path)


def require_one(rows: list[Any], claim: str) -> Any:
    require(len(rows) == 1, f"{claim} lookup is ambiguous: found {len(rows)} candidates")
    return rows[0]


def scenario_representative(
    scenarios: dict[str, Any],
    scenario_name: str,
) -> dict[str, Any]:
    scenario = scenarios.get(scenario_name)
    require(isinstance(scenario, dict), f"HUD scenario {scenario_name!r} is missing")
    captures = scenario.get("independent_captures") or []
    require(
        len(captures) == 2,
        f"HUD scenario {scenario_name!r} lacks two independent settled captures",
    )
    representative = captures[0].get("representative")
    require(
        isinstance(representative, dict),
        f"HUD scenario {scenario_name!r} lacks a representative frame",
    )
    return representative


def draw_at(representative: dict[str, Any], draw_order: int) -> dict[str, Any]:
    return require_one(
        [
            draw
            for draw in representative.get("draws") or []
            if int(draw.get("draw_order", -1)) == draw_order
        ],
        f"HUD draw order {draw_order}",
    )


def union_rects(rects: list[list[float]], claim: str) -> list[float]:
    require(rects, f"{claim} has no real rectangles to union")
    require(
        all(len(rect) == 4 for rect in rects),
        f"{claim} includes a malformed rectangle",
    )
    return [
        min(float(rect[0]) for rect in rects),
        min(float(rect[1]) for rect in rects),
        max(float(rect[2]) for rect in rects),
        max(float(rect[3]) for rect in rects),
    ]


def draw_union(
    representative: dict[str, Any],
    draw_orders: list[int],
    *,
    clipped: bool = False,
    visible_only: bool = False,
    claim: str,
) -> list[float]:
    draws = [draw_at(representative, order) for order in draw_orders]
    if visible_only:
        draws = [draw for draw in draws if draw.get("visible")]
    key = "clipped_screen_rect" if clipped else "resolved_screen_rect"
    return union_rects([list(draw[key]) for draw in draws], claim)


def strip_by_art(
    representative: dict[str, Any],
    art_id: str,
    *,
    x: float | None = None,
) -> dict[str, Any]:
    candidates = [
        strip
        for strip in representative.get("strips") or []
        if (strip.get("art") or {}).get("id") == art_id
        and (x is None or math.isclose(float(strip.get("x", math.nan)), x, abs_tol=0.001))
    ]
    return require_one(candidates, f"HUD strip {art_id} at x={x}")


def strip_draw_orders(strip: dict[str, Any]) -> list[int]:
    first = int(strip["first_draw_order"])
    count = int(strip["draw_count"])
    require(count > 0, f"HUD strip {strip.get('art')} recorded no draw calls")
    return list(range(first, first + count))


ASSET_PACK_MANIFEST_IDS = {
    "UI.0",
    "UI.42",
    "UI.47",
    "UI.48",
    "UI.82",
    "UI.100",
}


def asset_source_for(atlas_id: str) -> dict[str, Any]:
    if atlas_id in ASSET_PACK_MANIFEST_IDS:
        return {
            "kind": "assetpack-manifest-id",
            "manifest": "webgame/assets/fixtures/asset-manifest-goldens.json",
        }
    if atlas_id.startswith("Fonts."):
        return {
            "kind": "native-bundle-record-group",
            "bundle": "images/Fonts.bundle",
        }
    if atlas_id.startswith("native.") or atlas_id == "none":
        return {"kind": "native-renderer-or-no-draw"}
    if "." in atlas_id:
        atlas, raw_index = atlas_id.rsplit(".", 1)
        if raw_index.isdigit():
            return {
                "kind": "native-bundle-record",
                "bundle": f"images/{atlas}.bundle",
                "record_index": int(raw_index),
            }
    return {"kind": "native-composite", "component_contract": atlas_id}


def build_element_census(scenarios: dict[str, Any]) -> dict[str, Any]:
    full = scenario_representative(scenarios, "full_health")
    xp = scenario_representative(scenarios, "partial_xp_progress")
    reserve = scenario_representative(scenarios, "mana_reserve_overlay")
    shield = scenario_representative(scenarios, "magic_shield_health")

    def sprite_id(representative: dict[str, Any], order: int) -> str:
        return str((draw_at(representative, order).get("sprite") or {}).get("id", ""))

    expected_draw_ids = {
        0: "UI.47",
        1: "UI.47",
        2: "UI.48",
        3: "UI.48",
        4: "Skills.72",
        5: "UI.100",
        6: "Inventory.46",
        7: "Inventory.46",
        11: "Fonts.535-626@0x2A4C",
        12: "Inventory.47",
        13: "Inventory.47",
        17: "Fonts.535-626@0x2B20",
        19: "UI.82",
        32: "UI.0",
        33: "native.untextured-quad",
        34: "Skills.67",
        35: "UI.42",
    }
    mismatches = {
        order: {"expected": expected, "actual": sprite_id(full, order)}
        for order, expected in expected_draw_ids.items()
        if sprite_id(full, order) != expected
    }
    require(not mismatches, f"retail HUD draw-order witnesses changed: {mismatches}")

    slots = full.get("slots") or []
    require(len(slots) == 8, f"retail HUD did not expose all eight belt slots: {slots}")
    by_input_slot = {int(slot["input_slot"]): slot for slot in slots}
    require(
        sorted(by_input_slot) == list(range(8)) and len(by_input_slot) == len(slots),
        "retail HUD belt slots are missing or duplicate input-slot identities",
    )

    entries: list[dict[str, Any]] = []

    def add(
        element_id: str,
        native_rect: list[float],
        atlas_id: str,
        draw_order: list[int],
        anchor: str,
        alignment: str,
        native_addresses: list[str],
        reference_scenario: str,
        *,
        clipped_native_rect: list[float] | None = None,
        logical_rect: list[float] | None = None,
        font: dict[str, Any] | None = None,
        component_atlas_ids: list[str] | None = None,
        mode_variants: list[dict[str, Any]] | None = None,
        observation: str = "live-settled",
        notes: str = "",
    ) -> None:
        require(
            not any(entry["id"] == element_id for entry in entries),
            f"HUD census element id {element_id!r} is duplicated",
        )
        entry = {
            "id": element_id,
            "native_rect": native_rect,
            "clipped_native_rect": clipped_native_rect or native_rect,
            "logical_rect": logical_rect,
            "anchor": anchor,
            "alignment": alignment,
            "atlas_id": atlas_id,
            "asset_source": asset_source_for(atlas_id),
            "font": font,
            "draw_order": draw_order,
            "native_addresses": native_addresses,
            "reference_scenario": reference_scenario,
            "observation": observation,
            "notes": notes,
        }
        if component_atlas_ids is not None:
            entry["component_atlas_ids"] = component_atlas_ids
        if mode_variants is not None:
            entry["mode_variants"] = mode_variants
        entries.append(entry)

    add(
        "cast.primary.card",
        draw_union(full, [0, 1], claim="primary cast card"),
        "UI.47",
        [0, 1],
        "center-bottom",
        "shadow +5,+5 behind base; base center x=-40, bottom=13",
        ["0x005D2520", "0x005D3E10"],
        "full_health",
    )
    add(
        "cast.secondary.card",
        draw_union(full, [2, 3], claim="secondary cast card"),
        "UI.48",
        [2, 3],
        "center-bottom",
        "shadow +5,+5 behind base; base center x=+40, bottom=13",
        ["0x005D2520", "0x005D3E10"],
        "full_health",
    )

    slot_atlas = {
        0: "Skills.72",
        1: "none",
        2: "none",
        3: "Inventory.46",
        4: "Inventory.47",
        5: "none",
        6: "none",
        7: "none",
    }
    slot_draws = {0: [4], 1: [], 2: [], 3: [6, 7], 4: [12, 13], 5: [], 6: [], 7: []}
    for slot_index in range(8):
        slot = by_input_slot[slot_index]
        logical_rect = [float(value) for value in slot["logical_rect"]]
        orders = slot_draws[slot_index]
        visual_rect = (
            draw_union(full, orders, claim=f"belt slot {slot_index}")
            if orders
            else logical_rect
        )
        add(
            f"belt.slot.{slot_index}",
            visual_rect,
            slot_atlas[slot_index],
            orders,
            "center-bottom",
            "60 px slot pitch; logical hit/layout box is 53 x 53",
            ["0x005D3E10"],
            "full_health",
            logical_rect=logical_rect,
            observation="live-logical-no-draw" if not orders else "live-settled",
            notes=(
                "Empty native slot emits no art; retain the logical rect for binding order."
                if not orders
                else ""
            ),
        )

    add(
        "belt.slot.0.input_hint",
        list(draw_at(full, 5)["resolved_screen_rect"]),
        "UI.100",
        [5],
        "center-bottom",
        "centered under slot 0; native bottom overflows by 8 px and is viewport-clipped",
        ["0x005D3E10"],
        "full_health",
        clipped_native_rect=list(draw_at(full, 5)["clipped_screen_rect"]),
    )
    count_font = {
        "bundle": "images/Fonts.bundle",
        "records": "535..626",
        "header": [10, 3, 28],
        "measured_line_height_px": 9,
        "renderer": "0x004A57C0",
    }
    add(
        "belt.slot.3.count",
        list(draw_at(full, 11)["resolved_screen_rect"]),
        "Fonts.535-626@0x2A4C",
        [8, 9, 10, 11],
        "center-bottom",
        "right/bottom count badge over health-potion slot",
        ["0x005D3E10", "0x004A57C0", "0x00415230"],
        "full_health",
        font=count_font,
        component_atlas_ids=["UI.22", "Fonts.535-626@0x2A4C"],
    )
    add(
        "belt.slot.4.count",
        list(draw_at(full, 17)["resolved_screen_rect"]),
        "Fonts.535-626@0x2B20",
        [14, 15, 16, 17],
        "center-bottom",
        "right/bottom count badge over mana-potion slot",
        ["0x005D3E10", "0x004A57C0", "0x00415230"],
        "full_health",
        font=count_font,
        component_atlas_ids=["UI.22", "Fonts.535-626@0x2B20"],
    )

    xp_fill = draw_at(xp, 18)
    add(
        "progression.xp.fill",
        [798.0, 833.0, 802.0, 881.0],
        "UI.81",
        [18],
        "center-bottom",
        "4 x 48 maximum; bottom anchored at y=881 and clipped upward by the XP ratio",
        ["0x005D2B0C", "0x00414D00"],
        "partial_xp_progress",
        clipped_native_rect=list(xp_fill["clipped_screen_rect"]),
        notes="The live partial state is clipped to 24 px at 45/90 XP. The low-level ownerless quad resolves statically to UI record 81 at UI object +0x3E3C.",
    )
    add(
        "progression.xp.track",
        list(draw_at(xp, 19)["resolved_screen_rect"]),
        "UI.82",
        [19],
        "center-bottom",
        "12 x 56 frame centered at x=800 and bottom=15",
        ["0x005D2B0C", "0x004142E0"],
        "partial_xp_progress",
    )

    mana_track = strip_by_art(full, "UI.70", x=0.0)
    mana_fill = strip_by_art(full, "UI.40", x=5.0)
    health_track = strip_by_art(full, "UI.70", x=-95.0)
    health_fill = strip_by_art(full, "UI.26", x=-90.0)
    for element_id, representative, strip, atlas_id, anchor, alignment, scenario_name in (
        ("mana.track", full, mana_track, "UI.70", "center-top", "110 x 20; left=center+50, top=14.5", "full_health"),
        ("mana.fill", full, mana_fill, "UI.40", "center-top", "100 x 10 maximum; left anchored", "full_health"),
        ("health.track", full, health_track, "UI.70", "center-top", "110 x 20; right=center-50, top=14.5", "full_health"),
        ("health.fill", full, health_fill, "UI.26", "center-top", "100 x 10 maximum; left anchored", "full_health"),
    ):
        orders = strip_draw_orders(strip)
        add(
            element_id,
            draw_union(representative, orders, claim=element_id),
            atlas_id,
            orders,
            anchor,
            alignment,
            ["0x005D2520", "0x00415230", "0x00420EC0"],
            scenario_name,
        )

    reserve_strip = strip_by_art(reserve, "UI.41")
    reserve_orders = strip_draw_orders(reserve_strip)
    add(
        "mana.reserve.overlay",
        draw_union(reserve, reserve_orders, claim="mana reserve overlay"),
        "UI.41",
        reserve_orders,
        "center-top",
        "right-side reserved-capacity segment; right edge is x=955 and width follows reserve/max mana",
        ["0x005D2BDD", "0x00415230"],
        "mana_reserve_overlay",
        notes="Conditional on progression+0x740 being nonzero.",
    )

    shield_strips = [
        strip
        for strip in shield.get("strips") or []
        if (strip.get("art") or {}).get("id") == "UI.26"
        and math.isclose(float(strip.get("x", math.nan)), -90.0, abs_tol=0.001)
    ]
    require(
        len(shield_strips) == 2,
        f"magic-shield composition did not expose life plus shield strips: {shield_strips}",
    )
    shield_strip = max(
        shield_strips,
        key=lambda strip: int(strip["first_draw_order"]),
    )
    shield_orders = strip_draw_orders(shield_strip)
    add(
        "health.magic_shield.overlay",
        draw_union(shield, shield_orders, claim="magic shield overlay"),
        "UI.26",
        shield_orders,
        "center-top",
        "left-anchored conditional layer composed against squared life fill",
        ["0x005D2BDD", "0x00415230", "0x00420EC0"],
        "magic_shield_health",
        notes="Conditional on actor+0x1C4 current and actor+0x1C8 maximum.",
    )

    add(
        "ally.row.0.identity",
        list(draw_at(full, 32)["resolved_screen_rect"]),
        "UI.0",
        [32],
        "center-top",
        "left=center-188; 128 px identity reservation; multiplayer name baseline y=46",
        ["0x005D3408", "0x005CF480", "0x004142E0", "0x0043BCD0"],
        "two_participant_ally_bar",
        font={
            "kind": "stock UI.0 ALLY glyph or gameplay_hud_hooks quarter-scale ExactText replacement",
            "loader_padding_px": 2,
            "loader_baseline_offset_px": 7,
            "loader_glyph_advance_px": 4,
            "loader_space_advance_px": 2,
        },
        component_atlas_ids=["UI.0", "Fonts.376-442"],
        mode_variants=[
            {
                "mode": "stock_single_player_or_bot_seam",
                "atlas_id": "UI.0",
                "rect": list(draw_at(full, 32)["resolved_screen_rect"]),
                "observation": "live-settled in this fixture",
            },
            {
                "mode": "multiplayer_transport",
                "atlas_id": "Fonts.376-442",
                "reserved_rect": list(draw_at(full, 32)["resolved_screen_rect"]),
                "name_left_x": 614.0,
                "baseline_y": 46.0,
                "width_function": "4 px per non-space byte plus 2 px per space byte",
                "observation": "prior live multiplayer acceptance in tools/verify_multiplayer_hud_names.py",
                "stock_label_suppressed": True,
            },
        ],
        notes="UI.0 is the stock ALLY glyph, not a participant name. Local transport suppresses it and renders the durable participant name inside the same reservation.",
    )
    add(
        "ally.row.0.health",
        list(draw_at(full, 33)["resolved_screen_rect"]),
        "native.untextured-quad",
        [33],
        "center-top",
        "50 x 5 maximum; left=center-240; row y=39.5",
        ["0x005D3408", "0x005CF480", "0x004142E0"],
        "two_participant_ally_bar",
    )
    add(
        "skill.binding.12.primary",
        list(draw_at(full, 34)["resolved_screen_rect"]),
        "Skills.67",
        [34],
        "center-top",
        "32.25 x 31.5 transform centered at x=800, y=25.5",
        ["0x005D367A", "0x0046B140", "0x00414EA0"],
        "full_health",
        notes="First of the conditional binding indices 12, 16, and 20; only index 12 is populated in this loadout.",
    )
    add(
        "aim.cursor",
        list(draw_at(full, 35)["resolved_screen_rect"]),
        "UI.42",
        [35],
        "pointer",
        "31 x 33 centered on the native mouse point; viewport clipped",
        ["0x005D3D48", "0x004F6070"],
        "full_health",
    )

    gold_rects = {
        tuple(float(value) for value in text["screen_rect"])
        for sample in scenarios["gold_pickup"]["behavior_trace"]
        for text in sample.get("exact_text") or []
        if "GOLD" in str(text.get("text", ""))
    }
    require(
        len(gold_rects) == 2,
        f"gold notification did not expose one base and one shadow rect: {sorted(gold_rects)}",
    )
    add(
        "notification.gold",
        union_rects([list(rect) for rect in sorted(gold_rects)], "gold notification"),
        "Fonts.376-442",
        [],
        "center-top",
        "centered notification stack; shadow is +0,+2 from the base line",
        ["0x005CA7C0", "0x005CF000", "0x004F5620"],
        "gold_pickup",
        font={
            "bundle": "images/Fonts.bundle",
            "records": "376..442",
            "header": [24, 5, 28],
            "format": "_s(%.2f)%s",
        },
    )

    require(entries, "HUD element census did not examine any live elements")
    return {
        "definition": "semantic visual elements; repeated strip segments and shadow/base draw calls are one element",
        "native_resolution": list(NATIVE_RESOLUTION),
        "count": len(entries),
        "elements": entries,
        "draw_call_witness": {
            "baseline_draw_count": len(full.get("draws") or []),
            "baseline_exact_text_count": len(full.get("exact_text") or []),
            "baseline_strip_count": len(full.get("strips") or []),
            "baseline_slot_count": len(slots),
        },
        "absence_findings": [
            {
                "id": "progression.numeric_level",
                "finding": "absent",
                "evidence": "level and XP changed without adding a numeric level draw to the in-run HUD; the level-up picker belongs to G11",
            },
            {
                "id": "gold.persistent_counter",
                "finding": "absent",
                "evidence": "gold state changed but the only new screen-overlay member was the transient 25 GOLD notification",
            },
            {
                "id": "wave.numeric_or_score_indicator",
                "finding": "absent",
                "evidence": "wave state changed without adding a screen-overlay draw or exact-text member",
            },
            {
                "id": "buff_or_debuff.icon_row",
                "finding": "absent",
                "evidence": "DamageX4 status and the prior invincibility-potion carrier effect add no retail screen HUD member",
            },
            {
                "id": "damage_or_heal.floater",
                "finding": "absent",
                "evidence": "the exhaustive HUD boundary has no numeric floater path; hit/heal presentation remains world/edge feedback",
            },
        ],
        "not_yet_reversed": [
            {
                "id": "featured_enemy.panel",
                "native_branch": "0x005D257E..0x005D2AEF, gated by gameplay+0x1C2C and actor config+0x1D0",
                "reason": "the sanctioned exact-spawn seam deliberately retires a featured pointer when the spawned actor has no durable EnemyConfig; fabricating that native object would violate the observation-only boundary",
            }
        ],
    }


def visible_strip_width_from_sample(
    sample: dict[str, Any],
    art_id: str,
    *,
    first_draw_order: int,
) -> float:
    strip = require_one(
        [
            row
            for row in sample.get("strip_widths") or []
            if row.get("art_id") == art_id
            and int(row.get("first_draw_order", -1)) == first_draw_order
        ],
        f"behavior strip {art_id} at draw {first_draw_order}",
    )
    rect = strip.get("visible_rect")
    if rect is None:
        return 0.0
    return float(rect[2]) - float(rect[0])


def build_behavior_contract(scenarios: dict[str, Any]) -> dict[str, Any]:
    health_samples = []
    for name in ("full_health", "damaged_health", "near_death_health"):
        scenario = scenarios[name]
        sample = scenario["behavior_trace"][0]
        current = float(sample["health"]["current"])
        maximum = float(sample["health"]["maximum"])
        health_samples.append(
            {
                "scenario": name,
                "tick": int(sample["tick"]),
                "current": current,
                "maximum": maximum,
                "ratio": current / maximum,
                "visible_width_px": visible_strip_width_from_sample(
                    sample,
                    "UI.26",
                    first_draw_order=29,
                ),
            }
        )

    mana_trace = scenarios["mana_drain_and_refill"]["behavior_trace"]
    require(len(mana_trace) >= 2, "mana refill trace did not measure a changing native pool")
    cooldown_trace = scenarios["active_cooldown"]["behavior_trace"]
    cooldown_points = [
        row
        for sample in cooldown_trace
        for row in sample.get("cooldowns") or []
        if int(row.get("input_slot", -1)) == 0
    ]
    require(
        len(cooldown_points) >= 2
        and float(cooldown_points[0]["current"]) > float(cooldown_points[-1]["current"]),
        "active cooldown trace did not measure a decreasing native remaining value",
    )

    charge_rows = [
        row
        for capture_rows in scenarios["earth_charge_hold"]["post_capture_observations"]
        for row in capture_rows
        if int(row["actor_address"]) > 0 and float(row["charge"]) >= 0.0
    ]
    require(len(charge_rows) >= 3, "Earth charge contract lacks fixed-tick native samples")
    adjacent = require_one(
        [
            (left, right)
            for left, right in zip(charge_rows, charge_rows[1:])
            if int(right["tick"]) == int(left["tick"]) + 1
            and 0.18 <= float(left["charge"]) < 0.95
        ][:1],
        "Earth charge adjacent fixed-tick witness",
    )
    measured_increment = float(adjacent[1]["charge"]) - float(adjacent[0]["charge"])
    require(
        math.isclose(measured_increment, 0.00125, rel_tol=0.0, abs_tol=2e-8),
        f"Earth charge increment changed from 0.00125: {measured_increment}",
    )

    xp_rep = scenario_representative(scenarios, "partial_xp_progress")
    xp_fill = draw_at(xp_rep, 18)
    xp_rect = list(xp_fill["clipped_screen_rect"])
    xp_height = float(xp_rect[3]) - float(xp_rect[1])
    require(xp_height > 0.0, "partial XP probe did not produce a visible vertical fill")

    shield_above = scenario_representative(scenarios, "magic_shield_health")
    shield_below = scenario_representative(
        scenarios, "magic_shield_below_health_fill"
    )

    def shield_composition(
        representative: dict[str, Any], scenario_name: str
    ) -> dict[str, Any]:
        strips = [
            strip
            for strip in representative.get("strips") or []
            if (strip.get("art") or {}).get("id") == "UI.26"
            and math.isclose(float(strip.get("x", math.nan)), -90.0, abs_tol=0.001)
        ]
        require(
            len(strips) == 2,
            f"{scenario_name} did not expose distinct life and magic-shield strips",
        )
        strips.sort(key=lambda strip: int(strip["first_draw_order"]))
        measured = []
        for strip in strips:
            orders = strip_draw_orders(strip)
            visible_rect = draw_union(
                representative,
                orders,
                clipped=True,
                visible_only=True,
                claim=f"{scenario_name} visible health-layer strip",
            )
            tints = {
                tuple(
                    float(draw_at(representative, order)["tint"][channel])
                    for channel in ("r", "g", "b", "a")
                )
                for order in orders
            }
            require(
                len(tints) == 1,
                f"{scenario_name} health-layer strip changed tint within one segmented draw: {tints}",
            )
            measured.append(
                {
                    "first_draw_order": int(strip["first_draw_order"]),
                    "visible_width_px": float(visible_rect[2]) - 645.0,
                    "tint_rgba": list(next(iter(tints))),
                }
            )
        by_tint = {tuple(row["tint_rgba"]): row for row in measured}
        require(
            set(by_tint) == {(1.0, 1.0, 1.0, 1.0), (0.5, 1.0, 1.0, 1.0)},
            f"{scenario_name} did not distinguish white life from cyan magic shield: {measured}",
        )
        require(
            [row["visible_width_px"] for row in measured]
            == sorted(row["visible_width_px"] for row in measured),
            f"{scenario_name} did not draw the shorter health layer before the longer layer: {measured}",
        )
        life = by_tint[(1.0, 1.0, 1.0, 1.0)]
        shield = by_tint[(0.5, 1.0, 1.0, 1.0)]
        return {
            "scenario": scenario_name,
            "life_visible_width_px": life["visible_width_px"],
            "shield_visible_width_px": shield["visible_width_px"],
            "life_first_draw_order": life["first_draw_order"],
            "shield_first_draw_order": shield["first_draw_order"],
            "shield_tint_rgba": [0.5, 1.0, 1.0, 1.0],
        }

    shield_compositions = [
        shield_composition(shield_above, "magic_shield_health"),
        shield_composition(shield_below, "magic_shield_below_health_fill"),
    ]

    gold_samples = [
        sample
        for sample in scenarios["gold_pickup"]["behavior_trace"]
        if any("GOLD" in str(text.get("text", "")) for text in sample.get("exact_text") or [])
    ]
    require(gold_samples, "gold pickup trace never observed its native notification")

    full_rep = scenario_representative(scenarios, "full_health")
    active_rep = scenario_representative(scenarios, "active_cooldown")
    return {
        "health_fill": {
            "function": "visible_width_px = dynamic_core_width * clamp(current / maximum, 0, 1)^2",
            "baseline_core_width_px": 100.0,
            "anchor": "left",
            "update": "samples native HP during every HUD render; no second display/smoothing accumulator",
            "native_fields": {
                "base": "progression+0x6C",
                "current": "progression+0x70",
                "maximum": "progression+0x74",
            },
            "near_death_flash_or_pulse": "none observed; tint remains RGBA (1,1,1,1) and only squared clipping changes",
            "normal_atlas_id": "UI.26",
            "magic_shield_atlas_id": "UI.26 (a second clipped strip)",
            "magic_shield": {
                "function": "second left-anchored width = dynamic_core_width * clamp(shield_current / shield_maximum, 0, 1)",
                "composition": "white life and cyan shield are sorted shorter-first, longer-last before drawing; the later layer can cover the earlier overlap",
                "observed_compositions": shield_compositions,
            },
            "observed_samples": health_samples,
        },
        "mana_fill": {
            "function": "visible_width_px = dynamic_core_width * clamp(current / maximum, 0, 1)",
            "baseline_core_width_px": 100.0,
            "anchor": "left",
            "update": "samples native MP during every HUD render",
            "native_fields": {
                "base": "progression+0x78",
                "current": "progression+0x7C",
                "maximum": "progression+0x80",
                "reserve": "progression+0x740",
            },
            "native_fixed_tick_hz": 100,
            "g1_250ms_distinction": "250 ms is the loader bot-reserve recovery service cadence, not a retail screen-fill smoothing timer",
            "reserve_overlay": "UI.41 marks the right-side reserved capacity; usable current mana is capped at maximum minus reserve",
            "first_sample": mana_trace[0],
            "last_sample": mana_trace[-1],
        },
        "cooldown": {
            "remaining_field_offset": "skill_entry+0x64",
            "capacity_field_offset": "skill_entry+0x68",
            "observed_capacity_ticks": float(cooldown_points[0]["capacity"]),
            "observed_first_remaining": float(cooldown_points[0]["current"]),
            "observed_last_remaining": float(cooldown_points[-1]["current"]),
            "sector_start_degrees": 360.0,
            "sector_end_degrees": "360 * (1 - remaining / capacity)",
            "covered_interval": "[end_degrees, 360]",
            "direction": "counter-clockwise in mathematical angle space; positive angle maps from screen-right toward screen-up",
            "segment_size_degrees": 45.0,
            "ready_icon_observed_alpha": float(draw_at(full_rep, 4)["tint"]["a"]),
            "active_icon_alpha": float(draw_at(active_rep, 4)["tint"]["a"]),
            "native_addresses": ["0x005C6D30", "0x00416330", "0x00416450"],
            "timing": "remaining decrements once per 100 Hz native fixed tick; renderer samples every HUD frame",
            "flash_or_pulse": "none observed; active icon alpha is steady 0.25 and ready icon alpha is steady 0.375",
        },
        "earth_charge": {
            "hud_meter": "none; charge presentation is the G2 world-space Boulder scale curve",
            "field": "Boulder+0x74",
            "initial_charge": 0.18,
            "increment_per_fixed_tick": 0.00125,
            "ticks_to_full_from_initial": 656,
            "seconds_to_full_at_100hz": 6.56,
            "measured_increment": measured_increment,
            "first_observed": charge_rows[0],
            "last_observed": charge_rows[-1],
        },
        "xp_and_level": {
            "fill_function": "bottom-anchored vertical ratio = (xp - previous_threshold) / (next_threshold - previous_threshold)",
            "fill_atlas_id": "UI.81",
            "track_atlas_id": "UI.82",
            "maximum_fill_height_px": 48.0,
            "observed_partial_fill_height_px": xp_height,
            "observed_partial_state": {"xp": 45, "previous_threshold": 0, "next_threshold": 90},
            "level_up_presentation": "G11-owned skill-picker screen; this fixture records only the fixed-tick XP/level transition",
            "numeric_level_in_run": "absent",
        },
        "gold_notification": {
            "format": "_s(%.2f)%s with payload 25 GOLD",
            "initial_lifetime_seconds": 1.5,
            "alpha": "clamp(timer, 0, 1)",
            "first_observed_tick": int(gold_samples[0]["tick"]),
            "last_observed_tick": int(gold_samples[-1]["tick"]),
            "native_addresses": ["0x005CA7C0", "0x005CF000"],
            "flash_or_pulse": "alpha-only expiry fade; no scale or position pulse observed",
        },
        "ally_health": {
            "function": "visible_width_px = 50 * clamp(current / maximum, 0, 1)",
            "anchor": "left",
            "row_pitch_px": 20.0,
            "append_abi": "0x005CF480(gameplay, glyph, health_ratio)",
        },
        "buff_debuff_and_floaters": {
            "screen_icon_row": "absent in the exhaustive retail HUD capture",
            "damage_x4_trigger_observed": True,
            "invincibility_potion": "world-space carrier/SpellGlow presentation; see potionvfx prior art",
            "numeric_damage_heal_floaters": "absent; do not invent position, velocity, lifetime, or damage-type colors",
        },
    }


def build_visibility_contract(scenarios: dict[str, Any]) -> dict[str, Any]:
    run = scenario_representative(scenarios, "full_health")
    run_ids = [
        (draw.get("sprite") or {}).get("id")
        for draw in run.get("draws") or []
    ]
    return {
        "matrix": [
            {
                "state": "hub_alive",
                "stock_hud": "run HUD remains visible and the courtyard adds four action/decor draws; College.18 and College.17 pulse alpha forever",
                "ally_rows": "one per additional durable participant",
                "evidence": "live diagnostic; NOT A GOLDEN because every one of 480 frames changed a non-rect tint field",
            },
            {
                "state": "run_alive",
                "stock_hud": "XP, belt/cast, vitals, ally rows, concentration emblems, notifications, and cursor",
                "ally_rows": "participant_count - 1 living/materialized peers",
                "evidence": "live-settled",
            },
            {
                "state": "run_alive_featured_enemy",
                "stock_hud": "binary branch exists but exact panel layout is Not Yet Reversed",
                "ally_rows": "normal run ownership remains outside the panel prefix",
                "evidence": "binary-static only; sanctioned exact spawns have no durable EnemyConfig",
            },
            {
                "state": "local_death",
                "stock_hud": "actor+0x160 skips featured enemy, XP, belt/cast, vitals, ally rows, concentration, and notifications; the aim cursor tail at 0x005D3D48 and optional gameplay fade still render",
                "ally_rows": "hidden locally",
                "evidence": "binary-static plus prior death/spectator live work",
            },
            {
                "state": "death_presentation_first_5_seconds",
                "stock_hud": "only the stock cursor/fade tail survives; no product spectator panel yet",
                "ally_rows": "hidden locally",
                "evidence": "host-spectator-ui prior art",
            },
            {
                "state": "spectating_living_peer",
                "stock_hud": "only the stock cursor/fade tail survives; product spectator overlay shows the local Spectating label, selected living peer, and click instruction",
                "ally_rows": "spectator overlay, not a second stock ally-vector ownership path",
                "evidence": "host-spectator-ui and mmspec prior art",
            },
            {
                "state": "respawned_alive",
                "stock_hud": "returns on the next alive render after scene-epoch/vitals convergence",
                "ally_rows": "rebuilt from durable current-epoch roster only",
                "evidence": "allyvis epoch-parity contract",
            },
            {
                "state": "level_up_picker",
                "stock_hud": "G11-owned overlay screen; no duplicate browser-HUD reconstruction",
                "ally_rows": "underlying run ownership unchanged",
                "evidence": "native-menus-and-boot contract",
            },
        ],
        "participant_count_rule": {
            "solo": 0,
            "two_participants": 1,
            "n_participants": "n - 1 unique nonlocal durable rows, sorted by participant id",
        },
        "live_draw_membership": {
            "run": run_ids,
            "hub_structurally_settled": False,
            "hub_diagnostic_draw_count": 40,
            "hub_run_draw_count": len(run_ids),
            "hub_non_rect_varying_draws": ["College.18", "College.17"],
        },
    }


def build_scaling_contract(census: dict[str, Any]) -> dict[str, Any]:
    require(
        census.get("native_resolution") == list(NATIVE_RESOLUTION),
        "HUD scaling contract did not start from the observed 1600x900 native viewport",
    )
    return {
        "observed_native_resolution": [1600, 900],
        "target_resolution": [1280, 800],
        "native_rule": "1:1 authored pixels; center anchors follow width/2, top anchors keep y, bottom anchors follow height",
        "target_transform": {
            "center_x_delta_px": -160,
            "bottom_y_delta_px": -100,
            "top_y_delta_px": 0,
            "scale_factor": 1.0,
        },
        "implementation": "re-evaluate each anchor at the target viewport; do not uniformly scale the 1600x900 bitmap",
        "designed_not_observed": {
            "safe_inset_px": 24,
            "minimum_skill_slot_px": [48, 48],
            "native_skill_slot_px": [53, 53],
            "minimum_vital_track_px": [110, 20],
            "minimum_ally_bar_px": [50, 8],
            "minimum_name_font_px": 12,
            "minimum_name_line_box_px": 16,
            "minimum_counter_font_px": 12,
            "minimum_notification_font_px": 16,
            "minimum_general_line_box_px": 16,
            "pointer_safe_rule": "clamp the complete 31x33 cursor inside the drawable viewport",
        },
        "design_reason": "readability policy required by roadmap section 4.1; every value in designed_not_observed is a rebuild decision, not a retail measurement",
    }


def create_reference_crops(
    crop_root: Path,
    scenarios: dict[str, Any],
    census: dict[str, Any],
) -> list[dict[str, Any]]:
    element_directory = crop_root / "elements"
    element_directory.mkdir(parents=True, exist_ok=False)
    specifications: list[dict[str, Any]] = [
        {
            "id": entry["id"],
            "scenario": entry["reference_scenario"],
            "rect": entry["native_rect"],
            "kind": "element",
        }
        for entry in census["elements"]
    ]
    specifications.extend(
        [
            {"id": "state.health.damaged", "scenario": "damaged_health", "rect": [630, 5, 760, 45], "kind": "state"},
            {"id": "state.health.near_death", "scenario": "near_death_health", "rect": [630, 5, 760, 45], "kind": "state"},
            {"id": "state.health.magic_shield", "scenario": "magic_shield_health", "rect": [630, 5, 760, 45], "kind": "state"},
            {"id": "state.health.magic_shield_below_life", "scenario": "magic_shield_below_health_fill", "rect": [630, 5, 760, 45], "kind": "state"},
            {"id": "state.mana.refill", "scenario": "mana_drain_and_refill", "rect": [840, 5, 970, 45], "kind": "state"},
            {"id": "state.mana.reserve", "scenario": "mana_reserve_overlay", "rect": [840, 5, 970, 45], "kind": "state"},
            {"id": "state.cooldown.active", "scenario": "active_cooldown", "rect": [460, 825, 525, 900], "kind": "state"},
            {"id": "state.earth.charge_world", "scenario": "earth_charge_hold", "rect": [720, 120, 880, 290], "kind": "state"},
            {"id": "state.gold.notification", "scenario": "gold_pickup", "rect": [720, 35, 880, 90], "kind": "state"},
            {"id": "state.buff.damage_x4_absence", "scenario": "damage_x4_buff", "rect": [620, 0, 980, 80], "kind": "state"},
            {"id": "state.ally.two_participant", "scenario": "two_participant_ally_bar", "rect": [545, 28, 750, 58], "kind": "state"},
            {"id": "state.xp.partial", "scenario": "partial_xp_progress", "rect": [785, 820, 815, 895], "kind": "state"},
        ]
    )

    records: list[dict[str, Any]] = []
    for specification in specifications:
        scenario = scenarios.get(specification["scenario"])
        require(
            isinstance(scenario, dict) and isinstance(scenario.get("screenshot"), dict),
            f"reference crop {specification['id']} has no source screenshot",
        )
        source_path = Path(str(scenario["screenshot"]["path"]))
        require(source_path.is_file(), f"reference crop source is missing: {source_path}")
        with Image.open(source_path) as source:
            require(
                source.size == NATIVE_RESOLUTION,
                f"reference crop {specification['id']} source is not 1600x900: {source.size}",
            )
            rect = [float(value) for value in specification["rect"]]
            padding = 6
            box = (
                max(0, math.floor(rect[0]) - padding),
                max(0, math.floor(rect[1]) - padding),
                min(source.width, math.ceil(rect[2]) + padding),
                min(source.height, math.ceil(rect[3]) + padding),
            )
            require(
                box[2] > box[0] and box[3] > box[1],
                f"reference crop {specification['id']} resolved an empty box {box}",
            )
            filename = specification["id"].replace(".", "-") + ".png"
            output_path = element_directory / filename
            source.crop(box).save(output_path, format="PNG")
        records.append(
            {
                "id": specification["id"],
                "kind": specification["kind"],
                "scenario": specification["scenario"],
                "source_path": str(source_path),
                "source_sha256": scenario["screenshot"]["sha256"],
                "crop_box": list(box),
                "path": str(output_path),
                "sha256": windows_sha256(output_path),
            }
        )
    require(
        len(records) >= int(census["count"]),
        "reference-crop pass did not emit at least one crop per census element",
    )
    return records


def record_full_session(
    session: OwnedSoloSession,
    raw_directory: Path,
    crop_root: Path,
) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}

    scenarios["full_health"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "full-health",
        prepare=lambda: set_player_vitals(session, hp=50.0, mp=100.0),
    )
    skill_entry = primary_skill_entry_index(scenarios["full_health"])

    scenarios["gold_pickup"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "gold-pickup",
        prepare=lambda: {
            "cooldown_reset": set_primary_cooldown(
                session, skill_entry, fraction=0.0
            ),
            "pickup": trigger_gold_pickup(session),
        },
        screenshot_text_witness="GOLD",
    )

    scenarios["damaged_health"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "damaged-health",
        prepare=lambda: set_player_vitals(session, hp=30.0, mp=100.0),
    )
    scenarios["near_death_health"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "near-death-health",
        prepare=lambda: set_player_vitals(session, hp=5.0, mp=100.0),
    )
    scenarios["magic_shield_health"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "magic-shield-health",
        prepare=lambda: {
            "vitals": set_player_vitals(session, hp=30.0, mp=100.0),
            "shield": set_magic_shield(session, current=25.0, maximum=50.0),
        },
    )
    scenarios["magic_shield_below_health_fill"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "magic-shield-below-health-fill",
        prepare=lambda: {
            "vitals": set_player_vitals(session, hp=30.0, mp=100.0),
            "shield": set_magic_shield(session, current=10.0, maximum=50.0),
        },
    )
    scenarios["mana_drain_and_refill"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "mana-drain-refill",
        prepare=lambda: {
            "vitals": set_player_vitals(session, hp=50.0, mp=100.0),
            "drain": begin_mana_refill(session),
        },
    )
    scenarios["mana_reserve_overlay"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "mana-reserve-overlay",
        prepare=lambda: {
            "vitals": set_player_vitals(session, hp=50.0, mp=100.0),
            "reserve": set_mana_reserve(session, current=50.0),
        },
    )
    scenarios["earth_charge_hold"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "earth-charge-hold",
        prepare=lambda: {
            "vitals": set_player_vitals(session, hp=50.0, mp=100.0),
            "cooldown": set_primary_cooldown(session, skill_entry, fraction=0.0),
            "wave": start_wave_counter(session),
            "charge": arm_earth_charge(session),
        },
        observe_after_capture=lambda: read_earth_charge_samples(session),
    )
    scenarios["active_cooldown"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "active-cooldown",
        prepare=lambda: set_primary_cooldown(session, skill_entry),
    )
    ally = ensure_hud_ally(session)
    scenarios["two_participant_ally_bar"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "two-participant-ally-bar",
        prepare=lambda: set_primary_cooldown(
            session, skill_entry, fraction=1.0
        ),
    )
    representative_ally_rows = scenarios["two_participant_ally_bar"][
        "independent_captures"
    ][0]["representative"]["ally_bars"]
    require(
        len(representative_ally_rows) == 1,
        f"two-participant HUD did not produce exactly one ally bar: {representative_ally_rows}",
    )

    wave = start_wave_counter(session)
    scenarios["wave_and_score"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "wave-and-score",
        prepare=lambda: set_primary_cooldown(
            session, skill_entry, fraction=1.0
        ),
    )

    scenarios["damage_x4_buff"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "damage-x4-buff",
        prepare=lambda: {
            "cooldown": set_primary_cooldown(
                session, skill_entry, fraction=1.0
            ),
            "buff": trigger_damage_x4(session),
        },
    )

    scenarios["partial_xp_progress"] = capture_scenario(
        session,
        raw_directory,
        crop_root,
        "partial-xp-progress",
        prepare=lambda: {
            "cooldown": set_primary_cooldown(
                session, skill_entry, fraction=1.0
            ),
            "xp": gain_partial_experience(session),
        },
        prepare_each_capture=False,
    )

    level_up = trigger_native_level_up(session)
    scenarios["level_up"] = {
        "kind": "fixed_tick_state_transition",
        "screen_capture": "excluded_g11_owned_unsettled_overlay",
        "screen_contract": "docs/reverse-engineering/native-menus-and-boot.md",
        "transition": level_up,
    }

    for scenario in scenarios.values():
        if scenario.get("screenshot") is not None:
            finalize_screenshot_provenance(scenario)

    element_census = build_element_census(scenarios)
    behavior_contract = build_behavior_contract(scenarios)
    visibility_contract = build_visibility_contract(scenarios)
    scaling_contract = build_scaling_contract(element_census)
    reference_crops = create_reference_crops(
        crop_root,
        scenarios,
        element_census,
    )

    return {
        "scenario_order": list(scenarios),
        "primary_skill_entry_index": skill_entry,
        "ally_setup": ally,
        "wave_setup": wave,
        "level_up_setup": level_up,
        "element_census": element_census,
        "behavior_contract": behavior_contract,
        "visibility_contract": visibility_contract,
        "scaling_contract": scaling_contract,
        "reference_crops": reference_crops,
        "scenarios": scenarios,
    }


def run_smoke(
    session: OwnedSoloSession,
    raw_directory: Path,
    crop_root: Path,
) -> dict[str, Any]:
    frames = queue_capture_sequence(session, raw_directory, "hud-smoke", 1)
    crop_root.mkdir(parents=True, exist_ok=True)
    backbuffer = capture_game_backbuffer(
        session.pipe_name,
        crop_root / "hud-smoke.png",
    )
    frame = frames[0]
    require(frame.get("hud_state") is not None, "smoke frame omitted HUD state")
    require(frame.get("draws"), "smoke frame omitted HUD draws")
    return {
        "draw_count": len(frame["draws"]),
        "text_count": len(frame.get("exact_text", [])),
        "slot_count": len(frame["hud_state"].get("slots", [])),
        "hud_state": frame["hud_state"],
        "backbuffer": backbuffer,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
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

    run_stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    raw_directory = DEFAULT_RAW_ROOT / run_stamp
    crop_root = DEFAULT_CROP_ROOT / run_stamp
    raw_directory.mkdir(parents=True, exist_ok=False)
    configure_capture_environment(raw_directory)

    session = OwnedSoloSession(
        instance=INSTANCE,
        ports=PORTS,
        mod_id=MOD_ID,
        participant_id=PARTICIPANT_ID,
        test_blank_boneyard=False,
        headless=False,
        quick_start_element="earth",
        quick_start_discipline="mind",
    )
    launch: dict[str, Any] | None = None
    cleanup: list[dict[str, Any]] = []
    document: dict[str, Any] | None = None
    try:
        launch = session.launch()
        session.wait_for_pipe()
        session.wait_for_scene("hub")
        hub_roster = configure_two_participant_hub_roster(session)
        stock_match = start_stock_match(session)
        run_presented = wait_for_run_presentation(session)
        arena_guard = stabilize_observation_arena(session)
        if args.smoke:
            result = run_smoke(session, raw_directory, crop_root)
            document = {
                "header": provenance_header(source, launch),
                "stock_match": stock_match,
                "hub_roster": hub_roster,
                "run_presented": run_presented,
                "observation_arena_guard": arena_guard,
                "smoke": result,
            }
        else:
            document = {
                "header": provenance_header(source, launch),
                "stock_match": stock_match,
                "hub_roster": hub_roster,
                "run_presented": run_presented,
                "observation_arena_guard": arena_guard,
                **record_full_session(
                    session,
                    raw_directory,
                    crop_root,
                ),
            }
    finally:
        cleanup = session.close()
        if launch is not None:
            require(
                any(
                    int(item.get("processId", 0)) == int(launch["processId"])
                    for item in cleanup
                ),
                f"owned HUD process cleanup omitted PID {launch['processId']}: {cleanup}",
            )

    require(document is not None, "HUD recorder completed without a document")
    document["header"]["cleanup"] = cleanup
    document["header"]["raw_capture_directory"] = str(raw_directory)
    document["header"]["reference_crop_directory"] = str(crop_root)
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.smoke:
        print(encoded, end="")
    else:
        DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_OUTPUT.write_text(encoded, encoding="utf-8")
        print(str(DEFAULT_OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
