std::uint32_t AdvanceParticipantPresentationSceneEpoch(
    std::uint32_t current_epoch) {
    const auto next_epoch = current_epoch + 1;
    return next_epoch == 0 ? 1 : next_epoch;
}

void RefreshLocalParticipantPresentationSceneTracking(
    const SDModSceneState& scene_state,
    ParticipantSceneIntentKind scene_kind) {
    if (!scene_state.valid) {
        return;
    }

    const auto scene_key = BuildWorldSceneKey(scene_state, scene_kind);
    if (scene_key ==
        g_local_transport.participant_presentation_scene_key) {
        return;
    }

    g_local_transport.participant_presentation_scene_key = scene_key;
    g_local_transport.participant_presentation_scene_epoch =
        AdvanceParticipantPresentationSceneEpoch(
            g_local_transport.participant_presentation_scene_epoch);
}
