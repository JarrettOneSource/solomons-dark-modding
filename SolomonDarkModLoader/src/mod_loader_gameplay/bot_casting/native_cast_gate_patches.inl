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

std::array<NativeCastGatePatch, 9> g_native_cast_gate_patches = {};

enum class NativePrimarySlotGatePolicy : std::uint8_t {
    ParticipantPresentation = 0,
    HostOwnedLuaDamage = 1,
};

struct NativePrimarySlotGatePatch {
    NativeCastGatePatch patch;
    std::int32_t primary_entry_index = -1;
    NativePrimarySlotGatePolicy policy =
        NativePrimarySlotGatePolicy::ParticipantPresentation;
    std::uint32_t scope_depth = 0;
};

std::array<NativePrimarySlotGatePatch, 5>
    g_native_primary_slot_gate_patches = {};

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
    for (auto& primary_patch :
         g_native_primary_slot_gate_patches) {
        primary_patch.scope_depth = 0;
        RestoreNativeCastGatePatch(&primary_patch.patch);
    }
    for (auto& patch : g_native_cast_gate_patches) {
        RestoreNativeCastGatePatch(&patch);
    }
}

bool AcquireNativePrimarySlotGatePatch(
    NativePrimarySlotGatePatch* primary_patch,
    std::string* error_message) {
    if (primary_patch == nullptr) {
        if (error_message != nullptr) {
            *error_message = "native primary slot gate patch is null";
        }
        return false;
    }
    if (primary_patch->scope_depth == 0) {
        if (!ApplyNativeCastGatePatch(
                &primary_patch->patch,
                error_message)) {
            return false;
        }
    } else if (!primary_patch->patch.installed) {
        if (error_message != nullptr) {
            *error_message =
                std::string("native primary slot gate lost while scoped: ") +
                primary_patch->patch.name;
        }
        return false;
    }
    ++primary_patch->scope_depth;
    return true;
}

void ReleaseNativePrimarySlotGatePatch(
    NativePrimarySlotGatePatch* primary_patch) {
    if (primary_patch == nullptr ||
        primary_patch->scope_depth == 0) {
        return;
    }
    --primary_patch->scope_depth;
    if (primary_patch->scope_depth == 0) {
        RestoreNativeCastGatePatch(&primary_patch->patch);
    }
}

bool ValidateNativePrimarySlotGatePatches(
    std::string* error_message) {
    for (auto& primary_patch :
         g_native_primary_slot_gate_patches) {
        std::string patch_error;
        if (!AcquireNativePrimarySlotGatePatch(
                &primary_patch,
                &patch_error)) {
            for (auto& restore_patch :
                 g_native_primary_slot_gate_patches) {
                restore_patch.scope_depth = 0;
                RestoreNativeCastGatePatch(
                    &restore_patch.patch);
            }
            if (error_message != nullptr) {
                *error_message = patch_error;
            }
            return false;
        }
        ReleaseNativePrimarySlotGatePatch(&primary_patch);
    }
    return true;
}

class ScopedNativePrimarySlotGatePatches {
public:
    explicit ScopedNativePrimarySlotGatePatches(
        uintptr_t actor_address) {
        if (actor_address == 0) {
            return;
        }

        std::lock_guard<std::recursive_mutex> lock(
            g_participant_entities_mutex);
        const auto* binding =
            FindParticipantEntityForActor(actor_address);
        if (binding == nullptr ||
            !binding->ongoing_cast.active ||
            !binding->ongoing_cast.remote_input_controlled) {
            return;
        }

        const auto primary_entry_index =
            binding->ongoing_cast.selection_state_target;
        for (auto& primary_patch :
             g_native_primary_slot_gate_patches) {
            if (primary_patch.primary_entry_index !=
                primary_entry_index) {
                continue;
            }

            const bool authorized =
                primary_patch.policy ==
                    NativePrimarySlotGatePolicy::
                        ParticipantPresentation ||
                (multiplayer::IsLocalTransportHost() &&
                 binding->controller_kind ==
                     multiplayer::ParticipantControllerKind::
                         LuaBrain);
            if (!authorized) {
                continue;
            }

            std::string patch_error;
            if (!AcquireNativePrimarySlotGatePatch(
                    &primary_patch,
                    &patch_error)) {
                error_message_ =
                    std::string(primary_patch.patch.name) +
                    ": " + patch_error;
                ready_ = false;
                ReleaseAcquired();
                return;
            }
            acquired_[acquired_count_++] =
                &primary_patch;
        }
    }

    ~ScopedNativePrimarySlotGatePatches() {
        ReleaseAcquired();
    }

    ScopedNativePrimarySlotGatePatches(
        const ScopedNativePrimarySlotGatePatches&) = delete;
    ScopedNativePrimarySlotGatePatches& operator=(
        const ScopedNativePrimarySlotGatePatches&) = delete;

    bool ready() const {
        return ready_;
    }

    const std::string& error_message() const {
        return error_message_;
    }

private:
    void ReleaseAcquired() {
        while (acquired_count_ > 0) {
            --acquired_count_;
            ReleaseNativePrimarySlotGatePatch(
                acquired_[acquired_count_]);
            acquired_[acquired_count_] = nullptr;
        }
    }

    bool ready_ = true;
    std::string error_message_;
    std::array<NativePrimarySlotGatePatch*, 5>
        acquired_ = {};
    std::size_t acquired_count_ = 0;
};

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
            // The downstream badguy-damage hook admits only a projectile
            // explicitly registered to a host-owned synthetic participant.
            // Real remote and observer-side Fireballs still reach that hook
            // with nonlocal ownership and are rejected before stock damage.
            "fireball_hit_damage_projectile_group_gate",
            kFireballHitDamageProjectileGroupGateBranch,
            0,
            {},
            nops,
            false,
            false,
            2,
        },
        {
            // Fireball's first projectile-group check at 0x005E5196 owns
            // impact damage. The loader widens it above, then applies the
            // participant authority predicate in HookBadguyDamage. This
            // second check only skips FUN_00642BF0; widening it lets remote
            // presentation projectiles enter that effect builder. Spawned
            // Embers inherit the nonlocal group byte, so their native hit
            // gate still suppresses observer damage.
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

    g_native_primary_slot_gate_patches = {{
        {
            {
                "spell_cast_010_fire_slot_gate",
                kSpellCast010SlotGateBranch,
                0,
                {},
                nops,
            },
            0x10,
            NativePrimarySlotGatePolicy::
                ParticipantPresentation,
        },
        {
            {
                "spell_cast_018_first_damage_slot_gate",
                kSpellCast018FirstDamageSlotGateBranch,
                0,
                {},
                nops,
            },
            0x18,
            NativePrimarySlotGatePolicy::HostOwnedLuaDamage,
        },
        {
            {
                "spell_cast_018_chain_damage_slot_gate",
                kSpellCast018ChainDamageSlotGateBranch,
                0,
                {},
                nops,
            },
            0x18,
            NativePrimarySlotGatePolicy::HostOwnedLuaDamage,
        },
        {
            {
                "spell_cast_020_water_damage_slot_gate",
                kSpellCast020DamageSlotGateBranch,
                0,
                {},
                nops,
            },
            0x20,
            NativePrimarySlotGatePolicy::HostOwnedLuaDamage,
        },
        {
            {
                "spell_cast_028_earth_slot_gate",
                kSpellCast028SlotGateBranch,
                0,
                {},
                nops,
            },
            0x28,
            NativePrimarySlotGatePolicy::
                ParticipantPresentation,
        },
    }};
    std::string primary_gate_error;
    if (!ValidateNativePrimarySlotGatePatches(
            &primary_gate_error)) {
        RestoreNativeCastGatePatches();
        if (error_message != nullptr) {
            *error_message = primary_gate_error;
        }
        return false;
    }

    Log(
        "Gameplay input injection: native actor cast/mana gates unlocked. mana_delta=" +
        HexString(kPlayerActorApplyManaDeltaLocalActorGateBranch) +
        " cleanup=" +
        HexString(kCastCleanupSlotGateBranch) +
        " spell_008=" + HexString(kSpellCast008SlotGateBranch) +
        " spell_008_projectile=" + HexString(kSpellCast008ProjectileSlotGateBranch) +
        " scoped_primary_fire=" +
            HexString(kSpellCast010SlotGateBranch) +
        " scoped_primary_air_first=" +
            HexString(kSpellCast018FirstDamageSlotGateBranch) +
        " scoped_primary_air_chain=" +
            HexString(kSpellCast018ChainDamageSlotGateBranch) +
        " scoped_primary_water=" +
            HexString(kSpellCast020DamageSlotGateBranch) +
        " scoped_primary_earth=" +
            HexString(kSpellCast028SlotGateBranch) +
        " spell_3ee=" + HexString(kSpellCast3EESlotGateBranch) +
        " spell_3f0=" + HexString(kSpellCast3F0SlotGateBranch) +
        " fireball_damage=" +
            HexString(kFireballHitDamageProjectileGroupGateBranch) +
        " fireball_secondary_effect=" +
            HexString(kFireballHitSecondaryEffectProjectileGroupGateBranch) +
        " magic_missile_hit=" + HexString(kMagicMissileHitDamageProjectileGroupGateBranch));
    return true;
}
