void __fastcall HookPoisonedModifierTick(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<PoisonedModifierTickFn>(
        g_gameplay_keyboard_injection.poisoned_modifier_tick_hook);
    if (original == nullptr) {
        return;
    }

    if (!multiplayer::IsLocalTransportClient()) {
        original(self);
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto damage_target_global =
        memory.ResolveGameAddressOrZero(kDamageContextTargetGlobal);
    uintptr_t actor_address = 0;
    std::int8_t source_slot = -1;
    float damage_per_tick = 0.0f;
    const auto local_actor_address =
        g_gameplay_keyboard_injection.local_player_tick_actor_address.load(
            std::memory_order_relaxed);
    // Owner corrections install source slot zero with real damage. Remote
    // presentation clones use source slot one and zero damage.
    const bool owner_authoritative_tick =
        self != nullptr &&
        damage_target_global != 0 &&
        memory.TryReadValue(damage_target_global, &actor_address) &&
        actor_address != 0 &&
        actor_address == local_actor_address &&
        memory.TryReadField(
            reinterpret_cast<uintptr_t>(self),
            kNativePoisonSourceSlotOffset,
            &source_slot) &&
        source_slot == 0 &&
        memory.TryReadField(
            reinterpret_cast<uintptr_t>(self),
            kNativePoisonDamagePerTickOffset,
            &damage_per_tick) &&
        std::isfinite(damage_per_tick) &&
        damage_per_tick > 0.0f;
    if (!owner_authoritative_tick) {
        original(self);
        return;
    }

    const auto previous_target =
        g_client_owner_authorized_damage_target;
    g_client_owner_authorized_damage_target = actor_address;
    original(self);
    g_client_owner_authorized_damage_target = previous_target;
}
