struct SceneContextSnapshot {
    uintptr_t gameplay_scene_address = 0;
    uintptr_t world_address = 0;
    uintptr_t arena_address = 0;
    uintptr_t region_state_address = 0;
    int current_region_index = -1;
    int region_type_id = -1;
};

struct ParticipantRematerializationRequest {
    std::uint64_t bot_id = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
    bool has_transform = false;
    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    uintptr_t previous_scene_address = 0;
    uintptr_t previous_world_address = 0;
    int previous_region_index = -1;
    uintptr_t next_scene_address = 0;
    uintptr_t next_world_address = 0;
    int next_region_index = -1;
};

struct ParticipantGameplaySnapshot {
    std::uint64_t bot_id = 0;
    bool entity_materialized = false;
    bool moving = false;
    int entity_kind = kSDModParticipantGameplayKindUnknown;
    std::uint64_t movement_intent_revision = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
    uintptr_t actor_address = 0;
    uintptr_t world_address = 0;
    uintptr_t animation_state_ptr = 0;
    uintptr_t render_frame_table = 0;
    uintptr_t hub_visual_attachment_ptr = 0;
    uintptr_t hub_visual_proxy_address = 0;
    uintptr_t hub_visual_source_profile_address = 0;
    uintptr_t progression_handle_address = 0;
    uintptr_t equip_handle_address = 0;
    uintptr_t progression_runtime_state_address = 0;
    uintptr_t equip_runtime_state_address = 0;
    int gameplay_slot = -1;
    int actor_slot = -1;
    int slot_anim_state_index = -1;
    int resolved_animation_state_id = kUnknownAnimationStateId;
    int hub_visual_source_kind = 0;
    std::uint32_t hub_visual_descriptor_signature = 0;
    std::uint32_t render_drive_flags = 0;
    std::uint8_t anim_drive_state = 0;
    std::uint8_t no_interrupt = 0;
    std::uint8_t active_cast_group = 0xFF;
    std::uint16_t active_cast_slot = 0xFFFF;
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
    bool cast_active = false;
    bool cast_startup_in_progress = false;
    bool cast_saw_activity = false;
    std::int32_t cast_skill_id = 0;
    int cast_ticks_waiting = 0;
    uintptr_t cast_target_actor_address = 0;
    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
    float render_advance_phase = 0.0f;
    float render_drive_overlay_alpha = 0.0f;
    float render_drive_move_blend = 0.0f;
    bool gameplay_attach_applied = false;
    SDModEquipVisualLaneState primary_visual_lane;
    SDModEquipVisualLaneState secondary_visual_lane;
    SDModEquipVisualLaneState attachment_visual_lane;
};

SDModEquipVisualLaneState ReadEquipVisualLaneState(
    uintptr_t equip_runtime_state_address,
    std::size_t lane_offset) {
    SDModEquipVisualLaneState lane;
    if (equip_runtime_state_address == 0) {
        return lane;
    }

    auto& memory = ProcessMemory::Instance();
    lane.wrapper_address =
        memory.ReadFieldOr<uintptr_t>(equip_runtime_state_address, lane_offset, 0);
    if (lane.wrapper_address == 0) {
        return lane;
    }

    lane.holder_address = memory.ReadValueOr<uintptr_t>(lane.wrapper_address, 0);
    if (lane.holder_address == 0) {
        return lane;
    }

    lane.holder_kind =
        memory.ReadFieldOr<std::uint32_t>(lane.holder_address, kVisualLaneHolderKindOffset, 0);
    lane.current_object_address = memory.ReadFieldOr<uintptr_t>(
        lane.holder_address,
        kVisualLaneHolderCurrentObjectOffset,
        0);
    if (lane.current_object_address == 0) {
        return lane;
    }

    lane.current_object_vtable =
        memory.ReadValueOr<uintptr_t>(lane.current_object_address, 0);
    lane.current_object_type_id = memory.ReadFieldOr<std::uint32_t>(
        lane.current_object_address,
        kGameObjectTypeIdOffset,
        0);
    return lane;
}

void AppendEquipVisualLaneSummary(
    std::ostringstream* out,
    std::string_view label,
    const SDModEquipVisualLaneState& lane) {
    if (out == nullptr) {
        return;
    }

    *out << " " << label
         << "{wrapper=" << HexString(lane.wrapper_address)
         << " holder=" << HexString(lane.holder_address)
         << " kind=" << lane.holder_kind
         << " object=" << HexString(lane.current_object_address)
         << " vtbl=" << HexString(lane.current_object_vtable)
         << " type=0x" << HexString(static_cast<uintptr_t>(lane.current_object_type_id))
         << "}";
}
