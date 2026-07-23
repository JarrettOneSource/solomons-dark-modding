bool EncodeLuaRegisteredSpellEffectState(
    const LuaRegisteredSpellEffectState& state,
    LuaRegisteredSpellEffectPacketState* packet_state) {
    if (packet_state == nullptr || state.effect_id == 0 ||
        state.cast_request_id == 0 || state.content_id == 0 ||
        state.key.empty() ||
        state.key.size() > kLuaRegisteredSpellEffectKeyBytes ||
        !std::isfinite(state.x) || !std::isfinite(state.y) ||
        !std::isfinite(state.velocity_x) ||
        !std::isfinite(state.velocity_y) || !std::isfinite(state.radius) ||
        state.radius < 0.0f) {
        return false;
    }
    std::vector<std::uint8_t> encoded_data;
    std::string encode_error;
    if (!EncodeLuaModValue(state.data, &encoded_data, &encode_error) ||
        encoded_data.empty() ||
        encoded_data.size() > kLuaRegisteredSpellEffectDataBytes) {
        return false;
    }

    LuaRegisteredSpellEffectPacketState encoded{};
    encoded.effect_id = state.effect_id;
    encoded.cast_request_id = state.cast_request_id;
    encoded.content_id = state.content_id;
    encoded.x = state.x;
    encoded.y = state.y;
    encoded.velocity_x = state.velocity_x;
    encoded.velocity_y = state.velocity_y;
    encoded.radius = state.radius;
    encoded.age_ms = state.age_ms;
    encoded.remaining_ms = state.remaining_ms;
    encoded.data_size = static_cast<std::uint16_t>(encoded_data.size());
    encoded.key_size = static_cast<std::uint8_t>(state.key.size());
    std::copy(state.key.begin(), state.key.end(), encoded.key);
    std::copy(encoded_data.begin(), encoded_data.end(), encoded.data);
    *packet_state = encoded;
    return true;
}

bool DecodeLuaRegisteredSpellEffectState(
    const LuaRegisteredSpellEffectPacketState& packet_state,
    std::uint64_t owner_participant_id,
    LuaRegisteredSpellEffectState* state) {
    if (state == nullptr || owner_participant_id == 0 ||
        packet_state.effect_id == 0 || packet_state.cast_request_id == 0 ||
        packet_state.content_id == 0 || packet_state.key_size == 0 ||
        packet_state.key_size > kLuaRegisteredSpellEffectKeyBytes ||
        packet_state.data_size == 0 ||
        packet_state.data_size > kLuaRegisteredSpellEffectDataBytes ||
        packet_state.flags != 0 || !std::isfinite(packet_state.x) ||
        !std::isfinite(packet_state.y) ||
        !std::isfinite(packet_state.velocity_x) ||
        !std::isfinite(packet_state.velocity_y) ||
        !std::isfinite(packet_state.radius) || packet_state.radius < 0.0f) {
        return false;
    }
    if (std::any_of(
            packet_state.key + packet_state.key_size,
            std::end(packet_state.key),
            [](char value) { return value != 0; }) ||
        std::any_of(
            packet_state.data + packet_state.data_size,
            std::end(packet_state.data),
            [](std::uint8_t value) { return value != 0; })) {
        return false;
    }

    LuaModValue data;
    std::string decode_error;
    if (!DecodeLuaModValue(
            packet_state.data,
            packet_state.data_size,
            &data,
            &decode_error)) {
        return false;
    }
    LuaRegisteredSpellEffectState decoded;
    decoded.owner_participant_id = owner_participant_id;
    decoded.effect_id = packet_state.effect_id;
    decoded.cast_request_id = packet_state.cast_request_id;
    decoded.content_id = packet_state.content_id;
    decoded.key.assign(packet_state.key, packet_state.key_size);
    decoded.x = packet_state.x;
    decoded.y = packet_state.y;
    decoded.velocity_x = packet_state.velocity_x;
    decoded.velocity_y = packet_state.velocity_y;
    decoded.radius = packet_state.radius;
    decoded.age_ms = packet_state.age_ms;
    decoded.remaining_ms = packet_state.remaining_ms;
    decoded.data = std::move(data);
    *state = std::move(decoded);
    return true;
}

void SendLuaRegisteredSpellEffectSnapshotForOwner(
    std::uint64_t owner_participant_id,
    std::uint32_t run_nonce,
    const std::vector<LuaRegisteredSpellEffectState>& effects) {
    auto& generation = g_local_transport
        .next_lua_registered_spell_effect_generation_by_owner[
            owner_participant_id];
    ++generation;
    if (generation == 0) {
        generation = 1;
    }
    const auto bounded_count = (std::min)(
        effects.size(),
        static_cast<std::size_t>(
            kLuaRegisteredSpellEffectMaxLogicalEffects));
    const auto fragment_count = static_cast<std::uint16_t>((std::max)(
        std::size_t{1},
        (bounded_count + kLuaRegisteredSpellEffectStatesPerFragment - 1) /
            kLuaRegisteredSpellEffectStatesPerFragment));

    for (std::uint16_t fragment_index = 0;
         fragment_index < fragment_count;
         ++fragment_index) {
        LuaRegisteredSpellEffectSnapshotPacket packet{};
        packet.header = MakePacketHeader(
            PacketKind::LuaRegisteredSpellEffectSnapshot,
            g_local_transport.next_sequence++);
        packet.owner_participant_id = owner_participant_id;
        packet.generation = generation;
        packet.run_nonce = run_nonce;
        packet.scene_epoch = g_local_transport.world_scene_epoch;
        packet.fragment_index = fragment_index;
        packet.fragment_count = fragment_count;
        packet.effect_total_count =
            static_cast<std::uint16_t>(bounded_count);
        const auto first = static_cast<std::size_t>(fragment_index) *
            kLuaRegisteredSpellEffectStatesPerFragment;
        const auto count = (std::min)(
            bounded_count - (std::min)(first, bounded_count),
            static_cast<std::size_t>(
                kLuaRegisteredSpellEffectStatesPerFragment));
        for (std::size_t index = 0; index < count; ++index) {
            if (!EncodeLuaRegisteredSpellEffectState(
                    effects[first + index],
                    &packet.effects[packet.effect_count])) {
                continue;
            }
            ++packet.effect_count;
        }
        if (packet.effect_count != count) {
            return;
        }
        const auto wire_size =
            LuaRegisteredSpellEffectSnapshotPacketWireSize(
                packet.effect_count);
        for (const auto& endpoint : BuildKnownSendEndpoints()) {
            SendBufferToEndpoint(
                &packet,
                wire_size,
                endpoint,
                SteamNetworkSendMode::UnreliableNoDelay);
        }
    }
}

void SendLuaRegisteredSpellEffectSnapshots(std::uint64_t now_ms) {
    if (now_ms -
            g_local_transport
                .last_lua_registered_spell_effect_snapshot_send_ms <
        kLuaRegisteredSpellEffectSnapshotIntervalMs) {
        return;
    }
    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr || !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind !=
            ParticipantSceneIntentKind::Run) {
        return;
    }
    auto local_effects = SnapshotLocalLuaRegisteredSpellEffects();
    std::map<std::uint64_t, std::vector<LuaRegisteredSpellEffectState>>
        effects_by_owner;
    for (auto& effect : local_effects) {
        if (effect.owner_participant_id == 0) {
            continue;
        }
        effects_by_owner[effect.owner_participant_id].push_back(
            std::move(effect));
    }
    for (const auto owner :
         g_local_transport.local_lua_registered_spell_effect_snapshot_owners) {
        effects_by_owner[owner];
    }
    if (effects_by_owner.empty()) {
        return;
    }
    std::size_t generation_wire_size = 0;
    for (const auto& entry : effects_by_owner) {
        const auto& effects = entry.second;
        const auto bounded_count = (std::min)(
            effects.size(),
            static_cast<std::size_t>(
                kLuaRegisteredSpellEffectMaxLogicalEffects));
        const auto fragment_count = (std::max)(
            std::size_t{1},
            (bounded_count +
             kLuaRegisteredSpellEffectStatesPerFragment - 1) /
                kLuaRegisteredSpellEffectStatesPerFragment);
        generation_wire_size +=
            fragment_count *
                kLuaRegisteredSpellEffectSnapshotPacketPrefixBytes +
            bounded_count * sizeof(LuaRegisteredSpellEffectPacketState);
    }
    const auto send_interval_ms = BandwidthLimitedSnapshotIntervalMs(
        generation_wire_size,
        kLuaRegisteredSpellEffectSnapshotIntervalMs,
        kLuaRegisteredSpellEffectSnapshotBudgetBytesPerSecond);
    if (now_ms -
            g_local_transport
                .last_lua_registered_spell_effect_snapshot_send_ms <
        send_interval_ms) {
        return;
    }
    g_local_transport.last_lua_registered_spell_effect_snapshot_send_ms =
        now_ms;
    g_local_transport.local_lua_registered_spell_effect_snapshot_owners.clear();
    for (auto& [owner, effects] : effects_by_owner) {
        std::sort(
            effects.begin(),
            effects.end(),
            [](const LuaRegisteredSpellEffectState& left,
               const LuaRegisteredSpellEffectState& right) {
                if (left.content_id != right.content_id) {
                    return left.content_id < right.content_id;
                }
                return left.effect_id < right.effect_id;
            });
        SendLuaRegisteredSpellEffectSnapshotForOwner(
            owner,
            local->runtime.run_nonce,
            effects);
        if (!effects.empty()) {
            g_local_transport
                .local_lua_registered_spell_effect_snapshot_owners.insert(
                    owner);
        }
    }
}

bool ValidateLuaRegisteredSpellEffectSnapshotEnvelope(
    const LuaRegisteredSpellEffectSnapshotPacket& packet) {
    if (packet.owner_participant_id == 0 || packet.generation == 0 ||
        packet.fragment_count == 0 ||
        packet.fragment_count >
            (kLuaRegisteredSpellEffectMaxLogicalEffects +
             kLuaRegisteredSpellEffectStatesPerFragment - 1) /
                kLuaRegisteredSpellEffectStatesPerFragment ||
        packet.fragment_index >= packet.fragment_count ||
        packet.effect_total_count >
            kLuaRegisteredSpellEffectMaxLogicalEffects ||
        packet.effect_count >
            kLuaRegisteredSpellEffectStatesPerFragment ||
        packet.flags != 0 ||
        std::any_of(
            std::begin(packet.reserved),
            std::end(packet.reserved),
            [](std::uint8_t value) { return value != 0; })) {
        return false;
    }
    const auto expected_fragment_count = static_cast<std::uint16_t>((std::max)(
        1u,
        (static_cast<unsigned>(packet.effect_total_count) +
         kLuaRegisteredSpellEffectStatesPerFragment - 1) /
            kLuaRegisteredSpellEffectStatesPerFragment));
    if (packet.fragment_count != expected_fragment_count) {
        return false;
    }
    const auto first = static_cast<std::uint32_t>(packet.fragment_index) *
        kLuaRegisteredSpellEffectStatesPerFragment;
    const auto remaining = packet.effect_total_count > first
        ? packet.effect_total_count - first
        : 0;
    const auto expected_effect_count = static_cast<std::uint16_t>((std::min)(
        remaining,
        static_cast<std::uint32_t>(
            kLuaRegisteredSpellEffectStatesPerFragment)));
    return packet.effect_count == expected_effect_count;
}

void ApplyLuaRegisteredSpellEffectSnapshotPacket(
    const LuaRegisteredSpellEffectSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!ValidateLuaRegisteredSpellEffectSnapshotEnvelope(packet) ||
        packet.owner_participant_id == g_local_transport.local_peer_id) {
        return;
    }
    if (IsLocalTransportClient() &&
        !IsConfiguredRemoteAuthorityEndpoint(from)) {
        return;
    }
    const auto runtime_state = SnapshotRuntimeState();
    const auto* owner = FindParticipant(
        runtime_state,
        packet.owner_participant_id);
    if (owner == nullptr || !IsRemoteParticipant(*owner) ||
        !owner->runtime.valid || !owner->runtime.in_run ||
        owner->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run ||
        (owner->runtime.run_nonce != 0 && packet.run_nonce != 0 &&
         owner->runtime.run_nonce != packet.run_nonce)) {
        return;
    }

    std::vector<LuaRegisteredSpellEffectState> decoded;
    decoded.reserve(packet.effect_count);
    for (std::uint16_t index = 0; index < packet.effect_count; ++index) {
        LuaRegisteredSpellEffectState state;
        if (!DecodeLuaRegisteredSpellEffectState(
                packet.effects[index],
                packet.owner_participant_id,
                &state)) {
            return;
        }
        decoded.push_back(std::move(state));
    }

    {
        std::lock_guard<std::mutex> lock(
            g_lua_registered_spell_effect_snapshot_mutex);
        const auto completed_it = g_local_transport
            .completed_lua_registered_spell_effect_snapshots.find(
                packet.owner_participant_id);
        if (completed_it != g_local_transport
                .completed_lua_registered_spell_effect_snapshots.end() &&
            !IsPacketSequenceNewer(
                packet.generation,
                completed_it->second.generation)) {
            return;
        }
        auto& assembly = g_local_transport
            .pending_lua_registered_spell_effect_snapshots[
                packet.owner_participant_id];
        if (assembly.generation != packet.generation) {
            if (assembly.generation != 0 &&
                !IsPacketSequenceNewer(
                    packet.generation,
                    assembly.generation)) {
                return;
            }
            assembly = PendingLuaRegisteredSpellEffectSnapshot{};
            assembly.generation = packet.generation;
            assembly.run_nonce = packet.run_nonce;
            assembly.scene_epoch = packet.scene_epoch;
            assembly.fragment_count = packet.fragment_count;
            assembly.effect_total_count = packet.effect_total_count;
            assembly.effects.resize(packet.effect_total_count);
            assembly.received_fragments.assign(packet.fragment_count, 0);
        } else if (assembly.run_nonce != packet.run_nonce ||
                   assembly.scene_epoch != packet.scene_epoch ||
                   assembly.fragment_count != packet.fragment_count ||
                   assembly.effect_total_count !=
                       packet.effect_total_count) {
            return;
        }
        assembly.last_update_ms = now_ms;
        if (assembly.received_fragments[packet.fragment_index] != 0) {
            return;
        }
        const auto first = static_cast<std::size_t>(packet.fragment_index) *
            kLuaRegisteredSpellEffectStatesPerFragment;
        for (std::size_t index = 0; index < decoded.size(); ++index) {
            assembly.effects[first + index] = std::move(decoded[index]);
        }
        assembly.received_fragments[packet.fragment_index] = 1;
        ++assembly.received_fragment_count;
        if (assembly.received_fragment_count == assembly.fragment_count) {
            std::set<std::pair<std::uint64_t, std::uint64_t>> effect_ids;
            for (const auto& effect : assembly.effects) {
                if (!effect_ids
                         .emplace(effect.content_id, effect.effect_id)
                         .second) {
                    g_local_transport
                        .pending_lua_registered_spell_effect_snapshots.erase(
                            packet.owner_participant_id);
                    return;
                }
            }

            CompletedLuaRegisteredSpellEffectSnapshot completed;
            completed.owner_participant_id = packet.owner_participant_id;
            completed.generation = assembly.generation;
            completed.run_nonce = assembly.run_nonce;
            completed.scene_epoch = assembly.scene_epoch;
            completed.received_ms = now_ms;
            completed.effects = std::move(assembly.effects);
            g_local_transport.completed_lua_registered_spell_effect_snapshots[
                packet.owner_participant_id] = std::move(completed);
            g_local_transport
                .pending_lua_registered_spell_effect_snapshots.erase(
                    packet.owner_participant_id);
        }
    }

    if (IsLocalTransportHost()) {
        UpsertPeerEndpoint(from, packet.owner_participant_id, now_ms);
        RelayPacketBufferToPeers(
            &packet,
            LuaRegisteredSpellEffectSnapshotPacketWireSize(
                packet.effect_count),
            from,
            SteamNetworkSendMode::UnreliableNoDelay);
    }
}
