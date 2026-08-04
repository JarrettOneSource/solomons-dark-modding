BoneyardPickerSnapshot GetBoneyardPickerSnapshot();
void RenderBoneyardPickerAfterStockHud();

void __fastcall HookGameplayHudRender(
    void* gameplay,
    void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<GameplayHudRenderFn>(
        g_picker.render_hook);
    if (original == nullptr) {
        return;
    }
    original(gameplay);
    RenderBoneyardPickerAfterStockHud();
}

bool InstallBoneyardAuthorityHooks(
    uintptr_t start_target,
    uintptr_t start_affordance_render_target,
    std::string* error_message) {
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(start_target),
            reinterpret_cast<void*>(&HookMapPickerStart),
            kMapPickerStartHookMinimumPatchSize,
            &g_picker.start_hook,
            error_message)) {
        return false;
    }
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(start_affordance_render_target),
            reinterpret_cast<void*>(&HookCourtyardStartAffordanceRender),
            kCourtyardStartAffordanceRenderHookMinimumPatchSize,
            &g_picker.start_affordance_render_hook,
            error_message)) {
        RemoveX86Hook(&g_picker.start_hook);
        return false;
    }
    return true;
}

BoneyardPickerSnapshot GetBoneyardPickerSnapshot() {
    std::scoped_lock lock(g_picker.mutex);
    BoneyardPickerSnapshot snapshot;
    snapshot.phase = g_picker.phase;
    snapshot.is_open = g_picker.picker_open;
    snapshot.catalog = g_picker.catalog;
    snapshot.selected_index = g_picker.selected_index;
    snapshot.selection_revision = g_picker.selection_revision;
    snapshot.selected_content_sha256 =
        DigestToHex(g_picker.selected_digest);
    snapshot.local_resolution = g_picker.local_resolution;
    snapshot.missing_participant_ids =
        g_picker.missing_participant_ids;
    snapshot.error_message = g_picker.error_message;
    snapshot.applied_stock_relative_path =
        g_picker.applied_stock_relative_path;
    return snapshot;
}

bool PickBoneyard(
    std::size_t index,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    std::scoped_lock lock(g_picker.mutex);
    if (!g_picker.initialized || !g_picker.picker_open ||
        !HasBoneyardAuthority()) {
        if (error_message != nullptr) {
            *error_message = "The host Boneyard picker is not open.";
        }
        return false;
    }
    if (g_picker.catalog == nullptr ||
        index >= g_picker.catalog->entries.size()) {
        if (error_message != nullptr) {
            *error_message = "Boneyard picker index is out of range.";
        }
        return false;
    }

    g_picker.cursor_index = index;
    g_picker.pending_selection_index = index;
    g_picker.pending_event = PendingFrontendEvent::Pick;
    return true;
}

bool CancelBoneyardPicker(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    std::scoped_lock lock(g_picker.mutex);
    if (!g_picker.initialized || !g_picker.picker_open ||
        !HasBoneyardAuthority()) {
        if (error_message != nullptr) {
            *error_message = "The host Boneyard picker is not open.";
        }
        return false;
    }
    g_picker.pending_event = PendingFrontendEvent::Cancel;
    g_picker.pending_selection_index = kBoneyardPickerNoSelection;
    return true;
}

bool InitializeBoneyardPicker(
    const RuntimeBootstrap& bootstrap,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    auto catalog = std::make_shared<BoneyardPickerCatalog>();
    catalog->entries.reserve(bootstrap.boneyards.size());
    std::unordered_map<std::string, std::size_t> entry_by_digest;
    for (const auto& descriptor : bootstrap.boneyards) {
        BoneyardPickerEntry entry;
        entry.display_name = descriptor.display_name;
        entry.source_mod_id = descriptor.source_mod_id;
        entry.source_mod_name = descriptor.source_mod_name;
        entry.source_mod_version = descriptor.source_mod_version;
        entry.source_mod_description = descriptor.source_mod_description;
        entry.updated_utc = descriptor.updated_utc;
        entry.filename = descriptor.filename;
        entry.source_relative_path = descriptor.source_relative_path;
        entry.content_sha256 = descriptor.content_sha256;
        if (!TryParseDigest(entry.content_sha256, &entry.content_digest)) {
            if (error_message != nullptr) {
                *error_message =
                    "Runtime bootstrap contains an invalid Boneyard SHA-256: " +
                    entry.content_sha256;
            }
            return false;
        }
        entry.stock_relative_path =
            descriptor.stock_relative_path.generic_string();
        entry.stage_path = descriptor.stage_path;
        entry.preview.file_length = descriptor.file_length;
        entry.preview.chunk_count = descriptor.chunk_count;
        entry.preview.named_buffer_count = descriptor.named_buffer_count;
        entry.preview.max_depth = descriptor.max_depth;
        if (entry.display_name.empty() || entry.source_mod_id.empty() ||
            entry.filename.empty() || entry.stock_relative_path.empty() ||
            entry.stage_path.empty() || entry.preview.file_length == 0) {
            if (error_message != nullptr) {
                *error_message =
                    "Runtime bootstrap contains an incomplete Boneyard picker entry.";
            }
            return false;
        }
        const auto index = catalog->entries.size();
        entry_by_digest.try_emplace(entry.content_sha256, index);
        catalog->entries.push_back(std::move(entry));
    }

    const bool has_custom_entries = !catalog->entries.empty();
    if (!InitializeGameplaySeams(error_message)) {
        return false;
    }
    const auto start_target = ProcessMemory::Instance().ResolveGameAddressOrZero(
        kMapPickerStart);
    const auto start_affordance_render_target =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kCourtyardStartAffordanceRender);
    const auto render_target = has_custom_entries
        ? ProcessMemory::Instance().ResolveGameAddressOrZero(
              kGameplayHudRender)
        : 0;
    if (start_target == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the stock MapPicker start path.";
        }
        return false;
    }
    if (start_affordance_render_target == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Unable to resolve the Courtyard start-affordance render path.";
        }
        return false;
    }
    if (has_custom_entries && render_target == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Unable to resolve the complete gameplay HUD render path.";
        }
        return false;
    }

    std::scoped_lock lock(g_picker.mutex);
    if (g_picker.initialized) {
        return true;
    }
    if (!InstallBoneyardAuthorityHooks(
            start_target,
            start_affordance_render_target,
            error_message)) {
        return false;
    }
    if (has_custom_entries && !InstallSafeX86Hook(
            reinterpret_cast<void*>(render_target),
            reinterpret_cast<void*>(&HookGameplayHudRender),
            kGameplayHudRenderHookMinimumPatchSize,
            &g_picker.render_hook,
            error_message)) {
        RemoveX86Hook(&g_picker.start_affordance_render_hook);
        RemoveX86Hook(&g_picker.start_hook);
        return false;
    }
    g_picker.catalog = std::move(catalog);
    g_picker.entry_by_digest = std::move(entry_by_digest);
    g_picker.phase = BoneyardPickerPhase::Closed;
    g_picker.initialized = true;
    if (!has_custom_entries) {
        Log(
            "Boneyard picker provider initialized. authority_hooks=enabled "
            "custom_hook=disabled entries=0");
        return true;
    }
    Log(
        "Boneyard picker provider initialized. start_hook=" +
        HexString(start_target) +
        " start_affordance_render_hook=" +
        HexString(start_affordance_render_target) +
        " custom_render_hook=" + HexString(render_target) +
        " entries=" + std::to_string(g_picker.catalog->entries.size()));
    return true;
}

void ShutdownBoneyardPicker() {
    RemoveX86Hook(&g_picker.render_hook);
    RemoveX86Hook(&g_picker.start_affordance_render_hook);
    RemoveX86Hook(&g_picker.start_hook);
    std::scoped_lock lock(g_picker.mutex);
    g_picker.initialized = false;
    g_picker.picker_open = false;
    g_picker.native_launch_dispatched = false;
    g_picker.catalog.reset();
    g_picker.entry_by_digest.clear();
    g_picker.phase = BoneyardPickerPhase::Closed;
    g_picker.selected_index = kBoneyardPickerNoSelection;
    g_picker.cursor_index = 0;
    g_picker.selection_revision = 0;
    g_picker.selected_digest.fill(0);
    g_picker.local_resolution = BoneyardResolutionStatus::None;
    g_picker.remote_resolutions.clear();
    g_picker.missing_participant_ids.clear();
    g_picker.error_message.clear();
    g_picker.peer_resolution_error_active = false;
    g_picker.applied_stock_relative_path.clear();
    g_picker.courtyard_address = 0;
    g_picker.next_resolution_retry_ms = 0;
    g_picker.next_peer_resolution_refresh_ms = 0;
    g_picker.pending_event = PendingFrontendEvent::None;
    g_picker.pending_selection_index = kBoneyardPickerNoSelection;
}

void PumpBoneyardPickerOnGameThread() {
    ProcessPickerInput();

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    bool refresh_host_resolutions = false;
    {
        std::scoped_lock lock(g_picker.mutex);
        if (g_picker.initialized &&
            HasBoneyardAuthority() &&
            !IsZeroDigest(g_picker.selected_digest) &&
            now_ms >= g_picker.next_peer_resolution_refresh_ms) {
            refresh_host_resolutions = true;
            g_picker.next_peer_resolution_refresh_ms =
                now_ms + kPeerResolutionRefreshMs;
        }
    }
    multiplayer::RuntimeState host_runtime;
    if (refresh_host_resolutions) {
        host_runtime = multiplayer::SnapshotRuntimeState();
    }

    BoneyardPickerEntry dispatch_entry;
    uintptr_t dispatch_courtyard = 0;
    bool dispatch_selection = false;
    bool dispatch_cancel = false;
    {
        std::scoped_lock lock(g_picker.mutex);
        if (!g_picker.initialized) {
            return;
        }
        if (g_picker.local_resolution ==
                BoneyardResolutionStatus::Missing &&
            now_ms >= g_picker.next_resolution_retry_ms) {
            ResolveSelectedEntryLocked(now_ms);
        }

        const bool host_ready = refresh_host_resolutions &&
            EvaluateHostReadinessLocked(host_runtime);
        if (g_picker.pending_event == PendingFrontendEvent::Pick) {
            const auto index = g_picker.pending_selection_index;
            g_picker.pending_event = PendingFrontendEvent::None;
            g_picker.pending_selection_index =
                kBoneyardPickerNoSelection;
            ApplyPendingPickLocked(index, now_ms);
        } else if (g_picker.pending_event == PendingFrontendEvent::Cancel) {
            g_picker.pending_event = PendingFrontendEvent::None;
            dispatch_cancel = true;
            dispatch_courtyard = g_picker.courtyard_address;
            g_picker.picker_open = false;
            ClearAuthoritativeSelectionLocked();
            g_picker.phase = BoneyardPickerPhase::Closed;
        } else if (g_picker.picker_open &&
                   HasBoneyardAuthority() &&
                   !IsZeroDigest(g_picker.selected_digest) &&
                   !g_picker.native_launch_dispatched &&
                   host_ready) {
            const auto* selected_entry = SelectedEntryLocked();
            dispatch_courtyard = g_picker.courtyard_address;
            std::string resolution_error;
            dispatch_selection = selected_entry != nullptr &&
                ResolveEntryFile(*selected_entry, &resolution_error);
            if (dispatch_selection) {
                dispatch_entry = *selected_entry;
            } else {
                g_picker.local_resolution = BoneyardResolutionStatus::Missing;
                g_picker.error_message = resolution_error.empty()
                    ? "The selected Boneyard catalog entry disappeared."
                    : std::move(resolution_error);
                g_picker.next_resolution_retry_ms = now_ms +
                    kMissingResolutionRetryMs;
            }
            g_picker.native_launch_dispatched = dispatch_selection;
            g_picker.picker_open = !dispatch_selection;
            g_picker.phase = dispatch_selection
                ? BoneyardPickerPhase::Launching
                : BoneyardPickerPhase::Error;
        }
    }

    if (dispatch_cancel) {
        std::string cancel_error;
        if (!ApplyStockSelectionAndOpenNativePicker(
                nullptr,
                dispatch_courtyard,
                true,
                &cancel_error)) {
            std::scoped_lock lock(g_picker.mutex);
            g_picker.phase = BoneyardPickerPhase::Error;
            g_picker.error_message = std::move(cancel_error);
        } else {
            Log("Boneyard picker canceled; stock MapPicker flow resumed.");
        }
    } else if (dispatch_selection) {
        std::string launch_error;
        if (!ApplyStockSelectionAndOpenNativePicker(
                &dispatch_entry,
                dispatch_courtyard,
                false,
                &launch_error)) {
            std::scoped_lock lock(g_picker.mutex);
            g_picker.picker_open = true;
            g_picker.native_launch_dispatched = false;
            g_picker.phase = BoneyardPickerPhase::Error;
            g_picker.error_message = std::move(launch_error);
        } else {
            std::scoped_lock lock(g_picker.mutex);
            g_picker.applied_stock_relative_path =
                dispatch_entry.stock_relative_path;
            Log(
                "Boneyard picker host stock handoff completed. revision=" +
                std::to_string(g_picker.selection_revision) +
                " sha256=" + dispatch_entry.content_sha256 +
                " stock_path=" + dispatch_entry.stock_relative_path);
        }
    }
}

void RenderBoneyardPickerAfterStockHud() {
    RenderBoneyardPickerUi(GetBoneyardPickerSnapshot());
}

bool ShouldHijackHostBoneyardStart() {
    if (!HasBoneyardAuthority()) {
        return false;
    }
    std::scoped_lock lock(g_picker.mutex);
    return g_picker.initialized && g_picker.catalog != nullptr &&
        !g_picker.catalog->entries.empty();
}

bool OpenHostBoneyardPicker(std::string* error_message) {
    std::scoped_lock lock(g_picker.mutex);
    return OpenPickerLocked(0, error_message);
}

bool TryDispatchAuthoritativeBoneyardRunOnGameThread(
    bool* handled,
    std::string* error_message) {
    if (handled != nullptr) {
        *handled = false;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!multiplayer::IsLocalTransportClient()) {
        return true;
    }

    BoneyardPickerEntry entry;
    {
        std::scoped_lock lock(g_picker.mutex);
        if (!g_picker.initialized || IsZeroDigest(g_picker.selected_digest)) {
            return true;
        }
        if (handled != nullptr) {
            *handled = true;
        }
        if (g_picker.local_resolution !=
            BoneyardResolutionStatus::Ready) {
            if (error_message != nullptr) {
                *error_message = g_picker.error_message.empty()
                    ? "The authoritative Boneyard is not ready on this client."
                    : g_picker.error_message;
            }
            return false;
        }
        if (g_picker.native_launch_dispatched) {
            return true;
        }
        const auto* selected_entry = SelectedEntryLocked();
        if (selected_entry == nullptr) {
            if (error_message != nullptr) {
                *error_message =
                    "The authoritative Boneyard catalog entry disappeared.";
            }
            return false;
        }
        std::string resolution_error;
        if (!ResolveEntryFile(*selected_entry, &resolution_error)) {
            g_picker.local_resolution = BoneyardResolutionStatus::Missing;
            g_picker.phase = BoneyardPickerPhase::Error;
            g_picker.error_message = resolution_error;
            g_picker.next_resolution_retry_ms =
                static_cast<std::uint64_t>(GetTickCount64()) +
                kMissingResolutionRetryMs;
            if (error_message != nullptr) {
                *error_message = std::move(resolution_error);
            }
            return false;
        }
        entry = *selected_entry;
        g_picker.native_launch_dispatched = true;
        g_picker.phase = BoneyardPickerPhase::Launching;
    }

    std::string launch_error;
    if (!ApplyStockSelectionAndOpenNativePicker(
            &entry,
            0,
            false,
            &launch_error)) {
        std::scoped_lock lock(g_picker.mutex);
        g_picker.native_launch_dispatched = false;
        g_picker.phase = BoneyardPickerPhase::Error;
        g_picker.error_message = launch_error;
        if (error_message != nullptr) {
            *error_message = std::move(launch_error);
        }
        return false;
    }

    {
        std::scoped_lock lock(g_picker.mutex);
        g_picker.applied_stock_relative_path = entry.stock_relative_path;
        Log(
            "Boneyard picker client stock handoff completed. revision=" +
            std::to_string(g_picker.selection_revision) +
            " sha256=" + entry.content_sha256 +
            " stock_path=" + entry.stock_relative_path);
    }
    return true;
}

BoneyardPickerPacketState BuildLocalBoneyardPickerPacketState() {
    std::scoped_lock lock(g_picker.mutex);
    BoneyardPickerPacketState packet;
    if (!g_picker.initialized) {
        return packet;
    }
    packet.revision = g_picker.selection_revision;
    packet.resolution = g_picker.local_resolution;
    packet.digest = g_picker.selected_digest;
    return packet;
}

void ApplyAuthoritativeBoneyardPickerPacket(
    const BoneyardPickerPacketState& packet) {
    if (!multiplayer::IsLocalTransportClient() || packet.revision == 0 ||
        static_cast<std::uint8_t>(packet.resolution) >
            static_cast<std::uint8_t>(BoneyardResolutionStatus::Missing)) {
        return;
    }

    std::scoped_lock lock(g_picker.mutex);
    if (!g_picker.initialized ||
        (g_picker.selection_revision != 0 &&
         !IsRevisionNewer(packet.revision, g_picker.selection_revision) &&
         packet.revision != g_picker.selection_revision)) {
        return;
    }
    if (packet.revision == g_picker.selection_revision &&
        packet.digest == g_picker.selected_digest) {
        return;
    }

    g_picker.selection_revision = packet.revision;
    g_picker.selected_digest = packet.digest;
    g_picker.selected_index = kBoneyardPickerNoSelection;
    g_picker.local_resolution = BoneyardResolutionStatus::None;
    g_picker.native_launch_dispatched = false;
    g_picker.error_message.clear();
    g_picker.peer_resolution_error_active = false;
    g_picker.applied_stock_relative_path.clear();
    g_picker.missing_participant_ids.clear();
    if (IsZeroDigest(packet.digest)) {
        g_picker.phase = BoneyardPickerPhase::Closed;
        Log(
            "Boneyard picker authoritative selection cleared. revision=" +
            std::to_string(packet.revision));
        return;
    }

    const auto digest = DigestToHex(packet.digest);
    const auto found = g_picker.entry_by_digest.find(digest);
    if (found != g_picker.entry_by_digest.end()) {
        g_picker.selected_index = found->second;
    }
    g_picker.phase = BoneyardPickerPhase::WaitingForPeers;
    ResolveSelectedEntryLocked(
        static_cast<std::uint64_t>(GetTickCount64()));
    Log(
        "Boneyard picker authoritative selection received. revision=" +
        std::to_string(packet.revision) +
        " sha256=" + digest +
        " resolution=" +
        BoneyardResolutionStatusLabel(g_picker.local_resolution) +
        (g_picker.error_message.empty()
             ? std::string()
             : " error=" + g_picker.error_message));
}

void RecordRemoteBoneyardPickerPacket(
    std::uint64_t participant_id,
    const BoneyardPickerPacketState& packet) {
    if (!multiplayer::IsLocalTransportHost() || participant_id == 0 ||
        static_cast<std::uint8_t>(packet.resolution) >
            static_cast<std::uint8_t>(BoneyardResolutionStatus::Missing)) {
        return;
    }
    std::scoped_lock lock(g_picker.mutex);
    if (!g_picker.initialized) {
        return;
    }
    auto& resolution = g_picker.remote_resolutions[participant_id];
    const bool changed =
        resolution.packet.revision != packet.revision ||
        resolution.packet.resolution != packet.resolution ||
        resolution.packet.digest != packet.digest;
    resolution.packet = packet;
    if (changed && packet.revision == g_picker.selection_revision &&
        packet.digest == g_picker.selected_digest) {
        Log(
            "Boneyard picker peer resolution received. participant_id=" +
            std::to_string(participant_id) +
            " revision=" + std::to_string(packet.revision) +
            " sha256=" + DigestToHex(packet.digest) +
            " resolution=" +
            BoneyardResolutionStatusLabel(packet.resolution));
    }
}

const char* BoneyardPickerPhaseLabel(BoneyardPickerPhase phase) {
    switch (phase) {
    case BoneyardPickerPhase::Closed:
        return "closed";
    case BoneyardPickerPhase::Choosing:
        return "choosing";
    case BoneyardPickerPhase::WaitingForPeers:
        return "waiting_for_peers";
    case BoneyardPickerPhase::Launching:
        return "launching";
    case BoneyardPickerPhase::Error:
        return "error";
    }
    return "closed";
}

const char* BoneyardResolutionStatusLabel(
    BoneyardResolutionStatus status) {
    switch (status) {
    case BoneyardResolutionStatus::None:
        return "none";
    case BoneyardResolutionStatus::Ready:
        return "ready";
    case BoneyardResolutionStatus::Missing:
        return "missing";
    }
    return "none";
}
