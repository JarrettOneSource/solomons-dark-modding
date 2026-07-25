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
    if (IsTrackedWizardParticipantActorForHud(actor_address)) {
        std::string display_name;
        std::uint64_t participant_id = 0;
        float health_ratio = 0.0f;
        const bool health_valid =
            TryGetGameplayHudParticipantDisplayNameForActor(
                actor_address,
                &display_name,
                &participant_id,
                &health_ratio);
        if (health_valid && !display_name.empty()) {
            DWORD exception_code = 0;
            float draw_x = 0.0f;
            float draw_y = 0.0f;
            const bool drew_label =
                DrawGameplayHudParticipantName(
                    actor_address,
                    participant_id,
                    display_name,
                    health_ratio,
                    &draw_x,
                    &draw_y,
                    &exception_code);
            const int health_percent = std::clamp(
                static_cast<int>(
                    std::lround(health_ratio * 100.0f)),
                0,
                100);
            static std::unordered_map<std::uint64_t, int>
                s_logged_nameplate_health_percent;
            static int s_failed_nameplate_draw_logs_remaining = 8;
            const bool draw_succeeded = drew_label;
            const auto logged_health =
                s_logged_nameplate_health_percent.find(participant_id);
            const bool health_changed =
                logged_health == s_logged_nameplate_health_percent.end() ||
                logged_health->second != health_percent;
            const bool should_log =
                (draw_succeeded && health_changed) ||
                (!draw_succeeded && s_failed_nameplate_draw_logs_remaining > 0);
            if (should_log) {
                if (draw_succeeded) {
                    s_logged_nameplate_health_percent[participant_id] =
                        health_percent;
                } else {
                    --s_failed_nameplate_draw_logs_remaining;
                }
                Log(
                    "[bots] native gameplay participant name draw. source=playerwizard_render actor=" +
                    HexString(actor_address) +
                    " participant=" + std::to_string(participant_id) +
                    " name=" + display_name +
                    " ok=" + std::string(drew_label ? "1" : "0") +
                    " health_bar=dx9" +
                    " health_valid=" +
                        std::string(health_valid ? "1" : "0") +
                    " health_ratio=" + std::to_string(health_ratio) +
                    " health_percent=" +
                        std::to_string(health_percent) +
                    " exception=" + HexString(static_cast<uintptr_t>(exception_code)) +
                    " xy=(" + std::to_string(draw_x) + "," + std::to_string(draw_y) + ")");
            }
        }
    }
    if (multiplayer::IsLocalTransportClient()) {
        (void)ApplyLatestReplicatedRunEnemyTargetForLocalActor(actor_address, false);
    }
}
