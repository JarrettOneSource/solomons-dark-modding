"""Static contracts for the sim-less P0 browser menu shell."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
)


WEBGAME = ROOT / "webgame"
INPUT = WEBGAME / "input"
CLIENT = WEBGAME / "client"
APP = CLIENT / "app.ts"
RENDERER = CLIENT / "webgl-renderer.ts"
RENDER_PLAN = CLIENT / "render-plan.ts"
MANIFEST_ASSETS = CLIENT / "manifest-assets.ts"
TEXT_INPUTS = CLIENT / "text-inputs.ts"
SHELL_CONTROLLER = CLIENT / "shell-controller.ts"
INTENT = INPUT / "intent.ts"
TWIN_STICK = INPUT / "twin-stick.ts"
GAMEPAD = INPUT / "gamepad-producer.ts"
KEYBOARD_MOUSE = INPUT / "keyboard-mouse-producer.ts"
FOCUS = INPUT / "focus-model.ts"
LAYOUT_REPLAY = WEBGAME / "conformance/run-layout-replay.ts"
CONTROLLER_TRAVERSAL = WEBGAME / "conformance/run-controller-traversal.ts"
CAPTURE = WEBGAME / "scripts/capture-shell.ts"
VITE = WEBGAME / "vite.config.ts"
PACKAGE = WEBGAME / "package.json"
FOCUS_GOLDEN = ROOT / "webgame-contracts/menu-focus-model.json"
MENU_GOLDEN = ROOT / "tests/fixtures/webgame/menu-goldens.json"
SHELL_MENU_GOLDEN = (
    ROOT / "webgame-contracts/baseline-snapshots/menu-goldens.json"
)
CI = ROOT / ".github/workflows/lua-authoring-contracts.yml"
VISUAL_GATE = ROOT / "webgame-contracts/menu-visual-gate.json"
VISUAL_GATE_SOURCE = WEBGAME / "conformance/menu-visual-gate.ts"
VISUAL_GATE_TEST = WEBGAME / "conformance/menu-visual-gate.test.ts"
MENU_BASELINE = ROOT / "webgame-contracts/menu-baseline.json"
MENU_BASELINE_SOURCE = WEBGAME / "conformance/menu-baseline.ts"
KNOWN_ISSUES = ROOT / "docs/browser-rebuild-known-issues.md"
MENU_LAYOUTS = ROOT / "tests/fixtures/webgame/menu-layouts"


def _read_text(path: Path, consequence: str) -> str:
    if not path.is_file():
        raise StaticReTestFailure(consequence)
    return path.read_text(encoding="utf-8")


def _read_json(path: Path, consequence: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path, consequence))
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(f"{consequence}: {exc}") from exc
    if not isinstance(value, dict):
        raise StaticReTestFailure(consequence)
    return value


def _require_regex(text: str, pattern: str, consequence: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE | re.DOTALL) is None:
        raise StaticReTestFailure(consequence)


def _production_typescript() -> dict[str, str]:
    paths = sorted(
        path
        for directory in (INPUT, CLIENT)
        for path in directory.rglob("*.ts")
        if not path.name.endswith(".test.ts")
    )
    relative_paths = {path.relative_to(WEBGAME).as_posix() for path in paths}
    witnesses = {
        "input/intent.ts",
        "input/gamepad-producer.ts",
        "input/keyboard-mouse-producer.ts",
        "input/focus-model.ts",
        "client/app.ts",
        "client/manifest-assets.ts",
        "client/text-inputs.ts",
        "client/webgl-renderer.ts",
    }
    missing = sorted(witnesses - relative_paths)
    if missing:
        raise StaticReTestFailure(
            "browser shell source sweep did not reach architecture witness(es): "
            + ", ".join(missing)
        )
    return {
        path.relative_to(WEBGAME).as_posix(): _read_text(
            path,
            f"browser shell production source disappeared: {path.relative_to(WEBGAME)}",
        )
        for path in paths
    }


def test_webgame_shell_architecture_keeps_devices_inside_input() -> str:
    sources = _production_typescript()
    intent = sources["input/intent.ts"]
    for kind in ("MoveIntent", "AimIntent", "CastIntent", "InteractIntent", "MenuNavIntent"):
        if f"export type {kind}" not in intent:
            raise StaticReTestFailure(f"G14 runtime Intent union lost its {kind} member")
    _require_regex(
        intent,
        r"export type Intent\s*=\s*MoveIntent\s*\|\s*AimIntent\s*\|\s*CastIntent\s*\|\s*InteractIntent\s*\|\s*MenuNavIntent\s*;",
        "browser shell Intent union no longer mirrors all five G14 intent families",
    )
    if "Runtime mirror of webgame-contracts/intent-schema.json" not in intent:
        raise StaticReTestFailure(
            "runtime Intent validation no longer declares the landed G14 schema as authority"
        )

    device_patterns = {
        r"navigator\.getGamepads\(\)": "input/gamepad-producer.ts",
        r"\bGamepad\b": "input/gamepad-producer.ts",
        r"\bKeyboardEvent\b": "input/keyboard-mouse-producer.ts",
        r"\bMouseEvent\b": "input/keyboard-mouse-producer.ts",
        r"addEventListener\(\"(?:keydown|keyup|mousemove|mousedown|mouseup|contextmenu)\"":
            "input/keyboard-mouse-producer.ts",
    }
    if "navigator.getGamepads()" not in sources["input/gamepad-producer.ts"]:
        raise StaticReTestFailure(
            "device-boundary sweep lost the real browser gamepad API witness"
        )
    if "KeyboardEvent" not in sources["input/keyboard-mouse-producer.ts"]:
        raise StaticReTestFailure(
            "device-boundary sweep lost the real keyboard-event witness"
        )
    for pattern, allowed in device_patterns.items():
        offenders = sorted(
            name for name, source in sources.items()
            if name != allowed and re.search(pattern, source) is not None
        )
        if offenders:
            raise StaticReTestFailure(
                "raw input device knowledge escaped webgame/input into " + ", ".join(offenders)
            )

    app = sources["client/app.ts"]
    _require_regex(
        app,
        r"const sink = \(intent: Intent\): void => \{\s*controller\.handle\(intent\);\s*\};",
        "browser client no longer joins both device producers through the G14 Intent sink",
    )
    return "webgame/input exclusively owns raw devices and emits the five-member G14 Intent union"


def test_webgame_shell_twin_stick_and_focus_follow_landed_contracts() -> str:
    twin = _read_text(TWIN_STICK, "twin-stick producer math is absent")
    producer = _read_text(GAMEPAD, "gamepad Intent producer is absent")
    focus_source = _read_text(FOCUS, "G11 focus/navigation implementation is absent")
    text_inputs = _read_text(TEXT_INPUTS, "Deck text-entry overlay implementation is absent")

    exact_constants = (
        "export const GAMEPAD_INNER_DEADZONE = 0.2;",
        "export const GAMEPAD_OUTER_DEADZONE = 0.95;",
        "export const AIM_ANCHOR_Y_OFFSET_PX = -25;",
    )
    for token in exact_constants:
        if token not in twin:
            raise StaticReTestFailure(
                "roadmap section 4.2 deadzone/aim constants no longer match the landed table"
            )
    _require_regex(
        twin,
        r"const magnitude = Math\.min\(1,\s*\(rawMagnitude - inner\) / \(outer - inner\)\);",
        "gamepad stick magnitude is no longer radially re-normalized between inner and outer edges",
    )
    _require_regex(
        twin,
        r"return \{\s*x: projection\.projectedPlayerPx\.x,\s*y: projection\.projectedPlayerPx\.y \+ AIM_ANCHOR_Y_OFFSET_PX,\s*\};",
        "aim anchor no longer uses project(player) plus the exact negative 25 screen pixels",
    )
    _require_regex(
        producer,
        r"if \(right !== null\) \{\s*this\.#lastAimDirection = right\.direction;\s*\}\s*"
        r"[\s\S]{0,420}?if \(this\.#lastAimDirection !== null && context\.aimProjection !== undefined\) \{\s*"
        r"this\.#sink\(\{\s*kind: \"aim\",\s*point: synthesizeAimPoint\(this\.#lastAimDirection, context\.aimProjection\)",
        "right-stick release no longer holds and reprojects the last aim direction",
    )
    if re.search(r"aim.?assist", _read_text(SHELL_CONTROLLER, "shell controller is absent"), re.I):
        raise StaticReTestFailure(
            "aim assistance escaped the producer boundary into shell state"
        )

    focus = _read_json(FOCUS_GOLDEN, "landed G11 focus contract is absent or malformed")
    menu = _read_json(
        SHELL_MENU_GOLDEN,
        "immutable pre-menufix shell golden is absent or malformed",
    )
    screens = focus.get("screens")
    census = menu.get("screen_census")
    if not isinstance(screens, list) or len(screens) != 28:
        raise StaticReTestFailure("focus implementation no longer has all 28 G11 screen rules")
    if not isinstance(census, list) or "native-loader" not in census or "game-over" not in census:
        raise StaticReTestFailure(
            "focus/menu comparison did not reach native-loader and game-over census witnesses"
        )
    focus_ids = {
        screen.get("layout_id")
        for screen in screens
        if isinstance(screen, dict)
    }
    if focus_ids != set(census):
        raise StaticReTestFailure("G11 focus rules no longer match the exact 28-layout census")
    if any(
        not isinstance(screen, dict)
        or screen.get("provenance") != "DESIGN_NOT_OBSERVED"
        for screen in screens
    ):
        raise StaticReTestFailure(
            "a designed controller behavior lost its G11 DESIGN_NOT_OBSERVED provenance marker"
        )
    modal = focus.get("modal_policy")
    if not isinstance(modal, dict) or {
        "trap_focus": modal.get("trap_focus"),
        "restore_invoker_focus_on_close": modal.get("restore_invoker_focus_on_close"),
        "block_underlay_navigation": modal.get("block_underlay_navigation"),
    } != {
        "trap_focus": True,
        "restore_invoker_focus_on_close": True,
        "block_underlay_navigation": True,
    }:
        raise StaticReTestFailure(
            "designed modal focus no longer traps, blocks its underlay, and restores its invoker"
        )
    if (
        'docs/reverse-engineering/native-menus-and-boot.md' not in focus_source
        or '§ "Focus — designed controller navigation"' not in focus_source
        or focus_source.count("DESIGN_NOT_OBSERVED") < 2
    ):
        raise StaticReTestFailure(
            "focus implementation no longer cites the G11 designed-navigation section beside its DESIGN_NOT_OBSERVED branches"
        )
    _require_regex(
        text_inputs,
        r"const input = document\.createElement\(\"input\"\);\s*"
        r"input\.type = node\.id\.endsWith\(\"\.password\"\) \? \"password\" : \"text\";",
        "Deck text entry is no longer implemented with real text/password HTML input elements",
    )
    return "radial 0.2..0.95 twin sticks, projected torso aim, retained direction, 28 marked focus rules, modal restoration, and real inputs are pinned"


def test_webgame_shell_manifest_renderer_and_layout_replay_are_strict() -> str:
    sources = _production_typescript()
    app = sources["client/app.ts"]
    manifest = sources["client/manifest-assets.ts"]
    renderer = sources["client/webgl-renderer.ts"]
    render_plan = sources["client/render-plan.ts"]
    replay = _read_text(LAYOUT_REPLAY, "T2 browser-shell layout replay is absent")
    vite = _read_text(VITE, "browser-shell assetpack server is absent")

    _require_regex(
        app,
        r'import menuGoldenJson from "\.\./\.\./webgame-contracts/baseline-snapshots/menu-goldens\.json" with \{ type: "json" \};\s*'
        r'import focusModelJson from "\.\./\.\./webgame-contracts/menu-focus-model\.json" with \{ type: "json" \};',
        "browser shell no longer imports the immutable shell menu and focus recordings directly and adjacently",
    )
    copied_goldens = sorted(
        path.relative_to(WEBGAME).as_posix()
        for path in WEBGAME.rglob("*.json")
        if path.name in {"menu-goldens.json", "menu-focus-model.json"}
    )
    if copied_goldens:
        raise StaticReTestFailure(
            "browser shell contains a second mutable copy of a landed menu/focus golden: "
            + ", ".join(copied_goldens)
        )

    manifest_claims = (
        ("entry and alias both exist", "manifest lookup no longer refuses direct/alias ambiguity"),
        ("resolution is ambiguous", "manifest lookup no longer refuses alias-chain ambiguity"),
        ("missing required asset id", "missing shell art no longer hard-fails with its asset id"),
        ("assetpack shell audit did not reach any G11 layout elements", "manifest audit can now pass without checking a real menu element"),
        ("missing glyph U+", "bitmap text can now silently skip a missing manifest glyph"),
    )
    for token, consequence in manifest_claims:
        if token not in manifest:
            raise StaticReTestFailure(consequence)
    if 'loadManifestAssets(url = "/assetpack/asset-manifest.json")' not in manifest:
        raise StaticReTestFailure(
            "browser shell manifest no longer loads through the one assetpack route"
        )
    if "publicDir: false" not in vite or 'server.middlewares.use("/assetpack"' not in vite:
        raise StaticReTestFailure(
            "Vite can serve shell images outside the explicit assetpack route"
        )

    literal_image = re.compile(r"[\"'][^\"']+\.(?:png|jpe?g|gif|webp|svg)(?:\?[^\"']*)?[\"']", re.I)
    image_offenders = sorted(
        name for name, source in sources.items()
        if literal_image.search(source) is not None
    )
    if image_offenders:
        raise StaticReTestFailure(
            "production shell hard-codes image files outside manifest lookup in "
            + ", ".join(image_offenders)
        )
    _require_regex(
        renderer,
        r'canvas\.getContext\("webgl2",\s*\{[\s\S]{0,420}?preserveDrawingBuffer: true,',
        "shell renderer no longer requires a real WebGL2 canvas context",
    )
    _require_regex(
        render_plan,
        r"export const G12_LAYER_ORDER = \[\s*"
        r'"framebuffer-clear",\s*"scene-underlay",\s*"world-sorted",\s*'
        r'"scene-overdraw",\s*"screen-overlay",\s*\] as const;',
        "browser render plans no longer retain the exact five-pass G12 physical order",
    )

    replay_claims = (
        ("const POSITION_EPSILON = 0;", "T2 replay no longer declares exact zero position epsilon"),
        ("standalone.layout", "T2 replay no longer compares standalone and embedded layout copies"),
        ("assets.assertShellAssets(catalog);", "T2 replay no longer audits every shell asset through the manifest"),
        ("screens=${catalog.layouts.size}/28", "T2 replay no longer reports the complete 28-screen census"),
        ("safe_area_1280x800=1280x720+40px_top+40px_bottom", "T2 replay no longer pins the 16:10 safe area"),
    )
    for token, consequence in replay_claims:
        if token not in replay:
            raise StaticReTestFailure(consequence)
    return "the WebGL2 shell consumes canonical G11 fixtures, resolves every image/glyph through one unambiguous manifest, and replays exact layouts in G12 order"


def test_webgame_shell_controller_traversal_covers_live_graph() -> str:
    traversal = _read_text(
        CONTROLLER_TRAVERSAL,
        "controller-only G11 navigation traversal is absent",
    )
    controller = _read_text(
        SHELL_CONTROLLER,
        "sim-less shell controller is absent",
    )
    required = (
        ("new GamepadProducer", "controller traversal no longer enters through the gamepad Intent producer"),
        ("producer.sample(snapshot(index));", "controller traversal no longer presses synthetic standard-gamepad snapshots"),
        ("assert.equal(edges.size, 39", "controller traversal no longer ingests the 39-edge live G11 graph"),
        ("assert.deepEqual(\n    [...visited].sort(),\n    [...edges.keys()].sort()", "controller traversal no longer proves exact live-edge set equality"),
        ("WEBGAME_TRAVERSAL_LOG", "controller traversal no longer emits human-readable evidence"),
        ("branch resets are test setup, never edge triggers", "traversal evidence no longer distinguishes branch setup from gamepad edges"),
        (
            "G11 28-SCREEN CONTROLLER OPERABILITY CENSUS",
            "controller traversal no longer emits a human-readable all-screen operability census",
        ),
        (
            "assert.equal(expectedDefault.size, 28",
            "controller traversal no longer pins one designed default for each G11 layout",
        ),
        (
            "controller screen census did not cover the exact 28 G11 layouts",
            "controller traversal no longer proves exact all-screen census equality",
        ),
        (
            "DESIGNED skill-picker: Back ignored; Confirm -> hub-stub",
            "controller traversal no longer proves mandatory skill-picker Back and Confirm semantics",
        ),
        (
            "DESIGNED map-picker: Back -> hub-stub; Start -> visible P0 boundary",
            "controller traversal no longer proves map-picker Back and Start semantics",
        ),
        (
            "DESIGNED game-over: early Confirm ignored; armed Confirm -> hall-of-fame",
            "controller traversal no longer proves the game-over input-arm behavior",
        ),
    )
    for token, consequence in required:
        if token not in traversal:
            raise StaticReTestFailure(consequence)
    if "controller.handle(intent);" not in traversal:
        raise StaticReTestFailure(
            "synthetic gamepad traversal no longer routes emitted Intents into shell state"
        )
    if "visited.add(edgeId);" not in traversal or "traversed twice instead of exactly once" not in traversal:
        raise StaticReTestFailure(
            "controller traversal no longer makes duplicate or omitted live edges fail by name"
        )
    _require_regex(
        controller,
        r'else if \(actionId\.startsWith\("map_picker\.story\["\)\) \{\s*'
        r'this\.#selectedMap = actionId;\s*this\.#enterOutOfScope\("Gameplay and Boneyard startup are outside P0;',
        "map Start no longer terminates visibly at the explicit P0 gameplay boundary",
    )
    if "Multiplayer, rooms, hub gameplay, and Boneyard gameplay are outside P0." not in controller:
        raise StaticReTestFailure(
            "Dark Cloud Play/Edit no longer terminates visibly at the P0 multiplayer/gameplay boundary"
        )
    return "synthetic standard-gamepad Intents traverse all 39 live G11 edges, probe defaults and wrap/input seals on all 28 layouts, and end gameplay starts at visible P0 boundaries"


def test_webgame_shell_visual_waiver_is_exact_two_directional_and_self_expiring() -> str:
    gate = _read_json(VISUAL_GATE, "G11 baseline-bound visual gate is absent or malformed")
    baseline = _read_json(MENU_BASELINE, "G11 shellfix baseline manifest is absent or malformed")
    menu = _read_json(
        SHELL_MENU_GOLDEN,
        "immutable pre-menufix shell golden is absent or malformed",
    )
    settled_menu = _read_json(
        MENU_GOLDEN, "settled G11 menu golden is absent or malformed"
    )
    gate_source = _read_text(VISUAL_GATE_SOURCE, "runtime G11 visual gate validation is absent")
    baseline_source = _read_text(MENU_BASELINE_SOURCE, "runtime G11 baseline receipt validation is absent")
    unit = _read_text(VISUAL_GATE_TEST, "G11 baseline visual-gate mutation tests are absent")
    capture = _read_text(CAPTURE, "browser-shell visual evidence runner is absent")
    replay = _read_text(LAYOUT_REPLAY, "T2 G11 baseline replay runner is absent")
    known_issues = _read_text(KNOWN_ISSUES, "webgame known-issues note is absent")

    pixel_rule = (
        "Human side-by-side review at 1600x900 requires the same assetpack art "
        "at exact G11 positions; font rasterization may differ."
    )
    if set(gate) != {
        "schema",
        "pixel_rule",
        "reviewed_pass_snapshots",
        "reviewed_divergent_snapshots",
        "pending_shellfix",
    }:
        raise StaticReTestFailure(
            "menu visual gate gained an unreviewed field that could smuggle extra tolerance"
        )
    if gate.get("schema") != "solomon-dark-menu-visual-gate-v2":
        raise StaticReTestFailure("menu visual gate lost its baseline-snapshot schema")
    if gate.get("pixel_rule") != pixel_rule:
        raise StaticReTestFailure(
            "menu visual gate loosened the original same-art exact-position rule"
        )
    if set(baseline) != {
        "schema",
        "corrective",
        "baseline_snapshot_count",
        "pending_shellfix_count",
        "baseline_snapshots",
        "pending_shellfix",
        "shell_golden_snapshot",
    }:
        raise StaticReTestFailure(
            "menu baseline manifest gained an unaudited field that could weaken shell isolation"
        )
    if baseline.get("schema") != "solomon-dark-menu-baseline-v2":
        raise StaticReTestFailure("menu baseline manifest lost its versioned schema")
    if baseline.get("corrective") != "shellfix task #101":
        raise StaticReTestFailure("menu baseline manifest lost shellfix task #101 ownership")
    if (
        baseline.get("baseline_snapshot_count") != 28
        or baseline.get("pending_shellfix_count") != 29
    ):
        raise StaticReTestFailure(
            "menu baseline manifest census must remain exactly 28 snapshots and 29 pending fixtures"
        )
    shell_golden_receipt = baseline.get("shell_golden_snapshot")
    if not isinstance(shell_golden_receipt, dict) or set(
        shell_golden_receipt
    ) != {"path", "sha256", "bytes"}:
        raise StaticReTestFailure(
            "menu baseline manifest lost its exact shell golden receipt"
        )
    if shell_golden_receipt.get("path") != (
        "webgame-contracts/baseline-snapshots/menu-goldens.json"
    ):
        raise StaticReTestFailure(
            "menu baseline shell golden receipt changed path"
        )
    assert_recorded_hash_matches_file(
        shell_golden_receipt.get("sha256"),
        SHELL_MENU_GOLDEN,
        "menu shell golden snapshot",
    )
    if shell_golden_receipt.get("bytes") != SHELL_MENU_GOLDEN.stat().st_size:
        raise StaticReTestFailure(
            "menu shell golden snapshot byte count mismatch"
        )

    census = menu.get("screen_census")
    wrappers = menu.get("layouts")
    if (
        not isinstance(census, list)
        or len(census) != 28
        or "native-loader" not in census
        or "game-over" not in census
    ):
        raise StaticReTestFailure(
            "menu baseline audit did not reach the exact G11 census witnesses"
        )
    if not isinstance(wrappers, list) or len(wrappers) != 28:
        raise StaticReTestFailure(
            "menu baseline audit did not reach all 28 embedded layout records"
        )
    embedded_by_fixture: dict[str, dict[str, Any]] = {}
    for wrapper in wrappers:
        if not isinstance(wrapper, dict):
            raise StaticReTestFailure(
                "menu baseline audit encountered a malformed embedded layout wrapper"
            )
        fixture = wrapper.get("fixture")
        layout = wrapper.get("layout")
        if not isinstance(fixture, str) or not isinstance(layout, dict):
            raise StaticReTestFailure(
                "menu baseline audit cannot resolve an embedded fixture to its layout"
            )
        if fixture in embedded_by_fixture:
            raise StaticReTestFailure(
                f"menu baseline audit refuses duplicate embedded fixture candidate {fixture}"
            )
        embedded_by_fixture[fixture] = wrapper
    canonical = set(embedded_by_fixture)
    if len(canonical) != 28 or "menu-layouts/beta-notice.json" not in canonical:
        raise StaticReTestFailure(
            "menu baseline audit no longer has one unambiguous wrapper per G11 layout"
        )

    pending_expected = (
        canonical - {"menu-layouts/dark-cloud-settings.json"}
    ) | {
        "menu-overlays/dark-cloud-settings.json",
        "menu-dialog-composites/beta-notice-first-boot.json",
    }
    settled_pending = {
        str(entry["fixture"])
        for field in (
            "layouts",
            "overlay_records",
            "semantic_dialog_composite_records",
        )
        for entry in settled_menu.get(field, [])
        if isinstance(entry, dict) and isinstance(entry.get("fixture"), str)
    }
    if settled_pending != pending_expected:
        raise StaticReTestFailure(
            "settled menu state census does not equal the exact 29 pending fixtures"
        )

    def indexed(
        rows: Any, label: str, expected: set[str]
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(rows, list) or len(rows) != len(expected):
            raise StaticReTestFailure(
                f"{label} must enumerate exactly {len(expected)} named fixtures"
            )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("fixture"), str):
                raise StaticReTestFailure(f"{label} contains an unresolvable fixture receipt")
            fixture = row["fixture"]
            if fixture in result:
                raise StaticReTestFailure(f"{label} refuses ambiguous duplicate {fixture}")
            result[fixture] = row
        if set(result) != expected:
            raise StaticReTestFailure(
                f"{label} no longer covers its exact named fixture census"
            )
        return result

    snapshots = indexed(
        baseline.get("baseline_snapshots"),
        "menu baseline snapshots",
        canonical,
    )
    pending_manifest = indexed(
        baseline.get("pending_shellfix"),
        "menu baseline pending_shellfix",
        pending_expected,
    )
    if "menu-layouts/native-loader.json" not in snapshots:
        raise StaticReTestFailure("menu baseline hash sweep did not reach the native-loader witness")
    for fixture in sorted(canonical):
        snapshot = snapshots[fixture]
        expected_snapshot = f"webgame-contracts/baseline-snapshots/{fixture}"
        if snapshot.get("snapshot") != expected_snapshot:
            raise StaticReTestFailure(
                f"menu baseline snapshot path does not derive exactly from {fixture}"
            )
        if snapshot.get("corrective") != "shellfix task #101":
            raise StaticReTestFailure(f"menu baseline entry {fixture} lost shellfix task #101 ownership")
        snapshot_file = ROOT / expected_snapshot
        if snapshot.get("bytes") != snapshot_file.stat().st_size:
            raise StaticReTestFailure(f"menu baseline snapshot {fixture} byte count mismatch")
        assert_recorded_hash_matches_file(
            snapshot.get("sha256"), snapshot_file, f"menu baseline snapshot {fixture}"
        )
        standalone = _read_json(
            snapshot_file, f"cannot parse baseline G11 fixture {fixture}"
        )
        if standalone.get("header") != embedded_by_fixture[fixture].get("header") or standalone.get("layout") != embedded_by_fixture[fixture].get("layout"):
            raise StaticReTestFailure(
                f"standalone and embedded G11 recordings disagree for {fixture}"
            )
    for fixture in sorted(pending_expected):
        pending = pending_manifest[fixture]
        fixture_file = ROOT / "tests/fixtures/webgame" / fixture
        if pending.get("corrective") != "shellfix task #101":
            raise StaticReTestFailure(
                f"menu pending entry {fixture} lost shellfix task #101 ownership"
            )
        if pending.get("bytes") != fixture_file.stat().st_size:
            raise StaticReTestFailure(
                f"menu pending_shellfix fixture {fixture} byte count mismatch"
            )
        assert_recorded_hash_matches_file(
            pending.get("sha256"),
            fixture_file,
            f"menu pending_shellfix fixture {fixture}",
        )

    reviewed_pass = gate.get("reviewed_pass_snapshots")
    reviewed_divergent = gate.get("reviewed_divergent_snapshots")
    pending_visual = gate.get("pending_shellfix")
    if not isinstance(reviewed_pass, list) or len(reviewed_pass) != 18:
        raise StaticReTestFailure("menu visual gate must preserve exactly 18 pass baseline attestations")
    if not isinstance(reviewed_divergent, list) or len(reviewed_divergent) != 10:
        raise StaticReTestFailure("menu visual gate must preserve exactly 10 divergent baseline attestations")
    if not isinstance(pending_visual, list) or len(pending_visual) != 29:
        raise StaticReTestFailure("menu visual gate pending_shellfix census must remain exactly 29")

    def visual_index(rows: list[Any], label: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("fixture"), str):
                raise StaticReTestFailure(f"{label} contains an unresolvable fixture record")
            fixture = row["fixture"]
            if fixture in result:
                raise StaticReTestFailure(f"{label} refuses ambiguous duplicate {fixture}")
            result[fixture] = row
        return result

    passed_by_fixture = visual_index(reviewed_pass, "menu visual pass snapshots")
    divergent_by_fixture = visual_index(reviewed_divergent, "menu visual divergent snapshots")
    pending_by_fixture = visual_index(pending_visual, "menu visual pending_shellfix")
    if set(passed_by_fixture) & set(divergent_by_fixture) or set(passed_by_fixture) | set(divergent_by_fixture) != canonical:
        raise StaticReTestFailure(
            "menu visual gate no longer partitions the exact census into 18 pass and 10 divergent baseline attestations"
        )
    if set(pending_by_fixture) != pending_expected:
        raise StaticReTestFailure(
            "menu visual pending_shellfix no longer covers the exact settled state census"
        )
    for fixture, row in {**passed_by_fixture, **divergent_by_fixture}.items():
        if row.get("corrective") != "shellfix task #101":
            raise StaticReTestFailure(f"menu visual review {fixture} lost shellfix task #101 ownership")
        if row.get("baseline_snapshot_sha256") != snapshots[fixture].get("sha256"):
            raise StaticReTestFailure(f"menu visual review {fixture} is not bound to its baseline snapshot hash")
    for fixture, row in pending_by_fixture.items():
        if row.get("corrective") != "shellfix task #101":
            raise StaticReTestFailure(f"menu visual pending entry {fixture} lost shellfix task #101 ownership")
        if row.get("settled_fixture_sha256") != pending_manifest[fixture].get("sha256"):
            raise StaticReTestFailure(f"menu visual pending entry {fixture} pins the wrong settled fixture hash")

    for fixture, wrapper in embedded_by_fixture.items():
        reference_capture = wrapper.get("reference_capture")
        reference_sha256 = wrapper.get("reference_sha256")
        if not isinstance(reference_capture, str) or not isinstance(reference_sha256, str):
            raise StaticReTestFailure(f"visual review cannot bind {fixture} to its committed reference capture")
        assert_recorded_hash_matches_file(
            reference_sha256,
            ROOT / "webgame-contracts/baseline-snapshots" / reference_capture,
            f"G11 visual reference for {fixture}",
        )

    claims = (
        (baseline_source, "menu baseline manifest census must remain exactly 28 snapshots and 29 pending fixtures", "runtime baseline gate no longer enforces the exact manifest census"),
        (baseline_source, "menu shell golden snapshot", "runtime baseline gate no longer verifies the exact shell aggregate"),
        (baseline_source, "menu baseline snapshot ${fixture}", "runtime baseline gate no longer checks each committed snapshot receipt"),
        (baseline_source, "menu pending_shellfix fixture ${fixture}", "runtime baseline gate no longer checks each settled fixture receipt"),
        (gate_source, "menu visual gate pending_shellfix census must remain exactly 29", "runtime visual gate no longer enforces the pending-shell census"),
        (gate_source, "is not bound to its baseline snapshot hash", "runtime visual gate no longer binds reviews to snapshot bytes"),
        (gate_source, "pins the wrong settled fixture hash", "runtime visual gate no longer pins pending settled bytes"),
        (gate_source, "menu visual gate changed the original pixel-plausibility rule or added tolerance", "runtime visual gate no longer rejects extra visual tolerance"),
        (unit, "rejects a dropped pending_shellfix entry", "unit mutation no longer exercises the pending-shell census"),
        (unit, "pinned to the wrong settled fixture hash", "unit mutation no longer exercises a wrong pending hash"),
        (capture, "verifyMenuBaseline(", "live capture no longer verifies the shellfix baseline receipts"),
        (capture, "validateMenuVisualGate(menuVisualGateJson, catalog, baseline)", "live capture no longer applies the baseline-bound visual gate"),
        (capture, "visualGate: { ...visualGate, artifacts: visualArtifacts }", "live capture no longer records all visual dispositions and artifact hashes"),
        (capture, "referenceSha256 !== layout.referenceSha256", "live visual evidence no longer binds each comparison to its committed reference"),
        (replay, "const baseline = await verifyMenuBaseline(", "T2 replay no longer verifies the baseline manifest"),
        (replay, "const catalog = parseMenuCatalog(baselineEmbedded);", "T2 replay no longer compares the shell to exact baseline bytes"),
        (replay, "standalone layout diverges from the embedded G11 recording", "T2 replay no longer checks settled standalone and embedded copies agree"),
    )
    for text, token, consequence in claims:
        if token not in text:
            raise StaticReTestFailure(consequence)
    if "stale controls omitted" in json.dumps(gate) or '"waiver"' in json.dumps(gate):
        raise StaticReTestFailure("deleted stale visual-waiver machinery reappeared in the v2 gate")
    if "shellfix task #101" not in known_issues:
        raise StaticReTestFailure("webgame known-issues note no longer assigns the shell interregnum to task #101")
    return "all 28 pre-menufix layout/reference snapshots and all 29 settled pending states are hash-pinned; T2 and the visual gate remain exact against snapshot bytes until shellfix task #101"


def test_webgame_shell_boot_capture_performance_and_ci_are_wired() -> str:
    app = _read_text(APP, "browser shell boot sequence is absent")
    controller = _read_text(SHELL_CONTROLLER, "browser shell input gate is absent")
    capture = _read_text(CAPTURE, "browser-shell Chromium evidence runner is absent")
    workflow = _read_text(CI, "repository CI workflow is absent")
    package = _read_json(PACKAGE, "webgame package scripts are absent or malformed")

    _require_regex(
        app,
        r"for \(const layoutId of catalog\.screenCensus\) \{[\s\S]{0,520}?"
        r"await renderer\.prepare\(buildRenderPlan\(layout, assets, null, false\)\);\s*"
        r"completed \+= 1;\s*renderer\.render\(withLoaderProgress\(loaderPlan, completed / catalog\.screenCensus\.length\)\);",
        "Raptisoft loader progress is no longer bound directly to each real 28-layout preparation unit",
    )
    if "setTimeout(" in app:
        raise StaticReTestFailure(
            "boot loader gained a timer and is no longer purely real-work-bound"
        )
    _require_regex(
        app,
        r"canvas\.animate\(\s*\[\{ opacity: 0 \}, \{ opacity: 1 \}\],\s*"
        r'\{ duration: 1100, easing: "linear", fill: "both" \},\s*\);',
        "first title entry no longer uses the G11 1.1-second fade",
    )
    if "this.#inputGateUntil = this.#clock() + 2000;" not in controller:
        raise StaticReTestFailure(
            "first title input no longer stays gated through the G11 two-second threshold"
        )

    capture_claims = (
        ("capture port ${SERVER_PORT} is busy", "evidence runner no longer refuses an already-busy server port"),
        ("browser shell server is broken, not busy", "evidence runner no longer distinguishes a broken launch from startup work"),
        ("browser = await chromium.launch", "evidence runner no longer exercises real headless Chromium"),
        ("for (const layoutId of catalog.screenCensus)", "evidence runner no longer sweeps the landed 28-screen census"),
        ("rendered-1280x800", "evidence runner no longer captures the 1280x800 Deck-safe render set"),
        ("side-by-side", "evidence runner no longer produces native/WebGL comparisons"),
        ("measureFrameTimes(600)", "evidence runner no longer measures a sustained 600-frame sample"),
        ("sameProcessStillRuns", "evidence cleanup no longer verifies PID identity before declaring owned processes gone"),
        ("shell loaded image outside the assetpack manifest", "live capture no longer rejects image requests outside the manifest"),
    )
    for token, consequence in capture_claims:
        if token not in capture:
            raise StaticReTestFailure(consequence)

    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        raise StaticReTestFailure("webgame package no longer exposes a command map")
    expected_commands = {
        "build": "vite build",
        "conformance": "tsx conformance/run-layout-replay.ts",
        "controller-traversal": "tsx conformance/run-controller-traversal.ts",
    }
    if {name: scripts.get(name) for name in expected_commands} != expected_commands:
        raise StaticReTestFailure(
            "webgame package no longer exposes build, T2 replay, and controller traversal commands exactly"
        )
    ci_steps = (
        (
            r"^      - name: Build browser shell\n^        run: npm --prefix webgame run build$",
            "CI no longer builds the browser shell",
        ),
        (
            r"^      - name: Replay G11 browser-shell layouts\n^        run: npm --prefix webgame run conformance$",
            "CI no longer runs the exact G11 T2 layout replay",
        ),
        (
            r"^      - name: Traverse browser shell with synthetic gamepad\n^        run: npm --prefix webgame run controller-traversal$",
            "CI no longer runs the complete controller-only navigation traversal",
        ),
    )
    for pattern, consequence in ci_steps:
        _require_regex(workflow, pattern, consequence)
    return "work-bound boot, title timings, real Chromium evidence, 1280x800 600-frame measurement, exact cleanup, and three shell CI gates are wired"
