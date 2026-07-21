bool CallActorWorldUnregisterSafe(
    uintptr_t actor_world_unregister_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    char remove_from_container,
    DWORD* exception_code) {
    auto* actor_world_unregister = reinterpret_cast<ActorWorldUnregisterFn>(actor_world_unregister_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_world_unregister == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        actor_world_unregister(
            reinterpret_cast<void*>(world_address),
            reinterpret_cast<void*>(actor_address),
            remove_from_container);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorRequestRetirementSafe(
    uintptr_t actor_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0 || kActorRequestRetirementVfuncOffset == 0) {
        return false;
    }

    __try {
        const auto vtable = *reinterpret_cast<uintptr_t*>(actor_address);
        if (vtable == 0) {
            return false;
        }
        const auto retire_address = *reinterpret_cast<uintptr_t*>(
            vtable + kActorRequestRetirementVfuncOffset);
        if (retire_address == 0 ||
            !ProcessMemory::Instance().IsExecutableRange(retire_address, 1)) {
            return false;
        }

        auto* request_retirement =
            reinterpret_cast<ActorRequestRetirementFn>(retire_address);
        request_retirement(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldUnregisterGameplaySlotActorSafe(
    uintptr_t unregister_address,
    uintptr_t world_address,
    int slot_index,
    DWORD* exception_code) {
    auto* unregister_slot_actor =
        reinterpret_cast<ActorWorldUnregisterGameplaySlotActorFn>(unregister_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (unregister_slot_actor == nullptr || world_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        unregister_slot_actor(reinterpret_cast<void*>(world_address), slot_index);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallScalarDeletingDestructorSafe(
    uintptr_t object_address,
    int flags,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (object_address == 0) {
        return true;
    }

    __try {
        const auto vtable = *reinterpret_cast<uintptr_t*>(object_address);
        if (vtable == 0) {
            return false;
        }

        const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
        if (destructor_address == 0) {
            return false;
        }

        auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
        destructor(reinterpret_cast<void*>(object_address), flags);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallScalarDeletingDestructorDetailedSafe(
    uintptr_t object_address,
    int flags,
    SehExceptionDetails* exception_details) {
    if (exception_details != nullptr) {
        *exception_details = {};
    }
    if (object_address == 0) {
        return true;
    }

    __try {
        const auto vtable = *reinterpret_cast<uintptr_t*>(object_address);
        if (vtable == 0) {
            return false;
        }

        const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
        if (destructor_address == 0) {
            return false;
        }

        auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
        destructor(reinterpret_cast<void*>(object_address), flags);
        return true;
    } __except (CaptureSehDetails(GetExceptionInformation(), exception_details)) {
        return false;
    }
}

bool CallActorGetProfileSafe(
    uintptr_t fn_address,
    uintptr_t actor_address,
    DWORD* exception_code,
    uintptr_t* out_profile) {
    auto* get_profile = reinterpret_cast<ActorGetProfileFn>(fn_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (out_profile != nullptr) {
        *out_profile = 0;
    }
    if (get_profile == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        auto* profile = get_profile(reinterpret_cast<void*>(actor_address));
        if (out_profile != nullptr) {
            *out_profile = reinterpret_cast<uintptr_t>(profile);
        }
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TryResolveWizardActorProfileAddress(
    uintptr_t actor_address,
    uintptr_t* profile_address) {
    if (profile_address == nullptr || actor_address == 0 || kActorGetProfile == 0) {
        return false;
    }
    *profile_address = 0;

    DWORD exception_code = 0;
    return CallActorGetProfileSafe(
               ProcessMemory::Instance().ResolveGameAddressOrZero(kActorGetProfile),
               actor_address,
               &exception_code,
               profile_address) &&
           *profile_address != 0;
}

bool TryReadWizardActorPersistentStatusFlags(
    uintptr_t actor_address,
    std::uint8_t* status_flags) {
    if (status_flags == nullptr || actor_address == 0 || kActorGetProfile == 0) {
        return false;
    }
    *status_flags = 0;

    uintptr_t profile_address = 0;
    if (!TryResolveWizardActorProfileAddress(
            actor_address,
            &profile_address)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t firewalker_active = 0;
    std::uint8_t mindstar_active = 0;
    std::uint8_t regenerate_active = 0;
    if (!memory.TryReadField(
            profile_address,
            kWizardProfileFirewalkerActiveOffset,
            &firewalker_active) ||
        !memory.TryReadField(
            profile_address,
            kWizardProfileMindstarActiveOffset,
            &mindstar_active) ||
        !memory.TryReadField(
            profile_address,
            kWizardProfileRegenerateActiveOffset,
            &regenerate_active)) {
        return false;
    }

    std::uint8_t flags =
        multiplayer::ParticipantPersistentStatusFlagSnapshotValid;
    if (firewalker_active != 0) {
        flags |= multiplayer::ParticipantPersistentStatusFlagFirewalker;
    }
    if (mindstar_active != 0) {
        flags |= multiplayer::ParticipantPersistentStatusFlagMindstar;
    }
    if (regenerate_active != 0) {
        flags |= multiplayer::ParticipantPersistentStatusFlagRegenerate;
    }
    *status_flags = flags;
    return true;
}

struct NativeWizardTransientStatusState {
    std::uint8_t flags = 0;
    std::int32_t poison_remaining_ticks = 0;
    uintptr_t poison_modifier_address = 0;
    uintptr_t poison_control_block_address = 0;
    std::int32_t webbed_remaining_ticks = 0;
    float webbed_strength = 0.0f;
    uintptr_t webbed_modifier_address = 0;
    uintptr_t webbed_control_block_address = 0;
};

bool TryReadWizardActorTransientStatusState(
    uintptr_t actor_address,
    NativeWizardTransientStatusState* state) {
    if (state == nullptr || actor_address == 0) {
        return false;
    }
    *state = NativeWizardTransientStatusState{};
    auto& memory = ProcessMemory::Instance();
    std::uint32_t render_drive_flags = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorRenderDriveFlagsOffset,
            &render_drive_flags)) {
        return false;
    }
    std::uint8_t flags =
        multiplayer::ParticipantTransientStatusFlagSnapshotValid;
    if ((render_drive_flags & 0x10u) != 0) {
        flags |= multiplayer::ParticipantTransientStatusFlagPlanewalker;
    }

    std::int32_t modifier_count = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorModifierListCountOffset,
            &modifier_count) ||
        modifier_count < 0 ||
        modifier_count > 512) {
        return false;
    }

    if (modifier_count == 0) {
        state->flags = flags;
        return true;
    }

    uintptr_t modifier_storage = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorModifierListStorageOffset,
            &modifier_storage) ||
        modifier_storage == 0) {
        return false;
    }

    std::int32_t longest_poison_duration = 0;
    uintptr_t poison_modifier = 0;
    uintptr_t poison_control_block = 0;
    std::int32_t longest_webbed_duration = 0;
    float longest_webbed_strength = 0.0f;
    uintptr_t webbed_modifier = 0;
    uintptr_t webbed_control_block = 0;
    for (std::int32_t index = 0; index < modifier_count; ++index) {
        uintptr_t control_block = 0;
        uintptr_t modifier = 0;
        std::uint32_t type_id = 0;
        if (!memory.TryReadValue(
                modifier_storage +
                    static_cast<std::size_t>(index) * sizeof(uintptr_t),
                &control_block) ||
            control_block == 0 ||
            !memory.TryReadValue(control_block, &modifier) ||
            modifier == 0 ||
            !memory.TryReadField(
                modifier,
                kNativeModifierTypeIdOffset,
                &type_id)) {
            continue;
        }

        if (type_id == kNativeStoneskinModifierTypeId) {
            flags |= multiplayer::ParticipantTransientStatusFlagStoneskin;
            continue;
        }
        if (type_id == kNativeWebbedModifierTypeId) {
            std::int32_t duration_ticks = 0;
            float strength = 0.0f;
            if (!memory.TryReadField(
                    modifier,
                    kNativeModifierDurationTicksOffset,
                    &duration_ticks) ||
                !memory.TryReadField(
                    modifier,
                    kNativeWebbedStrengthOffset,
                    &strength) ||
                !std::isfinite(strength)) {
                return false;
            }
            if (webbed_modifier == 0 ||
                duration_ticks > longest_webbed_duration) {
                webbed_modifier = modifier;
                webbed_control_block = control_block;
                longest_webbed_duration = duration_ticks;
                longest_webbed_strength = strength;
            }
            continue;
        }
        if (type_id != kNativePoisonModifierTypeId) {
            continue;
        }

        std::int32_t duration_ticks = 0;
        if (!memory.TryReadField(
                modifier,
                kNativeModifierDurationTicksOffset,
                &duration_ticks)) {
            return false;
        }
        if (poison_modifier == 0 ||
            duration_ticks > longest_poison_duration) {
            poison_modifier = modifier;
            poison_control_block = control_block;
            longest_poison_duration = duration_ticks;
        }
    }

    if (poison_modifier != 0) {
        state->poison_modifier_address = poison_modifier;
        state->poison_control_block_address = poison_control_block;
        if (longest_poison_duration > 0) {
            flags |= multiplayer::ParticipantTransientStatusFlagPoisoned;
            state->poison_remaining_ticks = (std::min)(
                longest_poison_duration,
                multiplayer::kParticipantPoisonMaxDurationTicks);
        }
    }
    if (webbed_modifier != 0) {
        state->webbed_modifier_address = webbed_modifier;
        state->webbed_control_block_address = webbed_control_block;
        if (longest_webbed_duration > 0 && longest_webbed_strength > 0.0f) {
            flags |= multiplayer::ParticipantTransientStatusFlagWebbed;
            state->webbed_remaining_ticks = (std::min)(
                longest_webbed_duration,
                multiplayer::kParticipantWebbedMaxDurationTicks);
            state->webbed_strength = (std::clamp)(
                longest_webbed_strength,
                0.0f,
                multiplayer::kParticipantWebbedMaxStrength);
        }
    }

    state->flags = flags;
    return true;
}

bool CallProfileResolveStatEntrySafe(
    uintptr_t fn_address,
    uintptr_t container_address,
    int stat_index,
    DWORD* exception_code,
    uintptr_t* out_entry) {
    auto* resolve_stat_entry = reinterpret_cast<ProfileResolveStatEntryFn>(fn_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (out_entry != nullptr) {
        *out_entry = 0;
    }
    if (resolve_stat_entry == nullptr || container_address == 0) {
        return false;
    }

    __try {
        auto* entry = resolve_stat_entry(reinterpret_cast<void*>(container_address), stat_index);
        if (out_entry != nullptr) {
            *out_entry = reinterpret_cast<uintptr_t>(entry);
        }
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallStatBookComputeValueSafe(
    uintptr_t fn_address,
    uintptr_t stat_book_address,
    float base_value,
    int entry_idx,
    char apply_modifier,
    DWORD* exception_code,
    float* out_value) {
    auto* compute_value = reinterpret_cast<StatBookComputeValueFn>(fn_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (out_value != nullptr) {
        *out_value = 0.0f;
    }
    if (compute_value == nullptr || stat_book_address == 0) {
        return false;
    }

    __try {
        const auto value = compute_value(
            reinterpret_cast<void*>(stat_book_address), base_value, entry_idx, apply_modifier);
        if (out_value != nullptr) {
            *out_value = value;
        }
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}
