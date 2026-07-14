constexpr std::size_t kAirChainRuntimeHistoryCapacity = 64;

float AirChainEndpointDistance(float left_x, float left_y, float right_x, float right_y) {
    const float dx = left_x - right_x;
    const float dy = left_y - right_y;
    const float squared = dx * dx + dy * dy;
    return std::isfinite(squared) && squared >= 0.0f ? std::sqrt(squared) : 0.0f;
}

std::uint32_t AllocateAirChainFrameSequence() {
    auto sequence = g_local_transport.next_air_chain_frame_sequence++;
    if (sequence == 0) {
        sequence = g_local_transport.next_air_chain_frame_sequence++;
    }
    return sequence;
}

void AppendAirChainRuntimeHistory(
    std::vector<AirChainSnapshotRuntimeInfo>* history,
    const AirChainSnapshotRuntimeInfo& snapshot) {
    if (history == nullptr) {
        return;
    }
    history->push_back(snapshot);
    if (history->size() > kAirChainRuntimeHistoryCapacity) {
        history->erase(
            history->begin(),
            history->begin() +
                static_cast<std::ptrdiff_t>(
                    history->size() - kAirChainRuntimeHistoryCapacity));
    }
}

AirChainSnapshotRuntimeInfo BuildAirChainSnapshotRuntimeInfo(
    const AirChainSnapshotPacket& packet,
    std::uint64_t received_ms) {
    AirChainSnapshotRuntimeInfo snapshot;
    snapshot.valid = true;
    snapshot.active =
        (packet.flags & AirChainSnapshotFlagActive) != 0;
    snapshot.terminal =
        (packet.flags & AirChainSnapshotFlagTerminal) != 0;
    snapshot.truncated =
        (packet.flags & AirChainSnapshotFlagTruncated) != 0;
    snapshot.owner_participant_id = packet.owner_participant_id;
    snapshot.received_ms = received_ms;
    snapshot.sequence = packet.header.sequence;
    snapshot.run_nonce = packet.run_nonce;
    snapshot.cast_sequence = packet.cast_sequence;
    snapshot.frame_sequence = packet.frame_sequence;
    snapshot.target_total_count = packet.target_total_count;

    const auto target_count = (std::min<std::uint32_t>)(
        packet.target_count,
        kAirChainSnapshotMaxTargets);
    snapshot.targets.reserve(target_count);
    for (std::uint32_t index = 0; index < target_count; ++index) {
        const auto& packet_target = packet.targets[index];
        AirChainTargetRuntimeInfo target;
        target.ordinal = packet_target.ordinal;
        target.network_actor_id = packet_target.network_actor_id;
        target.authoritative_null = packet_target.network_actor_id == 0;
        target.source_x = packet_target.source_x;
        target.source_y = packet_target.source_y;
        target.target_x = packet_target.target_x;
        target.target_y = packet_target.target_y;
        snapshot.targets.push_back(target);
    }
    return snapshot;
}

bool IsValidAirChainSnapshotPayload(const AirChainSnapshotPacket& packet) {
    const bool active =
        (packet.flags & AirChainSnapshotFlagActive) != 0;
    const bool terminal =
        (packet.flags & AirChainSnapshotFlagTerminal) != 0;
    const bool truncated =
        (packet.flags & AirChainSnapshotFlagTruncated) != 0;
    if (packet.owner_participant_id == 0 ||
        packet.cast_sequence == 0 ||
        packet.frame_sequence == 0 ||
        active == terminal ||
        packet.target_count > kAirChainSnapshotMaxTargets ||
        packet.target_total_count < packet.target_count ||
        truncated != (packet.target_total_count > packet.target_count) ||
        (terminal && (packet.target_count != 0 || packet.target_total_count != 0))) {
        return false;
    }

    for (std::uint32_t index = 0; index < packet.target_count; ++index) {
        const auto& target = packet.targets[index];
        if (target.ordinal != index ||
            !std::isfinite(target.source_x) ||
            !std::isfinite(target.source_y) ||
            !std::isfinite(target.target_x) ||
            !std::isfinite(target.target_y)) {
            return false;
        }
    }
    return true;
}

void StoreLocalAirChainRuntimeSnapshot(
    const AirChainSnapshotPacket& packet,
    std::uint64_t now_ms) {
    auto snapshot = BuildAirChainSnapshotRuntimeInfo(packet, now_ms);
    std::lock_guard<std::mutex> lock(g_air_chain_runtime_mutex);
    g_local_air_chain_capture_runtime = snapshot;
    AppendAirChainRuntimeHistory(&g_local_air_chain_history_runtime, snapshot);
}

void ResetAirChainRuntimeState() {
    std::lock_guard<std::mutex> lock(g_air_chain_runtime_mutex);
    g_local_air_chain_capture_runtime = AirChainSnapshotRuntimeInfo{};
    g_local_air_chain_history_runtime.clear();
    g_replicated_air_chain_snapshots_by_participant.clear();
    g_replicated_air_chain_history_runtime.clear();
    g_air_chain_apply_runtime = AirChainApplyRuntimeInfo{};
}

void QueueAirChainTerminal(
    std::uint32_t cast_sequence,
    std::uint32_t run_nonce,
    std::uint64_t now_ms) {
    if (cast_sequence == 0) {
        return;
    }
    const auto existing = std::find_if(
        g_local_transport.pending_air_chain_terminals.begin(),
        g_local_transport.pending_air_chain_terminals.end(),
        [&](const PendingAirChainTerminal& terminal) {
            return terminal.cast_sequence == cast_sequence;
        });
    if (existing != g_local_transport.pending_air_chain_terminals.end()) {
        existing->run_nonce = run_nonce;
        existing->expires_ms = now_ms + kAirChainTerminalHoldMs;
        return;
    }

    PendingAirChainTerminal terminal;
    terminal.cast_sequence = cast_sequence;
    terminal.run_nonce = run_nonce;
    terminal.expires_ms = now_ms + kAirChainTerminalHoldMs;
    g_local_transport.pending_air_chain_terminals.push_back(terminal);
}

bool TakeQueuedLocalAirChainFrame(QueuedLocalAirChainFrame* frame) {
    if (frame == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    if (!g_have_queued_local_air_chain_frame) {
        return false;
    }
    *frame = g_queued_local_air_chain_frame;
    g_queued_local_air_chain_frame = QueuedLocalAirChainFrame{};
    g_have_queued_local_air_chain_frame = false;
    return true;
}

void QueueLocalAirChainFrameInternal(
    uintptr_t caster_actor_address,
    const AirChainTargetCapture* targets,
    std::size_t target_count,
    std::size_t target_total_count) {
    if (!g_local_transport.initialized ||
        caster_actor_address == 0 ||
        (target_count != 0 && targets == nullptr)) {
        return;
    }

    QueuedLocalAirChainFrame frame;
    frame.caster_actor_address = caster_actor_address;
    frame.captured_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto copied_count = (std::min)(
        target_count,
        static_cast<std::size_t>(kAirChainSnapshotMaxTargets));
    const auto bounded_total_count = (std::min)(
        (std::max)(target_total_count, target_count),
        static_cast<std::size_t>(0xFFu));
    frame.target_count = static_cast<std::uint8_t>(copied_count);
    frame.target_total_count = static_cast<std::uint8_t>(bounded_total_count);
    frame.truncated = bounded_total_count > copied_count;
    for (std::size_t index = 0; index < copied_count; ++index) {
        auto captured = targets[index];
        if (!std::isfinite(captured.source_x) ||
            !std::isfinite(captured.source_y) ||
            !std::isfinite(captured.target_x) ||
            !std::isfinite(captured.target_y)) {
            captured = AirChainTargetCapture{};
        }
        frame.targets[index] = captured;
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    g_queued_local_air_chain_frame = frame;
    g_have_queued_local_air_chain_frame = true;
}

void SendAirChainSnapshots(std::uint64_t now_ms) {
    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return;
    }

    for (auto& terminal : g_local_transport.pending_air_chain_terminals) {
        if (terminal.cast_sequence == 0 ||
            terminal.expires_ms <= now_ms ||
            (terminal.last_sent_ms != 0 &&
             now_ms - terminal.last_sent_ms < kAirChainTerminalResendIntervalMs)) {
            continue;
        }

        AirChainSnapshotPacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::AirChainSnapshot,
            g_local_transport.next_sequence++);
        packet.owner_participant_id = g_local_transport.local_peer_id;
        packet.run_nonce = terminal.run_nonce;
        packet.cast_sequence = terminal.cast_sequence;
        packet.frame_sequence = AllocateAirChainFrameSequence();
        packet.flags = AirChainSnapshotFlagTerminal;
        for (const auto& endpoint : endpoints) {
            SendPacketToEndpoint(packet, endpoint);
        }
        terminal.last_sent_ms = now_ms;
        StoreLocalAirChainRuntimeSnapshot(packet, now_ms);
    }
    g_local_transport.pending_air_chain_terminals.erase(
        std::remove_if(
            g_local_transport.pending_air_chain_terminals.begin(),
            g_local_transport.pending_air_chain_terminals.end(),
            [&](const PendingAirChainTerminal& terminal) {
                return terminal.expires_ms <= now_ms;
            }),
        g_local_transport.pending_air_chain_terminals.end());
    for (auto it =
             g_local_transport.recent_local_air_chain_target_until_ms.begin();
         it != g_local_transport.recent_local_air_chain_target_until_ms.end();) {
        if (it->second < now_ms) {
            it = g_local_transport.recent_local_air_chain_target_until_ms.erase(it);
        } else {
            ++it;
        }
    }

    QueuedLocalAirChainFrame frame;
    if (!TakeQueuedLocalAirChainFrame(&frame)) {
        return;
    }
    const auto active = g_local_transport.active_local_cast_input;
    if (!active.active ||
        active.skill_id != kAirPrimarySkillId ||
        active.cast_sequence == 0 ||
        frame.captured_ms > now_ms ||
        now_ms - frame.captured_ms > kAirChainSnapshotFreshnessMs) {
        return;
    }

    AirChainSnapshotPacket packet{};
    packet.header = MakePacketHeader(
        PacketKind::AirChainSnapshot,
        g_local_transport.next_sequence++);
    packet.owner_participant_id = g_local_transport.local_peer_id;
    packet.run_nonce = active.run_nonce;
    packet.cast_sequence = active.cast_sequence;
    packet.frame_sequence = AllocateAirChainFrameSequence();
    packet.target_count = frame.target_count;
    packet.target_total_count = frame.target_total_count;
    packet.flags = static_cast<std::uint8_t>(
        AirChainSnapshotFlagActive |
        (frame.truncated ? AirChainSnapshotFlagTruncated : 0));
    for (std::uint32_t index = 0; index < frame.target_count; ++index) {
        const auto& captured = frame.targets[index];
        auto& target = packet.targets[index];
        target.network_actor_id = captured.network_actor_id;
        target.ordinal = static_cast<std::uint16_t>(index);
        target.source_x = captured.source_x;
        target.source_y = captured.source_y;
        target.target_x = captured.target_x;
        target.target_y = captured.target_y;
        if (captured.network_actor_id != 0) {
            g_local_transport.recent_local_air_chain_target_until_ms[
                captured.network_actor_id] =
                now_ms + kRecentLocalCastAssociationWindowMs;
        }
    }
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
    StoreLocalAirChainRuntimeSnapshot(packet, now_ms);
}

void ApplyAirChainSnapshotPacket(
    const AirChainSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsValidAirChainSnapshotPayload(packet) ||
        packet.owner_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* owner = FindParticipant(runtime_state, packet.owner_participant_id);
    if (owner == nullptr ||
        !IsRemoteParticipant(*owner) ||
        !owner->runtime.valid ||
        !owner->runtime.in_run ||
        owner->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run ||
        (owner->runtime.run_nonce != 0 &&
         packet.run_nonce != 0 &&
         owner->runtime.run_nonce != packet.run_nonce)) {
        return;
    }

    auto& last_sequence =
        g_local_transport.last_air_chain_packet_sequence_by_participant[
            packet.owner_participant_id];
    if (last_sequence != 0 &&
        static_cast<std::int32_t>(packet.header.sequence - last_sequence) <= 0) {
        return;
    }
    last_sequence = packet.header.sequence;

    UpsertPeerEndpoint(from, packet.owner_participant_id, now_ms);
    RelayPacketToPeers(packet, from);

    auto snapshot = BuildAirChainSnapshotRuntimeInfo(packet, now_ms);
    std::lock_guard<std::mutex> lock(g_air_chain_runtime_mutex);
    g_replicated_air_chain_snapshots_by_participant[
        packet.owner_participant_id] = snapshot;
    AppendAirChainRuntimeHistory(
        &g_replicated_air_chain_history_runtime,
        snapshot);
}

void UpsertAirChainApplyBinding(
    AirChainApplyRuntimeInfo* apply,
    const AirChainTargetRuntimeInfo& binding) {
    if (apply == nullptr) {
        return;
    }
    const auto existing = std::find_if(
        apply->bindings.begin(),
        apply->bindings.end(),
        [&](const AirChainTargetRuntimeInfo& candidate) {
            return candidate.ordinal == binding.ordinal;
        });
    if (existing == apply->bindings.end()) {
        apply->bindings.push_back(binding);
    } else {
        *existing = binding;
    }
    std::sort(
        apply->bindings.begin(),
        apply->bindings.end(),
        [](const AirChainTargetRuntimeInfo& left,
           const AirChainTargetRuntimeInfo& right) {
            return left.ordinal < right.ordinal;
        });
    apply->max_applied_target_count = (std::max)(
        apply->max_applied_target_count,
        static_cast<std::uint32_t>(apply->bindings.size()));
}

uintptr_t ResolveReplicatedAirChainTargetInternal(
    uintptr_t caster_actor_address,
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    uintptr_t fallback_actor_address,
    float source_x,
    float source_y,
    AirChainSourceEndpoint* authoritative_source,
    AirChainTargetEndpoint* authoritative_target) {
    if (authoritative_source != nullptr) {
        *authoritative_source = AirChainSourceEndpoint{};
    }
    if (authoritative_target != nullptr) {
        *authoritative_target = AirChainTargetEndpoint{};
    }
    if (caster_actor_address == 0 || owner_participant_id == 0) {
        return fallback_actor_address;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    std::lock_guard<std::mutex> lock(g_air_chain_runtime_mutex);
    const auto snapshot_it =
        g_replicated_air_chain_snapshots_by_participant.find(
            owner_participant_id);
    if (snapshot_it ==
        g_replicated_air_chain_snapshots_by_participant.end()) {
        g_air_chain_apply_runtime.cumulative_missing_snapshot_fallback_count += 1;
        return fallback_actor_address;
    }

    const auto& snapshot = snapshot_it->second;
    if (!snapshot.valid ||
        !snapshot.active ||
        snapshot.terminal ||
        now_ms < snapshot.received_ms ||
        now_ms - snapshot.received_ms > kAirChainSnapshotFreshnessMs) {
        g_air_chain_apply_runtime.cumulative_stale_snapshot_fallback_count += 1;
        return fallback_actor_address;
    }

    auto& apply = g_air_chain_apply_runtime;
    apply.valid = true;
    apply.applied_ms = now_ms;
    apply.cumulative_override_attempt_count += 1;
    if (apply.owner_participant_id != owner_participant_id ||
        apply.cast_sequence != snapshot.cast_sequence ||
        apply.frame_sequence != snapshot.frame_sequence) {
        apply.owner_participant_id = owner_participant_id;
        apply.cast_sequence = snapshot.cast_sequence;
        apply.frame_sequence = snapshot.frame_sequence;
        apply.bindings.clear();
    }

    AirChainTargetRuntimeInfo binding;
    binding.ordinal = target_ordinal;
    binding.fallback_actor_address = fallback_actor_address;
    binding.local_source_x = source_x;
    binding.local_source_y = source_y;

    if (target_ordinal >= snapshot.targets.size()) {
        if (snapshot.truncated) {
            apply.cumulative_missing_snapshot_fallback_count += 1;
            return fallback_actor_address;
        }
        binding.authoritative_null = true;
        binding.matched = true;
        apply.cumulative_authoritative_null_count += 1;
        UpsertAirChainApplyBinding(&apply, binding);
        return 0;
    }

    const auto& authoritative = snapshot.targets[target_ordinal];
    if (authoritative_source != nullptr &&
        authoritative.network_actor_id != 0) {
        authoritative_source->valid = true;
        authoritative_source->x = authoritative.source_x;
        authoritative_source->y = authoritative.source_y;
    }
    if (authoritative_target != nullptr &&
        authoritative.network_actor_id != 0) {
        authoritative_target->valid = true;
        authoritative_target->x = authoritative.target_x;
        authoritative_target->y = authoritative.target_y;
    }
    binding.network_actor_id = authoritative.network_actor_id;
    binding.source_x = authoritative.source_x;
    binding.source_y = authoritative.source_y;
    binding.target_x = authoritative.target_x;
    binding.target_y = authoritative.target_y;
    binding.source_error = AirChainEndpointDistance(
        source_x,
        source_y,
        authoritative.source_x,
        authoritative.source_y);
    if (authoritative.network_actor_id == 0) {
        binding.authoritative_null = true;
        binding.matched = true;
        apply.cumulative_authoritative_null_count += 1;
        UpsertAirChainApplyBinding(&apply, binding);
        return 0;
    }

    SDModSceneActorState local_target;
    if (!TryFindLocalRunEnemyByNetworkIdInternal(
            authoritative.network_actor_id,
            &local_target) ||
        local_target.actor_address == 0) {
        apply.cumulative_unmapped_target_count += 1;
        UpsertAirChainApplyBinding(&apply, binding);
        // An authoritative target that is not materialized must not silently
        // become a different local victim.
        return 0;
    }

    binding.local_actor_address = local_target.actor_address;
    binding.local_target_x = local_target.x;
    binding.local_target_y = local_target.y;
    binding.target_error = AirChainEndpointDistance(
        local_target.x,
        local_target.y,
        authoritative.target_x,
        authoritative.target_y);
    binding.matched = true;
    apply.cumulative_override_success_count += 1;
    UpsertAirChainApplyBinding(&apply, binding);
    return local_target.actor_address;
}

void RecordAirChainSourceOverrideInternal(
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    bool applied) {
    std::lock_guard<std::mutex> lock(g_air_chain_runtime_mutex);
    auto& apply = g_air_chain_apply_runtime;
    if (!apply.valid || apply.owner_participant_id != owner_participant_id) {
        return;
    }

    const auto binding_it = std::find_if(
        apply.bindings.begin(),
        apply.bindings.end(),
        [&](const AirChainTargetRuntimeInfo& binding) {
            return binding.ordinal == target_ordinal;
        });
    if (binding_it == apply.bindings.end()) {
        return;
    }

    auto& binding = *binding_it;
    binding.source_override_attempted = true;
    binding.source_override_applied = applied;
    binding.source_error_before_override = binding.source_error;
    if (applied) {
        binding.local_source_x = binding.source_x;
        binding.local_source_y = binding.source_y;
        binding.source_error = 0.0f;
        apply.cumulative_source_override_success_count += 1;
    } else {
        apply.cumulative_source_override_failure_count += 1;
    }
}

void RecordAirChainTargetOverrideInternal(
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    bool applied) {
    std::lock_guard<std::mutex> lock(g_air_chain_runtime_mutex);
    auto& apply = g_air_chain_apply_runtime;
    if (!apply.valid || apply.owner_participant_id != owner_participant_id) {
        return;
    }

    const auto binding_it = std::find_if(
        apply.bindings.begin(),
        apply.bindings.end(),
        [&](const AirChainTargetRuntimeInfo& binding) {
            return binding.ordinal == target_ordinal;
        });
    if (binding_it == apply.bindings.end()) {
        return;
    }

    auto& binding = *binding_it;
    binding.target_override_attempted = true;
    binding.target_override_applied = applied;
    binding.target_error_before_override = binding.target_error;
    if (applied) {
        binding.local_target_x = binding.target_x;
        binding.local_target_y = binding.target_y;
        binding.target_error = 0.0f;
        apply.cumulative_target_override_success_count += 1;
    } else {
        apply.cumulative_target_override_failure_count += 1;
    }
}
