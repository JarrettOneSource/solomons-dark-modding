bool DispatchNativeAudioCensusProbe(
    std::int32_t registry_index,
    const std::string& operation,
    float gain,
    float pitch,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_native_audio_dispatch_capture_enabled) {
        if (error_message != nullptr) {
            *error_message =
                "Native audio census probe requires opt-in dispatch capture.";
        }
        return false;
    }
    std::uint8_t engine_enabled = 0;
    if (g_engine_enabled_address == 0 ||
        !ProcessMemory::Instance().TryReadValue(
            g_engine_enabled_address,
            &engine_enabled)) {
        if (error_message != nullptr) {
            *error_message =
                "Native audio census probe could not read the engine gate.";
        }
        return false;
    }
    if (engine_enabled != 0) {
        if (error_message != nullptr) {
            *error_message =
                "Native audio census probe refused an enabled audio engine.";
        }
        return false;
    }
    if (!std::isfinite(gain) || !std::isfinite(pitch)) {
        if (error_message != nullptr) {
            *error_message =
                "Native audio census probe parameters must be finite.";
        }
        return false;
    }

    std::uint64_t previous_sequence = 0;
    uintptr_t observed_music_object = 0;
    {
        std::lock_guard<std::mutex> lock(g_native_audio_mutex);
        if (!g_native_audio_dispatch_events.empty()) {
            previous_sequence =
                g_native_audio_dispatch_events.back().event_sequence;
        }
        observed_music_object = g_observed_music_object_address;
    }

    if (registry_index == -1 &&
        operation == "music_crossfade_empty") {
        if (observed_music_object == 0) {
            if (error_message != nullptr) {
                *error_message =
                    "Native audio census probe has no naturally observed "
                    "Music object; startup is broken, not busy.";
            }
            return false;
        }
        reinterpret_cast<MusicPlayCrossfadeFn>(
            g_music_play_crossfade_address)(
                reinterpret_cast<void*>(observed_music_object),
                NativeAudioString{},
                gain);
        bool observed = false;
        {
            std::lock_guard<std::mutex> lock(g_native_audio_mutex);
            observed = std::any_of(
                g_native_audio_dispatch_events.begin(),
                g_native_audio_dispatch_events.end(),
                [&](const NativeAudioDispatchSnapshot& event) {
                    return event.event_sequence > previous_sequence &&
                           event.native_class == "Music" &&
                           event.operation == "music_play_crossfade" &&
                           event.requested_name.empty() &&
                           !event.engine_enabled;
                });
        }
        if (!observed && error_message != nullptr) {
            *error_message =
                "Native audio census probe reached no empty-song Music "
                "dispatch; the capture tap is broken, not busy.";
        }
        return observed;
    }

    uintptr_t object_address = 0;
    const char* native_class = nullptr;
    if (!TryResolveRegistryIndex(
            registry_index,
            &object_address,
            &native_class) ||
        native_class == nullptr) {
        if (error_message != nullptr) {
            *error_message =
                "Native audio census probe registry index is absent or "
                "ambiguous.";
        }
        return false;
    }

    const std::string resolved_class(native_class);
    if (operation == "play_gain" && resolved_class == "Sound") {
        reinterpret_cast<SoundPlayFn>(g_sound_play_address)(
            reinterpret_cast<void*>(object_address),
            gain);
    } else if (operation == "play_pitch_gain" &&
               resolved_class == "Sound") {
        reinterpret_cast<SoundPlayWithPitchFn>(
            g_sound_play_with_pitch_address)(
                reinterpret_cast<void*>(object_address),
                pitch,
                gain);
    } else if (operation == "loop_start" &&
               resolved_class == "SoundLoop") {
        reinterpret_cast<SoundLoopLifecycleFn>(
            g_sound_loop_start_address)(
                reinterpret_cast<void*>(object_address));
    } else if (operation == "loop_stop" &&
               resolved_class == "SoundLoop") {
        reinterpret_cast<SoundLoopLifecycleFn>(
            g_sound_loop_stop_address)(
                reinterpret_cast<void*>(object_address));
    } else if (operation == "stream_play" &&
               resolved_class == "SoundStream") {
        reinterpret_cast<SoundStreamPlayFn>(
            g_sound_stream_play_address)(
                reinterpret_cast<void*>(object_address),
                gain);
    } else if (operation == "stream_pause" &&
               resolved_class == "SoundStream") {
        reinterpret_cast<SoundStreamPauseFn>(
            g_sound_stream_pause_address)(
                reinterpret_cast<void*>(object_address));
    } else {
        if (error_message != nullptr) {
            *error_message =
                "Native audio census probe operation does not match the "
                "resolved registry class.";
        }
        return false;
    }

    const auto expected_operation = operation;
    bool observed = false;
    {
        std::lock_guard<std::mutex> lock(g_native_audio_mutex);
        observed = std::any_of(
            g_native_audio_dispatch_events.begin(),
            g_native_audio_dispatch_events.end(),
            [&](const NativeAudioDispatchSnapshot& event) {
                return event.event_sequence > previous_sequence &&
                       event.registry_index == registry_index &&
                       event.operation == expected_operation &&
                       !event.engine_enabled;
            });
    }
    if (!observed) {
        if (error_message != nullptr) {
            *error_message =
                "Native audio census probe reached no matching dispatch "
                "event; the capture tap is broken, not busy.";
        }
        return false;
    }
    return true;
}
