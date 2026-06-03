constexpr std::uint32_t kFallbackRunGenerationSeed = 0x6D2B79F5u;
constexpr std::uint32_t kNativeRngSeedMask = 0x3FFFFFFFu;
constexpr std::size_t kNativeRngStateMinimumSize = 0xE4;

std::uint32_t NormalizeRunGenerationSeed(std::uint32_t seed) {
    seed = seed & kNativeRngSeedMask;
    return seed != 0 ? seed : (kFallbackRunGenerationSeed & kNativeRngSeedMask);
}

void PublishLocalRunNonce(std::uint32_t seed) {
    if (seed == 0) {
        return;
    }

    multiplayer::UpdateRuntimeState([&](multiplayer::RuntimeState& state) {
        auto* local = multiplayer::UpsertLocalParticipant(state);
        if (local == nullptr) {
            return;
        }
        local->runtime.run_nonce = seed;
    });
}

std::uint32_t ReadPendingRunGenerationSeed() {
    if (g_gameplay_keyboard_injection.pending_run_generation_seed_valid.load(std::memory_order_acquire) == 0) {
        return 0;
    }
    return g_gameplay_keyboard_injection.pending_run_generation_seed.load(std::memory_order_acquire);
}

std::uint32_t BuildHostRunGenerationSeed() {
    LARGE_INTEGER counter{};
    (void)::QueryPerformanceCounter(&counter);
    const auto tick_count = static_cast<std::uint64_t>(::GetTickCount64());
    const auto participant_id = multiplayer::GetLocalTransportParticipantId();
    const auto process_id = static_cast<std::uint64_t>(::GetCurrentProcessId());
    std::uint32_t seed = 0xA511E9B3u;
    seed ^= static_cast<std::uint32_t>(tick_count);
    seed ^= static_cast<std::uint32_t>(tick_count >> 32);
    seed ^= static_cast<std::uint32_t>(counter.QuadPart);
    seed ^= static_cast<std::uint32_t>(counter.QuadPart >> 32);
    seed ^= static_cast<std::uint32_t>(participant_id);
    seed ^= static_cast<std::uint32_t>(participant_id >> 32);
    seed ^= static_cast<std::uint32_t>(process_id);
    seed ^= static_cast<std::uint32_t>(process_id >> 32);
    return NormalizeRunGenerationSeed(seed);
}

bool SetPendingRunGenerationSeedInternal(std::uint32_t seed, const char* source) {
    seed = NormalizeRunGenerationSeed(seed);
    g_gameplay_keyboard_injection.pending_run_generation_seed.store(seed, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_run_generation_seed_valid.store(1, std::memory_order_release);
    PublishLocalRunNonce(seed);
    Log(
        "Stored host-authoritative run generation seed. source=" +
        std::string(source != nullptr ? source : "unknown") +
        " seed=" + HexString(static_cast<uintptr_t>(seed)));
    return true;
}

bool TryResolveNativeGlobalRngState(uintptr_t* global_address, uintptr_t* state_address) {
    if (global_address != nullptr) {
        *global_address = 0;
    }
    if (state_address != nullptr) {
        *state_address = 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolved_global = memory.ResolveGameAddressOrZero(kNativeGlobalRngStateGlobal);
    if (global_address != nullptr) {
        *global_address = resolved_global;
    }
    if (resolved_global == 0) {
        return false;
    }

    uintptr_t resolved_state = 0;
    if (!memory.TryReadValue(resolved_global, &resolved_state) || resolved_state == 0) {
        return false;
    }
    if (!memory.IsWritableRange(resolved_state, kNativeRngStateMinimumSize)) {
        return false;
    }

    if (state_address != nullptr) {
        *state_address = resolved_state;
    }
    return true;
}

bool InitializeNativeGlobalRngForRunGeneration(std::uint32_t seed, const char* source) {
    auto& memory = ProcessMemory::Instance();
    const auto initialize_address = memory.ResolveGameAddressOrZero(kNativeRngInitialize);
    uintptr_t rng_global_address = 0;
    uintptr_t rng_state_address = 0;
    DWORD exception_code = 0;

    const bool resolved_state = TryResolveNativeGlobalRngState(&rng_global_address, &rng_state_address);
    const bool initialized = resolved_state &&
        initialize_address != 0 &&
        CallNativeRngInitializeSafe(initialize_address, rng_state_address, seed, &exception_code);

    Log(
        "Initialized host-authoritative run generation RNG. source=" +
        std::string(source != nullptr ? source : "unknown") +
        " seed=" + HexString(static_cast<uintptr_t>(seed)) +
        " rng_global=" + (rng_global_address != 0 ? HexString(rng_global_address) : std::string("unresolved")) +
        " rng_state=" + (rng_state_address != 0 ? HexString(rng_state_address) : std::string("unresolved")) +
        " initialize=" + (initialize_address != 0 ? HexString(initialize_address) : std::string("unresolved")) +
        " resolved_state=" + std::to_string(resolved_state ? 1 : 0) +
        " ok=" + std::to_string(initialized ? 1 : 0) +
        (exception_code != 0 ? " seh=" + HexString(exception_code) : std::string{}));
    return initialized;
}

std::uint32_t EnsureHostRunGenerationSeed(const char* source) {
    const auto pending = ReadPendingRunGenerationSeed();
    if (pending != 0) {
        PublishLocalRunNonce(pending);
        return pending;
    }

    const auto seed = BuildHostRunGenerationSeed();
    (void)SetPendingRunGenerationSeedInternal(seed, source);
    return seed;
}

bool ApplyPendingRunGenerationSeedForSceneSwitch(int region_index, const char* source) {
    if (region_index != kArenaRegionIndex) {
        return false;
    }

    if (multiplayer::IsLocalTransportHost()) {
        (void)EnsureHostRunGenerationSeed(source);
    }

    const bool had_pending =
        g_gameplay_keyboard_injection.pending_run_generation_seed_valid.exchange(0, std::memory_order_acq_rel) != 0;
    const auto seed = NormalizeRunGenerationSeed(
        g_gameplay_keyboard_injection.pending_run_generation_seed.exchange(0, std::memory_order_acq_rel));
    if (!had_pending) {
        return false;
    }

    PublishLocalRunNonce(seed);
    return InitializeNativeGlobalRngForRunGeneration(seed, source);
}
