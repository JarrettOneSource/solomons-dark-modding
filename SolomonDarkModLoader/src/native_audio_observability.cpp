#include "native_audio_observability.h"

#include "binary_layout.h"
#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "x86_hook.h"

#include <Windows.h>
#include <intrin.h>

#include <algorithm>
#include <array>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>

namespace sdmod {
namespace {

constexpr std::size_t kSoundLoopChannelRecordOffset = 0x44;
constexpr std::size_t kSoundLoopReferenceCountOffset = 0x4C;
constexpr std::size_t kSoundChannelHandleOffset = 0x00;
constexpr std::size_t kMinimumLifecycleHookPatchSize = 5;
constexpr std::size_t kWorldPointGainVfuncOffset = 0x100;
constexpr std::uint32_t kNativeFootstepCadenceFrames = 25;
constexpr std::size_t kMaximumObservedFootstepActors = 16;

struct LoopCatalogEntry {
    std::int32_t registry_index;
    std::size_t object_offset;
    const char* asset;
};

constexpr std::array<LoopCatalogEntry, 22> kLoopCatalog = {{
    {151, 0x146C, "sounds\\beam__loop"},
    {152, 0x14CC, "sounds\\comet__loop"},
    {153, 0x152C, "sounds\\deepthunder__loop"},
    {154, 0x158C, "sounds\\earthquake__loop"},
    {155, 0x15EC, "sounds\\eerie__loop"},
    {156, 0x164C, "sounds\\electric__loop"},
    {157, 0x16AC, "sounds\\fire__loop"},
    {158, 0x170C, "sounds\\flyblown__loop"},
    {159, 0x176C, "sounds\\gatherrocksloop__loop"},
    {160, 0x17CC, "sounds\\icebeam__loop"},
    {161, 0x182C, "sounds\\iceloop__loop"},
    {162, 0x188C, "sounds\\lightningloop__loop"},
    {163, 0x18EC, "sounds\\lowfire__loop"},
    {164, 0x194C, "sounds\\maggots__loop"},
    {165, 0x19AC, "sounds\\meteor__loop"},
    {166, 0x1A0C, "sounds\\PlaneCross__Loop"},
    {167, 0x1A6C, "sounds\\rainfall__loop"},
    {168, 0x1ACC, "sounds\\rollingstoneloop__loop"},
    {169, 0x1B2C, "sounds\\shockblast__loop"},
    {170, 0x1B8C, "sounds\\Soul__Loop"},
    {171, 0x1BEC, "sounds\\steadywind__loop"},
    {172, 0x1C4C, "sounds\\steam__loop"},
}};

struct OneShotCatalogEntry {
    std::int32_t registry_index;
    std::size_t object_offset;
    const char* asset;
};

constexpr std::array<OneShotCatalogEntry, 2> kFootstepCatalog = {{
    {214, 0x23B8, "sounds\\Step\\step1"},
    {215, 0x23E4, "sounds\\Step\\step2"},
}};

struct NativeAudioChannelRecord {
    NativeAudioChannelSnapshot snapshot;
};

std::mutex g_native_audio_mutex;
std::unordered_map<uintptr_t, NativeAudioChannelRecord>
    g_native_audio_channels;
std::uint64_t g_next_event_sequence = 1;
uintptr_t g_compiled_registry_global = 0;
uintptr_t g_sound_play_address = 0;
uintptr_t g_footstep_frame_counter = 0;
uintptr_t g_footstep_gain_scale = 0;
X86Hook g_sound_loop_start_hook;
X86Hook g_sound_loop_stop_hook;
X86Hook g_sound_play_hook;
thread_local NativeAudioAttributionContext g_current_attribution;
std::unordered_map<uintptr_t, std::uint32_t>
    g_last_footstep_frame_by_actor;

using SoundLoopLifecycleFn = void(__thiscall*)(void* self);
using SoundPlayFn = void(__thiscall*)(void* self, float gain);
using NativeRngIntegerFn =
    std::int32_t(__thiscall*)(void* self, std::int32_t range, char sign_mode);
using WorldPointGainFn =
    float(__thiscall*)(void* self, float x, float y);

uintptr_t ToPreferredImageAddress(uintptr_t runtime_address) {
    const auto module_base = ProcessMemory::Instance().ModuleBase();
    const auto image_base = GetConfiguredImageBase();
    if (runtime_address == 0 ||
        module_base == 0 ||
        image_base == 0 ||
        runtime_address < module_base) {
        return runtime_address;
    }
    return image_base + (runtime_address - module_base);
}

std::string ResolveOwner(
    uintptr_t preferred_return_address,
    const NativeAudioAttributionContext& attribution) {
    if (preferred_return_address == 0x00549BB7 ||
        attribution.skill_id == 0x20) {
        return "spell.frost_jet";
    }
    if (preferred_return_address == 0x00549F5C ||
        attribution.skill_id == 0x28) {
        return "spell.earth_boulder_charge";
    }
    if (preferred_return_address >= 0x00548B00 &&
        preferred_return_address < 0x0054B570) {
        return "spell.player_primary";
    }
    return "native@" + HexString(preferred_return_address);
}

const LoopCatalogEntry* ResolveLoopCatalogEntry(uintptr_t object_address) {
    uintptr_t registry_address = 0;
    if (g_compiled_registry_global == 0 ||
        !ProcessMemory::Instance().TryReadValue(
            g_compiled_registry_global,
            &registry_address) ||
        registry_address == 0 ||
        object_address < registry_address) {
        return nullptr;
    }

    const auto object_offset =
        static_cast<std::size_t>(object_address - registry_address);
    const auto it = std::find_if(
        kLoopCatalog.begin(),
        kLoopCatalog.end(),
        [object_offset](const LoopCatalogEntry& entry) {
            return entry.object_offset == object_offset;
        });
    return it == kLoopCatalog.end() ? nullptr : &*it;
}

const OneShotCatalogEntry* ResolveFootstepCatalogEntry(
    uintptr_t object_address) {
    uintptr_t registry_address = 0;
    if (g_compiled_registry_global == 0 ||
        !ProcessMemory::Instance().TryReadValue(
            g_compiled_registry_global,
            &registry_address) ||
        registry_address == 0 ||
        object_address < registry_address) {
        return nullptr;
    }

    const auto object_offset =
        static_cast<std::size_t>(object_address - registry_address);
    const auto it = std::find_if(
        kFootstepCatalog.begin(),
        kFootstepCatalog.end(),
        [object_offset](const OneShotCatalogEntry& entry) {
            return entry.object_offset == object_offset;
        });
    return it == kFootstepCatalog.end() ? nullptr : &*it;
}

void ObserveSoundPlay(
    uintptr_t object_address,
    uintptr_t return_address,
    float gain) {
    const auto* catalog =
        ResolveFootstepCatalogEntry(object_address);
    if (catalog == nullptr) {
        return;
    }

    const auto now_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    const auto preferred_return_address =
        ToPreferredImageAddress(return_address);
    const auto attribution = g_current_attribution;
    std::uint64_t sequence = 0;
    {
        std::lock_guard<std::mutex> lock(g_native_audio_mutex);
        sequence = g_next_event_sequence++;
    }
    Log(
        "[native-audio] event=play monotonic_ms=" +
        std::to_string(now_ms) +
        " sequence=" + std::to_string(sequence) +
        " asset=\"" + catalog->asset +
        "\" owner=movement.footstep" +
        " object=" + HexString(object_address) +
        " registry_index=" +
        std::to_string(catalog->registry_index) +
        " gain=" + std::to_string(gain) +
        " actor=" + HexString(attribution.actor_address) +
        " participant_id=" +
        std::to_string(attribution.participant_id) +
        " remote=" +
        std::to_string(attribution.remote ? 1 : 0) +
        " return=" + HexString(preferred_return_address));
}

void ReadLoopRuntimeState(
    uintptr_t object_address,
    uintptr_t* channel_handle,
    std::int32_t* reference_count) {
    auto& memory = ProcessMemory::Instance();
    uintptr_t channel_record = 0;
    if (channel_handle != nullptr) {
        *channel_handle = 0;
        if (memory.TryReadField(
                object_address,
                kSoundLoopChannelRecordOffset,
                &channel_record) &&
            channel_record != 0) {
            (void)memory.TryReadField(
                channel_record,
                kSoundChannelHandleOffset,
                channel_handle);
        }
    }
    if (reference_count != nullptr) {
        *reference_count = 0;
        (void)memory.TryReadField(
            object_address,
            kSoundLoopReferenceCountOffset,
            reference_count);
    }
}

void ObserveSoundLoopStart(
    uintptr_t object_address,
    uintptr_t return_address) {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto preferred_return_address =
        ToPreferredImageAddress(return_address);
    const auto attribution = g_current_attribution;
    uintptr_t channel_handle = 0;
    std::int32_t reference_count = 0;
    ReadLoopRuntimeState(
        object_address,
        &channel_handle,
        &reference_count);
    const auto* catalog = ResolveLoopCatalogEntry(object_address);

    NativeAudioChannelSnapshot logged;
    {
        std::lock_guard<std::mutex> lock(g_native_audio_mutex);
        auto& channel =
            g_native_audio_channels[object_address].snapshot;
        const bool new_lifecycle = !channel.active;
        if (channel.event_sequence == 0 || new_lifecycle) {
            channel.event_sequence = g_next_event_sequence++;
            channel.started_ms = now_ms;
            channel.stopped_ms = 0;
            channel.start_return_address = preferred_return_address;
            channel.actor_address = attribution.actor_address;
            channel.participant_id = attribution.participant_id;
            channel.skill_id = attribution.skill_id;
            channel.cast_sequence = attribution.cast_sequence;
            channel.remote = attribution.remote;
            channel.owner = ResolveOwner(
                preferred_return_address,
                attribution);
        }
        channel.object_address = object_address;
        channel.channel_handle = channel_handle;
        channel.last_return_address = preferred_return_address;
        channel.native_reference_count = reference_count;
        channel.registry_index =
            catalog == nullptr ? -1 : catalog->registry_index;
        channel.asset =
            catalog == nullptr ? "dynamic_sound_loop" : catalog->asset;
        channel.loop_flag = true;
        channel.active = reference_count > 0;
        channel.start_count += 1;
        logged = channel;
    }

    Log(
        "[native-audio] event=start monotonic_ms=" +
        std::to_string(now_ms) +
        " sequence=" + std::to_string(logged.event_sequence) +
        " asset=\"" + logged.asset +
        "\" owner=" + logged.owner +
        " object=" + HexString(logged.object_address) +
        " channel=" + HexString(logged.channel_handle) +
        " loop=1 active=" + std::to_string(logged.active ? 1 : 0) +
        " refcount=" +
        std::to_string(logged.native_reference_count) +
        " actor=" + HexString(logged.actor_address) +
        " participant_id=" +
        std::to_string(logged.participant_id) +
        " remote=" + std::to_string(logged.remote ? 1 : 0) +
        " skill_id=" + std::to_string(logged.skill_id) +
        " cast_sequence=" +
        std::to_string(logged.cast_sequence) +
        " return=" + HexString(logged.last_return_address));
}

void ObserveSoundLoopStop(
    uintptr_t object_address,
    uintptr_t return_address) {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto preferred_return_address =
        ToPreferredImageAddress(return_address);
    uintptr_t channel_handle = 0;
    std::int32_t reference_count = 0;
    ReadLoopRuntimeState(
        object_address,
        &channel_handle,
        &reference_count);

    NativeAudioChannelSnapshot logged;
    bool observed = false;
    {
        std::lock_guard<std::mutex> lock(g_native_audio_mutex);
        const auto found = g_native_audio_channels.find(object_address);
        if (found != g_native_audio_channels.end()) {
            auto& channel = found->second.snapshot;
            channel.channel_handle = channel_handle;
            channel.last_return_address = preferred_return_address;
            channel.native_reference_count = reference_count;
            channel.stop_count += 1;
            channel.active = reference_count > 0;
            if (!channel.active) {
                channel.stopped_ms = now_ms;
            }
            logged = channel;
            observed = true;
        }
    }
    if (!observed) {
        return;
    }

    Log(
        "[native-audio] event=stop monotonic_ms=" +
        std::to_string(now_ms) +
        " sequence=" + std::to_string(logged.event_sequence) +
        " asset=\"" + logged.asset +
        "\" owner=" + logged.owner +
        " object=" + HexString(logged.object_address) +
        " channel=" + HexString(logged.channel_handle) +
        " loop=1 active=" + std::to_string(logged.active ? 1 : 0) +
        " refcount=" +
        std::to_string(logged.native_reference_count) +
        " age_ms=" +
        std::to_string(now_ms - logged.started_ms) +
        " actor=" + HexString(logged.actor_address) +
        " participant_id=" +
        std::to_string(logged.participant_id) +
        " remote=" + std::to_string(logged.remote ? 1 : 0) +
        " skill_id=" + std::to_string(logged.skill_id) +
        " cast_sequence=" +
        std::to_string(logged.cast_sequence) +
        " return=" + HexString(logged.last_return_address));
}

void __fastcall HookSoundLoopStart(
    void* self,
    void* /*unused_edx*/) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto original =
        GetX86HookTrampoline<SoundLoopLifecycleFn>(
            g_sound_loop_start_hook);
    if (original == nullptr) {
        return;
    }
    original(self);
    ObserveSoundLoopStart(
        reinterpret_cast<uintptr_t>(self),
        return_address);
}

void __fastcall HookSoundLoopStop(
    void* self,
    void* /*unused_edx*/) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto original =
        GetX86HookTrampoline<SoundLoopLifecycleFn>(
            g_sound_loop_stop_hook);
    if (original == nullptr) {
        return;
    }
    original(self);
    ObserveSoundLoopStop(
        reinterpret_cast<uintptr_t>(self),
        return_address);
}

void __fastcall HookSoundPlay(
    void* self,
    void* /*unused_edx*/,
    float gain) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto original =
        GetX86HookTrampoline<SoundPlayFn>(
            g_sound_play_hook);
    if (original == nullptr) {
        return;
    }
    original(self, gain);
    ObserveSoundPlay(
        reinterpret_cast<uintptr_t>(self),
        return_address,
        gain);
}

bool ResolveAudioAddress(
    const char* section,
    const char* key,
    uintptr_t* address) {
    uintptr_t preferred_address = 0;
    return address != nullptr &&
           TryGetBinaryLayoutNumericValue(
               section,
               key,
               &preferred_address) &&
           preferred_address != 0 &&
           ProcessMemory::Instance().TryResolveGameAddress(
               preferred_address,
               address);
}

#include "native_audio_observability/footstep_dispatch_helpers.inl"

}  // namespace

ScopedNativeAudioAttribution::ScopedNativeAudioAttribution(
    uintptr_t actor_address)
    : previous_(g_current_attribution) {
    g_current_attribution = {};
    g_current_attribution.actor_address = actor_address;
}

ScopedNativeAudioAttribution::~ScopedNativeAudioAttribution() {
    g_current_attribution = previous_;
}

void ScopedNativeAudioAttribution::SetParticipantCast(
    std::uint64_t participant_id,
    bool remote,
    std::int32_t skill_id,
    std::uint32_t cast_sequence) {
    g_current_attribution.participant_id = participant_id;
    g_current_attribution.remote = remote;
    g_current_attribution.skill_id = skill_id;
    g_current_attribution.cast_sequence = cast_sequence;
}

bool InitializeNativeAudioObservability(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_sound_play_hook.installed &&
        g_sound_loop_start_hook.installed &&
        g_sound_loop_stop_hook.installed) {
        return true;
    }

    uintptr_t sound_play = 0;
    uintptr_t sound_loop_start = 0;
    uintptr_t sound_loop_stop = 0;
    if (!ResolveAudioAddress(
            "audio.lifecycle",
            "sound_play",
            &sound_play) ||
        !ResolveAudioAddress(
            "audio.lifecycle",
            "sound_loop_start",
            &sound_loop_start) ||
        !ResolveAudioAddress(
            "audio.lifecycle",
            "sound_loop_stop",
            &sound_loop_stop) ||
        !ResolveAudioAddress(
            "audio.globals",
            "compiled_registry",
            &g_compiled_registry_global) ||
        !ResolveAudioAddress(
            "audio.globals",
            "footstep_frame_counter",
            &g_footstep_frame_counter) ||
        !ResolveAudioAddress(
            "audio.globals",
            "footstep_gain_scale",
            &g_footstep_gain_scale)) {
        if (error_message != nullptr) {
            *error_message =
                "Native audio observability could not resolve the stock "
                "SoundLoop lifecycle and compiled registry.";
        }
        return false;
    }
    g_sound_play_address = sound_play;

    std::string hook_error;
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(sound_play),
            reinterpret_cast<void*>(&HookSoundPlay),
            kMinimumLifecycleHookPatchSize,
            &g_sound_play_hook,
            &hook_error)) {
        if (error_message != nullptr) {
            *error_message =
                "Native audio observability could not hook Sound_Play: " +
                hook_error;
        }
        return false;
    }
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(sound_loop_start),
            reinterpret_cast<void*>(&HookSoundLoopStart),
            kMinimumLifecycleHookPatchSize,
            &g_sound_loop_start_hook,
            &hook_error)) {
        RemoveX86Hook(&g_sound_play_hook);
        if (error_message != nullptr) {
            *error_message =
                "Native audio observability could not hook "
                "SoundLoop_Start: " +
                hook_error;
        }
        return false;
    }
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(sound_loop_stop),
            reinterpret_cast<void*>(&HookSoundLoopStop),
            kMinimumLifecycleHookPatchSize,
            &g_sound_loop_stop_hook,
            &hook_error)) {
        RemoveX86Hook(&g_sound_loop_start_hook);
        RemoveX86Hook(&g_sound_play_hook);
        if (error_message != nullptr) {
            *error_message =
                "Native audio observability could not hook "
                "SoundLoop_Stop: " +
                hook_error;
        }
        return false;
    }

    Log(
        "Native audio observability enabled for stock Sound_Play and "
        "SoundLoop lifecycle events.");
    return true;
}

void ShutdownNativeAudioObservability() {
    RemoveX86Hook(&g_sound_loop_stop_hook);
    RemoveX86Hook(&g_sound_loop_start_hook);
    RemoveX86Hook(&g_sound_play_hook);
    std::lock_guard<std::mutex> lock(g_native_audio_mutex);
    g_native_audio_channels.clear();
    g_last_footstep_frame_by_actor.clear();
    g_next_event_sequence = 1;
    g_compiled_registry_global = 0;
    g_sound_play_address = 0;
    g_footstep_frame_counter = 0;
    g_footstep_gain_scale = 0;
}

#include "native_audio_observability/footstep_dispatch.inl"

std::vector<NativeAudioChannelSnapshot> SnapshotNativeAudioChannels(
    bool include_inactive) {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    std::vector<NativeAudioChannelSnapshot> channels;
    {
        std::lock_guard<std::mutex> lock(g_native_audio_mutex);
        channels.reserve(g_native_audio_channels.size());
        for (const auto& [object_address, record] :
             g_native_audio_channels) {
            (void)object_address;
            if (!include_inactive && !record.snapshot.active) {
                continue;
            }
            auto snapshot = record.snapshot;
            const auto end_ms =
                snapshot.active || snapshot.stopped_ms == 0
                    ? now_ms
                    : snapshot.stopped_ms;
            snapshot.age_ms =
                end_ms >= snapshot.started_ms
                    ? end_ms - snapshot.started_ms
                    : 0;
            channels.push_back(std::move(snapshot));
        }
    }
    std::sort(
        channels.begin(),
        channels.end(),
        [](const NativeAudioChannelSnapshot& left,
           const NativeAudioChannelSnapshot& right) {
            if (left.active != right.active) {
                return left.active > right.active;
            }
            if (left.registry_index != right.registry_index) {
                return left.registry_index < right.registry_index;
            }
            return left.event_sequence < right.event_sequence;
        });
    return channels;
}

std::size_t ClearInactiveNativeAudioChannelHistory() {
    std::lock_guard<std::mutex> lock(g_native_audio_mutex);
    std::size_t removed = 0;
    for (auto it = g_native_audio_channels.begin();
         it != g_native_audio_channels.end();) {
        if (!it->second.snapshot.active) {
            it = g_native_audio_channels.erase(it);
            removed += 1;
        } else {
            ++it;
        }
    }
    return removed;
}

std::size_t DumpNativeAudioChannelsToLog(bool include_inactive) {
    const auto channels =
        SnapshotNativeAudioChannels(include_inactive);
    const auto active_count = static_cast<std::size_t>(
        std::count_if(
            channels.begin(),
            channels.end(),
            [](const NativeAudioChannelSnapshot& channel) {
                return channel.active;
            }));
    Log(
        "[native-audio] dump channel_count=" +
        std::to_string(channels.size()) +
        " active_count=" + std::to_string(active_count) +
        " include_inactive=" +
        std::to_string(include_inactive ? 1 : 0));
    for (const auto& channel : channels) {
        Log(
            "[native-audio] channel sequence=" +
            std::to_string(channel.event_sequence) +
            " asset=\"" + channel.asset +
            "\" owner=" + channel.owner +
            " object=" + HexString(channel.object_address) +
            " channel=" + HexString(channel.channel_handle) +
            " loop=" + std::to_string(channel.loop_flag ? 1 : 0) +
            " active=" + std::to_string(channel.active ? 1 : 0) +
            " age_ms=" + std::to_string(channel.age_ms) +
            " refcount=" +
            std::to_string(channel.native_reference_count) +
            " starts=" + std::to_string(channel.start_count) +
            " stops=" + std::to_string(channel.stop_count) +
            " actor=" + HexString(channel.actor_address) +
            " participant_id=" +
            std::to_string(channel.participant_id) +
            " remote=" + std::to_string(channel.remote ? 1 : 0) +
            " skill_id=" + std::to_string(channel.skill_id) +
            " cast_sequence=" +
            std::to_string(channel.cast_sequence) +
            " start_return=" +
            HexString(channel.start_return_address) +
            " last_return=" +
            HexString(channel.last_return_address));
    }
    return channels.size();
}

}  // namespace sdmod
