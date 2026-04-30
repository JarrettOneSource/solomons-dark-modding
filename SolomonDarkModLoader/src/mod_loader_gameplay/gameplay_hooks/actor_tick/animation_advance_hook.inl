void __fastcall HookActorAnimationAdvance(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<ActorAnimationAdvanceFn>(g_gameplay_keyboard_injection.actor_animation_advance_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    const auto previous_depth = g_player_actor_vslot1c_depth;
    const auto previous_actor = g_player_actor_vslot1c_actor;
    const auto previous_caller = g_player_actor_vslot1c_caller;
    ++g_player_actor_vslot1c_depth;
    g_player_actor_vslot1c_actor = actor_address;
    g_player_actor_vslot1c_caller = reinterpret_cast<uintptr_t>(_ReturnAddress());

    const auto previous_participant_depth = g_gameplay_hud_participant_actor_depth;
    const auto previous_participant_actor = g_gameplay_hud_participant_actor;
    const auto previous_participant_caller = g_gameplay_hud_participant_actor_caller;
    ++g_gameplay_hud_participant_actor_depth;
    g_gameplay_hud_participant_actor = actor_address;
    g_gameplay_hud_participant_actor_caller = g_player_actor_vslot1c_caller;

    if constexpr (kEnableWizardBotHotPathDiagnostics) {
        static int s_vslot1c_logs_remaining = 24;
        if (s_vslot1c_logs_remaining > 0 && IsTrackedWizardParticipantActorForHud(actor_address)) {
            std::string display_name;
            std::uint64_t participant_id = 0;
            const auto resolved =
                TryGetGameplayHudParticipantDisplayNameForActor(actor_address, &display_name, &participant_id);
            --s_vslot1c_logs_remaining;
            Log(
                "[bots] vslot1c overlay callback. actor=" + HexString(actor_address) +
                " participant=" + std::to_string(participant_id) +
                " resolved=" + std::string(resolved ? "1" : "0") +
                " name=" + display_name +
                " caller=" + HexString(g_player_actor_vslot1c_caller) +
                " hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
        }
    }

    const bool standalone_wizard_actor =
        TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, nullptr, nullptr);
    if (standalone_wizard_actor) {
        NormalizeGameplaySlotBotSyntheticVisualState(actor_address);
    }
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
            if constexpr (kEnableWizardBotHotPathDiagnostics) {
                static int s_native_hud_name_draw_logs_remaining = 24;
                if (s_native_hud_name_draw_logs_remaining > 0) {
                    --s_native_hud_name_draw_logs_remaining;
                    Log(
                        "[bots] native gameplay HUD participant name draw. actor=" + HexString(actor_address) +
                        " participant=" + std::to_string(participant_id) +
                        " name=" + display_name +
                        " ok=" + std::string(drew_label ? "1" : "0") +
                        " exception=" + HexString(static_cast<uintptr_t>(exception_code)) +
                        " xy=(" + std::to_string(draw_x) + "," + std::to_string(draw_y) + ")");
                }
            }
        }
    }

    g_gameplay_hud_participant_actor_depth = previous_participant_depth;
    g_gameplay_hud_participant_actor = previous_participant_actor;
    g_gameplay_hud_participant_actor_caller = previous_participant_caller;
    g_player_actor_vslot1c_depth = previous_depth;
    g_player_actor_vslot1c_actor = previous_actor;
    g_player_actor_vslot1c_caller = previous_caller;
}
