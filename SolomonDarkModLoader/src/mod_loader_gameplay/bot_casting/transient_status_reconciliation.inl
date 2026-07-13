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

bool CallPointerListRemoveSmartPointerSafe(
    uintptr_t remove_address,
    uintptr_t list_address,
    uintptr_t control_block_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* remove = reinterpret_cast<PointerListRemoveSmartPointerFn>(
        remove_address);
    if (remove == nullptr || list_address == 0 || control_block_address == 0) {
        return false;
    }
    __try {
        remove(
            reinterpret_cast<void*>(list_address),
            control_block_address);
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
        !std::isfinite(damage_per_tick) ||
        damage_per_tick < 0.0f ||
        damage_per_tick > 10000.0f) {
        if (error_message != nullptr) {
            *error_message = "invalid replicated poison install request";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context_address =
        memory.ResolveGameAddressOrZero(kGameObjectFactoryContextGlobal);
    const auto operator_new_address =
        memory.ResolveGameAddressOrZero(kGameOperatorNew);
    const auto damage_target_address =
        memory.ResolveGameAddressOrZero(kDamageContextTargetGlobal);
    if (factory_address == 0 ||
        factory_context_address == 0 ||
        operator_new_address == 0 ||
        damage_target_address == 0) {
        if (error_message != nullptr) {
            *error_message = "replicated poison native seams unavailable";
        }
        return false;
    }

    uintptr_t poison_modifier = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectFactorySafe(
            factory_address,
            factory_context_address,
            static_cast<int>(kNativePoisonModifierTypeId),
            &poison_modifier,
            &exception_code) ||
        poison_modifier == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Mod_Poisoned factory failed seh=0x" +
                HexString(exception_code);
        }
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
        (void)DestroyUnownedNativeModifier(poison_modifier, &exception_code);
        if (error_message != nullptr) {
            *error_message = "failed to seed replicated Mod_Poisoned";
        }
        return false;
    }

    uintptr_t modifier_vtable = 0;
    uintptr_t apply_address = 0;
    if (!memory.TryReadValue(poison_modifier, &modifier_vtable) ||
        modifier_vtable == 0 ||
        !memory.TryReadValue(modifier_vtable + 0x24, &apply_address) ||
        apply_address == 0 ||
        !memory.IsExecutableRange(apply_address, 1)) {
        (void)DestroyUnownedNativeModifier(poison_modifier, &exception_code);
        if (error_message != nullptr) {
            *error_message = "Mod_Poisoned apply vfunc unavailable";
        }
        return false;
    }

    // Replicated durations have already paid the owner's Resist Poison
    // reduction. Suppress the native transform for those installs so observer
    // and owner-correction clones are not reduced a second time. The queued
    // behavior probe deliberately leaves the transform enabled.
    uintptr_t progression_address = 0;
    float saved_resist_poison = 0.0f;
    bool saved_resist_poison_valid =
        kProgressionResistPoisonFractionOffset != 0 &&
        TryResolveActorProgressionRuntime(
            actor_address,
            &progression_address) &&
        progression_address != 0 &&
        memory.TryReadField(
            progression_address,
            kProgressionResistPoisonFractionOffset,
            &saved_resist_poison);
    uintptr_t saved_damage_target = 0;
    const bool saved_damage_target_valid =
        memory.TryReadValue(damage_target_address, &saved_damage_target);
    bool context_ready =
        saved_damage_target_valid &&
        memory.TryWriteValue(damage_target_address, actor_address);
    if (duration_already_resisted && saved_resist_poison_valid) {
        context_ready =
            memory.TryWriteField(
                progression_address,
                kProgressionResistPoisonFractionOffset,
                0.0f) &&
            context_ready;
    }

    std::uint32_t apply_result = 0;
    const bool applied =
        context_ready &&
        CallNativeModifierApplySafe(
            apply_address,
            poison_modifier,
            actor_address,
            &apply_result,
            &exception_code);
    if (duration_already_resisted && saved_resist_poison_valid) {
        (void)memory.TryWriteField(
            progression_address,
            kProgressionResistPoisonFractionOffset,
            saved_resist_poison);
    }
    if (saved_damage_target_valid) {
        (void)memory.TryWriteValue(
            damage_target_address,
            saved_damage_target);
    }
    if (!applied || apply_result == 0) {
        (void)DestroyUnownedNativeModifier(poison_modifier, &exception_code);
        if (error_message != nullptr) {
            *error_message =
                "Mod_Poisoned OnApply rejected replicated status seh=0x" +
                HexString(exception_code);
        }
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
    // Observer clones pass zero damage; an owner correction carries the
    // already-resisted native damage captured by the host mirror.
    if (!duration_finalized ||
        !memory.TryWriteField(
            poison_modifier,
            kNativePoisonDamagePerTickOffset,
            damage_per_tick) ||
        !memory.TryWriteField(
            poison_modifier,
            kNativePoisonSourceSlotOffset,
            source_slot)) {
        (void)DestroyUnownedNativeModifier(poison_modifier, &exception_code);
        if (error_message != nullptr) {
            *error_message = "failed to finalize replicated Mod_Poisoned";
        }
        return false;
    }

    uintptr_t control_block = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            sizeof(std::uint32_t) * 2,
            &control_block,
            &exception_code) ||
        control_block == 0 ||
        !memory.TryWriteValue(control_block, poison_modifier) ||
        !memory.TryWriteValue(
            control_block + sizeof(std::uint32_t),
            std::int32_t{1})) {
        if (control_block != 0) {
            const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
            (void)CallGameFreeSafe(
                free_address,
                control_block,
                &exception_code);
        }
        (void)DestroyUnownedNativeModifier(poison_modifier, &exception_code);
        if (error_message != nullptr) {
            *error_message = "failed to allocate replicated poison smart pointer";
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
        // The stock wrapper at 0x00624610 constructs and releases its own
        // by-value smart pointer around the virtual list insertion. Release
        // only our original local reference here.
        (void)ReleaseSmartPointerWrapperSafe(control_block, &exception_code);
        if (error_message != nullptr) {
            *error_message =
                "failed to insert replicated poison modifier seh=0x" +
                HexString(exception_code);
        }
        return false;
    }

    // The stock wrapper transfers the original reference into the list. Its
    // two nested by-value temporaries balance internally, and the post-call
    // count is exactly one: the list's ownership. Releasing here would leave
    // a dangling modifier in PlayerActor's native list.

    std::uint8_t verified_flags = 0;
    std::int32_t verified_duration = 0;
    uintptr_t verified_modifier = 0;
    const bool verified =
        TryReadWizardActorTransientStatusState(
            actor_address,
            &verified_flags,
            &verified_duration,
            &verified_modifier) &&
        verified_modifier == poison_modifier &&
        (verified_flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) != 0;
    if (!verified && error_message != nullptr) {
        *error_message = "replicated poison modifier was not retained by actor";
    }
    return verified;
}

bool ReconcileNativeRemoteParticipantTransientStatuses(
    ParticipantEntityBinding* binding,
    std::uint64_t now_ms) {
    if (binding == nullptr ||
        binding->actor_address == 0 ||
        binding->bot_id == 0 ||
        !IsNativeRemoteParticipantBinding(binding)) {
        return false;
    }

    const auto runtime = multiplayer::SnapshotRuntimeState();
    const auto* participant =
        multiplayer::FindParticipant(runtime, binding->bot_id);
    if (participant == nullptr) {
        return false;
    }
    const auto desired_flags =
        participant->runtime.transient_status_flags;
    if ((desired_flags &
         multiplayer::ParticipantTransientStatusFlagSnapshotValid) == 0) {
        return false;
    }

    std::uint8_t native_flags = 0;
    std::int32_t native_duration = 0;
    uintptr_t poison_modifier = 0;
    uintptr_t poison_control_block = 0;
    if (!TryReadWizardActorTransientStatusState(
            binding->actor_address,
            &native_flags,
            &native_duration,
            &poison_modifier,
            &poison_control_block)) {
        return false;
    }

    const bool desired_poisoned =
        participant->runtime.life_current > 0.0f &&
        (desired_flags &
         multiplayer::ParticipantTransientStatusFlagPoisoned) != 0 &&
        participant->runtime.poison_remaining_ticks > 0;
    auto& memory = ProcessMemory::Instance();
    if (!desired_poisoned) {
        if (poison_modifier == 0) {
            return true;
        }
        const float zero_damage = 0.0f;
        const std::int8_t remote_visual_source_slot = 1;
        const bool neutralized =
            memory.TryWriteField(
                poison_modifier,
                kNativeModifierDurationTicksOffset,
                std::int32_t{0}) &&
            memory.TryWriteField(
                poison_modifier,
                kNativePoisonDamagePerTickOffset,
                zero_damage) &&
            memory.TryWriteField(
                poison_modifier,
                kNativePoisonSourceSlotOffset,
                remote_visual_source_slot);
        const auto modifier_list_address =
            binding->actor_address + kActorModifierListOffset;
        uintptr_t modifier_list_vtable = 0;
        uintptr_t remove_address = 0;
        DWORD exception_code = 0;
        const bool removed =
            neutralized &&
            poison_control_block != 0 &&
            memory.TryReadValue(
                modifier_list_address,
                &modifier_list_vtable) &&
            modifier_list_vtable != 0 &&
            memory.TryReadValue(
                modifier_list_vtable +
                    kPointerListRemoveSmartPointerVtableOffset,
                &remove_address) &&
            remove_address != 0 &&
            memory.IsExecutableRange(remove_address, 1) &&
            CallPointerListRemoveSmartPointerSafe(
                remove_address,
                modifier_list_address,
                poison_control_block,
                &exception_code);
        std::uint8_t verified_flags = 0;
        std::int32_t verified_duration = 0;
        uintptr_t verified_modifier = 0;
        const bool cleared =
            removed &&
            TryReadWizardActorTransientStatusState(
                binding->actor_address,
                &verified_flags,
                &verified_duration,
                &verified_modifier) &&
            verified_modifier == 0;
        if (cleared) {
            Log(
                "[bots] remote transient poison cleared. bot_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(binding->actor_address));
        } else {
            Log(
                "[bots] remote transient poison clear failed. bot_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(binding->actor_address) +
                " control=" + HexString(poison_control_block) +
                " seh=0x" + HexString(exception_code));
        }
        return cleared;
    }

    const auto desired_duration = (std::clamp)(
        participant->runtime.poison_remaining_ticks,
        std::int32_t{1},
        multiplayer::kParticipantPoisonMaxDurationTicks);
    if (poison_modifier == 0) {
        std::string error_message;
        const bool installed = InstallReplicatedPoisonModifier(
            binding->actor_address,
            desired_duration,
            &error_message);
        Log(
            "[bots] remote transient poison install. bot_id=" +
            std::to_string(binding->bot_id) +
            " actor=" + HexString(binding->actor_address) +
            " desired_ticks=" + std::to_string(desired_duration) +
            " installed=" + std::to_string(installed ? 1 : 0) +
            " error=" + error_message);
        return installed;
    }

    const float zero_damage = 0.0f;
    const std::int8_t remote_visual_source_slot = 1;
    bool reconciled =
        memory.TryWriteField(
            poison_modifier,
            kNativePoisonDamagePerTickOffset,
            zero_damage) &&
        memory.TryWriteField(
            poison_modifier,
            kNativePoisonSourceSlotOffset,
            remote_visual_source_slot);
    constexpr std::int32_t kPoisonDurationDriftToleranceTicks = 20;
    const auto duration_delta =
        static_cast<std::int64_t>(native_duration) -
        static_cast<std::int64_t>(desired_duration);
    if (duration_delta < -kPoisonDurationDriftToleranceTicks ||
        duration_delta > kPoisonDurationDriftToleranceTicks) {
        reconciled =
            memory.TryWriteField(
                poison_modifier,
                kNativeModifierDurationTicksOffset,
                desired_duration) &&
            reconciled;
    }
    (void)now_ms;
    return reconciled;
}
