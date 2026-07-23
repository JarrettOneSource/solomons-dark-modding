#include "lua_sprite_runtime.h"

#include "lua_draw_internal.h"

#include <Windows.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <utility>

namespace sdmod {
namespace {

constexpr std::array<std::uint8_t, 8> kPngSignature = {
    0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A,
};

struct LuaSpriteAtlasRegistration {
    LuaSpriteAtlasSnapshot snapshot;
    std::filesystem::path canonical_image_path;
    std::vector<LuaDrawSpriteInfo> frames;
};

struct LuaSpriteRegistryState {
    std::map<std::string, LuaSpriteAtlasRegistration> atlases;
    std::uint64_t next_revision = 1;
    std::mutex mutex;
};

LuaSpriteRegistryState& SpriteRegistry() {
    static LuaSpriteRegistryState registry;
    return registry;
}

void SetError(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
}

bool EqualPathComponent(
    const std::filesystem::path& left,
    const std::filesystem::path& right) {
    const auto& left_text = left.native();
    const auto& right_text = right.native();
    return CompareStringOrdinal(
               left_text.c_str(),
               static_cast<int>(left_text.size()),
               right_text.c_str(),
               static_cast<int>(right_text.size()),
               TRUE) == CSTR_EQUAL;
}

bool IsWithinRoot(
    const std::filesystem::path& root,
    const std::filesystem::path& candidate) {
    auto root_component = root.begin();
    auto candidate_component = candidate.begin();
    while (root_component != root.end()) {
        if (candidate_component == candidate.end() ||
            !EqualPathComponent(*root_component, *candidate_component)) {
            return false;
        }
        ++root_component;
        ++candidate_component;
    }
    return true;
}

bool HasExtension(
    const std::filesystem::path& path,
    const wchar_t* expected) {
    const auto extension = path.extension().native();
    return CompareStringOrdinal(
               extension.c_str(),
               static_cast<int>(extension.size()),
               expected,
               -1,
               TRUE) == CSTR_EQUAL;
}

bool ResolveSpriteAssetPath(
    const std::filesystem::path& mod_root,
    std::string_view relative_path,
    const wchar_t* required_extension,
    std::uintmax_t maximum_bytes,
    std::filesystem::path* resolved_path,
    std::string* error_message) {
    if (resolved_path == nullptr || error_message == nullptr) {
        return false;
    }
    resolved_path->clear();
    if (relative_path.empty() ||
        relative_path.size() > kLuaSpriteMaximumRelativePathBytes ||
        relative_path.find('\0') != std::string_view::npos) {
        SetError(error_message, "sprite path must contain 1 through 512 bytes");
        return false;
    }

    const int decoded_size = MultiByteToWideChar(
        CP_UTF8,
        MB_ERR_INVALID_CHARS,
        relative_path.data(),
        static_cast<int>(relative_path.size()),
        nullptr,
        0);
    if (decoded_size <= 0) {
        SetError(error_message, "sprite path must be valid UTF-8");
        return false;
    }
    std::wstring decoded_path(static_cast<std::size_t>(decoded_size), L'\0');
    if (MultiByteToWideChar(
            CP_UTF8,
            MB_ERR_INVALID_CHARS,
            relative_path.data(),
            static_cast<int>(relative_path.size()),
            decoded_path.data(),
            decoded_size) != decoded_size) {
        SetError(error_message, "sprite path must be valid UTF-8");
        return false;
    }

    const std::filesystem::path relative(decoded_path);
    if (relative.empty() || relative.is_absolute() || relative.has_root_path()) {
        SetError(error_message, "sprite path must be relative to the owning mod root");
        return false;
    }
    for (const auto& component : relative) {
        if (component == "." || component == "..") {
            SetError(error_message, "sprite path may not contain '.' or '..' components");
            return false;
        }
    }
    if (!HasExtension(relative, required_extension)) {
        const bool expects_png =
            CompareStringOrdinal(required_extension, -1, L".png", -1, TRUE) ==
            CSTR_EQUAL;
        SetError(
            error_message,
            expects_png
                ? "sprite image path must end in .png"
                : "sprite metadata path must end in .bundle");
        return false;
    }
    if (mod_root.empty()) {
        SetError(error_message, "owning mod root is unavailable");
        return false;
    }

    std::error_code filesystem_error;
    const auto canonical_root =
        std::filesystem::canonical(mod_root, filesystem_error);
    if (filesystem_error ||
        !std::filesystem::is_directory(canonical_root, filesystem_error)) {
        SetError(error_message, "owning mod root could not be resolved");
        return false;
    }
    const auto canonical_asset = std::filesystem::canonical(
        canonical_root / relative,
        filesystem_error);
    if (filesystem_error ||
        !std::filesystem::is_regular_file(canonical_asset, filesystem_error)) {
        SetError(error_message, "sprite asset is not a readable regular file");
        return false;
    }
    if (!IsWithinRoot(canonical_root, canonical_asset)) {
        SetError(error_message, "sprite asset resolves outside the owning mod root");
        return false;
    }
    const auto asset_size = std::filesystem::file_size(
        canonical_asset,
        filesystem_error);
    if (filesystem_error || asset_size == 0 || asset_size > maximum_bytes) {
        SetError(error_message, "sprite asset size is outside its allowed bound");
        return false;
    }
    *resolved_path = canonical_asset;
    return true;
}

std::uint32_t ReadBigEndianU32(
    const std::array<std::uint8_t, 24>& bytes,
    std::size_t offset) {
    return (static_cast<std::uint32_t>(bytes[offset]) << 24) |
        (static_cast<std::uint32_t>(bytes[offset + 1]) << 16) |
        (static_cast<std::uint32_t>(bytes[offset + 2]) << 8) |
        static_cast<std::uint32_t>(bytes[offset + 3]);
}

bool TryReadPngDimensions(
    const std::filesystem::path& path,
    std::uint32_t* width,
    std::uint32_t* height,
    std::string* error_message) {
    if (width == nullptr || height == nullptr || error_message == nullptr) {
        return false;
    }
    *width = 0;
    *height = 0;
    std::ifstream input(path, std::ios::binary);
    std::array<std::uint8_t, 24> header{};
    if (!input.read(
            reinterpret_cast<char*>(header.data()),
            static_cast<std::streamsize>(header.size())) ||
        !std::equal(
            kPngSignature.begin(),
            kPngSignature.end(),
            header.begin()) ||
        ReadBigEndianU32(header, 8) != 13 ||
        header[12] != 'I' || header[13] != 'H' ||
        header[14] != 'D' || header[15] != 'R') {
        SetError(error_message, "sprite image is not a PNG with a valid IHDR header");
        return false;
    }
    *width = ReadBigEndianU32(header, 16);
    *height = ReadBigEndianU32(header, 20);
    if (*width == 0 || *height == 0 ||
        *width > kLuaSpriteMaximumImageDimension ||
        *height > kLuaSpriteMaximumImageDimension) {
        SetError(error_message, "sprite image dimensions must be from 1 through 4096 pixels");
        return false;
    }
    return true;
}

bool ValidateFrames(
    const std::vector<LuaDrawSpriteInfo>& frames,
    std::uint32_t image_width,
    std::uint32_t image_height,
    std::string* error_message) {
    if (frames.empty() || frames.size() > kLuaSpriteMaximumFramesPerAtlas) {
        SetError(error_message, "sprite bundle must contain 1 through 4096 frames");
        return false;
    }
    for (std::size_t index = 0; index < frames.size(); ++index) {
        const auto& frame = frames[index];
        if (frame.rotated) {
            SetError(
                error_message,
                "sprite bundle frame " + std::to_string(index) +
                    " is rotated; registered atlases require unrotated frames");
            return false;
        }
        if (frame.atlas_x > image_width ||
            frame.atlas_y > image_height ||
            frame.packed_width > image_width - frame.atlas_x ||
            frame.packed_height > image_height - frame.atlas_y) {
            SetError(
                error_message,
                "sprite bundle frame " + std::to_string(index) +
                    " extends beyond the PNG dimensions");
            return false;
        }
        if (frame.content_width <= 0.0f ||
            frame.content_height <= 0.0f ||
            frame.logical_width > kLuaSpriteMaximumFrameGeometry ||
            frame.logical_height > kLuaSpriteMaximumFrameGeometry ||
            frame.content_width > kLuaSpriteMaximumFrameGeometry ||
            frame.content_height > kLuaSpriteMaximumFrameGeometry ||
            std::fabs(frame.center_offset_x) >
                kLuaSpriteMaximumFrameGeometry ||
            std::fabs(frame.center_offset_y) >
                kLuaSpriteMaximumFrameGeometry) {
            SetError(
                error_message,
                "sprite bundle frame " + std::to_string(index) +
                    " exceeds the 16384-pixel geometry bound");
            return false;
        }
    }
    return true;
}

std::string BuildAtlasId(
    std::string_view mod_id,
    std::string_view key) {
    std::string id(mod_id);
    id.push_back(':');
    id.append(key);
    return id;
}

std::size_t CountGlobalFrames(
    const LuaSpriteRegistryState& registry,
    std::string_view replacing_id) {
    std::size_t count = 0;
    for (const auto& [id, atlas] : registry.atlases) {
        if (id != replacing_id) {
            count += atlas.frames.size();
        }
    }
    return count;
}

std::size_t CountModAtlases(
    const LuaSpriteRegistryState& registry,
    std::string_view mod_id) {
    return static_cast<std::size_t>(std::count_if(
        registry.atlases.begin(),
        registry.atlases.end(),
        [mod_id](const auto& entry) {
            return entry.second.snapshot.mod_id == mod_id;
        }));
}

}  // namespace

bool RegisterLuaSpriteAtlas(
    std::string_view mod_id,
    const std::filesystem::path& mod_root,
    std::string_view key,
    std::string_view image_path,
    std::string_view bundle_path,
    LuaSpriteAtlasSnapshot* snapshot,
    std::string* error_message) {
    if (snapshot == nullptr || error_message == nullptr) {
        return false;
    }
    *snapshot = LuaSpriteAtlasSnapshot{};
    error_message->clear();
    if (!IsValidLuaContentIdentifier(mod_id) ||
        !IsValidLuaContentIdentifier(key)) {
        SetError(error_message, "sprite mod id and key must be lowercase content identifiers");
        return false;
    }

    std::filesystem::path resolved_image;
    if (!ResolveSpriteAssetPath(
            mod_root,
            image_path,
            L".png",
            kLuaSpriteMaximumImageBytes,
            &resolved_image,
            error_message)) {
        return false;
    }
    std::filesystem::path resolved_bundle;
    if (!ResolveSpriteAssetPath(
            mod_root,
            bundle_path,
            L".bundle",
            kLuaSpriteMaximumBundleBytes,
            &resolved_bundle,
            error_message)) {
        return false;
    }

    std::uint32_t image_width = 0;
    std::uint32_t image_height = 0;
    if (!TryReadPngDimensions(
            resolved_image,
            &image_width,
            &image_height,
            error_message)) {
        return false;
    }
    std::vector<LuaDrawSpriteInfo> frames;
    if (!detail::TryParseLuaDrawSpriteBundle(
            resolved_bundle,
            &frames,
            error_message) ||
        !ValidateFrames(
            frames,
            image_width,
            image_height,
            error_message)) {
        return false;
    }

    LuaSpriteAtlasRegistration candidate;
    candidate.snapshot.id = BuildAtlasId(mod_id, key);
    candidate.snapshot.mod_id.assign(mod_id);
    candidate.snapshot.key.assign(key);
    candidate.snapshot.image_path.assign(image_path);
    candidate.snapshot.bundle_path.assign(bundle_path);
    candidate.snapshot.frame_count = frames.size();
    candidate.snapshot.image_width = image_width;
    candidate.snapshot.image_height = image_height;
    candidate.canonical_image_path = std::move(resolved_image);
    candidate.frames = std::move(frames);

    auto& registry = SpriteRegistry();
    std::scoped_lock lock(registry.mutex);
    const auto existing = registry.atlases.find(candidate.snapshot.id);
    if (existing == registry.atlases.end() &&
        (registry.atlases.size() >= kLuaSpriteMaximumGlobalAtlases ||
         CountModAtlases(registry, mod_id) >=
             kLuaSpriteMaximumAtlasesPerMod)) {
        SetError(error_message, "sprite atlas registration limit reached");
        return false;
    }
    if (CountGlobalFrames(registry, candidate.snapshot.id) +
            candidate.frames.size() >
        kLuaSpriteMaximumGlobalFrames) {
        SetError(error_message, "global registered sprite-frame limit reached");
        return false;
    }
    candidate.snapshot.revision = registry.next_revision++;
    if (registry.next_revision == 0) {
        registry.next_revision = 1;
    }
    const auto id = candidate.snapshot.id;
    registry.atlases[id] = std::move(candidate);
    *snapshot = registry.atlases[id].snapshot;
    return true;
}

bool UnregisterLuaSpriteAtlas(
    std::string_view mod_id,
    std::string_view key) {
    if (!IsValidLuaContentIdentifier(mod_id) ||
        !IsValidLuaContentIdentifier(key)) {
        return false;
    }
    auto& registry = SpriteRegistry();
    std::scoped_lock lock(registry.mutex);
    return registry.atlases.erase(BuildAtlasId(mod_id, key)) != 0;
}

std::optional<LuaSpriteAtlasSnapshot> FindLuaSpriteAtlas(
    std::string_view mod_id,
    std::string_view key) {
    if (!IsValidLuaContentIdentifier(mod_id) ||
        !IsValidLuaContentIdentifier(key)) {
        return std::nullopt;
    }
    auto& registry = SpriteRegistry();
    std::scoped_lock lock(registry.mutex);
    const auto found = registry.atlases.find(BuildAtlasId(mod_id, key));
    return found == registry.atlases.end()
        ? std::nullopt
        : std::optional<LuaSpriteAtlasSnapshot>(found->second.snapshot);
}

std::vector<LuaSpriteAtlasSnapshot> ListLuaSpriteAtlases(
    std::string_view mod_id) {
    std::vector<LuaSpriteAtlasSnapshot> snapshots;
    auto& registry = SpriteRegistry();
    std::scoped_lock lock(registry.mutex);
    for (const auto& [id, atlas] : registry.atlases) {
        (void)id;
        if (atlas.snapshot.mod_id == mod_id) {
            snapshots.push_back(atlas.snapshot);
        }
    }
    return snapshots;
}

void ClearLuaSpriteAtlasesForMod(std::string_view mod_id) {
    auto& registry = SpriteRegistry();
    std::scoped_lock lock(registry.mutex);
    for (auto iterator = registry.atlases.begin();
         iterator != registry.atlases.end();) {
        if (iterator->second.snapshot.mod_id == mod_id) {
            iterator = registry.atlases.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

void ResetLuaSpriteRegistry() {
    auto& registry = SpriteRegistry();
    std::scoped_lock lock(registry.mutex);
    registry.atlases.clear();
    registry.next_revision = 1;
}

bool TryGetLuaRegisteredSpriteInfo(
    std::string_view atlas_id,
    std::uint32_t sprite_index,
    LuaDrawSpriteInfo* info,
    std::string* canonical_atlas,
    std::string* error_message) {
    if (info == nullptr || canonical_atlas == nullptr ||
        error_message == nullptr) {
        return false;
    }
    error_message->clear();
    if (atlas_id.empty() ||
        atlas_id.size() > kLuaSpriteMaximumAtlasIdBytes) {
        SetError(error_message, "registered sprite atlas id is outside its byte bound");
        return false;
    }
    auto& registry = SpriteRegistry();
    std::scoped_lock lock(registry.mutex);
    const auto found = registry.atlases.find(std::string(atlas_id));
    if (found == registry.atlases.end()) {
        SetError(error_message, "unknown stock or registered sprite atlas");
        return false;
    }
    if (sprite_index >= found->second.frames.size()) {
        SetError(
            error_message,
            "registered sprite index " + std::to_string(sprite_index) +
                " is outside atlas " + found->second.snapshot.id +
                " (frame count " +
                std::to_string(found->second.frames.size()) + ")");
        return false;
    }
    *info = found->second.frames[sprite_index];
    *canonical_atlas = found->second.snapshot.id;
    return true;
}

bool TryGetLuaRegisteredSpriteSource(
    std::string_view atlas_id,
    std::filesystem::path* image_path,
    std::uint64_t* revision) {
    if (image_path == nullptr || revision == nullptr ||
        atlas_id.empty() || atlas_id.size() > kLuaSpriteMaximumAtlasIdBytes) {
        return false;
    }
    image_path->clear();
    *revision = 0;
    auto& registry = SpriteRegistry();
    std::scoped_lock lock(registry.mutex);
    const auto found = registry.atlases.find(std::string(atlas_id));
    if (found == registry.atlases.end()) {
        return false;
    }
    *image_path = found->second.canonical_image_path;
    *revision = found->second.snapshot.revision;
    return true;
}

}  // namespace sdmod
