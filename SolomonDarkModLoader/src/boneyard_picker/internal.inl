constexpr char kPlaceholderDrawOwner[] = "__loader.boneyard_picker";
constexpr std::size_t kVisiblePlaceholderRows = 14;
constexpr std::uint64_t kMissingResolutionRetryMs = 1000;
constexpr std::uint64_t kPeerResolutionRefreshMs = 250;
constexpr std::size_t kMapPickerStartHookMinimumPatchSize = 5;

using MapPickerStartFn = void(__thiscall*)(void* courtyard);
using NativeStringAssignFn = void(__thiscall*)(void* self, char* text);

enum class PendingFrontendEvent {
    None,
    Pick,
    Cancel,
};

struct RemoteResolution {
    BoneyardPickerPacketState packet;
};

struct BoneyardPickerState {
    bool initialized = false;
    bool picker_open = false;
    bool native_launch_dispatched = false;
    std::shared_ptr<const BoneyardPickerCatalog> catalog;
    std::unordered_map<std::string, std::size_t> entry_by_digest;
    BoneyardPickerPhase phase = BoneyardPickerPhase::Closed;
    std::size_t selected_index = kBoneyardPickerNoSelection;
    std::size_t placeholder_cursor = 0;
    std::uint32_t selection_revision = 0;
    BoneyardPickerDigest selected_digest{};
    BoneyardResolutionStatus local_resolution =
        BoneyardResolutionStatus::None;
    std::unordered_map<std::uint64_t, RemoteResolution> remote_resolutions;
    std::vector<std::uint64_t> missing_participant_ids;
    std::string error_message;
    bool peer_resolution_error_active = false;
    std::string applied_stock_relative_path;
    uintptr_t courtyard_address = 0;
    std::uint64_t next_resolution_retry_ms = 0;
    std::uint64_t next_peer_resolution_refresh_ms = 0;
    PendingFrontendEvent pending_event = PendingFrontendEvent::None;
    std::size_t pending_selection_index = kBoneyardPickerNoSelection;
    X86Hook start_hook;
    std::mutex mutex;
};

BoneyardPickerState g_picker;

bool IsZeroDigest(const BoneyardPickerDigest& digest) {
    return std::all_of(
        digest.begin(),
        digest.end(),
        [](std::uint8_t value) { return value == 0; });
}

char HexDigit(std::uint8_t value) {
    return static_cast<char>(value < 10 ? '0' + value : 'a' + value - 10);
}

std::string DigestToHex(const BoneyardPickerDigest& digest) {
    if (IsZeroDigest(digest)) {
        return {};
    }
    std::string text;
    text.resize(digest.size() * 2);
    for (std::size_t index = 0; index < digest.size(); ++index) {
        text[index * 2] = HexDigit(static_cast<std::uint8_t>(digest[index] >> 4));
        text[index * 2 + 1] = HexDigit(static_cast<std::uint8_t>(digest[index] & 0x0f));
    }
    return text;
}

int HexValue(char value) {
    if (value >= '0' && value <= '9') {
        return value - '0';
    }
    value = static_cast<char>(std::tolower(static_cast<unsigned char>(value)));
    return value >= 'a' && value <= 'f' ? value - 'a' + 10 : -1;
}

bool TryParseDigest(
    const std::string& text,
    BoneyardPickerDigest* digest) {
    if (digest == nullptr || text.size() != digest->size() * 2) {
        return false;
    }
    digest->fill(0);
    for (std::size_t index = 0; index < digest->size(); ++index) {
        const auto high = HexValue(text[index * 2]);
        const auto low = HexValue(text[index * 2 + 1]);
        if (high < 0 || low < 0) {
            digest->fill(0);
            return false;
        }
        (*digest)[index] = static_cast<std::uint8_t>((high << 4) | low);
    }
    return !IsZeroDigest(*digest);
}

std::uint32_t NextRevision(std::uint32_t revision) {
    ++revision;
    return revision == 0 ? 1 : revision;
}

bool IsRevisionNewer(std::uint32_t candidate, std::uint32_t baseline) {
    return candidate != baseline &&
        static_cast<std::uint32_t>(candidate - baseline) < 0x80000000u;
}

const BoneyardPickerEntry* SelectedEntryLocked() {
    if (g_picker.catalog == nullptr ||
        g_picker.selected_index >= g_picker.catalog->entries.size()) {
        return nullptr;
    }
    return &g_picker.catalog->entries[g_picker.selected_index];
}

bool TryReadCourtyardAddress(uintptr_t* courtyard_address) {
    if (courtyard_address == nullptr) {
        return false;
    }
    *courtyard_address = 0;
    auto& memory = ProcessMemory::Instance();
    const auto global_address =
        memory.ResolveGameAddressOrZero(kHubCourtyardGlobal);
    return global_address != 0 &&
        memory.TryReadValue(global_address, courtyard_address) &&
        *courtyard_address != 0;
}

bool TryReadGameplayAddress(uintptr_t* gameplay_address) {
    if (gameplay_address == nullptr) {
        return false;
    }
    *gameplay_address = 0;
    auto& memory = ProcessMemory::Instance();
    const auto global_address =
        memory.ResolveGameAddressOrZero(kGameObjectGlobal);
    return global_address != 0 &&
        memory.TryReadValue(global_address, gameplay_address) &&
        *gameplay_address != 0;
}

bool CallNativeSelectionHandoff(
    NativeStringAssignFn string_assign,
    MapPickerStartFn original_start,
    uintptr_t gameplay_address,
    std::size_t selected_string_offset,
    uintptr_t courtyard_address,
    char* resolved_boneyard_path,
    DWORD* out_exception_code) {
    if (out_exception_code != nullptr) {
        *out_exception_code = 0;
    }
    __try {
        string_assign(
            reinterpret_cast<void*>(gameplay_address + selected_string_offset),
            resolved_boneyard_path);
        original_start(reinterpret_cast<void*>(courtyard_address));
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        if (out_exception_code != nullptr) {
            *out_exception_code = GetExceptionCode();
        }
        return false;
    }
}

bool ApplyStockSelectionAndOpenNativePicker(
    const BoneyardPickerEntry* selection,
    uintptr_t preferred_courtyard,
    bool clear_selection,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    auto& memory = ProcessMemory::Instance();
    const auto assign_address =
        memory.ResolveGameAddressOrZero(kGameplayStringAssign);
    const auto original_start =
        GetX86HookTrampoline<MapPickerStartFn>(g_picker.start_hook);
    uintptr_t gameplay_address = 0;
    uintptr_t courtyard_address = preferred_courtyard;
    if (assign_address == 0 || original_start == nullptr ||
        kGameplaySelectedBoneyardOffset == 0 ||
        !TryReadGameplayAddress(&gameplay_address) ||
        gameplay_address == 0 ||
        (courtyard_address == 0 &&
         !TryReadCourtyardAddress(&courtyard_address))) {
        if (error_message != nullptr) {
            *error_message =
                "The stock MapPicker selection boundary is not available in the current hub.";
        }
        return false;
    }

    std::string resolved_path;
    if (!clear_selection) {
        if (selection == nullptr) {
            if (error_message != nullptr) {
                *error_message = "The selected Boneyard catalog entry disappeared.";
            }
            return false;
        }
        resolved_path = selection->stage_path.string();
        std::replace(
            resolved_path.begin(),
            resolved_path.end(),
            '/',
            '\\');
    }

    DWORD exception_code = 0;
    if (!CallNativeSelectionHandoff(
            reinterpret_cast<NativeStringAssignFn>(assign_address),
            original_start,
            gameplay_address,
            kGameplaySelectedBoneyardOffset,
            courtyard_address,
            resolved_path.data(),
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "The stock MapPicker selection handoff raised exception " +
                HexString(exception_code) + ".";
        }
        return false;
    }
    return true;
}

void ClearAuthoritativeSelectionLocked() {
    if (!IsZeroDigest(g_picker.selected_digest) ||
        g_picker.selection_revision != 0) {
        g_picker.selection_revision =
            NextRevision(g_picker.selection_revision);
    }
    g_picker.selected_digest.fill(0);
    g_picker.selected_index = kBoneyardPickerNoSelection;
    g_picker.local_resolution = BoneyardResolutionStatus::None;
    g_picker.native_launch_dispatched = false;
    g_picker.remote_resolutions.clear();
    g_picker.missing_participant_ids.clear();
    g_picker.error_message.clear();
    g_picker.peer_resolution_error_active = false;
    g_picker.applied_stock_relative_path.clear();
    g_picker.next_peer_resolution_refresh_ms = 0;
    g_picker.pending_selection_index = kBoneyardPickerNoSelection;
}

bool OpenPickerLocked(
    uintptr_t courtyard_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_picker.initialized || g_picker.catalog == nullptr ||
        g_picker.catalog->entries.empty()) {
        if (error_message != nullptr) {
            *error_message = "No staged Boneyards are available.";
        }
        return false;
    }
    if (!multiplayer::IsLocalTransportHost()) {
        if (error_message != nullptr) {
            *error_message =
                "Only the multiplayer host can open the Boneyard picker.";
        }
        return false;
    }
    if (g_picker.picker_open) {
        return true;
    }

    ClearAuthoritativeSelectionLocked();
    g_picker.picker_open = true;
    g_picker.phase = BoneyardPickerPhase::Choosing;
    g_picker.placeholder_cursor = 0;
    g_picker.courtyard_address = courtyard_address;
    g_picker.pending_event = PendingFrontendEvent::None;
    g_picker.pending_selection_index = kBoneyardPickerNoSelection;
    Log(
        "Boneyard picker opened. entries=" +
        std::to_string(g_picker.catalog->entries.size()));
    return true;
}

void __fastcall HookMapPickerStart(
    void* courtyard,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<MapPickerStartFn>(g_picker.start_hook);
    if (original == nullptr) {
        return;
    }
    if (!ShouldHijackHostBoneyardStart()) {
        original(courtyard);
        return;
    }

    std::scoped_lock lock(g_picker.mutex);
    if (g_picker.picker_open) {
        g_picker.pending_event = PendingFrontendEvent::Cancel;
        return;
    }
    std::string ignored_error;
    if (!OpenPickerLocked(
            reinterpret_cast<uintptr_t>(courtyard),
            &ignored_error)) {
        original(courtyard);
    }
}

LuaDrawCommand MakeRectangle(
    LuaDrawCommandKind kind,
    float x,
    float y,
    float width,
    float height,
    LuaDrawColor color,
    float thickness = 1.0f) {
    LuaDrawCommand command;
    command.kind = kind;
    command.x = x;
    command.y = y;
    command.width = width;
    command.height = height;
    command.color = color;
    command.thickness = thickness;
    return command;
}

LuaDrawCommand MakeText(
    float x,
    float y,
    std::string text,
    LuaDrawColor color,
    float scale = 0.8f) {
    LuaDrawCommand command;
    command.kind = LuaDrawCommandKind::Text;
    command.x = x;
    command.y = y;
    command.text = std::move(text);
    command.color = color;
    command.scale = scale;
    return command;
}

void SubmitPlaceholderCommand(LuaDrawCommand command) {
    std::string ignored_error;
    (void)SubmitLuaDrawCommand(
        kPlaceholderDrawOwner,
        std::move(command),
        &ignored_error);
}

void RenderPlaceholder(const BoneyardPickerSnapshot& snapshot) {
    if (!IsLuaDrawRuntimeInitialized() ||
        (!snapshot.is_open && snapshot.error_message.empty())) {
        ClearLuaDrawFrameForMod(kPlaceholderDrawOwner);
        return;
    }

    std::uint32_t viewport_width = 1280;
    std::uint32_t viewport_height = 720;
    std::string ignored_error;
    (void)TryGetLuaDrawViewport(
        &viewport_width,
        &viewport_height,
        &ignored_error);
    const float panel_width = (std::min)(
        860.0f,
        static_cast<float>(viewport_width) - 48.0f);
    const float panel_height = (std::min)(
        520.0f,
        static_cast<float>(viewport_height) - 48.0f);
    const float panel_x =
        (static_cast<float>(viewport_width) - panel_width) * 0.5f;
    const float panel_y =
        (static_cast<float>(viewport_height) - panel_height) * 0.5f;

    BeginLuaDrawFrame(kPlaceholderDrawOwner);
    SubmitPlaceholderCommand(MakeRectangle(
        LuaDrawCommandKind::FilledRect,
        panel_x,
        panel_y,
        panel_width,
        panel_height,
        LuaDrawColor{8, 10, 16, 238}));
    SubmitPlaceholderCommand(MakeRectangle(
        LuaDrawCommandKind::OutlinedRect,
        panel_x,
        panel_y,
        panel_width,
        panel_height,
        LuaDrawColor{220, 184, 92, 255},
        2.0f));
    SubmitPlaceholderCommand(MakeText(
        panel_x + 18.0f,
        panel_y + 16.0f,
        "Boneyard Picker (functional placeholder)",
        LuaDrawColor{248, 220, 150, 255},
        1.0f));

    if (snapshot.catalog != nullptr && !snapshot.catalog->entries.empty()) {
        std::size_t cursor = 0;
        {
            std::scoped_lock lock(g_picker.mutex);
            cursor = (std::min)(
                g_picker.placeholder_cursor,
                snapshot.catalog->entries.size() - 1);
        }
        const auto first = cursor >= kVisiblePlaceholderRows
            ? cursor - kVisiblePlaceholderRows + 1
            : 0;
        const auto last = (std::min)(
            first + kVisiblePlaceholderRows,
            snapshot.catalog->entries.size());
        float row_y = panel_y + 58.0f;
        for (std::size_t index = first; index < last; ++index) {
            const auto& entry = snapshot.catalog->entries[index];
            const bool selected = index == cursor;
            if (selected) {
                SubmitPlaceholderCommand(MakeRectangle(
                    LuaDrawCommandKind::FilledRect,
                    panel_x + 14.0f,
                    row_y - 3.0f,
                    panel_width - 28.0f,
                    24.0f,
                    LuaDrawColor{86, 67, 31, 230}));
            }
            SubmitPlaceholderCommand(MakeText(
                panel_x + 24.0f,
                row_y,
                (selected ? "> " : "  ") + entry.display_name +
                    "  [" + entry.source_mod_name + "]",
                selected
                    ? LuaDrawColor{255, 238, 180, 255}
                    : LuaDrawColor{225, 225, 225, 255}));
            row_y += 27.0f;
        }
    }

    std::string footer;
    if (!snapshot.error_message.empty()) {
        footer = "ERROR: " + snapshot.error_message;
    } else if (snapshot.phase == BoneyardPickerPhase::WaitingForPeers) {
        footer = "Waiting for every connected player to resolve the selected Boneyard...";
    } else if (snapshot.phase == BoneyardPickerPhase::Launching) {
        footer = "Launching the selected Boneyard through the stock MapPicker path...";
    } else {
        footer = "Up/Down or Page Up/Page Down - Enter pick - Escape stock picker";
    }
    SubmitPlaceholderCommand(MakeText(
        panel_x + 18.0f,
        panel_y + panel_height - 34.0f,
        std::move(footer),
        snapshot.error_message.empty()
            ? LuaDrawColor{190, 205, 220, 255}
            : LuaDrawColor{255, 116, 116, 255},
        0.75f));
    CommitLuaDrawFrame(kPlaceholderDrawOwner);
}

void MovePlaceholderCursor(int delta) {
    std::scoped_lock lock(g_picker.mutex);
    if (!g_picker.picker_open || g_picker.catalog == nullptr ||
        g_picker.catalog->entries.empty()) {
        return;
    }
    const auto count = g_picker.catalog->entries.size();
    if (delta < 0) {
        const auto magnitude = static_cast<std::size_t>(-delta);
        g_picker.placeholder_cursor =
            magnitude > g_picker.placeholder_cursor
                ? 0
                : g_picker.placeholder_cursor - magnitude;
    } else {
        g_picker.placeholder_cursor = (std::min)(
            count - 1,
            g_picker.placeholder_cursor + static_cast<std::size_t>(delta));
    }
}

void ProcessPlaceholderInput() {
    bool accepts_input = false;
    std::size_t cursor = 0;
    {
        std::scoped_lock lock(g_picker.mutex);
        accepts_input =
            g_picker.picker_open && multiplayer::IsLocalTransportHost();
        cursor = g_picker.placeholder_cursor;
    }
    if (!accepts_input) {
        return;
    }
    if ((GetAsyncKeyState(VK_UP) & 1) != 0) {
        MovePlaceholderCursor(-1);
    }
    if ((GetAsyncKeyState(VK_DOWN) & 1) != 0) {
        MovePlaceholderCursor(1);
    }
    if ((GetAsyncKeyState(VK_PRIOR) & 1) != 0) {
        MovePlaceholderCursor(-static_cast<int>(kVisiblePlaceholderRows));
    }
    if ((GetAsyncKeyState(VK_NEXT) & 1) != 0) {
        MovePlaceholderCursor(static_cast<int>(kVisiblePlaceholderRows));
    }
    if ((GetAsyncKeyState(VK_RETURN) & 1) != 0) {
        {
            std::scoped_lock lock(g_picker.mutex);
            cursor = g_picker.placeholder_cursor;
        }
        std::string ignored_error;
        (void)PickBoneyard(cursor, &ignored_error);
    }
    if ((GetAsyncKeyState(VK_ESCAPE) & 1) != 0) {
        std::string ignored_error;
        (void)CancelBoneyardPicker(&ignored_error);
    }
}

bool EvaluateHostReadinessLocked(
    const multiplayer::RuntimeState& runtime) {
    g_picker.missing_participant_ids.clear();
    if (g_picker.local_resolution != BoneyardResolutionStatus::Ready) {
        return false;
    }

    bool waiting = false;
    for (const auto& participant : runtime.participants) {
        if (!multiplayer::IsRemoteParticipant(participant) ||
            !multiplayer::IsNativeControlledParticipant(participant) ||
            !participant.transport_connected) {
            continue;
        }
        const auto found =
            g_picker.remote_resolutions.find(participant.participant_id);
        if (found == g_picker.remote_resolutions.end() ||
            found->second.packet.revision != g_picker.selection_revision ||
            found->second.packet.digest != g_picker.selected_digest) {
            waiting = true;
            continue;
        }
        if (found->second.packet.resolution ==
            BoneyardResolutionStatus::Missing) {
            g_picker.missing_participant_ids.push_back(
                participant.participant_id);
        } else if (found->second.packet.resolution !=
                   BoneyardResolutionStatus::Ready) {
            waiting = true;
        }
    }

    if (!g_picker.missing_participant_ids.empty()) {
        std::ostringstream message;
        message << "Selected Boneyard is missing for player";
        if (g_picker.missing_participant_ids.size() != 1) {
            message << 's';
        }
        message << ' ';
        for (std::size_t index = 0;
             index < g_picker.missing_participant_ids.size();
             ++index) {
            if (index != 0) {
                message << ", ";
            }
            message << g_picker.missing_participant_ids[index];
        }
        const bool launch_pending =
            g_picker.picker_open && !g_picker.native_launch_dispatched;
        message << (launch_pending
            ? ". The run was not launched."
            : ". Affected players cannot enter the active run.");
        const auto peer_error = message.str();
        if (!g_picker.peer_resolution_error_active ||
            g_picker.error_message != peer_error) {
            Log(
                "Boneyard picker host peer-resolution error. revision=" +
                std::to_string(g_picker.selection_revision) +
                " sha256=" + DigestToHex(g_picker.selected_digest) +
                " error=" + peer_error);
        }
        g_picker.error_message = peer_error;
        g_picker.peer_resolution_error_active = true;
        g_picker.phase = BoneyardPickerPhase::Error;
        return false;
    }
    if (g_picker.peer_resolution_error_active) {
        Log(
            "Boneyard picker host peer resolution recovered. revision=" +
            std::to_string(g_picker.selection_revision) +
            " sha256=" + DigestToHex(g_picker.selected_digest));
        g_picker.peer_resolution_error_active = false;
        g_picker.error_message.clear();
        g_picker.phase = g_picker.native_launch_dispatched
            ? BoneyardPickerPhase::Launching
            : BoneyardPickerPhase::WaitingForPeers;
    }
    if (waiting) {
        if (g_picker.picker_open && !g_picker.native_launch_dispatched &&
            g_picker.error_message.empty()) {
            g_picker.phase = BoneyardPickerPhase::WaitingForPeers;
        }
        return false;
    }
    return true;
}
