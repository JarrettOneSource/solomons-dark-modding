enum class SDModNativeMinionKind : std::uint8_t {
    Unknown = 0,
    GoodImp = 1,
    Leviathan = 2,
    Golem = 3,
};

struct SDModNativeMinionState {
    bool valid = false;
    SDModNativeMinionKind kind = SDModNativeMinionKind::Unknown;
    std::uint32_t native_type_id = 0;
    std::uint64_t owner_participant_id = 0;
    std::uint32_t state_flags = 0;
    multiplayer::NativeMinionTerminalReason terminal_reason =
        multiplayer::NativeMinionTerminalReasonNone;
    float hp = 0.0f;
    float max_hp = 0.0f;
    std::int32_t target_actor_group = -1;
    std::int32_t target_world_slot = -1;
    std::uint32_t native_age = 0;
    std::int32_t attack_timer = 0;
    std::int32_t attack_cooldown = 0;
    std::uint32_t gait_primary = 0;
    std::uint32_t gait_secondary = 0;
    std::int32_t target_refresh_timer = 0;
    std::uint32_t locomotion_sample_counter = 0;
    std::uint32_t ambient_effect_timer = 0;
    std::uint32_t iron = 0;
    float animation_phase = 0.0f;
    float steering_heading = 0.0f;
    float steering_step = 0.0f;
    float damage_primary = 0.0f;
    float damage_secondary = 0.0f;
    float reflect_ratio = 0.0f;
};
