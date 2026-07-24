// Compact run-world motion generations and bounded transport fragmentation.

struct CompleteWorldMotionSnapshotPacketState {
    std::uint64_t authority_participant_id = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t snapshot_id = 0;
    WorldSceneKind scene_kind = WorldSceneKind::Unknown;
    std::vector<WorldActorMotionPacketState> actors;
};

struct PendingWorldMotionSnapshotAssembly {
    std::uint64_t authority_participant_id = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t snapshot_id = 0;
    WorldSceneKind scene_kind = WorldSceneKind::Unknown;
    std::uint16_t fragment_count = 0;
    std::uint16_t received_fragment_count = 0;
    std::uint32_t actor_total_count = 0;
    std::uint64_t first_received_ms = 0;
    std::vector<std::uint8_t> received_fragments;
    std::vector<WorldActorMotionPacketState> actors;
};

struct PendingWorldMotionSnapshotAssemblies {
    bool has_completed_snapshot = false;
    std::uint32_t last_completed_snapshot_id = 0;
    std::deque<PendingWorldMotionSnapshotAssembly> assemblies;
};

constexpr std::size_t kPendingWorldMotionSnapshotAssemblyLimit = 8;
constexpr std::uint64_t kPendingWorldMotionSnapshotAssemblyMaxAgeMs = 500;
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

bool WorldMotionSnapshotFragmentMatchesPendingAssembly(
    const WorldMotionSnapshotPacket& packet,
    const PendingWorldMotionSnapshotAssembly& pending) {
    return packet.authority_participant_id ==
            pending.authority_participant_id &&
        packet.scene_epoch == pending.scene_epoch &&
        packet.run_nonce == pending.run_nonce &&
        packet.snapshot_id == pending.snapshot_id &&
        static_cast<WorldSceneKind>(packet.scene_kind) ==
            pending.scene_kind &&
        packet.fragment_count == pending.fragment_count &&
        packet.actor_total_count == pending.actor_total_count;
}

void BeginPendingWorldMotionSnapshotAssembly(
    const WorldMotionSnapshotPacket& packet,
    std::uint64_t now_ms,
    PendingWorldMotionSnapshotAssembly* pending) {
    pending->authority_participant_id =
        packet.authority_participant_id;
    pending->scene_epoch = packet.scene_epoch;
    pending->run_nonce = packet.run_nonce;
    pending->snapshot_id = packet.snapshot_id;
    pending->scene_kind =
        static_cast<WorldSceneKind>(packet.scene_kind);
    pending->fragment_count = packet.fragment_count;
    pending->received_fragment_count = 0;
    pending->actor_total_count = packet.actor_total_count;
    pending->first_received_ms = now_ms;
    pending->received_fragments.assign(
        packet.fragment_count,
        std::uint8_t{0});
    pending->actors.assign(
        packet.actor_total_count,
        WorldActorMotionPacketState{});
}

void PrunePendingWorldMotionSnapshotAssemblies(
    PendingWorldMotionSnapshotAssemblies* pending,
    std::uint64_t now_ms) {
    for (auto it = pending->assemblies.begin();
         it != pending->assemblies.end();) {
        if (now_ms < it->first_received_ms ||
            now_ms - it->first_received_ms >
                kPendingWorldMotionSnapshotAssemblyMaxAgeMs) {
            it = pending->assemblies.erase(it);
        } else {
            ++it;
        }
    }
    while (pending->assemblies.size() >=
           kPendingWorldMotionSnapshotAssemblyLimit) {
        pending->assemblies.pop_front();
    }
}

bool TryAcceptWorldMotionSnapshotFragment(
    const WorldMotionSnapshotPacket& packet,
    std::uint64_t now_ms,
    PendingWorldMotionSnapshotAssemblies* pending,
    CompleteWorldMotionSnapshotPacketState* out_snapshot) {
    if (pending == nullptr ||
        out_snapshot == nullptr ||
        !IsValidWorldMotionSnapshotFragmentMetadata(packet)) {
        return false;
    }
    *out_snapshot = {};
    PrunePendingWorldMotionSnapshotAssemblies(
        pending,
        now_ms);

    if (pending->has_completed_snapshot &&
        !IsPacketSequenceNewer(
            packet.snapshot_id,
            pending->last_completed_snapshot_id)) {
        return false;
    }

    auto assembly = std::find_if(
        pending->assemblies.begin(),
        pending->assemblies.end(),
        [&](const PendingWorldMotionSnapshotAssembly& candidate) {
            return candidate.snapshot_id == packet.snapshot_id;
        });
    if (assembly == pending->assemblies.end()) {
        pending->assemblies.emplace_back();
        assembly = std::prev(pending->assemblies.end());
        BeginPendingWorldMotionSnapshotAssembly(
            packet,
            now_ms,
            &*assembly);
    } else if (!WorldMotionSnapshotFragmentMatchesPendingAssembly(
                   packet,
                   *assembly)) {
        return false;
    }

    if (assembly->received_fragments[packet.fragment_index] != 0) {
        return false;
    }

    const auto actor_start =
        static_cast<std::size_t>(packet.actor_start_index);
    for (std::uint16_t actor_index = 0;
         actor_index < packet.actor_count;
         ++actor_index) {
        assembly->actors[actor_start + actor_index] =
            packet.actors[actor_index];
    }
    assembly->received_fragments[packet.fragment_index] = 1;
    ++assembly->received_fragment_count;
    if (assembly->received_fragment_count !=
        assembly->fragment_count) {
        return false;
    }

    std::unordered_set<std::uint64_t> actor_ids;
    actor_ids.reserve(assembly->actors.size());
    for (const auto& actor : assembly->actors) {
        if (!IsValidWorldActorMotionPacketState(actor) ||
            !actor_ids.insert(actor.network_actor_id).second) {
            pending->assemblies.erase(assembly);
            return false;
        }
    }

    out_snapshot->authority_participant_id =
        assembly->authority_participant_id;
    out_snapshot->scene_epoch = assembly->scene_epoch;
    out_snapshot->run_nonce = assembly->run_nonce;
    out_snapshot->snapshot_id = assembly->snapshot_id;
    out_snapshot->scene_kind = assembly->scene_kind;
    out_snapshot->actors = std::move(assembly->actors);

    const auto completed_snapshot_id =
        assembly->snapshot_id;
    pending->has_completed_snapshot = true;
    pending->last_completed_snapshot_id =
        completed_snapshot_id;
    for (auto it = pending->assemblies.begin();
         it != pending->assemblies.end();) {
        if (it->snapshot_id == completed_snapshot_id ||
            !IsPacketSequenceNewer(
                it->snapshot_id,
                completed_snapshot_id)) {
            it = pending->assemblies.erase(it);
        } else {
            ++it;
        }
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

bool MergeWorldMotionSnapshotWithIdentity(
    const CompleteWorldMotionSnapshotPacketState& motion,
    const CompleteWorldSnapshotPacketState& identity,
    CompleteWorldSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        motion.authority_participant_id !=
            identity.authority_participant_id ||
        motion.scene_epoch != identity.scene_epoch ||
        motion.run_nonce != identity.run_nonce ||
        motion.scene_kind != WorldSceneKind::Run ||
        identity.scene_kind != WorldSceneKind::Run ||
        motion.actors.size() != identity.actors.size()) {
        return false;
    }

    *snapshot = identity;
    snapshot->snapshot_id = motion.snapshot_id;
    std::unordered_map<
        std::uint64_t,
        WorldActorSnapshotPacketState*> actors_by_id;
    actors_by_id.reserve(snapshot->actors.size());
    for (auto& actor : snapshot->actors) {
        actors_by_id.emplace(actor.network_actor_id, &actor);
    }
    for (const auto& actor_motion : motion.actors) {
        const auto actor = actors_by_id.find(
            actor_motion.network_actor_id);
        if (actor == actors_by_id.end() ||
            actor->second == nullptr) {
            return false;
        }
        ApplyWorldActorMotionPacketState(
            actor_motion,
            actor->second);
    }
    return std::all_of(
        snapshot->actors.begin(),
        snapshot->actors.end(),
        IsValidWorldSnapshotActorPacketState);
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
