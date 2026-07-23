#!/usr/bin/env python3
"""Verify scoped Lua storage, including an optional cross-process read phase."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_storage_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"


def run(pipe_name: str, phase: str, token: str) -> dict[str, Any]:
    if phase == "write":
        code = f'''
assert(sd.runtime.has_capability("storage.profile.local"))
sd.storage.clear()
assert(sd.storage.get("missing", "fallback") == "fallback")
assert(sd.storage.set("acceptance", {{token={json.dumps(token)}, count=41, flags={{true, false}}}}))
local cycle = {{}}; cycle.self = cycle
local cycle_ok = pcall(sd.storage.set, "cycle", cycle)
if cycle_ok then error("cyclic value was accepted") end
local snapshot = sd.storage.snapshot()
print("token=" .. tostring(snapshot.acceptance.token))
print("count=" .. tostring(snapshot.acceptance.count))
print("cycle_rejected=" .. tostring(not cycle_ok))
'''
        values = parse_key_values(lua(pipe_name, code, timeout=12.0))
        if values.get("token") != token or values.get("count") != "41":
            raise VerifyFailure(f"write phase mismatch: {values}")
        if values.get("cycle_rejected") != "true":
            raise VerifyFailure(f"cyclic value was accepted: {values}")
    elif phase == "read":
        code = '''
local value = sd.storage.get("acceptance")
print("present=" .. tostring(type(value) == "table"))
print("token=" .. tostring(value and value.token or ""))
print("count=" .. tostring(value and value.count or -1))
print("deleted_missing=" .. tostring(not sd.storage.delete("missing")))
'''
        values = parse_key_values(lua(pipe_name, code, timeout=12.0))
        if values.get("present") != "true" or values.get("token") != token:
            raise VerifyFailure(f"persisted token mismatch: {values}")
        if values.get("count") != "41" or values.get("deleted_missing") != "true":
            raise VerifyFailure(f"persisted payload mismatch: {values}")
    else:
        code = '''
local cleared = sd.storage.clear()
print("cleared=" .. tostring(cleared))
print("empty=" .. tostring(next(sd.storage.snapshot()) == nil))
'''
        values = parse_key_values(lua(pipe_name, code, timeout=12.0))
        if values.get("empty") != "true":
            raise VerifyFailure(f"clear phase left stored values: {values}")

    return {
        "ok": True,
        "pipe": pipe_name,
        "phase": phase,
        "token": token,
        "values": values,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--phase", choices=("write", "read", "clear"), required=True)
    parser.add_argument("--token", default="lua-storage-acceptance")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe, "phase": args.phase}
    try:
        result = run(args.pipe, args.phase, args.token)
        return_code = 0
    except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
        result["error"] = str(error)
        return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
