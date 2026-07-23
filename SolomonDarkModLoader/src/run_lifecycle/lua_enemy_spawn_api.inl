bool QueueRunLifecycleLuaEnemySpawn(
    const SDModLuaEnemySpawnConfig& config,
    int type_id,
    float x,
    float y,
    std::string* error_message,
    std::uint64_t* request_id) {
    if (config.content_id == 0) {
        if (error_message != nullptr) {
            *error_message = "Lua enemy spawn requires a registered content id.";
        }
        if (request_id != nullptr) {
            *request_id = 0;
        }
        return false;
    }
    if (!multiplayer::IsLuaModSimulationAuthority()) {
        if (error_message != nullptr) {
            *error_message = "Lua enemy spawn requires simulation authority.";
        }
        if (request_id != nullptr) {
            *request_id = 0;
        }
        return false;
    }
    uintptr_t spawner_address = 0;
    uintptr_t remembered_vtable = 0;
    if (!TryGetPreferredManualRunEnemySpawner(
            &spawner_address,
            &remembered_vtable)) {
        if (error_message != nullptr) {
            *error_message = "stock wave spawner is not ready.";
        }
        if (request_id != nullptr) {
            *request_id = 0;
        }
        return false;
    }
    return QueueRunLifecycleEnemySpawnRequestInternal(
        0,
        config,
        type_id,
        x,
        y,
        true,
        false,
        error_message,
        request_id);
}
