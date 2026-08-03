bool ParseHexDigest(std::string_view text, Digest* digest) {
    if (digest == nullptr || text.size() != digest->size() * 2) {
        return false;
    }
    const auto nibble = [](char value) -> int {
        if (value >= '0' && value <= '9') return value - '0';
        if (value >= 'a' && value <= 'f') return value - 'a' + 10;
        if (value >= 'A' && value <= 'F') return value - 'A' + 10;
        return -1;
    };
    for (std::size_t index = 0; index < digest->size(); ++index) {
        const auto high = nibble(text[index * 2]);
        const auto low = nibble(text[index * 2 + 1]);
        if (high < 0 || low < 0) {
            return false;
        }
        (*digest)[index] = static_cast<std::uint8_t>((high << 4) | low);
    }
    return true;
}

std::string DigestHex(const Digest& digest) {
    constexpr char digits[] = "0123456789abcdef";
    std::string result(digest.size() * 2, '0');
    for (std::size_t index = 0; index < digest.size(); ++index) {
        result[index * 2] = digits[digest[index] >> 4];
        result[index * 2 + 1] = digits[digest[index] & 0x0F];
    }
    return result;
}

bool HashBytes(const void* bytes, std::size_t size, Digest* digest) {
    if (digest == nullptr || (bytes == nullptr && size != 0) ||
        size > (std::numeric_limits<DWORD>::max)()) {
        return false;
    }
    HCRYPTPROV provider = 0;
    HCRYPTHASH hash = 0;
    const bool created = CryptAcquireContextW(
        &provider, nullptr, nullptr, PROV_RSA_AES, CRYPT_VERIFYCONTEXT) &&
        CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash);
    const bool hashed = created &&
        (size == 0 || CryptHashData(
            hash,
            static_cast<const BYTE*>(bytes),
            static_cast<DWORD>(size),
            0));
    DWORD digest_bytes = static_cast<DWORD>(digest->size());
    const bool read = hashed && CryptGetHashParam(
        hash, HP_HASHVAL, digest->data(), &digest_bytes, 0) &&
        digest_bytes == static_cast<DWORD>(digest->size());
    if (hash != 0) CryptDestroyHash(hash);
    if (provider != 0) CryptReleaseContext(provider, 0);
    return read;
}

bool HashFile(const std::filesystem::path& path, Digest* digest) {
    HCRYPTPROV provider = 0;
    HCRYPTHASH hash = 0;
    if (digest == nullptr ||
        !CryptAcquireContextW(
            &provider, nullptr, nullptr, PROV_RSA_AES, CRYPT_VERIFYCONTEXT) ||
        !CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash)) {
        if (hash != 0) CryptDestroyHash(hash);
        if (provider != 0) CryptReleaseContext(provider, 0);
        return false;
    }
    std::ifstream input(path, std::ios::binary);
    std::array<char, 64 * 1024> buffer{};
    bool ok = input.is_open();
    while (ok && input.good()) {
        input.read(
            buffer.data(),
            static_cast<std::streamsize>(buffer.size()));
        const auto count = input.gcount();
        if (count > 0 && !CryptHashData(
                hash,
                reinterpret_cast<const BYTE*>(buffer.data()),
                static_cast<DWORD>(count),
                0)) {
            ok = false;
        }
    }
    DWORD digest_bytes = static_cast<DWORD>(digest->size());
    ok = ok && input.eof() && CryptGetHashParam(
        hash, HP_HASHVAL, digest->data(), &digest_bytes, 0) &&
        digest_bytes == static_cast<DWORD>(digest->size());
    CryptDestroyHash(hash);
    CryptReleaseContext(provider, 0);
    return ok;
}

template <typename Integer>
Integer ReadLittleEndian(const std::uint8_t* bytes) {
    Integer value = 0;
    for (std::size_t index = 0; index < sizeof(Integer); ++index) {
        value |= static_cast<Integer>(bytes[index]) << (index * 8);
    }
    return value;
}

bool ReadFixedText(const std::uint8_t* source, std::size_t size, char* target) {
    if (source == nullptr || target == nullptr || size == 0) {
        return false;
    }
    std::size_t terminator = 0;
    while (terminator < size && source[terminator] != 0) ++terminator;
    if (terminator == 0 || terminator >= size) return false;
    if (MultiByteToWideChar(
            CP_UTF8,
            MB_ERR_INVALID_CHARS,
            reinterpret_cast<const char*>(source),
            static_cast<int>(terminator),
            nullptr,
            0) <= 0) {
        return false;
    }
    for (std::size_t index = terminator; index < size; ++index) {
        if (source[index] != 0) return false;
    }
    std::memcpy(target, source, size);
    return true;
}

bool LoadIndex(TransferIndex* index, std::string* error) {
    const auto path = g_stage_runtime_directory / "mod-transfer" / "index.bin";
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input.is_open()) {
        *error = "staged transfer index is missing";
        return false;
    }
    const auto stream_size = input.tellg();
    if (stream_size < static_cast<std::streamoff>(kIndexHeaderBytes) ||
        stream_size > static_cast<std::streamoff>(
            kIndexHeaderBytes + kModTransferMaxPackages * kIndexEntryBytes)) {
        *error = "staged transfer index has an invalid size";
        return false;
    }
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(stream_size));
    input.seekg(0);
    input.read(
        reinterpret_cast<char*>(bytes.data()),
        static_cast<std::streamsize>(bytes.size()));
    if (!input || std::memcmp(bytes.data(), "SDMXFER\0", 8) != 0 ||
        ReadLittleEndian<std::uint16_t>(bytes.data() + 8) != 1 ||
        ReadLittleEndian<std::uint16_t>(bytes.data() + 10) != kProtocolVersion ||
        ReadLittleEndian<std::uint32_t>(bytes.data() + 12) != kIndexHeaderBytes ||
        ReadLittleEndian<std::uint32_t>(bytes.data() + 16) != kIndexEntryBytes) {
        *error = "staged transfer index header is invalid";
        return false;
    }
    const auto count = ReadLittleEndian<std::uint32_t>(bytes.data() + 20);
    const auto total_bytes = ReadLittleEndian<std::uint64_t>(bytes.data() + 24);
    if (count > kModTransferMaxPackages || total_bytes > kModTransferMaxTotalBytes ||
        bytes.size() != kIndexHeaderBytes + count * kIndexEntryBytes) {
        *error = "staged transfer index bounds are invalid";
        return false;
    }
    std::memcpy(index->host_manifest_sha256.data(), bytes.data() + 32, 32);
    std::memcpy(index->index_sha256.data(), bytes.data() + 64, 32);
    if (index->host_manifest_sha256 != g_expected_manifest) {
        *error = "staged transfer fingerprint does not match the launched stage";
        return false;
    }
    Digest actual_index{};
    if (!HashBytes(bytes.data() + kIndexHeaderBytes,
                   bytes.size() - kIndexHeaderBytes,
                   &actual_index) ||
        actual_index != index->index_sha256) {
        *error = "staged transfer descriptor digest is invalid";
        return false;
    }
    index->total_package_bytes = total_bytes;
    index->entries.reserve(count);
    std::uint64_t checked_total = 0;
    for (std::uint32_t item = 0; item < count; ++item) {
        const auto* entry_bytes =
            bytes.data() + kIndexHeaderBytes + item * kIndexEntryBytes;
        TransferIndexEntry entry;
        if (!ReadFixedText(entry_bytes, 128, entry.mod_id.data()) ||
            !ReadFixedText(entry_bytes + 128, 64, entry.version.data())) {
            *error = "staged transfer descriptor text is invalid";
            return false;
        }
        std::memcpy(entry.content_sha256.data(), entry_bytes + 192, 32);
        std::memcpy(entry.package_sha256.data(), entry_bytes + 224, 32);
        entry.package_bytes = ReadLittleEndian<std::uint64_t>(entry_bytes + 256);
        if (entry.package_bytes == 0 ||
            entry.package_bytes > kModTransferMaxPackageBytes ||
            checked_total > kModTransferMaxTotalBytes - entry.package_bytes) {
            *error = "staged transfer package bounds are invalid";
            return false;
        }
        checked_total += entry.package_bytes;
        entry.package_path = g_stage_runtime_directory / "mod-transfer" /
            "packages" / (DigestHex(entry.package_sha256) + ".zip");
        std::error_code file_error;
        if (!std::filesystem::is_regular_file(entry.package_path, file_error) ||
            std::filesystem::file_size(entry.package_path, file_error) !=
                entry.package_bytes) {
            *error = "staged transfer package is missing or has the wrong size";
            return false;
        }
        Digest actual_package{};
        if (!HashFile(entry.package_path, &actual_package) ||
            actual_package != entry.package_sha256) {
            *error = "staged transfer package digest is invalid";
            return false;
        }
        index->entries.push_back(std::move(entry));
    }
    if (checked_total != total_bytes) {
        *error = "staged transfer aggregate size is invalid";
        return false;
    }
    return true;
}
