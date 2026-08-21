from __future__ import annotations

import json
import math
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/webgame/native-derived-hud-goldens.json"
HUD_DOC = ROOT / "docs/reverse-engineering/native-hud.md"
LAYOUT = ROOT / "config/binary-layout.ini"


def section_owners(path: Path) -> dict[str, str]:
    current = ""
    owners: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            continue
        if "=" in line:
            owners[line.split("=", 1)[0].strip()] = current
    return owners


class NativeDerivedHudContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_pins_native_provenance(self) -> None:
        self.assertEqual(
            self.fixture["schema"],
            "solomon-dark-native-derived-hud-goldens-v1",
        )
        source = self.fixture["source"]
        self.assertEqual(len(source["commit"]), 40)
        self.assertEqual(len(source["binary_sha256"]), 64)
        self.assertEqual(len(source["loader_sha256"]), 64)
        self.assertEqual(len(source["skill_capture_roots"]), 3)

    def test_every_meter_case_obeys_recovered_dynamic_widths(self) -> None:
        constants = self.fixture["constants"]
        for case in self.fixture["meter_cases"]:
            with self.subTest(case=case["id"]):
                health_core = constants["health_core_scale"] * (
                    constants["base_health"]
                    + constants["maximum_delta_scale"]
                    * (case["maximum_health"] - constants["base_health"])
                )
                mana_core = (
                    constants["base_mana"]
                    + constants["maximum_delta_scale"]
                    * (case["maximum_mana"] - constants["base_mana"])
                )
                self.assertEqual(case["health_core_width"], health_core)
                self.assertEqual(
                    case["health_track_width"],
                    health_core + constants["track_padding"],
                )
                self.assertEqual(case["mana_core_width"], mana_core)
                self.assertEqual(
                    case["mana_track_width"],
                    mana_core + constants["track_padding"],
                )
                if "health_core_rect" in case:
                    self.assertEqual(
                        case["health_core_rect"],
                        [
                            constants["health_core_right"] - health_core,
                            19.5,
                            constants["health_core_right"],
                            29.5,
                        ],
                    )
                if "mana_core_rect" in case:
                    self.assertEqual(
                        case["mana_core_rect"],
                        [
                            constants["mana_core_left"],
                            19.5,
                            constants["mana_core_left"] + mana_core,
                            29.5,
                        ],
                    )

    def test_current_reserve_and_shield_use_the_dynamic_core(self) -> None:
        half = next(
            case for case in self.fixture["meter_cases"]
            if case["id"] == "both-rank-one-half-current"
        )
        self.assertTrue(math.isclose(
            half["health_visible_width"],
            half["health_core_width"]
            * (half["current_health"] / half["maximum_health"]) ** 2,
            abs_tol=0.000_05,
        ))
        self.assertTrue(math.isclose(
            half["mana_visible_width"],
            half["mana_core_width"]
            * half["current_mana"] / half["maximum_mana"],
            abs_tol=0.000_05,
        ))
        reserve = next(
            case for case in self.fixture["meter_cases"]
            if case["id"] == "mana-up-reserve-50"
        )
        self.assertEqual(reserve["reserve_logical_width"], 125 * 50 / 200)
        shield = next(
            case for case in self.fixture["meter_cases"]
            if case["id"] == "health-up-shield-25-of-50"
        )
        self.assertEqual(shield["shield_width"], 125 * 25 / 50)

    def test_every_reachable_concentration_and_cluster_layout_is_pinned(self) -> None:
        bindings = self.fixture["skill_bindings"]
        records = {
            int(skill_id): record
            for skill_id, record
            in bindings["reachable_concentration_icon_records"].items()
        }
        self.assertEqual(
            list(records),
            [57, 58, 59, 60, 61, 62, 63, 65, 66, 67, 68, 69, 70, 71],
        )
        self.assertNotIn(64, records)
        self.assertEqual(list(records.values()), [
            84, 85, 86, 87, 88, 89, 90,
            92, 93, 94, 95, 96, 97, 98,
        ])
        self.assertEqual(
            [(row["binding"], row["center"][0])
             for row in bindings["primary_only"]],
            [(12, 800)],
        )
        self.assertEqual(
            [(row["binding"], row["center"][0])
             for row in bindings["primary_and_a"]],
            [(12, 780), (16, 820)],
        )
        self.assertEqual(
            [(row["binding"], row["center"][0])
             for row in bindings["primary_a_b_draw_order"]],
            [(12, 760), (16, 840), (20, 800)],
        )

    def test_authoritative_document_contains_implementation_formulas(self) -> None:
        document = HUD_DOC.read_text(encoding="utf-8")
        for marker in (
            "health_core_width =",
            "mana_core_width =",
            "Health Up rank one",
            "Mana Up rank one",
            "Maximum-vital producers and refresh ownership",
            "Selected-primary and concentration emblems",
            "57->84",
            "71->98",
        ):
            self.assertIn(marker, document)
        self.assertNotIn("### Binding 16/20 concentration emblems", document)

    def test_pause_section_cannot_split_gameplay_globals_again(self) -> None:
        owners = section_owners(LAYOUT)
        for key in (
            "menu_keybinding",
            "belt_slot_8_keybinding",
            "cursor_secondary_at_mouse",
            "game_object",
            "arena",
            "damage_context_target",
            "gameplay_index_state_table",
        ):
            with self.subTest(key=key):
                self.assertEqual(owners[key], "gameplay.globals")
        self.assertEqual(owners["game_tick"], "gameplay.pause")
        self.assertNotEqual(
            owners["cursor_secondary_at_mouse"],
            owners["game_tick"],
        )


if __name__ == "__main__":
    unittest.main()
