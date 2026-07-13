struct ReplicatedSpellEffectBinding {
    std::uint64_t owner_participant_id = 0;
    std::uint32_t effect_serial = 0;
    std::uint32_t cast_sequence = 0;
    std::uint32_t native_type_id = 0;
    std::uint16_t effect_ordinal = 0;
    uintptr_t actor_address = 0;
};

std::unordered_map<
    std::uint64_t,
    std::unordered_map<std::uint32_t, ReplicatedSpellEffectBinding>>
    g_replicated_spell_effect_bindings;
std::unordered_map<std::uint64_t, std::unordered_set<std::uint32_t>>
    g_observed_replicated_spell_effect_serials;

constexpr std::uint64_t kReplicatedSpellEffectSnapshotFreshMs = 500;
constexpr float kReplicatedSpellEffectBindingMaxDistance = 1024.0f;
constexpr std::uint32_t kReplicatedFireEmberNativeTypeId = 0x07D6;
constexpr std::uint32_t kReplicatedFirewalkerTrailNativeTypeId = 0x07EE;

#include "spell_effect_materialization.inl"

void ClearReplicatedSpellEffectBindings() {
    g_replicated_spell_effect_bindings.clear();
    g_observed_replicated_spell_effect_serials.clear();
    ClearPendingReplicatedSpellEffectMaterialization();
    multiplayer::UpdateRuntimeState([](multiplayer::RuntimeState& state) {
        state.spell_effect_apply = multiplayer::SpellEffectApplyRuntimeInfo{};
    });
}

const SDModSceneActorState* FindSpellEffectSceneActor(
    const std::vector<SDModSceneActorState>& actors,
    uintptr_t actor_address,
    std::uint32_t native_type_id) {
    const auto it = std::find_if(
        actors.begin(),
        actors.end(),
        [&](const SDModSceneActorState& actor) {
            return actor.actor_address == actor_address &&
                   actor.object_type_id == native_type_id;
        });
    return it == actors.end() ? nullptr : &*it;
}

bool TryApplyReplicatedSpellEffectState(
    uintptr_t actor_address,
    int owner_gameplay_slot,
    const multiplayer::SpellEffectSnapshot& effect,
    multiplayer::SpellEffectApplyRuntimeInfo* apply_info) {
    if (actor_address == 0 || apply_info == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool wrote_any = false;
    if (effect.transform_valid) {
        const bool wrote_transform =
            memory.TryWriteField(
                actor_address,
                kActorPositionXOffset,
                effect.position_x) &&
            memory.TryWriteField(
                actor_address,
                kActorPositionYOffset,
                effect.position_y) &&
            memory.TryWriteField(
                actor_address,
                kActorCollisionRadiusOffset,
                effect.radius) &&
            memory.TryWriteField(
                actor_address,
                kActorHeadingOffset,
                effect.heading);
        if (wrote_transform) {
            apply_info->transform_write_count += 1;
            wrote_any = true;
        }
    }

    if (effect.motion_valid) {
        const bool wrote_motion =
            memory.TryWriteField(
                actor_address,
                kSpellEffectMotionXOffset,
                effect.motion_x) &&
            memory.TryWriteField(
                actor_address,
                kSpellEffectMotionYOffset,
                effect.motion_y);
        if (wrote_motion) {
            apply_info->motion_write_count += 1;
            wrote_any = true;
        }
    }

    if (TryWriteReplicatedEmberRuntime(actor_address, effect)) {
        apply_info->ember_runtime_write_count += 1;
        wrote_any = true;
    }

    if (TryWriteReplicatedFirewalkerRuntime(
            actor_address,
            owner_gameplay_slot,
            effect)) {
        apply_info->firewalker_runtime_write_count += 1;
        wrote_any = true;
    }

    if (effect.terminal) {
        std::size_t lifetime_offset = 0;
        if (effect.native_type_id == kReplicatedFireEmberNativeTypeId) {
            lifetime_offset = kEmberLifetimeOffset;
        } else if (effect.native_type_id ==
                   kReplicatedFirewalkerTrailNativeTypeId) {
            lifetime_offset = kFirewalkerLifetimeOffset;
        }
        if (lifetime_offset != 0 &&
            memory.TryWriteField<float>(
                actor_address,
                lifetime_offset,
                0.0f)) {
            apply_info->terminal_write_count += 1;
            wrote_any = true;
        }
    }
    return wrote_any;
}

uintptr_t MatchReplicatedSpellEffectActor(
    const std::vector<SDModSceneActorState>& actors,
    const std::unordered_set<uintptr_t>& bound_actor_addresses,
    int owner_gameplay_slot,
    const multiplayer::SpellEffectSnapshot& effect) {
    uintptr_t best_actor_address = 0;
    float best_distance_sq =
        kReplicatedSpellEffectBindingMaxDistance *
        kReplicatedSpellEffectBindingMaxDistance;
    for (const auto& actor : actors) {
        if (actor.actor_address == 0 ||
            actor.object_type_id != effect.native_type_id ||
            // Native child spell objects inherit the owning player's gameplay
            // slot as their actor-group tag. A materialized remote wizard's own
            // actor_slot is independent and is not a stable ownership key.
            actor.actor_slot != owner_gameplay_slot ||
            bound_actor_addresses.find(actor.actor_address) !=
                bound_actor_addresses.end()) {
            continue;
        }
        const auto dx = actor.x - effect.position_x;
        const auto dy = actor.y - effect.position_y;
        const auto distance_sq = dx * dx + dy * dy;
        if (!std::isfinite(distance_sq) || distance_sq > best_distance_sq) {
            continue;
        }
        best_distance_sq = distance_sq;
        best_actor_address = actor.actor_address;
    }
    return best_actor_address;
}

void ApplyReplicatedSpellEffectSnapshotsIfActive(std::uint64_t now_ms) {
    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) ||
        !scene_state.valid ||
        scene_state.kind != "arena") {
        if (!g_replicated_spell_effect_bindings.empty() ||
            HasPendingReplicatedSpellEffectMaterialization()) {
            ClearReplicatedSpellEffectBindings();
        }
        return;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return;
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

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    multiplayer::SpellEffectApplyRuntimeInfo apply_info{};
    apply_info.valid = true;
    apply_info.applied_ms = now_ms;

    std::unordered_set<uintptr_t> bound_actor_addresses;
    for (auto owner_it = g_replicated_spell_effect_bindings.begin();
         owner_it != g_replicated_spell_effect_bindings.end();) {
        for (auto binding_it = owner_it->second.begin();
             binding_it != owner_it->second.end();) {
            const auto& binding = binding_it->second;
            if (FindSpellEffectSceneActor(
                    actors,
                    binding.actor_address,
                    binding.native_type_id) == nullptr) {
                binding_it = owner_it->second.erase(binding_it);
                continue;
            }
            bound_actor_addresses.insert(binding.actor_address);
            ++binding_it;
        }
        if (owner_it->second.empty()) {
            owner_it = g_replicated_spell_effect_bindings.erase(owner_it);
        } else {
            ++owner_it;
        }
    }

    for (const auto& snapshot : runtime_state.spell_effect_snapshots) {
        if (!snapshot.valid ||
            snapshot.owner_participant_id == 0 ||
            snapshot.owner_participant_id ==
                multiplayer::GetLocalTransportParticipantId() ||
            now_ms < snapshot.received_ms ||
            now_ms - snapshot.received_ms >
                kReplicatedSpellEffectSnapshotFreshMs) {
            continue;
        }

        const auto* owner = multiplayer::FindParticipant(
            runtime_state,
            snapshot.owner_participant_id);
        if (owner == nullptr ||
            !owner->runtime.valid ||
            !owner->runtime.in_run ||
            (owner->runtime.run_nonce != 0 &&
             snapshot.run_nonce != 0 &&
             owner->runtime.run_nonce != snapshot.run_nonce)) {
            continue;
        }

        SDModParticipantGameplayState owner_gameplay{};
        if (!TryRefreshParticipantGameplayState(
                snapshot.owner_participant_id,
                &owner_gameplay) ||
            !owner_gameplay.entity_materialized ||
            owner_gameplay.gameplay_slot < kFirstWizardBotSlot ||
            owner_gameplay.gameplay_slot >=
                static_cast<int>(kGameplayPlayerSlotCount)) {
            continue;
        }

        apply_info.snapshot_count += 1;
        auto& owner_bindings =
            g_replicated_spell_effect_bindings[
                snapshot.owner_participant_id];
        auto& observed_serials =
            g_observed_replicated_spell_effect_serials[
                snapshot.owner_participant_id];
        for (const auto& effect : snapshot.effects) {
            apply_info.effect_count += 1;
            if (effect.terminal) {
                apply_info.terminal_effect_count += 1;
            }
            auto binding_it = owner_bindings.find(effect.effect_serial);
            if (binding_it == owner_bindings.end() &&
                observed_serials.find(effect.effect_serial) ==
                    observed_serials.end() &&
                (effect.active || effect.terminal)) {
                auto matched_actor_address =
                    MatchReplicatedSpellEffectActor(
                        actors,
                        bound_actor_addresses,
                        owner_gameplay.gameplay_slot,
                        effect);
                const bool should_materialize =
                    matched_actor_address == 0 &&
                    ShouldMaterializeMissingReplicatedSpellEffect(
                        snapshot.owner_participant_id,
                        effect,
                        now_ms);
                if (should_materialize &&
                    TryCreateReplicatedSpellEffect(
                        scene_state.world_address,
                        owner_gameplay.gameplay_slot,
                        effect,
                        &matched_actor_address)) {
                    SDModSceneActorState created_actor{};
                    created_actor.valid = true;
                    created_actor.actor_address = matched_actor_address;
                    created_actor.object_type_id = effect.native_type_id;
                    created_actor.actor_slot = owner_gameplay.gameplay_slot;
                    created_actor.x = effect.position_x;
                    created_actor.y = effect.position_y;
                    created_actor.radius = effect.radius;
                    actors.push_back(created_actor);
                    if (effect.native_type_id ==
                        kReplicatedFireEmberNativeTypeId) {
                        apply_info.created_ember_effect_count += 1;
                    } else if (effect.native_type_id ==
                               kReplicatedFirewalkerTrailNativeTypeId) {
                        apply_info.created_firewalker_effect_count += 1;
                    }
                }
                if (matched_actor_address != 0) {
                    observed_serials.insert(effect.effect_serial);
                    ForgetPendingReplicatedSpellEffectMaterialization(
                        snapshot.owner_participant_id,
                        effect.effect_serial);
                    ReplicatedSpellEffectBinding binding{};
                    binding.owner_participant_id =
                        snapshot.owner_participant_id;
                    binding.effect_serial = effect.effect_serial;
                    binding.cast_sequence = effect.cast_sequence;
                    binding.native_type_id = effect.native_type_id;
                    binding.effect_ordinal = effect.effect_ordinal;
                    binding.actor_address = matched_actor_address;
                    binding_it = owner_bindings
                        .emplace(effect.effect_serial, binding)
                        .first;
                    bound_actor_addresses.insert(matched_actor_address);
                }
            }
            if (effect.terminal) {
                ForgetPendingReplicatedSpellEffectMaterialization(
                    snapshot.owner_participant_id,
                    effect.effect_serial);
            }

            multiplayer::SpellEffectBindingRuntimeInfo binding_info{};
            binding_info.owner_participant_id =
                snapshot.owner_participant_id;
            binding_info.owner_gameplay_slot =
                owner_gameplay.gameplay_slot;
            binding_info.owner_actor_slot =
                owner_gameplay.actor_slot;
            binding_info.effect_serial = effect.effect_serial;
            binding_info.cast_sequence = effect.cast_sequence;
            binding_info.native_type_id = effect.native_type_id;
            binding_info.effect_ordinal = effect.effect_ordinal;
            binding_info.active = effect.active;
            binding_info.terminal = effect.terminal;
            binding_info.authoritative_x = effect.position_x;
            binding_info.authoritative_y = effect.position_y;

            if (binding_it != owner_bindings.end()) {
                const auto actor_address = binding_it->second.actor_address;
                binding_info.local_actor_address = actor_address;
                std::int8_t local_actor_slot = -1;
                if (ProcessMemory::Instance().TryReadField(
                        actor_address,
                        kActorSlotOffset,
                        &local_actor_slot)) {
                    binding_info.local_actor_slot =
                        static_cast<std::int32_t>(local_actor_slot);
                }
                std::int8_t local_firewalker_source_slot = -1;
                if (effect.native_type_id ==
                        kReplicatedFirewalkerTrailNativeTypeId &&
                    ProcessMemory::Instance().TryReadField(
                        actor_address,
                        kFirewalkerSourceSlotOffset,
                        &local_firewalker_source_slot)) {
                    binding_info.local_firewalker_source_slot =
                        static_cast<std::int32_t>(
                            local_firewalker_source_slot);
                }
                binding_info.matched = true;
                apply_info.matched_effect_count += 1;
                if (effect.native_type_id ==
                    kReplicatedFireEmberNativeTypeId) {
                    apply_info.matched_ember_effect_count += 1;
                }
                if (effect.native_type_id ==
                    kReplicatedFirewalkerTrailNativeTypeId) {
                    apply_info.matched_firewalker_effect_count += 1;
                }
                (void)TryApplyReplicatedSpellEffectState(
                    actor_address,
                    owner_gameplay.gameplay_slot,
                    effect,
                    &apply_info);
                float local_x = effect.position_x;
                float local_y = effect.position_y;
                (void)ProcessMemory::Instance().TryReadField(
                    actor_address,
                    kActorPositionXOffset,
                    &local_x);
                (void)ProcessMemory::Instance().TryReadField(
                    actor_address,
                    kActorPositionYOffset,
                    &local_y);
                binding_info.local_x = local_x;
                binding_info.local_y = local_y;
                const auto dx = local_x - effect.position_x;
                const auto dy = local_y - effect.position_y;
                binding_info.position_error =
                    std::sqrt(dx * dx + dy * dy);
            }
            apply_info.bindings.push_back(binding_info);
        }
    }

    multiplayer::UpdateRuntimeState(
        [&](multiplayer::RuntimeState& state) {
            const auto& previous = state.spell_effect_apply;
            apply_info.reconcile_revision =
                previous.reconcile_revision + 1;
            apply_info.max_matched_effect_count = (std::max)(
                previous.max_matched_effect_count,
                apply_info.matched_effect_count);
            apply_info.max_matched_ember_effect_count = (std::max)(
                previous.max_matched_ember_effect_count,
                apply_info.matched_ember_effect_count);
            apply_info.max_matched_firewalker_effect_count = (std::max)(
                previous.max_matched_firewalker_effect_count,
                apply_info.matched_firewalker_effect_count);
            apply_info.cumulative_transform_write_count =
                previous.cumulative_transform_write_count +
                apply_info.transform_write_count;
            apply_info.cumulative_motion_write_count =
                previous.cumulative_motion_write_count +
                apply_info.motion_write_count;
            apply_info.cumulative_ember_runtime_write_count =
                previous.cumulative_ember_runtime_write_count +
                apply_info.ember_runtime_write_count;
            apply_info.cumulative_ember_create_count =
                previous.cumulative_ember_create_count +
                apply_info.created_ember_effect_count;
            apply_info.cumulative_firewalker_create_count =
                previous.cumulative_firewalker_create_count +
                apply_info.created_firewalker_effect_count;
            apply_info.cumulative_firewalker_runtime_write_count =
                previous.cumulative_firewalker_runtime_write_count +
                apply_info.firewalker_runtime_write_count;
            apply_info.cumulative_terminal_write_count =
                previous.cumulative_terminal_write_count +
                apply_info.terminal_write_count;
            state.spell_effect_apply = std::move(apply_info);
        });
}
