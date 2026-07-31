#!/usr/bin/env python3
"""Contracts for the local-player bot-brain adapter."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LUA_CONTRACT = ROOT / "tests" / "lua" / "bot_play_for_me_contract.lua"


class BotPlayForMeTests(unittest.TestCase):
    def test_local_player_adapter_uses_shared_brain_and_cleans_release(
        self,
    ) -> None:
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
        for key in (
            "takeover_path",
            "movement_path",
            "primary_path",
            "secondary_path",
            "indicator_path",
            "skill_choice_path",
            "loot_path",
            "death_respawn_path",
            "clean_release",
        ):
            self.assertEqual(values.get(key), "true", result.stdout)
        self.assertGreaterEqual(
            int(values.get("shared_brain_thinks", "0")),
            4,
        )


if __name__ == "__main__":
    unittest.main()
