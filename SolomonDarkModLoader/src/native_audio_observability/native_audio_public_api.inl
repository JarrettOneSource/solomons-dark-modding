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
    const bool capture_requested =
        IsEnvironmentFlagSet("SDMOD_CAPTURE_AUDIO_EVENTS");
    if (capture_requested &&
        !IsEnvironmentFlagSet("SDMOD_DISABLE_AUDIO")) {
        if (error_message != nullptr) {
            *error_message =
                "Native audio dispatch capture requires "
                "SDMOD_DISABLE_AUDIO=1.";
        }
        return false;
    }
    if (g_sound_play_hook.installed &&
        g_sound_loop_start_hook.installed &&
        g_sound_loop_stop_hook.installed &&
        (!capture_requested ||
         g_native_audio_dispatch_capture_enabled)) {
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
    g_sound_loop_start_address = sound_loop_start;
    g_sound_loop_stop_address = sound_loop_stop;

    if (capture_requested) {
        if (!ResolveAudioAddress(
                "audio.lifecycle",
                "sound_play_with_pitch",
                &g_sound_play_with_pitch_address) ||
            !ResolveAudioAddress(
                "audio.lifecycle",
                "sound_stream_play",
                &g_sound_stream_play_address) ||
            !ResolveAudioAddress(
                "audio.lifecycle",
                "sound_stream_pause",
                &g_sound_stream_pause_address) ||
            !ResolvePreferredAudioAddress(
                kMusicPlayImmediatePreferredAddress,
                &g_music_play_immediate_address) ||
            !ResolvePreferredAudioAddress(
                kMusicPlayCrossfadePreferredAddress,
                &g_music_play_crossfade_address) ||
            !ResolvePreferredAudioAddress(
                kMusicTransitionPreferredAddress,
                &g_music_transition_address) ||
            !ResolveAudioAddress(
                "audio.lifecycle",
                "music_stop",
                &g_music_stop_address) ||
            !ResolveAudioAddress(
                "audio.globals",
                "engine_enabled",
                &g_engine_enabled_address)) {
            if (error_message != nullptr) {
                *error_message =
                    "Native audio dispatch capture could not resolve every "
                    "dispatch wrapper and the engine gate.";
            }
            return false;
        }
        std::uint8_t engine_enabled = 0;
        if (!ProcessMemory::Instance().TryReadValue(
                g_engine_enabled_address,
                &engine_enabled)) {
            if (error_message != nullptr) {
                *error_message =
                    "Native audio dispatch capture could not read the "
                    "runtime engine gate.";
            }
            return false;
        }
        if (engine_enabled != 0) {
            if (error_message != nullptr) {
                *error_message =
                    "Native audio dispatch capture refused an enabled "
                    "audio engine.";
            }
            return false;
        }
    }

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

    if (capture_requested &&
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(g_sound_play_with_pitch_address),
            reinterpret_cast<void*>(&HookSoundPlayWithPitch),
            kMinimumLifecycleHookPatchSize,
            &g_sound_play_with_pitch_hook,
            &hook_error)) {
        RemoveX86Hook(&g_sound_loop_stop_hook);
        RemoveX86Hook(&g_sound_loop_start_hook);
        RemoveX86Hook(&g_sound_play_hook);
        if (error_message != nullptr) {
            *error_message =
                "Native audio dispatch capture could not hook "
                "Sound_PlayWithPitch: " + hook_error;
        }
        return false;
    }
    if (capture_requested &&
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(g_sound_stream_play_address),
            reinterpret_cast<void*>(&HookSoundStreamPlay),
            kMinimumLifecycleHookPatchSize,
            &g_sound_stream_play_hook,
            &hook_error)) {
        RemoveX86Hook(&g_sound_play_with_pitch_hook);
        RemoveX86Hook(&g_sound_loop_stop_hook);
        RemoveX86Hook(&g_sound_loop_start_hook);
        RemoveX86Hook(&g_sound_play_hook);
        if (error_message != nullptr) {
            *error_message =
                "Native audio dispatch capture could not hook "
                "SoundStream_Play: " + hook_error;
        }
        return false;
    }
    if (capture_requested &&
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(g_sound_stream_pause_address),
            reinterpret_cast<void*>(&HookSoundStreamPause),
            kMinimumLifecycleHookPatchSize,
            &g_sound_stream_pause_hook,
            &hook_error)) {
        RemoveX86Hook(&g_sound_stream_play_hook);
        RemoveX86Hook(&g_sound_play_with_pitch_hook);
        RemoveX86Hook(&g_sound_loop_stop_hook);
        RemoveX86Hook(&g_sound_loop_start_hook);
        RemoveX86Hook(&g_sound_play_hook);
        if (error_message != nullptr) {
            *error_message =
                "Native audio dispatch capture could not hook "
                "SoundStream_Pause: " + hook_error;
        }
        return false;
    }

    struct OptionalHookSpec {
        uintptr_t address;
        void* detour;
        X86Hook* hook;
        const char* name;
    };
    const std::array<OptionalHookSpec, 4> music_hook_specs = {{
        {
            g_music_play_immediate_address,
            reinterpret_cast<void*>(&HookMusicPlayImmediate),
            &g_music_play_immediate_hook,
            "Music_PlayImmediate",
        },
        {
            g_music_play_crossfade_address,
            reinterpret_cast<void*>(&HookMusicPlayCrossfade),
            &g_music_play_crossfade_hook,
            "Music_PlayCrossfade",
        },
        {
            g_music_transition_address,
            reinterpret_cast<void*>(&HookMusicTransition),
            &g_music_transition_hook,
            "Music_Transition",
        },
        {
            g_music_stop_address,
            reinterpret_cast<void*>(&HookMusicStop),
            &g_music_stop_hook,
            "Music_Stop",
        },
    }};
    if (capture_requested) {
        for (const auto& spec : music_hook_specs) {
            if (InstallSafeX86Hook(
                    reinterpret_cast<void*>(spec.address),
                    spec.detour,
                    kMinimumLifecycleHookPatchSize,
                    spec.hook,
                    &hook_error)) {
                continue;
            }
            RemoveNativeAudioDispatchCaptureHooks();
            RemoveX86Hook(&g_sound_loop_stop_hook);
            RemoveX86Hook(&g_sound_loop_start_hook);
            RemoveX86Hook(&g_sound_play_hook);
            if (error_message != nullptr) {
                *error_message =
                    std::string(
                        "Native audio dispatch capture could not hook ") +
                    spec.name + ": " + hook_error;
            }
            return false;
        }
    }

    g_native_audio_dispatch_capture_enabled = capture_requested;

    Log(
        capture_requested
            ? "Native audio observability enabled with silent opt-in "
              "dispatch capture for Sound, SoundStream, SoundLoop, and Music."
            : "Native audio observability enabled for stock Sound_Play and "
              "SoundLoop lifecycle events.");
    return true;
}

void ShutdownNativeAudioObservability() {
    g_native_audio_dispatch_capture_enabled = false;
    RemoveNativeAudioDispatchCaptureHooks();
    RemoveX86Hook(&g_sound_loop_stop_hook);
    RemoveX86Hook(&g_sound_loop_start_hook);
    RemoveX86Hook(&g_sound_play_hook);
    std::lock_guard<std::mutex> lock(g_native_audio_mutex);
    g_native_audio_channels.clear();
    g_native_audio_dispatch_events.clear();
    g_last_footstep_frame_by_actor.clear();
    g_next_event_sequence = 1;
    g_compiled_registry_global = 0;
    g_sound_play_address = 0;
    g_sound_play_with_pitch_address = 0;
    g_sound_loop_start_address = 0;
    g_sound_loop_stop_address = 0;
    g_sound_stream_play_address = 0;
    g_sound_stream_pause_address = 0;
    g_music_play_immediate_address = 0;
    g_music_play_crossfade_address = 0;
    g_music_transition_address = 0;
    g_music_stop_address = 0;
    g_engine_enabled_address = 0;
    g_observed_music_object_address = 0;
    g_footstep_frame_counter = 0;
    g_footstep_gain_scale = 0;
}

#include "native_audio_observability/footstep_dispatch.inl"
#include "native_audio_observability/ouch_dispatch.inl"

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

bool IsNativeAudioDispatchCaptureEnabled() {
    return g_native_audio_dispatch_capture_enabled;
}

std::vector<NativeAudioDispatchSnapshot>
SnapshotNativeAudioDispatchEvents() {
    std::lock_guard<std::mutex> lock(g_native_audio_mutex);
    return g_native_audio_dispatch_events;
}

std::size_t ClearNativeAudioDispatchEvents() {
    std::lock_guard<std::mutex> lock(g_native_audio_mutex);
    const auto removed = g_native_audio_dispatch_events.size();
    g_native_audio_dispatch_events.clear();
    return removed;
}
