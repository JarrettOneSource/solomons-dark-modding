from __future__ import annotations

import copy
import unittest

from tools.native_menu_settlement_v2 import (
    SettlementV2Error,
    assert_confirmation_matches,
    classify_window,
    find_settled_window,
    structural_layout_bytes,
    validate_declared_settlement,
)


def _element(index: int) -> dict[str, object]:
    left = float(index * 10)
    return {
        "id": f"screen.art.item_{index}.1",
        "kind": "art",
        "text": "",
        "action_id": "",
        "art_id": f"UI.{index}",
        "font_id": "",
        "text_style": "sprite",
        "visible": True,
        "interactive": False,
        "draw_order": index,
        "rect": [left, 20.0, left + 8.0, 26.0],
        "unclipped_rect": [left, 20.0, left + 8.0, 26.0],
    }


def _samples(*, animated_count: int = 1) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for sample_index in range(40):
        elements = [_element(index) for index in range(10)]
        for index in range(animated_count):
            offset = sample_index * (index + 1) * 0.25
            element = elements[index]
            element["rect"] = [
                float(index * 10) + offset,
                20.0,
                float(index * 10) + 8.0 + offset,
                26.0,
            ]
            element["unclipped_rect"] = list(element["rect"])
        result.append(
            {
                "elapsed_milliseconds": sample_index * 55,
                "captured_at_milliseconds": 1_000 + sample_index * 55,
                "payload": {
                    "generation": 7,
                    "screen_id": "screen",
                    "screen_title": "Screen",
                    "capture_method": "native",
                    "elements": elements,
                },
            }
        )
    return result


class NativeMenuSettlementV2Tests(unittest.TestCase):
    def test_measures_animation_anchor_and_envelope(self) -> None:
        classified = classify_window(_samples())

        self.assertEqual(
            classified["animated_element_ids"],
            ["screen.art.item_0.1"],
        )
        layout = classified["layout"]
        animated = layout["elements"][0]
        self.assertTrue(animated["animated_geometry"])
        self.assertEqual(animated["anchor_rect"], [0.0, 20.0, 8.0, 26.0])
        self.assertEqual(animated["envelope"]["sample_count"], 40)
        self.assertEqual(animated["envelope"]["rect"]["min_x"], 0.0)
        self.assertEqual(animated["envelope"]["rect"]["max_x"], 9.75)
        self.assertNotIn("rect", animated)
        self.assertEqual(classified["consecutive_structural_samples"], 40)
        self.assertGreaterEqual(classified["stable_span_milliseconds"], 2_000)

    def test_non_animated_rect_mutation_trips_structural_contract(self) -> None:
        samples = _samples()
        layout = copy.deepcopy(classify_window(samples)["layout"])
        layout["animated_element_ids"] = []
        animated = layout["elements"][0]
        animated.pop("animated_geometry")
        animated["rect"] = animated.pop("anchor_rect")
        animated["unclipped_rect"] = animated.pop("anchor_unclipped_rect")
        animated.pop("envelope")

        with self.assertRaisesRegex(
            SettlementV2Error,
            "structural settlement contract: non-animated element "
            "'screen.art.item_0.1' varied rect/unclipped_rect",
        ):
            validate_declared_settlement(layout, samples)

    def test_text_variation_cannot_be_presented_as_animation(self) -> None:
        samples = _samples()
        samples[-1]["payload"]["elements"][0]["text"] = "changed"
        declared = copy.deepcopy(classify_window(_samples())["layout"])

        with self.assertRaisesRegex(
            SettlementV2Error,
            "animated classification guardrail: element "
            "'screen.art.item_0.1' field 'text' varied; non-geometry changes "
            "are instability, not animation",
        ):
            validate_declared_settlement(declared, samples)

    def test_more_than_thirty_percent_animated_stops(self) -> None:
        with self.assertRaisesRegex(
            SettlementV2Error,
            r"animated geometry cap exceeded: 4/10 elements \(40.0%\) "
            r"exceeds 30% for 'screen'",
        ):
            classify_window(_samples(animated_count=4))

    def test_fresh_confirmation_requires_identical_animated_id_set(self) -> None:
        primary = classify_window(_samples(animated_count=1))["layout"]
        confirmation = classify_window(_samples(animated_count=2))["layout"]

        with self.assertRaisesRegex(
            SettlementV2Error,
            "animated ID confirmation mismatch",
        ):
            assert_confirmation_matches(primary, confirmation)

    def test_structural_comparison_ignores_only_measured_animation(self) -> None:
        candidate = classify_window(_samples())["layout"]
        landed = copy.deepcopy(candidate)
        animated = landed["elements"][0]
        animated["rect"] = [400.0, 401.0, 402.0, 403.0]
        animated["unclipped_rect"] = [400.0, 401.0, 402.0, 403.0]
        for field in (
            "animated_geometry",
            "anchor_rect",
            "anchor_unclipped_rect",
            "envelope",
        ):
            animated.pop(field, None)
        landed.pop("animated_element_ids")

        self.assertEqual(
            structural_layout_bytes(candidate),
            structural_layout_bytes(
                landed,
                candidate["animated_element_ids"],
            ),
        )
        landed["elements"][1]["rect"][0] += 1.0
        self.assertNotEqual(
            structural_layout_bytes(candidate),
            structural_layout_bytes(
                landed,
                candidate["animated_element_ids"],
            ),
        )

    def test_finder_resets_on_population_change_before_settling(self) -> None:
        transient = _samples()[:10]
        for sample in transient:
            sample["payload"]["elements"].append(_element(99))
        settled = _samples()
        offset = transient[-1]["elapsed_milliseconds"] + 55
        for sample in settled:
            sample["elapsed_milliseconds"] += offset

        result = find_settled_window(transient + settled)

        self.assertEqual(result["stable_start_index"], len(transient))
        self.assertEqual(result["stable_end_index"], 49)
        self.assertEqual(result["total_semantic_samples"], 50)


if __name__ == "__main__":
    unittest.main()
