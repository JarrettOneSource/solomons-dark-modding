#!/usr/bin/env python3
"""Verify the authority-owned Lua run seed contract in a live hub."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_rng_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
ACCEPTANCE_SEED = 0x1234567


PROBE = f'''
assert(sd.runtime.has_capability("rng.run.seed"))
local accepted = sd.rng.set_seed({ACCEPTANCE_SEED})
local observed = sd.rng.get_seed()
local zero_ok = pcall(sd.rng.set_seed, 0)
local large_ok = pcall(sd.rng.set_seed, 0x40000000)
local fraction_ok = pcall(sd.rng.set_seed, 1.5)
print("accepted=" .. tostring(accepted))
print("observed=" .. tostring(observed))
print("zero_rejected=" .. tostring(not zero_ok))
print("large_rejected=" .. tostring(not large_ok))
print("fraction_rejected=" .. tostring(not fraction_ok))
'''


def run(pipe_name: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, PROBE, timeout=12.0))
    expected = str(ACCEPTANCE_SEED)
    if values.get("accepted") != expected or values.get("observed") != expected:
        raise VerifyFailure(f"run seed did not round trip exactly: {values}")
    for field in ("zero_rejected", "large_rejected", "fraction_rejected"):
        if values.get(field) != "true":
            raise VerifyFailure(f"run seed validation did not reject {field}: {values}")
    return {"ok": True, "pipe": pipe_name, "seed": ACCEPTANCE_SEED, "values": values}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "pipe": args.pipe}
    try:
        result = run(args.pipe)
        return_code = 0
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
