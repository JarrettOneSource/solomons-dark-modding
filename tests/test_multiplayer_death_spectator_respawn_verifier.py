#!/usr/bin/env python3
"""Behavior tests for the multiplayer death/spectator/respawn verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


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

    def test_explicit_ports_keep_the_verifier_in_its_assigned_group(
        self,
    ) -> None:
        with mock.patch.object(verifier, "_reserve_udp_ports") as reserve:
            ports = verifier._resolve_udp_ports(23111, 23112, 23113)

        self.assertEqual(ports, [23111, 23112, 23113])
        reserve.assert_not_called()

    def test_partial_or_duplicate_explicit_port_groups_are_rejected(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "all three ports",
        ):
            verifier._resolve_udp_ports(23111, None, 23113)
        with self.assertRaisesRegex(
            ValueError,
            "must be distinct",
        ):
            verifier._resolve_udp_ports(23111, 23111, 23113)

    def test_death_presentation_stays_in_run_without_game_over_surface(self) -> None:
        values = {
            "active": "true",
            "phase": "DeathPresentation",
            "presentation_remaining_ms": "4875",
            "scene": "testrun",
            "game_over_surface": "false",
            "hp": "0.001",
            "anim_drive_state": "1",
            "display_text": "",
        }
        self.assertTrue(verifier.death_presentation_state_matches(values))
        values["game_over_surface"] = "true"
        self.assertFalse(verifier.death_presentation_state_matches(values))

    def test_death_animation_phase_matches_owner_and_observers(self) -> None:
        states = [
            {
                "materialized": "true",
                "hp": "0",
                "death_drive_state": "1",
                "death_presentation_ticks": "74",
                "authoritative_death_presentation_ticks": "74",
                "terminal_pending": "0",
                "presentation_active": "true",
            },
            {
                "materialized": "true",
                "hp": "0",
                "death_drive_state": "1",
                "death_presentation_ticks": "71",
                "authoritative_death_presentation_ticks": "71",
                "terminal_pending": "0",
                "presentation_active": "true",
            },
            {
                "materialized": "true",
                "hp": "0",
                "death_drive_state": "1",
                "death_presentation_ticks": "69",
                "authoritative_death_presentation_ticks": "69",
                "terminal_pending": "0",
                "presentation_active": "true",
            },
        ]
        self.assertTrue(
            verifier.death_animation_sync_matches(
                states,
                presentation_active=True,
            )
        )
        states[1]["death_drive_state"] = "0"
        self.assertFalse(
            verifier.death_animation_sync_matches(
                states,
                presentation_active=True,
            )
        )
        states[1]["death_drive_state"] = "1"
        states[1][
            "authoritative_death_presentation_ticks"
        ] = "120"
        self.assertFalse(
            verifier.death_animation_clock_sync_matches(states)
        )

    def test_staff_drop_trace_is_exactly_once_on_owner_only(self) -> None:
        states = {
            "host": {
                "death_transition_hits": "1",
                "staff_drop_hits": "1",
            },
            "client": {
                "death_transition_hits": "0",
                "staff_drop_hits": "0",
            },
            "third": {
                "death_transition_hits": "0",
                "staff_drop_hits": "0",
            },
        }
        self.assertTrue(
            verifier.staff_drop_once_matches(
                states,
                owner_label="host",
            )
        )
        states["host"]["staff_drop_hits"] = "2"
        self.assertFalse(
            verifier.staff_drop_once_matches(
                states,
                owner_label="host",
            )
        )

    def test_host_lethal_fixture_preserves_a_live_native_damage_target(
        self,
    ) -> None:
        values = {
            "after.hp": "1",
            "after.max_hp": "50",
            "after.anim_drive_state": "0",
        }
        with mock.patch.object(
            verifier,
            "set_local_player_vitals",
            return_value=values,
        ) as set_vitals:
            actual = verifier._establish_host_lethal_precondition(
                r"\\.\pipe\host"
            )

        self.assertEqual(actual, values)
        set_vitals.assert_called_once_with(
            r"\\.\pipe\host",
            1.0,
            50.0,
            mp=50.0,
            max_mp=50.0,
        )

    def test_lethal_trials_target_local_host_and_remote_client(self) -> None:
        with mock.patch.object(
            verifier,
            "invoke_native_magic_hit_trial",
            return_value={"hp_after": -1.0},
        ) as invoke:
            verifier._apply_authoritative_host_lethal_hit(
                r"\\.\pipe\host"
            )
            verifier._apply_authoritative_client_lethal_hit(
                r"\\.\pipe\host"
            )

        self.assertEqual(
            [
                call.kwargs["target_participant_id"]
                for call in invoke.call_args_list
            ],
            [0, verifier.CLIENT_ID],
        )

    def test_grace_expiry_clears_red_effect_without_clearing_dead_state(self) -> None:
        states = [
            {
                "materialized": "true",
                "hp": "0",
                "death_drive_state": "1",
                "death_presentation_ticks": "150",
                "authoritative_death_presentation_ticks": "150",
                "terminal_pending": "0",
                "presentation_active": "false",
                "red_effect_active": "false",
            },
            {
                "materialized": "true",
                "hp": "0",
                "death_drive_state": "1",
                "death_presentation_ticks": "150",
                "authoritative_death_presentation_ticks": "150",
                "terminal_pending": "0",
                "presentation_active": "false",
                "red_effect_active": "false",
            },
        ]
        self.assertTrue(
            verifier.death_animation_sync_matches(
                states,
                presentation_active=False,
            )
        )
        states[0]["red_effect_active"] = "true"
        self.assertFalse(
            verifier.death_animation_sync_matches(
                states,
                presentation_active=False,
            )
        )

    def test_red_effect_must_appear_during_grace_then_clear(self) -> None:
        values = {
            "death_drive_state": "1",
            "death_presentation_ticks": "150",
            "authoritative_death_presentation_ticks": "151",
            "presentation_active": "true",
            "red_effect_active": "true",
        }
        self.assertTrue(
            verifier.red_death_effect_matches(values, active=True)
        )
        values.update(
            {
                "death_presentation_ticks": "150",
                "authoritative_death_presentation_ticks": "150",
                "presentation_active": "false",
                "red_effect_active": "false",
            }
        )
        self.assertTrue(
            verifier.red_death_effect_matches(values, active=False)
        )

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
            "death_presentation_ticks": "0",
            "terminal_pending": "0",
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
