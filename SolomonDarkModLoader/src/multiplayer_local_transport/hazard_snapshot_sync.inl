// Authority-owned hostile projectile/area/beam snapshots. Native addresses are
// short-lived capture keys and never cross the packet or Lua boundary.

struct LocalHazardTrackingState {
    std::uint64_t hazard_id = 0;
    std::uint64_t last_seen_ms = 0;
    float last_x = 0.0f;
    float last_y = 0.0f;
};

std::unordered_map<uintptr_t, LocalHazardTrackingState> g_local_hazard_tracking_by_address;
std::uint64_t g_next_local_hazard_id = 1;
std::uint32_t g_local_hazard_tracking_run_nonce = 0;
std::uint32_t g_local_hazard_tracking_scene_epoch = 0;
std::uint64_t g_last_hazard_snapshot_send_ms = 0;
bool g_hazard_snapshot_had_hazards = false;

#include "hazard_snapshot_registry.inl"

void ResetLocalHazardTracking(
    std::uint32_t run_nonce,
    std::uint32_t scene_epoch) {
    g_local_hazard_tracking_by_address.clear();
    g_next_local_hazard_id = 1;
    g_local_hazard_tracking_run_nonce = run_nonce;
    g_local_hazard_tracking_scene_epoch = scene_epoch;
}

bool TryCaptureHazardState(
    const SDModSceneActorState& actor,
    std::uint64_t now_ms,
    HazardPacketState* state) {
    if (state == nullptr ||
        !actor.valid ||
        actor.actor_address == 0 ||
        actor.tracked_enemy ||
        actor.object_type_id == 0 ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        actor.radius < 0.0f ||
        actor.radius > 1024.0f) {
        return false;
    }

    HazardKind kind = HazardKind::Unknown;
    const bool type_known =
        TryResolveKnownHazardKind(
            actor.object_type_id,
            &kind);
    if (!type_known &&
        !IsUnknownEffectBandCandidate(
            actor.object_type_id)) {
        return false;
    }

    const auto source_participant_id =
        ResolveSemanticDamageSourceParticipantId(
            actor.actor_address);
    // A resolved participant source is friendly. Enemy-authored effects
    // inherit the targeted gameplay group, including group zero, so actor
    // group alone is not allegiance and must not suppress a hostile effect.
    if (source_participant_id != 0) {
        return false;
    }

    std::uint8_t pending_remove = 0;
    if (ProcessMemory::Instance().TryReadField(
            actor.actor_address,
            std::size_t{0x05},
            &pending_remove) &&
        pending_remove != 0) {
        return false;
    }

    auto [tracking_it, inserted] =
        g_local_hazard_tracking_by_address.try_emplace(
            actor.actor_address);
    auto& tracking = tracking_it->second;
    if (inserted || tracking.hazard_id == 0) {
        tracking.hazard_id =
            g_next_local_hazard_id++;
        if (tracking.hazard_id == 0) {
            tracking.hazard_id =
                g_next_local_hazard_id++;
        }
        tracking.last_x = actor.x;
        tracking.last_y = actor.y;
    }

    HazardPacketState captured{};
    captured.hazard_id = tracking.hazard_id;
    captured.native_type_id =
        actor.object_type_id;
    captured.source_participant_id =
        source_participant_id;
    captured.flags =
        HazardStateFlagActive |
        HazardStateFlagHostile |
        (type_known
             ? HazardStateFlagTypeKnown
             : 0);
    captured.kind = kind;
    captured.position_x = actor.x;
    captured.position_y = actor.y;
    captured.radius = actor.radius;
    captured.heading =
        ReadActorHeadingOrZero(
            actor.actor_address);
    if (tracking.last_seen_ms != 0 &&
        now_ms > tracking.last_seen_ms) {
        const auto elapsed_seconds =
            static_cast<float>(
                now_ms - tracking.last_seen_ms) /
            1000.0f;
        if (elapsed_seconds > 0.0f &&
            elapsed_seconds <= 1.0f) {
            captured.motion_x =
                (actor.x - tracking.last_x) /
                elapsed_seconds;
            captured.motion_y =
                (actor.y - tracking.last_y) /
                elapsed_seconds;
            if (std::isfinite(
                    captured.motion_x) &&
                std::isfinite(
                    captured.motion_y)) {
                captured.flags |=
                    HazardStateFlagMotionResolved;
            } else {
                captured.motion_x = 0.0f;
                captured.motion_y = 0.0f;
            }
        }
    }
    if (IsHomingHazardType(
            actor.object_type_id)) {
        captured.flags |=
            HazardStateFlagHoming;
    }

    tracking.last_seen_ms = now_ms;
    tracking.last_x = actor.x;
    tracking.last_y = actor.y;
    *state = captured;
    return true;
}

void AppendSyntheticUnknownHazardProbe(
    const ParticipantRuntimeInfo& observer,
    std::vector<HazardPacketState>* states) {
    if (states == nullptr ||
        !IsHazardSyntheticUnknownProbeEnabled()) {
        return;
    }
    HazardPacketState probe{};
    probe.hazard_id =
        0x7FFF000000000001ull;
    probe.native_type_id =
        0x0803; // Deliberate absent factory slot.
    probe.flags =
        HazardStateFlagActive |
        HazardStateFlagHostile |
        HazardStateFlagMotionResolved |
        HazardStateFlagLifetimeResolved;
    probe.kind = HazardKind::Projectile;
    probe.position_x =
        observer.position_x + 120.0f;
    probe.position_y = observer.position_y;
    probe.radius = 12.0f;
    probe.heading = 180.0f;
    probe.motion_x = -60.0f;
    probe.motion_y = 0.0f;
    probe.remaining_ticks = 300;
    states->push_back(probe);
}

HazardSnapshotRuntimeInfo
BuildHazardSnapshotRuntimeInfo(
    const HazardSnapshotPacket& packet,
    std::uint64_t now_ms) {
    HazardSnapshotRuntimeInfo snapshot{};
    snapshot.valid = true;
    snapshot.authority_participant_id =
        packet.authority_participant_id;
    snapshot.received_ms = now_ms;
    snapshot.sequence = packet.header.sequence;
    snapshot.scene_epoch = packet.scene_epoch;
    snapshot.run_nonce = packet.run_nonce;
    snapshot.hazard_total_count =
        packet.hazard_total_count;
    snapshot.truncated =
        (packet.snapshot_flags &
         HazardSnapshotFlagTruncated) != 0;
    snapshot.hazards.reserve(
        packet.hazard_count);

    for (std::uint32_t index = 0;
         index < packet.hazard_count;
         ++index) {
        const auto& packet_hazard =
            packet.hazards[index];
        if (packet_hazard.hazard_id == 0 ||
            (packet_hazard.flags &
             ~kHazardStateKnownFlags) != 0 ||
            (packet_hazard.flags &
             HazardStateFlagActive) == 0 ||
            (packet_hazard.flags &
             HazardStateFlagHostile) == 0 ||
            packet_hazard.kind >
                HazardKind::Beam ||
            !std::isfinite(
                packet_hazard.position_x) ||
            !std::isfinite(
                packet_hazard.position_y) ||
            !std::isfinite(
                packet_hazard.radius) ||
            packet_hazard.radius < 0.0f ||
            packet_hazard.radius > 1024.0f ||
            !std::isfinite(
                packet_hazard.heading) ||
            !std::isfinite(
                packet_hazard.motion_x) ||
            !std::isfinite(
                packet_hazard.motion_y) ||
            packet_hazard.remaining_ticks < 0 ||
            packet_hazard.remaining_ticks >
                1'000'000) {
            continue;
        }

        HazardSnapshot hazard{};
        hazard.hazard_id =
            packet_hazard.hazard_id;
        hazard.native_type_id =
            packet_hazard.native_type_id;
        hazard.active = true;
        hazard.hostile = true;
        hazard.type_known =
            (packet_hazard.flags &
             HazardStateFlagTypeKnown) != 0;
        hazard.kind = packet_hazard.kind;
        hazard.source_participant_id =
            packet_hazard
                .source_participant_id;
        hazard.source_network_actor_id =
            packet_hazard
                .source_network_actor_id;
        hazard.target_participant_id =
            packet_hazard
                .target_participant_id;
        hazard.target_network_actor_id =
            packet_hazard
                .target_network_actor_id;
        hazard.position_x =
            packet_hazard.position_x;
        hazard.position_y =
            packet_hazard.position_y;
        hazard.radius = packet_hazard.radius;
        hazard.heading =
            packet_hazard.heading;
        hazard.motion_resolved =
            (packet_hazard.flags &
             HazardStateFlagMotionResolved) != 0;
        hazard.motion_x =
            packet_hazard.motion_x;
        hazard.motion_y =
            packet_hazard.motion_y;
        hazard.lifetime_resolved =
            (packet_hazard.flags &
             HazardStateFlagLifetimeResolved) !=
            0;
        hazard.remaining_ticks =
            packet_hazard.remaining_ticks;
        hazard.homing =
            (packet_hazard.flags &
             HazardStateFlagHoming) != 0;
        snapshot.hazards.push_back(hazard);
    }
    return snapshot;
}

bool BuildLocalHazardSnapshotPacket(
    std::uint64_t now_ms,
    HazardSnapshotPacket* packet) {
    if (packet == nullptr ||
        !g_local_transport.is_host) {
        return false;
    }

    const auto runtime_state =
        SnapshotRuntimeState();
    const auto* local =
        FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind !=
            ParticipantSceneIntentKind::Run) {
        ResetLocalHazardTracking(0, 0);
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) ||
        !scene_state.valid ||
        SceneIntentFromLocalScene().kind !=
            ParticipantSceneIntentKind::Run) {
        return false;
    }
    RefreshWorldSceneTracking(
        scene_state,
        ParticipantSceneIntentKind::Run);
    if (g_local_hazard_tracking_run_nonce !=
            local->runtime.run_nonce ||
        g_local_hazard_tracking_scene_epoch !=
            g_local_transport.world_scene_epoch) {
        ResetLocalHazardTracking(
            local->runtime.run_nonce,
            g_local_transport.world_scene_epoch);
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }
    std::vector<SDModSceneActorState>
        transient_actors;
    if (!TryListTransientSceneActors(
            &transient_actors)) {
        return false;
    }
    actors.insert(
        actors.end(),
        transient_actors.begin(),
        transient_actors.end());

    std::vector<HazardPacketState> states;
    states.reserve(actors.size() + 1);
    std::unordered_set<uintptr_t>
        seen_addresses;
    std::unordered_set<uintptr_t>
        candidate_addresses;
    for (const auto& actor : actors) {
        if (!candidate_addresses
                 .insert(actor.actor_address)
                 .second) {
            continue;
        }
        HazardPacketState captured{};
        if (!TryCaptureHazardState(
                actor,
                now_ms,
                &captured)) {
            continue;
        }
        seen_addresses.insert(
            actor.actor_address);
        states.push_back(captured);
    }
    AppendSyntheticUnknownHazardProbe(
        local->runtime,
        &states);

    for (auto it =
             g_local_hazard_tracking_by_address
                 .begin();
         it !=
         g_local_hazard_tracking_by_address.end();) {
        if (seen_addresses.find(it->first) ==
            seen_addresses.end()) {
            it =
                g_local_hazard_tracking_by_address
                    .erase(it);
        } else {
            ++it;
        }
    }
    std::sort(
        states.begin(),
        states.end(),
        [](const HazardPacketState& left,
           const HazardPacketState& right) {
            return left.hazard_id <
                   right.hazard_id;
        });

    HazardSnapshotPacket built{};
    built.header = MakePacketHeader(
        PacketKind::HazardSnapshot,
        g_local_transport.next_sequence++);
    built.authority_participant_id =
        g_local_transport.local_peer_id;
    built.run_nonce =
        local->runtime.run_nonce;
    built.scene_epoch =
        g_local_transport.world_scene_epoch;
    built.hazard_total_count =
        static_cast<std::uint8_t>(
            (std::min<std::size_t>)(
                states.size(),
                0xFFu));
    const auto packet_count =
        (std::min)(
            states.size(),
            static_cast<std::size_t>(
                kHazardSnapshotMaxHazards));
    built.hazard_count =
        static_cast<std::uint8_t>(
            packet_count);
    if (states.size() > packet_count) {
        built.snapshot_flags |=
            HazardSnapshotFlagTruncated;
    }
    for (std::size_t index = 0;
         index < packet_count;
         ++index) {
        built.hazards[index] = states[index];
    }
    *packet = built;
    return true;
}

void PublishLocalHazardSnapshot(
    const HazardSnapshotPacket& packet,
    std::uint64_t now_ms) {
    auto snapshot =
        BuildHazardSnapshotRuntimeInfo(
            packet,
            now_ms);
    UpdateRuntimeState(
        [&](RuntimeState& state) {
            state.hazard_snapshot =
                std::move(snapshot);
        });
}

void SendHazardSnapshot(std::uint64_t now_ms) {
    constexpr std::uint64_t
        kMinimumIntervalMs = 50;
    if (now_ms -
            g_last_hazard_snapshot_send_ms <
        kMinimumIntervalMs) {
        return;
    }

    HazardSnapshotPacket packet{};
    if (!BuildLocalHazardSnapshotPacket(
            now_ms,
            &packet)) {
        return;
    }
    const auto wire_size =
        HazardSnapshotPacketWireSize(
            packet.hazard_count);
    const auto send_interval_ms =
        BandwidthLimitedSnapshotIntervalMs(
            wire_size,
            kMinimumIntervalMs,
            kLocalTransportAuxiliarySnapshotBudgetBytesPerSecond);
    if (now_ms -
            g_last_hazard_snapshot_send_ms <
        send_interval_ms) {
        return;
    }
    g_last_hazard_snapshot_send_ms = now_ms;
    PublishLocalHazardSnapshot(
        packet,
        now_ms);

    const bool has_hazards =
        packet.hazard_count != 0;
    if (!has_hazards &&
        !g_hazard_snapshot_had_hazards) {
        return;
    }
    g_hazard_snapshot_had_hazards =
        has_hazards;
    for (const auto& endpoint :
         BuildKnownSendEndpoints()) {
        SendBufferToEndpoint(
            &packet,
            wire_size,
            endpoint,
            SteamSendModeForPacket(packet));
    }
}

void ApplyHazardSnapshotPacket(
    const HazardSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        !IsConfiguredRemoteAuthorityEndpoint(
            from) ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id ==
            g_local_transport.local_peer_id) {
        return;
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        if (state.hazard_snapshot.valid &&
            state.hazard_snapshot.run_nonce ==
                packet.run_nonce &&
            !IsPacketSequenceNewer(
                packet.header.sequence,
                state.hazard_snapshot.sequence)) {
            return;
        }
        state.hazard_snapshot =
            BuildHazardSnapshotRuntimeInfo(
                packet,
                now_ms);
    });
}
