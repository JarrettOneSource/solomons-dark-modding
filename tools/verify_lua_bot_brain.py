#!/usr/bin/env python3
"""Unattended wave-five acceptance for the synthetic-participant bot brain."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import multiplayer_frame_capture
import verify_local_multiplayer_sync as local_sync


ROOT = Path(__file__).resolve().parents[1]
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
EVIDENCE_ROOT = Path(
    "/mnt/d/codex-evidence/bot-players-20260726/phase3"
)
INSTANCE_PREFIX = "bot"
HOST_PORT = 48811
CLIENT_PORT = 48812
HOST_PIPE = "SolomonDarkModLoader_LuaExec_bot-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_bot-client"
EXACT_MOD_ID = "bot.brain"
BOT_NAME = "Ember"
DEFAULT_RUN_COUNT = 3
DEFAULT_RUN_TIMEOUT_SECONDS = 900.0
SAMPLE_INTERVAL_SECONDS = 1.0
TIMELINE_INTERVAL_SECONDS = 2.0
WAVE_FIVE_STABILITY_SECONDS = 2.0


class BotBrainAcceptanceFailure(RuntimeError):
    pass


def _number(
    values: dict[str, str],
    key: str,
    default: float = 0.0,
) -> float:
    try:
        return float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _integer(
    values: dict[str, str],
    key: str,
    default: int = 0,
) -> int:
    return int(_number(values, key, float(default)))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


PAIR_PROBE = """
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end

local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("authority", sd.state.is_authority())

local wave = sd.waves.get_state()
emit("wave.number", wave and wave.wave or 0)
emit("wave.phase", wave and wave.phase or "")
emit("wave.planned", wave and wave.planned or 0)
emit("wave.remaining", wave and wave.remaining_to_spawn or 0)
emit("wave.spawned", wave and wave.spawned or 0)
emit("wave.alive", wave and wave.alive or 0)
emit("wave.killed", wave and wave.killed or 0)

local bots = sd.bots.list() or {}
local bot = bots[1]
emit("bot.count", #bots)
emit("bot.found", bot ~= nil)
local participant_id = bot and tonumber(bot:participant_id()) or 0
emit("bot.participant_id", participant_id)
if bot ~= nil then
  local position_ok, x, y = pcall(function() return bot:position() end)
  local hp_ok, hp = pcall(function() return bot:hp() end)
  local max_hp_ok, max_hp = pcall(function() return bot:max_hp() end)
  local alive_ok, alive = pcall(function() return bot:alive() end)
  local slot_ok, slot = pcall(function() return bot:slot() end)
  emit("bot.position_ok", position_ok and x ~= nil and y ~= nil)
  emit("bot.x", x or 0)
  emit("bot.y", y or 0)
  emit("bot.hp_ok", hp_ok and hp ~= nil)
  emit("bot.hp", hp or 0)
  emit("bot.max_hp", max_hp_ok and max_hp or 0)
  emit("bot.alive", alive_ok and alive == true)
  emit("bot.slot", slot_ok and slot or -1)
end

local multiplayer = sd.runtime.get_multiplayer_state()
local local_participant_id = 0
local bot_member = nil
for _, participant in ipairs(multiplayer and multiplayer.participants or {}) do
  if participant.is_owner == true and
      tostring(participant.controller_kind or "") ~= "LuaBrain" then
    local_participant_id = tonumber(participant.participant_id) or 0
  end
  if tonumber(participant.participant_id) == participant_id then
    bot_member = participant
  end
end
emit("local.participant_id", local_participant_id)
emit("member.name", bot_member and bot_member.name or "")
emit("member.controller", bot_member and bot_member.controller_kind or "")
emit("member.in_run", bot_member and bot_member.in_run or false)
emit("member.level", bot_member and bot_member.level or 0)
emit("member.life", bot_member and bot_member.life_current or 0)
emit("member.max_life", bot_member and bot_member.life_max or 0)

local offer = multiplayer and multiplayer.active_level_up_offer or nil
emit("offer.valid", offer and offer.valid or false)
emit("offer.submitted", offer and offer.selection_submitted or false)
emit("offer.id", offer and offer.offer_id or 0)
emit("offer.target", offer and offer.target_participant_id or 0)
emit("offer.count", offer and offer.option_count or 0)
for index, option in ipairs(offer and offer.options or {}) do
  emit("offer.option." .. tostring(index), option.option_id or option.id or -1)
end

local snapshot = sd.world.get_replicated_actors()
local live_enemies = 0
local enemies_targeting_bot = 0
for _, actor in ipairs(snapshot and snapshot.actors or {}) do
  if actor.tracked_enemy == true and actor.dead ~= true and
      (tonumber(actor.hp) or 0) > 0.0 then
    live_enemies = live_enemies + 1
    if tonumber(actor.target_participant_id) == participant_id then
      enemies_targeting_bot = enemies_targeting_bot + 1
    end
  end
end
emit("world.live_enemies", live_enemies)
emit("world.enemies_targeting_bot", enemies_targeting_bot)

local debug_state = rawget(_G, "bot_brain_debug")
for _, key in ipairs({
  "authority",
  "active",
  "participant_id",
  "wave",
  "mode",
  "hp",
  "max_hp",
  "live_enemy_count",
  "threat_count",
  "target_network_actor_id",
  "target_distance",
  "think_count",
  "move_issued",
  "move_accepted",
  "movement_candidates_blocked",
  "cast_issued",
  "cast_accepted",
  "skill_choices_accepted",
  "kite_path_distance",
  "arena_grid_backed",
  "nearest_threat_distance",
  "edge_pressure",
  "destination_x",
  "destination_y",
  "last_error"
}) do
  emit("brain." .. key, type(debug_state) == "table" and debug_state[key] or "")
end
"""


def _query(pipe_name: str) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, PAIR_PROBE, timeout=10.0)
    )


def _wait(
    probe,
    predicate,
    *,
    timeout: float,
    label: str,
    interval: float = 0.25,
):
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = probe()
            last_error = ""
            if predicate(last):
                return last
        except (
            BotBrainAcceptanceFailure,
            local_sync.VerifyFailure,
            TimeoutError,
        ) as exc:
            last_error = str(exc)
        time.sleep(interval)
    detail = f" last={last!r}"
    if last_error:
        detail += f" error={last_error}"
    raise BotBrainAcceptanceFailure(f"{label} timed out.{detail}")


def _pair_bot_ready(
    views: dict[str, dict[str, str]],
    *,
    expected_scene: str,
) -> bool:
    host = views["host"]
    client = views["client"]
    participant_id = _integer(host, "bot.participant_id")
    return (
        host.get("scene") == expected_scene
        and client.get("scene") == expected_scene
        and host.get("authority") == "true"
        and client.get("authority") == "false"
        and _integer(host, "bot.count") == 1
        and _integer(client, "bot.count") == 1
        and participant_id > 0
        and _integer(client, "bot.participant_id") == participant_id
        and host.get("bot.position_ok") == "true"
        and client.get("bot.position_ok") == "true"
        and host.get("bot.hp_ok") == "true"
        and client.get("bot.hp_ok") == "true"
        and host.get("bot.alive") == "true"
        and client.get("bot.alive") == "true"
        and 1 <= _integer(host, "bot.slot", -1) <= 3
        and 1 <= _integer(client, "bot.slot", -1) <= 3
        and host.get("member.name") == BOT_NAME
        and client.get("member.name") == BOT_NAME
        and host.get("member.controller") == "LuaBrain"
        and client.get("member.controller") == "LuaBrain"
    )


def _start_testrun() -> None:
    last_error = ""
    for _ in range(60):
        try:
            local_sync.start_testrun(HOST_PIPE)
            return
        except local_sync.VerifyFailure as exc:
            last_error = str(exc)
            if "still settling" not in last_error:
                raise
            time.sleep(0.25)
    raise BotBrainAcceptanceFailure(
        f"host could not enter the test run: {last_error}"
    )


def _resolve_local_offer(
    pipe_name: str,
    values: dict[str, str],
    resolved: set[tuple[str, int]],
) -> dict[str, Any] | None:
    if (
        values.get("offer.valid") != "true"
        or values.get("offer.submitted") == "true"
    ):
        return None
    offer_id = _integer(values, "offer.id")
    option_count = _integer(values, "offer.count")
    local_participant_id = _integer(values, "local.participant_id")
    target_participant_id = _integer(values, "offer.target")
    key = (pipe_name, offer_id)
    if (
        offer_id <= 0
        or option_count <= 0
        or local_participant_id <= 0
        or target_participant_id != local_participant_id
        or key in resolved
    ):
        return None

    priority = (64, 16, 18, 17)
    option_ids = [
        _integer(values, f"offer.option.{index}", -1)
        for index in range(1, option_count + 1)
    ]
    option_index = 1
    for wanted in priority:
        if wanted in option_ids:
            option_index = option_ids.index(wanted) + 1
            break
    code = f"""
local ok, result = pcall(
  sd.runtime.choose_level_up_option,
  {{offer_id={offer_id}, option_index={option_index}}})
print("pcall_ok=" .. tostring(ok))
print("result=" .. tostring(result))
"""
    response = local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=7.5)
    )
    if (
        response.get("pcall_ok") != "true"
        or response.get("result") != "true"
    ):
        return {
            "offerId": offer_id,
            "targetParticipantId": target_participant_id,
            "optionIds": option_ids,
            "optionIndex": option_index,
            "accepted": False,
            "response": response,
        }
    resolved.add(key)
    return {
        "offerId": offer_id,
        "targetParticipantId": target_participant_id,
        "optionIds": option_ids,
        "optionIndex": option_index,
        "selectedOptionId": option_ids[option_index - 1],
        "accepted": True,
        "response": response,
    }


def _distance(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _compact_sample(
    elapsed_seconds: float,
    views: dict[str, dict[str, str]],
) -> dict[str, Any]:
    host = views["host"]
    client = views["client"]
    return {
        "elapsedSeconds": round(elapsed_seconds, 3),
        "wave": _integer(host, "wave.number"),
        "wavePhase": host.get("wave.phase", ""),
        "enemiesAlive": _integer(host, "world.live_enemies"),
        "enemiesTargetingBot": _integer(
            host,
            "world.enemies_targeting_bot",
        ),
        "bot": {
            "hp": _number(host, "bot.hp"),
            "maxHp": _number(host, "bot.max_hp"),
            "alive": host.get("bot.alive") == "true",
            "x": _number(host, "bot.x"),
            "y": _number(host, "bot.y"),
            "mode": host.get("brain.mode", ""),
        },
        "client": {
            "hp": _number(client, "bot.hp"),
            "alive": client.get("bot.alive") == "true",
            "x": _number(client, "bot.x"),
            "y": _number(client, "bot.y"),
        },
        "brain": {
            "castsIssued": _integer(host, "brain.cast_issued"),
            "castsAccepted": _integer(host, "brain.cast_accepted"),
            "movesAccepted": _integer(host, "brain.move_accepted"),
            "kitePathDistance": _number(
                host,
                "brain.kite_path_distance",
            ),
            "threatCount": _integer(host, "brain.threat_count"),
            "targetNetworkActorId": _integer(
                host,
                "brain.target_network_actor_id",
            ),
        },
    }


def _set_camera_focus(
    pipe_name: str,
    values: dict[str, str],
) -> dict[str, str]:
    x = _number(values, "bot.x", math.nan)
    y = _number(values, "bot.y", math.nan)
    if not math.isfinite(x) or not math.isfinite(y):
        raise BotBrainAcceptanceFailure(
            f"bot camera focus lacks a finite position on {pipe_name}"
        )
    response = local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            f"""
local ok, result = pcall(sd.camera.set_focus, {x:.9f}, {y:.9f})
print("pcall_ok=" .. tostring(ok))
print("result=" .. tostring(result))
""",
            timeout=7.5,
        )
    )
    if (
        response.get("pcall_ok") != "true"
        or response.get("result") != "true"
    ):
        raise BotBrainAcceptanceFailure(
            f"bot camera focus failed on {pipe_name}: {response}"
        )
    return response


def _clear_camera_focus(pipe_name: str) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            """
local ok, result = pcall(sd.camera.clear_focus)
print("pcall_ok=" .. tostring(ok))
print("result=" .. tostring(result))
""",
            timeout=7.5,
        )
    )


def _capture_bot_fight_views(
    output_directory: Path,
    views: dict[str, dict[str, str]],
    *,
    wave: int,
    elapsed_seconds: float,
) -> dict[str, Any]:
    focus: dict[str, dict[str, str]] = {}
    try:
        focus["host"] = _set_camera_focus(HOST_PIPE, views["host"])
        focus["client"] = _set_camera_focus(
            CLIENT_PIPE,
            views["client"],
        )
        time.sleep(0.35)
        host_capture = multiplayer_frame_capture.capture_game_backbuffer(
            HOST_PIPE,
            output_directory / "host-wave3-mid-fight.png",
        )
        client_capture = multiplayer_frame_capture.capture_game_backbuffer(
            CLIENT_PIPE,
            output_directory / "client-wave3-mid-fight.png",
        )
    finally:
        if "host" in focus:
            focus["hostClear"] = _clear_camera_focus(HOST_PIPE)
        if "client" in focus:
            focus["clientClear"] = _clear_camera_focus(CLIENT_PIPE)
    return {
        "wave": wave,
        "elapsedSeconds": round(elapsed_seconds, 3),
        "cameraFocus": focus,
        "host": host_capture,
        "client": client_capture,
    }


def _copy_runtime_evidence(
    output_directory: Path,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    for role in ("host", "client"):
        stage_path = (
            ROOT
            / "runtime"
            / "instances"
            / f"{INSTANCE_PREFIX}-{role}"
            / "stage"
        )
        for relative, label in (
            (
                Path(".sdmod/logs/solomondarkmodloader.log"),
                f"{role}-solomondarkmodloader.log",
            ),
            (
                Path(".sdmod/startup-status.json"),
                f"{role}-startup-status.json",
            ),
            (
                Path(".sdmod/multiplayer-session-status.json"),
                f"{role}-multiplayer-session-status.json",
            ),
        ):
            source = stage_path / relative
            if not source.is_file():
                continue
            destination = output_directory / label
            shutil.copy2(source, destination)
            copied[label] = str(destination)
    return copied


def _brain_log_summary(output_directory: Path) -> dict[str, Any]:
    log_path = output_directory / "host-solomondarkmodloader.log"
    if not log_path.is_file():
        return {"available": False}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    brain_lines = [
        line for line in text.splitlines() if "[bot-brain]" in line
    ]
    accepted_cast_lines = [
        line for line in brain_lines if "cast accepted count=" in line
    ]
    return {
        "available": True,
        "lineCount": len(brain_lines),
        "acceptedCastLineCount": len(accepted_cast_lines),
        "lastLines": brain_lines[-40:],
    }


def _monitor_run(
    output_directory: Path,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    started = time.monotonic()
    last_timeline_sample = -TIMELINE_INTERVAL_SECONDS
    last_sample_position: tuple[float, float] | None = None
    harness_kite_distance = 0.0
    highest_wave = 0
    timeline: list[dict[str, Any]] = []
    offer_choices: list[dict[str, Any]] = []
    resolved_offers: set[tuple[str, int]] = set()
    screenshots: dict[str, Any] | None = None
    wave_five_since: float | None = None
    last_views: dict[str, dict[str, str]] = {}
    consecutive_query_failures = 0
    previous_cast_accepted = 0

    while time.monotonic() - started < timeout_seconds:
        elapsed = time.monotonic() - started
        try:
            views = {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            }
            last_views = views
            consecutive_query_failures = 0
        except (local_sync.VerifyFailure, TimeoutError) as exc:
            consecutive_query_failures += 1
            if consecutive_query_failures >= 3:
                raise BotBrainAcceptanceFailure(
                    "pair stopped responding during autonomous run: "
                    f"{exc}"
                ) from exc
            time.sleep(SAMPLE_INTERVAL_SECONDS)
            continue

        for role, pipe_name in (
            ("host", HOST_PIPE),
            ("client", CLIENT_PIPE),
        ):
            choice = _resolve_local_offer(
                pipe_name,
                views[role],
                resolved_offers,
            )
            if choice is not None:
                choice["role"] = role
                choice["elapsedSeconds"] = round(elapsed, 3)
                offer_choices.append(choice)

        host = views["host"]
        client = views["client"]
        wave = _integer(host, "wave.number")
        cast_accepted = _integer(host, "brain.cast_accepted")
        cast_advanced = cast_accepted > previous_cast_accepted
        highest_wave = max(highest_wave, wave)
        host_position = (
            _number(host, "bot.x", math.nan),
            _number(host, "bot.y", math.nan),
        )
        if all(math.isfinite(value) for value in host_position):
            if last_sample_position is not None:
                step = _distance(last_sample_position, host_position)
                if step <= 350.0:
                    harness_kite_distance += step
            last_sample_position = host_position

        if elapsed - last_timeline_sample >= TIMELINE_INTERVAL_SECONDS:
            timeline.append(_compact_sample(elapsed, views))
            last_timeline_sample = elapsed

        host_hp = _number(host, "bot.hp")
        client_hp = _number(client, "bot.hp")
        if wave > 0 and (
            host_hp <= 0.0
            or client_hp <= 0.0
            or host.get("brain.mode") == "dead"
        ):
            return {
                "success": False,
                "completionReason": "bot_died",
                "highestWaveReached": highest_wave,
                "botAliveAtWaveFive": False,
                "death": {
                    "wave": wave,
                    "hostHp": host_hp,
                    "clientHp": client_hp,
                    "liveEnemies": _integer(
                        host,
                        "world.live_enemies",
                    ),
                    "enemiesTargetingBot": _integer(
                        host,
                        "world.enemies_targeting_bot",
                    ),
                    "cause": (
                        "native bot HP reached zero during stock wave "
                        "combat"
                    ),
                },
                "timeline": timeline,
                "offerChoices": offer_choices,
                "harnessKitePathDistance": harness_kite_distance,
                "lastViews": last_views,
            }

        if (
            screenshots is None
            and wave >= 3
            and _integer(host, "world.live_enemies") > 0
            and host.get("bot.alive") == "true"
            and client.get("bot.alive") == "true"
            and cast_advanced
            and _integer(
                host,
                "brain.target_network_actor_id",
            ) > 0
        ):
            screenshots = _capture_bot_fight_views(
                output_directory,
                views,
                wave=wave,
                elapsed_seconds=elapsed,
            )

        bot_alive_at_wave_five = (
            wave >= 5
            and host.get("bot.alive") == "true"
            and client.get("bot.alive") == "true"
            and host_hp > 0.0
            and client_hp > 0.0
        )
        if bot_alive_at_wave_five:
            if wave_five_since is None:
                wave_five_since = time.monotonic()
            elif (
                time.monotonic() - wave_five_since
                >= WAVE_FIVE_STABILITY_SECONDS
            ):
                timeline.append(_compact_sample(elapsed, views))
                return {
                    "success": screenshots is not None,
                    "completionReason": (
                        "wave_five_reached_alive"
                        if screenshots is not None
                        else "wave_five_without_combat_visual"
                    ),
                    "highestWaveReached": highest_wave,
                    "botAliveAtWaveFive": True,
                    "timeline": timeline,
                    "offerChoices": offer_choices,
                    "screenshots": screenshots,
                    "harnessKitePathDistance": harness_kite_distance,
                    "lastViews": last_views,
                }
        else:
            wave_five_since = None

        previous_cast_accepted = cast_accepted
        time.sleep(SAMPLE_INTERVAL_SECONDS)

    return {
        "success": False,
        "completionReason": "timeout",
        "highestWaveReached": highest_wave,
        "botAliveAtWaveFive": False,
        "timeline": timeline,
        "offerChoices": offer_choices,
        "screenshots": screenshots,
        "harnessKitePathDistance": harness_kite_distance,
        "lastViews": last_views,
    }


def verify_one_run(
    run_index: int,
    *,
    output_directory: Path,
    game_directory: Path,
    launcher_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    output_directory.mkdir(parents=True, exist_ok=True)
    launch: dict[str, object] = {}
    result: dict[str, Any] = {
        "runId": f"bot-wave5-{run_index}",
        "runIndex": run_index,
        "startedUtc": _utc_now(),
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "exactModId": EXACT_MOD_ID,
        "audioExpectedDisabled": True,
        "waveSchedule": "retail staged data/wave.txt; no test override",
    }
    failure: BaseException | None = None
    try:
        launch = local_sync.launch_pair(
            instance_prefix=INSTANCE_PREFIX,
            host_port=HOST_PORT,
            client_port=CLIENT_PORT,
            temporary_host_profile=True,
            kill_existing=False,
            god_mode=True,
            exact_mod_id=EXACT_MOD_ID,
            launcher_path=launcher_path,
            game_directory=game_directory,
            enable_audio=False,
        )
        result["launch"] = launch
        if (
            launch.get("audioDisabled") is not True
            or int(launch.get("hostPort", 0)) != HOST_PORT
            or int(launch.get("clientPort", 0)) != CLIENT_PORT
            or launch.get("testWaveOverride") not in ("", None)
        ):
            raise BotBrainAcceptanceFailure(
                f"isolated retail-wave pair contract failed: {launch}"
            )

        hub_views = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            lambda values: _pair_bot_ready(
                values,
                expected_scene="hub",
            ),
            timeout=25.0,
            label="bot brain participant in the shared hub",
        )
        result["hub"] = hub_views

        _start_testrun()
        local_sync.wait_for_scene(
            HOST_PIPE,
            "testrun",
            timeout=45.0,
        )
        local_sync.wait_for_scene(
            CLIENT_PIPE,
            "testrun",
            timeout=45.0,
        )
        run_views = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            lambda values: _pair_bot_ready(
                values,
                expected_scene="testrun",
            ),
            timeout=25.0,
            label="bot brain participant in the shared run",
        )
        result["runEntry"] = run_views

        start = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                """
print("prelude=" ..
  tostring(sd.gameplay.enable_combat_prelude()))
print("waves=" ..
  tostring(sd.gameplay.start_waves()))
""",
                timeout=10.0,
            )
        )
        if (
            start.get("prelude") != "true"
            or start.get("waves") != "true"
        ):
            raise BotBrainAcceptanceFailure(
                f"stock waves did not start: {start}"
            )
        result["waveStart"] = start

        monitored = _monitor_run(
            output_directory,
            timeout_seconds=timeout_seconds,
        )
        result.update(monitored)
        if not monitored["success"]:
            raise BotBrainAcceptanceFailure(
                "autonomous run failed: "
                f"{monitored['completionReason']} "
                f"highest_wave={monitored['highestWaveReached']}"
            )
    except BaseException as exc:
        result["success"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        failure = exc
    finally:
        result["finishedUtc"] = _utc_now()
        if launch:
            try:
                result["runtimeEvidence"] = _copy_runtime_evidence(
                    output_directory
                )
                result["brainLog"] = _brain_log_summary(
                    output_directory
                )
                if "lastViews" in result:
                    host = result["lastViews"]["host"]
                    result["castsIssued"] = _integer(
                        host,
                        "brain.cast_issued",
                    )
                    result["castsAccepted"] = _integer(
                        host,
                        "brain.cast_accepted",
                    )
                    result["kitePathDistance"] = _number(
                        host,
                        "brain.kite_path_distance",
                    )
                    result["botHpAtFinish"] = _number(
                        host,
                        "bot.hp",
                    )
            except BaseException as evidence_error:
                result["evidenceError"] = (
                    f"{type(evidence_error).__name__}: "
                    f"{evidence_error}"
                )
                if failure is None:
                    failure = evidence_error
                    result["success"] = False
            try:
                result["cleanup"] = (
                    local_sync.stop_exact_game_processes(launch)
                )
            except BaseException as cleanup_error:
                result["cleanupError"] = (
                    f"{type(cleanup_error).__name__}: "
                    f"{cleanup_error}"
                )
                if failure is None:
                    failure = cleanup_error
                    result["success"] = False

        result_path = output_directory / "result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"RUN={run_index} SUCCESS={result.get('success')} "
            f"WAVE={result.get('highestWaveReached', 0)} "
            f"HP={result.get('botHpAtFinish', 0)} "
            f"RESULT={result_path}"
        )

    if failure is not None:
        raise failure
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUN_COUNT,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_RUN_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=EVIDENCE_ROOT,
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=GAME_DIRECTORY,
    )
    parser.add_argument(
        "--launcher",
        type=Path,
        default=ROOT / "dist/launcher/SolomonDarkModLauncher.exe",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be positive")
    if args.timeout_seconds <= 0.0:
        raise SystemExit("--timeout-seconds must be positive")
    if not (args.game_dir / "SolomonDark.exe").is_file():
        raise SystemExit(
            f"source game directory is invalid: {args.game_dir}"
        )
    if not args.launcher.is_file():
        raise SystemExit(
            f"launcher does not exist: {args.launcher}"
        )

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "phase": "autonomous_wave_five",
        "startedUtc": _utc_now(),
        "requiredConsecutiveRuns": args.runs,
        "retailWaveSchedule": True,
        "runs": [],
        "success": False,
    }
    summary_path = args.evidence_dir / "result.json"
    try:
        for run_index in range(1, args.runs + 1):
            result = verify_one_run(
                run_index,
                output_directory=(
                    args.evidence_dir / f"run-{run_index}"
                ),
                game_directory=args.game_dir,
                launcher_path=args.launcher,
                timeout_seconds=args.timeout_seconds,
            )
            summary["runs"].append(
                {
                    "runId": result["runId"],
                    "result": str(
                        args.evidence_dir
                        / f"run-{run_index}"
                        / "result.json"
                    ),
                    "highestWaveReached": result[
                        "highestWaveReached"
                    ],
                    "botAliveAtWaveFive": result[
                        "botAliveAtWaveFive"
                    ],
                    "botHpAtFinish": result[
                        "botHpAtFinish"
                    ],
                    "castsIssued": result["castsIssued"],
                    "castsAccepted": result["castsAccepted"],
                    "kitePathDistance": result[
                        "kitePathDistance"
                    ],
                }
            )
        summary["success"] = (
            len(summary["runs"]) == args.runs
            and all(
                run["highestWaveReached"] >= 5
                and run["botAliveAtWaveFive"] is True
                for run in summary["runs"]
            )
        )
    except BaseException as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        summary["success"] = False
        raise
    finally:
        summary["finishedUtc"] = _utc_now()
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"SUMMARY={summary_path}")

    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
