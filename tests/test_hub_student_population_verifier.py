#!/usr/bin/env python3
"""Behavior tests for the connected hub Student population verifier."""

from __future__ import annotations

import ast
import inspect
import sys
import unittest
from pathlib import Path


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
    return {
        "scene": "hub",
        "registered_students": active,
        "pending_students": 0,
        "active_students": active,
        "stock_student_count": active,
        "authoritative_students": authoritative,
        "bound_students": bound,
        "unbound_students": active - bound,
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
    def test_accepts_rotating_stock_populations_after_surplus_retirement(
        self,
    ) -> None:
        samples = [
            sample(0, host_students=10, client_students=18, removed=0),
            sample(1, host_students=11, client_students=15, removed=1),
            sample(2, host_students=12, client_students=13, removed=2),
            sample(3, host_students=12, client_students=12, removed=2),
            sample(4, host_students=11, client_students=12, removed=2),
            sample(5, host_students=10, client_students=10, removed=3),
            sample(6, host_students=9, client_students=10, removed=3),
        ]

        aggregate = verifier.evaluate_samples(
            samples,
            warmup_samples=2,
        )

        self.assertEqual(aggregate["maximum_client_surplus"], 1)
        self.assertEqual(aggregate["student_retirement_total"], 3)
        self.assertEqual(aggregate["final_population_gap"], 1)

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
            "retained 10 surplus Students",
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

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "bindings did not converge often enough",
        ):
            verifier.evaluate_samples(samples, warmup_samples=1)

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
