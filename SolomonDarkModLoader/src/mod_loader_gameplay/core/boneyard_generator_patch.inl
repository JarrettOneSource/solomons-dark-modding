struct BoneyardGeneratorPatchState {
    uintptr_t empty_candidate_address = 0;
    std::array<uintptr_t, 7> compact_flags_addresses = {};
    std::array<X86Hook, 7> presentation_hooks = {};
    uintptr_t native_rng_integer_address = 0;
    uintptr_t native_rng_float_address = 0;
    uintptr_t marker_primary_tint_rng_address = 0;
    uintptr_t compact_ambient_rng_gate_address = 0;
    uintptr_t secondary_ambient_rng_gate_address = 0;
    uintptr_t marker_secondary_tint_rng_address = 0;
    bool installed = false;
};

BoneyardGeneratorPatchState g_boneyard_generator_patch;

enum BoneyardPresentationHookIndex : std::size_t {
    kBoneyardTreeCtorHook = 0,
    kBoneyardTreeTickHook,
    kBoneyardTreeRenderOverlayHook,
    kBoneyardSceneryRenderLightingHook,
    kBoneyardScrubCtorHook,
    kBoneyardScrubTickHook,
    kBoneyardGoodieCtorHook,
};

using BoneyardObjectCtorFn = void*(__thiscall*)(void* self);
using BoneyardObjectTickFn = void(__thiscall*)(void* self);
using BoneyardNativeRngIntegerFn =
    std::int32_t(__thiscall*)(void* self, std::int32_t range, std::int32_t sign_mode);
using BoneyardNativeRngFloatFn =
    float(__thiscall*)(void* self, float scale, std::int32_t sign_mode);

constexpr std::uint32_t kBoneyardTreeTypeId = 2001;
constexpr std::uint32_t kBoneyardCanonicalTreeSwayCountdown = 25;
constexpr std::uint32_t kBoneyardScrubPhasePeriod = 360;
constexpr std::size_t kBoneyardPresentationHookMinimumPatchSize = 5;
constexpr std::array<std::uint8_t, 8> kBoneyardGeneratorOriginalBytes = {0x3B, 0xFB, 0x7F, 0x04, 0x33, 0xC0, 0xEB, 0x09};
constexpr std::array<std::uint8_t, 8> kBoneyardGeneratorReplacementBytes = {0x85, 0xFF, 0x0F, 0x8E, 0xC2, 0x02, 0x00, 0x00};
constexpr std::array<std::uint8_t, 4> kBoneyardCompactFlagsOriginalBytes = {0x80, 0x4E, 0x18, 0x01};
constexpr std::array<std::uint8_t, 4> kBoneyardCompactFlagsReplacementBytes = {0xC6, 0x46, 0x18, 0x01};
constexpr std::array<std::uint8_t, 5> kBoneyardCompactAmbientRngOriginalBytes = {
    0xE8, 0x66, 0xF9, 0xF8, 0xFF};
constexpr std::array<std::uint8_t, 5> kBoneyardSecondaryAmbientRngOriginalBytes = {
    0xE8, 0xA9, 0xED, 0xF8, 0xFF};
constexpr std::array<std::uint8_t, 5> kBoneyardMarkerPrimaryTintRngOriginalBytes = {
    0xE8, 0x50, 0x00, 0xF9, 0xFF};
constexpr std::array<std::uint8_t, 5> kBoneyardMarkerSecondaryTintRngOriginalBytes = {
    0xE8, 0x28, 0xEC, 0xF8, 0xFF};

std::uint32_t MixBoneyardPresentationSeed(
    std::uint32_t hash,
    std::uint32_t value) {
    hash ^= value + 0x9E3779B9u + (hash << 6) + (hash >> 2);
    hash ^= hash >> 16;
    hash *= 0x7FEB352Du;
    hash ^= hash >> 15;
    return hash;
}

std::uint32_t StableBoneyardSceneryHash(
    void* self,
    std::uint32_t salt) {
    const auto address = reinterpret_cast<uintptr_t>(self);
    auto hash = MixBoneyardPresentationSeed(
        salt,
        g_gameplay_keyboard_injection.applied_run_generation_seed.load(
            std::memory_order_acquire));
    hash = MixBoneyardPresentationSeed(
        hash,
        *reinterpret_cast<const std::uint32_t*>(
            address + kActorPositionXOffset));
    hash = MixBoneyardPresentationSeed(
        hash,
        *reinterpret_cast<const std::uint32_t*>(
            address + kActorPositionYOffset));
    hash = MixBoneyardPresentationSeed(
        hash,
        *reinterpret_cast<const std::uint32_t*>(
            address + kRegionObjectTypeIdOffset));
    return MixBoneyardPresentationSeed(
        hash,
        *reinterpret_cast<const std::uint32_t*>(
            address + kBoneyardScrubVariantOffset));
}

float StableBoneyardTreeLightingScalar(void* self) {
    const auto hash = StableBoneyardSceneryHash(self, 0x71EEu);
    constexpr float kUnitDenominator = 16777215.0f;
    const auto unit =
        static_cast<float>(hash & 0x00FFFFFFu) / kUnitDenominator;
    return 0.5f + unit * 0.5f;
}

float StableBoneyardTreeSwayScale(void* self) {
    const auto hash = StableBoneyardSceneryHash(self, 0x5A7A11u);
    constexpr float kUnitDenominator = 16777215.0f;
    const auto unit =
        static_cast<float>(hash & 0x00FFFFFFu) / kUnitDenominator;
    return 0.96f + unit * 0.08f;
}

std::uint32_t StableBoneyardScrubPhase(void* self) {
    const auto hash =
        StableBoneyardSceneryHash(self, 0xB07E5EEDu);
    return hash % kBoneyardScrubPhasePeriod;
}

float StableBoneyardMarkerTint(float scale, std::uint32_t salt) {
    auto hash = MixBoneyardPresentationSeed(
        0xA6E4A2D5u ^ salt,
        g_gameplay_keyboard_injection.applied_run_generation_seed.load(
            std::memory_order_acquire));
    hash = MixBoneyardPresentationSeed(hash, salt);
    constexpr float kUnitDenominator = 16777215.0f;
    const auto unit =
        static_cast<float>(hash & 0x00FFFFFFu) / kUnitDenominator;
    return unit * scale;
}

void SetBoneyardTreeLightingScalar(void* self, float scalar) {
    *reinterpret_cast<float*>(
        reinterpret_cast<uintptr_t>(self) +
        kBoneyardSceneryCommonScalarOffset) = scalar;
}

void CanonicalizeBoneyardTreeLightingScalar(void* self) {
    SetBoneyardTreeLightingScalar(
        self,
        StableBoneyardTreeLightingScalar(self));
}

void* __fastcall HookBoneyardTreeCtor(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<BoneyardObjectCtorFn>(
        g_boneyard_generator_patch.presentation_hooks[
            kBoneyardTreeCtorHook]);
    void* result = original(self);
    if (multiplayer::IsLocalTransportEnabled() && result != nullptr) {
        SetBoneyardTreeLightingScalar(result, 1.0f);
    }
    return result;
}

void __fastcall HookBoneyardTreeTick(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<BoneyardObjectTickFn>(
        g_boneyard_generator_patch.presentation_hooks[
            kBoneyardTreeTickHook]);
    original(self);
    if (!multiplayer::IsLocalTransportEnabled() || self == nullptr) {
        return;
    }

    const auto address = reinterpret_cast<uintptr_t>(self);
    *reinterpret_cast<std::uint32_t*>(
        address + kBoneyardTreeSwayCountdownOffset) =
        kBoneyardCanonicalTreeSwayCountdown;
    const auto stable_sway = StableBoneyardTreeSwayScale(self);
    *reinterpret_cast<float*>(
        address + kBoneyardTreeSwayTargetOffset) = stable_sway;
    *reinterpret_cast<float*>(
        address + kBoneyardTreeSwayCurrentOffset) = stable_sway;
    CanonicalizeBoneyardTreeLightingScalar(self);
}

void __fastcall HookBoneyardTreeRenderOverlay(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<BoneyardObjectTickFn>(
        g_boneyard_generator_patch.presentation_hooks[
            kBoneyardTreeRenderOverlayHook]);
    if (multiplayer::IsLocalTransportEnabled() && self != nullptr) {
        CanonicalizeBoneyardTreeLightingScalar(self);
    }
    original(self);
}

void __fastcall HookBoneyardSceneryRenderLighting(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<BoneyardObjectTickFn>(
        g_boneyard_generator_patch.presentation_hooks[
            kBoneyardSceneryRenderLightingHook]);
    original(self);
    if (!multiplayer::IsLocalTransportEnabled() || self == nullptr) {
        return;
    }
    if (*reinterpret_cast<const std::uint32_t*>(
            reinterpret_cast<uintptr_t>(self) +
            kRegionObjectTypeIdOffset) == kBoneyardTreeTypeId) {
        CanonicalizeBoneyardTreeLightingScalar(self);
    }
}

void* __fastcall HookBoneyardScrubCtor(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<BoneyardObjectCtorFn>(
        g_boneyard_generator_patch.presentation_hooks[
            kBoneyardScrubCtorHook]);
    void* result = original(self);
    if (multiplayer::IsLocalTransportEnabled() && result != nullptr) {
        *reinterpret_cast<std::uint32_t*>(
            reinterpret_cast<uintptr_t>(result) +
            kBoneyardScrubPhaseOffset) = 0;
    }
    return result;
}

void __fastcall HookBoneyardScrubTick(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<BoneyardObjectTickFn>(
        g_boneyard_generator_patch.presentation_hooks[
            kBoneyardScrubTickHook]);
    original(self);
    if (multiplayer::IsLocalTransportEnabled() && self != nullptr) {
        *reinterpret_cast<std::uint32_t*>(
            reinterpret_cast<uintptr_t>(self) +
            kBoneyardScrubPhaseOffset) =
            StableBoneyardScrubPhase(self);
    }
}

void* __fastcall HookBoneyardGoodieCtor(
    void* self,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<BoneyardObjectCtorFn>(
        g_boneyard_generator_patch.presentation_hooks[
            kBoneyardGoodieCtorHook]);
    void* result = original(self);
    if (multiplayer::IsLocalTransportEnabled() && result != nullptr) {
        *reinterpret_cast<std::uint32_t*>(
            reinterpret_cast<uintptr_t>(result) +
            kBoneyardGoodieTimerOffset) = 0;
    }
    return result;
}

std::int32_t __fastcall BoneyardAmbientRngGate(
    void* self,
    void* /*unused_edx*/,
    std::int32_t range,
    std::int32_t sign_mode) {
    if (multiplayer::IsLocalTransportEnabled()) {
        return 0;
    }
    const auto original = reinterpret_cast<BoneyardNativeRngIntegerFn>(
        g_boneyard_generator_patch.native_rng_integer_address);
    return original(self, range, sign_mode);
}

float BoneyardMarkerTintRng(
    void* self,
    float scale,
    std::int32_t sign_mode,
    std::uint32_t salt) {
    if (multiplayer::IsLocalTransportEnabled()) {
        float value = StableBoneyardMarkerTint(scale, salt);
        if (sign_mode == 1 && (salt & 1u) != 0) {
            value = -value;
        }
        return value;
    }
    const auto original = reinterpret_cast<BoneyardNativeRngFloatFn>(
        g_boneyard_generator_patch.native_rng_float_address);
    return original(self, scale, sign_mode);
}

float __fastcall BoneyardMarkerPrimaryTintRng(
    void* self,
    void* /*unused_edx*/,
    float scale,
    std::int32_t sign_mode) {
    return BoneyardMarkerTintRng(
        self,
        scale,
        sign_mode,
        0x4712BBu);
}

float __fastcall BoneyardMarkerSecondaryTintRng(
    void* self,
    void* /*unused_edx*/,
    float scale,
    std::int32_t sign_mode) {
    return BoneyardMarkerTintRng(
        self,
        scale,
        sign_mode,
        0x4726E3u);
}

std::array<std::uint8_t, 5> BuildBoneyardRelativeCall(
    uintptr_t callsite,
    const void* target) {
    std::array<std::uint8_t, 5> bytes = {0xE8, 0, 0, 0, 0};
    const auto relative =
        reinterpret_cast<intptr_t>(target) -
        static_cast<intptr_t>(callsite + bytes.size());
    const auto relative32 = static_cast<std::int32_t>(relative);
    std::memcpy(bytes.data() + 1, &relative32, sizeof(relative32));
    return bytes;
}

template <std::size_t Size>
std::string FormatBoneyardGeneratorPatchBytes(
    const std::array<std::uint8_t, Size>& bytes) {
    std::ostringstream out;
    for (std::size_t index = 0; index < bytes.size(); ++index) {
        if (index != 0) {
            out << ' ';
        }
        out << HexString(static_cast<std::uint32_t>(bytes[index]));
    }
    return out.str();
}

bool InstallBoneyardGeneratorPatch(std::string* error_message) {
    if (g_boneyard_generator_patch.installed) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto empty_candidate_address =
        memory.ResolveGameAddressOrZero(kBoneyardEmptyCandidateInterpolationBranch);
    if (empty_candidate_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "unable to resolve Boneyard empty-candidate branch at " +
                HexString(kBoneyardEmptyCandidateInterpolationBranch);
        }
        return false;
    }

    std::array<uintptr_t, 7> compact_flags_addresses = {};
    for (std::size_t index = 0; index < compact_flags_addresses.size(); ++index) {
        compact_flags_addresses[index] =
            memory.ResolveGameAddressOrZero(kBoneyardCompactFlagsInitializeSites[index]);
        if (compact_flags_addresses[index] == 0) {
            if (error_message != nullptr) {
                *error_message =
                    "unable to resolve Boneyard compact-decoration flags site " +
                    std::to_string(index) + " at " +
                    HexString(kBoneyardCompactFlagsInitializeSites[index]);
            }
            return false;
        }
    }

    const std::array<uintptr_t, 7> presentation_addresses = {
        memory.ResolveGameAddressOrZero(kBoneyardTreeCtor),
        memory.ResolveGameAddressOrZero(kBoneyardTreeTick),
        memory.ResolveGameAddressOrZero(kBoneyardTreeRenderOverlay),
        memory.ResolveGameAddressOrZero(kBoneyardSceneryRenderLighting),
        memory.ResolveGameAddressOrZero(kBoneyardScrubCtor),
        memory.ResolveGameAddressOrZero(kBoneyardScrubTick),
        memory.ResolveGameAddressOrZero(kBoneyardGoodieCtor),
    };
    for (std::size_t index = 0;
         index < presentation_addresses.size();
         ++index) {
        if (presentation_addresses[index] != 0) {
            continue;
        }
        if (error_message != nullptr) {
            *error_message =
                "unable to resolve Boneyard presentation hook " +
                std::to_string(index);
        }
        return false;
    }
    const auto compact_ambient_rng_gate =
        memory.ResolveGameAddressOrZero(
            kBoneyardCompactAmbientRngGate);
    const auto secondary_ambient_rng_gate =
        memory.ResolveGameAddressOrZero(
            kBoneyardSecondaryAmbientRngGate);
    const auto marker_primary_tint_rng =
        memory.ResolveGameAddressOrZero(
            kBoneyardArenaMarkerPrimaryTintRng);
    const auto marker_secondary_tint_rng =
        memory.ResolveGameAddressOrZero(
            kBoneyardArenaMarkerSecondaryTintRng);
    const auto native_rng_integer_address =
        memory.ResolveGameAddressOrZero(kNativeRngInteger);
    const auto native_rng_float_address =
        memory.ResolveGameAddressOrZero(kNativeRngFloat);
    if (native_rng_integer_address == 0 ||
        native_rng_float_address == 0 ||
        marker_primary_tint_rng == 0 ||
        compact_ambient_rng_gate == 0 ||
        secondary_ambient_rng_gate == 0 ||
        marker_secondary_tint_rng == 0) {
        if (error_message != nullptr) {
            *error_message =
                "unable to resolve Boneyard render RNG call sites";
        }
        return false;
    }

    std::array<std::uint8_t, 8> current = {};
    if (!memory.TryRead(
            empty_candidate_address,
            current.data(),
            current.size())) {
        if (error_message != nullptr) {
            *error_message =
                "unable to read Boneyard empty-candidate branch at " +
                HexString(kBoneyardEmptyCandidateInterpolationBranch);
        }
        return false;
    }
    if (current != kBoneyardGeneratorOriginalBytes) {
        if (error_message != nullptr) {
            *error_message =
                "Boneyard empty-candidate branch does not match the supported binary. actual=" +
                FormatBoneyardGeneratorPatchBytes(current);
        }
        return false;
    }

    for (std::size_t index = 0; index < compact_flags_addresses.size(); ++index) {
        std::array<std::uint8_t, 4> compact_current = {};
        if (!memory.TryRead(
                compact_flags_addresses[index],
                compact_current.data(),
                compact_current.size())) {
            if (error_message != nullptr) {
                *error_message =
                    "unable to read Boneyard compact-decoration flags site " +
                    std::to_string(index) + " at " +
                    HexString(kBoneyardCompactFlagsInitializeSites[index]);
            }
            return false;
        }
        if (compact_current != kBoneyardCompactFlagsOriginalBytes) {
            if (error_message != nullptr) {
                *error_message =
                    "Boneyard compact-decoration flags site " +
                    std::to_string(index) +
                    " does not match the supported binary. actual=" +
                    FormatBoneyardGeneratorPatchBytes(compact_current);
            }
            return false;
        }
    }

    std::array<std::uint8_t, 5> marker_primary_tint_current = {};
    std::array<std::uint8_t, 5> compact_ambient_current = {};
    std::array<std::uint8_t, 5> secondary_ambient_current = {};
    std::array<std::uint8_t, 5> marker_secondary_tint_current = {};
    if (!memory.TryRead(
            marker_primary_tint_rng,
            marker_primary_tint_current.data(),
            marker_primary_tint_current.size()) ||
        !memory.TryRead(
            compact_ambient_rng_gate,
            compact_ambient_current.data(),
            compact_ambient_current.size()) ||
        !memory.TryRead(
            secondary_ambient_rng_gate,
            secondary_ambient_current.data(),
            secondary_ambient_current.size()) ||
        !memory.TryRead(
            marker_secondary_tint_rng,
            marker_secondary_tint_current.data(),
            marker_secondary_tint_current.size())) {
        if (error_message != nullptr) {
            *error_message =
                "unable to read Boneyard render RNG call sites";
        }
        return false;
    }
    if (marker_primary_tint_current !=
            kBoneyardMarkerPrimaryTintRngOriginalBytes ||
        compact_ambient_current !=
            kBoneyardCompactAmbientRngOriginalBytes ||
        secondary_ambient_current !=
            kBoneyardSecondaryAmbientRngOriginalBytes ||
        marker_secondary_tint_current !=
            kBoneyardMarkerSecondaryTintRngOriginalBytes) {
        if (error_message != nullptr) {
            *error_message =
                "Boneyard render RNG call sites do not match the supported binary";
        }
        return false;
    }

    if (!memory.TryWrite(
            empty_candidate_address,
            kBoneyardGeneratorReplacementBytes.data(),
            kBoneyardGeneratorReplacementBytes.size())) {
        if (error_message != nullptr) {
            *error_message =
                "unable to patch Boneyard empty-candidate branch at " +
                HexString(kBoneyardEmptyCandidateInterpolationBranch);
        }
        return false;
    }

    std::size_t compact_flags_written = 0;
    for (; compact_flags_written < compact_flags_addresses.size();
         ++compact_flags_written) {
        if (memory.TryWrite(
                compact_flags_addresses[compact_flags_written],
                kBoneyardCompactFlagsReplacementBytes.data(),
                kBoneyardCompactFlagsReplacementBytes.size())) {
            continue;
        }

        for (std::size_t restore_index = 0;
             restore_index < compact_flags_written;
             ++restore_index) {
            (void)memory.TryWrite(
                compact_flags_addresses[restore_index],
                kBoneyardCompactFlagsOriginalBytes.data(),
                kBoneyardCompactFlagsOriginalBytes.size());
        }
        (void)memory.TryWrite(
            empty_candidate_address,
            kBoneyardGeneratorOriginalBytes.data(),
            kBoneyardGeneratorOriginalBytes.size());
        if (error_message != nullptr) {
            *error_message =
                "unable to patch Boneyard compact-decoration flags site " +
                std::to_string(compact_flags_written) + " at " +
                HexString(
                    kBoneyardCompactFlagsInitializeSites[compact_flags_written]);
        }
        return false;
    }

    g_boneyard_generator_patch.native_rng_integer_address =
        native_rng_integer_address;
    g_boneyard_generator_patch.native_rng_float_address =
        native_rng_float_address;
    g_boneyard_generator_patch.marker_primary_tint_rng_address =
        marker_primary_tint_rng;
    g_boneyard_generator_patch.compact_ambient_rng_gate_address =
        compact_ambient_rng_gate;
    g_boneyard_generator_patch.secondary_ambient_rng_gate_address =
        secondary_ambient_rng_gate;
    g_boneyard_generator_patch.marker_secondary_tint_rng_address =
        marker_secondary_tint_rng;
    const std::array<uintptr_t, 4> render_rng_addresses = {
        marker_primary_tint_rng,
        compact_ambient_rng_gate,
        secondary_ambient_rng_gate,
        marker_secondary_tint_rng,
    };
    const std::array<std::array<std::uint8_t, 5>, 4>
        render_rng_original_bytes = {
            kBoneyardMarkerPrimaryTintRngOriginalBytes,
            kBoneyardCompactAmbientRngOriginalBytes,
            kBoneyardSecondaryAmbientRngOriginalBytes,
            kBoneyardMarkerSecondaryTintRngOriginalBytes,
        };
    const std::array<const void*, 4> render_rng_detours = {
        reinterpret_cast<const void*>(&BoneyardMarkerPrimaryTintRng),
        reinterpret_cast<const void*>(&BoneyardAmbientRngGate),
        reinterpret_cast<const void*>(&BoneyardAmbientRngGate),
        reinterpret_cast<const void*>(&BoneyardMarkerSecondaryTintRng),
    };
    std::array<std::array<std::uint8_t, 5>, 4>
        render_rng_replacements = {};
    for (std::size_t index = 0;
         index < render_rng_replacements.size();
         ++index) {
        render_rng_replacements[index] = BuildBoneyardRelativeCall(
            render_rng_addresses[index],
            render_rng_detours[index]);
    }
    std::size_t render_rng_written = 0;
    for (; render_rng_written < render_rng_addresses.size();
         ++render_rng_written) {
        if (memory.TryWrite(
                render_rng_addresses[render_rng_written],
                render_rng_replacements[render_rng_written].data(),
                render_rng_replacements[render_rng_written].size())) {
            continue;
        }
        for (std::size_t restore_index = 0;
             restore_index < render_rng_written;
             ++restore_index) {
            (void)memory.TryWrite(
                render_rng_addresses[restore_index],
                render_rng_original_bytes[restore_index].data(),
                render_rng_original_bytes[restore_index].size());
        }
        for (const auto address : compact_flags_addresses) {
            (void)memory.TryWrite(
                address,
                kBoneyardCompactFlagsOriginalBytes.data(),
                kBoneyardCompactFlagsOriginalBytes.size());
        }
        (void)memory.TryWrite(
            empty_candidate_address,
            kBoneyardGeneratorOriginalBytes.data(),
            kBoneyardGeneratorOriginalBytes.size());
        g_boneyard_generator_patch = {};
        if (error_message != nullptr) {
            *error_message =
                "unable to patch Boneyard render RNG call site " +
                std::to_string(render_rng_written);
        }
        return false;
    }

    const std::array<void*, 7> presentation_detours = {
        reinterpret_cast<void*>(&HookBoneyardTreeCtor),
        reinterpret_cast<void*>(&HookBoneyardTreeTick),
        reinterpret_cast<void*>(&HookBoneyardTreeRenderOverlay),
        reinterpret_cast<void*>(&HookBoneyardSceneryRenderLighting),
        reinterpret_cast<void*>(&HookBoneyardScrubCtor),
        reinterpret_cast<void*>(&HookBoneyardScrubTick),
        reinterpret_cast<void*>(&HookBoneyardGoodieCtor),
    };
    const std::array<const char*, 7> presentation_names = {
        "Tree constructor",
        "Tree tick",
        "Tree overlay render",
        "scenery render lighting",
        "Scrub constructor",
        "Scrub tick",
        "Goodie constructor",
    };
    std::size_t presentation_hooks_written = 0;
    std::string presentation_hook_error;
    for (; presentation_hooks_written < presentation_addresses.size();
         ++presentation_hooks_written) {
        if (InstallSafeX86Hook(
                reinterpret_cast<void*>(
                    presentation_addresses[presentation_hooks_written]),
                presentation_detours[presentation_hooks_written],
                kBoneyardPresentationHookMinimumPatchSize,
                &g_boneyard_generator_patch.presentation_hooks[
                    presentation_hooks_written],
                &presentation_hook_error)) {
            continue;
        }
        for (std::size_t restore_index = 0;
             restore_index < presentation_hooks_written;
             ++restore_index) {
            RemoveX86Hook(
                &g_boneyard_generator_patch.presentation_hooks[
                    restore_index]);
        }
        for (const auto address : compact_flags_addresses) {
            (void)memory.TryWrite(
                address,
                kBoneyardCompactFlagsOriginalBytes.data(),
                kBoneyardCompactFlagsOriginalBytes.size());
        }
        for (std::size_t restore_index = 0;
             restore_index < render_rng_addresses.size();
             ++restore_index) {
            (void)memory.TryWrite(
                render_rng_addresses[restore_index],
                render_rng_original_bytes[restore_index].data(),
                render_rng_original_bytes[restore_index].size());
        }
        (void)memory.TryWrite(
            empty_candidate_address,
            kBoneyardGeneratorOriginalBytes.data(),
            kBoneyardGeneratorOriginalBytes.size());
        g_boneyard_generator_patch = {};
        if (error_message != nullptr) {
            *error_message =
                "unable to install Boneyard " +
                std::string(
                    presentation_names[presentation_hooks_written]) +
                " hook: " + presentation_hook_error;
        }
        return false;
    }

    g_boneyard_generator_patch.empty_candidate_address =
        empty_candidate_address;
    g_boneyard_generator_patch.compact_flags_addresses =
        compact_flags_addresses;
    g_boneyard_generator_patch.installed = true;
    Log(
        "Boneyard generator patch installed. empty_candidate_branch=" +
        HexString(kBoneyardEmptyCandidateInterpolationBranch) +
        " compact_flags_sites=" +
        std::to_string(compact_flags_addresses.size()) +
        " presentation_hooks=" +
        std::to_string(presentation_addresses.size()) +
        " ambient_rng_suppression=2"
        " marker_tint_rng_stabilization=2");
    return true;
}

void RestoreBoneyardGeneratorPatch() {
    if (!g_boneyard_generator_patch.installed ||
        g_boneyard_generator_patch.empty_candidate_address == 0) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    for (auto& hook :
         g_boneyard_generator_patch.presentation_hooks) {
        RemoveX86Hook(&hook);
    }
    if (g_boneyard_generator_patch.marker_primary_tint_rng_address != 0) {
        (void)memory.TryWrite(
            g_boneyard_generator_patch
                .marker_primary_tint_rng_address,
            kBoneyardMarkerPrimaryTintRngOriginalBytes.data(),
            kBoneyardMarkerPrimaryTintRngOriginalBytes.size());
    }
    if (g_boneyard_generator_patch.compact_ambient_rng_gate_address != 0) {
        (void)memory.TryWrite(
            g_boneyard_generator_patch
                .compact_ambient_rng_gate_address,
            kBoneyardCompactAmbientRngOriginalBytes.data(),
            kBoneyardCompactAmbientRngOriginalBytes.size());
    }
    if (g_boneyard_generator_patch.secondary_ambient_rng_gate_address != 0) {
        (void)memory.TryWrite(
            g_boneyard_generator_patch
                .secondary_ambient_rng_gate_address,
            kBoneyardSecondaryAmbientRngOriginalBytes.data(),
            kBoneyardSecondaryAmbientRngOriginalBytes.size());
    }
    if (g_boneyard_generator_patch.marker_secondary_tint_rng_address != 0) {
        (void)memory.TryWrite(
            g_boneyard_generator_patch
                .marker_secondary_tint_rng_address,
            kBoneyardMarkerSecondaryTintRngOriginalBytes.data(),
            kBoneyardMarkerSecondaryTintRngOriginalBytes.size());
    }
    for (const auto address :
         g_boneyard_generator_patch.compact_flags_addresses) {
        if (address == 0) {
            continue;
        }
        (void)memory.TryWrite(
            address,
            kBoneyardCompactFlagsOriginalBytes.data(),
            kBoneyardCompactFlagsOriginalBytes.size());
    }
    (void)memory.TryWrite(
        g_boneyard_generator_patch.empty_candidate_address,
        kBoneyardGeneratorOriginalBytes.data(),
        kBoneyardGeneratorOriginalBytes.size());
    g_boneyard_generator_patch = {};
}
