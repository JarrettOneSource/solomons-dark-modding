#!/usr/bin/env python3
"""Behavior tests for the isolated bot-polish live verifier."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_bot_polish as verifier  # noqa: E402


def complete_probe() -> dict[str, str]:
    values = {
        "scene": "hub",
        "authority": "true",
        "count": "2",
        "brain.active": "2",
        "brain.desired": "2",
    }
    rows = (
        (
            "Ember",
            101,
            0,
            2,
            "skirmisher",
            "arcane",
            7,
            "A1B2C3D4",
            "01020304",
        ),
        (
            "Brook",
            102,
            1,
            0,
            "guardian",
            "mind",
            6,
            "10203040",
            "05060708",
        ),
    )
    for index, row in enumerate(rows, start=1):
        (
            name,
            participant_id,
            element_id,
            discipline_id,
            behavior,
            discipline,
            selected_row,
            robe_color,
            hat_color,
        ) = row
        prefix = f"bot.{index}."
        values.update(
            {
                prefix + "id": str(participant_id),
                prefix + "name": name,
                prefix + "element": str(element_id),
                prefix + "discipline": str(discipline_id),
                prefix + "behavior": behavior,
                prefix + "debug_discipline": discipline,
                prefix + "slot": str(index),
                prefix + "materialized": "true",
                prefix + "actor": str(200 + index),
                prefix + "x": str(10 * index),
                prefix + "y": str(20 * index),
                prefix + "robe.type": str(0x1B5E),
                prefix + "robe.color_valid": "true",
                prefix + "robe.color": robe_color,
                prefix + "hat.type": str(0x1B5D),
                prefix + "hat.color_valid": "true",
                prefix + "hat.color": hat_color,
                prefix + "staff.type": str(0x1B5C),
                prefix + "nameplate": name,
                prefix + "progression": str(300 + index),
                prefix + "book.table": str(400 + index),
                prefix + "book.count": "100",
                prefix + "book.selected": str(selected_row),
            }
        )
        for skill_row in (5, 6, 7):
            values[prefix + f"book.{skill_row}.active"] = "1"
            values[prefix + f"book.{skill_row}.effective"] = "1"
            values[prefix + f"book.{skill_row}.definition"] = str(
                500 + skill_row
            )
            values[prefix + f"book.{skill_row}.maximum"] = "1"
    return values


class BotPolishVerifierTests(unittest.TestCase):
    def test_isolation_and_process_contract_is_fixed(self) -> None:
        self.assertEqual(verifier.INSTANCE_PREFIX, "botpolish")
        self.assertEqual(verifier.HOST_PORT, 50011)
        self.assertEqual(verifier.CLIENT_PORT, 50012)
        self.assertEqual(verifier.EXACT_MOD_ID, "bot.brain")
        self.assertEqual(verifier.CLIENT_NAME, "client B")
        source = (TOOLS_ROOT / "verify_bot_polish.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("enable_audio=False", source)
        self.assertIn("__botpolish_survival_guard", source)
        self.assertIn('"scope": "HP only; movement and waves unchanged"', source)
        self.assertIn("stop_exact_game_processes(launch)", source)
        self.assertNotIn("stop_game_processes(", source)
        self.assertNotIn("test_wave_override=", source)

    def test_visual_and_native_discipline_probe_requires_every_lane(self) -> None:
        values = complete_probe()
        self.assertTrue(verifier.valid_bot_probe(values))
        agreement = verifier.assert_peer_visual_agreement(values, values)
        self.assertEqual(
            agreement["host"]["Ember"]["selectedRow"],
            7,
        )
        values["bot.2.robe.color"] = values["bot.1.robe.color"]
        self.assertFalse(verifier.valid_bot_probe(values))

    def test_stuck_log_parser_preserves_window_and_landing(self) -> None:
        text = (
            "[bots] native spawn placement accepted. bot_id=101 "
            "scene=Run phase=stuck_teleport anchor_x=10.000000 "
            "anchor_y=20.000000 resolved_x=35.000000 "
            "resolved_y=20.000000 radius=25.000000 primary_mask=0x1 "
            "reservation_count=0 probe_count=9 search_distance=25.000000 "
            "search_bound=300.000000 basic_result=0 extended_result=0\n"
            "[bots] stuck teleport. bot_id=101 actor=0x123 "
            "target=(10.000000, 20.000000) "
            "landing=(35.000000, 20.000000) window_ms=30017 "
            "search_distance=25.000000\n"
        )
        rows = verifier.stuck_rows(text, 101)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["windowMs"], 30017)
        self.assertEqual(rows[0]["landingX"], 35.0)
        placement = verifier.accepted_stuck_placement(text, 101)
        self.assertIsNotNone(placement)
        assert placement is not None
        self.assertEqual(placement["probeCount"], 9)
        self.assertEqual(placement["basicResult"], 0)
        self.assertEqual(placement["extendedResult"], 0)

    def test_log_tail_uses_byte_offsets_for_windows_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loader.log"
            prefix = "before\r\n".encode()
            tail = "after \u2603\r\n".encode()
            path.write_bytes(prefix + tail)
            self.assertEqual(
                verifier.read_log_since(path, len(prefix)),
                "after \u2603\r\n",
            )

    def test_four_slot_status_requires_two_humans_and_two_bots(self) -> None:
        status = {
            "enabled": True,
            "maxParticipants": 4,
            "members": [
                {"participantId": verifier.HOST_ID, "name": "host"},
                {
                    "participantId": verifier.CLIENT_ID,
                    "name": "client B",
                },
                {
                    "participantId": 101,
                    "name": "Ember",
                    "isBot": True,
                    "isSynthetic": True,
                },
                {
                    "participantId": 102,
                    "name": "Brook",
                    "isBot": True,
                    "isSynthetic": True,
                },
            ],
        }
        self.assertTrue(verifier.full_status(status))
        status["members"][3]["name"] = "Wrong"
        self.assertFalse(verifier.full_status(status))


if __name__ == "__main__":
    unittest.main()
