from __future__ import annotations

import copy
import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from tools.resolve_native_menu_ambient_campaign import (
    CampaignResolutionError,
    _assert_runtime_provenance_matches,
    _resolve_layout_id,
    file_sha256,
    resolve_baseline_evidence,
)

from tools.native_menu_ambient_lifecycle import (
    AmbientLifecycleError,
    classify_ambient_extended_observation,
    classify_ambient_window,
    resolve_ambient_lifecycle,
    validate_ambient_resolution,
)
from tools.native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    diagnose_landed_layout,
    diagnosis_prereference_residual,
    semantic_overlay_corroboration,
)
from tools.native_menu_overlay_v25 import (
    OverlayV25Error,
    assert_overlay_hygiene,
    derive_overlay_reference,
    overlay_draw_payload,
)


def _art(index: int, *, art_id: str | None = None) -> dict[str, object]:
    left = float(index * 10)
    return {
        "id": f"screen.art.item_{index}.1",
        "kind": "art",
        "text": "",
        "action_id": "",
        "art_id": art_id or f"UI.{index}",
        "font_id": "",
        "text_style": "sprite",
        "visible": True,
        "interactive": False,
        "draw_order": index,
        "rect": [left, 20.0, left + 8.0, 26.0],
        "unclipped_rect": [left, 20.0, left + 8.0, 26.0],
    }


def _control(index: int) -> dict[str, object]:
    element = _art(index)
    element.update(
        {
            "id": f"screen.control.action_{index}.1",
            "kind": "control",
            "text": "Continue",
            "action_id": "continue",
            "art_id": "",
            "text_style": "button",
            "interactive": True,
        }
    )
    return element


def _samples(
    make_elements: Callable[[int], list[dict[str, object]]],
    *,
    sample_count: int = 40,
    interval_milliseconds: int = 55,
) -> list[dict[str, object]]:
    return [
        {
            "elapsed_milliseconds": sample_index * interval_milliseconds,
            "captured_at_milliseconds": 1_000
            + sample_index * interval_milliseconds,
            "semantic_surface": "menu",
            "semantic_generation": 11,
            "payload": {
                "generation": 7,
                "screen_id": "screen",
                "screen_title": "Screen",
                "capture_method": "native",
                "elements": make_elements(sample_index),
            },
        }
        for sample_index in range(sample_count)
    ]


def _stable_samples(count: int = 10) -> list[dict[str, object]]:
    return _samples(lambda _: [_art(index) for index in range(count)])


def _observation(
    samples: list[dict[str, object]], instance: str, process_id: int
) -> dict[str, object]:
    return {
        "label": instance,
        "kind": "settled_window",
        "corroboration_anchor": True,
        "instance": instance,
        "process_id": process_id,
        "samples": samples,
    }


def _resolve_pair(
    primary: list[dict[str, object]],
    confirmation: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return resolve_ambient_lifecycle(
        [
            _observation(primary, "menufx-primary", 101),
            _observation(
                confirmation if confirmation is not None else copy.deepcopy(primary),
                "menufx-confirmation",
                202,
            ),
        ]
    )


def _family_samples(*, perturb_stable: bool = False) -> list[dict[str, object]]:
    def elements(sample_index: int) -> list[dict[str, object]]:
        core = [_art(index) for index in range(3)]
        promoted = _art(20, art_id="Title.P")
        promoted["text_style"] = "structural"
        if perturb_stable:
            promoted["font_id"] = "perturbed"
        particle = _art(21, art_id="Title.P")
        particle["text_style"] = "particle"
        particle["visible"] = sample_index % 2 == 0
        return [*core, promoted, particle]

    return _samples(elements)


def _multiset_reference(elements: list[dict[str, object]]) -> dict[str, object]:
    counts: dict[bytes, int] = {}
    payloads: dict[bytes, dict[str, object]] = {}
    for element in elements:
        payload = overlay_draw_payload(element)
        signature = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        counts[signature] = counts.get(signature, 0) + 1
        payloads[signature] = payload
    return {
        "overlay_semantic_draw_multiset": [
            {"count": counts[signature], "payload": payloads[signature]}
            for signature in sorted(counts)
        ]
    }


def _overlay_derivation_inputs() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    title = [_art(0, art_id="Title.0"), _art(1, art_id="Title.1")]
    underlying = [_art(2, art_id="UI.base")]
    overlay = [_art(3, art_id="UI.dialog.a"), _art(4, art_id="UI.dialog.b")]
    main = {"structural_core": {"elements": copy.deepcopy([*title, *underlying])}}
    beta = {
        "structural_core": {
            "elements": copy.deepcopy([*title, *underlying, *overlay])
        }
    }
    reference = _multiset_reference(overlay)
    return beta, main, reference, copy.deepcopy(reference)


def _trace(
    settled_samples: list[dict[str, object]],
    population_elements: list[dict[str, object]],
    *,
    population_generation: int = 6,
) -> dict[str, object]:
    first_payload = copy.deepcopy(settled_samples[0]["payload"])
    first_payload["generation"] = population_generation
    first_payload["elements"] = copy.deepcopy(population_elements)
    return {
        "structural_phases": [
            {
                "observations": 1,
                "payload": first_payload,
            }
        ],
        "high_cadence_structural_phases": [],
        "settled_window_samples": copy.deepcopy(settled_samples),
    }


class NativeMenuAmbientLifecycleTests(unittest.TestCase):
    def test_path_local_layout_generations_do_not_change_screen_identity(self) -> None:
        primary = _stable_samples(3)
        confirmation = copy.deepcopy(primary)
        for sample in confirmation:
            sample["semantic_generation"] = 19
            sample["payload"]["generation"] = 19

        resolved = _resolve_pair(primary, confirmation)

        self.assertEqual(
            resolved["identity"]["observed_layout_generations"], [7, 19]
        )
        self.assertEqual(resolved["structural_core_element_count"], 3)

    def test_runtime_provenance_allows_independent_capture_commits(self) -> None:
        observed = {
            "base_commit_sha": "1" * 40,
            "source_tree_sha": "2" * 40,
            "game_executable_sha256": "3" * 64,
            "loader_dll_sha256": "4" * 64,
        }
        reference = {
            **observed,
            "base_commit_sha": "5" * 40,
            "source_tree_sha": "6" * 40,
        }

        _assert_runtime_provenance_matches(observed, reference, "independent capture")

        reference["loader_dll_sha256"] = "7" * 64
        with self.assertRaisesRegex(
            CampaignResolutionError,
            "independent capture changed runtime provenance field "
            "'loader_dll_sha256'",
        ):
            _assert_runtime_provenance_matches(
                observed, reference, "independent capture"
            )

    def test_extended_baseline_receipt_resolves_exact_recording_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path = root / "hub-primary.baseline.json"
            baseline_path.write_text(
                json.dumps(
                    {
                        "schema": "solomon-dark-native-menu-layout-v2",
                        "header": {"label": "hub"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            receipt = {
                "sha256": file_sha256(baseline_path),
                "bytes": baseline_path.stat().st_size,
                "selector": {
                    "schema": "solomon-dark-native-menu-layout-v2",
                },
            }

            resolved_path, recording = resolve_baseline_evidence(
                root, receipt, "hub motion"
            )

            self.assertEqual(resolved_path, baseline_path.resolve())
            self.assertEqual(
                recording["schema"], "solomon-dark-native-menu-layout-v2"
            )

    def test_extended_baseline_receipt_rejects_absent_or_duplicate_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path = root / "hub-primary.baseline.json"
            baseline_path.write_text(
                '{"schema":"solomon-dark-native-menu-layout-v2"}\n',
                encoding="utf-8",
            )
            receipt = {
                "sha256": "0" * 64,
                "bytes": baseline_path.stat().st_size,
                "selector": {
                    "schema": "solomon-dark-native-menu-layout-v2",
                },
            }
            with self.assertRaisesRegex(
                CampaignResolutionError,
                "extended observation baseline receipt does not resolve exactly "
                "one byte-identical evidence file",
            ):
                resolve_baseline_evidence(root, receipt, "hub motion")

            receipt["sha256"] = file_sha256(baseline_path)
            (root / "duplicate.json").write_bytes(baseline_path.read_bytes())
            with self.assertRaisesRegex(
                CampaignResolutionError,
                "extended observation baseline receipt does not resolve exactly "
                "one byte-identical evidence file",
            ):
                resolve_baseline_evidence(root, receipt, "hub motion")

    def test_ambiguous_settings_screen_requires_exact_edge_route(self) -> None:
        fixtures = {
            "game-settings-title": {"native_screen_id": "settings"},
            "game-settings-gameplay": {"native_screen_id": "settings"},
            "game-settings-dark-cloud": {"native_screen_id": "settings"},
        }

        layout_id, used_explicit_mapping = _resolve_layout_id(
            "settings",
            "settings",
            fixtures,
            "main_to_settings",
            "after",
        )

        self.assertEqual(layout_id, "game-settings-title")
        self.assertTrue(used_explicit_mapping)
        with self.assertRaisesRegex(
            CampaignResolutionError,
            "is ambiguous without explicit route mapping for edge "
            "'unknown_settings_edge' side 'before'",
        ):
            _resolve_layout_id(
                "settings",
                "settings",
                fixtures,
                "unknown_settings_edge",
                "before",
            )

    def test_non_element_structural_field_variance_stops_settlement(self) -> None:
        samples = _stable_samples()
        samples[20]["payload"]["screen_title"] = "Changed"  # type: ignore[index]

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "non-element payload field 'screen_title' varied",
        ):
            classify_ambient_window(samples)

    def test_churn_on_control_member_is_not_classifiable(self) -> None:
        samples = _samples(
            lambda sample_index: [
                _art(0),
                *([_control(1)] if sample_index % 2 == 0 else []),
            ]
        )

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "ambient lifecycle art-only guard: membership churn on "
            "text/control member 'screen.control.action_1.1' is not classifiable",
        ):
            classify_ambient_window(samples)

    def test_visible_variance_on_control_member_is_not_classifiable(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            control = _control(1)
            control["visible"] = sample_index % 2 == 0
            return [_art(0), control]

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "ambient lifecycle art-only guard: visible variance on "
            "text/control member 'screen.control.action_1.1' is not classifiable",
        ):
            classify_ambient_window(_samples(elements))

    def test_core_relative_order_flip_trips(self) -> None:
        samples = _stable_samples(3)
        samples[20]["payload"]["elements"][0]["draw_order"] = 2.5  # type: ignore[index]

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "relative draw sequence contract: structural core relative-order flip",
        ):
            _resolve_pair(samples)

    def test_cross_instance_core_byte_inequality_trips(self) -> None:
        primary = _stable_samples(3)
        confirmation = copy.deepcopy(primary)
        for sample in confirmation:
            sample["payload"]["elements"][0]["font_id"] = "different"  # type: ignore[index]

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "cross-instance structural core inequality: non-ambient "
            "full-presence member 'UI.0' differs or is missing",
        ):
            _resolve_pair(primary, confirmation)

    def test_reproduced_family_art_promotes_to_core(self) -> None:
        resolved = _resolve_pair(_family_samples())

        promoted = [
            element
            for element in resolved["structural_core"]["elements"]
            if element.get("art_id") == "Title.P"
        ]
        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0]["text_style"], "structural")

    def test_nonreproduced_family_art_demotes_to_ambient_persistent(self) -> None:
        resolved = _resolve_pair(
            _family_samples(), _family_samples(perturb_stable=True)
        )

        promoted = [
            element
            for element in resolved["structural_core"]["elements"]
            if element.get("art_id") == "Title.P"
        ]
        self.assertEqual(promoted, [])
        family = next(
            entry
            for entry in resolved["ambient_members"]
            if entry["art_id"] == "Title.P"
        )
        self.assertIn(
            "ambient_persistent", resolved["classification_map"][family["id"]]
        )

    def test_ambient_fraction_above_forty_percent_stops(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            core = [_art(index) for index in range(5)]
            cycling: list[dict[str, object]] = []
            for index in range(5, 10):
                element = _art(index, art_id=f"Title.{index}")
                element["visible"] = (sample_index + index) % 2 == 0
                cycling.append(element)
            return [*core, *cycling]

        samples = _samples(elements)
        with self.assertRaisesRegex(
            AmbientLifecycleError,
            r"ambient lifecycle cap exceeded: 5/10 semantic members "
            r"\(50.0%\) exceeds 40%",
        ):
            _resolve_pair(samples)

    def test_one_way_spawn_without_family_despawn_is_population_not_ephemeral(
        self,
    ) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            return [
                _art(0),
                *([_art(1, art_id="Title.1")] if sample_index >= 20 else []),
            ]

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "population-versus-ephemeral guardrail: ephemeral family lacks "
            "bidirectional spawn and despawn witnesses",
        ):
            _resolve_pair(_samples(elements))

    def test_family_wide_bidirectional_churn_resolves_one_way_members(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            return [
                *[_art(index) for index in range(5)],
                *([_art(10, art_id="Title.1")] if sample_index >= 20 else []),
                *([_art(11, art_id="Title.2")] if sample_index < 20 else []),
            ]

        resolved = _resolve_pair(_samples(elements))

        self.assertEqual(
            resolved["ephemeral_family"]["art_ids"], ["Title.1", "Title.2"]
        )
        self.assertTrue(
            resolved["ephemeral_family"]["bidirectional_churn_witnessed"]
        )

    def test_nonfamily_rect_animation_above_thirty_percent_stops(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            result = [_art(index) for index in range(10)]
            for index in range(4):
                offset = sample_index * 0.25
                result[index]["rect"] = [
                    index * 10.0 + offset,
                    20.0,
                    index * 10.0 + 8.0 + offset,
                    26.0,
                ]
                result[index]["unclipped_rect"] = list(result[index]["rect"])
            return result

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            r"animated geometry cap exceeded: 4/10 elements \(40.0%\) "
            r"exceeds 30%",
        ):
            classify_ambient_window(_samples(elements))

    def test_rect_only_control_motion_remains_an_authorized_animation(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            result = [_art(index) for index in range(5)]
            control = _control(10)
            offset = sample_index * 0.25
            control["rect"] = [100.0 + offset, 20.0, 108.0 + offset, 26.0]
            control["unclipped_rect"] = list(control["rect"])
            return [*result, control]

        resolved = _resolve_pair(_samples(elements))

        self.assertEqual(len(resolved["animated_element_ids"]), 1)
        animated = next(
            entry
            for entry in resolved["ambient_members"]
            if entry["id"] == resolved["animated_element_ids"][0]
        )
        self.assertTrue(animated["member_key"].startswith("member:"))

    def test_stationary_side_of_motion_mismatch_requires_extended_evidence(
        self,
    ) -> None:
        def moving(sample_index: int) -> list[dict[str, object]]:
            result = [_art(index) for index in range(5)]
            offset = sample_index * 0.25
            result[0]["rect"] = [offset, 20.0, 8.0 + offset, 26.0]
            result[0]["unclipped_rect"] = list(result[0]["rect"])
            return result

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "motion capability resolution requires extended-observation evidence "
            "for stationary member 'screen.art.item_0.1' in instance "
            "'menufx-confirmation' PID 202",
        ):
            _resolve_pair(_samples(moving), _stable_samples(5))

    def test_extended_stationary_evidence_resolves_motion_asymmetrically(self) -> None:
        def moving(sample_index: int) -> list[dict[str, object]]:
            result = [_art(index) for index in range(5)]
            offset = sample_index * 0.25
            result[0]["rect"] = [offset, 20.0, 8.0 + offset, 26.0]
            result[0]["unclipped_rect"] = list(result[0]["rect"])
            return result

        resolved = resolve_ambient_lifecycle(
            [
                _observation(_samples(moving), "menufx-primary", 101),
                _observation(_stable_samples(5), "menufx-confirmation", 202),
                {
                    **_observation(
                        _samples(
                            lambda _: [_art(index) for index in range(5)],
                            sample_count=200,
                            interval_milliseconds=310,
                        ),
                        "menufx-confirmation",
                        202,
                    ),
                    "kind": "extended_observation",
                    "label": "confirmation-extension",
                },
            ]
        )

        self.assertEqual(len(resolved["animated_element_ids"]), 1)
        self.assertEqual(len(resolved["motion_capability_corroborations"]), 1)

    def test_navigation_replays_do_not_multiply_corroboration_duty(self) -> None:
        def moving(sample_index: int) -> list[dict[str, object]]:
            result = [_art(index) for index in range(5)]
            offset = sample_index * 0.25
            result[0]["rect"] = [offset, 20.0, 8.0 + offset, 26.0]
            result[0]["unclipped_rect"] = list(result[0]["rect"])
            return result

        navigation_replay = {
            **_observation(_stable_samples(5), "menufx-navigation", 303),
            "label": "navigation-replay",
            "corroboration_anchor": False,
        }
        extension = {
            **_observation(
                _samples(
                    lambda _: [_art(index) for index in range(5)],
                    sample_count=200,
                    interval_milliseconds=310,
                ),
                "menufx-confirmation",
                202,
            ),
            "kind": "extended_observation",
            "label": "confirmation-extension",
            "corroboration_anchor": False,
        }

        resolved = resolve_ambient_lifecycle(
            [
                _observation(_samples(moving), "menufx-primary", 101),
                _observation(_stable_samples(5), "menufx-confirmation", 202),
                navigation_replay,
                extension,
            ]
        )

        self.assertEqual(len(resolved["animated_element_ids"]), 1)
        self.assertEqual(len(resolved["motion_capability_corroborations"]), 1)

    def test_declared_phantom_ambient_class_is_a_recorder_defect(self) -> None:
        observations = [
            _observation(_stable_samples(3), "menufx-primary", 101),
            _observation(_stable_samples(3), "menufx-confirmation", 202),
        ]
        declared = resolve_ambient_lifecycle(observations)
        declared = copy.deepcopy(declared)
        declared["classification_map"]["UI.phantom"] = ["animated"]

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "ambient lifecycle recorder defect: phantom ambient classification "
            "'animated' for art family 'UI.phantom' has zero observed events",
        ):
            validate_ambient_resolution(declared, observations)

    def test_surface_or_generation_change_prevents_settlement(self) -> None:
        samples = _stable_samples(3)
        samples[-1]["semantic_generation"] = 12

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "surface, semantic generation, layout generation, or screen changed",
        ):
            classify_ambient_window(samples)

    def test_empty_semantic_surface_is_a_constant_gameplay_surface(self) -> None:
        samples = _stable_samples(3)
        for sample in samples:
            sample["semantic_surface"] = ""

        classified = classify_ambient_window(samples)

        self.assertEqual(
            classified["window_classification"]["identity"]["semantic_surface"],
            "",
        )

    def test_non_string_semantic_surface_is_a_recorder_defect(self) -> None:
        samples = _stable_samples(3)
        samples[-1]["semantic_surface"] = None

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "ambient lifecycle recorder defect: sample has no semantic surface",
        ):
            classify_ambient_window(samples)

    def test_extended_observation_records_motion_and_lifecycle_events(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            result = [_art(index) for index in range(5)]
            if sample_index >= 100:
                result[0]["rect"][0] = 1.0  # type: ignore[index]
                result[0]["rect"][2] = 9.0  # type: ignore[index]
                result[0]["unclipped_rect"] = list(result[0]["rect"])
            if sample_index < 150:
                result.append(_art(10, art_id="Title.10"))
            return result

        classified = classify_ambient_extended_observation(
            _samples(
                elements,
                sample_count=200,
                interval_milliseconds=310,
            ),
            required_span_milliseconds=60_000,
        )

        self.assertEqual(classified["motion_event_count"], 1)
        self.assertEqual(classified["motion_events"][0]["sample_index"], 100)
        self.assertEqual(classified["lifecycle_event_count"], 1)
        self.assertEqual(
            classified["lifecycle_events"][0]["event"], "despawn"
        )

    def test_overlay_reference_derives_and_corroborates_exact_multiset(self) -> None:
        reference = derive_overlay_reference(*_overlay_derivation_inputs())

        self.assertEqual(reference["overlay_semantic_draw_count"], 2)
        self.assertEqual(len(reference["overlay_semantic_draw_multiset"]), 2)

    def test_overlay_derivation_trips_when_title_core_member_is_missing(self) -> None:
        beta, main, create, pause = _overlay_derivation_inputs()
        beta["structural_core"]["elements"] = [  # type: ignore[index]
            element
            for element in beta["structural_core"]["elements"]  # type: ignore[index]
            if element["art_id"] != "Title.1"
        ]

        with self.assertRaisesRegex(
            OverlayV25Error,
            "overlay reference derivation: title-core member is missing from "
            "beta_notice structural core",
        ):
            derive_overlay_reference(beta, main, create, pause)

    def test_overlay_corroboration_trips_on_one_perturbed_draw(self) -> None:
        beta, main, create, pause = _overlay_derivation_inputs()
        payloads = [
            copy.deepcopy(entry["payload"])
            for entry in pause["overlay_semantic_draw_multiset"]  # type: ignore[index]
        ]
        payloads[0]["font_id"] = "perturbed"
        pause = _multiset_reference(payloads)

        with self.assertRaisesRegex(
            OverlayV25Error,
            "overlay reference corroboration: derived beta-dialog multiset does "
            "not equal the proven Create and pause correction multisets",
        ):
            derive_overlay_reference(beta, main, create, pause)

    def test_derived_overlay_hygiene_refuses_complete_multiset(self) -> None:
        beta, main, create, pause = _overlay_derivation_inputs()
        reference = derive_overlay_reference(beta, main, create, pause)
        layout = {
            "screen_id": "pause_menu",
            "elements": copy.deepcopy(beta["structural_core"]["elements"]),  # type: ignore[index]
        }

        with self.assertRaisesRegex(
            OverlayV25Error,
            "overlay hygiene contract: non-overlay screen contains the complete "
            "derived beta-dialog semantic multiset",
        ):
            assert_overlay_hygiene(layout, reference)

    def test_derived_overlay_hygiene_accepts_partial_suffix_sharing(self) -> None:
        beta, main, create, pause = _overlay_derivation_inputs()
        reference = derive_overlay_reference(beta, main, create, pause)
        layout = {
            "screen_id": "pause_menu",
            "elements": [
                copy.deepcopy(beta["structural_core"]["elements"][-1])  # type: ignore[index]
            ],
        }

        assert_overlay_hygiene(layout, reference)

    def test_landed_diagnosis_strict_screen_matches_reproduced_core(self) -> None:
        samples = _stable_samples(3)
        settled = _resolve_pair(samples)
        landed = copy.deepcopy(samples[0]["payload"])
        trace = _trace(samples, copy.deepcopy(landed["elements"]))
        unused_overlay = _multiset_reference([_art(99, art_id="UI.overlay")])

        diagnosis = diagnose_landed_layout(
            landed,
            {**settled["structural_core"], **{
                key: copy.deepcopy(settled[key])
                for key in ("ambient_members",)
            }},
            trace,
            copy.deepcopy(trace),
            unused_overlay,
        )

        self.assertEqual(diagnosis["status"], "strict_structural_bit_match")

    def test_landed_diagnosis_assigns_visibility_cycle_before_other_legs(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            cycling = _art(9, art_id="Title.9")
            cycling["visible"] = sample_index % 2 == 0
            return [_art(index) for index in range(3)] + [cycling]

        samples = _samples(elements)
        settled = _resolve_pair(samples)
        settled_layout = {
            **settled["structural_core"],
            "ambient_members": copy.deepcopy(settled["ambient_members"]),
        }
        landed = copy.deepcopy(samples[0]["payload"])
        trace = _trace(samples, copy.deepcopy(landed["elements"]))
        unused_overlay = _multiset_reference([_art(99, art_id="UI.overlay")])

        diagnosis = diagnose_landed_layout(
            landed, settled_layout, trace, copy.deepcopy(trace), unused_overlay
        )

        self.assertEqual(len(diagnosis["ambient_lifecycle_dispositions"]), 1)
        self.assertEqual(diagnosis["population_phase_dispositions"], [])
        self.assertEqual(diagnosis["overlay_dispositions"], [])

    def test_landed_diagnosis_requires_two_trace_population_witnesses(self) -> None:
        samples = _stable_samples(3)
        settled = _resolve_pair(samples)
        settled_layout = {
            **settled["structural_core"],
            "ambient_members": copy.deepcopy(settled["ambient_members"]),
        }
        vanished = _art(9, art_id="UI.population")
        landed = copy.deepcopy(samples[0]["payload"])
        landed["generation"] = 6
        landed["elements"].append(copy.deepcopy(vanished))
        primary = _trace(samples, copy.deepcopy(landed["elements"]))
        confirmation = _trace(samples, copy.deepcopy(samples[0]["payload"]["elements"]))
        unused_overlay = _multiset_reference([_art(99, art_id="UI.overlay")])

        with self.assertRaisesRegex(
            LandedDiagnosisError,
            "landed-vs-settled mismatch survives ambient, population, overlay, "
            "and animation diagnosis",
        ):
            diagnose_landed_layout(
                landed,
                settled_layout,
                primary,
                confirmation,
                unused_overlay,
            )

    def test_landed_diagnosis_accepts_two_trace_population_member(self) -> None:
        samples = _stable_samples(3)
        settled = _resolve_pair(samples)
        settled_layout = {
            **settled["structural_core"],
            "ambient_members": copy.deepcopy(settled["ambient_members"]),
        }
        vanished = _art(9, art_id="UI.population")
        landed = copy.deepcopy(samples[0]["payload"])
        landed["generation"] = 6
        landed["elements"].append(copy.deepcopy(vanished))
        trace = _trace(samples, copy.deepcopy(landed["elements"]))
        unused_overlay = _multiset_reference([_art(99, art_id="UI.overlay")])

        diagnosis = diagnose_landed_layout(
            landed, settled_layout, trace, copy.deepcopy(trace), unused_overlay
        )

        self.assertEqual(len(diagnosis["population_phase_dispositions"]), 1)
        self.assertTrue(
            diagnosis["population_proof"][
                "generation_difference_witnessed_in_both_traces"
            ]
        )

    def test_landed_diagnosis_accepts_exact_semantic_overlay_only(self) -> None:
        samples = _stable_samples(3)
        settled = _resolve_pair(samples)
        settled_layout = {
            **settled["structural_core"],
            "ambient_members": copy.deepcopy(settled["ambient_members"]),
        }
        overlay = [_art(90, art_id="UI.dialog.a"), _art(91, art_id="UI.dialog.b")]
        landed = copy.deepcopy(samples[0]["payload"])
        landed["generation"] = 6
        landed["elements"].extend(copy.deepcopy(overlay))
        population_elements = copy.deepcopy(samples[0]["payload"]["elements"])
        trace = _trace(samples, population_elements)
        reference = _multiset_reference(overlay)

        diagnosis = diagnose_landed_layout(
            landed, settled_layout, trace, copy.deepcopy(trace), reference
        )

        self.assertEqual(len(diagnosis["overlay_dispositions"]), 2)
        self.assertEqual(diagnosis["population_phase_dispositions"], [])

    def test_landed_diagnosis_corroboration_excludes_measured_motion(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            moving = _art(8, art_id="Create.moving")
            moving["rect"][0] += sample_index * 0.1  # type: ignore[index]
            moving["rect"][2] += sample_index * 0.1  # type: ignore[index]
            moving["unclipped_rect"] = list(moving["rect"])
            return [_art(index) for index in range(4)] + [moving]

        samples = _samples(elements)
        settled = _resolve_pair(samples)
        settled_layout = {
            **settled["structural_core"],
            "ambient_members": copy.deepcopy(settled["ambient_members"]),
        }
        overlay = _art(90, art_id="UI.dialog")
        landed = copy.deepcopy(samples[0]["payload"])
        landed["elements"].append(copy.deepcopy(overlay))

        residual, ambient = diagnosis_prereference_residual(
            landed, settled_layout
        )
        corroboration = semantic_overlay_corroboration(residual)

        self.assertEqual(len(ambient), 1)
        self.assertEqual(corroboration["overlay_semantic_draw_count"], 1)


if __name__ == "__main__":
    unittest.main()
