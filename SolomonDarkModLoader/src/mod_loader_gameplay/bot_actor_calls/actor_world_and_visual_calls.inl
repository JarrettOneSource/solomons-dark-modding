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

        const auto attach_address =
            *reinterpret_cast<uintptr_t*>(vtable + kGameplayActorAttachVfuncOffset);
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

bool CallGameplayActorDetachSafe(
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

        const auto detach_address =
            *reinterpret_cast<uintptr_t*>(vtable + kGameplayActorDetachVfuncOffset);
        if (detach_address == 0) {
            return false;
        }

        auto* detach_actor = reinterpret_cast<GameplayActorDetachFn>(detach_address);
        detach_actor(reinterpret_cast<void*>(subobject_address), reinterpret_cast<void*>(actor_address));
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

bool CallNativeRngFloatSafe(
    uintptr_t random_address,
    uintptr_t rng_state_address,
    float maximum,
    float* value,
    DWORD* exception_code) {
    if (value != nullptr) {
        *value = 0.0f;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* random_float =
        reinterpret_cast<NativeRngFloatFn>(random_address);
    if (random_float == nullptr ||
        rng_state_address == 0 ||
        value == nullptr ||
        !std::isfinite(maximum) ||
        maximum <= 0.0f) {
        return false;
    }

    __try {
        const auto sampled = random_float(
            reinterpret_cast<void*>(rng_state_address),
            maximum,
            0);
        if (!std::isfinite(sampled) ||
            sampled < 0.0f ||
            sampled > maximum) {
            return false;
        }
        *value = sampled;
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallAnimationBouncerVisualResolverSafe(
    uintptr_t resolver_address,
    uintptr_t bouncer_address,
    uintptr_t item_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* resolver =
        reinterpret_cast<AnimationBouncerVisualResolverFn>(
            resolver_address);
    if (resolver == nullptr ||
        bouncer_address == 0 ||
        item_address == 0) {
        return false;
    }

    __try {
        resolver(
            reinterpret_cast<void*>(bouncer_address),
            reinterpret_cast<void*>(item_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallWorldAnimationLaneInsertSafe(
    uintptr_t world_address,
    uintptr_t bouncer_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (world_address == 0 || bouncer_address == 0) {
        return false;
    }

    __try {
        const auto lane_address =
            world_address + kWorldAnimationLaneOffset;
        const auto vtable =
            *reinterpret_cast<uintptr_t*>(lane_address);
        if (vtable == 0) {
            return false;
        }
        const auto insert_address =
            *reinterpret_cast<uintptr_t*>(
                vtable +
                kWorldAnimationLaneInsertVfuncOffset);
        if (insert_address == 0 ||
            !ProcessMemory::Instance().IsExecutableRange(
                insert_address,
                1)) {
            return false;
        }
        auto* insert =
            reinterpret_cast<WorldAnimationLaneInsertFn>(
                insert_address);
        insert(
            reinterpret_cast<void*>(lane_address),
            reinterpret_cast<void*>(bouncer_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallAnimationBouncerPostInsertSafe(
    uintptr_t bouncer_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (bouncer_address == 0) {
        return false;
    }

    __try {
        const auto vtable =
            *reinterpret_cast<uintptr_t*>(bouncer_address);
        if (vtable == 0) {
            return false;
        }
        const auto post_insert_address =
            *reinterpret_cast<uintptr_t*>(
                vtable +
                kAnimationBouncerPostInsertVfuncOffset);
        if (post_insert_address == 0 ||
            !ProcessMemory::Instance().IsExecutableRange(
                post_insert_address,
                1)) {
            return false;
        }
        auto* post_insert =
            reinterpret_cast<AnimationBouncerPostInsertFn>(
                post_insert_address);
        post_insert(reinterpret_cast<void*>(bouncer_address));
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
