void CopyEquipVisualLaneState(
    const SDModEquipVisualLaneState& source,
    BotEquipVisualLaneState* destination) {
    if (destination == nullptr) {
        return;
    }

    destination->wrapper_address = source.wrapper_address;
    destination->holder_address = source.holder_address;
    destination->current_object_address = source.current_object_address;
    destination->holder_kind = source.holder_kind;
    destination->current_object_vtable = source.current_object_vtable;
    destination->current_object_type_id = source.current_object_type_id;
}

BotLoadoutInfo DefaultBotLoadout() {
    return BotLoadoutInfo{};
}

std::string DefaultBotName(std::uint64_t bot_id) {
    return "Lua Bot " + std::to_string(bot_id - kFirstLuaBotParticipantId + 1ull);
}

const char* BotControllerStateLabelInternal(BotControllerState state) {
    switch (state) {
        case BotControllerState::Idle:
            return "idle";
        case BotControllerState::Moving:
            return "moving";
        case BotControllerState::Attacking:
            return "attacking";
    }

    return "idle";
}

PendingBotCast* FindPendingCast(std::uint64_t bot_id) {
    const auto it = std::find_if(g_pending_casts.begin(), g_pending_casts.end(), [&](const PendingBotCast& cast) {
        return cast.bot_id == bot_id;
    });
    return it == g_pending_casts.end() ? nullptr : &(*it);
}

void RemovePendingCast(std::uint64_t bot_id) {
    g_pending_casts.erase(
        std::remove_if(g_pending_casts.begin(), g_pending_casts.end(), [&](const PendingBotCast& cast) {
            return cast.bot_id == bot_id;
        }),
        g_pending_casts.end());
}

PendingBotEntitySync* FindPendingEntitySync(std::uint64_t bot_id) {
    const auto it = std::find_if(g_pending_entity_syncs.begin(), g_pending_entity_syncs.end(), [&](const PendingBotEntitySync& sync) {
        return sync.bot_id == bot_id;
    });
    return it == g_pending_entity_syncs.end() ? nullptr : &(*it);
}

void RemovePendingEntitySync(std::uint64_t bot_id) {
    g_pending_entity_syncs.erase(
        std::remove_if(g_pending_entity_syncs.begin(), g_pending_entity_syncs.end(), [&](const PendingBotEntitySync& sync) {
            return sync.bot_id == bot_id;
        }),
        g_pending_entity_syncs.end());
}

PendingBotMovementIntent* FindPendingMovementIntent(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_bot_movement_intents.begin(),
        g_bot_movement_intents.end(),
        [&](const PendingBotMovementIntent& intent) {
            return intent.bot_id == bot_id;
        });
    return it == g_bot_movement_intents.end() ? nullptr : &(*it);
}

void RemovePendingMovementIntent(std::uint64_t bot_id) {
    g_bot_movement_intents.erase(
        std::remove_if(
            g_bot_movement_intents.begin(),
            g_bot_movement_intents.end(),
            [&](const PendingBotMovementIntent& intent) {
                return intent.bot_id == bot_id;
            }),
        g_bot_movement_intents.end());
}

PendingBotDestroy* FindPendingDestroy(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_pending_destroys.begin(),
        g_pending_destroys.end(),
        [&](const PendingBotDestroy& pending_destroy) {
            return pending_destroy.bot_id == bot_id;
        });
    return it == g_pending_destroys.end() ? nullptr : &(*it);
}

void RemovePendingDestroy(std::uint64_t bot_id) {
    g_pending_destroys.erase(
        std::remove_if(
            g_pending_destroys.begin(),
            g_pending_destroys.end(),
            [&](const PendingBotDestroy& pending_destroy) {
                return pending_destroy.bot_id == bot_id;
            }),
        g_pending_destroys.end());
}

ParticipantInfo* FindBot(RuntimeState& state, std::uint64_t bot_id) {
    auto* participant = FindParticipant(state, bot_id);
    return participant != nullptr && IsLuaBotParticipant(*participant) ? participant : nullptr;
}

const ParticipantInfo* FindBot(const RuntimeState& state, std::uint64_t bot_id) {
    const auto* participant = FindParticipant(state, bot_id);
    return participant != nullptr && IsLuaBotParticipant(*participant) ? participant : nullptr;
}

void FillBotSnapshot(const ParticipantInfo& participant, BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return;
    }

    snapshot->available = true;
    snapshot->bot_id = participant.participant_id;
    snapshot->display_name = participant.name;
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
        snapshot->queued_cast_count = pending_cast->queued_cast_count;
        snapshot->last_queued_cast_ms = pending_cast->queued_at_ms;
    }
}

void ApplyGameplayStateToSnapshot(std::uint64_t bot_id, BotSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return;
    }

    SDModBotGameplayState gameplay_state;
    if (!TryGetWizardBotGameplayState(bot_id, &gameplay_state) || !gameplay_state.available) {
        return;
    }

    snapshot->runtime_valid = snapshot->runtime_valid || gameplay_state.entity_materialized;
    snapshot->transform_valid = snapshot->transform_valid || gameplay_state.entity_materialized;
    snapshot->entity_materialized = gameplay_state.entity_materialized;
    snapshot->position_x = gameplay_state.x;
    snapshot->position_y = gameplay_state.y;
    snapshot->heading = gameplay_state.heading;
    snapshot->hp = gameplay_state.hp;
    snapshot->max_hp = gameplay_state.max_hp;
    snapshot->mp = gameplay_state.mp;
    snapshot->max_mp = gameplay_state.max_mp;
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
    snapshot->render_variant_primary = gameplay_state.render_variant_primary;
    snapshot->render_variant_secondary = gameplay_state.render_variant_secondary;
    snapshot->render_weapon_type = gameplay_state.render_weapon_type;
    snapshot->render_selection_byte = gameplay_state.render_selection_byte;
    snapshot->render_variant_tertiary = gameplay_state.render_variant_tertiary;
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

float NormalizeHeadingDegrees(float heading_degrees) {
    if (!std::isfinite(heading_degrees)) {
        return 0.0f;
    }

    while (heading_degrees < 0.0f) {
        heading_degrees += 360.0f;
    }
    while (heading_degrees >= 360.0f) {
        heading_degrees -= 360.0f;
    }
    return heading_degrees;
}

void DeriveControllerMotionFromTransform(
    PendingBotMovementIntent* intent,
    bool have_transform,
    float current_x,
    float current_y,
    float current_heading) {
    if (intent == nullptr) {
        return;
    }

    intent->direction_x = 0.0f;
    intent->direction_y = 0.0f;
    intent->distance_to_target = 0.0f;
    if (!intent->desired_heading_valid && have_transform) {
        intent->desired_heading_valid = true;
        intent->desired_heading = current_heading;
    }

    if (intent->state == BotControllerState::Moving) {
        if (!intent->has_target) {
            intent->state = BotControllerState::Idle;
            return;
        }
        if (!have_transform) {
            return;
        }

        const auto delta_x = intent->target_x - current_x;
        const auto delta_y = intent->target_y - current_y;
        const auto distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
        intent->distance_to_target = distance;
        if (distance <= kBotArrivalThreshold) {
            intent->state = BotControllerState::Idle;
            intent->has_target = false;
            intent->target_x = current_x;
            intent->target_y = current_y;
            intent->distance_to_target = 0.0f;
            intent->desired_heading_valid = true;
            intent->desired_heading = current_heading;
            return;
        }

        // Final-destination ownership now lives in runtime, but actual path
        // generation and per-step steering live on the gameplay thread.
        // Runtime keeps the destination and the remaining distance current so
        // gameplay can rebuild paths when the intent revision changes.
        intent->direction_x = 0.0f;
        intent->direction_y = 0.0f;
        intent->desired_heading_valid = true;
        intent->desired_heading = current_heading;
        return;
    }

    if (intent->state != BotControllerState::Attacking) {
        intent->state = BotControllerState::Idle;
    }
}

bool IsValidCreateRequest(const BotCreateRequest& request) {
    return
        IsValidCharacterProfile(request.character_profile) &&
        (!request.has_scene_intent || IsValidParticipantSceneIntent(request.scene_intent));
}

bool IsValidUpdateRequest(const BotUpdateRequest& request) {
    return request.bot_id != 0 &&
        (!request.has_scene_intent || IsValidParticipantSceneIntent(request.scene_intent));
}

bool IsValidCastRequest(const BotCastRequest& request) {
    if (request.bot_id == 0) {
        return false;
    }

    if (request.kind == BotCastKind::Secondary &&
        (request.secondary_slot < 0 || request.secondary_slot >= static_cast<std::int32_t>(DefaultBotLoadout().secondary_skill_ids.size()))) {
        return false;
    }

    return true;
}

bool IsValidMoveRequest(const BotMoveToRequest& request) {
    if (request.bot_id == 0) {
        return false;
    }

    return std::isfinite(request.target_x) && std::isfinite(request.target_y);
}

ParticipantSceneIntent ResolveDefaultBotSceneIntentFromCurrentScene() {
    ParticipantSceneIntent scene_intent = DefaultParticipantSceneIntent();

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return scene_intent;
    }

    if (scene_state.name == "testrun" || scene_state.kind == "arena") {
        scene_intent.kind = ParticipantSceneIntentKind::Run;
        scene_intent.region_index = scene_state.current_region_index;
        scene_intent.region_type_id = scene_state.region_type_id;
        return scene_intent;
    }

    if (scene_state.name == "hub" || scene_state.kind == "hub") {
        scene_intent.kind = ParticipantSceneIntentKind::SharedHub;
        scene_intent.region_index = scene_state.current_region_index;
        scene_intent.region_type_id = scene_state.region_type_id;
        return scene_intent;
    }

    scene_intent.kind = ParticipantSceneIntentKind::PrivateRegion;
    scene_intent.region_index = scene_state.current_region_index;
    scene_intent.region_type_id = scene_state.region_type_id;
    return scene_intent;
}

void ApplyTransform(
    ParticipantInfo* participant,
    float position_x,
    float position_y,
    bool has_heading,
    float heading) {
    if (participant == nullptr) {
        return;
    }

    participant->runtime.valid = true;
    participant->runtime.transform_valid = true;
    participant->runtime.position_x = position_x;
    participant->runtime.position_y = position_y;
    if (has_heading) {
        participant->runtime.heading = heading;
    }
}

void ApplyLoadout(ParticipantInfo* participant, const BotLoadoutInfo& loadout) {
    if (participant == nullptr) {
        return;
    }

    participant->runtime.primary_skill_id = loadout.primary_skill_id;
    participant->runtime.primary_combo_id = loadout.primary_combo_id;
    participant->runtime.queued_secondary_ids = loadout.secondary_skill_ids;
}

void ApplySceneIntent(ParticipantInfo* participant, const ParticipantSceneIntent& scene_intent) {
    if (participant == nullptr) {
        return;
    }

    participant->runtime.scene_intent = scene_intent;
    participant->runtime.in_run = scene_intent.kind == ParticipantSceneIntentKind::Run;
}

void ApplyCharacterProfile(ParticipantInfo* participant, const MultiplayerCharacterProfile& profile) {
    if (participant == nullptr) {
        return;
    }

    participant->character_profile = profile;
    participant->runtime.level = profile.level;
    participant->runtime.experience_current = profile.experience;
    ApplyLoadout(participant, profile.loadout);
}

void ResetPendingState() {
    g_pending_casts.clear();
    g_pending_entity_syncs.clear();
    g_bot_movement_intents.clear();
    g_pending_destroys.clear();
    g_next_cast_sequence = 1;
    g_next_entity_sync_generation = 1;
    g_next_movement_intent_revision = 1;
    g_next_destroy_generation = 1;
}

void DestroyAllBotsLocked() {
    UpdateRuntimeState([](RuntimeState& state) {
        state.participants.erase(
            std::remove_if(state.participants.begin(), state.participants.end(), [](const ParticipantInfo& participant) {
                return IsLuaBotParticipant(participant);
            }),
            state.participants.end());
    });

    ResetPendingState();
}

void SchedulePendingEntitySyncLocked(
    std::uint64_t bot_id,
    const MultiplayerCharacterProfile& character_profile,
    const ParticipantSceneIntent& scene_intent,
    bool has_transform,
    bool has_heading,
    float position_x,
    float position_y,
    float heading,
    std::uint64_t now_ms) {
    auto* pending_sync = FindPendingEntitySync(bot_id);
    if (pending_sync == nullptr) {
        g_pending_entity_syncs.push_back(PendingBotEntitySync{});
        pending_sync = &g_pending_entity_syncs.back();
        pending_sync->bot_id = bot_id;
    }

    pending_sync->generation = g_next_entity_sync_generation++;
    pending_sync->character_profile = character_profile;
    pending_sync->scene_intent = scene_intent;
    pending_sync->has_transform = has_transform;
    pending_sync->has_heading = has_heading;
    pending_sync->position_x = position_x;
    pending_sync->position_y = position_y;
    pending_sync->heading = heading;
    pending_sync->next_attempt_ms = now_ms;
}

void SchedulePendingMovementIntentLocked(
    std::uint64_t bot_id,
    BotControllerState state,
    bool has_target,
    float target_x,
    float target_y,
    bool desired_heading_valid,
    float desired_heading) {
    auto* pending_intent = FindPendingMovementIntent(bot_id);
    if (pending_intent == nullptr) {
        g_bot_movement_intents.push_back(PendingBotMovementIntent{});
        pending_intent = &g_bot_movement_intents.back();
        pending_intent->bot_id = bot_id;
    }

    pending_intent->revision = g_next_movement_intent_revision++;
    pending_intent->state = state;
    pending_intent->has_target = has_target;
    pending_intent->target_x = target_x;
    pending_intent->target_y = target_y;
    pending_intent->distance_to_target = 0.0f;
    pending_intent->direction_x = 0.0f;
    pending_intent->direction_y = 0.0f;
    pending_intent->desired_heading_valid = desired_heading_valid;
    pending_intent->desired_heading = desired_heading;
}

void SchedulePendingDestroyLocked(std::uint64_t bot_id) {
    auto* pending_destroy = FindPendingDestroy(bot_id);
    if (pending_destroy == nullptr) {
        g_pending_destroys.push_back(PendingBotDestroy{});
        pending_destroy = &g_pending_destroys.back();
        pending_destroy->bot_id = bot_id;
    }

    pending_destroy->generation = g_next_destroy_generation++;
}

bool TryDispatchEntitySync(
    std::uint64_t bot_id,
    const MultiplayerCharacterProfile& character_profile,
    const ParticipantSceneIntent& scene_intent,
    bool has_transform,
    bool has_heading,
    float position_x,
    float position_y,
    float heading,
    std::string* error_message) {
    return QueueWizardBotEntitySync(
        bot_id,
        character_profile,
        scene_intent,
        has_transform,
        has_heading,
        position_x,
        position_y,
        heading,
        error_message);
}

bool TryDispatchDestroy(std::uint64_t bot_id, std::string* error_message) {
    return QueueWizardBotDestroy(bot_id, error_message);
}
