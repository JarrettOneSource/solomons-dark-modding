#!/usr/bin/env python3
"""Executable Lua contract for participant-owned bot mana reserve state."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LUA_CONTRACT = ROOT / "tests" / "lua" / "bot_mana_reserve_contract.lua"


class BotManaReserveTests(unittest.TestCase):
    def test_reserve_and_choices_are_participant_scoped(self) -> None:
        lua = shutil.which("lua")
        if lua is None:
            self.skipTest("Lua interpreter is unavailable")
        result = subprocess.run(
            [lua, str(LUA_CONTRACT), str(ROOT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        values = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
        self.assertEqual(
            values,
            {
                "participant_scoped_choices": "true",
                "native_reserve_source": "true",
                "exact_boundaries": "true",
                "local_player_fallback": "true",
            },
        )


if __name__ == "__main__":
    unittest.main()
