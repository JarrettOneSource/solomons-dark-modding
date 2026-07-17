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


def test_lobby_directory_privacy_contract_is_end_to_end() -> str:
    privacy = _read(
        "SolomonDarkModLauncher/src/Launch/MultiplayerLobbyPrivacy.cs"
    )
    parser = _read("SolomonDarkModLauncher/src/Commands/LauncherCommandParser.cs")
    environment = _read(
        "SolomonDarkModLauncher/src/Launch/MultiplayerLaunchEnvironment.cs"
    )
    staged_launcher = _read(
        "SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs"
    )
    publisher = _read(
        "SolomonDarkModLauncher/src/Launch/LobbyDirectoryPublisher.cs"
    )
    protocol_handler = _read(
        "SolomonDarkModLauncher/src/Launch/SdrProtocolHandler.cs"
    )
    steam_bridge = _read("SolomonDarkModLoader/src/steam_api_bridge.cpp")
    steam_session = _read_many(
        "SolomonDarkModLoader/src/multiplayer_steam_session/state_and_helpers.inl",
        "SolomonDarkModLoader/src/multiplayer_steam_session/public_lifecycle.inl",
        "SolomonDarkModLoader/src/multiplayer_steam_session/lobby_and_events.inl",
        "SolomonDarkModLoader/src/multiplayer_steam_session/network_messages.inl",
    )
    access = _read("SolomonDarkModLoader/src/lobby_access.cpp")
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    status = _read("SolomonDarkModLoader/src/startup_status.cpp")

    for token in (
        '"public"',
        '"passwordProtected"',
        '"friendsOnly"',
        'arg == "--lobby-privacy"',
        'arg == "--lobby-password-hash"',
        'arg == "--join-ticket"',
    ):
        assert token in privacy + parser, f"launcher privacy contract lacks: {token}"

    for token in (
        'LobbyPrivacyVariable = "SDMOD_LOBBY_PRIVACY"',
        'DirectorySecretVariable = "SDMOD_LOBBY_DIRECTORY_SECRET"',
        'JoinTicketVariable = "SDMOD_LOBBY_JOIN_TICKET"',
        "LobbyDirectoryPublisher.Start(",
        'new HttpRequestMessage(HttpMethod.Post, "api/lobbies/announce")',
        "while (!gameProcess.HasExited)",
    ):
        assert token in environment + staged_launcher + publisher, (
            f"directory publisher lacks: {token}"
        )

    for token in (
        "SteamLobbyVisibility::Public",
        "SteamLobbyVisibility::Invisible",
        "SteamLobbyVisibility::FriendsOnly",
        "SteamGetImmediateFriends()",
        "SteamHasImmediateFriend(message.sender_steam_id)",
        "ValidatePasswordLobbyJoinTicket(",
        "SessionHelloResultCode::AccessDenied",
        "packet.join_ticket",
    ):
        assert token in steam_bridge + steam_session, f"native lobby access lacks: {token}"

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 60;",
        "char join_ticket[kLobbyJoinTicketBytes];",
        "AccessDenied = 9",
        '"  \\"localSteamId\\": "',
        '"  \\"friendSteamIds\\": ["',
    ):
        assert token in protocol + status, f"session/status contract lacks: {token}"

    for token in (
        'const std::string& secret_hex',
        "BCRYPT_SHA256_ALGORITHM",
        "ticket_steam_id != steam_id",
        "expires_at + kClockSkewSeconds < now_unix_seconds",
        "FixedTimeEquals(expected_digest, provided_digest)",
    ):
        assert token in access, f"password ticket validation lacks: {token}"

    for token in (
        'string.Equals(args[0], "protocol"',
        "Registry.CurrentUser.CreateSubKey(RegistryPath",
        "commandKey?.SetValue(null",
        'string.Equals(args[0], "open-uri"',
        '"--join-ticket"',
    ):
        assert token in protocol_handler, f"sdr protocol backend lacks: {token}"

    return (
        "all lobby privacy modes publish through a detached best-effort directory worker; "
        "Steam transport and invites remain native, and protected joins are SteamID-bound"
    )


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
        "accept uint32 wraparound, and reset every stream on a new gameplay-session nonce"
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


def test_native_item_pickup_converges_into_stock_inventory() -> str:
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
    authority = _read(
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
    assert "CallActorWorldUnregisterSafe(" in host_deactivation
    assert "CallActorWorldUnregisterSafe(" not in transport
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
    pickup_authority = _read(
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
    incoming_state = _read(
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

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 60;",
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
        "static_assert(sizeof(StatePacket) == 4196",
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
        "entry.active == 0",
        "TryResolveDamageX4DurationTicks",
        "RollParticipantSkillChoiceOptions",
        "IssueHostLevelUpOfferForParticipant",
        "IssueLocalHostSelfLevelUpOffer",
        "ApplyParticipantSkillChoiceOption",
        "ApplyLocalPlayerSkillChoiceOption",
        "TryWriteParticipantDamageX4Ticks",
        "ProcessQueuedLocalHostPowerupPickups",
        "queued.capture.requester_position_x",
        "captured_positions",
    ):
        assert token in authority, f"powerup authority lacks: {token}"

    for token in (
        "TryPreparePowerupReward",
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
    assert "binding.drop_kind == multiplayer::LootDropKind::Powerup" in reconciliation
    assert "return ParkReplicatedLootPresentationActor(binding);" in reconciliation
    assert "ParkReplicatedLootPresentationActor(binding)" in deactivation
    assert "kReplicatedLootPowerupNativeTypeId = 0x07F6" in reconciliation
    assert 'spawn_kind = "bonus_skill"' in reconciliation
    assert 'spawn_kind = "random_skill"' in reconciliation
    assert 'spawn_kind = "damage_x4"' in reconciliation
    assert "ReconcileRemoteParticipantDamageX4State" in native_progression
    assert "packet.damage_x4_remaining_ticks" in local_state
    assert "effective_damage_x4_remaining_ticks" in incoming_state
    assert '"damage_x4_remaining_ticks"' in lua_gameplay
    assert '"damage_x4_remaining_ticks"' in lua_runtime
    assert "powerup_pickup=0x006039C0" in layout
    assert "game_timing_scale=0x00820230" in layout
    assert "progression_damage_x4_remaining_ticks=0x824" in layout

    for token in (
        "verify_random_skill",
        "verify_damage_x4",
        "verify_bonus_skill",
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

    return (
        "stock bonus-skill, learned-skill-rank, and DamageX4 rewards use host "
        "pickup authority, exact native owner/observer application, and a two-owner live matrix"
    )


def test_exact_native_equipment_identity_and_color_replicate() -> str:
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl"
    )
    incoming_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_packet_sync.inl"
    )
    remote_playback = _read(
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
        "constexpr std::uint16_t kProtocolVersion = 60;",
        "ParticipantPresentationFlagEquipmentState = 1 << 5",
        "std::uint32_t primary_visual_link_recipe_uid;",
        "std::uint32_t secondary_visual_link_recipe_uid;",
        "std::uint32_t attachment_visual_link_recipe_uid;",
        "constexpr std::uint32_t kParticipantRingSlotCount = 3;",
        "struct ParticipantEquippedItemPacketState",
        "std::uint32_t equipment_revision;",
        "ParticipantEquippedItemPacketState equipped_rings[kParticipantRingSlotCount];",
        "ParticipantEquippedItemPacketState equipped_amulet;",
        "static_assert(sizeof(StatePacket) == 4196",
    ):
        assert token in protocol, f"exact equipment packet contract lacks: {token}"

    _require_in_order(
        local_state,
        "TryReadVisualLinkColorBlock(",
        "ParticipantPresentationFlagEquipmentState",
        "local->runtime.primary_visual_link_recipe_uid = primary_visual_recipe_uid;",
        "local->runtime.attachment_visual_link_recipe_uid =",
        "packet.primary_visual_link_recipe_uid = local->runtime.primary_visual_link_recipe_uid;",
        "packet.attachment_visual_link_recipe_uid = local->runtime.attachment_visual_link_recipe_uid;",
    )
    _require_in_order(
        incoming_state,
        "equipment_packet_is_sane",
        "packet.equipped_rings",
        "participant->owned_progression.equipment_revision =",
        "participant->runtime.primary_visual_link_recipe_uid =",
        "participant->runtime.attachment_visual_link_recipe_uid =",
        "sample.primary_visual_link_recipe_uid =",
        "sample.attachment_visual_link_recipe_uid =",
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
        "flow from stock local ownership through protocol v60; visible lanes self-correct natively"
    )


def test_hub_shops_preserve_participant_ownership() -> str:
    inventory_shop_verifier = _read(
        "tools/verify_multiplayer_hub_inventory_shop_sync.py"
    )
    merchant_verifier = _read("tools/verify_multiplayer_hub_shop_ownership.py")
    click_helper = _read("scripts/click_window.py")
    inventory_audit = _read("tools/verify_multiplayer_inventory_audit.py")
    inventory_doc = _read("docs/inventory-item-investigation.md")

    for token in (
        '"--drag-x"',
        '"--drag-y"',
        "drag_client_point",
        "drag_screen_point",
        "release_client_lparam = drag_lparam",
        "step_count = max(6, min(24, drag_hold_ms // 40))",
        "fraction = step / step_count",
    ):
        assert token in click_helper, f"stock inventory drag helper lacks: {token}"
    for token in (
        'emit("inventory.raw_item_count"',
        '"raw_item_count": parse_int_text(',
    ):
        assert token in inventory_audit, f"inventory audit raw-count surface lacks: {token}"
    for token in (
        "open_luthacus_inventory(host_pid)",
        "drag_to_private_storage",
        "drag_back_to_backpack",
        "client private inventory changed with host storage",
        'host["raw_item_count"] <= 64',
        'current["client_view_host"]["revision"] <= baseline_revision',
        'current["client_view_host"]["revision"] <= stored_revision',
        "assert_ledger_matches_local(",
    ):
        assert token in inventory_shop_verifier, (
            f"hub inventory-shop live verifier lacks: {token}"
        )
    for token in (
        "open_fomentius(pid)",
        "open_hagatha(pid)",
        "host purchase changed the client's native gold",
        "host purchase changed the client's native backpack",
        "client did not observe exact purchased host backpack",
        'baseline_host["gold"] - host["gold"] != 600',
        'expected_max_hp = baseline_host["max_hp"] * 1.25',
        "client did not observe exact Life Charm max HP",
        "Life Charm changed the client backpack",
        "dismiss_intro",
        "menu_movement",
    ):
        assert token in merchant_verifier, f"hub merchant live verifier lacks: {token}"
    assert "participant-private" in inventory_doc
    assert "Luthacus" in inventory_doc

    return (
        "real Luthacus, Fomentius, and Hagatha UI actions keep storage, gold, "
        "inventory, and perk-derived stats participant-owned while peers observe exact results"
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
    real_cast_verifier = _read("tools/verify_real_input_spell_cast_sync.py")
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
        "def log_position(path: Path) -> int:",
        'with path.open("rb") as stream:',
        "stream.seek(offset)",
    ):
        assert token in real_cast_verifier, (
            f"spell verifier incremental log reader lacks: {token}"
        )
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
        '$_ -like "Could not locate SolomonDarkModLauncher.exe*"',
        '$result.uiCatalogStatus = "Ready"',
    ):
        assert token in smoke, f"beta package smoke test lacks: {token}"

    return (
        "the packaged desktop UI accepts its single-file CLI and proves a "
        "catalog command crosses the real UI-to-CLI boundary"
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
    choices = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "level_up_packet_sync.inl"
    )
    picker = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "level_up_choice_and_picker.inl"
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

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 60;",
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
        "ApplyParticipantSkillChoiceOption(",
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
        "} else if (!ApplyParticipantSkillChoiceOption(",
        "result_code = LevelUpChoiceResultCode::Accepted;",
        "offer.resolved = true;",
    )

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
    ):
        assert token in verifier, f"live exact-rank regression lacks: {token}"

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
