from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.native_menu_browser_tab import (
    ENTRY_STATE_STOP,
    NativeMenuBrowserTabError,
    resolve_browser_tab,
    validate_browser_tab,
)
from tools.native_menu_profile_state import (
    BASELINE_REPO_PATH,
    BASELINE_SCHEMA,
    IDENTITY_SCHEMA,
    PROFILE_MISMATCH_REASON,
    RECEIPT_SCHEMA,
    NativeMenuProfileStateError,
    compute_profile_state_identity,
    sha256_file,
    validate_capture_profile_state,
)


def _profile_fixture(repo_root: Path, evidence_root: Path) -> dict[str, object]:
    profile_state = {
        "identity_schema": IDENTITY_SCHEMA,
        "baseline_mode": "fresh_install",
        "source_sandbox_excluded": True,
        "retail_appdata_seeded": False,
        "files": [],
    }
    identity = compute_profile_state_identity(profile_state)
    profile_state["profile_state_identity_sha256"] = identity
    baseline_path = repo_root / BASELINE_REPO_PATH
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_text(
        json.dumps(
            {
                "schema": BASELINE_SCHEMA,
                "header": {"label": "unit-test pristine baseline"},
                "profile_state": profile_state,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    launch_receipt = {
        "schema": RECEIPT_SCHEMA,
        "profile_state_identity_sha256": identity,
        "baseline_mode": "fresh_install",
        "source_sandbox_excluded": True,
        "retail_appdata_seeded": False,
        "files": [],
        "stage_sandbox_root": "C:/instance/stage/sandbox",
        "isolated_profile_root": "C:/instance/profile",
        "recorded_at_utc": "2026-08-08T00:00:00Z",
        "receipt_path": "C:/instance/stage/.sdmod/native-menu-profile-state.json",
    }
    evidence_root.mkdir(parents=True)
    receipt_path = evidence_root / "capture.profile-state.json"
    receipt_path.write_text(
        json.dumps(launch_receipt, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "source": {"profile_state_identity_sha256": identity},
        "profile_state": {
            "schema": RECEIPT_SCHEMA,
            "profile_state_identity_sha256": identity,
            "baseline_mode": "fresh_install",
            "source_sandbox_excluded": True,
            "retail_appdata_seeded": False,
            "durable_file_count": 0,
            "baseline_fixture": {
                "repo_relative_path": BASELINE_REPO_PATH.as_posix(),
                "sha256": sha256_file(baseline_path),
                "bytes": baseline_path.stat().st_size,
            },
            "launch_receipt": {
                "evidence_filename": receipt_path.name,
                "sha256": sha256_file(receipt_path),
                "bytes": receipt_path.stat().st_size,
            },
        },
    }


def _browser_layout(selected_tab: str) -> dict[str, object]:
    tab_specs = (
        ("recent", "dark_cloud_browser.recent", 10.0),
        ("online_levels", "dark_cloud_browser.online_levels", 210.0),
        ("my_levels", "dark_cloud_browser.my_levels", 410.0),
    )
    elements: list[dict[str, object]] = []
    for ordinal, (tab, action_id, left) in enumerate(tab_specs, start=1):
        right = left + 100.0
        top = 50.0 if tab == selected_tab else 56.0
        elements.extend(
            (
                {
                    "id": f"dark_cloud_browser.control.{tab}.1",
                    "kind": "control",
                    "action_id": action_id,
                    "rect": [left, 40.0, right, 80.0],
                },
                {
                    "id": f"dark_cloud_browser.art.ui_13.{ordinal * 2 - 1}",
                    "kind": "art",
                    "art_id": "UI.13",
                    "rect": [left, top, left + 8.0, top + 16.0],
                },
                {
                    "id": f"dark_cloud_browser.art.ui_13.{ordinal * 2}",
                    "kind": "art",
                    "art_id": "UI.13",
                    "rect": [right - 8.0, top, right, top + 16.0],
                },
            )
        )
    return {
        "generation": 7,
        "screen_id": "dark_cloud_browser",
        "screen_title": "Dark Cloud",
        "capture_method": "unit-test machine layout",
        "elements": elements,
    }


class NativeMenuProfileStateTests(unittest.TestCase):
    def test_matching_pristine_state_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            header = _profile_fixture(repo, evidence)

            result = validate_capture_profile_state(
                repo_root=repo,
                header=header,
                label="matching capture",
                evidence_root=evidence,
            )

            self.assertEqual(
                result["identity"],
                header["profile_state"]["profile_state_identity_sha256"],
            )

    def test_mismatched_identity_is_rejected_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            header = _profile_fixture(repo, evidence)
            header["profile_state"]["profile_state_identity_sha256"] = "0" * 64

            with self.assertRaisesRegex(
                NativeMenuProfileStateError, PROFILE_MISMATCH_REASON
            ):
                validate_capture_profile_state(
                    repo_root=repo,
                    header=header,
                    label="mismatched capture",
                    evidence_root=evidence,
                )

    def test_duplicate_receipt_lookup_refuses_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            header = _profile_fixture(repo, evidence)
            duplicate = evidence / "second" / "capture.profile-state.json"
            duplicate.parent.mkdir()
            duplicate.write_bytes((evidence / duplicate.name).read_bytes())

            with self.assertRaisesRegex(
                NativeMenuProfileStateError, "absent or ambiguous"
            ):
                validate_capture_profile_state(
                    repo_root=repo,
                    header=header,
                    label="ambiguous capture",
                    evidence_root=evidence,
                )


class NativeMenuBrowserTabTests(unittest.TestCase):
    def test_pristine_online_entry_and_exact_receipt_are_accepted(self) -> None:
        layout = _browser_layout("online_levels")
        measured = resolve_browser_tab(layout, "online entry")
        receipt = {"expected_tab": "online_levels", **measured}

        result = validate_browser_tab(
            screen_tag="dark_cloud_browser",
            layout=layout,
            receipt=receipt,
            label="online entry",
        )

        self.assertEqual(result, measured)
        self.assertEqual(len(measured["member_ids"]), 6)

    def test_recent_entry_trips_the_case_a_contract(self) -> None:
        layout = _browser_layout("recent")
        measured = resolve_browser_tab(layout, "recent entry")
        receipt = {"expected_tab": "recent", **measured}

        with self.assertRaisesRegex(
            NativeMenuBrowserTabError, ENTRY_STATE_STOP
        ):
            validate_browser_tab(
                screen_tag="dark_cloud_browser",
                layout=layout,
                receipt=receipt,
                label="recent entry",
            )

    def test_false_geometry_receipt_is_rejected(self) -> None:
        layout = _browser_layout("online_levels")
        measured = resolve_browser_tab(layout, "online entry")
        receipt = {"expected_tab": "online_levels", **measured}
        receipt = copy.deepcopy(receipt)
        receipt["geometry_sha256"] = "f" * 64

        with self.assertRaisesRegex(
            NativeMenuBrowserTabError, "false capture-time"
        ):
            validate_browser_tab(
                screen_tag="dark_cloud_browser",
                layout=layout,
                receipt=receipt,
                label="forged receipt",
            )

    def test_non_browser_layout_cannot_carry_a_tab_receipt(self) -> None:
        with self.assertRaisesRegex(
            NativeMenuBrowserTabError, "non-browser layout"
        ):
            validate_browser_tab(
                screen_tag="settings",
                layout={"elements": []},
                receipt={},
                label="settings",
            )


if __name__ == "__main__":
    unittest.main()
