struct SDModSolomonDigState {
    bool valid = false;
    uintptr_t actor_address = 0;
    float x = 0.0f;
    float y = 0.0f;
    std::int32_t interaction_state = -1;
    bool participant_acquired = false;
    std::int32_t target_gameplay_slot = -1;
};

struct SDModGameplayOpenableObstacleState {
    uintptr_t object_address = 0;
    uintptr_t collision_record_address = 0;
    float start_x = 0.0f;
    float start_y = 0.0f;
    float end_x = 0.0f;
    float end_y = 0.0f;
};
