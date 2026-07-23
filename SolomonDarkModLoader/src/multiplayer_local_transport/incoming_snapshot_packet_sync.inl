// World and loot snapshot runtime publication and inbound application.

WorldSnapshotRuntimeInfo BuildWorldSnapshotRuntimeInfo(
    const CompleteWorldSnapshotPacketState& complete_snapshot,
    std::uint64_t now_ms) {
    WorldSnapshotRuntimeInfo snapshot;
    snapshot.valid = true;
    snapshot.authority_participant_id =
        complete_snapshot.authority_participant_id;
    snapshot.received_ms = now_ms;
    snapshot.sequence = complete_snapshot.snapshot_id;
    snapshot.scene_epoch = complete_snapshot.scene_epoch;
    snapshot.run_nonce = complete_snapshot.run_nonce;
    snapshot.actor_total_count = static_cast<std::uint32_t>(
        complete_snapshot.actors.size());
    snapshot.scene_intent =
        SceneIntentFromWorldSceneKind(complete_snapshot.scene_kind);
    snapshot.actors.reserve(complete_snapshot.actors.size());

    for (const auto& packet_actor : complete_snapshot.actors) {

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
        actor.status_flags = packet_actor.status_flags;
        actor.turn_undead_duration_ticks =
            packet_actor.turn_undead_duration_ticks;
        actor.turn_undead_flee_heading =
            packet_actor.turn_undead_flee_heading;
        actor.turn_undead_activation_scalar =
            packet_actor.turn_undead_activation_scalar;
        std::memcpy(
            actor.student_visual_state.data(),
            packet_actor.student_visual_state,
            actor.student_visual_state.size());
        actor.student_book_palette_count =
            packet_actor.student_book_palette_count <= kWorldActorStudentBookPaletteMaxEntries
            ? packet_actor.student_book_palette_count
            : 0;
        for (std::size_t palette_index = 0;
             palette_index < actor.student_book_palette_count;
             ++palette_index) {
            const auto& packet_entry = packet_actor.student_book_palette[palette_index];
            auto& entry = actor.student_book_palette[palette_index];
            const float values[] = {
                packet_entry.red,
                packet_entry.green,
                packet_entry.blue,
                packet_entry.alpha,
                packet_entry.radial_offset,
                packet_entry.angular_offset,
            };
            bool entry_valid = true;
            for (const float value : values) {
                entry_valid = entry_valid && std::isfinite(value) && value >= -4096.0f && value <= 4096.0f;
            }
            if (!entry_valid) {
                actor.presentation_flags &= ~WorldActorPresentationFlagStudentBookPalette;
                actor.student_book_palette_count = 0;
                break;
            }
            entry.red = packet_entry.red;
            entry.green = packet_entry.green;
            entry.blue = packet_entry.blue;
            entry.alpha = packet_entry.alpha;
            entry.radial_offset = packet_entry.radial_offset;
            entry.angular_offset = packet_entry.angular_offset;
        }

        const auto& packet_named = packet_actor.named_hub_npc;
        auto& named = actor.named_hub_npc;
        named.idle_active = packet_named.idle_active;
        named.idle_enabled = packet_named.idle_enabled;
        named.type_state_byte = packet_named.type_state_byte;
        named.idle_phase = packet_named.idle_phase;
        named.idle_frame = packet_named.idle_frame;
        named.idle_rate = packet_named.idle_rate;
        named.idle_amplitude = packet_named.idle_amplitude;
        named.motion_position = packet_named.motion_position;
        named.motion_direction = packet_named.motion_direction;
        named.render_scale = packet_named.render_scale;
        named.timer = packet_named.timer;
        named.pose = packet_named.pose;

        const bool idle_animator_valid =
            (actor.native_type_id == 0x138B ||
             actor.native_type_id == 0x138C ||
             actor.native_type_id == 0x138D ||
             actor.native_type_id == 0x138F) &&
            named.idle_active <= 1 &&
            named.idle_enabled <= 1 &&
            IsSaneNamedHubNpcPresentationFloat(named.idle_phase) &&
            IsSaneNamedHubNpcPresentationFloat(named.idle_frame) &&
            IsSaneNamedHubNpcPresentationFloat(named.idle_rate) &&
            IsSaneNamedHubNpcPresentationFloat(named.idle_amplitude);
        if (!idle_animator_valid) {
            actor.presentation_flags &= ~WorldActorPresentationFlagNamedHubNpcIdleAnimator;
        }

        const bool witch_orbit_valid =
            actor.native_type_id == 0x1389 &&
            IsSaneNamedHubNpcPresentationFloat(named.idle_frame) &&
            IsSaneNamedHubNpcPresentationFloat(named.idle_rate);
        if (!witch_orbit_valid) {
            actor.presentation_flags &= ~WorldActorPresentationFlagNamedHubNpcWitchOrbit;
        }

        const bool potion_motion_valid =
            actor.native_type_id == 0x138C &&
            IsSaneNamedHubNpcPresentationFloat(named.motion_position) &&
            IsSaneNamedHubNpcPresentationFloat(named.motion_direction) &&
            named.timer >= 0 &&
            named.timer <= 100000;
        if (!potion_motion_valid) {
            actor.presentation_flags &= ~WorldActorPresentationFlagNamedHubNpcPotionMotion;
        }

        const bool tyrannia_pose_valid =
            actor.native_type_id == 0x138F &&
            named.timer >= -1 &&
            named.timer <= 100000 &&
            named.pose >= 0 &&
            named.pose <= 2 &&
            IsSaneNamedHubNpcPresentationFloat(named.render_scale);
        if (!tyrannia_pose_valid) {
            actor.presentation_flags &= ~WorldActorPresentationFlagNamedHubNpcTyranniaPose;
        }

        const bool teacher_cycle_valid =
            actor.native_type_id == 0x1390 &&
            named.type_state_byte <= 1 &&
            IsSaneNamedHubNpcPresentationFloat(named.idle_phase) &&
            IsSaneNamedHubNpcPresentationFloat(named.idle_frame);
        if (!teacher_cycle_valid) {
            actor.presentation_flags &= ~WorldActorPresentationFlagNamedHubNpcTeacherCycle;
        }
        snapshot.actors.push_back(actor);
    }

    return snapshot;
}

void PublishWorldSnapshotRuntimeInfo(
    const CompleteWorldSnapshotPacketState& complete_snapshot,
    std::uint64_t now_ms) {
    UpdateRuntimeState([&](RuntimeState& state) {
        AppendWorldSnapshot(
            &state,
            BuildWorldSnapshotRuntimeInfo(
                complete_snapshot,
                now_ms));
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
    CompleteWorldSnapshotPacketState complete_snapshot;
    if (!TryAcceptWorldSnapshotFragment(
            packet,
            now_ms,
            &g_local_transport.pending_world_snapshots,
            &complete_snapshot)) {
        return;
    }
    PublishWorldSnapshotRuntimeInfo(complete_snapshot, now_ms);
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
            (drop_kind == LootDropKind::Powerup &&
                (packet_drop.native_type_id != kPowerupRewardNativeTypeId ||
                 packet_drop.amount_tier <
                     static_cast<std::int32_t>(PowerupRewardKind::BonusSkillPoint) ||
                 packet_drop.amount_tier >
                     static_cast<std::int32_t>(PowerupRewardKind::DamageX4) ||
                 !std::isfinite(packet_drop.value) ||
                 !std::isfinite(packet_drop.motion) ||
                 !std::isfinite(packet_drop.progress) ||
                 !std::isfinite(packet_drop.auxiliary))) ||
            ((drop_kind == LootDropKind::Item || drop_kind == LootDropKind::Potion) &&
                packet_drop.item_type_id == 0) ||
            (drop_kind == LootDropKind::Potion &&
                (packet_drop.item_type_id != kPotionItemTypeId ||
                 packet_drop.item_slot < kStockPotionSubtypeMin ||
                 packet_drop.item_slot > kStockPotionSubtypeMax)) ||
            (drop_kind == LootDropKind::Item &&
                packet_drop.item_recipe_uid == 0 &&
                !IsSupportedNonRecipeLootItem(
                    packet_drop.item_type_id,
                    packet_drop.item_recipe_uid,
                    packet_drop.item_slot))) {
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
        drop.auxiliary = packet_drop.auxiliary;
        drop.item_type_id = packet_drop.item_type_id;
        drop.item_recipe_uid = packet_drop.item_recipe_uid;
        drop.item_color_state_valid =
            (packet_drop.flags & LootDropSnapshotFlagItemColorState) != 0;
        if (drop.item_color_state_valid) {
            std::memcpy(
                drop.item_color_state.data(),
                packet_drop.item_color_state,
                drop.item_color_state.size());
        }
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

    const auto previous_runtime_state = SnapshotRuntimeState();
    if (previous_runtime_state.loot_snapshot.valid &&
        previous_runtime_state.loot_snapshot.run_nonce !=
            packet.run_nonce) {
        g_local_transport
            .native_applied_powerup_result_drop_ids.clear();
    }
    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    if (!PublishLootSnapshotRuntimeInfo(packet, now_ms)) {
        return;
    }

    std::string queue_error;
    (void)sdmod::QueueReplicatedLootSnapshot(SnapshotRuntimeState().loot_snapshot, &queue_error);
}

#include "multiplayer_local_transport/enemy_damage_authority.inl"

#include "multiplayer_local_transport/powerup_loot_authority.inl"
#include "multiplayer_local_transport/loot_pickup_authority.inl"

#include "multiplayer_local_transport/level_up_packet_sync.inl"
#include "multiplayer_local_transport/level_up_barrier_sync.inl"

#include "multiplayer_local_transport/spell_effect_sync.inl"
#include "multiplayer_local_transport/air_chain_sync.inl"
#include "multiplayer_local_transport/participant_vitals_authority.inl"

using TransportPacketBuffer =
    std::array<char, sizeof(LootSnapshotPacket)>;
