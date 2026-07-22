"""Runtime behavior and application-thread ownership contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

from static_re_contract_support import (
    DEBUG_UI_OVERLAY_FRAME_RENDER,
    MULTIPLAYER_SERVICE_LOOP,
    ROOT,
    StaticReTestFailure,
    read_source_unit,
    read_text,
)

def test_semantic_air_damage_quantum_uses_authoritative_total() -> str:
    from verify_multiplayer_battle_siege_behavior_sync import (
        estimate_fundamental_damage_quantum,
    )

    cases = (
        ([0.08] * 20, 1.72, 0.04, 43.0),
        ([0.05] * 20, 1.025, 0.025, 41.0),
    )
    for samples, authoritative_damage, expected_quantum, expected_multiple in cases:
        result = estimate_fundamental_damage_quantum(
            samples,
            authoritative_damage=authoritative_damage,
        )
        if not math.isclose(
            float(result["quantum"]), expected_quantum, abs_tol=1e-9
        ) or not math.isclose(
            float(result["authoritative_multiple"]),
            expected_multiple,
            abs_tol=1e-9,
        ):
            raise StaticReTestFailure(
                "semantic Air damage quantum did not use authoritative HP loss "
                f"to reject bundled half-hit candidates: {result}"
            )
    return "semantic Air damage estimation resolves bundled claims against authoritative HP loss"


def test_mindstar_semantic_spell_projection_ignores_raw_storage_tail() -> str:
    from verify_multiplayer_mindstar_behavior_sync import (
        compact_native_output_buffer,
        compact_spell,
    )

    semantic_spell = {
        "resolved": True,
        "build_skill_id": 0x3F3,
        "current_spell_id": 0x3F3,
        "progression_level": 4,
        "logical_output_count": 2,
        "outputs": [4140.0, 370.0],
        "damage": 4140.0,
        "secondary_damage": 0.0,
        "secondary_damage_available": False,
        "mana_cost": 370.0,
        "mana_cost_available": True,
        "mana_spend_cost": 37.0,
        "mana_spend_cost_available": True,
        "mana_output_scale": 10.0,
        "mana_output_scaled": True,
        "builder_seh_code": 0,
        "error": "",
    }
    owner = {
        "spell": {
            **semantic_spell,
            "raw_output_count": 2,
            "raw_outputs": [4140.0, 370.0],
        }
    }
    observer = {
        "spell": {
            **semantic_spell,
            "raw_output_count": 9,
            "raw_outputs": [4140.0, 370.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
    }
    if compact_spell(owner) != compact_spell(observer):
        raise StaticReTestFailure(
            "Mindstar semantic parity still treats a grow-only raw tail as spell state"
        )
    if compact_native_output_buffer(owner) == compact_native_output_buffer(observer):
        raise StaticReTestFailure(
            "Mindstar raw-buffer diagnostics did not preserve the 2-versus-9 repro"
        )

    owner_projection = compact_spell(owner)
    for field, value in owner_projection.items():
        changed = {**semantic_spell}
        if isinstance(value, bool):
            changed[field] = not value
        elif isinstance(value, int):
            changed[field] = value + 1
        elif isinstance(value, float):
            changed[field] = value + 0.5
        else:
            changed[field] = value + "changed"
        changed_view = {
            "spell": {
                **changed,
                "raw_output_count": 9,
                "raw_outputs": observer["spell"]["raw_outputs"],
            }
        }
        if compact_spell(owner) == compact_spell(changed_view):
            raise StaticReTestFailure(
                f"Mindstar semantic projection omitted identity field {field}"
            )
    return (
        "Mindstar ignores grow-only raw output tails while preserving every "
        "resolved spell identity field"
    )


def test_regenerate_behavior_traces_stock_native_heal_updates() -> str:
    verifier_text = read_text(
        ROOT / "tools/verify_multiplayer_regenerate_behavior_sync.py"
    )
    required_tokens = (
        'NATIVE_REGENERATE_HEAL_INSTRUCTION = read_runtime_layout_offset(',
        '"regenerate_heal_instruction"',
        'RUNTIME_FRAME_RATE_GLOBAL = read_runtime_layout_offset(',
        '"game_timing_scale"',
        'PROGRESSION_HEALTH_REGEN_OFFSET = read_runtime_layout_offset(',
        '"progression_health_regeneration"',
        'NATIVE_HEAL_NUMERATOR = 1.5',
        'NATIVE_BASE_HEAL_DIVISOR = 10.0',
        "sd.events.on('runtime.tick', function(event)",
        "sd.debug.trace_function(",
        "sd.debug.get_trace_hits(monitor.trace_name)",
        "tonumber(hit.esi) == progression",
        "base_heal / (frame_rate * monitor.base_heal_divisor)",
        "def ensure_vital_monitor_registered(",
        "def start_vital_monitor(",
        "def collect_vital_monitor(",
        "concurrent.futures.ThreadPoolExecutor(max_workers=2)",
        '"observer": executor.submit(',
        '"owner": executor.submit(',
        '"owner_native_heal_updates"',
        '"owner_heal_per_native_update"',
        '"expected_heal_per_native_update"',
        "OWNER_OBSERVER_HP_ENVELOPE = 1.05",
        "post_active_convergence = wait_for_vitals(",
        '"post_active_convergence": post_active_convergence',
    )
    missing = [token for token in required_tokens if token not in verifier_text]
    if missing:
        raise StaticReTestFailure(
            "Regenerate native-update verification is missing token(s): "
            + ", ".join(missing)
        )
    forbidden_tokens = (
        "EXPECTED_NATIVE_HEAL_PER_SECOND",
        "EXPECTED_NATIVE_HEAL_PER_TICK",
        "fallback_ms",
    )
    present_forbidden = [
        token for token in forbidden_tokens if token in verifier_text
    ]
    if present_forbidden:
        raise StaticReTestFailure(
            "Regenerate verification retained guessed cadence/fallback token(s): "
            + ", ".join(present_forbidden)
        )

    sample_start = verifier_text.find("def sample_vitals_for(")
    sample_end = verifier_text.find(
        "\ndef assert_regenerate_inactive(", sample_start
    )
    sample_body = verifier_text[sample_start:sample_end]
    if (
        sample_start == -1
        or sample_end == -1
        or "query_persistent_status(" in sample_body
    ):
        raise StaticReTestFailure(
            "Regenerate sampling must stay in-process instead of depressing the "
            "game tick rate with repeated cross-process Lua queries"
        )

    return (
        "Regenerate behavior traces the stock heal instruction and validates "
        "each native update against the live frame-rate divisor"
    )


def test_steam_rush_reuses_strict_prepared_matrix() -> str:
    behavior_text = read_text(
        ROOT / "tools/verify_multiplayer_rush_behavior_sync.py"
    )
    steam_text = read_text(
        ROOT / "tools/verify_steam_friend_active_pair_rush.py"
    )
    required_behavior_tokens = (
        "def run_prepared_rush_matrix(",
        'output["real_keyboard_baseline"]',
        'output["real_keyboard_upgraded"]',
        "COMBINED_MAX_SPEED_MULTIPLIER",
        "minimum_ranked_rush_step_ratio",
    )
    required_steam_tokens = (
        "require_shared_test_run(output[\"pair\"])",
        "configure_behavior_context(pair)",
        "rush.load_native_rush_evidence(",
        "real_input_control.windows_process_id(HOST_INSTANCE)",
        "hold_proton_key",
        "resolve_keyboard_drivers()",
        "rush.run_prepared_rush_matrix(",
    )
    missing = [
        token
        for token in required_behavior_tokens
        if token not in behavior_text
    ] + [token for token in required_steam_tokens if token not in steam_text]
    if missing:
        raise StaticReTestFailure(
            "Steam Rush behavior verification is missing token(s): "
            + ", ".join(missing)
        )
    if "launch_pair(" in steam_text or "stop_games(" in steam_text:
        raise StaticReTestFailure(
            "Steam Rush verification must consume the genuine active friend pair "
            "without a local-transport launch or fallback"
        )

    main_start = behavior_text.find("def main() -> int:")
    main_body = behavior_text[main_start:]
    if main_body.count("run_prepared_rush_matrix(") != 1:
        raise StaticReTestFailure(
            "the standalone Rush entry point must call the shared strict matrix "
            "exactly once instead of duplicating its behavior assertions"
        )

    return "Windows/Proton Steam Rush verification reuses the strict native-evidence and real-input matrix"


def test_semantic_ui_actions_dispatch_only_on_app_update_thread() -> str:
    layout_text = read_text(ROOT / "config/binary-layout.ini")
    layout_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/binary_layout.h"
    )
    layout_parser_text = read_text(
        ROOT / "SolomonDarkModLoader/src/binary_layout_parser.cpp"
    )
    layout_validation_text = read_text(
        ROOT / "SolomonDarkModLoader/src/binary_layout_validation.cpp"
    )
    action_helpers_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions_helpers.inl"
    )
    request_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions_requests_and_reset.inl"
    )
    owner_resolution_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions_surface_owner_resolution.inl"
    )
    tracked_surfaces_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/debug_ui_overlay/tracked_surfaces_and_main_menu.inl"
    )
    overlay_source_text = read_source_unit(
        ROOT / "SolomonDarkModLoader/src/debug_ui_overlay.cpp"
    )
    overlay_frame_text = read_text(DEBUG_UI_OVERLAY_FRAME_RENDER)
    public_actions_text = read_text(
        ROOT / "SolomonDarkModLoader/src/debug_ui_overlay/public_api_actions.inl"
    )
    background_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/background_focus_bypass.cpp"
    )
    onboarding_text = read_text(ROOT / "tools/drive_steam_friend_active_pair.py")

    stale_timing_owners = [
        name
        for name, text in (
            ("binary layout", layout_text),
            ("binary layout declarations", layout_header_text),
            ("binary layout parser", layout_parser_text),
            ("binary layout validation", layout_validation_text),
            ("semantic action helpers", action_helpers_text),
            ("semantic action request path", request_text),
        )
        if "dispatch_timing" in text or "ResolveUiActionDispatchTiming" in text
    ]
    if stale_timing_owners:
        raise StaticReTestFailure(
            "semantic UI dispatch still exposes selectable thread ownership in: "
            + ", ".join(stale_timing_owners)
        )

    required_pairs = (
        (request_text, "void DispatchPendingSemanticUiActionRequest()"),
        (
            public_actions_text,
            "DispatchPendingSemanticUiActionRequest();",
        ),
        (background_tick_text, "DispatchPendingDebugUiActionOnAppTick();"),
        (
            request_text,
            "Debug UI overlay dispatched semantic UI action on the app update thread.",
        ),
        (overlay_source_text, "kPendingSemanticUiActionRequestMaximumAgeMs = 3000"),
        (request_text, "request.snapshot_generation = snapshot_generation;"),
        (request_text, "snapshot.generation != request.snapshot_generation"),
        (request_text, "TryCopyUsableDebugUiSurfaceSnapshot(&snapshot)"),
        (public_actions_text, "snapshot->snapshot_generation = pending.snapshot_generation;"),
        (owner_resolution_text, "TryResolveValidatedUiOwnerPointer("),
        (owner_resolution_text, "snapshot_owner_address != validated_owner_address"),
        (owner_resolution_text, "TryGetCurrentSpellPicker(&candidate_owner_address)"),
        (tracked_surfaces_text, "*browser_address = tracked_browser.tracked_object_ptr;"),
        (onboarding_text, "run_entry_dispatched = False"),
        (onboarding_text, "if exercise_last_game_redirect:"),
        (
            onboarding_text,
            'elif "main_menu.new_game" in available:',
        ),
        (onboarding_text, 'host_view.get("scene") == "testrun"'),
        (onboarding_text, 'host_view.get("local.in_run") == "true"'),
        (
            onboarding_text,
            'local_sync.wait_for_scene(CLIENT_ENDPOINT, "testrun", timeout=45.0)',
        ),
        (onboarding_text, '"rejoined_active_run": True'),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "app-thread semantic UI dispatch regression is missing token(s): "
            + ", ".join(missing)
        )

    forbidden_render_or_caller_thread_dispatch = (
        "DispatchPendingSemanticUiActionRequest(",
        "TryDispatchSemanticUiActionRequestImmediately",
        '"overlay_frame"',
        '"render thread"',
    )
    stale_render_tokens = [
        token
        for token in forbidden_render_or_caller_thread_dispatch
        if token in overlay_frame_text
        or token == "TryDispatchSemanticUiActionRequestImmediately"
        and token in request_text
    ]
    if stale_render_tokens:
        raise StaticReTestFailure(
            "semantic UI mutation still has a render/caller-thread path: "
            + ", ".join(stale_render_tokens)
        )

    pump = background_tick_text.find("DispatchPendingDebugUiActionOnAppTick();")
    stock_tick = background_tick_text.find("original(app, edx);", pump)
    if pump == -1 or stock_tick == -1 or pump > stock_tick:
        raise StaticReTestFailure(
            "pending update-owned UI actions must run before the stock MyApp update loop"
        )

    new_game_choice = onboarding_text.find(
        'elif "main_menu.new_game" in available:'
    )
    redirect_opt_in = onboarding_text.find("if exercise_last_game_redirect:")
    resume_choice = onboarding_text.find(
        'action = ("main_menu.resume_last_game", "main_menu")', redirect_opt_in
    )
    if not 0 <= redirect_opt_in < resume_choice < new_game_choice:
        raise StaticReTestFailure(
            "connected onboarding must select native New Game by default and isolate Last Game to its regression flag"
        )

    claim = request_text.find(
        "g_debug_ui_overlay_state.pending_semantic_ui_action = "
        "PendingSemanticUiActionRequest{};",
    )
    dispatch_entry = request_text.find("void DispatchPendingSemanticUiActionRequest()")
    if dispatch_entry == -1 or claim == -1 or dispatch_entry > claim:
        raise StaticReTestFailure(
            "the app-thread dispatcher must claim pending semantic UI actions"
        )

    expiry_check = request_text.find(
        "now - request.queued_at > kPendingSemanticUiActionRequestMaximumAgeMs",
        claim,
    )
    generation_check = request_text.find(
        "snapshot.generation != request.snapshot_generation",
        claim,
    )
    if not 0 <= claim < expiry_check < generation_check:
        raise StaticReTestFailure(
            "the app-thread dispatcher must claim, expire, and generation-check every queued UI request"
        )

    forbidden_stale_owner_paths = (
        "*owner_address = snapshot_owner_address",
        "pending_skips_snapshot_match",
    )
    stale_owner_tokens = [
        token
        for token in forbidden_stale_owner_paths
        if token in request_text or token in owner_resolution_text
    ]
    if stale_owner_tokens:
        raise StaticReTestFailure(
            "semantic UI dispatch still contains a stale-observation escape hatch: "
            + ", ".join(stale_owner_tokens)
        )

    return (
        "all semantic UI mutation is queued, generation-bound, expiry-bounded, "
        "and live-owner-validated on the app thread"
    )


def test_debug_ui_frame_render_does_not_log_each_snapshot_generation() -> str:
    overlay_source_text = "\n".join(
        (
            read_text(ROOT / "SolomonDarkModLoader/src/debug_ui_overlay.cpp"),
            read_text(
                ROOT
                / "SolomonDarkModLoader/src/debug_ui_overlay/dialog_tracking_and_snapshots_snapshot_render.inl"
            ),
            read_text(
                ROOT
                / "SolomonDarkModLoader/src/debug_ui_overlay/dialog_tracking_and_snapshots_observation.inl"
            ),
            read_text(
                ROOT
                / "SolomonDarkModLoader/src/debug_ui_overlay/label_resolution_surface_registry_and_frame_render.inl"
            ),
            read_text(
                ROOT
                / "SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions_requests_and_reset.inl"
            ),
        )
    )
    forbidden_generation_diagnostics = (
        "Debug UI semantic snapshot update:",
        "Debug UI overlay drew bbox generation=",
        "Debug UI overlay cleared bbox surface after generation=",
        "last_logged_overlay_draw_generation",
        "last_logged_overlay_clear_generation",
        "BuildDebugUiSnapshotLabelSummary",
    )
    present = [
        token
        for token in forbidden_generation_diagnostics
        if token in overlay_source_text
    ]
    if present:
        raise StaticReTestFailure(
            "debug UI render still formats or writes generation diagnostics on "
            "the frame path: "
            + ", ".join(present)
        )

    required_transition_diagnostics = (
        "Debug UI overlay rendered its first ",
        "Debug UI overlay observed ",
    )
    missing = [
        token
        for token in required_transition_diagnostics
        if token not in overlay_source_text
    ]
    if missing:
        raise StaticReTestFailure(
            "debug UI lost bounded first-frame diagnostics: " + ", ".join(missing)
        )

    return "debug UI frame rendering keeps bounded startup diagnostics without generation log flooding"


def test_main_thread_work_pump_is_not_render_owned() -> str:
    background_tick_text = read_text(
        ROOT / "SolomonDarkModLoader/src/background_focus_bypass.cpp"
    )
    internal_header_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_internal.h"
    )
    public_api_text = read_text(
        ROOT / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api.inl"
    )
    public_pump_path = (
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_main_thread_pump.inl"
    )
    if not public_pump_path.exists():
        raise StaticReTestFailure(
            "main-thread gameplay/Lua work needs a public app-tick pump seam"
        )
    public_pump_text = read_text(public_pump_path)
    keyboard_injection_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
    )
    pump_loop_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    runtime_request_state_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    player_tick_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
    )
    gameplay_dispatch_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl"
    )
    actor_lifecycle_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    d3d_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/d3d9_end_scene_hook.h"
    )
    d3d_source_text = read_text(
        ROOT / "SolomonDarkModLoader/src/d3d9_end_scene_hook.cpp"
    )

    required_pairs = (
        (internal_header_text, "void PumpGameplayMainThreadWork();"),
        (
            public_api_text,
            '#include "public_api_main_thread_pump.inl"',
        ),
        (public_pump_text, "void PumpGameplayMainThreadWork()"),
        (public_pump_text, "if (!g_gameplay_keyboard_injection.initialized)"),
        (public_pump_text, "PumpQueuedGameplayActions();"),
        (background_tick_text, "PumpGameplayMainThreadWork();"),
        (pump_loop_text, "AppMainTick and HookPlayerActorTick"),
        (pump_loop_text, "TryResolvePlayerActorForSlot("),
        (pump_loop_text, "&local_player_actor_address"),
        (pump_loop_text, "generation_before == generation_after"),
        (pump_loop_text, "generation_after != previously_observed_generation"),
        (pump_loop_text, "tick_scene_address == active_gameplay_address"),
        (pump_loop_text, "tick_actor_address == local_player_actor_address"),
        (
            pump_loop_text,
            "creation publishes a game object and a slot-zero preview actor",
        ),
        (
            runtime_request_state_text,
            "void PublishLocalPlayerTickOwnership(",
        ),
        (
            runtime_request_state_text,
            "void ClearLocalPlayerTickOwnership()",
        ),
        (
            runtime_request_state_text,
            "void ResetLocalPlayerTickOwnershipState()",
        ),
        (player_tick_text, "PublishLocalPlayerTickOwnership("),
        (gameplay_dispatch_text, "ClearLocalPlayerTickOwnership();"),
        (actor_lifecycle_text, "ClearLocalPlayerTickOwnership();"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "app-tick main-thread work ownership is missing token(s): "
            + ", ".join(missing)
        )

    main_pump = background_tick_text.find("PumpGameplayMainThreadWork();")
    ui_dispatch = background_tick_text.find(
        "DispatchPendingDebugUiActionOnAppTick();",
        main_pump,
    )
    stock_tick = background_tick_text.find("original(app, edx);", ui_dispatch)
    if (
        main_pump == -1
        or ui_dispatch == -1
        or stock_tick == -1
        or not main_pump < ui_dispatch < stock_tick
    ):
        raise StaticReTestFailure(
            "MyApp tick must pump queued main-thread work, dispatch resulting UI "
            "actions, then enter the stock update loop"
        )

    render_owned_tokens = (
        "D3d9FrameActionPump",
        "SetD3d9FrameActionPump",
        "g_action_pump",
    )
    render_owned_text = (
        d3d_header_text
        + d3d_source_text
        + keyboard_injection_text
    )
    stale = [token for token in render_owned_tokens if token in render_owned_text]
    if stale:
        raise StaticReTestFailure(
            "D3D EndScene must remain presentation-only; stale work-pump token(s): "
            + ", ".join(stale)
        )

    forbidden_ownership_heuristics = (
        "kLocalPlayerTickOwnershipFreshnessMs",
        "last_local_player_tick_ms",
        "now_ms - last_local_player_tick_ms",
    )
    present_heuristics = [
        token
        for token in forbidden_ownership_heuristics
        if token in pump_loop_text or token in runtime_request_state_text
    ]
    if present_heuristics:
        raise StaticReTestFailure(
            "main-thread Lua ownership still uses wall-clock freshness "
            "heuristics: " + ", ".join(present_heuristics)
        )

    return "main-thread Lua/menu work is app-tick owned and D3D EndScene remains presentation-only"


def test_steam_io_is_service_thread_owned_and_gameplay_application_is_app_thread_owned() -> str:
    service_loop_text = read_text(MULTIPLAYER_SERVICE_LOOP)
    service_loop_header_text = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_service_loop.h"
    )
    steam_gameplay_queue_text = read_text(
        ROOT / "SolomonDarkModLoader/src/multiplayer_steam_gameplay_queue.cpp"
    )
    local_transport_public_api_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl"
    )
    outgoing_packet_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/outgoing_packet_sync.inl"
    )
    public_pump_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_main_thread_pump.inl"
    )
    run_exit_reentry_verifier_text = read_text(
        ROOT / "tools/verify_steam_friend_run_exit_reentry.py"
    )

    service_thread_start = service_loop_text.find("void ServiceThreadMain()")
    service_thread_end = service_loop_text.find(
        "\n}  // namespace",
        service_thread_start,
    )
    if service_thread_start == -1 or service_thread_end == -1:
        raise StaticReTestFailure("multiplayer service-thread body is unavailable")
    service_thread_body = service_loop_text[
        service_thread_start:service_thread_end
    ]
    forbidden_service_thread_calls = (
        "TickLocalTransport(",
    )
    stale_calls = [
        token
        for token in forbidden_service_thread_calls
        if token in service_thread_body
    ]
    if stale_calls:
        raise StaticReTestFailure(
            "native gameplay work still runs on the Steam service thread: "
            + ", ".join(stale_calls)
        )

    required_pairs = (
        (
            service_loop_header_text,
            "void TickGameplayTransportOnAppThread(std::uint64_t now_ms);",
        ),
        (service_loop_text, "g_session_transport_lifecycle_mutex"),
        (service_thread_body, "SteamBootstrapTick();"),
        (service_thread_body, "TickSteamSession(now_ms);"),
        (service_thread_body, "ServiceSteamGameplaySendQueue();"),
        (service_loop_text, "void TickGameplayTransportOnAppThread"),
        (public_pump_text, "multiplayer::TickGameplayTransportOnAppThread("),
        (local_transport_public_api_text, "void ApplyQueuedSteamGameplayEvents("),
        (local_transport_public_api_text, "ApplyQueuedSteamGameplayEvents(now_ms);"),
        (local_transport_public_api_text, "QueueSteamGameplayPeerConnected("),
        (local_transport_public_api_text, "QueueSteamGameplayPeerDisconnected("),
        (local_transport_public_api_text, "QueueSteamGameplayPacketReceived("),
        (outgoing_packet_text, "QueueSteamGameplayPacketSend("),
        (steam_gameplay_queue_text, "void ServiceSteamGameplaySendQueue()"),
        (run_exit_reentry_verifier_text, 'PAIR_BACKEND == "wsl"'),
        (
            run_exit_reentry_verifier_text,
            'PAIR_BACKEND == "remote-windows-host"',
        ),
        (run_exit_reentry_verifier_text, "remote_windows_process_id()"),
        (run_exit_reentry_verifier_text, "pause_menu.leave_game"),
        (run_exit_reentry_verifier_text, "drive_pair_to_hub"),
        (run_exit_reentry_verifier_text, "after_processes != initial_processes"),
        (run_exit_reentry_verifier_text, "new_crash_artifacts(started_at, instances)"),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "split Steam/gameplay thread ownership is missing token(s): "
            + ", ".join(missing)
        )

    app_tick_call = public_pump_text.find(
        "multiplayer::TickGameplayTransportOnAppThread("
    )
    gameplay_injection_guard = public_pump_text.find(
        "if (!g_gameplay_keyboard_injection.initialized)"
    )
    if (
        app_tick_call == -1
        or gameplay_injection_guard == -1
        or app_tick_call > gameplay_injection_guard
    ):
        raise StaticReTestFailure(
            "queued gameplay transport must tick from AppMainTick even when "
            "gameplay injection is unavailable"
        )

    app_tick_definition = service_loop_text.find(
        "void TickGameplayTransportOnAppThread"
    )
    app_tick_end = service_loop_text.find(
        "\nbool IsServiceLoopRunning()",
        app_tick_definition,
    )
    if app_tick_definition == -1 or app_tick_end == -1:
        raise StaticReTestFailure("app-thread gameplay transport body is unavailable")
    app_tick_body = service_loop_text[app_tick_definition:app_tick_end]
    transport_tick = service_loop_text.find(
        "TickLocalTransport(now_ms);",
        app_tick_definition,
    )
    forbidden_app_thread_steam_calls = (
        "SteamBootstrapTick(",
        "TickSteamSession(",
        "SteamSendNetworkMessage(",
        "SteamReceiveNetworkMessages(",
    )
    present_app_thread_calls = [
        token for token in forbidden_app_thread_steam_calls if token in app_tick_body
    ]
    if transport_tick == -1 or present_app_thread_calls:
        raise StaticReTestFailure(
            "AppMainTick must apply queued gameplay without calling Steam directly: "
            + ", ".join(present_app_thread_calls)
        )

    if "SteamSendNetworkMessage(" in outgoing_packet_text:
        raise StaticReTestFailure(
            "gameplay packet production still calls Steam on the game thread"
        )
    submit_start = local_transport_public_api_text.find(
        "bool SubmitSteamGameplayPacket("
    )
    submit_end = local_transport_public_api_text.find(
        "\nbool ApplySteamGameplayPacketReceived(",
        submit_start,
    )
    if submit_start == -1 or submit_end == -1:
        raise StaticReTestFailure("Steam gameplay packet submission body is unavailable")
    if "DispatchReceivedPacket(" in local_transport_public_api_text[submit_start:submit_end]:
        raise StaticReTestFailure(
            "the Steam service thread still dispatches gameplay packets into native state"
        )

    return (
        "one service thread owns blocking Steam I/O while AppMainTick applies queued "
        "gameplay packets and native state"
    )


def test_participant_native_state_is_owned_by_current_scene() -> str:
    snapshot_types_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/core/participant_snapshot_types.inl"
    )
    scene_context_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/scene_and_animation_scene_context.inl"
    )
    snapshot_builder_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_snapshot.inl"
    )
    state_getter_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    progression_sync_text = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/native_progression_sync.inl"
    )

    required_pairs = (
        (snapshot_types_text, "uintptr_t materialized_scene_address = 0;"),
        (snapshot_types_text, "uintptr_t materialized_world_address = 0;"),
        (scene_context_text, "bool IsParticipantMaterializationOwnedByCurrentScene("),
        (scene_context_text, "current_gameplay_address != materialized_scene_address"),
        (scene_context_text, "current_context.world_address == materialized_world_address"),
        (scene_context_text, "ShouldParticipantSceneIntentMaterializeInScene(scene_intent, current_context)"),
        (snapshot_builder_text, "snapshot.materialized_scene_address = binding.materialized_scene_address;"),
        (snapshot_builder_text, "snapshot.materialized_world_address = binding.materialized_world_address;"),
        (state_getter_text, "snapshot = *it;"),
        (state_getter_text, "snapshot.materialized_scene_address"),
        (state_getter_text, "snapshot.materialized_world_address"),
        (progression_sync_text, "DoesLocalSceneMatchParticipantIntent(participant.runtime.scene_intent)"),
        (progression_sync_text, "!gameplay_state.entity_materialized"),
        (progression_sync_text, "native_progression_reconcile_by_participant.erase("),
    )
    missing = [token for text, token in required_pairs if token not in text]
    if missing:
        raise StaticReTestFailure(
            "participant native scene ownership is missing token(s): "
            + ", ".join(missing)
        )

    ownership_start = scene_context_text.find(
        "bool IsParticipantMaterializationOwnedByCurrentScene("
    )
    ownership_end = scene_context_text.find(
        "\nbool ShouldBotBeMaterializedInScene(",
        ownership_start,
    )
    ownership_body = scene_context_text[ownership_start:ownership_end]
    forbidden_ownership_heuristics = (
        "GetTickCount64",
        "freshness",
        "retry",
        "grace",
    )
    stale_heuristics = [
        token for token in forbidden_ownership_heuristics if token in ownership_body
    ]
    if stale_heuristics:
        raise StaticReTestFailure(
            "participant native ownership must be exact, not time-based: "
            + ", ".join(stale_heuristics)
        )

    builder_owner_check = snapshot_builder_text.find(
        "!IsParticipantMaterializationOwnedByCurrentScene("
    )
    builder_native_probe = snapshot_builder_text.find(
        "IsParticipantActorMemoryFreshReadable(",
        builder_owner_check,
    )
    if (
        builder_owner_check == -1
        or builder_native_probe == -1
        or builder_owner_check > builder_native_probe
    ):
        raise StaticReTestFailure(
            "participant snapshots must prove current scene ownership before "
            "probing actor memory"
        )

    getter_owner_check = state_getter_text.find(
        "!IsParticipantMaterializationOwnedByCurrentScene("
    )
    getter_native_publish = state_getter_text.find(
        "state->actor_address = snapshot.actor_address;",
        getter_owner_check,
    )
    getter_native_read = state_getter_text.find(
        "TryReadWizardActorPersistentStatusFlags(",
        getter_owner_check,
    )
    if not (
        0 <= getter_owner_check < getter_native_publish < getter_native_read
    ):
        raise StaticReTestFailure(
            "participant state getters must reject stale scene bindings before "
            "publishing or reading native pointers"
        )

    progression_start = progression_sync_text.find(
        "void ReconcileRemoteParticipantNativeProgression("
    )
    semantic_scene_check = progression_sync_text.find(
        "DoesLocalSceneMatchParticipantIntent(participant.runtime.scene_intent)",
        progression_start,
    )
    gameplay_state_lookup = progression_sync_text.find(
        "TryGetParticipantGameplayState(",
        progression_start,
    )
    progression_write = progression_sync_text.find(
        "ReconcileRemoteParticipantDamageX4State(",
        gameplay_state_lookup,
    )
    if not (
        0 <= progression_start < semantic_scene_check < gameplay_state_lookup < progression_write
    ):
        raise StaticReTestFailure(
            "remote progression reconciliation must prove semantic scene intent "
            "and current native materialization before any write"
        )

    run_exit_reentry_verifier_text = read_text(
        ROOT / "tools/verify_steam_friend_run_exit_reentry.py"
    )
    live_release_tokens = (
        "verify_run_exit_releases_native_participants(",
        "participant.progression_runtime_state_address",
        "participant.equip_runtime_state_address",
        "outgoing-scene native participant pointers",
        'record["transition_native_release"]',
    )
    missing_live_release = [
        token
        for token in live_release_tokens
        if token not in run_exit_reentry_verifier_text
    ]
    if missing_live_release:
        raise StaticReTestFailure(
            "real-Steam run re-entry lacks native transition release checks: "
            + ", ".join(missing_live_release)
        )

    return (
        "participant native pointers are exact scene/world-owned and remote "
        "progression writes stop immediately during semantic transitions"
    )
