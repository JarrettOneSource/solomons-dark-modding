void NotifyMultiplayerJoinFlowPresentationRendered(
    std::string_view message) {
    std::scoped_lock lock(g_join_flow.mutex);
    if (!g_join_flow.enabled ||
        g_join_flow.phase != JoinFlowPhase::LoadingBoneyard ||
        message != "Loading Boneyard" ||
        g_join_flow.loading_presentation_first_rendered_ms != 0) {
        return;
    }
    g_join_flow.loading_presentation_first_rendered_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    Log(
        "Multiplayer join flow rendered its first Loading Boneyard frame.");
}

MultiplayerJoinFlowPresentation
GetMultiplayerJoinFlowPresentation() {
    std::scoped_lock lock(g_join_flow.mutex);
    switch (g_join_flow.phase) {
    case JoinFlowPhase::AdvancingMenus:
        return {
            g_join_flow.main_menu_first_seen_ms != 0,
            {},
        };
    case JoinFlowPhase::PrivateGameplay:
        return {};
    case JoinFlowPhase::AwaitingLoadout:
        return {true, {}};
    case JoinFlowPhase::Connecting:
        return {true, "Connecting to match"};
    case JoinFlowPhase::LoadingBoneyard:
        return {true, "Loading Boneyard"};
    default:
        return {};
    }
}
