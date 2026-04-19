bool CreateStandaloneWizardVisualLinkObject(
    uintptr_t ctor_address,
    const std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize>& descriptor,
    uintptr_t* object_address,
    std::string* error_message) {
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone visual-link creation requires a live ctor address.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto object_allocate_address = memory.ResolveGameAddressOrZero(kObjectAllocate);
    const auto operator_new_address = memory.ResolveGameAddressOrZero(kGameOperatorNew);
    const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
    if (object_allocate_address == 0 || operator_new_address == 0 || free_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the visual-link allocation entrypoints.";
        }
        return false;
    }

    uintptr_t object_memory = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectAllocateSafe(
            object_allocate_address,
            kStandaloneWizardVisualLinkSize,
            &object_memory,
            &exception_code) ||
        object_memory == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone visual-link Object_Allocate failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t built_object_address = 0;
    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            ctor_address,
            reinterpret_cast<void*>(object_memory),
            &built_object_address,
            &exception_code) ||
        built_object_address == 0) {
        DWORD release_exception_code = 0;
        (void)CallGameFreeSafe(free_address, object_memory, &release_exception_code);
        if (error_message != nullptr) {
            *error_message =
                "Standalone visual-link ctor failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    if (!memory.TryWriteField(
            built_object_address,
            kStandaloneWizardVisualLinkResetStateOffset,
            static_cast<std::int32_t>(0)) ||
        !memory.TryWriteField(
            built_object_address,
            kStandaloneWizardVisualLinkActiveFlagOffset,
            static_cast<std::uint8_t>(1)) ||
        !memory.TryWrite(
            built_object_address + kStandaloneWizardVisualLinkColorBlockOffset,
            descriptor.data(),
            descriptor.size())) {
        DWORD destroy_exception_code = 0;
        (void)CallScalarDeletingDestructorSafe(
            built_object_address,
            1,
            &destroy_exception_code);
        if (error_message != nullptr) {
            *error_message = "Failed to seed the standalone visual-link payload.";
        }
        return false;
    }

    if (object_address != nullptr) {
        *object_address = built_object_address;
    }
    return true;
}

bool CreateGameplaySlotStaffItemObject(
    uintptr_t* object_address,
    std::string* error_message) {
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& memory = ProcessMemory::Instance();
    const auto object_allocate_address = memory.ResolveGameAddressOrZero(kObjectAllocate);
    const auto free_address = memory.ResolveGameAddressOrZero(kGameFree);
    const auto staff_ctor_address = memory.ResolveGameAddressOrZero(kItemStaffCtor);
    if (object_allocate_address == 0 || free_address == 0 || staff_ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the stock staff allocation entrypoints.";
        }
        return false;
    }

    uintptr_t object_memory = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectAllocateSafe(
            object_allocate_address,
            0x88,
            &object_memory,
            &exception_code) ||
        object_memory == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Stock staff Object_Allocate failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t built_object_address = 0;
    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            staff_ctor_address,
            reinterpret_cast<void*>(object_memory),
            &built_object_address,
            &exception_code) ||
        built_object_address == 0) {
        DWORD release_exception_code = 0;
        (void)CallGameFreeSafe(free_address, object_memory, &release_exception_code);
        if (error_message != nullptr) {
            *error_message =
                "Stock staff ctor failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    if (!memory.TryWriteField(
            built_object_address,
            kStandaloneWizardVisualLinkActiveFlagOffset,
            static_cast<std::uint8_t>(1)) ||
        !memory.TryWriteField(
            built_object_address,
            kStandaloneWizardVisualLinkResetStateOffset,
            static_cast<std::int32_t>(0))) {
        DWORD destroy_exception_code = 0;
        (void)CallScalarDeletingDestructorSafe(
            built_object_address,
            1,
            &destroy_exception_code);
        if (error_message != nullptr) {
            *error_message = "Failed to seed the stock staff startup flags.";
        }
        return false;
    }

    if (object_address != nullptr) {
        *object_address = built_object_address;
    }
    return true;
}

bool SetEquipVisualLaneObject(
    uintptr_t actor_address,
    std::size_t lane_offset,
    uintptr_t object_address,
    std::string_view label,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone " + std::string(label) +
                " lane update requires a live actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    const auto lane = ReadEquipVisualLaneState(equip_runtime_state_address, lane_offset);
    if (lane.holder_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone " + std::string(label) +
                " attach could not resolve the equip sink holder.";
        }
        return false;
    }

    const auto attach_address = memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkAttach);
    if (attach_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve EquipAttachmentSink_Attach.";
        }
        return false;
    }

    const auto holder_object_before = memory.ReadFieldOr<uintptr_t>(
        lane.holder_address,
        kVisualLaneHolderCurrentObjectOffset,
        0);
    std::ostringstream before_out;
    before_out << "[bots] equip_attach before label=" << label
               << " actor=" << HexString(actor_address)
               << " holder=" << HexString(lane.holder_address)
               << " object_before=" << HexString(holder_object_before)
               << " object_new=" << HexString(object_address);
    if (holder_object_before != 0) {
        AppendAttachmentObjectDebugSummary(
            &before_out,
            "holder_object_before",
            holder_object_before);
    }
    if (object_address != 0) {
        AppendAttachmentObjectDebugSummary(
            &before_out,
            "object_new_state",
            object_address);
    }
    Log(before_out.str());

    DWORD exception_code = 0;
    if (!CallStandaloneWizardVisualLinkAttachSafe(
            attach_address,
            lane.holder_address,
            object_address,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone " + std::string(label) +
                " lane update failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    const auto holder_object_after = memory.ReadFieldOr<uintptr_t>(
        lane.holder_address,
        kVisualLaneHolderCurrentObjectOffset,
        0);
    std::ostringstream after_out;
    after_out << "[bots] equip_attach after label=" << label
              << " actor=" << HexString(actor_address)
              << " holder=" << HexString(lane.holder_address)
              << " object_after=" << HexString(holder_object_after);
    if (holder_object_after != 0) {
        AppendAttachmentObjectDebugSummary(
            &after_out,
            "holder_object_after",
            holder_object_after);
    }
    Log(after_out.str());

    return true;
}

bool DetachGameplaySlotBotVisualLanes(uintptr_t actor_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        return true;
    }

    std::string lane_error;
    if (!SetEquipVisualLaneObject(
            actor_address,
            kActorEquipRuntimeVisualLinkPrimaryOffset,
            0,
            "primary",
            &lane_error)) {
        if (error_message != nullptr) {
            *error_message = lane_error;
        }
        return false;
    }

    if (!SetEquipVisualLaneObject(
            actor_address,
            kActorEquipRuntimeVisualLinkSecondaryOffset,
            0,
            "secondary",
            &lane_error)) {
        if (error_message != nullptr) {
            *error_message = lane_error;
        }
        return false;
    }

    if (!SetEquipVisualLaneObject(
            actor_address,
            kActorEquipRuntimeVisualLinkAttachmentOffset,
            0,
            "attachment",
            &lane_error)) {
        if (error_message != nullptr) {
            *error_message = lane_error;
        }
        return false;
    }

    return true;
}

bool AttachBuiltDescriptorToEquipVisualLane(
    uintptr_t actor_address,
    std::size_t lane_offset,
    uintptr_t ctor_address,
    const std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize>& descriptor,
    std::string_view label,
    std::string* error_message) {
    uintptr_t object_address = 0;
    if (!CreateStandaloneWizardVisualLinkObject(
            ctor_address,
            descriptor,
            &object_address,
            error_message)) {
        return false;
    }

    if (!SetEquipVisualLaneObject(
            actor_address,
            lane_offset,
            object_address,
            label,
            error_message)) {
        DWORD exception_code = 0;
        (void)CallScalarDeletingDestructorSafe(object_address, 1, &exception_code);
        return false;
    }

    return true;
}
