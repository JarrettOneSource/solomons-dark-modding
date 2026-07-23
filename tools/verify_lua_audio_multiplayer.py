#!/usr/bin/env python3
"""Verify presentation-local Lua audio across a disposable pair."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import time
import wave
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_lua_client
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    disable_bots,
    game_process_ids,
    launch_pair,
    stop_game_processes,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_audio_multiplayer_verification.json"
MOD_ROOT = ROOT / "mods" / "lua_audio_lab"
FIXTURE_SOURCE = MOD_ROOT / "audio" / "acceptance.wav.base64"
FIXTURE_AUDIO = MOD_ROOT / "audio" / "acceptance.wav"
FIXTURE_SHA256 = (
    "60c0b6c740c791f5d9c1b7d688aa4e6719b93c8f4e7c4b7919ab86ad78b74068"
)
ACCEPTANCE_MOD_ID = "sample.lua.audio_lab"
ASSET_PATH = "audio/acceptance.wav"
HOST_LABEL = "host-audio-state"
CLIENT_LABEL = "client-audio-state"


CONTRACT_PROBE = f"""
local mod = assert(sd.runtime.get_mod())
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {{}}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end
local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.audio) do
  namespace_count = namespace_count + 1
  if (name ~= "play_sample" and name ~= "play_stream" and
      name ~= "stop" and name ~= "set_volume" and
      name ~= "get_state" and name ~= "clear" and
      name ~= "is_available") or type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 7
local precleared = sd.audio.clear()
_G.__sd_audio_multiplayer_acceptance = nil
local states = sd.audio.get_state()
local asset = {json.dumps(ASSET_PATH)}

local traversal_ok = pcall(sd.audio.play_sample, "../escape.wav")
local absolute_ok = pcall(sd.audio.play_sample, "C:\\\\escape.wav")
local extension_ok = pcall(sd.audio.play_sample, "audio/test.flac")
local invalid_utf8_ok = pcall(
  sd.audio.play_sample, string.char(255) .. ".wav")
local missing_ok = pcall(sd.audio.play_sample, "audio/missing.wav")
local high_volume_ok = pcall(
  sd.audio.play_sample, asset, {{volume = 1.1}})
local nan_volume_ok = pcall(
  sd.audio.play_sample, asset, {{volume = 0 / 0}})
local bad_loop_ok = pcall(
  sd.audio.play_stream, asset, {{loop = 1}})
local unknown_option_ok = pcall(
  sd.audio.play_sample, asset, {{autoplay = true}})
local extra_play_ok = pcall(
  sd.audio.play_sample, asset, {{}}, true)
local zero_handle_ok = pcall(sd.audio.stop, 0)
local fractional_handle_ok = pcall(sd.audio.stop, 1.5)
local bad_set_volume_ok = pcall(sd.audio.set_volume, 1, -0.1)
local extra_state_ok = pcall(sd.audio.get_state, nil, true)
local extra_clear_ok = pcall(sd.audio.clear, true)
local extra_available_ok = pcall(sd.audio.is_available, true)

print("mod_id=" .. tostring(mod.id))
print("playback_capability=" .. tostring(
  sd.runtime.has_capability("audio.local.playback")))
print("sample_capability=" .. tostring(
  sd.runtime.has_capability("audio.sample")))
print("stream_capability=" .. tostring(
  sd.runtime.has_capability("audio.stream")))
print("available=" .. tostring(sd.audio.is_available()))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {{}})))
print("owner_count=" .. tostring(owner_count))
print("namespace_exact=" .. tostring(namespace_exact))
print("precleared=" .. tostring(precleared))
print("initial_count=" .. tostring(#states))
print("traversal_rejected=" .. tostring(not traversal_ok))
print("absolute_rejected=" .. tostring(not absolute_ok))
print("extension_rejected=" .. tostring(not extension_ok))
print("invalid_utf8_rejected=" .. tostring(not invalid_utf8_ok))
print("missing_rejected=" .. tostring(not missing_ok))
print("high_volume_rejected=" .. tostring(not high_volume_ok))
print("nan_volume_rejected=" .. tostring(not nan_volume_ok))
print("bad_loop_rejected=" .. tostring(not bad_loop_ok))
print("unknown_option_rejected=" .. tostring(not unknown_option_ok))
print("extra_play_rejected=" .. tostring(not extra_play_ok))
print("zero_handle_rejected=" .. tostring(not zero_handle_ok))
print("fractional_handle_rejected=" .. tostring(not fractional_handle_ok))
print("bad_set_volume_rejected=" .. tostring(not bad_set_volume_ok))
print("extra_state_rejected=" .. tostring(not extra_state_ok))
print("extra_clear_rejected=" .. tostring(not extra_clear_ok))
print("extra_available_rejected=" .. tostring(not extra_available_ok))
"""


STATE_PROBE = f"""
local mod = assert(sd.runtime.get_mod())
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {{}}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end
local states = sd.audio.get_state()
local acceptance = _G.__sd_audio_multiplayer_acceptance
local sample = nil
local stream = nil
local schema_exact = true
local raw_internals_absent = true
local activity_exact = true
local created_positive = true
for _, playback in ipairs(states) do
  local allowed = {{
    handle = true, kind = true, path = true, volume = true,
    loop = true, created_milliseconds = true, state = true,
  }}
  local count = 0
  for key, _ in pairs(playback) do
    if type(key) ~= "string" or not allowed[key] then
      schema_exact = false
    end
    count = count + 1
  end
  schema_exact = schema_exact and count == 7
  raw_internals_absent =
    raw_internals_absent and playback.channel_handle == nil and
    playback.sample_handle == nil and playback.bass_handle == nil and
    playback.native_handle == nil and playback.pointer == nil and
    playback.function_address == nil
  activity_exact =
    activity_exact and
    (playback.state == "playing" or playback.state == "stalled" or
     playback.state == "paused")
  created_positive =
    created_positive and
    type(playback.created_milliseconds) == "number" and
    playback.created_milliseconds > 0
  if playback.kind == "sample" then sample = playback end
  if playback.kind == "stream" then stream = playback end
end
local paths_exact =
  (sample == nil or sample.path == {json.dumps(ASSET_PATH)}) and
  (stream == nil or stream.path == {json.dumps(ASSET_PATH)})
local loops_exact =
  (sample == nil or sample.loop == true) and
  (stream == nil or stream.loop == true)
local handles_exact =
  (sample == nil or
   (acceptance ~= nil and sample.handle == acceptance.sample)) and
  (stream == nil or
   (acceptance ~= nil and stream.handle == acceptance.stream))

print("mod_id=" .. tostring(mod.id))
print("available=" .. tostring(sd.audio.is_available()))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {{}})))
print("owner_count=" .. tostring(owner_count))
print("playback_count=" .. tostring(#states))
print("label=" .. tostring(acceptance and acceptance.label or ""))
print("sample_present=" .. tostring(sample ~= nil))
print("stream_present=" .. tostring(stream ~= nil))
print("sample_volume=" .. string.format(
  "%.2f", sample and sample.volume or 0))
print("stream_volume=" .. string.format(
  "%.2f", stream and stream.volume or 0))
print("schema_exact=" .. tostring(schema_exact))
print("raw_internals_absent=" .. tostring(raw_internals_absent))
print("activity_exact=" .. tostring(activity_exact))
print("created_positive=" .. tostring(created_positive))
print("paths_exact=" .. tostring(paths_exact))
print("loops_exact=" .. tostring(loops_exact))
print("handles_exact=" .. tostring(handles_exact))
"""


STOP_SAMPLE_PROBE = """
local acceptance = assert(_G.__sd_audio_multiplayer_acceptance)
local first = sd.audio.stop(acceptance.sample)
local second = sd.audio.stop(acceptance.sample)
local missing = sd.audio.get_state(acceptance.sample) == nil
print("first=" .. tostring(first))
print("second=" .. tostring(second))
print("missing=" .. tostring(missing))
print("remaining=" .. tostring(#sd.audio.get_state()))
"""


CLEAR_PROBE = """
local first = sd.audio.clear()
local second = sd.audio.clear()
_G.__sd_audio_multiplayer_acceptance = nil
print("first=" .. tostring(first))
print("second=" .. tostring(second))
print("empty=" .. tostring(#sd.audio.get_state() == 0))
"""


CAPACITY_PROBE = f"""
local before = sd.audio.clear()
local handles = {{}}
for index = 1, 64 do
  handles[index] = sd.audio.play_sample(
    {json.dumps(ASSET_PATH)}, {{volume = 0.0, loop = true}})
end
local overflow_ok = pcall(
  sd.audio.play_sample,
  {json.dumps(ASSET_PATH)},
  {{volume = 0.0, loop = true}})
local ids_valid = true
for index, handle in ipairs(handles) do
  if type(handle) ~= "number" or math.type(handle) ~= "integer" or
      handle <= 0 or (index > 1 and handle <= handles[index - 1]) then
    ids_valid = false
  end
end
local live_count = #sd.audio.get_state()
local cleared = sd.audio.clear()
_G.__sd_audio_multiplayer_acceptance = nil
print("before=" .. tostring(before))
print("overflow_rejected=" .. tostring(not overflow_ok))
print("ids_valid=" .. tostring(ids_valid))
print("live_count=" .. tostring(live_count))
print("cleared=" .. tostring(cleared))
print("empty=" .. tostring(#sd.audio.get_state() == 0))
"""


CLEANUP_PROBE = """
local cleared = sd.audio.clear()
_G.__sd_audio_multiplayer_acceptance = nil
print("cleared=" .. tostring(cleared))
"""


def _play_probe(label: str) -> str:
    return f"""
local asset = {json.dumps(ASSET_PATH)}
local precleared = sd.audio.clear()
local sample = sd.audio.play_sample(
  asset, {{volume = 0.25, loop = true}})
local stream = sd.audio.play_stream(
  asset, {{volume = 0.30, loop = true}})
local sample_volume_set = sd.audio.set_volume(sample, 0.40)
local stream_volume_set = sd.audio.set_volume(stream, 0.45)
local sample_state = assert(sd.audio.get_state(sample))
local stream_state = assert(sd.audio.get_state(stream))
_G.__sd_audio_multiplayer_acceptance = {{
  label = {json.dumps(label)},
  sample = sample,
  stream = stream,
}}
print("played=true")
print("label=" .. tostring({json.dumps(label)}))
print("precleared=" .. tostring(precleared))
print("sample_handle=" .. tostring(sample))
print("stream_handle=" .. tostring(stream))
print("handles_monotonic=" .. tostring(
  type(sample) == "number" and type(stream) == "number" and
  math.type(sample) == "integer" and math.type(stream) == "integer" and
  sample > 0 and stream > sample))
print("sample_volume_set=" .. tostring(sample_volume_set))
print("stream_volume_set=" .. tostring(stream_volume_set))
print("sample_volume=" .. string.format("%.2f", sample_state.volume))
print("stream_volume=" .. string.format("%.2f", stream_state.volume))
print("playback_count=" .. tostring(#sd.audio.get_state()))
"""


def _volume_probe(volume: float) -> str:
    return f"""
local acceptance = assert(_G.__sd_audio_multiplayer_acceptance)
local changed = sd.audio.set_volume(acceptance.stream, {volume})
local state = assert(sd.audio.get_state(acceptance.stream))
print("changed=" .. tostring(changed))
print("volume=" .. string.format("%.2f", state.volume))
print("playback_count=" .. tostring(#sd.audio.get_state()))
"""


@contextlib.contextmanager
def _materialize_fixture_asset() -> Iterator[dict[str, Any]]:
    if FIXTURE_AUDIO.exists():
        raise RuntimeError(
            f"refusing to overwrite existing audio fixture: {FIXTURE_AUDIO}"
        )
    payload = base64.b64decode(
        FIXTURE_SOURCE.read_text(encoding="ascii").strip(),
        validate=True,
    )
    digest = hashlib.sha256(payload).hexdigest()
    if digest != FIXTURE_SHA256:
        raise RuntimeError(
            f"encoded audio fixture hash mismatch: {digest} != "
            f"{FIXTURE_SHA256}"
        )
    with wave.open(io.BytesIO(payload), "rb") as fixture:
        frame_count = fixture.getnframes()
        properties = {
            "channels": fixture.getnchannels(),
            "sample_width": fixture.getsampwidth(),
            "sample_rate": fixture.getframerate(),
            "frame_count": frame_count,
            "compression": fixture.getcomptype(),
        }
        pcm = fixture.readframes(frame_count)
    expected = {
        "channels": 1,
        "sample_width": 2,
        "sample_rate": 8000,
        "frame_count": 80,
        "compression": "NONE",
    }
    if properties != expected:
        raise RuntimeError(
            f"audio fixture format mismatch: {properties} != {expected}"
        )
    if any(pcm):
        raise RuntimeError("audio fixture contains non-silent PCM samples")

    created = False
    try:
        with FIXTURE_AUDIO.open("xb") as output:
            created = True
            output.write(payload)
        yield {
            "path": ASSET_PATH,
            "bytes": len(payload),
            "sha256": digest,
            **properties,
            "silent_pcm": True,
        }
    finally:
        if created:
            FIXTURE_AUDIO.unlink(missing_ok=True)


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(
        result.get("stderr") or result.get("stdout") or "Lua exec failed"
    ).strip()


def _values(result: dict[str, Any]) -> dict[str, str]:
    values = result.get("values", {})
    if not isinstance(values, dict):
        raise RuntimeError(f"Lua probe returned invalid values: {result}")
    return values


def _int_value(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error


def contract_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("playback_capability") == "true"
            and values.get("sample_capability") == "true"
            and values.get("stream_capability") == "true"
            and values.get("available") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and values.get("world_scene") == "hub"
            and _int_value(values, "participant_count") == 2
            and _int_value(values, "participant_rows") == 2
            and _int_value(values, "owner_count") == 1
            and values.get("namespace_exact") == "true"
            and _int_value(values, "precleared") == 0
            and _int_value(values, "initial_count") == 0
            and all(
                values.get(name) == "true"
                for name in (
                    "traversal_rejected",
                    "absolute_rejected",
                    "extension_rejected",
                    "invalid_utf8_rejected",
                    "missing_rejected",
                    "high_volume_rejected",
                    "nan_volume_rejected",
                    "bad_loop_rejected",
                    "unknown_option_rejected",
                    "extra_play_rejected",
                    "zero_handle_rejected",
                    "fractional_handle_rejected",
                    "bad_set_volume_rejected",
                    "extra_state_rejected",
                    "extra_clear_rejected",
                    "extra_available_rejected",
                )
            )
        )
    except RuntimeError:
        return False


def audio_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
    label: str | None,
    sample_volume: float | None,
    stream_volume: float | None,
) -> bool:
    try:
        expected_count = int(sample_volume is not None) + int(
            stream_volume is not None
        )
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("available") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and values.get("world_scene") == "hub"
            and _int_value(values, "participant_count") == 2
            and _int_value(values, "participant_rows") == 2
            and _int_value(values, "owner_count") == 1
            and _int_value(values, "playback_count") == expected_count
            and values.get("label") == (label or "")
            and values.get("sample_present")
            == ("true" if sample_volume is not None else "false")
            and values.get("stream_present")
            == ("true" if stream_volume is not None else "false")
            and values.get("sample_volume")
            == f"{sample_volume or 0:.2f}"
            and values.get("stream_volume")
            == f"{stream_volume or 0:.2f}"
            and all(
                values.get(name) == "true"
                for name in (
                    "schema_exact",
                    "raw_internals_absent",
                    "activity_exact",
                    "created_positive",
                    "paths_exact",
                    "loops_exact",
                    "handles_exact",
                )
            )
        )
    except RuntimeError:
        return False


def play_matches(values: dict[str, str], *, label: str) -> bool:
    try:
        return (
            values.get("played") == "true"
            and values.get("label") == label
            and _int_value(values, "precleared") == 0
            and _int_value(values, "sample_handle") > 0
            and _int_value(values, "stream_handle")
            > _int_value(values, "sample_handle")
            and values.get("handles_monotonic") == "true"
            and values.get("sample_volume_set") == "true"
            and values.get("stream_volume_set") == "true"
            and values.get("sample_volume") == "0.40"
            and values.get("stream_volume") == "0.45"
            and values.get("playback_count") == "2"
        )
    except RuntimeError:
        return False


def volume_matches(values: dict[str, str], *, volume: float) -> bool:
    return (
        values.get("changed") == "true"
        and values.get("volume") == f"{volume:.2f}"
        and values.get("playback_count") == "2"
    )


def stop_matches(values: dict[str, str]) -> bool:
    return (
        values.get("first") == "true"
        and values.get("second") == "false"
        and values.get("missing") == "true"
        and values.get("remaining") == "1"
    )


def clear_matches(values: dict[str, str], *, expected: int) -> bool:
    return (
        values.get("first") == str(expected)
        and values.get("second") == "0"
        and values.get("empty") == "true"
    )


def capacity_matches(values: dict[str, str]) -> bool:
    return (
        values.get("before") == "1"
        and values.get("overflow_rejected") == "true"
        and values.get("ids_valid") == "true"
        and values.get("live_count") == "64"
        and values.get("cleared") == "64"
        and values.get("empty") == "true"
    )


def _run_probe(
    client: tuple[str, str],
    code: str,
) -> dict[str, Any]:
    result = run_lua_client(client[0], client[1], code, timeout=12.0)
    failure = _failed_exec(result)
    if failure:
        raise RuntimeError(failure)
    return result


def _require_action(
    client: tuple[str, str],
    code: str,
    predicate: Callable[[dict[str, str]], bool],
    description: str,
) -> dict[str, Any]:
    result = _run_probe(client, code)
    if not predicate(_values(result)):
        raise RuntimeError(f"{description} failed: {result}")
    return result


def _poll_state(
    client: tuple[str, str],
    *,
    authority: bool,
    label: str | None,
    sample_volume: float | None,
    stream_volume: float | None,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(
            client[0],
            client[1],
            STATE_PROBE,
            timeout=12.0,
        )
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and audio_state_matches(
                values,
                authority=authority,
                label=label,
                sample_volume=sample_volume,
                stream_volume=stream_volume,
            )
        ):
            return last
        time.sleep(0.05)
    raise RuntimeError(
        f"{description} did not converge for {client[0]}: {last}"
    )


def _cleanup_peer(client: tuple[str, str]) -> dict[str, Any]:
    try:
        return run_lua_client(
            client[0],
            client[1],
            CLEANUP_PROBE,
            timeout=5.0,
        )
    except Exception as error:  # noqa: BLE001 - process teardown is final.
        return {"returncode": 1, "error": str(error)}


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua audio acceptance requires --launch-pair")
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host, client = clients
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "host": host[0],
        "client": client[0],
    }
    launched_process_ids: list[int] = []
    pair_ready = False
    with _materialize_fixture_asset() as fixture:
        result["fixture"] = fixture
        try:
            result["pair"] = launch_pair(
                tile_windows=False,
                kill_existing=False,
                exact_mod_id=ACCEPTANCE_MOD_ID,
            )
            launched_process_ids.extend(game_process_ids(result["pair"]))
            if len(set(launched_process_ids)) != 2:
                raise RuntimeError(
                    "local pair did not report two exact process IDs: "
                    f"{launched_process_ids}"
                )
            disable_bots()
            wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
            wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")
            pair_ready = True

            result["contract"] = [
                _require_action(
                    peer,
                    CONTRACT_PROBE,
                    lambda values, authority=index == 0: contract_matches(
                        values,
                        authority=authority,
                    ),
                    "local audio contract",
                )
                for index, peer in enumerate((host, client))
            ]
            result["initial"] = [
                _poll_state(
                    peer,
                    authority=index == 0,
                    label=None,
                    sample_volume=None,
                    stream_volume=None,
                    timeout=timeout,
                    description="empty local audio registry",
                )
                for index, peer in enumerate((host, client))
            ]

            result["host_play"] = _require_action(
                host,
                _play_probe(HOST_LABEL),
                lambda values: play_matches(values, label=HOST_LABEL),
                "host audio playback",
            )
            result["host_play_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    label=HOST_LABEL,
                    sample_volume=0.40,
                    stream_volume=0.45,
                    timeout=timeout,
                    description="host local audio playbacks",
                ),
                _poll_state(
                    client,
                    authority=False,
                    label=None,
                    sample_volume=None,
                    stream_volume=None,
                    timeout=timeout,
                    description="client isolation from host audio",
                ),
            ]

            result["client_play"] = _require_action(
                client,
                _play_probe(CLIENT_LABEL),
                lambda values: play_matches(values, label=CLIENT_LABEL),
                "client audio playback",
            )
            result["independent_playback"] = [
                _poll_state(
                    host,
                    authority=True,
                    label=HOST_LABEL,
                    sample_volume=0.40,
                    stream_volume=0.45,
                    timeout=timeout,
                    description="host retained audio playbacks",
                ),
                _poll_state(
                    client,
                    authority=False,
                    label=CLIENT_LABEL,
                    sample_volume=0.40,
                    stream_volume=0.45,
                    timeout=timeout,
                    description="client local audio playbacks",
                ),
            ]

            result["client_volume"] = _require_action(
                client,
                _volume_probe(0.55),
                lambda values: volume_matches(values, volume=0.55),
                "client local volume change",
            )
            result["volume_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    label=HOST_LABEL,
                    sample_volume=0.40,
                    stream_volume=0.45,
                    timeout=timeout,
                    description="host volume isolation",
                ),
                _poll_state(
                    client,
                    authority=False,
                    label=CLIENT_LABEL,
                    sample_volume=0.40,
                    stream_volume=0.55,
                    timeout=timeout,
                    description="client changed volume",
                ),
            ]

            result["host_stop_sample"] = _require_action(
                host,
                STOP_SAMPLE_PROBE,
                stop_matches,
                "host sample stop",
            )
            result["host_stop_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    label=HOST_LABEL,
                    sample_volume=None,
                    stream_volume=0.45,
                    timeout=timeout,
                    description="host retained stream",
                ),
                _poll_state(
                    client,
                    authority=False,
                    label=CLIENT_LABEL,
                    sample_volume=0.40,
                    stream_volume=0.55,
                    timeout=timeout,
                    description="client retained audio after host stop",
                ),
            ]

            result["host_capacity"] = _require_action(
                host,
                CAPACITY_PROBE,
                capacity_matches,
                "host audio capacity",
            )
            result["capacity_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    label=None,
                    sample_volume=None,
                    stream_volume=None,
                    timeout=timeout,
                    description="host released audio capacity",
                ),
                _poll_state(
                    client,
                    authority=False,
                    label=CLIENT_LABEL,
                    sample_volume=0.40,
                    stream_volume=0.55,
                    timeout=timeout,
                    description="client retained audio during host capacity",
                ),
            ]

            result["client_clear"] = _require_action(
                client,
                CLEAR_PROBE,
                lambda values: clear_matches(values, expected=2),
                "client audio clear",
            )
            result["released"] = [
                _poll_state(
                    peer,
                    authority=index == 0,
                    label=None,
                    sample_volume=None,
                    stream_volume=None,
                    timeout=timeout,
                    description="released local audio registry",
                )
                for index, peer in enumerate((host, client))
            ]
            result["ok"] = True
            return result
        finally:
            if pair_ready:
                result["cleanup"] = [
                    _cleanup_peer(peer)
                    for peer in (host, client)
                ]
            stop_game_processes(launched_process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua endpoint as NAME=PIPE; provide exactly host then client.",
    )
    parser.add_argument(
        "--launch-pair",
        action="store_true",
        help="stage and launch the disposable local pair required by this verifier",
    )
    parser.add_argument(
        "--confirm-silent-playback",
        action="store_true",
        help="confirm local playback of the deterministic silent fixture",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_silent_playback:
        result["error"] = (
            "refusing audio playback without --confirm-silent-playback"
        )
        return_code = 2
    elif not args.launch_pair:
        result["error"] = "Lua audio acceptance requires --launch-pair"
        return_code = 2
    else:
        try:
            result = run(
                args.client or list(DEFAULT_CLIENTS),
                launch=True,
                timeout=max(1.0, args.timeout),
            )
            return_code = 0 if result.get("ok") else 1
        except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
            result["error"] = str(error)
            return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
