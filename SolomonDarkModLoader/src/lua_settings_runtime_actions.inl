LuaSettingsOperationResult ReloadLuaSettings(
    std::string_view mod_id) {
    LuaSettingsOperationResult result;
    auto* mod = FindLoadedSettingsMod(mod_id);
    if (mod == nullptr) {
        result.error = "mod is not loaded";
        return result;
    }
    if (!mod->settings_available) {
        result.error = "mod has no valid settings declaration";
        return result;
    }
    if (!HasSettingsCapability(*mod)) {
        result.error = "mod does not declare settings.self";
        return result;
    }

    ModSettingValues next_local;
    std::map<std::string, std::string, std::less<>>
        persisted_entry_errors;
    std::string read_error;
    if (!ReadLocalValues(
            mod,
            &next_local,
            &persisted_entry_errors,
            &read_error)) {
        result.error =
            "failed to reload persisted settings: " + read_error;
        return result;
    }
    result.entry_errors = std::move(persisted_entry_errors);
    for (const auto& entry : mod->settings_declaration.entries) {
        if (entry.type == ModSettingType::Action ||
            entry.requires_restart) {
            continue;
        }
        const auto value = next_local.find(entry.key);
        if (value != next_local.end()) {
            mod->local_settings_values[entry.key] = value->second;
        }
    }
    for (const auto& entry : mod->settings_declaration.entries) {
        if (entry.type == ModSettingType::Action ||
            entry.requires_restart) {
            continue;
        }
        const auto local = next_local.find(entry.key);
        if (local == next_local.end()) {
            continue;
        }
        if (entry.scope == ModSettingScope::Host &&
            IsActiveClientSession()) {
            continue;
        }
        const auto previous =
            mod->effective_settings_values.find(entry.key);
        const bool changed =
            previous == mod->effective_settings_values.end() ||
            previous->second != local->second;
        ApplyEffectiveChange(
            mod,
            entry,
            local->second,
            &result.changed,
            &result.entry_errors,
            true);
        if (changed &&
            !PublishHostValue(*mod, entry, local->second)) {
            result.error =
                "failed to replicate host setting '" +
                entry.key + "'";
            return result;
        }
    }
    result.ok = result.entry_errors.empty();
    if (!result.ok && result.error.empty()) {
        result.error = "one or more settings failed to apply";
    }
    return result;
}

LuaSettingsOperationResult InvokeLuaSettingsAction(
    std::string_view mod_id,
    std::string_view key) {
    LuaSettingsOperationResult result;
    auto* mod = FindLoadedSettingsMod(mod_id);
    if (mod == nullptr) {
        result.error = "mod is not loaded";
        return result;
    }
    if (!mod->settings_available || !HasSettingsCapability(*mod)) {
        result.error = "mod settings are unavailable";
        return result;
    }
    const auto* entry = mod->settings_declaration.Find(key);
    if (entry == nullptr || entry->type != ModSettingType::Action) {
        result.error = "unknown action setting";
        return result;
    }
    if (entry->scope == ModSettingScope::Host &&
        multiplayer::IsLocalTransportClient()) {
        result.error = "host-scope action requires session authority";
        return result;
    }
    const auto callback =
        mod->settings_action_callbacks.find(std::string(key));
    if (callback == mod->settings_action_callbacks.end()) {
        result.error = "action has no registered handler";
        LogSettingsError(
            "action_handler_missing",
            *mod,
            std::string(key));
        return result;
    }

    ScopedSuspendedSettingsPrivilege suspended_privilege(mod->state);
    lua_rawgeti(
        mod->state,
        LUA_REGISTRYINDEX,
        callback->second);
    if (lua_pcall(mod->state, 0, 0, 0) != LUA_OK) {
        const auto* error = lua_tostring(mod->state, -1);
        result.error =
            error == nullptr
                ? "action handler failed"
                : error;
        lua_pop(mod->state, 1);
        LogSettingsError(
            "action_handler_failed",
            *mod,
            result.error);
        return result;
    }
    result.ok = true;
    return result;
}
