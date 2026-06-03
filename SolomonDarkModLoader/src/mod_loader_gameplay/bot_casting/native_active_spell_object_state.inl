struct BotNativeActiveSpellObjectState {
    std::uint8_t group = 0xFF;
    std::uint16_t slot = 0xFFFF;
    std::uintptr_t world = 0;
    std::uintptr_t selection_state = 0;
    std::uintptr_t object = 0;
    DWORD lookup_exception = 0;
    std::uint32_t object_type = 0;
    std::uint32_t phase = 0;
    std::uint32_t release_timer = 0;
    float object_x = 0.0f;
    float object_y = 0.0f;
    float object_heading = 0.0f;
    float object_radius = 0.0f;
    float charge = 0.0f;
    float growth_rate = 0.0f;
    float release_charge = 0.0f;
    float release_damage = 0.0f;
    float release_base_damage = 0.0f;
    float max_charge = 0.0f;
    bool readable = false;
    bool lookup_attempted = false;
    bool lookup_succeeded = false;
    bool handle_from_selection_state = false;
    bool boulder_max_size_reached = false;
};

BotNativeActiveSpellObjectState ReadBotNativeActiveSpellObjectState(
    const BotCastProcessingContext& context,
    bool allow_selection_state_handle = true) {
    auto& memory = *context.memory;
    const auto actor_address = context.actor_address;

    BotNativeActiveSpellObjectState state{};
    if (!memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &state.group) ||
        !memory.TryReadField(actor_address, kActorActiveCastSlotShortOffset, &state.slot) ||
        !memory.TryReadField(actor_address, kActorOwnerOffset, &state.world) ||
        !memory.TryReadField(actor_address, kActorAnimationSelectionStateOffset, &state.selection_state)) {
        state.group = kBotCastActorActiveCastGroupSentinel;
        state.slot = kBotCastActorActiveCastSlotSentinel;
        state.world = 0;
        state.selection_state = 0;
        return state;
    }
    if (allow_selection_state_handle &&
        (state.group == kBotCastActorActiveCastGroupSentinel ||
         state.slot == kBotCastActorActiveCastSlotSentinel)) {
        if (state.selection_state != 0 &&
            memory.IsReadableRange(state.selection_state, 0x10)) {
            std::uint8_t selection_group = kBotCastActorActiveCastGroupSentinel;
            std::uint16_t selection_slot = kBotCastActorActiveCastSlotSentinel;
            if (!memory.TryReadValue(
                    state.selection_state + kActorControlBrainTargetSlotOffset,
                    &selection_group) ||
                !memory.TryReadValue(
                    state.selection_state + kActorControlBrainTargetHandleOffset,
                    &selection_slot)) {
                selection_group = kBotCastActorActiveCastGroupSentinel;
                selection_slot = kBotCastActorActiveCastSlotSentinel;
            }
            if (selection_group != kBotCastActorActiveCastGroupSentinel &&
                selection_slot != kBotCastActorActiveCastSlotSentinel) {
                state.group = selection_group;
                state.slot = selection_slot;
                state.handle_from_selection_state = true;
            }
        }
    }
    if (state.group == kBotCastActorActiveCastGroupSentinel ||
        state.slot == kBotCastActorActiveCastSlotSentinel ||
        state.world == 0) {
        return state;
    }

    const auto lookup_address = memory.ResolveGameAddressOrZero(kActorWorldLookupObjectByHandle);
    state.lookup_attempted = lookup_address != 0;
    if (!state.lookup_attempted ||
        !CallActorWorldLookupObjectByHandleSafe(
            lookup_address,
            state.world,
            state.group,
            state.slot,
            &state.object,
            &state.lookup_exception)) {
        return state;
    }
    state.lookup_succeeded = state.object != 0;
    if (state.object == 0 || !memory.IsReadableRange(state.object, 0x240)) {
        return state;
    }

    if (!memory.TryReadField(state.object, kGameObjectTypeIdOffset, &state.object_type) ||
        !TryReadFiniteFloatField(state.object, kSpellObjectChargeOffset, &state.charge) ||
        !TryReadFiniteFloatField(state.object, kSpellObjectGrowthRateOffset, &state.growth_rate) ||
        !TryReadFiniteFloatField(state.object, kSpellObjectReleaseChargeOffset, &state.release_charge) ||
        !TryReadFiniteFloatField(state.object, kSpellObjectReleaseDamageOffset, &state.release_damage) ||
        !TryReadFiniteFloatField(state.object, kSpellObjectReleaseBaseDamageOffset, &state.release_base_damage) ||
        !TryReadFiniteFloatField(state.object, kSpellObjectMaxChargeOffset, &state.max_charge) ||
        !memory.TryReadField(state.object, kSpellObjectPhaseOffset, &state.phase) ||
        !memory.TryReadField(state.object, kSpellObjectReleaseTimerOffset, &state.release_timer) ||
        !TryReadFiniteFloatField(state.object, kObjectPositionXOffset, &state.object_x) ||
        !TryReadFiniteFloatField(state.object, kObjectPositionYOffset, &state.object_y) ||
        !TryReadFiniteFloatField(state.object, kObjectHeadingOffset, &state.object_heading) ||
        !TryReadFiniteFloatField(state.object, kObjectCollisionRadiusOffset, &state.object_radius)) {
        return state;
    }
    state.readable = true;
    state.boulder_max_size_reached =
        std::isfinite(state.charge) &&
        std::isfinite(state.max_charge) &&
        state.max_charge > 0.0f &&
        state.charge >= state.max_charge - 0.001f;
    return state;
}
