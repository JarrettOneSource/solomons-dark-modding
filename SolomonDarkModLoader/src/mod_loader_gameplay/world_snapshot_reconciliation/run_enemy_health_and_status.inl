bool ApplyReplicatedRunEnemyTransientStatus(
    uintptr_t actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    if (actor_address == 0 ||
        !authoritative_actor.tracked_enemy ||
        !multiplayer::IsTurnUndeadEligibleRunEnemyType(
            authoritative_actor.native_type_id) ||
        (authoritative_actor.status_flags &
         multiplayer::WorldActorStatusFlagTurnUndeadStateValid) == 0 ||
        kActorTurnUndeadFleeHeadingOffset == 0 ||
        kActorTurnUndeadActivationScalarOffset == 0 ||
        kActorTurnUndeadDurationTicksOffset == 0 ||
        authoritative_actor.turn_undead_duration_ticks < 0 ||
        authoritative_actor.turn_undead_duration_ticks > 100000 ||
        !std::isfinite(authoritative_actor.turn_undead_flee_heading) ||
        std::abs(authoritative_actor.turn_undead_flee_heading) > 36000.0f ||
        !std::isfinite(authoritative_actor.turn_undead_activation_scalar) ||
        authoritative_actor.turn_undead_activation_scalar < 0.0f ||
        authoritative_actor.turn_undead_activation_scalar > 65536.0f) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool wrote = memory.TryWriteField(
        actor_address,
        kActorTurnUndeadActivationScalarOffset,
        authoritative_actor.turn_undead_activation_scalar);
    const bool active =
        (authoritative_actor.status_flags &
         multiplayer::WorldActorStatusFlagTurnUndeadActive) != 0;
    if (active) {
        const bool wrote_flee_heading = memory.TryWriteField(
            actor_address,
            kActorTurnUndeadFleeHeadingOffset,
            authoritative_actor.turn_undead_flee_heading);
        const bool wrote_duration = memory.TryWriteField(
            actor_address,
            kActorTurnUndeadDurationTicksOffset,
            authoritative_actor.turn_undead_duration_ticks);
        return wrote && wrote_flee_heading && wrote_duration;
    }

    std::int32_t local_duration_ticks = 0;
    if (memory.TryReadField(
            actor_address,
            kActorTurnUndeadDurationTicksOffset,
            &local_duration_ticks) &&
        local_duration_ticks > 0) {
        wrote = memory.TryWriteField<std::int32_t>(
            actor_address,
            kActorTurnUndeadDurationTicksOffset,
            0) || wrote;
    }
    return wrote;
}
bool ApplyReplicatedWorldActorTransform(
    uintptr_t actor_address,
    std::uint32_t local_native_type_id,
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    bool force_write) {
    if (actor_address == 0 ||
        !std::isfinite(authoritative_actor.position_x) ||
        !std::isfinite(authoritative_actor.position_y) ||
        !std::isfinite(authoritative_actor.heading)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    float current_x = 0.0f;
    float current_y = 0.0f;
    const bool have_current_position =
        TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &current_x) &&
        TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &current_y);
    const float dx = have_current_position ? authoritative_actor.position_x - current_x : 0.0f;
    const float dy = have_current_position ? authoritative_actor.position_y - current_y : 0.0f;
    const float position_error_squared = dx * dx + dy * dy;
    const bool position_changed =
        force_write ||
        !have_current_position ||
        position_error_squared > kWorldSnapshotSettleDistance * kWorldSnapshotSettleDistance;

    bool wrote_position = false;
    if (position_changed) {
        const bool soft_correct_live_run_enemy =
            !force_write &&
            have_current_position &&
            authoritative_actor.tracked_enemy &&
            !authoritative_actor.dead &&
            position_error_squared <
                kReplicatedRunEnemyHardSnapDistance * kReplicatedRunEnemyHardSnapDistance;
        const float corrected_x = soft_correct_live_run_enemy
            ? current_x + dx * kReplicatedRunEnemySoftCorrectionFactor
            : authoritative_actor.position_x;
        const float corrected_y = soft_correct_live_run_enemy
            ? current_y + dy * kReplicatedRunEnemySoftCorrectionFactor
            : authoritative_actor.position_y;
        wrote_position =
            memory.TryWriteField(actor_address, kActorPositionXOffset, corrected_x) &&
            memory.TryWriteField(actor_address, kActorPositionYOffset, corrected_y);
        if (wrote_position) {
            DWORD rebind_exception_code = 0;
            (void)TryRebindActorToOwnerWorld(actor_address, &rebind_exception_code);
        }
    }

    (void)memory.TryWriteField(actor_address, kActorHeadingOffset, authoritative_actor.heading);
    if (local_native_type_id != 0 &&
        local_native_type_id == authoritative_actor.native_type_id) {
        ApplyReplicatedWorldActorDriveState(actor_address, authoritative_actor.anim_drive_state);
    }
    return wrote_position;
}

bool TryCreateReplicatedSharedHubActor(
    uintptr_t world_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    uintptr_t* actor_address_out) {
    if (actor_address_out != nullptr) {
        *actor_address_out = 0;
    }
    if (world_address == 0 ||
        !IsReplicatedSharedHubLifecycleOwnedActorType(authoritative_actor.native_type_id) ||
        !std::isfinite(authoritative_actor.position_x) ||
        !std::isfinite(authoritative_actor.position_y)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory_address = memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address = memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    const auto register_address = memory.ResolveGameAddressOrZero(kActorWorldRegister);
    if (factory_address == 0 || factory_context_address == 0 || register_address == 0) {
        return false;
    }

    uintptr_t actor_address = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectFactorySafe(
            factory_address,
            factory_context_address,
            static_cast<int>(authoritative_actor.native_type_id),
            &actor_address,
            &exception_code) ||
        actor_address == 0) {
        Log(
            "world_snapshot: factory create failed. type=0x" +
            HexString(static_cast<uintptr_t>(authoritative_actor.native_type_id)) +
            " seh=" + HexString(exception_code));
        return false;
    }

    (void)memory.TryWriteField(actor_address, kActorPositionXOffset, authoritative_actor.position_x);
    (void)memory.TryWriteField(actor_address, kActorPositionYOffset, authoritative_actor.position_y);
    if (std::isfinite(authoritative_actor.heading)) {
        (void)memory.TryWriteField(actor_address, kActorHeadingOffset, authoritative_actor.heading);
    }

    exception_code = 0;
    if (!CallActorWorldRegisterSafe(
            register_address,
            world_address,
            0,
            actor_address,
            -1,
            0,
            &exception_code)) {
        const auto object_delete_address = memory.ResolveGameAddressOrZero(kObjectDelete);
        DWORD delete_exception_code = 0;
        if (object_delete_address != 0) {
            (void)CallObjectDeleteSafe(object_delete_address, actor_address, &delete_exception_code);
        }
        Log(
            "world_snapshot: actor register failed. type=0x" +
            HexString(static_cast<uintptr_t>(authoritative_actor.native_type_id)) +
            " actor=" + HexString(actor_address) +
            " seh=" + HexString(exception_code) +
            " delete_seh=" + HexString(delete_exception_code));
        return false;
    }

    (void)ApplyReplicatedWorldActorTransform(
        actor_address,
        authoritative_actor.native_type_id,
        authoritative_actor,
        true);
    Log(
        "world_snapshot: created replicated hub actor. type=0x" +
        HexString(static_cast<uintptr_t>(authoritative_actor.native_type_id)) +
        " actor=" + HexString(actor_address) +
        " network_actor_id=" + std::to_string(authoritative_actor.network_actor_id));
    if (actor_address_out != nullptr) {
        *actor_address_out = actor_address;
    }
    return true;
}

bool TryFindCreatedReplicatedSharedHubActor(
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    uintptr_t* actor_address_out) {
    if (actor_address_out != nullptr) {
        *actor_address_out = 0;
    }

    const auto it = g_replicated_created_hub_actors.find(authoritative_actor.network_actor_id);
    if (it == g_replicated_created_hub_actors.end()) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint32_t native_type_id = 0;
    if (it->second == 0 ||
        !memory.TryReadField(it->second, kGameObjectTypeIdOffset, &native_type_id) ||
        native_type_id != authoritative_actor.native_type_id) {
        g_replicated_created_hub_actors.erase(it);
        return false;
    }

    if (actor_address_out != nullptr) {
        *actor_address_out = it->second;
    }
    BindReplicatedSharedHubActor(authoritative_actor.network_actor_id, it->second);
    return true;
}

bool IsAuthoritativeRunTrackedEnemyDeadSnapshot(
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    if (!authoritative_actor.tracked_enemy ||
        !std::isfinite(authoritative_actor.hp) ||
        !std::isfinite(authoritative_actor.max_hp) ||
        authoritative_actor.max_hp <= 0.0f) {
        return false;
    }
    return authoritative_actor.dead ||
           authoritative_actor.hp <= kReplicatedRunEnemyDeathHpEpsilon;
}

bool IsRunEnemyNativeDeathHandled(uintptr_t actor_address) {
    if (actor_address == 0 || kEnemyDeathHandledOffset == 0) {
        return false;
    }

    std::uint8_t death_handled_byte = 0;
    return ProcessMemory::Instance().TryReadField(
               actor_address,
               kEnemyDeathHandledOffset,
               &death_handled_byte) &&
           death_handled_byte != 0;
}

bool IsReplicatedRunEnemyDeathPending(std::uint64_t network_actor_id, std::uint64_t now_ms) {
    const auto pending_it = g_replicated_run_pending_enemy_death_until_ms.find(network_actor_id);
    if (pending_it == g_replicated_run_pending_enemy_death_until_ms.end()) {
        return false;
    }
    if (now_ms < pending_it->second) {
        return true;
    }
    g_replicated_run_pending_enemy_death_until_ms.erase(pending_it);
    return false;
}

bool HasReplicatedRunEnemyDeathPresentationStarted(std::uint64_t network_actor_id) {
    return network_actor_id != 0 &&
           g_replicated_run_enemy_death_hold_started_ids.find(network_actor_id) !=
               g_replicated_run_enemy_death_hold_started_ids.end();
}

void HoldReplicatedRunEnemyDeath(std::uint64_t network_actor_id, std::uint64_t now_ms) {
    if (network_actor_id == 0) {
        return;
    }
    const auto hold_until_ms = now_ms + kReplicatedRunEnemyRemoteDeathHoldMs;
    const auto pending_it = g_replicated_run_pending_enemy_death_until_ms.find(network_actor_id);
    if (pending_it == g_replicated_run_pending_enemy_death_until_ms.end() ||
        pending_it->second < hold_until_ms) {
        g_replicated_run_pending_enemy_death_until_ms[network_actor_id] = hold_until_ms;
    }
}

void MarkReplicatedRunEnemyDeathPresentationStarted(std::uint64_t network_actor_id, std::uint64_t now_ms) {
    if (network_actor_id == 0) {
        return;
    }
    g_replicated_run_enemy_death_hold_started_ids.insert(network_actor_id);
    HoldReplicatedRunEnemyDeath(network_actor_id, now_ms);
}

void ClearReplicatedRunEnemyDeathPresentationState(std::uint64_t network_actor_id) {
    if (network_actor_id == 0) {
        return;
    }
    g_replicated_run_pending_enemy_death_until_ms.erase(network_actor_id);
    g_replicated_run_enemy_death_hold_started_ids.erase(network_actor_id);
}

bool TryBeginReplicatedRunEnemyDeathHold(std::uint64_t network_actor_id, std::uint64_t now_ms) {
    if (network_actor_id == 0 || HasReplicatedRunEnemyDeathPresentationStarted(network_actor_id)) {
        return false;
    }
    MarkReplicatedRunEnemyDeathPresentationStarted(network_actor_id, now_ms);
    return true;
}

bool ApplyReplicatedRunEnemyHealth(
    uintptr_t actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    std::uint64_t now_ms) {
    if (actor_address == 0 ||
        !authoritative_actor.tracked_enemy ||
        !std::isfinite(authoritative_actor.hp) ||
        !std::isfinite(authoritative_actor.max_hp) ||
        authoritative_actor.max_hp <= 0.0f) {
        return false;
    }

    ActorHealthRuntime local_health;
    if (!TryReadArenaEnemyActorHealth(actor_address, &local_health)) {
        return false;
    }

    const float authoritative_max_hp = authoritative_actor.max_hp;
    float authoritative_hp = (std::max)(0.0f, (std::min)(authoritative_actor.hp, authoritative_max_hp));
    if (authoritative_actor.dead) {
        authoritative_hp = 0.0f;
    }
    const bool authoritative_dead =
        authoritative_actor.dead || authoritative_hp <= kReplicatedRunEnemyDeathHpEpsilon;
    if (multiplayer::IsLocalTransportClient() &&
        !authoritative_dead &&
        (HasReplicatedRunEnemyDeathPresentationStarted(authoritative_actor.network_actor_id) ||
         multiplayer::HasLocalPendingLethalEnemyDamageClaim(authoritative_actor.network_actor_id, now_ms))) {
        return false;
    }
    const bool max_hp_changed = std::fabs(local_health.max_hp - authoritative_max_hp) > 0.01f;
    const bool max_hp_synced =
        std::fabs(local_health.max_hp - authoritative_max_hp) <= 0.05f;
    const bool death_handled = IsRunEnemyNativeDeathHandled(actor_address);
    if (authoritative_dead && death_handled) {
        MarkReplicatedRunEnemyDeathPresentationStarted(authoritative_actor.network_actor_id, now_ms);
    }
    const bool has_damage_baseline =
        multiplayer::HasReplicatedRunEnemyDamageBaseline(authoritative_actor.network_actor_id);
    if (multiplayer::IsLocalTransportClient() &&
        authoritative_actor.network_actor_id != 0 &&
        !authoritative_dead &&
        !has_damage_baseline &&
        max_hp_synced &&
        local_health.hp + 0.05f >= authoritative_hp) {
        multiplayer::MarkReplicatedRunEnemyDamageBaseline(
            authoritative_actor.network_actor_id,
            authoritative_hp);
    }
    const bool observed_local_damage =
        multiplayer::IsLocalTransportClient() &&
        authoritative_actor.network_actor_id != 0 &&
        !authoritative_dead &&
        has_damage_baseline &&
        max_hp_synced &&
        local_health.hp + kReplicatedRunEnemyDamageObservationEpsilon < authoritative_hp;
    // Every observed client-native damage sample must be followed by an
    // authoritative write. Otherwise a sub-centi-HP tick would remain local
    // for several snapshots and its cumulative value would be counted more
    // than once by the damage accumulator.
    const bool hp_changed =
        observed_local_damage ||
        std::fabs(local_health.hp - authoritative_hp) > 0.01f;
    if (!hp_changed && !max_hp_changed && (!authoritative_dead || death_handled)) {
        return false;
    }

    float claimed_target_x = authoritative_actor.position_x;
    float claimed_target_y = authoritative_actor.position_y;
    if (observed_local_damage) {
        // Preserve native hit reactions (notably Fortunate Flailing knockback)
        // before this snapshot rolls the client back to the host transform. The
        // host independently bounds this position against its authoritative
        // target before accepting either the damage or the transform.
        float local_target_x = authoritative_actor.position_x;
        float local_target_y = authoritative_actor.position_y;
        if (TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &local_target_x) &&
            TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &local_target_y)) {
            const float position_dx = local_target_x - authoritative_actor.position_x;
            const float position_dy = local_target_y - authoritative_actor.position_y;
            const float preserve_distance =
                kLocalEnemyDamageClaimPositionPreserveDistance;
            if (position_dx * position_dx + position_dy * position_dy <=
                preserve_distance * preserve_distance) {
                claimed_target_x = local_target_x;
                claimed_target_y = local_target_y;
            }
        }
    }

    auto& memory = ProcessMemory::Instance();
    bool wrote = true;
    if (max_hp_changed) {
        wrote = memory.TryWriteField(actor_address, kEnemyMaxHpOffset, authoritative_max_hp) && wrote;
    }
    if (hp_changed) {
        wrote = memory.TryWriteField(actor_address, kEnemyCurrentHpOffset, authoritative_hp) && wrote;
    }
    if (wrote &&
        multiplayer::IsLocalTransportClient() &&
        authoritative_actor.network_actor_id != 0) {
        if (authoritative_dead) {
            multiplayer::ClearReplicatedRunEnemyDamageBaseline(authoritative_actor.network_actor_id);
        } else {
            if (observed_local_damage) {
                if (local_health.hp + 0.05f < authoritative_hp) {
                    multiplayer::QueueLocalEnemyDamageClaim(
                        authoritative_actor.network_actor_id,
                        0,
                        authoritative_hp,
                        local_health.hp,
                        authoritative_max_hp,
                        claimed_target_x,
                        claimed_target_y,
                        true);
                } else {
                    multiplayer::ObserveReplicatedRunEnemyDamage(
                        authoritative_actor.network_actor_id,
                        authoritative_hp,
                        local_health.hp,
                        authoritative_max_hp,
                        claimed_target_x,
                        claimed_target_y,
                        true);
                }
            }
            multiplayer::MarkReplicatedRunEnemyDamageBaseline(
                authoritative_actor.network_actor_id,
                authoritative_hp);
        }
    }
    if (wrote && authoritative_dead && !death_handled) {
        std::uint32_t death_exception_code = 0;
        const bool death_called = sdmod::TryTriggerRunEnemyDeath(actor_address, &death_exception_code);
        ClearManualRunEnemyFreeze(actor_address);
        Log(
            "world_snapshot: triggered replicated run enemy death. actor=" +
            HexString(actor_address) +
            " network_actor_id=" + std::to_string(authoritative_actor.network_actor_id) +
            " hp=" + std::to_string(authoritative_hp) +
            " dead=" + std::to_string(authoritative_actor.dead ? 1 : 0) +
            " death_called=" + std::to_string(death_called ? 1 : 0) +
            " death_seh=" + HexString(static_cast<uintptr_t>(death_exception_code)));
        if (death_called && authoritative_actor.network_actor_id != 0) {
            MarkReplicatedRunEnemyDeathPresentationStarted(authoritative_actor.network_actor_id, now_ms);
        }
        if (death_called && multiplayer::IsLocalTransportClient()) {
            SuppressClientLocalLootActors("client_replicated_enemy_death_snapshot");
        }
        wrote = death_called || wrote;
    }
    return wrote;
}
