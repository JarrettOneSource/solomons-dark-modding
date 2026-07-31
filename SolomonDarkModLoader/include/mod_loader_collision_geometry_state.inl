struct SDModCollisionGeometryPoint {
    float x = 0.0f;
    float y = 0.0f;
};

struct SDModCollisionCircle {
    std::uint64_t geometry_id = 0;
    std::uint32_t native_type_id = 0;
    float x = 0.0f;
    float y = 0.0f;
    float radius = 0.0f;
    std::uint32_t mask = 0;
    bool path_blocks = false;
    bool pushable = false;
    bool destructible = false;
    bool destructible_resolved = false;
    bool dynamic = false;
};

struct SDModCollisionSegment {
    std::uint64_t geometry_id = 0;
    std::uint32_t native_type_id = 0;
    float start_x = 0.0f;
    float start_y = 0.0f;
    float end_x = 0.0f;
    float end_y = 0.0f;
    std::uint32_t mask = 0;
    bool path_blocks = false;
    bool openable = false;
    bool destructible = false;
    bool destructible_resolved = false;
    bool dynamic = false;
};

struct SDModCollisionPolygon {
    std::uint64_t geometry_id = 0;
    std::uint32_t native_type_id = 0;
    float bounds_x = 0.0f;
    float bounds_y = 0.0f;
    float bounds_w = 0.0f;
    float bounds_h = 0.0f;
    bool path_blocks = false;
    bool destructible = false;
    bool destructible_resolved = false;
    bool dynamic = false;
    std::vector<SDModCollisionGeometryPoint> points;
};

struct SDModCollisionParticipantRadius {
    std::uint64_t participant_id = 0;
    float radius = 0.0f;
    bool radius_resolved = false;
};

struct SDModCollisionGeometryState {
    bool valid = false;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t static_revision = 0;
    std::uint32_t dynamic_revision = 0;
    bool refresh_pending = false;
    float observer_radius = 0.0f;
    bool observer_radius_resolved = false;
    float participant_collision_padding = 0.5f;
    std::vector<SDModCollisionCircle> circles;
    std::vector<SDModCollisionSegment> segments;
    std::vector<SDModCollisionPolygon> polygons;
    std::vector<SDModCollisionParticipantRadius> participant_radii;
};
