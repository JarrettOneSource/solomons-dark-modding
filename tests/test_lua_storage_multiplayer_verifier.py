#!/usr/bin/env python3
"""Tests for the two-peer Lua storage verifier."""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_storage_multiplayer as verifier  # noqa: E402


class LuaStorageMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _state(
        *,
        authority: bool,
        token: str | None = None,
        owner: str | None = None,
        launches: int | None = None,
    ) -> dict[str, str]:
        return {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "storage_capability": "true",
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "namespace_exact": "true",
            "entry_count": str(
                int(token is not None) + int(launches is not None)
            ),
            "has_launches": "true" if launches is not None else "false",
            "launches": str(launches or 0),
            "has_acceptance": "true" if token is not None else "false",
            "acceptance_exact": "true",
            "token": token or "",
            "owner": owner or "",
        }

    @staticmethod
    def _result(values: dict[str, str]) -> dict[str, Any]:
        return {"returncode": 0, "values": values}

    @staticmethod
    def _write_result() -> dict[str, Any]:
        names = (
            "stored",
            "default_ok",
            "ephemeral_set",
            "ephemeral_deleted",
            "delete_missing",
            "empty_key_rejected",
            "long_key_rejected",
            "cycle_rejected",
            "sparse_rejected",
            "mixed_rejected",
            "nan_rejected",
            "infinity_rejected",
            "nil_rejected",
            "transactional_unchanged",
        )
        return {
            "returncode": 0,
            "values": {name: "true" for name in names},
        }

    @staticmethod
    def _clear_result() -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "first": "true",
                "second": "false",
                "empty": "true",
            },
        }

    @staticmethod
    def _delete_result() -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "first": "true",
                "second": "false",
                "entry_count": "1",
                "launches_retained": "true",
            },
        }

    @staticmethod
    def _profiles() -> (
        contextlib.AbstractContextManager[dict[str, str]]
    ):
        return contextlib.nullcontext(
            {
                "local-mp-host": "host/profile-storage.bin",
                "local-mp-client": "client/profile-storage.bin",
            }
        )

    def test_state_matcher_requires_exact_local_value(self) -> None:
        values = self._state(
            authority=False,
            token=verifier.CLIENT_TOKEN,
            owner="client",
            launches=1,
        )
        self.assertTrue(
            verifier.storage_state_matches(
                values,
                authority=False,
                token=verifier.CLIENT_TOKEN,
                owner="client",
                launches=1,
            )
        )
        values["token"] = verifier.HOST_TOKEN
        self.assertFalse(
            verifier.storage_state_matches(
                values,
                authority=False,
                token=verifier.CLIENT_TOKEN,
                owner="client",
                launches=1,
            )
        )

    def test_profile_files_are_preserved_and_generated_files_removed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            host = root / "host" / "profile-storage.bin"
            client = root / "client" / "profile-storage.bin"
            host.parent.mkdir(parents=True)
            host.write_bytes(b"existing-host")
            host_tmp = verifier._temporary_path(host)
            host_tmp.write_bytes(b"existing-temporary")

            with self.assertRaisesRegex(RuntimeError, "forced failure"):
                with (
                    mock.patch.object(verifier, "ROOT", root),
                    mock.patch.object(
                        verifier,
                        "PROFILE_STORAGE_PATHS",
                        (host, client),
                    ),
                    verifier._preserve_profile_storage() as paths,
                ):
                    self.assertEqual(
                        paths["local-mp-host"],
                        "host/profile-storage.bin",
                    )
                    self.assertFalse(host.exists())
                    self.assertFalse(host_tmp.exists())
                    host.write_bytes(b"acceptance-host")
                    client.parent.mkdir(parents=True)
                    client.write_bytes(b"acceptance-client")
                    verifier._temporary_path(client).write_bytes(
                        b"temporary"
                    )
                    raise RuntimeError("forced failure")

            self.assertEqual(host.read_bytes(), b"existing-host")
            self.assertEqual(host_tmp.read_bytes(), b"existing-temporary")
            self.assertFalse(client.exists())
            self.assertFalse(verifier._temporary_path(client).exists())

    def test_durable_file_evidence_requires_distinct_bounded_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            host = root / "host" / "profile-storage.bin"
            client = root / "client" / "profile-storage.bin"
            host.parent.mkdir(parents=True)
            client.parent.mkdir(parents=True)
            host.write_bytes(b"host")
            client.write_bytes(b"client")
            with mock.patch.object(
                verifier,
                "PROFILE_STORAGE_PATHS",
                (host, client),
            ):
                evidence = verifier._storage_file_evidence()
                self.assertNotEqual(
                    evidence["local-mp-host"]["sha256"],
                    evidence["local-mp-client"]["sha256"],
                )
                client.write_bytes(b"host")
                with self.assertRaisesRegex(
                    RuntimeError,
                    "not distinct",
                ):
                    verifier._storage_file_evidence()

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
            self.assertIn(
                "without --confirm-profile-mutation",
                result["error"],
            )

    def test_disposable_pair_is_required_before_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "verify",
                        "--confirm-profile-mutation",
                        "--output",
                        str(output),
                    ],
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
                "_preserve_profile_storage",
                side_effect=self._profiles,
            ),
            mock.patch.object(
                verifier,
                "launch_pair",
                side_effect=RuntimeError("launch failed"),
            ),
            mock.patch.object(verifier, "_run_probe") as run_probe,
            mock.patch.object(verifier, "_poll_state") as poll_state,
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_state.assert_not_called()
        wait_remote.assert_not_called()
        stop.assert_called_once_with([])

    def test_incomplete_process_ledger_stops_only_owned_process(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        with (
            mock.patch.object(
                verifier,
                "_preserve_profile_storage",
                side_effect=self._profiles,
            ),
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 61},
            ),
            mock.patch.object(verifier, "_run_probe") as run_probe,
            mock.patch.object(verifier, "_poll_state") as poll_state,
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "two exact process IDs",
            ):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_state.assert_not_called()
        wait_remote.assert_not_called()
        stop.assert_called_once_with([61])

    def test_run_proves_local_persistence_and_restores_profiles(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        poll_results = [
            self._result(self._state(authority=True, launches=1)),
            self._result(self._state(authority=False, launches=1)),
            self._result(self._state(authority=True)),
            self._result(self._state(authority=False)),
            self._result(
                self._state(
                    authority=True,
                    token=verifier.HOST_TOKEN,
                    owner="host",
                )
            ),
            self._result(self._state(authority=False)),
            self._result(
                self._state(
                    authority=True,
                    token=verifier.HOST_TOKEN,
                    owner="host",
                )
            ),
            self._result(
                self._state(
                    authority=False,
                    token=verifier.CLIENT_TOKEN,
                    owner="client",
                )
            ),
            self._result(
                self._state(
                    authority=True,
                    token=verifier.HOST_TOKEN,
                    owner="host",
                    launches=1,
                )
            ),
            self._result(
                self._state(
                    authority=False,
                    token=verifier.CLIENT_TOKEN,
                    owner="client",
                    launches=1,
                )
            ),
            self._result(self._state(authority=True, launches=1)),
            self._result(
                self._state(
                    authority=False,
                    token=verifier.CLIENT_TOKEN,
                    owner="client",
                    launches=1,
                )
            ),
            self._result(self._state(authority=True)),
            self._result(
                self._state(
                    authority=False,
                    token=verifier.CLIENT_TOKEN,
                    owner="client",
                    launches=1,
                )
            ),
            self._result(self._state(authority=True)),
            self._result(self._state(authority=False)),
        ]
        action_results = [
            self._clear_result(),
            self._clear_result(),
            self._write_result(),
            self._write_result(),
            self._delete_result(),
            self._clear_result(),
            self._clear_result(),
        ]
        pair_results = [
            {"hostProcessId": 61, "clientProcessId": 62},
            {"hostProcessId": 71, "clientProcessId": 72},
        ]
        disk_evidence = {
            "local-mp-host": {
                "bytes": 90,
                "sha256": "host-hash",
                "temporary_absent": True,
            },
            "local-mp-client": {
                "bytes": 92,
                "sha256": "client-hash",
                "temporary_absent": True,
            },
        }

        with (
            mock.patch.object(
                verifier,
                "_preserve_profile_storage",
                side_effect=self._profiles,
            ) as preserve,
            mock.patch.object(
                verifier,
                "launch_pair",
                side_effect=pair_results,
            ) as launch_pair,
            mock.patch.object(verifier, "disable_bots") as disable_bots,
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(
                verifier,
                "_run_probe",
                side_effect=action_results,
            ) as run_probe,
            mock.patch.object(
                verifier,
                "_poll_state",
                side_effect=poll_results,
            ) as poll_state,
            mock.patch.object(
                verifier,
                "_storage_file_evidence",
                return_value=disk_evidence,
            ) as storage_evidence,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        self.assertEqual(result["durable_files"], disk_evidence)
        preserve.assert_called_once_with()
        self.assertEqual(launch_pair.call_count, 2)
        for call in launch_pair.call_args_list:
            self.assertEqual(
                call.kwargs,
                {
                    "temporary_host_profile": True,
                    "tile_windows": False,
                    "kill_existing": False,
                    "exact_mod_id": verifier.ACCEPTANCE_MOD_ID,
                },
            )
        self.assertEqual(disable_bots.call_count, 2)
        self.assertEqual(wait_remote.call_count, 4)
        self.assertEqual(run_probe.call_count, 7)
        self.assertEqual(poll_state.call_count, 16)
        storage_evidence.assert_called_once_with()
        self.assertEqual(
            [call.args[0] for call in stop.call_args_list],
            [[61, 62], [71, 72]],
        )


if __name__ == "__main__":
    unittest.main()
