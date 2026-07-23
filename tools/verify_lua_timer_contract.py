#!/usr/bin/env python3
"""Verify the static contract for the Lua timer scheduler."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "tests" / "re"


def main() -> int:
    sys.path.insert(0, str(TEST_ROOT))
    from static_lua_timer_contracts import (  # noqa: PLC0415
        test_lua_timers_are_bounded_local_and_tick_driven,
    )

    try:
        detail = test_lua_timers_are_bounded_local_and_tick_driven()
    except Exception as error:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return 1
    print(json.dumps({"ok": True, "detail": detail}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
