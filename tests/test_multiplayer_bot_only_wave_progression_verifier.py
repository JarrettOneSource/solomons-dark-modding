from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_multiplayer_bot_only_wave_progression as verifier  # noqa: E402


BOT_ID = 0x1000000000000001


def completed_cycles() -> dict[str, object]:
    return {
        "startingWave": 2,
        "targetWave": 4,
        "spawns": [
            {"firstSeenWave": 2},
            {"firstSeenWave": 3},
        ],
        "targetSamples": [
            {"spawnWave": 2},
            {"spawnWave": 3},
        ],
        "waveTransitions": [
            {"fromWave": 2, "toWave": 3},
            {"fromWave": 3, "toWave": 4},
        ],
        "waveEvents": [
            {"kind": "started", "wave": 2},
            {"kind": "completed", "wave": 2},
            {"kind": "started", "wave": 3},
            {"kind": "completed", "wave": 3},
        ],
        "damage": [
            {
                "lane": "bot_to_enemy",
                "sourceParticipantId": BOT_ID,
                "combatWave": wave,
                "damage": 1.0,
            }
            for wave in (2, 3)
        ]
        + [
            {
                "lane": "enemy_to_participant",
                "targetParticipantId": BOT_ID,
                "combatWave": wave,
                "damage": 1.0,
            }
            for wave in (2, 3)
        ],
    }


class BotOnlyWaveProgressionVerifierTests(unittest.TestCase):
    def test_two_complete_cycles_require_both_pressure_lanes(self) -> None:
        verifier.assert_cycle_contract(completed_cycles(), BOT_ID)

    def test_counter_motion_cannot_replace_a_completed_event(self) -> None:
        evidence = completed_cycles()
        evidence["waveEvents"] = [
            row
            for row in evidence["waveEvents"]
            if not (row["kind"] == "completed" and row["wave"] == 3)
        ]

        with self.assertRaisesRegex(
            verifier.BotOnlyWaveFailure,
            "wave 3 completed event",
        ):
            verifier.assert_cycle_contract(evidence, BOT_ID)

    def test_enemy_damage_must_belong_to_each_completed_wave(self) -> None:
        evidence = completed_cycles()
        evidence["damage"] = [
            row
            for row in evidence["damage"]
            if not (
                row["lane"] == "enemy_to_participant"
                and row["combatWave"] == 3
            )
        ]

        with self.assertRaisesRegex(
            verifier.BotOnlyWaveFailure,
            "wave 3 enemy damage edge",
        ):
            verifier.assert_cycle_contract(evidence, BOT_ID)

    def test_bot_damage_must_belong_to_each_completed_wave(self) -> None:
        evidence = completed_cycles()
        evidence["damage"] = [
            row
            for row in evidence["damage"]
            if not (
                row["lane"] == "bot_to_enemy"
                and row["combatWave"] == 2
            )
        ]

        with self.assertRaisesRegex(
            verifier.BotOnlyWaveFailure,
            "wave 2 bot damage edge",
        ):
            verifier.assert_cycle_contract(evidence, BOT_ID)

    def test_proof_cycles_never_force_native_enemy_death(self) -> None:
        source = inspect.getsource(verifier.observe_cycles)
        self.assertNotIn("kill_one_native_enemy", source)
        self.assertNotIn("trigger_enemy_death", source)

    def test_game_over_accepts_the_atomic_post_run_roster_reset(self) -> None:
        self.assertTrue(
            verifier.stock_game_over_observed(
                {
                    "bot_count": "0",
                    "game_over_accepted_epoch": "1",
                    "game_over_dispatch_count": "1",
                }
            )
        )
        self.assertFalse(
            verifier.stock_game_over_observed(
                {
                    "bot_count": "1",
                    "bot.1.hp": "10",
                    "game_over_accepted_epoch": "0",
                    "game_over_dispatch_count": "0",
                }
            )
        )

    def test_fixture_is_one_melee_template(self) -> None:
        fixture = verifier.DEFAULT_WAVE_FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(
            sum(line.strip() == "WAVE" for line in fixture.splitlines()),
            1,
        )
        self.assertNotIn("SKELETONARCHER", fixture)
        self.assertEqual(fixture.count("SKELETON:FLAG_WEAK|FLAG_HPDOWN"), 1)

    def test_effective_schedule_preserves_the_retail_next_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "game" / "data"
            data.mkdir(parents=True)
            (data / "wave.txt").write_text(
                "WAVE\n\tNEXT:1\n\tSPAWN:2\n\tGROUP\n\t\tSPIDER\n\tENDWAVE\n"
                "WAVE\n\tNEXT:0\n\tSPAWN:3\n\tGROUP\n\t\tZOMBIE\n\tENDWAVE\n",
                encoding="ascii",
            )
            output = root / "effective-wave.txt"

            receipt = verifier.materialize_effective_wave_schedule(
                game_directory=root / "game",
                fixture_path=verifier.DEFAULT_WAVE_FIXTURE,
                output_path=output,
            )

            effective = output.read_text(encoding="ascii")
            self.assertEqual(receipt["record_count"], 2)
            self.assertEqual(receipt["next_graph"], ["1", "0"])
            self.assertEqual(receipt["spawn_delay_ticks"], 4096)
            self.assertEqual(
                sum(line == "WAVE" for line in effective.splitlines()),
                2,
            )
            self.assertEqual(effective.count("\tSPAWNDELAY:4096-4096\n"), 2)
            self.assertEqual(effective.count("\tNEXT:1\n"), 1)
            self.assertEqual(effective.count("\tNEXT:0\n"), 1)
            self.assertEqual(
                effective.count("SKELETON:FLAG_WEAK|FLAG_HPDOWN"),
                2,
            )


if __name__ == "__main__":
    unittest.main()
