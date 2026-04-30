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
