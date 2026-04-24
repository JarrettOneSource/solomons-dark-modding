bool DestroyGameplaySlotBotResources(
    uintptr_t gameplay_address,
    int slot_index,
    uintptr_t actor_address,
    uintptr_t world_address,
    uintptr_t synthetic_source_profile_address,
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
    const auto published_actor_address =
        memory.ReadFieldOr<uintptr_t>(gameplay_address, actor_slot_offset, 0);
    if (actor_address == 0) {
        actor_address = published_actor_address;
    }

    if (world_address == 0 && actor_address != 0) {
        world_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
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

    (void)synthetic_source_profile_address;

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
    const auto live_owner_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    if (live_owner_address != 0) {
        world_address = live_owner_address;
    } else if (!raw_allocation) {
        world_address = 0;
    }

    auto build_destroy_summary = [&](std::string_view stage) {
        std::ostringstream out;
        out << "stage=" << stage
            << " actor=" << HexString(actor_address)
            << " world=" << HexString(world_address)
            << " raw_allocation=" << (raw_allocation ? "true" : "false")
            << " actor_summary={" << BuildActorVisualDebugSummary(actor_address) << "}"
            << " byte5=" << static_cast<int>(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x05, 0))
            << " byte6=" << static_cast<int>(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x06, 0))
            << " vtable=" << HexString(memory.ReadValueOr<uintptr_t>(actor_address, 0))
            << " owner=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0))
            << " attach=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0));
        return out.str();
    };

    auto build_dtor_precrash_dump = [&]() {
        auto read_u32 = [&](uintptr_t addr) {
            return memory.ReadValueOr<std::uint32_t>(addr, 0u);
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
        const std::uint32_t dat_81c264 = read_u32(0x00C0C264u);
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
        if (!CallActorWorldUnregisterSafe(
                unregister_address,
                world_address,
                actor_address,
                1,
                &exception_code)) {
            Log("[bots] destroy_loader_owned_actor unregister_failed " + build_destroy_summary("post_unregister_exception"));
            if (error_message != nullptr) {
                *error_message = "ActorWorld_Unregister failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }

        // Matches DestroyWizardCloneSourceActor: factory-created world-owned
        // actors treat ActorWorld_Unregister as the terminal owner transition.
        // Following it with PuppetManager::DeletePuppet or Object_Delete causes
        // an execute AV inside the scalar deleting destructor (verified in the
        // 2026-04-19 crash at EIP=0x49C5E460 during the clone-bot dtor chain).
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
