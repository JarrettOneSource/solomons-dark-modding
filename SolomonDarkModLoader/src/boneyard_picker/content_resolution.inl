bool ResolveEntryFile(
    const BoneyardPickerEntry& entry,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    std::error_code error;
    if (!std::filesystem::is_regular_file(entry.stage_path, error)) {
        if (error_message != nullptr) {
            *error_message =
                "Selected Boneyard is missing from this staged mod set: " +
                entry.filename + " (" + entry.content_sha256 + ").";
        }
        return false;
    }
    const auto length = std::filesystem::file_size(entry.stage_path, error);
    if (error || length != entry.preview.file_length) {
        if (error_message != nullptr) {
            *error_message =
                "Selected Boneyard has the wrong staged length: " +
                entry.filename + " (" + entry.content_sha256 + ").";
        }
        return false;
    }

    HCRYPTPROV provider = 0;
    HCRYPTHASH hash = 0;
    if (!CryptAcquireContextW(
            &provider,
            nullptr,
            nullptr,
            PROV_RSA_AES,
            CRYPT_VERIFYCONTEXT) ||
        !CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash)) {
        const auto crypto_error = GetLastError();
        if (hash != 0) {
            CryptDestroyHash(hash);
        }
        if (provider != 0) {
            CryptReleaseContext(provider, 0);
        }
        if (error_message != nullptr) {
            *error_message =
                "Selected Boneyard could not be verified: " +
                entry.filename + " (Windows error " +
                std::to_string(crypto_error) + ").";
        }
        return false;
    }

    std::ifstream input(entry.stage_path, std::ios::binary);
    std::array<char, 64 * 1024> buffer{};
    bool read_ok = input.is_open();
    while (read_ok && input.good()) {
        input.read(
            buffer.data(),
            static_cast<std::streamsize>(buffer.size()));
        const auto bytes_read = input.gcount();
        if (bytes_read > 0 &&
            !CryptHashData(
                hash,
                reinterpret_cast<const BYTE*>(buffer.data()),
                static_cast<DWORD>(bytes_read),
                0)) {
            read_ok = false;
        }
    }
    read_ok = read_ok && (input.eof() || input.good());

    BoneyardPickerDigest actual_digest{};
    DWORD digest_length = static_cast<DWORD>(actual_digest.size());
    const bool digest_ok = read_ok &&
        CryptGetHashParam(
            hash,
            HP_HASHVAL,
            actual_digest.data(),
            &digest_length,
            0) &&
        digest_length == static_cast<DWORD>(actual_digest.size());
    CryptDestroyHash(hash);
    CryptReleaseContext(provider, 0);
    if (!digest_ok || actual_digest != entry.content_digest) {
        if (error_message != nullptr) {
            *error_message = digest_ok
                ? "Selected Boneyard bytes do not match the staged SHA-256: " +
                      entry.filename + " (" + entry.content_sha256 + ")."
                : "Selected Boneyard could not be read for SHA-256 verification: " +
                      entry.filename + ".";
        }
        return false;
    }
    return true;
}

void ResolveSelectedEntryLocked(std::uint64_t now_ms) {
    const auto* entry = SelectedEntryLocked();
    if (entry == nullptr) {
        g_picker.local_resolution = BoneyardResolutionStatus::Missing;
        g_picker.phase = BoneyardPickerPhase::Error;
        g_picker.error_message =
            "The host-selected Boneyard is not present in this staged mod catalog: " +
            DigestToHex(g_picker.selected_digest) + ".";
        g_picker.next_resolution_retry_ms = now_ms + kMissingResolutionRetryMs;
        return;
    }

    std::string resolution_error;
    if (!ResolveEntryFile(*entry, &resolution_error)) {
        g_picker.local_resolution = BoneyardResolutionStatus::Missing;
        g_picker.phase = BoneyardPickerPhase::Error;
        g_picker.error_message = std::move(resolution_error);
        g_picker.next_resolution_retry_ms = now_ms + kMissingResolutionRetryMs;
        return;
    }

    const bool recovered =
        g_picker.local_resolution == BoneyardResolutionStatus::Missing;
    g_picker.local_resolution = BoneyardResolutionStatus::Ready;
    g_picker.next_resolution_retry_ms = 0;
    g_picker.error_message.clear();
    if (!g_picker.native_launch_dispatched) {
        g_picker.phase = BoneyardPickerPhase::WaitingForPeers;
    }
    if (recovered) {
        Log(
            "Boneyard picker local resolution recovered. revision=" +
            std::to_string(g_picker.selection_revision) +
            " sha256=" + entry->content_sha256);
    }
}

void ApplyPendingPickLocked(
    std::size_t index,
    std::uint64_t now_ms) {
    if (g_picker.catalog == nullptr ||
        index >= g_picker.catalog->entries.size()) {
        g_picker.phase = BoneyardPickerPhase::Error;
        g_picker.error_message =
            "The queued Boneyard picker entry is no longer available.";
        return;
    }

    g_picker.selected_index = index;
    g_picker.placeholder_cursor = index;
    g_picker.selection_revision =
        NextRevision(g_picker.selection_revision);
    g_picker.selected_digest =
        g_picker.catalog->entries[index].content_digest;
    g_picker.remote_resolutions.clear();
    g_picker.missing_participant_ids.clear();
    g_picker.error_message.clear();
    g_picker.peer_resolution_error_active = false;
    g_picker.applied_stock_relative_path.clear();
    g_picker.next_peer_resolution_refresh_ms = 0;
    g_picker.native_launch_dispatched = false;
    g_picker.phase = BoneyardPickerPhase::WaitingForPeers;
    ResolveSelectedEntryLocked(now_ms);
    const auto& entry = g_picker.catalog->entries[index];
    Log(
        "Boneyard picker host selection published. revision=" +
        std::to_string(g_picker.selection_revision) +
        " index=" + std::to_string(index) +
        " sha256=" + entry.content_sha256 +
        " mod=" + entry.source_mod_id +
        " file=" + entry.filename +
        " resolution=" +
        BoneyardResolutionStatusLabel(g_picker.local_resolution));
}
