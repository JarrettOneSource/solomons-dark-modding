struct BoneyardGeneratorPatchState {
    uintptr_t empty_candidate_address = 0;
    std::array<uintptr_t, 7> compact_flags_addresses = {};
    bool installed = false;
};

BoneyardGeneratorPatchState g_boneyard_generator_patch;

constexpr std::array<std::uint8_t, 8> kBoneyardGeneratorOriginalBytes = {0x3B, 0xFB, 0x7F, 0x04, 0x33, 0xC0, 0xEB, 0x09};
constexpr std::array<std::uint8_t, 8> kBoneyardGeneratorReplacementBytes = {0x85, 0xFF, 0x0F, 0x8E, 0xC2, 0x02, 0x00, 0x00};
constexpr std::array<std::uint8_t, 4> kBoneyardCompactFlagsOriginalBytes = {0x80, 0x4E, 0x18, 0x01};
constexpr std::array<std::uint8_t, 4> kBoneyardCompactFlagsReplacementBytes = {0xC6, 0x46, 0x18, 0x01};

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

    g_boneyard_generator_patch.empty_candidate_address =
        empty_candidate_address;
    g_boneyard_generator_patch.compact_flags_addresses =
        compact_flags_addresses;
    g_boneyard_generator_patch.installed = true;
    Log(
        "Boneyard generator patch installed. empty_candidate_branch=" +
        HexString(kBoneyardEmptyCandidateInterpolationBranch) +
        " compact_flags_sites=" +
        std::to_string(compact_flags_addresses.size()));
    return true;
}

void RestoreBoneyardGeneratorPatch() {
    if (!g_boneyard_generator_patch.installed ||
        g_boneyard_generator_patch.empty_candidate_address == 0) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
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
