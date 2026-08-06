std::size_t NativeActorAllocationSize(std::uint32_t type_id) {
    switch (type_id) {
        case 0x3E8: return 0x210;
        case 0x3E9: return 0x248;
        case 0x3EA: return 0x270;
        case 0x3EB: return 0x2AC;
        case 0x3EC: return 0x23C;
        case 0x3ED: return 0x244;
        case 0x3EE: return 0x260;
        case 0x3EF: return 0x234;
        case 0x3F0: return 0x274;
        case 0x3F1: return 0x2E4;
        case 0x3F2: return 0x270;
        case 0x3F3: return 0x30C;
        case 0x3F5: return 0x2F0;
        case 0x7FC: return 0x23C;
        case 0x7FD: return 0x268;
        case 0x809: return 0x254;
        case 0x80A: return 0x21C;
        case 0x139D: return 0x23C;
        default: return 0;
    }
}

void CaptureAnimationActors(SceneFrameCapture* frame) {
    if (frame == nullptr) {
        return;
    }
    frame->player_available = TryGetPlayerState(&frame->player);
    if (frame->player_available && frame->player.actor_address != 0) {
        (void)TryReadRuntimeField(
            frame->player.actor_address,
            0x1BC,
            &frame->player_animation_duration_ticks);
        (void)TryReadRuntimeField(
            frame->player.actor_address,
            0x22C,
            &frame->player_render_frame_state);
    }
    std::vector<SDModSceneActorState> actors;
    frame->actors_available = TryListSceneActors(&actors);
    if (!frame->actors_available) {
        return;
    }
    for (const auto& actor : actors) {
        if (!actor.valid || !actor.tracked_enemy || actor.actor_address == 0) {
            continue;
        }
        const auto allocation_size = NativeActorAllocationSize(
            actor.object_type_id);
        if (allocation_size <= kAnimationWindowOffset) {
            continue;
        }
        ActorAnimationCapture capture;
        capture.actor = actor;
        (void)TryReadRuntimeField(
            actor.actor_address, kActorHeadingOffset, &capture.heading);
        if (TryReadRuntimeField(
                actor.actor_address, 0xE4, &capture.action_count) &&
            capture.action_count == 0) {
            capture.action_available = true;
        } else if (capture.action_count == 1) {
            uintptr_t action_list = 0;
            uintptr_t control = 0;
            uintptr_t action = 0;
            if (TryReadRuntimeField(
                    actor.actor_address, 0xF0, &action_list) &&
                action_list != 0 &&
                ProcessMemory::Instance().TryReadValue(
                    action_list, &control) &&
                control != 0 &&
                ProcessMemory::Instance().TryReadValue(control, &action) &&
                action != 0 &&
                TryReadRuntimeField(action, 0x14, &capture.action_id) &&
                TryReadRuntimeField(
                    action, 0x30, &capture.action_progress)) {
                capture.action_available = true;
            }
        }
        const auto byte_count = (std::min)(
            allocation_size - kAnimationWindowOffset,
            kMaximumAnimationWindowBytes);
        capture.presentation_bytes.resize(byte_count);
        if (!ProcessMemory::Instance().TryRead(
                actor.actor_address + kAnimationWindowOffset,
                capture.presentation_bytes.data(),
                capture.presentation_bytes.size())) {
            FailActiveSceneCapture(
                "native scene capture could not read a tracked enemy presentation window");
            return;
        }
        frame->actors.push_back(std::move(capture));
    }
}
