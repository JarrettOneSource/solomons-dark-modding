#!/usr/bin/env python3
"""Safety contracts for all 58 owner-audited legacy verifier entry points."""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from legacy_verifier_inventory import (  # noqa: E402
    AUDITED_LEGACY_VERIFIERS,
)
from probe_legacy_verifier_process_safety import run_all  # noqa: E402


class LegacyVerifierProcessSafetyTests(unittest.TestCase):
    def test_inventory_matches_all_58_owner_audited_rows(self) -> None:
        audit = (
            ROOT / "docs" / "testing" / "suite-audit-2026-07.md"
        ).read_text(encoding="utf-8")
        section = audit.split(
            "## Legacy live entry points — exact-ownership re-audit",
            maxsplit=1,
        )[1].split("## Detailed inventory", maxsplit=1)[0]
        documented = tuple(
            re.findall(r"^\| (tools/[^ |]+\.py) \|", section, re.MULTILINE)
        )

        self.assertEqual(len(AUDITED_LEGACY_VERIFIERS), 58)
        self.assertEqual(AUDITED_LEGACY_VERIFIERS, documented)
        self.assertEqual(len(set(AUDITED_LEGACY_VERIFIERS)), 58)

    def test_all_entry_points_are_present_and_parse(self) -> None:
        for relative in AUDITED_LEGACY_VERIFIERS:
            with self.subTest(entry_point=relative):
                path = ROOT / relative
                self.assertTrue(path.is_file())
                ast.parse(path.read_text(encoding="utf-8"), path.name)

    def test_all_entry_points_use_the_shared_owned_cleanup(self) -> None:
        for relative in AUDITED_LEGACY_VERIFIERS:
            source = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(entry_point=relative):
                self.assertIn("stop_owned_game_processes", source)
                self.assertNotRegex(source, r"\bstop_games\b")

    def test_all_entry_points_forbid_name_wide_process_access(self) -> None:
        forbidden = (
            r"Get-Process\s+SolomonDark",
            r"Get-CimInstance[^\n]+Name\s*=\s*['\"]?SolomonDark",
            r"\b(?:taskkill|pkill|killall)\b[^\n]*SolomonDark",
            r"Stop-Process\b",
            r"\bos\.kill(?:pg)?\s*\(",
            r"\bTerminateProcess\b",
            r"\bprocess_iter\s*\(",
        )
        for relative in AUDITED_LEGACY_VERIFIERS:
            source = (ROOT / relative).read_text(encoding="utf-8")
            for pattern in forbidden:
                with self.subTest(
                    entry_point=relative,
                    forbidden=pattern,
                ):
                    self.assertNotRegex(source, pattern)

    def test_shared_layer_is_the_only_game_process_stop_authority(
        self,
    ) -> None:
        source = (
            ROOT / "tools" / "owned_process_ledger.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Get-CimInstance -ClassName Win32_Process",
            source,
        )
        self.assertIn('-Filter "ProcessId = $processId"', source)
        self.assertIn("$process.ExecutablePath", source)
        self.assertIn("if (-not $refused)", source)
        self.assertIn("Stop-Process -Id", source)
        self.assertNotIn("Get-Process SolomonDark", source)
        self.assertNotRegex(
            source,
            r"Name\s*=\s*['\"]SolomonDark\.exe",
        )

    def test_launchers_publish_pid_and_exact_staged_path_together(
        self,
    ) -> None:
        pair = (
            ROOT / "scripts" / "Launch-LocalMultiplayerPair.ps1"
        ).read_text(encoding="utf-8")
        additional = (
            ROOT
            / "scripts"
            / "Launch-LocalMultiplayerAdditionalClient.ps1"
        ).read_text(encoding="utf-8")

        for token in (
            "hostProcessId",
            "hostExecutablePath",
            "clientProcessId",
            "clientExecutablePath",
            "thirdProcessId",
            "thirdExecutablePath",
            "Get-InstanceExecutablePath",
        ):
            self.assertIn(token, pair)
        for token in (
            "processId",
            "executablePath",
            'processRole = "third"',
        ):
            self.assertIn(token, additional)

    def test_import_help_and_argument_failure_have_no_process_events(
        self,
    ) -> None:
        summary = run_all()

        self.assertTrue(summary["ok"], summary["failures"])
        self.assertEqual(summary["entry_point_count"], 58)
        self.assertEqual(summary["mode_count"], 3)
        self.assertEqual(summary["probe_count"], 174)
        self.assertEqual(summary["process_event_count"], 0)


if __name__ == "__main__":
    unittest.main()
