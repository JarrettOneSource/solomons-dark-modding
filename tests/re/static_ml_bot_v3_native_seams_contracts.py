"""Static contracts for the frozen ML Bot Policy v3 native seams."""

from __future__ import annotations

import re

from static_multiplayer_contract_support import _read, _require_in_order


def test_ml_bot_v3_collision_geometry_is_exact_semantic_and_address_free() -> str:
    layout = _read("config/binary-layout.ini")
    state = _read(
        "SolomonDarkModLoader/include/mod_loader_collision_geometry_state.inl"
    )
    capture = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_pathfinding_grid_setup.inl"
    )
    public_api = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_collision_geometry.inl"
    )
    binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_foundations.cpp"
    )

    for token in (
        "movement_controller_shape_count=0x28",
        "movement_controller_shape_list=0x34",
        "movement_shape_points=0x00",
        "movement_shape_cached_points=0x04",
        "movement_shape_bounds_x=0x08",
        "movement_shape_bounds_y=0x0C",
        "movement_shape_bounds_w=0x10",
        "movement_shape_bounds_h=0x14",
        "movement_shape_point_count=0x38",
        "fence_grate_segment_start_x=0x140",
        "fence_grate_segment_start_y=0x144",
        "fence_grate_segment_end_x=0x148",
        "fence_grate_segment_end_y=0x14C",
        "broken_fence_segment_start_x=0x150",
        "broken_fence_segment_start_y=0x154",
        "broken_fence_segment_end_x=0x158",
        "broken_fence_segment_end_y=0x15C",
    ):
        assert token in layout, f"exact geometry layout lacks {token}"
    for token in (
        "struct SDModCollisionCircle",
        "struct SDModCollisionSegment",
        "struct SDModCollisionPolygon",
        "struct SDModCollisionParticipantRadius",
        "geometry_id",
        "native_type_id",
        "path_blocks",
        "destructible_resolved",
        "observer_radius",
        "participant_collision_padding",
        "static_revision",
        "dynamic_revision",
    ):
        assert token in state, f"collision geometry state lacks {token}"
    for token in (
        "CaptureGameplayPathShapePolicy(",
        "snapshot->circle_obstacles.push_back",
        "snapshot->segment_obstacles.push_back",
        "snapshot->polygon_obstacles.push_back",
        "TryReadGameplayPathDirectSegmentObstacle(",
        "kMovementShapePointsOffset",
        "kMovementShapeCachedPointsOffset",
    ):
        assert token in capture, f"geometry capture lacks {token}"
    for token in (
        "TryBuildGameplayPathGridSnapshot(",
        "AllocateCollisionGeometryId(",
        "source.native_type_id == 1",
        "built.participant_radii",
        "circle.destructible_resolved",
        "segment.destructible_resolved",
        "segment.path_blocks = !segment.openable",
        "built.static_revision",
        "built.dynamic_revision",
    ):
        assert token in public_api, f"geometry publication lacks {token}"

    push = binding.split("void PushCollisionGeometry(", 1)[1].split(
        "int LuaNavGetCollisionGeometry(", 1
    )[0]
    for field in (
        "scene_epoch",
        "run_nonce",
        "static_revision",
        "dynamic_revision",
        "refresh_pending",
        "observer_radius",
        "observer_radius_resolved",
        "participant_collision_padding",
        "circles",
        "segments",
        "polygons",
        "participant_radii",
    ):
        assert f'"{field}"' in push, f"geometry Lua row omits {field}"
    for forbidden in ('"address"', '"pointer"', '"exception"', '"seh"'):
        assert forbidden not in push
    assert (
        'RegisterFunction(\n'
        "        state,\n"
        "        &LuaNavGetCollisionGeometry,\n"
        '        "get_collision_geometry")'
    ) in binding
    return (
        "Collision geometry enumerates exact circles, segments, polygons, "
        "and participant radii behind stable semantic IDs"
    )


def test_ml_bot_v3_enemy_statuses_are_semantic_bounded_and_replicated() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    capture = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "world_snapshot_capture.inl"
    )
    binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )

    for token in (
        "WorldActorStatusFlagCombatModifiersResolved",
        "WorldActorStatusFlagSlowed",
        "WorldActorStatusFlagFrozen",
        "WorldActorStatusFlagPoisoned",
        "WorldActorStatusFlagWebbed",
        "constexpr float kWorldActorStatusTicksPerSecond = 100.0f",
        "slow_remaining_ticks",
        "frozen_remaining_ticks",
        "poison_remaining_ticks",
        "webbed_remaining_ticks",
        "static_assert(sizeof(WorldActorSnapshotPacketState) == 400",
        "static_assert(sizeof(WorldSnapshotPacket) == 1248",
    ):
        assert token in protocol, f"enemy status protocol lacks {token}"
    for token in (
        "TryListNativeActorModifiers(",
        "case 0x1B69",
        "case 0x1B70",
        "case 0x1B6F",
        "case 0x1B72",
        "case 0x1B79",
        "PopulateRunEnemyCombatModifierSnapshot(",
    ):
        assert token in capture, f"enemy status capture lacks {token}"
    actor_push = binding.split(
        "void PushReplicatedWorldActor(", 1
    )[1].split("void PushReplicatedLootDrop(", 1)[0]
    for field in (
        "combat_status_resolved",
        "slowed",
        "slow_remaining_ticks",
        "slow_remaining_seconds",
        "frozen",
        "frozen_remaining_ticks",
        "frozen_remaining_seconds",
        "poisoned",
        "poison_remaining_ticks",
        "poison_remaining_seconds",
        "webbed",
        "webbed_remaining_ticks",
        "webbed_remaining_seconds",
        "turn_undead_resolved",
    ):
        assert f'"{field}"' in actor_push, f"enemy Lua row omits {field}"
    return (
        "Enemy snapshots carry resolved slow, freeze, poison, web, and "
        "Turn-Undead state with 100-Hz tick and seconds forms"
    )


def test_ml_bot_v3_hazards_include_unknown_hostile_classes_without_addresses() -> str:
    protocol = _read(
        "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    registry = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "hazard_snapshot_registry.inl"
    )
    sync = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "hazard_snapshot_sync.inl"
    )
    transient_api = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_transient_actors.inl"
    )
    binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )

    for token in (
        "constexpr std::uint16_t kProtocolVersion = 90;",
        "constexpr std::uint32_t kHazardSnapshotMaxHazards = 32;",
        "HazardStateFlagHostile",
        "HazardStateFlagTypeKnown",
        "struct HazardPacketState",
        "struct HazardSnapshotPacket",
        "static_assert(sizeof(HazardPacketState) == 76",
        "static_assert(sizeof(HazardSnapshotPacket) == 2464",
    ):
        assert token in protocol, f"hazard protocol lacks {token}"

    known_block = registry.split(
        "bool TryResolveKnownHazardKind", 1
    )[1].split("bool IsPinnedNonHazardEffectBandType", 1)[0]
    known_types = re.findall(r"case (0x[0-9A-F]+)", known_block)
    assert len(known_types) == 38
    for non_hazard in (
        "0x07EA",
        "0x07ED",
        "0x07EE",
        "0x07EF",
        "0x07F2",
        "0x07F4",
        "0x07F6",
        "0x080F",
    ):
        assert non_hazard in registry
    for token in (
        "IsUnknownEffectBandCandidate(",
        "SDMOD_TEST_UNKNOWN_HOSTILE_HAZARD",
        "probe.native_type_id =\n        0x0803",
        "HazardStateFlagActive |\n        HazardStateFlagHostile",
    ):
        assert token in registry + sync, f"unknown hazard rule lacks {token}"
    for token in (
        "ResolveSemanticDamageSourceParticipantId(",
        "BuildLocalHazardSnapshotPacket(",
        "PublishLocalHazardSnapshot(",
        "ApplyHazardSnapshotPacket(",
        "HazardSnapshotFlagTruncated",
        "TryListTransientSceneActors(",
        "candidate_addresses",
    ):
        assert token in sync, f"hazard replication lacks {token}"
    assert "AppendTransientSceneActors(" in transient_api
    assert "actor.actor_slot == 0" not in sync

    lua_api = binding.split(
        "int LuaWorldGetReplicatedHazards(", 1
    )[1].split("int LuaWorldGetReplicatedSpellEffects(", 1)[0]
    for field in (
        "hazard_id",
        "native_type_id",
        "hostile",
        "type_known",
        "kind",
        "source_participant_id",
        "source_network_actor_id",
        "target_participant_id",
        "target_network_actor_id",
        "motion_resolved",
        "lifetime_resolved",
        "remaining_ticks",
        "homing",
    ):
        assert f'"{field}"' in lua_api, f"hazard Lua row omits {field}"
    for forbidden in ('"address"', '"pointer"', '"exception"', '"seh"'):
        assert forbidden not in lua_api
    return (
        "Protocol 90 carries 38 classified hostile hazard families and "
        "surfaces unclassified hostile effect-band actors with type_known=false"
    )


def test_ml_bot_v3_inventory_details_are_revision_cached_and_content_identified() -> str:
    runtime = _read("SolomonDarkModLoader/src/bot_runtime.cpp")
    helpers = _read(
        "SolomonDarkModLoader/src/bot_runtime/helpers/inventory_details.inl"
    )
    api = _read(
        "SolomonDarkModLoader/src/bot_runtime/public_api/"
        "inventory_details_api.inl"
    )
    binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_bots/"
        "inventory_bindings.inl"
    )
    multiplayer_binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    items = _read("SolomonDarkModLoader/src/lua_engine_bindings_consumables.cpp")
    policy = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_consumables/"
        "policy_effects.inl"
    )

    for token in (
        "struct BotInventoryRevisionTuple",
        "g_inventory_details_cache",
    ):
        assert token in runtime, f"inventory cache lacks {token}"
    for token in (
        "participant.runtime.run_nonce",
        "participant.owned_progression.inventory_revision",
        "participant.owned_progression.equipment_revision",
        "participant.owned_progression.derived_stat_revision",
        "participant.owned_progression.statbook_revision",
        "BuildStockPotionDetails(",
        "BuildCustomPotionDetails(",
        "kNativeItemPolicyCatalog",
        "TryResolveNativeItemRecipeIdentityByUid(",
        "OverlayLiveParticipantConsumableState(",
    ):
        assert token in helpers, f"inventory descriptor producer lacks {token}"
    _require_in_order(
        api,
        "BotInventoryRevisionTuplesEqual(",
        "*details = cached->details",
        "OverlayLiveParticipantConsumableState(details)",
    )
    for field in (
        "participant_id",
        "run_nonce",
        "inventory_revision",
        "equipment_revision",
        "descriptors_resolved",
        "damage_x4_remaining_seconds",
        "poison_immunity_remaining_seconds",
        "all_concentration_remaining_seconds",
        "timers_resolved",
        "potions",
        "equipped",
        "summary",
        "synthetic_use_supported",
        "identity_key",
    ):
        assert f'"{field}"' in binding, f"inventory Lua shape omits {field}"
    inventory_push = multiplayer_binding.split(
        "void PushOwnedProgressionState", 1
    )[1].split("void PushLevelUpOptionState", 1)[0]
    assert '"content_id"' in inventory_push
    assert '#include "lua_engine_bindings_consumables/policy_effects.inl"' in items
    assert "ReadConsumablePolicyEffects(" in policy
    for field in (
        "synthetic_safe",
        "restores_hp_fraction",
        "restores_mana_fraction",
        "damage_multiplier",
        "cures_poison",
        "poison_immunity_duration_seconds",
        "concentrates_all",
        "effect_duration_seconds",
    ):
        assert f'"{field}"' in policy, f"custom policy metadata omits {field}"
    return (
        "Inventory descriptors join stable content identities, stock catalog "
        "semantics, equipment, and live timers behind a five-revision cache"
    )


def test_ml_bot_v3_consumable_use_is_reserved_exactly_once_and_native_routed() -> str:
    layout = _read("config/binary-layout.ini")
    native = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_participant_consumables.inl"
    )
    use = _read(
        "SolomonDarkModLoader/src/bot_runtime/public_api/"
        "consumable_use_api.inl"
    )
    binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_bots/"
        "inventory_bindings.inl"
    )
    transport = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "lua_consumable_use_sync.inl"
    )
    pickup = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "loot_pickup_authority.inl"
    )

    for token in (
        "player_actor_apply_health_delta=0x0052AC80",
        "progression_damage_x4_remaining_ticks=0x824",
        "progression_all_concentration_remaining_ticks=0x828",
        "progression_poison_immunity_remaining_ticks=0x74C",
    ):
        assert token in layout, f"consumable native layout lacks {token}"
    for token in (
        "stock_subtype != 0",
        "stock_subtype != 1",
        "stock_subtype != 5",
        "CallParticipantHealthDeltaSafe(",
        "TryApplyLocalRegisteredSpellManaDelta(",
        "kNativeTimerTicksPerSecond = 100.0f",
        "observation-only because no participant-scoped native use path",
    ):
        assert token in native, f"native consumable routing lacks {token}"

    transaction = use.split("bool UseParticipantConsumable(", 1)[1]
    _require_in_order(
        transaction,
        "ReserveParticipantPotionStack(",
        "TryApplyParticipantStockConsumable(",
        "PublishParticipantConsumableVitals(",
    )
    for token in (
        "RollBackParticipantPotionReservation(",
        "The consumable selector has a stale inventory_revision.",
        "The selected potion has no proven synthetic-safe effect path.",
        "InvalidateParticipantInventoryDetailsLocked(",
        "consumable applied exactly once",
    ):
        assert token in use, f"exactly-once consumable transaction lacks {token}"
    for token in (
        "RememberLuaConsumableUse(",
        "participant_session_nonce",
        "SteamNetworkSendMode::ReliableNoNagle",
        "DispatchLuaConsumableUse(",
    ):
        assert token in transport, f"custom consumable replication lacks {token}"
    _require_in_order(
        pickup,
        "host_synthetic_ingress",
        "sdmod::TryGetParticipantPickupRange(",
        '"participant_pickup_range_unavailable"',
    )
    assert (
        'RegisterFunction(state, &LuaBotsUseConsumable, "use_consumable")'
        in _read("SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp")
    )
    for forbidden in ('"address"', '"pointer"', '"exception"', '"seh"'):
        assert forbidden not in binding
    return (
        "Ranked consumable use reserves one authoritative stack revision "
        "before native routing; only Health, Mana, and Rejuvenation are actionable"
    )
