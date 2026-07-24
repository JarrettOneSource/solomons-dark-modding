// Compact run-world motion generations and bounded transport fragmentation.

struct CompleteWorldMotionSnapshotPacketState {
    std::uint64_t authority_participant_id = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t snapshot_id = 0;
    WorldSceneKind scene_kind = WorldSceneKind::Unknown;
    std::vector<WorldActorMotionPacketState> actors;
};

struct WorldMotionSnapshotMergeState {
    // Motion is disposable per fragment. Keep one identity-backed overlay so a
    // missing fragment cannot withhold actors updated by the fragments received.
    bool initialized = false;
    std::uint32_t identity_snapshot_id = 0;
    CompleteWorldSnapshotPacketState snapshot;
    std::unordered_map<std::uint64_t, std::uint32_t>
        last_snapshot_id_by_actor;
};

constexpr std::uint8_t kWorldActorMotionFlags =
    WorldActorSnapshotFlagDead |
    WorldActorSnapshotFlagTargetAuthoritative;

std::uint16_t WorldMotionSnapshotFragmentCountForActorCount(
    std::uint32_t actor_count) {
    const auto fragment_count =
        actor_count == 0
            ? 1u
            : (actor_count +
               kWorldMotionSnapshotActorsPerFragment - 1u) /
                  kWorldMotionSnapshotActorsPerFragment;
    return static_cast<std::uint16_t>(fragment_count);
}

WorldActorMotionPacketState BuildWorldActorMotionPacketState(
    const WorldActorSnapshotPacketState& actor) {
    WorldActorMotionPacketState motion{};
    motion.network_actor_id = actor.network_actor_id;
    motion.target_participant_id = actor.target_participant_id;
    motion.target_native_type_id = actor.target_native_type_id;
    motion.target_actor_slot = actor.target_actor_slot;
    motion.target_world_slot = actor.target_world_slot;
    motion.target_bucket_delta = actor.target_bucket_delta;
    motion.flags = static_cast<std::uint8_t>(
        actor.flags & kWorldActorMotionFlags);
    motion.anim_drive_state = actor.anim_drive_state;
    motion.presentation_flags = actor.presentation_flags;
    motion.position_x = actor.position_x;
    motion.position_y = actor.position_y;
    motion.radius = actor.radius;
    motion.heading = actor.heading;
    motion.hp = actor.hp;
    motion.max_hp = actor.max_hp;
    motion.anim_drive_state_word = actor.anim_drive_state_word;
    motion.walk_cycle_primary = actor.walk_cycle_primary;
    motion.walk_cycle_secondary = actor.walk_cycle_secondary;
    motion.render_variant_primary = actor.render_variant_primary;
    motion.render_variant_secondary = actor.render_variant_secondary;
    motion.render_weapon_type = actor.render_weapon_type;
    motion.render_selection_byte = actor.render_selection_byte;
    motion.render_variant_tertiary = actor.render_variant_tertiary;
    motion.status_flags = actor.status_flags;
    motion.turn_undead_duration_ticks =
        actor.turn_undead_duration_ticks;
    motion.turn_undead_flee_heading =
        actor.turn_undead_flee_heading;
    motion.turn_undead_activation_scalar =
        actor.turn_undead_activation_scalar;
    return motion;
}

CompleteWorldMotionSnapshotPacketState BuildWorldMotionSnapshot(
    const CompleteWorldSnapshotPacketState& snapshot) {
    CompleteWorldMotionSnapshotPacketState motion;
    motion.authority_participant_id =
        snapshot.authority_participant_id;
    motion.scene_epoch = snapshot.scene_epoch;
    motion.run_nonce = snapshot.run_nonce;
    motion.snapshot_id = snapshot.snapshot_id;
    motion.scene_kind = snapshot.scene_kind;
    motion.actors.reserve(snapshot.actors.size());
    for (const auto& actor : snapshot.actors) {
        motion.actors.push_back(
            BuildWorldActorMotionPacketState(actor));
    }
    return motion;
}

bool IsValidWorldActorMotionPacketState(
    const WorldActorMotionPacketState& actor) {
    if (actor.network_actor_id == 0 ||
        (actor.flags & ~kWorldActorMotionFlags) != 0 ||
        !std::isfinite(actor.position_x) ||
        !std::isfinite(actor.position_y) ||
        !std::isfinite(actor.radius) ||
        actor.radius < 0.0f ||
        !std::isfinite(actor.heading) ||
        !std::isfinite(actor.hp) ||
        !std::isfinite(actor.max_hp) ||
        !std::isfinite(actor.walk_cycle_primary) ||
        !std::isfinite(actor.walk_cycle_secondary) ||
        (actor.status_flags & ~kWorldActorStatusKnownFlags) != 0) {
        return false;
    }

    const bool turn_undead_state_valid =
        (actor.status_flags &
         WorldActorStatusFlagTurnUndeadStateValid) != 0;
    const bool turn_undead_active =
        (actor.status_flags &
         WorldActorStatusFlagTurnUndeadActive) != 0;
    if (turn_undead_active && !turn_undead_state_valid) {
        return false;
    }
    if (!turn_undead_state_valid) {
        return true;
    }
    return actor.turn_undead_duration_ticks >= 0 &&
        actor.turn_undead_duration_ticks <= 100000 &&
        (turn_undead_active ==
         (actor.turn_undead_duration_ticks > 0)) &&
        std::isfinite(actor.turn_undead_flee_heading) &&
        std::abs(actor.turn_undead_flee_heading) <= 36000.0f &&
        std::isfinite(actor.turn_undead_activation_scalar) &&
        actor.turn_undead_activation_scalar >= 0.0f &&
        actor.turn_undead_activation_scalar <= 65536.0f;
}

bool IsValidWorldMotionSnapshotFragmentMetadata(
    const WorldMotionSnapshotPacket& packet) {
    const auto scene_kind =
        static_cast<WorldSceneKind>(packet.scene_kind);
    if (packet.authority_participant_id == 0 ||
        packet.snapshot_id == 0 ||
        scene_kind != WorldSceneKind::Run ||
        packet.actor_total_count >
            kWorldSnapshotMaxLogicalActors) {
        return false;
    }

    const auto expected_fragment_count =
        WorldMotionSnapshotFragmentCountForActorCount(
            packet.actor_total_count);
    if (packet.fragment_count != expected_fragment_count ||
        packet.fragment_index >= packet.fragment_count ||
        packet.actor_count >
            kWorldMotionSnapshotActorsPerFragment) {
        return false;
    }

    const auto expected_start =
        static_cast<std::uint32_t>(packet.fragment_index) *
        kWorldMotionSnapshotActorsPerFragment;
    if (packet.actor_start_index != expected_start ||
        expected_start > packet.actor_total_count) {
        return false;
    }

    const auto expected_actor_count =
        (std::min<std::uint32_t>)(
            packet.actor_total_count - expected_start,
            kWorldMotionSnapshotActorsPerFragment);
    if (packet.actor_count != expected_actor_count) {
        return false;
    }

    for (std::uint16_t index = 0;
         index < packet.actor_count;
         ++index) {
        if (!IsValidWorldActorMotionPacketState(
                packet.actors[index])) {
            return false;
        }
    }
    return true;
}

bool BuildWorldMotionSnapshotFragmentPackets(
    const CompleteWorldMotionSnapshotPacketState& snapshot,
    std::uint32_t* next_packet_sequence,
    std::vector<WorldMotionSnapshotPacket>* packets) {
    if (next_packet_sequence == nullptr ||
        packets == nullptr ||
        snapshot.authority_participant_id == 0 ||
        snapshot.snapshot_id == 0 ||
        snapshot.scene_kind != WorldSceneKind::Run ||
        snapshot.actors.size() >
            kWorldSnapshotMaxLogicalActors) {
        return false;
    }

    packets->clear();
    const auto actor_total_count =
        static_cast<std::uint32_t>(snapshot.actors.size());
    const auto fragment_count =
        WorldMotionSnapshotFragmentCountForActorCount(
            actor_total_count);
    packets->reserve(fragment_count);

    for (std::uint16_t fragment_index = 0;
         fragment_index < fragment_count;
         ++fragment_index) {
        WorldMotionSnapshotPacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::WorldMotionSnapshot,
            (*next_packet_sequence)++);
        packet.authority_participant_id =
            snapshot.authority_participant_id;
        packet.scene_epoch = snapshot.scene_epoch;
        packet.run_nonce = snapshot.run_nonce;
        packet.snapshot_id = snapshot.snapshot_id;
        packet.fragment_index = fragment_index;
        packet.fragment_count = fragment_count;
        packet.actor_start_index =
            static_cast<std::uint16_t>(
                static_cast<std::uint32_t>(fragment_index) *
                kWorldMotionSnapshotActorsPerFragment);
        packet.actor_total_count = actor_total_count;
        packet.scene_kind =
            static_cast<std::uint8_t>(snapshot.scene_kind);
        packet.actor_count = static_cast<std::uint16_t>(
            (std::min<std::uint32_t>)(
                actor_total_count -
                    packet.actor_start_index,
                kWorldMotionSnapshotActorsPerFragment));
        for (std::uint16_t actor_index = 0;
             actor_index < packet.actor_count;
             ++actor_index) {
            packet.actors[actor_index] =
                snapshot.actors[
                    static_cast<std::size_t>(
                        packet.actor_start_index) +
                    actor_index];
        }
        packets->push_back(packet);
    }
    return true;
}

void ApplyWorldActorMotionPacketState(
    const WorldActorMotionPacketState& motion,
    WorldActorSnapshotPacketState* actor) {
    actor->target_participant_id =
        motion.target_participant_id;
    actor->target_native_type_id =
        motion.target_native_type_id;
    actor->target_actor_slot = motion.target_actor_slot;
    actor->target_world_slot = motion.target_world_slot;
    actor->target_bucket_delta = motion.target_bucket_delta;
    actor->flags = static_cast<std::uint8_t>(
        (actor->flags & ~kWorldActorMotionFlags) |
        (motion.flags & kWorldActorMotionFlags));
    actor->anim_drive_state = motion.anim_drive_state;
    actor->presentation_flags = motion.presentation_flags;
    actor->position_x = motion.position_x;
    actor->position_y = motion.position_y;
    actor->radius = motion.radius;
    actor->heading = motion.heading;
    actor->hp = motion.hp;
    actor->max_hp = motion.max_hp;
    actor->anim_drive_state_word =
        motion.anim_drive_state_word;
    actor->walk_cycle_primary = motion.walk_cycle_primary;
    actor->walk_cycle_secondary =
        motion.walk_cycle_secondary;
    actor->render_variant_primary =
        motion.render_variant_primary;
    actor->render_variant_secondary =
        motion.render_variant_secondary;
    actor->render_weapon_type = motion.render_weapon_type;
    actor->render_selection_byte =
        motion.render_selection_byte;
    actor->render_variant_tertiary =
        motion.render_variant_tertiary;
    actor->status_flags = motion.status_flags;
    actor->turn_undead_duration_ticks =
        motion.turn_undead_duration_ticks;
    actor->turn_undead_flee_heading =
        motion.turn_undead_flee_heading;
    actor->turn_undead_activation_scalar =
        motion.turn_undead_activation_scalar;
}

bool WorldMotionSnapshotMetadataMatchesIdentity(
    const WorldMotionSnapshotPacket& motion,
    const CompleteWorldSnapshotPacketState& identity) {
    return
        motion.authority_participant_id ==
            identity.authority_participant_id &&
        motion.scene_epoch == identity.scene_epoch &&
        motion.run_nonce == identity.run_nonce &&
        static_cast<WorldSceneKind>(motion.scene_kind) ==
            WorldSceneKind::Run &&
        identity.scene_kind == WorldSceneKind::Run &&
        motion.actor_total_count == identity.actors.size();
}

void ResetWorldMotionSnapshotMergeState(
    const CompleteWorldSnapshotPacketState& identity,
    WorldMotionSnapshotMergeState* merge_state) {
    merge_state->initialized = true;
    merge_state->identity_snapshot_id =
        identity.snapshot_id;
    merge_state->snapshot = identity;
    merge_state->last_snapshot_id_by_actor.clear();
    merge_state->last_snapshot_id_by_actor.reserve(
        identity.actors.size());
    for (const auto& actor : identity.actors) {
        merge_state->last_snapshot_id_by_actor.emplace(
            actor.network_actor_id,
            identity.snapshot_id);
    }
}

void RefreshWorldMotionSnapshotIdentity(
    const CompleteWorldSnapshotPacketState& identity,
    WorldMotionSnapshotMergeState* merge_state) {
    if (!merge_state->initialized ||
        merge_state->snapshot.authority_participant_id !=
            identity.authority_participant_id ||
        merge_state->snapshot.scene_epoch !=
            identity.scene_epoch ||
        merge_state->snapshot.run_nonce != identity.run_nonce ||
        merge_state->snapshot.scene_kind != identity.scene_kind) {
        ResetWorldMotionSnapshotMergeState(
            identity,
            merge_state);
        return;
    }
    if (merge_state->identity_snapshot_id ==
        identity.snapshot_id) {
        return;
    }

    std::unordered_map<
        std::uint64_t,
        const WorldActorSnapshotPacketState*> old_actors_by_id;
    old_actors_by_id.reserve(
        merge_state->snapshot.actors.size());
    for (const auto& actor : merge_state->snapshot.actors) {
        old_actors_by_id.emplace(
            actor.network_actor_id,
            &actor);
    }

    // A reliable identity checkpoint can arrive behind newer disposable
    // motion. Refresh structural fields without regressing those actors.
    CompleteWorldSnapshotPacketState refreshed = identity;
    std::unordered_map<std::uint64_t, std::uint32_t>
        refreshed_snapshot_ids;
    refreshed_snapshot_ids.reserve(identity.actors.size());
    for (auto& actor : refreshed.actors) {
        const auto last_snapshot =
            merge_state->last_snapshot_id_by_actor.find(
                actor.network_actor_id);
        const auto old_actor = old_actors_by_id.find(
            actor.network_actor_id);
        if (last_snapshot !=
                merge_state->last_snapshot_id_by_actor.end() &&
            old_actor != old_actors_by_id.end() &&
            IsPacketSequenceNewer(
                last_snapshot->second,
                identity.snapshot_id)) {
            const auto motion =
                BuildWorldActorMotionPacketState(
                    *old_actor->second);
            ApplyWorldActorMotionPacketState(
                motion,
                &actor);
            refreshed_snapshot_ids.emplace(
                actor.network_actor_id,
                last_snapshot->second);
        } else {
            refreshed_snapshot_ids.emplace(
                actor.network_actor_id,
                identity.snapshot_id);
        }
    }
    if (IsPacketSequenceNewer(
            merge_state->snapshot.snapshot_id,
            refreshed.snapshot_id)) {
        refreshed.snapshot_id =
            merge_state->snapshot.snapshot_id;
    }
    merge_state->identity_snapshot_id =
        identity.snapshot_id;
    merge_state->snapshot = std::move(refreshed);
    merge_state->last_snapshot_id_by_actor =
        std::move(refreshed_snapshot_ids);
}

bool TryApplyWorldMotionSnapshotFragment(
    const WorldMotionSnapshotPacket& packet,
    const CompleteWorldSnapshotPacketState& identity,
    WorldMotionSnapshotMergeState* merge_state,
    CompleteWorldSnapshotPacketState* out_snapshot) {
    if (merge_state == nullptr ||
        out_snapshot == nullptr ||
        !IsValidWorldMotionSnapshotFragmentMetadata(packet)) {
        return false;
    }
    *out_snapshot = {};
    if (!WorldMotionSnapshotMetadataMatchesIdentity(
            packet,
            identity)) {
        return false;
    }

    RefreshWorldMotionSnapshotIdentity(
        identity,
        merge_state);
    std::unordered_map<
        std::uint64_t,
        WorldActorSnapshotPacketState*> actors_by_id;
    actors_by_id.reserve(
        merge_state->snapshot.actors.size());
    for (auto& actor : merge_state->snapshot.actors) {
        actors_by_id.emplace(
            actor.network_actor_id,
            &actor);
    }

    std::unordered_set<std::uint64_t> fragment_actor_ids;
    fragment_actor_ids.reserve(packet.actor_count);
    for (std::uint16_t actor_index = 0;
         actor_index < packet.actor_count;
         ++actor_index) {
        const auto& motion = packet.actors[actor_index];
        const auto actor = actors_by_id.find(
            motion.network_actor_id);
        if (actor == actors_by_id.end() ||
            actor->second == nullptr ||
            !fragment_actor_ids.insert(
                motion.network_actor_id).second) {
            return false;
        }
    }

    bool applied = false;
    for (std::uint16_t actor_index = 0;
         actor_index < packet.actor_count;
         ++actor_index) {
        const auto& motion = packet.actors[actor_index];
        const auto actor = actors_by_id.find(
            motion.network_actor_id);
        auto& last_snapshot_id =
            merge_state->last_snapshot_id_by_actor[
                motion.network_actor_id];
        if (last_snapshot_id != 0 &&
            !IsPacketSequenceNewer(
                packet.snapshot_id,
                last_snapshot_id)) {
            continue;
        }
        ApplyWorldActorMotionPacketState(
            motion,
            actor->second);
        last_snapshot_id = packet.snapshot_id;
        applied = true;
    }
    if (!applied) {
        return false;
    }
    if (IsPacketSequenceNewer(
            packet.snapshot_id,
            merge_state->snapshot.snapshot_id)) {
        merge_state->snapshot.snapshot_id =
            packet.snapshot_id;
    }
    if (!std::all_of(
            merge_state->snapshot.actors.begin(),
            merge_state->snapshot.actors.end(),
            IsValidWorldSnapshotActorPacketState)) {
        return false;
    }
    *out_snapshot = merge_state->snapshot;
    return true;
}

bool SameWorldActorIdentity(
    const WorldActorSnapshotPacketState& left,
    const WorldActorSnapshotPacketState& right) {
    constexpr std::uint8_t kIdentityFlags =
        WorldActorSnapshotFlagTrackedEnemy |
        WorldActorSnapshotFlagLifecycleOwned |
        WorldActorSnapshotFlagRunStatic |
        WorldActorSnapshotFlagPlayerCreated;
    return left.network_actor_id == right.network_actor_id &&
        left.native_type_id == right.native_type_id &&
        left.enemy_type == right.enemy_type &&
        left.actor_slot == right.actor_slot &&
        left.world_slot == right.world_slot &&
        (left.flags & kIdentityFlags) ==
            (right.flags & kIdentityFlags) &&
        left.lua_enemy_spawn_flags ==
            right.lua_enemy_spawn_flags &&
        left.lua_content_id == right.lua_content_id &&
        left.lua_spawn_hp == right.lua_spawn_hp &&
        left.lua_spawn_chase_speed ==
            right.lua_spawn_chase_speed &&
        left.lua_spawn_attack_speed ==
            right.lua_spawn_attack_speed &&
        left.lua_spawn_scale == right.lua_spawn_scale;
}

bool SameWorldSnapshotIdentity(
    const CompleteWorldSnapshotPacketState& left,
    const CompleteWorldSnapshotPacketState& right) {
    if (left.authority_participant_id !=
            right.authority_participant_id ||
        left.scene_epoch != right.scene_epoch ||
        left.run_nonce != right.run_nonce ||
        left.scene_kind != right.scene_kind ||
        left.actors.size() != right.actors.size()) {
        return false;
    }
    for (std::size_t index = 0;
         index < left.actors.size();
         ++index) {
        if (!SameWorldActorIdentity(
                left.actors[index],
                right.actors[index])) {
            return false;
        }
    }
    return true;
}
