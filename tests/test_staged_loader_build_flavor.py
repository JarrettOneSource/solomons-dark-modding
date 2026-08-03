#!/usr/bin/env python3
"""Executable tests for the staged Release-loader assertion."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSERTION = ROOT / "scripts" / "Assert-StagedReleaseLoader.ps1"


def windows_path(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path.resolve())],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout.strip()


class StagedLoaderBuildFlavorTests(unittest.TestCase):
    def invoke(self, loader_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                windows_path(ASSERTION),
                "-LoaderPath",
                windows_path(loader_path),
            ],
            cwd=ROOT,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def fixture(self, *stamps: str, pe: bool = True) -> Path:
        fixture_root = Path(
            tempfile.mkdtemp(prefix="loader-flavor-", dir=ROOT / "runtime")
        )
        self.addCleanup(shutil.rmtree, fixture_root)
        loader = fixture_root / "SolomonDarkModLoader.dll"
        prefix = b"MZ\x00\x00" if pe else b"not-a-pe\x00"
        loader.write_bytes(
            prefix
            + b"payload\x00"
            + b"\x00".join(stamp.encode("ascii") for stamp in stamps)
            + b"\x00"
        )
        return loader

    def test_release_stamp_passes(self) -> None:
        result = self.invoke(self.fixture("SDMOD_BUILD_FLAVOR=Release"))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Release", result.stdout)

    def test_debug_stamp_is_refused_with_recovery_command(self) -> None:
        result = self.invoke(self.fixture("SDMOD_BUILD_FLAVOR=Debug"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Live acceptance requires a Release", result.stdout)
        self.assertIn("Build-All.ps1 -Configuration Release", result.stdout)

    def test_missing_stamp_is_refused(self) -> None:
        result = self.invoke(self.fixture("unrelated"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no single recognized build-flavor stamp", result.stdout)

    def test_ambiguous_stamp_is_refused(self) -> None:
        result = self.invoke(
            self.fixture(
                "SDMOD_BUILD_FLAVOR=Debug",
                "SDMOD_BUILD_FLAVOR=Release",
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no single recognized build-flavor stamp", result.stdout)

    def test_non_pe_input_is_refused(self) -> None:
        result = self.invoke(
            self.fixture("SDMOD_BUILD_FLAVOR=Release", pe=False)
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a PE DLL", result.stdout)

    def test_missing_loader_is_refused(self) -> None:
        fixture_root = Path(
            tempfile.mkdtemp(prefix="loader-flavor-", dir=ROOT / "runtime")
        )
        self.addCleanup(shutil.rmtree, fixture_root)
        result = self.invoke(fixture_root / "missing.dll")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot find path", result.stdout)


if __name__ == "__main__":
    unittest.main()
