bool CallNativeModifierApplySafe(
    uintptr_t apply_address,
    uintptr_t modifier_address,
    uintptr_t actor_address,
    std::uint32_t* result,
    DWORD* exception_code) {
    if (result != nullptr) {
        *result = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* apply = reinterpret_cast<NativeModifierApplyFn>(apply_address);
    if (apply == nullptr || modifier_address == 0 || actor_address == 0) {
        return false;
    }
    __try {
        const auto value = apply(
            reinterpret_cast<void*>(modifier_address),
            reinterpret_cast<void*>(actor_address));
        if (result != nullptr) {
            *result = value;
        }
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPointerListAddSmartPointerSafe(
    uintptr_t add_address,
    uintptr_t list_address,
    uintptr_t control_block_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* add = reinterpret_cast<PointerListAddSmartPointerFn>(add_address);
    if (add == nullptr || list_address == 0 || control_block_address == 0) {
        return false;
    }
    __try {
        add(
            reinterpret_cast<void*>(list_address),
            control_block_address);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPointerListRemoveValueSafe(
    uintptr_t remove_address,
    uintptr_t list_address,
    uintptr_t value,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* remove = reinterpret_cast<PointerListRemoveValueFn>(
        remove_address);
    if (remove == nullptr || list_address == 0 || value == 0) {
        return false;
    }
    __try {
        remove(
            reinterpret_cast<void*>(list_address),
            value);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool DestroyUnownedNativeModifier(
    uintptr_t modifier_address,
    DWORD* exception_code) {
    if (modifier_address == 0) {
        return true;
    }
    return CallScalarDeletingDestructorSafe(
        modifier_address,
        1,
        exception_code);
}

bool CreateNativeModifierByType(
    std::uint32_t type_id,
    std::string_view label,
    uintptr_t* modifier_address,
    std::string* error_message) {
    if (modifier_address == nullptr || type_id == 0) {
        return false;
    }
    *modifier_address = 0;
    auto& memory = ProcessMemory::Instance();
    const auto factory_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    DWORD exception_code = 0;
    if (factory_address == 0 ||
        factory_context_address == 0 ||
        !CallGameObjectFactorySafe(
            factory_address,
            factory_context_address,
            static_cast<int>(type_id),
            modifier_address,
            &exception_code) ||
        *modifier_address == 0) {
        if (error_message != nullptr) {
            *error_message = std::string(label) +
                " factory failed seh=0x" + HexString(exception_code);
        }
        return false;
    }
    return true;
}

bool ApplyNativeModifierToActor(
    uintptr_t modifier_address,
    uintptr_t actor_address,
    std::string_view label,
    std::string* error_message) {
    auto& memory = ProcessMemory::Instance();
    uintptr_t modifier_vtable = 0;
    uintptr_t apply_address = 0;
    const auto damage_target_address =
        memory.ResolveGameAddressOrZero(kDamageContextTargetGlobal);
    if (modifier_address == 0 || actor_address == 0 ||
        damage_target_address == 0 ||
        !memory.TryReadValue(modifier_address, &modifier_vtable) ||
        modifier_vtable == 0 ||
        !memory.TryReadValue(modifier_vtable + 0x24, &apply_address) ||
        apply_address == 0 ||
        !memory.IsExecutableRange(apply_address, 1)) {
        if (error_message != nullptr) {
            *error_message = std::string(label) + " apply vfunc unavailable";
        }
        return false;
    }

    uintptr_t saved_damage_target = 0;
    const bool context_ready =
        memory.TryReadValue(damage_target_address, &saved_damage_target) &&
        memory.TryWriteValue(damage_target_address, actor_address);
    std::uint32_t apply_result = 0;
    DWORD exception_code = 0;
    const bool applied =
        context_ready &&
        CallNativeModifierApplySafe(
            apply_address,
            modifier_address,
            actor_address,
            &apply_result,
            &exception_code);
    if (context_ready) {
        (void)memory.TryWriteValue(
            damage_target_address,
            saved_damage_target);
    }
    if (!applied || apply_result == 0) {
        if (error_message != nullptr) {
            *error_message = std::string(label) +
                " OnApply rejected status seh=0x" +
                HexString(exception_code);
        }
        return false;
    }
    return true;
}

bool AttachOwnedNativeModifierToActor(
    uintptr_t modifier_address,
    uintptr_t actor_address,
    std::string_view label,
    std::string* error_message) {
    auto& memory = ProcessMemory::Instance();
    const auto operator_new_address =
        memory.ResolveGameAddressOrZero(kGameOperatorNew);
    DWORD exception_code = 0;
    uintptr_t control_block = 0;
    if (operator_new_address == 0 ||
        !CallGameOperatorNewSafe(
            operator_new_address,
            sizeof(std::uint32_t) * 2,
            &control_block,
            &exception_code) ||
        control_block == 0 ||
        !memory.TryWriteValue(control_block, modifier_address) ||
        !memory.TryWriteValue(
            control_block + sizeof(std::uint32_t),
            std::int32_t{1})) {
        if (control_block != 0) {
            const auto free_address =
                memory.ResolveGameAddressOrZero(kGameFree);
            (void)CallGameFreeSafe(
                free_address,
                control_block,
                &exception_code);
        }
        (void)DestroyUnownedNativeModifier(
            modifier_address,
            &exception_code);
        if (error_message != nullptr) {
            *error_message = std::string(label) +
                " smart-pointer allocation failed seh=0x" +
                HexString(exception_code);
        }
        return false;
    }

    const auto modifier_list_address =
        actor_address + kActorModifierListOffset;
    uintptr_t modifier_list_vtable = 0;
    uintptr_t add_address = 0;
    if (!memory.TryReadValue(
            modifier_list_address,
            &modifier_list_vtable) ||
        modifier_list_vtable == 0 ||
        !memory.TryReadValue(
            modifier_list_vtable + 0x10,
            &add_address) ||
        add_address == 0 ||
        !memory.IsExecutableRange(add_address, 1) ||
        !CallPointerListAddSmartPointerSafe(
            add_address,
            modifier_list_address,
            control_block,
            &exception_code)) {
        (void)ReleaseSmartPointerWrapperSafe(
            control_block,
            &exception_code);
        if (error_message != nullptr) {
            *error_message = std::string(label) +
                " list insertion failed seh=0x" +
                HexString(exception_code);
        }
        return false;
    }

    // The list owns the one remaining smart-pointer reference after its
    // by-value insertion temporaries balance. Releasing here would leave a
    // dangling modifier in the actor.
    return true;
}

bool InstallReplicatedPoisonModifier(
    uintptr_t actor_address,
    std::int32_t desired_duration_ticks,
    std::string* error_message,
    float damage_per_tick = 0.0f,
    std::int8_t source_slot = 1,
    bool duration_already_resisted = true) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 ||
        desired_duration_ticks <= 0 ||
        desired_duration_ticks >
            multiplayer::kParticipantPoisonMaxDurationTicks ||
        !std::isfinite(damage_per_tick) ||
        damage_per_tick < 0.0f ||
        damage_per_tick > 10000.0f) {
        if (error_message != nullptr) {
            *error_message = "invalid replicated poison install request";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t poison_modifier = 0;
    DWORD exception_code = 0;
    if (!CreateNativeModifierByType(
            kNativePoisonModifierTypeId,
            "Mod_Poisoned",
            &poison_modifier,
            error_message)) {
        return false;
    }

    const bool seeded =
        memory.TryWriteField(
            poison_modifier,
            kNativeModifierDurationTicksOffset,
            desired_duration_ticks) &&
        memory.TryWriteField(
            poison_modifier,
            kNativePoisonDamagePerTickOffset,
            damage_per_tick) &&
        memory.TryWriteField(
            poison_modifier,
            kNativePoisonSourceSlotOffset,
            source_slot);
    if (!seeded) {
        (void)DestroyUnownedNativeModifier(
            poison_modifier,
            &exception_code);
        if (error_message != nullptr) {
            *error_message = "failed to seed replicated Mod_Poisoned";
        }
        return false;
    }

    // Replicated durations have already paid the owner's Resist Poison
    // reduction. Suppress that one native transform during owner correction.
    uintptr_t progression_address = 0;
    float saved_resist_poison = 0.0f;
    const bool saved_resist_poison_valid =
        kProgressionResistPoisonFractionOffset != 0 &&
        TryResolveActorProgressionRuntime(
            actor_address,
            &progression_address) &&
        progression_address != 0 &&
        memory.TryReadField(
            progression_address,
            kProgressionResistPoisonFractionOffset,
            &saved_resist_poison);
    bool resist_suppressed = true;
    if (duration_already_resisted && saved_resist_poison_valid) {
        resist_suppressed = memory.TryWriteField(
            progression_address,
            kProgressionResistPoisonFractionOffset,
            0.0f);
    }
    const bool applied =
        resist_suppressed &&
        ApplyNativeModifierToActor(
            poison_modifier,
            actor_address,
            "Mod_Poisoned",
            error_message);
    if (duration_already_resisted && saved_resist_poison_valid) {
        (void)memory.TryWriteField(
            progression_address,
            kProgressionResistPoisonFractionOffset,
            saved_resist_poison);
    }
    if (!applied) {
        (void)DestroyUnownedNativeModifier(
            poison_modifier,
            &exception_code);
        return false;
    }

    std::int32_t finalized_duration_ticks = 0;
    const bool duration_finalized = duration_already_resisted
        ? memory.TryWriteField(
              poison_modifier,
              kNativeModifierDurationTicksOffset,
              desired_duration_ticks)
        : memory.TryReadField(
              poison_modifier,
              kNativeModifierDurationTicksOffset,
              &finalized_duration_ticks) &&
              finalized_duration_ticks > 0 &&
              finalized_duration_ticks <=
                  multiplayer::kParticipantPoisonMaxDurationTicks;
    if (!duration_finalized ||
        !memory.TryWriteField(
            poison_modifier,
            kNativePoisonDamagePerTickOffset,
            damage_per_tick) ||
        !memory.TryWriteField(
            poison_modifier,
            kNativePoisonSourceSlotOffset,
            source_slot)) {
        (void)DestroyUnownedNativeModifier(
            poison_modifier,
            &exception_code);
        if (error_message != nullptr) {
            *error_message = "failed to finalize replicated Mod_Poisoned";
        }
        return false;
    }

    if (!AttachOwnedNativeModifierToActor(
            poison_modifier,
            actor_address,
            "Mod_Poisoned",
            error_message)) {
        return false;
    }

    NativeWizardTransientStatusState verified_state;
    const bool verified =
        TryReadWizardActorTransientStatusState(
            actor_address,
            &verified_state) &&
        verified_state.poison_modifier_address == poison_modifier &&
        (verified_state.flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) != 0;
    if (!verified && error_message != nullptr) {
        *error_message = "replicated poison modifier was not retained by actor";
    }
    return verified;
}

bool InstallReplicatedWebbedModifier(
    uintptr_t actor_address,
    std::int32_t desired_duration_ticks,
    float strength,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 ||
        desired_duration_ticks <= 0 ||
        desired_duration_ticks >
            multiplayer::kParticipantWebbedMaxDurationTicks ||
        !std::isfinite(strength) ||
        strength <= 0.0f ||
        strength > multiplayer::kParticipantWebbedMaxStrength) {
        if (error_message != nullptr) {
            *error_message = "invalid replicated webbed install request";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t webbed_modifier = 0;
    DWORD exception_code = 0;
    if (!CreateNativeModifierByType(
            kNativeWebbedModifierTypeId,
            "Mod_Webbed",
            &webbed_modifier,
            error_message)) {
        return false;
    }

    const bool seeded =
        memory.TryWriteField(
            webbed_modifier,
            kNativeModifierDurationTicksOffset,
            desired_duration_ticks) &&
        memory.TryWriteField(
            webbed_modifier,
            kNativeWebbedStrengthOffset,
            strength) &&
        memory.TryWriteField(
            webbed_modifier,
            kNativeWebbedRequestedStrengthOffset,
            strength);
    if (!seeded ||
        !ApplyNativeModifierToActor(
            webbed_modifier,
            actor_address,
            "Mod_Webbed",
            error_message)) {
        (void)DestroyUnownedNativeModifier(
            webbed_modifier,
            &exception_code);
        if (!seeded && error_message != nullptr) {
            *error_message = "failed to seed replicated Mod_Webbed";
        }
        return false;
    }

    // Preserve the already-elapsed host-native values after the stock Apply
    // wrapper initializes its working fields.
    if (!memory.TryWriteField(
            webbed_modifier,
            kNativeModifierDurationTicksOffset,
            desired_duration_ticks) ||
        !memory.TryWriteField(
            webbed_modifier,
            kNativeWebbedStrengthOffset,
            strength) ||
        !memory.TryWriteField(
            webbed_modifier,
            kNativeWebbedRequestedStrengthOffset,
            strength)) {
        (void)DestroyUnownedNativeModifier(
            webbed_modifier,
            &exception_code);
        if (error_message != nullptr) {
            *error_message = "failed to finalize replicated Mod_Webbed";
        }
        return false;
    }
    if (!AttachOwnedNativeModifierToActor(
            webbed_modifier,
            actor_address,
            "Mod_Webbed",
            error_message)) {
        return false;
    }

    NativeWizardTransientStatusState verified_state;
    const bool verified =
        TryReadWizardActorTransientStatusState(
            actor_address,
            &verified_state) &&
        verified_state.webbed_modifier_address == webbed_modifier &&
        (verified_state.flags &
         multiplayer::ParticipantTransientStatusFlagWebbed) != 0;
    if (!verified && error_message != nullptr) {
        *error_message = "replicated webbed modifier was not retained by actor";
    }
    return verified;
}

struct NativeTransientStatusMapping {
    std::uint8_t flag = 0;
    std::int32_t skill_entry = -1;
    std::uint32_t installed_modifier_type = 0;
    const char* label = "unknown";
};

constexpr std::array<NativeTransientStatusMapping, 2>
    kNativeTransientStatusMappings = {{
        {
            multiplayer::ParticipantTransientStatusFlagPlanewalker,
            0x0C,
            0,
            "planewalker",
        },
        {
            multiplayer::ParticipantTransientStatusFlagStoneskin,
            0x2E,
            kNativeStoneskinModifierTypeId,
            "stoneskin",
        },
    }};

constexpr std::uint8_t kNativeTransientStatusValueMask =
    multiplayer::ParticipantTransientStatusFlagPlanewalker |
    multiplayer::ParticipantTransientStatusFlagStoneskin;

bool RemoveAllNativeActorModifiersByType(
    uintptr_t actor_address,
    std::uint32_t modifier_type,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 || modifier_type == 0) {
        if (error_message != nullptr) {
            *error_message = "invalid native modifier removal request";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto modifier_list_address =
        actor_address + kActorModifierListOffset;
    uintptr_t modifier_list_vtable = 0;
    uintptr_t remove_address = 0;
    if (!memory.TryReadValue(
            modifier_list_address,
            &modifier_list_vtable) ||
        modifier_list_vtable == 0 ||
        !memory.TryReadValue(
            modifier_list_vtable + kPointerListRemoveValueVtableOffset,
            &remove_address) ||
        remove_address == 0 ||
        !memory.IsExecutableRange(remove_address, 1)) {
        if (error_message != nullptr) {
            *error_message = "native modifier list removal seam unavailable";
        }
        return false;
    }

    constexpr std::int32_t kMaximumRemovalCount = 32;
    for (std::int32_t removal_count = 0;
         removal_count < kMaximumRemovalCount;
         ++removal_count) {
        std::int32_t modifier_count = 0;
        if (!memory.TryReadField(
                actor_address,
                kActorModifierListCountOffset,
                &modifier_count) ||
            modifier_count < 0 ||
            modifier_count > 512) {
            if (error_message != nullptr) {
                *error_message = "native modifier list count is invalid";
            }
            return false;
        }
        if (modifier_count == 0) {
            return true;
        }

        uintptr_t modifier_storage = 0;
        if (!memory.TryReadField(
                actor_address,
                kActorModifierListStorageOffset,
                &modifier_storage) ||
            modifier_storage == 0) {
            if (error_message != nullptr) {
                *error_message = "native modifier list storage is unavailable";
            }
            return false;
        }

        uintptr_t matching_control_block = 0;
        uintptr_t matching_modifier = 0;
        for (std::int32_t index = 0; index < modifier_count; ++index) {
            uintptr_t control_block = 0;
            uintptr_t modifier = 0;
            std::uint32_t type_id = 0;
            if (memory.TryReadValue(
                    modifier_storage +
                        static_cast<std::size_t>(index) * sizeof(uintptr_t),
                    &control_block) &&
                control_block != 0 &&
                memory.TryReadValue(control_block, &modifier) &&
                modifier != 0 &&
                memory.TryReadField(
                    modifier,
                    kNativeModifierTypeIdOffset,
                    &type_id) &&
                type_id == modifier_type) {
                matching_control_block = control_block;
                matching_modifier = modifier;
                break;
            }
        }
        if (matching_control_block == 0 || matching_modifier == 0) {
            return true;
        }

        DWORD exception_code = 0;
        if (!memory.TryWriteField(
                matching_modifier,
                kNativeModifierDurationTicksOffset,
                std::int32_t{0}) ||
            !CallPointerListRemoveValueSafe(
                remove_address,
                modifier_list_address,
                matching_control_block,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "native modifier removal failed seh=0x" +
                    HexString(exception_code);
            }
            return false;
        }
    }

    if (error_message != nullptr) {
        *error_message = "native modifier removal exceeded safety bound";
    }
    return false;
}

#include "transient_status_participant_reconciliation.inl"
