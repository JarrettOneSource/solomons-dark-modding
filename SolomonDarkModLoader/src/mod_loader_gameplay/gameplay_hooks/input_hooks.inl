// While the loader's boneyard picker modal is open it owns these DirectInput
// scancodes outright (cursor movement, pick, cancel). The stock game must not
// see their edges at all: an unconsumed Escape edge otherwise opens the pause
// menu on top of the picker, and Return would double-drive the stock start
// flow the picker is already brokering.
bool BoneyardPickerOwnsScancode(std::uint32_t scancode) {
    switch (scancode) {
        case 0x01:  // DIK_ESCAPE
        case 0x1C:  // DIK_RETURN
        case 0xC8:  // DIK_UP
        case 0xC9:  // DIK_PRIOR (PgUp)
        case 0xD0:  // DIK_DOWN
        case 0xD1:  // DIK_NEXT (PgDn)
            return GetBoneyardPickerSnapshot().is_open;
        default:
            return false;
    }
}

std::uint8_t __fastcall HookGameplayKeyboardEdge(void* self, void* /*unused_edx*/, std::uint32_t scancode) {
    const bool blocking_overlay_owns_input =
        BlockingOverlayOwnsGameplayInput();
    if (blocking_overlay_owns_input ||
        BoneyardPickerOwnsScancode(scancode)) {
        if (blocking_overlay_owns_input) {
            DiscardQueuedGameplayInputForBlockingOverlay();
        }
        // Let the stock helper update its internal edge bookkeeping, then
        // report "no edge" so the game never reacts while the picker owns
        // the key. The picker reads these keys through GetAsyncKeyState.
        const auto original_fn = GetX86HookTrampoline<GameplayKeyboardEdgeFn>(
            g_gameplay_keyboard_injection.edge_hook);
        if (original_fn != nullptr) {
            (void)original_fn(self, scancode);
        }
        return 0;
    }
    if (scancode < g_gameplay_keyboard_injection.pending_scancodes.size()) {
        auto& pending = g_gameplay_keyboard_injection.pending_scancodes[scancode];
        auto available = pending.load(std::memory_order_acquire);
        while (available > 0) {
            if (pending.compare_exchange_weak(
                    available,
                    available - 1,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                Log(
                    "Consumed queued gameplay keyboard edge. scancode=" +
                    std::to_string(scancode) +
                    " remaining=" + std::to_string(available - 1));
                const auto belt_slot = RecordGameplayBeltSlotEdge(scancode);
                if (TryDispatchSelectedLuaRegisteredSecondaryBeltInput(
                        belt_slot) !=
                    LuaRegisteredSpellInputDispatchResult::NotSelected) {
                    return 0;
                }
                return 1;
            }
        }
    }

    const auto original =
        GetX86HookTrampoline<GameplayKeyboardEdgeFn>(g_gameplay_keyboard_injection.edge_hook);
    const std::uint8_t result =
        original != nullptr ? original(self, scancode) : 0;
    if (result != 0) {
        const auto belt_slot = RecordGameplayBeltSlotEdge(scancode);
        if (TryDispatchSelectedLuaRegisteredSecondaryBeltInput(
                belt_slot) !=
            LuaRegisteredSpellInputDispatchResult::NotSelected) {
            return 0;
        }
    }
    return result;
}
