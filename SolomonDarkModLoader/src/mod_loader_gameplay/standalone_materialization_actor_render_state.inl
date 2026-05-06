struct ActorRenderBuildSnapshot {
    std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize> descriptor{};
    std::uint32_t source_profile_unknown74_mirror = 0;
    std::uint16_t source_profile_unknown56_mirror = 0;
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
    (void)memory.TryReadField(
        actor_address,
        kGameNpcSourceProfile74MirrorOffset,
        &snapshot.source_profile_unknown74_mirror);
    (void)memory.TryReadField(
        actor_address,
        kGameNpcSourceProfile56MirrorOffset,
        &snapshot.source_profile_unknown56_mirror);
    (void)memory.TryReadField(actor_address, kActorRenderVariantPrimaryOffset, &snapshot.variant_primary);
    (void)memory.TryReadField(actor_address, kActorRenderVariantSecondaryOffset, &snapshot.variant_secondary);
    (void)memory.TryReadField(actor_address, kActorRenderWeaponTypeOffset, &snapshot.weapon_type);
    (void)memory.TryReadField(actor_address, kActorRenderSelectionByteOffset, &snapshot.render_selection);
    (void)memory.TryReadField(actor_address, kActorRenderVariantTertiaryOffset, &snapshot.variant_tertiary);
    (void)memory.TryReadField(actor_address, kActorHubVisualAttachmentPtrOffset, &snapshot.attachment_address);
    return snapshot;
}

bool RestoreActorRenderBuildSnapshot(
    uintptr_t actor_address,
    const ActorRenderBuildSnapshot& snapshot,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Actor render-state restore requires a live actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(
            actor_address,
            kActorRenderVariantPrimaryOffset,
            snapshot.variant_primary) ||
        !memory.TryWriteField(
            actor_address,
            kActorRenderVariantSecondaryOffset,
            snapshot.variant_secondary) ||
        !memory.TryWriteField(
            actor_address,
            kActorRenderWeaponTypeOffset,
            snapshot.weapon_type) ||
        !memory.TryWriteField(
            actor_address,
            kActorRenderSelectionByteOffset,
            snapshot.render_selection) ||
        !memory.TryWriteField(
            actor_address,
            kActorRenderVariantTertiaryOffset,
            snapshot.variant_tertiary) ||
        !memory.TryWriteValue(
            actor_address + kGameNpcSourceProfile74MirrorOffset,
            snapshot.source_profile_unknown74_mirror) ||
        !memory.TryWriteValue(
            actor_address + kGameNpcSourceProfile56MirrorOffset,
            snapshot.source_profile_unknown56_mirror) ||
        !memory.TryWrite(
            actor_address + kActorHubVisualDescriptorBlockOffset,
            snapshot.descriptor.data(),
            snapshot.descriptor.size()) ||
        !memory.TryWriteField(
            actor_address,
            kActorHubVisualAttachmentPtrOffset,
            snapshot.attachment_address)) {
        if (error_message != nullptr) {
            *error_message = "Failed to restore the actor render-state snapshot.";
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

void ClearActorLiveDescriptorBlock(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize> zero_descriptor{};
    (void)memory.TryWrite(
        actor_address + kActorHubVisualDescriptorBlockOffset,
        zero_descriptor.data(),
        zero_descriptor.size());
    (void)memory.TryWriteField<uintptr_t>(
        actor_address,
        kActorHubVisualAttachmentPtrOffset,
        0);
}

void NormalizeGameplaySlotBotSyntheticVisualState(uintptr_t actor_address) {
    ClearActorSyntheticVisualSourceState(actor_address);
}
