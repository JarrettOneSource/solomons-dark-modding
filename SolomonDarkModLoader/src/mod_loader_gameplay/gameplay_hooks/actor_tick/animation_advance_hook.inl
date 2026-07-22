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

    original(self);
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
