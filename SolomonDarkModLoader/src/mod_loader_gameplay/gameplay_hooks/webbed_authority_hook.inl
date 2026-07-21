void __fastcall HookWebbedModifierTick(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<WebbedModifierTickFn>(
        g_gameplay_keyboard_injection.webbed_modifier_tick_hook);
    if (original == nullptr) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto active_actor_global =
        memory.ResolveGameAddressOrZero(kDamageContextTargetGlobal);
    uintptr_t actor_address = 0;
    if (active_actor_global == 0 ||
        !memory.TryReadValue(active_actor_global, &actor_address) ||
        actor_address == 0) {
        original(self);
        return;
    }

    float movement_x = 0.0f;
    float movement_y = 0.0f;
    std::uint64_t remote_participant_id = 0;
    bool have_remote_owner_movement = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        const auto* binding = FindParticipantEntityForActor(actor_address);
        if (binding != nullptr && IsNativeRemoteParticipantBinding(binding)) {
            remote_participant_id = binding->bot_id;
            movement_x = binding->replicated_movement_intent_x;
            movement_y = binding->replicated_movement_intent_y;
            const auto magnitude_squared =
                movement_x * movement_x + movement_y * movement_y;
            have_remote_owner_movement =
                std::isfinite(magnitude_squared) &&
                magnitude_squared > 0.000001f &&
                magnitude_squared <= 1.0001f;
        }
    }
    if (!have_remote_owner_movement) {
        original(self);
        return;
    }

    float saved_movement_x = 0.0f;
    float saved_movement_y = 0.0f;
    if (!TryReadFiniteFloatField(
            actor_address,
            kActorAnimationConfigBlockOffset,
            &saved_movement_x) ||
        !TryReadFiniteFloatField(
            actor_address,
            kActorAnimationDriveParameterOffset,
            &saved_movement_y)) {
        original(self);
        return;
    }

    const bool wrote_movement_x = memory.TryWriteField(
        actor_address, kActorAnimationConfigBlockOffset, movement_x);
    const bool wrote_movement_y = memory.TryWriteField(
        actor_address, kActorAnimationDriveParameterOffset, movement_y);
    if (!wrote_movement_x || !wrote_movement_y) {
        if (wrote_movement_x) {
            (void)memory.TryWriteField(
                actor_address,
                kActorAnimationConfigBlockOffset,
                saved_movement_x);
        }
        if (wrote_movement_y) {
            (void)memory.TryWriteField(
                actor_address,
                kActorAnimationDriveParameterOffset,
                saved_movement_y);
        }
        original(self);
        return;
    }

    Log(
        "[bots] remote native Webbed consumed owner movement intent. bot_id=" +
        std::to_string(remote_participant_id) +
        " actor=" + HexString(actor_address) +
        " movement=(" + std::to_string(movement_x) + "," +
        std::to_string(movement_y) + ")");
    original(self);
    (void)memory.TryWriteField(
        actor_address, kActorAnimationConfigBlockOffset, saved_movement_x);
    (void)memory.TryWriteField(
        actor_address, kActorAnimationDriveParameterOffset, saved_movement_y);
}
