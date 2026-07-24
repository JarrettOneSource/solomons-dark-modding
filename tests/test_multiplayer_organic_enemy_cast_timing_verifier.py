#!/usr/bin/env python3
"""Behavior tests for the organic enemy and Air timing verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_multiplayer_organic_enemy_cast_timing as verifier  # noqa: E402


def _actor(position: float) -> dict[str, object]:
    return {
        "x": position,
        "y": 0.0,
        "hp": 100.0,
        "dead": 0,
        "anim": 1,
        "target": verifier.HOST_ID,
        "local_x": position,
        "local_y": 0.0,
        "local_hp": 100.0,
        "local_dead": 0,
        "local_anim": 1,
    }


def _samples(*, stalled: bool = False) -> tuple[list[dict], list[dict]]:
    host: list[dict] = []
    client: list[dict] = []
    for sample_index in range(20):
        actors = {
            1000 + actor_index: _actor(
                sample_index * (2.0 + actor_index * 0.1)
            )
            for actor_index in range(6)
        }
        received_ms = 1000 + sample_index * 70
        if stalled and sample_index >= 10:
            received_ms += 500
        host.append(
            {
                "monotonic_ms": received_ms,
                "received_ms": received_ms,
                "sequence": 10 + sample_index,
                "actors": actors,
            }
        )
        client.append(
            {
                "monotonic_ms": received_ms + 15,
                "received_ms": received_ms + 15,
                "sequence": 10 + sample_index,
                "actors": {
                    network_id: dict(actor)
                    for network_id, actor in actors.items()
                },
            }
        )
    return host, client


class OrganicEnemyCastTimingVerifierTests(unittest.TestCase):
    def test_generated_instance_prefix_is_short_and_unique(self) -> None:
        prefix = verifier._default_instance_prefix()
        self.assertLessEqual(len(prefix), 18)
        self.assertRegex(prefix, r"^n82-[0-9a-f]+-[0-9a-f]{4}$")

    def test_multi_enemy_motion_analysis_accepts_bounded_organic_motion(
        self,
    ) -> None:
        host, client = _samples()
        analysis = verifier.analyze_enemy_sync(host, client)
        self.assertEqual(analysis["minimum_compared_enemy_count"], 6)
        self.assertGreaterEqual(analysis["moving_enemy_count"], 4)
        self.assertEqual(
            analysis["maximum_host_client_position_error"],
            0.0,
        )

    def test_multi_enemy_motion_analysis_rejects_generation_stalls(
        self,
    ) -> None:
        host, client = _samples(stalled=True)
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "motion stream stalled",
        ):
            verifier.analyze_enemy_sync(host, client)

    def test_air_cast_timing_uses_explicit_start_and_stop_edges(self) -> None:
        source = "\n".join(
            (
                "[2026-07-24 12:00:00.000] Multiplayer local cast sent. "
                f"participant_id={verifier.CLIENT_ID} cast_sequence=7 "
                "kind=primary phase=pressed skill_id=24",
                "[2026-07-24 12:00:00.200] Multiplayer local cast sent. "
                f"participant_id={verifier.CLIENT_ID} cast_sequence=7 "
                "kind=primary phase=released skill_id=24",
            )
        )
        observer = "\n".join(
            (
                "[2026-07-24 12:00:00.020] Multiplayer remote cast queued. "
                f"participant_id={verifier.CLIENT_ID} cast_sequence=7 "
                "phase=pressed skill_id=24",
                "[2026-07-24 12:00:00.225] Multiplayer remote cast input "
                f"release. participant_id={verifier.CLIENT_ID} "
                "cast_sequence=7 skill_id=24",
                "[2026-07-24 12:00:00.240] [bots] cast complete "
                f"(remote_input_released). bot_id={verifier.CLIENT_ID} "
                "remote_cast_sequence=7",
            )
        )
        analysis = verifier.analyze_air_cast_timing(
            source,
            observer,
            verifier.CLIENT_ID,
        )
        self.assertEqual(analysis["skill_id"], 24)
        self.assertEqual(analysis["start_latency_ms"], 20.0)
        self.assertEqual(analysis["stop_latency_ms"], 25.0)
        self.assertEqual(analysis["duration_error_ms"], 5.0)

    def test_air_cast_timing_rejects_delayed_release(self) -> None:
        source = "\n".join(
            (
                "[2026-07-24 12:00:00.000] Multiplayer local cast sent. "
                f"participant_id={verifier.CLIENT_ID} cast_sequence=7 "
                "phase=pressed skill_id=24",
                "[2026-07-24 12:00:00.200] Multiplayer local cast sent. "
                f"participant_id={verifier.CLIENT_ID} cast_sequence=7 "
                "phase=released skill_id=24",
            )
        )
        observer = "\n".join(
            (
                "[2026-07-24 12:00:00.020] Multiplayer remote cast queued. "
                f"participant_id={verifier.CLIENT_ID} cast_sequence=7 "
                "phase=pressed skill_id=24",
                "[2026-07-24 12:00:00.800] Multiplayer remote cast input "
                f"release. participant_id={verifier.CLIENT_ID} "
                "cast_sequence=7 skill_id=24",
                "[2026-07-24 12:00:00.820] [bots] cast complete "
                f"(remote_input_released). bot_id={verifier.CLIENT_ID} "
                "remote_cast_sequence=7",
            )
        )
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "stop latency",
        ):
            verifier.analyze_air_cast_timing(
                source,
                observer,
                verifier.CLIENT_ID,
            )


if __name__ == "__main__":
    unittest.main()
