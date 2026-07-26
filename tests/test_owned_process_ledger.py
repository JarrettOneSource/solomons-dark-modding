#!/usr/bin/env python3
"""Contracts for the shared exact PID and staged-path process ledger."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import owned_process_ledger as ledger_module  # noqa: E402


class OwnedProcessLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = ledger_module.OwnedProcessLedger()
        self.host = ledger_module.OwnedProcessIdentity(
            role="host",
            process_id=4311,
            executable_path=(
                r"C:\acceptance\instances\guard-host"
                r"\stage\SolomonDark.exe"
            ),
            instance="guard-host",
        )

    @staticmethod
    def completed(rows: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(rows),
            stderr="",
        )

    def inspection(
        self,
        identity: ledger_module.OwnedProcessIdentity,
        *,
        actual_path: str | None = None,
        exited: bool = False,
        matched: bool = True,
        stopped: bool = False,
    ) -> dict[str, object]:
        return {
            "role": identity.role,
            "instance": identity.instance,
            "processId": identity.process_id,
            "expectedPath": identity.executable_path,
            "actualPath": (
                None
                if exited
                else actual_path or identity.executable_path
            ),
            "alreadyExited": exited,
            "pathMatched": matched,
            "stopped": stopped,
        }

    def test_pair_launch_requires_complete_staged_executable_identities(
        self,
    ) -> None:
        identities = ledger_module.identities_from_launch(
            {
                "instancePrefix": "guard",
                "hostProcessId": 4311,
                "hostExecutablePath": self.host.executable_path,
                "clientProcessId": "4312",
                "clientExecutablePath": (
                    r"C:\acceptance\instances\guard-client"
                    r"\stage\SolomonDark.exe"
                ),
            }
        )

        self.assertEqual(
            [(item.role, item.process_id, item.instance) for item in identities],
            [
                ("host", 4311, "guard-host"),
                ("client", 4312, "guard-client"),
            ],
        )

    def test_launcher_pid_without_staged_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ledger_module.OwnedProcessError,
            "hostExecutablePath",
        ):
            ledger_module.identities_from_launch(
                {"hostProcessId": 4311}
            )

    def test_non_stage_executable_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ledger_module.OwnedProcessError,
            "not a staged SolomonDark.exe",
        ):
            ledger_module.identities_from_launch(
                {
                    "processId": 4311,
                    "executablePath": (
                        r"C:\Users\User\Downloads\SolomonDark.exe"
                    ),
                }
            )

    def test_acquisition_validates_win32_executable_before_recording(
        self,
    ) -> None:
        completed = self.completed([self.inspection(self.host)])
        with mock.patch.object(
            ledger_module.subprocess,
            "run",
            return_value=completed,
        ) as run:
            acquired = self.ledger.acquire([self.host])

        self.assertEqual(acquired, [self.host])
        self.assertEqual(self.ledger.snapshot(), [self.host])
        script = run.call_args.args[0][-1]
        self.assertIn(
            "Get-CimInstance -ClassName Win32_Process",
            script,
        )
        self.assertIn('-Filter "ProcessId = $processId"', script)
        self.assertIn("$process.ExecutablePath", script)
        self.assertIn(
            "$decodedTargets = ConvertFrom-Json -InputObject $payload",
            script,
        )
        self.assertIn("$targets = @($decodedTargets)", script)
        self.assertNotIn(
            "$targets = @(ConvertFrom-Json -InputObject $payload)",
            script,
        )
        self.assertNotIn("Name='SolomonDark.exe'", script)

    def test_acquisition_refuses_path_mismatch(self) -> None:
        mismatch = self.inspection(
            self.host,
            actual_path=(
                r"C:\other\instances\foreign-host"
                r"\stage\SolomonDark.exe"
            ),
            matched=False,
        )
        with (
            mock.patch.object(
                ledger_module.subprocess,
                "run",
                return_value=self.completed([mismatch]),
            ),
            self.assertRaisesRegex(
                ledger_module.OwnedProcessError,
                "refusing ownership",
            ),
        ):
            self.ledger.acquire([self.host])

        self.assertEqual(self.ledger.snapshot(), [])

    def test_cleanup_revalidates_all_paths_before_exact_pid_stop(
        self,
    ) -> None:
        with mock.patch.object(
            ledger_module.subprocess,
            "run",
            side_effect=[
                self.completed([self.inspection(self.host)]),
                self.completed(
                    [self.inspection(self.host, stopped=True)]
                ),
            ],
        ) as run:
            self.ledger.acquire([self.host])
            results = self.ledger.stop()

        self.assertTrue(results[0]["stopped"])
        self.assertEqual(self.ledger.snapshot(), [])
        cleanup_script = run.call_args_list[1].args[0][-1]
        self.assertIn("if (-not $refused)", cleanup_script)
        self.assertIn(
            "Get-CimInstance -ClassName Win32_Process",
            cleanup_script,
        )
        self.assertIn("Stop-Process -Id", cleanup_script)
        self.assertIn(
            "$decodedTargets = ConvertFrom-Json -InputObject $payload",
            cleanup_script,
        )
        self.assertIn("$targets = @($decodedTargets)", cleanup_script)
        self.assertNotIn(
            "$targets = @(ConvertFrom-Json -InputObject $payload)",
            cleanup_script,
        )
        self.assertNotIn("Get-Process SolomonDark", cleanup_script)

    def test_cleanup_refuses_changed_path_without_dropping_ledger(
        self,
    ) -> None:
        mismatch = self.inspection(
            self.host,
            actual_path=(
                r"C:\other\instances\foreign-host"
                r"\stage\SolomonDark.exe"
            ),
            matched=False,
        )
        with mock.patch.object(
            ledger_module.subprocess,
            "run",
            side_effect=[
                self.completed([self.inspection(self.host)]),
                self.completed([mismatch]),
            ],
        ):
            self.ledger.acquire([self.host])
            with self.assertRaisesRegex(
                ledger_module.OwnedProcessError,
                "refused to stop",
            ):
                self.ledger.stop()

        self.assertEqual(self.ledger.snapshot(), [self.host])

    def test_unknown_pid_cleanup_refuses_without_process_query(self) -> None:
        with (
            mock.patch.object(ledger_module.subprocess, "run") as run,
            self.assertRaisesRegex(
                ledger_module.OwnedProcessError,
                "absent from the owned process ledger",
            ),
        ):
            self.ledger.stop([9999])

        run.assert_not_called()

    def test_empty_cleanup_has_no_process_side_effect(self) -> None:
        with mock.patch.object(ledger_module.subprocess, "run") as run:
            self.assertEqual(self.ledger.stop(), [])
            self.assertEqual(self.ledger.stop([]), [])

        run.assert_not_called()

    def test_exited_process_is_removed_during_exact_ledger_inspection(
        self,
    ) -> None:
        with mock.patch.object(
            ledger_module.subprocess,
            "run",
            side_effect=[
                self.completed([self.inspection(self.host)]),
                self.completed(
                    [
                        self.inspection(
                            self.host,
                            exited=True,
                            matched=False,
                        )
                    ]
                ),
            ],
        ):
            self.ledger.acquire([self.host])
            self.assertEqual(self.ledger.process_ids_by_role(), {})

        self.assertEqual(self.ledger.snapshot(), [])

    def test_additional_client_role_comes_from_launcher_instance(
        self,
    ) -> None:
        identities = ledger_module.identities_from_launch(
            {
                "processId": 4313,
                "executablePath": (
                    r"C:\acceptance\instances\guard-third"
                    r"\stage\SolomonDark.exe"
                ),
                "instance": "guard-third",
            }
        )

        self.assertEqual(identities[0].role, "third")
        self.assertEqual(identities[0].process_id, 4313)

    def test_launcher_ledger_reader_rejects_malformed_or_non_object_data(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            path.write_text("{bad", encoding="utf-8")
            self.assertEqual(
                ledger_module.read_launcher_ledger(path),
                {},
            )
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(
                ledger_module.read_launcher_ledger(path),
                {},
            )


if __name__ == "__main__":
    unittest.main()
