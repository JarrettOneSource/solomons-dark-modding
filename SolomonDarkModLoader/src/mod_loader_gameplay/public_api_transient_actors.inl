bool TryListTransientSceneActors(
    std::vector<SDModSceneActorState>* actors) {
    if (actors == nullptr) {
        return false;
    }

    uintptr_t gameplay_scene_address = 0;
    if (!TryResolveCurrentGameplayScene(
            &gameplay_scene_address) ||
        gameplay_scene_address == 0) {
        return false;
    }

    SceneContextSnapshot scene_context;
    if (!TryBuildSceneContextSnapshot(
            gameplay_scene_address,
            &scene_context) ||
        scene_context.world_address == 0) {
        return false;
    }

    actors->clear();
    std::unordered_set<uintptr_t> seen;
    AppendTransientSceneActors(
        scene_context,
        &seen,
        actors,
        false);
    std::sort(
        actors->begin(),
        actors->end(),
        [](const SDModSceneActorState& left,
           const SDModSceneActorState& right) {
            return left.actor_address <
                   right.actor_address;
        });
    return true;
}
