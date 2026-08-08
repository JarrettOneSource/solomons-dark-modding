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
    FRESH_BASELINE_ID,
    HUB_BINDINGS_REPO_PATH,
    IDENTITY_SCHEMA,
    PROFILE_MISMATCH_REASON,
    PER_BINDING_MISMATCH_REASON,
    DERIVATION_MISMATCH_REASON,
    RECEIPT_SCHEMA,
    V212_EXACT_LAYOUT_REASON,
    V212_SCOPE_REASON,
    V213_EXACT_LAYOUT_REASON,
    NativeMenuProfileStateError,
    compute_profile_state_identity,
    load_hub_binding_contract,
    sha256_file,
    resolve_navigation_profile_binding,
    required_baseline_for_layout,
    validate_exact_hub_layout_pair,
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
    contract_path = repo_root / HUB_BINDINGS_REPO_PATH
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    source_contract_path = (
        Path(__file__).resolve().parents[1] / HUB_BINDINGS_REPO_PATH
    )
    contract = json.loads(source_contract_path.read_text(encoding="utf-8"))
    contract["baselines"][FRESH_BASELINE_ID][
        "profile_state_identity_sha256"
    ] = identity
    contract["baselines"][FRESH_BASELINE_ID]["fixture"] = {
        "repo_relative_path": BASELINE_REPO_PATH.as_posix(),
        "sha256": sha256_file(baseline_path),
        "bytes": baseline_path.stat().st_size,
    }
    contract_path.write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
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
            "baseline_id": FRESH_BASELINE_ID,
            "baseline_mode": "fresh_install",
            "source_sandbox_excluded": True,
            "retail_appdata_seeded": False,
            "durable_file_count": 0,
            "baseline_fixture": {
                "repo_relative_path": BASELINE_REPO_PATH.as_posix(),
                "sha256": sha256_file(baseline_path),
                "bytes": baseline_path.stat().st_size,
            },
            "binding_contract": {
                "repo_relative_path": HUB_BINDINGS_REPO_PATH.as_posix(),
                "sha256": sha256_file(contract_path),
                "bytes": contract_path.stat().st_size,
            },
            "launch_receipt": {
                "evidence_filename": receipt_path.name,
                "sha256": sha256_file(receipt_path),
                "bytes": receipt_path.stat().st_size,
            },
        },
    }


def _derived_profile_fixture(
    repo_root: Path, evidence_root: Path
) -> dict[str, object]:
    _profile_fixture(repo_root, evidence_root)
    receipt_state = {
        "baseline_mode": "persistent_profile",
        "source_sandbox_excluded": False,
        "retail_appdata_seeded": False,
        "files": [
            {
                "root": "stage_sandbox",
                "relative_path": "savegames/solomondark/darkdata.cfg",
                "bytes": 3,
                "sha256": "a" * 64,
            }
        ],
    }
    identity = compute_profile_state_identity(receipt_state)
    launch_receipt = {
        "schema": RECEIPT_SCHEMA,
        "profile_state_identity_sha256": identity,
        **receipt_state,
        "stage_sandbox_root": "C:/instance/stage/sandbox",
        "isolated_profile_root": "C:/instance/profile",
        "recorded_at_utc": "2026-08-08T00:00:00Z",
        "receipt_path": "C:/instance/stage/.sdmod/native-menu-profile-state.json",
    }
    receipt_path = evidence_root / "derived.profile-state.json"
    receipt_path.write_text(
        json.dumps(launch_receipt, indent=2) + "\n", encoding="utf-8"
    )
    contract_path = repo_root / HUB_BINDINGS_REPO_PATH
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    witness = contract["baselines"]["hub_new_game_two_action_v213"][
        "witnesses"
    ][0]
    witness["profile_state_identity_sha256"] = identity
    witness["profile_state_receipt"] = {
        "evidence_path": "derived.profile-state.json",
        "sha256": sha256_file(receipt_path),
        "bytes": receipt_path.stat().st_size,
    }
    contract_path.write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
    )
    contract_receipt = {
        "repo_relative_path": HUB_BINDINGS_REPO_PATH.as_posix(),
        "sha256": sha256_file(contract_path),
        "bytes": contract_path.stat().st_size,
    }
    return {
        "source": {"profile_state_identity_sha256": identity},
        "profile_state": {
            "schema": RECEIPT_SCHEMA,
            "profile_state_identity_sha256": identity,
            "baseline_id": "hub_new_game_two_action_v213",
            "derivation_witness_role": "primary",
            "baseline_mode": "persistent_profile",
            "source_sandbox_excluded": False,
            "retail_appdata_seeded": False,
            "durable_file_count": 1,
            "baseline_fixture": contract_receipt,
            "binding_contract": copy.deepcopy(contract_receipt),
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


def _exact_hub_layout(repo_root: Path, layout_id: str) -> dict[str, object]:
    contract = load_hub_binding_contract(repo_root)["value"]
    members = contract["layouts"][layout_id]["resolved_semantic_multiset"]
    elements: list[dict[str, object]] = []
    for ordinal, member in enumerate(members, start=1):
        (
            kind,
            text,
            action_id,
            art_id,
            font_id,
            text_style,
            visible,
            interactive,
            geometry,
        ) = member
        if geometry == ["v2.3-motion-capable-geometry"]:
            rect = [720.0, 300.0, 730.0, 310.0]
            unclipped_rect = list(rect)
        else:
            rect, unclipped_rect = copy.deepcopy(geometry)
        elements.append(
            {
                "id": f"hub.{kind}.fixture.{ordinal}",
                "kind": kind,
                "text": text,
                "action_id": action_id,
                "art_id": art_id,
                "font_id": font_id,
                "text_style": text_style,
                "visible": visible,
                "interactive": interactive,
                "draw_order": ordinal,
                "rect": rect,
                "unclipped_rect": unclipped_rect,
            }
        )
    return {
        "generation": 4,
        "screen_id": "hub",
        "screen_title": "",
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
            self.assertEqual(result["baseline_id"], FRESH_BASELINE_ID)

    def test_per_binding_baseline_match_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            header = _profile_fixture(repo, evidence)

            result = validate_capture_profile_state(
                repo_root=repo,
                header=header,
                label="fresh Hub binding",
                evidence_root=evidence,
                required_baseline_id=FRESH_BASELINE_ID,
                binding_label="layout 'hub_pristine_second_new_game'",
            )

            self.assertEqual(result["baseline_id"], FRESH_BASELINE_ID)

    def test_per_binding_baseline_mismatch_is_rejected_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            header = _profile_fixture(repo, evidence)

            with self.assertRaisesRegex(
                NativeMenuProfileStateError, PER_BINDING_MISMATCH_REASON
            ):
                validate_capture_profile_state(
                    repo_root=repo,
                    header=header,
                    label="wrong derived binding",
                    evidence_root=evidence,
                    required_baseline_id="hub_new_game_two_action_v213",
                    binding_label="layout 'hub_new_game'",
                )

    def test_exact_hub_edge_binding_uses_baseline_and_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            _profile_fixture(repo, evidence)

            self.assertEqual(
                required_baseline_for_layout(
                    repo, "hub_pristine_second_new_game"
                ),
                FRESH_BASELINE_ID,
            )
            self.assertEqual(
                resolve_navigation_profile_binding(
                    repo,
                    edge_id="create_discipline_to_hub",
                    endpoint="after",
                    baseline_id=FRESH_BASELINE_ID,
                ),
                "hub_pristine_second_new_game",
            )

    def test_exact_derived_witness_is_accepted_for_hub_new_game(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            header = _derived_profile_fixture(repo, evidence)

            result = validate_capture_profile_state(
                repo_root=repo,
                header=header,
                label="derived Hub binding",
                evidence_root=evidence,
                required_baseline_id="hub_new_game_two_action_v213",
                binding_label="layout 'hub_new_game'",
            )

            self.assertEqual(result["witness_role"], "primary")

    def test_derived_receipt_mismatch_is_rejected_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            header = _derived_profile_fixture(repo, evidence)
            header["profile_state"]["launch_receipt"]["sha256"] = "0" * 64

            with self.assertRaisesRegex(
                NativeMenuProfileStateError, DERIVATION_MISMATCH_REASON
            ):
                validate_capture_profile_state(
                    repo_root=repo,
                    header=header,
                    label="mutated derivation receipt",
                    evidence_root=evidence,
                    required_baseline_id="hub_new_game_two_action_v213",
                )

    def test_v212_exact_pristine_second_new_game_layout_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            _profile_fixture(repo, evidence)
            layout = _exact_hub_layout(repo, "hub_pristine_second_new_game")

            result = validate_exact_hub_layout_pair(
                repo,
                layout_id="hub_pristine_second_new_game",
                primary_layout=layout,
                confirmation_layout=copy.deepcopy(layout),
                baseline_id=FRESH_BASELINE_ID,
            )

            self.assertEqual(result["element_count"], 15)

    def test_v212_missing_ui28_is_rejected_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            _profile_fixture(repo, evidence)
            layout = _exact_hub_layout(repo, "hub_pristine_second_new_game")
            layout["elements"] = [
                element
                for element in layout["elements"]
                if element["art_id"] != "UI.28"
            ]

            with self.assertRaisesRegex(
                NativeMenuProfileStateError, V212_SCOPE_REASON
            ):
                validate_exact_hub_layout_pair(
                    repo,
                    layout_id="hub_pristine_second_new_game",
                    primary_layout=layout,
                    confirmation_layout=copy.deepcopy(layout),
                    baseline_id=FRESH_BASELINE_ID,
                )

    def test_v212_missing_level_picker_member_is_rejected_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            _profile_fixture(repo, evidence)
            layout = _exact_hub_layout(repo, "hub_pristine_second_new_game")
            victim = next(
                element
                for element in layout["elements"]
                if element["art_id"] == "LevelPicker.0"
            )
            layout["elements"].remove(victim)

            with self.assertRaisesRegex(
                NativeMenuProfileStateError, V212_EXACT_LAYOUT_REASON
            ):
                validate_exact_hub_layout_pair(
                    repo,
                    layout_id="hub_pristine_second_new_game",
                    primary_layout=layout,
                    confirmation_layout=copy.deepcopy(layout),
                    baseline_id=FRESH_BASELINE_ID,
                )

    def test_v212_extra_member_is_rejected_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            _profile_fixture(repo, evidence)
            layout = _exact_hub_layout(repo, "hub_pristine_second_new_game")
            extra = copy.deepcopy(layout["elements"][0])
            extra["id"] = "hub.art.fixture.extra"
            extra["art_id"] = "LevelPicker.extra"
            layout["elements"].append(extra)

            with self.assertRaisesRegex(
                NativeMenuProfileStateError, V212_EXACT_LAYOUT_REASON
            ):
                validate_exact_hub_layout_pair(
                    repo,
                    layout_id="hub_pristine_second_new_game",
                    primary_layout=layout,
                    confirmation_layout=copy.deepcopy(layout),
                    baseline_id=FRESH_BASELINE_ID,
                )

    def test_v212_exact_multiset_cannot_leak_to_another_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            _profile_fixture(repo, evidence)
            layout = _exact_hub_layout(repo, "hub_pristine_second_new_game")

            for wrong_layout in ("hub_new_game", "settings"):
                with self.subTest(wrong_layout=wrong_layout), self.assertRaisesRegex(
                    NativeMenuProfileStateError, V212_SCOPE_REASON
                ):
                    validate_exact_hub_layout_pair(
                        repo,
                        layout_id=wrong_layout,
                        primary_layout=layout,
                        confirmation_layout=copy.deepcopy(layout),
                        baseline_id=FRESH_BASELINE_ID,
                    )

    def test_v213_exact_derived_layout_and_receipt_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            header = _derived_profile_fixture(repo, evidence)
            layout = _exact_hub_layout(repo, "hub_new_game")

            profile = validate_capture_profile_state(
                repo_root=repo,
                header=header,
                label="derived Hub binding",
                evidence_root=evidence,
                required_baseline_id="hub_new_game_two_action_v213",
                binding_label="layout 'hub_new_game'",
            )
            exact = validate_exact_hub_layout_pair(
                repo,
                layout_id="hub_new_game",
                primary_layout=layout,
                confirmation_layout=copy.deepcopy(layout),
                baseline_id=profile["baseline_id"],
            )

            self.assertEqual(profile["witness_role"], "primary")
            self.assertEqual(exact["element_count"], 14)

    def test_v213_wrong_exact_multiset_is_rejected_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            evidence = root / "evidence"
            _profile_fixture(repo, evidence)
            layout = _exact_hub_layout(repo, "hub_new_game")
            layout["elements"][0]["rect"][0] += 1.0

            with self.assertRaisesRegex(
                NativeMenuProfileStateError, V213_EXACT_LAYOUT_REASON
            ):
                validate_exact_hub_layout_pair(
                    repo,
                    layout_id="hub_new_game",
                    primary_layout=layout,
                    confirmation_layout=copy.deepcopy(layout),
                    baseline_id="hub_new_game_two_action_v213",
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
