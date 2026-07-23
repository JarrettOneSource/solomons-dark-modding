#!/usr/bin/env python3
"""Behavior tests for the multiplayer death/spectator/respawn verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_multiplayer_death_spectator_respawn as verifier  # noqa: E402


class DeathSpectatorRespawnVerifierTests(unittest.TestCase):
    def test_generated_instance_prefix_stays_below_native_path_limit(self) -> None:
        prefix = verifier._default_instance_prefix()
        self.assertLessEqual(len(prefix), 18)
        self.assertRegex(prefix, r"^ds-[0-9a-f]+-[0-9a-f]{4}$")

    def test_death_presentation_stays_in_run_without_game_over_surface(self) -> None:
        values = {
            "active": "true",
            "phase": "DeathPresentation",
            "presentation_remaining_ms": "2875",
            "scene": "testrun",
            "game_over_surface": "false",
            "hp": "0",
            "anim_drive_state": "1",
            "display_text": "",
        }
        self.assertTrue(verifier.death_presentation_state_matches(values))
        values["game_over_surface"] = "true"
        self.assertFalse(verifier.death_presentation_state_matches(values))

    def test_spectator_state_requires_named_alive_target_and_local_camera(self) -> None:
        values = {
            "active": "true",
            "phase": "Spectating",
            "presentation_remaining_ms": "0",
            "target_participant_id": "0x2000000000000001",
            "target_name": "Host",
            "waiting_for_alive_target": "false",
            "target_alive": "true",
            "camera_focus_active": "true",
            "camera_center_x": "480.5",
            "camera_center_y": "320.25",
            "target_x": "480.5",
            "target_y": "320.25",
            "display_text": (
                "Spectating Host  |  Left / Right click: next player"
            ),
        }
        self.assertTrue(verifier.spectator_state_matches(values))
        values["target_alive"] = "false"
        self.assertFalse(verifier.spectator_state_matches(values))

    def test_respawn_state_requires_new_epoch_full_vitals_and_spawn_readback(self) -> None:
        values = {
            "active": "false",
            "phase": "Inactive",
            "last_applied_respawn_epoch": "7",
            "last_applied_respawn_wave": "3",
            "last_respawn_x": "128.0",
            "last_respawn_y": "256.0",
            "hp": "500.0",
            "max_hp": "500.0",
            "mp": "300.0",
            "max_mp": "300.0",
            "anim_drive_state": "0",
            "x": "128.0",
            "y": "256.0",
        }
        self.assertTrue(
            verifier.respawn_state_matches(
                values,
                previous_epoch=6,
                expected_wave=3,
            )
        )
        values["hp"] = "0"
        self.assertFalse(
            verifier.respawn_state_matches(
                values,
                previous_epoch=6,
                expected_wave=3,
            )
        )


if __name__ == "__main__":
    unittest.main()
