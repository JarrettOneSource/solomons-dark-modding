void DispatchLuaRunStarted() {
    detail::QueueRunStartedEvent();
}

void DispatchLuaRunEnded(const char* reason) {
    detail::QueueRunEndedEvent(reason);
}

void DispatchLuaWaveStarted(const WaveSummary& summary) {
    detail::QueueWaveStartedEvent(summary);
}

void DispatchLuaWaveCompleted(int wave_number) {
    detail::QueueWaveCompletedEvent(wave_number);
}

void DispatchLuaEnemyDeath(
    int enemy_type,
    float x,
    float y,
    const char* kill_method,
    std::uint64_t content_id) {
    detail::QueueEnemyDeathEvent(
        enemy_type,
        x,
        y,
        kill_method,
        content_id);
}

void DispatchLuaEnemySpawned(
    int enemy_type,
    float x,
    float y,
    std::uint64_t content_id) {
    detail::QueueEnemySpawnedEvent(enemy_type, x, y, content_id);
}

void DispatchLuaSpellCast(
    int spell_id,
    float x,
    float y,
    float direction_x,
    float direction_y) {
    detail::QueueSpellCastEvent(
        spell_id,
        x,
        y,
        direction_x,
        direction_y);
}

void DispatchLuaGoldChanged(int gold, int delta, const char* source) {
    detail::QueueGoldChangedEvent(gold, delta, source);
}

void DispatchLuaDropSpawned(const char* kind, float x, float y) {
    detail::QueueDropSpawnedEvent(kind, x, y);
}

void DispatchLuaLevelUp(int level, int xp) {
    detail::QueueLevelUpEvent(level, xp);
}

void DispatchLuaConsumableUse(
    std::uint64_t content_id,
    std::uint64_t participant_id,
    std::uint64_t use_id,
    bool local_owner) {
    (void)QueueLuaConsumableNativeVfx(
        LuaConsumableNativeVfxRequest{
            content_id,
            participant_id,
            use_id,
        });
    detail::QueueConsumableUseEvent(
        content_id,
        participant_id,
        use_id,
        local_owner);
}

void DispatchLuaCustomEvent(
    const std::string& mod_id,
    const std::string& event_name,
    const LuaModValue& payload,
    std::uint64_t authority_participant_id,
    std::uint64_t stream_sequence) {
    detail::QueueCustomEvent(
        mod_id,
        event_name,
        payload,
        authority_participant_id,
        stream_sequence);
}
