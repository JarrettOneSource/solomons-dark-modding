struct BotActiveSpellObjectSnapshot {
    std::uint8_t group = 0xFF;
    std::uint16_t slot = 0xFFFF;
    std::uintptr_t world = 0;
    std::uintptr_t selection_state = 0;
    std::uintptr_t object = 0;
    std::uintptr_t vtable = 0;
    std::uintptr_t update_fn = 0;
    std::uintptr_t release_secondary_fn = 0;
    std::uintptr_t release_finalize_fn = 0;
    std::uint32_t object_type = 0;
    std::uint32_t object_f74_raw = 0;
    std::uint32_t object_f1f0_raw = 0;
    std::uint32_t object_f1fc_raw = 0;
    std::uint32_t object_f22c = 0;
    std::uint32_t object_f230 = 0;
    float object_x = 0.0f;
    float object_y = 0.0f;
    float object_heading = 0.0f;
    float object_radius = 0.0f;
    float object_f74 = 0.0f;
    float object_f1f0 = 0.0f;
    float object_f1fc = 0.0f;
    bool readable = false;
    bool handle_from_selection_state = false;
    bool boulder_max_size_reached = false;
};

BotActiveSpellObjectSnapshot ReadBotActiveSpellObjectSnapshot(
    const BotCastProcessingContext& context,
    bool allow_selection_state_fallback = true) {
    auto& memory = *context.memory;
    const auto actor_address = context.actor_address;

    BotActiveSpellObjectSnapshot snapshot{};
    snapshot.group =
        memory.ReadFieldOr<std::uint8_t>(
            actor_address,
            kActorActiveCastGroupByteOffset,
            kBotCastActorActiveCastGroupSentinel);
    snapshot.slot =
        memory.ReadFieldOr<std::uint16_t>(
            actor_address,
            kActorActiveCastSlotShortOffset,
            kBotCastActorActiveCastSlotSentinel);
    snapshot.world = memory.ReadFieldOr<std::uintptr_t>(actor_address, kActorOwnerOffset, 0);
    snapshot.selection_state =
        memory.ReadFieldOr<std::uintptr_t>(
            actor_address,
            kActorAnimationSelectionStateOffset,
            0);
    if (allow_selection_state_fallback &&
        (snapshot.group == kBotCastActorActiveCastGroupSentinel ||
         snapshot.slot == kBotCastActorActiveCastSlotSentinel)) {
        if (snapshot.selection_state != 0 &&
            memory.IsReadableRange(snapshot.selection_state, 0x10)) {
            const auto selection_group =
                memory.ReadValueOr<std::uint8_t>(
                    snapshot.selection_state + 0x4,
                    kBotCastActorActiveCastGroupSentinel);
            const auto selection_slot =
                memory.ReadValueOr<std::uint16_t>(
                    snapshot.selection_state + 0x6,
                    kBotCastActorActiveCastSlotSentinel);
            if (selection_group != kBotCastActorActiveCastGroupSentinel &&
                selection_slot != kBotCastActorActiveCastSlotSentinel) {
                snapshot.group = selection_group;
                snapshot.slot = selection_slot;
                snapshot.handle_from_selection_state = true;
            }
        }
    }
    if (snapshot.group == kBotCastActorActiveCastGroupSentinel ||
        snapshot.slot == kBotCastActorActiveCastSlotSentinel ||
        snapshot.world == 0) {
        return snapshot;
    }

    const std::uintptr_t entry_address =
        snapshot.world + kActorWorldBucketTableOffset +
        static_cast<std::uintptr_t>(
            static_cast<std::uint32_t>(snapshot.group) * kActorWorldBucketStride +
            static_cast<std::uint32_t>(snapshot.slot)) *
            sizeof(std::uintptr_t);
    snapshot.object = memory.ReadValueOr<std::uintptr_t>(entry_address, 0);
    if (snapshot.object == 0 || !memory.IsReadableRange(snapshot.object, 0x240)) {
        return snapshot;
    }

    snapshot.readable = true;
    snapshot.vtable = memory.ReadFieldOr<std::uintptr_t>(snapshot.object, 0x00, 0);
    if (snapshot.vtable != 0 && memory.IsReadableRange(snapshot.vtable, 0x74)) {
        snapshot.update_fn = memory.ReadValueOr<std::uintptr_t>(snapshot.vtable + 0x1C, 0);
        snapshot.release_secondary_fn = memory.ReadValueOr<std::uintptr_t>(snapshot.vtable + 0x6C, 0);
        snapshot.release_finalize_fn = memory.ReadValueOr<std::uintptr_t>(snapshot.vtable + 0x70, 0);
    }
    snapshot.object_type = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x08, 0);
    snapshot.object_f74 = memory.ReadFieldOr<float>(snapshot.object, 0x74, 0.0f);
    snapshot.object_f1f0 = memory.ReadFieldOr<float>(snapshot.object, 0x1F0, 0.0f);
    snapshot.object_f1fc = memory.ReadFieldOr<float>(snapshot.object, 0x1FC, 0.0f);
    snapshot.object_f74_raw = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x74, 0);
    snapshot.object_f1f0_raw = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x1F0, 0);
    snapshot.object_f1fc_raw = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x1FC, 0);
    snapshot.object_f22c = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x22C, 0);
    snapshot.object_f230 = memory.ReadFieldOr<std::uint32_t>(snapshot.object, 0x230, 0);
    snapshot.object_x = memory.ReadFieldOr<float>(snapshot.object, 0x18, 0.0f);
    snapshot.object_y = memory.ReadFieldOr<float>(snapshot.object, 0x1C, 0.0f);
    snapshot.object_heading = memory.ReadFieldOr<float>(snapshot.object, 0x6C, 0.0f);
    snapshot.object_radius = memory.ReadFieldOr<float>(snapshot.object, 0x70, 0.0f);
    snapshot.boulder_max_size_reached =
        std::isfinite(snapshot.object_f74) &&
        std::isfinite(snapshot.object_f1fc) &&
        snapshot.object_f1fc > 0.0f &&
        snapshot.object_f74 >= snapshot.object_f1fc - 0.001f;
    return snapshot;
}
