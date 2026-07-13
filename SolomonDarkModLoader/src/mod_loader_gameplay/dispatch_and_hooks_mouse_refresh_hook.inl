bool ClearRawGameplayMouseLeft(uintptr_t input_state_address) {
    if (input_state_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t mouse_button_mask = 0;
    if (!memory.TryReadField(
            input_state_address,
            kGameplayInputMouseButtonMaskOffset,
            &mouse_button_mask)) {
        return false;
    }

    constexpr std::uint8_t kMouseLeftMask = 1;
    const auto released_mask = static_cast<std::uint8_t>(mouse_button_mask & ~kMouseLeftMask);
    return released_mask == mouse_button_mask ||
           memory.TryWriteField(
               input_state_address,
               kGameplayInputMouseButtonMaskOffset,
               released_mask);
}

void __fastcall HookGameplayMouseRefresh(void* self, void* unused_edx) {
    const auto self_address = reinterpret_cast<uintptr_t>(self);
    if (self_address != 0) {
        g_gameplay_keyboard_injection.input_state_address.store(
            self_address,
            std::memory_order_release);
        if (g_gameplay_keyboard_injection.injected_mouse_left_active.load(
                std::memory_order_acquire) &&
            g_gameplay_keyboard_injection.pending_mouse_left_frames.load(
                std::memory_order_acquire) == 0) {
            (void)ClearRawGameplayMouseLeft(self_address);
        }
    }

    const auto original =
        GetX86HookTrampoline<GameplayMouseRefreshFn>(g_gameplay_keyboard_injection.mouse_refresh_hook);
    if (original != nullptr) {
        original(self, unused_edx);
    }

    if (self_address == 0) {
        return;
    }

    int live_buffer_index = -1;
    if (!ProcessMemory::Instance().TryReadField(
            self_address,
            kGameplayInputBufferIndexOffset,
            &live_buffer_index)) {
        return;
    }
    if (live_buffer_index >= 0) {
        const auto live_mouse_button_offset = static_cast<std::size_t>(
            live_buffer_index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
        std::uint8_t mouse_left = 0;
        const bool is_pressed =
            ProcessMemory::Instance().TryReadField(self_address, live_mouse_button_offset, &mouse_left) &&
            mouse_left != 0;
        const bool was_pressed =
            g_gameplay_keyboard_injection.last_observed_mouse_left_down.exchange(is_pressed, std::memory_order_acq_rel);
        if (is_pressed && !was_pressed) {
            RecordGameplayMouseLeftEdge();
        }
    }

    auto& pending = g_gameplay_keyboard_injection.pending_mouse_left_frames;
    auto available = pending.load(std::memory_order_acquire);
    while (available > 0) {
        if (!pending.compare_exchange_weak(
                available,
                available - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            continue;
        }

        int buffer_index = -1;
        if (!ProcessMemory::Instance().TryReadField(
                self_address,
                kGameplayInputBufferIndexOffset,
                &buffer_index) ||
            buffer_index < 0) {
            return;
        }

        const auto mouse_button_offset = static_cast<std::size_t>(
            buffer_index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
        const std::uint8_t pressed = 1;
        const bool wrote_mouse_button =
            ProcessMemory::Instance().TryWriteField(self_address, mouse_button_offset, pressed);

        uintptr_t gameplay_address = 0;
        const bool have_gameplay_address =
            TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0;
        const bool wrote_cast_intent =
            have_gameplay_address &&
            ProcessMemory::Instance().TryWriteField(gameplay_address, kGameplayCastIntentOffset, pressed);

        if (wrote_mouse_button || wrote_cast_intent) {
            g_gameplay_keyboard_injection.injected_mouse_left_active.store(true, std::memory_order_release);
            g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(true, std::memory_order_release);
            auto& pending_edge_events = g_gameplay_keyboard_injection.pending_mouse_left_edge_events;
            auto available_edge_events = pending_edge_events.load(std::memory_order_acquire);
            while (available_edge_events > 0) {
                if (!pending_edge_events.compare_exchange_weak(
                        available_edge_events,
                        available_edge_events - 1,
                        std::memory_order_acq_rel,
                        std::memory_order_acquire)) {
                    continue;
                }
                RecordGameplayMouseLeftEdge();
                break;
            }
            Log(
                "Injected gameplay mouse-left click. input_state=" + HexString(self_address) +
                " buffer_index=" + std::to_string(buffer_index) +
                " gameplay=" + (have_gameplay_address ? HexString(gameplay_address) : std::string("0x00000000")) +
                " cast_intent=" + std::to_string(wrote_cast_intent ? 1 : 0));
        }
        return;
    }

    if (g_gameplay_keyboard_injection.injected_mouse_left_active.load(std::memory_order_acquire)) {
        int buffer_index = -1;
        if (!ProcessMemory::Instance().TryReadField(
                self_address,
                kGameplayInputBufferIndexOffset,
                &buffer_index) ||
            buffer_index < 0) {
            return;
        }

        const std::uint8_t released = 0;
        bool wrote_mouse_button = false;
        for (int index = 0; index < kGameplayInputBufferCount; ++index) {
            const auto mouse_button_offset = static_cast<std::size_t>(
                index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
            wrote_mouse_button =
                ProcessMemory::Instance().TryWriteField(
                    self_address,
                    mouse_button_offset,
                    released) ||
                wrote_mouse_button;
        }

        uintptr_t gameplay_address = 0;
        const bool have_gameplay_address =
            TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0;
        const bool wrote_cast_intent =
            have_gameplay_address &&
            ProcessMemory::Instance().TryWriteField(gameplay_address, kGameplayCastIntentOffset, released);

        if (wrote_mouse_button || wrote_cast_intent) {
            g_gameplay_keyboard_injection.injected_mouse_left_active.store(false, std::memory_order_release);
            g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(false, std::memory_order_release);
            Log(
                "Released injected gameplay mouse-left. input_state=" + HexString(self_address) +
                " live_buffer_index=" + std::to_string(buffer_index) +
                " cleared_buffer_count=" + std::to_string(kGameplayInputBufferCount) +
                " gameplay=" + (have_gameplay_address ? HexString(gameplay_address) : std::string("0x00000000")) +
                " cast_intent=" + std::to_string(wrote_cast_intent ? 1 : 0));
        }
    }

}
