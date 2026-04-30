bool TryDeleteStagedSurvivalSaveDirectory(std::string* error_message) {
    std::error_code exists_error;
    const auto save_directory = GetStagedSurvivalSaveDirectoryPath();
    if (!std::filesystem::exists(save_directory, exists_error)) {
        return true;
    }

    std::error_code remove_error;
    std::filesystem::remove_all(save_directory, remove_error);
    if (!remove_error) {
        Log("Debug UI compatibility: deleted staged survival save directory at " + save_directory.string());
        return true;
    }

    if (error_message != nullptr) {
        *error_message =
            "Unable to delete the staged survival save directory at " + save_directory.string() +
            ": " + remove_error.message();
    }
    return false;
}

bool TryPrepareMainMenuNewGameCompatibility(uintptr_t main_menu_address, std::string* error_message) {
    if (main_menu_address == 0) {
        return true;
    }

    std::uint8_t has_previous_save = 0;
    if (!TryReadByteValueDirect(main_menu_address + kTitleMainMenuHasPreviousSaveOffset, &has_previous_save)) {
        if (error_message != nullptr) {
            *error_message =
                "Unable to read the Main Menu previous-save flag at " +
                HexString(main_menu_address + kTitleMainMenuHasPreviousSaveOffset) + ".";
        }
        return false;
    }

    if (has_previous_save == 0) {
        return true;
    }

    if (!TryDeleteStagedSurvivalSaveDirectory(error_message)) {
        return false;
    }

    constexpr std::uint8_t kNoPreviousSave = 0;
    if (!ProcessMemory::Instance().TryWriteValue(
            main_menu_address + kTitleMainMenuHasPreviousSaveOffset,
            kNoPreviousSave)) {
        if (error_message != nullptr) {
            *error_message =
                "Unable to clear the Main Menu previous-save flag at " +
                HexString(main_menu_address + kTitleMainMenuHasPreviousSaveOffset) + ".";
        }
        return false;
    }

    Log(
        "Debug UI compatibility: bypassed existing-save confirm for NEW GAME. menu=" +
        HexString(main_menu_address) + " cleared +" +
        HexString(kTitleMainMenuHasPreviousSaveOffset) + ".");
    return true;
}

}  // namespace
