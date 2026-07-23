"""Transport, snapshot, and world replication contracts."""

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
    _require_in_order,
    read_source_unit,
    read_source_units,
)

def test_app_thread_transport_verifier_tracks_named_cadence_gap() -> str:
    service_loop = _read(
        "SolomonDarkModLoader/src/multiplayer_service_loop.cpp"
    )
    _require_in_order(
        service_loop,
        "const auto tick_gap_ms = now_ms - g_last_gameplay_transport_tick_ms;",
        "if (tick_gap_ms < kServiceTickIntervalMs)",
        "if (tick_gap_ms >= kTransportTickGapDiagnosticMs)",
        "std::to_string(tick_gap_ms)",
    )
    return "the app-thread gameplay cadence and gap diagnostic share one named interval"


def test_hub_service_fragments_are_visual_studio_project_items() -> str:
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    filters = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj.filters")
    for path in (
        r"src\mod_loader_gameplay\hub_service_runtime.inl",
        r"src\mod_loader_gameplay\public_api_hub.inl",
    ):
        item = f'<ClInclude Include="{path}"'
        assert item in project, f"Visual Studio project omits {path}"
        assert item in filters, f"Visual Studio filters omit {path}"
    return "the split hub runtime and API remain visible to Visual Studio tooling"


def test_native_project_uses_repo_local_lua_sources() -> str:
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    lua_source = r"$(ProjectDir)..\third_party\lua-5.4.8\src"
    legacy_checkout_path = r"$(ProjectDir)..\..\..\Mod Loader\third_party"

    assert legacy_checkout_path not in project, (
        "the native build must not depend on the original workstation checkout layout"
    )
    assert project.count(lua_source) == 2, (
        "both native configurations must include the repository-local Lua headers"
    )
    lua_compile_item = (
        r'<ClCompile Include="..\third_party\lua-5.4.8\src\*.c" '
        r'Exclude="..\third_party\lua-5.4.8\src\lua.c;'
        r'..\third_party\lua-5.4.8\src\luac.c">'
    )
    assert lua_compile_item in project, (
        "the native project must compile the repository-local Lua runtime sources"
    )
    for relative_path in (
        "third_party/lua-5.4.8/src/lua.h",
        "third_party/lua-5.4.8/src/lauxlib.h",
        "third_party/lua-5.4.8/src/lapi.c",
        "third_party/lua-5.4.8/src/linit.c",
    ):
        assert (ROOT / relative_path).is_file(), f"repository omits {relative_path}"

    return "the native project builds from the Lua sources owned by the clone"


def test_build_all_rebuilds_native_loader_from_clean_intermediates() -> str:
    build_script = _read("scripts/Build-All.ps1")
    assert "& $msbuild $loader /t:Rebuild /m /nologo" in build_script, (
        "the release build must clean native intermediates before compiling so "
        "objects and PDBs from another platform toolset cannot be reused"
    )
    assert "Remove-OrphanedLoaderObjects" not in build_script, (
        "a full native rebuild supersedes partial stale-object cleanup"
    )
    return "native builds start from clean toolset-specific compiler state"


def test_unreliable_snapshot_ordering_is_wrap_safe() -> str:
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    incoming = read_source_units(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_cast_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_snapshot_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_dispatch.inl",
    )
    lifecycle = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/remote_peer_lifecycle.inl"
    )
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl"
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
    for token in (
        "std::uint64_t participant_session_nonce;",
        "session_nonce_by_participant",
        "retired_session_nonces_by_participant",
        "packet.participant_session_nonce = g_local_transport.local_session_nonce;",
        "ResetRemoteParticipantSessionEpoch(",
        "preserve_session_nonce_history",
    ):
        assert token in protocol + transport + incoming + lifecycle + local_state, (
            f"same-identity reconnect contract lacks: {token}"
        )
    _require_in_order(
        incoming,
        "void ApplyRemoteStatePacket(",
        "session_nonce_by_participant.find(",
        "retired_session_nonces_by_participant.find(",
        "ResetRemoteParticipantSessionEpoch(",
        "last_state_packet_sequence_by_participant.find(",
        "!IsPacketSequenceNewer(",
        "RelayParticipantPacketToPeers(packet, from);",
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
        "accept uint32 wraparound, and reset every stream on a new gameplay-session nonce"
    )


def test_snapshot_streams_are_compact_and_bandwidth_bounded() -> str:
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    runtime_state = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_effect_state.inl"
    )
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    lua_runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_state_packet_sync.inl"
    )
    outgoing = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_packet_sync.inl"
    )
    incoming = read_source_units(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_sync.inl",
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_dispatch.inl",
    )
    spell_effect = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "spell_effect_sync.inl"
    )
    lifecycle = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "remote_peer_lifecycle.inl"
    )
    large_world_verifier = _read(
        "tools/verify_steam_friend_large_enemy_sync.py"
    )

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 81;",
        "ParticipantFrame = 20",
        "struct ParticipantFramePacket",
        "static_assert(sizeof(ParticipantFramePacket) == 570",
        "kLootSnapshotPacketPrefixBytes",
        "LootSnapshotPacketWireSize(",
        "IsValidLootSnapshotPacketWireSize(",
        "kSpellEffectSnapshotPacketPrefixBytes",
        "SpellEffectSnapshotPacketWireSize(",
        "IsValidSpellEffectSnapshotPacketWireSize(",
    ):
        assert token in protocol, f"compact snapshot protocol lacks: {token}"

    for token in (
        "kLocalTransportParticipantFrameIntervalMs = 50",
        "kLocalTransportStateCheckpointIntervalMs = 1000",
        "kLocalTransportWorldSnapshotBudgetBytesPerSecond",
        "kLocalTransportWorldReliableCheckpointBudgetBytesPerSecond",
        "kLocalTransportAuxiliarySnapshotBudgetBytesPerSecond",
        "BandwidthLimitedSnapshotIntervalMs(",
        "last_participant_frame_sequence_by_participant",
    ):
        assert token in transport, f"snapshot stream budget contract lacks: {token}"

    _require_in_order(
        local_state,
        "void PopulateLocalParticipantFrameFields(",
        "ParticipantFramePacket BuildLocalParticipantFramePacket()",
        "PopulateLocalParticipantFrameFields(*local, runtime_state, &packet);",
        "StatePacket BuildLocalStatePacket()",
        "PopulateLocalParticipantFrameFields(*local, runtime_state, &packet);",
    )
    _require_in_order(
        outgoing,
        "void SendLocalState(std::uint64_t now_ms)",
        "kLocalTransportStateCheckpointIntervalMs",
        "SteamNetworkSendMode::ReliableNoNagle",
        "void SendLocalParticipantFrame(std::uint64_t now_ms)",
        "kLocalTransportParticipantFrameIntervalMs",
    )
    assert "case PacketKind::ParticipantFrame:" in outgoing
    state_case = outgoing.find("case PacketKind::State:")
    assert state_case == -1, "high-rate packet classifier must not make State disposable"

    for token in (
        "SteamPacketOwnerMatches<ParticipantFramePacket>",
        "ApplyRemoteParticipantFramePacket(packet, from, now_ms)",
        "last_participant_frame_sequence_by_participant.find(",
        "RelayParticipantPacketToPeers(packet, from)",
        "ApplyParticipantFrameToRuntime(",
        "IsValidLootSnapshotPacketWireSize(",
        "IsValidSpellEffectSnapshotPacketWireSize(",
    ):
        assert token in incoming, f"compact snapshot receive path lacks: {token}"
    assert (
        "last_participant_frame_sequence_by_participant.erase(\n"
        "        participant_id)" in lifecycle
    ), "participant reconnect must reset its high-rate frame epoch"

    loot_send = outgoing[
        outgoing.index("void SendLootSnapshot(") :
        outgoing.index("std::vector<QueuedLocalLootPickupRequest>")
    ]
    assert "LootSnapshotPacketWireSize(packet.drop_count)" in loot_send
    assert "SendBufferToEndpoint(" in loot_send
    assert "SendPacketToEndpoint(packet, endpoint)" not in loot_send
    spell_send = spell_effect[
        spell_effect.index("void SendSpellEffectSnapshot(") :
        spell_effect.index("SpellEffectSnapshotRuntimeInfo")
    ]
    assert "SpellEffectSnapshotPacketWireSize(packet.effect_count)" in spell_send
    assert "BandwidthLimitedSnapshotIntervalMs(" in spell_send
    assert "SendBufferToEndpoint(" in spell_send
    assert "SendPacketToEndpoint(packet, endpoint)" not in spell_send
    assert "RelayPacketBufferToPeers(" in spell_effect

    for token in (
        "transport_packets_sent",
        "transport_packets_received",
        "steam_send_failures",
        "steam_reliable_send_failures",
        "last_steam_send_failure_result",
    ):
        assert token in runtime_state, f"runtime transport diagnostics lack: {token}"
        assert token in transport, f"transport diagnostics publisher lacks: {token}"
        assert token in lua_runtime, f"Lua transport diagnostics lack: {token}"
    for token in (
        "def capture_transport_diagnostics(",
        "def transport_deltas(",
        'diagnostics["steam_send_failures"] != 0',
    ):
        assert token in large_world_verifier, (
            f"large-world send-rejection regression lacks: {token}"
        )

    return (
        "participant motion uses a compact disposable frame, progression uses a "
        "reliable checkpoint, and variable loot/effect/world streams are wire-sized "
        "and bandwidth bounded; large-world cycles also fail on Steam send rejection"
    )


def test_empty_run_snapshot_unregisters_stale_enemies_without_parking() -> str:
    reconciliation = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "world_snapshot_reconciliation.inl"
    )
    verifier = _read("tools/verify_steam_friend_large_enemy_sync.py")

    apply = reconciliation[
        reconciliation.index("void ApplyReplicatedWorldSnapshotIfActive(") :
    ]
    sample_gate = apply[
        apply.index("const bool have_snapshot =") :
        apply.index("if (local_transport_participant_id != 0")
    ]
    assert "snapshot.actors.empty()" not in sample_gate, (
        "a valid empty Run snapshot must remain authoritative for teardown"
    )

    unmatched_binding = apply[
        apply.index("if (local_it == local_by_network_id.end()) {") :
        apply.index("binding.matched = true;")
    ]
    assert (
        "if (local_it == local_by_network_id.end() &&" not in unmatched_binding
    ), "stale snapshots must not gate the unmatched-binding guard"
    _require_in_order(
        unmatched_binding,
        "if (local_it == local_by_network_id.end()) {",
        "if (allow_structural_reconciliation &&",
        "            continue;\n        }\n\n        auto& binding = "
        "local_bindings[local_it->second];",
    )

    for forbidden in (
        "kWorldSnapshotParkBase",
        "IsParkedReplicatedWorldActor",
        "ParkReplicatedRunActor",
        "parked extra run actor",
    ):
        assert forbidden not in reconciliation, (
            f"run-enemy reconciliation still hides stale actors: {forbidden}"
        )

    remove = reconciliation[
        reconciliation.index("bool RemoveReplicatedRunActor(") :
        reconciliation.index("void RemoveReplicatedCreatedSharedHubActorsForSceneSwitch(")
    ]
    _require_in_order(
        remove,
        "ClearManualRunEnemyFreeze(binding.actor.actor_address);",
        "NeutralizeReplicatedRunEnemyActor(binding.actor.actor_address)",
        "kActorOwnerOffset",
        "CallActorWorldUnregisterSafe(",
    )

    removal_start = apply.index(
        "DWORD exception_code = 0;",
        apply.index("holding local replicated run enemy death"),
    )
    removal = apply[
        removal_start :
        apply.index(
            "if (snapshot.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::SharedHub",
            removal_start,
        )
    ]
    _require_in_order(
        removal,
        "RemoveReplicatedRunActor(binding, &exception_code)",
        "counts.removed_actor_count += 1;",
        "RecordWorldSnapshotBinding(&counts, removed_binding, false, false, true);",
        "UnbindReplicatedRunActor(removed_network_actor_id, removed_actor_address);",
    )
    failed = removal[removal.index("} else {") :]
    assert "counts.failed_remove_actor_count += 1;" in failed
    assert "UnbindReplicatedRunActor(" not in failed, (
        "a failed native unregister must retain its binding for the next snapshot"
    )

    for token in (
        "cleanup_after_parity",
        "partial_expected_count",
        "partial_samples",
        "cleanup_after_partial",
        "zero_after_cleanup",
        "HOST_REMOVE_SUBSET_LUA",
        "remove_host_enemy_subset",
        "static_world_baseline",
        'summary["host_tracked"] == 0',
        'summary["client_snapshot_tracked"] == 0',
        'summary["client_snapshot_dead_tracked"] == 0',
        'summary["client_binding_tracked"] == 0',
        'summary["client_binding_orphan"] == 0',
        'summary["client_parked"] == 0',
        'summary["client_local_tracked"] == 0',
        'summary["client_failed_remove"] == 0',
    ):
        assert token in verifier, f"large-enemy teardown regression lacks: {token}"

    return (
        "valid empty Run snapshots neutralize and unregister unmatched native enemies, "
        "retain failed bindings for retry, and never hide actors off-map"
    )


def test_run_enemy_death_tombstones_precede_structural_omission() -> str:
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    capture = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "world_snapshot_capture.inl"
    )
    builder = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_snapshot_packet_builders.inl"
    )
    public_api = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    verifier = _read("tools/verify_multiplayer_primary_kill_stress.py")

    for token in (
        "struct RetainedRunEnemySnapshot",
        "retained_run_enemy_snapshots_by_network_id",
    ):
        assert token in transport, f"tracked-enemy retention state lacks: {token}"
    _require_in_order(
        builder,
        "g_local_transport.retained_run_enemy_snapshots_by_network_id[",
        "Native enemy health can cross zero just before the stock death hook",
        "built.actors.push_back(retained.packet);",
        "g_local_transport.recent_run_enemy_deaths_by_network_id",
    )
    _require_in_order(
        capture,
        "RecordRecentRunEnemyDeathSnapshot(",
        "g_local_transport.retained_run_enemy_snapshots_by_network_id.erase(",
        "g_local_transport.recent_run_enemy_deaths_by_network_id[network_actor_id]",
    )
    assert "ForgetRetainedRunEnemySnapshotForActor(actor_address);" in public_api
    for token in (
        '"world_snapshot: unregistered extra run actor" in last_receiver',
        '"before its authoritative native death presentation. "',
    ):
        assert token in verifier, f"primary-kill omission regression lacks: {token}"

    return (
        "tracked enemies survive transient native-list omission until an explicit "
        "unregister or authoritative death tombstone"
    )


def test_hub_students_remain_in_the_stock_transient_lifecycle() -> str:
    reconciliation = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "world_snapshot_reconciliation.inl"
    )

    lifecycle_start = reconciliation.index(
        "bool IsReplicatedSharedHubLifecycleOwnedActorType("
    )
    lifecycle_end = reconciliation.index(
        "std::uint64_t BuildReplicatedWorldActorNetworkId(",
        lifecycle_start,
    )
    lifecycle = reconciliation[lifecycle_start:lifecycle_end]
    assert "IsReplicatedSharedHubFactoryActorType(native_type_id)" in lifecycle
    assert "native_type_id != 0x138A" in lifecycle, (
        "Student actors must remain owned by the stock transient hub lifecycle"
    )

    for function_name in (
        "TryCreateReplicatedSharedHubActor",
        "RemoveReplicatedSharedHubActor",
    ):
        function_start = reconciliation.index(f"bool {function_name}(")
        function_end = reconciliation.index("\n}\n", function_start) + 3
        function_body = reconciliation[function_start:function_end]
        assert "IsReplicatedSharedHubLifecycleOwnedActorType(" in function_body, (
            f"{function_name} can structurally mutate stock Student actors"
        )

    creation_gate = reconciliation[
        reconciliation.index("if (local_it == local_by_network_id.end()) {") :
        reconciliation.index("auto& binding = local_bindings[local_it->second];")
    ]
    assert "IsReplicatedSharedHubLifecycleOwnedActorType(" in creation_gate

    cleanup_start = reconciliation.index(
        "if (snapshot.scene_intent.kind != "
        "multiplayer::ParticipantSceneIntentKind::SharedHub ||"
    )
    cleanup = reconciliation[
        cleanup_start : reconciliation.index(
            "counts.presentation_write_count += latest_target_write_count;",
            cleanup_start,
        )
    ]
    _require_in_order(
        cleanup,
        "!IsReplicatedSharedHubLifecycleOwnedActorType(",
        "UnbindReplicatedSharedHubActor(",
        "RemoveReplicatedSharedHubActor(binding, &exception_code)",
    )

    return (
        "hub Students synchronize through local stock actors without multiplayer "
        "factory creation or native unregister"
    )


def test_run_enemy_materialization_preserves_exact_native_type() -> str:
    layout = _read("config/binary-layout.ini")
    seam_header = _read("SolomonDarkModLoader/src/gameplay_seams.h")
    seam_storage = _read(
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    seam_bindings = _read(
        "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    lifecycle_state = _read(
        "SolomonDarkModLoader/src/run_lifecycle/state_and_targets.inl"
    )
    lifecycle_hooks = read_source_unit(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    lua_gameplay = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    primary_verifier = _read(
        "tools/verify_multiplayer_primary_kill_stress.py"
    )
    reconciliation = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "world_snapshot_reconciliation.inl"
    )

    for source, token in (
        (layout, "spawn_exact_enemy_group=0x0046BCD0"),
        (seam_header, "extern uintptr_t kSpawnExactEnemyGroup;"),
        (seam_storage, "uintptr_t kSpawnExactEnemyGroup = 0;"),
        (
            seam_bindings,
            'SDMOD_ADDR("run_lifecycle.hooks", "spawn_exact_enemy_group", '
            "kSpawnExactEnemyGroup)",
        ),
        (lifecycle_state, "using SpawnExactEnemyGroupFn = void(__thiscall*)("),
        (lifecycle_hooks, "CallSpawnExactEnemyGroupSafe("),
        (
            lifecycle_hooks,
            "memory.ResolveGameAddressOrZero(kNativeIntArrayVtable)",
        ),
        (lifecycle_hooks, "memory.ResolveGameAddressOrZero(kGameFree)"),
        (lifecycle_hooks, "no_modifiers.vtable = modifier_array_vtable"),
        (lifecycle_hooks, "free_fn(reinterpret_cast<void*>(no_modifiers.entries))"),
        (lifecycle_hooks, "request.type_id"),
        (lifecycle_hooks, "actual native type did not match authority"),
        (
            reconciliation,
            "static_cast<int>(authoritative_actor.native_type_id),",
        ),
    ):
        assert token in source, f"exact run-enemy materialization lacks: {token}"

    assert (
        "actor_object_type == static_cast<std::uint32_t>(request.type_id)"
        in lifecycle_hooks
    )
    exact_call_start = lifecycle_hooks.index(
        "bool CallSpawnExactEnemyGroupSafe("
    )
    exact_call_end = lifecycle_hooks.index(
        "void RetireInvalidFeaturedEnemyAfterExactSpawn(",
        exact_call_start,
    )
    assert (
        "IsArenaCombatActorType(native_type_id)"
        in lifecycle_hooks[exact_call_start:exact_call_end]
    )
    manual_spawn_start = lua_gameplay.index(
        "int LuaGameplaySpawnManualRunEnemy("
    )
    manual_spawn_end = lua_gameplay.index(
        "int LuaGameplayGetLastManualRunEnemySpawn(",
        manual_spawn_start,
    )
    assert "int type_id = 1001;" in lua_gameplay[
        manual_spawn_start:manual_spawn_end
    ]
    assert "SKELETON_TYPE_ID = 1001" in primary_verifier

    kind_match_start = reconciliation.index(
        "bool IsSameReplicatedRunEnemyKind("
    )
    kind_match = reconciliation[
        kind_match_start :
        reconciliation.index(
            "bool IsReplicatedSharedHubFactoryActorType(",
            kind_match_start,
        )
    ]
    assert (
        "local_actor.object_type_id == authoritative_actor.native_type_id"
        in kind_match
    )
    for forbidden in (
        "arena-combat family is the binding key",
        "bound arena run enemy variant",
        "IsArenaCombatActorTypeInternal(local_actor.object_type_id)",
        "local_actor.enemy_type == authoritative_actor.enemy_type",
    ):
        assert forbidden not in kind_match, (
            "run enemies still accept a visually different native class: "
            f"{forbidden}"
        )

    return (
        "replicated run enemies are created through the exact stock native-type "
        "wrapper and never cross-bind different enemy classes"
    )


def test_exact_spawn_retires_invalid_featured_enemy() -> str:
    layout = _read("config/binary-layout.ini")
    seam_header = _read("SolomonDarkModLoader/src/gameplay_seams.h")
    seam_storage = _read(
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    seam_bindings = _read(
        "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl"
    )
    lifecycle_hooks = read_source_unit(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )

    for source, token in (
        (layout, "gameplay_featured_enemy_actor=0x1C2C"),
        (seam_header, "extern std::size_t kGameplayFeaturedEnemyActorOffset;"),
        (seam_storage, "std::size_t kGameplayFeaturedEnemyActorOffset = 0;"),
        (
            seam_bindings,
            'SDMOD_SIZE("gameplay.offsets", "gameplay_featured_enemy_actor", '
            "kGameplayFeaturedEnemyActorOffset)",
        ),
        (
            lifecycle_hooks,
            "RetireInvalidFeaturedEnemyAfterExactSpawn(request);",
        ),
    ):
        assert token in source, f"exact-spawn featured-enemy retirement lacks: {token}"

    helper_start = lifecycle_hooks.index(
        "void RetireInvalidFeaturedEnemyAfterExactSpawn("
    )
    helper_end = lifecycle_hooks.index(
        "ManualRunEnemySpawnerDispatchResult DispatchExactRunEnemySpawn(",
        helper_start,
    )
    helper = lifecycle_hooks[helper_start:helper_end]
    for token in (
        "g_last_manual_run_enemy_spawn_result.request_id != request.request_id",
        "g_last_manual_run_enemy_spawn_result.actor_address",
        "kEnemyConfigOffset",
        "enemy_config_address != 0",
        "memory.ResolveGameAddressOrZero(kGameObjectGlobal)",
        "kGameplayFeaturedEnemyActorOffset",
        "featured_enemy_actor != spawned_actor_address",
        "TryWriteField<uintptr_t>",
    ):
        assert token in helper, f"featured-enemy ownership guard lacks: {token}"
    assert "request.network_actor_id == 0" not in helper, (
        "local exact spawns still skip the featured-enemy safety repair"
    )

    dispatch_start = lifecycle_hooks.index(
        "ManualRunEnemySpawnerDispatchResult DispatchExactRunEnemySpawn("
    )
    dispatch_end = lifecycle_hooks.index(
        "void RememberArenaEnemyWaveSpawner(",
        dispatch_start,
    )
    dispatch = lifecycle_hooks[dispatch_start:dispatch_end]
    _require_in_order(
        dispatch,
        "const bool call_ok = CallSpawnExactEnemyGroupSafe(",
        "RetireInvalidFeaturedEnemyAfterExactSpawn(request);",
        "g_manual_run_enemy_spawner_tick_active = previous_manual_tick;",
    )

    return (
        "exact spawns clear a stock featured-enemy reference only when "
        "that request produced the referenced actor after its native config retired"
    )


def test_client_enemy_hot_path_uses_constant_time_authority_cache() -> str:
    reconciliation = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "world_snapshot_reconciliation.inl"
    )
    player_state_header = _read("SolomonDarkModLoader/include/mod_loader.h")
    runtime_state_header = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_state.h"
    )
    player_state_getter = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    lua_gameplay = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    lua_engine_header = _read("SolomonDarkModLoader/include/lua_engine.h")
    lua_engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    d3d9_hook = _read("SolomonDarkModLoader/src/d3d9_end_scene_hook.cpp")
    lua_runtime = read_source_unit(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    lua_runtime_api = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime/"
        "level_up_and_runtime_api.inl"
    )
    large_world = _read("tools/verify_steam_friend_large_enemy_sync.py")

    for source, token in (
        (
            reconciliation,
            "g_latest_run_enemy_snapshots_by_network_id",
        ),
        (
            reconciliation,
            "RefreshLatestRunEnemySnapshotCache(runtime_state.world_snapshot, now_ms);",
        ),
        (runtime_state_header, "bool sampled_transform_valid = false;"),
        (runtime_state_header, "float sampled_position_x = 0.0f;"),
        (runtime_state_header, "float sampled_position_y = 0.0f;"),
        (
            reconciliation,
            "binding.sampled_position_x = authoritative_actor.position_x;",
        ),
        (
            reconciliation,
            "binding.sampled_position_y = authoritative_actor.position_y;",
        ),
        (lua_gameplay, 'lua_setfield(state, -2, "sampled_transform_valid");'),
        (lua_gameplay, 'lua_setfield(state, -2, "sampled_position_x");'),
        (lua_gameplay, 'lua_setfield(state, -2, "sampled_position_y");'),
        (large_world, "binding.sampled_transform_valid"),
        (large_world, "tonumber(binding.sampled_position_x)"),
        (large_world, "tonumber(binding.sampled_position_y)"),
        (player_state_header, "std::uint64_t local_player_tick_count = 0;"),
        (player_state_header, "std::uint64_t local_player_tick_observed_ms = 0;"),
        (
            player_state_getter,
            "g_gameplay_keyboard_injection.local_player_tick_generation.load(",
        ),
        (lua_gameplay, 'lua_setfield(state, -2, "local_player_tick_count");'),
        (
            lua_gameplay,
            'lua_setfield(state, -2, "local_player_tick_observed_ms");',
        ),
        (large_world, "def measure_client_tick_rate("),
        (large_world, 'result["client_tick_rate_baseline"]'),
        (large_world, 'result["client_tick_rate_loaded"]'),
        (large_world, "MINIMUM_CLIENT_TICK_RATE_HZ"),
        (large_world, "MINIMUM_LOADED_TO_BASELINE_TICK_RATE_RATIO"),
        (lua_engine_header, "g_endscene_generation"),
        (lua_engine, "g_endscene_generation{0}"),
        (d3d9_hook, "g_endscene_generation.fetch_add("),
        (lua_runtime, "int LuaRuntimeGetFrameState(lua_State* state)"),
        (
            lua_runtime_api,
            'RegisterFunction(state, &LuaRuntimeGetFrameState, "get_frame_state");',
        ),
        (large_world, "def measure_client_render_frame_rate("),
        (large_world, 'result["client_render_frame_rate_baseline"]'),
        (large_world, 'result["client_render_frame_rate_loaded"]'),
        (large_world, "MINIMUM_CLIENT_RENDER_FRAME_RATE_HZ"),
        (large_world, "MINIMUM_LOADED_TO_BASELINE_RENDER_FRAME_RATE_RATIO"),
        (large_world, "def prepare_client_performance_sample()"),
        (large_world, "PAIR_BACKEND == \"wsl\""),
        (large_world, "proton_input_process_id()"),
        (large_world, "activate_proton_window(process_id)"),
        (large_world, '"wslg_copy_mode":'),
        (large_world, 'result["client_render_frame_rate_floor_applicable"]'),
        (
            large_world,
            'if result.get("spawns") and "zero_after_cleanup" not in result:',
        ),
        (large_world, 'result["teardown_cleanup"] = primary.cleanup_live_enemies()'),
        (large_world, 'result["teardown_zero"] = wait_for_zero('),
        (large_world, "freeze_on_spawn=False"),
    ):
        assert token in source, f"client enemy-load regression lacks: {token}"

    for function_name, next_function in (
        (
            "bool ApplyLatestReplicatedRunEnemyTargetForLocalActor(",
            "bool IsBoundReplicatedRunEnemyActorForLocalClient(",
        ),
        (
            "bool IsBoundReplicatedRunEnemyActorForLocalClient(",
            "bool NeutralizeReplicatedRunEnemyActor(",
        ),
    ):
        start = reconciliation.index(function_name)
        end = reconciliation.index(next_function, start)
        hot_path = reconciliation[start:end]
        assert "SnapshotRuntimeState()" not in hot_path, (
            f"{function_name} still copies the complete runtime state per enemy"
        )
        assert "std::find_if" not in hot_path and "std::any_of" not in hot_path, (
            f"{function_name} still linearly searches all authority actors per enemy"
        )
        assert "g_latest_run_enemy_snapshots_by_network_id.find(" in hot_path

    return (
        "per-enemy client hooks use one constant-time authority cache, and the real "
        "active 80-enemy Steam cycle bounds both simulation and D3D frame rates "
        "against their own empty-run baselines"
    )


def test_client_replicated_enemy_movement_is_host_authored() -> str:
    layout = _read("config/binary-layout.ini")
    seam_header = _read("SolomonDarkModLoader/src/gameplay_seams.h")
    seam_storage = _read(
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    seam_bindings = _read(
        "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    constants = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    native_types = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"
    )
    runtime_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    movement_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "monster_pathfinding_hook.inl"
    )
    installation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_keyboard_injection.inl"
    )
    steam_verifier = _read(
        "tools/verify_steam_friend_enemy_motion_authority.py"
    )
    steam_reconciliation_verifier = _read(
        "tools/verify_steam_friend_enemy_soft_reconciliation.py"
    )

    for source, token in (
        (layout, "badguy_move_step=0x00475FE0"),
        (seam_header, "extern uintptr_t kBadguyMoveStep;"),
        (seam_storage, "uintptr_t kBadguyMoveStep = 0;"),
        (
            seam_bindings,
            'SDMOD_ADDR("gameplay.hooks", "badguy_move_step", kBadguyMoveStep)',
        ),
        (constants, "kBadguyMoveStepHookMinimumPatchSize = 5"),
        (native_types, "using BadguyMoveStepFn = std::uint32_t(__thiscall*)("),
        (runtime_state, "X86Hook badguy_move_step_hook;"),
        (movement_hook, "std::uint32_t __fastcall HookBadguyMoveStep("),
        (
            movement_hook,
            "IsBoundReplicatedRunEnemyActorForLocalClient(actor_address)",
        ),
        (
            movement_hook,
            "GetX86HookTrampoline<BadguyMoveStepFn>(",
        ),
        (installation, "ResolveGameAddressOrZero(kBadguyMoveStep)"),
        (installation, "reinterpret_cast<void*>(&HookBadguyMoveStep)"),
        (installation, "kBadguyMoveStepHookMinimumPatchSize"),
        (
            installation,
            "&g_gameplay_keyboard_injection.badguy_move_step_hook",
        ),
        (
            installation,
            "RemoveX86Hook(&g_gameplay_keyboard_injection.badguy_move_step_hook);",
        ),
        (steam_verifier, "SAMPLE_COUNT = 240"),
        (steam_verifier, "MAXIMUM_LOCAL_ERROR = 3.0"),
        (steam_verifier, 'sd.events.on("runtime.tick"'),
        (steam_verifier, "maximum_local_error"),
        (steam_reconciliation_verifier, "reconciliation.INJECTED_DRIFT"),
        (steam_reconciliation_verifier, "reconciliation.MAX_CORRECTION_STEP"),
        (steam_reconciliation_verifier, "reconciliation.CONVERGED_ERROR"),
    ):
        assert token in source, f"host-authored enemy movement contract lacks: {token}"

    hook = movement_hook[
        movement_hook.index("std::uint32_t __fastcall HookBadguyMoveStep(") :
        movement_hook.index("bool ClearHostileTargetsForDeadWizardActor(")
    ]
    _require_in_order(
        hook,
        "GetX86HookTrampoline<BadguyMoveStepFn>(",
        "IsBoundReplicatedRunEnemyActorForLocalClient(actor_address)",
        "return 1;",
        "return original(movement_context, actor, move_x, move_y);",
    )
    assert "multiplayer::IsLocalTransportClient()" not in hook, (
        "movement suppression must be scoped to a bound replicated enemy, not "
        "to every client-side native actor"
    )

    return (
        "Badguy_MoveStep remains stock-owned on hosts, offline games, and "
        "unbound actors while bound client replicas cannot author movement"
    )


def test_scene_tick_keeps_dead_remote_participants_inert() -> str:
    scene_tick = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement_tick/"
        "participant_scene_binding_ticks.inl"
    )
    death_verifier = _read("tools/verify_player_health_death_sync.py")

    assert scene_tick.count("ApplyNativeRemoteParticipantPlayback(") == 1
    _require_in_order(
        scene_tick,
        "RefreshNativeRemoteParticipantTransformTarget(",
        "if (!IsActorRuntimeDead(binding.actor_address)) {",
        "ApplyNativeRemoteParticipantPlayback(",
    )
    for token in (
        "assert_dead_remote_ignores_transform(",
        "dead_inert",
    ):
        assert token in death_verifier, (
            f"remote death lifecycle verifier lacks: {token}"
        )

    return (
        "scene-tick reconciliation buffers remote targets but does not move "
        "a native proxy while its replicated actor is dead"
    )
