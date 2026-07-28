from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_multiplayer_host_death_continuity as verifier  # noqa: E402


def _input_sample(
    monotonic_ms: int,
    *,
    host_life: float,
    intent: float = 1.0,
    native: float = 1.0,
    gameplay: float = 1.0,
    control: float = 1.0,
    x: float = 0.0,
) -> dict[str, int | float]:
    return {
        "monotonic_ms": monotonic_ms,
        "host_life": host_life,
        "host_life_valid": 1,
        "intent_x": intent,
        "intent_y": 0.0,
        "native_x": native,
        "native_y": 0.0,
        "gameplay_x": gameplay,
        "gameplay_y": 0.0,
        "control_x": control,
        "control_y": 0.0,
        "x": x,
        "y": 0.0,
    }


class HostDeathContinuityVerifierTests(unittest.TestCase):
    def test_real_input_chain_passes_across_observed_host_death(self) -> None:
        samples = [
            _input_sample(
                timestamp,
                host_life=50.0 if timestamp < 600 else 0.0,
                x=timestamp / 20.0,
            )
            for timestamp in range(0, 1400, 100)
        ]

        analysis = verifier.analyze_survivor_input(samples)

        self.assertTrue(analysis["passed"])
        self.assertTrue(analysis["intent_before_death"])
        self.assertTrue(analysis["intent_after_death"])
        self.assertTrue(analysis["native_vector_before_death"])
        self.assertTrue(analysis["native_vector_after_death"])
        self.assertGreater(analysis["maximum_displacement"], 16.0)

    def test_input_intent_without_post_death_native_vector_fails(self) -> None:
        samples = [
            _input_sample(
                timestamp,
                host_life=50.0 if timestamp < 600 else 0.0,
                native=1.0 if timestamp < 600 else 0.0,
                x=timestamp / 20.0,
            )
            for timestamp in range(0, 1400, 100)
        ]

        analysis = verifier.analyze_survivor_input(samples)

        self.assertFalse(analysis["passed"])
        self.assertTrue(analysis["intent_after_death"])
        self.assertFalse(analysis["native_vector_after_death"])
        self.assertGreater(analysis["maximum_displacement"], 16.0)

    def test_enemy_motion_requires_net_displacement_not_jitter_path(self) -> None:
        samples = [
            {
                "monotonic_ms": index * 100,
                "local_address": 0x1234,
                "local_x": float(index % 2),
                "local_y": 0.0,
            }
            for index in range(40)
        ]

        motion = verifier._movement_summary(
            samples,
            start_ms=0,
            x_key="local_x",
            y_key="local_y",
        )

        self.assertGreater(motion["path_distance"], 16.0)
        self.assertEqual(motion["maximum_displacement"], 1.0)

    def test_terminal_damage_must_cover_all_three_segments(self) -> None:
        complete = verifier._terminal_damage_segment_coverage(
            [
                {"monotonic_ms": 5_000.0, "damage": 1.0},
                {"monotonic_ms": 25_000.0, "damage": 1.0},
                {"monotonic_ms": 50_000.0, "damage": 1.0},
            ],
            start_ms=0,
            end_ms=60_000,
        )
        incomplete = verifier._terminal_damage_segment_coverage(
            [
                {"monotonic_ms": 5_000.0, "damage": 1.0},
                {"monotonic_ms": 25_000.0, "damage": 1.0},
            ],
            start_ms=0,
            end_ms=60_000,
        )

        self.assertTrue(complete["complete"])
        self.assertFalse(incomplete["complete"])
        self.assertEqual(incomplete["covered_segments"], [0, 1])

    def test_unbound_pending_clone_is_not_simulation_eligible(self) -> None:
        common = {
            "network_actor_id": 17,
            "local_address": 0x1234,
            "binding_matched": 0,
            "binding_parked": 0,
            "binding_removed": 0,
        }

        summary = verifier._client_binding_summary(
            [
                {**common, "pending_initialize": 1},
                {**common, "pending_initialize": 0},
            ]
        )

        self.assertEqual(summary["unbound_sample_count"], 2)
        self.assertEqual(
            summary["simulation_eligible_unbound_sample_count"],
            1,
        )

    def test_death_window_state_regressions_are_counted(self) -> None:
        baseline = {
            "monotonic_ms": 900,
            "run_nonce": 7,
            "loading_run_nonce": 7,
            "loading_release_nonce": 7,
            "authority_participant_id": verifier.HOST_ID,
            "shared_pause_active": 0,
            "teardown_active": 0,
            "game_over_command_epoch": 0,
            "game_over_accepted_epoch": 0,
            "game_over_pending_dispatch": 0,
            "game_over_dispatch_count": 0,
            "session_state": "in-boneyard",
        }
        regression = {
            **baseline,
            "monotonic_ms": 2_100,
            "loading_release_nonce": 8,
            "authority_participant_id": verifier.CLIENT_ID,
            "shared_pause_active": 1,
            "teardown_active": 1,
            "game_over_command_epoch": 1,
            "session_state": "in-hub",
        }

        result = verifier._state_regression_summary(
            [baseline, regression],
            death_ms=1_000,
        )

        self.assertEqual(result["barrier_restart_count"], 1)
        self.assertEqual(result["authority_change_count"], 1)
        self.assertEqual(result["shared_pause_count"], 1)
        self.assertEqual(result["teardown_count"], 1)
        self.assertEqual(result["game_over_armed_count"], 1)
        self.assertEqual(result["wrong_session_state_count"], 1)


if __name__ == "__main__":
    unittest.main()
