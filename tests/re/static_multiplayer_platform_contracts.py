"""Platform, launcher, and session lifecycle contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

from static_multiplayer_contract_support import (
    ROOT,
    _read,
    _read_many,
    _require_in_order,
    read_source_unit,
)

def test_proton_input_targets_the_exact_native_game_window() -> str:
    automation = _read("tools/steam_friend_hub_automation.py")
    activation_helper = _read("scripts/activate_window.py")
    windows_hub_input = _read(
        "tools/verify_multiplayer_hub_inventory_shop_sync.py"
    )
    real_input = _read("tools/verify_steam_friend_real_input_control.py")
    storage = _read("tools/verify_steam_friend_hub_inventory_storage.py")
    shop = _read("tools/verify_steam_friend_hub_shop_ownership.py")
    steam_rush = _read("tools/verify_steam_friend_active_pair_rush.py")
    rush = _read("tools/verify_multiplayer_rush_behavior_sync.py")
    combined = "\n".join((real_input, storage, shop, steam_rush))

    for token in (
        '"^SolomonDark$"',
        "def proton_input_process_id() -> int:",
        "SolomonDark (Ubuntu)",
        "[WARN:COPY MODE] SolomonDark (Ubuntu)",
        "Get-Process msrdc",
        "def activate_proton_window(input_window_pid: int) -> str:",
        "def hold_proton_key(",
        "def hold_key(target: HubInputTarget, key: str, hold_ms: int) -> str:",
    ):
        assert token in automation, f"exact Proton input routing lacks: {token}"

    for token in (
        '"stage/SolomonDark.exe"',
        "path_for_powershell(executable)",
        "[string]::Equals([string]$_.ExecutablePath,$path,",
        "[System.StringComparison]::OrdinalIgnoreCase",
    ):
        assert token in real_input, f"exact Windows input routing lacks: {token}"
    assert "$_.CommandLine -like" not in real_input

    assert "SolomonDark (Ubuntu)" not in combined
    assert "wslg_window_process_id" not in combined
    assert "windowactivate" not in automation
    assert "windowfocus" not in automation
    assert '["keydown"' not in automation
    assert '["keyup"' not in automation
    for token in (
        "find_window(pid=args.pid)",
        "activate_window(window.hwnd, args.delay_ms)",
    ):
        assert token in activation_helper, (
            f"exact Windows activation helper lacks: {token}"
        )
    for verifier in (storage, shop):
        assert "proton_input_process_id()" in verifier
        assert "hold_key(direction," in verifier
        assert "hub_inventory.hold_real_key(" not in verifier
    for token in (
        "proton_input_process_id()",
        "hold_proton_key(",
        'direction.input_window_kind == "windows"',
    ):
        assert token in real_input, f"two-owner input verifier lacks: {token}"
    for token in (
        "keyboard_drivers: dict[str, KeyboardDriver]",
        "keyboard_drivers[direction.name]",
    ):
        assert token in rush, f"Rush keyboard routing lacks: {token}"
    assert "hold_proton_key" in steam_rush
    for token in (
        "WINDOWS_CLICK_HOLD_MS = 300",
        '"--hold-ms", str(WINDOWS_CLICK_HOLD_MS)',
    ):
        assert token in windows_hub_input, (
            f"Windows stock UI click timing lacks: {token}"
        )
    for token in (
        "PROTON_CLICK_HOLD_SECONDS = 0.30",
        "time.sleep(PROTON_CLICK_HOLD_SECONDS)",
    ):
        assert token in automation, f"Proton stock UI click timing lacks: {token}"

    return (
        "Proton keyboard and pointer input bind the one exact native X11 game "
        "window while Windows input remains process-owned"
    )


def test_native_local_player_keeps_stock_input_and_equipment_ownership() -> str:
    removed_prime = (
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "standalone_materialization_local_player_cast_state.inl"
    )
    actor_tick = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )
    native_primary = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/local_player_native_primary_runtime.inl"
    )
    stock_input = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/local_player_stock_input_runtime.inl"
    )
    ranked_rush = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/ranked_rush_movement_scale.inl"
    )
    player_control = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_control_hooks.inl"
    )
    actor_tick_includes = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick_hooks.inl"
    )
    materialization = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/standalone_materialization.inl"
    )
    declarations = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "internal_forward_declarations.inl"
    )
    native_control_contract = _read_many(
        "config/binary-layout.ini",
        "SolomonDarkModLoader/src/gameplay_seams.h",
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl",
        "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl",
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl",
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/internal_forward_declarations.inl",
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_actor_calls/player_runtime_and_progression_calls.inl",
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "scene_and_animation_bot_priming_and_selection.inl",
        "mods/lua_ui_sandbox_lab/config/probe-layout.ini",
        "mods/lua_ui_sandbox_lab/scripts/lib/config.lua",
        "mods/lua_ui_sandbox_lab/scripts/lib/create_probe.lua",
    )
    getters = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    verifier = _read("tools/verify_multiplayer_player_visibility.py")

    assert not removed_prime.exists(), (
        "native local players must not carry the bot cast/equip/control materializer"
    )
    for text in (actor_tick, materialization, declarations):
        assert "MaybePrimeLocalPlayerRunCastState" not in text
    for token in (
        "EnsureWizardActorEquipRuntimeHandles(",
        "PrimeGameplaySlotBotSelectionState(",
        "WireGameplaySlotBotRuntimeHandles(",
        "TryWriteGameplaySelectionStateForSlot(",
        "ApplyStandaloneWizardPuppetDriveState(",
    ):
        assert token not in native_primary, (
            f"local primary initializer still installs bot-owned state: {token}"
        )

    for stale_name in (
        "PlayerActorRefreshRuntimeHandles",
        "player_actor_refresh_runtime_handles",
        "refresh_runtime_handles",
        "trace_player_refresh_runtime",
    ):
        assert stale_name not in native_control_contract, (
            f"decoded control-brain initializer keeps stale name: {stale_name}"
        )
    for token in (
        "player_actor_initialize_control_brain=0x0052A370",
        "kPlayerActorInitializeControlBrain",
        "PlayerActorInitializeControlBrainFn",
        "CallPlayerActorInitializeControlBrainSafe(",
        "PlayerActor_InitializeControlBrain",
        "trace_player_initialize_control_brain",
    ):
        assert token in native_control_contract, (
            f"decoded control-brain initializer lacks: {token}"
        )

    for token in (
        "MaybeInitializeLocalPlayerNativePrimaryRuntime(",
        "EnsureActorProgressionRuntimeFieldFromHandle(",
        "ApplyProfilePrimaryLoadoutToSkillsWizard(",
        "kActorProgressionRuntimeStateOffset",
        "kProgressionCurrentSpellIdOffset",
        "spellbook_revision",
        "statbook_revision",
        "loadout_revision",
        "concentration_revision",
        "derived_stat_revision",
    ):
        assert token in native_primary, (
            f"native local primary initialization lacks: {token}"
        )
    _require_in_order(
        actor_tick_includes,
        '#include "actor_tick/local_player_native_primary_runtime.inl"',
        '#include "actor_tick/local_player_stock_input_runtime.inl"',
        '#include "actor_tick/player_actor_tick_hook.inl"',
    )
    assert "EnsureLocalPlayerNativeControlBrain(" not in actor_tick
    assert "EnsureLocalPlayerNativeControlBrain(" not in native_primary
    assert "CallPlayerActorInitializeControlBrainSafe(" not in native_primary
    assert "kPlayerActorInitializeControlBrain" not in native_primary
    for token in (
        "class ScopedLocalPlayerScriptedMovementInput final",
        "g_gameplay_keyboard_injection.pending_movement_frames",
        "kGameplayLocalMovementInputXOffset",
        "kGameplayLocalMovementInputYOffset",
        "pending_frames.compare_exchange_weak(",
        "pending_frames.fetch_add(1, std::memory_order_acq_rel)",
    ):
        assert token in stock_input, f"stock local scripted input lacks: {token}"
    _require_in_order(
        actor_tick,
        "ScopedLocalPlayerScriptedMovementInput scripted_movement_input(",
        "ScopedLocalPlayerRushMovementScale rush_movement_scale(actor_address)",
        "original(self);",
    )
    assert "pending_movement_frames" not in player_control, (
        "human scripted movement must not be consumed by the AI control-brain hook"
    )
    for token in (
        "kActorMoveStepScaleOffset",
        '"mValue"',
        '"mConcentration"',
        "TryReadGameplayConcentrationStateForSlot(",
        "concentration_entry_a == kRushProgressionEntryIndex",
        "concentration_entry_b == kRushProgressionEntryIndex",
        "original_move_step_scale_ * movement_multiplier",
    ):
        assert token in ranked_rush, f"stock human Rush movement lacks: {token}"
    assert "kActorMovementSpeedMultiplierOffset" not in ranked_rush, (
        "Rush must scale the native human move step, not only raise an unreachable velocity cap"
    )

    cast_verifier = _read("tools/verify_multiplayer_primary_kill_stress.py")
    steam_cast_verifier = _read("tools/verify_steam_friend_primary_kill_stress.py")
    stale_hold_verifier = _read(
        "tools/verify_steam_friend_world_snapshot_stale_hold.py"
    )
    real_cast_verifier = _read("tools/verify_real_input_spell_cast_sync.py")
    multiplayer_log_probe = _read("tools/multiplayer_log_probe.py")
    cast_runtime = cast_verifier[
        cast_verifier.index('CAST_RUNTIME_STATE_LUA = r"""') :
        cast_verifier.index('SPAWN_REWARD_LUA = r"""')
    ]
    for token in (
        "progression_runtime == progression_inner",
        "progression_spell > 0",
        "native_local_control",
    ):
        assert token in cast_runtime, f"native cast readiness lacks: {token}"
    ready_clause = cast_runtime[
        cast_runtime.index("local ready =") : cast_runtime.index('emit("ok", true)')
    ]
    assert "equip_ready" not in ready_clause
    assert "selection_ptr ~= 0" not in ready_clause
    assert "selection_state > 0" not in ready_clause
    assert (
        "local native_local_control = equip_runtime == 0 and selection_ptr == 0"
        in cast_runtime
    )
    for token in (
        "LEVEL_UP_PAUSE_LOG_MARKERS",
        "def resolve_active_level_up_barrier(",
        "def wait_for_source_cast_resolving_level_ups(",
        "resolve_level_ups_from_snapshots(last_host, last_client)",
        'record["level_up_resolutions"]',
    ):
        assert token in cast_verifier, (
            f"primary-kill verifier mid-cast level-up handling lacks: {token}"
        )
    level_up_verifier = _read("tools/verify_multiplayer_level_up_offer_sync.py")
    choice_wait_start = level_up_verifier.index("def wait_for_choice_result(")
    choice_wait_end = level_up_verifier.find("\ndef ", choice_wait_start + 1)
    assert choice_wait_end >= 0, "wait_for_choice_result must have a function boundary"
    choice_wait = level_up_verifier[choice_wait_start:choice_wait_end]
    _require_in_order(
        choice_wait,
        "target_participant_id: int | None = None",
        "if target_participant_id is None:",
        "target_participant_id = CLIENT_ID",
        "deadline = time.monotonic() + timeout",
    )
    source_cast_wait = cast_verifier[
        cast_verifier.index("def wait_for_source_cast_resolving_level_ups(") :
        cast_verifier.index("def execute_primary_kill_attempt(")
    ]
    _require_in_order(
        source_cast_wait,
        "parse_phase_counts(last_log, direction.source_id)",
        "if last_native_hook_count >= 1",
        "combined_log = last_log + receiver_log",
        "resolve_active_level_up_barrier(",
        "deadline += time.monotonic() - resolution_started",
    )
    assert "wait_for_source_cast," not in cast_verifier
    for token in (
        "local verbose = __VERBOSE__",
        "def build_find_target_lua(",
        'verbose=False',
        "def diagnose_target_or_last(",
        'emit("rep.apply_valid"',
        'emit("rep.age_ms"',
        'emit("rep.apply_age_ms"',
        'emit("rep.apply_holding_stale_snapshot"',
        'emit("rep.apply_source_snapshot_age_ms"',
    ):
        assert token in cast_verifier, (
            f"primary-kill verifier compact polling lacks: {token}"
        )
    assert '.replace("__VERBOSE__", "true" if verbose else "false")' in cast_verifier
    for token in (
        'stress_output = args.output.with_name(',
        'output=stress_output',
        'stress_output.read_text(encoding="utf-8")',
    ):
        assert token in steam_cast_verifier, (
            f"Steam primary-kill wrapper evidence preservation lacks: {token}"
        )

    world_reconciliation = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "world_snapshot_reconciliation.inl"
    )
    world_apply_runtime = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_effect_state.inl"
    )
    world_lua = _read("SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    for token in (
        "bool holding_stale_snapshot = false;",
        "std::uint64_t source_snapshot_age_ms = 0;",
    ):
        assert token in world_apply_runtime, (
            f"world snapshot stale-hold runtime lacks: {token}"
        )
    stale_hold = world_reconciliation[
        world_reconciliation.index("const auto sampled_snapshot_age_ms") :
        world_reconciliation.index("const auto used_latest_presentation")
    ]
    for token in (
        "runtime_state.session_status == multiplayer::SessionStatus::Ready",
        "authority_participant_present",
        "IsSameWorldSnapshotTimeline(snapshot, runtime_state.world_snapshot)",
        "snapshot = runtime_state.world_snapshot;",
        "holding last authoritative actor state",
        "stale_without_live_authority",
    ):
        assert token in stale_hold, (
            f"world snapshot stale-hold decision lacks: {token}"
        )
    for token in (
        "const bool allow_structural_reconciliation = !holding_stale_snapshot;",
        "if (allow_structural_reconciliation) {\n        MaybeQueueRunLifecycleForAuthoritativeSnapshot",
        "if (allow_structural_reconciliation) {\n        MaybeCatchUpRunEnemyPoolForAuthoritativeSnapshot",
        "if (allow_structural_reconciliation &&\n        snapshot_may_be_complete",
        "holding_stale_snapshot,\n        holding_stale_snapshot",
    ):
        assert token in world_reconciliation, (
            f"world snapshot stale-hold structural guard lacks: {token}"
        )
    assert 'lua_setfield(state, -2, "apply_holding_stale_snapshot")' in world_lua
    assert 'lua_setfield(state, -2, "apply_source_snapshot_age_ms")' in world_lua
    for token in (
        "manual_prelude = primary.enable_manual_stock_spawner_combat()",
        "NtSuspendProcess",
        "NtResumeProcess",
        'marker != "suspended"',
        'sample["holding_stale_snapshot"]',
        'sample["binding_count"] < 1',
        'abs(sample["snapshot_hp"] - sample["local_hp"]) > 0.05',
        "drift > 8.0",
        'not resumed["holding_stale_snapshot"]',
        'resumed["source_snapshot_age_ms"] < 800',
    ):
        assert token in stale_hold_verifier, (
            f"real-Steam stale world-snapshot hold verifier lacks: {token}"
        )
    for token in (
        "def log_position(path: Path) -> int:",
        'with path.open("rb") as stream:',
        "stream.seek(offset)",
    ):
        assert token in multiplayer_log_probe, (
            f"shared multiplayer incremental log reader lacks: {token}"
        )
    assert (
        "from multiplayer_log_probe import log_after, log_position, read_log"
        in real_cast_verifier
    ), "real-input spell verifier bypasses the shared byte-positioned log reader"
    assert "return read_log(path)[offset:]" not in real_cast_verifier
    assert "len(read_log(" not in real_cast_verifier
    assert "len(read_log(" not in cast_verifier

    _require_in_order(
        getters,
        "if (state->equip_runtime_state_address != 0)",
        "kActorEquipRuntimeVisualLinkPrimaryOffset",
        "if (resolved_gameplay_address && state->equip_runtime_state_address == 0)",
        "kGameplayVisualSinkPrimaryOffset",
        "kGameplayVisualSinkAttachmentOffset",
    )
    for token in (
        "RUN_ENTRY_FORMATION_RELEASE_SECONDS = 5.25",
        'result["hub_screenshots"]',
        'result["run_screenshots"]',
        "VISIBILITY_PAIR_HALF_SEPARATION = 100.0",
    ):
        assert token in verifier, f"visibility verifier lacks: {token}"

    return (
        "native local players retain the stock null control-brain slot-table path "
        "while synchronized progression/spells initialize and bot-owned equipment "
        "and drive materializers remain excluded"
    )


def test_host_run_exit_is_authoritative_and_self_correcting() -> str:
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    transport_api = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl"
    )
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl"
    )
    outgoing = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/outgoing_packet_sync.inl"
    )
    incoming = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_sync.inl"
    )
    run_exit = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/run_exit_sync.inl"
    )
    lifecycle = _read(
        "SolomonDarkModLoader/src/run_lifecycle/enemy_tracking_and_reset.inl"
    )
    ui_action = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "state_actions_activation/resolved_action_activation.inl"
    )
    verifier = _read("tools/verify_multiplayer_player_visibility.py")

    assert '#include "multiplayer_local_transport/run_exit_sync.inl"' in transport
    assert "void NotifyLocalRunEnded(std::string_view reason)" in transport
    _require_in_order(
        lifecycle,
        "multiplayer::NotifyLocalRunEnded(reason);",
        "ResetRunLifecycleBookkeeping(clear_enemy_tracking);",
        "ClearLocalRunGenerationSeed();",
    )
    assert "complete_successful_dispatch(TryInvokeOwnerControlActionByControlAddress(" in ui_action
    assert (
        'dispatched && action_id == "pause_menu.leave_game"' in ui_action
    ), "run lifecycle must end only after the stock Leave Game handler succeeds"

    for token in (
        "packet_from_configured_authority",
        "packet.in_run != 0",
        "packet.run_nonce == 0",
        "local->runtime.run_nonce != packet.run_nonce",
        'QueueGameplayKeyPress("menu", &menu_error)',
        'TryFindDebugUiActionElement(\n            "pause_menu.leave_game",\n            "simple_menu"',
        'TryActivateDebugUiAction(\n                "pause_menu.leave_game",\n                "simple_menu"',
    ):
        assert token in run_exit, f"host run-exit follow lacks: {token}"

    _require_in_order(
        local_state,
        "g_local_run_exit_latched_nonce.load",
        "packet->in_run = 0;",
        "packet->transform_valid = 0;",
        "packet->run_nonce = run_exit_nonce;",
    )
    assert (
        "packet.transform_valid == 0 &&\n"
        "        !(g_local_transport.is_host && packet.run_nonce != 0 && packet.in_run == 0)"
        in outgoing
    )
    _require_in_order(
        incoming,
        "MaybeQueueClientHostRunStart(packet, scene_intent, from, now_ms);",
        "StageClientHostRunExitFollow(",
    )
    _require_in_order(
        transport_api,
        "ReceivePackets(now_ms);",
        "ServiceClientHostRunExitFollow(now_ms);",
        "SendLocalState(now_ms);",
    )
    for token in (
        "assert_complete_local_wizard_visuals(",
        "wait_for_pause_leave_action(",
        "wait_for_pair_to_leave_run(",
        '"pause_menu.leave_game",\n        "simple_menu"',
        'result["post_run_exit_scenes"]',
    ):
        assert token in verifier, f"visibility/run-exit verifier lacks: {token}"

    return (
        "successful host run exits persist in authenticated state packets and "
        "clients self-correct through their own stock Leave Game UI path"
    )


def test_pair_launcher_drains_redirected_json_output() -> str:
    process_helper = _read("scripts/LocalMultiplayerLauncher.Process.ps1")

    for token in (
        "function Read-MultiplayerProcessOutput",
        "[System.IO.FileShare]::ReadWrite",
        "$process.WaitForExit()",
        "ConvertFrom-MultiplayerLauncherJson -Text $stdout",
        "if ($null -ne $process -and -not $process.HasExited)",
    ):
        assert token in process_helper, f"launcher process helper lacks: {token}"
    _require_in_order(
        process_helper,
        "$process.WaitForExit()",
        "$stdout = Read-MultiplayerProcessOutput -Path $stdoutPath",
        "$result = ConvertFrom-MultiplayerLauncherJson -Text $stdout",
    )

    return (
        "pair launches drain redirected streams before parsing JSON and clean "
        "up a still-running launcher on every exit path"
    )


def test_packaged_ui_accepts_single_file_launcher() -> str:
    resolver = _read(
        "SolomonDarkModLauncher.UI/src/Infrastructure/"
        "LauncherExecutableResolver.cs"
    )
    package = _read("scripts/New-BetaReleasePackage.ps1")
    smoke = _read("scripts/Test-BetaReleasePackage.ps1")

    assert "if (File.Exists(candidate))" in resolver
    for rejected_token in (
        "managedDllPath",
        "runtimeConfigPath",
        "depsPath",
        "Build the launcher project first",
    ):
        assert rejected_token not in resolver, (
            f"packaged launcher resolver still requires {rejected_token}"
        )
    assert "-p:PublishSingleFile=true" in package
    for token in (
        '$catalogReady = $visibleText -contains "Ready"',
        "$modSummaryPattern =",
        "'^Enabled mods: \\d+ of '",
        '$_ -like "Could not locate SolomonDarkModLauncher.exe*"',
        '$result.uiCatalogStatus = "Ready"',
    ):
        assert token in smoke, f"beta package smoke test lacks: {token}"

    return (
        "the packaged desktop UI accepts its single-file CLI and proves a "
        "catalog command crosses the real UI-to-CLI boundary"
    )


def test_beta_release_smoke_canonicalizes_packaged_steam_path() -> str:
    smoke = _read("scripts/Test-BetaReleasePackage.ps1")

    canonical_expected_root = (
        "$expectedSteamRoot = [System.IO.Path]::GetFullPath("
    )
    assert canonical_expected_root in smoke, (
        "the package smoke test must canonicalize its expected Steam root so "
        "equivalent Windows short and long paths compare equal"
    )
    _require_in_order(
        smoke,
        canonical_expected_root,
        "$result.steamApiSource.StartsWith(",
    )

    return "package smoke canonicalizes 8.3 path aliases before containment checks"


def test_packaged_ui_does_not_inherit_test_world_overrides() -> str:
    command_client = _read(
        "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherUiCommandClient.cs"
    )

    for variable_name in (
        "SDMOD_TEST_BLANK_BONEYARD",
        "SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE",
        "SDMOD_TEST_WAVE_OVERRIDE",
    ):
        assert f'"{variable_name}"' in command_client, (
            f"desktop launcher does not isolate {variable_name}"
        )
    _require_in_order(
        command_client,
        "var startInfo = new ProcessStartInfo(executablePath)",
        "foreach (var variableName in TestOnlyChildEnvironmentVariables)",
        "startInfo.Environment.Remove(variableName);",
        "using var process = new Process { StartInfo = startInfo };",
        "process.Start();",
    )

    return "desktop launches cannot inherit test-only Boneyard or wave overrides"


def test_launcher_auto_accepts_steam_invites_and_hub_gates_discovery() -> str:
    parser = _read("SolomonDarkModLauncher/src/Commands/LauncherCommandParser.cs")
    listener = _read("SolomonDarkModLauncher/src/Steam/SteamInviteListener.cs")
    listener_client = _read(
        "SolomonDarkModLauncher.UI/src/Infrastructure/SteamInviteListenerClient.cs"
    )
    view_model = _read(
        "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
    )
    status_reader = _read(
        "SolomonDarkModLauncher.UI/src/Infrastructure/"
        "LauncherMultiplayerSessionStatusReader.cs"
    )
    publisher = _read(
        "SolomonDarkModLauncher/src/Launch/LobbyDirectoryPublisher.cs"
    )
    native_status = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/lobby_and_events.inl"
    )
    smoke = _read("scripts/Test-BetaReleasePackage.ps1")

    for token in ("--lobby-privacy", "--directory-url"):
        assert token in parser, f"launcher parser lacks {token}"
        assert token in smoke, f"package smoke test lacks {token}"
    for token in (
        "GameLobbyJoinRequestedCallbackId = 333",
        "GameRichPresenceJoinRequestedCallbackId = 337",
        'kind = "accepted"',
        "SDMOD_STEAM_INVITE ",
    ):
        assert token in listener, f"Steam invite listener lacks: {token}"
    for token in (
        "__listen-steam-invites",
        "NotificationReceived",
        "Environment.ProcessId",
    ):
        assert token in listener_client, f"launcher invite client lacks: {token}"
    for token in (
        "pendingLobbyJoinId_",
        "QueueLobbyJoin(acceptedLobbyId)",
        "TryLaunchPendingLobbyJoin",
        "The launcher joins lobby",
        "LauncherUiCommandMode.JoinSteam",
        "DescribeLobbyConnection",
        "response.Stage?.StageRoot",
    ):
        assert token in view_model, f"launcher auto-join flow lacks: {token}"
    assert 'Path.Combine(stageRootPath, ".sdmod", StatusFileName)' in status_reader
    assert "StageRuntimeRootPath" not in view_model[
        view_model.index("private void StartSteamSessionMonitoring"):
        view_model.index("private void ApplySteamSessionStatus")
    ], "launcher session monitor still polls the staged runtime-mod directory"
    _require_in_order(
        publisher,
        'hubObserved = hubObserved || status?.GamePhase == "hub"',
        "if (hubObserved &&",
        "var result = await AnnounceAsync(",
        "configuration.ActiveMods)",
    )
    for token in (
        'std::string game_phase = "loading"',
        'game_phase = "hub"',
        'game_phase = "session"',
        "SteamGetImmediateFriends()",
    ):
        assert token in native_status, f"native lobby status lacks: {token}"

    return (
        "accepted Steam callbacks auto-launch lobby-ID joins, connection details "
        "are visible, and website discovery begins only after a real hub state"
    )


def test_website_lobby_links_register_and_route_to_launcher() -> str:
    app = _read("SolomonDarkModLauncher.UI/App.xaml.cs")
    command_client = _read(
        "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherUiCommandClient.cs"
    )
    executor = _read(
        "SolomonDarkModLauncher/src/App/LauncherCommandExecutor.cs"
    )
    join_uri = _read(
        "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherJoinUri.cs"
    )
    protocol_registration = _read(
        "SolomonDarkModLauncher.UI/src/Infrastructure/"
        "LauncherProtocolRegistration.cs"
    )
    activation_broker = _read(
        "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherActivationBroker.cs"
    )
    view_model = _read(
        "SolomonDarkModLauncher.UI/src/ViewModels/MainWindowViewModel.cs"
    )
    package_smoke = _read("scripts/Test-BetaReleasePackage.ps1")
    playtest_guide = _read("docs/networking/steam-friend-playtest.md")

    for token in (
        "LauncherProtocolRegistration.RegisterCurrentExecutable()",
        "LauncherActivationBroker",
        "LauncherJoinUri.TryParse",
        "viewModel.QueueWebsiteLobbyJoin(activation)",
    ):
        assert token in app, f"desktop launcher startup lacks: {token}"
    for token in (
        'private const string Scheme = "solomondarkrevived";',
        '!string.Equals(uri.Host, "join", StringComparison.Ordinal)',
        "ulong.TryParse",
        "query.Length < 2",
        "uri.Query.Length == 0",
    ):
        assert token in join_uri, f"website lobby URI parser lacks: {token}"
    for token in (
        '@"Software\\Classes\\solomondarkrevived"',
        'protocolKey.SetValue("URL Protocol", string.Empty)',
        '@"shell\\open\\command"',
        'commandKey.SetValue(null, $"\\\"{executablePath}\\\" \\"%1\\\"")',
    ):
        assert token in protocol_registration, f"sdr protocol registration lacks: {token}"
    for token in (
        'private const string MutexName = @"Local\\SolomonDarkMultiplayerBeta";',
        "NamedPipeServerStream",
        "NamedPipeClientStream",
        "ForwardActivation",
    ):
        assert token in activation_broker, f"single-instance lobby activation lacks: {token}"
    for token in (
        "public void QueueLobbyJoin(ulong lobbyId)",
        "pendingLobbyJoinId_ = lobbyId;",
        "TryLaunchPendingLobbyJoin();",
    ):
        assert token in view_model, f"unified pending lobby join lacks: {token}"
    join_arguments = command_client[
        command_client.index("case LauncherUiCommandMode.JoinSteam:") :
        command_client.index("return arguments;")
    ]
    for token in ('arguments.Add("--directory-url")', "arguments.Add(directoryUrl_)"):
        assert token in join_arguments, f"P2P joins do not attempt website mod sync: {token}"
    assert "--sync-lobby-mods" not in command_client, (
        "website mod sync is still opt-in instead of automatic for P2P joins"
    )
    _require_in_order(
        executor,
        "command.MultiplayerMode == MultiplayerLaunchMode.Join",
        "command.SteamLobbyId is { } lobbyId",
        "LobbyModSynchronizer.SynchronizeAsync(",
    )
    for token in (
        "TryFetchRequiredModsAsync",
        "LobbyModSyncResult.Offline(localCatalog",
    ):
        assert token in _read(
            "SolomonDarkModLauncher/src/Mods/LobbyModSynchronizer.cs"
        ), f"automatic P2P mod sync lacks offline fallback: {token}"
    process_exit_monitor = view_model[
        view_model.index("private async Task MonitorGameProcessExitAsync") :
        view_model.index("private void StartSteamSessionMonitoring")
    ]
    assert "TryLaunchPendingLobbyJoin();" in process_exit_monitor, (
        "a website lobby link queued during gameplay is not retried after exit"
    )
    for token in (
        '"Software\\Classes\\solomondarkrevived"',
        '"URL Protocol"',
        '$expectedProtocolCommand = "`"$uiExecutable`" `"%1`""',
        "$result.uiSingleInstanceForwarding = $true",
        '"solomondarkrevived://join/$testLobbyId"',
        "$result.uiLobbyLinkForwarding = $true",
    ):
        assert token in package_smoke, f"package protocol smoke check lacks: {token}"

    for stale_text in ("Steam invites ready", "Browse Lobbies"):
        assert stale_text not in playtest_guide, (
            "playtest guide still documents removed launcher copy: " + stale_text
        )

    return (
        "website lobby links register the packaged launcher, forward to one active "
        "window, and use the same pending lobby join as Steam callbacks"
    )


def test_explicit_blank_boneyard_removes_native_scenery_and_collision() -> str:
    blank_runtime = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "test_blank_boneyard_reconciliation.inl"
    )
    dispatch = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks.inl"
    )
    pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    layout = _read("config/binary-layout.ini")
    launcher = _read("scripts/Launch-LocalMultiplayerPair.ps1")
    staged_game_launcher = _read(
        "SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs"
    )
    verifier = _read("tools/verify_flat_multiplayer_boneyard.py")
    steam_verifier = _read("tools/verify_steam_friend_flat_boneyard.py")

    assert '#include "test_blank_boneyard_reconciliation.inl"' in dispatch
    assert "ReconcileExplicitTestBlankBoneyard(" in pump
    assert '"SDMOD_TEST_BLANK_BONEYARD"' in blank_runtime
    assert "length == 1 && value[0] == '1'" in blank_runtime
    assert "IsExpectedBlankBoneyardSceneryType" in blank_runtime
    assert "IsExpectedBlankBoneyardScriptedSetpieceType" in blank_runtime
    assert "kTestBlankBoneyardSolomonDigTypeId = 0x1391" in blank_runtime
    assert "kTestBlankBoneyardLanternTypeId = 0x1392" in blank_runtime
    assert "TryRequestBlankBoneyardScriptedSetpieceRetirement" in blank_runtime
    assert "CallActorRequestRetirementSafe(" in blank_runtime
    assert "kActorPendingRemoveOffset" in blank_runtime
    assert "kGameplayPrimaryGateBlockFlagOffset" not in blank_runtime
    assert "0x1ABE" not in blank_runtime
    assert "type == 3004" in blank_runtime
    assert "type == 3005" in blank_runtime
    _require_in_order(
        blank_runtime,
        '"static movement-circle cache"',
        "TryDetachMovementCircleFromGridCell(\n                object_address,",
        '"movement-circle list"',
        "owner_list.address,",
        "CallScalarDeletingDestructorSafe(",
    )
    for token in (
        "actor_world_scenery_object_list=0x87C4",
        "actor_world_road_list=0x8810",
        "actor_world_fence_list=0x885C",
        "movement_controller_static_circle_count=0x12C",
        "movement_controller_static_circle_list=0x138",
    ):
        assert token in layout, f"blank Boneyard layout lacks: {token}"

    assert "[switch]$TestBlankBoneyard" in launcher
    assert 'if ($TestBlankBoneyard)' in launcher
    assert '$env.SDMOD_TEST_BLANK_BONEYARD = "1"' in launcher
    assert (
        'TestBlankBoneyardEnvironmentVariable =\n'
        '        "SDMOD_TEST_BLANK_BONEYARD";'
    ) in staged_game_launcher
    assert (
        "TestBlankBoneyardEnvironmentVariable\n    };"
        in staged_game_launcher
    )
    assert "test_blank_boneyard=True" in verifier
    assert "wait_for_blank_arena_census(HOST_PIPE)" in verifier
    assert "wait_for_blank_arena_census(CLIENT_PIPE)" in verifier
    assert "expected_actor_count: int | None = None" in verifier
    assert "expected_actor_count=0" in verifier
    assert "expected_actor_count=0" in steam_verifier
    for zero_count in (
        'last.get("scripted_setpiece_actor_count", "-1")',
        'last.get("primary_gate_blocked", "-1")',
        'last.get("cast_ui_blocked", "-1")',
        'last.get("scenery_count", "-1")',
        'last.get("road_count", "-1")',
        'last.get("fence_count", "-1")',
        'last.get("static_circle_count", "-1")',
        'last.get("scenery_circle_count", "-1")',
    ):
        assert zero_count in verifier

    return (
        "the opt-in flat test retires the stock Solomon intro setpiece, removes "
        "only known native scenery/road/fence objects, clears all native "
        "circle/cell collision indexes, and verifies open controls on both peers"
    )


def test_progression_matrices_prearm_quiet_spawning_before_run_entry() -> str:
    for verifier_path in (
        "tools/verify_multiplayer_all_upgrade_sync.py",
        "tools/verify_multiplayer_all_stat_sync.py",
    ):
        verifier = _read(verifier_path)
        _require_in_order(
            verifier,
            'output["quiet_progression_test_mode"] = enable_quiet_progression_test_mode()',
            'output["run_entry"] = start_host_testrun_and_wait_for_clients(',
            'output["post_run_progression_ready"] = wait_for_post_run_progression_ready(',
        )

    steam_verifier = _read(
        "tools/verify_steam_friend_active_pair_progression.py"
    )
    for token in (
        "FIRST_LEVEL_UP_UPGRADE_ENTRY = 8",
        "return list(range(FIRST_LEVEL_UP_UPGRADE_ENTRY, real_count))",
        'os.environ.get("SDMOD_STEAM_HOST_INSTANCE", "").strip()',
        'os.environ.get("SDMOD_STEAM_CLIENT_INSTANCE", "").strip()',
        "both Steam instance environment variables are required",
        "def steam_skill_config_root()",
        "catalog_probe.load_skill_configs(config_root)",
        "config_root = steam_skill_config_root()",
    ):
        assert token in steam_verifier, (
            f"active Steam progression matrix lacks: {token}"
        )
    for stale_default in ("steam-host-gameplay10", "wsl-steam-gameplay10"):
        assert stale_default not in steam_verifier

    return (
        "progression matrices suppress stock waves before entering the run so "
        "combat cannot invalidate participant-owned stat and skill observations"
    )


def test_steam_behavior_arena_reset_waits_for_native_spawner() -> str:
    behavior_context = _read("tools/steam_friend_behavior_context.py")
    _require_in_order(
        behavior_context,
        "def reset_quiet_arena()",
        "manual_enemy_mode = upgrades.enable_quiet_progression_test_mode()",
        '"host": primary.wait_for_manual_spawner_ready(',
        "HOST_ENDPOINT,\n            timeout=12.0,",
        '"client": primary.wait_for_manual_spawner_ready(',
        "CLIENT_ENDPOINT,\n            timeout=12.0,",
        '"manual_spawner_ready": manual_spawner_ready,',
    )
    return (
        "Steam behavior fixtures wait for both real stock wave spawners after "
        "re-enabling quiet-arena mode"
    )


def test_active_steam_behavior_harnesses_preserve_fixture_state() -> str:
    driver = _read("tools/drive_steam_friend_active_pair.py")
    behavior_context = _read("tools/steam_friend_behavior_context.py")
    staff_harness = _read("tools/multiplayer_staff_behavior_harness.py")
    steam_stats = _read("tools/verify_steam_friend_active_pair_stat_behaviors.py")
    steam_persistent = _read(
        "tools/verify_steam_friend_active_pair_persistent_behavior.py"
    )
    run_reentry = _read("tools/verify_steam_friend_run_exit_reentry.py")
    steam_state = _read("tools/verify_steam_friend_active_pair_state.py")
    defense = _read("tools/verify_multiplayer_defense_behavior_sync.py")
    staff = _read("tools/verify_multiplayer_staff_stat_behavior_sync.py")

    assert "POISON_DURATION_OBSERVATION_TOLERANCE_TICKS = 12" in defense
    assert defense.count(
        "> POISON_DURATION_OBSERVATION_TOLERANCE_TICKS"
    ) == 2

    for token in (
        "_G.__sdmod_steam_test_manual_enemy_mode_registered",
        "_G.__sdmod_steam_test_manual_enemy_mode_enabled",
        "if _G.__sdmod_steam_test_manual_enemy_mode_enabled ~= true then",
        "return false, 'disabled'",
        "DISABLE_TEST_MANUAL_ENEMY_MODE_LUA",
        "def disable_test_manual_enemy_mode(",
        "sd.gameplay.set_manual_enemy_spawner_test_mode(false)",
        "DISABLE_TEST_GODMODE_LUA",
        "def disable_test_godmode(",
        "_G.__sdmod_steam_test_godmode_enabled = false",
    ):
        assert token in driver, f"persistent Steam manual-mode driver lacks: {token}"
    _require_in_order(
        driver,
        "if not _G.__sdmod_steam_test_manual_enemy_mode_registered then",
        "sd.events.on('runtime.tick', sustain)",
        "_G.__sdmod_steam_test_manual_enemy_mode_registered = true",
        "_G.__sdmod_steam_test_manual_enemy_mode_enabled = true",
    )
    _require_in_order(
        steam_state,
        'output["test_godmode_disabled"] = {',
        'output["status_resources"] = {',
        'output["vitals_remote_death_recovery"] = vitals_recovery',
    )
    for token in (
        '"SDMOD_STEAM_HOST_LOG_PATH"',
        '"SDMOD_STEAM_CLIENT_LOG_PATH"',
        "return Path(override)",
    ):
        assert token in behavior_context, (
            f"physical Steam behavior log routing lacks: {token}"
        )
    _require_in_order(
        behavior_context,
        "manual_enemy_mode = upgrades.enable_quiet_progression_test_mode()",
        "enemy_cleanup = primary.cleanup_live_enemies()",
    )

    natural_waves = staff_harness[
        staff_harness.index("def start_natural_staff_waves(") :
        staff_harness.index("\ndef park_natural_staff_targets(")
    ]
    for token in (
        "COMBAT_STATE_LUA",
        "stock_wave_already_active = (",
        '"already_active": True',
        '"already_active": False',
        "wait_for_natural_staff_actors(minimum_actors)",
    ):
        assert token in staff_harness, f"natural staff-wave adoption lacks: {token}"
    assert "spawn_manual_enemy" not in natural_waves

    for token in (
        "assert_pristine_rows(",
        "configure_behavior_context(pair)",
        "session = load_progression_inputs(timeout)",
        "defense.run_prepared_magic_stat_session(",
        "defense.run_prepared_deflect_stat_session(",
        "defense.run_prepared_poison_stat_session(",
        "disable_test_manual_enemy_mode(pair, HOST_ENDPOINT)",
        "disable_test_manual_enemy_mode(pair, CLIENT_ENDPOINT)",
        'output["test_godmode"] = disable_runtime_test_godmode(pair)',
        "staff.run_prepared_staff_matrix(",
    ):
        assert token in steam_stats, f"active Steam stat wrapper lacks: {token}"
    assert 'session["quiet"] = quiet' in steam_stats
    assert "launch_pair(" not in steam_stats
    assert "stop_games(" not in steam_stats
    for token in (
        "def prepare_progression_state(",
        "def run_prepared_magic_stat_session(",
        "def run_prepared_deflect_stat_session(",
        "def run_prepared_poison_stat_session(",
    ):
        assert token in defense, f"prepared defense harness lacks: {token}"
    assert "def run_prepared_staff_matrix(" in staff

    for token in (
        "disable_runtime_test_godmode",
        'output["test_godmode"] = disable_runtime_test_godmode(pair)',
        'instance_log(HOST_INSTANCE, "SDMOD_STEAM_HOST_LOG_PATH")',
        'instance_log(CLIENT_INSTANCE, "SDMOD_STEAM_CLIENT_LOG_PATH")',
    ):
        assert token in steam_persistent, (
            f"active Steam persistent wrapper lacks: {token}"
        )
    for token in (
        'PAIR_BACKEND == "wsl"',
        'PAIR_BACKEND == "remote-windows-host"',
        "remote_windows_process_id()",
        'instance_log(host_instance, "SDMOD_STEAM_HOST_LOG_PATH")',
        'instance_log(client_instance, "SDMOD_STEAM_CLIENT_LOG_PATH")',
        'parser.add_argument("--test-godmode", action="store_true")',
        'parser.add_argument("--test-manual-enemy-mode", action="store_true")',
        'parser.add_argument("--host-element", default="fire")',
        'parser.add_argument("--client-element", default="air")',
        "host_element=host_element",
        "client_element=client_element",
        '"host": drive.arm_test_godmode(pair, HOST_ENDPOINT)',
        '"client": drive.arm_test_manual_enemy_mode(pair, CLIENT_ENDPOINT)',
    ):
        assert token in run_reentry, (
            f"physical Steam run re-entry lacks: {token}"
        )
    _require_in_order(
        steam_persistent,
        "directions = configure(pair)",
        'output["test_godmode"] = disable_runtime_test_godmode(pair)',
        'output["resources"] = {',
        'output["active_step"] = "acquire_persistent_skills"',
    )

    return (
        "active Steam behavior harnesses keep persistent callbacks disableable, "
        "adopt genuine stock waves, and reuse strict prepared matrices"
    )


def test_staff_target_selection_skips_local_only_enemies() -> str:
    import multiplayer_staff_behavior_harness as staff

    replacements = {
        "query_natural_staff_arena": lambda: {
            "actor_count": "2",
            "actor.1.address": "11",
            "actor.1.live": "true",
            "actor.1.x": "10",
            "actor.1.y": "20",
            "actor.2.address": "22",
            "actor.2.live": "true",
            "actor.2.x": "30",
            "actor.2.y": "40",
        },
        "find_target": lambda pipe, x, y, **kwargs: (
            {"network_id": "0" if x == 10.0 else "9001"}
            if pipe == staff.HOST_PIPE
            else {"local.actor_address": "33"}
        ),
        "set_natural_staff_layout": lambda positions: {"valid": "true"},
        "configure_enemy": lambda actor, x, y, hp: {"ok": "true"},
        "values": lambda pipe, code: {"ok": "true", "error": ""},
    }
    originals = {name: getattr(staff, name) for name in replacements}
    try:
        for name, replacement in replacements.items():
            setattr(staff, name, replacement)
        targets = staff.configure_natural_staff_targets(
            [11, 22],
            [(100.0, 200.0)],
        )
    finally:
        for name, original in originals.items():
            setattr(staff, name, original)

    assert len(targets) == 1
    assert targets[0].host_actor == 22
    assert targets[0].network_id == 9001
    assert targets[0].client_actor == 33
    return "staff trials select only host-authoritative networked enemies"
