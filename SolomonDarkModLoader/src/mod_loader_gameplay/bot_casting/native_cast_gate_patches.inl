struct NativeCastGatePatch {
    const char* name = "";
    uintptr_t address = 0;
    uintptr_t resolved_address = 0;
    std::array<std::uint8_t, 6> expected = {};
    std::array<std::uint8_t, 6> replacement = {};
    bool installed = false;
    bool restore_needed = false;
};

std::array<NativeCastGatePatch, 5> g_native_cast_gate_patches = {};

bool BytesEqual(
    const std::array<std::uint8_t, 6>& left,
    const std::array<std::uint8_t, 6>& right) {
    return std::equal(left.begin(), left.end(), right.begin());
}

std::string FormatPatchBytes(const std::array<std::uint8_t, 6>& bytes) {
    std::ostringstream out;
    for (std::size_t index = 0; index < bytes.size(); ++index) {
        if (index != 0) {
            out << ' ';
        }
        out << HexString(static_cast<std::uint32_t>(bytes[index]));
    }
    return out.str();
}

bool ApplyNativeCastGatePatch(NativeCastGatePatch* patch, std::string* error_message) {
    if (patch == nullptr || patch->address == 0) {
        if (error_message != nullptr) {
            *error_message = "native cast gate patch has no address";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    patch->resolved_address = memory.ResolveGameAddressOrZero(patch->address);
    if (patch->resolved_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                std::string("unable to resolve native cast gate patch target ") +
                patch->name + " at " + HexString(patch->address);
        }
        return false;
    }

    std::array<std::uint8_t, 6> current = {};
    if (!memory.TryRead(patch->resolved_address, current.data(), current.size())) {
        if (error_message != nullptr) {
            *error_message =
                std::string("unable to read native cast gate patch target ") +
                patch->name + " at " + HexString(patch->address) +
                " resolved=" + HexString(patch->resolved_address);
        }
        return false;
    }

    if (BytesEqual(current, patch->replacement)) {
        patch->installed = true;
        patch->restore_needed = false;
        return true;
    }

    if (!BytesEqual(current, patch->expected)) {
        if (error_message != nullptr) {
            *error_message =
                std::string("native cast gate patch target bytes changed for ") +
                patch->name + " at " + HexString(patch->address) +
                " resolved=" + HexString(patch->resolved_address) +
                " expected=" + FormatPatchBytes(patch->expected) +
                " actual=" + FormatPatchBytes(current);
        }
        return false;
    }

    if (!memory.TryWrite(patch->resolved_address, patch->replacement.data(), patch->replacement.size())) {
        if (error_message != nullptr) {
            *error_message =
                std::string("unable to write native cast gate patch ") +
                patch->name + " at " + HexString(patch->address) +
                " resolved=" + HexString(patch->resolved_address);
        }
        return false;
    }

    patch->installed = true;
    patch->restore_needed = true;
    return true;
}

void RestoreNativeCastGatePatch(NativeCastGatePatch* patch) {
    if (patch == nullptr || !patch->installed || !patch->restore_needed || patch->address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto target_address =
        patch->resolved_address != 0
            ? patch->resolved_address
            : memory.ResolveGameAddressOrZero(patch->address);
    if (target_address == 0) {
        return;
    }
    (void)ProcessMemory::Instance().TryWrite(
        target_address,
        patch->expected.data(),
        patch->expected.size());
    patch->installed = false;
    patch->restore_needed = false;
    patch->resolved_address = 0;
}

void RestoreNativeCastGatePatches() {
    for (auto& patch : g_native_cast_gate_patches) {
        RestoreNativeCastGatePatch(&patch);
    }
}

bool InstallNativeCastGatePatches(std::string* error_message) {
    const std::array<std::uint8_t, 6> nops = {0x90, 0x90, 0x90, 0x90, 0x90, 0x90};
    g_native_cast_gate_patches = {{
        {
            "player_actor_apply_mana_delta_local_actor_gate",
            kPlayerActorApplyManaDeltaLocalActorGateBranch,
            0,
            {0x0F, 0x85, 0x1F, 0x03, 0x00, 0x00},
            nops,
        },
        {
            "cast_active_handle_cleanup_slot_gate",
            kCastCleanupSlotGateBranch,
            0,
            {0x0F, 0x85, 0xA3, 0x00, 0x00, 0x00},
            nops,
        },
        {
            "spell_cast_028_slot_gate",
            kSpellCast028SlotGateBranch,
            0,
            {0x0F, 0x85, 0x15, 0x03, 0x00, 0x00},
            nops,
        },
        {
            "spell_cast_3ee_slot_gate",
            kSpellCast3EESlotGateBranch,
            0,
            {0x0F, 0x85, 0xA9, 0x01, 0x00, 0x00},
            nops,
        },
        {
            "spell_cast_3f0_slot_gate",
            kSpellCast3F0SlotGateBranch,
            0,
            {0x0F, 0x85, 0x1F, 0x01, 0x00, 0x00},
            nops,
        },
    }};

    for (auto& patch : g_native_cast_gate_patches) {
        std::string patch_error;
        if (!ApplyNativeCastGatePatch(&patch, &patch_error)) {
            RestoreNativeCastGatePatches();
            if (error_message != nullptr) {
                *error_message = patch_error;
            }
            return false;
        }
    }

    Log(
        "Gameplay input injection: native actor cast/mana gates unlocked. mana_delta=" +
        HexString(kPlayerActorApplyManaDeltaLocalActorGateBranch) +
        " cleanup=" +
        HexString(kCastCleanupSlotGateBranch) +
        " spell_028=" + HexString(kSpellCast028SlotGateBranch) +
        " spell_3ee=" + HexString(kSpellCast3EESlotGateBranch) +
        " spell_3f0=" + HexString(kSpellCast3F0SlotGateBranch));
    return true;
}
