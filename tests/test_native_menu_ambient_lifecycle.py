from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from tools.resolve_native_menu_ambient_campaign import (
    CampaignResolutionError,
    PATH_DEPENDENT_CORE_ENDPOINTS,
    PATH_DEPENDENT_CORE_LAYOUTS,
    _assert_game_executable_matches,
    _assert_runtime_provenance_matches,
    _resolve_layout_id,
    build_extended_baseline_filename_map,
    collect_supplemental_standalones,
    file_sha256,
    resolve_baseline_evidence,
    validate_path_dependent_core_forks,
)

from tools.native_menu_ambient_lifecycle import (
    AmbientLifecycleError,
    classify_ambient_extended_observation,
    classify_ambient_window,
    find_ambient_settled_window,
    reproduce_standalone_structural_core,
    resolve_ambient_lifecycle,
    validate_ambient_resolution,
)
from tools.native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    _signature,
    _v29_beta_notice_order_projection,
    diagnose_landed_layout,
    diagnosis_prereference_residual,
    match_ambient_members,
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
    *,
    asset_manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    return resolve_ambient_lifecycle(
        [
            _observation(primary, "menufx-primary", 101),
            _observation(
                confirmation if confirmation is not None else copy.deepcopy(primary),
                "menufx-confirmation",
                202,
            ),
        ],
        asset_manifest=asset_manifest,
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


def _two_band_ephemeral_samples(*, include_upper_band: bool = True) -> list[dict[str, object]]:
    def elements(sample_index: int) -> list[dict[str, object]]:
        core = [_art(index) for index in range(3)]
        for element, draw_order in zip(core, (0, 10, 20), strict=True):
            element["draw_order"] = draw_order
        if sample_index % 2:
            return core
        particle = _art(10, art_id="Title.spark")
        particle["id"] = "screen.art.spark.1"
        particle["draw_order"] = (
            15 if include_upper_band and sample_index % 4 == 2 else 5
        )
        return [*core, particle]

    return _samples(elements)


def _same_art_disjoint_phase_samples(phase: float) -> list[dict[str, object]]:
    def elements(sample_index: int) -> list[dict[str, object]]:
        core = [_art(index) for index in range(7)]
        movers: list[dict[str, object]] = []
        for index in range(3):
            mover = _art(20 + index, art_id="UI.scroll")
            mover["id"] = f"screen.art.scroll.{index + 1}"
            left = phase + index * 100.0 + sample_index * 0.25
            mover["rect"] = [left, 100.0, left + 80.0, 120.0]
            mover["unclipped_rect"] = list(mover["rect"])
            mover["draw_order"] = 100 + index
            movers.append(mover)
        return [*core, *movers]

    return _samples(elements)


def _skill_picker_animated_family_samples(
    phase: float = 0.0,
) -> list[dict[str, object]]:
    def elements(sample_index: int) -> list[dict[str, object]]:
        core = [_art(index, art_id=f"Core.{index}") for index in range(31)]
        movers: list[dict[str, object]] = []
        for index in range(8):
            mover = _art(100 + index, art_id="UI.3")
            mover["id"] = f"skill_picker.art.ui_3.{index + 1}"
            left = phase + index * 100.0 + sample_index * 10.0
            mover["rect"] = [left, 100.0, left + 80.0, 120.0]
            mover["unclipped_rect"] = list(mover["rect"])
            mover["draw_order"] = 100 + ((index + sample_index // 4) % 8)
            movers.append(mover)
        rings: list[dict[str, object]] = []
        for index, top in enumerate((300.0, 500.0), start=1):
            ring = _art(200 + index, art_id="UI.62")
            ring["id"] = f"skill_picker.art.ui_62.{index}"
            left = 500.0 + phase + sample_index * 0.25
            ring["rect"] = [left, top, left + 80.0, top + 80.0]
            ring["unclipped_rect"] = list(ring["rect"])
            ring["draw_order"] = 200 + index
            rings.append(ring)
        return [*core, *movers, *rings]

    samples = _samples(elements)
    for sample in samples:
        sample["payload"]["screen_id"] = "skill_picker"  # type: ignore[index]
        sample["payload"]["generation"] = 8  # type: ignore[index]
    return samples


def _skill_picker_choice_manifest() -> dict[str, object]:
    return {
        "schema": "solomon-dark-web-asset-manifest-v1",
        "entries": {
            "Skills.48": {"logicalSize": {"width": 28, "height": 42}},
            "Skills.83": {"logicalSize": {"width": 43, "height": 43}},
            "Skills.45": {"logicalSize": {"width": 46, "height": 46}},
            "Skills.92": {"logicalSize": {"width": 41, "height": 46}},
        },
    }


def _skill_picker_choice_samples(
    roster: tuple[str, str],
    *,
    phase: float = 0.0,
    first_anchor_delta: tuple[float, float] = (0.0, 0.0),
    second_draw_offset: tuple[float, float] = (-4.0, -4.0),
) -> list[dict[str, object]]:
    logical_sizes = {
        "Skills.48": (28.0, 42.0),
        "Skills.83": (43.0, 43.0),
        "Skills.45": (46.0, 46.0),
        "Skills.92": (41.0, 46.0),
    }

    def choice(
        order: int,
        art_id: str,
        anchor: tuple[float, float],
        offset: tuple[float, float],
    ) -> dict[str, object]:
        width, height = logical_sizes[art_id]
        center_x = anchor[0] + offset[0]
        center_y = anchor[1] + offset[1]
        element = _art(order, art_id=art_id)
        element["id"] = f"skill_picker.art.choice_{order}.1"
        element["draw_order"] = order
        element["rect"] = [
            center_x - width / 2.0,
            center_y - height / 2.0,
            center_x + width / 2.0,
            center_y + height / 2.0,
        ]
        element["unclipped_rect"] = list(element["rect"])
        return element

    def elements(sample_index: int) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for order in range(1, 42):
            if 11 <= order <= 18:
                index = order - 11
                mover = _art(100 + index, art_id="UI.3")
                mover["id"] = f"skill_picker.art.ui_3.{index + 1}"
                left = phase + index * 100.0 + sample_index * 10.0
                mover["rect"] = [left, 100.0, left + 80.0, 120.0]
                mover["unclipped_rect"] = list(mover["rect"])
                mover["draw_order"] = 11 + ((index + sample_index // 4) % 8)
                result.append(mover)
                continue
            if order in {19, 20}:
                index = order - 18
                ring = _art(200 + index, art_id="UI.62")
                ring["id"] = f"skill_picker.art.ui_62.{index}"
                top = 300.0 if order == 19 else 500.0
                left = 500.0 + phase + sample_index * 0.25
                ring["rect"] = [left, top, left + 80.0, top + 80.0]
                ring["unclipped_rect"] = list(ring["rect"])
                ring["draw_order"] = order
                result.append(ring)
                continue
            if order in {30, 31}:
                anchor = (
                    604.0 + first_anchor_delta[0],
                    386.5 + first_anchor_delta[1],
                )
                offset = (0.0, 0.0) if order == 30 else second_draw_offset
                result.append(choice(order, roster[0], anchor, offset))
                continue
            if order in {40, 41}:
                offset = (0.0, 0.0) if order == 40 else (-4.0, -4.0)
                result.append(choice(order, roster[1], (1004.0, 386.5), offset))
                continue
            core = _art(order, art_id=f"Core.{order}")
            core["draw_order"] = order
            result.append(core)
        return result

    samples = _samples(elements, interval_milliseconds=390)
    for sample in samples:
        sample["payload"]["screen_id"] = "skill_picker"  # type: ignore[index]
        sample["payload"]["generation"] = 8  # type: ignore[index]
    return samples


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


def _v29_order_case() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    remaining = [_art(index, art_id=f"Core.{index}") for index in range(4)]
    trio = [_art(20 + index, art_id=f"UI.dialog.{index}") for index in range(3)]
    landed_elements = [remaining[0], *trio, *remaining[1:]]
    for draw_order, element in enumerate(landed_elements):
        element["draw_order"] = draw_order
    settled_elements = copy.deepcopy([*remaining, *trio])
    landed = {
        "screen_id": "beta_notice",
        "screen_title": "Beta notice",
        "generation": 13,
        "elements": landed_elements,
    }
    settled = {
        "screen_id": "beta_notice",
        "screen_title": "Beta notice",
        "generation": 2,
        "elements": settled_elements,
        "ambient_members": [],
    }
    contract = {
        "schema": "solomon-dark-native-menu-beta-notice-order-v29",
        "layout_id": "beta-notice",
        "screen_id": "beta_notice",
        "core_member_count": len(settled_elements),
        "longest_common_subsequence_count": len(remaining),
        "moved_members": [
            {
                "art_id": element["art_id"],
                "rect": copy.deepcopy(element["rect"]),
                "semantic_sha256": hashlib.sha256(_signature(element)).hexdigest(),
                "landed_relative_core_index": index + 1,
                "settled_relative_core_index": len(remaining) + index,
                "native_paint_order": 100 + index,
                "overlay_reference_member": True,
            }
            for index, element in enumerate(trio)
        ],
        "paint_truth": {"source": "synthetic-test"},
        "source_stop_audit": {"source": "synthetic-test"},
    }
    return landed, settled, _multiset_reference(trio), contract


class NativeMenuAmbientLifecycleTests(unittest.TestCase):
    def test_sealed_v6_surface_fallback_does_not_override_live_probe_identity(
        self,
    ) -> None:
        historical = _stable_samples(3)
        for sample in historical:
            sample.pop("semantic_surface")
            sample.pop("semantic_generation")

        resolved = resolve_ambient_lifecycle(
            [
                _observation(_stable_samples(3), "menufx-primary", 101),
                _observation(_stable_samples(3), "menufx-confirmation", 202),
                {
                    **_observation(historical, "menufx-history", 303),
                    "corroboration_anchor": False,
                },
            ]
        )

        self.assertEqual(resolved["identity"]["semantic_surface"], "menu")
        self.assertEqual(resolved["identity"]["semantic_generations"], [11])

    def test_two_live_probed_semantic_surfaces_remain_a_stop(self) -> None:
        confirmation = _stable_samples(3)
        for sample in confirmation:
            sample["semantic_surface"] = "different_surface"

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "observations do not name one semantic surface and screen",
        ):
            _resolve_pair(_stable_samples(3), confirmation)

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

    def test_navigation_provenance_allows_recorder_evolution(self) -> None:
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
            "loader_dll_sha256": "7" * 64,
        }

        _assert_game_executable_matches(observed, reference, "independent capture")

        reference["game_executable_sha256"] = "8" * 64
        with self.assertRaisesRegex(
            CampaignResolutionError,
            "independent capture changed game executable provenance field "
            "'game_executable_sha256'",
        ):
            _assert_game_executable_matches(
                observed, reference, "independent capture"
            )

        with self.assertRaisesRegex(
            CampaignResolutionError,
            "independent capture changed runtime provenance field "
            "'game_executable_sha256'",
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

    def test_supplemental_settled_pair_uses_exact_hashed_recordings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = {
                "base_commit_sha": "1" * 40,
                "source_tree_sha": "2" * 40,
                "game_executable_sha256": "3" * 64,
                "loader_dll_sha256": "4" * 64,
            }

            def write(path: Path, value: dict[str, object]) -> None:
                path.write_text(
                    json.dumps(value, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )

            def receipt(path: Path) -> dict[str, object]:
                return {
                    "evidence_path": path.relative_to(root).as_posix(),
                    "evidence_filename": path.name,
                    "sha256": file_sha256(path),
                    "bytes": path.stat().st_size,
                }

            primary_trace = root / "screen.settlement.json"
            confirmation = root / "screen.confirmation.json"
            historical_fixture = root / "screen.json"
            write(
                primary_trace,
                {"settled_window_samples": _stable_samples(5)},
            )
            write(
                confirmation,
                {
                    "header": {
                        "instance": "menufx-history-b",
                        "process_id": 404,
                        "source": source,
                    },
                    "settled_window_samples": _stable_samples(5),
                },
            )
            write(
                historical_fixture,
                {
                    "schema": "solomon-dark-native-menu-layout-v2",
                    "header": {
                        "instance": "menufx-history-a",
                        "process_id": 303,
                        "source": source,
                        "settlement_trace": receipt(primary_trace),
                        "animation_confirmation": receipt(confirmation),
                    },
                },
            )
            manifest = root / "supplemental.json"
            write(
                manifest,
                {
                    "schema": (
                        "solomon-dark-native-menu-supplemental-settled-pairs-v1"
                    ),
                    "pairs": [
                        {
                            "pair_id": "screen-history",
                            "layout_id": "screen",
                            "primary_fixture": receipt(historical_fixture),
                            "primary_trace": receipt(primary_trace),
                            "confirmation": receipt(confirmation),
                        }
                    ],
                },
            )
            observations = {
                "screen": [
                    _observation(_stable_samples(5), "menufx-current-a", 101),
                    _observation(_stable_samples(5), "menufx-current-b", 202),
                ]
            }

            count = collect_supplemental_standalones(
                manifest,
                root,
                {
                    "screen": {
                        "native_screen_id": "screen",
                        "source": {
                            **source,
                            "loader_dll_sha256": "5" * 64,
                        },
                    }
                },
                observations,
            )

            self.assertEqual(count, 1)
            self.assertEqual(len(observations["screen"]), 4)
            self.assertEqual(
                [row["label"] for row in observations["screen"][-2:]],
                [
                    "supplemental:screen-history:primary",
                    "supplemental:screen-history:confirmation",
                ],
            )

    def test_extended_baseline_layout_names_are_exact_and_unambiguous(self) -> None:
        mapping = build_extended_baseline_filename_map(
            {
                "game-settings-gameplay": {
                    "path": Path("game-settings-gameplay.json"),
                    "confirmation_path": Path(
                        "game-settings-gameplay.confirmation.json"
                    ),
                }
            }
        )

        self.assertEqual(
            mapping["game-settings-gameplay-primary.baseline.json"],
            "game-settings-gameplay",
        )
        self.assertEqual(
            mapping["game-settings-gameplay-confirmation.baseline.json"],
            "game-settings-gameplay",
        )
        with self.assertRaisesRegex(
            CampaignResolutionError,
            "extended baseline filename map is ambiguous",
        ):
            build_extended_baseline_filename_map(
                {
                    "first": {
                        "path": Path("first.json"),
                        "confirmation_path": Path(
                            "shared-confirmation.baseline.json"
                        ),
                    },
                    "shared": {
                        "path": Path("shared.json"),
                        "confirmation_path": Path("shared.confirmation.json"),
                    },
                }
            )

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

        controls_source_id, controls_source_explicit = _resolve_layout_id(
            "settings",
            "settings",
            fixtures,
            "settings_to_controls",
            "before",
        )
        self.assertEqual(controls_source_id, "game-settings-title")
        self.assertTrue(controls_source_explicit)

        controls_return_id, controls_return_explicit = _resolve_layout_id(
            "settings",
            "settings",
            fixtures,
            "controls_to_settings",
            "after",
        )
        self.assertEqual(controls_return_id, "game-settings-title")
        self.assertTrue(controls_return_explicit)
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

    def test_hub_path_dependent_core_routes_are_exact_and_complete(self) -> None:
        fixtures = {
            layout_id: {"native_screen_id": "hub"}
            for layout_id in PATH_DEPENDENT_CORE_LAYOUTS
        }
        for (edge_id, endpoint), expected_layout_id in (
            PATH_DEPENDENT_CORE_ENDPOINTS.items()
        ):
            layout_id, explicit = _resolve_layout_id(
                "hub", "hub", fixtures, edge_id, endpoint
            )
            self.assertEqual(layout_id, expected_layout_id)
            self.assertTrue(explicit)

        with self.assertRaisesRegex(
            CampaignResolutionError,
            "screen 'hub' is ambiguous without explicit route mapping for edge "
            "'unknown_hub_edge' side 'after'",
        ):
            _resolve_layout_id(
                "hub", "hub", fixtures, "unknown_hub_edge", "after"
            )

    def test_hub_path_dependent_core_requires_distinct_reproduced_censuses(
        self,
    ) -> None:
        receipt = {
            "evidence_path": "raw-final/hub-path-dependent-core-stop-audit.json",
            "sha256": "1" * 64,
            "bytes": 101,
        }
        fixtures = {
            layout_id: {
                "native_screen_id": "hub",
                "header": {
                    "path_dependent_core": {
                        **policy,
                        "measured_settled_element_count": count,
                    }
                },
                "fork_decision_receipt": copy.deepcopy(receipt),
            }
            for (layout_id, policy), count in zip(
                PATH_DEPENDENT_CORE_LAYOUTS.items(), (14, 10), strict=True
            )
        }
        resolutions = {
            layout_id: {
                "peak_element_count": record["header"][
                    "path_dependent_core"
                ]["measured_settled_element_count"],
                "structural_core_element_count": (
                    record["header"]["path_dependent_core"][
                        "measured_settled_element_count"
                    ]
                    - (layout_id == "hub_resumed")
                ),
                "structural_core_sha256": str(index + 2) * 64,
            }
            for index, (layout_id, record) in enumerate(fixtures.items())
        }

        audit = validate_path_dependent_core_forks(
            fixtures, resolutions, dict(PATH_DEPENDENT_CORE_ENDPOINTS)
        )
        self.assertEqual(
            [row["layout_id"] for row in audit],
            list(PATH_DEPENDENT_CORE_LAYOUTS),
        )

        resolutions["hub_resumed"]["peak_element_count"] = 14
        fixtures["hub_resumed"]["header"]["path_dependent_core"][
            "measured_settled_element_count"
        ] = 14
        with self.assertRaisesRegex(
            CampaignResolutionError,
            "path-dependent core contract: Hub variants do not differ in element census",
        ):
            validate_path_dependent_core_forks(
                fixtures, resolutions, dict(PATH_DEPENDENT_CORE_ENDPOINTS)
            )

    def test_hub_path_dependent_core_rejects_an_unbound_endpoint(self) -> None:
        receipt = {
            "evidence_path": "raw-final/hub-path-dependent-core-stop-audit.json",
            "sha256": "1" * 64,
            "bytes": 101,
        }
        fixtures = {
            layout_id: {
                "native_screen_id": "hub",
                "header": {
                    "path_dependent_core": {
                        **policy,
                        "measured_settled_element_count": count,
                    }
                },
                "fork_decision_receipt": copy.deepcopy(receipt),
            }
            for (layout_id, policy), count in zip(
                PATH_DEPENDENT_CORE_LAYOUTS.items(), (14, 10), strict=True
            )
        }
        resolutions = {
            layout_id: {
                "peak_element_count": count,
                "structural_core_element_count": count,
                "structural_core_sha256": str(index + 2) * 64,
            }
            for index, (layout_id, count) in enumerate(
                (("hub_new_game", 14), ("hub_resumed", 10))
            )
        }
        endpoints = dict(PATH_DEPENDENT_CORE_ENDPOINTS)
        endpoints.pop(("settings_to_hub", "after"))

        with self.assertRaisesRegex(
            CampaignResolutionError,
            "path-dependent core contract: one or more Hub navigation endpoints "
            "remain ambiguous",
        ):
            validate_path_dependent_core_forks(fixtures, resolutions, endpoints)

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

    def test_settlement_skips_one_way_membership_decay(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            core = [_art(index) for index in range(5)]
            if sample_index < 5:
                decay = _art(10, art_id="Create.4")
                decay["id"] = "screen.art.transition_decay.1"
                return [*core, decay]
            return core

        settled = find_ambient_settled_window(
            _samples(elements, sample_count=45)
        )

        self.assertEqual(settled["stable_start_index"], 5)
        self.assertEqual(settled["stable_end_index"], 44)
        self.assertEqual(settled["ephemeral_art_ids"], [])

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

    def test_reproduced_multiband_ephemeral_family_pins_exact_band_set(self) -> None:
        resolved = _resolve_pair(_two_band_ephemeral_samples())
        family = next(
            entry
            for entry in resolved["ambient_members"]
            if entry["art_id"] == "Title.spark"
        )

        self.assertEqual(len(family["draw_bands"]), 2)

    def test_one_instance_ambient_band_is_not_contractual(self) -> None:
        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "ambient draw-band cross-instance contract: member family "
            "'art:Title.spark'.*lacks two independent instance witnesses",
        ):
            _resolve_pair(
                _two_band_ephemeral_samples(),
                _two_band_ephemeral_samples(include_upper_band=False),
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

    def test_cross_window_rect_variance_proves_motion_capability(self) -> None:
        def stationary_at(left: float, *, extended: bool = False) -> list[dict[str, object]]:
            def elements(_: int) -> list[dict[str, object]]:
                result = [_art(index) for index in range(5)]
                result[0]["rect"] = [left, 20.0, left + 8.0, 26.0]
                result[0]["unclipped_rect"] = list(result[0]["rect"])
                return result

            return _samples(
                elements,
                sample_count=200 if extended else 40,
                interval_milliseconds=310 if extended else 55,
            )

        primary = _observation(stationary_at(1.0), "menufx-primary", 101)
        confirmation = _observation(
            stationary_at(3.0), "menufx-confirmation", 202
        )
        primary_extension = {
            **_observation(
                stationary_at(1.0, extended=True), "menufx-primary", 101
            ),
            "kind": "extended_observation",
            "label": "primary-extension",
        }
        confirmation_extension = {
            **_observation(
                stationary_at(3.0, extended=True), "menufx-confirmation", 202
            ),
            "kind": "extended_observation",
            "label": "confirmation-extension",
        }

        resolved = resolve_ambient_lifecycle(
            [primary, confirmation, primary_extension, confirmation_extension]
        )

        self.assertEqual(len(resolved["animated_element_ids"]), 1)
        animated = next(
            member
            for member in resolved["ambient_members"]
            if "animated" in member["member_classes"]
        )
        self.assertEqual(animated["events"]["cross_window_rect_change"], 1)
        self.assertEqual(len(resolved["motion_capability_corroborations"]), 2)

    def test_cross_window_motion_requires_each_stationary_anchor_extension(self) -> None:
        primary = _stable_samples(5)
        confirmation = _stable_samples(5)
        confirmation[0]["payload"]["elements"][0]["rect"] = [
            1.0,
            20.0,
            9.0,
            26.0,
        ]
        for sample in confirmation:
            sample["payload"]["elements"][0]["rect"] = [
                1.0,
                20.0,
                9.0,
                26.0,
            ]
            sample["payload"]["elements"][0]["unclipped_rect"] = list(
                sample["payload"]["elements"][0]["rect"]
            )

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "motion capability resolution requires extended-observation evidence "
            "for stationary member 'screen.art.item_0.1' in instance "
            "'menufx-primary' PID 101",
        ):
            resolve_ambient_lifecycle(
                [
                    _observation(primary, "menufx-primary", 101),
                    _observation(confirmation, "menufx-confirmation", 202),
                ]
            )

    def test_cross_window_motion_rejects_nonrect_variance(self) -> None:
        primary = _stable_samples(5)
        confirmation = _stable_samples(5)
        for sample in confirmation:
            element = sample["payload"]["elements"][0]
            element["rect"] = [1.0, 20.0, 9.0, 26.0]
            element["unclipped_rect"] = list(element["rect"])
            element["visible"] = False

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "motion capability guardrail: cross-window member "
            "'screen.art.item_0.1' varied outside rect/unclipped_rect",
        ):
            _resolve_pair(primary, confirmation)

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

    def test_same_art_motion_slot_does_not_demote_stable_sibling(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            result = [_art(index) for index in range(4)]
            moving = result[0]
            stable_sibling = result[1]
            moving["art_id"] = "UI.shared"
            stable_sibling["art_id"] = "UI.shared"
            offset = sample_index * 0.25
            moving["rect"] = [offset, 20.0, 8.0 + offset, 26.0]
            moving["unclipped_rect"] = list(moving["rect"])
            stable_sibling["rect"] = [200.0, 40.0, 208.0, 46.0]
            stable_sibling["unclipped_rect"] = list(stable_sibling["rect"])
            return result

        resolved = _resolve_pair(_samples(elements))

        self.assertEqual(len(resolved["animated_element_ids"]), 1)
        self.assertEqual(
            sum(
                element["art_id"] == "UI.shared"
                for element in resolved["structural_core"]["elements"]
            ),
            1,
        )
        animated = next(
            member
            for member in resolved["ambient_members"]
            if "animated" in member["member_classes"]
        )
        self.assertEqual(animated["art_id"], "UI.shared")
        self.assertTrue(animated["member_key"].startswith("member:"))

    def test_same_art_disjoint_motion_phases_resolve_by_geometry_rank(self) -> None:
        resolved = _resolve_pair(
            _same_art_disjoint_phase_samples(0.0),
            _same_art_disjoint_phase_samples(50.0),
        )

        animated = [
            member
            for member in resolved["ambient_members"]
            if "animated" in member["member_classes"]
        ]
        self.assertEqual(len(animated), 3)
        self.assertEqual({member["art_id"] for member in animated}, {"UI.scroll"})

    def test_skill_picker_crossed_octet_resolves_one_animated_family(self) -> None:
        resolved = _resolve_pair(
            _skill_picker_animated_family_samples(),
            _skill_picker_animated_family_samples(50.0),
        )

        self.assertEqual(resolved["settlement_spec"], "2.9")
        self.assertEqual(resolved["peak_element_count"], 41)
        self.assertEqual(resolved["structural_core_element_count"], 31)
        self.assertEqual(len(resolved["animated_family_ids"]), 1)
        self.assertEqual(len(resolved["animated_element_ids"]), 3)
        family = next(
            member
            for member in resolved["ambient_members"]
            if member["id"] == resolved["animated_family_ids"][0]
        )
        self.assertEqual(family["art_id"], "UI.3")
        self.assertEqual(family["member_classes"], ["animated_family"])
        self.assertEqual(
            family["animated_family"]["exact_per_sample_member_count"], 8
        )
        self.assertEqual(
            family["animated_family"]["relative_draw_slots"],
            list(range(31, 39)),
        )
        self.assertEqual(
            len(
                family["animated_family"][
                    "fresh_instance_rank_crossing_witnesses"
                ]
            ),
            2,
        )
        per_member = [
            member
            for member in resolved["ambient_members"]
            if member["art_id"] == "UI.62"
        ]
        self.assertEqual(len(per_member), 2)
        self.assertTrue(
            all(member["member_classes"] == ["animated"] for member in per_member)
        )

    def test_animated_family_declaration_without_crossing_proof_fails(self) -> None:
        observations = [
            _observation(
                _same_art_disjoint_phase_samples(0.0), "menufx-primary", 101
            ),
            _observation(
                _same_art_disjoint_phase_samples(50.0),
                "menufx-confirmation",
                202,
            ),
        ]
        declared = resolve_ambient_lifecycle(observations)
        declared = copy.deepcopy(declared)
        declared["animated_family_ids"].append("screen.ambient.false-family.1")

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "animated family rank-crossing contract: declared family collapse "
            "lacks the machine-derived both-instance crossing proof",
        ):
            validate_ambient_resolution(declared, observations)

    def test_skill_picker_octet_still_stops_when_family_rule_is_disabled(
        self,
    ) -> None:
        with mock.patch(
            "tools.native_menu_ambient_lifecycle._resolve_animated_family_keys",
            return_value=({}, {}),
        ):
            with self.assertRaisesRegex(
                AmbientLifecycleError,
                "varying-member identity ambiguity: motion envelopes crossed "
                "measured geometry ranks",
            ):
                _resolve_pair(
                    _skill_picker_animated_family_samples(),
                    _skill_picker_animated_family_samples(50.0),
                )

    def test_animated_family_crossing_must_reproduce_in_both_instances(self) -> None:
        confirmation = _skill_picker_animated_family_samples(50.0)
        for sample_index, sample in enumerate(confirmation):
            movers = [
                element
                for element in sample["payload"]["elements"]  # type: ignore[index]
                if element["art_id"] == "UI.3"
            ]
            for index, mover in enumerate(movers):
                left = index * 1_000.0 + sample_index * 0.25
                mover["rect"] = [left, 100.0, left + 80.0, 120.0]
                mover["unclipped_rect"] = list(mover["rect"])

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "animated family rank-crossing contract: repeated mover crossing "
            "was not reproduced in fresh instance 'menufx-confirmation' PID 202",
        ):
            _resolve_pair(
                _skill_picker_animated_family_samples(), confirmation
            )

    def test_animated_family_rejects_non_geometric_member_variance(self) -> None:
        confirmation = _skill_picker_animated_family_samples(50.0)
        for sample in confirmation:
            mover = next(
                element
                for element in sample["payload"]["elements"]  # type: ignore[index]
                if element["id"] == "skill_picker.art.ui_3.8"
            )
            mover["font_id"] = "different"

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "animated family non-geometric contract: non-geometric payload "
            "changed between fresh instances",
        ):
            _resolve_pair(
                _skill_picker_animated_family_samples(), confirmation
            )

    def test_animated_family_rejects_visibility_or_member_count_change(self) -> None:
        confirmation = _skill_picker_animated_family_samples(50.0)
        for sample_index, sample in enumerate(confirmation):
            mover = next(
                element
                for element in sample["payload"]["elements"]  # type: ignore[index]
                if element["id"] == "skill_picker.art.ui_3.8"
            )
            mover["visible"] = sample_index % 2 == 0

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "animated family member-count contract: visibility or membership "
            "changed inside a fresh-instance family window",
        ):
            _resolve_pair(
                _skill_picker_animated_family_samples(), confirmation
            )

    def test_animated_family_rejects_nonconstant_collective_slots(self) -> None:
        confirmation = _skill_picker_animated_family_samples(50.0)
        confirmation[20]["payload"]["elements"][0]["draw_order"] = 150  # type: ignore[index]

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "animated family relative-slot contract: collective draw-slot set "
            "changed within 'menufx-confirmation'",
        ):
            _resolve_pair(
                _skill_picker_animated_family_samples(), confirmation
            )

    def test_skill_picker_choice_slots_resolve_from_manifest_geometry(self) -> None:
        resolved = _resolve_pair(
            _skill_picker_choice_samples(("Skills.48", "Skills.45")),
            _skill_picker_choice_samples(
                ("Skills.83", "Skills.92"), phase=50.0
            ),
            asset_manifest=_skill_picker_choice_manifest(),
        )

        self.assertEqual(resolved["settlement_spec"], "2.9")
        self.assertEqual(resolved["peak_element_count"], 41)
        self.assertEqual(resolved["structural_core_element_count"], 27)
        self.assertEqual(len(resolved["animated_family_ids"]), 1)
        self.assertEqual(
            resolved["choice_slot_ids"],
            ["skill_picker.choice_slot.1", "skill_picker.choice_slot.2"],
        )
        slots = resolved["choice_slots"]
        self.assertEqual(
            [slot["relative_draw_positions"] for slot in slots],
            [[30, 31], [40, 41]],
        )
        self.assertEqual(
            [slot["anchor"] for slot in slots],
            [{"x": 604, "y": 386.5}, {"x": 1004, "y": 386.5}],
        )
        self.assertEqual(
            [slot["exemplar_art_id"] for slot in slots],
            ["Skills.48", "Skills.45"],
        )
        self.assertTrue(
            all(
                slot["inter_draw_offset_vectors"][1]["x"] == -4
                and slot["inter_draw_offset_vectors"][1]["y"] == -4
                for slot in slots
            )
        )
        self.assertTrue(
            all(slot["trim_centering_verified_member_count"] == 4 for slot in slots)
        )
        self.assertEqual(
            resolved["classification_map"]["skill_picker.choice_slot.1"],
            ["choice_slot"],
        )

    def test_choice_slot_anchor_mismatch_stops_instead_of_collapsing(self) -> None:
        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "choice-slot anchor contract: per-position anchor differs across "
            "fresh instances",
        ):
            _resolve_pair(
                _skill_picker_choice_samples(("Skills.48", "Skills.45")),
                _skill_picker_choice_samples(
                    ("Skills.83", "Skills.92"),
                    phase=50.0,
                    first_anchor_delta=(1.0, 0.0),
                ),
                asset_manifest=_skill_picker_choice_manifest(),
            )

    def test_choice_slot_offset_mismatch_stops_instead_of_collapsing(self) -> None:
        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "choice-slot inter-draw offset contract: intra-position offset "
            "vectors differ across fresh instances",
        ):
            _resolve_pair(
                _skill_picker_choice_samples(("Skills.48", "Skills.45")),
                _skill_picker_choice_samples(
                    ("Skills.83", "Skills.92"),
                    phase=50.0,
                    second_draw_offset=(-3.0, -4.0),
                ),
                asset_manifest=_skill_picker_choice_manifest(),
            )

    def test_choice_slot_trim_centering_is_arithmetic_against_manifest(self) -> None:
        manifest = _skill_picker_choice_manifest()
        manifest["entries"]["Skills.83"]["logicalSize"]["width"] = 44  # type: ignore[index]

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "choice-slot manifest trim-centering contract: residual art "
            "'Skills.83' rect is not exactly its manifest logicalSize",
        ):
            _resolve_pair(
                _skill_picker_choice_samples(("Skills.48", "Skills.45")),
                _skill_picker_choice_samples(
                    ("Skills.83", "Skills.92"), phase=50.0
                ),
                asset_manifest=manifest,
            )

    def test_skill_picker_choice_residual_still_stops_when_rule_disabled(
        self,
    ) -> None:
        with mock.patch(
            "tools.native_menu_ambient_lifecycle._resolve_choice_slot_keys",
            return_value=({}, {}),
        ):
            with self.assertRaisesRegex(
                AmbientLifecycleError,
                "cross-instance structural core inequality: non-ambient "
                "full-presence member 'Skills.48' differs or is missing in "
                "observation 0",
            ):
                _resolve_pair(
                    _skill_picker_choice_samples(("Skills.48", "Skills.45")),
                    _skill_picker_choice_samples(
                        ("Skills.83", "Skills.92"), phase=50.0
                    ),
                    asset_manifest=_skill_picker_choice_manifest(),
                )

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

    def test_overlay_reference_uses_two_instance_local_standalone_cores(self) -> None:
        title = _art(1, art_id="Title.0")
        dialog = [
            _art(2, art_id="UI.dialog.frame"),
            _art(3, art_id="UI.dialog.button"),
        ]

        def beta_elements(sample_index: int) -> list[dict[str, object]]:
            elements = copy.deepcopy([title, *dialog])
            for element in elements:
                element["draw_order"] = int(element["draw_order"]) + sample_index
            return elements

        beta_primary = _samples(beta_elements)
        beta_confirmation = _samples(beta_elements)
        main_primary = _samples(lambda _: [copy.deepcopy(title)])
        main_confirmation = _samples(lambda _: [copy.deepcopy(title)])
        beta_core = reproduce_standalone_structural_core(
            beta_primary,
            beta_confirmation,
            label="beta_notice",
        )
        main_core = reproduce_standalone_structural_core(
            main_primary,
            main_confirmation,
            label="main_menu_root",
        )
        corroboration = _multiset_reference(dialog)

        reference = derive_overlay_reference(
            beta_core,
            main_core,
            corroboration,
            copy.deepcopy(corroboration),
        )

        self.assertEqual(beta_core["element_count"], 3)
        self.assertEqual(main_core["element_count"], 1)
        self.assertEqual(reference["overlay_semantic_draw_count"], 2)

    def test_local_standalone_core_rejects_nonambient_instance_residual(self) -> None:
        primary = _stable_samples(2)
        confirmation = _stable_samples(2)
        confirmation[0]["payload"]["elements"][1]["text"] = "changed"  # type: ignore[index]
        for sample in confirmation[1:]:
            sample["payload"]["elements"][1]["text"] = "changed"  # type: ignore[index]

        with self.assertRaisesRegex(
            AmbientLifecycleError,
            "standalone structural-core reproduction contract: non-ambient member",
        ):
            reproduce_standalone_structural_core(
                primary,
                confirmation,
                label="screen",
            )

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

    def test_landed_ambient_lookup_uses_unique_exact_anchor_not_ordinal(self) -> None:
        landed = _art(9, art_id="UI.shared")
        anchors = [copy.deepcopy(landed), copy.deepcopy(landed)]
        anchors[0]["rect"] = [1.0, 2.0, 9.0, 8.0]
        anchors[0]["unclipped_rect"] = list(anchors[0]["rect"])
        members = []
        for index, anchor in enumerate(anchors, start=1):
            anchor.pop("id")
            anchor.pop("draw_order")
            members.append(
                {
                    "id": f"screen.ambient.shared_slot_{index}.1",
                    "class_members": [
                        {
                            "classification": "animated",
                            "anchor_payload": anchor,
                            "union_spatial_envelope": {
                                "rect": {
                                    "min_x": 0.0,
                                    "max_x": 100.0,
                                    "min_y": 0.0,
                                    "max_y": 100.0,
                                    "min_width": 8.0,
                                    "max_width": 8.0,
                                    "min_height": 6.0,
                                    "max_height": 6.0,
                                },
                                "unclipped_rect": {
                                    "min_x": 0.0,
                                    "max_x": 100.0,
                                    "min_y": 0.0,
                                    "max_y": 100.0,
                                    "min_width": 8.0,
                                    "max_width": 8.0,
                                    "min_height": 6.0,
                                    "max_height": 6.0,
                                },
                            },
                        }
                    ],
                    "observed_concurrency_range": [1, 1],
                }
            )

        lifecycle, animation, unmatched = match_ambient_members(
            [landed], {"ambient_members": members}
        )

        self.assertEqual(lifecycle, [])
        self.assertEqual(unmatched, [])
        self.assertEqual(animation[0]["member_id"], members[1]["id"])

    def test_v29_beta_notice_exact_trio_moves_to_final_core_positions(self) -> None:
        landed, settled, overlay, contract = _v29_order_case()

        _, _, correction = _v29_beta_notice_order_projection(
            landed, settled, overlay, contract
        )

        self.assertIsNotNone(correction)
        self.assertEqual(
            [
                member["settled_relative_core_index"]
                for member in correction["moved_members"]  # type: ignore[index]
            ],
            [4, 5, 6],
        )

    def test_v29_beta_notice_non_exempt_reorder_still_stops(self) -> None:
        landed, settled, overlay, contract = _v29_order_case()
        settled["elements"][1], settled["elements"][2] = (  # type: ignore[index]
            settled["elements"][2],  # type: ignore[index]
            settled["elements"][1],  # type: ignore[index]
        )

        with self.assertRaisesRegex(
            LandedDiagnosisError,
            "v2.9 beta-notice paint-order correction: a non-exempt core member moved",
        ):
            _v29_beta_notice_order_projection(landed, settled, overlay, contract)

    def test_v29_beta_notice_dropped_trio_member_stops_set_identity(self) -> None:
        landed, settled, overlay, contract = _v29_order_case()
        settled["elements"].pop()  # type: ignore[union-attr]

        with self.assertRaisesRegex(
            LandedDiagnosisError,
            "v2.9 beta-notice paint-order correction: exact core set identity failed",
        ):
            _v29_beta_notice_order_projection(landed, settled, overlay, contract)

    def test_v29_beta_notice_mutated_trio_rect_stops_identity(self) -> None:
        landed, settled, overlay, contract = _v29_order_case()
        settled["elements"][-1]["rect"][0] += 1.0  # type: ignore[index]

        with self.assertRaisesRegex(
            LandedDiagnosisError,
            "v2.9 beta-notice paint-order correction: exact core set identity failed",
        ):
            _v29_beta_notice_order_projection(landed, settled, overlay, contract)

    def test_v29_beta_notice_trio_in_nonfinal_positions_stops(self) -> None:
        landed, settled, overlay, contract = _v29_order_case()
        elements = settled["elements"]  # type: ignore[assignment]
        settled["elements"] = [
            elements[0],
            elements[1],
            elements[4],
            elements[5],
            elements[6],
            elements[2],
            elements[3],
        ]

        with self.assertRaisesRegex(
            LandedDiagnosisError,
            "v2.9 beta-notice paint-order correction: bounded landed-to-settled positions differ",
        ):
            _v29_beta_notice_order_projection(landed, settled, overlay, contract)

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

    def test_landed_frozen_animated_rect_need_not_fit_new_envelope(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            moving = _art(8, art_id="UI.intermittent")
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
        landed = copy.deepcopy(samples[0]["payload"])
        frozen = landed["elements"][-1]
        frozen["rect"] = [900.0, 20.0, 908.0, 26.0]
        frozen["unclipped_rect"] = list(frozen["rect"])

        residual, ambient = diagnosis_prereference_residual(
            landed, settled_layout
        )

        self.assertEqual(residual, [])
        self.assertEqual(len(ambient), 1)
        self.assertEqual(ambient[0]["member_classes"], ["animated"])

    def test_landed_diagnosis_consumes_measured_animation_before_overlay(self) -> None:
        def elements(sample_index: int) -> list[dict[str, object]]:
            moving = _art(8, art_id="UI.intermittent")
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
        landed = copy.deepcopy(samples[0]["payload"])
        frozen = landed["elements"][-1]
        frozen["rect"] = [900.0, 20.0, 908.0, 26.0]
        frozen["unclipped_rect"] = list(frozen["rect"])
        trace = _trace(samples, copy.deepcopy(landed["elements"]))
        unused_overlay = _multiset_reference([_art(99, art_id="UI.overlay")])

        diagnosis = diagnose_landed_layout(
            landed,
            settled_layout,
            trace,
            copy.deepcopy(trace),
            unused_overlay,
        )

        self.assertEqual(diagnosis["status"], "corrected")
        self.assertEqual(len(diagnosis["animated_geometry_dispositions"]), 1)
        self.assertEqual(diagnosis["overlay_dispositions"], [])


if __name__ == "__main__":
    unittest.main()
