enum class HubServiceKind : std::uint32_t {
    None = 0,
    LuthacusStorage = 1,
    Fomentius = 2,
    Hagatha = 3,
};

const char* HubServiceName(HubServiceKind kind) {
    switch (kind) {
        case HubServiceKind::LuthacusStorage:
            return "luthacus_storage";
        case HubServiceKind::Fomentius:
            return "fomentius";
        case HubServiceKind::Hagatha:
            return "hagatha";
        default:
            return "none";
    }
}

bool TryParseHubServiceName(std::string_view name, HubServiceKind* kind) {
    if (kind == nullptr) {
        return false;
    }
    *kind = HubServiceKind::None;
    if (name == "luthacus_storage") {
        *kind = HubServiceKind::LuthacusStorage;
    } else if (name == "fomentius") {
        *kind = HubServiceKind::Fomentius;
    } else if (name == "hagatha") {
        *kind = HubServiceKind::Hagatha;
    }
    return *kind != HubServiceKind::None;
}

std::size_t HubServiceActionOffset(HubServiceKind kind) {
    switch (kind) {
        case HubServiceKind::LuthacusStorage:
            return kHubLuthacusStorageActionOffset;
        case HubServiceKind::Fomentius:
            return kHubFomentiusActionOffset;
        case HubServiceKind::Hagatha:
            return kHubHagathaActionOffset;
        default:
            return 0;
    }
}

bool TryReadHubSurfaceStateInternal(
    SDModHubSurfaceState* state,
    std::string* error_message) {
    if (state == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Hub surface state output is required.";
        }
        return false;
    }
    *state = {};
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }
    state->gameplay_address = gameplay_address;

    SceneContextSnapshot scene_context;
    if (!TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene context is unreadable.";
        }
        return false;
    }
    state->shared_hub = IsSharedHubSceneContext(scene_context);

    auto& memory = ProcessMemory::Instance();
    const auto chat_active_address =
        memory.ResolveGameAddressOrZero(kHubChatActiveGlobal);
    std::uint8_t chat_active = 0;
    if (chat_active_address == 0 ||
        !memory.TryReadValue(chat_active_address, &chat_active)) {
        if (error_message != nullptr) {
            *error_message = "Hub chat state is unreadable.";
        }
        return false;
    }
    state->chat_active = chat_active != 0;

    if (!TryReadResolvedGamePointerAbsolute(
            kHubCourtyardGlobal,
            &state->courtyard_address)) {
        if (error_message != nullptr) {
            *error_message = "Courtyard object is unreadable.";
        }
        return false;
    }

    if (!memory.TryReadField(
            gameplay_address,
            kGameplayHubSurfaceOffset,
            &state->surface_address)) {
        if (error_message != nullptr) {
            *error_message = "Hub surface slot is unreadable.";
        }
        return false;
    }
    state->surface_active = state->surface_address != 0;
    if (!state->surface_active) {
        state->valid = true;
        return true;
    }

    if (!memory.TryReadValue(state->surface_address, &state->surface_vtable)) {
        if (error_message != nullptr) {
            *error_message = "Active hub surface vtable is unreadable.";
        }
        return false;
    }
    const auto inventory_screen_vtable =
        memory.ResolveGameAddressOrZero(kInventoryScreenVtable);
    state->inventory_screen_active =
        inventory_screen_vtable != 0 &&
        state->surface_vtable == inventory_screen_vtable;
    if (!state->inventory_screen_active) {
        state->valid = true;
        return true;
    }

    if (!memory.TryReadField(
            state->surface_address,
            kInventoryScreenShopOffset,
            &state->shop_address)) {
        if (error_message != nullptr) {
            *error_message = "InventoryScreen shop slot is unreadable.";
        }
        return false;
    }
    if (state->shop_address != 0 &&
        !memory.TryReadValue(state->shop_address, &state->shop_vtable)) {
        if (error_message != nullptr) {
            *error_message = "InventoryShop vtable is unreadable.";
        }
        return false;
    }
    const auto inventory_shop_vtable =
        memory.ResolveGameAddressOrZero(kInventoryShopVtable);
    state->inventory_shop_active =
        state->shop_address != 0 &&
        inventory_shop_vtable != 0 &&
        state->shop_vtable == inventory_shop_vtable;
    state->valid = true;
    return true;
}

struct HubServiceDispatchContext {
    uintptr_t gameplay_address = 0;
    uintptr_t courtyard_address = 0;
    uintptr_t dispatch_address = 0;
    uintptr_t action_address = 0;
};

bool TryBuildHubServiceDispatchContext(
    HubServiceKind kind,
    HubServiceDispatchContext* context,
    std::string* error_message) {
    if (context == nullptr || kind == HubServiceKind::None) {
        if (error_message != nullptr) {
            *error_message = "Hub service request is invalid.";
        }
        return false;
    }
    *context = {};

    SDModHubSurfaceState surface;
    if (!TryReadHubSurfaceStateInternal(&surface, error_message)) {
        return false;
    }
    if (!surface.shared_hub) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not in the shared hub.";
        }
        return false;
    }
    if (surface.chat_active) {
        if (error_message != nullptr) {
            *error_message = "Close the active hub conversation before opening a service.";
        }
        return false;
    }
    if (surface.surface_active) {
        if (error_message != nullptr) {
            *error_message = "Close the active hub surface before opening another service.";
        }
        return false;
    }
    if (surface.courtyard_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Courtyard object is not active.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t courtyard_vtable = 0;
    if (!memory.TryReadValue(surface.courtyard_address, &courtyard_vtable)) {
        if (error_message != nullptr) {
            *error_message = "Courtyard vtable is unreadable.";
        }
        return false;
    }
    const auto expected_courtyard_vtable =
        memory.ResolveGameAddressOrZero(kHubCourtyardVtable);
    if (expected_courtyard_vtable == 0 ||
        courtyard_vtable != expected_courtyard_vtable) {
        if (error_message != nullptr) {
            *error_message = "Active Courtyard object has an unexpected native type.";
        }
        return false;
    }

    const auto dispatch_address =
        memory.ResolveGameAddressOrZero(kHubServiceDispatch);
    uintptr_t vtable_dispatch_address = 0;
    if (dispatch_address == 0 ||
        !memory.TryReadValue(
            courtyard_vtable + kHubCourtyardServiceVfuncOffset,
            &vtable_dispatch_address) ||
        vtable_dispatch_address != dispatch_address) {
        if (error_message != nullptr) {
            *error_message = "Courtyard service dispatcher does not match the verified binary layout.";
        }
        return false;
    }

    const auto action_offset = HubServiceActionOffset(kind);
    if (action_offset == 0) {
        if (error_message != nullptr) {
            *error_message = "Hub service action offset is unavailable.";
        }
        return false;
    }
    context->gameplay_address = surface.gameplay_address;
    context->courtyard_address = surface.courtyard_address;
    context->dispatch_address = dispatch_address;
    context->action_address = surface.gameplay_address + action_offset;
    return true;
}

int CaptureHubServiceDispatchException(
    EXCEPTION_POINTERS* exception_pointers,
    DWORD* exception_code) {
    if (exception_code != nullptr &&
        exception_pointers != nullptr &&
        exception_pointers->ExceptionRecord != nullptr) {
        *exception_code =
            exception_pointers->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool CallHubServiceDispatchSafe(
    const HubServiceDispatchContext& context,
    DWORD* exception_code) {
    auto* dispatch =
        reinterpret_cast<HubServiceDispatchFn>(context.dispatch_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    __try {
        dispatch(
            reinterpret_cast<void*>(context.courtyard_address),
            reinterpret_cast<void*>(context.action_address));
        return true;
    } __except (CaptureHubServiceDispatchException(
        GetExceptionInformation(),
        exception_code)) {
        return false;
    }
}

bool CallCourtyardTickSafe(
    uintptr_t tick_address,
    uintptr_t courtyard_address,
    DWORD* exception_code) {
    using CourtyardTickFn = void(__thiscall*)(void*);
    auto* tick = reinterpret_cast<CourtyardTickFn>(tick_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    __try {
        tick(reinterpret_cast<void*>(courtyard_address));
        return true;
    } __except (CaptureHubServiceDispatchException(
        GetExceptionInformation(),
        exception_code)) {
        return false;
    }
}

void TickDormantSharedHubOnGameThread() {
    if (!multiplayer::IsLocalTransportHost()) {
        return;
    }

    uintptr_t gameplay_address = 0;
    SceneContextSnapshot local_context;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) ||
        gameplay_address == 0 ||
        !TryBuildSceneContextSnapshot(
            gameplay_address,
            &local_context) ||
        local_context.world_address == 0 ||
        local_context.current_region_index <= kHubRegionIndex ||
        local_context.current_region_index >= kArenaRegionIndex) {
        return;
    }

    SceneContextSnapshot hub_context;
    if (!TryBuildGameplayRegionSceneContextSnapshot(
            gameplay_address,
            kHubRegionIndex,
            &hub_context) ||
        !IsSharedHubSceneContext(hub_context) ||
        hub_context.world_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t published_courtyard = 0;
    uintptr_t courtyard_vtable = 0;
    const auto expected_courtyard_vtable =
        memory.ResolveGameAddressOrZero(kHubCourtyardVtable);
    const auto courtyard_tick =
        memory.ResolveGameAddressOrZero(kCourtyardRegionTick);
    if (!TryReadResolvedGamePointerAbsolute(
            kHubCourtyardGlobal,
            &published_courtyard) ||
        published_courtyard != hub_context.world_address ||
        !memory.TryReadValue(
            hub_context.world_address,
            &courtyard_vtable) ||
        expected_courtyard_vtable == 0 ||
        courtyard_vtable != expected_courtyard_vtable ||
        courtyard_tick == 0 ||
        !memory.IsExecutableRange(courtyard_tick, 1)) {
        return;
    }

    DWORD exception_code = 0;
    if (!CallCourtyardTickSafe(
            courtyard_tick,
            hub_context.world_address,
            &exception_code)) {
        static std::uint64_t last_failure_log_ms = 0;
        const auto now_ms =
            static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms >= last_failure_log_ms + 1000) {
            last_failure_log_ms = now_ms;
            Log(
                "Dormant shared-hub tick raised exception " +
                HexString(exception_code) + ".");
        }
    }
}


void TryDispatchPendingHubServiceOnGameThread() {
    const auto raw_kind =
        g_gameplay_keyboard_injection.pending_hub_service_request.exchange(
            0,
            std::memory_order_acq_rel);
    if (raw_kind == 0) {
        return;
    }

    const auto kind = static_cast<HubServiceKind>(raw_kind);
    HubServiceDispatchContext context;
    std::string error_message;
    if (!TryBuildHubServiceDispatchContext(kind, &context, &error_message)) {
        Log(
            "hub.open_service: rejected service=" +
            std::string(HubServiceName(kind)) + " error=" + error_message);
        return;
    }

    DWORD exception_code = 0;
    if (!CallHubServiceDispatchSafe(context, &exception_code)) {
        Log(
            "hub.open_service: native dispatch raised. service=" +
            std::string(HubServiceName(kind)) +
            " exception_code=" + HexString(exception_code));
        return;
    }

    SDModHubSurfaceState surface;
    if (!TryReadHubSurfaceStateInternal(&surface, &error_message) ||
        !surface.inventory_screen_active ||
        !surface.inventory_shop_active) {
        Log(
            "hub.open_service: native surface postcondition failed. service=" +
            std::string(HubServiceName(kind)) + " error=" +
            (error_message.empty()
                 ? std::string("InventoryScreen/InventoryShop is not active.")
                 : error_message));
        return;
    }

    Log(
        "hub.open_service: opened service=" +
        std::string(HubServiceName(kind)) +
        " gameplay=" + HexString(context.gameplay_address) +
        " courtyard=" + HexString(context.courtyard_address) +
        " action=" + HexString(context.action_address) +
        " surface=" + HexString(surface.surface_address) +
        " shop=" + HexString(surface.shop_address));
}
