// Complete logical world snapshots and bounded transport fragmentation.

struct CompleteWorldSnapshotPacketState {
    std::uint64_t authority_participant_id = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t snapshot_id = 0;
    WorldSceneKind scene_kind = WorldSceneKind::Unknown;
    std::vector<WorldActorSnapshotPacketState> actors;
};

struct PendingWorldSnapshotAssembly {
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
    std::vector<WorldActorSnapshotPacketState> actors;
};

struct PendingWorldSnapshotAssemblies {
    bool has_completed_snapshot = false;
    std::uint32_t last_completed_snapshot_id = 0;
    std::deque<PendingWorldSnapshotAssembly> assemblies;
};

constexpr std::size_t kPendingWorldSnapshotAssemblyLimit = 8;
constexpr std::uint64_t kPendingWorldSnapshotAssemblyMaxAgeMs = 500;

std::uint16_t WorldSnapshotFragmentCountForActorCount(
    std::uint32_t actor_count) {
    const auto fragment_count =
        actor_count == 0
            ? 1u
            : (actor_count + kWorldSnapshotActorsPerFragment - 1u) /
                  kWorldSnapshotActorsPerFragment;
    return static_cast<std::uint16_t>(fragment_count);
}

bool IsReplicatedWorldSceneKind(WorldSceneKind scene_kind) {
    return scene_kind == WorldSceneKind::SharedHub ||
        scene_kind == WorldSceneKind::Run;
}

bool IsValidWorldSnapshotActorPacketState(
    const WorldActorSnapshotPacketState& actor) {
    if (actor.network_actor_id == 0 ||
        actor.native_type_id == 0 ||
        !std::isfinite(actor.position_x) ||
        !std::isfinite(actor.position_y) ||
        !std::isfinite(actor.radius) ||
        actor.radius < 0.0f ||
        (actor.status_flags & ~kWorldActorStatusKnownFlags) != 0 ||
        (actor.lua_enemy_spawn_flags &
         ~kLuaEnemySpawnSnapshotKnownFlags) != 0) {
        return false;
    }

    if (actor.lua_content_id == 0) {
        if (actor.lua_enemy_spawn_flags != 0) {
            return false;
        }
    } else {
        if ((actor.flags & WorldActorSnapshotFlagTrackedEnemy) == 0 ||
            actor.lua_content_id >
                static_cast<std::uint64_t>(INT64_MAX)) {
            return false;
        }
        if (((actor.lua_enemy_spawn_flags & LuaEnemySpawnSnapshotFlagHp) != 0 &&
             (!std::isfinite(actor.lua_spawn_hp) || actor.lua_spawn_hp <= 0.0f ||
              actor.lua_spawn_hp > 1'000'000.0f)) ||
            ((actor.lua_enemy_spawn_flags & LuaEnemySpawnSnapshotFlagChaseSpeed) != 0 &&
             (!std::isfinite(actor.lua_spawn_chase_speed) ||
              actor.lua_spawn_chase_speed < 0.0f ||
              actor.lua_spawn_chase_speed > 1'000'000.0f)) ||
            ((actor.lua_enemy_spawn_flags & LuaEnemySpawnSnapshotFlagAttackSpeed) != 0 &&
             (!std::isfinite(actor.lua_spawn_attack_speed) ||
              actor.lua_spawn_attack_speed < 0.0f ||
              actor.lua_spawn_attack_speed > 1'000'000.0f)) ||
            ((actor.lua_enemy_spawn_flags & LuaEnemySpawnSnapshotFlagScale) != 0 &&
             (!std::isfinite(actor.lua_spawn_scale) ||
              actor.lua_spawn_scale < 0.01f ||
              actor.lua_spawn_scale > 1'000.0f))) {
            return false;
        }
    }

    const bool turn_undead_state_valid =
        (actor.status_flags &
         WorldActorStatusFlagTurnUndeadStateValid) != 0;
    const bool turn_undead_active =
        (actor.status_flags & WorldActorStatusFlagTurnUndeadActive) != 0;
    if (turn_undead_active && !turn_undead_state_valid) {
        return false;
    }
    if (!turn_undead_state_valid) {
        return true;
    }
    return IsTurnUndeadEligibleRunEnemyType(actor.native_type_id) &&
        actor.turn_undead_duration_ticks >= 0 &&
        actor.turn_undead_duration_ticks <= 100000 &&
        (turn_undead_active ==
         (actor.turn_undead_duration_ticks > 0)) &&
        std::isfinite(actor.turn_undead_flee_heading) &&
        std::abs(actor.turn_undead_flee_heading) <= 36000.0f &&
        std::isfinite(actor.turn_undead_activation_scalar) &&
        actor.turn_undead_activation_scalar >= 0.0f &&
        actor.turn_undead_activation_scalar <= 65536.0f;
}

bool IsValidWorldSnapshotFragmentMetadata(
    const WorldSnapshotPacket& packet) {
    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);
    if (packet.authority_participant_id == 0 ||
        packet.snapshot_id == 0 ||
        !IsReplicatedWorldSceneKind(scene_kind) ||
        packet.actor_total_count > kWorldSnapshotMaxLogicalActors) {
        return false;
    }

    const auto expected_fragment_count =
        WorldSnapshotFragmentCountForActorCount(packet.actor_total_count);
    if (packet.fragment_count != expected_fragment_count ||
        packet.fragment_index >= packet.fragment_count ||
        packet.actor_count > kWorldSnapshotActorsPerFragment) {
        return false;
    }

    const auto expected_start =
        static_cast<std::uint32_t>(packet.fragment_index) *
        kWorldSnapshotActorsPerFragment;
    if (packet.actor_start_index != expected_start ||
        expected_start > packet.actor_total_count) {
        return false;
    }

    const auto remaining_actor_count =
        packet.actor_total_count - expected_start;
    const auto expected_actor_count =
        (std::min<std::uint32_t>)(
            remaining_actor_count,
            kWorldSnapshotActorsPerFragment);
    if (packet.actor_count != expected_actor_count) {
        return false;
    }

    for (std::uint16_t index = 0; index < packet.actor_count; ++index) {
        if (!IsValidWorldSnapshotActorPacketState(packet.actors[index])) {
            return false;
        }
    }
    return true;
}

bool BuildWorldSnapshotFragmentPackets(
    const CompleteWorldSnapshotPacketState& snapshot,
    std::uint32_t* next_packet_sequence,
    std::vector<WorldSnapshotPacket>* packets) {
    if (next_packet_sequence == nullptr ||
        packets == nullptr ||
        snapshot.authority_participant_id == 0 ||
        snapshot.snapshot_id == 0 ||
        !IsReplicatedWorldSceneKind(snapshot.scene_kind) ||
        snapshot.actors.size() > kWorldSnapshotMaxLogicalActors) {
        return false;
    }

    packets->clear();
    const auto actor_total_count =
        static_cast<std::uint32_t>(snapshot.actors.size());
    const auto fragment_count =
        WorldSnapshotFragmentCountForActorCount(actor_total_count);
    packets->reserve(fragment_count);

    for (std::uint16_t fragment_index = 0;
         fragment_index < fragment_count;
         ++fragment_index) {
        WorldSnapshotPacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::WorldSnapshot,
            (*next_packet_sequence)++);
        packet.authority_participant_id =
            snapshot.authority_participant_id;
        packet.scene_epoch = snapshot.scene_epoch;
        packet.run_nonce = snapshot.run_nonce;
        packet.snapshot_id = snapshot.snapshot_id;
        packet.fragment_index = fragment_index;
        packet.fragment_count = fragment_count;
        packet.actor_start_index = static_cast<std::uint16_t>(
            static_cast<std::uint32_t>(fragment_index) *
            kWorldSnapshotActorsPerFragment);
        packet.actor_total_count = actor_total_count;
        packet.scene_kind =
            static_cast<std::uint8_t>(snapshot.scene_kind);

        const auto remaining_actor_count =
            actor_total_count - packet.actor_start_index;
        packet.actor_count = static_cast<std::uint16_t>(
            (std::min<std::uint32_t>)(
                remaining_actor_count,
                kWorldSnapshotActorsPerFragment));
        for (std::uint16_t actor_index = 0;
             actor_index < packet.actor_count;
             ++actor_index) {
            packet.actors[actor_index] =
                snapshot.actors[
                    static_cast<std::size_t>(packet.actor_start_index) +
                    actor_index];
        }
        packets->push_back(packet);
    }
    return true;
}

bool WorldSnapshotFragmentMatchesPendingAssembly(
    const WorldSnapshotPacket& packet,
    const PendingWorldSnapshotAssembly& pending) {
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

void BeginPendingWorldSnapshotAssembly(
    const WorldSnapshotPacket& packet,
    std::uint64_t now_ms,
    PendingWorldSnapshotAssembly* pending) {
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
        WorldActorSnapshotPacketState{});
}

void PrunePendingWorldSnapshotAssemblies(
    PendingWorldSnapshotAssemblies* pending,
    std::uint64_t now_ms) {
    for (auto it = pending->assemblies.begin();
         it != pending->assemblies.end();) {
        if (now_ms < it->first_received_ms ||
            now_ms - it->first_received_ms >
                kPendingWorldSnapshotAssemblyMaxAgeMs) {
            it = pending->assemblies.erase(it);
        } else {
            ++it;
        }
    }
    while (pending->assemblies.size() >=
           kPendingWorldSnapshotAssemblyLimit) {
        pending->assemblies.pop_front();
    }
}

bool TryAcceptWorldSnapshotFragment(
    const WorldSnapshotPacket& packet,
    std::uint64_t now_ms,
    PendingWorldSnapshotAssemblies* pending,
    CompleteWorldSnapshotPacketState* out_snapshot) {
    if (pending == nullptr ||
        out_snapshot == nullptr ||
        !IsValidWorldSnapshotFragmentMetadata(packet)) {
        return false;
    }
    *out_snapshot = {};
    PrunePendingWorldSnapshotAssemblies(pending, now_ms);

    if (pending->has_completed_snapshot &&
        !IsPacketSequenceNewer(
            packet.snapshot_id,
            pending->last_completed_snapshot_id)) {
        return false;
    }

    auto assembly = std::find_if(
        pending->assemblies.begin(),
        pending->assemblies.end(),
        [&](const PendingWorldSnapshotAssembly& candidate) {
            return candidate.snapshot_id == packet.snapshot_id;
        });
    if (assembly == pending->assemblies.end()) {
        pending->assemblies.emplace_back();
        assembly = std::prev(pending->assemblies.end());
        BeginPendingWorldSnapshotAssembly(packet, now_ms, &*assembly);
    } else if (!WorldSnapshotFragmentMatchesPendingAssembly(
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

    const bool assembly_complete =
        assembly->received_fragment_count == assembly->fragment_count;
    if (!assembly_complete) {
        return false;
    }

    std::unordered_set<std::uint64_t> actor_ids;
    actor_ids.reserve(assembly->actors.size());
    for (const auto& actor : assembly->actors) {
        if (!IsValidWorldSnapshotActorPacketState(actor) ||
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

    const auto completed_snapshot_id = assembly->snapshot_id;
    pending->has_completed_snapshot = true;
    pending->last_completed_snapshot_id = completed_snapshot_id;
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
