bool DestroyGameplaySlotBotResources(
    uintptr_t gameplay_address,
    int slot_index,
    uintptr_t actor_address,
    uintptr_t world_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_address == 0 || slot_index < 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay slot cleanup requires a live gameplay scene and slot index.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_slot_offset =
        kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    const auto progression_slot_offset =
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    uintptr_t published_actor_address = 0;
    if (!memory.TryReadField(gameplay_address, actor_slot_offset, &published_actor_address)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay slot cleanup could not read published actor slot.";
        }
        return false;
    }
    if (actor_address == 0) {
        actor_address = published_actor_address;
    }

    if (world_address == 0 && actor_address != 0) {
        if (!memory.TryReadField(actor_address, kActorOwnerOffset, &world_address)) {
            if (error_message != nullptr) {
                *error_message = "Gameplay slot cleanup could not read actor world owner.";
            }
            return false;
        }
    }

    if (actor_address != 0) {
        std::string detach_error;
        if (!DetachGameplaySlotBotVisualLanes(actor_address, &detach_error)) {
            if (error_message != nullptr) {
                *error_message = detach_error;
            }
            return false;
        }
    }

    if (world_address != 0) {
        const auto unregister_slot_address =
            memory.ResolveGameAddressOrZero(kActorWorldUnregisterGameplaySlotActor);
        if (unregister_slot_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve ActorWorld_UnregisterGameplaySlotActor.";
            }
            return false;
        }

        DWORD exception_code = 0;
        if (!CallActorWorldUnregisterGameplaySlotActorSafe(
                unregister_slot_address,
                world_address,
                slot_index,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "ActorWorld_UnregisterGameplaySlotActor failed with 0x" +
                    HexString(exception_code) + ".";
            }
            return false;
        }
    }

    (void)memory.TryWriteField<uintptr_t>(gameplay_address, actor_slot_offset, 0);
    (void)memory.TryWriteField<uintptr_t>(gameplay_address, progression_slot_offset, 0);

    return true;
}

bool DetachLoaderOwnedWizardActorFromGameplayActorList(
    uintptr_t actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto gameplay_global_address = memory.ResolveGameAddressOrZero(kGameplayRuntimeGlobal);
    if (gameplay_global_address == 0) {
        return true;
    }

    uintptr_t gameplay_address = 0;
    if (!memory.TryReadValue(gameplay_global_address, &gameplay_address) ||
        gameplay_address == 0) {
        return true;
    }

    DWORD exception_code = 0;
    if (!CallGameplayActorDetachSafe(gameplay_address, actor_address, &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay actor-list detach failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    return true;
}

bool DestroyLoaderOwnedWizardActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    bool raw_allocation,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t live_owner_address = 0;
    const bool live_owner_readable =
        memory.TryReadField(actor_address, kActorOwnerOffset, &live_owner_address);
    if (live_owner_address != 0) {
        world_address = live_owner_address;
    } else if (!raw_allocation || !live_owner_readable) {
        world_address = 0;
    }

    std::string detach_error;
    if (!DetachLoaderOwnedWizardActorFromGameplayActorList(actor_address, &detach_error)) {
        Log(
            "[bots] destroy_loader_owned_actor gameplay_detach_failed actor=" +
            HexString(actor_address) +
            (detach_error.empty() ? std::string() : " detail=" + detach_error));
        if (error_message != nullptr) {
            *error_message = detach_error;
        }
        return false;
    }

    auto build_destroy_summary = [&](std::string_view stage) {
        const auto read_u8_text = [&](std::size_t offset) {
            std::uint8_t value = 0;
            return memory.TryReadField(actor_address, offset, &value)
                ? std::to_string(static_cast<int>(value))
                : std::string("unreadable");
        };
        const auto read_ptr_text = [&](std::size_t offset) {
            uintptr_t value = 0;
            return memory.TryReadField(actor_address, offset, &value)
                ? HexString(value)
                : std::string("unreadable");
        };
        uintptr_t vtable = 0;
        const auto vtable_text =
            memory.TryReadValue(actor_address, &vtable)
                ? HexString(vtable)
                : std::string("unreadable");
        std::ostringstream out;
        out << "stage=" << stage
            << " actor=" << HexString(actor_address)
            << " world=" << HexString(world_address)
            << " raw_allocation=" << (raw_allocation ? "true" : "false")
            << " actor_summary={" << BuildActorVisualDebugSummary(actor_address) << "}"
            << " byte5=" << read_u8_text(0x05)
            << " byte6=" << read_u8_text(0x06)
            << " vtable=" << vtable_text
            << " owner=" << read_ptr_text(kActorOwnerOffset)
            << " attach=" << read_ptr_text(kActorHubVisualAttachmentPtrOffset);
        return out.str();
    };

    auto build_dtor_precrash_dump = [&]() {
        auto read_u32 = [&](uintptr_t addr) {
            std::uint32_t value = 0;
            (void)memory.TryReadValue(addr, &value);
            return value;
        };
        const uintptr_t om_base = actor_address + 0x16C;
        const std::uint32_t om_vt = read_u32(om_base + 0x00);
        const std::uint32_t om_cond8 = read_u32(om_base + 0x08);
        const std::uint32_t om_count20 = read_u32(om_base + 0x20);
        const std::uint32_t om_e0_vt = read_u32(om_base + 0x18);
        const std::uint32_t om_e0_f4 = read_u32(om_base + 0x18 + 0x04);
        const std::uint32_t om_e0_f8 = read_u32(om_base + 0x18 + 0x08);
        const std::uint32_t om_e0_fc = read_u32(om_base + 0x18 + 0x0C);
        const std::uint32_t om_e0_f10 = read_u32(om_base + 0x18 + 0x10);
        const std::uint32_t om_e0_f14 = read_u32(om_base + 0x18 + 0x14);
        const std::uint32_t om_e1_vt = read_u32(om_base + 0x18 + 0x18);
        const std::uint32_t om_e1_f4 = read_u32(om_base + 0x18 + 0x18 + 0x04);
        const std::uint32_t om_e1_f8 = read_u32(om_base + 0x18 + 0x18 + 0x08);
        const std::uint32_t om_tail = read_u32(om_base + 0x38);
        const std::uint32_t e_vt_s0 = om_e0_vt ? read_u32(om_e0_vt + 0x00) : 0;
        const std::uint32_t e_vt_s4 = om_e0_vt ? read_u32(om_e0_vt + 0x04) : 0;
        const std::uint32_t e_vt_s8 = om_e0_vt ? read_u32(om_e0_vt + 0x08) : 0;
        const auto dat_81c264_global = memory.ResolveGameAddressOrZero(kGameplayRuntimeGlobal);
        const std::uint32_t dat_81c264 = dat_81c264_global ? read_u32(dat_81c264_global) : 0;
        const std::uint32_t dat_1388 = dat_81c264 ? read_u32(dat_81c264 + 0x1388) : 0;
        const std::uint32_t dat_1388_1c = dat_1388 ? read_u32(dat_1388 + 0x1C) : 0;
        std::ostringstream out;
        out << " actor_vt=" << HexString(read_u32(actor_address))
            << " om_vt=" << HexString(om_vt)
            << " om_cond8=" << HexString(om_cond8)
            << " om_count20=" << HexString(om_count20)
            << " om_tail=" << HexString(om_tail)
            << " om_e0_vt=" << HexString(om_e0_vt)
            << " om_e0_f4=" << HexString(om_e0_f4)
            << " om_e0_f8=" << HexString(om_e0_f8)
            << " om_e0_fc=" << HexString(om_e0_fc)
            << " om_e0_f10=" << HexString(om_e0_f10)
            << " om_e0_f14=" << HexString(om_e0_f14)
            << " om_e1_vt=" << HexString(om_e1_vt)
            << " om_e1_f4=" << HexString(om_e1_f4)
            << " om_e1_f8=" << HexString(om_e1_f8)
            << " e_vt_s0=" << HexString(e_vt_s0)
            << " e_vt_s4=" << HexString(e_vt_s4)
            << " e_vt_s8=" << HexString(e_vt_s8)
            << " puppet_dc=" << HexString(read_u32(actor_address + 0xDC))
            << " puppet_118=" << HexString(read_u32(actor_address + 0x118))
            << " inner_150=" << HexString(read_u32(actor_address + 0x150))
            << " prog300=" << HexString(read_u32(actor_address + 0x300))
            << " equip304=" << HexString(read_u32(actor_address + 0x304))
            << " dat_81c264=" << HexString(dat_81c264)
            << " dat_1388=" << HexString(dat_1388)
            << " dat_1388_1c=" << HexString(dat_1388_1c);
        return out.str();
    };

    if (world_address != 0) {
        const auto unregister_address = memory.ResolveGameAddressOrZero(kActorWorldUnregister);
        if (unregister_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve ActorWorld_Unregister.";
            }
            return false;
        }

        Log(
            "[bots] destroy_loader_owned_actor pre_unregister_dump actor=" +
            HexString(actor_address) +
            build_dtor_precrash_dump());

        DWORD exception_code = 0;
        ++g_loader_owned_actor_destroy_unregister_depth;
        const bool unregistered = CallActorWorldUnregisterSafe(
            unregister_address,
            world_address,
            actor_address,
            0,
            &exception_code);
        --g_loader_owned_actor_destroy_unregister_depth;
        if (!unregistered) {
            Log("[bots] destroy_loader_owned_actor unregister_failed " + build_destroy_summary("post_unregister_exception"));
            if (error_message != nullptr) {
                *error_message = "ActorWorld_Unregister failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }

        // Standalone wizard clones are PlayerActor-family objects and the
        // stock scene-churn hook unregisters tracked standalone actors with
        // remove_from_container=0.  The container-removal path aliases stock
        // slot/player teardown state during hub->run churn, so keep this path
        // aligned with the hook and treat unregister as the terminal owner
        // transition for registered standalone clones.
        if (!raw_allocation) {
            return true;
        }
    } else if (!raw_allocation) {
        const auto object_delete_address = memory.ResolveGameAddressOrZero(kObjectDelete);
        if (object_delete_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve Object_Delete.";
            }
            return false;
        }

        DWORD exception_code = 0;
        if (!CallObjectDeleteSafe(object_delete_address, actor_address, &exception_code)) {
            Log(
                "[bots] destroy_loader_owned_actor object_delete_failed " +
                build_destroy_summary("no_world"));
            if (error_message != nullptr) {
                *error_message = "Object_Delete failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }
        return true;
    }

    SehExceptionDetails exception_details = {};
    if (!CallScalarDeletingDestructorDetailedSafe(
            actor_address,
            0,
            &exception_details)) {
        const auto detail_summary = FormatSehExceptionDetails(exception_details);
        Log(
            "[bots] destroy_loader_owned_actor dtor_failed " +
            build_destroy_summary("post_unregister") +
            " seh{" + detail_summary + "}");
        if (error_message != nullptr) {
            *error_message = "Actor scalar deleting destructor failed. " + detail_summary;
        }
        return false;
    }

    if (raw_allocation) {
        _aligned_free(reinterpret_cast<void*>(actor_address));
    }

    return true;
}
