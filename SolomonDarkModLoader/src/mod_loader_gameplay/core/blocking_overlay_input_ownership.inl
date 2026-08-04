// Blocking loader overlays own gameplay input as one modal class. Drop queued
// input as well as masking the live stock fields so actions pressed under an
// overlay cannot fire after it closes.
void DiscardQueuedGameplayInputForBlockingOverlay() {
    for (auto& pending_scancode :
         g_gameplay_keyboard_injection.pending_scancodes) {
        pending_scancode.store(0, std::memory_order_release);
    }
    g_gameplay_keyboard_injection.pending_movement_x.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_y.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_right_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_injected_keyboard_control_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_manual_spawner_primary_cast_allowances.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.manual_spawner_primary_cast_control_grace_until_ms.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.manual_spawner_primary_target_actor.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_x.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_y.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_observed_ms.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_left_active.store(
        false,
        std::memory_order_release);
    g_gameplay_keyboard_injection.injected_mouse_right_active.store(
        false,
        std::memory_order_release);
}
