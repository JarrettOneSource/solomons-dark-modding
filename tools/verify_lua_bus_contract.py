#!/usr/bin/env python3
"""Verify the static contract for the local cross-mod Lua bus."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "tests" / "re"


def main() -> int:
    sys.path.insert(0, str(TEST_ROOT))
    from static_lua_bus_contracts import (  # noqa: PLC0415
        test_lua_bus_is_manifest_resolved_bounded_and_local,
    )

    try:
        detail = test_lua_bus_is_manifest_resolved_bounded_and_local()
    except Exception as error:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return 1
    print(json.dumps({"ok": True, "detail": detail}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
