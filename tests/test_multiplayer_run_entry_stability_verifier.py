from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_multiplayer_run_entry_stability as verifier  # noqa: E402


class RunEntryStabilityVerifierTests(unittest.TestCase):
    def make_result(
        self,
        root: Path,
        *,
        failing_role: str | None = None,
    ) -> dict[str, object]:
        runs: list[dict[str, object]] = []
        for run_index in range(1, 6):
            logs: dict[str, str] = {}
            for role in ("host", "client"):
                log_path = root / f"run-{run_index:02d}-{role}.log"
                text = "Hub testrun region switch completed.\n"
                if run_index == 3 and role == failing_role:
                    text += (
                        "first-chance exception count=1 "
                        "code=0xC0000005 access_type=0x00000008\n"
                    )
                log_path.write_text(text, encoding="utf-8")
                logs[role] = str(log_path)
            runs.append(
                {
                    "run_index": run_index,
                    "ok": True,
                    "host_run_entry": {
                        "host_started": True,
                        "client_followed_host": True,
                    },
                    "cleanup": {"exact_pid_path_cleanup": True},
                    "launch": {
                        "hostLog": logs["host"],
                        "clientLog": logs["client"],
                    },
                }
            )
        return {"ok": True, "runs": runs}

    def test_five_clean_entries_pass_with_ten_peer_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = verifier.validate_layout_result(
                self.make_result(Path(temporary)),
                5,
            )
        self.assertEqual(summary["runs_completed"], 5)
        self.assertEqual(summary["peer_entries_completed"], 10)
        self.assertEqual(summary["access_violation_count"], 0)

    def test_first_chance_access_violation_fails_even_after_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                verifier.StabilityFailure,
                r"run 3 host logged an access violation",
            ):
                verifier.validate_layout_result(
                    self.make_result(
                        Path(temporary),
                        failing_role="host",
                    ),
                    5,
                )

    def test_incomplete_entry_fails_before_log_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self.make_result(Path(temporary))
            result["runs"][1]["host_run_entry"]["client_followed_host"] = False
            with self.assertRaisesRegex(
                verifier.StabilityFailure,
                r"run 2 did not complete host/client entry",
            ):
                verifier.validate_layout_result(result, 5)


if __name__ == "__main__":
    unittest.main()
