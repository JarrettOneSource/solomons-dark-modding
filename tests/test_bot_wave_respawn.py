#!/usr/bin/env python3
"""Contracts for the native synthetic wave-respawn verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_bot_wave_respawn as respawn  # noqa: E402


def state(
    *,
    actor: int,
    progression: int,
    hp: float,
    epoch: int,
    presentation_flags: int,
) -> dict[str, str]:
    return {
        "found": "true",
        "id": "42",
        "name": "Ember",
        "materialized": "true",
        "in_run": "true",
        "run_nonce": "9",
        "gameplay_slot": "1",
        "actor": str(actor),
        "progression": str(progression),
        "hp": str(hp),
        "max_hp": "100",
        "mp": "80",
        "max_mp": "80",
        "x": "10",
        "y": "20",
        "actor_x": "10",
        "actor_y": "20",
        "collision_radius": "25",
        "move_step_scale": "4",
        "local_player_x": "10",
        "local_player_y": "20",
        "spawn_nav_traversable": "true",
        "actor_nav_traversable": "true",
        "grid_member": "1" if hp > 0 else "0",
        "grid_cell": "123" if hp > 0 else "0",
        "terminal_pending": "0",
        "anim_drive": "7" if hp <= 0 else "0",
        "presentation_flags": str(presentation_flags),
        "death_tick": "180" if hp <= 0 else "0",
        "respawn_epoch": str(epoch),
        "respawn_wave": "1" if epoch else "0",
        "first_respawn_epoch": str(epoch),
        "first_respawn_actor": str(actor if epoch else 0),
        "first_respawn_progression": str(
            progression if epoch else 0
        ),
        "first_respawn_hp": str(hp if epoch else 0),
        "first_respawn_max_hp": "100" if epoch else "0",
        "first_respawn_mp": "80" if epoch else "0",
        "first_respawn_max_mp": "80" if epoch else "0",
        "spawn_valid": "true",
        "spawn_x": "10",
        "spawn_y": "20",
        "nameplate_id": "42",
        "nameplate_name": "Ember",
        "nameplate_health_ratio": "1" if hp > 0 else "0",
    }


class BotWaveRespawnTests(unittest.TestCase):
    def test_retail_gate_is_selected_by_native_route_geometry(self) -> None:
        gate = respawn.select_retail_gate(
            (326.0, 150.0),
            (799.0, 984.0),
            [
                {
                    "start": (264.5, 300.0),
                    "end": (324.7, 294.3),
                    "midpoint": (294.6, 297.15),
                },
                {
                    "start": (327.0, 301.1),
                    "end": (387.5, 300.0),
                    "midpoint": (357.25, 300.55),
                },
            ],
        )
        self.assertAlmostEqual(gate["midpoint"][0], 325.925, places=2)
        self.assertGreater(gate["routeUnit"][1], 0.9)

    def test_transition_preserves_each_peer_actor_and_epoch(self) -> None:
        host_dead = state(
            actor=100,
            progression=200,
            hp=0,
            epoch=0,
            presentation_flags=1,
        )
        client_dead = state(
            actor=300,
            progression=400,
            hp=0,
            epoch=0,
            presentation_flags=1,
        )
        host_alive = state(
            actor=100,
            progression=200,
            hp=100,
            epoch=1,
            presentation_flags=0,
        )
        client_alive = state(
            actor=300,
            progression=400,
            hp=100,
            epoch=1,
            presentation_flags=0,
        )
        contract = respawn.validate_respawn_transition(
            host_dead,
            client_dead,
            host_alive,
            client_alive,
        )
        self.assertEqual(contract["epoch"], 1)
        self.assertTrue(contract["clientActorPreserved"])

    def test_transition_rejects_replacement_and_bad_hp_bar(self) -> None:
        dead = state(
            actor=100,
            progression=200,
            hp=0,
            epoch=0,
            presentation_flags=1,
        )
        alive = state(
            actor=101,
            progression=200,
            hp=100,
            epoch=1,
            presentation_flags=0,
        )
        with self.assertRaisesRegex(
            respawn.RespawnVerificationFailure,
            "replaced the actor/progression",
        ):
            respawn.validate_respawn_transition(
                dead,
                dead,
                alive,
                alive,
            )

    def test_transition_rejects_destroyed_move_step_scale(self) -> None:
        dead = state(
            actor=100,
            progression=200,
            hp=0,
            epoch=0,
            presentation_flags=1,
        )
        alive = state(
            actor=100,
            progression=200,
            hp=100,
            epoch=1,
            presentation_flags=0,
        )
        alive["move_step_scale"] = "0"
        with self.assertRaisesRegex(
            respawn.RespawnVerificationFailure,
            "move-step scale",
        ):
            respawn.validate_respawn_transition(
                dead,
                dead,
                alive,
                alive,
            )

    def test_transition_rejects_peer_respawn_placement_divergence(
        self,
    ) -> None:
        dead = state(
            actor=100,
            progression=200,
            hp=0,
            epoch=0,
            presentation_flags=1,
        )
        alive = state(
            actor=100,
            progression=200,
            hp=100,
            epoch=1,
            presentation_flags=0,
        )
        client_alive = dict(alive)
        client_alive["actor_y"] = "200"
        with self.assertRaisesRegex(
            respawn.RespawnVerificationFailure,
            "did not converge on respawn placement",
        ):
            respawn.validate_respawn_transition(
                dead,
                dead,
                alive,
                client_alive,
            )

    def test_transition_allows_living_local_players_to_stay_apart(
        self,
    ) -> None:
        dead = state(
            actor=100,
            progression=200,
            hp=0,
            epoch=0,
            presentation_flags=1,
        )
        host_alive = state(
            actor=100,
            progression=200,
            hp=100,
            epoch=1,
            presentation_flags=0,
        )
        client_alive = dict(host_alive)
        host_alive["local_player_x"] = "900"
        host_alive["local_player_y"] = "1600"
        client_alive["local_player_x"] = "1800"
        client_alive["local_player_y"] = "2900"
        contract = respawn.validate_respawn_transition(
            dead,
            dead,
            host_alive,
            client_alive,
        )
        self.assertTrue(contract["peerRespawnPlacementConverged"])
        self.assertEqual(contract["peerRespawnPlacementDelta"], 0)

    def test_transition_rejects_missing_full_first_respawn_sample(
        self,
    ) -> None:
        dead = state(
            actor=100,
            progression=200,
            hp=0,
            epoch=0,
            presentation_flags=1,
        )
        alive = state(
            actor=100,
            progression=200,
            hp=100,
            epoch=1,
            presentation_flags=0,
        )
        alive["first_respawn_mp"] = "68"
        with self.assertRaisesRegex(
            respawn.RespawnVerificationFailure,
            "first publish full native respawn resources",
        ):
            respawn.validate_respawn_transition(
                dead,
                dead,
                alive,
                alive,
            )


if __name__ == "__main__":
    unittest.main()
