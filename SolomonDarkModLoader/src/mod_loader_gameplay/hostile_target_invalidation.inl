bool CaptureLiveHostilesTargetingActor(
    uintptr_t target_actor_address,
    std::vector<uintptr_t>* hostile_actor_addresses) {
    if (target_actor_address == 0 || hostile_actor_addresses == nullptr) {
        return false;
    }
    hostile_actor_addresses->clear();

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    for (const auto& actor : actors) {
        if (!actor.tracked_enemy ||
            actor.actor_address == 0 ||
            actor.actor_address == target_actor_address ||
            actor.dead) {
            continue;
        }
        uintptr_t current_target_actor_address = 0;
        if (memory.TryReadField(
                actor.actor_address,
                kActorCurrentTargetActorOffset,
                &current_target_actor_address) &&
            current_target_actor_address == target_actor_address) {
            hostile_actor_addresses->push_back(actor.actor_address);
        }
    }
    return true;
}

bool IsParticipantRuntimeDeadForHostileTargeting(
    const multiplayer::ParticipantInfo& participant) {
    return participant.runtime.valid &&
           participant.runtime.in_run &&
           std::isfinite(participant.runtime.life_current) &&
           std::isfinite(participant.runtime.life_max) &&
           participant.runtime.life_max > 0.0f &&
           participant.runtime.life_current <= 0.0f;
}

bool IsCurrentGameplayLocalPlayerActor(uintptr_t actor_address) {
    uintptr_t gameplay_address = 0;
    uintptr_t local_actor_address = 0;
    return actor_address != 0 &&
           TryResolveCurrentGameplayScene(&gameplay_address) &&
           TryResolvePlayerActorForSlot(
               gameplay_address,
               0,
               &local_actor_address) &&
           local_actor_address == actor_address;
}

bool HasLocalPlayerNativeDeathTransitionStarted(
    uintptr_t actor_address) {
    if (!IsCurrentGameplayLocalPlayerActor(actor_address)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t ineligible_state = 0;
    return memory.TryReadField(
               actor_address,
               kActorHostileTargetIneligibleStateOffset,
               &ineligible_state) &&
           ineligible_state != 0;
}

bool IsHostileTargetReacquisitionDeferred(
    uintptr_t hostile_actor_address) {
    if (hostile_actor_address == 0) {
        return false;
    }
    const auto now_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    for (auto& [dead_actor_address, maintenance] :
         g_hostile_target_death_maintenance) {
        if (maintenance.hostile_actor_addresses.find(
                hostile_actor_address) ==
            maintenance.hostile_actor_addresses.end()) {
            continue;
        }
        if (maintenance.awaiting_local_native_death_transition &&
            (HasLocalPlayerNativeDeathTransitionStarted(
                 dead_actor_address) ||
             now_ms >= maintenance.local_death_fallback_at_ms)) {
            maintenance.awaiting_local_native_death_transition = false;
        }
        if (maintenance.awaiting_local_native_death_transition) {
            return true;
        }
    }
    return false;
}

void ScheduleHostileTargetReacquisitionAfterNativeDeathTransition(
    uintptr_t dead_actor_address,
    const std::vector<uintptr_t>& hostile_actor_addresses) {
    if (dead_actor_address == 0 ||
        hostile_actor_addresses.empty() ||
        multiplayer::IsLocalTransportClient()) {
        return;
    }

    const auto [iterator, inserted] =
        g_hostile_target_death_maintenance.try_emplace(
            dead_actor_address);
    auto& maintenance = iterator->second;
    if (inserted) {
        const auto now_ms =
            static_cast<std::uint64_t>(GetTickCount64());
        maintenance.expires_at_ms =
            now_ms +
            kHostileTargetDeathMaintenanceMaxMs;
        maintenance.awaiting_local_native_death_transition =
            IsCurrentGameplayLocalPlayerActor(dead_actor_address) &&
            !HasLocalPlayerNativeDeathTransitionStarted(
                dead_actor_address);
        maintenance.local_death_fallback_at_ms =
            now_ms + kHostileTargetLocalDeathFallbackMs;
    }
    maintenance.hostile_actor_addresses.insert(
        hostile_actor_addresses.begin(),
        hostile_actor_addresses.end());
}

bool DeferHostileTargetReacquisitionForLocalNativeDeath(
    uintptr_t hostile_actor_address,
    uintptr_t target_actor_address) {
    if (hostile_actor_address == 0 ||
        target_actor_address == 0 ||
        !IsCurrentGameplayLocalPlayerActor(target_actor_address) ||
        !IsActorRuntimeDead(target_actor_address) ||
        HasLocalPlayerNativeDeathTransitionStarted(
            target_actor_address)) {
        return false;
    }

    ScheduleHostileTargetReacquisitionAfterNativeDeathTransition(
        target_actor_address,
        std::vector<uintptr_t>{hostile_actor_address});
    return IsHostileTargetReacquisitionDeferred(
        hostile_actor_address);
}

void RefreshHostileTargetParticipantDeathLatches(
    const multiplayer::RuntimeState& runtime_state) {
    struct ParticipantActorDeathState {
        uintptr_t actor_address = 0;
        bool dead = false;
    };

    std::vector<ParticipantActorDeathState> actor_states;
    {
        std::lock_guard<std::recursive_mutex> lock(
            g_participant_entities_mutex);
        actor_states.reserve(g_participant_entities.size());
        for (const auto& binding : g_participant_entities) {
            if (!IsWizardParticipantKind(binding.kind) ||
                binding.actor_address == 0) {
                continue;
            }
            const auto* participant =
                multiplayer::FindParticipant(runtime_state, binding.bot_id);
            actor_states.push_back({
                binding.actor_address,
                binding.native_remote_death_epoch_active ||
                    (participant != nullptr &&
                     IsParticipantRuntimeDeadForHostileTargeting(
                         *participant)),
            });
        }
    }

    uintptr_t gameplay_address = 0;
    uintptr_t local_actor_address = 0;
    if (const auto* local_participant =
            multiplayer::FindLocalParticipant(runtime_state);
        local_participant != nullptr &&
        TryResolveCurrentGameplayScene(&gameplay_address) &&
        TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &local_actor_address) &&
        local_actor_address != 0) {
        actor_states.push_back({
            local_actor_address,
            IsParticipantRuntimeDeadForHostileTargeting(
                *local_participant),
        });
    }

    std::unordered_map<uintptr_t, bool> dead_by_actor_address;
    dead_by_actor_address.reserve(actor_states.size());
    for (const auto& state : actor_states) {
        dead_by_actor_address[state.actor_address] =
            dead_by_actor_address[state.actor_address] || state.dead;
    }

    std::unordered_set<uintptr_t> observed_actor_addresses;
    std::vector<uintptr_t> newly_dead_actor_addresses;
    observed_actor_addresses.reserve(dead_by_actor_address.size());
    for (const auto& [actor_address, dead] : dead_by_actor_address) {
        observed_actor_addresses.insert(actor_address);
        if (dead) {
            if (g_hostile_target_dead_participant_actors
                    .insert(actor_address)
                    .second) {
                newly_dead_actor_addresses.push_back(actor_address);
            }
        } else {
            g_hostile_target_dead_participant_actors.erase(
                actor_address);
            g_hostile_target_death_maintenance.erase(actor_address);
        }
    }
    for (auto iterator =
             g_hostile_target_dead_participant_actors.begin();
         iterator !=
             g_hostile_target_dead_participant_actors.end();) {
        if (observed_actor_addresses.find(*iterator) ==
            observed_actor_addresses.end()) {
            g_hostile_target_death_maintenance.erase(*iterator);
            iterator =
                g_hostile_target_dead_participant_actors.erase(iterator);
        } else {
            ++iterator;
        }
    }

    if (multiplayer::IsLocalTransportClient()) {
        return;
    }
    for (const auto dead_actor_address : newly_dead_actor_addresses) {
        std::vector<uintptr_t> hostile_actor_addresses;
        if (!CaptureLiveHostilesTargetingActor(
                dead_actor_address,
                &hostile_actor_addresses)) {
            continue;
        }
        ScheduleHostileTargetReacquisitionAfterNativeDeathTransition(
            dead_actor_address,
            hostile_actor_addresses);
        if (!hostile_actor_addresses.empty()) {
            Log(
                std::string("[hostile_ai] participant life-zero captured for native-transition-safe reacquisition") +
                ". dead_target=" + HexString(dead_actor_address) +
                " affected=" +
                    std::to_string(hostile_actor_addresses.size()));
        }
    }
}

void MaintainNearestValidHostileTargets(std::uint64_t now_ms) {
    if (multiplayer::IsLocalTransportClient() ||
        now_ms <
            g_hostile_target_nearest_maintenance_not_before_ms) {
        return;
    }
    g_hostile_target_nearest_maintenance_not_before_ms =
        now_ms + kHostileTargetNearestMaintenanceIntervalMs;

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return;
    }

    uintptr_t world_address = 0;
    std::vector<uintptr_t> hostile_actor_addresses;
    hostile_actor_addresses.reserve(actors.size());
    for (const auto& actor : actors) {
        if (!actor.valid ||
            !actor.tracked_enemy ||
            actor.actor_address == 0 ||
            actor.dead ||
            IsActorRuntimeDead(actor.actor_address)) {
            continue;
        }
        if (world_address == 0) {
            world_address = actor.owner_address;
        }
        hostile_actor_addresses.push_back(actor.actor_address);
    }
    if (world_address != 0) {
        ReplacePlayerOwnedHostileTargetSidecars(
            world_address,
            now_ms,
            actors);
    }

    for (const auto hostile_actor_address : hostile_actor_addresses) {
        if (IsHostileTargetReacquisitionDeferred(
                hostile_actor_address)) {
            continue;
        }
        (void)ReacquireHostileTargetAfterInvalidation(
            hostile_actor_address,
            0,
            "nearest_valid_maintenance");
    }
}

bool HostileTargetRequiresInvalidationRepair(
    uintptr_t hostile_actor_address,
    uintptr_t dead_actor_address) {
    uintptr_t current_target_actor_address = 0;
    if (!ProcessMemory::Instance().TryReadField(
            hostile_actor_address,
            kActorCurrentTargetActorOffset,
            &current_target_actor_address)) {
        return true;
    }
    if (current_target_actor_address == 0 ||
        current_target_actor_address == dead_actor_address ||
        IsActorRuntimeDead(current_target_actor_address) ||
        IsDeadWizardParticipantActor(current_target_actor_address)) {
        return true;
    }

    std::uint8_t ineligible_state = 0;
    return !ProcessMemory::Instance().TryReadField(
               current_target_actor_address,
               kActorHostileTargetIneligibleStateOffset,
               &ineligible_state) ||
           ineligible_state != 0;
}

void MaintainInvalidatedHostileTargetAfterNativeTick(
    uintptr_t hostile_actor_address) {
    if (hostile_actor_address == 0 ||
        multiplayer::IsLocalTransportClient() ||
        g_hostile_target_death_maintenance.empty()) {
        return;
    }

    const auto now_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    for (auto maintenance_iterator =
             g_hostile_target_death_maintenance.begin();
         maintenance_iterator !=
             g_hostile_target_death_maintenance.end();) {
        const auto dead_actor_address = maintenance_iterator->first;
        auto& maintenance = maintenance_iterator->second;
        const auto hostile_iterator =
            maintenance.hostile_actor_addresses.find(
                hostile_actor_address);
        if (hostile_iterator !=
            maintenance.hostile_actor_addresses.end()) {
            if (!IsActorRuntimeDead(hostile_actor_address) &&
                HostileTargetRequiresInvalidationRepair(
                    hostile_actor_address,
                    dead_actor_address)) {
                (void)ReacquireHostileTargetAfterInvalidation(
                    hostile_actor_address,
                    dead_actor_address,
                    "participant_death_maintenance");
            }
            if (IsActorRuntimeDead(hostile_actor_address) ||
                now_ms >= maintenance.expires_at_ms) {
                maintenance.hostile_actor_addresses.erase(
                    hostile_iterator);
            }
        }

        if (maintenance.hostile_actor_addresses.empty()) {
            maintenance_iterator =
                g_hostile_target_death_maintenance.erase(
                    maintenance_iterator);
        } else {
            ++maintenance_iterator;
        }
    }
}

void MaintainMissingOrInvalidHostileTargetAfterNativeTick(
    uintptr_t hostile_actor_address) {
    if (hostile_actor_address == 0 ||
        multiplayer::IsLocalTransportClient()) {
        return;
    }

    uintptr_t current_target_actor_address = 0;
    const bool have_current_target =
        ProcessMemory::Instance().TryReadField(
            hostile_actor_address,
            kActorCurrentTargetActorOffset,
            &current_target_actor_address);
    if (have_current_target &&
        !HostileTargetRequiresInvalidationRepair(
            hostile_actor_address,
            0)) {
        return;
    }

    (void)ReacquireHostileTargetAfterInvalidation(
        hostile_actor_address,
        have_current_target ? current_target_actor_address : 0,
        "native_chase_invalid_target");
}

void MaintainInvalidatedHostileTargetsAfterLocalPlayerTick() {
    if (multiplayer::IsLocalTransportClient() ||
        g_hostile_target_death_maintenance.empty()) {
        return;
    }

    const auto now_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    for (auto maintenance_iterator =
             g_hostile_target_death_maintenance.begin();
         maintenance_iterator !=
             g_hostile_target_death_maintenance.end();) {
        const auto dead_actor_address = maintenance_iterator->first;
        auto& maintenance = maintenance_iterator->second;
        for (auto hostile_iterator =
                 maintenance.hostile_actor_addresses.begin();
             hostile_iterator !=
                 maintenance.hostile_actor_addresses.end();) {
            if (IsActorRuntimeDead(*hostile_iterator)) {
                hostile_iterator =
                    maintenance.hostile_actor_addresses.erase(
                        hostile_iterator);
                continue;
            }
            if (HostileTargetRequiresInvalidationRepair(
                    *hostile_iterator,
                    dead_actor_address)) {
                (void)ReacquireHostileTargetAfterInvalidation(
                    *hostile_iterator,
                    dead_actor_address,
                    "participant_death_post_player_tick");
            }
            ++hostile_iterator;
        }

        if (maintenance.hostile_actor_addresses.empty() ||
            now_ms >= maintenance.expires_at_ms) {
            maintenance_iterator =
                g_hostile_target_death_maintenance.erase(
                    maintenance_iterator);
        } else {
            ++maintenance_iterator;
        }
    }
}
