#include "lua_engine_internal.h"

#include "logger.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <limits>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>

#include <Windows.h>

namespace sdmod::detail {
namespace {

constexpr std::size_t kLuaAudioMaximumPlaybacksPerMod = 64;
constexpr std::size_t kLuaAudioMaximumGlobalPlaybacks = 256;
constexpr std::size_t kLuaAudioMaximumRelativePathBytes = 512;
constexpr std::uintmax_t kLuaAudioMaximumAssetBytes = 512ULL * 1024ULL * 1024ULL;
constexpr std::uint32_t kBassSampleLoop = 4;
constexpr std::uint32_t kBassUnicode = 0x80000000U;
constexpr std::uint32_t kBassAttributeVolume = 2;
constexpr std::uint32_t kBassActiveStopped = 0;
constexpr std::uint32_t kBassActivePlaying = 1;
constexpr std::uint32_t kBassActiveStalled = 2;
constexpr std::uint32_t kBassActivePaused = 3;

using BassSampleLoadFn = std::uint32_t(WINAPI*)(
    BOOL, const void*, std::uint64_t, std::uint32_t, std::uint32_t,
    std::uint32_t);
using BassSampleFreeFn = BOOL(WINAPI*)(std::uint32_t);
using BassSampleGetChannelFn = std::uint32_t(WINAPI*)(std::uint32_t, BOOL);
using BassStreamCreateFileFn = std::uint32_t(WINAPI*)(
    BOOL, const void*, std::uint64_t, std::uint64_t, std::uint32_t);
using BassStreamFreeFn = BOOL(WINAPI*)(std::uint32_t);
using BassChannelPlayFn = BOOL(WINAPI*)(std::uint32_t, BOOL);
using BassChannelStopFn = BOOL(WINAPI*)(std::uint32_t);
using BassChannelSetAttributeFn = BOOL(WINAPI*)(
    std::uint32_t, std::uint32_t, float);
using BassChannelIsActiveFn = std::uint32_t(WINAPI*)(std::uint32_t);
using BassErrorGetCodeFn = int(WINAPI*)();
using BassGetVersionFn = std::uint32_t(WINAPI*)();

struct LuaAudioBassApi {
    HMODULE module = nullptr;
    BassSampleLoadFn sample_load = nullptr;
    BassSampleFreeFn sample_free = nullptr;
    BassSampleGetChannelFn sample_get_channel = nullptr;
    BassStreamCreateFileFn stream_create_file = nullptr;
    BassStreamFreeFn stream_free = nullptr;
    BassChannelPlayFn channel_play = nullptr;
    BassChannelStopFn channel_stop = nullptr;
    BassChannelSetAttributeFn channel_set_attribute = nullptr;
    BassChannelIsActiveFn channel_is_active = nullptr;
    BassErrorGetCodeFn error_get_code = nullptr;
    BassGetVersionFn get_version = nullptr;
    std::uint32_t version = 0;
    bool available = false;
};

LuaAudioBassApi g_bass;

template <typename T>
bool ResolveBassExport(T* target, const char* name) {
    if (target == nullptr || g_bass.module == nullptr) {
        return false;
    }
    *target = reinterpret_cast<T>(GetProcAddress(g_bass.module, name));
    if (*target != nullptr) {
        return true;
    }
    Log(std::string("Lua audio unavailable: bass.dll lacks ") + name + ".");
    return false;
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

bool HasSupportedAudioExtension(const std::filesystem::path& path) {
    const auto extension = path.extension().native();
    constexpr std::array<const wchar_t*, 4> kSupportedExtensions = {
        L".wav", L".ogg", L".mp3", L".caf",
    };
    return std::any_of(
        kSupportedExtensions.begin(),
        kSupportedExtensions.end(),
        [&extension](const wchar_t* expected) {
            return CompareStringOrdinal(
                       extension.c_str(),
                       static_cast<int>(extension.size()),
                       expected,
                       -1,
                       TRUE) == CSTR_EQUAL;
        });
}

bool ResolveAudioAssetPath(
    const LoadedLuaMod& mod,
    std::string_view relative_path,
    std::filesystem::path* resolved_path,
    std::string* error_message) {
    if (resolved_path == nullptr || error_message == nullptr) {
        return false;
    }
    resolved_path->clear();
    if (relative_path.empty() ||
        relative_path.size() > kLuaAudioMaximumRelativePathBytes ||
        relative_path.find('\0') != std::string_view::npos) {
        *error_message = "Audio path must contain 1 through 512 bytes.";
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
        *error_message = "Audio path must be valid UTF-8.";
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
        *error_message = "Audio path must be valid UTF-8.";
        return false;
    }

    const std::filesystem::path relative(decoded_path);
    if (relative.empty() || relative.is_absolute() || relative.has_root_path()) {
        *error_message = "Audio path must be relative to the owning mod root.";
        return false;
    }
    for (const auto& component : relative) {
        if (component == "." || component == "..") {
            *error_message = "Audio path may not contain '.' or '..' components.";
            return false;
        }
    }
    if (!HasSupportedAudioExtension(relative)) {
        *error_message = "Audio path must end in .wav, .ogg, .mp3, or .caf.";
        return false;
    }
    if (mod.descriptor.root_path.empty()) {
        *error_message = "Owning mod root is unavailable.";
        return false;
    }

    std::error_code filesystem_error;
    const auto canonical_root =
        std::filesystem::canonical(mod.descriptor.root_path, filesystem_error);
    if (filesystem_error ||
        !std::filesystem::is_directory(canonical_root, filesystem_error)) {
        *error_message = "Owning mod root could not be resolved.";
        return false;
    }
    const auto canonical_asset = std::filesystem::canonical(
        canonical_root / relative, filesystem_error);
    if (filesystem_error ||
        !std::filesystem::is_regular_file(canonical_asset, filesystem_error)) {
        *error_message = "Audio asset is not a readable regular file.";
        return false;
    }
    if (!IsWithinRoot(canonical_root, canonical_asset)) {
        *error_message = "Audio asset resolves outside the owning mod root.";
        return false;
    }

    const auto asset_size = std::filesystem::file_size(
        canonical_asset, filesystem_error);
    if (filesystem_error || asset_size == 0 ||
        asset_size > kLuaAudioMaximumAssetBytes) {
        *error_message =
            "Audio asset must contain 1 through 536870912 bytes.";
        return false;
    }
    *resolved_path = canonical_asset;
    return true;
}

std::size_t CountGlobalPlaybacks() {
    std::size_t count = 0;
    for (const auto& mod : LoadedLuaModsStorage()) {
        if (mod != nullptr) {
            count += mod->audio_playbacks.size();
        }
    }
    return count;
}

int GetBassErrorCode() {
    return g_bass.error_get_code == nullptr ? -1 : g_bass.error_get_code();
}

std::string BassFailure(std::string_view operation, int error_code) {
    return std::string(operation) + " failed with BASS error " +
        std::to_string(error_code) + ".";
}

void ReleasePlayback(LuaAudioPlayback* playback) {
    if (playback == nullptr) {
        return;
    }
    if (playback->channel_handle != 0 && g_bass.channel_stop != nullptr) {
        g_bass.channel_stop(playback->channel_handle);
    }
    if (playback->kind == LuaAudioPlaybackKind::Sample) {
        if (playback->sample_handle != 0 && g_bass.sample_free != nullptr) {
            g_bass.sample_free(playback->sample_handle);
        }
    } else if (playback->channel_handle != 0 && g_bass.stream_free != nullptr) {
        g_bass.stream_free(playback->channel_handle);
    }
    playback->sample_handle = 0;
    playback->channel_handle = 0;
}

std::string DescribeActivity(std::uint32_t activity) {
    switch (activity) {
        case kBassActiveStopped:
            return "stopped";
        case kBassActivePlaying:
            return "playing";
        case kBassActiveStalled:
            return "stalled";
        case kBassActivePaused:
            return "paused";
        default:
            return "unknown";
    }
}

LuaAudioPlaybackSnapshot BuildPlaybackSnapshot(
    const LuaAudioPlayback& playback) {
    LuaAudioPlaybackSnapshot snapshot;
    snapshot.id = playback.id;
    snapshot.kind = playback.kind;
    snapshot.relative_path = playback.relative_path;
    snapshot.volume = playback.volume;
    snapshot.loop = playback.loop;
    snapshot.created_ms = playback.created_ms;
    const auto activity =
        g_bass.available && playback.channel_handle != 0
            ? g_bass.channel_is_active(playback.channel_handle)
            : kBassActiveStopped;
    snapshot.activity = DescribeActivity(activity);
    return snapshot;
}

}  // namespace

void InitializeLuaAudioRuntime() {
    g_bass = LuaAudioBassApi{};
    g_bass.module = GetModuleHandleW(L"bass.dll");
    if (g_bass.module == nullptr) {
        Log("Lua audio unavailable: the game-owned bass.dll is not loaded.");
        return;
    }

    const bool resolved =
        ResolveBassExport(&g_bass.sample_load, "BASS_SampleLoad") &&
        ResolveBassExport(&g_bass.sample_free, "BASS_SampleFree") &&
        ResolveBassExport(&g_bass.sample_get_channel, "BASS_SampleGetChannel") &&
        ResolveBassExport(&g_bass.stream_create_file, "BASS_StreamCreateFile") &&
        ResolveBassExport(&g_bass.stream_free, "BASS_StreamFree") &&
        ResolveBassExport(&g_bass.channel_play, "BASS_ChannelPlay") &&
        ResolveBassExport(&g_bass.channel_stop, "BASS_ChannelStop") &&
        ResolveBassExport(
            &g_bass.channel_set_attribute, "BASS_ChannelSetAttribute") &&
        ResolveBassExport(&g_bass.channel_is_active, "BASS_ChannelIsActive") &&
        ResolveBassExport(&g_bass.error_get_code, "BASS_ErrorGetCode") &&
        ResolveBassExport(&g_bass.get_version, "BASS_GetVersion");
    if (!resolved) {
        g_bass = LuaAudioBassApi{};
        return;
    }

    g_bass.version = g_bass.get_version();
    g_bass.available = true;
    Log("Lua audio bound to game-owned bass.dll version " +
        std::to_string(g_bass.version) + ".");
}

void ShutdownLuaAudioRuntime() {
    g_bass = LuaAudioBassApi{};
}

bool IsLuaAudioRuntimeAvailable() {
    return g_bass.available;
}

void AppendLuaAudioCapabilities(std::vector<std::string>* capabilities) {
    if (!g_bass.available || capabilities == nullptr) {
        return;
    }
    capabilities->emplace_back("audio.local.playback");
    capabilities->emplace_back("audio.sample");
    capabilities->emplace_back("audio.stream");
}

bool PlayLuaAudio(
    LoadedLuaMod* mod,
    LuaAudioPlaybackKind kind,
    std::string_view relative_path,
    float volume,
    bool loop,
    std::uint64_t* playback_id,
    std::string* error_message) {
    if (playback_id == nullptr || error_message == nullptr) {
        return false;
    }
    *playback_id = 0;
    error_message->clear();
    if (mod == nullptr) {
        *error_message = "Lua audio playback has no owning mod.";
        return false;
    }
    if (!g_bass.available) {
        *error_message = "Lua audio is unavailable because bass.dll was not bound.";
        return false;
    }
    if (mod->audio_playbacks.size() >= kLuaAudioMaximumPlaybacksPerMod) {
        *error_message = "Lua audio playback limit exceeded for this mod.";
        return false;
    }
    if (CountGlobalPlaybacks() >= kLuaAudioMaximumGlobalPlaybacks) {
        *error_message = "Lua audio global playback limit exceeded.";
        return false;
    }
    if (mod->next_audio_playback_id == 0 ||
        mod->next_audio_playback_id >
            static_cast<std::uint64_t>(
                (std::numeric_limits<std::int64_t>::max)())) {
        *error_message = "Lua audio playback handle space is exhausted.";
        return false;
    }

    std::filesystem::path asset_path;
    if (!ResolveAudioAssetPath(
            *mod, relative_path, &asset_path, error_message)) {
        return false;
    }

    LuaAudioPlayback playback;
    playback.id = mod->next_audio_playback_id++;
    playback.kind = kind;
    playback.relative_path.assign(relative_path.begin(), relative_path.end());
    playback.volume = volume;
    playback.loop = loop;
    playback.created_ms = static_cast<std::uint64_t>(GetTickCount64());
    const std::uint32_t flags = kBassUnicode | (loop ? kBassSampleLoop : 0U);

    if (kind == LuaAudioPlaybackKind::Sample) {
        playback.sample_handle = g_bass.sample_load(
            FALSE, asset_path.c_str(), 0, 0, 1, flags);
        if (playback.sample_handle == 0) {
            *error_message = BassFailure("BASS_SampleLoad", GetBassErrorCode());
            return false;
        }
        playback.channel_handle =
            g_bass.sample_get_channel(playback.sample_handle, FALSE);
        if (playback.channel_handle == 0) {
            const int bass_error = GetBassErrorCode();
            ReleasePlayback(&playback);
            *error_message = BassFailure("BASS_SampleGetChannel", bass_error);
            return false;
        }
    } else {
        playback.channel_handle = g_bass.stream_create_file(
            FALSE, asset_path.c_str(), 0, 0, flags);
        if (playback.channel_handle == 0) {
            *error_message =
                BassFailure("BASS_StreamCreateFile", GetBassErrorCode());
            return false;
        }
    }

    if (!g_bass.channel_set_attribute(
            playback.channel_handle, kBassAttributeVolume, volume)) {
        const int bass_error = GetBassErrorCode();
        ReleasePlayback(&playback);
        *error_message = BassFailure("BASS_ChannelSetAttribute", bass_error);
        return false;
    }
    if (!g_bass.channel_play(playback.channel_handle, FALSE)) {
        const int bass_error = GetBassErrorCode();
        ReleasePlayback(&playback);
        *error_message = BassFailure("BASS_ChannelPlay", bass_error);
        return false;
    }

    *playback_id = playback.id;
    mod->audio_playbacks.push_back(std::move(playback));
    return true;
}

bool StopLuaAudioPlayback(LoadedLuaMod* mod, std::uint64_t playback_id) {
    if (mod == nullptr) {
        return false;
    }
    const auto found = std::find_if(
        mod->audio_playbacks.begin(),
        mod->audio_playbacks.end(),
        [playback_id](const LuaAudioPlayback& playback) {
            return playback.id == playback_id;
        });
    if (found == mod->audio_playbacks.end()) {
        return false;
    }
    ReleasePlayback(&*found);
    mod->audio_playbacks.erase(found);
    return true;
}

bool SetLuaAudioPlaybackVolume(
    LoadedLuaMod* mod,
    std::uint64_t playback_id,
    float volume,
    bool* found,
    std::string* error_message) {
    if (found == nullptr || error_message == nullptr) {
        return false;
    }
    *found = false;
    error_message->clear();
    if (mod == nullptr || !g_bass.available) {
        *error_message = "Lua audio is unavailable.";
        return false;
    }
    const auto playback = std::find_if(
        mod->audio_playbacks.begin(),
        mod->audio_playbacks.end(),
        [playback_id](const LuaAudioPlayback& entry) {
            return entry.id == playback_id;
        });
    if (playback == mod->audio_playbacks.end()) {
        return true;
    }
    *found = true;
    if (!g_bass.channel_set_attribute(
            playback->channel_handle, kBassAttributeVolume, volume)) {
        *error_message =
            BassFailure("BASS_ChannelSetAttribute", GetBassErrorCode());
        return false;
    }
    playback->volume = volume;
    return true;
}

bool TryGetLuaAudioPlaybackSnapshot(
    const LoadedLuaMod* mod,
    std::uint64_t playback_id,
    LuaAudioPlaybackSnapshot* snapshot) {
    if (mod == nullptr || snapshot == nullptr) {
        return false;
    }
    const auto found = std::find_if(
        mod->audio_playbacks.begin(),
        mod->audio_playbacks.end(),
        [playback_id](const LuaAudioPlayback& playback) {
            return playback.id == playback_id;
        });
    if (found == mod->audio_playbacks.end()) {
        return false;
    }
    *snapshot = BuildPlaybackSnapshot(*found);
    return true;
}

std::vector<LuaAudioPlaybackSnapshot> SnapshotLuaAudioPlaybacks(
    const LoadedLuaMod* mod) {
    std::vector<LuaAudioPlaybackSnapshot> snapshots;
    if (mod == nullptr) {
        return snapshots;
    }
    snapshots.reserve(mod->audio_playbacks.size());
    for (const auto& playback : mod->audio_playbacks) {
        snapshots.push_back(BuildPlaybackSnapshot(playback));
    }
    return snapshots;
}

bool HasLuaAudioPlaybacks(const LoadedLuaMod* mod) {
    return mod != nullptr && !mod->audio_playbacks.empty();
}

void TickLuaAudioRuntime() {
    if (!g_bass.available) {
        return;
    }
    for (const auto& mod : LoadedLuaModsStorage()) {
        if (mod == nullptr) {
            continue;
        }
        auto& playbacks = mod->audio_playbacks;
        for (auto playback = playbacks.begin(); playback != playbacks.end();) {
            if (g_bass.channel_is_active(playback->channel_handle) !=
                kBassActiveStopped) {
                ++playback;
                continue;
            }
            ReleasePlayback(&*playback);
            playback = playbacks.erase(playback);
        }
    }
}

std::size_t ClearLuaAudioRuntimeForMod(LoadedLuaMod* mod) {
    if (mod == nullptr) {
        return 0;
    }
    const auto count = mod->audio_playbacks.size();
    for (auto& playback : mod->audio_playbacks) {
        ReleasePlayback(&playback);
    }
    mod->audio_playbacks.clear();
    return count;
}

void ResetLuaAudioRuntimeForMod(LoadedLuaMod* mod) {
    ClearLuaAudioRuntimeForMod(mod);
    if (mod != nullptr) {
        mod->next_audio_playback_id = 1;
    }
}

}  // namespace sdmod::detail
