std::string JsonEscape(std::string_view value) {
    std::ostringstream stream;
    for (const unsigned char character : value) {
        switch (character) {
        case '\\': stream << "\\\\"; break;
        case '"': stream << "\\\""; break;
        case '\b': stream << "\\b"; break;
        case '\f': stream << "\\f"; break;
        case '\n': stream << "\\n"; break;
        case '\r': stream << "\\r"; break;
        case '\t': stream << "\\t"; break;
        default:
            if (character < 0x20) {
                stream << "\\u" << std::hex << std::setw(4)
                       << std::setfill('0')
                       << static_cast<unsigned int>(character)
                       << std::dec;
            } else {
                stream << static_cast<char>(character);
            }
            break;
        }
    }
    return stream.str();
}

std::string ReadEnvironmentValue(const char* name) {
    if (name == nullptr || *name == '\0') {
        return {};
    }
    std::string value(32768, '\0');
    const auto length = GetEnvironmentVariableA(
        name,
        value.data(),
        static_cast<DWORD>(value.size()));
    if (length == 0 || length >= value.size()) {
        return {};
    }
    value.resize(length);
    return value;
}

std::string HexAddress(std::uintptr_t value) {
    std::ostringstream stream;
    stream << "0x" << std::uppercase << std::hex << std::setw(8)
           << std::setfill('0') << value;
    return stream.str();
}

bool WriteTextAtomically(
    const std::filesystem::path& destination,
    std::string_view text,
    std::string* error_message) {
    const auto temporary = destination.wstring() + L".tmp";
    {
        std::ofstream stream(
            std::filesystem::path(temporary),
            std::ios::binary | std::ios::trunc);
        stream.write(text.data(), static_cast<std::streamsize>(text.size()));
        stream.flush();
        if (!stream) {
            if (error_message != nullptr) {
                *error_message = "session-flow recorder could not flush " +
                    destination.string();
            }
            return false;
        }
    }
    if (!MoveFileExW(
            temporary.c_str(),
            destination.c_str(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileW(temporary.c_str());
        if (error_message != nullptr) {
            *error_message = "session-flow recorder could not publish " +
                destination.string() + " (Win32 " +
                std::to_string(GetLastError()) + ")";
        }
        return false;
    }
    return true;
}

void WriteStatusLocked() {
    if (g_capture.status_path.empty()) {
        return;
    }
    std::ostringstream stream;
    stream << "{\n"
           << "  \"schema_version\": 1,\n"
           << "  \"instance\": \"" << JsonEscape(g_capture.instance)
           << "\",\n"
           << "  \"state\": \"" << JsonEscape(g_capture.status)
           << "\",\n"
           << "  \"initialized\": "
           << (g_capture.initialized ? "true" : "false") << ",\n"
           << "  \"runnable\": "
           << (g_capture.runnable ? "true" : "false") << ",\n"
           << "  \"active_transition_id\": "
           << g_capture.active_transition_id << ",\n"
           << "  \"error\": \""
           << JsonEscape(g_capture.error_message) << "\"\n"
           << "}\n";
    std::string ignored_error;
    (void)WriteTextAtomically(
        g_capture.status_path,
        stream.str(),
        &ignored_error);
}

void MarkBrokenLocked(std::string error_message) {
    g_capture.status = "broken";
    g_capture.runnable = false;
    g_capture.error_message = std::move(error_message);
    WriteStatusLocked();
}

bool ReadCaptureSnapshot(CaptureSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return false;
    }
    *snapshot = CaptureSnapshot{};
    snapshot->loading_sealed = GetLoadingScreenSnapshot().active;
    auto& memory = ProcessMemory::Instance();
    if (g_capture.gameplay_global != 0) {
        (void)memory.TryReadValue(
            g_capture.gameplay_global,
            &snapshot->gameplay);
    }
    if (g_capture.active_region_global != 0) {
        (void)memory.TryReadValue(
            g_capture.active_region_global,
            &snapshot->active_region);
    }
    if (g_capture.region_assignment_array_global != 0) {
        std::uintptr_t assignments = 0;
        if (memory.TryReadValue(
                g_capture.region_assignment_array_global,
                &assignments) &&
            assignments != 0) {
            (void)memory.TryReadValue(
                assignments,
                &snapshot->current_region);
        }
    }
    if (snapshot->gameplay != 0) {
        (void)memory.TryReadField(
            snapshot->gameplay,
            kGameplayPendingRegionOffset,
            &snapshot->pending_region);
    }
    return true;
}

bool AppendEventLocked(
    std::uint64_t transition_id,
    std::string_view step,
    std::uintptr_t object,
    const EventDetails& details) {
    if (!g_capture.initialized || !g_capture.events.is_open() ||
        g_capture.status == "broken") {
        return false;
    }
    CaptureSnapshot snapshot;
    (void)ReadCaptureSnapshot(&snapshot);
    const auto sequence = g_capture.next_sequence++;
    const auto monotonic_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    const auto simulation_tick = GetLocalPlayerSimulationTickCount();
    const auto target_region = transition_id != 0
        ? g_capture.active_target_region
        : -1;

    g_capture.events
        << "{\"schema_version\":1"
        << ",\"sequence\":" << sequence
        << ",\"transition_id\":" << transition_id
        << ",\"monotonic_ms\":" << monotonic_ms
        << ",\"simulation_tick\":" << simulation_tick
        << ",\"process_id\":" << GetCurrentProcessId()
        << ",\"thread_id\":" << GetCurrentThreadId()
        << ",\"step\":\"" << JsonEscape(step) << "\""
        << ",\"object\":\"" << HexAddress(object) << "\""
        << ",\"native_argument\":" << details.native_argument
        << ",\"current_region\":" << snapshot.current_region
        << ",\"target_region\":" << target_region
        << ",\"pending_region\":" << snapshot.pending_region
        << ",\"gameplay\":\"" << HexAddress(snapshot.gameplay) << "\""
        << ",\"active_region\":\""
        << HexAddress(snapshot.active_region) << "\""
        << ",\"input_sealed\":"
        << (snapshot.loading_sealed ? "true" : "false");
    if (details.has_fade_values) {
        g_capture.events
            << std::setprecision(9)
            << ",\"fade_alpha_before\":" << details.alpha_before
            << ",\"fade_alpha_after\":" << details.alpha_after
            << ",\"fade_rate_before\":" << details.rate_before
            << ",\"fade_rate_after\":" << details.rate_after;
    }
    g_capture.events << "}\n";
    g_capture.events.flush();
    if (!g_capture.events) {
        MarkBrokenLocked(
            "session-flow recorder event stream stopped accepting writes");
        return false;
    }
    return true;
}

void AppendEvent(
    std::uint64_t transition_id,
    std::string_view step,
    std::uintptr_t object = 0,
    const EventDetails& details = {}) noexcept {
    try {
        std::scoped_lock lock(g_capture.mutex);
        (void)AppendEventLocked(
            transition_id,
            step,
            object,
            details);
    } catch (const std::exception& ex) {
        std::scoped_lock lock(g_capture.mutex);
        MarkBrokenLocked(
            std::string("session-flow recorder event exception: ") +
            ex.what());
    } catch (...) {
        std::scoped_lock lock(g_capture.mutex);
        MarkBrokenLocked("session-flow recorder event exception");
    }
}

std::uint64_t CurrentTransitionId() {
    if (g_thread_transition_id != 0) {
        return g_thread_transition_id;
    }
    std::scoped_lock lock(g_capture.mutex);
    return g_capture.waiting_for_unseal
        ? g_capture.active_transition_id
        : 0;
}

bool WriteGraphFile(std::string* error_message) {
    const auto* layout = TryGetBinaryLayout();
    const auto runtime_image_base = ProcessMemory::Instance().ModuleBase();
    std::ostringstream stream;
    stream << "{\n"
           << "  \"schema_version\": 1,\n"
           << "  \"capture_method\": \"injected read-only native session-flow recorder\",\n"
           << "  \"instance\": \"" << JsonEscape(g_capture.instance)
           << "\",\n"
           << "  \"binary_version\": \""
           << JsonEscape(layout != nullptr ? layout->binary_version : "")
           << "\",\n"
           << "  \"runtime_image_base\": \""
           << HexAddress(runtime_image_base) << "\",\n"
           << "  \"states\": [\n";
    for (std::size_t index = 0; index < kNativeStates.size(); ++index) {
        const auto& state = kNativeStates[index];
        const auto runtime_address = state.primary_address == 0
            ? 0
            : runtime_image_base + state.primary_address -
                kPreferredImageBase;
        stream << "    {\"state\":\"" << JsonEscape(state.state)
               << "\",\"native_identifier\":\""
               << JsonEscape(state.native_identifier)
               << "\",\"native_region_id\":"
               << state.native_region_id
               << ",\"preferred_address\":\""
               << HexAddress(state.primary_address)
               << "\",\"runtime_address\":\""
               << HexAddress(runtime_address)
               << "\",\"vtable_address\":\""
               << HexAddress(state.vtable_address) << "\"}"
               << (index + 1 == kNativeStates.size() ? "\n" : ",\n");
    }
    stream << "  ],\n  \"edges\": [\n";
    for (std::size_t index = 0; index < kNativeEdges.size(); ++index) {
        const auto& edge = kNativeEdges[index];
        stream << "    {\"state\":\"" << JsonEscape(edge.state)
               << "\",\"edge\":\"" << JsonEscape(edge.edge)
               << "\",\"trigger\":\"" << JsonEscape(edge.trigger)
               << "\",\"destination\":\""
               << JsonEscape(edge.destination) << "\"}"
               << (index + 1 == kNativeEdges.size() ? "\n" : ",\n");
    }
    stream << "  ],\n"
           << "  \"illegal_edge_classes\": [\n"
           << "    \"private region to different private region\",\n"
           << "    \"private region directly to Arena\",\n"
           << "    \"ordinary Arena switch to a fixed region\",\n"
           << "    \"same-region request is a no-op, not an edge\",\n"
           << "    \"target -1 is a detach transient, not a stable state\",\n"
           << "    \"target outside 0..5 is unchecked native memory access\",\n"
           << "    \"post-run Mortuary directly to Courtyard bypasses stock front end\",\n"
           << "    \"multiplayer client to Arena without authenticated host intent\"\n"
           << "  ]\n"
           << "}\n";
    return WriteTextAtomically(
        g_capture.graph_path,
        stream.str(),
        error_message);
}

bool ResolveLayoutAddress(
    const char* key,
    std::uintptr_t* resolved,
    std::string* error_message) {
    std::uintptr_t preferred = 0;
    if (key == nullptr || resolved == nullptr ||
        !TryGetBinaryLayoutNumericValue(
            kLayoutSection,
            key,
            &preferred) ||
        preferred == 0) {
        if (error_message != nullptr) {
            *error_message = std::string(
                "session-flow recorder layout is missing ") +
                (key != nullptr ? key : "an unnamed key");
        }
        return false;
    }
    *resolved =
        ProcessMemory::Instance().ResolveGameAddressOrZero(preferred);
    if (*resolved == 0) {
        if (error_message != nullptr) {
            *error_message = std::string(
                "session-flow recorder could not resolve ") + key;
        }
        return false;
    }
    return true;
}

void RemoveCaptureHooks() {
    for (auto& hook : g_capture.hooks) {
        RemoveX86Hook(&hook);
    }
}
