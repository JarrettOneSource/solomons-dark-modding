struct WizardRespawnTarget {
    uintptr_t actor_address = 0;
    uintptr_t progression_address = 0;
    float current_hp = 0.0f;
    float max_hp = 0.0f;
    float max_mp = 0.0f;
};

bool TryBuildWizardRespawnTarget(
    uintptr_t actor_address,
    WizardRespawnTarget* target,
    std::string* error_message) {
    if (target == nullptr || actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "A live wizard actor is required.";
        }
        return false;
    }

    uintptr_t progression_address = 0;
    float current_hp = 0.0f;
    float max_hp = 0.0f;
    float max_mp = 0.0f;
    uintptr_t world_address = 0;
    auto& memory = ProcessMemory::Instance();
    if (!TryResolveActorProgressionRuntime(
            actor_address,
            &progression_address) ||
        progression_address == 0 ||
        !memory.TryReadField(
            actor_address,
            kActorOwnerOffset,
            &world_address) ||
        world_address == 0 ||
        !TryReadFiniteFloatField(
            progression_address,
            kProgressionHpOffset,
            &current_hp) ||
        !TryReadFiniteFloatField(
            progression_address,
            kProgressionMaxHpOffset,
            &max_hp) ||
        !TryReadFiniteFloatField(
            progression_address,
            kProgressionMaxMpOffset,
            &max_mp) ||
        !std::isfinite(max_hp) ||
        !std::isfinite(max_mp) ||
        max_hp <= 0.0f ||
        max_mp <= 0.0f) {
        if (error_message != nullptr) {
            *error_message =
                "The wizard actor has no live world/progression "
                "respawn target.";
        }
        return false;
    }

    *target = WizardRespawnTarget{
        actor_address,
        progression_address,
        current_hp,
        max_hp,
        max_mp,
    };
    return true;
}

bool TryRespawnWizardActorAt(
    const WizardRespawnTarget& target,
    float world_x,
    float world_y,
    bool* did_respawn,
    std::string* error_message) {
    if (did_respawn != nullptr) {
        *did_respawn = false;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    constexpr float kMaximumRespawnCoordinateMagnitude =
        1000000.0f;
    if (target.actor_address == 0 ||
        target.progression_address == 0 ||
        !std::isfinite(target.current_hp) ||
        !std::isfinite(target.max_hp) ||
        !std::isfinite(target.max_mp) ||
        target.max_hp <= 0.0f ||
        target.max_mp <= 0.0f ||
        !std::isfinite(world_x) ||
        !std::isfinite(world_y) ||
        std::abs(world_x) >
            kMaximumRespawnCoordinateMagnitude ||
        std::abs(world_y) >
            kMaximumRespawnCoordinateMagnitude ||
        kProgressionHpOffset == 0 ||
        kProgressionMpOffset == 0 ||
        kActorPositionXOffset == 0 ||
        kActorPositionYOffset == 0 ||
        kActorAnimationDriveStateByteOffset == 0 ||
        kActorAnimationMoveDurationTicksOffset == 0 ||
        kActorTerminalDispatchPendingOffset == 0 ||
        kActorTerminalDispatchCountdownOffset == 0 ||
        kActorGridCellPtrOffset == 0 ||
        kActorGridMemberFlagOffset == 0 ||
        kActorRenderSortBiasOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "Wizard respawn target is invalid.";
        }
        return false;
    }

    uintptr_t resolved_progression_address = 0;
    if (!TryResolveActorProgressionRuntime(
            target.actor_address,
            &resolved_progression_address) ||
        resolved_progression_address !=
            target.progression_address) {
        if (error_message != nullptr) {
            *error_message =
                "Wizard progression changed before respawn.";
        }
        return false;
    }

    float current_hp = 0.0f;
    if (!TryReadFiniteFloatField(
            target.progression_address,
            kProgressionHpOffset,
            &current_hp)) {
        if (error_message != nullptr) {
            *error_message =
                "Wizard HP could not be read immediately before respawn.";
        }
        return false;
    }
    if (current_hp > 0.0f) {
        Log(
            "Wave respawn left living participant untouched. actor=" +
            HexString(target.actor_address) +
            " hp=" + std::to_string(current_hp));
        return true;
    }

    std::string cast_error;
    if (!ClearWizardActorGameplayCastState(
            target.actor_address,
            &cast_error)) {
        if (error_message != nullptr) {
            *error_message =
                "The wizard cast state could not be cleared: " +
                cast_error;
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const bool wrote =
        memory.TryWriteField(
            target.progression_address,
            kProgressionHpOffset,
            target.max_hp) &&
        memory.TryWriteField(
            target.progression_address,
            kProgressionMpOffset,
            target.max_mp) &&
        memory.TryWriteField(
            target.actor_address,
            kActorPositionXOffset,
            world_x) &&
        memory.TryWriteField(
            target.actor_address,
            kActorPositionYOffset,
            world_y) &&
        memory.TryWriteField<float>(
            target.actor_address,
            kActorAnimationConfigBlockOffset,
            0.0f) &&
        memory.TryWriteField<float>(
            target.actor_address,
            kActorAnimationDriveParameterOffset,
            0.0f) &&
        memory.TryWriteField<std::uint8_t>(
            target.actor_address,
            kActorTerminalDispatchPendingOffset,
            0) &&
        memory.TryWriteField<std::int32_t>(
            target.actor_address,
            kActorTerminalDispatchCountdownOffset,
            0) &&
        memory.TryWriteField<std::int32_t>(
            target.actor_address,
            kActorAnimationMoveDurationTicksOffset,
            0);
    if (!wrote) {
        if (error_message != nullptr) {
            *error_message =
                "One or more native respawn fields could not be "
                "written.";
        }
        return false;
    }

    ClearLiveWizardActorAnimationDriveState(
        target.actor_address);
    if (!RestoreWizardActorAliveRegistrationState(
            target.actor_address)) {
        if (error_message != nullptr) {
            *error_message =
                "The native corpse registration fields could not "
                "be restored.";
        }
        return false;
    }
    std::string rebind_error;
    if (!RebindSceneActorCell(
            target.actor_address,
            &rebind_error)) {
        if (error_message != nullptr) {
            *error_message =
                "The respawn position could not be rebound to the "
                "world grid: " +
                rebind_error;
        }
        return false;
    }

    float verified_hp = 0.0f;
    float verified_mp = 0.0f;
    float verified_x = 0.0f;
    float verified_y = 0.0f;
    std::uint8_t verified_anim_drive_state = 1;
    std::uint8_t verified_terminal_pending = 1;
    std::uint8_t verified_grid_member = 0;
    std::int32_t verified_terminal_countdown = -1;
    std::int32_t verified_death_presentation_ticks = -1;
    uintptr_t verified_grid_cell = 0;
    float verified_render_sort_bias =
        (std::numeric_limits<float>::quiet_NaN)();
    constexpr float kRespawnReadbackTolerance = 0.05f;
    if (!TryReadFiniteFloatField(
            target.progression_address,
            kProgressionHpOffset,
            &verified_hp) ||
        !TryReadFiniteFloatField(
            target.progression_address,
            kProgressionMpOffset,
            &verified_mp) ||
        !TryReadFiniteFloatField(
            target.actor_address,
            kActorPositionXOffset,
            &verified_x) ||
        !TryReadFiniteFloatField(
            target.actor_address,
            kActorPositionYOffset,
            &verified_y) ||
        !memory.TryReadField(
            target.actor_address,
            kActorAnimationDriveStateByteOffset,
            &verified_anim_drive_state) ||
        !memory.TryReadField(
            target.actor_address,
            kActorTerminalDispatchPendingOffset,
            &verified_terminal_pending) ||
        !memory.TryReadField(
            target.actor_address,
            kActorTerminalDispatchCountdownOffset,
            &verified_terminal_countdown) ||
        !memory.TryReadField(
            target.actor_address,
            kActorAnimationMoveDurationTicksOffset,
            &verified_death_presentation_ticks) ||
        !memory.TryReadField(
            target.actor_address,
            kActorGridCellPtrOffset,
            &verified_grid_cell) ||
        !memory.TryReadField(
            target.actor_address,
            kActorGridMemberFlagOffset,
            &verified_grid_member) ||
        !memory.TryReadField(
            target.actor_address,
            kActorRenderSortBiasOffset,
            &verified_render_sort_bias) ||
        std::abs(verified_hp - target.max_hp) >
            kRespawnReadbackTolerance ||
        std::abs(verified_mp - target.max_mp) >
            kRespawnReadbackTolerance ||
        std::abs(verified_x - world_x) >
            kRespawnReadbackTolerance ||
        std::abs(verified_y - world_y) >
            kRespawnReadbackTolerance ||
        verified_anim_drive_state != 0 ||
        verified_terminal_pending != 0 ||
        verified_terminal_countdown != 0 ||
        verified_death_presentation_ticks != 0 ||
        verified_grid_cell == 0 ||
        verified_grid_member != 1 ||
        verified_render_sort_bias != 0.0f) {
        if (error_message != nullptr) {
            *error_message =
                "Native respawn fields did not converge after "
                "writeback.";
        }
        return false;
    }

    Log(
        "Respawned wizard through native same-actor contract. "
        "actor=" +
        HexString(target.actor_address) +
        " progression=" +
        HexString(target.progression_address) +
        " position=(" + std::to_string(world_x) + "," +
        std::to_string(world_y) + ")" +
        " grid_cell=" + HexString(verified_grid_cell) +
        " hp=" + std::to_string(verified_hp) +
        " mp=" + std::to_string(verified_mp));
    if (did_respawn != nullptr) {
        *did_respawn = true;
    }
    return true;
}

void QuiesceLocalPlayerRespawnInput() {
    g_gameplay_keyboard_injection.pending_movement_x.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_y.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_x.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_y.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection
        .local_movement_intent_observed_ms.store(
            0,
            std::memory_order_release);
}

bool TryRespawnLocalPlayerAt(
    float world_x,
    float world_y,
    bool* did_respawn,
    std::string* error_message) {
    if (did_respawn != nullptr) {
        *did_respawn = false;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    SDModPlayerState player;
    if (!TryGetPlayerState(&player) ||
        !player.valid ||
        player.actor_address == 0 ||
        player.world_address == 0 ||
        player.progression_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "A live local run player with valid progression is "
                "required.";
        }
        return false;
    }

    const WizardRespawnTarget target{
        player.actor_address,
        player.progression_address,
        player.hp,
        player.max_hp,
        player.max_mp,
    };
    bool respawned = false;
    if (!TryRespawnWizardActorAt(
            target,
            world_x,
            world_y,
            &respawned,
            error_message)) {
        return false;
    }
    if (!respawned) {
        Log(
            "Wave respawn acknowledged for living local participant "
            "without mutation. actor=" +
            HexString(player.actor_address) +
            " hp=" + std::to_string(player.hp));
        return true;
    }

    ClearQueuedGameplayMouseLeft();
    ClearQueuedGameplayMouseRight();
    QuiesceLocalPlayerRespawnInput();

    Log(
        "Respawned local multiplayer player. actor=" +
        HexString(player.actor_address) +
        " position=(" + std::to_string(world_x) + "," +
        std::to_string(world_y) + ")");
    if (did_respawn != nullptr) {
        *did_respawn = true;
    }
    return true;
}

bool TryRespawnHostOwnedSyntheticParticipantsAt(
    std::uint32_t respawn_epoch,
    std::int32_t wave,
    std::uint32_t run_nonce,
    float world_x,
    float world_y,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!multiplayer::IsLocalTransportHost() ||
        respawn_epoch == 0 ||
        wave <= 0 ||
        run_nonce == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Host authority and a valid wave respawn epoch are "
                "required.";
        }
        return false;
    }

    const auto runtime_state =
        multiplayer::SnapshotRuntimeState();
    std::lock_guard<std::recursive_mutex> lock(
        g_participant_entities_mutex);
    for (auto& binding : g_participant_entities) {
        const auto* participant =
            multiplayer::FindParticipant(
                runtime_state,
                binding.bot_id);
        if (binding.bot_id == 0 ||
            binding.controller_kind !=
                multiplayer::ParticipantControllerKind::LuaBrain ||
            !IsWizardParticipantKind(binding.kind) ||
            binding.actor_address == 0 ||
            binding.scene_intent.kind !=
                multiplayer::ParticipantSceneIntentKind::Run ||
            participant == nullptr ||
            !participant->runtime.valid ||
            !participant->runtime.in_run ||
            participant->runtime.run_nonce != run_nonce) {
            continue;
        }

        if (binding.last_applied_wave_respawn_run_nonce ==
                run_nonce &&
            binding.last_applied_wave_respawn_epoch ==
                respawn_epoch) {
            continue;
        }

        WizardRespawnTarget target;
        std::string target_error;
        if (!TryBuildWizardRespawnTarget(
                binding.actor_address,
                &target,
                &target_error)) {
            if (error_message != nullptr) {
                *error_message =
                    "Synthetic participant " +
                    std::to_string(binding.bot_id) +
                    " has no respawn target: " + target_error;
            }
            return false;
        }
        if (target.current_hp > 0.0f) {
            binding.last_applied_wave_respawn_run_nonce =
                run_nonce;
            binding.last_applied_wave_respawn_epoch =
                respawn_epoch;
            PublishParticipantGameplaySnapshot(binding);
            Log(
                "[bots] host synthetic wave respawn left living "
                "participant untouched. participant_id=" +
                std::to_string(binding.bot_id) +
                " actor=" + HexString(binding.actor_address) +
                " hp=" + std::to_string(target.current_hp) +
                " run_nonce=" + std::to_string(run_nonce) +
                " epoch=" + std::to_string(respawn_epoch) +
                " wave=" + std::to_string(wave));
            continue;
        }

        if (binding.ongoing_cast.active) {
            auto& memory = ProcessMemory::Instance();
            const auto cleanup_address =
                memory.ResolveGameAddressOrZero(
                    kCastActiveHandleCleanup);
            if (cleanup_address == 0) {
                if (error_message != nullptr) {
                    *error_message =
                        "Synthetic participant cast cleanup seam is "
                        "unavailable.";
                }
                return false;
            }
            const BotCastProcessingContext cast_context{
                &binding,
                binding.actor_address,
                cleanup_address,
                &memory,
            };
            FinishBotCastNativeLifecycle(
                cast_context,
                binding.ongoing_cast,
                "wave_respawn",
                true);
            binding.ongoing_cast =
                ParticipantEntityBinding::OngoingCastState{};
        }

        if (!multiplayer::StopBot(binding.bot_id)) {
            if (error_message != nullptr) {
                *error_message =
                    "Synthetic participant " +
                    std::to_string(binding.bot_id) +
                    " retained its pre-death movement intent.";
            }
            return false;
        }
        QuiesceDeadWizardBinding(&binding);
        bool respawned = false;
        if (!TryRespawnWizardActorAt(
                target,
                world_x,
                world_y,
                &respawned,
                &target_error)) {
            if (error_message != nullptr) {
                *error_message =
                    "Synthetic participant " +
                    std::to_string(binding.bot_id) +
                    " did not converge: " + target_error;
            }
            return false;
        }
        if (!respawned) {
            binding.last_applied_wave_respawn_run_nonce =
                run_nonce;
            binding.last_applied_wave_respawn_epoch =
                respawn_epoch;
            PublishParticipantGameplaySnapshot(binding);
            Log(
                "[bots] host synthetic wave respawn observed living "
                "participant at final native gate. participant_id=" +
                std::to_string(binding.bot_id) +
                " actor=" + HexString(binding.actor_address) +
                " run_nonce=" + std::to_string(run_nonce) +
                " epoch=" + std::to_string(respawn_epoch) +
                " wave=" + std::to_string(wave));
            continue;
        }

        binding.death_transition_stock_tick_seen = false;
        binding.local_death_presentation_started_ms = 0;
        binding.native_remote_death_epoch_active = false;
        binding.native_remote_death_attachment_actor_address = 0;
        binding.native_remote_death_drop_spawned = false;
        binding.last_applied_wave_respawn_run_nonce =
            run_nonce;
        binding.last_applied_wave_respawn_epoch =
            respawn_epoch;
        PublishParticipantGameplaySnapshot(binding);
        Log(
            "[bots] host synthetic wave respawn applied. "
            "participant_id=" +
            std::to_string(binding.bot_id) +
            " actor=" + HexString(binding.actor_address) +
            " run_nonce=" + std::to_string(run_nonce) +
            " epoch=" + std::to_string(respawn_epoch) +
            " wave=" + std::to_string(wave));
    }
    return true;
}
