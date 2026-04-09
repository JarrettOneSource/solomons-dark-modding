#include "binary_layout_internal.h"

#include <mutex>

namespace sdmod {
namespace {

template <typename TDefinition>
const TDefinition* FindDefinitionById(const std::vector<TDefinition>& definitions, std::string_view id) {
    for (const auto& definition : definitions) {
        if (definition.id == id) {
            return &definition;
        }
    }

    return nullptr;
}

}  // namespace

BinaryLayoutState& GetBinaryLayoutState() {
    static BinaryLayoutState state;
    return state;
}

bool InitializeBinaryLayout(const std::filesystem::path& stage_runtime_directory) {
    auto& state = GetBinaryLayoutState();
    std::scoped_lock lock(state.mutex);
    if (state.loaded) {
        return true;
    }

    BinaryLayout layout;
    std::string error_message;
    if (!LoadBinaryLayoutFromDisk(GetBinaryLayoutPath(stage_runtime_directory), &layout, &error_message)) {
        state.layout = BinaryLayout{};
        state.loaded = false;
        state.last_error = std::move(error_message);
        return false;
    }

    state.layout = std::move(layout);
    state.loaded = true;
    state.last_error.clear();
    return true;
}

void ShutdownBinaryLayout() {
    auto& state = GetBinaryLayoutState();
    std::scoped_lock lock(state.mutex);
    state.layout = BinaryLayout{};
    state.loaded = false;
    state.last_error.clear();
}

bool IsBinaryLayoutLoaded() {
    auto& state = GetBinaryLayoutState();
    std::scoped_lock lock(state.mutex);
    return state.loaded;
}

const BinaryLayout* TryGetBinaryLayout() {
    auto& state = GetBinaryLayoutState();
    std::scoped_lock lock(state.mutex);
    return state.loaded ? &state.layout : nullptr;
}

std::string GetBinaryLayoutLoadError() {
    auto& state = GetBinaryLayoutState();
    std::scoped_lock lock(state.mutex);
    return state.last_error;
}

const UiSurfaceDefinition* FindUiSurfaceDefinition(std::string_view id) {
    auto& state = GetBinaryLayoutState();
    std::scoped_lock lock(state.mutex);
    if (!state.loaded) {
        return nullptr;
    }

    return FindDefinitionById(state.layout.ui_surfaces, id);
}

const UiActionDefinition* FindUiActionDefinition(std::string_view id) {
    auto& state = GetBinaryLayoutState();
    std::scoped_lock lock(state.mutex);
    if (!state.loaded) {
        return nullptr;
    }

    return FindDefinitionById(state.layout.ui_actions, id);
}

uintptr_t GetConfiguredImageBase() {
    auto& state = GetBinaryLayoutState();
    std::scoped_lock lock(state.mutex);
    return state.loaded ? state.layout.image_base : 0;
}

std::filesystem::path GetBinaryLayoutPath(const std::filesystem::path& stage_runtime_directory) {
    return stage_runtime_directory / "config" / "binary-layout.ini";
}

}  // namespace sdmod
