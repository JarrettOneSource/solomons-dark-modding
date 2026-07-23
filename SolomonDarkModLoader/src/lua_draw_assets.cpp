#include "lua_draw_runtime.h"

#include "lua_draw_internal.h"
#include "lua_sprite_runtime.h"

#include <array>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

constexpr std::size_t kCommonSpriteHeaderBytes = 45;
constexpr std::size_t kSpritePointBytes = 8;
constexpr std::size_t kMaximumBundleBytes = 16 * 1024 * 1024;
constexpr std::size_t kMaximumBundleRecords = 20 * 1024;
constexpr std::uint32_t kMaximumSpritePoints = 128 * 1024;
constexpr std::size_t kMaximumFontTableEntries = 16 * 1024;

constexpr std::array<std::string_view, 28> kStockAtlasNames = {
    "BadGuys",
    "Bonedit",
    "Clothes",
    "College",
    "ControlPanel",
    "Controls",
    "Create",
    "DeadHawg",
    "Demon",
    "Faculty",
    "Fonts",
    "GameOver",
    "Golem",
    "Heartmonger",
    "Inventory",
    "LevelPicker",
    "Library",
    "Loader",
    "Memoratorium",
    "NPCs",
    "Office",
    "Skills",
    "Solomon",
    "SolomonRiff",
    "Storage",
    "Title",
    "UI",
    "Unholy",
};

struct LuaDrawAtlasMetadata {
    bool load_attempted = false;
    std::vector<LuaDrawSpriteInfo> sprites;
    std::string error_message;
};

std::filesystem::path g_lua_draw_images_directory;
std::unordered_map<std::string, LuaDrawAtlasMetadata> g_lua_draw_atlases;
std::mutex g_lua_draw_assets_mutex;

bool AsciiEqualsIgnoreCase(std::string_view left, std::string_view right) {
    if (left.size() != right.size()) {
        return false;
    }
    for (std::size_t index = 0; index < left.size(); ++index) {
        auto left_ch = static_cast<unsigned char>(left[index]);
        auto right_ch = static_cast<unsigned char>(right[index]);
        if (left_ch >= 'A' && left_ch <= 'Z') {
            left_ch = static_cast<unsigned char>(left_ch - 'A' + 'a');
        }
        if (right_ch >= 'A' && right_ch <= 'Z') {
            right_ch = static_cast<unsigned char>(right_ch - 'A' + 'a');
        }
        if (left_ch != right_ch) {
            return false;
        }
    }
    return true;
}

bool TryCanonicalizeAtlasName(
    std::string_view atlas,
    std::string* canonical_atlas) {
    if (atlas.empty() ||
        atlas.size() > kLuaDrawMaxAtlasNameBytes ||
        canonical_atlas == nullptr) {
        return false;
    }
    for (const auto candidate : kStockAtlasNames) {
        if (AsciiEqualsIgnoreCase(atlas, candidate)) {
            canonical_atlas->assign(candidate);
            return true;
        }
    }
    return false;
}

template <typename Value>
bool TryReadBundleValue(
    const std::vector<std::uint8_t>& bytes,
    std::size_t offset,
    Value* value) {
    if (value == nullptr ||
        offset > bytes.size() ||
        sizeof(Value) > bytes.size() - offset) {
        return false;
    }
    std::memcpy(value, bytes.data() + offset, sizeof(Value));
    return true;
}

bool TryParseCommonSprite(
    const std::vector<std::uint8_t>& bytes,
    std::size_t offset,
    LuaDrawSpriteInfo* info,
    std::size_t* next_offset,
    std::string* error_message) {
    if (info == nullptr || next_offset == nullptr || error_message == nullptr) {
        return false;
    }
    if (offset > bytes.size() ||
        kCommonSpriteHeaderBytes > bytes.size() - offset) {
        *error_message = "common sprite header is truncated at byte " +
            std::to_string(offset);
        return false;
    }

    LuaDrawSpriteInfo parsed;
    std::uint8_t rotated = 0;
    std::uint32_t point_count = 0;
    if (!TryReadBundleValue(bytes, offset + 0x00, &parsed.atlas_x) ||
        !TryReadBundleValue(bytes, offset + 0x04, &parsed.atlas_y) ||
        !TryReadBundleValue(bytes, offset + 0x08, &parsed.packed_width) ||
        !TryReadBundleValue(bytes, offset + 0x0C, &parsed.packed_height) ||
        !TryReadBundleValue(bytes, offset + 0x10, &parsed.logical_width) ||
        !TryReadBundleValue(bytes, offset + 0x14, &parsed.logical_height) ||
        !TryReadBundleValue(bytes, offset + 0x18, &parsed.content_width) ||
        !TryReadBundleValue(bytes, offset + 0x1C, &parsed.content_height) ||
        !TryReadBundleValue(bytes, offset + 0x20, &parsed.center_offset_x) ||
        !TryReadBundleValue(bytes, offset + 0x24, &parsed.center_offset_y) ||
        !TryReadBundleValue(bytes, offset + 0x28, &rotated) ||
        !TryReadBundleValue(bytes, offset + 0x29, &point_count)) {
        *error_message = "common sprite header could not be decoded at byte " +
            std::to_string(offset);
        return false;
    }
    if (rotated > 1) {
        *error_message = "common sprite rotation byte is invalid at byte " +
            std::to_string(offset);
        return false;
    }
    if (point_count > kMaximumSpritePoints) {
        *error_message = "common sprite point count exceeds its bound at byte " +
            std::to_string(offset);
        return false;
    }
    const auto point_bytes =
        static_cast<std::size_t>(point_count) * kSpritePointBytes;
    if (point_bytes > bytes.size() - offset - kCommonSpriteHeaderBytes) {
        *error_message = "common sprite point tail is truncated at byte " +
            std::to_string(offset);
        return false;
    }

    const std::array<float, 8> numeric_fields = {
        parsed.atlas_x,
        parsed.atlas_y,
        parsed.packed_width,
        parsed.packed_height,
        parsed.content_width,
        parsed.content_height,
        parsed.center_offset_x,
        parsed.center_offset_y,
    };
    for (const auto value : numeric_fields) {
        if (!std::isfinite(value)) {
            *error_message = "common sprite contains a non-finite value at byte " +
                std::to_string(offset);
            return false;
        }
    }
    for (std::uint32_t point_index = 0;
         point_index < point_count;
         ++point_index) {
        float point_x = 0.0f;
        float point_y = 0.0f;
        const auto point_offset =
            offset + kCommonSpriteHeaderBytes +
            static_cast<std::size_t>(point_index) * kSpritePointBytes;
        if (!TryReadBundleValue(bytes, point_offset, &point_x) ||
            !TryReadBundleValue(bytes, point_offset + sizeof(float), &point_y) ||
            !std::isfinite(point_x) ||
            !std::isfinite(point_y)) {
            *error_message = "common sprite contains a non-finite point at byte " +
                std::to_string(point_offset);
            return false;
        }
    }
    if (parsed.atlas_x < 0.0f ||
        parsed.atlas_y < 0.0f ||
        parsed.packed_width <= 0.0f ||
        parsed.packed_height <= 0.0f ||
        parsed.logical_width <= 0 ||
        parsed.logical_height == 0) {
        *error_message = "common sprite contains invalid geometry at byte " +
            std::to_string(offset);
        return false;
    }

    parsed.rotated = rotated != 0;
    *info = parsed;
    *next_offset = offset + kCommonSpriteHeaderBytes + point_bytes;
    return true;
}

bool TryParseAuxiliaryFontGroups(
    const std::vector<std::uint8_t>& bytes,
    std::size_t offset,
    std::vector<LuaDrawSpriteInfo>* sprites,
    std::string* error_message) {
    while (offset < bytes.size()) {
        std::array<float, 3> group_metrics{};
        if (!TryReadBundleValue(bytes, offset, &group_metrics)) {
            *error_message = "font group header is truncated at byte " +
                std::to_string(offset);
            return false;
        }
        for (const auto value : group_metrics) {
            if (!std::isfinite(value)) {
                *error_message = "font group contains a non-finite metric at byte " +
                    std::to_string(offset);
                return false;
            }
        }
        offset += sizeof(group_metrics);

        std::size_t kerning_count = 0;
        for (;;) {
            std::uint16_t left_id = 0;
            std::uint16_t right_id = 0;
            if (!TryReadBundleValue(bytes, offset, &left_id) ||
                !TryReadBundleValue(bytes, offset + 2, &right_id)) {
                *error_message = "font kerning table is truncated at byte " +
                    std::to_string(offset);
                return false;
            }
            if (left_id == 0 && right_id == 0) {
                offset += 4;
                break;
            }
            float adjustment = 0.0f;
            if (!TryReadBundleValue(bytes, offset + 4, &adjustment) ||
                !std::isfinite(adjustment)) {
                *error_message = "font kerning entry is invalid at byte " +
                    std::to_string(offset);
                return false;
            }
            offset += 8;
            if (++kerning_count > kMaximumFontTableEntries) {
                *error_message = "font kerning table exceeds its entry bound.";
                return false;
            }
        }

        std::size_t glyph_count = 0;
        for (;;) {
            std::uint16_t glyph_id = 0;
            if (!TryReadBundleValue(bytes, offset, &glyph_id)) {
                *error_message = "font glyph table is truncated at byte " +
                    std::to_string(offset);
                return false;
            }
            if (glyph_id == 0) {
                offset += 2;
                break;
            }

            std::array<float, 3> glyph_metrics{};
            if (!TryReadBundleValue(bytes, offset + 2, &glyph_metrics)) {
                *error_message = "font glyph metrics are truncated at byte " +
                    std::to_string(offset);
                return false;
            }
            for (const auto value : glyph_metrics) {
                if (!std::isfinite(value)) {
                    *error_message = "font glyph contains a non-finite metric at byte " +
                        std::to_string(offset);
                    return false;
                }
            }

            LuaDrawSpriteInfo sprite;
            std::size_t next_offset = 0;
            if (!TryParseCommonSprite(
                    bytes,
                    offset + 14,
                    &sprite,
                    &next_offset,
                    error_message)) {
                return false;
            }
            sprites->push_back(sprite);
            if (sprites->size() > kMaximumBundleRecords) {
                *error_message = "bundle exceeds its sprite-record bound.";
                return false;
            }
            offset = next_offset;
            if (++glyph_count > kMaximumFontTableEntries) {
                *error_message = "font glyph table exceeds its entry bound.";
                return false;
            }
        }
    }
    return true;
}

bool TryReadBundleFile(
    const std::filesystem::path& path,
    std::vector<std::uint8_t>* bytes,
    std::string* error_message) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream.is_open()) {
        *error_message = "stock sprite bundle was not found: " + path.string();
        return false;
    }
    const auto end = stream.tellg();
    if (end <= 0 ||
        static_cast<std::uint64_t>(end) > kMaximumBundleBytes) {
        *error_message = "stock sprite bundle has an invalid or oversized length: " +
            path.string();
        return false;
    }
    bytes->resize(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    if (!stream.read(
            reinterpret_cast<char*>(bytes->data()),
            static_cast<std::streamsize>(bytes->size()))) {
        *error_message = "stock sprite bundle could not be read: " + path.string();
        return false;
    }
    return true;
}

bool TryParseBundle(
    const std::filesystem::path& path,
    std::vector<LuaDrawSpriteInfo>* sprites,
    std::string* error_message) {
    std::vector<std::uint8_t> bytes;
    if (!TryReadBundleFile(path, &bytes, error_message)) {
        return false;
    }

    sprites->clear();
    std::size_t offset = 0;
    std::string common_error;
    while (offset < bytes.size()) {
        LuaDrawSpriteInfo sprite;
        std::size_t next_offset = 0;
        if (!TryParseCommonSprite(
                bytes,
                offset,
                &sprite,
                &next_offset,
                &common_error)) {
            break;
        }
        sprites->push_back(sprite);
        if (sprites->size() > kMaximumBundleRecords) {
            *error_message = "bundle exceeds its sprite-record bound: " +
                path.string();
            return false;
        }
        offset = next_offset;
    }
    if (offset < bytes.size() &&
        !TryParseAuxiliaryFontGroups(bytes, offset, sprites, error_message)) {
        *error_message =
            "stock sprite bundle common stream stopped at byte " +
            std::to_string(offset) + " (" + common_error +"); " +
            *error_message + ": " + path.string();
        return false;
    }
    if (sprites->empty()) {
        *error_message = "stock sprite bundle contains no records: " + path.string();
        return false;
    }
    return true;
}

}  // namespace

namespace detail {

void ConfigureLuaDrawAssets(const std::filesystem::path& images_directory) {
    std::scoped_lock lock(g_lua_draw_assets_mutex);
    g_lua_draw_images_directory = images_directory;
    g_lua_draw_atlases.clear();
}

void ResetLuaDrawAssets() {
    std::scoped_lock lock(g_lua_draw_assets_mutex);
    g_lua_draw_images_directory.clear();
    g_lua_draw_atlases.clear();
}

bool TryParseLuaDrawSpriteBundle(
    const std::filesystem::path& path,
    std::vector<LuaDrawSpriteInfo>* sprites,
    std::string* error_message) {
    return TryParseBundle(path, sprites, error_message);
}

}  // namespace detail

bool TryGetLuaDrawSpriteInfo(
    std::string_view atlas,
    std::uint32_t sprite_index,
    LuaDrawSpriteInfo* info,
    std::string* canonical_atlas,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (info == nullptr || canonical_atlas == nullptr || error_message == nullptr) {
        return false;
    }
    if (!TryCanonicalizeAtlasName(atlas, canonical_atlas)) {
        return TryGetLuaRegisteredSpriteInfo(
            atlas,
            sprite_index,
            info,
            canonical_atlas,
            error_message);
    }

    std::scoped_lock lock(g_lua_draw_assets_mutex);
    if (g_lua_draw_images_directory.empty()) {
        *error_message = "Lua draw asset directory is not configured.";
        return false;
    }
    auto& metadata = g_lua_draw_atlases[*canonical_atlas];
    if (!metadata.load_attempted) {
        metadata.load_attempted = true;
        const auto bundle_path =
            g_lua_draw_images_directory / (*canonical_atlas + ".bundle");
        if (!TryParseBundle(
                bundle_path,
                &metadata.sprites,
                &metadata.error_message)) {
            metadata.sprites.clear();
        }
    }
    if (!metadata.error_message.empty()) {
        *error_message = metadata.error_message;
        return false;
    }
    if (sprite_index >= metadata.sprites.size()) {
        *error_message =
            "stock sprite index " + std::to_string(sprite_index) +
            " is outside atlas " + *canonical_atlas +
            " (record count " + std::to_string(metadata.sprites.size()) + ").";
        return false;
    }

    *info = metadata.sprites[sprite_index];
    return true;
}

bool TryGetLuaDrawAtlasSource(
    std::string_view canonical_atlas,
    std::filesystem::path* image_path,
    std::uint64_t* revision) {
    if (image_path == nullptr || revision == nullptr) {
        return false;
    }
    image_path->clear();
    *revision = 0;
    std::string verified_atlas;
    if (!TryCanonicalizeAtlasName(canonical_atlas, &verified_atlas)) {
        return TryGetLuaRegisteredSpriteSource(
            canonical_atlas,
            image_path,
            revision);
    }
    std::scoped_lock lock(g_lua_draw_assets_mutex);
    if (g_lua_draw_images_directory.empty()) {
        return false;
    }
    *image_path = g_lua_draw_images_directory / (verified_atlas + ".png");
    *revision = 1;
    return true;
}

}  // namespace sdmod
