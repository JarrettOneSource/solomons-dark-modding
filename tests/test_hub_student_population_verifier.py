#!/usr/bin/env python3
"""Behavior tests for the connected hub Student population verifier."""

from __future__ import annotations

import ast
import inspect
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_hub_student_population_sync as verifier  # noqa: E402


def endpoint(
    active: int,
    *,
    authoritative: int,
    bound: int,
    removed: int,
) -> dict[str, object]:
    authoritative_ids = list(range(1, authoritative + 1))
    bound_ids = authoritative_ids[:bound]
    return {
        "scene": "hub",
        "registered_students": active,
        "pending_students": 0,
        "active_students": active,
        "stock_student_count": active,
        "authoritative_students": authoritative,
        "bound_students": bound,
        "unbound_students": active - bound,
        "authoritative_student_ids": authoritative_ids,
        "bound_student_ids": bound_ids,
        "missing_student_ids": authoritative_ids[bound:],
        "snapshot_sequence": 1,
        "apply_sequence": 1,
        "apply_source_snapshot_age_ms": 0,
        "removed_actor_total_count": removed,
        "failed_remove_actor_total_count": 0,
    }


def sample(
    index: int,
    *,
    host_students: int,
    client_students: int,
    removed: int,
) -> dict[str, object]:
    return {
        "index": index,
        "host": endpoint(
            host_students,
            authoritative=host_students,
            bound=host_students,
            removed=0,
        ),
        "client": endpoint(
            client_students,
            authoritative=host_students,
            bound=min(host_students, client_students),
            removed=removed,
        ),
    }


class HubStudentPopulationVerifierTests(unittest.TestCase):
    def test_waits_past_a_late_gap_for_three_exact_identity_samples(
        self,
    ) -> None:
        samples = [
            sample(0, host_students=10, client_students=18, removed=0),
            sample(1, host_students=11, client_students=15, removed=1),
            sample(2, host_students=12, client_students=11, removed=2),
            sample(3, host_students=12, client_students=12, removed=2),
            sample(4, host_students=12, client_students=12, removed=2),
            sample(5, host_students=12, client_students=11, removed=2),
            sample(6, host_students=12, client_students=12, removed=3),
            sample(7, host_students=12, client_students=12, removed=3),
            sample(8, host_students=12, client_students=12, removed=3),
        ]

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "3 consecutive exact",
        ):
            verifier.evaluate_samples(
                samples[:-1],
                warmup_samples=2,
            )

        aggregate = verifier.evaluate_samples(
            samples,
            warmup_samples=2,
        )

        self.assertEqual(aggregate["consecutive_converged_sample_count"], 3)
        self.assertEqual(aggregate["student_retirement_total"], 3)
        self.assertEqual(aggregate["final_population_gap"], 0)

    def test_rejects_a_doubled_connected_client_population(self) -> None:
        samples = [
            sample(
                index,
                host_students=10,
                client_students=20,
                removed=1,
            )
            for index in range(5)
        ]

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "3 consecutive exact",
        ):
            verifier.evaluate_samples(samples, warmup_samples=1)

    def test_rejects_stock_counter_drift(self) -> None:
        samples = [
            sample(
                index,
                host_students=10,
                client_students=10,
                removed=1,
            )
            for index in range(4)
        ]
        client = samples[-1]["client"]
        assert isinstance(client, dict)
        client["stock_student_count"] = 20

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "stock Student counter 20 does not match active population 10",
        ):
            verifier.evaluate_samples(samples, warmup_samples=1)

    def test_rejects_unbound_students_that_never_retire(self) -> None:
        samples = [
            sample(
                index,
                host_students=10,
                client_students=10,
                removed=1,
            )
            for index in range(5)
        ]
        for row in samples:
            client = row["client"]
            assert isinstance(client, dict)
            client["bound_students"] = 5
            client["unbound_students"] = 5
            client["bound_student_ids"] = list(range(1, 6))
            client["missing_student_ids"] = list(range(6, 11))

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "3 consecutive exact",
        ):
            verifier.evaluate_samples(samples, warmup_samples=1)

    @mock.patch.object(verifier.time, "sleep")
    @mock.patch.object(verifier.time, "monotonic", return_value=0.0)
    @mock.patch.object(verifier, "stop_game_processes")
    @mock.patch.object(verifier, "game_process_ids", return_value=[111, 222])
    @mock.patch.object(
        verifier,
        "launch_pair",
        return_value={
            "hostLuaPipe": "host-pipe",
            "clientLuaPipe": "client-pipe",
        },
    )
    def test_live_gate_observes_until_late_gap_reconverges(
        self,
        _launch_pair: mock.Mock,
        _game_process_ids: mock.Mock,
        stop_game_processes: mock.Mock,
        _monotonic: mock.Mock,
        _sleep: mock.Mock,
    ) -> None:
        observations = [
            sample(
                index,
                host_students=10,
                client_students=9,
                removed=1,
            )
            for index in range(9)
        ]
        observations.extend(
            [
                sample(9, host_students=10, client_students=10, removed=1),
                sample(10, host_students=10, client_students=10, removed=1),
                sample(11, host_students=10, client_students=9, removed=1),
                sample(12, host_students=10, client_students=10, removed=1),
                sample(13, host_students=10, client_students=10, removed=1),
                sample(14, host_students=10, client_students=10, removed=1),
            ]
        )

        with (
            mock.patch("builtins.print"),
            mock.patch.object(
                verifier,
                "capture_sample",
                side_effect=observations,
            ),
        ):
            result = verifier.run_live_verification(
                convergence_timeout=30.0,
                confirmation_samples=3,
                warmup_samples=3,
                interval=0.0,
                timeout=5.0,
                instance_prefix="test-student-convergence",
                host_port=31001,
                client_port=31002,
                game_directory=None,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["samples"]), 15)
        self.assertEqual(result["aggregate"]["final_population_gap"], 0)
        self.assertEqual(
            result["aggregate"]["consecutive_converged_sample_count"],
            3,
        )
        stop_game_processes.assert_called_once_with([111, 222])

    def test_live_gate_fails_once_at_its_bounded_deadline(self) -> None:
        observation = sample(
            0,
            host_students=10,
            client_students=10,
            removed=1,
        )
        launch = {
            "hostLuaPipe": "host-pipe",
            "clientLuaPipe": "client-pipe",
        }

        with (
            mock.patch("builtins.print"),
            mock.patch.object(verifier, "launch_pair", return_value=launch),
            mock.patch.object(
                verifier,
                "game_process_ids",
                return_value=[111, 222],
            ),
            mock.patch.object(
                verifier,
                "capture_sample",
                return_value=observation,
            ),
            mock.patch.object(
                verifier.time,
                "monotonic",
                side_effect=[0.0, 0.0, 1.1, 1.1],
            ),
            mock.patch.object(verifier.time, "sleep"),
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run_live_verification(
                convergence_timeout=1.0,
                confirmation_samples=1,
                warmup_samples=0,
                interval=0.0,
                timeout=5.0,
                instance_prefix="test-student-deadline",
                host_port=31001,
                client_port=31002,
                game_directory=None,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(len(result["samples"]), 1)
        self.assertIn("within 1s", result["error"])
        self.assertEqual(result["aggregate"]["final_population_gap"], 0)
        stop.assert_called_once_with([111, 222])

    def test_live_pair_uses_an_isolated_instance_and_exact_pid_cleanup(
        self,
    ) -> None:
        source = inspect.getsource(verifier.run_live_verification)
        tree = ast.parse(source)
        launch_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "launch_pair"
        ]
        self.assertEqual(len(launch_calls), 1)
        keywords = {
            keyword.arg: keyword.value
            for keyword in launch_calls[0].keywords
            if keyword.arg is not None
        }
        for name in (
            "tile_windows",
            "allow_focus_steal",
            "kill_existing",
        ):
            value = keywords.get(name)
            self.assertIsInstance(value, ast.Constant)
            self.assertIs(value.value, False)
        self.assertIn("two exact process IDs", source)
        self.assertIn("stop_game_processes(process_ids", source)
        self.assertNotIn("stop_games(", source)


if __name__ == "__main__":
    unittest.main()
