class ScopedLocalPlayerRushMovementScale {
public:
    explicit ScopedLocalPlayerRushMovementScale(uintptr_t actor_address)
        : actor_address_(actor_address) {
        if (actor_address_ == 0 || kActorMoveStepScaleOffset == 0) {
            return;
        }

        uintptr_t progression_address = 0;
        float rush_speed_percent = 0.0f;
        int rush_rank = 0;
        if (!TryResolveActorProgressionRuntime(actor_address_, &progression_address) ||
            progression_address == 0 ||
            !TryReadProgressionRankedNumericStat(
                progression_address,
                kRushProgressionEntryIndex,
                "mValue",
                &rush_speed_percent,
                &rush_rank) ||
            rush_rank <= 0) {
            return;
        }

        auto movement_multiplier = 1.0f + rush_speed_percent / 100.0f;
        std::int32_t concentration_entry_a = -1;
        std::int32_t concentration_entry_b = -1;
        if (TryReadGameplayConcentrationStateForSlot(
                0,
                &concentration_entry_a,
                &concentration_entry_b) &&
            (concentration_entry_a == kRushProgressionEntryIndex ||
             concentration_entry_b == kRushProgressionEntryIndex)) {
            float concentration_speed_percent = 0.0f;
            int concentration_rank = 0;
            if (!TryReadProgressionRankedNumericStat(
                    progression_address,
                    kRushProgressionEntryIndex,
                    "mConcentration",
                    &concentration_speed_percent,
                    &concentration_rank) ||
                concentration_rank <= 0) {
                return;
            }
            movement_multiplier *=
                1.0f + concentration_speed_percent / 100.0f;
        }

        if (!std::isfinite(movement_multiplier) ||
            movement_multiplier <= 0.0f ||
            movement_multiplier > 16.0f ||
            !TryReadFiniteFloatField(
                actor_address_,
                kActorMoveStepScaleOffset,
                &original_move_step_scale_) ||
            original_move_step_scale_ <= 0.0f) {
            return;
        }

        const auto scaled_move_step =
            original_move_step_scale_ * movement_multiplier;
        if (!std::isfinite(scaled_move_step)) {
            return;
        }

        active_ = ProcessMemory::Instance().TryWriteField(
            actor_address_,
            kActorMoveStepScaleOffset,
            scaled_move_step);
    }

    ~ScopedLocalPlayerRushMovementScale() {
        if (active_) {
            (void)ProcessMemory::Instance().TryWriteField(
                actor_address_,
                kActorMoveStepScaleOffset,
                original_move_step_scale_);
        }
    }

    ScopedLocalPlayerRushMovementScale(const ScopedLocalPlayerRushMovementScale&) = delete;
    ScopedLocalPlayerRushMovementScale& operator=(const ScopedLocalPlayerRushMovementScale&) = delete;

private:
    uintptr_t actor_address_ = 0;
    float original_move_step_scale_ = 0.0f;
    bool active_ = false;
};
