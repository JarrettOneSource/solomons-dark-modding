#!/usr/bin/env python3
"""Verify the local Lua BASS contract against an already-running loader."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_audio_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


CONTRACT_PROBE = r'''
assert(type(sd.audio) == "table", "missing sd.audio")
for _, name in ipairs({
  "play_sample", "play_stream", "stop", "set_volume",
  "get_state", "clear", "is_available",
}) do
  assert(type(sd.audio[name]) == "function", "missing sd.audio." .. name)
end
assert(sd.runtime.has_capability("audio.local.playback"))
assert(sd.runtime.has_capability("audio.sample"))
assert(sd.runtime.has_capability("audio.stream"))

local states = sd.audio.get_state()
assert(type(states) == "table")
local raw_internals_absent = true
for _, state in ipairs(states) do
  for _, field in ipairs({
    "channel_handle", "sample_handle", "bass_handle", "native_handle",
    "pointer", "function_address",
  }) do
    if state[field] ~= nil then raw_internals_absent = false end
  end
end

local traversal_ok = pcall(sd.audio.play_sample, "../escape.wav")
local absolute_ok = pcall(sd.audio.play_sample, "C:\\escape.wav")
local extension_ok = pcall(sd.audio.play_sample, "audio/test.flac")
local invalid_utf8_ok = pcall(sd.audio.play_sample, string.char(255) .. ".wav")
local high_volume_ok = pcall(sd.audio.play_sample, "missing.wav", {volume = 1.1})
local bad_loop_ok = pcall(sd.audio.play_stream, "missing.wav", {loop = 1})
local unknown_option_ok = pcall(
  sd.audio.play_sample, "missing.wav", {autoplay = true})
local zero_handle_ok = pcall(sd.audio.stop, 0)
local fractional_handle_ok = pcall(sd.audio.stop, 1.5)
local bad_set_volume_ok = pcall(sd.audio.set_volume, 1, -0.1)
local extra_clear_ok = pcall(sd.audio.clear, true)

print("available=" .. tostring(sd.audio.is_available()))
print("raw_internals_absent=" .. tostring(raw_internals_absent))
print("traversal_rejected=" .. tostring(not traversal_ok))
print("absolute_rejected=" .. tostring(not absolute_ok))
print("extension_rejected=" .. tostring(not extension_ok))
print("invalid_utf8_rejected=" .. tostring(not invalid_utf8_ok))
print("high_volume_rejected=" .. tostring(not high_volume_ok))
print("bad_loop_rejected=" .. tostring(not bad_loop_ok))
print("unknown_option_rejected=" .. tostring(not unknown_option_ok))
print("zero_handle_rejected=" .. tostring(not zero_handle_ok))
print("fractional_handle_rejected=" .. tostring(not fractional_handle_ok))
print("bad_set_volume_rejected=" .. tostring(not bad_set_volume_ok))
print("extra_clear_rejected=" .. tostring(not extra_clear_ok))
print("initial_playback_count=" .. tostring(#states))
'''


def _playback_probe(asset: str) -> str:
    encoded_asset = json.dumps(asset)
    return f'''
local asset = {encoded_asset}
sd.audio.clear()

local sample = sd.audio.play_sample(asset, {{volume = 0.25, loop = true}})
assert(type(sample) == "number" and sample > 0)
local sample_state = assert(sd.audio.get_state(sample))
assert(sample_state.handle == sample)
assert(sample_state.kind == "sample")
assert(sample_state.path == asset)
assert(sample_state.loop == true)
assert(sample_state.state == "playing" or sample_state.state == "stalled" or
       sample_state.state == "paused")
assert(sd.audio.set_volume(sample, 0.4) == true)
sample_state = assert(sd.audio.get_state(sample))
assert(math.abs(sample_state.volume - 0.4) < 0.0001)
assert(sd.audio.stop(sample) == true)
assert(sd.audio.stop(sample) == false)
assert(sd.audio.get_state(sample) == nil)

local stream = sd.audio.play_stream(asset, {{volume = 0.3, loop = true}})
assert(type(stream) == "number" and stream > sample)
local stream_state = assert(sd.audio.get_state(stream))
assert(stream_state.handle == stream)
assert(stream_state.kind == "stream")
assert(stream_state.path == asset)
assert(stream_state.loop == true)
assert(stream_state.state == "playing" or stream_state.state == "stalled" or
       stream_state.state == "paused")
assert(sd.audio.set_volume(stream, 0.45) == true)
stream_state = assert(sd.audio.get_state(stream))
assert(math.abs(stream_state.volume - 0.45) < 0.0001)
assert(#sd.audio.get_state() == 1)
assert(sd.audio.clear() == 1)
assert(#sd.audio.get_state() == 0)

print("sample_handle=" .. tostring(sample))
print("sample_kind=" .. sample_state.kind)
print("sample_volume=" .. tostring(sample_state.volume))
print("stream_handle=" .. tostring(stream))
print("stream_kind=" .. stream_state.kind)
print("stream_volume=" .. tostring(stream_state.volume))
print("playback_paths_passed=true")
'''


def _require_true(values: dict[str, str], *names: str) -> None:
    for name in names:
        if values.get(name) != "true":
            raise VerifyFailure(f"Lua audio contract failed {name}: {values}")


def run(pipe_name: str, asset: str | None) -> dict[str, Any]:
    contract = parse_key_values(lua(pipe_name, CONTRACT_PROBE, timeout=12.0))
    _require_true(
        contract,
        "available",
        "raw_internals_absent",
        "traversal_rejected",
        "absolute_rejected",
        "extension_rejected",
        "invalid_utf8_rejected",
        "high_volume_rejected",
        "bad_loop_rejected",
        "unknown_option_rejected",
        "zero_handle_rejected",
        "fractional_handle_rejected",
        "bad_set_volume_rejected",
        "extra_clear_rejected",
    )

    result: dict[str, Any] = {
        "ok": True,
        "pipe": pipe_name,
        "contract": contract,
        "asset": asset,
        "playback_checked": asset is not None,
    }
    if asset is not None:
        playback = parse_key_values(
            lua(pipe_name, _playback_probe(asset), timeout=12.0)
        )
        _require_true(playback, "playback_paths_passed")
        if playback.get("sample_kind") != "sample":
            raise VerifyFailure(f"sample playback schema differs: {playback}")
        if playback.get("stream_kind") != "stream":
            raise VerifyFailure(f"stream playback schema differs: {playback}")
        result["playback"] = playback
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument(
        "--asset",
        help=(
            "Optional audio path relative to the first loaded Lua mod. The same "
            "asset is exercised through sample and stream playback."
        ),
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(args.pipe, args.asset)
        return_code = 0
    except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
        result["error"] = str(error)
        return_code = 1
        if args.asset is not None:
            try:
                lua(args.pipe, "return sd.audio.clear()", timeout=5.0)
            except Exception:  # noqa: BLE001 - original failure remains primary.
                pass

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
