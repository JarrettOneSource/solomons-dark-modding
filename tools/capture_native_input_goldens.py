#!/usr/bin/env python3
"""Record native input traces and mechanically encode browser Intent goldens.

This tool is intentionally live-only. It arms the bounded loader recorder,
drives the exact staged process through its retail Win32 window procedure,
retains the recorder's raw records verbatim, and proves the native_source round
trip before writing a fixture. It never synthesizes or edits a trace event.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
LUA_EXEC = ROOT / "tools" / "lua-exec.py"
REAL_INPUT = ROOT / "runtime" / "tools" / "win32_real_input.exe"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "webgame" / "input-goldens.json"

FORMAT = "sd-webgame-input-goldens-v1"
SCHEMA_VERSION = "1.0.0"
EARTH_SKILL_ID = 40
FROST_SKILL_ID = 32
CAPTURE_HP = 5000.0

ORDER = {
    "click_open_ground_native_absence": 0,
    "click_wall_native_absence": 1,
    "tap_cast": 2,
    "earth_charge_120ms": 3,
    "earth_charge_600ms": 4,
    "earth_charge_1500ms": 5,
    "frost_channel_start_stop": 6,
    "hud_click_swallowed": 7,
}


class CaptureFailure(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise CaptureFailure(
            f"command failed ({completed.returncode}): {command!r}: {detail}"
        )
    return completed


class LiveSession:
    def __init__(
        self,
        *,
        instance: str,
        process_id: int,
        executable_path: Path,
        real_input_path: Path,
    ) -> None:
        self.instance = instance
        self.process_id = process_id
        self.executable_path = executable_path.resolve()
        self.real_input_path = real_input_path.resolve()
        self.environment = os.environ.copy()
        self.environment["SDMOD_LUA_EXEC_PIPE_NAME"] = (
            f"SolomonDarkModLoader_LuaExec_{instance}"
        )

    def lua(self, code: str, *, timeout: float = 35.0) -> str:
        deadline = time.time() + timeout
        last_error = ""
        while time.time() < deadline:
            completed = subprocess.run(
                [sys.executable, str(LUA_EXEC), code],
                cwd=ROOT,
                env=self.environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15.0,
                check=False,
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            if completed.returncode == 0:
                return output.strip()
            last_error = output.strip()
            if (
                "Lua engine is busy" not in output
                and "Cannot connect to pipe" not in output
                and "No loaded Lua mod state" not in output
            ):
                raise CaptureFailure(last_error or "lua-exec failed")
            time.sleep(0.2)
        raise CaptureFailure(
            f"timed out waiting for {self.instance} Lua exec: {last_error}"
        )

    def wait_ready(self, timeout: float = 90.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if "inputre_ready=true" in self.lua(
                    "print('inputre_ready=true')", timeout=5.0
                ):
                    return
            except CaptureFailure:
                pass
            time.sleep(0.25)
        raise CaptureFailure(f"{self.instance}: Lua exec never became ready")

    def enter_solo_run(self) -> None:
        # The stock-routed hub seam queues the same native transition as the UI.
        deadline = time.time() + 45.0
        queued = False
        last = ""
        while time.time() < deadline:
            if not queued:
                output = self.lua(
                    "local s=sd.world and sd.world.get_scene "
                    "and sd.world.get_scene(); "
                    "local queued=false; "
                    "if type(s)=='table' and s.kind=='hub' then "
                    "local ok,value=pcall(sd.hub.start_match); "
                    "queued=ok and value==true; end; "
                    "print('kind=' .. tostring(type(s)=='table' and s.kind) "
                    ".. ';queued=' .. tostring(queued))"
                )
                queued = "queued=true" in output
            output = self.lua(
                "local p=sd.player and sd.player.get_state and sd.player.get_state(); "
                "local c=sd.camera and sd.camera.get_state and sd.camera.get_state(); "
                "local s=sd.world and sd.world.get_scene and sd.world.get_scene(); "
                "print('live=' .. tostring(type(p)=='table' "
                "and (tonumber(p.actor_address) or 0) > 0 "
                "and type(c)=='table' and c.scene_available==true "
                "and type(s)=='table' and s.kind=='arena'))"
            )
            if "live=true" in output:
                self.ensure_combat_started()
                return
            last = output
            time.sleep(0.25)
        raise CaptureFailure(
            f"{self.instance}: stock solo run did not materialize: {last}"
        )

    def stabilize_vitals(self) -> None:
        output = self.lua(
            f"""
local p = assert(sd.player.get_state(), 'player unavailable')
local progression = tonumber(p.progression_address) or 0
if progression == 0 then
  progression = tonumber(sd.debug.read_ptr(
    p.actor_address + sd.debug.layout_offset('actor_progression_runtime_state'))) or 0
end
assert(progression ~= 0, 'player progression unavailable')
local hp = sd.debug.layout_offset('progression_hp')
local max_hp = sd.debug.layout_offset('progression_max_hp')
assert(sd.debug.write_float(progression + max_hp, {CAPTURE_HP}))
assert(sd.debug.write_float(progression + hp, {CAPTURE_HP}))
print('vitals_stable=true')
""".strip()
        )
        if "vitals_stable=true" not in output:
            raise CaptureFailure(
                f"{self.instance}: could not stabilize vitals: {output}"
            )

    def combat_state(self) -> dict[str, int | bool]:
        output = self.lua(
            """
local state = sd.gameplay.get_combat_state()
local slot = sd.debug.resolve_game_address(0x0081C264)
local gameplay = tonumber(sd.debug.read_u32(slot)) or 0
local gate = gameplay ~= 0
  and tonumber(sd.debug.read_u8(gameplay + 0x1ABE)) or -1
print('combat_active=' .. tostring(state and state.combat_active == true))
print('music_started=' .. tostring(state and state.music_started == true))
print('wave_index=' .. tostring(state and state.wave_index or 0))
print('cast_gate=' .. tostring(gate))
""".strip()
        )
        values: dict[str, int | bool] = {}
        for line in output.splitlines():
            if "=" not in line:
                continue
            key, raw = line.strip().split("=", 1)
            if raw in {"true", "false"}:
                values[key] = raw == "true"
            else:
                try:
                    values[key] = int(float(raw))
                except ValueError:
                    continue
        return values

    def ensure_combat_started(self) -> None:
        self.stabilize_vitals()
        before = self.combat_state()
        if before.get("cast_gate") == 0 and (
            before.get("combat_active") is True
            or before.get("music_started") is True
            or int(before.get("wave_index", 0)) > 0
        ):
            return
        output = self.lua(
            "print('start_waves=' .. tostring(sd.gameplay.start_waves()))"
        )
        if "start_waves=true" not in output:
            raise CaptureFailure(f"{self.instance}: start_waves failed: {output}")
        deadline = time.time() + 12.0
        last = before
        while time.time() < deadline:
            self.stabilize_vitals()
            last = self.combat_state()
            if last.get("cast_gate") == 0 and (
                last.get("combat_active") is True
                or last.get("music_started") is True
                or int(last.get("wave_index", 0)) > 0
            ):
                return
            time.sleep(0.1)
        raise CaptureFailure(
            f"{self.instance}: combat did not open the stock cast gate: {last}"
        )

    def query_context(self) -> dict[str, float | int | bool]:
        code = r"""
local function emit(key, value)
  print(key .. '=' .. tostring(value))
end
local p = assert(sd.player.get_state(), 'player unavailable')
local c = assert(sd.camera.get_state(), 'camera unavailable')
emit('player_x', p.x)
emit('player_y', p.y)
emit('actor_address', p.actor_address)
emit('camera_origin_x', c.origin_x)
emit('camera_origin_y', c.origin_y)
emit('camera_width', c.width)
emit('camera_height', c.height)
emit('camera_scale', c.scale)
local globals = {
  menu = 0x00B3BCCC,
  inventory = 0x00B3BCC4,
  skills = 0x00B3BCC8,
  belt_1 = 0x00B3BCD0,
  belt_2 = 0x00B3BCD4,
  belt_3 = 0x00B3BCD8,
  belt_4 = 0x00B3BCDC,
  belt_5 = 0x00B3BCE0,
  belt_6 = 0x00B3BCE4,
  belt_7 = 0x00B3BCE8,
  belt_8 = 0x00B3BCEC,
  secondary_at_mouse = 0x00B3BCF4,
}
for name, address in pairs(globals) do
  local resolved = sd.debug.resolve_game_address(address)
  emit('binding_' .. name, sd.debug.read_u32(resolved))
end
""".strip()
        values: dict[str, float | int | bool] = {}
        for line in self.lua(code).splitlines():
            if "=" not in line:
                continue
            key, raw = line.strip().split("=", 1)
            if raw == "true":
                values[key] = True
            elif raw == "false":
                values[key] = False
            else:
                try:
                    number = float(raw)
                except ValueError:
                    continue
                values[key] = int(number) if number.is_integer() else number
        required = {
            "player_x",
            "player_y",
            "actor_address",
            "camera_origin_x",
            "camera_origin_y",
            "camera_width",
            "camera_height",
            "camera_scale",
        }
        missing = sorted(required - values.keys())
        if missing:
            raise CaptureFailure(f"live context omitted {missing}: {values}")
        return values

    def classify_nav_candidates(
        self,
        context: dict[str, float | int | bool],
    ) -> tuple[dict[str, float], dict[str, float]]:
        candidates = [
            (0.50, 0.18),
            (0.18, 0.56),
            (0.82, 0.56),
            (0.30, 0.70),
            (0.70, 0.70),
            (0.18, 0.18),
            (0.82, 0.18),
            (0.18, 0.36),
            (0.82, 0.36),
        ]
        origin_x = float(context["camera_origin_x"])
        origin_y = float(context["camera_origin_y"])
        width = float(context["camera_width"])
        height = float(context["camera_height"])
        scale = float(context["camera_scale"])
        player_x = float(context["player_x"])
        player_y = float(context["player_y"])
        if not math.isfinite(scale) or abs(scale) < 0.0001:
            raise CaptureFailure(f"invalid live camera scale: {scale}")

        records: list[dict[str, float]] = []
        for fraction_x, fraction_y in candidates:
            records.append(
                {
                    "fraction_x": fraction_x,
                    "fraction_y": fraction_y,
                    "world_x": origin_x + fraction_x * width / scale,
                    "world_y": origin_y + fraction_y * height / scale,
                }
            )
        lines = [
            "local function emit(k,v) print(k .. '=' .. tostring(v)) end"
        ]
        for index, record in enumerate(records):
            lines.append(
                "emit('candidate_%d', sd.nav.test_segment(%.9g, %.9g, %.9g, %.9g))"
                % (
                    index,
                    player_x,
                    player_y,
                    record["world_x"],
                    record["world_y"],
                )
            )
        classification: dict[int, bool] = {}
        for line in self.lua("\n".join(lines)).splitlines():
            if not line.startswith("candidate_") or "=" not in line:
                continue
            key, raw = line.split("=", 1)
            classification[int(key.removeprefix("candidate_"))] = raw == "true"
        open_point = next(
            (record for index, record in enumerate(records) if classification.get(index)),
            None,
        )
        wall_point = next(
            (
                record
                for index, record in enumerate(records)
                if classification.get(index) is False
            ),
            None,
        )
        if open_point is None or wall_point is None:
            raise CaptureFailure(
                "live nav classification did not find both an open and blocked "
                f"screen target: {classification}"
            )
        return open_point, wall_point

    def start_trace(self, label: str) -> None:
        escaped = label.replace("\\", "\\\\").replace("'", "\\'")
        output = self.lua(
            f"return sd.debug.start_native_input_trace('{escaped}')"
        )
        if "true" not in output:
            raise CaptureFailure(f"failed to arm trace {label}: {output}")

    def stop_trace(self) -> dict[str, Any]:
        output = self.lua("return sd.debug.stop_native_input_trace()")
        start = output.find('{"format":"sd-native-input-trace-v1"')
        if start < 0:
            raise CaptureFailure(f"native trace JSON missing from response: {output[-500:]}")
        try:
            trace = json.loads(output[start:])
        except json.JSONDecodeError as exc:
            raise CaptureFailure(
                f"invalid native trace JSON at {exc.pos}: {output[-500:]}"
            ) from exc
        if trace.get("dropped_events") != 0:
            raise CaptureFailure(
                f"native trace overflowed its bound: {trace.get('dropped_events')}"
            )
        return trace

    def click(self, fraction_x: float, fraction_y: float, hold_ms: int) -> dict[str, Any]:
        completed = run_command(
            [
                str(self.real_input_path),
                "message-click",
                str(self.process_id),
                str(self.executable_path),
                f"{fraction_x:.9g}",
                f"{fraction_y:.9g}",
                str(hold_ms),
            ],
            timeout=max(20.0, hold_ms / 1000.0 + 10.0),
        )
        try:
            return json.loads(completed.stdout.strip())
        except json.JSONDecodeError as exc:
            raise CaptureFailure(
                f"real-input helper returned invalid JSON: {completed.stdout!r}"
            ) from exc

    def record_click(
        self,
        *,
        label: str,
        fraction_x: float,
        fraction_y: float,
        hold_ms: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.start_trace(label)
        try:
            helper = self.click(fraction_x, fraction_y, hold_ms)
            time.sleep(0.30)
        finally:
            trace = self.stop_trace()
        return trace, helper


def actor_is_casting(event: dict[str, Any]) -> bool:
    spell = event.get("active_spell") or {}
    return bool(
        event.get("cast_active")
        or int(event.get("primary_skill_id", 0)) != 0
        or spell.get("readable")
    )


def find_click_edges(
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    down = next(
        (event for event in events if event.get("message_name") == "WM_LBUTTONDOWN"),
        None,
    )
    up = next(
        (
            event
            for event in events
            if event.get("message_name") == "WM_LBUTTONUP"
            and down is not None
            and int(event["sequence"]) > int(down["sequence"])
        ),
        None,
    )
    if down is None or up is None:
        raise CaptureFailure("trace omitted a physical left-button down/up pair")
    moves = [
        event
        for event in events
        if event.get("message_name") == "WM_MOUSEMOVE"
        and int(event["sequence"]) < int(down["sequence"])
    ]
    return (moves[-1] if moves else None), down, up


def aim_point_from_trace(
    events: Iterable[dict[str, Any]],
) -> dict[str, float]:
    for event in events:
        cursor = event.get("cursor_world") or {}
        if cursor.get("readable"):
            return {"x": float(cursor["x"]), "y": float(cursor["y"])}
    raise CaptureFailure("trace did not expose a readable native cursor world point")


def intent_record(
    sequence: int,
    raw: dict[str, Any],
    intent: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "tick": int(raw.get("simulation_tick", 0)),
        "intent": intent,
        "native_source": {
            "kind": str(raw["kind"]),
            "raw": raw,
        },
    }


def encode_click_trace(
    trace: dict[str, Any],
    *,
    expected_route: str,
    interact_target: str = "hud",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    events = list(trace.get("events") or [])
    move, down, up = find_click_edges(events)
    actor_events = [event for event in events if event.get("kind") == "actor_tick"]
    active_actor_events = [
        event
        for event in actor_events
        if int(down["sequence"]) < int(event["sequence"]) < int(up["sequence"])
        and actor_is_casting(event)
    ]
    route = "world_cast" if active_actor_events else "hud_interaction"
    if route != expected_route:
        raise CaptureFailure(
            f"expected {expected_route}, observed {route}; "
            f"active_ticks={len(active_actor_events)}"
        )

    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if route == "world_cast":
        aim_point = aim_point_from_trace(
            event
            for event in events
            if int(event["sequence"]) >= int(down["sequence"])
        )
        if move is not None:
            selected.append((move, {"kind": "aim", "point": aim_point}))
        selected.append(
            (
                down,
                {"kind": "cast", "slot": "primary", "phase": "press"},
            )
        )
        for event in active_actor_events:
            selected.append(
                (
                    event,
                    {"kind": "cast", "slot": "primary", "phase": "hold"},
                )
            )
        selected.append(
            (
                up,
                {"kind": "cast", "slot": "primary", "phase": "release"},
            )
        )
    else:
        selected.append(
            (
                down,
                {
                    "kind": "interact",
                    "target": interact_target,
                    "phase": "press",
                },
            )
        )
        selected.append(
            (
                up,
                {
                    "kind": "interact",
                    "target": interact_target,
                    "phase": "release",
                },
            )
        )
    selected.sort(key=lambda item: int(item[0]["sequence"]))
    raw_timeline = [raw for raw, _ in selected]
    intents = [
        intent_record(index, raw, intent)
        for index, (raw, intent) in enumerate(selected)
    ]

    positions = [
        event.get("player")
        for event in actor_events
        if event.get("actor_readable") and isinstance(event.get("player"), dict)
    ]
    position_delta = 0.0
    if len(positions) >= 2:
        position_delta = math.hypot(
            float(positions[-1]["x"]) - float(positions[0]["x"]),
            float(positions[-1]["y"]) - float(positions[0]["y"]),
        )
    transient_skill_ids = sorted(
        {
            int(event.get("primary_skill_id", 0))
            for event in active_actor_events
            if int(event.get("primary_skill_id", 0)) != 0
        }
    )
    selected_skill_ids = sorted(
        {
            int((event.get("selected_primary_skill") or {}).get("skill_id", 0))
            for event in active_actor_events
            if (event.get("selected_primary_skill") or {}).get("readable")
        }
    )
    spell_samples = [
        event["active_spell"]
        for event in active_actor_events
        if (event.get("active_spell") or {}).get("readable")
    ]
    observations = {
        "surface_route": route,
        "world_move_intent_count": sum(
            1 for record in intents if record["intent"]["kind"] == "move"
        ),
        "native_actor_position_delta": position_delta,
        "active_actor_tick_count": len(active_actor_events),
        "primary_skill_ids": transient_skill_ids,
        "selected_primary_skill_ids": selected_skill_ids,
        "active_spell_samples": spell_samples,
        "release_observed": any(
            int(event["sequence"]) > int(up["sequence"])
            and not actor_is_casting(event)
            for event in actor_events
        ),
    }
    return raw_timeline, intents, observations


def build_capture(
    *,
    scenario: str,
    instance: str,
    source_sha: str,
    executable_sha256: str,
    trace: dict[str, Any],
    helper: dict[str, Any],
    target: dict[str, float],
    context: dict[str, float | int | bool],
    expected_route: str,
    interact_target: str = "hud",
) -> dict[str, Any]:
    raw_timeline, intent_timeline, observations = encode_click_trace(
        trace,
        expected_route=expected_route,
        interact_target=interact_target,
    )
    reconstructed = [
        record["native_source"]["raw"] for record in intent_timeline
    ]
    raw_hash = sha256_bytes(canonical_bytes(raw_timeline))
    reconstructed_hash = sha256_bytes(canonical_bytes(reconstructed))
    exact_equal = reconstructed == raw_timeline
    if not exact_equal or raw_hash != reconstructed_hash:
        raise CaptureFailure(f"{scenario}: raw -> Intent -> raw was not lossless")
    return {
        "header": {
            "scenario": scenario,
            "instance": instance,
            "source_sha": source_sha,
            "executable_sha256": executable_sha256,
            "captured_utc": dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "capture_method": (
                "exact-PID/path win32_real_input SendMessageTimeoutW WM_MOUSE* "
                "-> retail GameWindowProc "
                "observer -> native Input double-buffer sample -> local "
                "PlayerActor post-stock sample; recorder JSON mechanically "
                "encoded by tools/capture_native_input_goldens.py"
            ),
            "trace_sha256": sha256_bytes(canonical_bytes(trace)),
            "round_trip": {
                "method": "native_source.raw verbatim reconstruction in sequence order",
                "raw_sha256": raw_hash,
                "reconstructed_sha256": reconstructed_hash,
                "exact_equal": exact_equal,
            },
        },
        "target": target,
        "real_input_result": helper,
        "live_context": context,
        "raw_timeline": raw_timeline,
        "intent_timeline": intent_timeline,
        "observations": observations,
    }


def persist_raw_trace(
    evidence_directory: Path,
    scenario: str,
    trace: dict[str, Any],
) -> None:
    raw_directory = evidence_directory / "raw-traces"
    raw_directory.mkdir(parents=True, exist_ok=True)
    path = raw_directory / f"{scenario}.json"
    path.write_text(
        json.dumps(trace, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def capture_profile(
    session: LiveSession,
    *,
    profile: str,
    source_sha: str,
    evidence_directory: Path,
) -> list[dict[str, Any]]:
    session.wait_ready()
    session.enter_solo_run()
    session.stabilize_vitals()
    context = session.query_context()
    executable_sha = sha256_file(session.executable_path)
    captures: list[dict[str, Any]] = []

    if profile == "earth":
        open_point, wall_point = session.classify_nav_candidates(context)
        scenarios: list[tuple[str, dict[str, float], int, str, str]] = [
            (
                "click_open_ground_native_absence",
                open_point,
                45,
                "world_cast",
                "world",
            ),
            (
                "click_wall_native_absence",
                wall_point,
                45,
                "world_cast",
                "world",
            ),
            ("tap_cast", open_point, 45, "world_cast", "world"),
            ("earth_charge_120ms", open_point, 120, "world_cast", "world"),
            ("earth_charge_600ms", open_point, 600, "world_cast", "world"),
            ("earth_charge_1500ms", open_point, 1500, "world_cast", "world"),
        ]
        for scenario, target, hold_ms, route, interact_target in scenarios:
            session.stabilize_vitals()
            trace, helper = session.record_click(
                label=scenario,
                fraction_x=target["fraction_x"],
                fraction_y=target["fraction_y"],
                hold_ms=hold_ms,
            )
            persist_raw_trace(evidence_directory, scenario, trace)
            capture = build_capture(
                scenario=scenario,
                instance=session.instance,
                source_sha=source_sha,
                executable_sha256=executable_sha,
                trace=trace,
                helper=helper,
                target=target,
                context=context,
                expected_route=route,
                interact_target=interact_target,
            )
            if scenario.startswith("earth_charge_"):
                observed_skills = capture["observations"][
                    "selected_primary_skill_ids"
                ]
                spell_samples = capture["observations"]["active_spell_samples"]
                if EARTH_SKILL_ID not in observed_skills or not spell_samples:
                    raise CaptureFailure(
                        f"{scenario}: live trace did not capture native Earth "
                        f"skill/object state: skills={observed_skills} "
                        f"spell_samples={len(spell_samples)}"
                    )
            captures.append(capture)
            time.sleep(0.8)

        hud_candidates = [
            {"fraction_x": x, "fraction_y": y, "world_x": 0.0, "world_y": 0.0}
            for y in (0.94, 0.89)
            for x in (0.50, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74)
        ]
        last_error = ""
        for target in hud_candidates:
            session.stabilize_vitals()
            trace, helper = session.record_click(
                label="hud_click_swallowed",
                fraction_x=target["fraction_x"],
                fraction_y=target["fraction_y"],
                hold_ms=45,
            )
            try:
                capture = build_capture(
                    scenario="hud_click_swallowed",
                    instance=session.instance,
                    source_sha=source_sha,
                    executable_sha256=executable_sha,
                    trace=trace,
                    helper=helper,
                    target=target,
                    context=context,
                    expected_route="hud_interaction",
                    interact_target="hud.belt",
                )
            except CaptureFailure as exc:
                last_error = str(exc)
                time.sleep(0.25)
                continue
            persist_raw_trace(
                evidence_directory,
                "hud_click_swallowed",
                trace,
            )
            captures.append(capture)
            break
        else:
            raise CaptureFailure(
                f"no tested HUD coordinate swallowed the click: {last_error}"
            )
    elif profile == "water":
        open_point, _ = session.classify_nav_candidates(context)
        scenario = "frost_channel_start_stop"
        trace, helper = session.record_click(
            label=scenario,
            fraction_x=open_point["fraction_x"],
            fraction_y=open_point["fraction_y"],
            hold_ms=750,
        )
        persist_raw_trace(evidence_directory, scenario, trace)
        capture = build_capture(
            scenario=scenario,
            instance=session.instance,
            source_sha=source_sha,
            executable_sha256=executable_sha,
            trace=trace,
            helper=helper,
            target=open_point,
            context=context,
            expected_route="world_cast",
        )
        observed_skills = capture["observations"]["selected_primary_skill_ids"]
        if FROST_SKILL_ID not in observed_skills:
            raise CaptureFailure(
                f"Frost trace did not observe skill {FROST_SKILL_ID}: "
                f"{observed_skills}"
            )
        captures.append(capture)
    else:
        raise CaptureFailure(f"unsupported capture profile: {profile}")

    return captures


def write_fixture(
    fixture_path: Path,
    captures: list[dict[str, Any]],
) -> None:
    if fixture_path.exists():
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        if fixture.get("format") != FORMAT:
            raise CaptureFailure(
                f"refusing to merge unknown fixture format: {fixture.get('format')}"
            )
    else:
        fixture = {
            "format": FORMAT,
            "intent_schema": "../../../webgame-contracts/intent-schema.json",
            "generated_by": "tools/capture_native_input_goldens.py",
            "captures": [],
        }
    replacements = {
        capture["header"]["scenario"]: capture for capture in captures
    }
    retained = [
        capture
        for capture in fixture.get("captures", [])
        if capture.get("header", {}).get("scenario") not in replacements
    ]
    retained.extend(replacements.values())
    retained.sort(
        key=lambda capture: ORDER.get(
            capture.get("header", {}).get("scenario", ""),
            999,
        )
    )
    fixture["captures"] = retained
    fixture["source_shas"] = sorted(
        {
            capture["header"]["source_sha"]
            for capture in retained
        }
    )
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True)
    parser.add_argument("--process-id", required=True, type=int)
    parser.add_argument("--executable-path", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--profile", choices=("earth", "water"), required=True)
    parser.add_argument("--real-input-path", type=Path, default=REAL_INPUT)
    parser.add_argument("--fixture-path", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.process_id <= 0:
        raise CaptureFailure("process id must be positive")
    if not args.executable_path.is_file():
        raise CaptureFailure(
            f"exact staged executable is missing: {args.executable_path}"
        )
    if not args.real_input_path.is_file():
        raise CaptureFailure(
            f"real-input helper is missing: {args.real_input_path}"
        )
    if len(args.source_sha) != 40 or any(
        character not in "0123456789abcdef" for character in args.source_sha.lower()
    ):
        raise CaptureFailure("source SHA must be a full 40-character Git SHA")

    session = LiveSession(
        instance=args.instance,
        process_id=args.process_id,
        executable_path=args.executable_path,
        real_input_path=args.real_input_path,
    )
    captures = capture_profile(
        session,
        profile=args.profile,
        source_sha=args.source_sha.lower(),
        evidence_directory=args.evidence_directory.resolve(),
    )
    write_fixture(args.fixture_path.resolve(), captures)
    print(
        json.dumps(
            {
                "success": True,
                "instance": args.instance,
                "profile": args.profile,
                "capture_count": len(captures),
                "fixture_path": str(args.fixture_path.resolve()),
                "scenarios": [capture["header"]["scenario"] for capture in captures],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CaptureFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
