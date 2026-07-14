// World and loot snapshot runtime publication and inbound application.

WorldSnapshotRuntimeInfo BuildWorldSnapshotRuntimeInfo(
    const WorldSnapshotPacket& packet,
    std::uint64_t now_ms) {
    const auto actor_count = static_cast<std::uint8_t>(
        (std::min<std::uint32_t>)(packet.actor_count, kWorldSnapshotMaxActors));
    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);
    WorldSnapshotRuntimeInfo snapshot;
    snapshot.valid = true;
    snapshot.authority_participant_id = packet.authority_participant_id;
    snapshot.received_ms = now_ms;
    snapshot.sequence = packet.header.sequence;
    snapshot.scene_epoch = packet.scene_epoch;
    snapshot.run_nonce = packet.run_nonce;
    snapshot.actor_total_count = packet.actor_total_count;
    snapshot.truncated = (packet.snapshot_flags & WorldSnapshotFlagTruncated) != 0;
    snapshot.scene_intent = SceneIntentFromWorldSceneKind(scene_kind);
    snapshot.actors.reserve(actor_count);

    for (std::uint8_t index = 0; index < actor_count; ++index) {
        const auto& packet_actor = packet.actors[index];
        if (packet_actor.network_actor_id == 0 ||
            packet_actor.native_type_id == 0 ||
            !std::isfinite(packet_actor.position_x) ||
            !std::isfinite(packet_actor.position_y) ||
            !std::isfinite(packet_actor.radius) ||
            packet_actor.radius < 0.0f) {
            continue;
        }

        WorldActorSnapshot actor;
        actor.network_actor_id = packet_actor.network_actor_id;
        actor.native_type_id = packet_actor.native_type_id;
        actor.enemy_type = packet_actor.enemy_type;
        actor.actor_slot = packet_actor.actor_slot;
        actor.world_slot = packet_actor.world_slot;
        actor.target_participant_id = packet_actor.target_participant_id;
        actor.target_native_type_id = packet_actor.target_native_type_id;
        actor.target_actor_slot = packet_actor.target_actor_slot;
        actor.target_world_slot = packet_actor.target_world_slot;
        actor.target_bucket_delta = packet_actor.target_bucket_delta;
        actor.dead = (packet_actor.flags & WorldActorSnapshotFlagDead) != 0;
        actor.tracked_enemy = (packet_actor.flags & WorldActorSnapshotFlagTrackedEnemy) != 0;
        actor.lifecycle_owned = (packet_actor.flags & WorldActorSnapshotFlagLifecycleOwned) != 0;
        actor.run_static = (packet_actor.flags & WorldActorSnapshotFlagRunStatic) != 0;
        actor.player_created =
            (packet_actor.flags & WorldActorSnapshotFlagPlayerCreated) != 0;
        actor.target_authoritative =
            (packet_actor.flags & WorldActorSnapshotFlagTargetAuthoritative) != 0;
        actor.anim_drive_state = packet_actor.anim_drive_state;
        actor.presentation_flags = packet_actor.presentation_flags;
        actor.position_x = packet_actor.position_x;
        actor.position_y = packet_actor.position_y;
        actor.radius = packet_actor.radius;
        actor.heading = std::isfinite(packet_actor.heading) ? packet_actor.heading : 0.0f;
        actor.hp = std::isfinite(packet_actor.hp) ? packet_actor.hp : 0.0f;
        actor.max_hp = std::isfinite(packet_actor.max_hp) ? packet_actor.max_hp : 0.0f;
        actor.anim_drive_state_word = packet_actor.anim_drive_state_word;
        actor.walk_cycle_primary =
            std::isfinite(packet_actor.walk_cycle_primary) ? packet_actor.walk_cycle_primary : 0.0f;
        actor.walk_cycle_secondary =
            std::isfinite(packet_actor.walk_cycle_secondary) ? packet_actor.walk_cycle_secondary : 0.0f;
        actor.render_variant_primary = packet_actor.render_variant_primary;
        actor.render_variant_secondary = packet_actor.render_variant_secondary;
        actor.render_weapon_type = packet_actor.render_weapon_type;
        actor.render_selection_byte = packet_actor.render_selection_byte;
        actor.render_variant_tertiary = packet_actor.render_variant_tertiary;
        std::memcpy(
            actor.student_visual_state.data(),
            packet_actor.student_visual_state,
            actor.student_visual_state.size());
        snapshot.actors.push_back(actor);
    }

    return snapshot;
}

void PublishWorldSnapshotRuntimeInfo(const WorldSnapshotPacket& packet, std::uint64_t now_ms) {
    UpdateRuntimeState([&](RuntimeState& state) {
        AppendWorldSnapshot(&state, BuildWorldSnapshotRuntimeInfo(packet, now_ms));
    });
}

void ApplyWorldSnapshotPacket(
    const WorldSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    PublishWorldSnapshotRuntimeInfo(packet, now_ms);
}

LootSnapshotRuntimeInfo BuildLootSnapshotRuntimeInfo(
    const LootSnapshotPacket& packet,
    std::uint64_t now_ms) {
    const auto drop_count = static_cast<std::uint8_t>(
        (std::min<std::uint32_t>)(packet.drop_count, kLootSnapshotMaxDrops));
    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);

    LootSnapshotRuntimeInfo snapshot;
    snapshot.valid = true;
    snapshot.authority_participant_id = packet.authority_participant_id;
    snapshot.received_ms = now_ms;
    snapshot.sequence = packet.header.sequence;
    snapshot.scene_epoch = packet.scene_epoch;
    snapshot.run_nonce = packet.run_nonce;
    snapshot.drop_total_count = packet.drop_total_count;
    snapshot.truncated = (packet.snapshot_flags & LootSnapshotFlagTruncated) != 0;
    snapshot.scene_intent = SceneIntentFromWorldSceneKind(scene_kind);
    snapshot.drops.reserve(drop_count);

    for (std::uint8_t index = 0; index < drop_count; ++index) {
        const auto& packet_drop = packet.drops[index];
        const auto drop_kind = LootDropKindFromPacketValue(packet_drop.drop_kind);
        if (packet_drop.network_drop_id == 0 ||
            packet_drop.native_type_id == 0 ||
            !std::isfinite(packet_drop.position_x) ||
            !std::isfinite(packet_drop.position_y) ||
            !std::isfinite(packet_drop.radius) ||
            packet_drop.radius < 0.0f ||
            (drop_kind == LootDropKind::Orb && !std::isfinite(packet_drop.value)) ||
            ((drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion) &&
                packet_drop.item_type_id == 0)) {
            continue;
        }

        LootDropSnapshot drop;
        drop.network_drop_id = packet_drop.network_drop_id;
        drop.native_type_id = packet_drop.native_type_id;
        drop.drop_kind = drop_kind;
        drop.active = (packet_drop.flags & LootDropSnapshotFlagActive) != 0;
        drop.presentation_state = packet_drop.presentation_state;
        drop.amount = packet_drop.amount;
        drop.amount_tier = packet_drop.amount_tier;
        drop.value = packet_drop.value;
        drop.motion = packet_drop.motion;
        drop.progress = packet_drop.progress;
        drop.item_type_id = packet_drop.item_type_id;
        drop.item_slot = packet_drop.item_slot;
        drop.stack_count = packet_drop.stack_count;
        drop.actor_slot = packet_drop.actor_slot;
        drop.world_slot = packet_drop.world_slot;
        drop.lifetime = packet_drop.lifetime;
        drop.position_x = packet_drop.position_x;
        drop.position_y = packet_drop.position_y;
        drop.radius = packet_drop.radius;
        snapshot.drops.push_back(drop);
    }

    return snapshot;
}

bool PublishLootSnapshotRuntimeInfo(const LootSnapshotPacket& packet, std::uint64_t now_ms) {
    bool accepted = false;
    UpdateRuntimeState([&](RuntimeState& state) {
        accepted = AppendLootSnapshot(
            &state,
            BuildLootSnapshotRuntimeInfo(packet, now_ms));
    });
    return accepted;
}

void ApplyLootSnapshotPacket(
    const LootSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    if (!PublishLootSnapshotRuntimeInfo(packet, now_ms)) {
        return;
    }

    std::string queue_error;
    (void)sdmod::QueueReplicatedLootSnapshot(SnapshotRuntimeState().loot_snapshot, &queue_error);
}

#include "multiplayer_local_transport/enemy_damage_authority.inl"

#include "multiplayer_local_transport/loot_pickup_authority.inl"

#include "multiplayer_local_transport/level_up_packet_sync.inl"
#include "multiplayer_local_transport/level_up_barrier_sync.inl"

#include "multiplayer_local_transport/spell_effect_sync.inl"
#include "multiplayer_local_transport/air_chain_sync.inl"
#include "multiplayer_local_transport/participant_vitals_authority.inl"

using TransportPacketBuffer = std::array<char, sizeof(WorldSnapshotPacket)>;
