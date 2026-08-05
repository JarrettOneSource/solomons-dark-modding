std::string SerializeTraceLocked(
    const NativeInputTraceState& state,
    bool active) {
    std::ostringstream output;
    output << std::setprecision(std::numeric_limits<float>::max_digits10);
    output << "{\"format\":\"sd-native-input-trace-v1\",\"label\":";
    AppendJsonString(output, state.label);
    output << ",\"active\":";
    AppendBool(output, active);
    output << ",\"capacity\":" << kNativeInputTraceCapacity
           << ",\"unchanged_input_sample_interval_ticks\":"
           << kUnchangedInputSampleIntervalTicks
           << ",\"dropped_events\":" << state.dropped_events
           << ",\"event_count\":" << state.events.size()
           << ",\"events\":[";
    for (std::size_t index = 0; index < state.events.size(); ++index) {
        if (index != 0) {
            output << ',';
        }
        const auto& event = state.events[index];
        output << '{';
        output << "\"kind\":";
        switch (event.kind) {
        case TraceEventKind::WindowMessage:
            AppendJsonString(output, "win32");
            break;
        case TraceEventKind::InputSample:
            AppendJsonString(output, "input_sample");
            break;
        case TraceEventKind::ActorTick:
            AppendJsonString(output, "actor_tick");
            break;
        }
        output << ",\"sequence\":" << event.sequence
               << ",\"monotonic_ms\":" << event.monotonic_ms
               << ",\"simulation_tick\":" << event.simulation_tick;
        if (event.kind == TraceEventKind::WindowMessage) {
            output << ",\"message\":" << event.message
                   << ",\"message_name\":";
            AppendJsonString(output, WindowMessageName(event.message));
            output << ",\"wparam\":" << event.wparam
                   << ",\"lparam\":" << event.lparam
                   << ",\"route_owner\":";
            AppendJsonString(output, event.stage);
            output << ",\"forwarded_to_stock\":";
            AppendBool(output, event.forwarded_to_stock);
            output << ",\"raw_client\":{";
            output << "\"x\":" << event.raw_x
                   << ",\"y\":" << event.raw_y << "},";
            output << "\"native_point\":{";
            output << "\"x\":" << event.native_x
                   << ",\"y\":" << event.native_y << "},";
            output << "\"client_size\":{";
            output << "\"width\":" << event.client_width
                   << ",\"height\":" << event.client_height << "},";
            output << "\"input_scale\":{";
            output << "\"x\":" << event.input_scale_x
                   << ",\"y\":" << event.input_scale_y << "},";
            output << "\"key\":{";
            output << "\"repeat\":" << event.key_repeat
                   << ",\"scancode\":" << event.key_scancode
                   << ",\"extended\":";
            AppendBool(output, event.key_extended);
            output << ",\"previous_down\":";
            AppendBool(output, event.key_previous_down);
            output << ",\"transition_up\":";
            AppendBool(output, event.key_transition_up);
            output << '}';
        } else if (event.kind == TraceEventKind::InputSample) {
            output << ",\"stage\":";
            AppendJsonString(output, event.stage);
            output << ",\"buffer_index\":" << event.input_buffer_index
                   << ",\"raw_mouse_mask\":"
                   << static_cast<unsigned int>(event.raw_mouse_mask)
                   << ",\"mouse\":{";
            output << "\"left\":";
            AppendBool(output, event.mouse_left);
            output << ",\"right\":";
            AppendBool(output, event.mouse_right);
            output << ",\"middle\":";
            AppendBool(output, event.mouse_middle);
            output << "},";
            AppendGameplayState(output, event);
        } else {
            output << ",\"actor_readable\":";
            AppendBool(output, event.actor_readable);
            output << ",\"player\":{";
            output << "\"x\":" << event.player_x
                   << ",\"y\":" << event.player_y << "},";
            output << "\"primary_skill_id\":" << event.primary_skill_id
                   << ",\"previous_skill_id\":"
                   << event.previous_skill_id << ',';
            AppendGameplayState(output, event);
            output << ",\"active_spell\":{";
            output << "\"readable\":";
            AppendBool(output, event.active_spell.readable);
            output << ",\"object_address\":"
                   << event.active_spell.object_address
                   << ",\"object_type\":"
                   << event.active_spell.object_type
                   << ",\"phase\":" << event.active_spell.phase
                   << ",\"release_timer\":"
                   << event.active_spell.release_timer
                   << ",\"charge\":" << event.active_spell.charge
                   << ",\"growth_rate\":"
                   << event.active_spell.growth_rate
                   << ",\"max_charge\":"
                   << event.active_spell.max_charge << '}';
        }
        output << '}';
    }
    output << "]}";
    return output.str();
}
