void __fastcall HookActorWorldTick(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<ActorWorldTickFn>(
        g_state.hooks[kHookActorWorldTick]);
    if (original == nullptr) {
        return;
    }

    struct ScopedGameplaySimulationFrame {
        ScopedGameplaySimulationFrame()
            : should_advance(multiplayer::BeginGameplaySimulationFrame()) {}
        ~ScopedGameplaySimulationFrame() {
            multiplayer::EndGameplaySimulationFrame();
        }
        bool should_advance = true;
    } frame;

    if (frame.should_advance) {
        original(self, unused_edx);
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto world_address = reinterpret_cast<uintptr_t>(self);
    const auto resolved_player_actor_tick =
        memory.ResolveGameAddressOrZero(kPlayerActorTick);
    std::int32_t actor_count = 0;
    uintptr_t actor_array_address = 0;
    constexpr std::int32_t kMaxReasonableActorWorldCount = 65'536;
    if (world_address == 0 ||
        resolved_player_actor_tick == 0 ||
        !memory.TryReadField(
            world_address,
            kActorWorldActorCountOffset,
            &actor_count) ||
        !memory.TryReadField(
            world_address,
            kActorWorldActorArrayOffset,
            &actor_array_address) ||
        actor_count < 0 ||
        actor_count > kMaxReasonableActorWorldCount ||
        (actor_count != 0 && actor_array_address == 0)) {
        static std::uint64_t s_last_invalid_actor_world_pause_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_invalid_actor_world_pause_log_ms >= 1000) {
            s_last_invalid_actor_world_pause_log_ms = now_ms;
            Log(
                "ActorWorld_Tick held for shared simulation control, but the "
                "player-only actor list could not be read. world=" +
                HexString(world_address) +
                " count=" + std::to_string(actor_count) +
                " actors=" + HexString(actor_array_address));
        }
        return;
    }

    std::int32_t player_actor_tick_count = 0;
    std::int32_t held_non_player_actor_count = 0;
    for (std::int32_t index = 0; index < actor_count; ++index) {
        uintptr_t actor_address = 0;
        if (!memory.TryReadValue(
                actor_array_address +
                    static_cast<uintptr_t>(index) * sizeof(uintptr_t),
                &actor_address) ||
            actor_address == 0) {
            continue;
        }

        std::uint8_t pending_remove = 0;
        uintptr_t actor_vtable = 0;
        uintptr_t actor_tick_address = 0;
        if (!memory.TryReadField(
                actor_address,
                kActorPendingRemoveOffset,
                &pending_remove) ||
            pending_remove != 0 ||
            !memory.TryReadValue(actor_address, &actor_vtable) ||
            actor_vtable == 0 ||
            !memory.TryReadField(
                actor_vtable,
                kActorVtableTickOffset,
                &actor_tick_address)) {
            continue;
        }
        if (actor_tick_address != resolved_player_actor_tick) {
            held_non_player_actor_count += 1;
            continue;
        }

        if (!memory.TryWriteField(
                world_address,
                kActorWorldCurrentActorOffset,
                actor_address)) {
            break;
        }

        auto* actor = reinterpret_cast<void*>(actor_address);
        std::uint8_t pending_initialize = 0;
        if (memory.TryReadField(
                actor_address,
                kActorPendingInitializeOffset,
                &pending_initialize) &&
            pending_initialize != 0) {
            uintptr_t actor_initialize_address = 0;
            if (!memory.TryReadField(
                    actor_vtable,
                    kActorVtableInitializeOffset,
                    &actor_initialize_address) ||
                actor_initialize_address == 0 ||
                !memory.TryWriteField<std::uint8_t>(
                    actor_address,
                    kActorPendingInitializeOffset,
                    0)) {
                continue;
            }
            const auto actor_initialize =
                reinterpret_cast<ActorWorldEntryFn>(actor_initialize_address);
            actor_initialize(actor);
        }

        const auto actor_tick =
            reinterpret_cast<ActorWorldEntryFn>(actor_tick_address);
        actor_tick(actor);
        player_actor_tick_count += 1;
    }

    (void)memory.TryWriteField<uintptr_t>(
        world_address,
        kActorWorldCurrentActorOffset,
        0);
    static std::uint64_t s_last_actor_world_pause_log_ms = 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (now_ms - s_last_actor_world_pause_log_ms >= 1000) {
        s_last_actor_world_pause_log_ms = now_ms;
        Log(
            "ActorWorld_Tick held for shared simulation control. player_ticks=" +
            std::to_string(player_actor_tick_count) +
            " non_player_actors_held=" +
            std::to_string(held_non_player_actor_count));
    }
}
