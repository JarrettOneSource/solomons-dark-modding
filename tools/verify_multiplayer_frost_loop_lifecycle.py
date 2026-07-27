#!/usr/bin/env python3
"""Verify that a replicated Frost cast releases every owned native loop."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_replicated_audio_events as audio


ROOT = Path(__file__).resolve().parent.parent
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
INSTANCE_PREFIX = "sfx"
HOST_PORT = 48611
CLIENT_PORT = 48612
SNAPSHOT_INTERVAL_MS = 50
FROST_HOLD_FRAMES = 170
FROST_REGISTRY_INDEX = 161
FROST_OWNER = "spell.frost_jet"
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"


def values(pipe_name: str, code: str) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=12.0)
    )


def integer_value(value: str | None) -> int:
    text = value or "0"
    if text.startswith(("0x", "0X")):
        return int(text, 16)
    return int(float(text))


def query_frost_channel(pipe_name: str) -> dict[str, Any]:
    raw = values(
        pipe_name,
        f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end
local latest = nil
for _, channel in ipairs(
    sd.debug.get_native_audio_channels(true) or {{}}) do
  if tonumber(channel.registry_index) == {FROST_REGISTRY_INDEX} and
     channel.owner == "{FROST_OWNER}" and
     (latest == nil or
      tonumber(channel.event_sequence) >
        tonumber(latest.event_sequence)) then
    latest = channel
  end
end
emit("found", latest ~= nil)
emit("event_sequence", latest and latest.event_sequence or 0)
emit("object_address", latest and string.format(
  "0x%08X", tonumber(latest.object_address) or 0) or "0x00000000")
emit("channel_handle", latest and string.format(
  "0x%08X", tonumber(latest.channel_handle) or 0) or "0x00000000")
emit("actor_address", latest and string.format(
  "0x%08X", tonumber(latest.actor_address) or 0) or "0x00000000")
emit("participant_id", latest and latest.participant_id_text or "0")
emit("started_ms", latest and latest.started_ms or 0)
emit("stopped_ms", latest and latest.stopped_ms or 0)
emit("age_ms", latest and latest.age_ms or 0)
emit("start_count", latest and latest.start_count or 0)
emit("stop_count", latest and latest.stop_count or 0)
emit("cast_sequence", latest and latest.cast_sequence or 0)
emit("native_reference_count",
  latest and latest.native_reference_count or 0)
emit("registry_index", latest and latest.registry_index or -1)
emit("skill_id", latest and latest.skill_id or 0)
emit("active", latest and latest.active or false)
emit("loop_flag", latest and latest.loop_flag or false)
emit("remote", latest and latest.remote or false)
emit("asset", latest and latest.asset or "")
emit("owner", latest and latest.owner or "")
""",
    )
    integer_keys = (
        "event_sequence",
        "started_ms",
        "stopped_ms",
        "age_ms",
        "start_count",
        "stop_count",
        "cast_sequence",
        "native_reference_count",
        "registry_index",
        "skill_id",
    )
    return {
        **raw,
        **{
            key: integer_value(raw.get(key))
            for key in integer_keys
        },
        "found": raw.get("found") == "true",
        "active": raw.get("active") == "true",
        "loop_flag": raw.get("loop_flag") == "true",
        "remote": raw.get("remote") == "true",
    }


def query_outliving_owned_loops(
    pipe_name: str,
    participant_id: int,
    cast_sequence: int,
) -> dict[str, Any]:
    raw = values(
        pipe_name,
        f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end
local participant = "{participant_id}"
local cast_sequence = {cast_sequence}
local count = 0
local details = {{}}
for _, channel in ipairs(
    sd.debug.get_native_audio_channels(false) or {{}}) do
  if channel.loop_flag and channel.active and channel.remote and
     channel.participant_id_text == participant and
     tonumber(channel.cast_sequence) == cast_sequence then
    count = count + 1
    details[#details + 1] = table.concat({{
      tostring(channel.owner),
      tostring(channel.asset),
      tostring(channel.age_ms),
      tostring(channel.native_reference_count),
      tostring(channel.event_sequence)
    }}, "|")
  end
end
emit("count", count)
emit("details", table.concat(details, ","))
""",
    )
    return {
        **raw,
        "count": integer_value(raw.get("count")),
    }


def clear_inactive_history(pipe_name: str) -> dict[str, Any]:
    raw = values(
        pipe_name,
        """
local active = sd.debug.get_native_audio_channels(false) or {}
local frost_active = 0
for _, channel in ipairs(active) do
  if tonumber(channel.registry_index) == 161 and
     channel.owner == "spell.frost_jet" then
    frost_active = frost_active + 1
  end
end
print("active_frost=" .. tostring(frost_active))
print("removed=" .. tostring(
  sd.debug.clear_native_audio_channel_history()))
""",
    )
    result = {
        **raw,
        "active_frost": integer_value(raw.get("active_frost")),
        "removed": integer_value(raw.get("removed")),
    }
    if result["active_frost"] != 0:
        raise local_sync.VerifyFailure(
            f"Frost loop was already active before trial: {result}"
        )
    return result


def dump_registry(pipe_name: str) -> int:
    raw = values(
        pipe_name,
        "print('count=' .. tostring("
        "sd.debug.dump_native_audio_channels(true)))",
    )
    return integer_value(raw.get("count"))


def wait_for_frost_start(
    source_pipe: str,
    observer_pipe: str,
    *,
    timeout: float = 8.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    source: dict[str, Any] = {}
    observer: dict[str, Any] = {}
    while time.monotonic() < deadline:
        source = query_frost_channel(source_pipe)
        observer = query_frost_channel(observer_pipe)
        if (
            source.get("found") is True
            and source.get("started_ms", 0) > 0
            and observer.get("found") is True
            and observer.get("started_ms", 0) > 0
        ):
            return source, observer
        time.sleep(0.04)
    raise local_sync.VerifyFailure(
        "Frost loop did not start on both peers: "
        f"source={source} observer={observer}"
    )


def wait_for_source_frost_stop(
    source_pipe: str,
    *,
    timeout: float = 12.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    source: dict[str, Any] = {}
    while time.monotonic() < deadline:
        source = query_frost_channel(source_pipe)
        if (
            source.get("found") is True
            and source.get("active") is False
            and source.get("stopped_ms", 0) > 0
        ):
            return source
        time.sleep(0.04)
    raise local_sync.VerifyFailure(
        f"local Frost loop did not stop: {source}"
    )


def run_trial(
    source_pipe: str,
    observer_pipe: str,
    trial: int,
) -> dict[str, Any]:
    history = {
        "source": clear_inactive_history(source_pipe),
        "observer": clear_inactive_history(observer_pipe),
    }
    audio.clear_cast_state(source_pipe)
    audio.clear_cast_state(observer_pipe)
    queued = audio.queue_earth_cast(
        source_pipe,
        FROST_HOLD_FRAMES,
    )
    source_start, observer_start = wait_for_frost_start(
        source_pipe,
        observer_pipe,
    )
    source_stop = wait_for_source_frost_stop(source_pipe)
    observer_idle = audio.wait_for_remote_cast_idle(
        observer_pipe,
        local_sync.CLIENT_ID,
        timeout=12.0,
    )

    time.sleep(SNAPSHOT_INTERVAL_MS / 1000.0)
    observer_final = query_frost_channel(observer_pipe)
    source_final = query_frost_channel(source_pipe)
    cast_sequence = int(observer_start["cast_sequence"])
    outliving = query_outliving_owned_loops(
        observer_pipe,
        local_sync.CLIENT_ID,
        cast_sequence,
    )
    registry_dump_counts = {
        "source": dump_registry(source_pipe),
        "observer": dump_registry(observer_pipe),
    }

    source_stopped_ms = int(source_final["stopped_ms"])
    observer_stopped_ms = int(observer_final["stopped_ms"])
    latency_ms = (
        observer_stopped_ms - source_stopped_ms
        if source_stopped_ms > 0 and observer_stopped_ms > 0
        else None
    )
    within_snapshot_interval = (
        latency_ms is not None
        and 0 <= latency_ms <= SNAPSHOT_INTERVAL_MS
    )
    no_outliving_owned_loop = (
        outliving["count"] == 0
        and observer_final["active"] is False
        and int(observer_final["native_reference_count"]) == 0
    )
    return {
        "trial": trial,
        "history_reset": history,
        "queued": queued,
        "source_start": source_start,
        "observer_start": observer_start,
        "source_stop": source_stop,
        "observer_cast_idle": observer_idle,
        "source_final": source_final,
        "observer_final": observer_final,
        "owned_cast_sequence": cast_sequence,
        "outliving_owned_loops": outliving,
        "registry_dump_counts": registry_dump_counts,
        "remote_stop_latency_ms": latency_ms,
        "within_snapshot_interval": within_snapshot_interval,
        "no_outliving_owned_loop": no_outliving_owned_loop,
        "ok": within_snapshot_interval and no_outliving_owned_loop,
    }


def copy_logs(
    runtime_root: Path,
    output_directory: Path,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    output_directory.mkdir(parents=True, exist_ok=True)
    for role in ("host", "client"):
        source = (
            runtime_root
            / "instances"
            / f"{INSTANCE_PREFIX}-{role}"
            / "stage"
            / ".sdmod"
            / "logs"
            / "solomondarkmodloader.log"
        )
        if source.is_file():
            target = output_directory / f"{role}-solomondarkmodloader.log"
            shutil.copy2(source, target)
            copied[role] = str(target)
    return copied


def launch_pair(
    runtime_root: Path,
) -> tuple[dict[str, Any], str, str, dict[int, Path]]:
    pair = local_sync.launch_pair(
        host_preset="map_create_water_mind_hub",
        client_preset="map_create_water_mind_hub",
        god_mode=True,
        tile_windows=False,
        kill_existing=False,
        instance_prefix=INSTANCE_PREFIX,
        host_port=HOST_PORT,
        client_port=CLIENT_PORT,
        game_directory=GAME_DIRECTORY,
        runtime_root=runtime_root,
        exact_mod_id=ACCEPTANCE_MOD_ID,
        enable_audio=False,
        test_blank_boneyard=True,
        test_survival_boneyard_override=(
            ROOT
            / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
        ),
        use_sandbox_preset_flow=True,
    )
    process_ids = local_sync.game_process_ids(pair)
    if (
        len(process_ids) != 2
        or pair.get("audioDisabled") is not True
    ):
        raise local_sync.VerifyFailure(
            "loopback launch was not exactly owned and audio-disabled: "
            f"{pair}"
        )
    expected = {
        int(pair["hostProcessId"]): audio.expected_executable(
            runtime_root,
            f"{INSTANCE_PREFIX}-host",
        ),
        int(pair["clientProcessId"]): audio.expected_executable(
            runtime_root,
            f"{INSTANCE_PREFIX}-client",
        ),
    }
    audio.validate_owned_processes(expected)
    return (
        pair,
        str(pair["hostLuaPipe"]),
        str(pair["clientLuaPipe"]),
        expected,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=ROOT / "runtime",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / "runtime"
            / "multiplayer_frost_loop_lifecycle.json"
        ),
    )
    args = parser.parse_args()
    if args.trials < 1:
        raise SystemExit("--trials must be positive")
    if not GAME_DIRECTORY.is_dir():
        raise SystemExit(
            f"game directory does not exist: {GAME_DIRECTORY}"
        )

    output = args.output.resolve()
    runtime_root = args.runtime_root.resolve()
    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": INSTANCE_PREFIX,
        "ports": [HOST_PORT, CLIENT_PORT],
        "snapshot_interval_ms": SNAPSHOT_INTERVAL_MS,
        "audio_enabled": False,
        "direction": "client_to_host",
        "trials": [],
    }
    expected: dict[int, Path] = {}
    return_code = 1
    try:
        pair, host_pipe, client_pipe, expected = launch_pair(
            runtime_root,
        )
        result["launch"] = pair
        result["owned_processes"] = {
            str(pid): str(path)
            for pid, path in expected.items()
        }
        result["pair_run"] = audio.enter_pair_run(
            host_pipe,
            client_pipe,
        )
        result["mana"] = {
            "host": audio.set_player_mana(host_pipe),
            "client": audio.set_player_mana(client_pipe),
        }
        for trial in range(1, args.trials + 1):
            trial_result = run_trial(
                client_pipe,
                host_pipe,
                trial,
            )
            result["trials"].append(trial_result)
            if not trial_result["ok"]:
                break
        result["ok"] = (
            len(result["trials"]) == args.trials
            and all(trial["ok"] for trial in result["trials"])
        )
        return_code = 0 if result["ok"] else 2
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if expected:
            try:
                result["cleanup"] = audio.stop_owned_processes(
                    expected
                )
            except Exception as exc:
                result["cleanup_error"] = str(exc)
                return_code = 1
        result["logs"] = copy_logs(
            runtime_root,
            output.parent / "logs",
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": result.get("ok"),
                    "trial_count": len(result["trials"]),
                    "output": str(output),
                    "error": result.get("error"),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
