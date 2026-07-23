void StartLuaEventQueue() {
    std::scoped_lock lock(g_pending_lua_event_mutex);
    g_pending_lua_events.clear();
    g_lua_event_queue_accepting = true;
}

void StopLuaEventQueue() {
    std::scoped_lock lock(g_pending_lua_event_mutex);
    g_lua_event_queue_accepting = false;
    g_pending_lua_events.clear();
}

void DispatchPendingLuaEventsToLuaMods() {
    // The caller owns LuaEngineMutex. Swap the current generation out before
    // invoking handlers so a handler-triggered native hook can enqueue the
    // next generation without re-entering Lua or blocking the hook thread.
    std::deque<PendingLuaEvent> pending;
    {
        std::scoped_lock lock(g_pending_lua_event_mutex);
        pending.swap(g_pending_lua_events);
    }

    for (const auto& event : pending) {
        std::visit(
            [](const auto& value) {
                using Event = std::decay_t<decltype(value)>;
                if constexpr (std::is_same_v<Event, RunStartedEvent>) {
                    DispatchRunStartedToLuaMods();
                } else if constexpr (std::is_same_v<Event, RunEndedEvent>) {
                    DispatchRunEndedToLuaMods(
                        value.reason ? value.reason->c_str() : nullptr);
                } else if constexpr (std::is_same_v<Event, WaveStartedEvent>) {
                    DispatchWaveStartedToLuaMods(value.summary);
                } else if constexpr (std::is_same_v<Event, WaveCompletedEvent>) {
                    DispatchWaveCompletedToLuaMods(value.wave_number);
                } else if constexpr (std::is_same_v<Event, EnemyDeathEvent>) {
                    DispatchEnemyDeathToLuaMods(
                        value.enemy_type,
                        value.x,
                        value.y,
                        value.kill_method ? value.kill_method->c_str() : nullptr,
                        value.content_id);
                } else if constexpr (std::is_same_v<Event, EnemySpawnedEvent>) {
                    DispatchEnemySpawnedToLuaMods(
                        value.enemy_type,
                        value.x,
                        value.y,
                        value.content_id);
                } else if constexpr (std::is_same_v<Event, SpellCastEvent>) {
                    DispatchSpellCastToLuaMods(
                        value.spell_id,
                        value.x,
                        value.y,
                        value.direction_x,
                        value.direction_y);
                } else if constexpr (std::is_same_v<Event, GoldChangedEvent>) {
                    DispatchGoldChangedToLuaMods(
                        value.gold,
                        value.delta,
                        value.source ? value.source->c_str() : nullptr);
                } else if constexpr (std::is_same_v<Event, DropSpawnedEvent>) {
                    DispatchDropSpawnedToLuaMods(
                        value.kind ? value.kind->c_str() : nullptr,
                        value.x,
                        value.y);
                } else if constexpr (std::is_same_v<Event, LevelUpEvent>) {
                    DispatchLevelUpToLuaMods(value.level, value.xp);
                } else if constexpr (std::is_same_v<Event, CustomEvent>) {
                    DispatchCustomEventToLuaMods(
                        value.mod_id,
                        value.event_name,
                        value.payload,
                        value.authority_participant_id,
                        value.stream_sequence);
                }
            },
            event);
    }
}

void QueueRunStartedEvent() {
    EnqueueLuaEvent(RunStartedEvent{});
}

void QueueRunEndedEvent(const char* reason) {
    EnqueueLuaEvent(RunEndedEvent{CopyNullableString(reason)});
}

void QueueWaveStartedEvent(const WaveSummary& summary) {
    EnqueueLuaEvent(WaveStartedEvent{summary});
}

void QueueWaveCompletedEvent(int wave_number) {
    EnqueueLuaEvent(WaveCompletedEvent{wave_number});
}

void QueueEnemyDeathEvent(
    int enemy_type,
    float x,
    float y,
    const char* kill_method,
    std::uint64_t content_id) {
    EnqueueLuaEvent(EnemyDeathEvent{
        enemy_type,
        x,
        y,
        content_id,
        CopyNullableString(kill_method)});
}

void QueueEnemySpawnedEvent(
    int enemy_type,
    float x,
    float y,
    std::uint64_t content_id) {
    EnqueueLuaEvent(EnemySpawnedEvent{enemy_type, x, y, content_id});
}

void QueueSpellCastEvent(
    int spell_id,
    float x,
    float y,
    float direction_x,
    float direction_y) {
    EnqueueLuaEvent(SpellCastEvent{
        spell_id,
        x,
        y,
        direction_x,
        direction_y});
}

void QueueGoldChangedEvent(int gold, int delta, const char* source) {
    EnqueueLuaEvent(GoldChangedEvent{
        gold,
        delta,
        CopyNullableString(source)});
}

void QueueDropSpawnedEvent(const char* kind, float x, float y) {
    EnqueueLuaEvent(DropSpawnedEvent{CopyNullableString(kind), x, y});
}

void QueueLevelUpEvent(int level, int xp) {
    EnqueueLuaEvent(LevelUpEvent{level, xp});
}

void QueueCustomEvent(
    const std::string& mod_id,
    const std::string& event_name,
    const LuaModValue& payload,
    std::uint64_t authority_participant_id,
    std::uint64_t stream_sequence) {
    EnqueueLuaEvent(CustomEvent{
        mod_id,
        event_name,
        payload,
        authority_participant_id,
        stream_sequence,
    });
}
