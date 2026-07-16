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
    if (IsTrackedWizardParticipantActorForHud(actor_address)) {
        std::string display_name;
        std::uint64_t participant_id = 0;
        if (TryGetGameplayHudParticipantDisplayNameForActor(actor_address, &display_name, &participant_id) &&
            !display_name.empty()) {
            DWORD exception_code = 0;
            float draw_x = 0.0f;
            float draw_y = 0.0f;
            const bool drew_label =
                DrawGameplayHudParticipantName(actor_address, display_name, &draw_x, &draw_y, &exception_code);
            float health_ratio = 0.0f;
            int health_segments = 0;
            DWORD health_bar_exception_code = 0;
            const bool drew_health_bar = DrawGameplayParticipantHealthBar(
                actor_address,
                draw_y,
                &health_ratio,
                &health_segments,
                &health_bar_exception_code);
            static std::unordered_map<std::uint64_t, int> s_logged_health_segments;
            static int s_failed_nameplate_draw_logs_remaining = 8;
            const auto logged_health = s_logged_health_segments.find(participant_id);
            const bool health_changed =
                logged_health == s_logged_health_segments.end() ||
                logged_health->second != health_segments;
            const bool draw_succeeded = drew_label && drew_health_bar;
            const bool should_log =
                (draw_succeeded && health_changed) ||
                (!draw_succeeded && s_failed_nameplate_draw_logs_remaining > 0);
            if (should_log) {
                if (draw_succeeded) {
                    s_logged_health_segments[participant_id] = health_segments;
                } else {
                    --s_failed_nameplate_draw_logs_remaining;
                }
                Log(
                    "[bots] native gameplay participant name draw. source=playerwizard_render actor=" +
                    HexString(actor_address) +
                    " participant=" + std::to_string(participant_id) +
                    " name=" + display_name +
                    " ok=" + std::string(drew_label ? "1" : "0") +
                    " health_bar=" + std::string(drew_health_bar ? "1" : "0") +
                    " health_ratio=" + std::to_string(health_ratio) +
                    " health_segments=" + std::to_string(health_segments) + "/12" +
                    " exception=" + HexString(static_cast<uintptr_t>(exception_code)) +
                    " health_bar_exception=" +
                        HexString(static_cast<uintptr_t>(health_bar_exception_code)) +
                    " xy=(" + std::to_string(draw_x) + "," + std::to_string(draw_y) + ")");
            }
        }
    }
    if (multiplayer::IsLocalTransportClient()) {
        (void)ApplyLatestReplicatedRunEnemyTargetForLocalActor(actor_address, false);
    }
}
