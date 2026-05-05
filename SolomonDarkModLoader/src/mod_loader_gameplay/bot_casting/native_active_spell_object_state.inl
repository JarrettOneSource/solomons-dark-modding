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
    bool allow_selection_state_fallback = true) {
    auto& memory = *context.memory;
    const auto actor_address = context.actor_address;

    BotNativeActiveSpellObjectState state{};
    state.group =
        memory.ReadFieldOr<std::uint8_t>(
            actor_address,
            kActorActiveCastGroupByteOffset,
            kBotCastActorActiveCastGroupSentinel);
    state.slot =
        memory.ReadFieldOr<std::uint16_t>(
            actor_address,
            kActorActiveCastSlotShortOffset,
            kBotCastActorActiveCastSlotSentinel);
    state.world = memory.ReadFieldOr<std::uintptr_t>(actor_address, kActorOwnerOffset, 0);
    state.selection_state =
        memory.ReadFieldOr<std::uintptr_t>(
            actor_address,
            kActorAnimationSelectionStateOffset,
            0);
    if (allow_selection_state_fallback &&
        (state.group == kBotCastActorActiveCastGroupSentinel ||
         state.slot == kBotCastActorActiveCastSlotSentinel)) {
        if (state.selection_state != 0 &&
            memory.IsReadableRange(state.selection_state, 0x10)) {
            const auto selection_group =
                memory.ReadValueOr<std::uint8_t>(
                    state.selection_state + kActorControlBrainTargetSlotOffset,
                    kBotCastActorActiveCastGroupSentinel);
            const auto selection_slot =
                memory.ReadValueOr<std::uint16_t>(
                    state.selection_state + kActorControlBrainTargetHandleOffset,
                    kBotCastActorActiveCastSlotSentinel);
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

    state.readable = true;
    state.object_type =
        memory.ReadFieldOr<std::uint32_t>(state.object, kGameObjectTypeIdOffset, 0);
    state.charge =
        memory.ReadFieldOr<float>(state.object, kSpellObjectChargeOffset, 0.0f);
    state.growth_rate =
        memory.ReadFieldOr<float>(state.object, kSpellObjectGrowthRateOffset, 0.0f);
    state.release_charge =
        memory.ReadFieldOr<float>(state.object, kSpellObjectReleaseChargeOffset, 0.0f);
    state.release_damage =
        memory.ReadFieldOr<float>(state.object, kSpellObjectReleaseDamageOffset, 0.0f);
    state.release_base_damage =
        memory.ReadFieldOr<float>(state.object, kSpellObjectReleaseBaseDamageOffset, 0.0f);
    state.max_charge =
        memory.ReadFieldOr<float>(state.object, kSpellObjectMaxChargeOffset, 0.0f);
    state.phase =
        memory.ReadFieldOr<std::uint32_t>(state.object, kSpellObjectPhaseOffset, 0);
    state.release_timer =
        memory.ReadFieldOr<std::uint32_t>(state.object, kSpellObjectReleaseTimerOffset, 0);
    state.object_x = memory.ReadFieldOr<float>(state.object, kObjectPositionXOffset, 0.0f);
    state.object_y = memory.ReadFieldOr<float>(state.object, kObjectPositionYOffset, 0.0f);
    state.object_heading =
        memory.ReadFieldOr<float>(state.object, kObjectHeadingOffset, 0.0f);
    state.object_radius =
        memory.ReadFieldOr<float>(state.object, kObjectCollisionRadiusOffset, 0.0f);
    state.boulder_max_size_reached =
        std::isfinite(state.charge) &&
        std::isfinite(state.max_charge) &&
        state.max_charge > 0.0f &&
        state.charge >= state.max_charge - 0.001f;
    return state;
}
