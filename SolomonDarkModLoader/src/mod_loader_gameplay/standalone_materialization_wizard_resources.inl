void ReleaseStandaloneWizardSmartPointerResource(
    uintptr_t actor_address,
    std::size_t handle_offset,
    std::size_t runtime_state_offset,
    uintptr_t wrapper_address,
    uintptr_t inner_address,
    const char* label) {
    auto& memory = ProcessMemory::Instance();
    if (actor_address != 0 &&
        memory.ReadFieldOr<uintptr_t>(actor_address, handle_offset, 0) == wrapper_address) {
        (void)memory.TryWriteField<uintptr_t>(actor_address, handle_offset, 0);
        (void)memory.TryWriteField<uintptr_t>(actor_address, runtime_state_offset, 0);
    }

    if (wrapper_address != 0) {
        DWORD exception_code = 0;
        if (!ReleaseSmartPointerWrapperSafe(wrapper_address, &exception_code)) {
            Log(
                "[bots] standalone " + std::string(label) + " release skipped. wrapper=" +
                HexString(wrapper_address) +
                " inner=" + HexString(inner_address) +
                " code=0x" + HexString(exception_code));
        }
    }
}

void ReleaseStandaloneWizardVisualResources(
    uintptr_t actor_address,
    uintptr_t progression_wrapper_address,
    uintptr_t progression_inner_address,
    uintptr_t equip_wrapper_address,
    uintptr_t equip_inner_address) {
    ReleaseStandaloneWizardSmartPointerResource(
        actor_address,
        kActorProgressionHandleOffset,
        kActorProgressionRuntimeStateOffset,
        progression_wrapper_address,
        progression_inner_address,
        "visual");
    ReleaseStandaloneWizardSmartPointerResource(
        actor_address,
        kActorEquipHandleOffset,
        kActorEquipRuntimeStateOffset,
        equip_wrapper_address,
        equip_inner_address,
        "equip");
}

bool CreateStandaloneWizardEquipWrapper(
    uintptr_t* wrapper_address,
    uintptr_t* inner_address,
    std::string* error_message) {
    if (wrapper_address != nullptr) {
        *wrapper_address = 0;
    }
    if (inner_address != nullptr) {
        *inner_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& memory = ProcessMemory::Instance();
    const auto operator_new_address = memory.ResolveGameAddressOrZero(kGameOperatorNew);
    const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
    const auto equip_ctor_address = memory.ResolveGameAddressOrZero(kStandaloneWizardEquipCtor);
    if (operator_new_address == 0 || free_address == 0 || equip_ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the standalone equip entrypoints.";
        }
        return false;
    }

    uintptr_t equip_object_memory = 0;
    DWORD exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            kStandaloneWizardEquipSize,
            &equip_object_memory,
            &exception_code) ||
        equip_object_memory == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone equip allocation failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t equip_object_address = 0;
    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            equip_ctor_address,
            reinterpret_cast<void*>(equip_object_memory),
            &equip_object_address,
            &exception_code) ||
        equip_object_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallGameFreeSafe(free_address, equip_object_memory, &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone equip raw cleanup skipped. inner=" +
                HexString(equip_object_memory) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message = "Standalone equip ctor failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t equip_wrapper_address = 0;
    exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            sizeof(std::uint32_t) * 2,
            &equip_wrapper_address,
            &exception_code) ||
        equip_wrapper_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallScalarDeletingDestructorSafe(equip_object_address, 1, &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone equip object cleanup skipped. inner=" +
                HexString(equip_object_address) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message = "Standalone equip wrapper allocation failed with 0x" +
                             HexString(exception_code) + ".";
        }
        return false;
    }

    auto* wrapper_words = reinterpret_cast<std::uint32_t*>(equip_wrapper_address);
    wrapper_words[0] = static_cast<std::uint32_t>(equip_object_address);
    wrapper_words[1] = 0;

    if (wrapper_address != nullptr) {
        *wrapper_address = equip_wrapper_address;
    }
    if (inner_address != nullptr) {
        *inner_address = equip_object_address;
    }
    return true;
}

bool CreateStandaloneWizardProgressionWrapper(
    uintptr_t* wrapper_address,
    uintptr_t* inner_address,
    std::string* error_message) {
    if (wrapper_address != nullptr) {
        *wrapper_address = 0;
    }
    if (inner_address != nullptr) {
        *inner_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& memory = ProcessMemory::Instance();
    const auto operator_new_address = memory.ResolveGameAddressOrZero(kGameOperatorNew);
    const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
    const auto progression_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualRuntimeCtor);
    if (operator_new_address == 0 ||
        free_address == 0 ||
        progression_ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the standalone progression entrypoints.";
        }
        return false;
    }

    uintptr_t progression_object_memory = 0;
    DWORD exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            kStandaloneWizardVisualRuntimeSize,
            &progression_object_memory,
            &exception_code) ||
        progression_object_memory == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone progression allocation failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t progression_object_address = 0;
    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            progression_ctor_address,
            reinterpret_cast<void*>(progression_object_memory),
            &progression_object_address,
            &exception_code) ||
        progression_object_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallGameFreeSafe(free_address, progression_object_memory, &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone progression raw cleanup skipped. inner=" +
                HexString(progression_object_memory) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message =
                "Standalone progression ctor failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t progression_wrapper_address = 0;
    exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            sizeof(std::uint32_t) * 2,
            &progression_wrapper_address,
            &exception_code) ||
        progression_wrapper_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallScalarDeletingDestructorSafe(
                progression_object_address,
                1,
                &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone progression object cleanup skipped. inner=" +
                HexString(progression_object_address) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message =
                "Standalone progression wrapper allocation failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    auto* wrapper_words = reinterpret_cast<std::uint32_t*>(progression_wrapper_address);
    wrapper_words[0] = static_cast<std::uint32_t>(progression_object_address);
    wrapper_words[1] = 0;

    if (wrapper_address != nullptr) {
        *wrapper_address = progression_wrapper_address;
    }
    if (inner_address != nullptr) {
        *inner_address = progression_object_address;
    }
    return true;
}

