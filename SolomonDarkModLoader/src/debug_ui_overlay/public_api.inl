#include "public_api_initialization.inl"
#include "public_api_surface_dispatch.inl"
#include "public_api_actions.inl"

bool TryPrepareMainMenuNewGameSaveReset(
    std::uintptr_t main_menu_address,
    std::string* error_message) {
    return TryPrepareMainMenuNewGameSaveResetImpl(main_menu_address, error_message);
}

void BeginDebugUiGameplayParticipantNameplateCapture(
    std::uint64_t participant_id,
    std::string_view exact_text,
    float health_ratio,
    float world_width) {
    g_gameplay_participant_nameplate_capture = {};
    if (participant_id == 0 ||
        exact_text.empty() ||
        !std::isfinite(health_ratio) ||
        !std::isfinite(world_width) ||
        world_width <= 0.0f) {
        return;
    }

    g_gameplay_participant_nameplate_capture.active = true;
    g_gameplay_participant_nameplate_capture.participant_id =
        participant_id;
    g_gameplay_participant_nameplate_capture.health_ratio =
        std::clamp(health_ratio, 0.0f, 1.0f);
    g_gameplay_participant_nameplate_capture.world_width = world_width;
    g_gameplay_participant_nameplate_capture.exact_text =
        exact_text;
}

void EndDebugUiGameplayParticipantNameplateCapture() {
    g_gameplay_participant_nameplate_capture = {};
}

void ObserveDebugUiExactTextGlyph(float x, float y) {
    ObserveActiveExactTextGlyph(x, y);
}

void QueueDebugUiMultiplayerDampenPresentation(
    std::uint64_t owner_participant_id,
    std::uint32_t cast_sequence) {
    if (owner_participant_id == 0 || cast_sequence == 0) {
        return;
    }

    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        auto& presentations =
            g_debug_ui_overlay_state.multiplayer_dampen_presentations;
        const auto duplicate = std::find_if(
            presentations.begin(),
            presentations.end(),
            [&](const auto& presentation) {
                return presentation.owner_participant_id ==
                           owner_participant_id &&
                    presentation.cast_sequence == cast_sequence;
            });
        if (duplicate != presentations.end()) {
            return;
        }
        if (presentations.size() == 8) {
            presentations.erase(presentations.begin());
        }
        presentations.push_back({
            owner_participant_id,
            cast_sequence,
            GetTickCount64(),
            false,
        });
    }
    Log(
        "Multiplayer Dampen DX9 presentation queued. owner_participant_id=" +
        std::to_string(owner_participant_id) +
        " cast_sequence=" + std::to_string(cast_sequence));
}
