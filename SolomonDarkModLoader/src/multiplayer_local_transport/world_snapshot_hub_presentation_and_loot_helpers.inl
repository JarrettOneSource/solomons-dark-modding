bool IsHubStudentActorType(std::uint32_t native_type_id) {
    return native_type_id == 0x138A;
}

bool IsNamedHubNpcActorType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case 0x1389: // PerkWitch
    case 0x138B: // Annalist
    case 0x138C: // PotionGuy
    case 0x138D: // ItemsGuy
    case 0x138F: // Tyrannia
    case 0x1390: // Teacher
        return true;
    default:
        return false;
    }
}

bool IsSaneNamedHubNpcPresentationFloat(float value) {
    constexpr float kMaxMagnitude = 65536.0f;
    return std::isfinite(value) && value >= -kMaxMagnitude && value <= kMaxMagnitude;
}

bool PopulateNamedHubNpcIdleAnimatorSnapshot(
    uintptr_t actor_address,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 ||
        snapshot == nullptr ||
        kNamedHubNpcIdleAnimationBlockOffset == 0) {
        return false;
    }

    constexpr std::size_t kActiveOffset = 0x00;
    constexpr std::size_t kPhaseOffset = 0x04;
    constexpr std::size_t kFrameOffset = 0x08;
    constexpr std::size_t kRateOffset = 0x0C;
    constexpr std::size_t kAmplitudeOffset = 0x10;
    constexpr std::size_t kEnabledOffset = 0x14;
    const auto block = actor_address + kNamedHubNpcIdleAnimationBlockOffset;
    auto& state = snapshot->named_hub_npc;
    auto& memory = ProcessMemory::Instance();
    if (!memory.TryReadValue(block + kActiveOffset, &state.idle_active) ||
        !memory.TryReadValue(block + kEnabledOffset, &state.idle_enabled) ||
        !memory.TryReadValue(block + kPhaseOffset, &state.idle_phase) ||
        !memory.TryReadValue(block + kFrameOffset, &state.idle_frame) ||
        !memory.TryReadValue(block + kRateOffset, &state.idle_rate) ||
        !memory.TryReadValue(block + kAmplitudeOffset, &state.idle_amplitude) ||
        state.idle_active > 1 ||
        state.idle_enabled > 1 ||
        !IsSaneNamedHubNpcPresentationFloat(state.idle_phase) ||
        !IsSaneNamedHubNpcPresentationFloat(state.idle_frame) ||
        !IsSaneNamedHubNpcPresentationFloat(state.idle_rate) ||
        !IsSaneNamedHubNpcPresentationFloat(state.idle_amplitude)) {
        return false;
    }

    snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcIdleAnimator;
    return true;
}

void PopulateNamedHubNpcPresentationSnapshot(
    uintptr_t actor_address,
    std::uint32_t native_type_id,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 ||
        snapshot == nullptr ||
        !IsNamedHubNpcActorType(native_type_id) ||
        kNamedHubNpcIdleAnimationBlockOffset == 0) {
        return;
    }

    constexpr std::size_t kPhaseOffset = 0x04;
    constexpr std::size_t kFrameOffset = 0x08;
    constexpr std::size_t kRateOffset = 0x0C;
    const auto idle_block = actor_address + kNamedHubNpcIdleAnimationBlockOffset;
    auto& state = snapshot->named_hub_npc;
    auto& memory = ProcessMemory::Instance();

    switch (native_type_id) {
    case 0x1389: // PerkWitch: +0x144 angle/frame and +0x148 angular rate.
        if (memory.TryReadValue(idle_block + kFrameOffset, &state.idle_frame) &&
            memory.TryReadValue(idle_block + kRateOffset, &state.idle_rate) &&
            IsSaneNamedHubNpcPresentationFloat(state.idle_frame) &&
            IsSaneNamedHubNpcPresentationFloat(state.idle_rate)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcWitchOrbit;
        }
        return;
    case 0x138B: // Annalist
    case 0x138D: // ItemsGuy
        (void)PopulateNamedHubNpcIdleAnimatorSnapshot(actor_address, snapshot);
        return;
    case 0x138C: { // PotionGuy
        (void)PopulateNamedHubNpcIdleAnimatorSnapshot(actor_address, snapshot);
        if (kNamedHubNpcTypeSpecificStateBlockOffset == 0) {
            return;
        }
        const auto type_block = actor_address + kNamedHubNpcTypeSpecificStateBlockOffset;
        if (memory.TryReadValue(type_block + 0x00, &state.motion_position) &&
            memory.TryReadValue(type_block + 0x04, &state.motion_direction) &&
            memory.TryReadValue(type_block + 0x08, &state.timer) &&
            IsSaneNamedHubNpcPresentationFloat(state.motion_position) &&
            IsSaneNamedHubNpcPresentationFloat(state.motion_direction) &&
            state.timer >= 0 && state.timer <= 100000) {
            snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcPotionMotion;
        }
        return;
    }
    case 0x138F: { // Tyrannia
        (void)PopulateNamedHubNpcIdleAnimatorSnapshot(actor_address, snapshot);
        if (kNamedHubNpcTypeSpecificStateBlockOffset == 0) {
            return;
        }
        const auto type_block = actor_address + kNamedHubNpcTypeSpecificStateBlockOffset;
        if (memory.TryReadValue(type_block + 0x00, &state.timer) &&
            memory.TryReadValue(type_block + 0x04, &state.pose) &&
            memory.TryReadValue(type_block + 0x08, &state.render_scale) &&
            state.timer >= -1 && state.timer <= 100000 &&
            state.pose >= 0 && state.pose <= 2 &&
            IsSaneNamedHubNpcPresentationFloat(state.render_scale)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcTyranniaPose;
        }
        return;
    }
    case 0x1390: // Teacher: dedicated cycle plus one-shot effect latch.
        if (kNamedHubNpcTypeSpecificStateBlockOffset != 0 &&
            memory.TryReadValue(idle_block + kPhaseOffset, &state.idle_phase) &&
            memory.TryReadValue(idle_block + kFrameOffset, &state.idle_frame) &&
            memory.TryReadValue(
                actor_address + kNamedHubNpcTypeSpecificStateBlockOffset,
                &state.type_state_byte) &&
            IsSaneNamedHubNpcPresentationFloat(state.idle_phase) &&
            IsSaneNamedHubNpcPresentationFloat(state.idle_frame) &&
            state.type_state_byte <= 1) {
            snapshot->presentation_flags |= WorldActorPresentationFlagNamedHubNpcTeacherCycle;
        }
        return;
    default:
        return;
    }
}

bool IsSharedHubFactoryActorType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case 0x1389:
    case 0x138A:
    case 0x138B:
    case 0x138C:
    case 0x138D:
    case 0x138F:
    case 0x1390:
        return true;
    default:
        return false;
    }
}

void PopulateWorldActorPresentationSnapshot(
    uintptr_t actor_address,
    std::uint32_t native_type_id,
    ParticipantSceneIntentKind scene_kind,
    bool tracked_enemy,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 || snapshot == nullptr) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    if (scene_kind == ParticipantSceneIntentKind::Run &&
        tracked_enemy &&
        native_type_id == 0x03E9 &&
        kActorWalkCyclePrimaryOffset != 0 &&
        kActorWalkCycleSecondaryOffset != 0) {
        auto read_sane_animation_float = [&](std::size_t offset, float* value) -> bool {
            if (value == nullptr ||
                !memory.TryReadField(actor_address, offset, value) ||
                !std::isfinite(*value)) {
                return false;
            }
            constexpr float kMaxSaneRunEnemyLocomotionMagnitude = 4096.0f;
            return *value >= -kMaxSaneRunEnemyLocomotionMagnitude &&
                   *value <= kMaxSaneRunEnemyLocomotionMagnitude;
        };

        float walk_cycle_primary = 0.0f;
        float walk_cycle_secondary = 0.0f;
        if (read_sane_animation_float(kActorWalkCyclePrimaryOffset, &walk_cycle_primary) &&
            read_sane_animation_float(kActorWalkCycleSecondaryOffset, &walk_cycle_secondary)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagLocomotionFloats;
            snapshot->walk_cycle_primary = walk_cycle_primary;
            snapshot->walk_cycle_secondary = walk_cycle_secondary;
        }
    }

    if (scene_kind == ParticipantSceneIntentKind::SharedHub &&
        IsSharedHubFactoryActorType(native_type_id) &&
        kActorAnimationDriveStateByteOffset != 0) {
        std::uint32_t drive_word = 0;
        if (memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &drive_word)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagAnimationDriveWord;
            snapshot->anim_drive_state_word = drive_word;
        }
    }

    if (scene_kind == ParticipantSceneIntentKind::SharedHub &&
        IsNamedHubNpcActorType(native_type_id)) {
        PopulateNamedHubNpcPresentationSnapshot(actor_address, native_type_id, snapshot);
    }

    if (scene_kind != ParticipantSceneIntentKind::SharedHub ||
        !IsHubStudentActorType(native_type_id)) {
        return;
    }

    if (kActorRenderVariantPrimaryOffset != 0 &&
        kActorRenderVariantSecondaryOffset != 0 &&
        kActorRenderWeaponTypeOffset != 0 &&
        kActorRenderSelectionByteOffset != 0 &&
        kActorRenderVariantTertiaryOffset != 0) {
        bool have_variant_bytes = true;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantPrimaryOffset,
            &snapshot->render_variant_primary) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantSecondaryOffset,
            &snapshot->render_variant_secondary) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderWeaponTypeOffset,
            &snapshot->render_weapon_type) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderSelectionByteOffset,
            &snapshot->render_selection_byte) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantTertiaryOffset,
            &snapshot->render_variant_tertiary) && have_variant_bytes;
        if (have_variant_bytes) {
            snapshot->presentation_flags |= WorldActorPresentationFlagStudentVariantBytes;
        }
    }

    if (kStudentVisualStateBlockOffset != 0 &&
        memory.TryRead(
            actor_address + kStudentVisualStateBlockOffset,
            snapshot->student_visual_state,
            kWorldActorStudentVisualStateBytes)) {
        snapshot->presentation_flags |= WorldActorPresentationFlagStudentVisualState;
    }

    if (kStudentBookPaletteBlockOffset == 0) {
        return;
    }

    constexpr std::size_t kStudentBookPaletteColorsOffset = 0x04;
    constexpr std::size_t kStudentBookPaletteRadialOffsetsOffset = 0x54;
    constexpr std::size_t kStudentBookPaletteAngularOffsetsOffset = 0x68;
    constexpr float kMaxSaneStudentBookPaletteMagnitude = 4096.0f;
    const auto palette_address = actor_address + kStudentBookPaletteBlockOffset;
    std::uint32_t palette_count = 0;
    if (!memory.TryReadValue(palette_address, &palette_count) ||
        palette_count > kWorldActorStudentBookPaletteMaxEntries) {
        return;
    }

    bool palette_valid = true;
    for (std::size_t index = 0; index < palette_count; ++index) {
        auto& entry = snapshot->student_book_palette[index];
        const auto color_address =
            palette_address + kStudentBookPaletteColorsOffset + index * sizeof(float) * 4;
        palette_valid = memory.TryRead(color_address, &entry.red, sizeof(float) * 4) &&
                        memory.TryReadValue(
                            palette_address + kStudentBookPaletteRadialOffsetsOffset +
                                index * sizeof(float),
                            &entry.radial_offset) &&
                        memory.TryReadValue(
                            palette_address + kStudentBookPaletteAngularOffsetsOffset +
                                index * sizeof(float),
                            &entry.angular_offset);
        const float values[] = {
            entry.red,
            entry.green,
            entry.blue,
            entry.alpha,
            entry.radial_offset,
            entry.angular_offset,
        };
        for (const float value : values) {
            palette_valid = palette_valid && std::isfinite(value) &&
                            value >= -kMaxSaneStudentBookPaletteMagnitude &&
                            value <= kMaxSaneStudentBookPaletteMagnitude;
        }
        if (!palette_valid) {
            return;
        }
    }

    snapshot->student_book_palette_count = palette_count;
    snapshot->presentation_flags |= WorldActorPresentationFlagStudentBookPalette;
}

std::int32_t RoundRewardAmountToInt(float amount) {
    if (!std::isfinite(amount) || amount <= 0.0f) {
        return 0;
    }
    if (amount >= static_cast<float>((std::numeric_limits<std::int32_t>::max)())) {
        return (std::numeric_limits<std::int32_t>::max)();
    }
    return static_cast<std::int32_t>(std::lround(amount));
}

bool TryResolveLootOrbResourceKind(std::int32_t resource_kind, LootOrbResourceKind* kind) {
    if (kind == nullptr) {
        return false;
    }
    switch (resource_kind) {
    case static_cast<std::int32_t>(LootOrbResourceKind::Health):
        *kind = LootOrbResourceKind::Health;
        return true;
    case static_cast<std::int32_t>(LootOrbResourceKind::Mana):
        *kind = LootOrbResourceKind::Mana;
        return true;
    default:
        return false;
    }
}

float LootOrbScaleForResourceKind(LootOrbResourceKind kind) {
    return kind == LootOrbResourceKind::Health ? kOrbHealthRewardScale : kOrbManaRewardScale;
}

float ComputeLootOrbResourceDelta(std::int32_t resource_kind, float raw_value) {
    LootOrbResourceKind kind = LootOrbResourceKind::Health;
    if (!TryResolveLootOrbResourceKind(resource_kind, &kind) ||
        !std::isfinite(raw_value) ||
        raw_value <= kLootPickupResourceEpsilon) {
        return 0.0f;
    }
    const float delta = raw_value * LootOrbScaleForResourceKind(kind);
    if (!std::isfinite(delta) || delta <= kLootPickupResourceEpsilon) {
        return 0.0f;
    }
    return (std::min)(delta, kLootPickupMaxResourceDelta);
}
