#!/usr/bin/env python3
"""Tests for the two-peer Lua run-seed verifier."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_rng_multiplayer as verifier  # noqa: E402


class LuaRngMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _initial(*, authority: bool) -> dict[str, str]:
        return {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "capability": "true",
            "authority": "true" if authority else "false",
            "seed_nil": "true",
            "namespace_exact": "true",
        }

    @staticmethod
    def _converged(*, authority: bool) -> dict[str, str]:
        return {
            "authority": "true" if authority else "false",
            "local_seed": (
                str(verifier.ACCEPTANCE_SEED) if authority else "0"
            ),
            "authority_row_found": "true",
            "authority_run_nonce": str(verifier.ACCEPTANCE_SEED),
            "authority_scene_kind": "SharedHub",
        }

    @staticmethod
    def _applied(*, authority: bool) -> dict[str, str]:
        return {
            "authority": "true" if authority else "false",
            "seed": str(verifier.ACCEPTANCE_SEED),
            "owner_count": "1",
            "runtime_valid": "true",
            "in_run": "true",
            "run_nonce": str(verifier.ACCEPTANCE_SEED),
            "participant_scene_kind": "Run",
            "world_scene": "testrun",
            "set_rejected": "true",
            "authority_error": "false" if authority else "true",
            "in_run_error": "true" if authority else "false",
        }

    def test_initial_state_requires_exact_empty_rng_namespace(self) -> None:
        values = self._initial(authority=True)
        self.assertTrue(
            verifier.initial_state_matches(values, authority=True)
        )
        values["namespace_exact"] = "false"
        self.assertFalse(
            verifier.initial_state_matches(values, authority=True)
        )

    def test_applied_state_requires_exact_nonce_and_rejection_reason(self) -> None:
        values = self._applied(authority=False)
        self.assertTrue(verifier.run_state_matches(values, authority=False))
        values["run_nonce"] = str(verifier.ACCEPTANCE_SEED + 1)
        self.assertFalse(verifier.run_state_matches(values, authority=False))

    def test_mutation_confirmation_is_required_before_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["verify", "--launch-pair", "--output", str(output)],
                ),
                mock.patch.object(verifier, "run") as run,
                mock.patch("builtins.print"),
            ):
                return_code = verifier.main()

            self.assertEqual(return_code, 2)
            run.assert_not_called()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("without --confirm-mutation", result["error"])

    def test_disposable_pair_is_required_before_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["verify", "--confirm-mutation", "--output", str(output)],
                ),
                mock.patch.object(verifier, "run") as run,
                mock.patch("builtins.print"),
            ):
                return_code = verifier.main()

            self.assertEqual(return_code, 2)
            run.assert_not_called()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("requires --launch-pair", result["error"])

    def test_failed_launch_does_not_contact_unowned_lua_pipes(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                side_effect=RuntimeError("launch failed"),
            ),
            mock.patch.object(verifier, "_run_probe") as run_probe,
            mock.patch.object(verifier, "_poll_probe") as poll_probe,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_probe.assert_not_called()
        stop.assert_called_once_with([])

    def test_run_stages_exact_mod_and_stops_only_launched_pair(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        initial_host = {
            "returncode": 0,
            "values": self._initial(authority=True),
        }
        initial_client = {
            "returncode": 0,
            "values": self._initial(authority=False),
        }
        client_rejection = {
            "returncode": 0,
            "values": {
                "rejected": "true",
                "authority_error": "true",
                "seed_nil": "true",
            },
        }
        host_set = {
            "returncode": 0,
            "values": {
                "accepted": str(verifier.ACCEPTANCE_SEED),
                "observed": str(verifier.ACCEPTANCE_SEED),
                "zero_rejected": "true",
                "large_rejected": "true",
                "fraction_rejected": "true",
            },
        }
        converged_host = {
            "returncode": 0,
            "values": self._converged(authority=True),
        }
        converged_client = {
            "returncode": 0,
            "values": self._converged(authority=False),
        }
        applied_host = {
            "returncode": 0,
            "values": self._applied(authority=True),
        }
        applied_client = {
            "returncode": 0,
            "values": self._applied(authority=False),
        }
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 61, "clientProcessId": 62},
            ) as launch_pair,
            mock.patch.object(verifier, "disable_bots"),
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(
                verifier,
                "start_host_testrun_and_wait_for_clients",
                return_value={"scene": "testrun"},
            ) as start_run,
            mock.patch.object(
                verifier,
                "_run_probe",
                side_effect=[client_rejection, host_set],
            ),
            mock.patch.object(
                verifier,
                "_poll_probe",
                side_effect=[
                    initial_host,
                    initial_client,
                    converged_host,
                    converged_client,
                    applied_host,
                    applied_client,
                ],
            ) as poll,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        launch_pair.assert_called_once_with(
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        start_run.assert_called_once_with(timeout=1.0)
        self.assertEqual(wait_remote.call_count, 4)
        self.assertEqual(poll.call_count, 6)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
