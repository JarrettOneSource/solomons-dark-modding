uintptr_t PreferredAddress(uintptr_t runtime_address) {
    if (runtime_address == 0 || g_scene_capture.runtime_image_base == 0 ||
        runtime_address < g_scene_capture.runtime_image_base) {
        return 0;
    }
    return kPreferredImageBase +
        (runtime_address - g_scene_capture.runtime_image_base);
}

template <typename Value>
bool TryReadRuntimeField(
    uintptr_t base,
    std::size_t offset,
    Value* value) {
    return base != 0 && value != nullptr &&
        ProcessMemory::Instance().TryReadField(base, offset, value);
}

bool TryReadNativeSpriteSignature(
    uintptr_t sprite_address,
    NativeSpriteSignature* signature) {
    if (sprite_address == 0 || signature == nullptr) {
        return false;
    }
    NativeSpriteSignature value;
    auto& memory = ProcessMemory::Instance();
    if (!memory.TryReadField(
            sprite_address,
            kNativeSpriteTextureHandleOffset,
            &value.texture_handle) ||
        !memory.TryRead(
            sprite_address + kNativeSpriteUvOffset,
            value.uv_bits.data(),
            sizeof(value.uv_bits)) ||
        !memory.TryReadField(
            sprite_address,
            kNativeSpriteLogicalWidthOffset,
            &value.logical_width) ||
        !memory.TryReadField(
            sprite_address,
            kNativeSpriteLogicalHeightOffset,
            &value.logical_height)) {
        return false;
    }
    *signature = value;
    return true;
}

bool IsDrawableNativeSprite(const NativeSpriteSignature& signature) {
    return signature.texture_handle != 0 && signature.logical_width > 0 &&
        signature.logical_height > 0;
}

std::string NativeSpriteSignatureKey(
    const NativeSpriteSignature& signature) {
    std::string key;
    key.reserve(
        sizeof(signature.texture_handle) + sizeof(signature.uv_bits) +
        sizeof(signature.logical_width) + sizeof(signature.logical_height));
    const auto append = [&](const void* data, std::size_t size) {
        key.append(static_cast<const char*>(data), size);
    };
    append(&signature.texture_handle, sizeof(signature.texture_handle));
    append(signature.uv_bits.data(), sizeof(signature.uv_bits));
    append(&signature.logical_width, sizeof(signature.logical_width));
    append(&signature.logical_height, sizeof(signature.logical_height));
    return key;
}

void NormalizeCandidates(std::vector<std::string>* candidates) {
    if (candidates == nullptr) {
        return;
    }
    std::sort(candidates->begin(), candidates->end());
    candidates->erase(
        std::unique(candidates->begin(), candidates->end()),
        candidates->end());
}

void RebuildNativeSceneArtResolver() {
    g_scene_capture.art_by_address.clear();
    g_scene_capture.art_by_signature.clear();
    auto& memory = ProcessMemory::Instance();

    for (const auto& span : kNativeSceneAtlasSpans) {
        const auto resolved_global =
            memory.ResolveGameAddressOrZero(span.singleton_global);
        std::uint32_t object_pointer = 0;
        if (resolved_global == 0 ||
            !memory.TryReadValue(resolved_global, &object_pointer) ||
            object_pointer == 0) {
            continue;
        }

        uintptr_t records =
            static_cast<uintptr_t>(object_pointer) + span.object_field;
        if (span.kind == NativeSceneAtlasSpanKind::Array) {
            std::uint32_t array_pointer = 0;
            std::uint32_t live_count = 0;
            if (!memory.TryReadValue(records, &array_pointer) ||
                !memory.TryReadValue(
                    records + sizeof(std::uint32_t),
                    &live_count) ||
                array_pointer == 0 || live_count < span.record_count) {
                continue;
            }
            records = static_cast<uintptr_t>(array_pointer);
        }

        for (std::uint32_t index = 0; index < span.record_count; ++index) {
            const auto address =
                records + static_cast<uintptr_t>(index) * kNativeSpriteStride;
            const auto id = std::string(span.atlas) + "." +
                std::to_string(span.first_record + index);
            g_scene_capture.art_by_address[address].push_back(id);

            NativeSpriteSignature signature;
            if (TryReadNativeSpriteSignature(address, &signature) &&
                IsDrawableNativeSprite(signature)) {
                g_scene_capture.art_by_signature[
                    NativeSpriteSignatureKey(signature)]
                    .push_back(id);
            }
        }
    }

    for (auto& [address, candidates] : g_scene_capture.art_by_address) {
        (void)address;
        NormalizeCandidates(&candidates);
    }
    for (auto& [signature, candidates] : g_scene_capture.art_by_signature) {
        (void)signature;
        NormalizeCandidates(&candidates);
    }
}

bool TryResolveNativeFontGroup(
    uintptr_t sprite_address,
    ResolvedNativeArt* art) {
    struct FontGroup {
        std::size_t offset;
        std::uint32_t first;
        std::uint32_t last;
    };
    constexpr FontGroup kFontGroups[] = {
        {0x0000FC, 1, 92},
        {0x04D530, 93, 184},
        {0x09A964, 185, 215},
        {0x0E7D98, 216, 307},
        {0x1351CC, 308, 349},
        {0x182600, 350, 375},
        {0x1CFA34, 376, 442},
        {0x21CE68, 443, 534},
        {0x26A29C, 535, 626},
    };
    constexpr std::size_t kFontGroupSpan = 0x4D434;

    auto& memory = ProcessMemory::Instance();
    const auto global = memory.ResolveGameAddressOrZero(0x008199A0);
    std::uint32_t object_pointer = 0;
    if (global == 0 || !memory.TryReadValue(global, &object_pointer) ||
        object_pointer == 0) {
        return false;
    }
    for (const auto& group : kFontGroups) {
        const auto start =
            static_cast<uintptr_t>(object_pointer) + group.offset;
        if (sprite_address < start ||
            sprite_address >= start + kFontGroupSpan) {
            continue;
        }
        std::ostringstream id;
        id << "Fonts." << group.first << '-' << group.last << "@0x"
           << std::hex << std::uppercase << (sprite_address - start);
        art->id = id.str();
        art->atlas = "Fonts";
        art->resolution = "font-group-offset";
        return true;
    }
    return false;
}

void ParseResolvedArtId(ResolvedNativeArt* art) {
    if (art == nullptr || art->id.empty()) {
        return;
    }
    const auto separator = art->id.rfind('.');
    if (separator == std::string::npos) {
        return;
    }
    art->atlas = art->id.substr(0, separator);
    const auto index = art->id.substr(separator + 1);
    char* end = nullptr;
    const auto parsed = std::strtol(index.c_str(), &end, 10);
    if (end != index.c_str() && *end == '\0' && parsed >= 0 &&
        parsed <= (std::numeric_limits<std::int32_t>::max)()) {
        art->sprite_index = static_cast<std::int32_t>(parsed);
    }
}

ResolvedNativeArt ResolveNativeSceneArt(uintptr_t sprite_address) {
    ResolvedNativeArt art;
    NativeSpriteSignature signature;
    if (TryReadNativeSpriteSignature(sprite_address, &signature)) {
        art.texture_handle = signature.texture_handle;
    }

    if (const auto direct =
            g_scene_capture.art_by_address.find(sprite_address);
        direct != g_scene_capture.art_by_address.end()) {
        art.candidates = direct->second;
        if (art.candidates.size() == 1) {
            art.id = art.candidates.front();
            art.resolution = "direct-address";
            ParseResolvedArtId(&art);
            return art;
        }
        art.id = "ambiguous-native-sprite";
        art.resolution = "ambiguous-direct-address";
        return art;
    }

    if (IsDrawableNativeSprite(signature)) {
        const auto copied = g_scene_capture.art_by_signature.find(
            NativeSpriteSignatureKey(signature));
        if (copied != g_scene_capture.art_by_signature.end()) {
            art.candidates = copied->second;
            if (art.candidates.size() == 1) {
                art.id = art.candidates.front();
                art.resolution = "unique-live-signature";
                ParseResolvedArtId(&art);
                return art;
            }
            art.id = "ambiguous-native-sprite";
            art.resolution = "ambiguous-live-signature";
            return art;
        }
    }

    if (TryResolveNativeFontGroup(sprite_address, &art)) {
        return art;
    }

    art.id = "unresolved-native-sprite";
    art.resolution = "unresolved";
    return art;
}

uintptr_t TryGetNativeRendererDrawState() {
    if (g_scene_capture.native_renderer_global == 0 ||
        g_scene_capture.native_renderer_draw_state_offset == 0) {
        return 0;
    }
    uintptr_t renderer = 0;
    if (!ProcessMemory::Instance().TryReadValue(
            g_scene_capture.native_renderer_global,
            &renderer) ||
        renderer == 0) {
        return 0;
    }
    return renderer + g_scene_capture.native_renderer_draw_state_offset;
}

bool TryReadRendererBase(float* x, float* y) {
    const auto draw_state = TryGetNativeRendererDrawState();
    return TryReadRuntimeField(draw_state, kRendererBaseXOffset, x) &&
        TryReadRuntimeField(draw_state, kRendererBaseYOffset, y) &&
        std::isfinite(*x) && std::isfinite(*y);
}

std::array<float, 4> ReadRendererTint() {
    std::array<float, 4> tint = {1.0f, 1.0f, 1.0f, 1.0f};
    const auto draw_state = TryGetNativeRendererDrawState();
    (void)TryReadRuntimeField(draw_state, kRendererRedOffset, &tint[0]);
    (void)TryReadRuntimeField(draw_state, kRendererGreenOffset, &tint[1]);
    (void)TryReadRuntimeField(draw_state, kRendererBlueOffset, &tint[2]);
    (void)TryReadRuntimeField(draw_state, kRendererAlphaOffset, &tint[3]);
    return tint;
}

BlendCapture ReadBlendState() {
    BlendCapture blend;
    auto* device = GetLastSeenD3d9Device();
    if (device == nullptr) {
        return blend;
    }
    blend.available =
        SUCCEEDED(device->GetRenderState(D3DRS_ALPHABLENDENABLE, &blend.enabled)) &&
        SUCCEEDED(device->GetRenderState(D3DRS_SRCBLEND, &blend.source)) &&
        SUCCEEDED(device->GetRenderState(D3DRS_DESTBLEND, &blend.destination)) &&
        SUCCEEDED(device->GetRenderState(D3DRS_BLENDOP, &blend.operation));
    return blend;
}
