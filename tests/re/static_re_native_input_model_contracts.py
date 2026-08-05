"""Static contracts for the native input model and browser Intent boundary."""

from __future__ import annotations

import json

from static_re_contract_support import ROOT, StaticReTestFailure


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _require(source: str, tokens: tuple[str, ...], contract: str) -> None:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise StaticReTestFailure(
            f"{contract} is incomplete: " + ", ".join(missing)
        )


def test_native_input_ingress_sampling_and_tick_order_are_pinned() -> str:
    findings = _read("docs/reverse-engineering/native-input-model.md")
    trace = _read("SolomonDarkModLoader/src/native_input_trace.cpp")
    window = _read("SolomonDarkModLoader/src/background_focus_bypass.cpp")
    mouse = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_mouse_refresh_hook.inl"
    )
    player = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )

    _require(
        findings,
        (
            "`GameWindowProc` `0x00443440`",
            "append routine `0x00443330`",
            "queue drain `0x0040D6B0`",
            "`Input::Refresh` `0x00429820`",
            "scheduler `0x0040D3C0`",
            "fixed-step body `0x0040D1B0`",
            "`PlayerActor::Tick` `0x00548B00`",
            "The nominal fixed step is 10 ms",
        ),
        "native ingress and tick ordering",
    )
    _require(
        trace + window + mouse + player,
        (
            "kNativeInputTraceCapacity = 768",
            "kUnchangedInputSampleIntervalTicks = 10",
            "InputSampleStateChanged(",
            "ObserveNativeInputWindowMessage(",
            '"post_native_refresh"',
            "ObserveNativeInputActorPostTick(",
        ),
        "bounded read-only native input recorder",
    )
    return (
        "Win32 ingress, ordered buffering, refresh-before-actor tick, and the "
        "bounded observation-only recorder are pinned"
    )


def test_native_surface_priority_and_loading_input_seal_are_pinned() -> str:
    findings = _read("docs/reverse-engineering/native-input-model.md")
    gate_contract = _read("tests/re/static_re_ui_interaction_gate_contracts.py")
    loading_bug = _read(
        "docs/bugs/beta32-ungated-client-interactions-2026-08-04.md"
    )

    _require(
        findings,
        (
            "down `0x0040E050`",
            "up `0x0040E190`",
            "recursive hit test `0x00428620`",
            "An active captured control wins",
            "active modal root is considered before",
            "walks children in reverse insertion order",
            "There is no bubbling to a lower world surface",
            "`hud_click_swallowed`",
            "There is no native world-move click",
        ),
        "native surface priority",
    )
    _require(
        findings + gate_contract + loading_bug,
        (
            "BlockingOverlayOwnsGameplayInput()",
            "DiscardQueuedGameplayInputForBlockingOverlay();",
            "SuppressGameplayMouseForBlockingOverlay(self_address);",
            "blocked native input must be discarded",
            "dropped, never deferred",
            "loader-authored loading UI still receives",
        ),
        "loading-screen input seal",
    )
    return (
        "capture/modal/reverse-z/first-hit surface priority and the no-deferral "
        "loading seal are pinned"
    )


def test_native_action_thresholds_absences_and_intent_shape_are_pinned() -> str:
    findings = _read("docs/reverse-engineering/native-input-model.md")
    schema = json.loads(_read("webgame-contracts/intent-schema.json"))
    fixture = json.loads(
        _read("tests/fixtures/webgame/input-goldens.json")
    )

    _require(
        findings,
        (
            "zero ticks, therefore 0 ms",
            "adds `growth_rate * 0.0025`",
            "approximately `0.19375` at 120",
            "`0.25375` at 600",
            "`0.36875` at 1500",
            "Frost primary is skill `0x20`",
            "Right is raw held bit `2`",
            "No native click-to-move",
            "No complete native gamepad path",
            "No native menu focus order",
            "## Not Yet Reversed",
        ),
        "native action semantics and observed absences",
    )

    definitions = schema.get("$defs", {})
    if schema.get("$ref") != "#/$defs/intent":
        raise StaticReTestFailure("the schema root is not the Intent union")
    move = definitions["moveIntent"]["properties"]["move"]["oneOf"]
    move_types = {
        variant["properties"]["type"]["const"] for variant in move
    }
    if move_types != {"world_target", "unit_vector"}:
        raise StaticReTestFailure(f"move union drifted: {move_types}")
    if definitions["castIntent"]["properties"]["phase"]["enum"] != [
        "press",
        "hold",
        "release",
    ]:
        raise StaticReTestFailure("cast phase enum drifted")
    if definitions["nativeEncodingRecord"]["properties"]["intents"][
        "items"
    ].get("$ref") != "#/$defs/intent":
        raise StaticReTestFailure("native encoding no longer contains Intent")

    scenarios = {
        capture["header"]["scenario"] for capture in fixture["captures"]
    }
    required = {
        "click_open_ground_native_absence",
        "click_wall_native_absence",
        "tap_cast",
        "earth_charge_120ms",
        "earth_charge_600ms",
        "earth_charge_1500ms",
        "frost_channel_start_stop",
        "hud_click_swallowed",
    }
    if scenarios != required:
        raise StaticReTestFailure(f"live input scenario set drifted: {scenarios}")
    if not all(
        capture["header"]["round_trip"]["exact_equal"] is True
        for capture in fixture["captures"]
    ):
        raise StaticReTestFailure("a native golden lost exact round-trip proof")
    return (
        "Earth/Frost/right-click thresholds, native absences, the five-way "
        "Intent union, and all eight live scenarios are pinned"
    )
