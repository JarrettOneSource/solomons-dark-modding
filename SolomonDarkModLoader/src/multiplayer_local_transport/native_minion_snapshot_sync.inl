bool PopulateNativeMinionSnapshot(
    const SDModSceneActorState& actor,
    WorldActorSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        actor.actor_address == 0 ||
        !IsNativeMinionType(actor.object_type_id)) {
        return false;
    }

    SDModNativeMinionState captured;
    if (!TryCaptureNativeMinionState(
            actor.actor_address,
            &captured) ||
        !captured.valid ||
        captured.native_type_id != actor.object_type_id ||
        captured.owner_participant_id == 0 ||
        captured.attack_timer < INT16_MIN ||
        captured.attack_timer > INT16_MAX ||
        captured.attack_cooldown < INT16_MIN ||
        captured.attack_cooldown > INT16_MAX ||
        captured.gait_primary > UINT8_MAX ||
        captured.gait_secondary > UINT8_MAX ||
        captured.target_refresh_timer < INT16_MIN ||
        captured.target_refresh_timer > INT16_MAX ||
        captured.ambient_effect_timer > UINT16_MAX ||
        captured.iron > UINT8_MAX) {
        return false;
    }

    snapshot->flags |=
        WorldActorSnapshotFlagNativeMinion;
    snapshot->flags |=
        WorldActorSnapshotFlagLifecycleOwned;
    snapshot->hp = captured.hp;
    snapshot->max_hp = captured.max_hp;

    auto& state = snapshot->native_minion;
    state.owner_participant_id =
        captured.owner_participant_id;
    state.state_flags = captured.state_flags;
    state.native_age = captured.native_age;
    state.attack_timer =
        static_cast<std::int16_t>(
            captured.attack_timer);
    state.attack_cooldown =
        static_cast<std::int16_t>(
            captured.attack_cooldown);
    state.gait_primary =
        static_cast<std::uint16_t>(
            captured.gait_primary);
    state.gait_secondary =
        static_cast<std::uint16_t>(
            captured.gait_secondary);
    state.target_refresh_timer =
        static_cast<std::int16_t>(
            captured.target_refresh_timer);
    state.ambient_effect_timer =
        static_cast<std::uint16_t>(
            captured.ambient_effect_timer);
    state.locomotion_sample_counter =
        static_cast<std::uint16_t>(
            captured.locomotion_sample_counter % 100);
    state.iron =
        static_cast<std::uint8_t>(captured.iron);
    state.terminal_reason =
        static_cast<std::uint8_t>(
            captured.terminal_reason);
    state.animation_phase =
        captured.animation_phase;
    state.steering_heading =
        captured.steering_heading;
    state.steering_step = captured.steering_step;
    state.damage_primary =
        captured.damage_primary;
    state.damage_secondary =
        captured.damage_secondary;
    state.reflect_ratio =
        captured.reflect_ratio;
    return ValidateNativeMinionPacketState(*snapshot);
}

void RetainActiveNativeMinionSnapshot(
    uintptr_t actor_address,
    const WorldActorSnapshotPacketState& packet) {
    if (actor_address == 0 ||
        packet.network_actor_id == 0 ||
        (packet.flags &
         WorldActorSnapshotFlagNativeMinion) == 0 ||
        (packet.native_minion.state_flags &
         NativeMinionStateFlagActive) == 0) {
        return;
    }
    RetainedNativeMinionSnapshot retained;
    retained.actor_address = actor_address;
    retained.packet = packet;
    g_local_transport
        .retained_native_minion_snapshots_by_network_id[
            packet.network_actor_id] =
        retained;
    g_local_transport
        .native_minion_terminal_tombstones_by_network_id
        .erase(packet.network_actor_id);
}

void ForgetNativeMinionSnapshotForActor(
    uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }
    for (auto it = g_local_transport
                       .retained_native_minion_snapshots_by_network_id
                       .begin();
         it != g_local_transport
                   .retained_native_minion_snapshots_by_network_id
                   .end();) {
        if (it->second.actor_address == actor_address) {
            it = g_local_transport
                     .retained_native_minion_snapshots_by_network_id
                     .erase(it);
        } else {
            ++it;
        }
    }
}

bool HasRetainedNativeMinionSnapshotForActor(
    uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }
    return std::any_of(
        g_local_transport
            .retained_native_minion_snapshots_by_network_id
            .begin(),
        g_local_transport
            .retained_native_minion_snapshots_by_network_id
            .end(),
        [&](const auto& entry) {
            return entry.second.actor_address ==
                actor_address;
        });
}

bool HasNativeMinionTerminalForNetworkActor(
    std::uint64_t network_actor_id) {
    return network_actor_id != 0 &&
        g_local_transport
            .native_minion_terminal_tombstones_by_network_id
            .find(network_actor_id) !=
        g_local_transport
            .native_minion_terminal_tombstones_by_network_id
            .end();
}

bool BuildNativeMinionTerminalTombstone(
    uintptr_t actor_address,
    NativeMinionTerminalReason reason,
    std::uint64_t now_ms) {
    if (actor_address == 0 ||
        !IsKnownNativeMinionTerminalReason(
            static_cast<std::uint8_t>(reason))) {
        return false;
    }

    const auto network_id_it =
        g_local_transport
            .run_host_local_world_actor_ids_by_address
            .find(actor_address);
    if (network_id_it ==
        g_local_transport
            .run_host_local_world_actor_ids_by_address
            .end()) {
        return false;
    }
    const auto network_actor_id =
        network_id_it->second;
    const auto retained_it =
        g_local_transport
            .retained_native_minion_snapshots_by_network_id
            .find(network_actor_id);
    if (retained_it ==
        g_local_transport
            .retained_native_minion_snapshots_by_network_id
            .end()) {
        return false;
    }

    NativeMinionTerminalTombstone tombstone;
    tombstone.actor_address = actor_address;
    tombstone.packet = retained_it->second.packet;
    tombstone.packet.flags |=
        WorldActorSnapshotFlagDead |
        WorldActorSnapshotFlagNativeMinion |
        WorldActorSnapshotFlagLifecycleOwned;
    tombstone.packet.native_minion.state_flags &=
        ~NativeMinionStateFlagActive;
    tombstone.packet.native_minion.state_flags |=
        NativeMinionStateFlagTerminal;
    tombstone.packet.native_minion.terminal_reason =
        static_cast<std::uint8_t>(reason);
    tombstone.packet.hp = 0.0f;
    tombstone.expires_ms =
        now_ms + kNativeMinionTombstoneHoldMs;
    if (!ValidateNativeMinionPacketState(
            tombstone.packet)) {
        return false;
    }

    g_local_transport
        .retained_native_minion_snapshots_by_network_id
        .erase(retained_it);
    g_local_transport
        .native_minion_terminal_tombstones_by_network_id[
            network_actor_id] =
        tombstone;
    return true;
}

void PruneNativeMinionTerminalTombstones(
    std::uint64_t now_ms) {
    for (auto it = g_local_transport
                       .native_minion_terminal_tombstones_by_network_id
                       .begin();
         it != g_local_transport
                   .native_minion_terminal_tombstones_by_network_id
                   .end();) {
        if (now_ms >= it->second.expires_ms) {
            it = g_local_transport
                     .native_minion_terminal_tombstones_by_network_id
                     .erase(it);
        } else {
            ++it;
        }
    }
}

bool AppendNativeMinionPacket(
    const WorldActorSnapshotPacketState& packet,
    CompleteWorldSnapshotPacketState* snapshot,
    std::unordered_set<std::uint64_t>*
        included_actor_ids) {
    if (snapshot == nullptr ||
        included_actor_ids == nullptr ||
        packet.network_actor_id == 0 ||
        included_actor_ids->find(packet.network_actor_id) !=
            included_actor_ids->end() ||
        snapshot->actors.size() >=
            kWorldSnapshotMaxLogicalActors ||
        !ValidateNativeMinionPacketState(packet)) {
        return false;
    }
    snapshot->actors.push_back(packet);
    included_actor_ids->insert(
        packet.network_actor_id);
    return true;
}

void AppendRetainedNativeMinionSnapshots(
    std::uint64_t now_ms,
    CompleteWorldSnapshotPacketState* snapshot,
    std::unordered_set<std::uint64_t>*
        included_actor_ids) {
    PruneNativeMinionTerminalTombstones(now_ms);
    for (const auto& [network_actor_id, retained] :
         g_local_transport
             .retained_native_minion_snapshots_by_network_id) {
        if (g_local_transport
                .native_minion_terminal_tombstones_by_network_id
                .find(network_actor_id) !=
            g_local_transport
                .native_minion_terminal_tombstones_by_network_id
                .end()) {
            continue;
        }
        (void)AppendNativeMinionPacket(
            retained.packet,
            snapshot,
            included_actor_ids);
    }
    for (const auto& [network_actor_id, tombstone] :
         g_local_transport
             .native_minion_terminal_tombstones_by_network_id) {
        (void)network_actor_id;
        (void)AppendNativeMinionPacket(
            tombstone.packet,
            snapshot,
            included_actor_ids);
    }
}
