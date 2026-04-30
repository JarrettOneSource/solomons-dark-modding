void FillBotSnapshot(const ParticipantInfo& participant, BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return;
    }

    snapshot->available = true;
    snapshot->bot_id = participant.participant_id;
    snapshot->display_name = participant.name;
    snapshot->participant_kind = participant.kind;
    snapshot->controller_kind = participant.controller_kind;
    snapshot->character_profile = participant.character_profile;
    snapshot->ready = participant.ready;
    snapshot->in_run = participant.runtime.in_run;
    snapshot->runtime_valid = participant.runtime.valid;
    snapshot->transform_valid = participant.runtime.transform_valid;
    snapshot->run_nonce = participant.runtime.run_nonce;
    snapshot->scene_intent = participant.runtime.scene_intent;
    snapshot->position_x = participant.runtime.position_x;
    snapshot->position_y = participant.runtime.position_y;
    snapshot->heading = participant.runtime.heading;
    if (const auto* pending_cast = FindPendingCast(participant.participant_id); pending_cast != nullptr) {
        snapshot->cast_pending = true;
        snapshot->queued_cast_count = pending_cast->queued_cast_count;
        snapshot->last_queued_cast_ms = pending_cast->queued_at_ms;
    }
    if (const auto* pending_choice = FindPendingSkillChoiceConst(participant.participant_id);
        pending_choice != nullptr) {
        snapshot->skill_choice_pending = true;
        snapshot->skill_choice_generation = pending_choice->generation;
        snapshot->skill_choice_level = pending_choice->level;
        snapshot->skill_choice_experience = pending_choice->experience;
        snapshot->skill_choice_options = pending_choice->options;
    }
}

void DeriveBotCastReadiness(BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return;
    }

    const bool dead = snapshot->max_hp > 0.0f && snapshot->hp <= 0.0f;
    const auto cast_mana = ResolveBotCastManaCost(
        snapshot->character_profile,
        BotCastKind::Primary,
        -1,
        0);
    const float required_mana = ResolveBotManaRequiredToStart(cast_mana);
    const bool mana_ready =
        cast_mana.resolved &&
        (cast_mana.kind == BotManaChargeKind::None ||
         snapshot->max_mp <= 0.0f ||
         snapshot->mp + 0.001f >= required_mana);
    snapshot->cast_ready =
        snapshot->available &&
        snapshot->entity_materialized &&
        snapshot->actor_address != 0 &&
        !dead &&
        mana_ready &&
        !snapshot->cast_pending &&
        !snapshot->cast_active;
}

void ApplyGameplayStateToSnapshot(std::uint64_t bot_id, BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return;
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(bot_id, &gameplay_state) || !gameplay_state.available) {
        return;
    }

    snapshot->entity_materialized = gameplay_state.entity_materialized;
    snapshot->moving = gameplay_state.moving;
    snapshot->actor_address = gameplay_state.actor_address;
    snapshot->world_address = gameplay_state.world_address;
    snapshot->animation_state_ptr = gameplay_state.animation_state_ptr;
    snapshot->render_frame_table = gameplay_state.render_frame_table;
    snapshot->hub_visual_attachment_ptr = gameplay_state.hub_visual_attachment_ptr;
    snapshot->hub_visual_source_profile_address = gameplay_state.hub_visual_source_profile_address;
    snapshot->hub_visual_descriptor_signature = gameplay_state.hub_visual_descriptor_signature;
    snapshot->hub_visual_proxy_address = gameplay_state.hub_visual_proxy_address;
    snapshot->progression_handle_address = gameplay_state.progression_handle_address;
    snapshot->equip_handle_address = gameplay_state.equip_handle_address;
    snapshot->progression_runtime_state_address = gameplay_state.progression_runtime_state_address;
    snapshot->equip_runtime_state_address = gameplay_state.equip_runtime_state_address;
    snapshot->gameplay_slot = gameplay_state.gameplay_slot;
    snapshot->actor_slot = gameplay_state.actor_slot;
    snapshot->slot_anim_state_index = gameplay_state.slot_anim_state_index;
    snapshot->resolved_animation_state_id = gameplay_state.resolved_animation_state_id;
    snapshot->hub_visual_source_kind = gameplay_state.hub_visual_source_kind;
    snapshot->render_drive_flags = gameplay_state.render_drive_flags;
    snapshot->anim_drive_state = gameplay_state.anim_drive_state;
    snapshot->no_interrupt = gameplay_state.no_interrupt;
    snapshot->active_cast_group = gameplay_state.active_cast_group;
    snapshot->active_cast_slot = gameplay_state.active_cast_slot;
    snapshot->render_variant_primary = gameplay_state.render_variant_primary;
    snapshot->render_variant_secondary = gameplay_state.render_variant_secondary;
    snapshot->render_weapon_type = gameplay_state.render_weapon_type;
    snapshot->render_selection_byte = gameplay_state.render_selection_byte;
    snapshot->render_variant_tertiary = gameplay_state.render_variant_tertiary;
    snapshot->cast_active = gameplay_state.cast_active;
    snapshot->cast_startup_in_progress = gameplay_state.cast_startup_in_progress;
    snapshot->cast_saw_activity = gameplay_state.cast_saw_activity;
    snapshot->cast_skill_id = gameplay_state.cast_skill_id;
    snapshot->cast_ticks_waiting = gameplay_state.cast_ticks_waiting;
    snapshot->cast_target_actor_address = gameplay_state.cast_target_actor_address;
    snapshot->walk_cycle_primary = gameplay_state.walk_cycle_primary;
    snapshot->walk_cycle_secondary = gameplay_state.walk_cycle_secondary;
    snapshot->render_drive_stride = gameplay_state.render_drive_stride;
    snapshot->render_advance_rate = gameplay_state.render_advance_rate;
    snapshot->render_advance_phase = gameplay_state.render_advance_phase;
    snapshot->render_drive_overlay_alpha = gameplay_state.render_drive_overlay_alpha;
    snapshot->render_drive_move_blend = gameplay_state.render_drive_move_blend;
    snapshot->gameplay_attach_applied = gameplay_state.gameplay_attach_applied;
    CopyEquipVisualLaneState(gameplay_state.primary_visual_lane, &snapshot->primary_visual_lane);
    CopyEquipVisualLaneState(gameplay_state.secondary_visual_lane, &snapshot->secondary_visual_lane);
    CopyEquipVisualLaneState(gameplay_state.attachment_visual_lane, &snapshot->attachment_visual_lane);

    if (!gameplay_state.entity_materialized) {
        return;
    }

    snapshot->runtime_valid = true;
    snapshot->transform_valid = true;
    snapshot->position_x = gameplay_state.x;
    snapshot->position_y = gameplay_state.y;
    snapshot->heading = gameplay_state.heading;
    snapshot->hp = gameplay_state.hp;
    snapshot->max_hp = gameplay_state.max_hp;
    snapshot->mp = gameplay_state.mp;
    snapshot->max_mp = gameplay_state.max_mp;
    snapshot->in_run = true;
}

void ApplyControllerStateToSnapshot(std::uint64_t bot_id, BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return;
    }

    if (const auto* controller = FindPendingMovementIntent(bot_id); controller != nullptr) {
        snapshot->state = controller->state;
        snapshot->moving = controller->state == BotControllerState::Moving;
        snapshot->has_target = controller->has_target;
        snapshot->target_x = controller->target_x;
        snapshot->target_y = controller->target_y;
        snapshot->distance_to_target = controller->distance_to_target;
    }
}
