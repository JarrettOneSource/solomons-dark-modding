from __future__ import annotations

import copy
import unittest

from tools.native_menu_generation_v218 import (
    RECORDED_GENERATION_STOP,
    WINDOW_GENERATION_STOP,
)
from tools.native_menu_generation_v219 import (
    PAIR_CORE_STOP,
    NativeMenuGenerationV219Error,
    authorize_cross_path_generation,
    derive_pair_core_equality,
    validate_instance_local_generation_pair,
)


def _layout(generation: int) -> dict[str, object]:
    return {
        "generation": generation,
        "screen_id": "control_scheme_picker",
        "screen_title": "SELECT A CONTROL SCHEME",
        "capture_method": "live native UI tree",
        "elements": [
            {
                "id": "control_scheme_picker.text.prompt.1",
                "kind": "text",
                "text": "SELECT A CONTROL SCHEME",
                "action_id": "",
                "art_id": "",
                "font_id": "Fonts.test",
                "text_style": "native",
                "visible": True,
                "interactive": False,
                "draw_order": 0,
                "rect": [10.0, 20.0, 30.0, 40.0],
                "unclipped_rect": [10.0, 20.0, 30.0, 40.0],
            }
        ],
    }


def _samples(generation: int) -> list[dict[str, object]]:
    return [
        {
            "elapsed_milliseconds": index * 60,
            "semantic_surface": "control_scheme_picker",
            "semantic_generation": generation,
            "payload": copy.deepcopy(_layout(generation)),
        }
        for index in range(40)
    ]


def _core(
    primary: list[dict[str, object]],
    confirmation: list[dict[str, object]],
) -> dict[str, object]:
    return derive_pair_core_equality(
        primary,
        confirmation,
        _layout(1),
        label="picker",
        bound_endpoints=["control_scheme_picker_to_create.before"],
        bound_endpoint_census_complete=True,
    )


class NativeMenuGenerationV219Tests(unittest.TestCase):
    def test_instance_local_generation_difference_passes_after_exact_core(self) -> None:
        primary = _samples(1)
        confirmation = _samples(3)
        core = _core(primary, confirmation)
        result = validate_instance_local_generation_pair(
            primary, confirmation, 1, core, label="picker"
        )
        self.assertEqual(result["primary"]["generation"], 1)
        self.assertEqual(result["confirmation"]["generation"], 3)
        self.assertTrue(result["paired_core_equality"]["zero_residual"])

    def test_equal_generation_core_difference_stops(self) -> None:
        primary = _samples(1)
        confirmation = _samples(1)
        confirmation[-1]["payload"]["elements"][0]["rect"][0] += 1
        with self.assertRaisesRegex(
            NativeMenuGenerationV219Error, PAIR_CORE_STOP
        ):
            _core(primary, confirmation)

    def test_generation_difference_never_masks_core_difference(self) -> None:
        primary = _samples(1)
        confirmation = _samples(2)
        confirmation[-1]["payload"]["elements"][0]["text"] = "DIFFERENT"
        with self.assertRaisesRegex(
            NativeMenuGenerationV219Error, PAIR_CORE_STOP
        ):
            _core(primary, confirmation)

    def test_mid_window_generation_change_remains_unsettled(self) -> None:
        primary = _samples(1)
        confirmation = _samples(1)
        confirmation[-1]["payload"]["generation"] = 2
        confirmation[-1]["semantic_generation"] = 2
        with self.assertRaisesRegex(
            NativeMenuGenerationV219Error, WINDOW_GENERATION_STOP
        ):
            _core(primary, confirmation)

    def test_hand_edited_fixture_generation_breaks_receipt_chain(self) -> None:
        primary = _samples(1)
        confirmation = _samples(2)
        core = _core(primary, confirmation)
        with self.assertRaisesRegex(
            NativeMenuGenerationV219Error, RECORDED_GENERATION_STOP
        ):
            validate_instance_local_generation_pair(
                primary, confirmation, 2, core, label="picker"
            )

    def test_landed_cross_path_exclusion_stays_field_bounded(self) -> None:
        primary = _samples(1)
        confirmation = _samples(2)
        core = _core(primary, confirmation)
        pair = validate_instance_local_generation_pair(
            primary, confirmation, 1, core, label="picker"
        )
        endpoint = {
            "semantic_multiset_equal": True,
            "relative_sequence_equal": True,
            "zero_residual": True,
            "exact": True,
        }
        result = authorize_cross_path_generation(
            _layout(2), _layout(1), pair, [endpoint]
        )
        self.assertEqual(result["field_scope"], ["generation", "semantic_generation"])
        self.assertTrue(result["no_other_field_excluded"])


if __name__ == "__main__":
    unittest.main()
