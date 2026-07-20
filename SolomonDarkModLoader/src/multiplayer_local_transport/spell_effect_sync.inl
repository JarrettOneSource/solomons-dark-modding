bool IsReplicatedSpellEffectNativeType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case kEtherPrimaryNativeTypeId:
    case kFireballPrimaryNativeTypeId:
    case kWaterPrimaryNativeTypeId:
    case kFireEmberNativeTypeId:
    case kFirewalkerTrailNativeTypeId:
    case kMagicStormNativeTypeId:
        return true;
    default:
        return false;
    }
}

bool IsReplicatedSpellEffectMotionNativeType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case kEtherPrimaryNativeTypeId:
    case kFireballPrimaryNativeTypeId:
    case kWaterPrimaryNativeTypeId:
    case kFireEmberNativeTypeId:
        return true;
    default:
        return false;
    }
}

bool TryCaptureLocalSpellEffectState(
    const SDModSceneActorState& actor,
    SpellEffectPacketState* state) {
    if (state == nullptr ||
        actor.actor_address == 0 ||
        actor.actor_slot != 0 ||
        !IsReplicatedSpellEffectNativeType(actor.object_type_id) ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        actor.radius < 0.0f) {
        return false;
    }

    SpellEffectPacketState captured{};
    captured.native_type_id = actor.object_type_id;
    captured.flags =
        SpellEffectStateFlagActive |
        SpellEffectStateFlagTransform;
    captured.position_x = actor.x;
    captured.position_y = actor.y;
    captured.radius = actor.radius;
    captured.heading = ReadActorHeadingOrZero(actor.actor_address);

    auto& memory = ProcessMemory::Instance();
    float motion_x = 0.0f;
    float motion_y = 0.0f;
    if (IsReplicatedSpellEffectMotionNativeType(actor.object_type_id) &&
        memory.TryReadField(actor.actor_address, kSpellEffectMotionXOffset, &motion_x) &&
        memory.TryReadField(actor.actor_address, kSpellEffectMotionYOffset, &motion_y) &&
        std::isfinite(motion_x) &&
        std::isfinite(motion_y)) {
        captured.flags |= SpellEffectStateFlagMotion;
        captured.motion_x = motion_x;
        captured.motion_y = motion_y;
    }

    if (actor.object_type_id == kFireEmberNativeTypeId) {
        const bool ember_runtime_readable =
            memory.TryReadField(
                actor.actor_address,
                kEmberVerticalPositionOffset,
                &captured.ember_vertical_position) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberVerticalVelocityOffset,
                &captured.ember_vertical_velocity) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberDamageOffset,
                &captured.ember_damage) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberLifetimeOffset,
                &captured.ember_lifetime) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberInitialLifetimeOffset,
                &captured.ember_initial_lifetime) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberAnimationProgressOffset,
                &captured.ember_animation_progress) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberVariantOffset,
                &captured.ember_variant) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberFrameIntervalOffset,
                &captured.ember_frame_interval) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberConfigPrimaryOffset,
                &captured.ember_config_primary) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberConfigSecondaryOffset,
                &captured.ember_config_secondary) &&
            memory.TryReadField(
                actor.actor_address,
                kEmberConfigTertiaryOffset,
                &captured.ember_config_tertiary) &&
            std::isfinite(captured.ember_vertical_position) &&
            std::isfinite(captured.ember_vertical_velocity) &&
            std::isfinite(captured.ember_damage) &&
            std::isfinite(captured.ember_lifetime) &&
            std::isfinite(captured.ember_initial_lifetime) &&
            std::isfinite(captured.ember_animation_progress);
        if (ember_runtime_readable) {
            captured.flags |= SpellEffectStateFlagEmberRuntime;
            if (captured.ember_lifetime <= 0.0f) {
                return false;
            }
        } else {
            return false;
        }
    }

    if (actor.object_type_id == kFirewalkerTrailNativeTypeId) {
        const bool firewalker_runtime_readable =
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerSourceSlotOffset,
                &captured.firewalker_source_slot) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerCollisionScaleOffset,
                &captured.firewalker_collision_scale) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerPhaseOffset,
                &captured.firewalker_phase) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerPhaseStepOffset,
                &captured.firewalker_phase_step) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerLifetimeOffset,
                &captured.firewalker_lifetime) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerFadeOffset,
                &captured.firewalker_fade) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerDirectionOffset,
                &captured.firewalker_direction) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerVisualScaleOffset,
                &captured.firewalker_visual_scale) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerActiveOffset,
                &captured.firewalker_active) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerDamageOffset,
                &captured.firewalker_damage) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerAuxOffset,
                &captured.firewalker_aux) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerVariantOffset,
                &captured.firewalker_variant) &&
            memory.TryReadField(
                actor.actor_address,
                kFirewalkerDamageMaskOffset,
                &captured.firewalker_damage_mask) &&
            std::isfinite(captured.firewalker_collision_scale) &&
            std::isfinite(captured.firewalker_phase) &&
            std::isfinite(captured.firewalker_phase_step) &&
            std::isfinite(captured.firewalker_lifetime) &&
            std::isfinite(captured.firewalker_fade) &&
            std::isfinite(captured.firewalker_direction) &&
            std::isfinite(captured.firewalker_visual_scale) &&
            std::isfinite(captured.firewalker_damage) &&
            captured.firewalker_lifetime > 0.0f;
        if (!firewalker_runtime_readable) {
            return false;
        }
        captured.flags |= SpellEffectStateFlagFirewalkerRuntime;
    }

    *state = captured;
    return true;
}

std::uint64_t SpellEffectOrdinalKey(
    std::uint32_t cast_sequence,
    std::uint32_t native_type_id) {
    return (static_cast<std::uint64_t>(cast_sequence) << 32) |
           static_cast<std::uint64_t>(native_type_id);
}

void RefreshLocalSpellEffectTracking(
    const std::vector<SDModSceneActorState>& actors,
    std::uint64_t now_ms,
    std::vector<SpellEffectPacketState>* states) {
    if (states == nullptr) {
        return;
    }
    states->clear();

    std::unordered_set<uintptr_t> seen_addresses;
    for (const auto& actor : actors) {
        SpellEffectPacketState captured{};
        if (!TryCaptureLocalSpellEffectState(actor, &captured)) {
            continue;
        }
        seen_addresses.insert(actor.actor_address);

        auto tracking_it =
            g_local_transport.local_spell_effects_by_address.find(actor.actor_address);
        if (tracking_it != g_local_transport.local_spell_effects_by_address.end() &&
            tracking_it->second.native_type_id != actor.object_type_id) {
            g_local_transport.local_spell_effects_by_address.erase(tracking_it);
            tracking_it = g_local_transport.local_spell_effects_by_address.end();
        }
        if (tracking_it == g_local_transport.local_spell_effects_by_address.end()) {
            LocalSpellEffectTracking tracking{};
            tracking.actor_address = actor.actor_address;
            tracking.effect_serial = g_local_transport.next_spell_effect_serial++;
            if (tracking.effect_serial == 0) {
                tracking.effect_serial = g_local_transport.next_spell_effect_serial++;
            }
            tracking.native_type_id = actor.object_type_id;
            if (actor.object_type_id != kFirewalkerTrailNativeTypeId &&
                g_local_transport.recent_local_cast_sequence != 0 &&
                now_ms - g_local_transport.recent_local_cast_ms <=
                    kRecentLocalCastAssociationWindowMs) {
                tracking.cast_sequence =
                    g_local_transport.recent_local_cast_sequence;
            }
            const auto ordinal_key =
                SpellEffectOrdinalKey(tracking.cast_sequence, tracking.native_type_id);
            tracking.effect_ordinal =
                g_local_transport.next_spell_effect_ordinal_by_cast_type[ordinal_key]++;
            tracking_it =
                g_local_transport.local_spell_effects_by_address
                    .emplace(actor.actor_address, tracking)
                    .first;
        }

        auto& tracking = tracking_it->second;
        tracking.last_seen_ms = now_ms;
        captured.effect_serial = tracking.effect_serial;
        captured.cast_sequence = tracking.cast_sequence;
        captured.effect_ordinal = tracking.effect_ordinal;
        tracking.last_state = captured;
        states->push_back(captured);
    }

    for (auto it = g_local_transport.local_spell_effects_by_address.begin();
         it != g_local_transport.local_spell_effects_by_address.end();) {
        if (seen_addresses.find(it->first) != seen_addresses.end()) {
            ++it;
            continue;
        }

        auto terminal = it->second;
        terminal.actor_address = 0;
        terminal.terminal_expires_ms = now_ms + kLocalSpellEffectTombstoneHoldMs;
        terminal.last_state.flags = static_cast<std::uint16_t>(
            (terminal.last_state.flags & ~SpellEffectStateFlagActive) |
            SpellEffectStateFlagTerminal);
        g_local_transport.local_spell_effect_tombstones.push_back(terminal);
        it = g_local_transport.local_spell_effects_by_address.erase(it);
    }

    g_local_transport.local_spell_effect_tombstones.erase(
        std::remove_if(
            g_local_transport.local_spell_effect_tombstones.begin(),
            g_local_transport.local_spell_effect_tombstones.end(),
            [&](const LocalSpellEffectTracking& tracking) {
                return tracking.terminal_expires_ms <= now_ms;
            }),
        g_local_transport.local_spell_effect_tombstones.end());
    for (const auto& terminal : g_local_transport.local_spell_effect_tombstones) {
        states->push_back(terminal.last_state);
    }

    std::sort(
        states->begin(),
        states->end(),
        [](const SpellEffectPacketState& left, const SpellEffectPacketState& right) {
            const auto priority = [](const SpellEffectPacketState& effect) {
                const bool active =
                    (effect.flags & SpellEffectStateFlagActive) != 0;
                if (!active) {
                    return 2;
                }
                return effect.native_type_id == kFirewalkerTrailNativeTypeId
                           ? 1
                           : 0;
            };
            const auto left_priority = priority(left);
            const auto right_priority = priority(right);
            if (left_priority != right_priority) {
                return left_priority < right_priority;
            }
            // Keep long-lived projectiles and child effects ahead of trail
            // churn. Within the bounded trail/tombstone partitions, the most
            // recent serials carry the current visual and teardown state.
            return left_priority == 0
                       ? left.effect_serial < right.effect_serial
                       : left.effect_serial > right.effect_serial;
        });
}

bool BuildLocalSpellEffectSnapshotPacket(
    std::uint64_t now_ms,
    SpellEffectSnapshotPacket* packet) {
    if (packet == nullptr) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) ||
        !scene_state.valid ||
        SceneIntentFromLocalScene().kind != ParticipantSceneIntentKind::Run) {
        g_local_transport.local_spell_effects_by_address.clear();
        g_local_transport.local_spell_effect_tombstones.clear();
        g_local_transport.next_spell_effect_ordinal_by_cast_type.clear();
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }
    std::vector<SDModNativeSpellEffectActorState> recent_effect_actors;
    if (TryListRecentNativeSpellEffectActors(&recent_effect_actors)) {
        for (const auto& recent : recent_effect_actors) {
            if (!recent.valid || recent.actor_address == 0) {
                continue;
            }
            const bool already_present = std::any_of(
                actors.begin(),
                actors.end(),
                [&](const SDModSceneActorState& actor) {
                    return actor.actor_address == recent.actor_address;
                });
            if (already_present) {
                continue;
            }
            SDModSceneActorState actor{};
            actor.valid = true;
            actor.actor_address = recent.actor_address;
            actor.object_type_id = recent.native_type_id;
            actor.actor_slot = recent.actor_slot;
            actor.x = recent.x;
            actor.y = recent.y;
            actor.radius = recent.radius;
            actors.push_back(actor);
        }
    }
    RefreshWorldSceneTracking(scene_state);

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    std::vector<SpellEffectPacketState> states;
    RefreshLocalSpellEffectTracking(actors, now_ms, &states);

    SpellEffectSnapshotPacket built{};
    built.header = MakePacketHeader(
        PacketKind::SpellEffectSnapshot,
        g_local_transport.next_sequence++);
    built.owner_participant_id = g_local_transport.local_peer_id;
    built.run_nonce = local->runtime.run_nonce;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.effect_total_count = static_cast<std::uint8_t>(
        (std::min<std::size_t>)(states.size(), 0xFFu));
    const auto packet_count = (std::min)(
        states.size(),
        static_cast<std::size_t>(kSpellEffectSnapshotMaxEffects));
    built.effect_count = static_cast<std::uint8_t>(packet_count);
    if (states.size() > packet_count) {
        built.snapshot_flags |= SpellEffectSnapshotFlagTruncated;
    }
    for (std::size_t index = 0; index < packet_count; ++index) {
        built.effects[index] = states[index];
    }

    *packet = built;
    return true;
}

void SendSpellEffectSnapshot(std::uint64_t now_ms) {
    if (now_ms - g_local_transport.last_spell_effect_snapshot_send_ms <
        kLocalTransportSpellEffectSnapshotIntervalMs) {
        return;
    }
    SpellEffectSnapshotPacket packet{};
    if (!BuildLocalSpellEffectSnapshotPacket(now_ms, &packet)) {
        return;
    }

    const auto wire_size =
        SpellEffectSnapshotPacketWireSize(packet.effect_count);
    const auto send_interval_ms = BandwidthLimitedSnapshotIntervalMs(
        wire_size,
        kLocalTransportSpellEffectSnapshotIntervalMs);
    if (now_ms - g_local_transport.last_spell_effect_snapshot_send_ms <
        send_interval_ms) {
        return;
    }
    g_local_transport.last_spell_effect_snapshot_send_ms = now_ms;

    const bool snapshot_has_effects = packet.effect_count != 0;
    if (!snapshot_has_effects &&
        !g_local_transport.spell_effect_snapshot_had_effects) {
        return;
    }
    g_local_transport.spell_effect_snapshot_had_effects =
        snapshot_has_effects;

    for (const auto& endpoint : BuildKnownSendEndpoints()) {
        SendBufferToEndpoint(
            &packet,
            wire_size,
            endpoint,
            SteamSendModeForPacket(packet));
    }
}

SpellEffectSnapshotRuntimeInfo BuildSpellEffectSnapshotRuntimeInfo(
    const SpellEffectSnapshotPacket& packet,
    std::uint64_t now_ms) {
    SpellEffectSnapshotRuntimeInfo snapshot{};
    snapshot.valid = true;
    snapshot.owner_participant_id = packet.owner_participant_id;
    snapshot.received_ms = now_ms;
    snapshot.sequence = packet.header.sequence;
    snapshot.run_nonce = packet.run_nonce;
    snapshot.scene_epoch = packet.scene_epoch;
    snapshot.effect_total_count = packet.effect_total_count;
    snapshot.truncated =
        (packet.snapshot_flags & SpellEffectSnapshotFlagTruncated) != 0;

    const auto effect_count = (std::min<std::uint32_t>)(
        packet.effect_count,
        kSpellEffectSnapshotMaxEffects);
    snapshot.effects.reserve(effect_count);
    for (std::uint32_t index = 0; index < effect_count; ++index) {
        const auto& packet_effect = packet.effects[index];
        if (packet_effect.effect_serial == 0 ||
            !IsReplicatedSpellEffectNativeType(packet_effect.native_type_id) ||
            !std::isfinite(packet_effect.position_x) ||
            !std::isfinite(packet_effect.position_y) ||
            !std::isfinite(packet_effect.radius) ||
            packet_effect.radius < 0.0f ||
            !std::isfinite(packet_effect.heading) ||
            !std::isfinite(packet_effect.motion_x) ||
            !std::isfinite(packet_effect.motion_y) ||
            !std::isfinite(packet_effect.ember_vertical_position) ||
            !std::isfinite(packet_effect.ember_vertical_velocity) ||
            !std::isfinite(packet_effect.ember_damage) ||
            !std::isfinite(packet_effect.ember_lifetime) ||
            !std::isfinite(packet_effect.ember_initial_lifetime) ||
            !std::isfinite(packet_effect.ember_animation_progress) ||
            !std::isfinite(packet_effect.firewalker_collision_scale) ||
            !std::isfinite(packet_effect.firewalker_phase) ||
            !std::isfinite(packet_effect.firewalker_phase_step) ||
            !std::isfinite(packet_effect.firewalker_lifetime) ||
            !std::isfinite(packet_effect.firewalker_fade) ||
            !std::isfinite(packet_effect.firewalker_direction) ||
            !std::isfinite(packet_effect.firewalker_visual_scale) ||
            !std::isfinite(packet_effect.firewalker_damage)) {
            continue;
        }

        SpellEffectSnapshot effect{};
        effect.effect_serial = packet_effect.effect_serial;
        effect.cast_sequence = packet_effect.cast_sequence;
        effect.native_type_id = packet_effect.native_type_id;
        effect.effect_ordinal = packet_effect.effect_ordinal;
        effect.active =
            (packet_effect.flags & SpellEffectStateFlagActive) != 0;
        effect.terminal =
            (packet_effect.flags & SpellEffectStateFlagTerminal) != 0;
        effect.transform_valid =
            (packet_effect.flags & SpellEffectStateFlagTransform) != 0;
        effect.motion_valid =
            (packet_effect.flags & SpellEffectStateFlagMotion) != 0;
        effect.ember_runtime_valid =
            (packet_effect.flags & SpellEffectStateFlagEmberRuntime) != 0 &&
            packet_effect.native_type_id == kFireEmberNativeTypeId;
        effect.firewalker_runtime_valid =
            (packet_effect.flags & SpellEffectStateFlagFirewalkerRuntime) != 0 &&
            packet_effect.native_type_id == kFirewalkerTrailNativeTypeId &&
            packet_effect.firewalker_lifetime > 0.0f;
        effect.position_x = packet_effect.position_x;
        effect.position_y = packet_effect.position_y;
        effect.radius = packet_effect.radius;
        effect.heading = packet_effect.heading;
        effect.motion_x = packet_effect.motion_x;
        effect.motion_y = packet_effect.motion_y;
        effect.ember_vertical_position = packet_effect.ember_vertical_position;
        effect.ember_vertical_velocity = packet_effect.ember_vertical_velocity;
        effect.ember_damage = packet_effect.ember_damage;
        effect.ember_lifetime = packet_effect.ember_lifetime;
        effect.ember_initial_lifetime = packet_effect.ember_initial_lifetime;
        effect.ember_animation_progress = packet_effect.ember_animation_progress;
        effect.ember_variant = packet_effect.ember_variant;
        effect.ember_frame_interval = packet_effect.ember_frame_interval;
        effect.ember_config_primary = packet_effect.ember_config_primary;
        effect.ember_config_secondary = packet_effect.ember_config_secondary;
        effect.ember_config_tertiary = packet_effect.ember_config_tertiary;
        effect.firewalker_collision_scale = packet_effect.firewalker_collision_scale;
        effect.firewalker_phase = packet_effect.firewalker_phase;
        effect.firewalker_phase_step = packet_effect.firewalker_phase_step;
        effect.firewalker_lifetime = packet_effect.firewalker_lifetime;
        effect.firewalker_fade = packet_effect.firewalker_fade;
        effect.firewalker_direction = packet_effect.firewalker_direction;
        effect.firewalker_visual_scale = packet_effect.firewalker_visual_scale;
        effect.firewalker_damage = packet_effect.firewalker_damage;
        effect.firewalker_source_slot = packet_effect.firewalker_source_slot;
        effect.firewalker_active = packet_effect.firewalker_active;
        effect.firewalker_variant = packet_effect.firewalker_variant;
        effect.firewalker_aux = packet_effect.firewalker_aux;
        effect.firewalker_damage_mask = packet_effect.firewalker_damage_mask;
        snapshot.effects.push_back(effect);
    }
    return snapshot;
}

void PublishSpellEffectSnapshotRuntimeInfo(
    const SpellEffectSnapshotPacket& packet,
    std::uint64_t now_ms) {
    auto snapshot = BuildSpellEffectSnapshotRuntimeInfo(packet, now_ms);
    UpdateRuntimeState([&](RuntimeState& state) {
        auto it = std::find_if(
            state.spell_effect_snapshots.begin(),
            state.spell_effect_snapshots.end(),
            [&](const SpellEffectSnapshotRuntimeInfo& existing) {
                return existing.owner_participant_id ==
                       snapshot.owner_participant_id;
            });
        if (it == state.spell_effect_snapshots.end()) {
            state.spell_effect_snapshots.push_back(std::move(snapshot));
        } else {
            *it = std::move(snapshot);
        }
    });
}

void ApplySpellEffectSnapshotPacket(
    const SpellEffectSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (packet.owner_participant_id == 0 ||
        packet.owner_participant_id == g_local_transport.local_peer_id ||
        packet.effect_count > kSpellEffectSnapshotMaxEffects) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* owner = FindParticipant(
        runtime_state,
        packet.owner_participant_id);
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
        g_local_transport
            .last_spell_effect_packet_sequence_by_participant[
                packet.owner_participant_id];
    if (last_sequence != 0 &&
        !IsPacketSequenceNewer(packet.header.sequence, last_sequence)) {
        return;
    }
    last_sequence = packet.header.sequence;

    UpsertPeerEndpoint(from, packet.owner_participant_id, now_ms);
    RelayPacketBufferToPeers(
        &packet,
        SpellEffectSnapshotPacketWireSize(packet.effect_count),
        from,
        SteamSendModeForPacket(packet));
    PublishSpellEffectSnapshotRuntimeInfo(packet, now_ms);
}
