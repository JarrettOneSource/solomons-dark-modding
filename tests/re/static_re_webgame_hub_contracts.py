"""Static contracts for the P1 browser hub built on the landed web shell."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from static_re_contract_support import ROOT, StaticReTestFailure


WEBGAME = ROOT / "webgame"
CLIENT = WEBGAME / "client"
HUB_CONTRACTS = CLIENT / "hub-contracts.ts"
HUB_CONTROLLER = CLIENT / "hub-controller.ts"
HUB_DATA = CLIENT / "hub-data.ts"
HUB_RENDER_PLAN = CLIENT / "hub-render-plan.ts"
HUB_SCENE = CLIENT / "hub-scene.ts"
SESSION_FLOW = CLIENT / "session-flow.ts"
APP = CLIENT / "app.ts"
MANIFEST_ASSETS = CLIENT / "manifest-assets.ts"
RENDERER = CLIENT / "webgl-renderer.ts"
HUB_REPLAY = WEBGAME / "conformance/run-hub-conformance.ts"
TRANSITION_REPLAY = WEBGAME / "conformance/run-transition-conformance.ts"
ANIMATION_REPLAY = WEBGAME / "conformance/run-animation-conformance.ts"
HUB_TRAVERSAL = WEBGAME / "conformance/run-hub-traversal.ts"
CAPTURE = WEBGAME / "scripts/capture-hub.ts"
PACKAGE = WEBGAME / "package.json"
QUALITY_FLOORS = WEBGAME / "quality-floors.json"
CI = ROOT / ".github/workflows/lua-authoring-contracts.yml"
SCENE_GOLDEN = ROOT / "tests/fixtures/webgame/scene-composition-goldens.json"
ECONOMY_GOLDEN = ROOT / "tests/fixtures/webgame/hub-economy-goldens.json"
SESSION_GOLDEN = ROOT / "tests/fixtures/webgame/session-flow-goldens.json"


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


def _require_tokens(
    text: str,
    claims: tuple[tuple[str, str], ...],
    empty_consequence: str,
) -> None:
    if not claims:
        raise StaticReTestFailure(empty_consequence)
    for token, consequence in claims:
        if token not in text:
            raise StaticReTestFailure(consequence)


def _unique_object(
    values: object,
    predicate: Any,
    consequence: str,
) -> dict[str, Any]:
    if not isinstance(values, list) or len(values) == 0:
        raise StaticReTestFailure(consequence)
    candidates = [value for value in values if isinstance(value, dict) and predicate(value)]
    if len(candidates) != 1:
        raise StaticReTestFailure(consequence)
    return candidates[0]


def _tracked_webgame_json() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "webgame"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise StaticReTestFailure(
            "P1 frozen-fixture audit could not enumerate the tracked webgame surface"
        )
    return sorted(
        path.removeprefix("webgame/")
        for path in result.stdout.decode("utf-8").split("\0")
        if path.endswith(".json")
    )


def test_webgame_hub_architecture_is_client_owned_provisional_and_sim_independent() -> str:
    required_paths = (
        HUB_CONTRACTS,
        HUB_CONTROLLER,
        HUB_DATA,
        HUB_RENDER_PLAN,
        HUB_SCENE,
        SESSION_FLOW,
        APP,
        RENDERER,
    )
    missing = [path.relative_to(WEBGAME).as_posix() for path in required_paths if not path.is_file()]
    if missing:
        raise StaticReTestFailure(
            "P1 hub architecture lost required webgame/client ownership: " + ", ".join(missing)
        )
    sources = {
        path.relative_to(WEBGAME).as_posix(): _read_text(
            path,
            f"P1 hub source disappeared: {path.relative_to(WEBGAME)}",
        )
        for path in required_paths
    }
    if set(sources) != {
        "client/app.ts",
        "client/hub-contracts.ts",
        "client/hub-controller.ts",
        "client/hub-data.ts",
        "client/hub-render-plan.ts",
        "client/hub-scene.ts",
        "client/session-flow.ts",
        "client/webgl-renderer.ts",
    }:
        raise StaticReTestFailure("P1 hub architecture sweep did not reach every named client witness")
    sim_import = re.compile(r"(?:from\s+|import\s*)[\"'][^\"']*(?:/|^)sim(?:/|[\"'])")
    offenders = sorted(name for name, source in sources.items() if sim_import.search(source))
    if offenders:
        raise StaticReTestFailure(
            "P1 hub client imported the concurrent P2 simulation boundary in " + ", ".join(offenders)
        )

    controller = sources["client/hub-controller.ts"]
    _require_tokens(
        controller,
        (
            (
                "export const PROVISIONAL_HUB_WALK_SPEED = 100;",
                "P1 shell locomotion no longer uses G1's documented 100 world-unit/s base walk speed",
            ),
            (
                "PROVISIONAL P1 SHELL movement: docs/browser-rebuild-roadmap.md P1 says",
                "P1 shell locomotion lost its explicit roadmap ownership citation",
            ),
            (
                "neither created nor imported here. The plausible 100 world-unit/s feel",
                "P1 shell locomotion now implies ownership of P2's deterministic integrator",
            ),
            (
                "is G1's documented base held-walk speed; this makes no fidelity or",
                "P1 shell locomotion lost its no-fidelity-claim boundary",
            ),
        ),
        "P1 provisional locomotion contract declared no source claims",
    )

    app = sources["client/app.ts"]
    _require_regex(
        app,
        r'if \(before\.surface\.kind === "hub-stub"\) \{\s*hub\.handle\(intent\);\s*return;\s*\}',
        "P1 input routing no longer sends G14 intents into hub shell state only while the hub owns the surface",
    )
    _require_regex(
        app,
        r'before\.surface\.layoutId === "map-picker"\s*&&\s*after\.surface\.kind === "out-of-scope"'
        r'\s*\) \{\s*controller\.showHubForConformance\(\);\s*hub\.beginRunEntry\(\);\s*\}',
        "P1 run entry no longer routes the frozen Courtyard MapPicker confirmation into the hub flow",
    )

    json_paths = _tracked_webgame_json()
    if "quality-floors.json" not in json_paths or "package.json" not in json_paths:
        raise StaticReTestFailure("P1 frozen-fixture sweep did not reach package and quality-floor witnesses")
    copied = sorted(
        name for name in json_paths
        if name.endswith((
            "scene-composition-goldens.json",
            "hub-economy-goldens.json",
            "session-flow-goldens.json",
            "animation-goldens.json",
            "menu-goldens.json",
        ))
    )
    if copied:
        raise StaticReTestFailure(
            "P1 hub contains a second mutable copy of a landed fixture: " + ", ".join(copied)
        )
    return "P1 hub production stays in webgame/client, consumes G14 intents, leaves webgame/sim independent, and labels 100-unit shell movement provisional"


def test_webgame_hub_scene_economy_animation_and_manifest_replays_are_strict() -> str:
    contracts = _read_text(HUB_CONTRACTS, "P1 canonical hub contract parser is absent")
    replay = _read_text(HUB_REPLAY, "P1 G12/G8 conformance replay is absent")
    animation = _read_text(ANIMATION_REPLAY, "P1 G4 animation conformance replay is absent")
    manifest = _read_text(MANIFEST_ASSETS, "P1 manifest-only hub lookup is absent")

    _require_regex(
        contracts,
        r'import economyGoldenJson from "\.\./\.\./tests/fixtures/webgame/hub-economy-goldens\.json" with \{ type: "json" \};\s*'
        r'import sceneGoldenJson from "\.\./\.\./tests/fixtures/webgame/scene-composition-goldens\.json" with \{ type: "json" \};\s*'
        r'import sessionGoldenJson from "\.\./\.\./tests/fixtures/webgame/session-flow-goldens\.json" with \{ type: "json" \};',
        "P1 client no longer imports the three landed hub goldens directly and adjacently",
    )

    scene = _read_json(SCENE_GOLDEN, "landed G12 scene golden is absent or malformed")
    captures = scene.get("captures")
    hub = _unique_object(
        captures,
        lambda value: isinstance(value.get("header"), dict)
        and value["header"].get("label") == "hub_camera_1000_375_final",
        "P1 G12 replay cannot resolve exactly one canonical Courtyard capture",
    )
    draws = hub.get("draws")
    if not isinstance(draws, list) or len(draws) != 1319:
        raise StaticReTestFailure("P1 G12 replay no longer reaches the complete 1,319-draw Courtyard list")
    if [draw.get("draw_order") if isinstance(draw, dict) else None for draw in draws] != list(range(1319)):
        raise StaticReTestFailure("P1 G12 replay no longer proves every exact draw-order identity")
    _require_tokens(
        replay,
        (
            (
                "assert.deepEqual(actual.worldTransform, expected.world_transform",
                "P1 T2 replay no longer compares every G12 native transform",
            ),
            (
                "assert.deepEqual(actual.blend, expected.blend",
                "P1 T2 replay no longer compares every G12 blend state",
            ),
            (
                "rendered_rects_checked=${renderedPlan.commands.length}",
                "P1 T2 replay no longer reports the rendered 1,319-rectangle check",
            ),
            (
                "delta <= HUB_SCENE_GOLDEN.epsilon.screen_pixels",
                "P1 rendered scene replay no longer enforces G12's declared pixel tolerance",
            ),
        ),
        "P1 G12 replay declared no transform or render claims",
    )

    economy = _read_json(ECONOMY_GOLDEN, "landed G8 hub economy golden is absent or malformed")
    census = economy.get("hub_entity_census")
    regions = census.get("regions") if isinstance(census, dict) else None
    if not isinstance(regions, list) or [region.get("name") for region in regions if isinstance(region, dict)] != [
        "Courtyard", "Mortuary", "Library", "StoreRoom", "Office",
    ]:
        raise StaticReTestFailure("P1 G8 replay no longer reaches the exact five ordered hub regions")
    fresh = _unique_object(
        economy.get("trader_captures"),
        lambda value: isinstance(value.get("progression_state"), dict)
        and value["progression_state"].get("id") == "fresh",
        "P1 G8 replay refuses a missing or ambiguous fresh trader capture",
    )
    fomentius = fresh.get("fomentius")
    hagatha = fresh.get("hagatha")
    rolls = fresh.get("shlorio_dowsing_rolls")
    if (
        not isinstance(fomentius, dict)
        or not isinstance(hagatha, dict)
        or not isinstance(rolls, list)
        or len(rolls) == 0
        or not isinstance(rolls[0], dict)
        or len(fomentius.get("offers", [])) != 6
        or fomentius.get("stock_count") != 12
        or len(hagatha.get("offers", [])) != 27
        or hagatha.get("stock_count") != 27
        or len(rolls[0].get("offers", [])) != 3
    ):
        raise StaticReTestFailure("P1 G8 replay lost an exact pinned Fomentius, Hagatha, or Shlorio stock table")
    _require_tokens(
        replay,
        (
            (
                "USEFUL_THYNGS_OFFERS.map(stripDisplay)",
                "P1 T2 replay no longer compares Useful Thyngs stock to the pinned G8 table",
            ),
            (
                "HAGATHA_OFFERS.map((offer) => ({",
                "P1 T2 replay no longer compares Hagatha stock to the pinned G8 table",
            ),
            (
                "SHLORIO_OFFERS.map((offer) => ({",
                "P1 T2 replay no longer compares Shlorio's pinned first inventory to G8",
            ),
            (
                "regeneration=OUT_OF_SCOPE",
                "P1 T2 replay now implies unsupported tick-seed stock regeneration",
            ),
        ),
        "P1 G8 replay declared no pinned-stock claims",
    )

    _require_tokens(
        manifest,
        (
            (
                'draws[0]?.sprite.id !== "native.framebuffer-clear"',
                "P1 asset audit can pass without the real first G12 draw witness",
            ),
            (
                "assetpack hub audit did not check every G12 draw",
                "P1 asset audit can silently skip a G12 draw",
            ),
            (
                "assetpack manifest is missing required special draw id",
                "P1 asset lookup can silently skip a missing typed G12 draw",
            ),
            (
                "special draw and sprite lookup both apply",
                "P1 asset lookup no longer refuses special/sprite ambiguity",
            ),
        ),
        "P1 manifest audit declared no fail-closed claims",
    )
    _require_tokens(
        animation,
        (
            ("idleFrames.length, 30", "P1 G4 replay no longer checks all thirty idle frames"),
            ("walkFrames.length, 100", "P1 G4 replay no longer checks all one hundred idle-walk-idle frames"),
            (
                '["absent->idle", "idle->walk", "walk->idle"]',
                "P1 G4 replay no longer checks the complete presentation locomotion sequence",
            ),
            (
                "combat_states=OUT_OF_SCOPE",
                "P1 G4 replay escaped its idle/walk-only presentation boundary",
            ),
            (
                "movement_fidelity_and_determinism=NOT_CLAIMED",
                "P1 G4 replay now implies movement fidelity or determinism",
            ),
        ),
        "P1 G4 replay declared no presentation claims",
    )
    return "P1 replays all 1,319 G12 draws, exact G8 pinned inventories, manifest-only assets, and G4 idle/walk frames from canonical fixtures"


def test_webgame_hub_session_graph_phase_order_and_fixture_timings_are_pinned() -> str:
    session = _read_text(SESSION_FLOW, "P1 G13 session-flow implementation is absent")
    replay = _read_text(TRANSITION_REPLAY, "P1 G13 transition conformance replay is absent")
    golden = _read_json(SESSION_GOLDEN, "landed G13 session-flow golden is absent or malformed")
    graph = golden.get("transition_graph")
    states = graph.get("states") if isinstance(graph, dict) else None
    edges = graph.get("edges") if isinstance(graph, dict) else None
    if not isinstance(states, list) or len(states) != 12 or not isinstance(edges, list) or len(edges) != 23:
        raise StaticReTestFailure("P1 G13 state machine no longer reaches the exact 12-state, 23-edge graph")
    edge_keys = [
        (edge.get("state"), edge.get("edge"), edge.get("destination"))
        for edge in edges
        if isinstance(edge, dict)
    ]
    if len(edge_keys) != 23 or len(set(edge_keys)) != 23 or (
        "gameplay.courtyard", "start_run", "loading.boneyard"
    ) not in edge_keys or (
        "loading.boneyard", "arena_materialized", "gameplay.arena"
    ) not in edge_keys:
        raise StaticReTestFailure("P1 G13 graph lost an unambiguous two-edge Courtyard-to-Arena path")

    _require_regex(
        session,
        r'export const G13_PHASE_ORDER = \[\s*'
        r'"fade-out endpoint",\s*"seal if entering Arena",\s*"transient participant cleanup",\s*'
        r'"slot detach",\s*"cache sleep",\s*"lifecycle unregister",\s*"publish target",\s*'
        r'"wake",\s*"attach",\s*"old-region post callback",\s*"target finalizer",\s*'
        r'"fade-in",\s*"barrier release",\s*"unseal",\s*\] as const;',
        "P1 G13 implementation no longer preserves the exact nested fourteen-phase order",
    )
    _require_tokens(
        session,
        (
            ("export const G13_FIXED_TICK_MS = 10;", "P1 G13 clock no longer uses the recorded 100 Hz tick"),
            ("export const G13_PORTAL_FADE_OUT_TICKS = 101;", "P1 G13 outgoing stock fade no longer lasts 101 ticks"),
            ("export const G13_ROOM_FADE_IN_TICKS = 41;", "P1 G13 ordinary room fade-in no longer lasts 41 ticks"),
            ("export const G13_CACHED_COURTYARD_FADE_IN_TICKS = 1;", "P1 G13 cached Courtyard fade-in no longer lasts one tick"),
            ("export const G13_ARENA_FADE_IN_TICKS = 20;", "P1 G13 Arena fade-in no longer lasts 20 ticks"),
            ("export const G13_ARENA_RELEASE_TICKS_AFTER_SEAL = 26;", "P1 G13 Arena input no longer releases 26 ticks after seal"),
            ("export const G13_SOLO_BARRIER_STABLE_MS = 250;", "P1 G13 solo exact-set barrier no longer requires 250 stable milliseconds"),
            ("export const G13_BARRIER_TIMEOUT_MS = 25_000;", "P1 G13 loading barrier lost its bounded 25-second timeout"),
        ),
        "P1 G13 timing contract declared no constants",
    )
    _require_tokens(
        replay,
        (
            (
                "implemented Library portal no longer presents the exact recorded stock fade-out duration",
                "P1 transition replay no longer compares the implemented portal fade to the fixture",
            ),
            (
                "implemented Library portal no longer presents the exact recorded 41-tick fade-in",
                "P1 transition replay no longer compares the implemented room fade to the fixture",
            ),
            (
                "implemented cached-Courtyard return no longer presents the exact recorded one-tick fade-in",
                "P1 transition replay no longer compares the implemented cached-room fade to the fixture",
            ),
            (
                "implemented Arena entry no longer holds the exact recorded 26-tick seal-to-unseal interval",
                "P1 transition replay no longer compares the implemented Arena handshake to the fixture",
            ),
            (
                "assert.equal(replays.length, 23",
                "P1 transition replay no longer executes every legal G13 graph edge",
            ),
        ),
        "P1 G13 replay declared no implementation-to-fixture comparisons",
    )
    return "P1 exposes the exact 12-state and 23-edge graph, fourteen ordered phases, stock room fades, and the solo Arena barrier at zero tick tolerance"


def test_webgame_hub_controller_traversal_covers_every_talk_purchase_and_run_boundary() -> str:
    traversal = _read_text(HUB_TRAVERSAL, "P1 controller-only hub traversal is absent")
    _require_tokens(
        traversal,
        (
            (
                "const producer = new GamepadProducer(route, () => {",
                "P1 hub traversal no longer enters through the real G14 gamepad producer",
            ),
            (
                "producer.sample(gamepad([x, y, 0, 0]));",
                "P1 hub traversal no longer walks through synthetic analog gamepad snapshots",
            ),
            (
                "HUB_NPCS.filter((candidate) => candidate.region ===",
                "P1 hub traversal no longer drives region-owned NPC talk flows",
            ),
            (
                "hub.snapshot().completedTalkFlows,\n    HUB_NPCS.map((npc) => npc.id).sort()",
                "P1 hub traversal no longer proves exact all-NPC talk-flow set equality",
            ),
            (
                "goldBefore: 698,\n          goldAfter: 548,\n          quantityBefore: 2,\n          quantityAfter: 1",
                "P1 hub traversal no longer proves the exact Useful Thyngs gold and stock ledger",
            ),
            (
                'layoutId: "map-picker"',
                "P1 run traversal no longer enters through the frozen Courtyard MapPicker",
            ),
            (
                '{ kind: "run-shell" }',
                "P1 run traversal no longer reaches the visible P2/P3 run-shell boundary",
            ),
            (
                "RUN SHELL LEFT: South triggered scripted_terminal_reset and returned to Courtyard.",
                "P1 run traversal no longer leaves the run shell through the G13 reset edge",
            ),
            (
                "WEBGAME_HUB_TRAVERSAL_LOG",
                "P1 controller-only traversal no longer emits a human-readable evidence log",
            ),
        ),
        "P1 controller traversal declared no gate claims",
    )
    _require_regex(
        traversal,
        r"hub\.snapshot\(\)\.completedSessionEdges\.slice\(-2\),\s*\[\s*"
        r'"gameplay\.courtyard --start_run--> loading\.boneyard",\s*'
        r'"loading\.boneyard --arena_materialized--> gameplay\.arena",\s*\]',
        "P1 run traversal no longer proves both nested G13 run-entry edges",
    )
    return "the real gamepad producer walks every G8 region, completes all 20 talk flows, buys the 150-gold item, and enters/leaves the run shell"


def test_webgame_hub_capture_assets_performance_provenance_and_ci_are_wired() -> str:
    capture = _read_text(CAPTURE, "P1 Chromium hub evidence runner is absent")
    package = _read_json(PACKAGE, "P1 webgame package scripts are absent or malformed")
    floors = _read_json(QUALITY_FLOORS, "P1 webgame quality floors are absent or malformed")
    workflow = _read_text(CI, "P1 repository workflow is absent")

    _require_tokens(
        capture,
        (
            (
                "two independent captures; 41 samples each; 40 consecutive byte-identical structural payloads spanning at least 2 seconds",
                "P1 capture no longer records the mandatory two-run 41/40/2-second settle rule",
            ),
            (
                "structural payload did not reproduce across two independent captures",
                "P1 capture no longer refuses a non-reproducible structural payload",
            ),
            (
                "classified more than 30 percent of its elements as animated",
                "P1 capture no longer rejects an excessive animated-element set",
            ),
            (
                "hub capture census must reach one hub, twenty NPCs, seven services, and one run shell",
                "P1 visual evidence no longer names its exact 29-surface census",
            ),
        ),
        "P1 capture declared no settle or surface-census claims",
    )
    _require_tokens(
        capture,
        (
            (
                "hub loaded asset outside the assetpack manifest",
                "P1 live asset audit can accept a request outside the manifest",
            ),
            (
                "JSON.stringify([0, 40, 1280, 720])",
                "P1 capture no longer enforces the exact 1280x800 16:10 safe area",
            ),
            (
                "measureFrameTimes(600)",
                "P1 capture no longer measures a sustained 600-frame live hub sample",
            ),
            (
                "framesPerSecond < 58 || performanceReport.p95Ms > 20.5",
                "P1 capture no longer fails a machine run outside its 60 fps frame budget",
            ),
            (
                'deckHardwareGate: "OPEN"',
                "P1 capture no longer records the Steam Deck hardware gate honestly open",
            ),
        ),
        "P1 capture declared no asset, safe-area, performance, or Deck claims",
    )
    _require_tokens(
        capture,
        (
            (
                "hub capture port ${SERVER_PORT} is busy; refusing to attach to an unowned server",
                "P1 capture no longer distinguishes an already-busy port from its own server",
            ),
            (
                "hub capture server is broken, not busy",
                "P1 capture no longer distinguishes a broken server launch from startup work",
            ),
            (
                "sameProcessStillRuns",
                "P1 capture cleanup no longer verifies executable and command identity before declaring a PID gone",
            ),
            (
                '["rev-parse", "HEAD"]',
                "P1 capture no longer derives its own source SHA from Git",
            ),
            (
                '["status", "--porcelain=v1", "--untracked-files=all"]',
                "P1 capture no longer derives and rejects dirty source provenance",
            ),
        ),
        "P1 capture declared no runnable-probe, ownership, or provenance claims",
    )

    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        raise StaticReTestFailure("P1 webgame package no longer exposes a command map")
    expected_scripts = {
        "animation-conformance": "tsx conformance/run-animation-conformance.ts",
        "hub-conformance": "tsx conformance/run-hub-conformance.ts",
        "hub-traversal": "tsx conformance/run-hub-traversal.ts",
        "transition-conformance": "tsx conformance/run-transition-conformance.ts",
    }
    if {name: scripts.get(name) for name in expected_scripts} != expected_scripts:
        raise StaticReTestFailure("P1 package no longer exposes all four exact hub gate commands")
    minimum_floors = {
        "lintFiles": 89,
        "typecheckedFiles": 86,
        "unitTestFiles": 26,
        "unitTests": 99,
    }
    if set(floors) != set(minimum_floors) or any(
        not isinstance(floors[name], int) or floors[name] < minimum
        for name, minimum in minimum_floors.items()
    ):
        raise StaticReTestFailure("P1 webgame quality floors no longer match the measured final workspace")
    ci_steps = (
        (
            r"^      - name: Replay P1 hub scene and economy\n^        run: npm --prefix webgame run hub-conformance$",
            "CI no longer replays exact P1 G12/G8 hub conformance",
        ),
        (
            r"^      - name: Replay P1 wizard presentation\n^        run: npm --prefix webgame run animation-conformance$",
            "CI no longer replays P1 G4 wizard presentation",
        ),
        (
            r"^      - name: Replay P1 session transitions\n^        run: npm --prefix webgame run transition-conformance$",
            "CI no longer replays P1 G13 transition conformance",
        ),
        (
            r"^      - name: Traverse P1 hub with synthetic gamepad\n^        run: npm --prefix webgame run hub-traversal$",
            "CI no longer runs the complete P1 controller-only hub walkthrough",
        ),
    )
    if len(ci_steps) != 4:
        raise StaticReTestFailure("P1 CI contract did not enumerate all four hub gate witnesses")
    for pattern, consequence in ci_steps:
        _require_regex(workflow, pattern, consequence)
    return "two-run settled 29-surface captures, manifest-only assets, 1280x800 600-frame timing, exact provenance, ratcheted floors, and four CI gates are wired"
