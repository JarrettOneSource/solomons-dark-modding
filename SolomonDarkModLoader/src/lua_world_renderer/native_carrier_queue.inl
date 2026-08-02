// Included by lua_world_renderer.cpp inside its anonymous namespace.

void __fastcall DrawWorldCarrierGlyph(
    void* self,
    void* /*unused_edx*/) {
    if (self == nullptr ||
        g_world_renderer.glyph_draw_at_position == nullptr) {
        return;
    }
    auto* carrier = static_cast<NativeWorldCarrier*>(self);
    const float x = ReadNativeField<float>(
        carrier->puppet.data(),
        kPuppetWorldPositionXOffset);
    const float y = ReadNativeField<float>(
        carrier->puppet.data(),
        kPuppetWorldPositionYOffset);
    void* renderer = TryGetNativeRenderer();
    std::array<float, 4> previous_color{};
    const bool apply_opacity =
        renderer != nullptr &&
        g_world_renderer.native_renderer_set_color != nullptr &&
        carrier->opacity < 0.999f;
    if (apply_opacity) {
        previous_color = {
            ReadNativeField<float>(
                renderer, kNativeRendererBaseRedOffset),
            ReadNativeField<float>(
                renderer, kNativeRendererBaseGreenOffset),
            ReadNativeField<float>(
                renderer, kNativeRendererBaseBlueOffset),
            ReadNativeField<float>(
                renderer, kNativeRendererBaseAlphaOffset),
        };
        g_world_renderer.native_renderer_set_color(
            renderer,
            previous_color[0],
            previous_color[1],
            previous_color[2],
            previous_color[3] * std::clamp(carrier->opacity, 0.0f, 1.0f));
    }
    g_world_renderer.glyph_draw_at_position(
        carrier->glyph.bytes.data(),
        x,
        y);
    if (apply_opacity) {
        g_world_renderer.native_renderer_set_color(
            renderer,
            previous_color[0],
            previous_color[1],
            previous_color[2],
            previous_color[3]);
    }
    if (!g_world_renderer.logged_native_carrier_draw) {
        g_world_renderer.logged_native_carrier_draw = true;
        Log("lua_world_render: native carrier glyph reached stock draw batch");
    }
}

NativeWorldCarrier* GetOrCreateCarrier(std::size_t index) {
    while (g_world_renderer.carriers.size() <= index) {
        if (g_world_renderer.carriers.size() >=
                kLuaWorldRenderMaxGlobalSprites +
                    kDampenPresentationLimit ||
            g_world_renderer.puppet_ctor == nullptr) {
            return nullptr;
        }
        auto carrier = std::make_unique<NativeWorldCarrier>();
        if (g_world_renderer.puppet_ctor(carrier->puppet.data()) == nullptr) {
            return nullptr;
        }
        const auto native_vtable = ReadNativeField<uintptr_t>(
            carrier->puppet.data(),
            0);
        if (native_vtable == 0) {
            return nullptr;
        }
        std::memcpy(
            carrier->vtable.data(),
            reinterpret_cast<const void*>(native_vtable),
            sizeof(carrier->vtable));
        if (carrier->vtable[kPuppetRenderDispatchVtableIndex] == 0) {
            return nullptr;
        }
        carrier->vtable[kPuppetPrimaryDrawVtableIndex] =
            reinterpret_cast<uintptr_t>(&DrawWorldCarrierGlyph);
        carrier->vtable[kPuppetSecondaryDrawVtableIndex] =
            reinterpret_cast<uintptr_t>(&DrawWorldCarrierGlyph);
        WriteNativeField(
            carrier->puppet.data(),
            0,
            reinterpret_cast<uintptr_t>(carrier->vtable.data()));
        g_world_renderer.carriers.push_back(std::move(carrier));
    }
    return g_world_renderer.carriers[index].get();
}

bool PrepareWorldCarrier(
    NativeWorldCarrier* carrier,
    const LuaWorldSpriteCommand& command,
    uintptr_t world_address,
    std::string* error_message) {
    if (carrier == nullptr || world_address == 0 ||
        !BuildNativeWorldGlyph(
            command,
            &carrier->glyph,
            &carrier->bounds,
            error_message)) {
        return false;
    }
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetWorldPositionXOffset,
        command.x);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetWorldPositionYOffset,
        command.y);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetOwnerWorldOffset,
        world_address);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetSortBiasOffset,
        command.sort_bias);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetBoundsPointerOffset,
        reinterpret_cast<uintptr_t>(carrier->bounds.data()));
    carrier->opacity = 1.0f;
    return true;
}

bool PrepareDampenCarrier(
    NativeWorldCarrier* carrier,
    const NativeWorldDampenPresentation& presentation,
    float progress,
    uintptr_t world_address,
    std::string* error_message) {
    const float radius = kDampenInitialRadius +
        (kDampenFinalRadius - kDampenInitialRadius) * progress;
    if (carrier == nullptr || world_address == 0 ||
        !BuildNativeDampenRingGlyph(
            radius,
            &carrier->glyph,
            &carrier->bounds,
            error_message)) {
        return false;
    }
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetWorldPositionXOffset,
        presentation.x);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetWorldPositionYOffset,
        presentation.y);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetOwnerWorldOffset,
        world_address);
    const float sort_bias = 0.0f;
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetSortBiasOffset,
        sort_bias);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetBoundsPointerOffset,
        reinterpret_cast<uintptr_t>(carrier->bounds.data()));
    carrier->opacity = std::clamp(1.0f - progress, 0.0f, 1.0f);
    return true;
}

void InsertWorldSpriteCarriers(void* queue, int pass) {
    if (queue == nullptr || pass != 0) {
        return;
    }
    SDModPlayerState player;
    if (!TryGetPlayerState(&player) || !player.valid ||
        player.world_address == 0 || !std::isfinite(player.y)) {
        return;
    }

    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized ||
        g_world_renderer.render_queue_insert == nullptr ||
        reinterpret_cast<uintptr_t>(queue) !=
            player.world_address + g_world_renderer.arena_render_queue_offset) {
        return;
    }
    PruneNativeAtlasTextures();
    RefreshLuaWorldRenderFrameSnapshots(
        &g_world_renderer.frame_snapshots);

    std::size_t carrier_index = 0;
    const auto reference_y = static_cast<int>(std::floor(player.y));
    for (const auto& frame : g_world_renderer.frame_snapshots) {
        for (const auto& command : frame.commands) {
            if (carrier_index >= kLuaWorldRenderMaxGlobalSprites) {
                return;
            }
            auto* carrier = GetOrCreateCarrier(carrier_index);
            std::string error_message;
            if (carrier == nullptr ||
                !PrepareWorldCarrier(
                    carrier,
                    command,
                    player.world_address,
                    &error_message)) {
                LogWorldRenderFailure(
                    "world sprite skipped. mod=" + frame.mod_id +
                    " atlas=" + command.atlas +
                    " record=" + std::to_string(command.sprite_index) +
                    " error=" + error_message);
                continue;
            }
            g_world_renderer.render_queue_insert(
                queue,
                reference_y,
                carrier->puppet.data(),
                pass);
            ++carrier_index;
        }
    }

    const auto now = GetTickCount64();
    auto& dampen = g_world_renderer.dampen_presentations;
    dampen.erase(
        std::remove_if(
            dampen.begin(),
            dampen.end(),
            [&](const NativeWorldDampenPresentation& presentation) {
                return now - presentation.started_at_milliseconds >=
                    kDampenPresentationDurationMilliseconds;
            }),
        dampen.end());
    for (auto& presentation : dampen) {
        const float progress = std::clamp(
            static_cast<float>(
                now - presentation.started_at_milliseconds) /
                static_cast<float>(
                    kDampenPresentationDurationMilliseconds),
            0.0f,
            1.0f);
        auto* carrier = GetOrCreateCarrier(carrier_index);
        std::string error_message;
        if (carrier == nullptr ||
            !PrepareDampenCarrier(
                carrier,
                presentation,
                progress,
                player.world_address,
                &error_message)) {
            LogWorldRenderFailure(
                "Dampen presentation skipped. owner_participant_id=" +
                std::to_string(presentation.owner_participant_id) +
                " cast_sequence=" +
                std::to_string(presentation.cast_sequence) +
                " error=" + error_message);
            continue;
        }
        g_world_renderer.render_queue_insert(
            queue,
            reference_y,
            carrier->puppet.data(),
            pass);
        ++carrier_index;
        if (!presentation.draw_logged) {
            presentation.draw_logged = true;
            Log(
                "Multiplayer Dampen native world presentation drawn. "
                "owner_participant_id=" +
                std::to_string(presentation.owner_participant_id) +
                " cast_sequence=" +
                std::to_string(presentation.cast_sequence));
        }
    }
}

void __fastcall HookNativeRenderQueueFlush(
    void* self,
    void* /*unused_edx*/,
    int pass) {
    const auto original =
        GetX86HookTrampoline<NativeRenderQueueFlushFn>(
            g_world_renderer.render_queue_flush_hook);
    if (original == nullptr) {
        return;
    }
    InsertWorldSpriteCarriers(self, pass);
    original(self, pass);
}
