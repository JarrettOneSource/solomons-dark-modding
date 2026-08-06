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
CI = ROOT / ".github/workflows/lua-authoring-contracts.yml"
VISUAL_GATE = ROOT / "webgame-contracts/menu-visual-gate.json"
VISUAL_GATE_SOURCE = WEBGAME / "conformance/menu-visual-gate.ts"
VISUAL_GATE_TEST = WEBGAME / "conformance/menu-visual-gate.test.ts"
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
    if (WEBGAME / "sim").exists():
        raise StaticReTestFailure(
            "P0 browser shell grew webgame/sim and now implies simulation fidelity"
        )

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
    return "webgame/input exclusively owns raw devices and emits the five-member G14 Intent union; webgame/sim remains absent"


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
    menu = _read_json(MENU_GOLDEN, "landed G11 menu golden is absent or malformed")
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
        r'import menuGoldenJson from "\.\./\.\./tests/fixtures/webgame/menu-goldens\.json" with \{ type: "json" \};\s*'
        r'import focusModelJson from "\.\./\.\./webgame-contracts/menu-focus-model\.json" with \{ type: "json" \};',
        "browser shell no longer imports the landed menu and focus recordings directly and adjacently",
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
    gate = _read_json(VISUAL_GATE, "enumerated G11 visual waiver contract is absent or malformed")
    menu = _read_json(MENU_GOLDEN, "landed G11 menu golden is absent or malformed")
    source = _read_text(VISUAL_GATE_SOURCE, "runtime G11 visual waiver validation is absent")
    unit = _read_text(VISUAL_GATE_TEST, "G11 visual waiver mutation unit tests are absent")
    capture = _read_text(CAPTURE, "browser-shell visual evidence runner is absent")
    known_issues = _read_text(KNOWN_ISSUES, "webgame known-issues note is absent")

    expected_waived = {
        "menu-layouts/controls.json",
        "menu-layouts/dark-cloud-login-settings.json",
        "menu-layouts/dark-cloud-search.json",
        "menu-layouts/dark-cloud-settings.json",
        "menu-layouts/game-over.json",
        "menu-layouts/game-settings-dark-cloud.json",
        "menu-layouts/game-settings-gameplay.json",
        "menu-layouts/game-settings-title.json",
        "menu-layouts/hall-of-fame.json",
        "menu-layouts/performance.json",
    }
    expected_root_keys = {
        "schema",
        "pixel_rule",
        "reviewed_pass_fixtures",
        "reviewed_divergent_fixtures",
        "waiver",
    }
    if set(gate) != expected_root_keys:
        raise StaticReTestFailure(
            "menu visual gate gained an unreviewed field that could smuggle extra tolerance"
        )
    if gate.get("schema") != "solomon-dark-menu-visual-gate-v1":
        raise StaticReTestFailure("menu visual gate lost its versioned schema")
    pixel_rule = (
        "Human side-by-side review at 1600x900 requires the same assetpack art "
        "at exact G11 positions; font rasterization may differ."
    )
    if gate.get("pixel_rule") != pixel_rule:
        raise StaticReTestFailure(
            "menu visual gate loosened the original same-art exact-position rule"
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
            "visual waiver audit did not reach the exact G11 census witnesses"
        )
    if not isinstance(wrappers, list) or len(wrappers) != 28:
        raise StaticReTestFailure(
            "visual waiver audit did not reach all 28 embedded layout records"
        )
    embedded_by_fixture: dict[str, dict[str, Any]] = {}
    for wrapper in wrappers:
        if not isinstance(wrapper, dict):
            raise StaticReTestFailure(
                "visual waiver audit encountered a malformed embedded layout wrapper"
            )
        fixture = wrapper.get("fixture")
        layout = wrapper.get("layout")
        if not isinstance(fixture, str) or not isinstance(layout, dict):
            raise StaticReTestFailure(
                "visual waiver audit cannot resolve an embedded fixture to its layout"
            )
        if fixture in embedded_by_fixture:
            raise StaticReTestFailure(
                f"visual waiver audit refuses duplicate embedded fixture candidate {fixture}"
            )
        embedded_by_fixture[fixture] = wrapper
    if len(embedded_by_fixture) != 28:
        raise StaticReTestFailure(
            "visual waiver audit no longer has one unambiguous wrapper per G11 layout"
        )

    divergent = gate.get("reviewed_divergent_fixtures")
    passed = gate.get("reviewed_pass_fixtures")
    if not isinstance(divergent, list) or any(not isinstance(item, str) for item in divergent):
        raise StaticReTestFailure(
            "menu visual gate no longer names divergent fixtures explicitly"
        )
    if len(divergent) != len(set(divergent)) or set(divergent) != expected_waived:
        extra = sorted(set(divergent) - expected_waived)
        missing = sorted(expected_waived - set(divergent))
        if extra:
            raise StaticReTestFailure(f"unwaived visual divergence: {extra[0]}")
        raise StaticReTestFailure(
            "menu visual gate no longer enumerates exactly the ten ATC-waived fixtures: "
            + ", ".join(missing)
        )
    if not isinstance(passed, list) or any(not isinstance(item, str) for item in passed):
        raise StaticReTestFailure(
            "menu visual gate no longer names the ordinary pixel-plausible passes"
        )
    passed_set = set(passed)
    canonical_set = set(embedded_by_fixture)
    if (
        len(passed) != 18
        or len(passed_set) != 18
        or passed_set & expected_waived
        or passed_set | expected_waived != canonical_set
    ):
        raise StaticReTestFailure(
            "menu visual gate no longer partitions the exact census into 18 unchanged passes and 10 waivers"
        )

    waiver = gate.get("waiver")
    if not isinstance(waiver, dict) or set(waiver) != {"decision", "entries"}:
        raise StaticReTestFailure(
            "menu visual waiver gained scope beyond its ATC decision and enumerated entries"
        )
    if waiver.get("decision") != "ATC 2026-08-05 evening":
        raise StaticReTestFailure("menu visual waiver lost the governing ATC decision")
    entries = waiver.get("entries")
    if not isinstance(entries, list) or len(entries) != 10:
        raise StaticReTestFailure(
            "menu visual waiver no longer has exactly ten fixture-specific entries"
        )
    entries_by_fixture: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "fixture",
            "required_marker",
            "corrective",
        }:
            raise StaticReTestFailure(
                "a menu visual waiver entry can no longer be audited as fixture, marker, and corrective"
            )
        fixture = entry.get("fixture")
        if not isinstance(fixture, str):
            raise StaticReTestFailure(
                "a menu visual waiver entry no longer names its fixture"
            )
        if fixture in entries_by_fixture:
            raise StaticReTestFailure(
                f"menu visual waiver refuses duplicate candidate {fixture}"
            )
        entries_by_fixture[fixture] = entry
    if set(entries_by_fixture) != expected_waived:
        unwaived = sorted(expected_waived - set(entries_by_fixture))
        if unwaived:
            raise StaticReTestFailure(f"unwaived visual divergence: {unwaived[0]}")
        raise StaticReTestFailure(
            "menu visual waiver contains a fixture outside the exact ten-screen decision"
        )

    for fixture, entry in entries_by_fixture.items():
        if entry.get("required_marker") != "stale controls omitted":
            raise StaticReTestFailure(
                f"visual waiver does not cite the literal stale marker: {fixture}"
            )
        if entry.get("corrective") != "menufix task #97":
            raise StaticReTestFailure(
                f"visual waiver does not point {fixture} to menufix task #97"
            )
        standalone = _read_json(
            ROOT / "tests/fixtures/webgame" / fixture,
            f"visual waiver cannot read listed fixture {fixture}",
        )
        standalone_layout = standalone.get("layout")
        if not isinstance(standalone_layout, dict):
            raise StaticReTestFailure(
                f"visual waiver cannot inspect capture provenance for {fixture}"
            )
        embedded_layout = embedded_by_fixture[fixture].get("layout")
        if not isinstance(embedded_layout, dict):
            raise StaticReTestFailure(
                f"visual waiver cannot inspect embedded capture provenance for {fixture}"
            )
        standalone_method = standalone_layout.get("capture_method")
        embedded_method = embedded_layout.get("capture_method")
        if standalone_method != embedded_method:
            raise StaticReTestFailure(
                f"standalone and embedded capture provenance disagree for waived fixture {fixture}"
            )
        if (
            not isinstance(standalone_method, str)
            or "stale controls omitted" not in standalone_method
        ):
            raise StaticReTestFailure(
                f'illegal stale visual waiver: {fixture} no longer bears literal marker "stale controls omitted"; delete the waiver and pass full visual match'
            )

    for fixture in passed_set:
        layout = embedded_by_fixture[fixture].get("layout")
        if not isinstance(layout, dict):
            raise StaticReTestFailure(
                f"ordinary visual review cannot inspect capture provenance for {fixture}"
            )
        method = layout.get("capture_method")
        if not isinstance(method, str) or "stale controls omitted" in method:
            raise StaticReTestFailure(f"unwaived stale visual fixture: {fixture}")

    for fixture, wrapper in embedded_by_fixture.items():
        reference_capture = wrapper.get("reference_capture")
        reference_sha256 = wrapper.get("reference_sha256")
        if not isinstance(reference_capture, str) or not isinstance(reference_sha256, str):
            raise StaticReTestFailure(
                f"visual review cannot bind {fixture} to its committed reference capture"
            )
        assert_recorded_hash_matches_file(
            reference_sha256,
            ROOT / "tests/fixtures/webgame" / reference_capture,
            f"G11 visual reference for {fixture}",
        )

    source_claims = (
        (
            "unwaived visual divergence: ${fixture}",
            "runtime visual gate no longer names an eleventh divergent fixture",
        ),
        (
            "illegal stale visual waiver: ${entry.fixture} no longer bears literal marker",
            "runtime visual gate no longer self-expires a corrected fixture waiver",
        ),
        (
            "menu visual gate changed the original pixel-plausibility rule or added tolerance",
            "runtime visual gate no longer rejects extra visual tolerance",
        ),
    )
    for token, consequence in source_claims:
        if token not in source:
            raise StaticReTestFailure(consequence)
    unit_claims = (
        (
            "rejects an eleventh, unlisted visual divergence by fixture name",
            "unit mutation no longer exercises the unlisted-divergence direction",
        ),
        (
            "scratch recapture loses the stale marker",
            "unit mutation no longer exercises the corrected-listed-fixture direction",
        ),
    )
    for token, consequence in unit_claims:
        if token not in unit:
            raise StaticReTestFailure(consequence)
    capture_claims = (
        (
            "validateMenuVisualGate(menuVisualGateJson, catalog)",
            "live capture no longer applies the enumerated visual gate",
        ),
        (
            "visualGate: { ...visualGate, artifacts: visualArtifacts }",
            "live capture no longer records all visual dispositions and artifact hashes",
        ),
        (
            "referenceSha256 !== layout.referenceSha256",
            "live visual evidence no longer binds each comparison to its committed reference",
        ),
    )
    for token, consequence in capture_claims:
        if token not in capture:
            raise StaticReTestFailure(consequence)

    documented = set(
        re.findall(r"^- `([a-z0-9-]+)`$", known_issues, flags=re.MULTILINE)
    )
    if documented != {Path(fixture).stem for fixture in expected_waived}:
        raise StaticReTestFailure(
            "webgame known-issues note no longer lists exactly the ten waived screen names"
        )
    if (
        "menufix task #97" not in known_issues
        or "Never\nreconstruct missing geometry from a PNG" not in known_issues
    ):
        raise StaticReTestFailure(
            "webgame known-issues note no longer names the corrective or forbids PNG-derived geometry"
        )
    return "exactly ten marker-backed G11 divergences are waived toward menufix task #97; 18 screens retain the original pixel rule and both waiver directions fail closed"


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
