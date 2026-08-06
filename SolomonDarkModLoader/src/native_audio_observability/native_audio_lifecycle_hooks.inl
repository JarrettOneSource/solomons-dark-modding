void ObserveSoundPlay(
    uintptr_t object_address,
    uintptr_t return_address,
    float gain) {
    CaptureDispatchEvent(
        object_address,
        return_address,
        "play_gain",
        gain,
        1.0f);
    const auto* catalog =
        ResolveOneShotCatalogEntry(object_address);
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
        "\" owner=" + catalog->owner +
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
    CaptureDispatchEvent(
        object_address,
        return_address,
        "loop_start",
        1.0f,
        1.0f,
        reference_count);
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
    CaptureDispatchEvent(
        object_address,
        return_address,
        "loop_stop",
        0.0f,
        1.0f,
        reference_count);

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

void __fastcall HookSoundPlayWithPitch(
    void* self,
    void* /*unused_edx*/,
    float pitch,
    float gain) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto original =
        GetX86HookTrampoline<SoundPlayWithPitchFn>(
            g_sound_play_with_pitch_hook);
    if (original == nullptr) {
        return;
    }
    original(self, pitch, gain);
    CaptureDispatchEvent(
        reinterpret_cast<uintptr_t>(self),
        return_address,
        "play_pitch_gain",
        gain,
        pitch);
}

void __fastcall HookSoundStreamPlay(
    void* self,
    void* /*unused_edx*/,
    float gain) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto original =
        GetX86HookTrampoline<SoundStreamPlayFn>(
            g_sound_stream_play_hook);
    if (original == nullptr) {
        return;
    }
    original(self, gain);
    CaptureDispatchEvent(
        reinterpret_cast<uintptr_t>(self),
        return_address,
        "stream_play",
        gain,
        1.0f);
}

void __fastcall HookSoundStreamPause(
    void* self,
    void* /*unused_edx*/) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto original =
        GetX86HookTrampoline<SoundStreamPauseFn>(
            g_sound_stream_pause_hook);
    if (original == nullptr) {
        return;
    }
    original(self);
    CaptureDispatchEvent(
        reinterpret_cast<uintptr_t>(self),
        return_address,
        "stream_pause",
        0.0f,
        1.0f);
}

void __fastcall HookMusicPlayImmediate(
    void* self,
    void* /*unused_edx*/,
    NativeAudioString song) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto requested_name = CopyNativeAudioString(song);
    const auto original =
        GetX86HookTrampoline<MusicPlayImmediateFn>(
            g_music_play_immediate_hook);
    if (original == nullptr) {
        return;
    }
    original(self, song);
    CaptureMusicDispatchEvent(
        reinterpret_cast<uintptr_t>(self),
        return_address,
        "music_play_immediate",
        requested_name,
        {},
        0.0f);
}

void __fastcall HookMusicPlayCrossfade(
    void* self,
    void* /*unused_edx*/,
    NativeAudioString song,
    float transition_ticks) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto requested_name = CopyNativeAudioString(song);
    const auto original =
        GetX86HookTrampoline<MusicPlayCrossfadeFn>(
            g_music_play_crossfade_hook);
    if (original == nullptr) {
        return;
    }
    original(self, song, transition_ticks);
    CaptureMusicDispatchEvent(
        reinterpret_cast<uintptr_t>(self),
        return_address,
        "music_play_crossfade",
        requested_name,
        {},
        transition_ticks);
}

void __fastcall HookMusicTransition(
    void* self,
    void* /*unused_edx*/,
    NativeAudioString song,
    NativeAudioString track,
    float transition_ticks) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto requested_name = CopyNativeAudioString(song);
    const auto requested_track = CopyNativeAudioString(track);
    const auto original =
        GetX86HookTrampoline<MusicTransitionFn>(
            g_music_transition_hook);
    if (original == nullptr) {
        return;
    }
    original(self, song, track, transition_ticks);
    CaptureMusicDispatchEvent(
        reinterpret_cast<uintptr_t>(self),
        return_address,
        "music_transition",
        requested_name,
        requested_track,
        transition_ticks);
}

void __fastcall HookMusicStop(
    void* self,
    void* /*unused_edx*/) {
    const auto return_address =
        reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto original =
        GetX86HookTrampoline<MusicStopFn>(g_music_stop_hook);
    if (original == nullptr) {
        return;
    }
    original(self);
    CaptureMusicDispatchEvent(
        reinterpret_cast<uintptr_t>(self),
        return_address,
        "music_stop",
        {},
        {},
        0.0f);
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

bool ResolvePreferredAudioAddress(
    uintptr_t preferred_address,
    uintptr_t* address) {
    return address != nullptr &&
           preferred_address != 0 &&
           ProcessMemory::Instance().TryResolveGameAddress(
               preferred_address,
               address);
}

#include "native_audio_observability/footstep_dispatch_helpers.inl"
