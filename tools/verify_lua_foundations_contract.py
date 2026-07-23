#!/usr/bin/env python3
"""Verify the static contracts for the Lua RNG and navigation foundations."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "tests" / "re"


def main() -> int:
    sys.path.insert(0, str(TEST_ROOT))
    from static_lua_foundations_contracts import (  # noqa: PLC0415
        test_lua_nav_is_bounded_read_only_and_native_backed,
        test_lua_run_seed_is_authority_owned_and_native_applied,
    )

    try:
        details = [
            test_lua_run_seed_is_authority_owned_and_native_applied(),
            test_lua_nav_is_bounded_read_only_and_native_backed(),
        ]
    except Exception as error:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return 1
    print(json.dumps({"ok": True, "details": details}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
