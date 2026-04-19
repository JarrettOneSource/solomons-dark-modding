bool IsGameplayKeyboardInjectionInitialized() {
    return g_gameplay_keyboard_injection.initialized;
}

std::uint64_t GetGameplayMouseLeftEdgeSerial() {
    return g_gameplay_keyboard_injection.mouse_left_edge_serial.load(std::memory_order_acquire);
}

std::uint64_t GetGameplayMouseLeftEdgeTickMs() {
    return g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.load(std::memory_order_acquire);
}

bool QueueGameplayMouseLeftClick(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay input injection is not initialized.";
        }
        return false;
    }

    uintptr_t scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&scene_address) || scene_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_mouse_left_frames.fetch_add(
        kInjectedGameplayMouseClickFrames,
        std::memory_order_acq_rel);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.fetch_add(1, std::memory_order_acq_rel);
    Log("Queued gameplay mouse-left click. gameplay=" + HexString(scene_address));
    return true;
}

bool QueueGameplayScancodePress(std::uint32_t scancode, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay keyboard injection is not initialized.";
        }
        return false;
    }
    if (scancode > 0xFF) {
        if (error_message != nullptr) {
            *error_message = "Scancode must be in the range 0..255.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_scancodes[scancode].fetch_add(1, std::memory_order_acq_rel);
    return true;
}

bool QueueGameplayKeyPress(std::string_view binding_name, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t absolute_global = 0;
    if (!TryResolveInjectedBindingGlobal(binding_name, &absolute_global)) {
        if (error_message != nullptr) {
            *error_message =
                "Unknown gameplay key binding. Use menu, inventory, skills, or belt_slot_1..belt_slot_8.";
        }
        return false;
    }

    std::uint32_t raw_binding_code = 0;
    if (!TryReadInjectedBindingCode(absolute_global, &raw_binding_code)) {
        if (error_message != nullptr) {
            *error_message = "Failed to read the live gameplay key binding.";
        }
        return false;
    }

    if (raw_binding_code > 0xFF) {
        if (error_message != nullptr) {
            *error_message =
                "The live gameplay binding is mouse-backed. Use sd.input.click_normalized for mouse-bound actions.";
        }
        return false;
    }

    return QueueGameplayScancodePress(raw_binding_code, error_message);
}

