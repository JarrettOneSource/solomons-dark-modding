"""Focused static contracts for multiplayer runtime hardening.

Keep new multiplayer checks out of the legacy monolithic RE test module.  Each
function raises AssertionError on failure and returns a short success detail so
the existing runner can report it uniformly.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _read_many(*relative_paths: str) -> str:
    return "\n".join(_read(path) for path in relative_paths)


_SPLIT_SOURCE_FRAGMENTS = frozenset(
    {
        "skill_choice_application.inl",
        "public_memory_forwarders.inl",
        "lua_engine_main_thread_pump.inl",
        "transient_status_participant_reconciliation.inl",
        "native_remote_vitals_and_playback.inl",
        "incoming_participant_state_sync.inl",
        "level_up_native_picker_presentation.inl",
        "level_up_packet_handlers.inl",
        "loot_pickup_packet_handlers.inl",
        "world_snapshot_hub_presentation_and_loot_helpers.inl",
        "lobby_event_handlers.inl",
    }
)


def read_source_unit(path: str | Path) -> str:
    source_path = Path(path)
    if not source_path.is_absolute():
        source_path = ROOT / source_path

    def expand(current_path: Path, active_paths: frozenset[Path]) -> str:
        resolved_path = current_path.resolve()
        assert resolved_path not in active_paths, (
            f"recursive split-source include: {resolved_path}"
        )
        text = current_path.read_text(encoding="utf-8")
        next_active_paths = active_paths | {resolved_path}

        def replace_include(match: re.Match[str]) -> str:
            include_name = match.group(1)
            if Path(include_name).name not in _SPLIT_SOURCE_FRAGMENTS:
                return match.group(0)
            include_path = current_path.parent / include_name
            assert include_path.is_file(), f"missing split-source fragment: {include_path}"
            return expand(include_path, next_active_paths)

        return re.sub(
            r'^\s*#include\s+"([^"]+)"\s*$',
            replace_include,
            text,
            flags=re.MULTILINE,
        )

    return expand(source_path, frozenset())


def read_source_units(*paths: str | Path) -> str:
    return "\n".join(read_source_unit(path) for path in paths)


def _require_in_order(text: str, *tokens: str) -> None:
    cursor = 0
    for token in tokens:
        position = text.find(token, cursor)
        assert position >= 0, f"missing ordered token: {token}"
        cursor = position + len(token)


def test_app_thread_transport_verifier_tracks_named_cadence_gap() -> str:
    verifier = _read("tests/re/run_static_re_tests.py")
    assert '"tick_gap_ms < kServiceTickIntervalMs"' in verifier, (
        "the app-thread transport verifier must recognize the named cadence gap "
        "used by transport diagnostics"
    )
    return "the app-thread ownership verifier accepts the diagnostic cadence variable"


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
        "constexpr std::uint16_t kProtocolVersion = 64;",
        "ParticipantFrame = 20",
        "struct ParticipantFramePacket",
        "static_assert(sizeof(ParticipantFramePacket) == 270",
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
        "PopulateLocalParticipantFrameFields(*local, &packet);",
        "StatePacket BuildLocalStatePacket()",
        "PopulateLocalParticipantFrameFields(*local, &packet);",
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
    reconciliation = _read(
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
    reconciliation = _read(
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
    lifecycle_hooks = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks.inl"
    )
    reconciliation = _read(
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
        (lifecycle_hooks, "request.type_id"),
        (lifecycle_hooks, "actual native type did not match authority"),
        (
            reconciliation,
            "static_cast<int>(authoritative_actor.native_type_id),",
        ),
    ):
        assert token in source, f"exact run-enemy materialization lacks: {token}"

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


def test_lua_exec_timeout_cancels_pending_work() -> str:
    engine = read_source_unit("SolomonDarkModLoader/src/lua_engine.cpp")
    engine_header = _read("SolomonDarkModLoader/include/lua_engine.h")
    pipe = _read("SolomonDarkModLoader/src/lua_exec_pipe.cpp")
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    engine_internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    lua_main = _read("mods/lua_bots/scripts/main.lua")
    lua_client = _read("tools/lua-exec.py")
    local_verifier = _read("tools/verify_local_multiplayer_sync.py")
    steam_driver = _read("tools/drive_steam_friend_active_pair.py")
    lua_contract_verifier = _read("tools/verify_lua_runtime_contract.py")
    spell_behavior_verifier = _read(
        "tools/verify_steam_friend_active_pair_spell_behavior.py"
    )

    for token in (
        "LuaExecRequestState::Pending",
        "LuaExecRequestState::Executing",
        "LuaExecRequestState::Canceled",
        "std::shared_ptr<PendingLuaExecRequest>",
        "bool TryCancelLuaExecRequest(",
        "bool TryClaimLuaExecRequest(",
        "std::atomic<std::uint64_t>& LuaExecPumpGeneration()",
        "LuaExecPumpGeneration().fetch_add(1, std::memory_order_release);",
        "pump_generation - pump_generation_at_enqueue >= 2",
    ):
        assert token in engine, f"Lua exec cancellation contract lacks: {token}"

    for token in (
        "const std::atomic<bool>* service_running = nullptr",
        "kLuaExecHangBackstopMs = 30000",
        "&g_pipe_running",
    ):
        assert token in engine_header + pipe, (
            f"Lua exec scene-load/shutdown deadline contract lacks: {token}"
        )

    assert "DEFAULT_WSL_BRIDGE_TIMEOUT_SECONDS = 35.0" in lua_client
    assert "NATIVE_UI_LUA_TIMEOUT_SECONDS = 35.0" in local_verifier
    assert local_verifier.count(
        "timeout=NATIVE_UI_LUA_TIMEOUT_SECONDS"
    ) >= 4
    assert (
        "timeout=local_sync.NATIVE_UI_LUA_TIMEOUT_SECONDS" in steam_driver
    )
    for token in (
        '"--steam-friend"',
        "def run_steam_friend_pair()",
        "SteamFriendActivePair",
        "pair.discover()",
        "pair.lua(endpoint, probe, timeout=12.0)",
        "return pair.redact(result)",
    ):
        assert token in lua_contract_verifier, (
            f"real-Steam Lua runtime contract lacks: {token}"
        )

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

    for token in (
        "using PendingLuaEvent = std::variant<",
        "std::deque<PendingLuaEvent> g_pending_lua_events;",
        "pending.swap(g_pending_lua_events);",
        "void DispatchPendingLuaEventsToLuaMods()",
        "detail::QueueEnemyDeathEvent(enemy_type, x, y, kill_method);",
        "void StartLuaEventQueue();",
        "void StopLuaEventQueue();",
    ):
        assert token in events + engine_internal, (
            f"reentrant Lua event queue contract lacks: {token}"
        )

    enemy_death_dispatch = events[
        events.index("void DispatchLuaEnemyDeath(") :
        events.index("void DispatchLuaEnemySpawned(")
    ]
    assert "LuaEngineMutex" not in enemy_death_dispatch, (
        "a native death reached from lua-exec must enqueue its event instead "
        "of recursively locking the Lua engine"
    )
    _require_in_order(
        engine,
        "detail::StartLuaEventQueue();",
        "detail::LuaEngineInitializedFlag() = true;",
    )
    _require_in_order(
        engine,
        "void ShutdownLuaEngine()",
        "detail::StopLuaEventQueue();",
        "detail::DrainLuaExecQueue();",
    )
    assert engine.count("detail::DispatchPendingLuaEventsToLuaMods();") == 2

    for token in (
        "presenter_log_offsets = capture_log_offsets()",
        'output["post_behavior_cleanup"] = primary.cleanup_live_enemies()',
        "verify_native_death_presenter_results(presenter_log_offsets)",
        "deadline = time.monotonic() + timeout",
        'if result["event_count"] == 0',
        "if not missing:",
        'outcome["called"] != 1 or outcome["seh"] != "0x0"',
    ):
        assert token in spell_behavior_verifier, (
            f"live Lua/death-presenter regression gate lacks: {token}"
        )

    for loader_token in (
        "runtime.get_mod_text_file",
        'load(source, "@" .. normalized, "t", _ENV)',
        "loading_sentinel",
        "pcall(chunk)",
    ):
        assert loader_token in lua_main

    return (
        "pending Lua exec requests are cancelable, stock scene-load stalls fit "
        "inside the hang backstop, pump skips fail by invariant, pipe shutdown "
        "interrupts its wait, hook events are deferred without re-entering the "
        "Lua VM, handlers remain isolated, and all ten current sd namespaces "
        "are registered"
    )


def test_remote_windows_lua_bridge_is_persistent_and_framed() -> str:
    pair = _read("tools/steam_friend_active_pair.py")
    primary_kill = _read("tools/verify_steam_friend_primary_kill_stress.py")
    bridge_script = _read("scripts/Invoke-RemoteLuaExecBridge.ps1")
    bridge = pair[
        pair.index("class RemoteWindowsLuaBridge:") :
        pair.index("class RemoteWindowsLogMirror:")
    ]
    mirror = pair[
        pair.index("class RemoteWindowsLogMirror:") :
        pair.index("class SteamFriendActivePair:")
    ]

    for token in (
        "def _encoded_bridge_command(self) -> str:",
        "-ListenPort 0",
        "self._server_process",
        "def _read_line(",
        're.fullmatch(r"SDMOD_BRIDGE_PORT=(\\d+)", line)',
        "stdin=subprocess.PIPE",
        "stdout=subprocess.PIPE",
        "bufsize=0",
        '"-W"',
        'f"127.0.0.1:{remote_port}"',
        'struct.pack("<II", REMOTE_BRIDGE_PING_LENGTH, 100)',
        "if response_size != 0:",
        "def _exchange(",
        "subprocess.Popen(",
        '"-EncodedCommand"',
        '"<II",',
        "response_timeout_milliseconds,",
        "time.monotonic() + response_timeout_seconds + 6.0",
        'response_size = struct.unpack(',
        "with self._lock:",
        "candidate.terminate()",
        'process.stdin.write(struct.pack("<II", 0, 100))',
    ):
        assert token in bridge, f"remote Windows Lua bridge lacks: {token}"
    assert "REMOTE_BRIDGE_PING_LENGTH = 0xFFFFFFFF" in pair
    for forbidden in (
        '"-Daemon"',
        "__SDLUA_EXIT__",
        "RemoteWindowsLuaDaemon",
        "shell=True",
        '"-tt"',
        '"-L"',
        "socket.create_connection(",
        "_remote_bridge_port",
    ):
        assert forbidden not in bridge, (
            "remote Windows Lua bridge retains an unsafe transport path: "
            f"{forbidden}"
        )

    for token in (
        "[ValidateRange(0, 65535)]",
        "[int]$ListenPort = 0",
        "[System.Net.IPAddress]::Loopback",
        "$listener.AcceptTcpClient()",
        'WriteLine("SDMOD_BRIDGE_PORT=$boundPort")',
        "$header = Read-ExactBytes -Stream $stream -Length 8",
        "$requestLength = [System.BitConverter]::ToUInt32($header, 0)",
        "if ($requestLength -eq [uint32]::MaxValue)",
        "$requestTimeoutMilliseconds = [System.BitConverter]::ToUInt32(",
        "-ResponseTimeoutMilliseconds ([int]$requestTimeoutMilliseconds)",
        "$responseHeader = [System.BitConverter]::GetBytes(",
        "$stream.Write($responseHeader, 0, $responseHeader.Length)",
        "[System.IO.Pipes.PipeOptions]::Asynchronous",
        "$pipe.ReadAsync($buffer, 0, $buffer.Length)",
        "$readTask.Wait($remaining)",
        "Timed out waiting for pipe '$PipeName'",
        "catch [System.IO.IOException]",
        "$shutdownRequested = $true",
    ):
        assert token in bridge_script, (
            f"remote Windows bridge lacks bounded framed relay: {token}"
        )
    assert bridge_script.count("while (-not $shutdownRequested)") == 2
    for token in (
        'name="remote-windows-log-mirror"',
        "def _append_available_bytes(self) -> None:",
        'f"$requested=[int64]{requested_offset};"',
        '"$available=[int][Math]::Min([int64]2097152,$length-$offset);"',
        '"[Console]::Out.Write($reset+\'|\'+$offset+\'|\'+($offset+$total)+\'|\'+$payload)"',
        "timeout=10.0",
        "thread.join(timeout=11.0)",
    ):
        assert token in mirror, f"remote log mirror lacks bounded polling: {token}"
    for forbidden in ("subprocess.Popen(", "Get-Content -LiteralPath", "-Wait -Tail 0"):
        assert forbidden not in mirror, f"remote log mirror retains persistent process: {forbidden}"
    assert '"same_machine": PAIR_BACKEND == "wsl"' in primary_kill, (
        "physical Windows-pair evidence must not claim both accounts ran on "
        "one machine"
    )
    for token in (
        'PAIR_BACKEND in ("remote-windows-host", "remote-windows-client")',
        'HOST_ENDPOINT if PAIR_BACKEND == "remote-windows-host" else CLIENT_ENDPOINT',
        "if endpoint == self._remote_windows_endpoint:",
        "if endpoint in (HOST_ENDPOINT, CLIENT_ENDPOINT):",
    ):
        assert token in pair, (
            "physical Windows Lua routing must support either machine owning "
            f"the host role: {token}"
        )
    for wrapper_path in (
        "tools/verify_steam_friend_active_run_reconnect.py",
        "tools/verify_steam_friend_host_loot_deactivation_soak.py",
        "tools/verify_steam_friend_native_inventory_sync.py",
        "tools/verify_steam_friend_powerup_sync.py",
        "tools/verify_steam_friend_world_snapshot_stale_hold.py",
    ):
        wrapper = _read(wrapper_path)
        assert '"same_machine": PAIR_BACKEND == "wsl"' in wrapper, (
            f"remote-capable evidence wrapper mislabels its topology: {wrapper_path}"
        )
        assert '"same_machine": True' not in wrapper, (
            f"remote-capable evidence wrapper hardcodes one-machine topology: {wrapper_path}"
        )

    return (
        "remote Windows Lua uses an OS-assigned loopback port reached by one "
        "persistent SSH stdio tunnel, while logs use finite byte-range polls"
    )


def test_steam_pair_recovers_lobby_membership_and_requires_stable_readiness() -> str:
    session = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_steam_session/lobby_and_events.inl"
    )
    session_lifecycle = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/public_lifecycle.inl"
    )
    steam_bootstrap = _read("SolomonDarkModLoader/src/steam_bootstrap.cpp")
    steam_header = _read("SolomonDarkModLoader/include/steam_bootstrap.h")
    pair_tool = _read("tools/steam_friend_active_pair.py")

    _require_in_order(
        session,
        "if (current.find(g_session.local_steam_id) == current.end())",
        "if (!g_session.is_host)",
        "BeginClientLobbyRecovery(",
        'SetError("Local Steam user is no longer a lobby member.", false);',
    )
    for token in (
        "SteamEventKind::SteamServersDisconnected",
        "SteamEventKind::SteamServersConnected",
        "kClientLobbyRecoveryRetryMs",
        "kClientLobbyRecoveryTimeoutMs",
        "void ServiceClientLobbyRecovery(std::uint64_t now_ms)",
        "ServiceClientLobbyRecovery(now_ms);",
        "if (!g_session.steam_servers_connected)",
        "g_session.client_lobby_recovery",
        '"the recovery state machine will retry."',
        '"Steam multiplayer network session failed. steam_id="',
        '" end_reason=" + std::to_string(event.network_status.end_reason)',
        '" debug=" + event.network_status.debug_text',
        "LUA_TRANSITION_TIMEOUT_SECONDS = 35.0",
        "PAIR_DISCOVERY_STABLE_SECONDS = 3.0",
        "stable_since: float | None = None",
        "and host_id != client_id",
        "if participant_id > 1",
        "if isinstance(value, bool):",
    ):
        assert token in (
            session + session_lifecycle + steam_bootstrap + steam_header + pair_tool
        ), (
            f"Steam reconnect/readiness contract lacks: {token}"
        )

    import sys

    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from steam_friend_active_pair import SteamFriendActivePair

    pair = SteamFriendActivePair.__new__(SteamFriendActivePair)
    pair.host_participant_id = 0
    pair.client_participant_id = 0
    assert pair.redact(False) is False
    assert pair.redact(0) == 0
    assert pair.redact("remote_count=0") == "remote_count=0"

    pair.host_participant_id = 76561190000000001
    pair.client_participant_id = 76561190000000002
    assert pair.redact(76561190000000001) == "host"
    assert pair.redact("id=76561190000000002") == "id=client"
    assert pair.redact("1765611900000000019") == "1765611900000000019"

    return (
        "Steam clients rejoin the authenticated lobby after backend churn, "
        "and live tools require stable two-sided identity without corrupting zero/false"
    )


def test_steam_client_reauthentication_preserves_live_message_session() -> str:
    helpers = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/state_and_helpers.inl"
    )
    messages = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/network_messages.inl"
    )
    events = _read(
        "SolomonDarkModLoader/src/multiplayer_steam_session/lobby_event_handlers.inl"
    )
    suspend_start = helpers.index("void SuspendPeerForReauthentication(")
    reset_start = helpers.index("void ResetPeerForReauthentication(", suspend_start)
    remove_start = helpers.index("void RemovePeer(", reset_start)
    restart_start = helpers.index("void RestartClientHostHandshake(", remove_start)
    remove_all_start = helpers.index("void RemoveAllPeers()", restart_start)

    suspend_body = helpers[suspend_start:reset_start]
    reset_body = helpers[reset_start:remove_start]
    remove_body = helpers[remove_start:restart_start]
    restart_body = helpers[restart_start:remove_all_start]
    assert "UnregisterSteamGameplayPeer(steam_id);" in suspend_body
    assert "peer.authenticated = false;" in suspend_body
    assert "g_session.peers.erase" not in suspend_body
    assert "SteamCloseNetworkSession" not in suspend_body
    assert "UnregisterSteamGameplayPeer(steam_id);" in reset_body
    assert "g_session.peers.erase(steam_id);" in reset_body
    assert "SteamCloseNetworkSession" not in reset_body
    assert "ResetPeerForReauthentication(steam_id);" in remove_body
    assert "SteamCloseNetworkSession(steam_id);" in remove_body
    assert "ResetPeerForReauthentication(host_steam_id);" in restart_body
    assert "RemovePeer(host_steam_id);" not in restart_body
    assert "if (reset_failed_route)" in restart_body
    assert "SteamCloseNetworkSession(host_steam_id);" in restart_body
    assert "g_session.last_hello_send_ms = reset_failed_route" in restart_body

    keepalive_start = messages.index("void HandleSessionKeepalive(")
    pump_start = messages.index("void PumpNetworkMessages(", keepalive_start)
    keepalive_body = messages[keepalive_start:pump_start]
    assert "if (!peer.authenticated)" in keepalive_body
    assert "g_session.is_host" in keepalive_body
    assert "peer.rejected" in keepalive_body
    assert "peer.session_nonce == 0" in keepalive_body
    assert "peer.authenticated = true;" in keepalive_body
    assert "RegisterSteamGameplayPeer(message.sender_steam_id, false);" in keepalive_body

    expire_start = messages.index("void ExpireInactivePeers(")
    route_start = messages.index("void RefreshRouteStatus(", expire_start)
    expire_body = messages[expire_start:route_start]
    assert "SuspendPeerForReauthentication(steam_id);" in expire_body
    assert "ResetPeerForReauthentication(steam_id);" not in expire_body
    assert "SteamCloseNetworkSession" not in expire_body
    assert "RemovePeer(steam_id);" not in expire_body
    assert (
        'RestartClientHostHandshake(\n'
        '                steam_id, "authenticated_peer_timeout", false);'
        in expire_body
    )

    failed_event_start = events.index("case SteamEventKind::NetworkSessionFailed:")
    invite_event_start = events.index(
        "case SteamEventKind::LobbyInviteReceived:", failed_event_start
    )
    failed_event_body = events[failed_event_start:invite_event_start]
    assert (
        'RestartClientHostHandshake(\n'
        '                event.user_id, "network_session_failed", true);'
        in failed_event_body
    )

    return (
        "lobby-member reauthentication preserves the live Steam message session "
        "and a validated keepalive repairs an asymmetric host timeout"
    )


def test_poison_correction_ack_waits_for_native_application() -> str:
    transport_header = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    mod_loader_header = _read("SolomonDarkModLoader/include/mod_loader.h")
    requests = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    queue = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_gameplay_action_queues.inl"
    )
    action = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_poison_actions.inl"
    )
    authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "participant_vitals_authority.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_packet_sync.inl"
    )

    for text, token in (
        (transport_header, "void ConfirmLocalParticipantVitalsCorrection("),
        (transport, "void ConfirmLocalParticipantVitalsCorrection("),
        (mod_loader_header, "std::uint32_t correction_sequence,"),
        (requests, "std::uint32_t correction_sequence = 0;"),
        (queue, "request.correction_sequence = correction_sequence;"),
        (
            action,
            "multiplayer::ConfirmLocalParticipantVitalsCorrection(\n"
            "                local_player_poison_correction.correction_sequence);",
        ),
        (
            action,
            "QueueLocalPlayerPoisonCorrection(\n"
            "                local_player_poison_correction.correction_sequence,",
        ),
        (
            authority,
            "QueueLocalPlayerPoisonCorrection(\n"
            "                packet.correction_sequence,",
        ),
    ):
        assert token in text, f"poison correction confirmation lacks: {token}"

    normalize_start = incoming.index("NormalizedParticipantFrameState")
    apply_start = incoming.index("void ApplyParticipantFrameToRuntime(")
    normalize_body = incoming[normalize_start:apply_start]
    assert "if (life_acknowledged)" in normalize_body
    assert "poison_acknowledged" not in normalize_body

    handler_start = authority.index("void ApplyParticipantVitalsCorrectionPacket(")
    handler_body = authority[handler_start:]
    queue_position = handler_body.index("QueueLocalPlayerPoisonCorrection(")
    immediate_ack_position = handler_body.index(
        "last_applied_participant_vitals_correction_sequence ="
    )
    assert immediate_ack_position > queue_position
    assert "if (!poison_active)" in handler_body[queue_position:immediate_ack_position]

    return (
        "poison corrections acknowledge only after native application, retry a "
        "failed gameplay action, and cannot pin a cleared remote status"
    )


def test_native_item_pickup_converges_into_stock_inventory() -> str:
    gold_authority = _read(
        "tools/verify_multiplayer_gold_pickup_authority.py"
    )
    orb_authority = _read(
        "tools/verify_multiplayer_orb_pickup_authority.py"
    )
    native_item_verifier = _read(
        "tools/verify_multiplayer_native_item_inventory_sync.py"
    )
    native_potion_verifier = _read(
        "tools/verify_multiplayer_native_potion_inventory_sync.py"
    )
    loot_materialization = _read(
        "tools/verify_multiplayer_loot_drop_materialization.py"
    )
    native_inventory = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/native_inventory_reconciliation.inl"
    )
    native_item = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/native_item_materialization.inl"
    )
    host_deactivation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl"
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
    authority = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl"
    )
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
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
    assert "item_wearable_color_state=0x88" in layout
    assert "TryResolveNativeItemRecipe(" in native_item
    assert "SpawnNativeItemDropFromRecipe(" in native_item
    assert "using ItemDropPostRegisterFn = void(__stdcall*)(void* actor);" in native_types

    _require_in_order(
        authority,
        "QueueHostLootDropDeactivation(",
        "pending_host_loot_pickups_by_drop_id.emplace",
    )
    assert "ProcessCompletedHostLootPickups()" in authority
    assert "PumpHostLootDropDeactivation()" in host_deactivation
    assert "CallActorWorldUnregisterSafe(" not in host_deactivation
    assert host_deactivation.count("CallActorRequestRetirementSafe(") == 1
    assert "ParkReplicatedLootPresentationActor" not in host_deactivation
    assert "ParkReplicatedLootPresentationActor" not in replicated_loot
    assert "g_client_non_authoritative_loot_suppressed_actors" not in replicated_loot
    _require_in_order(
        host_deactivation,
        "request.drop_kind == multiplayer::LootDropKind::Gold",
        "request.drop_kind == multiplayer::LootDropKind::Orb",
        "request.drop_kind == multiplayer::LootDropKind::Powerup",
        "CallActorRequestRetirementSafe(",
    )
    _require_in_order(
        replicated_loot,
        "void RemoveUnboundClientLootActors(",
        "RemoveReplicatedLootPresentationActor(binding, &exception_code)",
    )
    assert "CallActorWorldUnregisterSafe(" not in transport
    assert "def wait_for_host_reward_unregistered(" in gold_authority
    assert '"host_drop_unregistered"' in gold_authority
    assert "wait_for_host_reward_zeroed" not in gold_authority
    assert "host gold reward actor remained registered" in gold_authority
    for token in (
        "STOCK_LOOT_WORLD_UNITS_PER_PICKUP_RANGE = 30.0",
        "PICKUP_RANGE_TEST_MARGIN = 0.95",
        "SPAWN_SETTLE_TOLERANCE = 3.0",
        "SPAWN_SETTLE_SECONDS = 0.4",
        "def settle_reachable_spawn_candidate(",
        "candidate = settle_reachable_spawn_candidate(",
        '"snapped_x": local_x',
        '"snapped_y": local_y',
        'capture_values.get(prefix + "pickup_range")',
        'local_row["pickup_range"]',
        'host_row["pickup_range"]',
        'last_client.get("pickup.result") == "Accepted"',
        "client proximity hook did not accept the in-range gold pickup",
    ):
        assert token in gold_authority, (
            f"gold verifier does not follow synchronized pickup geometry: {token}"
        )
    select_spawn = gold_authority[
        gold_authority.index("def select_spawn_point(") :
        gold_authority.index("\ndef verify_gold_pickup_authority(")
    ]
    assert "except Exception" not in select_spawn
    for token in (
        "STOCK_ORB_WORLD_UNITS_PER_PICKUP_RANGE = 60.0",
        "PICKUP_RANGE_TEST_MARGIN = 0.95",
        'capture_values.get(row_prefix + "pickup_range")',
        'local_row["pickup_range"]',
        'host_row["pickup_range"]',
        'last_client.get("pickup.result") == "Accepted"',
        "client orb proximity hook did not accept the in-range pickup",
    ):
        assert token in orb_authority, (
            f"orb verifier does not follow synchronized pickup geometry: {token}"
        )
    assert "PICKUP_POSITION_TOLERANCE" not in gold_authority + orb_authority
    assert "request_pickup_when_ready" not in orb_authority
    for verifier in (
        gold_authority,
        native_item_verifier,
        native_potion_verifier,
    ):
        assert "else:\n        request = request_pickup(network_drop_id)" not in verifier
    assert (
        "client item-drop proximity hook did not accept the in-range pickup"
        in native_item_verifier
    )
    for token in (
        "network_id: int | None = None",
        'drop["network_id"] != network_id',
        "local_actor_address: int | None = None",
        "excluded_network_ids: set[int] | None = None",
        'drop["network_id"] in excluded_network_ids',
        "pipe_name: str | None = None",
        "capture(CLIENT_PIPE if pipe_name is None else pipe_name)",
        "def wait_for_drop_metadata(",
    ):
        assert token in loot_materialization, (
            f"materialized-loot selector lacks exact drop correlation: {token}"
        )
    assert "pipe_name: str = CLIENT_PIPE" not in loot_materialization
    for token in (
        "host_drop_ids_before = {",
        "host_actor_addresses_before = {",
        "host_drop = wait_for_drop_metadata(",
        "pipe_name=HOST_PIPE",
        "excluded_network_ids=host_drop_ids_before",
        "excluded_actor_addresses=host_actor_addresses_before",
        'network_id = int(host_drop["network_id"])',
        "network_id=network_id",
    ):
        assert token in native_item_verifier, (
            f"native item verifier lacks exact host/client drop correlation: {token}"
        )
    for token in (
        "host_drop_ids_before = {",
        "host_drop = wait_for_drop_metadata(",
        "pipe_name=HOST_PIPE",
        "excluded_network_ids=host_drop_ids_before",
        'network_drop_id = int(host_drop["network_id"])',
        "network_id=network_drop_id",
    ):
        assert token in native_potion_verifier, (
            f"native potion verifier lacks exact host/client drop correlation: {token}"
        )
    assert (
        "client item-drop proximity hook did not accept the in-range potion pickup"
        in native_potion_verifier
    )
    _require_in_order(
        native_inventory,
        "QueueNativeInventoryCreditInternal(",
        "pending_native_inventory_credit_drop_ids.insert(network_drop_id)",
    )
    _require_in_order(
        native_inventory,
        "ExecuteNativeInventoryCreditNow(",
        "kItemDropHeldItemOffset,",
        "cleared_held_item_address",
        "CallInventoryInsertOrStackItemSafe(",
        "expected_quantity_after",
        "MarkLocalInventoryNativeConverged",
    )
    assert "completed_native_inventory_credit_drop_ids" in native_inventory
    assert "IsNativeInventoryCreditCompleted(snapshot.run_nonce" in replicated_loot
    assert "NativeInventoryCreditOutcome::ApplyStateUnknown" in pump
    assert "pending_native_inventory_credits.push_back" in pump
    _require_in_order(
        transport_api,
        "bool MarkLocalInventoryNativeConverged(",
        "inventory_revision != inventory_revision",
        "inventory_host_authoritative = false",
    )

    return (
        "accepted remote items and potions transfer through the stock insertion ABI, "
        "verify exact native inventory growth, deduplicate by run/drop, and release the ledger guard"
    )


def test_loot_deactivation_uses_stock_deferred_retirement() -> str:
    host_deactivation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl"
    )
    replicated_loot = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    generic_pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    post_tick_pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_main_thread_pump.inl"
    )
    app_tick = _read("SolomonDarkModLoader/src/background_focus_bypass.cpp")
    internal_api = _read("SolomonDarkModLoader/src/mod_loader_internal.h")
    steam_soak = _read(
        "tools/verify_steam_friend_host_loot_deactivation_soak.py"
    )

    assert "void PumpGameplayPostStockTickWork();" in internal_api
    assert "void PumpGameplayPostStockTickWork()" in post_tick_pump
    assert "PumpHostLootDropDeactivation();" in post_tick_pump
    assert "PumpHostLootDropDeactivation();" not in generic_pump
    assert "stock deferred-retirement request" in host_deactivation
    assert "CallActorWorldUnregisterSafe(" not in host_deactivation
    assert "CallActorWorldUnregisterSafe(" not in replicated_loot
    assert host_deactivation.count("CallActorRequestRetirementSafe(") == 1
    assert replicated_loot.count("CallActorRequestRetirementSafe(") == 1

    stock_tick = app_tick.find("original(app, edx);")
    post_tick = app_tick.find("PumpGameplayPostStockTickWork();", stock_tick)
    lifecycle_log = app_tick.find("LogCpuLifecycleGuardActivity();", stock_tick)
    assert 0 <= stock_tick < post_tick < lifecycle_log

    for token in (
        "DEFAULT_ITERATIONS = 64",
        "args.iterations <= 37",
        'pickup_owner = "client"',
        "pickup_pipe=CLIENT_ENDPOINT",
        "require_deferred_retirement_log(",
        'drop["host_native_actor_absent_after_pickup"]',
        'drop["client_native_actor_absent_after_pickup"]',
        'result["host_crash_delta"] or result["client_crash_delta"]',
    ):
        assert token in steam_soak, f"Steam loot-retirement soak lacks: {token}"

    return (
        "accepted host and replicated client loot use the stock deferred-retirement "
        "lifecycle from the app thread, with a 64-pickup two-account Steam soak"
    )


def test_client_loot_pickup_requests_are_single_flight_per_drop() -> str:
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    queue = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_queue_api.inl"
    )
    outgoing = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "outgoing_packet_sync.inl"
    )
    authority = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "loot_pickup_authority.inl"
    )

    for token in (
        "struct InFlightLocalLootPickupRequest",
        "g_in_flight_local_loot_pickup_requests_by_drop_id",
        "kLocalLootPickupRequestRetryMs",
        "void ClearLocalLootPickupRequestStateLocked()",
    ):
        assert token in transport, f"loot single-flight state lacks: {token}"
    _require_in_order(
        queue,
        "const auto queued_request_it = std::find_if(",
        "const auto in_flight_it =",
        "g_next_local_loot_pickup_request_sequence++",
        "g_queued_local_loot_pickup_requests.push_back(request)",
    )
    _require_in_order(
        outgoing,
        "requests.swap(g_queued_local_loot_pickup_requests)",
        "g_in_flight_local_loot_pickup_requests_by_drop_id[",
        "SendPacketToEndpoint(packet, endpoint)",
    )
    _require_in_order(
        authority,
        "CompleteInFlightLocalLootPickupRequest(",
        "UpdateRuntimeState([&](RuntimeState& state)",
    )

    return (
        "client loot pickup RPCs coalesce queued and in-flight requests by drop, "
        "retry only after a bounded timeout, and retire only their matching result sequence"
    )


def test_native_unregister_retires_address_bound_network_identity() -> str:
    header = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    transport_api = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_api.inl"
    )
    actor_lifecycle = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )

    assert "void NotifyLocalWorldActorUnregistered(uintptr_t actor_address);" in header
    _require_in_order(
        transport_api,
        "void NotifyLocalWorldActorUnregistered(uintptr_t actor_address)",
        "hub_world_actor_ids_by_address.erase(actor_address)",
        "run_host_local_world_actor_ids_by_address.erase(",
        "run_loot_drop_ids_by_address.erase(actor_address)",
    )
    _require_in_order(
        actor_lifecycle,
        "ForgetAuthoritativeTurnUndeadTargetLocksForActor(actor_address)",
        "multiplayer::NotifyLocalWorldActorUnregistered(actor_address)",
        "original(self, actor, remove_from_container)",
    )
    assert "remove_from_container == 1" in actor_lifecycle

    return (
        "the exact native unregister boundary retires host address-bound world and loot "
        "identities before the allocator can recycle that address for a different actor"
    )


def test_powerup_rewards_are_authoritative_and_native() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    capture = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/loot_snapshot_capture.inl"
    )
    authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/powerup_loot_authority.inl"
    )
    pickup_authority = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl"
    )
    hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/powerup_pickup_hook.inl"
    )
    reconciliation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
    )
    deactivation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/host_loot_drop_deactivation.inl"
    )
    native_progression = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/native_progression_sync.inl"
    )
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl"
    )
    incoming_state = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_sync.inl"
    )
    lua_gameplay = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    lua_runtime = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    layout = _read("config/binary-layout.ini")
    verifier = _read("tools/verify_multiplayer_powerup_sync.py")
    steam_verifier = _read("tools/verify_steam_friend_powerup_sync.py")
    bonus_skill_verifier = verifier[
        verifier.index("def verify_bonus_skill("):
        verifier.index("\ndef run_cases(", verifier.index("def verify_bonus_skill("))
    ]

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 64;",
        "Powerup = 5",
        "enum class PowerupRewardKind",
        "BonusSkillPoint = 0",
        "RandomSkillRank = 1",
        "DamageX4 = 2",
        "ParticipantTransientStatusFlagDamageX4",
        "std::int32_t damage_x4_remaining_ticks;",
        "std::int32_t powerup_kind;",
        "std::int32_t powerup_skill_entry_index;",
        "std::uint16_t powerup_skill_resulting_active;",
        "static_assert(sizeof(StatePacket) == 4204",
        "static_assert(sizeof(LootDropSnapshotPacketState) == 112",
        "static_assert(sizeof(LootSnapshotPacket) == 7200",
        "static_assert(sizeof(LootPickupResultPacket) == 164",
    ):
        assert token in protocol, f"powerup protocol lacks: {token}"

    for token in (
        "kPowerupRewardNativeTypeId",
        "TryPopulatePowerupLootDropSnapshot",
        "kPowerupRewardKindOffset",
        "kPowerupRewardMotionOffset",
        "kPowerupRewardLifetimeOffset",
        "kPowerupRewardProgressOffset",
        "kPowerupRewardValueOffset",
        "kPowerupRewardAuxiliaryOffset",
    ):
        assert token in capture, f"powerup carrier capture lacks: {token}"

    for token in (
        "TrySelectRandomSkillRankPowerupOption",
        "std::uint64_t owner_participant_id",
        "(owner_participant_id +",
        "g_local_transport.local_peer_id,\n                true,",
        "entry.active == 0",
        "TryResolveDamageX4DurationTicks",
        "RollParticipantSkillChoiceOptions",
        "IssueHostLevelUpOfferForParticipant",
        "IssueLocalHostSelfLevelUpOffer",
        "HydrateAuthoritativeRemoteProgressionEntryState",
        "ApplyLocalPlayerSkillChoiceOption",
        "TryWriteParticipantDamageX4Ticks",
        "ProcessQueuedLocalHostPowerupPickups",
        "queued.capture.requester_position_x",
        "captured_positions",
    ):
        assert token in authority, f"powerup authority lacks: {token}"
    assert "ApplyParticipantSkillChoiceOption(" not in authority, (
        "remote powerup replication must not execute stock skill-choice side effects"
    )

    for token in (
        "TryPreparePowerupReward",
        "packet.participant_id,\n                false,",
        "pending.packet.participant_id,\n                    false,",
        "TryApplyPreparedPowerupReward",
        "ProcessPendingHostPowerupPreparations",
        "awaiting_powerup_preparation",
        "powerup_prepared",
        "deferred powerup pickup deactivation queue expired",
        "IsPowerupPreparationPendingMaterializationError",
        "native_applied_powerup_result_drop_ids",
        "powerup_skill_resulting_active",
        "damage_x4_remaining_ticks",
    ):
        assert token in pickup_authority, f"powerup result flow lacks: {token}"

    assert "QueueLocalHostPowerupPickup" in hook
    assert "TryQueueReplicatedLootPickupRequest" in hook
    assert "QueueClientLocalLootSuppressionInternal" in hook
    assert "ParkReplicatedLootPresentationActor" not in reconciliation
    assert "ParkReplicatedLootPresentationActor" not in deactivation
    assert "CallActorWorldUnregisterSafe(" not in reconciliation
    assert "CallActorWorldUnregisterSafe(" not in deactivation
    assert "CallActorRequestRetirementSafe(" in reconciliation
    assert "CallActorRequestRetirementSafe(" in deactivation
    assert "actor_request_retirement_vfunc=0x18" in layout
    assert "kReplicatedLootPowerupNativeTypeId = 0x07F6" in reconciliation
    assert 'spawn_kind = "bonus_skill"' in reconciliation
    assert 'spawn_kind = "random_skill"' in reconciliation
    assert 'spawn_kind = "damage_x4"' in reconciliation
    assert "ReconcileRemoteParticipantDamageX4State" in native_progression
    assert "packet->damage_x4_remaining_ticks" in local_state
    assert "normalized.damage_x4_remaining_ticks" in incoming_state
    assert '"damage_x4_remaining_ticks"' in lua_gameplay
    assert '"damage_x4_remaining_ticks"' in lua_runtime
    assert "powerup_pickup=0x006039C0" in layout
    assert "game_timing_scale=0x00820230" in layout
    assert "progression_damage_x4_remaining_ticks=0x824" in layout

    for token in (
        "verify_random_skill",
        "verify_damage_x4",
        "verify_bonus_skill",
        "wait_for_carrier_retirement_requested",
        "wait_for_carrier_unregistered",
        'layout_offset("actor_pending_remove")',
        "run_cases",
        "wait_for_entry_parity",
        "wait_for_damage_x4_parity",
        "Waiting on 1 player",
        "client_random_skill",
        "host_random_skill",
        "client_damage_x4",
        "host_damage_x4",
        "client_bonus_skill",
        "host_bonus_skill",
    ):
        assert token in verifier, f"powerup live verifier lacks: {token}"

    _require_in_order(
        bonus_skill_verifier,
        "accepted = wait_for_accepted_pickup(",
        "retirement_requested = wait_for_carrier_retirement_requested(",
        "offer = wait_for_local_offer(",
        "choice = choose_local_option(",
        "cleared = wait_for_waiting_ids(",
        "cleanup = wait_for_carrier_unregistered(",
    )

    for token in (
        "SteamFriendActivePair",
        "require_shared_test_run",
        "SDMOD_STEAM_HOST_INSTANCE",
        "SDMOD_STEAM_CLIENT_INSTANCE",
        "powerups.run_cases",
        "find_new_crash_artifacts",
    ):
        assert token in steam_verifier, f"Steam powerup verifier lacks: {token}"

    return (
        "stock bonus-skill, learned-skill-rank, and DamageX4 rewards use host "
        "pickup authority, exact native owner/observer application, and a two-owner live matrix"
    )


def test_exact_native_equipment_identity_and_color_replicate() -> str:
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl"
    )
    incoming_state = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_sync.inl"
    )
    remote_playback = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/native_remote_playback.inl"
    )
    local_equip = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/local_player_native_equipment.inl"
    )
    inventory_getter = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    gameplay_constants = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/gameplay_constants.inl"
    )
    runtime_state = _read("SolomonDarkModLoader/include/multiplayer_runtime_state.h")
    lua_runtime = _read("SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp")
    binary_layout = _read("config/binary-layout.ini")
    public_equip = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_inventory.inl"
    )
    public_header = _read(
        "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    lua_gameplay = _read("SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp")
    pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    verifier = _read("tools/verify_multiplayer_native_item_inventory_sync.py")

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 64;",
        "ParticipantPresentationFlagEquipmentState = 1 << 5",
        "std::uint32_t primary_visual_link_recipe_uid;",
        "std::uint32_t secondary_visual_link_recipe_uid;",
        "std::uint32_t attachment_visual_link_recipe_uid;",
        "constexpr std::uint32_t kParticipantRingSlotCount = 3;",
        "struct ParticipantEquippedItemPacketState",
        "std::uint32_t equipment_revision;",
        "ParticipantEquippedItemPacketState equipped_rings[kParticipantRingSlotCount];",
        "ParticipantEquippedItemPacketState equipped_amulet;",
        "static_assert(sizeof(StatePacket) == 4204",
    ):
        assert token in protocol, f"exact equipment packet contract lacks: {token}"

    _require_in_order(
        local_state,
        "TryReadVisualLinkColorBlock(",
        "ParticipantPresentationFlagEquipmentState",
        "local->runtime.primary_visual_link_recipe_uid = primary_visual_recipe_uid;",
        "local->runtime.attachment_visual_link_recipe_uid =",
        "packet->primary_visual_link_recipe_uid =",
        "packet->attachment_visual_link_recipe_uid =",
    )
    _require_in_order(
        incoming_state,
        "void ApplyParticipantFrameToRuntime(",
        "participant->runtime.primary_visual_link_recipe_uid =",
        "participant->runtime.attachment_visual_link_recipe_uid =",
        "sample.primary_visual_link_recipe_uid =",
        "sample.attachment_visual_link_recipe_uid =",
    )
    _require_in_order(
        incoming_state,
        "equipment_packet_is_sane",
        "packet.equipped_rings",
        "participant->owned_progression.equipment_revision =",
    )

    for token in (
        "ApplyNativeRemoteParticipantEquipmentState(",
        "desired_type_id == 0",
        "SetEquipVisualLaneObject(",
        "CloneNativeItemFromRecipe(",
        "TryApplyNativeRemoteParticipantWearableColor(",
        "current.current_object_recipe_uid == desired_recipe_uid",
        "RefreshParticipantNativeProgression(",
        "equipment_reconcile_not_before_ms",
    ):
        assert token in remote_playback, f"remote native equipment reconciliation lacks: {token}"

    for token in (
        "RemoveNativeInventoryItemPointer(",
        "CallPointerListRemoveValueSafe(",
        "AttachLocalNativeEquipmentObject(",
        "ResolveLocalNativeEquipLaneByHolder(",
        "CallInventoryInsertOrStackItemSafe(",
        "RestoreLocalNativeEquipTransaction(",
        "CallActorProgressionRefreshSafe(",
        "current_object_recipe_uid != request.recipe_uid",
        "kStandaloneWizardRingItemTypeId",
        "kStandaloneWizardAmuletItemTypeId",
        "inventory.ring_lanes[index]",
        "inventory.amulet_lane",
    ):
        assert token in local_equip, f"local native equip transaction lacks: {token}"
    assert "kInventoryPlaceholderItemTypeId" in gameplay_constants
    for token in (
        "state->raw_item_count = raw_item_count;",
        "for (int index = 0; index < raw_item_count; ++index)",
        "item_type_id == kInventoryPlaceholderItemTypeId",
        "state->item_count += 1;",
    ):
        assert token in inventory_getter, (
            f"native inventory placeholder filtering lacks: {token}"
        )
    assert 'lua_setfield(state, -2, "raw_item_count")' in lua_gameplay
    _require_in_order(
        local_equip,
        "kGameplayInventoryDirtyOffset",
        "RemoveNativeInventoryItemPointer(",
        "AttachLocalNativeEquipmentObject(",
        "CallActorProgressionRefreshSafe(",
        "Native equipment verification did not converge",
    )

    for token in (
        "ParticipantEquipmentState",
        "std::uint32_t equipment_revision = 0;",
        "std::array<ParticipantEquippedItemState, kParticipantRingSlotCount> rings;",
    ):
        assert token in runtime_state, f"owned equipment state lacks: {token}"
    for token in (
        "RefreshOwnedEquipmentFromSnapshot(inventory_state",
        "packet.equipment_revision = local->owned_progression.equipment_revision;",
        "packet.equipped_rings[index]",
        "packet.equipped_amulet",
    ):
        assert token in local_state, f"owner equipment packet authoring lacks: {token}"
    for token in (
        "kGameplayEquipmentRing0Offset",
        "kGameplayEquipmentRing1Offset",
        "kGameplayEquipmentRing2Offset",
        "kGameplayEquipmentAmuletOffset",
        "state->ring_lanes[0]",
        "state->amulet_lane",
    ):
        assert token in inventory_getter, f"native ring/amulet capture lacks: {token}"
    for token in (
        "gameplay_equipment_ring_0=0x1430",
        "gameplay_equipment_ring_1=0x1434",
        "gameplay_equipment_ring_2=0x1438",
        "gameplay_equipment_amulet=0x143C",
    ):
        assert token in binary_layout, f"native equipment layout lacks: {token}"
    for token in (
        "PushEquipmentIdentityState",
        'lua_setfield(state, -2, "rings")',
        'lua_setfield(state, -2, "amulet")',
        'lua_setfield(state, -2, "equipment_revision")',
    ):
        assert token in lua_runtime, f"Lua equipment audit surface lacks: {token}"

    assert "bool QueuePlayerInventoryItemEquip(" in public_header
    assert "pending_local_inventory_equip_requests" in public_equip
    assert "ExecuteLocalInventoryEquipNow(" in pump
    assert "QueuePlayerInventoryItemEquip(" in lua_gameplay
    assert 'RegisterFunction(state, &LuaPlayerEquipInventoryItem, "equip_inventory_item")' in lua_gameplay

    for token in (
        "sd.player.equip_inventory_item",
        "previous_item_returned",
        "host_native_remote_equipment",
        "host_bot_color_matches",
        'last["client_inventory_revision"] > accepted_revision',
        'last["host_inventory_revision"] > accepted_revision',
        'all(last["color_matches"].values())',
    ):
        assert token in verifier, f"native equipment live verifier lacks: {token}"

    return (
        "exact hat/robe/staff-or-wand presentation plus all three ring slots and the amulet "
        "flow from stock local ownership through protocol v64; visible lanes self-correct natively"
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

    world_reconciliation = _read(
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
    window = _read("SolomonDarkModLauncher.UI/src/Views/MainWindow.xaml")
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
        "pendingAcceptedInvite_",
        "TryLaunchPendingInvite",
        "The launcher connects to",
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
    for token in (
        'Content="Join Lobby ID"',
        'Content="How to Play"',
        "Select the host's lobby through Steam",
        "Steam P2P sends all gameplay data",
        "LobbyConnectionDetailsText",
    ):
        assert token in window, f"launcher UI lacks: {token}"
    for removed in (
        "Join Friend",
        "Join Steam Invite",
        "Waiting for a Steam Invite",
        "HostPrivacyPassword",
    ):
        assert removed not in window, f"launcher UI retains removed flow: {removed}"
    _require_in_order(
        publisher,
        'hubObserved = hubObserved || status?.GamePhase == "hub"',
        "if (hubObserved &&",
        "AnnounceAsync(client, secret!, status!)",
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
        "if (multiplayer::ShouldPauseGameplayForLevelUpSelection())",
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
    level_hook = _read(
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
        "constexpr std::uint16_t kProtocolVersion = 64;",
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
        "multiplayer::ShouldPauseGameplayForLevelUpSelection()",
        "resolved_player_actor_tick",
        "actor_tick_address != resolved_player_actor_tick",
        "actor_initialize(actor);",
        "actor_tick(actor);",
    ):
        assert token in actor_world_hook, f"actor-world level-up pause lacks: {token}"
    _require_in_order(
        actor_world_hook,
        "if (!multiplayer::ShouldPauseGameplayForLevelUpSelection())",
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


def test_native_remote_fireball_retains_cast_heading_until_projectile_birth() -> str:
    playback = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_playback.inl"
    )
    documentation = _read("docs/spell-cast-cleanup-chain.md")

    for token in (
        "const bool cast_heading_owns_native_initialization =",
        "ongoing_cast.active &&",
        "ongoing_cast.have_aim_heading &&",
        "!ongoing_cast.remote_per_cast_projectile_observed;",
        "NormalizeWizardActorHeadingForWrite(ongoing_cast.aim_heading)",
        ": binding->replicated_target_heading;",
        "ShortestHeadingDeltaDegrees(heading, next_heading)",
        "ApplyWizardActorFacingState(actor_address, next_heading);",
    ):
        assert token in playback, f"remote Fire heading ownership lacks: {token}"
    assert (
        "const float next_heading = binding->replicated_target_heading;"
        not in playback
    ), "replicated transform heading must not overwrite pre-birth Fire cast aim"

    for token in (
        "Fire (0x0053DC60)",
        "actor + 0x6C",
        "0x00410500",
        "Fireball + 0x13C/+0x140",
        "0x00529380",
        "per-cast projectile is observed",
        "already-created projectile.",
    ):
        assert token in documentation, f"Fire direction RE contract lacks: {token}"

    return (
        "native remote Fire casts retain cast-facing through stock projectile "
        "birth, then return heading ownership to participant playback"
    )


def test_native_remote_fireball_inverts_presentation_heading_for_stock_fire() -> str:
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
    assert (
        "NormalizeWizardActorHeadingForWrite(ongoing_cast.aim_heading)"
        not in playback
    ), "presentation heading must not be written directly into stock Fire direction"

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
        "remote Fire replay converts all cardinal presentation headings into "
        "stock native directions"
    )


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
        "kActorPositionXOffset, frozen_x",
        "kActorPositionYOffset, frozen_y",
        "return 1;",
        "IsBoundReplicatedRunEnemyActorForLocalClient(actor_address)",
        "return original(movement_context, actor, move_x, move_y);",
    )

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
    _require_in_order(
        body,
        "original(self);",
        "ApplyPinnedManualSpawnerPrimaryTarget(actor_address);",
        "QueueLocalPlayerPrimaryCastForMultiplayer(actor_address);",
    )
    return (
        "manual primary casts restore their world target after stock cursor "
        "refresh and before owner-authored packet capture"
    )


def test_new_run_retires_the_prior_host_run_exit_latch() -> str:
    header = _read("SolomonDarkModLoader/include/multiplayer_local_transport.h")
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    run_hooks = _read(
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


def test_secondary_behavior_matrix_uses_native_two_owner_witnesses() -> str:
    harness = _read("tools/multiplayer_secondary_behavior_harness.py")
    runner = _read("tools/verify_steam_friend_active_pair_secondary_behavior.py")
    active_pair = _read("tools/steam_friend_active_pair.py")
    focus = _read("tools/verify_multiplayer_focus_behavior_sync.py")
    ring = _read("tools/verify_multiplayer_ring_of_fire_multikill_stability.py")
    layout = _read("config/binary-layout.ini")
    seams = _read("SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl")
    mouse_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_mouse_refresh_hook.inl"
    )
    input_queue = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_input_queueing.inl"
    )
    lua_input = _read("SolomonDarkModLoader/src/lua_engine_bindings_input.cpp")
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    runtime_state = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_state.h"
    )
    transport = _read("SolomonDarkModLoader/src/multiplayer_local_transport.cpp")
    spell_effect_sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "spell_effect_sync.inl"
    )
    spell_effect_reconciliation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "spell_effect_reconciliation.inl"
    )
    world_capture = read_source_unit(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "world_snapshot_capture.inl"
    )
    world_packet_builder = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "local_snapshot_packet_builders.inl"
    )
    world_packet_reader = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "incoming_snapshot_packet_sync.inl"
    )
    world_fragmentation = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "world_snapshot_fragmentation.inl"
    )
    world_reconciliation = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "world_snapshot_reconciliation.inl"
    )
    status_reader = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_actor_calls/lifecycle_and_stat_calls.inl"
    )
    status_reconcile = read_source_unit(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_casting/transient_status_reconciliation.inl"
    )
    entity_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "core/participant_entity_state.inl"
    )
    vitals_authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "participant_vitals_authority.inl"
    )
    secondary_replay = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_casting/native_secondary_cast_replay.inl"
    )
    gameplay_api = _read("SolomonDarkModLoader/include/mod_loader_gameplay_api.inl")
    state_getters = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_state_getters.inl"
    )
    debug_observations = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_debug/"
        "functions_combat_observations.inl"
    )
    debug_bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp")
    dampen_context = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "stock_dampen_effect_context.inl"
    )
    dampen_rendering = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "gameplay_dampen_rendering.inl"
    )
    dampen_effect = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/"
        "multiplayer_dampen_effect.inl"
    )
    player_cast_hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl"
    )
    turn_undead_target_lock = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
        "turn_undead_caster_target_lock.inl"
    )
    monster_pathfinding = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "monster_pathfinding_hook.inl"
    )
    actor_lifecycle = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_actor_lifecycle_hooks.inl"
    )

    assert len(re.findall(r"^\s*SecondarySkillSpec\(\d+,", harness, re.MULTILINE)) == 23
    for token in (
        '"[bots] remote native secondary cast replayed."',
        'and "success=1" in line',
        '"Injected gameplay mouse-right click."',
        '"native_mouse_right_injection_count"',
        '"native_keyboard_edge_count"',
        "concurrent.futures.ThreadPoolExecutor(max_workers=2)",
        "SECONDARY_SKILL_BELT_SLOTS = (0, 1, 2, 5, 6, 7)",
        "if belt[slot] == -1",
        "ARM_EFFECT_MONITOR_LUA",
        "COLLECT_EFFECT_MONITOR_LUA",
        "primary.spawn_one_enemy(",
        "primary.find_target(",
        "target_x = float(owner_transform[0]) + TARGET_OFFSET_X",
        "target_y = float(owner_transform[1]) + TARGET_OFFSET_Y",
        "wait_for_target_convergence(",
        "maximum_hp_satisfied",
        "damage_baseline_hp",
        'float(target["baseline"]["host"]["hp"])',
        'float(target_after["client"]["hp"])',
        'skill.behavior in ("area_damage", "target_damage")',
        '"host_damage": host_damage',
        '"client_damage": client_damage',
        'native_mana_spent = float(mana_observation["spent_total"])',
        'float(mana_observation["spent_total"])',
        "sd.debug.reset_local_cast_observation(1)",
        "sd.debug.get_local_cast_observation(1)",
        'int(mana_observation["spend_call_count"]) < 1',
        "after_delivery_owner = query_vitals(",
        "wait_for_vitals_convergence(",
        "mana_error <= mana_tolerance",
        "observer_mana_error",
        "shared_effect_types",
        'SecondarySkillSpec(27, "Magic Storm", "field", True, True, 0x07F0)',
        "synchronized_effect_type: int | None = None",
        "verify_synchronized_effect_positions(",
        "wait_for_effect_type_absent(",
        'owner["last_x"] - best["last_x"]',
        'if maximum_position_error > tolerance:',
        '"effect_position_sync": effect_position_sync',
        "NATIVE_TRANSIENT_STATUS_FLAGS",
        "run_native_transient_status(",
        'observer["native_transient_status_flags"] & status_flag',
        "MINIMUM_TRANSIENT_STATUS_OBSERVATION_SECONDS = 2.5",
        "MINIMUM_TRANSIENT_STATUS_COMPARISON_SAMPLES = 2",
        "TRANSIENT_STATUS_CLEAR_PROPAGATION_BUDGET_SECONDS = 2.0",
        "active_observation_seconds = owner_cleared_at - owner_active_since",
        "minimum_matching_samples = math.ceil(compared_active_samples * 0.9)",
        "clear_delay > clear_delay_budget",
        "baseline = rush.run_movement_trial(",
        "extra_displacement < 60.0",
        "position_error > 2.0",
        'SecondarySkillSpec(54, "Magic Shield", "magic_shield")',
        "run_magic_shield(",
        "defense.invoke_native_magic_hit_trial(",
        "require_life_loss=False",
        'expected_capacity=MAGIC_SHIELD_RANK_ONE_ABSORB',
        'flashes["observer_replicated"] <= 0.001',
        'expected_capacity=0.0',
        "NATIVE_TARGET_MODIFIER_TYPES = {",
        "30: 0x1B76",
        "35: 0x1B6F",
        "QUERY_ACTOR_MODIFIERS_LUA",
        "sd.debug.get_actor_modifiers(actor)",
        'target.get("actor_address", "0")',
        "require_target_modifier_absent(",
        "wait_for_target_modifier_sync(",
        'durations["host"] > 0',
        'durations["client"] > 0',
        "duration_error <= duration_tolerance",
        'SecondarySkillSpec(51, "Dampen", "dampen")',
        "DAMPEN_DISPATCH_TOKEN",
        "DAMPEN_PRESENTATION_PATTERN",
        "prepare_dampen_shared_view_geometry(",
        "DAMPEN_SHARED_VIEW_OFFSET_X = 160.0",
        "owner_on_observer = rush.wait_for_remote_convergence(",
        "observer_on_owner = rush.wait_for_remote_convergence(",
        "wait_for_dampen_application(",
        'source["cast_sequence"] != observer["cast_sequence"]',
        'source["authority_instance"]',
        '"projectiles_repelled"',
        '"mages_disrupted"',
        '"shields_dispelled"',
        'SecondarySkillSpec(77, "Turn Undead", "turn_undead", True)',
        "TURN_UNDEAD_ELIGIBLE_ACTOR_TYPES",
        "QUERY_TURN_UNDEAD_STATE_LUA",
        "actor_turn_undead_flee_heading",
        "actor_turn_undead_activation_scalar",
        "actor_turn_undead_duration_ticks",
        "require_turn_undead_baseline(",
        "wait_for_turn_undead_activation(",
        "clear_turn_undead_target_freeze(",
        "wait_for_turn_undead_flee(",
        "TURN_UNDEAD_MINIMUM_DISPLACEMENT",
        "TURN_UNDEAD_MINIMUM_RADIAL_GAIN",
        "TURN_UNDEAD_MAXIMUM_VISUAL_POSITION_ERROR",
        'and state["duration_ticks"] > 0',
        "best_active_radial_gain",
    ):
        assert token in harness, f"secondary behavior harness lacks: {token}"
    for source, token in (
        (transport, "kMagicStormNativeTypeId = 0x07F0"),
        (spell_effect_sync, "case kMagicStormNativeTypeId:"),
        (spell_effect_sync, "IsReplicatedSpellEffectMotionNativeType("),
        (
            spell_effect_sync,
            "if (IsReplicatedSpellEffectMotionNativeType(actor.object_type_id)",
        ),
        (spell_effect_reconciliation, "if (effect.transform_valid && !native_replay_driven_primary)"),
    ):
        assert token in source, (
            f"Magic Storm authoritative effect-transform path lacks: {token}"
        )
    for token in (
        "actor_turn_undead_flee_heading=0x19C",
        "actor_turn_undead_activation_scalar=0x1B4",
        "actor_turn_undead_duration_ticks=0x20C",
    ):
        assert token in layout, f"Turn Undead native state layout lacks: {token}"
        assert f'"{token.split("=")[0]}"' in seams, (
            f"Turn Undead native state seam lacks: {token}"
        )
    for token in (
        "WorldActorStatusFlagTurnUndeadStateValid",
        "WorldActorStatusFlagTurnUndeadActive",
        "IsTurnUndeadEligibleRunEnemyType(",
        "std::uint8_t status_flags;",
        "std::int32_t turn_undead_duration_ticks;",
        "float turn_undead_flee_heading;",
        "float turn_undead_activation_scalar;",
    ):
        assert token in protocol, f"Turn Undead wire status lacks: {token}"
        assert token.split(";")[0] in runtime_state + protocol, (
            f"Turn Undead runtime status lacks: {token}"
        )
    for source, token in (
        (world_capture, "PopulateRunEnemyTransientStatusSnapshot("),
        (world_capture, "kActorTurnUndeadDurationTicksOffset"),
        (world_packet_builder, "PopulateRunEnemyTransientStatusSnapshot("),
        (world_packet_reader, "actor.status_flags = packet_actor.status_flags"),
        (world_fragmentation, "kWorldActorStatusKnownFlags"),
        (world_fragmentation, "turn_undead_active && !turn_undead_state_valid"),
        (world_reconciliation, "CopyWorldActorTransientStatusState("),
        (world_reconciliation, "ApplyReplicatedRunEnemyTransientStatus("),
        (world_reconciliation, "local_duration_ticks > 0"),
    ):
        assert token in source, (
            f"authoritative Turn Undead status path lacks: {token}"
        )
    for source, token in (
        (turn_undead_target_lock, "CaptureAuthoritativeTurnUndeadPrecastState("),
        (turn_undead_target_lock, "duration_ticks < -100000"),
        (turn_undead_target_lock, "RegisterAuthoritativeTurnUndeadCasterTargets("),
        (turn_undead_target_lock, "current_duration_ticks <= previous.duration_ticks"),
        (turn_undead_target_lock, "WriteAuthoritativeTurnUndeadCasterTarget("),
        (turn_undead_target_lock, "caster_actor_address"),
        (player_cast_hooks, "CaptureAuthoritativeTurnUndeadPrecastState("),
        (player_cast_hooks, "RegisterAuthoritativeTurnUndeadCasterTargets("),
        (secondary_replay, "CaptureAuthoritativeTurnUndeadPrecastState("),
        (secondary_replay, "RegisterAuthoritativeTurnUndeadCasterTargets("),
        (monster_pathfinding, "ApplyAuthoritativeTurnUndeadCasterTargetLock("),
        (actor_lifecycle, "ForgetAuthoritativeTurnUndeadTargetLocksForActor("),
        (actor_lifecycle, "ClearAuthoritativeTurnUndeadTargetLocks();"),
    ):
        assert token in source, (
            f"authoritative Turn Undead caster-target lock lacks: {token}"
        )
    _require_in_order(
        monster_pathfinding,
        "ApplyAuthoritativeTurnUndeadCasterTargetLock(hostile_actor_address)",
        "if (multiplayer::IsLocalTransportClient())",
        "original(self, nullptr);",
    )
    assert "TARGET_X =" not in harness
    assert "TARGET_Y =" not in harness
    assert 'SecondarySkillSpec(21, "Ring of Fire", "area_damage", True, True)' not in harness
    assert 'SecondarySkillSpec(35, "Ring of Ice", "target_status", True, True)' not in harness
    discovery = active_pair[
        active_pair.index("def discover(self)") :
        active_pair.index("def redact(self", active_pair.index("def discover(self)"))
    ]
    assert "except VerifyFailure as exc:" in discovery
    assert "last_read_error = str(exc)" in discovery
    assert "self.lua(" not in discovery

    requires_slot_zero = secondary_replay[
        secondary_replay.index("bool RequiresStockSecondaryActorSlotZero(") :
        secondary_replay.index(
            "struct ScopedStockSecondaryActorSlotZeroContext"
        )
    ]
    assert "return skill_entry_index == 0x1E;" in requires_slot_zero
    slot_zero_return = re.search(r"return\s+[^;]+;", requires_slot_zero)
    assert slot_zero_return is not None
    assert slot_zero_return.group(0) == "return skill_entry_index == 0x1E;"
    for token in (
        "ScopedStockSecondaryActorSlotZeroContext",
        "kActorSlotOffset",
        "original_slot",
        "applied_slot != 0",
        "restored_slot == original_slot",
        "return slot_context.ready && slot_context.restored;",
        "InvokeWithStockSecondaryActorSlotZeroContext(",
        "stock_slot_context_ok &&",
        "stock_effect_verified &&",
        "kNativePrismaticModifierTypeId",
        "modifier.duration_ticks > 0",
        '" stock_slot_context_ok="',
    ):
        assert token in secondary_replay, (
            f"Prismatic stock slot transaction lacks: {token}"
        )
    assert secondary_replay.count("InvokeWithStockSecondaryActorSlotZeroContext(") == 2

    for token in (
        "dampen_stock_effect_block=0x0054F0D6",
        "kDampenStockEffectBlock",
    ):
        assert token in layout + seams + _read(
            "SolomonDarkModLoader/src/gameplay_seams.h"
        ), f"stock Dampen presentation seam lacks: {token}"
    for token in (
        "kStockDampenEffectBlockBytes",
        "0x53, 0x83, 0xEC, 0x08, 0x8D",
        "0x46, 0x18, 0x8B, 0xCC, 0x89",
        "kStockDampenEffectBlockSkipBytes",
        "0xC6, 0x44, 0x24, 0x1F, 0x01",
        "0xE9, 0x3B, 0x00, 0x00, 0x00",
        "ScopedStockDampenEffectSuppression",
        "current != kStockDampenEffectBlockBytes",
        "applied != kStockDampenEffectBlockSkipBytes",
        "restored_bytes == kStockDampenEffectBlockBytes",
        "return succeeded;",
    ):
        assert token in dampen_context, (
            f"stock Dampen effect-call transaction lacks: {token}"
        )
    assert player_cast_hooks.count(
        "InvokeWithStockDampenEffectSuppressed("
    ) == 2
    assert "TryConsumeLocalMultiplayerDampenMana" not in player_cast_hooks
    assert "Multiplayer remote Dampen used the safe replicated dispatcher" not in (
        player_cast_hooks
    )
    for token in (
        "kMultiplayerDampenDisruptableFlag = 0x2u",
        "actor.object_header_word &",
        "kMultiplayerDampenDisruptableFlag",
    ):
        assert token in dampen_effect, (
            f"deterministic Dampen native-family gate lacks: {token}"
        )
    assert "if (!actor.tracked_enemy)" not in dampen_effect
    assert "QueueDebugUiMultiplayerDampenPresentation(" in dampen_effect
    for token in (
        "BuildGameplayDampenPresentationRenderItems(",
        "multiplayer::GetLocalTransportParticipantId()",
        'element.surface_id == "gameplay_nameplate"',
        "D3DPT_LINESTRIP",
        "DrawGameplayDampenPresentation(",
        '"Multiplayer Dampen DX9 presentation drawn.',
    ):
        assert token in dampen_rendering, (
            f"multiplayer Dampen DX9 presentation lacks: {token}"
        )

    for source, token in (
        (gameplay_api, "bool TryListNativeActorModifiers("),
        (state_getters, "bool TryListNativeActorModifiers("),
        (state_getters, "kActorModifierListCountOffset"),
        (state_getters, "kNativeModifierTypeIdOffset"),
        (state_getters, "kNativeModifierDurationTicksOffset"),
        (debug_observations, "int LuaDebugGetActorModifiers("),
        (debug_bindings, '"get_actor_modifiers"'),
    ):
        assert token in source, f"exact native modifier witness lacks: {token}"

    for token in (
        "SteamFriendActivePair",
        "require_shared_test_run",
        "secondary.ensure_batch_capacity(",
        "for direction in context.focus_directions:",
        "reset_quiet_arena(",
        "secondary.wait_for_effect_type_absent(",
        '"prior_effect_retirement"',
        "require_manual_spawner=skill.target_required",
        "secondary.acquire_skill(",
        "secondary.run_skill(",
        "find_new_crash_artifacts",
    ):
        assert token in runner, f"Steam secondary behavior runner lacks: {token}"
    _require_in_order(
        runner,
        'output["active_step"] = "initial_arena_reset"',
        'output["initial_arena_reset"] = reset_quiet_arena()',
        'output["active_step"] = "capacity"',
        'output["active_step"] = "acquire"',
    )

    for token in (
        "gameplay_mouse_right_button=0x27A",
        "FUN_00429820 writes raw mouse-mask bit 2",
    ):
        assert token in layout, f"right-mouse layout lacks: {token}"
    assert '"gameplay_mouse_right_button"' in seams
    for token in (
        "kGameplayMouseRightButtonOffset",
        "pending_mouse_right_frames",
        "ClearRawGameplayMouseRight",
        "Injected gameplay mouse-right click",
        "Released injected gameplay mouse-right",
    ):
        assert token in mouse_hook, f"right-mouse hook lacks: {token}"
    for token in (
        "bool QueueGameplayBindingPress(",
        "kMouseLeftBindingCode = 0x200",
        "kMouseRightBindingCode = 0x201",
        "return QueueGameplayMouseRightClick(error_message);",
    ):
        assert token in input_queue, f"exact binding dispatcher lacks: {token}"
    for token in (
        'RegisterFunction(state, &LuaInputPressBinding, "press_binding")',
        'RegisterFunction(state, &LuaInputHoldMouseRightFrames, "hold_mouse_right_frames")',
        'RegisterFunction(state, &LuaInputClearMouseRight, "clear_mouse_right")',
        'RegisterFunction(state, &LuaInputGetMouseRightState, "get_mouse_right_state")',
    ):
        assert token in lua_input, f"Lua right-mouse binding lacks: {token}"
    assert "falling back to windowed SendInput" not in lua_input
    assert "sd.input.press_binding" in focus
    assert "sd.input.hold_mouse_right_frames" not in focus
    assert "activation was not consumed" in focus
    assert "source_offset = log_position(direction.source_log)" in focus
    assert "log_after(direction.source_log, source_offset)" in focus
    assert "deadline - time.monotonic()" in focus
    assert "time.sleep(min(0.05, remaining))" in focus
    assert "consumption_count_before" not in focus
    assert "def queue_secondary_belt_slot(" in focus
    assert "def queue_until_accepted_casts(" in focus
    assert "parse_secondary_accept_times(last_log, belt_slot)" in focus
    assert '"native_accept_timestamps"' in focus
    assert "(current - previous).total_seconds()" in focus
    assert "wait_for_next_accept" not in focus
    assert '"input_kind": "mouse_right" if mouse_backed else "keyboard"' in focus
    for relative_path in (
        "tools/verify_multiplayer_focus_behavior_sync.py",
        "tools/verify_multiplayer_persistent_status_sync.py",
        "tools/verify_multiplayer_ring_of_fire_multikill_stability.py",
        "tools/multiplayer_secondary_behavior_harness.py",
    ):
        tree = ast.parse(_read(relative_path), filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if function_name != "cast_secondary_belt_slot":
                continue
            has_timeout = len(node.args) >= 3 or any(
                keyword.arg == "timeout" for keyword in node.keywords
            )
            assert has_timeout, (
                f"{relative_path} calls cast_secondary_belt_slot without its "
                "bounded input-consumption timeout"
            )
    assert "input_witnessed = (" in harness
    assert "if belt_slot == 0" in harness
    assert "click_process(" not in ring
    assert 'input_modes.append("live_native_binding")' in ring

    for token in (
        "ParticipantTransientStatusFlagPlanewalker = 1 << 2",
        "ParticipantTransientStatusFlagStoneskin = 1 << 3",
        "constexpr std::uint16_t kProtocolVersion = 64;",
    ):
        assert token in protocol, f"native transient status protocol lacks: {token}"
    for token in (
        "kActorRenderDriveFlagsOffset",
        "ParticipantTransientStatusFlagPlanewalker",
        "kNativeStoneskinModifierTypeId",
        "ParticipantTransientStatusFlagStoneskin",
    ):
        assert token in status_reader, f"native transient status reader lacks: {token}"
    for token in (
        "kNativeTransientStatusMappings",
        "RemoveAllNativeActorModifiersByType(",
        "InvokeNativeRemoteParticipantSecondarySkill(",
        "transient_status_reconcile_not_before_ms",
        "now_ms + 500",
        "now_ms + (verified ? 100 : 1000)",
    ):
        assert token in status_reconcile, (
            f"native transient status reconciliation lacks: {token}"
        )
    assert "transient_status_reconcile_desired_flags" in entity_state
    assert (
        "transient_status_flags & ParticipantTransientStatusFlagPoisoned"
        in vitals_authority
    ), "host damage correction must not claim owner-authored secondary statuses"

    primary = _read("tools/verify_multiplayer_primary_kill_stress.py")
    faster = _read("tools/verify_multiplayer_faster_caster_behavior_sync.py")
    stale_hold = _read("tools/verify_steam_friend_world_snapshot_stale_hold.py")
    for source, token in (
        (primary, 'network_id = int(spawn["network_actor_id"])'),
        (harness, 'network_id = int(spawned["network_actor_id"])'),
        (faster, 'network_id = int(spawn["network_actor_id"])'),
        (stale_hold, 'network_id = int(spawn["network_actor_id"])'),
    ):
        assert token in source, (
            "spawn-driven combat verification must bind the exact returned "
            f"network actor id: {token}"
        )
    assert '"network_actor_id": network_actor_id' in primary

    _require_in_order(
        runner,
        'output["capacity"] = secondary.ensure_batch_capacity(',
        'output["acquisitions"] = {}',
        'output["behaviors"] = {}',
        "reset_quiet_arena(",
        "secondary.run_skill(",
    )
    return (
        "all 23 native secondary skills have a capacity-safe real-Steam matrix "
        "with both-owner dispatch, replay, effect, resource, target, and motion witnesses"
    )


def test_mana_recovery_tolerance_respects_float32_precision() -> str:
    import verify_multiplayer_all_stat_sync as stats

    # Native progression mana is stored as a 32-bit float. A comparison exactly
    # on the semantic 0.5 boundary can therefore arrive one float ULP above it.
    assert not stats.exceeds_float32_tolerance(
        0.5000001192092896,
        0.5,
        (1.0, 1.5),
    )
    assert stats.exceeds_float32_tolerance(
        0.501,
        0.5,
        (1.0, 1.5),
    )
    return "mana comparison admits one native-float rounding edge, not real skew"


def test_health_up_contract_composes_with_life_charm() -> str:
    import verify_multiplayer_all_stat_sync as stats

    ranked_values = (0.0, 50.0, 100.0, 150.0, 200.0)
    assert stats.expected_ranked_max_hp(62.5, 0, 2, ranked_values) == 187.5
    assert stats.expected_ranked_max_hp(187.5, 2, 4, ranked_values) == 312.5
    return "HEALTH UP retains the native Life Charm multiplier from any initial rank"


def test_mana_up_contract_replaces_the_initial_rank_bonus() -> str:
    import verify_multiplayer_all_stat_sync as stats

    ranked_values = (0.0, 100.0, 200.0, 300.0, 400.0)
    assert stats.expected_ranked_max_mp(100.0, 0, 3, ranked_values) == 400.0
    assert stats.expected_ranked_max_mp(200.0, 1, 3, ranked_values) == 400.0
    return "MANA UP replaces an inherited rank bonus instead of counting it twice"


def test_world_stale_hold_controls_the_exact_remote_host_process() -> str:
    verifier = _read("tools/verify_steam_friend_world_snapshot_stale_hold.py")
    for token in (
        'if PAIR_BACKEND == "remote-windows-host":',
        "remote_windows_process_id()",
        "def suspend_remote_windows_game(",
        "[string]::Equals([string]$cim.ExecutablePath,$path,",
        "return suspend_remote_windows_game(pid, duration_ms)",
    ):
        assert token in verifier, token
    _require_in_order(
        verifier,
        "configure(pair)",
        "primary.cleanup_live_enemies()",
        "manual_prelude = primary.enable_manual_stock_spawner_combat()",
    )
    assert "finally:\n        primary.cleanup_live_enemies()" in verifier
    return "stale-authority testing suspends only the exact remote Windows host game"


def test_hub_presentation_uses_stored_authority_across_lifecycle_rotation() -> str:
    import probe_hub_npc_presentation_sync as presentation

    client = {
        "repactor.1.network_id": "123",
        "repactor.1.type": str(presentation.STUDENT_TYPE_ID),
        "appactor.1.network_id": "123",
        "appactor.1.type": str(presentation.STUDENT_TYPE_ID),
        "appactor.1.student_book_palette_count": "0",
        "binding.1.network_id": "123",
        "binding.1.address": "0x1000",
        "binding.1.type": str(presentation.STUDENT_TYPE_ID),
        "binding.1.matched": "true",
        "binding.1.parked": "false",
        "actor.1.address": "0x1000",
        "actor.1.type": str(presentation.STUDENT_TYPE_ID),
        "replicated.apply_valid": "true",
        "replicated.apply_presentation_available": "true",
        "replicated.apply_presentation_received_ms": "90",
        "replicated.applied_ms": "100",
        "replicated.sampled_ms": "110",
    }
    comparison = presentation.compare_host_to_client({}, client)
    assert comparison["summary"]["compared_total"] == 1
    assert comparison["summary"]["student_compared"] == 1
    assert comparison["comparisons"][0]["student_color_match"]
    assert comparison["comparisons"][0]["student_book_palette_match"]
    return "hub presentation survives host lifecycle rotation by using stored applied authority"




def test_hub_services_use_typed_native_lua_dispatch() -> str:
    layout = _read("config/binary-layout.ini")
    runtime = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/hub_service_runtime.inl"
    )
    public_api = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_hub.inl"
    )
    lua = _read("SolomonDarkModLoader/src/lua_engine_bindings_input.cpp")
    pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )

    for token in (
        "hub_service_dispatch=0x00514A20",
        "hub_courtyard=0x00819A70",
        "hub_chat_active=0x008199F0",
        "hub_courtyard_vtable=0x00792644",
        "inventory_screen_vtable=0x00794F54",
        "inventory_shop_vtable=0x0079044C",
        "gameplay_hub_surface=0x15A0",
        "hub_luthacus_storage_action=0x10D0",
        "hub_fomentius_action=0x1184",
        "hub_hagatha_action=0x101C",
        "inventory_screen_shop=0x160",
    ):
        assert token in layout, f"typed hub service layout lacks: {token}"

    for token in (
        "enum class HubServiceKind",
        'name == "luthacus_storage"',
        'name == "fomentius"',
        'name == "hagatha"',
        "IsSharedHubSceneContext(scene_context)",
        "surface.chat_active",
        "surface.surface_active",
        "courtyard_vtable != expected_courtyard_vtable",
        "vtable_dispatch_address != dispatch_address",
        "CallHubServiceDispatchSafe",
        "surface.inventory_screen_active",
        "surface.inventory_shop_active",
    ):
        assert token in runtime, f"typed hub service runtime lacks: {token}"
    assert "SendInput" not in runtime
    assert "mouse_event" not in runtime

    for token in (
        "QueueHubOpenService(",
        "pending_hub_service_request",
        "Another hub service request is already pending.",
        "TryGetHubSurfaceState(",
    ):
        assert token in public_api, f"typed hub service API lacks: {token}"
    for token in (
        'RegisterFunction(state, &LuaHubOpenService, "open_service")',
        'RegisterFunction(state, &LuaHubGetSurfaceState, "get_surface_state")',
        'lua_setfield(state, -2, "inventory_screen_active")',
        'lua_setfield(state, -2, "inventory_shop_active")',
    ):
        assert token in lua, f"typed hub Lua API lacks: {token}"
    assert "TryDispatchPendingHubServiceOnGameThread();" in pump
    return "Lua opens named hub services through the verified stock Courtyard dispatcher"




def test_natural_offer_expectation_clamps_to_native_maximum() -> str:
    import verify_multiplayer_all_stat_sync as stats

    assert stats.expected_natural_offer_active(
        {"active": 1, "statbook_max_level": 1}, 1
    ) == 1
    assert stats.expected_natural_offer_active(
        {"active": 3, "statbook_max_level": 12}, 2
    ) == 5
    return "natural choices accept stock max-rank clamping without hiding rank growth"


def test_stat_matrix_waits_for_expected_derived_contract() -> str:
    stats = _read("tools/verify_multiplayer_all_stat_sync.py")
    assert "def wait_for_stat_contract(" in stats
    assert "contract_convergence = wait_for_stat_contract(" in stats
    assert '"contract_convergence": contract_convergence' in stats
    return "stat steps require expected owner/observer values, not stale matching views"


def test_mana_recovery_precondition_holds_zero_until_replication() -> str:
    stats = _read("tools/verify_multiplayer_all_stat_sync.py")
    loop = stats.split("while time.monotonic() < settle_deadline:", 1)[1].split(
        "else:", 1
    )[0]
    assert "settle_reset = set_local_mana(target_pipe, 0.0)" in loop
    assert '"owner_mp": owner["native"]' in loop
    assert 'float(settle_sample["owner_mp"]) < settle_ceiling' in loop
    return "high recovery cannot outrun the replicated zero-mana precondition"


def test_reconnect_verifier_has_a_dedicated_cold_launch_timeout() -> str:
    reconnect = _read("tools/verify_steam_friend_active_run_reconnect.py")
    assert '"--launch-timeout", type=float, default=180.0' in reconnect
    assert "wait_for_game(args.new_client_instance, args.launch_timeout)" in reconnect
    return "cold Proton staging is not bounded by the gameplay convergence timeout"


def test_loot_materialization_waits_for_native_field_convergence() -> str:
    loot = _read("tools/verify_multiplayer_loot_drop_materialization.py")
    assert "def wait_for_probe_field_convergence(" in loot
    assert "field_state = wait_for_probe_field_convergence(" in loot
    assert 'result["field_convergence"] = field_state["convergence"]' in loot
    assert 'result["final_host_capture"] = field_state["host_capture"]' in loot
    assert 'result["final_client_capture"] = field_state["client_capture"]' in loot
    return "loot evidence uses settled native actors rather than first materialization frames"


def test_primary_kill_stress_resumes_only_a_contiguous_passed_prefix() -> str:
    import verify_multiplayer_primary_kill_stress as primary

    prior = {
        "kills": [
            {"kill_index": 1, "direction": "host_to_client", "status": "passed"},
            {"kill_index": 2, "direction": "host_to_client", "status": "setup"},
        ]
    }
    resumed = primary.validated_resume_kills(
        prior,
        ("host_to_client", "client_to_host"),
        2,
    )
    assert len(resumed) == 1
    invalid = {
        "kills": prior["kills"]
        + [{"kill_index": 3, "direction": "client_to_host", "status": "passed"}]
    }
    try:
        primary.validated_resume_kills(
            invalid,
            ("host_to_client", "client_to_host"),
            2,
        )
    except primary.VerifyFailure:
        pass
    else:
        raise AssertionError("non-contiguous passed kills were accepted")
    source = _read("tools/verify_multiplayer_primary_kill_stress.py")
    assert "FAST_LUA_TIMEOUT_SECONDS = 8.0" in source
    assert "timeout=FAST_LUA_TIMEOUT_SECONDS" in source
    return "kill stress preserves proved prefixes and rejects gaps after automation faults"


def test_primary_kill_stress_accepts_a_late_death_from_the_prior_cast() -> str:
    import verify_multiplayer_primary_kill_stress as primary

    original = primary.require_death_logs
    calls = []
    try:
        primary.require_death_logs = lambda *args, **kwargs: calls.append(
            (args, kwargs)
        ) or {"source_ok": True, "receiver_ok": True}
        attempt = {
            "status": "native_primary_no_kill",
            "source_log_offset": 11,
            "receiver_log_offset": 22,
        }
        target = {
            "network_id": 33,
            "host_actor_address": 44,
            "x": 1.0,
            "y": 2.0,
        }
        observed = primary.finalize_late_primary_death(
            object(),
            target,
            attempt,
            {
                "host": {"found": "true", "snapshot.dead": "true"},
                "client": {"found": "true", "snapshot.dead": "false"},
            },
        )
        removed_attempt = {
            "status": "native_primary_no_kill",
            "source_log_offset": 33,
            "receiver_log_offset": 44,
        }
        removed = primary.finalize_late_primary_death(
            object(),
            target,
            removed_attempt,
            {
                "host": {"found": "false", "live_local_count": "0"},
                "client": {"found": "false", "live_local_count": "0"},
            },
        )
    finally:
        primary.require_death_logs = original
    assert observed
    assert attempt["status"] == "death_logs_observed"
    assert attempt["late_death_observed"] is True
    assert attempt["death_logs"] == {"source_ok": True, "receiver_ok": True}
    assert removed
    assert removed_attempt["target_removed_after_late_death"] is True
    assert removed_attempt["status"] == "death_logs_observed"
    assert len(calls) == 2
    assert calls[0][0][2:] == (11, 22)
    return "a delayed lethal effect is attributed to its real prior native cast"


def test_animated_loot_comparison_bounds_snapshot_phase_skew() -> str:
    import verify_multiplayer_primary_kill_stress as primary

    host = {
        "network_drop_id": 1,
        "type_id": primary.LOOT_ORB_TYPE_ID,
        "kind": "Orb",
        "active": True,
        "presentation_state": 0,
        "materialized": False,
        "local_actor_address": 0,
        "actor_type_id": 0,
        "x": 100.0,
        "y": 200.0,
        "actor_x": 100.0,
        "actor_y": 200.0,
        "radius": 15.0,
        "actor_radius": 15.0,
        "amount": 23,
        "amount_tier": 1,
        "value": 0.584,
        "actor_amount": 0,
        "actor_amount_tier": 0,
        "actor_value": 0.0,
        "item_type_id": 0,
        "item_slot": -1,
        "stack_count": 0,
        "actor_item_type_id": 0,
        "actor_item_slot": -1,
        "actor_stack_count": 0,
    }
    client = {
        **host,
        "materialized": True,
        "local_actor_address": 2,
        "actor_type_id": primary.LOOT_ORB_TYPE_ID,
        "x": 104.5,
        "actor_x": 104.5,
        "actor_amount_tier": 1,
        "actor_value": 0.584,
    }
    bounded = primary.compare_replicated_loot_drop(host, client)
    assert bounded["ok"], bounded
    assert bounded["actor_position_delta"] == 0.0
    assert primary.client_loot_presentation_converged(client)

    client["actor_x"] = 100.0
    assert not primary.client_loot_presentation_converged(client)

    client["x"] = 109.0
    client["actor_x"] = 109.0
    excessive = primary.compare_replicated_loot_drop(host, client)
    assert not excessive["ok"]
    assert "client snapshot drop position differs from host" in excessive["failures"]
    return "animated loot allows one transport phase of skew while bounding real drift"
