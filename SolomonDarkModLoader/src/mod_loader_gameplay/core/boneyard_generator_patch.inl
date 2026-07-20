struct BoneyardGeneratorPatchState {
    uintptr_t resolved_address = 0;
    bool installed = false;
};

BoneyardGeneratorPatchState g_boneyard_generator_patch;

constexpr std::array<std::uint8_t, 8> kBoneyardGeneratorOriginalBytes = {0x3B, 0xFB, 0x7F, 0x04, 0x33, 0xC0, 0xEB, 0x09};
constexpr std::array<std::uint8_t, 8> kBoneyardGeneratorReplacementBytes = {0x85, 0xFF, 0x0F, 0x8E, 0xC2, 0x02, 0x00, 0x00};

std::string FormatBoneyardGeneratorPatchBytes(
    const std::array<std::uint8_t, 8>& bytes) {
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
    const auto resolved_address =
        memory.ResolveGameAddressOrZero(kBoneyardEmptyCandidateInterpolationBranch);
    if (resolved_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "unable to resolve Boneyard empty-candidate branch at " +
                HexString(kBoneyardEmptyCandidateInterpolationBranch);
        }
        return false;
    }

    std::array<std::uint8_t, 8> current = {};
    if (!memory.TryRead(resolved_address, current.data(), current.size())) {
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
    if (!memory.TryWrite(
            resolved_address,
            kBoneyardGeneratorReplacementBytes.data(),
            kBoneyardGeneratorReplacementBytes.size())) {
        if (error_message != nullptr) {
            *error_message =
                "unable to patch Boneyard empty-candidate branch at " +
                HexString(kBoneyardEmptyCandidateInterpolationBranch);
        }
        return false;
    }

    g_boneyard_generator_patch.resolved_address = resolved_address;
    g_boneyard_generator_patch.installed = true;
    Log(
        "Boneyard generator patch installed. empty_candidate_branch=" +
        HexString(kBoneyardEmptyCandidateInterpolationBranch));
    return true;
}

void RestoreBoneyardGeneratorPatch() {
    if (!g_boneyard_generator_patch.installed ||
        g_boneyard_generator_patch.resolved_address == 0) {
        return;
    }
    (void)ProcessMemory::Instance().TryWrite(
        g_boneyard_generator_patch.resolved_address,
        kBoneyardGeneratorOriginalBytes.data(),
        kBoneyardGeneratorOriginalBytes.size());
    g_boneyard_generator_patch = {};
}
