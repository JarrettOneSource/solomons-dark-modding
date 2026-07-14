class ScopedLocalPlayerRushMovementScale {
public:
    explicit ScopedLocalPlayerRushMovementScale(uintptr_t actor_address)
        : actor_address_(actor_address) {
        if (actor_address_ == 0 || kActorMovementSpeedMultiplierOffset == 0) {
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

        const auto rush_speed_multiplier = 1.0f + rush_speed_percent / 100.0f;
        if (!std::isfinite(rush_speed_multiplier) ||
            rush_speed_multiplier <= 0.0f ||
            rush_speed_multiplier > 16.0f ||
            !TryReadFiniteFloatField(
                actor_address_,
                kActorMovementSpeedMultiplierOffset,
                &original_movement_speed_multiplier_) ||
            original_movement_speed_multiplier_ < 0.0f) {
            return;
        }

        const auto scaled_movement_speed_multiplier =
            original_movement_speed_multiplier_ * rush_speed_multiplier;
        if (!std::isfinite(scaled_movement_speed_multiplier)) {
            return;
        }

        active_ = ProcessMemory::Instance().TryWriteField(
            actor_address_,
            kActorMovementSpeedMultiplierOffset,
            scaled_movement_speed_multiplier);
    }

    ~ScopedLocalPlayerRushMovementScale() {
        if (active_) {
            (void)ProcessMemory::Instance().TryWriteField(
                actor_address_,
                kActorMovementSpeedMultiplierOffset,
                original_movement_speed_multiplier_);
        }
    }

    ScopedLocalPlayerRushMovementScale(const ScopedLocalPlayerRushMovementScale&) = delete;
    ScopedLocalPlayerRushMovementScale& operator=(const ScopedLocalPlayerRushMovementScale&) = delete;

private:
    uintptr_t actor_address_ = 0;
    float original_movement_speed_multiplier_ = 0.0f;
    bool active_ = false;
};
