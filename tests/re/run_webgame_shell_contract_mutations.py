#!/usr/bin/env python3
"""Mutation-audit every consequence enforced by the P0 web shell contracts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import static_re_webgame_shell_contracts as contracts


@dataclass(frozen=True)
class TextMutation:
    claim: str
    contract: str
    target: Path
    old: str
    new: str
    expected: str
    replace_all: bool = False


@dataclass(frozen=True)
class SpecialMutation:
    claim: str
    contract: str
    activate: Callable[[], AbstractContextManager[None]]
    expected: str


@dataclass(frozen=True)
class MutationResult:
    claim: str
    contract: str
    expected_message: str
    observed_message: str
    baseline_before: str
    baseline_after: str


Mutation = TextMutation | SpecialMutation


def clear_contract_bytecode() -> None:
    cache = Path(__file__).resolve().parent / "__pycache__"
    if not cache.is_dir():
        return
    for child in cache.iterdir():
        if not child.is_file() or child.suffix != ".pyc":
            raise RuntimeError(f"refusing to clear unexpected contract cache entry {child}")
        child.unlink()
    cache.rmdir()


@contextmanager
def text_mutation(mutation: TextMutation) -> Iterator[None]:
    original_read = contracts._read_text  # noqa: SLF001 - this is the mutation seam.
    target = mutation.target.resolve()
    applied = False

    def mutated_read(path: Path, consequence: str) -> str:
        nonlocal applied
        text = original_read(path, consequence)
        if path.resolve() != target:
            return text
        occurrences = text.count(mutation.old)
        if occurrences == 0:
            raise RuntimeError(
                f"mutation {mutation.claim} cannot find its source token in {mutation.target}"
            )
        applied = True
        count = occurrences if mutation.replace_all else 1
        return text.replace(mutation.old, mutation.new, count)

    with patch.object(contracts, "_read_text", mutated_read):
        yield
    if not applied:
        raise RuntimeError(f"mutation {mutation.claim} never reached {mutation.target}")


@contextmanager
def production_witness_missing() -> Iterator[None]:
    original_rglob = Path.rglob
    witness = (contracts.INPUT / "intent.ts").resolve()

    def mutated_rglob(path: Path, pattern: str):  # type: ignore[no-untyped-def]
        values = original_rglob(path, pattern)
        if path.resolve() == contracts.INPUT.resolve() and pattern == "*.ts":
            return (candidate for candidate in values if candidate.resolve() != witness)
        return values

    with patch.object(Path, "rglob", mutated_rglob):
        yield


@contextmanager
def copied_golden_present() -> Iterator[None]:
    original_rglob = Path.rglob

    def mutated_rglob(path: Path, pattern: str):  # type: ignore[no-untyped-def]
        values = list(original_rglob(path, pattern))
        if path.resolve() == contracts.WEBGAME.resolve() and pattern == "*.json":
            values.append(contracts.WEBGAME / "menu-goldens.json")
        return iter(values)

    with patch.object(Path, "rglob", mutated_rglob):
        yield


@contextmanager
def corrected_controls_copies() -> Iterator[None]:
    """Present matching scratch copies of both committed G11 recordings as corrected."""
    original_read = contracts._read_text  # noqa: SLF001 - this is the mutation seam.
    targets = {
        (contracts.ROOT / "tests/fixtures/webgame/menu-layouts/controls.json").resolve(),
        contracts.MENU_GOLDEN.resolve(),
    }
    reached: set[Path] = set()

    def mutated_read(path: Path, consequence: str) -> str:
        text = original_read(path, consequence)
        resolved = path.resolve()
        if resolved not in targets:
            return text
        if "stale controls omitted" not in text:
            raise RuntimeError(f"corrected-controls mutation cannot find marker in {path}")
        reached.add(resolved)
        return text.replace(
            "stale controls omitted",
            "settle-gated machine-derived provenance",
        )

    with patch.object(contracts, "_read_text", mutated_read):
        yield
    if reached != targets:
        missing = sorted(str(path) for path in targets - reached)
        raise RuntimeError(
            "corrected-controls mutation did not reach both recording copies: "
            + ", ".join(missing)
        )


ARCHITECTURE = "test_webgame_shell_architecture_keeps_devices_inside_input"
FOCUS = "test_webgame_shell_twin_stick_and_focus_follow_landed_contracts"
RENDERER = "test_webgame_shell_manifest_renderer_and_layout_replay_are_strict"
TRAVERSAL = "test_webgame_shell_controller_traversal_covers_live_graph"
VISUAL = "test_webgame_shell_visual_waiver_is_exact_two_directional_and_self_expiring"
BOOT = "test_webgame_shell_boot_capture_performance_and_ci_are_wired"


MUTATIONS: tuple[Mutation, ...] = (
    SpecialMutation(
        "architecture.source-witness",
        ARCHITECTURE,
        production_witness_missing,
        "browser shell source sweep did not reach architecture witness(es): input/intent.ts",
    ),
    TextMutation(
        "architecture.intent-member",
        ARCHITECTURE,
        contracts.INTENT,
        "export type CastIntent = {",
        "type CastIntent = {",
        "G14 runtime Intent union lost its CastIntent member",
    ),
    TextMutation(
        "architecture.intent-union",
        ARCHITECTURE,
        contracts.INTENT,
        "export type Intent = MoveIntent | AimIntent | CastIntent | InteractIntent | MenuNavIntent;",
        "export type Intent = MoveIntent & AimIntent | CastIntent | InteractIntent | MenuNavIntent;",
        "browser shell Intent union no longer mirrors all five G14 intent families",
    ),
    TextMutation(
        "architecture.schema-authority",
        ARCHITECTURE,
        contracts.INTENT,
        "Runtime mirror of webgame-contracts/intent-schema.json",
        "Runtime mirror without authority",
        "runtime Intent validation no longer declares the landed G14 schema as authority",
    ),
    TextMutation(
        "architecture.gamepad-witness",
        ARCHITECTURE,
        contracts.GAMEPAD,
        "navigator.getGamepads()",
        'navigator["getGamepads"]()',
        "device-boundary sweep lost the real browser gamepad API witness",
        True,
    ),
    TextMutation(
        "architecture.keyboard-witness",
        ARCHITECTURE,
        contracts.KEYBOARD_MOUSE,
        "KeyboardEvent",
        "KeyEvent",
        "device-boundary sweep lost the real keyboard-event witness",
        True,
    ),
    TextMutation(
        "architecture.gamepad-boundary",
        ARCHITECTURE,
        contracts.APP,
        "  const sink = (intent: Intent): void => {",
        "  void navigator.getGamepads();\n  const sink = (intent: Intent): void => {",
        "raw input device knowledge escaped webgame/input into client/app.ts",
    ),
    TextMutation(
        "architecture.mouse-boundary",
        ARCHITECTURE,
        contracts.APP,
        "  const sink = (intent: Intent): void => {",
        "  let leakedMouse: MouseEvent;\n  void leakedMouse;\n  const sink = (intent: Intent): void => {",
        "raw input device knowledge escaped webgame/input into client/app.ts",
    ),
    TextMutation(
        "architecture.listener-boundary",
        ARCHITECTURE,
        contracts.APP,
        "  const sink = (intent: Intent): void => {",
        '  window.addEventListener("keydown", () => undefined);\n  const sink = (intent: Intent): void => {',
        "raw input device knowledge escaped webgame/input into client/app.ts",
    ),
    TextMutation(
        "architecture.intent-sink",
        ARCHITECTURE,
        contracts.APP,
        "    controller.handle(intent);",
        "    controller.handle(parseIntent(intent));",
        "browser client no longer joins both device producers through the G14 Intent sink",
    ),
    TextMutation(
        "input.inner-deadzone",
        FOCUS,
        contracts.TWIN_STICK,
        "export const GAMEPAD_INNER_DEADZONE = 0.2;",
        "export const GAMEPAD_INNER_DEADZONE = 0.21;",
        "roadmap section 4.2 deadzone/aim constants no longer match the landed table",
    ),
    TextMutation(
        "input.outer-deadzone",
        FOCUS,
        contracts.TWIN_STICK,
        "export const GAMEPAD_OUTER_DEADZONE = 0.95;",
        "export const GAMEPAD_OUTER_DEADZONE = 0.94;",
        "roadmap section 4.2 deadzone/aim constants no longer match the landed table",
    ),
    TextMutation(
        "input.aim-offset",
        FOCUS,
        contracts.TWIN_STICK,
        "export const AIM_ANCHOR_Y_OFFSET_PX = -25;",
        "export const AIM_ANCHOR_Y_OFFSET_PX = -24;",
        "roadmap section 4.2 deadzone/aim constants no longer match the landed table",
    ),
    TextMutation(
        "input.radial-renormalization",
        FOCUS,
        contracts.TWIN_STICK,
        "const magnitude = Math.min(1, (rawMagnitude - inner) / (outer - inner));",
        "const magnitude = Math.min(1, rawMagnitude);",
        "gamepad stick magnitude is no longer radially re-normalized between inner and outer edges",
    ),
    TextMutation(
        "input.projected-aim-anchor",
        FOCUS,
        contracts.TWIN_STICK,
        "y: projection.projectedPlayerPx.y + AIM_ANCHOR_Y_OFFSET_PX,",
        "y: projection.playerWorld.y + AIM_ANCHOR_Y_OFFSET_PX,",
        "aim anchor no longer uses project(player) plus the exact negative 25 screen pixels",
    ),
    TextMutation(
        "input.retained-aim",
        FOCUS,
        contracts.GAMEPAD,
        "this.#lastAimDirection = right.direction;",
        "this.#lastAimDirection = null;",
        "right-stick release no longer holds and reprojects the last aim direction",
    ),
    TextMutation(
        "input.producer-only-assist",
        FOCUS,
        contracts.SHELL_CONTROLLER,
        "export class ShellController {",
        "// aim assist mutant\nexport class ShellController {",
        "aim assistance escaped the producer boundary into shell state",
    ),
    TextMutation(
        "focus.screen-floor",
        FOCUS,
        contracts.FOCUS_GOLDEN,
        '"screens": [',
        '"screens": [], "discarded_screens": [',
        "focus implementation no longer has all 28 G11 screen rules",
    ),
    TextMutation(
        "focus.census-witnesses",
        FOCUS,
        contracts.MENU_GOLDEN,
        '"screen_census":  [',
        '"screen_census":  ["mutant"], "discarded_screen_census":  [',
        "focus/menu comparison did not reach native-loader and game-over census witnesses",
    ),
    TextMutation(
        "focus.exact-census",
        FOCUS,
        contracts.FOCUS_GOLDEN,
        '"layout_id": "native-loader"',
        '"layout_id": "mutant-loader"',
        "G11 focus rules no longer match the exact 28-layout census",
    ),
    TextMutation(
        "focus.fixture-provenance",
        FOCUS,
        contracts.FOCUS_GOLDEN,
        '"layout_id": "native-loader",\n      "provenance": "DESIGN_NOT_OBSERVED"',
        '"layout_id": "native-loader",\n      "provenance": "MUTANT"',
        "a designed controller behavior lost its G11 DESIGN_NOT_OBSERVED provenance marker",
    ),
    TextMutation(
        "focus.modal-policy",
        FOCUS,
        contracts.FOCUS_GOLDEN,
        '"trap_focus": true',
        '"trap_focus": false',
        "designed modal focus no longer traps, blocks its underlay, and restores its invoker",
    ),
    TextMutation(
        "focus.code-provenance-citation",
        FOCUS,
        contracts.FOCUS,
        "docs/reverse-engineering/native-menus-and-boot.md",
        "docs/mutant.md",
        "focus implementation no longer cites the G11 designed-navigation section beside its DESIGN_NOT_OBSERVED branches",
    ),
    TextMutation(
        "focus.real-html-input",
        FOCUS,
        contracts.TEXT_INPUTS,
        'const input = document.createElement("input");',
        'const input = document.createElement("canvas");',
        "Deck text entry is no longer implemented with real text/password HTML input elements",
    ),
    TextMutation(
        "render.canonical-golden-imports",
        RENDERER,
        contracts.APP,
        'import inertControlsJson from "../../webgame-contracts/inert-controls.json" with { type: "json" };\nimport focusModelJson',
        'import inertControlsJson from "../../webgame-contracts/inert-controls.json" with { type: "json" };\nvoid 0;\nimport focusModelJson',
        "browser shell no longer imports the preview aggregate, inert worklist, and focus recording directly and adjacently",
    ),
    SpecialMutation(
        "render.no-copied-golden",
        RENDERER,
        copied_golden_present,
        "browser shell contains a second mutable copy of a landed menu/focus golden: menu-goldens.json",
    ),
    TextMutation(
        "manifest.direct-alias-ambiguity",
        RENDERER,
        contracts.MANIFEST_ASSETS,
        "entry and alias both exist",
        "entry wins over alias",
        "manifest lookup no longer refuses direct/alias ambiguity",
    ),
    TextMutation(
        "manifest.alias-chain-ambiguity",
        RENDERER,
        contracts.MANIFEST_ASSETS,
        "resolution is ambiguous",
        "resolution is accepted",
        "manifest lookup no longer refuses alias-chain ambiguity",
    ),
    TextMutation(
        "manifest.missing-id-hard-failure",
        RENDERER,
        contracts.MANIFEST_ASSETS,
        "missing required asset id",
        "optional absent art",
        "missing shell art no longer hard-fails with its asset id",
    ),
    TextMutation(
        "manifest.audit-witness-floor",
        RENDERER,
        contracts.MANIFEST_ASSETS,
        "assetpack shell audit did not reach any G11 layout elements",
        "empty audit accepted",
        "manifest audit can now pass without checking a real menu element",
    ),
    TextMutation(
        "manifest.missing-glyph-hard-failure",
        RENDERER,
        contracts.MANIFEST_ASSETS,
        "missing glyph U+",
        "skipped glyph U+",
        "bitmap text can now silently skip a missing manifest glyph",
    ),
    TextMutation(
        "manifest.single-route",
        RENDERER,
        contracts.MANIFEST_ASSETS,
        'loadManifestAssets(url = "/assetpack/asset-manifest.json")',
        'loadManifestAssets(url = "/images/asset-manifest.json")',
        "browser shell manifest no longer loads through the one assetpack route",
    ),
    TextMutation(
        "manifest.vite-boundary",
        RENDERER,
        contracts.VITE,
        "publicDir: false",
        'publicDir: "public"',
        "Vite can serve shell images outside the explicit assetpack route",
    ),
    TextMutation(
        "manifest.no-literal-images",
        RENDERER,
        contracts.APP,
        "async function main(): Promise<void> {",
        'const leakedImage = "placeholder.png";\nvoid leakedImage;\n\nasync function main(): Promise<void> {',
        "production shell hard-codes image files outside manifest lookup in client/app.ts",
    ),
    TextMutation(
        "render.webgl2-required",
        RENDERER,
        contracts.RENDERER,
        'canvas.getContext("webgl2", {',
        'canvas.getContext("webgl", {',
        "shell renderer no longer requires a real WebGL2 canvas context",
    ),
    TextMutation(
        "render.g12-layer-order",
        RENDERER,
        contracts.RENDER_PLAN,
        '  "world-sorted",',
        '  "world-unsorted",',
        "browser render plans no longer retain the exact five-pass G12 physical order",
    ),
    TextMutation(
        "replay.zero-epsilon",
        RENDERER,
        contracts.LAYOUT_REPLAY,
        "const POSITION_EPSILON = 0;",
        "const POSITION_EPSILON = 0.5;",
        "T2 replay no longer declares exact zero position epsilon",
    ),
    TextMutation(
        "replay.aggregate-layout-consumption",
        RENDERER,
        contracts.LAYOUT_REPLAY,
        "assertLayoutReplay(layout, wrapper, assets)",
        "acceptLayoutWithoutReplay(layout, wrapper, assets)",
        "T2 replay no longer consumes every embedded aggregate layout",
    ),
    TextMutation(
        "replay.manifest-audit",
        RENDERER,
        contracts.LAYOUT_REPLAY,
        "assets.assertShellAssets(catalog);",
        "void catalog;",
        "T2 replay no longer audits every shell asset through the manifest",
    ),
    TextMutation(
        "replay.screen-census",
        RENDERER,
        contracts.LAYOUT_REPLAY,
        "layouts=${conformed.size}/${catalog.screenCensus.length}",
        "layouts=${conformed.size}/unknown",
        "T2 replay no longer reports the complete aggregate census",
    ),
    TextMutation(
        "replay.ambient-census",
        RENDERER,
        contracts.LAYOUT_REPLAY,
        "ambient_members=${ambientCount}",
        "ambient_members=unknown",
        "T2 replay no longer reports exact ambient-member replay coverage",
    ),
    TextMutation(
        "replay.critical-zero-waiver",
        RENDERER,
        contracts.LAYOUT_REPLAY,
        "critical_layouts=${criticalLayouts.size}/${criticalLayouts.size}; waivers=0",
        "critical_layouts=${criticalLayouts.size}/${criticalLayouts.size}; waivers=1",
        "T2 replay no longer proves zero critical-layout waivers",
    ),
    TextMutation(
        "replay.composite-zero-residue",
        RENDERER,
        contracts.LAYOUT_REPLAY,
        "beta_residue=0",
        "beta_residue=unknown",
        "T2 replay no longer proves zero-residue first-boot decomposition",
    ),
    TextMutation(
        "replay.deck-safe-area",
        RENDERER,
        contracts.LAYOUT_REPLAY,
        "safe_area_1280x800=1280x720+40px_top+40px_bottom",
        "safe_area_1280x800=unchecked",
        "T2 replay no longer pins the 16:10 safe area",
    ),
    TextMutation(
        "traversal.gamepad-producer",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "new GamepadProducer",
        "new MutantProducer",
        "controller traversal no longer enters through the gamepad Intent producer",
    ),
    TextMutation(
        "traversal.synthetic-snapshots",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "producer.sample(snapshot(index));",
        "producer.sampleFromCursor(index);",
        "controller traversal no longer presses synthetic standard-gamepad snapshots",
    ),
    TextMutation(
        "traversal.exact-edge-set",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "[...CRITICAL_MENU_EDGE_IDS].sort()",
        "[...visited].sort()",
        "controller traversal no longer proves exact equality with the ruled critical-edge set",
    ),
    TextMutation(
        "traversal.edge-report",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "visited.size}/${CRITICAL_MENU_EDGE_IDS.length",
        "visited.size}/unknown",
        "controller traversal no longer reports exact critical-edge coverage",
    ),
    TextMutation(
        "traversal.human-log",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "WEBGAME_TRAVERSAL_LOG",
        "MUTANT_TRAVERSAL_LOG",
        "controller traversal no longer emits human-readable evidence",
    ),
    TextMutation(
        "traversal.reset-provenance",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "setup resets never count as graph edges",
        "resets may count as edges",
        "traversal evidence no longer distinguishes setup from gamepad edges",
    ),
    TextMutation(
        "traversal.action-family-log",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "CRITICAL ACTION FAMILIES",
        "MUTANT ACTION FAMILIES",
        "controller traversal no longer emits the complete scheme/element/discipline family sweep",
    ),
    TextMutation(
        "traversal.action-family-discovery",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "actionId.startsWith(family.prefix)",
        "actionId === family.prefix",
        "controller traversal no longer discovers every selectable action-family member",
    ),
    TextMutation(
        "traversal.inert-log",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "MANIFEST-DRIVEN INERT SWEEP",
        "PARTIAL INERT SWEEP",
        "controller traversal no longer activates the machine-readable inert worklist",
    ),
    TextMutation(
        "traversal.inert-state-equality",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "controller.snapshot(),\n      before",
        "controller.snapshot(),\n      structuredClone(before)",
        "inert sweep no longer proves navigation and state remain unchanged",
    ),
    TextMutation(
        "traversal.pending-capture-class",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        'assert.equal(pendingCapture, 1, "inert sweep must contain exactly the ruled NEW GAME capture gap")',
        'assert.equal(pendingCapture, 0, "inert sweep accepts no capture gap")',
        "inert sweep no longer distinguishes the pending-capture NEW GAME entry",
    ),
    TextMutation(
        "traversal.disposition-report",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "owner_descoped, ${pendingCapture} pending_capture",
        "inert, ${pendingCapture} unknown",
        "inert sweep no longer reports both machine disposition tags",
    ),
    TextMutation(
        "traversal.intent-routing",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "controller.handle(intent);",
        "void intent;",
        "synthetic gamepad traversal no longer routes emitted Intents into shell state",
    ),
    TextMutation(
        "traversal.exactly-once",
        TRAVERSAL,
        contracts.CONTROLLER_TRAVERSAL,
        "visited.add(edgeId);",
        "void edgeId;",
        "controller traversal no longer makes duplicate or omitted critical edges fail by name",
    ),
    TextMutation(
        "traversal.inert-controller-gate",
        TRAVERSAL,
        contracts.SHELL_CONTROLLER,
        "if (this.#inert.has(screen, actionId)) {\n      return;",
        "if (false) {\n      return;",
        "shell controller no longer consumes the inert manifest before dispatch",
    ),
    TextMutation(
        "traversal.edge-witness",
        TRAVERSAL,
        contracts.SHELL_CONTROLLER,
        '"profile_select_resume_to_hub",',
        '"profile_select_resume_to_void",',
        "shell controller lost ruled critical edge profile_select_resume_to_hub",
    ),
    TextMutation(
        "visual.no-extra-tolerance-field",
        VISUAL,
        contracts.VISUAL_GATE,
        '{\n  "schema":',
        '{\n  "epsilon": 1,\n  "schema":',
        "menu visual gate gained an unreviewed field that could smuggle extra tolerance",
    ),
    TextMutation(
        "visual.versioned-schema",
        VISUAL,
        contracts.VISUAL_GATE,
        "solomon-dark-menu-visual-gate-v1",
        "solomon-dark-menu-visual-gate-v2",
        "menu visual gate lost its versioned schema",
    ),
    TextMutation(
        "visual.original-pixel-rule",
        VISUAL,
        contracts.VISUAL_GATE,
        "requires the same assetpack art at exact G11 positions",
        "allows similar assetpack art near G11 positions",
        "menu visual gate loosened the original same-art exact-position rule",
    ),
    TextMutation(
        "visual.census-witness-floor",
        VISUAL,
        contracts.MENU_GOLDEN,
        '"screen_census":  [',
        '"screen_census":  [],\n    "discarded_screen_census":  [',
        "visual waiver audit did not reach the exact G11 census witnesses",
    ),
    TextMutation(
        "visual.wrapper-floor",
        VISUAL,
        contracts.MENU_GOLDEN,
        '"layouts":  [',
        '"layouts":  [],\n    "discarded_layouts":  [',
        "visual waiver audit did not reach all 28 embedded layout records",
    ),
    TextMutation(
        "visual.wrapper-resolves-layout",
        VISUAL,
        contracts.MENU_GOLDEN,
        '"fixture":  "menu-layouts/beta-notice.json"',
        '"mutant_fixture":  "menu-layouts/beta-notice.json"',
        "visual waiver audit cannot resolve an embedded fixture to its layout",
    ),
    TextMutation(
        "visual.wrapper-refuses-duplicate",
        VISUAL,
        contracts.MENU_GOLDEN,
        '"fixture":  "menu-layouts/control-scheme-picker.json"',
        '"fixture":  "menu-layouts/beta-notice.json"',
        "visual waiver audit refuses duplicate embedded fixture candidate menu-layouts/beta-notice.json",
    ),
    TextMutation(
        "visual.divergences-are-named",
        VISUAL,
        contracts.VISUAL_GATE,
        '"reviewed_divergent_fixtures": [\n    "menu-layouts/controls.json"',
        '"reviewed_divergent_fixtures": [\n    7',
        "menu visual gate no longer names divergent fixtures explicitly",
    ),
    TextMutation(
        "visual.unlisted-eleventh-divergence",
        VISUAL,
        contracts.VISUAL_GATE,
        '"reviewed_divergent_fixtures": [\n    "menu-layouts/controls.json"',
        '"reviewed_divergent_fixtures": [\n    "menu-layouts/main-menu-root.json"',
        "unwaived visual divergence: menu-layouts/main-menu-root.json",
    ),
    TextMutation(
        "visual.exact-ten-divergences",
        VISUAL,
        contracts.VISUAL_GATE,
        '"reviewed_divergent_fixtures": [\n    "menu-layouts/controls.json"',
        '"reviewed_divergent_fixtures": [\n    "menu-layouts/dark-cloud-login-settings.json"',
        "menu visual gate no longer enumerates exactly the ten ATC-waived fixtures: menu-layouts/controls.json",
    ),
    TextMutation(
        "visual.passes-are-named",
        VISUAL,
        contracts.VISUAL_GATE,
        '"reviewed_pass_fixtures": [\n    "menu-layouts/beta-notice.json"',
        '"reviewed_pass_fixtures": [\n    7',
        "menu visual gate no longer names the ordinary pixel-plausible passes",
    ),
    TextMutation(
        "visual.exact-18-10-partition",
        VISUAL,
        contracts.VISUAL_GATE,
        '"reviewed_pass_fixtures": [\n    "menu-layouts/beta-notice.json"',
        '"reviewed_pass_fixtures": [\n    "menu-layouts/control-scheme-picker.json"',
        "menu visual gate no longer partitions the exact census into 18 unchanged passes and 10 waivers",
    ),
    TextMutation(
        "visual.waiver-scope",
        VISUAL,
        contracts.VISUAL_GATE,
        '"waiver": {\n    "decision":',
        '"waiver": {\n    "epsilon": 1,\n    "decision":',
        "menu visual waiver gained scope beyond its ATC decision and enumerated entries",
    ),
    TextMutation(
        "visual.governing-decision",
        VISUAL,
        contracts.VISUAL_GATE,
        "ATC 2026-08-05 evening",
        "ATC 2026-08-05 afternoon",
        "menu visual waiver lost the governing ATC decision",
    ),
    TextMutation(
        "visual.exact-entry-count",
        VISUAL,
        contracts.VISUAL_GATE,
        ',\n      {\n        "fixture": "menu-layouts/performance.json",\n        "required_marker": "stale controls omitted",\n        "corrective": "menufix task #97"\n      }',
        "",
        "menu visual waiver no longer has exactly ten fixture-specific entries",
    ),
    TextMutation(
        "visual.entry-audit-schema",
        VISUAL,
        contracts.VISUAL_GATE,
        '"fixture": "menu-layouts/controls.json",\n        "required_marker":',
        '"fixture": "menu-layouts/controls.json",\n        "epsilon": 1,\n        "required_marker":',
        "a menu visual waiver entry can no longer be audited as fixture, marker, and corrective",
    ),
    TextMutation(
        "visual.entry-names-fixture",
        VISUAL,
        contracts.VISUAL_GATE,
        '"entries": [\n      {\n        "fixture": "menu-layouts/controls.json"',
        '"entries": [\n      {\n        "fixture": 7',
        "a menu visual waiver entry no longer names its fixture",
    ),
    TextMutation(
        "visual.entry-refuses-duplicate",
        VISUAL,
        contracts.VISUAL_GATE,
        '"fixture": "menu-layouts/dark-cloud-login-settings.json",',
        '"fixture": "menu-layouts/controls.json",',
        "menu visual waiver refuses duplicate candidate menu-layouts/controls.json",
    ),
    TextMutation(
        "visual.entry-covers-each-divergence",
        VISUAL,
        contracts.VISUAL_GATE,
        '"entries": [\n      {\n        "fixture": "menu-layouts/controls.json"',
        '"entries": [\n      {\n        "fixture": "menu-layouts/main-menu-root.json"',
        "unwaived visual divergence: menu-layouts/controls.json",
    ),
    TextMutation(
        "visual.literal-marker-citation",
        VISUAL,
        contracts.VISUAL_GATE,
        '"fixture": "menu-layouts/controls.json",\n        "required_marker": "stale controls omitted"',
        '"fixture": "menu-layouts/controls.json",\n        "required_marker": "stale elements omitted"',
        "visual waiver does not cite the literal stale marker: menu-layouts/controls.json",
    ),
    TextMutation(
        "visual.menufix-corrective",
        VISUAL,
        contracts.VISUAL_GATE,
        '"fixture": "menu-layouts/controls.json",\n        "required_marker": "stale controls omitted",\n        "corrective": "menufix task #97"',
        '"fixture": "menu-layouts/controls.json",\n        "required_marker": "stale controls omitted",\n        "corrective": "goldfix"',
        "visual waiver does not point menu-layouts/controls.json to menufix task #97",
    ),
    TextMutation(
        "visual.standalone-layout-provenance",
        VISUAL,
        contracts.ROOT / "tests/fixtures/webgame/menu-layouts/controls.json",
        '"layout":  {',
        '"mutant_layout":  {',
        "visual waiver cannot inspect capture provenance for menu-layouts/controls.json",
    ),
    TextMutation(
        "visual.recording-copies-agree",
        VISUAL,
        contracts.ROOT / "tests/fixtures/webgame/menu-layouts/controls.json",
        '"screen_title":  "",\n                   "capture_method":  "live native UI tree + exact text/font hooks + native Sprite draw hooks + exact live-navigation screen tag (stale controls omitted)"',
        '"screen_title":  "",\n                   "capture_method":  "live native UI tree + exact text/font hooks + native Sprite draw hooks + exact live-navigation screen tag (settle-gated machine-derived provenance)"',
        "standalone and embedded capture provenance disagree for waived fixture menu-layouts/controls.json",
    ),
    SpecialMutation(
        "visual.corrected-fixture-self-expires",
        VISUAL,
        corrected_controls_copies,
        'illegal stale visual waiver: menu-layouts/controls.json no longer bears literal marker "stale controls omitted"; delete the waiver and pass full visual match',
    ),
    TextMutation(
        "visual.no-unwaived-stale-pass",
        VISUAL,
        contracts.MENU_GOLDEN,
        '"screen_title":  "Dialog",\n                                       "capture_method":  "live native UI tree + exact text/font hooks + native Sprite draw hooks"',
        '"screen_title":  "Dialog",\n                                       "capture_method":  "live native UI tree + exact text/font hooks + native Sprite draw hooks (stale controls omitted)"',
        "unwaived stale visual fixture: menu-layouts/beta-notice.json",
    ),
    TextMutation(
        "visual.reference-metadata",
        VISUAL,
        contracts.MENU_GOLDEN,
        '"fixture":  "menu-layouts/beta-notice.json",\n                        "reference_capture":',
        '"fixture":  "menu-layouts/beta-notice.json",\n                        "mutant_reference_capture":',
        "visual review cannot bind menu-layouts/beta-notice.json to its committed reference capture",
    ),
    TextMutation(
        "visual.reference-hash-binds-file",
        VISUAL,
        contracts.MENU_GOLDEN,
        '"reference_sha256":  "400e98e7b338aa89fce84fcd17991bdf406fb2b72549e60f2c930012cba3450c"',
        '"reference_sha256":  "500e98e7b338aa89fce84fcd17991bdf406fb2b72549e60f2c930012cba3450c"',
        "G11 visual reference for menu-layouts/controls.json does not match its file: recorded 500e98e7b338aa89, controls.png hashes to 400e98e7b338aa89",
    ),
    TextMutation(
        "visual.runtime-unlisted-message",
        VISUAL,
        contracts.VISUAL_GATE_SOURCE,
        "unwaived visual divergence: ${fixture}",
        "visual mismatch: ${fixture}",
        "runtime visual gate no longer names an eleventh divergent fixture",
    ),
    TextMutation(
        "visual.runtime-self-expiry-message",
        VISUAL,
        contracts.VISUAL_GATE_SOURCE,
        "illegal stale visual waiver: ${entry.fixture} no longer bears literal marker",
        "stale waiver: ${entry.fixture}",
        "runtime visual gate no longer self-expires a corrected fixture waiver",
    ),
    TextMutation(
        "visual.runtime-no-tolerance",
        VISUAL,
        contracts.VISUAL_GATE_SOURCE,
        "menu visual gate changed the original pixel-plausibility rule or added tolerance",
        "menu visual gate accepted approximate pixels",
        "runtime visual gate no longer rejects extra visual tolerance",
    ),
    TextMutation(
        "visual.unit-unlisted-direction",
        VISUAL,
        contracts.VISUAL_GATE_TEST,
        "rejects an eleventh, unlisted visual divergence by fixture name",
        "accepts an eleventh divergence",
        "unit mutation no longer exercises the unlisted-divergence direction",
    ),
    TextMutation(
        "visual.unit-corrected-direction",
        VISUAL,
        contracts.VISUAL_GATE_TEST,
        "scratch recapture loses the stale marker",
        "scratch recapture keeps the marker",
        "unit mutation no longer exercises the corrected-listed-fixture direction",
    ),
    TextMutation(
        "visual.capture-zero-waiver",
        VISUAL,
        contracts.CAPTURE,
        "criticalWaivers: 0",
        "criticalWaivers: 1",
        "preview capture no longer records that critical layouts use zero waivers",
    ),
    TextMutation(
        "visual.capture-dispositions",
        VISUAL,
        contracts.CAPTURE,
        'disposition: isCritical ? "critical_exact_review_required" : "inert_rendered"',
        'disposition: "unreviewed"',
        "preview capture no longer distinguishes critical comparisons from inert render proofs",
    ),
    TextMutation(
        "visual.capture-composite",
        VISUAL,
        contracts.CAPTURE,
        "criticalCompositeIds: compositeArtifacts.map",
        "ignoredCompositeIds: compositeArtifacts.map",
        "live visual evidence no longer includes the first-boot semantic dialog composite",
    ),
    TextMutation(
        "visual.capture-binds-reference",
        VISUAL,
        contracts.CAPTURE,
        "referenceSha256 !== layout.referenceSha256",
        "referenceSha256 === layout.referenceSha256",
        "live visual evidence no longer binds each comparison to its committed reference",
    ),
    TextMutation(
        "visual.docs-exact-screen-list",
        VISUAL,
        contracts.KNOWN_ISSUES,
        "- `controls`",
        "- controls",
        "webgame known-issues note no longer lists exactly the ten waived screen names",
    ),
    TextMutation(
        "visual.docs-corrective",
        VISUAL,
        contracts.KNOWN_ISSUES,
        "menufix task #97",
        "future correction",
        "webgame known-issues note no longer names the corrective or forbids PNG-derived geometry",
        True,
    ),
    TextMutation(
        "visual.docs-no-png-geometry",
        VISUAL,
        contracts.KNOWN_ISSUES,
        "Never\nreconstruct missing geometry from a PNG",
        "May\nreconstruct missing geometry from a PNG",
        "webgame known-issues note no longer names the corrective or forbids PNG-derived geometry",
    ),
    TextMutation(
        "boot.real-work-progress",
        BOOT,
        contracts.APP,
        "completed += 1;",
        "completed = completed + 1;",
        "Raptisoft loader progress is no longer bound directly to each real 28-layout preparation unit",
    ),
    TextMutation(
        "boot.no-timer",
        BOOT,
        contracts.APP,
        "async function main(): Promise<void> {",
        "async function main(): Promise<void> {\n  setTimeout(() => undefined, 0);",
        "boot loader gained a timer and is no longer purely real-work-bound",
    ),
    TextMutation(
        "boot.title-fade",
        BOOT,
        contracts.APP,
        "{ duration: 1100, easing: \"linear\", fill: \"both\" },",
        "{ duration: 900, easing: \"linear\", fill: \"both\" },",
        "first title entry no longer uses the G11 1.1-second fade",
    ),
    TextMutation(
        "boot.input-gate",
        BOOT,
        contracts.SHELL_CONTROLLER,
        "this.#inputGateUntil = this.#clock() + 2000;",
        "this.#inputGateUntil = this.#clock() + 1000;",
        "first title input no longer stays gated through the G11 two-second threshold",
    ),
    TextMutation(
        "capture.busy-port",
        BOOT,
        contracts.CAPTURE,
        "capture port ${SERVER_PORT} is busy",
        "port ownership ignored",
        "evidence runner no longer refuses an already-busy server port",
    ),
    TextMutation(
        "capture.broken-vs-busy",
        BOOT,
        contracts.CAPTURE,
        "browser shell server is broken, not busy",
        "browser shell still waiting",
        "evidence runner no longer distinguishes a broken launch from startup work",
    ),
    TextMutation(
        "capture.real-chromium",
        BOOT,
        contracts.CAPTURE,
        "browser = await chromium.launch",
        "browser = await fakeBrowser.launch",
        "evidence runner no longer exercises real headless Chromium",
    ),
    TextMutation(
        "capture.screen-census",
        BOOT,
        contracts.CAPTURE,
        "for (const layoutId of catalog.screenCensus)",
        "for (const layoutId of selectedScreens)",
        "evidence runner no longer sweeps the landed 28-screen census",
        True,
    ),
    TextMutation(
        "capture.deck-render-set",
        BOOT,
        contracts.CAPTURE,
        "rendered-1280x800",
        "rendered-unknown",
        "evidence runner no longer captures the 1280x800 Deck-safe render set",
        True,
    ),
    TextMutation(
        "capture.side-by-side",
        BOOT,
        contracts.CAPTURE,
        "side-by-side",
        "unpaired",
        "evidence runner no longer produces native/WebGL comparisons",
        True,
    ),
    TextMutation(
        "capture.sustained-frame-sample",
        BOOT,
        contracts.CAPTURE,
        "measureFrameTimes(600)",
        "measureFrameTimes(6)",
        "evidence runner no longer measures a sustained 600-frame sample",
    ),
    TextMutation(
        "capture.pid-identity",
        BOOT,
        contracts.CAPTURE,
        "sameProcessStillRuns",
        "pidNumberStillExists",
        "evidence cleanup no longer verifies PID identity before declaring owned processes gone",
        True,
    ),
    TextMutation(
        "capture.live-asset-audit",
        BOOT,
        contracts.CAPTURE,
        "shell loaded image outside the assetpack manifest",
        "external image accepted",
        "live capture no longer rejects image requests outside the manifest",
    ),
    TextMutation(
        "ci.package-command-map",
        BOOT,
        contracts.PACKAGE,
        '"scripts": {',
        '"scripts": [], "discarded_scripts": {',
        "webgame package no longer exposes a command map",
    ),
    TextMutation(
        "ci.exact-package-commands",
        BOOT,
        contracts.PACKAGE,
        '"build": "vite build"',
        '"build": "vite build --mode mutant"',
        "webgame package no longer exposes build, T2 replay, and controller traversal commands exactly",
    ),
    TextMutation(
        "ci.build-step",
        BOOT,
        contracts.CI,
        "      - name: Build browser shell",
        "      - name: Mutant browser shell",
        "CI no longer builds the browser shell",
    ),
    TextMutation(
        "ci.replay-step",
        BOOT,
        contracts.CI,
        "      - name: Replay G11 browser-shell layouts",
        "      - name: Skip G11 browser-shell layouts",
        "CI no longer runs the exact G11 T2 layout replay",
    ),
    TextMutation(
        "ci.controller-step",
        BOOT,
        contracts.CI,
        "      - name: Traverse browser shell with synthetic gamepad",
        "      - name: Skip browser shell traversal",
        "CI no longer runs the complete controller-only navigation traversal",
    ),
)


def run_mutation(mutation: Mutation) -> MutationResult:
    contract = getattr(contracts, mutation.contract)
    clear_contract_bytecode()
    before = contract()
    observed = ""
    active = text_mutation(mutation) if isinstance(mutation, TextMutation) else mutation.activate()
    clear_contract_bytecode()
    with active:
        try:
            contract()
        except contracts.StaticReTestFailure as exc:
            observed = str(exc)
        else:
            raise RuntimeError(f"mutation {mutation.claim} failed to trip {mutation.contract}")
    if observed != mutation.expected:
        raise RuntimeError(
            f"mutation {mutation.claim} tripped the wrong claim:\n"
            f"expected: {mutation.expected}\nobserved: {observed}"
        )
    clear_contract_bytecode()
    after = contract()
    return MutationResult(
        claim=mutation.claim,
        contract=mutation.contract,
        expected_message=mutation.expected,
        observed_message=observed,
        baseline_before=before,
        baseline_after=after,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="Write the complete mutation table as JSON")
    args = parser.parse_args()
    results: list[MutationResult] = []
    for index, mutation in enumerate(MUTATIONS, start=1):
        result = run_mutation(mutation)
        results.append(result)
        print(
            f"PASS {index:02d}/{len(MUTATIONS)} {result.claim}: "
            f"{result.observed_message} [green before/after]"
        )
    if args.json is not None:
        args.json.write_text(
            json.dumps([asdict(result) for result in results], indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"{len(results)}/{len(MUTATIONS)} shell contract mutations tripped the named claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
