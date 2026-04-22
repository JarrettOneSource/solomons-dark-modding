bool CallPlayerActorEnsureProgressionHandleSafe(
    uintptr_t ensure_progression_handle_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* ensure_progression_handle =
        reinterpret_cast<PlayerActorNoArgMethodFn>(ensure_progression_handle_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (ensure_progression_handle == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        ensure_progression_handle(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorRefreshRuntimeHandlesSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* refresh_runtime_handles = reinterpret_cast<PlayerActorRefreshRuntimeHandlesFn>(refresh_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (refresh_runtime_handles == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        refresh_runtime_handles(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorProgressionRefreshSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* refresh_progression = reinterpret_cast<ActorProgressionRefreshFn>(refresh_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (refresh_progression == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        auto& memory = ProcessMemory::Instance();
        const auto progression_handle =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
        const auto progression_runtime =
            progression_handle != 0 ? ReadSmartPointerInnerObject(progression_handle) : 0;
        if (progression_runtime == 0) {
            return false;
        }

        refresh_progression(reinterpret_cast<void*>(progression_runtime));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallSkillsWizardBuildPrimarySpellSafe(
    uintptr_t build_address,
    uintptr_t progression_address,
    float primary_entry_arg,
    float combo_entry_arg,
    DWORD* exception_code) {
    auto* build_primary_spell =
        reinterpret_cast<SkillsWizardBuildPrimarySpellFn>(build_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (build_primary_spell == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        build_primary_spell(
            reinterpret_cast<void*>(progression_address),
            primary_entry_arg,
            combo_entry_arg);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerAppearanceApplyChoiceSafe(
    uintptr_t apply_choice_address,
    uintptr_t progression_address,
    int choice_id,
    int ensure_assets,
    DWORD* exception_code) {
    auto* apply_choice = reinterpret_cast<PlayerAppearanceApplyChoiceFn>(apply_choice_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (apply_choice == nullptr || progression_address == 0 || choice_id < 0) {
        return false;
    }

    __try {
        apply_choice(reinterpret_cast<void*>(progression_address), choice_id, ensure_assets);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool EnterLocalPlayerCastShim(
    const ParticipantEntityBinding* binding,
    LocalPlayerCastShimState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = LocalPlayerCastShimState{};
    if (binding == nullptr ||
        binding->actor_address == 0 ||
        binding->gameplay_slot <= 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    state->actor_address = binding->actor_address;
    state->saved_actor_slot = memory.ReadFieldOr<std::uint8_t>(
        binding->actor_address,
        kActorSlotOffset,
        static_cast<std::uint8_t>(0));

    if (!memory.TryWriteField<std::uint8_t>(
            binding->actor_address,
            kActorSlotOffset,
            static_cast<std::uint8_t>(0))) {
        *state = LocalPlayerCastShimState{};
        return false;
    }

    state->active = true;
    return true;
}

void LeaveLocalPlayerCastShim(const LocalPlayerCastShimState& state) {
    if (!state.active) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::uint8_t>(
        state.actor_address,
        kActorSlotOffset,
        state.saved_actor_slot);
}

bool CallGameNpcSetMoveGoalSafe(
    uintptr_t set_move_goal_address,
    uintptr_t npc_address,
    std::uint8_t mode,
    int follow_flag,
    float x,
    float y,
    float extra_scalar,
    DWORD* exception_code,
    SehExceptionDetails* exception_details) {
    auto* set_move_goal = reinterpret_cast<GameNpcSetMoveGoalFn>(set_move_goal_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (exception_details != nullptr) {
        *exception_details = {};
    }
    if (set_move_goal == nullptr || npc_address == 0) {
        return false;
    }

    __try {
        set_move_goal(reinterpret_cast<void*>(npc_address), mode, follow_flag, x, y, extra_scalar);
        return true;
    } __except (
        exception_details != nullptr
            ? CaptureSehDetails(GetExceptionInformation(), exception_details)
            : CaptureSehCode(GetExceptionInformation(), exception_code)) {
        if (exception_code != nullptr && exception_details != nullptr) {
            *exception_code = exception_details->code;
        }
        return false;
    }
}

bool CallGameNpcSetTrackedSlotAssistSafe(
    uintptr_t set_tracked_slot_assist_address,
    uintptr_t npc_address,
    int slot_index,
    int require_callback,
    DWORD* exception_code,
    SehExceptionDetails* exception_details) {
    auto* set_tracked_slot_assist =
        reinterpret_cast<GameNpcSetTrackedSlotAssistFn>(set_tracked_slot_assist_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (exception_details != nullptr) {
        *exception_details = {};
    }
    if (set_tracked_slot_assist == nullptr || npc_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        set_tracked_slot_assist(reinterpret_cast<void*>(npc_address), slot_index, require_callback);
        return true;
    } __except (
        exception_details != nullptr
            ? CaptureSehDetails(GetExceptionInformation(), exception_details)
            : CaptureSehCode(GetExceptionInformation(), exception_code)) {
        if (exception_code != nullptr && exception_details != nullptr) {
            *exception_code = exception_details->code;
        }
        return false;
    }
}

bool CallGameplayActorAttachSafe(
    uintptr_t gameplay_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (gameplay_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        const auto subobject_address = gameplay_address + kGameplayActorAttachSubobjectOffset;
        const auto vtable = *reinterpret_cast<uintptr_t*>(subobject_address);
        if (vtable == 0) {
            return false;
        }

        const auto attach_address = *reinterpret_cast<uintptr_t*>(vtable + 0x10);
        if (attach_address == 0) {
            return false;
        }

        auto* attach_actor = reinterpret_cast<GameplayActorAttachFn>(attach_address);
        attach_actor(reinterpret_cast<void*>(subobject_address), reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorBuildRenderDescriptorFromSourceSafe(
    uintptr_t build_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* build_descriptor = reinterpret_cast<ActorBuildRenderDescriptorFromSourceFn>(build_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (build_descriptor == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        build_descriptor(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallWizardCloneFromSourceActorSafe(
    uintptr_t clone_address,
    uintptr_t source_actor_address,
    uintptr_t* clone_actor_address,
    DWORD* exception_code) {
    if (clone_actor_address != nullptr) {
        *clone_actor_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* clone_from_source = reinterpret_cast<WizardCloneFromSourceActorFn>(clone_address);
    if (clone_from_source == nullptr || source_actor_address == 0) {
        return false;
    }

    __try {
        auto* clone_actor = clone_from_source(reinterpret_cast<void*>(source_actor_address));
        if (clone_actor_address != nullptr) {
            *clone_actor_address = reinterpret_cast<uintptr_t>(clone_actor);
        }
        return clone_actor != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallStandaloneWizardVisualLinkAttachSafe(
    uintptr_t attach_address,
    uintptr_t self_address,
    uintptr_t value_address,
    DWORD* exception_code) {
    auto* attach = reinterpret_cast<StandaloneWizardVisualLinkAttachFn>(attach_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (attach == nullptr || self_address == 0) {
        return false;
    }

    __try {
        return attach(reinterpret_cast<void*>(self_address), reinterpret_cast<void*>(value_address)) != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldRegisterGameplaySlotActorSafe(
    uintptr_t register_address,
    uintptr_t world_address,
    int slot_index,
    DWORD* exception_code) {
    auto* register_slot_actor =
        reinterpret_cast<ActorWorldRegisterGameplaySlotActorFn>(register_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (register_slot_actor == nullptr || world_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        register_slot_actor(reinterpret_cast<void*>(world_address), slot_index);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallWorldCellGridRebindActorSafe(
    uintptr_t rebind_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* rebind_actor = reinterpret_cast<WorldCellGridRebindActorFn>(rebind_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (rebind_actor == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        rebind_actor(
            reinterpret_cast<void*>(world_address + kActorOwnerMovementControllerOffset),
            reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorMoveByDeltaSafe(
    uintptr_t move_by_delta_address,
    uintptr_t actor_address,
    float move_x,
    float move_y,
    DWORD* exception_code) {
    auto* move_by_delta = reinterpret_cast<ActorMoveByDeltaFn>(move_by_delta_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (move_by_delta == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        move_by_delta(reinterpret_cast<void*>(actor_address), move_x, move_y, 0);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorMoveStepSafe(
    uintptr_t move_step_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    float move_x,
    float move_y,
    unsigned int flags,
    DWORD* exception_code,
    std::uint32_t* result) {
    auto* move_step = reinterpret_cast<PlayerActorMoveStepFn>(move_step_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (result != nullptr) {
        *result = 0;
    }
    if (move_step == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        const auto move_result =
            move_step(reinterpret_cast<void*>(world_address), reinterpret_cast<void*>(actor_address), move_x, move_y, flags);
        if (result != nullptr) {
            *result = move_result;
        }
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallSpellCastDispatcherSafe(
    uintptr_t dispatcher_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* dispatcher = reinterpret_cast<SpellCastDispatcherFn>(dispatcher_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (dispatcher == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        dispatcher(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPurePrimarySpellStartSafe(
    uintptr_t startup_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* startup = reinterpret_cast<PurePrimarySpellStartFn>(startup_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (startup == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        startup(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallCastActiveHandleCleanupSafe(
    uintptr_t cleanup_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* cleanup = reinterpret_cast<CastActiveHandleCleanupFn>(cleanup_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (cleanup == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        cleanup(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

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
