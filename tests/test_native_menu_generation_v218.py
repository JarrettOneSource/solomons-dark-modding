from __future__ import annotations

import copy
import unittest

from tools.native_menu_generation_v218 import (
    ADDITIONAL_FIELD_STOP,
    CORE_GENERATION_STOP,
    DISABLED_GENERATION_STOP,
    PAIRED_GENERATION_STOP,
    WINDOW_GENERATION_STOP,
    NativeMenuGenerationV218Error,
    authorize_cross_path_generation,
    compare_semantic_cores,
    measure_generation_window,
    validate_paired_route_generation,
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
            "semantic_generation": generation,
            "payload": copy.deepcopy(_layout(generation)),
        }
        for index in range(40)
    ]


def _pair(generation: int = 1) -> dict[str, object]:
    return validate_paired_route_generation(
        _samples(generation),
        _samples(generation),
        generation,
        label="picker",
    )


def _endpoint(layout: dict[str, object]) -> dict[str, object]:
    result = compare_semantic_cores(layout, layout, label="picker edge")
    result.update(
        {
            "edge_id": "control_scheme_picker_to_create",
            "side": "before",
            "generation_equal": True,
            "exact": True,
        }
    )
    return result


class NativeMenuGenerationV218Tests(unittest.TestCase):
    def test_exact_generation_only_difference_is_authorized(self) -> None:
        settled = _layout(1)
        result = authorize_cross_path_generation(
            _layout(2), settled, _pair(), [_endpoint(settled)]
        )
        self.assertEqual(result["landed_generation"], 2)
        self.assertEqual(result["settled_generation"], 1)
        self.assertTrue(result["no_other_field_excluded"])

    def test_disabled_rule_reproduces_original_generation_stop(self) -> None:
        settled = _layout(1)
        with self.assertRaisesRegex(
            NativeMenuGenerationV218Error, DISABLED_GENERATION_STOP
        ):
            authorize_cross_path_generation(
                _layout(2), settled, _pair(), [_endpoint(settled)], enabled=False
            )

    def test_semantic_core_or_order_difference_stops(self) -> None:
        settled = _layout(1)
        settled["elements"][0]["text"] = "DIFFERENT"
        with self.assertRaisesRegex(
            NativeMenuGenerationV218Error, CORE_GENERATION_STOP
        ):
            authorize_cross_path_generation(
                _layout(2), settled, _pair(), [_endpoint(settled)]
            )

    def test_generation_plus_another_layout_field_stops(self) -> None:
        settled = _layout(1)
        settled["screen_title"] = "DIFFERENT"
        with self.assertRaisesRegex(
            NativeMenuGenerationV218Error, ADDITIONAL_FIELD_STOP
        ):
            authorize_cross_path_generation(
                _layout(2), settled, _pair(), [_endpoint(settled)]
            )

    def test_capture_method_annotation_is_not_a_generation_identity_field(self) -> None:
        landed = _layout(2)
        settled = _layout(1)
        settled["capture_method"] = "settled semantic recorder"

        result = authorize_cross_path_generation(
            landed, settled, _pair(), [_endpoint(settled)]
        )

        self.assertEqual(result["semantic_core"]["differing_fields"], [])
        self.assertTrue(result["semantic_core"]["exact"])

    def test_paired_instance_generation_disagreement_stops(self) -> None:
        with self.assertRaisesRegex(
            NativeMenuGenerationV218Error, PAIRED_GENERATION_STOP
        ):
            validate_paired_route_generation(
                _samples(1), _samples(2), 1, label="picker"
            )

    def test_mid_window_generation_change_is_unsettled(self) -> None:
        samples = _samples(1)
        samples[-1]["payload"]["generation"] = 2
        samples[-1]["semantic_generation"] = 2
        with self.assertRaisesRegex(
            NativeMenuGenerationV218Error, WINDOW_GENERATION_STOP
        ):
            measure_generation_window(samples, "picker")


if __name__ == "__main__":
    unittest.main()
