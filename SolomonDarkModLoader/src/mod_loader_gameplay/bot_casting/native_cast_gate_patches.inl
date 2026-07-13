struct NativeCastGatePatch {
    const char* name = "";
    uintptr_t address = 0;
    uintptr_t resolved_address = 0;
    std::array<std::uint8_t, 6> original = {};
    std::array<std::uint8_t, 6> replacement = {};
    bool installed = false;
    bool restore_needed = false;
    std::size_t byte_count = 6;
};

std::array<NativeCastGatePatch, 10> g_native_cast_gate_patches = {};

bool BytesEqual(
    const std::array<std::uint8_t, 6>& left,
    const std::array<std::uint8_t, 6>& right,
    const std::size_t byte_count) {
    return std::equal(left.begin(), left.begin() + byte_count, right.begin());
}

std::string FormatPatchBytes(const std::array<std::uint8_t, 6>& bytes, const std::size_t byte_count) {
    std::ostringstream out;
    for (std::size_t index = 0; index < byte_count; ++index) {
        if (index != 0) {
            out << ' ';
        }
        out << HexString(static_cast<std::uint32_t>(bytes[index]));
    }
    return out.str();
}

std::array<std::uint8_t, 6> MakeNativeGateReplacementBytes() {
    std::array<std::uint8_t, 6> bytes = {};
    bytes.fill(0x90);
    return bytes;
}

bool LooksLikeNativeJnzGate(const std::array<std::uint8_t, 6>& bytes, const std::size_t byte_count) {
    if (byte_count == 6) {
        return bytes[0] == 0x0F && bytes[1] == 0x85;
    }
    if (byte_count == 2) {
        return bytes[0] == 0x75;
    }
    return false;
}

bool ApplyNativeCastGatePatch(NativeCastGatePatch* patch, std::string* error_message) {
    if (patch == nullptr || patch->address == 0) {
        if (error_message != nullptr) {
            *error_message = "native cast gate patch has no address";
        }
        return false;
    }
    if (patch->byte_count == 0 || patch->byte_count > patch->original.size()) {
        if (error_message != nullptr) {
            *error_message =
                std::string("native cast gate patch has invalid byte count for ") +
                patch->name + " count=" + std::to_string(patch->byte_count);
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
    if (!memory.TryRead(patch->resolved_address, current.data(), patch->byte_count)) {
        if (error_message != nullptr) {
            *error_message =
                std::string("unable to read native cast gate patch target ") +
                patch->name + " at " + HexString(patch->address) +
                " resolved=" + HexString(patch->resolved_address);
        }
        return false;
    }

    if (BytesEqual(current, patch->replacement, patch->byte_count)) {
        patch->installed = true;
        patch->restore_needed = false;
        return true;
    }

    if (!LooksLikeNativeJnzGate(current, patch->byte_count)) {
        if (error_message != nullptr) {
            *error_message =
                std::string("native cast gate patch target is not a native jnz gate for ") +
                patch->name + " at " + HexString(patch->address) +
                " resolved=" + HexString(patch->resolved_address) +
                " actual=" + FormatPatchBytes(current, patch->byte_count);
        }
        return false;
    }

    patch->original = current;
    if (!memory.TryWrite(patch->resolved_address, patch->replacement.data(), patch->byte_count)) {
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
    if (patch->original == std::array<std::uint8_t, 6>{}) {
        return;
    }
    (void)ProcessMemory::Instance().TryWrite(
        target_address,
        patch->original.data(),
        patch->byte_count);
    patch->installed = false;
    patch->restore_needed = false;
    patch->resolved_address = 0;
    patch->original = {};
}

void RestoreNativeCastGatePatches() {
    for (auto& patch : g_native_cast_gate_patches) {
        RestoreNativeCastGatePatch(&patch);
    }
}

bool InstallNativeCastGatePatches(std::string* error_message) {
    const auto nops = MakeNativeGateReplacementBytes();
    g_native_cast_gate_patches = {{
        {
            "player_actor_apply_mana_delta_local_actor_gate",
            kPlayerActorApplyManaDeltaLocalActorGateBranch,
            0,
            {},
            nops,
        },
        {
            "cast_active_handle_cleanup_slot_gate",
            kCastCleanupSlotGateBranch,
            0,
            {},
            nops,
        },
        {
            "spell_cast_008_ether_slot_gate",
            kSpellCast008SlotGateBranch,
            0,
            {},
            nops,
        },
        {
            "spell_cast_008_ether_projectile_slot_gate",
            kSpellCast008ProjectileSlotGateBranch,
            0,
            {},
            nops,
        },
        {
            "spell_cast_010_fire_slot_gate",
            kSpellCast010SlotGateBranch,
            0,
            {},
            nops,
        },
        {
            "spell_cast_028_slot_gate",
            kSpellCast028SlotGateBranch,
            0,
            {},
            nops,
        },
        {
            "spell_cast_3ee_slot_gate",
            kSpellCast3EESlotGateBranch,
            0,
            {},
            nops,
        },
        {
            "spell_cast_3f0_slot_gate",
            kSpellCast3F0SlotGateBranch,
            0,
            {},
            nops,
        },
        {
            // Fireball's first projectile-group check at 0x005E5196 owns
            // impact damage and stays intact. This second check only skips
            // FUN_00642BF0. Let remote presentation projectiles enter that
            // effect builder: spawned Embers inherit the nonlocal group byte,
            // so their own native hit gate still suppresses observer damage.
            "fireball_hit_secondary_effect_projectile_group_gate",
            kFireballHitSecondaryEffectProjectileGroupGateBranch,
            0,
            {},
            nops,
        },
        {
            "magic_missile_hit_damage_projectile_group_gate",
            kMagicMissileHitDamageProjectileGroupGateBranch,
            0,
            {},
            nops,
            false,
            false,
            2,
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
        " spell_008=" + HexString(kSpellCast008SlotGateBranch) +
        " spell_008_projectile=" + HexString(kSpellCast008ProjectileSlotGateBranch) +
        " spell_010=" + HexString(kSpellCast010SlotGateBranch) +
        " spell_028=" + HexString(kSpellCast028SlotGateBranch) +
        " spell_3ee=" + HexString(kSpellCast3EESlotGateBranch) +
        " spell_3f0=" + HexString(kSpellCast3F0SlotGateBranch) +
        " fireball_secondary_effect=" +
            HexString(kFireballHitSecondaryEffectProjectileGroupGateBranch) +
        " magic_missile_hit=" + HexString(kMagicMissileHitDamageProjectileGroupGateBranch));
    return true;
}
