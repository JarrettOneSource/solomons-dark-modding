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
    for sample_index in range(40):
        actors = {
            1000 + actor_index: _actor(
                sample_index * (2.0 + actor_index * 0.1)
            )
            for actor_index in range(6)
        }
        received_ms = 1000 + sample_index * 70
        if stalled and sample_index >= 20:
            received_ms += 500
        host.append(
            {
                "monotonic_ms": received_ms,
                "received_ms": received_ms,
                "sequence": 10 + sample_index,
                "source_age_ms": 150,
                "unbound_local_count": 0,
                "actors": actors,
            }
        )
        client.append(
            {
                "monotonic_ms": received_ms + 15,
                "received_ms": received_ms + 15,
                "sequence": 10 + sample_index,
                "source_age_ms": 150,
                "unbound_local_count": 0,
                "actors": {
                    network_id: dict(actor)
                    for network_id, actor in actors.items()
                },
            }
        )
    return host, client


def _time_aligned_samples(
    *,
    lag_samples: int = 0,
    teleport_sample: int | None = None,
    ghost_range: range | None = None,
    source_age_ms: int = 150,
) -> tuple[list[dict], list[dict]]:
    host: list[dict] = []
    client: list[dict] = []
    for sample_index in range(120):
        sampled_ms = 1000 + sample_index * 16
        host_actors = {}
        client_actors = {}
        for actor_index in range(6):
            network_id = 1000 + actor_index
            speed = 1.8 + actor_index * 0.02
            host_position = sample_index * speed
            host_actor = _actor(host_position)
            client_actor = _actor(
                (sample_index - lag_samples) * speed
            )
            if teleport_sample is not None:
                if sample_index == teleport_sample:
                    client_actor["local_x"] = (
                        float(client_actor["local_x"]) + 50.0
                    )
                elif sample_index == teleport_sample + 1:
                    client_actor["local_x"] = float(client_actor["local_x"])
            if (
                ghost_range is not None
                and sample_index in ghost_range
                and actor_index == 0
            ):
                client_actor["local_x"] = None
                client_actor["local_y"] = None
                client_actor["local_hp"] = None
                client_actor["local_dead"] = None
                client_actor["local_anim"] = None
            host_actors[network_id] = host_actor
            client_actor["x"] = host_actor["x"]
            client_actor["y"] = host_actor["y"]
            client_actors[network_id] = client_actor
        common = {
            "monotonic_ms": sampled_ms,
            "received_ms": sampled_ms,
            "sequence": 10 + sample_index,
            "source_age_ms": source_age_ms,
            "unbound_local_count": 0,
        }
        host.append({**common, "actors": host_actors})
        client.append({**common, "actors": client_actors})
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

    def test_native_fidelity_exposes_lag_hidden_by_sequence_pairing(
        self,
    ) -> None:
        host, client = _time_aligned_samples(lag_samples=10)
        analysis = verifier.analyze_enemy_sync(host, client)
        self.assertEqual(
            analysis["maximum_host_client_position_error"],
            0.0,
        )
        self.assertLessEqual(
            analysis["p95_client_clone_position_error"],
            verifier.P95_CLIENT_CLONE_POSITION_ERROR,
        )
        self.assertGreaterEqual(
            analysis["native_fidelity"]["p50_native_lag_ms"],
            144.0,
        )
        self.assertGreater(
            analysis["native_fidelity"]["p95_native_position_error"],
            17.0,
        )

    def test_native_fidelity_rejects_adaptive_delay_hidden_by_old_gate(
        self,
    ) -> None:
        host, client = _time_aligned_samples(
            lag_samples=10,
            source_age_ms=305,
        )
        measured = verifier.analyze_enemy_sync(
            host,
            client,
            enforce_bounds=False,
        )
        self.assertEqual(
            measured["maximum_host_client_position_error"],
            0.0,
        )
        self.assertLessEqual(
            measured["p95_client_clone_position_error"],
            verifier.P95_CLIENT_CLONE_POSITION_ERROR,
        )
        self.assertIn(
            "client enemy presentation source age exceeded its p95 bound",
            measured["failures"],
        )
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "presentation source age",
        ):
            verifier.analyze_enemy_sync(host, client)

    def test_native_fidelity_counts_teleport_and_rubber_band(
        self,
    ) -> None:
        host, client = _time_aligned_samples(teleport_sample=30)
        analysis = verifier.analyze_enemy_sync(
            host,
            client,
            enforce_bounds=False,
        )
        self.assertGreater(
            analysis["native_fidelity"]["teleport_event_count"],
            0,
        )
        self.assertGreater(
            analysis["native_fidelity"]["rubber_band_event_count"],
            0,
        )

    def test_native_fidelity_counts_persistent_missing_clone_as_ghost(
        self,
    ) -> None:
        host, client = _time_aligned_samples(
            ghost_range=range(70, 110),
        )
        analysis = verifier.analyze_enemy_sync(
            host,
            client,
            enforce_bounds=False,
        )
        self.assertGreater(
            analysis["native_fidelity"]["ghost_sample_count"],
            0,
        )
        self.assertGreater(
            analysis["native_fidelity"]["ghost_episode_count"],
            0,
        )
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "enemy ghosts persisted",
        ):
            verifier.analyze_enemy_sync(host, client)

    def test_native_fidelity_allows_bounded_spawn_convergence(self) -> None:
        host, client = _time_aligned_samples(
            ghost_range=range(70, 76),
        )
        analysis = verifier.analyze_enemy_sync(host, client)
        self.assertGreater(
            analysis["native_fidelity"]["ghost_sample_count"],
            0,
        )
        self.assertEqual(
            analysis["native_fidelity"]["ghost_episode_count"],
            0,
        )

    def test_native_fidelity_ignores_initial_materialization(self) -> None:
        host, client = _time_aligned_samples(
            ghost_range=range(0, 6),
        )
        analysis = verifier.analyze_enemy_sync(host, client)
        self.assertEqual(
            analysis["native_fidelity"]["ghost_episode_count"],
            0,
        )

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
