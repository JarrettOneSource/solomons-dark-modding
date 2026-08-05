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
        stream << "{\"type_id\":" << draw.object_type
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
           << "  \"capture_method\": \"native Region render + queue insertion/flush + Glyph/TextQuad + mesh/quad hooks\",\n"
           << "  \"instance\": \"" << EscapeSceneJson(frame.instance)
           << "\",\n"
           << "  \"label\": \"" << EscapeSceneJson(frame.label)
           << "\",\n"
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
