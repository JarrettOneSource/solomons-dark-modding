from __future__ import annotations

import copy
import unittest

from tools.native_menu_settlement_v2 import (
    OVERLAY_REFERENCE_SCHEMA,
    SettlementV2Error,
    assert_overlay_hygiene,
    assert_overlay_sample_hygiene,
    assert_confirmation_matches,
    build_overlay_contamination_override,
    build_population_phase_override,
    classify_window,
    derive_overlay_reference,
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


def _reordered_samples() -> list[dict[str, object]]:
    samples = _samples()
    for sample in samples:
        sample["payload"]["elements"] = list(  # type: ignore[index]
            reversed(sample["payload"]["elements"])  # type: ignore[index]
        )
    return samples


def _population_override_inputs() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    primary_samples = _samples()
    confirmation_samples = _reordered_samples()
    primary_layout = classify_window(primary_samples)["layout"]
    confirmation_layout = classify_window(confirmation_samples)["layout"]
    landed = copy.deepcopy(primary_samples[0]["payload"])
    landed["generation"] = 6
    landed["elements"].append(_element(99))  # type: ignore[index]
    primary_population = copy.deepcopy(landed)
    confirmation_population = copy.deepcopy(landed)
    confirmation_population["elements"] = list(  # type: ignore[index]
        reversed(confirmation_population["elements"])  # type: ignore[index]
    )
    primary_trace = {
        "structural_phases": [
            {"payload": primary_population, "observations": 1},
        ],
        "settled_window_samples": primary_samples,
    }
    confirmation_trace = {
        "structural_phases": [
            {"payload": confirmation_population, "observations": 1},
        ],
        "settled_window_samples": confirmation_samples,
    }
    return (
        landed,
        primary_layout,
        confirmation_layout,
        primary_trace,
        confirmation_trace,
    )


def _overlay_reference(elements: list[dict[str, object]]) -> dict[str, object]:
    suffixes = sorted(
        str(element["id"]).split(".art.", 1)[1] for element in elements
    )
    return {
        "schema": OVERLAY_REFERENCE_SCHEMA,
        "header": {
            "overlay_capture": {
                "evidence_path": "raw-v4/overlay.json",
                "sha256": "1" * 64,
                "bytes": 100,
            },
            "clean_capture": {
                "evidence_path": "raw-v4/clean.json",
                "sha256": "2" * 64,
                "bytes": 90,
            },
        },
        "art_element_id_suffixes": suffixes,
        "overlay_only_art_elements": copy.deepcopy(elements),
    }


def _overlay_override_inputs() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    primary_samples = _samples()
    confirmation_samples = _reordered_samples()
    primary_layout = classify_window(primary_samples)["layout"]
    confirmation_layout = classify_window(confirmation_samples)["layout"]
    overlay_elements = [_element(100), _element(101)]
    overlay_elements[0]["draw_order"] = 0
    overlay_elements[1]["draw_order"] = 1
    landed = copy.deepcopy(primary_samples[0]["payload"])
    landed["generation"] = 6
    for element in landed["elements"]:  # type: ignore[index]
        element["draw_order"] += len(overlay_elements)
    landed["elements"] = [  # type: ignore[index]
        *copy.deepcopy(overlay_elements),
        *landed["elements"],  # type: ignore[index]
    ]
    primary_population = copy.deepcopy(primary_samples[0]["payload"])
    primary_population["generation"] = 6
    confirmation_population = copy.deepcopy(primary_population)
    confirmation_population["elements"] = list(  # type: ignore[index]
        reversed(confirmation_population["elements"])  # type: ignore[index]
    )
    primary_trace = {
        "structural_phases": [
            {"payload": primary_population, "observations": 1},
        ],
        "settled_window_samples": primary_samples,
    }
    confirmation_trace = {
        "structural_phases": [
            {"payload": confirmation_population, "observations": 1},
        ],
        "settled_window_samples": confirmation_samples,
    }
    return (
        landed,
        primary_layout,
        confirmation_layout,
        primary_trace,
        confirmation_trace,
        _overlay_reference(overlay_elements),
    )


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

    def test_fresh_confirmation_does_not_widen_beyond_animated_ids(self) -> None:
        primary = classify_window(_samples(animated_count=2))["layout"]
        confirmation = copy.deepcopy(primary)
        confirmation["elements"] = list(reversed(confirmation["elements"]))
        confirmation["animated_element_ids"] = list(
            reversed(confirmation["animated_element_ids"])
        )

        assert_confirmation_matches(primary, confirmation)

    def test_settlement_ignores_only_raw_element_list_position(self) -> None:
        samples = _samples()
        for index, sample in enumerate(samples):
            if index % 2:
                sample["payload"]["elements"] = list(  # type: ignore[index]
                    reversed(sample["payload"]["elements"])  # type: ignore[index]
                )

        classified = classify_window(samples)

        self.assertEqual(classified["element_count"], 10)
        self.assertEqual(classified["layout"]["elements"][0]["id"], "screen.art.item_0.1")

    def test_cross_instance_structure_uses_draw_order_then_id(self) -> None:
        primary = classify_window(_samples())["layout"]
        confirmation = classify_window(_reordered_samples())["layout"]

        self.assertNotEqual(primary["elements"], confirmation["elements"])
        self.assertEqual(
            structural_layout_bytes(primary),
            structural_layout_bytes(confirmation),
        )

    def test_population_phase_override_is_derived_from_two_traces(self) -> None:
        override = build_population_phase_override(*_population_override_inputs())

        self.assertEqual(
            override["canonical_order"],
            "draw_order_then_element_id",
        )
        self.assertEqual(override["landed_generation"], 6)
        self.assertEqual(override["settled_generation"], 7)
        self.assertEqual(override["landed_element_count"], 11)
        self.assertEqual(override["settled_element_count"], 10)
        differences = override["structural_differences"]
        self.assertEqual(
            [(value["kind"], value.get("element_id")) for value in differences],
            [("layout_field", None), ("landed_only_element", "screen.art.item_99.1")],
        )
        for difference in differences:
            self.assertEqual(difference["primary_population_phase_indexes"], [0])
            self.assertEqual(
                difference["confirmation_population_phase_indexes"],
                [0],
            )
            self.assertEqual(difference["primary_settled_absence_samples"], 40)
            self.assertEqual(
                difference["confirmation_settled_absence_samples"],
                40,
            )

    def test_population_override_requires_second_instance_agreement(self) -> None:
        inputs = list(_population_override_inputs())
        confirmation = copy.deepcopy(inputs[2])
        confirmation["elements"][1]["text"] = "different"
        inputs[2] = confirmation

        with self.assertRaisesRegex(
            SettlementV2Error,
            "landed population override requires second-instance canonical "
            "structural agreement",
        ):
            build_population_phase_override(*inputs)

    def test_population_override_rejects_member_in_settled_window(self) -> None:
        inputs = list(_population_override_inputs())
        primary_trace = copy.deepcopy(inputs[3])
        primary_trace["settled_window_samples"][0]["payload"]["elements"].append(
            _element(99)
        )
        inputs[3] = primary_trace

        with self.assertRaisesRegex(
            SettlementV2Error,
            "landed population override rejected: differing member "
            "'screen.art.item_99.1' is present in a settled window",
        ):
            build_population_phase_override(*inputs)

    def test_population_override_requires_both_population_traces(self) -> None:
        inputs = list(_population_override_inputs())
        confirmation_trace = copy.deepcopy(inputs[4])
        confirmation_trace["structural_phases"][0]["payload"]["elements"] = [
            element
            for element in confirmation_trace["structural_phases"][0]["payload"][
                "elements"
            ]
            if element["id"] != "screen.art.item_99.1"
        ]
        inputs[4] = confirmation_trace

        with self.assertRaisesRegex(
            SettlementV2Error,
            "landed population override lacks two-instance population proof "
            "for differing member 'screen.art.item_99.1'",
        ):
            build_population_phase_override(*inputs)

    def test_population_override_uses_high_cadence_dispatch_phases(self) -> None:
        inputs = list(_population_override_inputs())
        compact_fields = (
            "id",
            "kind",
            "text",
            "action_id",
            "art_id",
            "font_id",
            "text_style",
            "visible",
            "interactive",
            "draw_order",
        )
        for trace_index in (3, 4):
            trace = copy.deepcopy(inputs[trace_index])
            high_cadence = copy.deepcopy(trace["structural_phases"])
            for phase in high_cadence:
                phase["payload_encoding"] = "structural-element-arrays-v1"
                phase["payload"]["elements"] = [
                    [element[field] for field in compact_fields]
                    for element in phase["payload"]["elements"]
                ]
            trace["high_cadence_structural_phases"] = high_cadence
            trace["structural_phases"][0]["payload"]["elements"] = [
                element
                for element in trace["structural_phases"][0]["payload"][
                    "elements"
                ]
                if element["id"] != "screen.art.item_99.1"
            ]
            inputs[trace_index] = trace

        override = build_population_phase_override(*inputs)

        vanished = next(
            difference
            for difference in override["structural_differences"]
            if difference["kind"] == "landed_only_element"
        )
        self.assertEqual(vanished["primary_population_phase_indexes"], [0])
        self.assertEqual(
            vanished["confirmation_population_phase_indexes"],
            [0],
        )

    def test_overlay_override_derives_exact_removal_and_recompaction(self) -> None:
        override = build_overlay_contamination_override(
            *_overlay_override_inputs()
        )

        self.assertEqual(
            override["rule"],
            "Settlement v2.2 landed beta-overlay contamination override",
        )
        self.assertEqual(override["landed_generation"], 6)
        self.assertEqual(override["settled_generation"], 7)
        self.assertEqual(override["landed_element_count"], 12)
        self.assertEqual(override["settled_element_count"], 10)
        self.assertEqual(
            override["overlay_art_id_suffixes"],
            ["item_100.1", "item_101.1"],
        )
        self.assertEqual(len(override["overlay_member_absence"]), 2)
        self.assertEqual(len(override["draw_order_recompaction"]), 10)

    def test_overlay_override_requires_exact_reference_set(self) -> None:
        inputs = list(_overlay_override_inputs())
        landed = copy.deepcopy(inputs[0])
        outside = _element(102)
        outside["draw_order"] = 2
        landed["elements"].append(outside)
        inputs[0] = landed

        with self.assertRaisesRegex(
            SettlementV2Error,
            "landed overlay override: landed-only art-ID suffix set does not "
            "exactly equal the overlay reference set",
        ):
            build_overlay_contamination_override(*inputs)

    def test_overlay_override_rejects_bad_draw_order_recompaction(self) -> None:
        inputs = list(_overlay_override_inputs())
        primary = copy.deepcopy(inputs[1])
        primary["elements"][3]["draw_order"] += 1
        inputs[1] = primary
        confirmation = copy.deepcopy(inputs[2])
        matching_id = primary["elements"][3]["id"]
        for element in confirmation["elements"]:
            if element["id"] == matching_id:
                element["draw_order"] += 1
        inputs[2] = confirmation

        with self.assertRaisesRegex(
            SettlementV2Error,
            "landed overlay override: draw-order recompaction arithmetic "
            "failed for surviving member",
        ):
            build_overlay_contamination_override(*inputs)

    def test_overlay_override_rejects_residual_field_difference(self) -> None:
        inputs = list(_overlay_override_inputs())
        primary = copy.deepcopy(inputs[1])
        primary["elements"][3]["text"] = "residual"
        inputs[1] = primary
        confirmation = copy.deepcopy(inputs[2])
        matching_id = primary["elements"][3]["id"]
        for element in confirmation["elements"]:
            if element["id"] == matching_id:
                element["text"] = "residual"
        inputs[2] = confirmation

        with self.assertRaisesRegex(
            SettlementV2Error,
            "landed overlay override: residual non-draw_order difference "
            "remains",
        ):
            build_overlay_contamination_override(*inputs)

    def test_overlay_hygiene_rejects_contaminated_non_overlay_screen(self) -> None:
        layout = copy.deepcopy(_samples()[0]["payload"])
        overlay = _element(100)
        layout["elements"].append(overlay)

        with self.assertRaisesRegex(
            SettlementV2Error,
            "overlay hygiene contract: non-overlay screen 'screen' "
            "intersects the beta-dialog reference art-ID set: item_100.1",
        ):
            assert_overlay_hygiene(layout, _overlay_reference([overlay]))

    def test_overlay_hygiene_allows_the_overlay_reference_screen(self) -> None:
        overlay = _element(100)
        layout = {
            "generation": 2,
            "screen_id": "beta_notice",
            "screen_title": "Beta Notice",
            "capture_method": "native",
            "elements": [overlay],
        }

        assert_overlay_hygiene(layout, _overlay_reference([overlay]))

    def test_overlay_hygiene_rejects_a_transient_contaminated_sample(self) -> None:
        samples = _samples()
        overlay = _element(100)
        samples[3]["payload"]["elements"].append(overlay)

        with self.assertRaisesRegex(
            SettlementV2Error,
            "overlay hygiene contract: sample 3 is contaminated",
        ):
            assert_overlay_sample_hygiene(
                samples,
                _overlay_reference([overlay]),
            )

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
