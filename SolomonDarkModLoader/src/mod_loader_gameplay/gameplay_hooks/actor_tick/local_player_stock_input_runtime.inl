class ScopedBlockingOverlayGameplayInput final {
public:
    explicit ScopedBlockingOverlayGameplayInput(
        uintptr_t gameplay_address)
        : gameplay_address_(gameplay_address),
          active_(BlockingOverlayOwnsGameplayInput()) {
        if (!active_ || gameplay_address_ == 0) {
            return;
        }

        DiscardQueuedGameplayInputForBlockingOverlay();
        SuppressNativeGameplayInput();
    }

    ~ScopedBlockingOverlayGameplayInput() {
        if (!active_) {
            return;
        }
        DiscardQueuedGameplayInputForBlockingOverlay();
        SuppressNativeGameplayInput();
    }

    ScopedBlockingOverlayGameplayInput(
        const ScopedBlockingOverlayGameplayInput&) = delete;
    ScopedBlockingOverlayGameplayInput& operator=(
        const ScopedBlockingOverlayGameplayInput&) = delete;

private:
    template <typename T>
    void ClearField(std::size_t offset, T released) {
        (void)ProcessMemory::Instance().TryWriteField(
            gameplay_address_,
            offset,
            released);
    }

    void SuppressNativeGameplayInput() {
        ClearField(kGameplayLocalMovementInputXOffset, 0.0f);
        ClearField(kGameplayLocalMovementInputYOffset, 0.0f);
        ClearField(
            kGameplayCastIntentOffset,
            static_cast<std::uint8_t>(0));
        for (int index = 0; index < kGameplayInputBufferCount; ++index) {
            const auto buffer_offset = static_cast<std::size_t>(
                index * kGameplayInputBufferStride);
            ClearField(
                buffer_offset + kGameplayMouseLeftButtonOffset,
                static_cast<std::uint8_t>(0));
            ClearField(
                buffer_offset + kGameplayMouseRightButtonOffset,
                static_cast<std::uint8_t>(0));
        }
    }

    uintptr_t gameplay_address_ = 0;
    bool active_ = false;
};

class ScopedLocalPlayerScriptedMovementInput final {
public:
    explicit ScopedLocalPlayerScriptedMovementInput(uintptr_t gameplay_address)
        : gameplay_address_(gameplay_address),
          takeover_active_(
              IsLocalPlayerControlTakeoverActive()) {
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
            consumed_pending_frame_ = true;
            pending_frames_before_consumption_ = available;
            break;
        }
        if (!takeover_active_ &&
            !consumed_pending_frame_) {
            return;
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
            RestoreConsumedPendingFrame();
            return;
        }

        float movement_x = 0.0f;
        float movement_y = 0.0f;
        if (consumed_pending_frame_) {
            movement_x =
                g_gameplay_keyboard_injection.pending_movement_x.load(
                    std::memory_order_acquire);
            movement_y =
                g_gameplay_keyboard_injection.pending_movement_y.load(
                    std::memory_order_acquire);
        }
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
        RestoreConsumedPendingFrame();
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
    void RestoreConsumedPendingFrame() {
        if (!consumed_pending_frame_ ||
            pending_frames_before_consumption_ == 0) {
            return;
        }
        auto expected = pending_frames_before_consumption_ - 1;
        (void)g_gameplay_keyboard_injection.pending_movement_frames
            .compare_exchange_strong(
                expected,
                pending_frames_before_consumption_,
                std::memory_order_acq_rel,
                std::memory_order_acquire);
    }

    uintptr_t gameplay_address_ = 0;
    float saved_x_ = 0.0f;
    float saved_y_ = 0.0f;
    bool takeover_active_ = false;
    bool consumed_pending_frame_ = false;
    std::uint32_t pending_frames_before_consumption_ = 0;
    bool applied_ = false;
};
