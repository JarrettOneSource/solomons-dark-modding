void SetAllBotSceneIntentsToRun() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        return;
    }

    UpdateRuntimeState([](RuntimeState& state) {
        for (auto& participant : state.participants) {
            if (!IsLuaControlledParticipant(participant)) {
                continue;
            }

            ApplySceneIntent(
                &participant,
                ParticipantSceneIntent{
                    ParticipantSceneIntentKind::Run,
                    -1,
                    -1,
                });
        }
    });
}

void SetAllBotSceneIntentsToSharedHub() {
    std::scoped_lock lock(g_bot_runtime_mutex);
    if (!g_bot_runtime_initialized) {
        return;
    }

    UpdateRuntimeState([](RuntimeState& state) {
        for (auto& participant : state.participants) {
            if (!IsLuaControlledParticipant(participant)) {
                continue;
            }

            ApplySceneIntent(
                &participant,
                ParticipantSceneIntent{
                    ParticipantSceneIntentKind::SharedHub,
                    0,
                    0,
                });
        }
    });
}

const char* BotControllerStateLabel(BotControllerState state) {
    return BotControllerStateLabelInternal(state);
}
