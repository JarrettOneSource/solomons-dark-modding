#!/usr/bin/env python3
"""Watch the host local player actor header during local-MP hub->run entry."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_NAME,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    start_testrun,
    stop_games,
    wait_for_both_hub_settled,
    wait_for_remote,
    wait_for_scene,
)


OUTPUT = ROOT / "runtime" / "multiplayer_run_entry_local_actor_header_watch.json"
HOST_LOG = ROOT / "runtime/instances/local-mp-host/stage/.sdmod/logs/solomondarkmodloader.log"
WATCH_NAME = "mp_run_entry_local_actor_vtable"


def values(pipe_name: str, code: str, timeout: float = 8.0) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code, timeout=timeout))


def read_log_tail(path: Path, marker: str, max_chars: int = 20000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    index = text.rfind(marker)
    if index >= 0:
        return text[index:index + max_chars]
    return text[-max_chars:]


ARM_WATCH_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local player = sd.player.get_state()
local actor = player and tonumber(player.actor_address) or 0
pcall(sd.debug.unwatch, "__WATCH_NAME__")
pcall(sd.debug.clear_write_hits, "__WATCH_NAME__")
emit("actor", hx(actor))
if actor == 0 then
  emit("ok", false)
  emit("reason", "player_missing")
  return
end
local vtable = sd.debug.read_ptr(actor) or 0
emit("vtable_before", hx(vtable))
emit("watch_ok", sd.debug.watch_write("__WATCH_NAME__", actor, 4))
emit("ok", true)
"""


READ_HITS_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local function hx(v) return string.format("0x%08X", tonumber(v) or 0) end
local hits = sd.debug.get_write_hits("__WATCH_NAME__") or {}
emit("hit_count", #hits)
for index, hit in ipairs(hits) do
  emit("hit." .. index .. ".eip", hx(hit.eip))
  emit("hit." .. index .. ".ret", hx(hit.ret))
  emit("hit." .. index .. ".access", hx(hit.access_address))
  emit("hit." .. index .. ".old", hit.before_bytes_hex or "")
  emit("hit." .. index .. ".new", hit.after_bytes_hex or "")
  emit("hit." .. index .. ".eax", hx(hit.eax))
  emit("hit." .. index .. ".ecx", hx(hit.ecx))
  emit("hit." .. index .. ".edx", hx(hit.edx))
  emit("hit." .. index .. ".arg0", hx(hit.arg0))
  emit("hit." .. index .. ".arg1", hx(hit.arg1))
  emit("hit." .. index .. ".arg2", hx(hit.arg2))
end
local player = sd.player.get_state()
local actor = player and tonumber(player.actor_address) or 0
emit("actor_after", hx(actor))
if actor ~= 0 then
  emit("vtable_after", hx(sd.debug.read_ptr(actor) or 0))
end
"""


def run() -> dict[str, Any]:
    result: dict[str, Any] = {
        "watch_name": WATCH_NAME,
        "started_at": time.time(),
    }
    stop_games()
    result["launch"] = launch_pair(god_mode=True)
    result["disable_bots"] = disable_bots()
    wait_for_both_hub_settled(settle_seconds=2.0, timeout=20.0)
    wait_for_remote(HOST_PIPE, 0x2000000000001002, CLIENT_NAME, "hub")
    wait_for_remote(CLIENT_PIPE, 0x2000000000001001, HOST_NAME, "hub")
    time.sleep(4.0)
    result["arm"] = values(HOST_PIPE, ARM_WATCH_LUA.replace("__WATCH_NAME__", WATCH_NAME), timeout=8.0)
    if result["arm"].get("ok") != "true" or result["arm"].get("watch_ok") != "true":
        raise VerifyFailure(f"failed to arm local actor header watch: {result['arm']}")

    result["start_requested_at"] = time.time()
    start_testrun(HOST_PIPE)
    try:
        wait_for_scene(HOST_PIPE, "testrun", timeout=20.0)
        result["host_reached_testrun"] = True
    except Exception as exc:  # The crash/hang is the current signal.
        result["host_reached_testrun"] = False
        result["host_wait_error"] = str(exc)
    try:
        wait_for_scene(CLIENT_PIPE, "testrun", timeout=20.0)
        result["client_reached_testrun"] = True
    except Exception as exc:
        result["client_reached_testrun"] = False
        result["client_wait_error"] = str(exc)

    try:
        result["hits"] = values(HOST_PIPE, READ_HITS_LUA.replace("__WATCH_NAME__", WATCH_NAME), timeout=8.0)
    except Exception as exc:
        result["hits_error"] = str(exc)
    result["host_log_tail"] = read_log_tail(HOST_LOG, "WRITE WATCH: " + WATCH_NAME)
    result["finished_at"] = time.time()
    return result


def main() -> int:
    result: dict[str, Any] = {}
    try:
        result = run()
        result["ok"] = bool(result.get("host_reached_testrun") and result.get("client_reached_testrun"))
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        result["finished_at"] = time.time()
        result["host_log_tail"] = read_log_tail(HOST_LOG, "WRITE WATCH: " + WATCH_NAME)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result.get("ok"):
        print(f"run-entry local actor header watch failed: {result.get('error') or result.get('host_wait_error')}")
        print(f"wrote {OUTPUT}")
        return 1
    print(f"PASS: wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
