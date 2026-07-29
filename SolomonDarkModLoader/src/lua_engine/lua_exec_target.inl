std::vector<std::unique_ptr<LoadedLuaMod>>& LoadedLuaModsStorage() {
    static std::vector<std::unique_ptr<LoadedLuaMod>> loaded_mods;
    return loaded_mods;
}

LoadedLuaMod* ResolveLuaExecTargetMod(
    std::string_view requested_mod_id) {
    constexpr char kTargetModEnvironment[] =
        "SDMOD_LUA_EXEC_TARGET_MOD_ID";
    const auto required =
        GetEnvironmentVariableA(kTargetModEnvironment, nullptr, 0);
    std::string requested(requested_mod_id);
    if (requested.empty() && required > 1) {
        requested.resize(required - 1);
        const auto written = GetEnvironmentVariableA(
            kTargetModEnvironment,
            requested.data(),
            required);
        if (written != required - 1) {
            requested.clear();
        }
    }

    auto& mods = LoadedLuaModsStorage();
    if (!requested.empty()) {
        const auto configured = std::find_if(
            mods.begin(),
            mods.end(),
            [&requested](const auto& mod) {
                return mod != nullptr &&
                    mod->state != nullptr &&
                    mod->descriptor.id == requested;
            });
        return configured == mods.end()
            ? nullptr
            : configured->get();
    }

    const auto available = std::find_if(
        mods.begin(),
        mods.end(),
        [](const auto& mod) {
            return mod != nullptr && mod->state != nullptr;
        });
    return available == mods.end() ? nullptr : available->get();
}

lua_State* ResolveLuaExecTargetState(
    std::string_view requested_mod_id) {
    auto* mod = ResolveLuaExecTargetMod(requested_mod_id);
    if (mod != nullptr) {
        return mod->state;
    }
    return requested_mod_id.empty()
        ? LuaExecControlStateStorage()
        : nullptr;
}
