struct ActorRenderBuildSnapshot {
    std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize> descriptor{};
    std::uint8_t variant_primary = 0;
    std::uint8_t variant_secondary = 0;
    std::uint8_t weapon_type = 0;
    std::uint8_t render_selection = 0;
    std::uint8_t variant_tertiary = 0;
    uintptr_t attachment_address = 0;
};

ActorRenderBuildSnapshot CaptureActorRenderBuildSnapshot(uintptr_t actor_address) {
    ActorRenderBuildSnapshot snapshot;
    if (actor_address == 0) {
        return snapshot;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryRead(
        actor_address + kActorHubVisualDescriptorBlockOffset,
        snapshot.descriptor.data(),
        snapshot.descriptor.size());
    (void)memory.TryReadField(actor_address, kActorRenderVariantPrimaryOffset, &snapshot.variant_primary);
    (void)memory.TryReadField(actor_address, kActorRenderVariantSecondaryOffset, &snapshot.variant_secondary);
    (void)memory.TryReadField(actor_address, kActorRenderWeaponTypeOffset, &snapshot.weapon_type);
    (void)memory.TryReadField(actor_address, kActorRenderSelectionByteOffset, &snapshot.render_selection);
    (void)memory.TryReadField(actor_address, kActorRenderVariantTertiaryOffset, &snapshot.variant_tertiary);
    (void)memory.TryReadField(actor_address, kActorHubVisualAttachmentPtrOffset, &snapshot.attachment_address);
    return snapshot;
}

bool ApplySourceActorRenderSelectorsToTargetActor(
    uintptr_t target_actor_address,
    const ActorRenderBuildSnapshot& source_snapshot,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (target_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Render selector publication requires a live target actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(
            target_actor_address,
            kActorRenderVariantPrimaryOffset,
            source_snapshot.variant_primary) ||
        !memory.TryWriteField(
            target_actor_address,
            kActorRenderVariantSecondaryOffset,
            source_snapshot.variant_secondary) ||
        !memory.TryWriteField(
            target_actor_address,
            kActorRenderWeaponTypeOffset,
            static_cast<std::uint8_t>(0)) ||
        !memory.TryWriteField(
            target_actor_address,
            kActorRenderSelectionByteOffset,
            source_snapshot.render_selection) ||
        !memory.TryWriteField(
            target_actor_address,
            kActorRenderVariantTertiaryOffset,
            source_snapshot.variant_tertiary)) {
        if (error_message != nullptr) {
            *error_message = "Failed to publish native-built render selector bytes.";
        }
        return false;
    }

    return true;
}

void ClearActorSyntheticVisualSourceState(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::int32_t>(
        actor_address,
        kActorHubVisualSourceKindOffset,
        0);
    (void)memory.TryWriteField<uintptr_t>(
        actor_address,
        kActorHubVisualSourceProfileOffset,
        0);
    (void)memory.TryWriteField<uintptr_t>(
        actor_address,
        kActorHubVisualSourceAuxPointerOffset,
        0);
}

void NormalizeGameplaySlotBotSyntheticVisualState(uintptr_t actor_address) {
    ClearActorSyntheticVisualSourceState(actor_address);
}
