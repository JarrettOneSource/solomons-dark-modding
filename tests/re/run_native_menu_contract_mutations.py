#!/usr/bin/env python3
"""Mutation-audit every Settlement v2.1/v2.3/v2.4/v2.5/v2.6 menu claim."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "tools", ROOT / "tests/re"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import static_re_native_menu_shell_contracts as static_contracts  # noqa: E402
from static_re_contract_support import StaticReTestFailure  # noqa: E402
from tests import test_native_menu_ambient_lifecycle as ambient_cases  # noqa: E402
from tests import test_native_menu_settlement_v2 as settlement_cases  # noqa: E402
from tools import native_menu_settlement_v2 as settlement_v2  # noqa: E402
from tools import resolve_native_menu_ambient_campaign as campaign_resolver  # noqa: E402
from tools.native_menu_ambient_lifecycle import (  # noqa: E402
    AmbientLifecycleError,
    classify_ambient_window,
    resolve_ambient_lifecycle,
    validate_ambient_resolution,
)
from tools.native_menu_overlay_v25 import (  # noqa: E402
    OverlayV25Error,
    assert_overlay_hygiene as assert_overlay_hygiene_v25,
    derive_overlay_reference,
)


Action = Callable[[], str]


@dataclass(frozen=True)
class BehaviorMutation:
    claim: str
    contract: str
    baseline: Action
    mutant: Action
    expected_message: str
    expected_exception: tuple[type[BaseException], ...] = ()


@dataclass(frozen=True)
class StaticMutation:
    claim: str
    contract: str
    target: str
    old: str
    new: str
    expected_message: str


@dataclass(frozen=True)
class MutationResult:
    claim: str
    contract: str
    edit: str
    expected_message: str
    observed_message: str
    baseline_before: str
    baseline_after: str


Mutation = BehaviorMutation | StaticMutation


def clear_contract_bytecode() -> None:
    for directory in (
        ROOT / "tests/__pycache__",
        ROOT / "tests/re/__pycache__",
        ROOT / "tools/__pycache__",
    ):
        if directory.is_dir():
            shutil.rmtree(directory)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def green_v2_window() -> str:
    classified = settlement_v2.classify_window(settlement_cases._samples())
    settlement_v2.validate_declared_settlement(
        classified["layout"], settlement_cases._samples()
    )
    return "green: Settlement v2 rect-only window validates with measured animation"


def mutate_nonanimated_rect() -> str:
    samples = settlement_cases._samples()
    layout = copy.deepcopy(settlement_v2.classify_window(samples)["layout"])
    layout["animated_element_ids"] = []
    element = layout["elements"][0]
    element.pop("animated_geometry")
    element["rect"] = element.pop("anchor_rect")
    element["unclipped_rect"] = element.pop("anchor_unclipped_rect")
    element.pop("envelope")
    settlement_v2.validate_declared_settlement(layout, samples)
    return "unreachable"


def mutate_animated_text() -> str:
    samples = settlement_cases._samples()
    samples[-1]["payload"]["elements"][0]["text"] = "changed"
    declared = copy.deepcopy(
        settlement_v2.classify_window(settlement_cases._samples())["layout"]
    )
    settlement_v2.validate_declared_settlement(declared, samples)
    return "unreachable"


def green_animated_cap() -> str:
    settlement_v2.classify_window(settlement_cases._samples(animated_count=3))
    return "green: three of ten rect-only movers remain within the 30 percent cap"


def mutate_animated_cap() -> str:
    settlement_v2.classify_window(settlement_cases._samples(animated_count=4))
    return "unreachable"


def green_ambient_core() -> str:
    resolved = ambient_cases._resolve_pair(ambient_cases._stable_samples(3))
    require(
        len(resolved["structural_core"]["elements"]) == 3,
        "ambient baseline did not reproduce its three-member structural core",
    )
    return "green: two independent windows reproduce the three-member structural core"


def mutate_non_element_payload() -> str:
    samples = ambient_cases._stable_samples(3)
    samples[20]["payload"]["screen_title"] = "Changed"
    classify_ambient_window(samples)
    return "unreachable"


def mutate_control_churn() -> str:
    samples = ambient_cases._samples(
        lambda index: [
            ambient_cases._art(0),
            *([ambient_cases._control(1)] if index % 2 == 0 else []),
        ]
    )
    classify_ambient_window(samples)
    return "unreachable"


def mutate_control_visibility() -> str:
    def elements(index: int) -> list[dict[str, object]]:
        control = ambient_cases._control(1)
        control["visible"] = index % 2 == 0
        return [ambient_cases._art(0), control]

    classify_ambient_window(ambient_cases._samples(elements))
    return "unreachable"


def mutate_core_order() -> str:
    samples = ambient_cases._stable_samples(3)
    samples[20]["payload"]["elements"][0]["draw_order"] = 2.5
    ambient_cases._resolve_pair(samples)
    return "unreachable"


def green_reproduced_ambient_bands() -> str:
    resolved = ambient_cases._resolve_pair(
        ambient_cases._two_band_ephemeral_samples()
    )
    family = next(
        entry
        for entry in resolved["ambient_members"]
        if entry["art_id"] == "Title.spark"
    )
    require(len(family["draw_bands"]) == 2, "ambient band baseline lost one band")
    return "green: both instances reproduce the exact two-band ambient family"


def mutate_one_instance_ambient_band() -> str:
    ambient_cases._resolve_pair(
        ambient_cases._two_band_ephemeral_samples(),
        ambient_cases._two_band_ephemeral_samples(include_upper_band=False),
    )
    return "unreachable"


def mutate_cross_instance_core() -> str:
    primary = ambient_cases._stable_samples(3)
    confirmation = copy.deepcopy(primary)
    for sample in confirmation:
        sample["payload"]["elements"][0]["font_id"] = "different"
    ambient_cases._resolve_pair(primary, confirmation)
    return "unreachable"


def green_family_promotion() -> str:
    resolved = ambient_cases._resolve_pair(ambient_cases._family_samples())
    promoted = [
        element
        for element in resolved["structural_core"]["elements"]
        if element.get("art_id") == "Title.P"
        and element.get("text_style") == "structural"
    ]
    require(len(promoted) == 1, "family-art reproduction did not promote exactly one core member")
    return "green: byte-equal full-presence family art promotes into structural core"


def mutate_family_promotion() -> str:
    resolved = ambient_cases._resolve_pair(
        ambient_cases._family_samples(),
        ambient_cases._family_samples(perturb_stable=True),
    )
    promoted = [
        element
        for element in resolved["structural_core"]["elements"]
        if element.get("art_id") == "Title.P"
    ]
    require(not promoted, "one-instance family-art byte perturb remained in structural core")
    require(
        any(
            entry.get("art_id") == "Title.P"
            and "ambient_persistent" in entry.get("member_classes", [])
            for entry in resolved["ambient_members"]
        ),
        "one-instance family-art byte perturb did not demote to ambient-persistent",
    )
    return (
        "promotion-by-reproduction consequence: one-instance byte perturb demoted "
        "family art to ambient-persistent"
    )


def green_ambient_cap() -> str:
    resolved = ambient_cases._resolve_pair(ambient_cases._stable_samples(10))
    require(not resolved["ambient_members"], "stable ambient-cap baseline classified ambient members")
    return "green: stable ten-member core has zero ambient fraction"


def mutate_ambient_cap() -> str:
    def elements(index: int) -> list[dict[str, object]]:
        core = [ambient_cases._art(value) for value in range(5)]
        cycling = []
        for value in range(5, 10):
            element = ambient_cases._art(value, art_id=f"Title.{value}")
            element["visible"] = (index + value) % 2 == 0
            cycling.append(element)
        return [*core, *cycling]

    ambient_cases._resolve_pair(ambient_cases._samples(elements))
    return "unreachable"


def green_motion_pair() -> str:
    moving = ambient_cases._samples(
        lambda index: _moving_ambient_elements(index)
    )
    resolved = ambient_cases._resolve_pair(moving, copy.deepcopy(moving))
    require(len(resolved["animated_element_ids"]) == 1, "motion baseline did not resolve one mover")
    return "green: two moving windows resolve one screen-member motion capability"


def _moving_ambient_elements(index: int) -> list[dict[str, object]]:
    result = [ambient_cases._art(value) for value in range(5)]
    offset = index * 0.25
    result[0]["rect"] = [offset, 20.0, 8.0 + offset, 26.0]
    result[0]["unclipped_rect"] = list(result[0]["rect"])
    return result


def mutate_missing_extended_evidence() -> str:
    moving = ambient_cases._samples(_moving_ambient_elements)
    ambient_cases._resolve_pair(moving, ambient_cases._stable_samples(5))
    return "unreachable"


def mutate_phantom_ambient() -> str:
    observations = [
        ambient_cases._observation(ambient_cases._stable_samples(3), "menufx-primary", 101),
        ambient_cases._observation(
            ambient_cases._stable_samples(3), "menufx-confirmation", 202
        ),
    ]
    declared = copy.deepcopy(resolve_ambient_lifecycle(observations))
    declared["classification_map"]["UI.phantom"] = ["animated"]
    validate_ambient_resolution(declared, observations)
    return "unreachable"


def green_population_override() -> str:
    settlement_v2.build_population_phase_override(
        *settlement_cases._population_override_inputs()
    )
    return "green: two fresh traces prove the one-way population override"


def mutate_population_second_instance() -> str:
    inputs = list(settlement_cases._population_override_inputs())
    confirmation = copy.deepcopy(inputs[2])
    confirmation["elements"][1]["text"] = "different"
    inputs[2] = confirmation
    settlement_v2.build_population_phase_override(*inputs)
    return "unreachable"


def mutate_population_member_survives() -> str:
    inputs = list(settlement_cases._population_override_inputs())
    trace = copy.deepcopy(inputs[3])
    trace["settled_window_samples"][0]["payload"]["elements"].append(
        settlement_cases._element(99)
    )
    inputs[3] = trace
    settlement_v2.build_population_phase_override(*inputs)
    return "unreachable"


def mutate_population_trace_missing() -> str:
    inputs = list(settlement_cases._population_override_inputs())
    trace = copy.deepcopy(inputs[4])
    trace["structural_phases"][0]["payload"]["elements"] = [
        element
        for element in trace["structural_phases"][0]["payload"]["elements"]
        if element["id"] != "screen.art.item_99.1"
    ]
    inputs[4] = trace
    settlement_v2.build_population_phase_override(*inputs)
    return "unreachable"


def green_overlay_override() -> str:
    settlement_v2.build_overlay_contamination_override(
        *settlement_cases._overlay_override_inputs()
    )
    return "green: exact overlay subtraction and deterministic survivor ordinals reproduce settled structure"


def mutate_overlay_residual_draw() -> str:
    inputs = list(settlement_cases._overlay_override_inputs())
    landed = copy.deepcopy(inputs[0])
    outside = settlement_cases._element(102)
    outside["draw_order"] = 2
    landed["elements"].append(outside)
    inputs[0] = landed
    settlement_v2.build_overlay_contamination_override(*inputs)
    return "unreachable"


def mutate_overlay_noncanonical_ordinal() -> str:
    calls = 0
    real = settlement_v2.deterministic_reordinalized_layout

    def perturb(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        layout, animated_ids, proof = real(*args, **kwargs)
        if calls == 1:
            element = next(
                value
                for value in reversed(layout["elements"])
                if value["kind"] == "art" and value["id"] not in animated_ids
            )
            element["id"] = str(element["id"]) + "_noncanonical"
        return layout, animated_ids, proof

    with patch.object(
        settlement_v2,
        "deterministic_reordinalized_layout",
        side_effect=perturb,
    ):
        settlement_v2.build_overlay_contamination_override(
            *settlement_cases._overlay_override_inputs()
        )
    return "unreachable"


def mutate_overlay_residual_field() -> str:
    inputs = list(settlement_cases._overlay_override_inputs())
    primary = copy.deepcopy(inputs[1])
    primary["elements"][3]["text"] = "residual"
    inputs[1] = primary
    confirmation = copy.deepcopy(inputs[2])
    target_id = primary["elements"][3]["id"]
    for element in confirmation["elements"]:
        if element["id"] == target_id:
            element["text"] = "residual"
    inputs[2] = confirmation
    settlement_v2.build_overlay_contamination_override(*inputs)
    return "unreachable"


def green_overlay_hygiene() -> str:
    layout = copy.deepcopy(settlement_cases._samples()[0]["payload"])
    overlay = [settlement_cases._element(100), settlement_cases._element(101)]
    settlement_v2.assert_overlay_hygiene(layout, settlement_cases._overlay_reference(overlay))
    return "green: uncontaminated layout passes complete-sub-multiset hygiene"


def mutate_complete_overlay_hygiene() -> str:
    layout = copy.deepcopy(settlement_cases._samples()[0]["payload"])
    overlay = [settlement_cases._element(100), settlement_cases._element(101)]
    contaminated = copy.deepcopy(overlay)
    for index, element in enumerate(contaminated, start=7):
        element["id"] = f"screen.art.item_{element['art_id']}.{index}"
        element["draw_order"] = 500 + index
    layout["elements"].extend(contaminated)
    settlement_v2.assert_overlay_hygiene(
        layout, settlement_cases._overlay_reference(overlay)
    )
    return "unreachable"


def mutate_partial_overlay_hygiene() -> str:
    layout = copy.deepcopy(settlement_cases._samples()[0]["payload"])
    overlay = [settlement_cases._element(100), settlement_cases._element(101)]
    layout["elements"].append(copy.deepcopy(overlay[0]))
    settlement_v2.assert_overlay_hygiene(
        layout, settlement_cases._overlay_reference(overlay)
    )
    return (
        "overlay hygiene regression consequence: pause-style partial shared atlas "
        "suffix subset remains accepted"
    )


def green_overlay_derivation() -> str:
    reference = derive_overlay_reference(*ambient_cases._overlay_derivation_inputs())
    require(reference["overlay_semantic_draw_count"] == 2, "overlay derivation baseline lost draw census")
    return "green: beta core minus title core equals both proven correction multisets"


def mutate_title_core_missing() -> str:
    beta, main, create, pause = ambient_cases._overlay_derivation_inputs()
    beta["structural_core"]["elements"] = [
        element
        for element in beta["structural_core"]["elements"]
        if element["art_id"] != "Title.1"
    ]
    derive_overlay_reference(beta, main, create, pause)
    return "unreachable"


def mutate_overlay_corroboration() -> str:
    beta, main, create, pause = ambient_cases._overlay_derivation_inputs()
    payloads = [
        copy.deepcopy(entry["payload"])
        for entry in pause["overlay_semantic_draw_multiset"]
    ]
    payloads[0]["font_id"] = "perturbed"
    derive_overlay_reference(
        beta, main, create, ambient_cases._multiset_reference(payloads)
    )
    return "unreachable"


def green_old_motion_resolution() -> str:
    primary = settlement_cases._motion_observation(
        settlement_cases._samples(), "menufx-primary", 101
    )
    confirmation = settlement_cases._motion_observation(
        settlement_cases._reordered_samples(), "menufx-confirmation", 202
    )
    settlement_v2.resolve_motion_capability([primary, confirmation], [])
    return "green: Settlement v2.3 resolves reproduced motion without phantom declarations"


def mutate_old_phantom_motion() -> str:
    primary = settlement_cases._motion_observation(
        settlement_cases._samples(), "menufx-primary", 101
    )
    confirmation = settlement_cases._motion_observation(
        settlement_cases._reordered_samples(), "menufx-confirmation", 202
    )
    resolved = settlement_v2.resolve_motion_capability([primary, confirmation], [])
    declaration = copy.deepcopy(resolved["resolution"])
    declaration["resolved_animated_element_ids"].append("screen.art.item_1.1")
    settlement_v2.validate_resolved_motion_capability(
        declaration, [primary, confirmation], []
    )
    return "unreachable"


def green_historical_baseline_receipt() -> str:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        baseline = root / "hub-primary.baseline.json"
        baseline.write_text(
            '{"schema":"solomon-dark-native-menu-layout-v2"}\n',
            encoding="utf-8",
        )
        receipt = {
            "sha256": campaign_resolver.file_sha256(baseline),
            "bytes": baseline.stat().st_size,
            "selector": {"schema": "solomon-dark-native-menu-layout-v2"},
        }
        resolved, _ = campaign_resolver.resolve_baseline_evidence(
            root, receipt, "scratch historical motion"
        )
        require(resolved == baseline.resolve(), "historical baseline did not resolve")
    return "green: historical motion resolves one byte-identical baseline recording"


def mutate_historical_baseline_receipt() -> str:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        baseline = root / "hub-primary.baseline.json"
        baseline.write_text(
            '{"schema":"solomon-dark-native-menu-layout-v2"}\n',
            encoding="utf-8",
        )
        receipt = {
            "sha256": "0" * 64,
            "bytes": baseline.stat().st_size,
            "selector": {"schema": "solomon-dark-native-menu-layout-v2"},
        }
        campaign_resolver.resolve_baseline_evidence(
            root, receipt, "scratch historical motion"
        )
    return "unreachable"


def _ambiguous_settings_fixtures() -> dict[str, dict[str, str]]:
    return {
        "game-settings-title": {"native_screen_id": "settings"},
        "game-settings-gameplay": {"native_screen_id": "settings"},
        "game-settings-dark-cloud": {"native_screen_id": "settings"},
    }


def green_settings_route_resolution() -> str:
    layout_id, explicit = campaign_resolver._resolve_layout_id(  # noqa: SLF001
        "settings",
        "settings",
        _ambiguous_settings_fixtures(),
        "main_to_settings",
        "after",
    )
    require(
        layout_id == "game-settings-title" and explicit,
        "known settings route did not resolve explicitly",
    )
    return "green: three-way settings identity resolves only by exact edge and side"


def mutate_ambiguous_settings_route() -> str:
    campaign_resolver._resolve_layout_id(  # noqa: SLF001
        "settings",
        "settings",
        _ambiguous_settings_fixtures(),
        "unknown_settings_edge",
        "before",
    )
    return "unreachable"


RECORDER = "test_native_menu_recorders_settle_and_derive_provenance"
OVERLAY = "test_native_menu_overlay_contamination_override_is_fail_closed"
CLASSIFIER = "test_native_menu_settlement_v2_classifier_is_strict_and_ci_wired"
CAMPAIGN = "test_native_menu_motion_capability_campaign_resolution_is_fail_closed"
PATH_FORK = "test_native_menu_path_dependent_core_fork_is_exact"
SURFACE_AGREEMENT = "test_native_menu_capture_surface_agreement_is_fail_closed"


BEHAVIOR_MUTATIONS: tuple[BehaviorMutation, ...] = (
    BehaviorMutation(
        "v2.nonanimated-rect-structural",
        "validate_declared_settlement",
        green_v2_window,
        mutate_nonanimated_rect,
        "structural settlement contract: non-animated element 'screen.art.item_0.1' varied rect/unclipped_rect",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.text-is-not-animation",
        "validate_declared_settlement",
        green_v2_window,
        mutate_animated_text,
        "animated classification guardrail: element 'screen.art.item_0.1' field 'text' varied; non-geometry changes are instability, not animation",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.animated-fraction-cap",
        "classify_window",
        green_animated_cap,
        mutate_animated_cap,
        "animated geometry cap exceeded: 4/10 elements (40.0%) exceeds 30% for 'screen'",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.5.non-element-structural-payload",
        "classify_ambient_window",
        green_ambient_core,
        mutate_non_element_payload,
        "ambient lifecycle structural-core guardrail: non-element payload field 'screen_title' varied at sample 20",
        (AmbientLifecycleError,),
    ),
    BehaviorMutation(
        "v2.5.control-membership-churn",
        "classify_ambient_window",
        green_ambient_core,
        mutate_control_churn,
        "ambient lifecycle art-only guard: membership churn on text/control member 'screen.control.action_1.1' is not classifiable",
        (AmbientLifecycleError,),
    ),
    BehaviorMutation(
        "v2.5.control-visible-variance",
        "classify_ambient_window",
        green_ambient_core,
        mutate_control_visibility,
        "ambient lifecycle art-only guard: visible variance on text/control member 'screen.control.action_1.1' is not classifiable",
        (AmbientLifecycleError,),
    ),
    BehaviorMutation(
        "v2.5.core-relative-order",
        "resolve_ambient_lifecycle",
        green_ambient_core,
        mutate_core_order,
        "relative draw sequence contract: structural core relative-order flip in 'menufx-primary' sample 20",
        (AmbientLifecycleError,),
    ),
    BehaviorMutation(
        "v2.5.ambient-band-cross-instance",
        "resolve_ambient_lifecycle",
        green_reproduced_ambient_bands,
        mutate_one_instance_ambient_band,
        "ambient draw-band cross-instance contract: member family "
        "'art:Title.spark' band 'screen.art.ui_1.1->screen.art.ui_2.1' "
        "lacks two independent instance witnesses: ['menufx-primary']",
        (AmbientLifecycleError,),
    ),
    BehaviorMutation(
        "v2.5.cross-instance-core-byte",
        "resolve_ambient_lifecycle",
        green_ambient_core,
        mutate_cross_instance_core,
        "cross-instance structural core inequality: non-ambient full-presence member 'UI.0' differs or is missing in observation 0",
        (AmbientLifecycleError,),
    ),
    BehaviorMutation(
        "v2.5.promotion-by-reproduction",
        "resolve_ambient_lifecycle",
        green_family_promotion,
        mutate_family_promotion,
        "promotion-by-reproduction consequence: one-instance byte perturb demoted family art to ambient-persistent",
    ),
    BehaviorMutation(
        "v2.5.ambient-fraction-cap",
        "resolve_ambient_lifecycle",
        green_ambient_cap,
        mutate_ambient_cap,
        "ambient lifecycle cap exceeded: 5/10 semantic members (50.0%) exceeds 40% for 'screen'",
        (AmbientLifecycleError,),
    ),
    BehaviorMutation(
        "v2.3.extended-corroboration-duty",
        "resolve_ambient_lifecycle",
        green_motion_pair,
        mutate_missing_extended_evidence,
        "motion capability resolution requires extended-observation evidence for stationary member 'screen.art.item_0.1' in instance 'menufx-confirmation' PID 202",
        (AmbientLifecycleError,),
    ),
    BehaviorMutation(
        "v2.3.historical-baseline-byte-binding",
        "resolve_baseline_evidence",
        green_historical_baseline_receipt,
        mutate_historical_baseline_receipt,
        "extended observation baseline receipt does not resolve exactly one "
        "byte-identical evidence file for scratch historical motion: []",
        (campaign_resolver.CampaignResolutionError,),
    ),
    BehaviorMutation(
        "v2.5.settings-route-ambiguity-refusal",
        "_resolve_layout_id",
        green_settings_route_resolution,
        mutate_ambiguous_settings_route,
        "navigation endpoint 'settings' screen 'settings' is ambiguous without "
        "explicit route mapping for edge 'unknown_settings_edge' side 'before': "
        "['game-settings-dark-cloud', 'game-settings-gameplay', "
        "'game-settings-title']",
        (campaign_resolver.CampaignResolutionError,),
    ),
    BehaviorMutation(
        "v2.5.phantom-ambient",
        "validate_ambient_resolution",
        green_ambient_core,
        mutate_phantom_ambient,
        "ambient lifecycle recorder defect: phantom ambient classification 'animated' for art family 'UI.phantom' has zero observed events",
        (AmbientLifecycleError,),
    ),
    BehaviorMutation(
        "v2.1.second-instance-agreement",
        "build_population_phase_override",
        green_population_override,
        mutate_population_second_instance,
        "landed population override requires second-instance canonical structural agreement",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.1.difference-absent-from-settlement",
        "build_population_phase_override",
        green_population_override,
        mutate_population_member_survives,
        "landed population override rejected: differing member 'screen.art.item_99.1' is present in a settled window",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.1.two-population-traces",
        "build_population_phase_override",
        green_population_override,
        mutate_population_trace_missing,
        "landed population override lacks two-instance population proof for differing member 'screen.art.item_99.1'",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.4.zero-residual-draws",
        "build_overlay_contamination_override",
        green_overlay_override,
        mutate_overlay_residual_draw,
        "landed overlay override: semantic-multiset difference leaves residual draws or fields after deterministic reordinalization at 'elements.membership'",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.4.canonical-reordinalization",
        "build_overlay_contamination_override",
        green_overlay_override,
        mutate_overlay_noncanonical_ordinal,
        "landed overlay override: deterministic reordinalization produced a noncanonical survivor ordinal for 'screen.art.item_9.1'",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.4.no-residual-survivor-field",
        "build_overlay_contamination_override",
        green_overlay_override,
        mutate_overlay_residual_field,
        "landed overlay override: semantic-multiset difference leaves residual draws or fields after deterministic reordinalization at 'elements[3].text'",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.4.complete-overlay-hygiene-refusal",
        "assert_overlay_hygiene",
        green_overlay_hygiene,
        mutate_complete_overlay_hygiene,
        "overlay hygiene contract: non-overlay screen 'screen' contains the complete beta-dialog semantic multiset",
        (settlement_v2.SettlementV2Error,),
    ),
    BehaviorMutation(
        "v2.4.partial-suffix-hygiene-acceptance",
        "assert_overlay_hygiene",
        green_overlay_hygiene,
        mutate_partial_overlay_hygiene,
        "overlay hygiene regression consequence: pause-style partial shared atlas suffix subset remains accepted",
    ),
    BehaviorMutation(
        "v2.5.title-core-embedding",
        "derive_overlay_reference",
        green_overlay_derivation,
        mutate_title_core_missing,
        "overlay reference derivation: title-core member is missing from beta_notice structural core",
        (OverlayV25Error,),
    ),
    BehaviorMutation(
        "v2.5.overlay-corroboration",
        "derive_overlay_reference",
        green_overlay_derivation,
        mutate_overlay_corroboration,
        "overlay reference corroboration: derived beta-dialog multiset does not equal the proven Create and pause correction multisets",
        (OverlayV25Error,),
    ),
    BehaviorMutation(
        "v2.3.phantom-motion-capability",
        "validate_resolved_motion_capability",
        green_old_motion_resolution,
        mutate_old_phantom_motion,
        "motion capability recorder defect: phantom animated classification for 'screen.art.item_1.1' has no varying recorded samples",
        (settlement_v2.SettlementV2Error,),
    ),
)


STATIC_MUTATIONS: tuple[StaticMutation, ...] = (
    StaticMutation(
        "v2.3.historical-baseline-hash-check",
        CAMPAIGN,
        "tools/resolve_native_menu_ambient_campaign.py",
        "if file_sha256(path) == recorded_sha256:",
        "if True:  # mutation accepts a same-size baseline with different bytes",
        "historical motion observations are no longer byte-bound to one copied "
        "baseline with matching capture and runtime provenance",
    ),
    StaticMutation(
        "v2.3.historical-baseline-provenance-check",
        CAMPAIGN,
        "tools/resolve_native_menu_ambient_campaign.py",
        "if canonical_bytes(baseline_source) != canonical_bytes(motion_source):",
        "if False and canonical_bytes(baseline_source) != canonical_bytes(motion_source):",
        "historical motion observations are no longer byte-bound to one copied "
        "baseline with matching capture and runtime provenance",
    ),
    StaticMutation(
        "v2.3.historical-baseline-logical-identity",
        CAMPAIGN,
        "tools/resolve_native_menu_ambient_campaign.py",
        'f"{layout_id}-primary.baseline.json"',
        'f"{layout_id}-unbound-primary.json"',
        "historical motion observations are no longer byte-bound to one copied "
        "baseline with matching capture and runtime provenance",
    ),
    StaticMutation(
        "v2.5.settings-route-exact-mapping",
        CAMPAIGN,
        "tools/resolve_native_menu_ambient_campaign.py",
        '("settings_to_controls", "before"): "game-settings-title",',
        '("settings_to_controls", "before"): "game-settings-gameplay",',
        "ambient-lifecycle resolver no longer refuses the three-way settings "
        "screen ambiguity with an every-edge explicit route map",
    ),
    StaticMutation(
        "v2.5.settings-route-complete-census",
        CAMPAIGN,
        "tools/resolve_native_menu_ambient_campaign.py",
        "if explicit_layout_ids != applicable_explicit_layout_ids:",
        "if False and explicit_layout_ids != applicable_explicit_layout_ids:",
        "ambient-lifecycle resolver no longer refuses the three-way settings "
        "screen ambiguity with an every-edge explicit route map",
    ),
    StaticMutation(
        "v2.6.hub-route-exact-mapping",
        PATH_FORK,
        "tools/resolve_native_menu_ambient_campaign.py",
        '("create_discipline_to_hub", "after"): "hub_new_game",',
        '("create_discipline_to_hub", "after"): "hub_resumed",',
        "Settlement v2.6 no longer names exactly two Hub layouts and binds "
        "every Hub navigation endpoint to its deterministic path/session state",
    ),
    StaticMutation(
        "v2.6.hub-distinct-census",
        PATH_FORK,
        "tools/resolve_native_menu_ambient_campaign.py",
        "if len(set(counts.values())) != len(counts):",
        "if False and len(set(counts.values())) != len(counts):",
        "Settlement v2.6 no longer rejects an equal-census, unbound, "
        "extra-layout, or differently evidenced Hub fork",
    ),
    StaticMutation(
        "v2.6.materializer-no-provenance-override",
        PATH_FORK,
        "tools/materialize_native_menu_path_forks_v26.py",
        'parser.add_argument("--candidate-root", required=True, type=Path)',
        'parser.add_argument("--base-commit-sha")\n'
        '    parser.add_argument("--candidate-root", required=True, type=Path)',
        "path-dependent core materializer accepts operator-supplied "
        "provenance or golden values: ['--base-commit-sha']",
    ),
    StaticMutation(
        "v2.6.spec-version-and-stop-changelog",
        PATH_FORK,
        "docs/reverse-engineering/native-menu-settlement.md",
        "# Native menu settlement specification v2.9",
        "# Native menu settlement specification v2.8",
        "the versioned settlement specification no longer records the narrow "
        "path-dependent-core rule and the STOP that caused it",
    ),
    StaticMutation(
        "v2.5.independent-capture-runtime-provenance",
        CAMPAIGN,
        "tools/resolve_native_menu_ambient_campaign.py",
        'NAVIGATION_GAME_PROVENANCE_FIELD = "game_executable_sha256"',
        'NAVIGATION_GAME_PROVENANCE_FIELD = "loader_dll_sha256"',
        "navigation-to-standalone comparison no longer rejects a changed game "
        "binary while allowing independently recorded loader evolution",
    ),
    StaticMutation(
        "v2.5.path-local-layout-generation",
        CAMPAIGN,
        "tools/native_menu_ambient_lifecycle.py",
        '{measurement["identity"]["layout_generation"] for measurement in measurements}',
        '{measurement["identity"]["semantic_generation"] for measurement in measurements}',
        "Settlement v2.5 no longer keeps path-local generation counters and "
        "sealed-v6 placeholder surfaces out of live-probed screen identity",
    ),
    StaticMutation(
        "v2.5.sealed-v6-surface-fallback",
        CAMPAIGN,
        "tools/native_menu_ambient_lifecycle.py",
        'semantic_generation_measurements = [\n'
        '        measurement\n'
        '        for measurement in measurements\n'
        '        if measurement["identity"]["identity_source"] == "semantic_probe"\n'
        '    ] or measurements',
        'semantic_generation_measurements = [\n'
        '        measurement\n'
        '        for measurement in measurements\n'
        '        if True  # mutation promotes sealed-v6 placeholder surface to live truth\n'
        '    ] or measurements',
        "Settlement v2.5 no longer keeps path-local generation counters and "
        "sealed-v6 placeholder surfaces out of live-probed screen identity",
    ),
    StaticMutation(
        "v2.3.navigation-replay-corroboration-scope",
        CAMPAIGN,
        "tools/resolve_native_menu_ambient_campaign.py",
        'f"edge:{edge_id}:{side}:{label}",\n                        corroboration_anchor=False,',
        'f"edge:{edge_id}:{side}:{label}",',
        "navigation replay windows again multiply the v2.3 extended-observation "
        "duty after screen classification was anchored to two fresh standalones",
    ),
    StaticMutation(
        "v2.3.same-art-motion-member-identity",
        CAMPAIGN,
        "tools/native_menu_ambient_lifecycle.py",
        "if max(left_min, right_min) > min(left_max, right_max):",
        "if False and max(left_min, right_min) > min(left_max, right_max):",
        "same-art rect animation again collapses distinct screen members and "
        "demotes a reproduced stable sibling from the structural core",
    ),
    StaticMutation(
        "v2.5.ambient-art-family-not-motion-slot",
        CAMPAIGN,
        "tools/native_menu_ambient_lifecycle.py",
        'and record[1]["art_id"] not in ambient_family',
        "and True  # mutation forces ambient title art through member slots",
        "title-backdrop ambient art is again forced through screen-member "
        "motion slots instead of retaining authorized art-family identity",
    ),
    StaticMutation(
        "v2.3.disjoint-phase-geometry-rank",
        CAMPAIGN,
        "tools/native_menu_ambient_lifecycle.py",
        "geometry_ranks = _varying_member_geometry_ranks(records)",
        "geometry_ranks = {}  # mutation fragments disjoint motion phases",
        "same-art movers observed at disjoint phases again fragment into "
        "instance-local slots instead of measured geometry-ranked members",
    ),
    StaticMutation(
        "v2.3.cross-window-quiet-motion-capability",
        CAMPAIGN,
        "tools/native_menu_ambient_lifecycle.py",
        "if len(geometry_samples) < 2:\n                    continue",
        "if True:  # mutation discards measured cross-window rect variance\n"
        "                    continue",
        "Settlement v2.3 no longer treats rect-only differences across valid "
        "quiet windows as measured screen-member motion while retaining the "
        "non-rect and phantom-classification guardrails",
    ),
    StaticMutation(
        "v2.5.one-way-decay-is-not-settled",
        CAMPAIGN,
        "tools/native_menu_ambient_lifecycle.py",
        "if window_ephemeral_art_ids and (",
        "if False and (  # mutation accepts one-way membership decay",
        "Settlement v2.5 again accepts one-way membership decay as settled "
        "ephemeral churn before bidirectional family evidence",
    ),
    StaticMutation(
        "v2.5.empty-gameplay-surface-is-constant",
        CLASSIFIER,
        "tools/native_menu_ambient_lifecycle.py",
        "if not isinstance(semantic_surface, str):",
        "if not isinstance(semantic_surface, str) or not semantic_surface:",
        "Settlement v2.5 no longer treats gameplay's empty semantic-surface "
        "identifier as a constant while rejecting non-string missing state",
    ),
    StaticMutation(
        "recorder.no-fixed-delay",
        RECORDER,
        "scripts/Record-NativeMenuLayout.ps1",
        "Set-StrictMode -Version 3.0",
        "Set-StrictMode -Version 3.0\nStart-Sleep -Milliseconds 4000",
        "Record-NativeMenuLayout.ps1 regained a fixed-delay capture path",
    ),
    StaticMutation(
        "recorder.dark-cloud-native-row-census",
        RECORDER,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "label_resolution_and_frame_render.inl",
        "                reinterpret_cast<const void*>(browser_address),\n"
        "                g_debug_ui_overlay_state.config."
        "dark_cloud_browser_entry_count_offset,",
        "                reinterpret_cast<const void*>(list_widget),\n"
        "                g_debug_ui_overlay_state.config."
        "dark_cloud_browser_entry_count_offset,",
        "Dark Cloud row census again trusts pointer-probed widget capacity "
        "instead of the browser's native +0x1E0 entry count",
    ),
    StaticMutation(
        "recorder.40-sample-floor",
        RECORDER,
        "scripts/NativeMenuCaptureSupport.ps1",
        "$script:NativeMenuSettleConsecutiveSamples = 40",
        "$script:NativeMenuSettleConsecutiveSamples = 39",
        "native-menu Settlement v2 no longer requires 40 samples over at least two seconds",
    ),
    StaticMutation(
        "recorder.extended-observed-span",
        RECORDER,
        "scripts/Observe-NativeMenuMotionCapability.ps1",
        "$observedSpanMilliseconds -lt $requiredSpanMilliseconds",
        "$clock.ElapsedMilliseconds -lt $requiredSpanMilliseconds",
        "the v2.3 corroboration recorder no longer derives 60-second/10x "
        "duration from the stationary window, measures that span between "
        "actual samples, and requires at least 200 samples",
    ),
    StaticMutation(
        "recorder.extended-sample-census-budget",
        RECORDER,
        "scripts/Observe-NativeMenuMotionCapability.ps1",
        "$sampleCensusDeadlineMilliseconds = (",
        "$sampleCensusDeadlineMilliseconds = 0L # mutation removes sample budget\n(",
        "extended observation timeout again budgets only elapsed span and can "
        "STOP before the independent 200-sample census",
    ),
    StaticMutation(
        "special.loader-full-progress-settle-hold",
        RECORDER,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "menu_layout_capture_snapshot_and_hooks.inl",
        "g_native_boot_capture_samples.back().progress >= 1.0",
        "g_native_boot_capture_samples.back().progress < 1.0",
        "native-loader capture no longer holds and settle-samples the real "
        "full-progress render or bounds failure as STOP",
    ),
    StaticMutation(
        "special.loading-client-viewport-only",
        RECORDER,
        "SolomonDarkModLoader/src/loading_screen_native_present.cpp",
        "if (!IsProcessClientPresentationViewport(*layout))",
        "if (false && !IsProcessClientPresentationViewport(*layout))",
        "loading-screen capture no longer rejects offscreen render targets "
        "before they can reset settlement",
    ),
    StaticMutation(
        "special.loading-final-barrier-settle-hold",
        RECORDER,
        "SolomonDarkModLoader/src/loading_screen_native_present.cpp",
        "snapshot.stage ==\n            LoadingScreenStage::WaitingForParticipants",
        "snapshot.stage !=\n            LoadingScreenStage::WaitingForParticipants",
        "loading-screen capture no longer holds and settle-samples the real "
        "final barrier or bounds failure as STOP",
    ),
    StaticMutation(
        "special.loading-pins-client-layout",
        RECORDER,
        "SolomonDarkModLoader/src/loading_screen_native_present.cpp",
        "snapshot,\n                *layout",
        "snapshot,\n                current_layout",
        "loading-screen settlement hold no longer pins the accepted client "
        "layout against concurrent offscreen last-layout replacement",
    ),
    StaticMutation(
        "recorder.blocking-modal-exact-surface",
        RECORDER,
        "scripts/NativeMenuCaptureSupport.ps1",
        "$dispatch.classified_surface -ceq",
        "$dispatch.classified_surface -cne",
        "native-menu semantic actions no longer distinguish queued or busy requests, exact-surface blocking modals, completed dispatch, and terminal dispatch failure",
    ),
    StaticMutation(
        "recorder.blocking-modal-generation-advance",
        RECORDER,
        "scripts/NativeMenuCaptureSupport.ps1",
        "$dispatch.layout_generation -ne",
        "$dispatch.layout_generation -eq",
        "native-menu semantic actions no longer distinguish queued or busy requests, exact-surface blocking modals, completed dispatch, and terminal dispatch failure",
    ),
    StaticMutation(
        "recorder.surface-mismatch-native-refusal",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/public_api_surface_dispatch.inl",
        "if (captured.screen_id != screen_id) {",
        "if (captured.screen_id == screen_id) {",
        "a classifier/tag mismatch can reach the accepted native layout cache",
    ),
    StaticMutation(
        "recorder.settings-current-frame-panel-art",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        "!HasCurrentSettingsPanelArt(current_elements)",
        "false && !HasCurrentSettingsPanelArt(current_elements)",
        "Settings cached art is no longer extracted from one complete live "
        "panel suffix or can include title-backdrop draws",
    ),
    StaticMutation(
        "recorder.settings-idle-owner-retention",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "tracked_surfaces_and_main_menu.inl",
        "if (now - g_debug_ui_overlay_state.settings_render.captured_at > "
        "kTrackedSettingsMaximumIdleMs) {\n        return false;\n    }",
        "if (now - g_debug_ui_overlay_state.settings_render.captured_at > "
        "kTrackedSettingsMaximumIdleMs) {\n"
        "        g_debug_ui_overlay_state.settings_render.tracked_object_ptr = 0;\n"
        "        return false;\n    }",
        "the idle settings probe can again erase the retained modal owner "
        "before current-frame evidence validates it",
    ),
    StaticMutation(
        "recorder.controls-underlay-multiset-difference",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        'if (element.art_id.rfind("Title.", 0) == 0) {',
        'if (element.art_id.rfind("Title.", 0) != 0) {',
        "Controls cached art is no longer the non-ID/non-draw-order semantic "
        "multiset difference against its measured Settings underlay, or can "
        "include title/partial Settings draws",
    ),
    StaticMutation(
        "recorder.controls-refuses-settings-panel-cache",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        "if (page_observation.page == "
        "SettingsRolloutPageState::Settings &&\n"
        "        TryExtractSettingsFamilyOverlayArt(",
        "if (page_observation.page != "
        "SettingsRolloutPageState::Settings &&\n"
        "        TryExtractSettingsFamilyOverlayArt(",
        "an outgoing Settings ControlPanel draw can populate the Controls "
        "destination cache instead of the measured Controls page difference",
    ),
    StaticMutation(
        "recorder.controls-quarantines-unresolved-settings-panel",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        "cache_state.settings.settings_address = settings_address;\n"
        "            cache_state.settings.elements =\n"
        "                std::move(transition_overlay);\n"
        "            cache_state.settings_underlay = current_elements;\n"
        "            cache_state.transition = CachedSettingsFamilyOverlayArt{};",
        "cache_state.transition.settings_address = settings_address;\n"
        "            cache_state.transition.elements =\n"
        "                std::move(transition_overlay);",
        "an unresolved outgoing Settings panel can enter the destination "
        "transition cache and be adopted as Controls art",
    ),
    StaticMutation(
        "recorder.settings-unresolved-cache-expiry",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        "now - cache_state.transition_started_at >\n"
        "                kTrackedSettingsMaximumIdleMs",
        "now - cache_state.transition_started_at <=\n"
        "                kTrackedSettingsMaximumIdleMs",
        "an unresolved Settings-family source can mask a settled main-menu "
        "destination beyond the bounded transition window",
    ),
    StaticMutation(
        "recorder.controls-retains-owner-through-underlay-frame",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "label_resolution_surface_registry_and_frame_render.inl",
        "if (entry.clear_settings_tracking &&\n"
        "                !retain_settings_tracking) {",
        "if (entry.clear_settings_tracking) {",
        "the main-menu underlay can retire the Settings owner before a visible "
        "Controls page reaches its unique native local origin",
    ),
    StaticMutation(
        "recorder.controls-current-frame-rollout",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        "page_observation.page == SettingsRolloutPageState::Controls;",
        "page_observation.page == SettingsRolloutPageState::Controls &&\n"
        "        !GetSettingsFamilyOverlayArtCacheState().controls.elements.empty();",
        "Controls classification can again wait for unrelated one-shot art "
        "after the native Controls page is uniquely at the local origin",
    ),
    StaticMutation(
        "recorder.controls-transition-source-surface",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        "cache_state.last_page == SettingsRolloutPageState::Controls &&\n"
        "        ShouldRetainSettingsTrackingAcrossMainMenuFallback() &&",
        "cache_state.last_page != SettingsRolloutPageState::Controls &&\n"
        "        ShouldRetainSettingsTrackingAcrossMainMenuFallback() &&",
        "Controls classification no longer requires either the unique live "
        "native rollout page or its bounded machine-proven transition source, "
        "plus the machine-measured Back control",
    ),
    StaticMutation(
        "recorder.settings-page-single-active",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_helpers.inl",
        "if (settings_at_origin == controls_at_origin) {",
        "if (settings_at_origin != controls_at_origin) {",
        "Settings and Controls can again be selected without one unique native "
        "rollout page occupying the live local origin",
    ),
    StaticMutation(
        "recorder.settings-cached-overlay-owner",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        "cache.settings_address != settings_address",
        "cache.settings_address == settings_address",
        "Settings-family cached page art can leak across an owner or "
        "transition, or the known source is not replayed while neither native "
        "page owns the origin",
    ),
    StaticMutation(
        "recorder.settings-transition-cache-adoption",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        "if (cache_state.last_page != page_observation.page &&\n"
        "        cache_state.transition.settings_address == settings_address &&",
        "if (cache_state.last_page == page_observation.page &&\n"
        "        cache_state.transition.settings_address == settings_address &&",
        "Settings-family cached page art can leak across an owner or "
        "transition, or the known source is not replayed while neither native "
        "page owns the origin",
    ),
    StaticMutation(
        "recorder.controls-live-back-action",
        SURFACE_AGREEMENT,
        "config/binary-layout.ini",
        ",controls.back",
        "",
        "the live Controls Back widget is no longer a configured interactive "
        "action backed by the native Settings done control",
    ),
    StaticMutation(
        "recorder.settings-live-rollout-affordance-pairing",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl",
        "rollout_rows.size() != marker_draws.size()",
        "rollout_rows.size() == marker_draws.size()",
        "Settings navigation can lose its unambiguous machine-measured "
        "rollout affordance and fall back to stale coordinates",
    ),
    StaticMutation(
        "recorder.settings-one-shot-row-retention",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_misc_surfaces.inl",
        'if (source.surface_id != "settings") {',
        'if (source.surface_id == "settings") {',
        "one-shot settings rows can disappear before settlement or leak from "
        "a different retained settings owner",
    ),
    StaticMutation(
        "recorder.settings-retired-owner-invalidation",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "state_actions_activation/resolved_action_activation.inl",
        "g_debug_ui_overlay_state.retained_settings_elements_owner = 0;",
        "g_debug_ui_overlay_state.retained_settings_elements_owner = "
        "g_debug_ui_overlay_state.settings_render.tracked_object_ptr;",
        "semantic action retirement can leave one-shot settings rows attached "
        "to a retired owner",
    ),
    StaticMutation(
        "recorder.foreign-exact-text-filter",
        SURFACE_AGREEMENT,
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "menu_layout_capture_snapshot_and_hooks.inl",
        "source_root != semantic_root &&",
        "source_root == semantic_root &&",
        "a selected native menu layout can inherit hidden exact text from a "
        "foreign semantic surface",
    ),
    StaticMutation(
        "recorder.transition-source-settlement-bound",
        SURFACE_AGREEMENT,
        "scripts/Record-NativeMenuTransition.ps1",
        "-TransitionalSourceScreen $SourceScreen",
        '-TransitionalSourceScreen ""',
        "a navigation edge can proceed without classifier agreement at both "
        "source and destination, or cannot distinguish a transient known "
        "source from wholesale surface substitution",
    ),
    StaticMutation(
        "recorder.failure-probe-shape",
        SURFACE_AGREEMENT,
        "scripts/Record-NativeMenuTransition.ps1",
        'probe_detail = Get-NativeMenuProbeProperty `\n'
        '                -Probe $failureProbe `\n'
        '                -Name "Detail" `\n'
        '                -Default $diagnosticError',
        'probe_detail = [string]$failureProbe.Detail',
        "a navigation failure can again mask its original error by reading "
        "probe-shape-specific properties or omit its click, measured surface, "
        "frame receipt, and exact failure class",
    ),
    StaticMutation(
        "recorder.no-provenance-override",
        RECORDER,
        "scripts/Import-NativeMenuSpecialCaptures.ps1",
        "    [string]$OutputRoot\n)",
        "    [string]$OutputRoot,\n\n    [string]$BaseCommitSha\n)",
        "native-menu recorder accepts operator-supplied provenance parameters in scripts/Import-NativeMenuSpecialCaptures.ps1: ['basecommitsha']",
    ),
    StaticMutation(
        "special.two-independent-instances",
        RECORDER,
        "tools/import_native_menu_special_captures_v25.py",
        "    assert_independent_pair(primary_header, confirmation_header, label)",
        "    pass  # mutation removes independent-pair enforcement",
        "native loader/loading import no longer requires two independent fresh instances with identical machine-derived provenance per surface",
    ),
    StaticMutation(
        "special.every-sample-overlay-hygiene",
        OVERLAY,
        "tools/import_native_menu_special_captures_v25.py",
        "    assert_overlay_sample_hygiene(\n        confirmation_samples, overlay_reference, f\"{label} confirmation\"\n    )",
        "    pass  # mutation drops confirmation sample-stream hygiene",
        "native-loader/loading import no longer overlay-gates every raw sample",
    ),
    StaticMutation(
        "aggregate.every-surface-overlay-hygiene",
        OVERLAY,
        "tools/build_native_menu_goldens_v25.py",
        "            assert_overlay_hygiene(fixture[\"layout\"], overlay)",
        "            pass  # mutation accepts a contaminated standalone",
        "the Settlement v2.5 aggregate can accept derived beta-dialog contamination in a standalone, transition source, or transition destination",
    ),
)


@contextmanager
def static_text_mutation(mutation: StaticMutation) -> Iterator[None]:
    original_read = static_contracts._read  # noqa: SLF001 - deliberate mutation seam.
    reached = False

    def mutated_read(relative_path: str) -> str:
        nonlocal reached
        text = original_read(relative_path)
        if relative_path != mutation.target:
            return text
        count = text.count(mutation.old)
        if count != 1:
            raise RuntimeError(
                f"mutation {mutation.claim!r} expected one source token in "
                f"{mutation.target}, found {count}"
            )
        reached = True
        return text.replace(mutation.old, mutation.new, 1)

    with patch.object(static_contracts, "_read", side_effect=mutated_read):
        yield
    if not reached:
        raise RuntimeError(
            f"mutation {mutation.claim!r} never reached {mutation.target}"
        )


def run_behavior_mutation(mutation: BehaviorMutation) -> MutationResult:
    clear_contract_bytecode()
    baseline_before = mutation.baseline()
    try:
        observed = mutation.mutant()
    except mutation.expected_exception as error:
        observed = str(error)
    except BaseException as error:
        raise RuntimeError(
            f"mutation {mutation.claim!r} raised the wrong exception "
            f"{type(error).__name__}: {error}"
        ) from error
    if observed != mutation.expected_message:
        raise RuntimeError(
            f"mutation {mutation.claim!r} tripped the wrong consequence:\n"
            f"expected: {mutation.expected_message}\nobserved: {observed}"
        )
    clear_contract_bytecode()
    baseline_after = mutation.baseline()
    return MutationResult(
        claim=mutation.claim,
        contract=mutation.contract,
        edit="scratch semantic payload mutation",
        expected_message=mutation.expected_message,
        observed_message=observed,
        baseline_before=baseline_before,
        baseline_after=baseline_after,
    )


def run_static_mutation(mutation: StaticMutation) -> MutationResult:
    contract = getattr(static_contracts, mutation.contract)
    clear_contract_bytecode()
    baseline_before = str(contract())
    observed = ""
    with static_text_mutation(mutation):
        clear_contract_bytecode()
        try:
            contract()
        except StaticReTestFailure as error:
            observed = str(error)
    if not observed:
        raise RuntimeError(
            f"mutation {mutation.claim!r} failed to trip {mutation.contract}"
        )
    if observed != mutation.expected_message:
        raise RuntimeError(
            f"mutation {mutation.claim!r} tripped the wrong claim:\n"
            f"expected: {mutation.expected_message}\nobserved: {observed}"
        )
    clear_contract_bytecode()
    baseline_after = str(contract())
    return MutationResult(
        claim=mutation.claim,
        contract=mutation.contract,
        edit=f"in-memory single-token edit of {mutation.target}",
        expected_message=mutation.expected_message,
        observed_message=observed,
        baseline_before=baseline_before,
        baseline_after=baseline_after,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()

    mutations: tuple[Mutation, ...] = (*BEHAVIOR_MUTATIONS, *STATIC_MUTATIONS)
    results: list[MutationResult] = []
    transcript: list[str] = []
    for index, mutation in enumerate(mutations, start=1):
        if isinstance(mutation, BehaviorMutation):
            result = run_behavior_mutation(mutation)
        else:
            result = run_static_mutation(mutation)
        results.append(result)
        line = (
            f"PASS {index:02d}/{len(mutations):02d} {result.claim}: "
            f"{result.observed_message} [green before/after]"
        )
        transcript.append(line)
        print(line)

    payload = {
        "schema": "solomon-dark-native-menu-contract-mutations-v1",
        "settlement_spec": "2.9",
        "count": len(results),
        "results": [asdict(result) for result in results],
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.json.with_name(args.json.name + ".menufix.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.json)
    summary = (
        f"{len(results)}/{len(mutations)} native-menu mutations reproduced "
        "their exact named consequence"
    )
    transcript.append(summary)
    if args.log is not None:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.log.with_name(args.log.name + ".menufix.tmp")
        temporary.write_text("\n".join(transcript) + "\n", encoding="utf-8")
        temporary.replace(args.log)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
