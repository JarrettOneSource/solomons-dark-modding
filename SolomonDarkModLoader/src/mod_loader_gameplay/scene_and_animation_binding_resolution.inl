void RecordGameplayMouseLeftEdge() {
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.fetch_add(1, std::memory_order_acq_rel);
}

std::string NormalizeInjectedKeyName(std::string_view value) {
    std::string normalized;
    normalized.reserve(value.size());
    for (char raw : value) {
        const auto ch = static_cast<unsigned char>(raw);
        if (std::isspace(ch) || ch == '_' || ch == '-') {
            continue;
        }
        normalized.push_back(static_cast<char>(std::tolower(ch)));
    }
    return normalized;
}

bool TryResolveInjectedBindingGlobal(std::string_view binding_name, uintptr_t* absolute_global) {
    if (absolute_global == nullptr) {
        return false;
    }

    const auto normalized = NormalizeInjectedKeyName(binding_name);
    if (normalized == "menu" || normalized == "pause" || normalized == "escape") {
        *absolute_global = kMenuKeybindingGlobal;
        return true;
    }
    if (normalized == "inventory" || normalized == "inv") {
        *absolute_global = kInventoryKeybindingGlobal;
        return true;
    }
    if (normalized == "skills" || normalized == "skill") {
        *absolute_global = kSkillsKeybindingGlobal;
        return true;
    }
    if (normalized.size() == 9 && normalized.rfind("beltslot", 0) == 0) {
        const auto slot_char = normalized[8];
        if (slot_char >= '1' && slot_char <= '8') {
            *absolute_global = kBeltSlotKeybindingGlobals[static_cast<std::size_t>(slot_char - '1')];
            return true;
        }
    }
    if (normalized.size() == 5 && normalized.rfind("slot", 0) == 0) {
        const auto slot_char = normalized[4];
        if (slot_char >= '1' && slot_char <= '8') {
            *absolute_global = kBeltSlotKeybindingGlobals[static_cast<std::size_t>(slot_char - '1')];
            return true;
        }
    }

    return false;
}

bool TryReadInjectedBindingCode(uintptr_t absolute_global, std::uint32_t* raw_binding_code) {
    if (raw_binding_code == nullptr) {
        return false;
    }

    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_global);
    if (resolved == 0) {
        return false;
    }

    std::uint32_t raw = 0;
    if (!ProcessMemory::Instance().TryReadValue(resolved, &raw)) {
        return false;
    }

    *raw_binding_code = raw;
    return true;
}

std::int32_t RecordGameplayBeltSlotEdge(std::uint32_t scancode) {
    for (std::size_t slot = 0; slot < kBeltSlotKeybindingGlobals.size(); ++slot) {
        std::uint32_t binding_code = 0;
        if (TryReadInjectedBindingCode(
                kBeltSlotKeybindingGlobals[slot],
                &binding_code) &&
            binding_code == scancode) {
            g_gameplay_keyboard_injection.last_belt_slot_edge.store(
                static_cast<std::int32_t>(slot),
                std::memory_order_release);
            g_gameplay_keyboard_injection.last_belt_slot_edge_tick_ms.store(
                static_cast<std::uint64_t>(GetTickCount64()),
                std::memory_order_release);
            return static_cast<std::int32_t>(slot);
        }
    }
    return -1;
}

bool TryGetRecentGameplayBeltSlotEdge(
    std::uint64_t now_ms,
    std::uint64_t maximum_age_ms,
    std::int32_t* belt_slot) {
    if (belt_slot == nullptr) {
        return false;
    }
    *belt_slot = -1;
    const auto tick_ms =
        g_gameplay_keyboard_injection.last_belt_slot_edge_tick_ms.load(
            std::memory_order_acquire);
    const auto slot =
        g_gameplay_keyboard_injection.last_belt_slot_edge.load(
            std::memory_order_acquire);
    if (tick_ms == 0 || now_ms < tick_ms ||
        now_ms - tick_ms > maximum_age_ms ||
        slot < 0 ||
        slot >= static_cast<std::int32_t>(kBeltSlotKeybindingGlobals.size())) {
        return false;
    }
    *belt_slot = slot;
    return true;
}

bool TryReadResolvedGamePointerAbsolute(uintptr_t absolute_address, uintptr_t* value) {
    if (value == nullptr) {
        return false;
    }

    *value = 0;
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return resolved != 0 && ProcessMemory::Instance().TryReadValue(resolved, value);
}
