std::string EscapeSceneJson(std::string_view value) {
    std::ostringstream stream;
    for (const unsigned char character : value) {
        switch (character) {
            case '\\':
                stream << "\\\\";
                break;
            case '"':
                stream << "\\\"";
                break;
            case '\b':
                stream << "\\b";
                break;
            case '\f':
                stream << "\\f";
                break;
            case '\n':
                stream << "\\n";
                break;
            case '\r':
                stream << "\\r";
                break;
            case '\t':
                stream << "\\t";
                break;
            default:
                if (character < 0x20) {
                    stream << "\\u" << std::hex << std::setw(4)
                           << std::setfill('0')
                           << static_cast<unsigned int>(character)
                           << std::dec << std::setfill(' ');
                } else {
                    stream << static_cast<char>(character);
                }
                break;
        }
    }
    return stream.str();
}

void WriteFloat(std::ostream& stream, float value) {
    if (!std::isfinite(value)) {
        stream << "null";
        return;
    }
    stream << std::setprecision(9) << value;
}

template <std::size_t Count>
void WriteFloatArray(
    std::ostream& stream,
    const std::array<float, Count>& values) {
    stream << '[';
    for (std::size_t index = 0; index < Count; ++index) {
        if (index != 0) {
            stream << ',';
        }
        WriteFloat(stream, values[index]);
    }
    stream << ']';
}

void WriteStringArray(
    std::ostream& stream,
    const std::vector<std::string>& values) {
    stream << '[';
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index != 0) {
            stream << ',';
        }
        stream << '"' << EscapeSceneJson(values[index]) << '"';
    }
    stream << ']';
}

void WriteResolvedNativeArt(
    std::ostream& stream,
    const ResolvedNativeArt& art) {
    stream << "{\"id\":\"" << EscapeSceneJson(art.id)
           << "\",\"atlas\":\"" << EscapeSceneJson(art.atlas)
           << "\",\"index\":";
    if (art.sprite_index >= 0) {
        stream << art.sprite_index;
    } else {
        stream << "null";
    }
    stream << ",\"texture_handle\":" << art.texture_handle
           << ",\"resolution\":\""
           << EscapeSceneJson(art.resolution)
           << "\",\"candidates\":";
    WriteStringArray(stream, art.candidates);
    stream << '}';
}

void WriteHudCapture(
    std::ostream& stream,
    const HudCapture& hud) {
    if (!hud.available) {
        stream << "null";
        return;
    }
    stream << "{\"gameplay_address\":" << hud.gameplay_address
           << ",\"actor_address\":" << hud.actor_address
           << ",\"progression_address\":" << hud.progression_address
           << ",\"simulation_tick\":" << hud.simulation_tick
           << ",\"local_dead\":"
           << (hud.local_dead ? "true" : "false")
           << ",\"visibility\":{\"score_indicator\":"
           << (hud.score_indicator_visible ? "true" : "false")
           << ",\"vitals_and_slots\":"
           << (hud.vitals_and_slots_visible ? "true" : "false")
           << ",\"level_up_choice\":"
           << (hud.level_up_choice_active ? "true" : "false")
           << ",\"featured_enemy\":"
           << (hud.featured_enemy_available ? "true" : "false")
           << "},\"health\":{\"current\":";
    WriteFloat(stream, hud.hp);
    stream << ",\"maximum\":";
    WriteFloat(stream, hud.max_hp);
    stream << ",\"magic_shield_current\":";
    WriteFloat(stream, hud.magic_shield_current);
    stream << ",\"magic_shield_maximum\":";
    WriteFloat(stream, hud.magic_shield_maximum);
    stream << "},\"mana\":{\"current\":";
    WriteFloat(stream, hud.mp);
    stream << ",\"maximum\":";
    WriteFloat(stream, hud.max_mp);
    stream << ",\"reserve\":";
    WriteFloat(stream, hud.mana_reserve);
    stream << "},\"progression\":{\"xp\":" << hud.xp
           << ",\"level\":" << hud.level
           << ",\"gold\":" << hud.gold
           << ",\"wave\":";
    if (hud.world_available) {
        stream << hud.wave;
    } else {
        stream << "null";
    }
    stream << "},\"status\":{\"persistent_flags\":"
           << static_cast<unsigned int>(hud.persistent_status_flags)
           << ",\"transient_flags\":"
           << static_cast<unsigned int>(hud.transient_status_flags)
           << ",\"poison_remaining_ticks\":"
           << hud.poison_remaining_ticks
           << ",\"webbed_remaining_ticks\":"
           << hud.webbed_remaining_ticks
           << ",\"damage_x4_remaining_ticks\":"
           << hud.damage_x4_remaining_ticks
           << "},\"ally_bars\":[";
    for (std::size_t index = 0; index < hud.ally_bars.size(); ++index) {
        if (index != 0) {
            stream << ',';
        }
        stream << "{\"glyph\":";
        WriteResolvedNativeArt(stream, hud.ally_bars[index].glyph);
        stream << ",\"health_ratio\":";
        WriteFloat(stream, hud.ally_bars[index].health_ratio);
        stream << '}';
    }
    stream << "],\"strips\":[";
    for (std::size_t index = 0; index < hud.strips.size(); ++index) {
        if (index != 0) {
            stream << ',';
        }
        const auto& strip = hud.strips[index];
        stream << "{\"art\":";
        WriteResolvedNativeArt(stream, strip.art);
        stream << ",\"first_draw_order\":" << strip.first_draw_order
               << ",\"draw_count\":" << strip.draw_count
               << ",\"x\":";
        WriteFloat(stream, strip.x);
        stream << ",\"y\":";
        WriteFloat(stream, strip.y);
        stream << ",\"width\":";
        WriteFloat(stream, strip.width);
        stream << '}';
    }
    stream << "],\"slots\":[";
    for (std::size_t index = 0; index < hud.slots.size(); ++index) {
        if (index != 0) {
            stream << ',';
        }
        const auto& slot = hud.slots[index];
        stream << "{\"draw_order\":" << slot.draw_order
               << ",\"object_address\":" << slot.object_address
               << ",\"kind_id\":" << slot.kind_id
               << ",\"logical_rect\":";
        WriteFloatArray(stream, slot.rect);
        stream << ",\"selection_flag\":"
               << static_cast<unsigned int>(slot.selection_flag)
               << ",\"skill_id\":" << slot.skill_id
               << ",\"item_value\":" << slot.item_value
               << ",\"presentation_value\":";
        WriteFloat(stream, slot.presentation_value);
        stream << ",\"count\":" << slot.count
               << ",\"input_slot\":"
               << static_cast<unsigned int>(slot.input_slot)
               << ",\"cooldown\":";
        if (slot.cooldown_available) {
            stream << "{\"current\":";
            WriteFloat(stream, slot.cooldown_current);
            stream << ",\"capacity\":";
            WriteFloat(stream, slot.cooldown_capacity);
            stream << '}';
        } else {
            stream << "null";
        }
        stream << '}';
    }
    stream << "]}";
}

void WriteExactTextCaptures(
    std::ostream& stream,
    const std::vector<ExactTextCapture>& captures) {
    stream << '[';
    for (std::size_t index = 0; index < captures.size(); ++index) {
        if (index != 0) {
            stream << ',';
        }
        const auto& capture = captures[index];
        stream << "{\"text\":\"" << EscapeSceneJson(capture.text)
               << "\",\"caller\":\"0x" << std::hex
               << std::uppercase << capture.caller_preferred_address
               << std::dec << "\",\"first_draw_order\":"
               << capture.first_draw_order
               << ",\"draw_count\":" << capture.draw_count
               << ",\"screen_rect\":";
        if (capture.draw_count == 0) {
            stream << "null";
        } else {
            WriteFloatArray(stream, capture.screen_rect);
        }
        stream << '}';
    }
    stream << ']';
}

void WriteHexBytes(
    std::ostream& stream,
    const std::vector<std::uint8_t>& values) {
    const auto flags = stream.flags();
    const auto fill = stream.fill();
    stream << '"' << std::hex << std::setfill('0');
    for (const auto value : values) {
        stream << std::setw(2) << static_cast<unsigned int>(value);
    }
    stream << '"';
    stream.flags(flags);
    stream.fill(fill);
}

void WritePlayerAnimationRecord(
    std::ostream& stream,
    const SDModPlayerState& player,
    std::int32_t animation_duration_ticks,
    std::uint32_t render_frame_state,
    const PlayerFixedTickAnimationCapture* fixed_tick) {
    stream << "{\"tick\":" << player.local_player_tick_count
           << ",\"tick_observed_ms\":" << player.local_player_tick_observed_ms
           << ",\"actor_address\":" << player.actor_address
           << ",\"position\":[";
    WriteFloat(stream, player.x);
    stream << ',';
    WriteFloat(stream, player.y);
    stream << "],\"heading\":";
    WriteFloat(stream, player.heading);
    stream << ",\"hp\":";
    WriteFloat(stream, player.hp);
    stream << ",\"movement_intent\":[";
    WriteFloat(stream, player.movement_intent_x);
    stream << ',';
    WriteFloat(stream, player.movement_intent_y);
    stream << ']';
    stream << ",\"anim_drive_state\":"
           << static_cast<unsigned int>(player.anim_drive_state)
           << ",\"animation_duration_ticks\":"
           << animation_duration_ticks
           << ",\"render_frame_state\":"
           << render_frame_state
           << ",\"resolved_animation_state_id\":"
           << player.resolved_animation_state_id
           << ",\"walk_cycle_primary\":";
    WriteFloat(stream, player.walk_cycle_primary);
    stream << ",\"walk_cycle_secondary\":";
    WriteFloat(stream, player.walk_cycle_secondary);
    stream << ",\"render_drive_stride\":";
    WriteFloat(stream, player.render_drive_stride);
    stream << ",\"render_advance_rate\":";
    WriteFloat(stream, player.render_advance_rate);
    stream << ",\"render_advance_phase\":";
    WriteFloat(stream, player.render_advance_phase);
    stream << ",\"render_selection_byte\":"
           << static_cast<unsigned int>(player.render_selection_byte)
           << ",\"render_weapon_type\":"
           << static_cast<unsigned int>(player.render_weapon_type)
           << ",\"render_variant_primary\":"
           << static_cast<unsigned int>(player.render_variant_primary)
           << ",\"render_variant_secondary\":"
           << static_cast<unsigned int>(player.render_variant_secondary)
           << ",\"render_variant_tertiary\":"
           << static_cast<unsigned int>(player.render_variant_tertiary)
           << ",\"render_overlay_phase\":";
    WriteFloat(stream, player.render_drive_move_blend);
    stream << ",\"magic_shield_absorb_remaining\":";
    WriteFloat(stream, player.magic_shield_absorb_remaining);
    stream << ",\"magic_shield_absorb_capacity\":";
    WriteFloat(stream, player.magic_shield_absorb_capacity);
    stream << ",\"magic_shield_hit_flash\":";
    WriteFloat(stream, player.magic_shield_hit_flash);
    if (fixed_tick != nullptr) {
        stream << ",\"action_count\":" << fixed_tick->action_count
               << ",\"action_id\":" << fixed_tick->action_id
               << ",\"action_progress\":";
        WriteFloat(stream, fixed_tick->action_progress);
    }
    stream << '}';
}

void WritePlayerAnimationCapture(
    std::ostream& stream,
    const SceneFrameCapture& frame) {
    if (!frame.player_available) {
        stream << "null";
        return;
    }
    WritePlayerAnimationRecord(
        stream,
        frame.player,
        frame.player_animation_duration_ticks,
        frame.player_render_frame_state,
        nullptr);
}

void WritePlayerFixedTickAnimationCaptures(
    std::ostream& stream,
    const SceneFrameCapture& frame) {
    stream << '[';
    for (std::size_t index = 0;
         index < frame.player_fixed_tick_animation.size();
         ++index) {
        if (index != 0) {
            stream << ',';
        }
        const auto& capture = frame.player_fixed_tick_animation[index];
        WritePlayerAnimationRecord(
            stream,
            capture.player,
            capture.animation_duration_ticks,
            capture.render_frame_state,
            &capture);
    }
    stream << ']';
}

void WriteActorAnimationCaptures(
    std::ostream& stream,
    const SceneFrameCapture& frame) {
    stream << '[';
    for (std::size_t index = 0; index < frame.actors.size(); ++index) {
        if (index != 0) {
            stream << ',';
        }
        const auto& capture = frame.actors[index];
        stream << "{\"actor_address\":" << capture.actor.actor_address
               << ",\"type_id\":" << capture.actor.object_type_id
               << ",\"enemy_type\":" << capture.actor.enemy_type
               << ",\"position\":[";
        WriteFloat(stream, capture.actor.x);
        stream << ',';
        WriteFloat(stream, capture.actor.y);
        stream << "],\"heading\":";
        WriteFloat(stream, capture.heading);
        stream << ",\"hp\":";
        WriteFloat(stream, capture.actor.hp);
        stream << ",\"dead\":"
               << (capture.actor.dead ? "true" : "false")
               << ",\"anim_drive_state\":"
               << static_cast<unsigned int>(capture.actor.anim_drive_state)
               << ",\"action_available\":"
               << (capture.action_available ? "true" : "false")
               << ",\"action_count\":" << capture.action_count
               << ",\"action_id\":" << capture.action_id
               << ",\"action_progress\":";
        WriteFloat(stream, capture.action_progress);
        stream << ",\"presentation_window_offset\":288,"
               << "\"presentation_bytes\":";
        WriteHexBytes(stream, capture.presentation_bytes);
        stream << '}';
    }
    stream << ']';
}

void WriteSortCapture(std::ostream& stream, const SortCapture& sort) {
    if (!sort.present) {
        stream << "null";
        return;
    }
    stream << "{\"lane\":\"" << EscapeSceneJson(sort.lane)
           << "\",\"gather_index\":" << sort.gather_index
           << ",\"pass\":" << sort.pass
           << ",\"queue_origin\":" << sort.queue_origin
           << ",\"queue_bucket_count\":" << sort.queue_bucket_count
           << ",\"reference_y\":" << sort.reference_y
           << ",\"world_y\":";
    WriteFloat(stream, sort.world_y);
    stream << ",\"sort_bias\":";
    WriteFloat(stream, sort.sort_bias);
    stream << ",\"floor_world_y\":" << sort.floor_world_y
           << ",\"floor_sort_bias\":" << sort.floor_sort_bias
           << ",\"relative\":" << sort.relative
           << ",\"bucket_offset\":" << sort.bucket_offset
           << ",\"bucket_index\":" << sort.bucket_index << '}';
}

void WriteDrawCapture(std::ostream& stream, const DrawCapture& draw) {
    stream << "    {\n"
           << "      \"draw_order\": " << draw.order << ",\n"
           << "      \"layer\": \"" << EscapeSceneJson(draw.layer)
           << "\",\n"
           << "      \"semantic_role\": \""
           << EscapeSceneJson(draw.semantic_role) << "\",\n"
           << "      \"native_phase\": \""
           << EscapeSceneJson(draw.phase) << "\",\n"
           << "      \"draw_kind\": \""
           << EscapeSceneJson(draw.draw_kind) << "\",\n"
           << "      \"caller\": \"0x" << std::hex << std::uppercase
           << draw.caller_preferred_address << std::dec << "\",\n"
           << "      \"sprite\": {\"id\": \""
           << EscapeSceneJson(draw.art.id) << "\", \"atlas\": \""
           << EscapeSceneJson(draw.art.atlas) << "\", \"index\": ";
    if (draw.art.sprite_index >= 0) {
        stream << draw.art.sprite_index;
    } else {
        stream << "null";
    }
    stream << ", \"texture_handle\": " << draw.art.texture_handle
           << ", \"resolution\": \""
           << EscapeSceneJson(draw.art.resolution)
           << "\", \"candidates\": ";
    WriteStringArray(stream, draw.art.candidates);
    stream << "},\n      \"world_transform\": {\"space\": \""
           << ((draw.layer == "framebuffer-clear" ||
                draw.layer == "screen-overlay")
                   ? "screen"
                   : "world")
           << "\", \"kind\": \""
           << EscapeSceneJson(draw.transform_kind)
           << "\", \"submitted_position\": ";
    WriteFloatArray(stream, draw.submitted_position);
    stream << ", \"matrix\": ";
    if (draw.transform_kind == "matrix4x4") {
        WriteFloatArray(stream, draw.submitted_matrix);
    } else {
        stream << "null";
    }
    stream << ", \"inverse_projected_quad\": ";
    if (draw.layer == "framebuffer-clear" ||
        draw.layer == "screen-overlay") {
        stream << "null";
    } else {
        WriteFloatArray(stream, draw.inverse_projected_world_quad);
    }
    stream << ", \"object\": ";
    if (draw.object_type == 0 && !draw.sort.present) {
        stream << "null";
    } else {
        stream << "{\"address\":" << draw.object_address
               << ",\"type_id\":" << draw.object_type
               << ",\"x\":";
        WriteFloat(stream, draw.object_world_x);
        stream << ",\"y\":";
        WriteFloat(stream, draw.object_world_y);
        stream << '}';
    }
    stream << "},\n      \"tint\": {\"r\": ";
    WriteFloat(stream, draw.tint[0]);
    stream << ", \"g\": ";
    WriteFloat(stream, draw.tint[1]);
    stream << ", \"b\": ";
    WriteFloat(stream, draw.tint[2]);
    stream << ", \"a\": ";
    WriteFloat(stream, draw.tint[3]);
    stream << "},\n      \"lighting_scalar\": ";
    if (draw.has_lighting_scalar) {
        WriteFloat(stream, draw.lighting_scalar);
    } else {
        stream << "null";
    }
    stream << ",\n      \"blend\": ";
    if (!draw.blend.available) {
        stream << "null";
    } else {
        stream << "{\"enabled\":"
               << (draw.blend.enabled != FALSE ? "true" : "false")
               << ",\"source\":" << draw.blend.source
               << ",\"destination\":" << draw.blend.destination
               << ",\"operation\":" << draw.blend.operation << '}';
    }
    stream << ",\n      \"resolved_screen_quad\": ";
    WriteFloatArray(stream, draw.screen_quad);
    stream << ",\n      \"resolved_screen_rect\": ";
    WriteFloatArray(stream, draw.screen_rect);
    stream << ",\n      \"clipped_screen_rect\": ";
    WriteFloatArray(stream, draw.clipped_screen_rect);
    stream << ",\n      \"visible\": "
           << (draw.visible ? "true" : "false")
           << ",\n      \"sort_key\": ";
    WriteSortCapture(stream, draw.sort);
    stream << "\n    }";
}

bool WriteNativeSceneCaptureFile(std::string* error_message) {
    const auto output = g_scene_capture.directory /
        (g_scene_capture.frame.label + ".json");
    const auto temporary = g_scene_capture.directory /
        (g_scene_capture.frame.label + ".json.tmp");
    if (std::filesystem::exists(output) ||
        std::filesystem::exists(temporary)) {
        if (error_message != nullptr) {
            *error_message =
                "native scene capture refuses to overwrite an existing output or temporary file";
        }
        return false;
    }

    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    if (!stream) {
        if (error_message != nullptr) {
            *error_message =
                "native scene capture could not create its temporary output";
        }
        return false;
    }

    const auto& frame = g_scene_capture.frame;
    stream << "{\n"
           << "  \"schema\": \"solomon-dark-native-scene-capture-v1\",\n"
           << "  \"capture_method\": \""
           << (frame.surface == CaptureSurface::Hud
                   ? "native Gameplay HUD render + belt slot + exact text + Glyph/TextQuad/quad hooks"
                   : "native Region render + queue insertion/flush + Glyph/TextQuad + mesh/quad hooks")
           << "\",\n"
           << "  \"surface\": \""
           << CaptureSurfaceLabel(frame.surface) << "\",\n"
           << "  \"instance\": \"" << EscapeSceneJson(frame.instance)
           << "\",\n"
           << "  \"label\": \"" << EscapeSceneJson(frame.label)
           << "\",\n"
           << "  \"render_sequence_index\": " << frame.sequence_index
           << ",\n  \"render_observed_ms\": " << frame.render_observed_ms
           << ",\n  \"player_animation\": ";
    WritePlayerAnimationCapture(stream, frame);
    stream << ",\n  \"player_fixed_tick_animation\": ";
    WritePlayerFixedTickAnimationCaptures(stream, frame);
    stream << ",\n  \"tracked_enemy_animation\": ";
    WriteActorAnimationCaptures(stream, frame);
    stream << ",\n  \"hud_state\": ";
    WriteHudCapture(stream, frame.hud);
    stream << ",\n  \"exact_text\": ";
    WriteExactTextCaptures(stream, frame.exact_text);
    stream << ",\n"
           << "  \"scene\": {\"kind\": \""
           << EscapeSceneJson(frame.scene_kind) << "\"},\n"
           << "  \"epsilon\": {\"screen_pixels\": 0.001, \"world_units\": 0.001, \"reason\": \"live float32/x87 submissions are serialized to 9 significant digits; 0.001 is below one native pixel and exceeds only representation noise\"},\n"
           << "  \"layer_order\": [\"framebuffer-clear\",\"scene-underlay\",\"world-sorted\",\"scene-overdraw\",\"screen-overlay\"],\n"
           << "  \"camera\": {\"scale\": ";
    WriteFloat(stream, frame.camera.scale);
    stream << ", \"world_bounds\": ";
    WriteFloatArray(stream, frame.camera.world_bounds);
    stream << ", \"primary_view\": ";
    WriteFloatArray(stream, frame.camera.primary_view);
    stream << ", \"expanded_view\": ";
    WriteFloatArray(stream, frame.camera.expanded_view);
    stream << ", \"culling_view\": ";
    WriteFloatArray(stream, frame.camera.culling_view);
    stream << ", \"shake_magnitude\": ";
    WriteFloat(stream, frame.camera.shake_magnitude);
    stream << ", \"shake_accumulator\": ";
    WriteFloat(stream, frame.camera.shake_accumulator);
    stream << "},\n  \"draws\": [\n";
    for (std::size_t index = 0; index < frame.draws.size(); ++index) {
        if (index != 0) {
            stream << ",\n";
        }
        WriteDrawCapture(stream, frame.draws[index]);
    }
    stream << "\n  ]\n}\n";
    stream.flush();
    if (!stream) {
        stream.close();
        std::error_code ignored;
        (void)std::filesystem::remove(temporary, ignored);
        if (error_message != nullptr) {
            *error_message =
                "native scene capture failed while writing its temporary output";
        }
        return false;
    }
    stream.close();
    if (!MoveFileExW(
            temporary.c_str(),
            output.c_str(),
            MOVEFILE_WRITE_THROUGH)) {
        std::error_code ignored;
        (void)std::filesystem::remove(temporary, ignored);
        if (error_message != nullptr) {
            *error_message =
                "native scene capture could not atomically publish its output";
        }
        return false;
    }
    g_scene_capture.output_path = output.u8string();
    return true;
}
