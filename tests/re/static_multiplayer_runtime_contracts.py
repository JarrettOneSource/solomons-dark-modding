"""Focused static contracts for multiplayer runtime hardening.

Keep new multiplayer checks out of the legacy monolithic RE test module.  Each
function raises AssertionError on failure and returns a short success detail so
the existing runner can report it uniformly.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _read_many(*relative_paths: str) -> str:
    return "\n".join(_read(path) for path in relative_paths)


def _require_in_order(text: str, *tokens: str) -> None:
    cursor = 0
    for token in tokens:
        position = text.find(token, cursor)
        assert position >= 0, f"missing ordered token: {token}"
        cursor = position + len(token)


def test_unreliable_snapshot_ordering_is_wrap_safe() -> str:
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    incoming = _read_many(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_cast_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_snapshot_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_dispatch.inl",
    )
    lifecycle = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/remote_peer_lifecycle.inl"
    )
    runtime_header = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_effect_state.inl"
    )
    runtime = _read("SolomonDarkModLoader/src/multiplayer_runtime_state.cpp")

    for token in (
        "constexpr bool IsPacketSequenceNewer(",
        "static_cast<std::uint32_t>(candidate - baseline) < 0x80000000u",
        "IsPacketSequenceNewer(0u, 0xFFFFFFFFu)",
        "!IsPacketSequenceNewer(0xFFFFFFFFu, 0u)",
    ):
        assert token in protocol, f"protocol lacks wrap-safe sequence contract: {token}"

    assert "last_state_packet_sequence_by_participant" in transport
    assert (
        "last_state_packet_sequence_by_participant.erase(participant_id)"
        in lifecycle
    ), "participant reconnect must reset its state-packet epoch"
    _require_in_order(
        incoming,
        "void ApplyRemoteStatePacket(",
        "last_state_packet_sequence_by_participant.find(",
        "!IsPacketSequenceNewer(",
        "RelayStatePacketToPeers(packet, from);",
        "UpdateRuntimeState([&](RuntimeState& state)",
    )

    assert "bool AppendLootSnapshot(" in runtime_header
    _require_in_order(
        runtime,
        "bool AppendLootSnapshot(",
        "SameLootSnapshotTimeline(latest, snapshot)",
        "!IsPacketSequenceNewer(snapshot.sequence, latest.sequence)",
        "state->loot_snapshot = std::move(snapshot);",
    )
    _require_in_order(
        incoming,
        "void ApplyLootSnapshotPacket(",
        "if (!PublishLootSnapshotRuntimeInfo(packet, now_ms))",
        "QueueReplicatedLootSnapshot(",
    )

    return (
        "participant and loot snapshots reject duplicate/out-of-order packets, "
        "accept uint32 wraparound, and reset on reconnect"
    )


def test_lua_exec_timeout_cancels_pending_work() -> str:
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    lua_main = _read("mods/lua_bots/scripts/main.lua")

    for token in (
        "LuaExecRequestState::Pending",
        "LuaExecRequestState::Executing",
        "LuaExecRequestState::Canceled",
        "std::shared_ptr<PendingLuaExecRequest>",
        "bool TryCancelLuaExecRequest(",
        "bool TryClaimLuaExecRequest(",
    ):
        assert token in engine, f"Lua exec cancellation contract lacks: {token}"

    _require_in_order(
        engine,
        "LuaExecResult QueueLuaExecRequestAndWait(",
        "TryCancelLuaExecRequest(queued.request)",
        "canceled before gameplay-thread execution",
    )
    _require_in_order(
        engine,
        "void ProcessLuaExecQueueOnMainThread()",
        "if (!TryClaimLuaExecRequest(request))",
        "ExecuteLuaCodeOnLockedState(shared_state, request->code)",
    )

    for unsafe_global in (
        '"debug"',
        '"dofile"',
        '"io"',
        '"loadfile"',
        '"os"',
        '"package"',
        '"require"',
    ):
        assert unsafe_global in engine

    for registration in (
        "RegisterLuaRuntimeBindings",
        "RegisterLuaEventBindings",
        "RegisterLuaBotBindings",
        "RegisterLuaUiBindings",
        "RegisterLuaInputBindings",
        "RegisterLuaGameplayBindings",
        "RegisterLuaHubBindings",
        "RegisterLuaDebugBindings",
    ):
        assert registration in bindings
    assert "lua_createtable(mod->state, 0, 10);" in bindings
    assert "lua_pcall" in events, "Lua event handlers must be fault isolated"

    for loader_token in (
        "runtime.get_mod_text_file",
        'load(source, "@" .. normalized, "t", _ENV)',
        "loading_sentinel",
        "pcall(chunk)",
    ):
        assert loader_token in lua_main

    return (
        "pending Lua exec requests are cancelable, handlers remain isolated, "
        "and all ten current sd namespaces are registered"
    )


def test_native_potion_pickup_converges_into_stock_inventory() -> str:
    native_inventory = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl"
    )
    replicated_loot = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    dispatch = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks.inl"
    )
    authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl"
    )
    transport_api = _read_many(
        "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_api.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/public_cast_loot_queue_api.inl",
    )
    native_types = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"
    )
    seams = _read("SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl")
    layout = _read("config/binary-layout.ini")

    assert len(replicated_loot.splitlines()) < 1000
    assert '#include "native_inventory_reconciliation.inl"' in dispatch
    assert "InventoryInsertOrStackItemFn" in native_types
    assert "allow_potion_stacking" in native_types
    assert "remove_placeholder" in native_types
    assert '"inventory_insert_or_stack_item"' in seams
    assert "inventory_insert_or_stack_item=0x0055FF20" in layout

    _require_in_order(
        authority,
        "PublishLootPickupResultRuntimeInfo(packet, now_ms);",
        "QueueNativePotionInventoryCredit(",
    )
    _require_in_order(
        native_inventory,
        "QueueNativePotionInventoryCreditInternal(",
        "pending_native_inventory_credit_drop_ids.insert(network_drop_id)",
    )
    _require_in_order(
        native_inventory,
        "ExecuteNativePotionInventoryCreditNow(",
        "kItemDropHeldItemOffset,",
        "cleared_held_item_address",
        "CallInventoryInsertOrStackItemSafe(",
        "expected_stack_after",
        "MarkLocalInventoryNativeConverged",
    )
    assert "completed_native_inventory_credit_drop_ids" in native_inventory
    assert "IsNativeInventoryCreditCompleted(snapshot.run_nonce" in replicated_loot
    assert "NativePotionInventoryCreditOutcome::ApplyStateUnknown" in pump
    assert "pending_native_potion_inventory_credits.push_back" in pump
    _require_in_order(
        transport_api,
        "bool MarkLocalInventoryNativeConverged(",
        "inventory_revision != inventory_revision",
        "inventory_host_authoritative = false",
    )

    return (
        "accepted remote potions transfer through the stock insertion ABI, "
        "verify native stack growth, deduplicate by run/drop, and release the ledger guard"
    )


def test_local_run_cast_prime_hydrates_actor_owned_visual_lanes() -> str:
    constants = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    prime = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "standalone_materialization_local_player_cast_state.inl"
    )
    getters = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    verifier = _read("tools/verify_multiplayer_player_visibility.py")

    assert "kStandaloneWizardHatVisualTypeId = 0x1B5D" in constants
    assert "kStandaloneWizardRobeVisualTypeId = 0x1B5E" in constants
    for token in (
        "bool LocalPlayerRunEquipVisualLanesReady(",
        "bool EnsureLocalPlayerRunEquipVisualLanes(",
        "kGameplayVisualSinkPrimaryOffset",
        "kGameplayVisualSinkSecondaryOffset",
        "AttachBuiltDescriptorToEquipVisualLane(",
        "[player-cast-prime] hydrated local run equip visual lanes.",
        "LocalPlayerRunEquipVisualLanesReady(after.equip_runtime)",
    ):
        assert token in prime, f"local player visual hydration lacks: {token}"

    prime_body = prime[prime.index("bool MaybePrimeLocalPlayerRunCastState(") :]
    _require_in_order(
        prime_body,
        "EnsureWizardActorEquipRuntimeHandles(",
        "EnsureLocalPlayerRunEquipVisualLanes(",
        "EnsureActorProgressionRuntimeFieldFromHandle(",
    )
    _require_in_order(
        getters,
        "if (state->equip_runtime_state_address != 0)",
        "kActorEquipRuntimeVisualLinkPrimaryOffset",
        "if (resolved_gameplay_address && state->equip_runtime_state_address == 0)",
    )
    for token in (
        "RUN_ENTRY_FORMATION_RELEASE_SECONDS = 5.25",
        'result["hub_screenshots"]',
        'result["run_screenshots"]',
        "VISIBILITY_PAIR_HALF_SEPARATION = 100.0",
    ):
        assert token in verifier, f"visibility verifier lacks: {token}"

    return (
        "local run cast priming clones the stock gameplay robe/hat descriptor "
        "into the actor-owned equip runtime and captures separated hub/run views"
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
    incoming = _read(
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
        "packet.in_run = 0;",
        "packet.transform_valid = 0;",
        "packet.run_nonce = run_exit_nonce;",
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
    verifier = _read("tools/verify_flat_multiplayer_boneyard.py")

    assert '#include "test_blank_boneyard_reconciliation.inl"' in dispatch
    assert "ReconcileExplicitTestBlankBoneyard(" in pump
    assert '"SDMOD_TEST_BLANK_BONEYARD"' in blank_runtime
    assert "length == 1 && value[0] == '1'" in blank_runtime
    assert "IsExpectedBlankBoneyardSceneryType" in blank_runtime
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
    assert "test_blank_boneyard=True" in verifier
    assert "wait_for_blank_arena_census(HOST_PIPE)" in verifier
    assert "wait_for_blank_arena_census(CLIENT_PIPE)" in verifier
    for zero_count in (
        'last.get("scenery_count", "-1")',
        'last.get("road_count", "-1")',
        'last.get("fence_count", "-1")',
        'last.get("static_circle_count", "-1")',
        'last.get("scenery_circle_count", "-1")',
    ):
        assert zero_count in verifier

    return (
        "the opt-in flat test removes only known native scenery/road/fence "
        "objects, clears all native circle/cell collision indexes, and verifies both peers"
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

    return (
        "progression matrices suppress stock waves before entering the run so "
        "combat cannot invalidate participant-owned stat and skill observations"
    )


def test_spell_verifiers_quiesce_input_and_prearm_manual_spawning() -> str:
    level_up_verifier = _read("tools/verify_multiplayer_level_up_offer_sync.py")
    _require_in_order(
        level_up_verifier,
        "cleanup = cleanup_live_enemies()",
        "pair = build_manual_pair(",
        "receiver_offset = len(read_log(HOST_LOG))",
        "cast = cast_fireball_pair(",
    )
    _require_in_order(
        level_up_verifier,
        'output["manual_spawner_prearm"] = {',
        'output["run_entry"] = start_host_testrun_and_wait_for_clients(',
    )
    _require_in_order(
        level_up_verifier,
        "combat = enable_progression_neutral_combat()",
        "baseline_fireball_cast = verify_client_fireball_cast_on_host(",
    )

    targeted_matrix = _read("tools/verify_multiplayer_targeted_spell_matrix.py")
    _require_in_order(
        targeted_matrix,
        '"host": set_manual_spawner_test_mode(HOST_PIPE, True)',
        '"client": set_manual_spawner_test_mode(CLIENT_PIPE, True)',
        "run_entry = start_host_testrun_and_wait_for_clients()",
    )

    shared_effect_harness = _read(
        "tools/verify_multiplayer_fireball_explode_effect_sync.py"
    )
    _require_in_order(
        shared_effect_harness,
        '"host": set_manual_spawner_test_mode(HOST_PIPE, True)',
        '"client": set_manual_spawner_test_mode(CLIENT_PIPE, True)',
        "run_entry = start_host_testrun_and_wait_for_clients(timeout=timeout)",
    )
    embers_verifier = _read(
        "tools/verify_multiplayer_fireball_embers_effect_sync.py"
    )
    assert "launch_pair_ready(timeout)" in embers_verifier

    faster_caster_verifier = _read(
        "tools/verify_multiplayer_faster_caster_behavior_sync.py"
    )
    _require_in_order(
        faster_caster_verifier,
        "manual_combat=True",
        'phase["manual_combat"] = startup["manual_combat"]',
        "measure_cadence(direction, timeout)",
    )
    assert "ensure_host_combat_started" not in faster_caster_verifier
    assert "enable_unsuppressed_combat_prelude" not in faster_caster_verifier
    assert faster_caster_verifier.count("clear_local_cast_state(direction)") == 2
    assert "arm_cadence_burst(direction, required_casts)" in faster_caster_verifier
    assert "for _ = 2, {required_casts} do" in faster_caster_verifier

    return (
        "focused spell verifiers quiesce input, use frozen manual targets, and "
        "prearm stock-wave suppression before run entry"
    )


def test_meditation_transient_counters_self_repair_to_native_bounds() -> str:
    layout = _read("config/binary-layout.ini")
    offsets = _read(
        "SolomonDarkModLoader/src/gameplay_seams/progression_and_actor_offsets.inl"
    )
    bindings = _read("SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl")
    hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )
    verifier = _read("tools/verify_multiplayer_meditation_behavior_sync.py")

    for token in (
        "progression_meditation_idle_elapsed_ticks=0x888",
        "progression_meditation_recovery_ramp_ticks=0x88C",
    ):
        assert token in layout, f"Meditation transient layout lacks: {token}"
    for token in (
        "kProgressionMeditationIdleElapsedTicksOffset",
        "kProgressionMeditationRecoveryRampTicksOffset",
    ):
        assert token in offsets, f"Meditation transient seam lacks: {token}"
        assert token in bindings, f"Meditation transient binding lacks: {token}"

    _require_in_order(
        hook,
        "void RepairInvalidNativeMeditationTransientState(uintptr_t actor_address)",
        "idle_ticks < -1",
        "const auto maximum_ramp_ticks = (std::max)(idle_ticks, 0);",
        "recovery_ramp_ticks < 0 || recovery_ramp_ticks > maximum_ramp_ticks",
        "kProgressionMeditationRecoveryRampTicksOffset,\n                       0",
        "RepairInvalidNativeMeditationTransientState(actor_address);",
        "if (multiplayer::ShouldPauseGameplayForLevelUpSelection())",
    )
    for token in (
        "def query_mana_view(",
        "write_idle_elapsed",
        'window_rate(samples, 1.25, 2.05)',
        "late_rate * 0.40 <= moving_late_rate <= late_rate * 0.60",
    ):
        assert token in verifier, f"Meditation live verifier lacks: {token}"

    return (
        "impossible stock Meditation counters self-repair before actor ticks, "
        "while live tests distinguish full stationary and half moving recovery"
    )


def test_level_up_barrier_waits_for_every_player_and_times_out() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    barrier = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "level_up_barrier_sync.inl"
    )
    authority = _read_many(
        "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_authority.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_debug_authority.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_barrier_authority.inl",
    )
    choices = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "level_up_packet_sync.inl"
    )
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    incoming = _read_many(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_cast_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_snapshot_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_dispatch.inl",
    )
    public_api = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    lifecycle = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "remote_peer_lifecycle.inl"
    )
    level_hook = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    lua_runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 52;",
        "LevelUpBarrier = 19",
        "struct LevelUpBarrierPacket",
        "kLevelUpChoiceResultFlagAutoPicked",
        "kLevelUpBarrierParticipantFlagDisconnected",
        "static_assert(sizeof(LevelUpBarrierPacket) == 308",
    ):
        assert token in protocol, f"level-up barrier protocol lacks: {token}"

    for token in (
        "kHostLevelUpBarrierTimeoutMs = 60'000",
        "kHostLevelUpBarrierBroadcastIntervalMs = 250",
        "kHostLevelUpBarrierResumeBroadcastMs = 3'000",
        "BeginOrExtendHostLevelUpBarrier(",
        "CompleteHostLevelUpBarrierIfReady(",
        "MarkHostLevelUpBarrierParticipantDisconnected(",
        "ApplyAuthoritativeLevelUpWaitStatus(",
        "packet.barrier_id < current.barrier_id",
        "packet.revision < current.revision",
        "ApplyLevelUpChoiceResultPacket(result, from, now_ms);",
    ):
        assert token in barrier, f"level-up barrier runtime lacks: {token}"

    _require_in_order(
        level_hook,
        "SyncBotsToSharedLevelUp(level_after, xp_after, progression_address)",
        "PublishHostLevelUpBarrierOffers(",
        "DispatchLuaLevelUp(level_after, xp_after)",
    )
    _require_in_order(
        authority,
        "void PublishHostLevelUpBarrierOffers(",
        "BeginOrExtendHostLevelUpBarrier(",
        "PublishHostLevelUpOffers(level, experience, source_progression_address);",
        "PublishLocalHostSelfLevelUpOffer(",
    )
    for token in (
        "TryAutoPickHostLevelUpBarrierParticipant(",
        "ProcessHostLevelUpBarrier(",
        "barrier.timed_out = true;",
        "ResolveHostSelfLevelUpChoice(",
        "ApplyParticipantSkillChoiceOption(",
        "BuildLevelUpChoiceResultPacket(",
        "MarkHostLevelUpBarrierParticipantResolved(result, true, now_ms);",
    ):
        assert token in authority, f"timeout auto-pick lacks: {token}"

    choice_handler = choices[
        choices.index("void ApplyLevelUpChoicePacket(") :
        choices.index("void ApplyLevelUpChoiceResultPacket(")
    ]
    assert choice_handler.count("offer.resolved = true;") == 1, (
        "only an accepted choice may resolve a barrier participant"
    )
    assert "MarkHostLevelUpBarrierParticipantResolved(result, false, now_ms);" in choices

    assert 'return "Waiting on " + std::to_string(participant_ids.size())' in local_state
    assert 'participant_ids.size() == 1 ? " player" : " players"' in local_state
    _require_in_order(
        public_api,
        "ProcessPendingHostLevelUpOffers(now_ms);",
        "ProcessHostLevelUpBarrier(now_ms);",
        "BroadcastHostLevelUpBarrierState(now_ms, false);",
        "SendLocalState(now_ms);",
    )
    assert "MarkHostLevelUpBarrierParticipantDisconnected(" in lifecycle
    assert "PacketKind::LevelUpBarrier" in incoming
    for token in (
        'lua_setfield(state, -2, "auto_picked")',
        'lua_setfield(state, -2, "timed_out")',
        'lua_setfield(state, -2, "barrier_id")',
        'lua_setfield(state, -2, "deadline_remaining_ms")',
    ):
        assert token in lua_runtime, f"Lua barrier observability lacks: {token}"

    return (
        "the host pauses one revisioned cohort, shows an exact waiting count, "
        "auto-picks at 60 seconds, and repeatedly broadcasts accepted results "
        "plus the final resume state"
    )
