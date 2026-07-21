class ScopedLocalPlayerScriptedMovementInput final {
public:
    explicit ScopedLocalPlayerScriptedMovementInput(uintptr_t gameplay_address)
        : gameplay_address_(gameplay_address) {
        if (gameplay_address_ == 0) {
            return;
        }

        auto& pending_frames =
            g_gameplay_keyboard_injection.pending_movement_frames;
        auto available = pending_frames.load(std::memory_order_acquire);
        while (available > 0) {
            if (!pending_frames.compare_exchange_weak(
                    available,
                    available - 1,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                continue;
            }

            auto& memory = ProcessMemory::Instance();
            if (!memory.TryReadField(
                    gameplay_address_,
                    kGameplayLocalMovementInputXOffset,
                    &saved_x_) ||
                !memory.TryReadField(
                    gameplay_address_,
                    kGameplayLocalMovementInputYOffset,
                    &saved_y_)) {
                pending_frames.fetch_add(1, std::memory_order_acq_rel);
                return;
            }

            const auto movement_x =
                g_gameplay_keyboard_injection.pending_movement_x.load(
                    std::memory_order_acquire);
            const auto movement_y =
                g_gameplay_keyboard_injection.pending_movement_y.load(
                    std::memory_order_acquire);
            const bool wrote_x = memory.TryWriteField(
                gameplay_address_,
                kGameplayLocalMovementInputXOffset,
                movement_x);
            const bool wrote_y = memory.TryWriteField(
                gameplay_address_,
                kGameplayLocalMovementInputYOffset,
                movement_y);
            if (wrote_x && wrote_y) {
                applied_ = true;
                return;
            }

            if (wrote_x) {
                (void)memory.TryWriteField(
                    gameplay_address_,
                    kGameplayLocalMovementInputXOffset,
                    saved_x_);
            }
            if (wrote_y) {
                (void)memory.TryWriteField(
                    gameplay_address_,
                    kGameplayLocalMovementInputYOffset,
                    saved_y_);
            }
            pending_frames.fetch_add(1, std::memory_order_acq_rel);
            return;
        }
    }

    ~ScopedLocalPlayerScriptedMovementInput() {
        if (!applied_) {
            return;
        }
        auto& memory = ProcessMemory::Instance();
        (void)memory.TryWriteField(
            gameplay_address_,
            kGameplayLocalMovementInputXOffset,
            saved_x_);
        (void)memory.TryWriteField(
            gameplay_address_,
            kGameplayLocalMovementInputYOffset,
            saved_y_);
    }

    ScopedLocalPlayerScriptedMovementInput(
        const ScopedLocalPlayerScriptedMovementInput&) = delete;
    ScopedLocalPlayerScriptedMovementInput& operator=(
        const ScopedLocalPlayerScriptedMovementInput&) = delete;

private:
    uintptr_t gameplay_address_ = 0;
    float saved_x_ = 0.0f;
    float saved_y_ = 0.0f;
    bool applied_ = false;
};
