bool ExecuteSpawnRewardNow(std::string_view kind, int amount, float x, float y, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (kind != "gold") {
        if (error_message != nullptr) {
            *error_message = "Only gold rewards are supported right now.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    const auto spawn_reward_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kSpawnRewardGold);
    if (spawn_reward_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the gold reward spawn function.";
        }
        return false;
    }

    auto spawn_reward = reinterpret_cast<SpawnRewardGoldFn>(spawn_reward_address);
    spawn_reward(
        reinterpret_cast<void*>(arena_address),
        FloatToBits(x),
        FloatToBits(y),
        amount,
        kSpawnRewardDefaultLifetime);
    return true;
}
