constexpr std::size_t kSoundLoopChannelRecordOffset = 0x44;
constexpr std::size_t kSoundLoopReferenceCountOffset = 0x4C;
constexpr std::size_t kSoundChannelHandleOffset = 0x00;
constexpr std::size_t kMinimumLifecycleHookPatchSize = 5;
constexpr std::size_t kWorldPointGainVfuncOffset = 0x100;
constexpr std::size_t kWorldHitPointGainVfuncOffset = 0x104;
constexpr std::uint32_t kNativeFootstepCadenceFrames = 25;
constexpr std::size_t kMaximumObservedFootstepActors = 16;
constexpr std::size_t kMaximumCapturedDispatchEvents = 4096;
constexpr uintptr_t kMusicPlayImmediatePreferredAddress = 0x00409A10;
constexpr uintptr_t kMusicPlayCrossfadePreferredAddress = 0x00409CD0;
constexpr uintptr_t kMusicTransitionPreferredAddress = 0x00409FA0;

struct RegistrySegment {
    std::int32_t first_index;
    std::int32_t count;
    std::size_t first_offset;
    std::size_t stride;
    const char* native_class;
};

constexpr std::array<RegistrySegment, 4> kRegistrySegments = {{
    {0, 111, 0x0018, 0x2C, "Sound"},
    {111, 40, 0x132C, 0x08, "SoundStream"},
    {151, 22, 0x146C, 0x60, "SoundLoop"},
    {173, 60, 0x1CAC, 0x2C, "Sound"},
}};

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
    const char* owner;
};

constexpr std::array<OneShotCatalogEntry, 2> kFootstepCatalog = {{
    {214, 0x23B8, "sounds\\Step\\step1", "movement.footstep"},
    {215, 0x23E4, "sounds\\Step\\step2", "movement.footstep"},
}};

constexpr std::array<OneShotCatalogEntry, 3> kOuchCatalog = {{
    {228, 0x2620, "sounds/Wizard_Ouch/SAY_OUCH1.wav", "player.hit"},
    {229, 0x264C, "sounds/Wizard_Ouch/SAY_OUCH2.wav", "player.hit"},
    {230, 0x2678, "sounds/Wizard_Ouch/SAY_OUCH3.wav", "player.hit"},
}};

struct NativeAudioChannelRecord {
    NativeAudioChannelSnapshot snapshot;
};

std::mutex g_native_audio_mutex;
std::unordered_map<uintptr_t, NativeAudioChannelRecord>
    g_native_audio_channels;
std::vector<NativeAudioDispatchSnapshot> g_native_audio_dispatch_events;
std::uint64_t g_next_event_sequence = 1;
uintptr_t g_compiled_registry_global = 0;
uintptr_t g_sound_play_address = 0;
uintptr_t g_sound_play_with_pitch_address = 0;
uintptr_t g_sound_loop_start_address = 0;
uintptr_t g_sound_loop_stop_address = 0;
uintptr_t g_sound_stream_play_address = 0;
uintptr_t g_sound_stream_pause_address = 0;
uintptr_t g_music_play_immediate_address = 0;
uintptr_t g_music_play_crossfade_address = 0;
uintptr_t g_music_transition_address = 0;
uintptr_t g_music_stop_address = 0;
uintptr_t g_engine_enabled_address = 0;
uintptr_t g_observed_music_object_address = 0;
uintptr_t g_footstep_frame_counter = 0;
uintptr_t g_footstep_gain_scale = 0;
X86Hook g_sound_loop_start_hook;
X86Hook g_sound_loop_stop_hook;
X86Hook g_sound_play_hook;
X86Hook g_sound_play_with_pitch_hook;
X86Hook g_sound_stream_play_hook;
X86Hook g_sound_stream_pause_hook;
X86Hook g_music_play_immediate_hook;
X86Hook g_music_play_crossfade_hook;
X86Hook g_music_transition_hook;
X86Hook g_music_stop_hook;
thread_local NativeAudioAttributionContext g_current_attribution;
std::unordered_map<uintptr_t, std::uint32_t>
    g_last_footstep_frame_by_actor;
bool g_native_audio_dispatch_capture_enabled = false;

using SoundLoopLifecycleFn = void(__thiscall*)(void* self);
using SoundPlayFn = void(__thiscall*)(void* self, float gain);
using SoundPlayWithPitchFn =
    void(__thiscall*)(void* self, float pitch, float gain);
using SoundStreamPlayFn = void(__thiscall*)(void* self, float gain);
using SoundStreamPauseFn = void(__thiscall*)(void* self);

struct NativeAudioString {
    uintptr_t vtable = 0;
    char* text = nullptr;
    std::uint32_t unknown_08 = 0;
    std::int32_t* ref_count = nullptr;
    std::uint32_t length = 0;
    std::uint8_t flags_14 = 0;
    std::uint8_t flags_15 = 0;
    std::uint16_t padding_16 = 0;
    std::uint32_t unknown_18 = 0;
};
static_assert(
    sizeof(NativeAudioString) == 0x1C,
    "Native audio String-by-value layout changed");

using MusicPlayImmediateFn =
    void(__thiscall*)(void* self, NativeAudioString song);
using MusicPlayCrossfadeFn =
    void(__thiscall*)(void* self, NativeAudioString song, float ticks);
using MusicTransitionFn = void(__thiscall*)(
    void* self,
    NativeAudioString song,
    NativeAudioString track,
    float ticks);
using MusicStopFn = void(__thiscall*)(void* self);

void RemoveNativeAudioDispatchCaptureHooks() {
    RemoveX86Hook(&g_music_stop_hook);
    RemoveX86Hook(&g_music_transition_hook);
    RemoveX86Hook(&g_music_play_crossfade_hook);
    RemoveX86Hook(&g_music_play_immediate_hook);
    RemoveX86Hook(&g_sound_stream_pause_hook);
    RemoveX86Hook(&g_sound_stream_play_hook);
    RemoveX86Hook(&g_sound_play_with_pitch_hook);
}
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
        return 0;
    }
    IMAGE_DOS_HEADER dos_header{};
    IMAGE_NT_HEADERS32 nt_headers{};
    auto& memory = ProcessMemory::Instance();
    if (!memory.TryReadValue(module_base, &dos_header) ||
        dos_header.e_magic != IMAGE_DOS_SIGNATURE ||
        dos_header.e_lfanew <= 0 ||
        !memory.TryReadValue(
            module_base + static_cast<uintptr_t>(dos_header.e_lfanew),
            &nt_headers) ||
        nt_headers.Signature != IMAGE_NT_SIGNATURE ||
        runtime_address >=
            module_base + nt_headers.OptionalHeader.SizeOfImage) {
        return 0;
    }
    return image_base + (runtime_address - module_base);
}

bool IsEnvironmentFlagSet(const char* name) {
    std::array<char, 8> value{};
    const auto length = GetEnvironmentVariableA(
        name,
        value.data(),
        static_cast<DWORD>(value.size()));
    return length == 1 && value[0] == '1';
}

bool TryReadCompiledRegistryBase(uintptr_t* registry_address) {
    return registry_address != nullptr &&
           g_compiled_registry_global != 0 &&
           ProcessMemory::Instance().TryReadValue(
               g_compiled_registry_global,
               registry_address) &&
           *registry_address != 0;
}

bool TryResolveRegistryObject(
    uintptr_t object_address,
    std::int32_t* registry_index,
    const char** native_class) {
    uintptr_t registry_address = 0;
    if (!TryReadCompiledRegistryBase(&registry_address) ||
        object_address < registry_address) {
        return false;
    }

    const auto object_offset =
        static_cast<std::size_t>(object_address - registry_address);
    std::size_t match_count = 0;
    std::int32_t matched_index = -1;
    const char* matched_class = nullptr;
    for (const auto& segment : kRegistrySegments) {
        if (object_offset < segment.first_offset) {
            continue;
        }
        const auto delta = object_offset - segment.first_offset;
        if (delta % segment.stride != 0) {
            continue;
        }
        const auto local_index = delta / segment.stride;
        if (local_index >= static_cast<std::size_t>(segment.count)) {
            continue;
        }
        match_count += 1;
        matched_index = segment.first_index +
                        static_cast<std::int32_t>(local_index);
        matched_class = segment.native_class;
    }
    if (match_count != 1) {
        return false;
    }
    if (registry_index != nullptr) {
        *registry_index = matched_index;
    }
    if (native_class != nullptr) {
        *native_class = matched_class;
    }
    return true;
}

bool TryResolveRegistryIndex(
    std::int32_t registry_index,
    uintptr_t* object_address,
    const char** native_class) {
    uintptr_t registry_address = 0;
    if (!TryReadCompiledRegistryBase(&registry_address)) {
        return false;
    }
    std::size_t match_count = 0;
    uintptr_t matched_address = 0;
    const char* matched_class = nullptr;
    for (const auto& segment : kRegistrySegments) {
        const auto local_index = registry_index - segment.first_index;
        if (local_index < 0 || local_index >= segment.count) {
            continue;
        }
        match_count += 1;
        matched_address = registry_address + segment.first_offset +
                          static_cast<std::size_t>(local_index) *
                              segment.stride;
        matched_class = segment.native_class;
    }
    if (match_count != 1) {
        return false;
    }

    std::int32_t round_trip_index = -1;
    const char* round_trip_class = nullptr;
    if (!TryResolveRegistryObject(
            matched_address,
            &round_trip_index,
            &round_trip_class) ||
        round_trip_index != registry_index ||
        round_trip_class == nullptr ||
        std::string(round_trip_class) != matched_class) {
        return false;
    }
    if (object_address != nullptr) {
        *object_address = matched_address;
    }
    if (native_class != nullptr) {
        *native_class = matched_class;
    }
    return true;
}

std::uint64_t ReadNativeAudioTick() {
    std::uint32_t tick = 0;
    if (g_footstep_frame_counter != 0) {
        (void)ProcessMemory::Instance().TryReadValue(
            g_footstep_frame_counter,
            &tick);
    }
    return tick;
}

bool ReadEngineEnabled() {
    std::uint8_t enabled = 0;
    return g_engine_enabled_address != 0 &&
           ProcessMemory::Instance().TryReadValue(
               g_engine_enabled_address,
               &enabled) &&
           enabled != 0;
}

void CaptureDispatchEvent(
    uintptr_t object_address,
    uintptr_t return_address,
    const char* operation,
    float gain,
    float pitch,
    std::int32_t native_reference_count = 0) {
    if (!g_native_audio_dispatch_capture_enabled) {
        return;
    }

    NativeAudioDispatchSnapshot event;
    event.native_tick = ReadNativeAudioTick();
    event.monotonic_ms = static_cast<std::uint64_t>(GetTickCount64());
    event.object_address = object_address;
    event.caller_return_address = ToPreferredImageAddress(return_address);
    event.caller_in_game_image = event.caller_return_address != 0;
    event.gain = gain;
    event.pitch = pitch;
    event.native_reference_count = native_reference_count;
    event.engine_enabled = ReadEngineEnabled();
    event.operation = operation == nullptr ? "unknown" : operation;
    const char* native_class = nullptr;
    if (TryResolveRegistryObject(
            object_address,
            &event.registry_index,
            &native_class)) {
        event.native_class = native_class;
    } else {
        event.native_class = "dynamic";
    }

    std::lock_guard<std::mutex> lock(g_native_audio_mutex);
    event.event_sequence = g_next_event_sequence++;
    if (g_native_audio_dispatch_events.size() >=
        kMaximumCapturedDispatchEvents) {
        g_native_audio_dispatch_events.erase(
            g_native_audio_dispatch_events.begin());
    }
    g_native_audio_dispatch_events.push_back(std::move(event));
}

std::string CopyNativeAudioString(const NativeAudioString& value) {
    if (value.text == nullptr || value.length == 0) {
        return {};
    }
    if (value.length > 127) {
        return "<invalid-native-string>";
    }
    std::string result;
    if (!ProcessMemory::Instance().TryReadCString(
            reinterpret_cast<uintptr_t>(value.text),
            static_cast<std::size_t>(value.length) + 1,
            &result) ||
        result.size() != value.length) {
        return "<unreadable-native-string>";
    }
    return result;
}

void CaptureMusicDispatchEvent(
    uintptr_t object_address,
    uintptr_t return_address,
    const char* operation,
    std::string requested_name,
    std::string requested_track,
    float transition_ticks) {
    if (!g_native_audio_dispatch_capture_enabled) {
        return;
    }
    NativeAudioDispatchSnapshot event;
    event.native_tick = ReadNativeAudioTick();
    event.monotonic_ms = static_cast<std::uint64_t>(GetTickCount64());
    event.object_address = object_address;
    event.caller_return_address = ToPreferredImageAddress(return_address);
    event.caller_in_game_image = event.caller_return_address != 0;
    event.registry_index = -1;
    event.native_class = "Music";
    event.operation = operation == nullptr ? "unknown" : operation;
    event.gain = 1.0f;
    event.pitch = 1.0f;
    event.transition_ticks = transition_ticks;
    event.engine_enabled = ReadEngineEnabled();
    event.requested_name = std::move(requested_name);
    event.requested_track = std::move(requested_track);

    std::lock_guard<std::mutex> lock(g_native_audio_mutex);
    g_observed_music_object_address = object_address;
    event.event_sequence = g_next_event_sequence++;
    if (g_native_audio_dispatch_events.size() >=
        kMaximumCapturedDispatchEvents) {
        g_native_audio_dispatch_events.erase(
            g_native_audio_dispatch_events.begin());
    }
    g_native_audio_dispatch_events.push_back(std::move(event));
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

const OneShotCatalogEntry* ResolveOneShotCatalogEntry(
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
    const auto footstep = std::find_if(
        kFootstepCatalog.begin(),
        kFootstepCatalog.end(),
        [object_offset](const OneShotCatalogEntry& entry) {
            return entry.object_offset == object_offset;
        });
    if (footstep != kFootstepCatalog.end()) {
        return &*footstep;
    }
    const auto ouch = std::find_if(
        kOuchCatalog.begin(),
        kOuchCatalog.end(),
        [object_offset](const OneShotCatalogEntry& entry) {
            return entry.object_offset == object_offset;
        });
    return ouch == kOuchCatalog.end() ? nullptr : &*ouch;
}
