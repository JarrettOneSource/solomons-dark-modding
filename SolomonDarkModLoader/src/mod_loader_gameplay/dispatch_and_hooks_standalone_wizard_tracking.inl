void LogStandaloneWizardActorLifecycleEvent(
    std::string_view label,
    uintptr_t actor_address,
    uintptr_t world_address,
    int free_flag_or_slot,
    uintptr_t caller_address) {
    if (actor_address == 0) {
        return;
    }

    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    bool tracked = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && binding->kind == ParticipantEntityBinding::Kind::StandaloneWizard) {
            bot_id = binding->bot_id;
            gameplay_slot = binding->gameplay_slot;
            tracked = true;
        }
    }
    if (!tracked) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    Log(
        "[bots] " + std::string(label) +
        " actor=" + HexString(actor_address) +
        " bot_id=" + std::to_string(bot_id) +
        " binding_slot=" + std::to_string(gameplay_slot) +
        " arg=" + std::to_string(free_flag_or_slot) +
        " caller=" + HexString(caller_address) +
        " vtable=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x00, 0)) +
        " +04=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kObjectHeaderWordOffset, 0)) +
        " owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
        " world_self=" + HexString(world_address) +
        " slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " +1FC=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0)) +
        " +200=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
        " +21C=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0)));
}

std::string CaptureStackTraceSummary(std::size_t frames_to_skip, std::size_t max_frames) {
    std::array<void*, 16> frames{};
    const auto captured = static_cast<std::size_t>(RtlCaptureStackBackTrace(
        0,
        static_cast<ULONG>(frames.size()),
        frames.data(),
        nullptr));
    if (captured <= frames_to_skip || max_frames == 0) {
        return {};
    }

    std::string summary;
    const auto requested_end = frames_to_skip + max_frames;
    const auto end = captured < requested_end ? captured : requested_end;
    for (std::size_t index = frames_to_skip; index < end; ++index) {
        if (!summary.empty()) {
            summary += ",";
        }
        summary += HexString(reinterpret_cast<uintptr_t>(frames[index]));
    }
    return summary;
}

thread_local int g_player_actor_vslot28_depth = 0;
thread_local uintptr_t g_player_actor_vslot28_actor = 0;
thread_local uintptr_t g_player_actor_vslot28_caller = 0;
thread_local int g_player_actor_vslot1c_depth = 0;
thread_local uintptr_t g_player_actor_vslot1c_actor = 0;
thread_local uintptr_t g_player_actor_vslot1c_caller = 0;
thread_local int g_gameplay_hud_participant_actor_depth = 0;
thread_local uintptr_t g_gameplay_hud_participant_actor = 0;
thread_local uintptr_t g_gameplay_hud_participant_actor_caller = 0;
thread_local int g_gameplay_hud_case100_depth = 0;
thread_local uintptr_t g_gameplay_hud_case100_owner = 0;
thread_local uintptr_t g_gameplay_hud_case100_caller = 0;
thread_local int g_puppet_manager_delete_batch_depth = 0;
thread_local uintptr_t g_puppet_manager_delete_batch_self = 0;
thread_local uintptr_t g_puppet_manager_delete_batch_list = 0;

bool TryCaptureTrackedStandaloneWizardBindingIdentity(
    uintptr_t actor_address,
    std::uint64_t* out_bot_id,
    int* out_gameplay_slot);

bool TryFindTrackedStandaloneWizardInPointerList(
    uintptr_t list_address,
    std::uint64_t* out_bot_id,
    int* out_gameplay_slot,
    uintptr_t* out_actor_address,
    int* out_tracked_count) {
    if (out_bot_id != nullptr) {
        *out_bot_id = 0;
    }
    if (out_gameplay_slot != nullptr) {
        *out_gameplay_slot = -1;
    }
    if (out_actor_address != nullptr) {
        *out_actor_address = 0;
    }
    if (out_tracked_count != nullptr) {
        *out_tracked_count = 0;
    }
    if (list_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto count = memory.ReadFieldOr<int>(list_address, kPointerListCountOffset, 0);
    const auto items_address = memory.ReadFieldOr<uintptr_t>(list_address, kPointerListItemsOffset, 0);
    if (count <= 0 || count > 1024 || items_address == 0) {
        return false;
    }

    int tracked_count = 0;
    for (int index = 0; index < count; ++index) {
        const auto actor_address =
            memory.ReadValueOr<uintptr_t>(items_address + static_cast<std::size_t>(index) * sizeof(std::uint32_t), 0);
        if (actor_address == 0) {
            continue;
        }

        std::uint64_t bot_id = 0;
        int gameplay_slot = -1;
        if (!TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, &bot_id, &gameplay_slot)) {
            continue;
        }

        ++tracked_count;
        if (tracked_count == 1) {
            if (out_bot_id != nullptr) {
                *out_bot_id = bot_id;
            }
            if (out_gameplay_slot != nullptr) {
                *out_gameplay_slot = gameplay_slot;
            }
            if (out_actor_address != nullptr) {
                *out_actor_address = actor_address;
            }
        }
    }

    if (out_tracked_count != nullptr) {
        *out_tracked_count = tracked_count;
    }
    return tracked_count > 0;
}

bool LogTrackedStandaloneWizardPuppetManagerDeleteBatchEvent(
    std::string_view label,
    uintptr_t self_address,
    uintptr_t list_address,
    uintptr_t caller_address) {
    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    uintptr_t actor_address = 0;
    int tracked_count = 0;
    if (!TryFindTrackedStandaloneWizardInPointerList(
            list_address,
            &bot_id,
            &gameplay_slot,
            &actor_address,
            &tracked_count)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto count = memory.ReadFieldOr<int>(list_address, kPointerListCountOffset, 0);
    const auto capacity = memory.ReadFieldOr<int>(list_address, kPointerListCapacityOffset, 0);
    const auto items_address = memory.ReadFieldOr<uintptr_t>(list_address, kPointerListItemsOffset, 0);
    const auto owns_storage = static_cast<unsigned>(memory.ReadFieldOr<std::uint8_t>(
        list_address,
        kPointerListOwnsStorageFlagOffset,
        0));
    const auto self_vtable = memory.ReadFieldOr<uintptr_t>(self_address, 0x00, 0);
    const auto owner_region = memory.ReadFieldOr<uintptr_t>(self_address, kPuppetManagerOwnerRegionOffset, 0);
    const auto expected_manager =
        owner_region == 0 ? 0 : owner_region + kRegionPuppetManagerOffset;
    const auto puppet_manager_vtable = memory.ResolveGameAddressOrZero(kPuppetManagerVtable);
    const auto list_delta = list_address >= self_address
        ? list_address - self_address
        : self_address - list_address;

    Log(
        "[bots] " + std::string(label) +
        " self=" + HexString(self_address) +
        " self_vtable=" + HexString(self_vtable) +
        " puppet_manager_vtable=" + HexString(puppet_manager_vtable) +
        " owner_region=" + HexString(owner_region) +
        " expected_manager=" + HexString(expected_manager) +
        " list=" + HexString(list_address) +
        " list_delta=" + HexString(list_delta) +
        " count=" + std::to_string(count) +
        " capacity=" + std::to_string(capacity) +
        " owns_storage=" + std::to_string(owns_storage) +
        " items=" + HexString(items_address) +
        " tracked_actor=" + HexString(actor_address) +
        " tracked_bot_id=" + std::to_string(bot_id) +
        " tracked_binding_slot=" + std::to_string(gameplay_slot) +
        " tracked_count=" + std::to_string(tracked_count) +
        " caller=" + HexString(caller_address) +
        " stack=" + CaptureStackTraceSummary(1, 5));
    return true;
}

void LogStandaloneWizardRegionDeleteEvent(
    std::string_view label,
    uintptr_t deleter_address,
    uintptr_t actor_address,
    uintptr_t caller_address) {
    if (actor_address == 0) {
        return;
    }

    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    bool tracked = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && binding->kind == ParticipantEntityBinding::Kind::StandaloneWizard) {
            bot_id = binding->bot_id;
            gameplay_slot = binding->gameplay_slot;
            tracked = true;
        }
    }
    if (!tracked) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    Log(
        "[bots] " + std::string(label) +
        " actor=" + HexString(actor_address) +
        " bot_id=" + std::to_string(bot_id) +
        " binding_slot=" + std::to_string(gameplay_slot) +
        " caller=" + HexString(caller_address) +
        " deleter_self=" + HexString(deleter_address) +
        " deleter_vtable=" + HexString(memory.ReadFieldOr<uintptr_t>(deleter_address, 0x00, 0)) +
        " deleter_world=" + HexString(memory.ReadFieldOr<uintptr_t>(
            deleter_address,
            kPuppetManagerOwnerRegionOffset,
            0)) +
        " actor_vtable=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x00, 0)) +
        " actor_owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
        " actor_slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " active_vslot28_depth=" + std::to_string(g_player_actor_vslot28_depth) +
        " active_vslot28_actor=" + HexString(g_player_actor_vslot28_actor) +
        " active_vslot28_caller=" + HexString(g_player_actor_vslot28_caller) +
        " active_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth) +
        " active_case100_owner=" + HexString(g_gameplay_hud_case100_owner) +
        " active_case100_caller=" + HexString(g_gameplay_hud_case100_caller) +
        " active_puppet_batch_depth=" + std::to_string(g_puppet_manager_delete_batch_depth) +
        " active_puppet_batch_self=" + HexString(g_puppet_manager_delete_batch_self) +
        " active_puppet_batch_list=" + HexString(g_puppet_manager_delete_batch_list) +
        " stack=" + CaptureStackTraceSummary(1, 5));
}

bool TryCaptureTrackedStandaloneWizardBindingIdentity(
    uintptr_t actor_address,
    std::uint64_t* out_bot_id,
    int* out_gameplay_slot) {
    if (out_bot_id != nullptr) {
        *out_bot_id = 0;
    }
    if (out_gameplay_slot != nullptr) {
        *out_gameplay_slot = -1;
    }
    if (actor_address == 0) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    if (const auto* binding = FindParticipantEntityForActor(actor_address);
        binding != nullptr && binding->kind == ParticipantEntityBinding::Kind::StandaloneWizard) {
        if (out_bot_id != nullptr) {
            *out_bot_id = binding->bot_id;
        }
        if (out_gameplay_slot != nullptr) {
            *out_gameplay_slot = binding->gameplay_slot;
        }
        return true;
    }
    return false;
}
