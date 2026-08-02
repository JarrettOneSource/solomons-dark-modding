bool TryResolveMultiplayerDeathPresentationRenderTick(
    uintptr_t actor_address,
    std::uint16_t* render_tick) {
    if (actor_address == 0 || render_tick == nullptr) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    SDModPlayerState local_player;
    if (TryGetPlayerState(&local_player) &&
        local_player.valid &&
        local_player.actor_address == actor_address) {
        std::uint16_t logical_tick = 0;
        if (runtime_state.death_spectator.phase ==
                multiplayer::DeathSpectatorPhase::
                    DeathPresentation) {
            const auto now_ms =
                static_cast<std::uint64_t>(::GetTickCount64());
            if (now_ms <
                runtime_state.death_spectator.death_started_ms) {
                return false;
            }
            logical_tick =
                multiplayer::
                    ResolveParticipantDeathPresentationTick(
                        now_ms -
                        runtime_state.death_spectator
                            .death_started_ms);
        } else if (
            runtime_state.death_spectator.phase ==
            multiplayer::DeathSpectatorPhase::Spectating) {
            logical_tick =
                multiplayer::
                    kNativeDeathPresentationTerminalCorpseTick;
        } else {
            return false;
        }
        *render_tick =
            multiplayer::
                ResolveParticipantDeathPresentationRenderTick(
                    logical_tick);
        return true;
    }

    std::lock_guard<std::recursive_mutex> lock(
        g_participant_entities_mutex);
    const auto* binding = FindParticipantEntityForActor(actor_address);
    if (binding == nullptr ||
        !binding->native_remote_death_epoch_active) {
        return false;
    }
    const auto* participant =
        multiplayer::FindParticipant(runtime_state, binding->bot_id);
    if (participant == nullptr ||
        !participant->runtime.valid ||
        !std::isfinite(participant->runtime.life_current) ||
        participant->runtime.life_current > 0.0f) {
        return false;
    }

    std::uint16_t logical_tick =
        multiplayer::kNativeDeathPresentationTerminalCorpseTick;
    if ((participant->runtime.presentation_flags &
         multiplayer::
             ParticipantPresentationFlagDeathPresentation) != 0) {
        const auto now_ms =
            static_cast<std::uint64_t>(::GetTickCount64());
        const auto packet_age_ms =
            participant->last_packet_ms != 0 &&
                now_ms >= participant->last_packet_ms
                ? now_ms - participant->last_packet_ms
                : 0;
        const auto packet_age_ticks =
            multiplayer::
                ResolveParticipantDeathPresentationTick(
                    packet_age_ms);
        const auto extrapolated_tick =
            static_cast<std::uint32_t>(
                participant->runtime.death_presentation_tick) +
            packet_age_ticks;
        logical_tick = static_cast<std::uint16_t>(
            (std::min)(
                extrapolated_tick,
                static_cast<std::uint32_t>(
                    multiplayer::
                        kNativeDeathPresentationMaximumHeldTick)));
    }
    *render_tick =
        multiplayer::
            ResolveParticipantDeathPresentationRenderTick(
                logical_tick);
    return true;
}

void __fastcall HookActorAnimationAdvance(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<ActorAnimationAdvanceFn>(g_gameplay_keyboard_injection.actor_animation_advance_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);

    struct AnimationAdvanceContextScope {
        int previous_depth = 0;
        uintptr_t previous_actor = 0;
        uintptr_t previous_caller = 0;
        int previous_participant_depth = 0;
        uintptr_t previous_participant_actor = 0;
        uintptr_t previous_participant_caller = 0;

        AnimationAdvanceContextScope(uintptr_t actor, uintptr_t caller)
            : previous_depth(g_player_actor_vslot1c_depth),
              previous_actor(g_player_actor_vslot1c_actor),
              previous_caller(g_player_actor_vslot1c_caller),
              previous_participant_depth(g_gameplay_hud_participant_actor_depth),
              previous_participant_actor(g_gameplay_hud_participant_actor),
              previous_participant_caller(g_gameplay_hud_participant_actor_caller) {
            ++g_player_actor_vslot1c_depth;
            g_player_actor_vslot1c_actor = actor;
            g_player_actor_vslot1c_caller = caller;

            ++g_gameplay_hud_participant_actor_depth;
            g_gameplay_hud_participant_actor = actor;
            g_gameplay_hud_participant_actor_caller = caller;
        }

        ~AnimationAdvanceContextScope() {
            g_gameplay_hud_participant_actor_depth = previous_participant_depth;
            g_gameplay_hud_participant_actor = previous_participant_actor;
            g_gameplay_hud_participant_actor_caller = previous_participant_caller;
            g_player_actor_vslot1c_depth = previous_depth;
            g_player_actor_vslot1c_actor = previous_actor;
            g_player_actor_vslot1c_caller = previous_caller;
        }
    } context_scope(actor_address, reinterpret_cast<uintptr_t>(_ReturnAddress()));

    {
        auto& memory = ProcessMemory::Instance();
        std::uint8_t death_drive_state = 0;
        std::int32_t stored_death_tick = 0;
        std::uint16_t render_death_tick = 0;
        std::uint16_t safe_storage_tick = 0;
        const bool can_project_death_tick =
            memory.TryReadField(
                actor_address,
                kActorAnimationDriveStateByteOffset,
                &death_drive_state) &&
            death_drive_state != 0 &&
            memory.TryReadField(
                actor_address,
                kActorAnimationMoveDurationTicksOffset,
                &stored_death_tick) &&
            TryResolveMultiplayerDeathPresentationRenderTick(
                actor_address,
                &render_death_tick);
        if (can_project_death_tick) {
            safe_storage_tick =
                multiplayer::
                    ResolveParticipantDeathPresentationStorageTick(
                        static_cast<std::uint16_t>(
                            (std::clamp)(
                                stored_death_tick,
                                0,
                                static_cast<std::int32_t>(
                                    multiplayer::
                                        kNativeDeathPresentationMaximumHeldTick))));
        }
        const bool restore_storage_tick_after_render =
            can_project_death_tick &&
            memory.TryWriteField<std::int32_t>(
                actor_address,
                kActorAnimationMoveDurationTicksOffset,
                render_death_tick);
        original(self);
        if (restore_storage_tick_after_render) {
            (void)memory.TryWriteField<std::int32_t>(
                actor_address,
                kActorAnimationMoveDurationTicksOffset,
                safe_storage_tick);
        }
    }
    CaptureLuaDrawWorldProjection(GetLastSeenD3d9Device());
    if (multiplayer::IsLocalTransportClient()) {
        (void)ApplyLatestReplicatedRunEnemyTargetForLocalActor(actor_address, false);
    }
}
