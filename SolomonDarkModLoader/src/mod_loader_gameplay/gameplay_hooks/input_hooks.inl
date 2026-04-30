std::uint8_t __fastcall HookGameplayKeyboardEdge(void* self, void* /*unused_edx*/, std::uint32_t scancode) {
    if (scancode < g_gameplay_keyboard_injection.pending_scancodes.size()) {
        auto& pending = g_gameplay_keyboard_injection.pending_scancodes[scancode];
        auto available = pending.load(std::memory_order_acquire);
        while (available > 0) {
            if (pending.compare_exchange_weak(
                    available,
                    available - 1,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                return 1;
            }
        }
    }

    const auto original =
        GetX86HookTrampoline<GameplayKeyboardEdgeFn>(g_gameplay_keyboard_injection.edge_hook);
    return original != nullptr ? original(self, scancode) : 0;
}
