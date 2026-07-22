"""Progression, level-up, and native lifecycle contracts."""

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
    _read,
    _read_many,
    _require_in_order,
    read_source_unit,
    read_source_units,
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

    third_observer = _read(
        "tools/verify_multiplayer_third_observer_upgrade_sync.py"
    )
    _require_in_order(
        third_observer,
        'output["quiet_progression_mode"] = enable_quiet_progression_mode()',
        'output["run_entry"] = start_trio_run(args.timeout)',
        'output["manual_combat"] = enable_flat_manual_cluster_combat()',
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
    assert faster_caster_verifier.count("clear_local_cast_state(direction)") == 4
    _require_in_order(
        faster_caster_verifier,
        "target = prepare_primary_target(direction)",
        "arm_cadence_burst(",
        "int(target[\"source_actor_address\"])",
    )
    assert "spawn_one_enemy(target_x, target_y, setup_hp=SETUP_TARGET_HP)" in faster_caster_verifier
    assert faster_caster_verifier.count(
        "host_target = wait_for_target_hp_at_least("
    ) == 1
    _require_in_order(
        faster_caster_verifier,
        "host_target = wait_for_target_hp_at_least(",
        "HOST_PIPE,",
        "network_id,",
        "SETUP_TARGET_HP,",
        "require_local_binding=False,",
        "before_hp = parse_float(target[\"host_target\"].get(\"snapshot.hp\"), 0.0)",
    )
    assert "prepare_and_queue_caster(" in faster_caster_verifier
    assert "primary_entry not in DISCRETE_PRIMARY_ENTRIES" in faster_caster_verifier
    assert "MEASURED_INTERVAL_COUNT = 10" in faster_caster_verifier
    assert "measured_intervals = intervals[WARMUP_INTERVAL_COUNT:]" in faster_caster_verifier
    assert "expected_ratio = baseline_multiplier / multiplier" in faster_caster_verifier
    assert "for _ = 2, {required_casts} do" in faster_caster_verifier
    for continuous_token in (
        "primary_entry not in CONTINUOUS_PRIMARY_ENTRIES",
        "wait_for_continuous_channel_window(",
        "remote_count = wait_for_remote_delivery(",
        'observation["damage_associated_skill_id"] != primary_entry',
        '"authoritative_damage_per_second"',
        "expected_ratio = upgraded_multiplier / baseline_multiplier",
        'parse_int(last.get("rep.tracked_actor_count")) == 0',
        'parse_int(last.get("rep.binding_count")) == 0',
        'parse_int(last.get("rep.local_actor_count")) == 0',
    ):
        assert continuous_token in faster_caster_verifier

    primary_kill_verifier = _read(
        "tools/verify_multiplayer_primary_kill_stress.py"
    )
    assert 'emit("rep.tracked_actor_count", replicated_tracked_actor_count)' in primary_kill_verifier

    outgoing_cast_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_cast_packet_sync.inl"
    )
    assert outgoing_cast_sync.count("RememberRecentLocalCast(packet, now_ms);") == 2
    _require_in_order(
        outgoing_cast_sync,
        "void SendActiveLocalCastInput(std::uint64_t now_ms)",
        "RememberRecentLocalCast(packet, now_ms);",
        "SendCastPacketToEndpoints(packet, endpoints);",
        "g_local_transport.active_local_cast_input = ActiveLocalCastInput{};",
    )

    return (
        "focused spell verifiers quiesce input, use frozen manual targets, keep "
        "held-channel tail damage associated, and prearm stock-wave suppression "
        "before run entry"
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
        "idle_ticks == -1",
        "recovery_ramp_ticks < -1 || recovery_ramp_ticks > 0",
        "recovery_ramp_ticks < 0 ||",
        "recovery_ramp_ticks > maximum_ramp_ticks",
        "kProgressionMeditationRecoveryRampTicksOffset,\n                       0",
        "RepairInvalidNativeMeditationTransientState(actor_address);",
        "if (multiplayer::ShouldPauseMultiplayerGameplay())",
    )
    for token in (
        "def query_mana_view(",
        "write_idle_elapsed",
        "cast_observed = cast_observed or (",
        "if 0 <= idle_elapsed <= 25:",
        "reset_observed = True",
        '"reset_sample": reset_sample',
        'window_rate(samples, 1.25, 2.05)',
        "late_rate * 0.40 <= moving_late_rate <= late_rate * 0.60",
    ):
        assert token in verifier, f"Meditation live verifier lacks: {token}"

    return (
        "impossible stock Meditation counters self-repair before actor ticks, "
        "while live tests distinguish full stationary and half moving recovery"
    )


def test_level_up_barrier_waits_for_forced_picker_confirmation() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    barrier = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "level_up_barrier_sync.inl"
    )
    offer_authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_authority.inl"
    )
    authority = _read_many(
        "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_authority.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_debug_authority.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/level_up_barrier_authority.inl",
    )
    choices = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "level_up_packet_sync.inl"
    )
    picker = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "level_up_choice_and_picker.inl"
    )
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    incoming = read_source_units(
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
    native_progression = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "native_progression_sync.inl"
    )
    transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport.cpp"
    )
    verifier = _read("tools/verify_multiplayer_level_up_barrier_sync.py")
    level_hook = read_source_unit(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    lifecycle_targets = _read(
        "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl"
    )
    lifecycle_install = _read(
        "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl"
    )
    gameplay_seams = _read(
        "SolomonDarkModLoader/src/gameplay_seams.h"
    )
    binary_layout = _read("config/binary-layout.ini")
    lua_runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    overlay_frame = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "label_resolution_surface_registry_and_frame_render.inl"
    )
    overlay_wait = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "gameplay_level_up_wait_rendering.inl"
    )
    gameplay_hud = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "gameplay_hud_hooks.inl"
    )

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 70;",
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

    result_handler = choices[
        choices.index("void ApplyLevelUpChoiceResultPacket(") :
    ]
    _require_in_order(
        result_handler,
        "std::unique_lock<std::recursive_mutex> picker_lock(",
        "if (packet.target_participant_id == g_local_transport.local_peer_id)",
        "picker_lock.lock();",
        "UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);",
        "const auto result_code = LevelUpChoiceResultCodeFromPacketValue(packet.result_code);",
        "g_local_transport.native_applied_level_up_result_offer_ids.find(",
        "return;",
        "if (result_code == LevelUpChoiceResultCode::Accepted) {",
        "ClearLocalLevelUpPickerAfterProgrammaticChoice(",
        "PublishLevelUpChoiceResultRuntimeInfo(packet, now_ms);",
    )
    assert "duplicate_result" not in result_handler

    for token in (
        "std::recursive_mutex g_local_level_up_picker_mutex;",
        "Keep the lock order picker -> runtime state",
        "RuntimeState update lambdas must not call",
    ):
        assert token in transport, f"local picker synchronization lacks: {token}"
    reconcile = picker[
        picker.index("void ReconcileLocalLevelUpOfferPresentation(") :
    ]
    _require_in_order(
        reconcile,
        "std::lock_guard<std::recursive_mutex> picker_lock(",
        "const auto runtime_state = SnapshotRuntimeState();",
        "const auto offer = runtime_state.active_level_up_offer;",
        "if (!offer.valid ||",
        "TryPresentLocalLevelUpPicker(",
    )
    for entry_point in (
        "bool ResolveHostSelfLevelUpChoice(",
        "bool QueueLocalLevelUpChoiceInternal(",
    ):
        guarded_entry = picker[picker.index(entry_point) :]
        _require_in_order(
            guarded_entry,
            "std::lock_guard<std::recursive_mutex> picker_lock(",
            "g_local_level_up_picker_mutex",
            "SnapshotRuntimeState()" if "QueueLocal" in entry_point else "issued_level_up_offers_by_id.find(offer_id)",
        )
    local_offer_handler = choices[
        choices.index("void ApplyLevelUpOfferPacket(") :
        choices.index("void ApplyLevelUpChoicePacket(")
    ]
    _require_in_order(
        local_offer_handler,
        "std::lock_guard<std::recursive_mutex> picker_lock(",
        "SnapshotRuntimeState();",
        "state.active_level_up_offer = std::move(offer);",
    )
    host_self_offer = offer_authority[
        offer_authority.index("bool IssueLocalHostSelfLevelUpOffer(") :
        offer_authority.index("void PublishLocalHostSelfLevelUpOffer(")
    ]
    _require_in_order(
        host_self_offer,
        "std::lock_guard<std::recursive_mutex> picker_lock(",
        "SnapshotRuntimeState();",
        "state.active_level_up_offer = std::move(offer);",
    )
    _require_in_order(
        lifecycle,
        "std::unique_lock<std::recursive_mutex> picker_lock(",
        "if (configured_authority_disconnected)",
        "picker_lock.lock();",
        "state.active_level_up_offer = LevelUpOfferRuntimeInfo{};",
    )

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

    issue_remote_offer = offer_authority[
        offer_authority.index("bool IssueHostLevelUpOfferForParticipant(") :
        offer_authority.index("HostLevelUpOfferPublishResult TryPublishHostLevelUpOfferForParticipant(")
    ]
    _require_in_order(
        issue_remote_offer,
        "HasUnresolvedIssuedLevelUpOfferForParticipant(target_participant_id)",
        "BeginOrExtendHostLevelUpBarrier(",
        "g_local_transport.issued_level_up_offers_by_id[offer_id] = issued_offer;",
    )
    publish_remote_offer = offer_authority[
        offer_authority.index("HostLevelUpOfferPublishResult TryPublishHostLevelUpOfferForParticipant(") :
        offer_authority.index("void ProcessPendingHostLevelUpOffers(")
    ]
    reentrant_offer_tokens = (
        "ScopedLocalLevelUpFanoutSuppression suppress_fanout;",
        "SyncParticipantProgressionToSharedLevelUpAndRollChoices(",
        "if (HasUnresolvedIssuedLevelUpOfferForParticipant(participant.participant_id))",
        "if (!IssueHostLevelUpOfferForParticipant(",
    )
    for token in reentrant_offer_tokens:
        assert token in publish_remote_offer, (
            f"reentrant native progression sync can duplicate a participant offer: {token}"
        )
    _require_in_order(publish_remote_offer, *reentrant_offer_tokens)
    for token in (
        "TryAutoPickHostLevelUpBarrierParticipant(",
        "ProcessHostLevelUpBarrier(",
        "barrier.timed_out = true;",
        "ResolveHostSelfLevelUpChoice(",
        "ApplyAuthoritativeRemoteSkillRankDelta(",
        "BuildLevelUpChoiceResultPacket(",
        "offer.auto_picked = true;",
        "barrier_participant->auto_picked = true;",
        "SendPacketToParticipantOrPeers(result, participant_id);",
        "waiting for native picker confirmation",
    ):
        assert token in authority, f"confirmed timeout auto-pick lacks: {token}"

    assert barrier.count("participant.last_offer_attempt_ms = now_ms;") == 2, (
        "a newly opened or extended barrier can race its initial offer publisher"
    )
    for token in (
        "void DisarmLocalLevelUpOptionRollForOffer(std::uint64_t offer_id)",
        "g_armed_local_level_up_option_roll.offer_id == offer_id",
        "DisarmLocalLevelUpOptionRollForOffer(packet.offer_id);",
        "DisarmLocalLevelUpOptionRollForOffer(offer_id);",
    ):
        assert token in choices, (
            f"a resolved picker can contaminate the next native option roll: {token}"
        )

    remote_auto_pick = authority[
        authority.index("bool TryAutoPickHostLevelUpBarrierParticipant(") :
        authority.index("void ProcessHostLevelUpBarrier(")
    ]
    assert "MarkHostLevelUpBarrierParticipantResolved(" not in remote_auto_pick, (
        "a forced remote choice must not release the barrier before client confirmation"
    )
    assert remote_auto_pick.count(
        "SendPacketToParticipantOrPeers(result, participant_id);"
    ) == 2, "forced results must be repeated until the client confirms native cleanup"

    for token in (
        "CallLevelUpScreenCloseSafe(screen_address, &close_exception)",
        "native picker close failed; synchronized pause retained",
        "else if (offer.auto_picked)",
        "auto_pick_confirmation = true;",
        "SendPacketToEndpoint(confirmation, from);",
        "MarkHostLevelUpBarrierParticipantResolved(\n            result,\n            auto_pick_confirmation,",
    ):
        assert token in choices, f"forced picker confirmation lacks: {token}"
    assert choices.count("SendPacketToEndpoint(confirmation, from);") == 2
    _require_in_order(
        choices,
        "else if (offer.auto_picked)",
        "auto_pick_confirmation = true;",
        "MarkHostLevelUpBarrierParticipantResolved(",
    )

    choice_handler = choices[
        choices.index("void ApplyLevelUpChoicePacket(") :
        choices.index("void ApplyLevelUpChoiceResultPacket(")
    ]
    for token in (
        "const auto* resolved_participant =",
        "resolved_participant->offer_id == packet.offer_id",
        "result_code = LevelUpChoiceResultCode::Accepted;",
        "auto_pick_confirmation = resolved_participant->auto_picked;",
    ):
        assert token in choice_handler, (
            f"duplicate forced confirmation is not idempotently accepted: {token}"
        )
    assert choice_handler.count("offer.resolved = true;") == 2, (
        "manual acceptance and confirmed forced acceptance must be the only resolution paths"
    )
    _require_in_order(
        choice_handler,
        "} else if (offer.auto_picked)",
        "result_code = LevelUpChoiceResultCode::Accepted;",
        "auto_pick_confirmation = true;",
        "offer.resolved = true;",
        "} else if (!ApplyAuthoritativeRemoteSkillRankDelta(",
        "result_code = LevelUpChoiceResultCode::Accepted;",
        "offer.resolved = true;",
    )
    assert "ApplyParticipantSkillChoiceOption(" not in (
        authority + choices + native_progression
    ), "observer level-up replication must not execute stock skill-choice side effects"

    for token in (
        "current.result_code == LevelUpChoiceResultCode::Accepted",
        "incoming_result_code != LevelUpChoiceResultCode::Accepted",
    ):
        assert token in choices, (
            f"accepted level-up result can be downgraded by a late packet: {token}"
        )

    for token in (
        "defer_progression_book_reconcile",
        "HasUnresolvedIssuedLevelUpOfferForParticipant(",
    ):
        assert token in native_progression, (
            f"unresolved remote level-up can race native rank reconciliation: {token}"
        )
    _require_in_order(
        native_progression,
        "defer_progression_book_reconcile",
        "NativeProgressionBookTableView table;",
        "if (defer_progression_book_reconcile)",
        "for (const auto& desired : participant.owned_progression.progression_book_entries)",
    )

    for token in (
        "confirmed_auto_pick_level_up_offer_ids",
        "native_active_after == packet.resulting_active",
        "auto-pick native rank verification failed; synchronized pause retained",
    ):
        assert token in transport + choices, (
            f"forced result confirmation is not exact and one-shot: {token}"
        )
    _require_in_order(
        choices,
        "confirmed_auto_pick_level_up_offer_ids.insert(",
        "packet.offer_id).second",
        "if (send_auto_pick_confirmation)",
        "SendPacketToEndpoint(confirmation, from);",
    )

    for token in (
        "--normal-only",
        'resulting_active == expected_client_active',
        'resulting_active == selected_baseline["expected_active"]',
        'host_remote_entry["active"] == resulting_active',
        'client_local_entry["active"] == resulting_active',
        "confirmation_send_count != 1",
        "world_activity_probe",
        "pause_position_drift",
        "resumed_position_drift",
        'source=dx9_level_up_barrier ok=1 ',
        "through the native DX9 overlay",
    ):
        assert token in verifier, f"live exact-rank regression lacks: {token}"

    for token in (
        "multiplayer::TryBuildLevelUpWaitStatusText(",
        "gameplay_level_up_wait_text.empty()",
        "DrawGameplayLevelUpWaitStatus(",
        "LogGameplayLevelUpWaitStatusDraw(",
    ):
        assert token in overlay_frame, f"DX9 level-up wait frame path lacks: {token}"
    for token in (
        "GameplayLevelUpWaitDrawResult DrawGameplayLevelUpWaitStatus(",
        "DrawFilledRect(",
        "DrawRectOutline(",
        "DrawLabelText(",
        'source=dx9_level_up_barrier',
    ):
        assert token in overlay_wait, f"DX9 level-up wait renderer lacks: {token}"
    assert "DrawGameplayHudLevelUpWaitStatusForHudPass" not in gameplay_hud

    for token in (
        "actor_world_tick=0x004022A0",
        "actor_world_actor_count=0x08",
        "actor_world_actor_array=0x14",
        "actor_world_current_actor=0x48",
        "actor_pending_initialize=0x04",
        "actor_pending_remove=0x05",
        "actor_vtable_initialize=0x04",
        "actor_vtable_tick=0x08",
    ):
        assert token in binary_layout, f"actor-world pause layout lacks: {token}"
    for token in (
        "kActorWorldTick",
        "kActorWorldActorCountOffset",
        "kActorWorldActorArrayOffset",
        "kActorWorldCurrentActorOffset",
        "kActorPendingInitializeOffset",
        "kActorPendingRemoveOffset",
        "kActorVtableInitializeOffset",
        "kActorVtableTickOffset",
    ):
        assert token in gameplay_seams, f"actor-world pause seams lack: {token}"
    for token in (
        "kHookActorWorldTick",
        "targets[kHookActorWorldTick] = {kActorWorldTick, 6};",
    ):
        assert token in lifecycle_targets, f"actor-world pause hook target lacks: {token}"
    for token in (
        "reinterpret_cast<void*>(&HookActorWorldTick)",
        '"actor_world.tick"',
    ):
        assert token in lifecycle_install, f"actor-world pause install lacks: {token}"
    actor_world_hook = level_hook[
        level_hook.index("void __fastcall HookActorWorldTick(") :
        level_hook.index("void __fastcall HookWaveSpawnerTick(")
    ]
    for token in (
        "multiplayer::ShouldPauseMultiplayerGameplay()",
        "resolved_player_actor_tick",
        "actor_tick_address != resolved_player_actor_tick",
        "actor_initialize(actor);",
        "actor_tick(actor);",
    ):
        assert token in actor_world_hook, f"actor-world level-up pause lacks: {token}"
    _require_in_order(
        actor_world_hook,
        "if (!multiplayer::ShouldPauseMultiplayerGameplay())",
        "original(self, unused_edx);",
        "actor_tick_address != resolved_player_actor_tick",
        "actor_tick(actor);",
    )

    for token in (
        "offer.local_progression_applied &&",
        "native_picker_local_apply_observed",
        "if (!offer.local_progression_applied)",
        "offer.local_progression_applied = true;",
        "host-self level-up retry does not match the already-applied option",
    ):
        assert token in picker, f"host-self picker idempotence lacks: {token}"
    _require_in_order(
        picker,
        "if (!offer.local_progression_applied)",
        "ApplyLocalPlayerSkillChoiceOption(option, &apply_error)",
        "offer.local_progression_applied = true;",
        "ClearLocalLevelUpPickerAfterProgrammaticChoice(",
    )

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
        "forces timed-out choices through the connected client's native picker, "
        "and resumes only after confirmed native cleanup"
    )


def test_level_up_choice_result_advances_owned_book_before_resume() -> str:
    owned_progression = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "owned_progression_state.inl"
    )
    choices = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "level_up_packet_sync.inl"
    )
    incoming_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_participant_state_sync.inl"
    )
    level_up_verifier = _read(
        "tools/verify_multiplayer_level_up_offer_sync.py"
    )
    kill_stress = _read(
        "tools/verify_multiplayer_primary_kill_stress.py"
    )

    for token in (
        "bool ApplyAuthoritativeProgressionBookEntryState(",
        "entry->active = resulting_active;",
        "entry->visible = resulting_visible;",
        "owned_progression->spellbook_revision += 1;",
        "owned_progression->statbook_revision += 1;",
    ):
        assert token in owned_progression, (
            f"authoritative progression-book mutation lacks: {token}"
        )

    publish_start = choices.index("void PublishLevelUpChoiceResultRuntimeInfo(")
    publish_end = choices.index(
        "bool ClearLocalLevelUpPickerAfterProgrammaticChoice(",
        publish_start,
    )
    publish = choices[publish_start:publish_end]
    _require_in_order(
        publish,
        "if (result.result_code != LevelUpChoiceResultCode::Accepted)",
        "ApplyAuthoritativeProgressionBookEntryState(",
        "participant->character_profile.level = packet.level;",
    )

    # The authority/result mutation advances both revisions. Therefore a
    # pre-choice state packet with the old revision fails these gates instead
    # of rolling the accepted rank back before the owner's next checkpoint.
    for token in (
        "packet.statbook_revision >= participant->owned_progression.statbook_revision",
        "packet.spellbook_revision >= participant->owned_progression.spellbook_revision",
    ):
        assert token in incoming_state, (
            f"progression-book packet revision gate lacks: {token}"
        )

    assert "def wait_for_progression_entry_active(" in level_up_verifier, (
        "live level-up verification must wait for the exact native rank on "
        "each owner/observer view"
    )
    assert "wait_for_progression_entry_active(" in kill_stress, (
        "primary-kill integration must use bounded native rank convergence"
    )

    return (
        "accepted level-up results advance the canonical owned book before "
        "barrier resume, so stale pre-choice checkpoints cannot roll native "
        "owner or observer ranks backward"
    )


def test_pointer_list_batch_rejects_stale_managed_release_callbacks() -> str:
    lifecycle_hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )
    constants = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    verifier = _read("tools/verify_multiplayer_ring_of_fire_multikill_stability.py")

    for token in (
        "kManagedPointerReleaseCallbackCellOffset = 0x00",
        "kManagedPointerReleaseCallbackEnabledOffset = 0x06",
        "kManagedPointerReleaseOwnerVtableOffset = 0x28",
        "kManagedPointerReleasePreflightMaxCount = 4096",
    ):
        assert token in constants, f"managed callback preflight lacks: {token}"

    preflight = lifecycle_hooks[
        lifecycle_hooks.index("int DisableStaleManagedPointerReleaseCallbacks(") :
        lifecycle_hooks.index("void __fastcall HookPointerListDeleteBatch(")
    ]
    for token in (
        "memory.ResolveGameAddressOrZero(kObjectDelete)",
        "self_vtable + kManagedPointerReleaseOwnerVtableOffset",
        "delete_callback != managed_pointer_release_callback",
        "callback_enabled == 0",
        "memory.IsExecutableRange(callback_address, 1)",
        "kManagedPointerReleaseCallbackEnabledOffset,\n                disabled",
    ):
        assert token in preflight, f"managed callback preflight lacks: {token}"

    hook = lifecycle_hooks[
        lifecycle_hooks.index("void __fastcall HookPointerListDeleteBatch(") :
        lifecycle_hooks.index("void LogSceneChurnActorWorldUnregisterCandidate(")
    ]
    _require_in_order(
        hook,
        "DisableStaleManagedPointerReleaseCallbacks(",
        "LogTrackedStandaloneWizardPuppetManagerDeleteBatchEvent(",
        "original(self, list);",
    )
    assert "stale_managed_callback_guard" in verifier
    assert "did not exercise the stale managed-callback seam" in verifier
    return "stale managed release callbacks are disabled before the stock batch dereference"


def test_steam_friend_native_inventory_matrix_is_wired() -> str:
    verifier = _read("tools/verify_steam_friend_native_inventory_sync.py")
    for token in (
        "SteamFriendActivePair()",
        "configure_modules(pair)",
        "disable_runtime_test_godmode(pair)",
        "gold.verify_gold_pickup_authority(shared_args)",
        "orb.verify_orb_pickup_authority(shared_args)",
        "native_potion.run(shared_args)",
        "for item_type in native_item.EQUIPPABLE_TYPE_IDS:",
        "native_item.run(",
        "loot.run_verifier(shared_args)",
        "SDMOD_STEAM_HOST_INSTANCE",
        "SDMOD_STEAM_CLIENT_INSTANCE",
    ):
        assert token in verifier, f"real-Steam native inventory matrix lacks: {token}"
    return "real Steam covers gold, both orbs, native potion, every equipment type, and loot materialization"


def test_steam_friend_active_run_reconnect_is_wired() -> str:
    verifier = _read("tools/verify_steam_friend_active_run_reconnect.py")
    for token in (
        'read_text().strip() != "SolomonDark.exe"',
        "stop_exact_game(args.old_client_instance",
        "wait_for_host_participant_absence(",
        "wait_for_authenticated_peers(host_status, 0",
        "SESSION_RESET_MARKER",
        "new_pair.client_participant_id != old_client_id",
        "old_proxy_was_removed_before_rejoin",
        '"address_reuse_allowed": True',
        '"gold_revision": 1',
        '"inventory_revision": 1',
        '"equipment_revision": 1',
        '"spellbook_revision": 1',
        '"statbook_revision": 1',
        '"loadout_revision": 1',
        'or observer["inventory_host_authoritative"]',
        "replacement retained host-authored inventory authority state",
        "previous_revisions[key] > actual_revisions[key]",
        '"all_revisions_strictly_decreased": True',
        "inventory_identities(old_owner)",
        "equipment_identities(old_owner)",
        "native_item.EQUIPPABLE_TYPE_IDS",
        "mutated_identities &",
        "progression.compare_book_rows(",
        "stats.wait_for_derived_parity(",
        "no_late_stale_state",
        'stage/.sdmod/multiplayer-compatibility.json',
        'document["compatibility"]["loader"]["sha256"]',
        "host_loader_sha256 != client_loader_sha256",
    ):
        assert token in verifier, f"real-Steam active-run reconnect lacks: {token}"
    for forbidden in ("pkill", "killall", "wineserver -k", "Stop-Process"):
        assert forbidden not in verifier, (
            f"active-run reconnect must stop only the exact game process: {forbidden}"
        )
    return "real Steam same-identity reconnect destroys the old proxy, starts a clean epoch, and rejects stale owned state"


def test_orb_pickup_verifier_preserves_native_maxima() -> str:
    verifier = _read("tools/verify_multiplayer_orb_pickup_authority.py")
    for token in (
        "def capture_client_vitals()",
        "def set_client_resources(",
        'result["baseline_client_vitals"] = baseline',
        'result["final_client_vitals"] = capture_client_vitals()',
        "wait_for_host_client_native_maxima(",
        'result["native_maxima_preserved"]',
        '"accepted_native_max_preserved"',
        '"accepted_result_includes_full_delta"',
        '"pickup_range": parse_float_text(',
    ):
        assert token in verifier, f"orb pickup verifier lacks test isolation: {token}"
    for forbidden in (
        "sd.debug.write_float(progression + omaxhp",
        "sd.debug.write_float(progression + omaxmp",
    ):
        assert forbidden not in verifier, (
            f"orb pickup verifier must preserve progression-derived maxima: {forbidden}"
        )
    orb_rows = verifier[
        verifier.index("def orb_rows(") :
        verifier.index("def loot_orb_rows(")
    ]
    participant_rows = verifier[
        verifier.index("def participant_rows(") :
        verifier.index("def find_participant(")
    ]
    assert '"pickup_range"' not in orb_rows, (
        "pickup range belongs to participant progression, not native orb rows"
    )
    assert '"pickup_range"' in participant_rows, (
        "participant pickup range must feed the natural proximity geometry check"
    )
    return "orb pickup verification preserves native maxima while retaining genuine authoritative results"


def test_primary_spell_effect_snapshots_do_not_fight_native_replay() -> str:
    reconciliation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "spell_effect_reconciliation.inl"
    )
    for token in (
        "bool IsNativeReplayDrivenPrimarySpellEffect(",
        "kReplicatedEtherPrimaryNativeTypeId",
        "kReplicatedFireballPrimaryNativeTypeId",
        "kReplicatedWaterPrimaryNativeTypeId",
        "const bool native_replay_driven_primary =",
        "effect.transform_valid && !native_replay_driven_primary",
        "effect.motion_valid && !native_replay_driven_primary",
        "TryWriteReplicatedEmberRuntime(actor_address, effect)",
        "TryWriteReplicatedFirewalkerRuntime(",
    ):
        assert token in reconciliation, (
            f"spell-effect ownership contract lacks: {token}"
        )
    return (
        "native replay exclusively owns primary-projectile motion while "
        "replicated snapshots continue to synchronize child effects"
    )


def test_native_remote_fireball_converts_cast_heading_until_projectile_birth() -> str:
    playback = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_playback.inl"
    )
    documentation = _read("docs/spell-cast-cleanup-chain.md")

    for token in (
        "const bool live_cast_heading_valid =",
        "const bool fireball_heading_owns_native_initialization =",
        "ongoing_cast.active &&",
        "ongoing_cast.have_aim_heading &&",
        "ongoing_cast.selection_state_target ==",
        "ResolveNativePrimaryEntryForElement(0)",
        "!ongoing_cast.remote_per_cast_projectile_observed;",
        "NormalizeWizardActorHeadingForWrite(90.0f - ongoing_cast.aim_heading)",
        "NormalizeWizardActorHeadingForWrite(ongoing_cast.aim_heading)",
        ": binding->replicated_target_heading);",
        "ShortestHeadingDeltaDegrees(heading, next_heading)",
        "ApplyWizardActorFacingState(actor_address, next_heading);",
    ):
        assert token in playback, f"remote Fire direction ownership lacks: {token}"
    assert (
        "const float next_heading = binding->replicated_target_heading;"
        not in playback
    ), "replicated transform heading must not overwrite pre-birth Fire direction"

    for token in (
        "Fire (0x0053DC60)",
        "actor + 0x6C",
        "0x00410500",
        "Fireball + 0x13C/+0x140",
        "0x00529380",
        "90 - aim_heading",
        "per-cast projectile is observed",
        "already-created projectile.",
    ):
        assert token in documentation, f"Fire direction RE contract lacks: {token}"

    return (
        "native remote Fire casts convert presentation aim to native direction "
        "through projectile birth while every live cast keeps presentation facing"
    )


def test_native_remote_fireball_conversion_is_scoped_to_stock_fire() -> str:
    playback = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_playback.inl"
    )

    converted_heading = (
        "NormalizeWizardActorHeadingForWrite(90.0f - ongoing_cast.aim_heading)"
    )
    assert converted_heading in playback, (
        "remote Fire replay must invert the presentation heading before stock "
        "projectile initialization"
    )
    fire_guard = re.search(
        r"const bool fireball_heading_owns_native_initialization =(?P<body>.*?);",
        playback,
        re.DOTALL,
    )
    assert fire_guard is not None, "remote Fire heading guard was not found"
    for token in (
        "live_cast_heading_valid",
        "ongoing_cast.selection_state_target ==",
        "ResolveNativePrimaryEntryForElement(0)",
        "!ongoing_cast.remote_per_cast_projectile_observed",
    ):
        assert token in fire_guard.group("body"), (
            f"remote Fire heading conversion is not scoped to stock Fire: {token}"
        )
    assert (
        "NormalizeWizardActorHeadingForWrite(ongoing_cast.aim_heading)"
        in playback
    ), "non-Fire live casts must retain their presentation-facing heading"

    cardinal_cases = {
        90.0: 0.0,
        0.0: 90.0,
        270.0: 180.0,
        180.0: 270.0,
    }
    for presentation_heading, expected_native_heading in cardinal_cases.items():
        native_heading = (90.0 - presentation_heading) % 360.0
        assert native_heading == expected_native_heading

    return (
        "remote Fire replay alone converts cardinal presentation headings for "
        "stock projectile birth while other casts keep presentation facing"
    )


def test_lightning_manual_cluster_stays_inside_flat_arena_spatial_grid() -> str:
    relative_path = "tools/verify_multiplayer_lightning_chaining_effect_sync.py"
    source = _read(relative_path)
    tree = ast.parse(source, filename=relative_path)
    literals: dict[str, object] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                literals[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue

    anchor = literals.get("LIGHTNING_CLUSTER_ANCHOR")
    patterns = literals.get("CLUSTER_PATTERNS")
    assert isinstance(anchor, tuple) and len(anchor) == 2
    assert isinstance(patterns, tuple) and patterns

    lane_path = "tools/verify_multiplayer_primary_kill_stress.py"
    lane_tree = ast.parse(_read(lane_path), filename=lane_path)
    lane_offsets: object = None
    for node in lane_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "lane_candidates":
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "offsets"
                ):
                    lane_offsets = ast.literal_eval(statement.value)
                    break
    assert isinstance(lane_offsets, list) and lane_offsets
    furthest_x = max(
        float(anchor[0]) + float(lane_x) + float(offset_x)
        for lane_x, _ in lane_offsets
        for pattern in patterns
        for offset_x, _ in pattern
    )
    # Live Steam evidence on the stock flat fixture showed native grid cells at
    # x=1872 and null cells at x=1944. Keep every scripted target within the
    # observed-good surface instead of testing actors the game cannot query.
    assert furthest_x <= 1872.0, (
        f"manual Lightning cluster crosses the verified native grid: {furthest_x}"
    )

    build_start = source.index("def build_manual_cluster(")
    build_end = source.index("\ndef ", build_start + 1)
    build_manual_cluster = source[build_start:build_end]
    assert (
        "place_pair_on_clear_lane(direction, LIGHTNING_CLUSTER_ANCHOR)"
        in build_manual_cluster
    )
    return "manual Lightning cluster remains entirely inside the verified flat-arena spatial grid"


def test_boneyard_generator_skips_empty_candidate_interpolation() -> str:
    layout = _read("config/binary-layout.ini")
    seam_bindings = _read_many(
        "SolomonDarkModLoader/src/gameplay_seams.h",
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl",
        "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl",
    )
    patch_source = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/boneyard_generator_patch.inl"
    )
    lifecycle = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
    )
    debug_binding = _read_many(
        "SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp",
        "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_typed_readers_and_writers.inl",
    )
    steam_driver = _read("tools/drive_steam_friend_active_pair.py")
    run_reentry = _read("tools/verify_steam_friend_run_exit_reentry.py")

    assert "boneyard_empty_candidate_interpolation_branch=0x0063D78F" in layout
    assert seam_bindings.count("kBoneyardEmptyCandidateInterpolationBranch") == 3
    assert "0x3B, 0xFB, 0x7F, 0x04, 0x33, 0xC0, 0xEB, 0x09" in patch_source
    assert "0x85, 0xFF, 0x0F, 0x8E, 0xC2, 0x02, 0x00, 0x00" in patch_source
    assert "InstallBoneyardGeneratorPatch" in lifecycle
    assert "RestoreBoneyardGeneratorPatch" in lifecycle
    assert "LuaDebugSetRunGenerationSeed" in debug_binding
    assert '"set_run_generation_seed"' in debug_binding
    assert "SetPendingRunGenerationSeed(seed, &error_message)" in debug_binding
    assert '"--run-generation-seed"' in steam_driver
    assert "sd.debug.set_run_generation_seed" in steam_driver
    assert '"--run-generation-seed"' in run_reentry
    assert "drive.set_run_generation_seed" in run_reentry
    _require_in_order(
        lifecycle,
        "InstallBoneyardGeneratorPatch",
        "g_gameplay_keyboard_injection.initialized = true",
    )
    return "empty stock Boneyard candidate sets branch to cleanup before interpolation"


def test_native_item_recipe_selection_excludes_equipped_items() -> str:
    verifier = _read("tools/verify_multiplayer_native_item_inventory_sync.py")
    for token in (
        "local_owner = find_local_participant(client_inventory)",
        'equipped = local_owner["equipment"][slot]',
        'int(equipped["type_id"])',
        'int(equipped["recipe_uid"])',
        "owned_identities.add(identity)",
    ):
        assert token in verifier, f"native item recipe selection ignores equipped ownership: {token}"
    return "native item tests select recipes absent from both backpack and equipped native lanes"


def test_cpu_tick_stops_after_virtual_update_marks_object_for_removal() -> str:
    guard = _read("SolomonDarkModLoader/src/cpu_lifecycle_guard.cpp")
    seams = _read_many(
        "SolomonDarkModLoader/src/gameplay_seams.h",
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl",
        "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl",
    )
    layout = _read("config/binary-layout.ini")
    loader = _read("SolomonDarkModLoader/src/mod_loader.cpp")
    app_tick = _read("SolomonDarkModLoader/src/background_focus_bypass.cpp")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")

    for token in (
        "cpu_tick_post_update=0x0042781E",
        "cpu_tick_epilogue=0x004278B6",
        "kCpuTickPostUpdate",
        "kCpuTickEpilogue",
        'SDMOD_ADDR("gameplay.hooks", "cpu_tick_post_update", kCpuTickPostUpdate)',
        'SDMOD_ADDR("gameplay.hooks", "cpu_tick_epilogue", kCpuTickEpilogue)',
    ):
        assert token in layout + seams, f"CPU lifecycle seam lacks: {token}"

    for token in (
        "constexpr std::array<std::uint8_t, 10> kExpectedPostUpdateBytes",
        "0x80, 0x7B, 0x2C, 0x00",
        "0x75, 0x03",
        "0xFF, 0x43, 0x28",
        "0x57",
        "current_bytes != kExpectedPostUpdateBytes",
        "__declspec(naked) void DetourCpuPostUpdate()",
        "cmp byte ptr [ebx + 5], 0",
        "jmp dword ptr [g_cpu_post_update_trampoline]",
        "jmp dword ptr [g_cpu_tick_epilogue]",
        "ResolveGameAddressOrZero(kCpuTickEpilogue)",
        "InstallX86Hook(",
        "kExpectedPostUpdateBytes.size()",
    ):
        assert token in guard, f"post-update pending-remove guard lacks: {token}"

    detour = guard[
        guard.index("__declspec(naked) void DetourCpuPostUpdate()") :
        guard.index("}  // namespace", guard.index("__declspec(naked) void DetourCpuPostUpdate()"))
    ]
    assert "[ebx + 0x44]" not in detour
    assert "VirtualQuery" not in detour
    assert "__try" not in detour

    _require_in_order(
        loader,
        "InitializeBackgroundFocusBypass(",
        "InitializeCpuLifecycleGuard(",
        "InitializeSteamBootstrap()",
    )
    assert "ShutdownCpuLifecycleGuard();" in loader
    assert 'RunShutdownStep("CPU lifecycle guard", &ShutdownCpuLifecycleGuard);' in loader
    _require_in_order(
        app_tick,
        "original(app, edx);",
        "LogCpuLifecycleGuardActivity();",
    )
    assert '<ClCompile Include="src\\cpu_lifecycle_guard.cpp" />' in project

    return (
        "CPU objects stop immediately after their own update marks them for removal, "
        "before stock code can enter recycled child-manager storage"
    )


def test_frozen_manual_enemy_cell_membership_stays_position_coherent() -> str:
    gameplay_api = _read(
        "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    run_public_api = _read(
        "SolomonDarkModLoader/src/run_lifecycle/public_api_and_install.inl"
    )
    manual_spawning = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "manual_enemy_spawning.inl"
    )
    monster_pathfinding = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "monster_pathfinding_hook.inl"
    )
    movement_hook = monster_pathfinding.split(
        "bool ClearHostileTargetsForDeadWizardActor",
        1,
    )[0]
    _require_in_order(
        movement_hook,
        "std::uint32_t __fastcall HookBadguyMoveStep(",
        "TryGetRunLifecycleManualEnemyFreezePosition(",
        "RestoreRunLifecycleFrozenManualEnemyPosition(actor_address)",
        "return 1;",
        "IsBoundReplicatedRunEnemyActorForLocalClient(actor_address)",
        "return original(movement_context, actor, move_x, move_y);",
    )
    assert (
        "bool RestoreRunLifecycleFrozenManualEnemyPosition(uintptr_t actor_address);"
        in gameplay_api
    )
    restore_start = run_public_api.index(
        "bool RestoreRunLifecycleFrozenManualEnemyPosition("
    )
    restore_end = run_public_api.index("\nvoid ", restore_start)
    restore_body = run_public_api[restore_start:restore_end]
    _require_in_order(
        restore_body,
        "TryGetRunLifecycleManualEnemyFreezePosition(",
        "kActorPositionXOffset",
        "kActorPositionYOffset",
        "RebindSceneActorCell(actor_address, &rebind_error)",
    )
    assert "RestoreRunLifecycleFrozenManualEnemyPosition(actor_address)" in (
        manual_spawning
    )
    assert monster_pathfinding.count(
        "RestoreRunLifecycleFrozenManualEnemyPosition("
    ) == 2

    harness = _read("tools/multiplayer_secondary_behavior_harness.py")
    for token in (
        "REBIND_TARGET_NATIVE_SPATIAL_LUA",
        "QUERY_TARGET_NATIVE_SPATIAL_LUA",
        "TARGET_NATIVE_CELL_STABILITY_SECONDS = 0.6",
        "TARGET_NATIVE_CELL_MINIMUM_SAMPLES = 3",
        "def require_target_native_cell_stability(",
        'cell != expected_cells[label]',
        'position_error > 3.0',
        "native_spatial_stability = require_target_native_cell_stability(",
        '"native_spatial_stability": native_spatial_stability',
    ):
        assert token in harness, f"frozen target spatial regression lacks: {token}"

    return (
        "frozen host targets bypass stock movement and physical spell fixtures "
        "prove their rebound native cells remain stable"
    )


def test_steam_onboarding_waits_out_blocking_dialogs_and_scene_churn() -> str:
    driver = _read("tools/drive_steam_friend_active_pair.py")
    for token in (
        "READY_SCENE_STABILITY_SECONDS = 1.0",
        "BLOCKING_ONBOARDING_SURFACES = frozenset(",
        'last["surface"] == "dialog" and "dialog.primary" in available',
        'last["surface"] not in BLOCKING_ONBOARDING_SURFACES',
        "now - ready_since >= READY_SCENE_STABILITY_SECONDS",
        'actions.extend(created["actions"])',
        "ready_scene = \"\"",
        "ready_since = None",
    ):
        assert token in driver, f"Steam onboarding stability lacks: {token}"
    _require_in_order(
        driver,
        "last = query_navigation_state(pair, endpoint)",
        'last["surface"] == "dialog" and "dialog.primary" in available',
        'last["scene"] in ("hub", "testrun")',
        'last["surface"] not in BLOCKING_ONBOARDING_SURFACES',
        "now - ready_since >= READY_SCENE_STABILITY_SECONDS",
        'return {"scene": last["scene"], "actions": actions}',
    )
    create_branch = driver.split('elif last["surface"] == "create":', 1)[1].split(
        "if last[\"scene\"] not in",
        1,
    )[0]
    assert "continue" in create_branch
    assert 'return {"scene": created["scene"]' not in create_branch
    return (
        "native onboarding dismisses late blocking dialogs and requires a "
        "stable ready scene before starting multiplayer tests"
    )


def test_manual_primary_target_survives_stock_cursor_refresh() -> str:
    player_control = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_control_hooks.inl"
    )
    start = player_control.index("void __fastcall HookPurePrimarySpellStart(")
    body = player_control[start:]
    dispatch_start = body.index("InvokeWithBotProgressionSlotOwnerContext(")
    dispatch_end = body.index("&slot_owner_context);", dispatch_start)
    dispatch = body[dispatch_start:dispatch_end]
    _require_in_order(
        dispatch,
        "ApplyPinnedManualSpawnerPrimaryTarget(actor_address);",
        "original(self);",
    )
    _require_in_order(
        body,
        "original(self);",
        "ApplyPinnedManualSpawnerPrimaryTarget(actor_address);",
        "QueueLocalPlayerPrimaryCastForMultiplayer(actor_address);",
    )
    return (
        "manual primary casts pin their world target at native dispatch, then "
        "restore it before owner-authored packet capture"
    )


def test_new_run_retires_the_prior_host_run_exit_latch() -> str:
    header = _read("SolomonDarkModLoader/include/multiplayer_local_transport.h")
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    run_hooks = read_source_unit(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    packet_builder = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    assert "void NotifyLocalRunStarted();" in header
    _require_in_order(
        transport,
        "void NotifyLocalRunStarted()",
        "g_local_run_exit_latched_nonce.exchange(0, std::memory_order_acq_rel)",
        "g_local_transport.client_host_run_exit_follow.active",
        "g_local_transport.client_host_run_exit_follow = ClientHostRunExitFollow{};",
        '"Multiplayer new run retired prior run-exit state. role="',
        "void NotifyLocalRunEnded(std::string_view reason)",
    )
    assert run_hooks.count("multiplayer::NotifyLocalRunStarted();") == 2
    for hook_name in ("HookCreateArena", "HookStartGame"):
        hook = run_hooks.split(f"void __fastcall {hook_name}", 1)[1].split(
            "void ",
            1,
        )[0]
        _require_in_order(
            hook,
            "original(self, unused_edx);",
            "multiplayer::NotifyLocalRunStarted();",
            "DispatchLuaRunStarted();",
        )
    _require_in_order(
        packet_builder,
        "void ApplyLocalRunExitLatch(Packet* packet)",
        "g_local_run_exit_latched_nonce.load(std::memory_order_acquire)",
        "packet->in_run = 0;",
    )
    return (
        "stock-confirmed run entry retires the previous reliable exit latch "
        "before new participant frames can contradict the run intent"
    )
