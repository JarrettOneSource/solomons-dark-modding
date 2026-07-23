#include "lua_engine_internal.h"

#include "logger.h"

#include <algorithm>
#include <memory>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace sdmod::detail {

void LoadLuaModsForBootstrap(
    const RuntimeBootstrap& bootstrap,
    const std::vector<std::string>& capabilities) {
    std::vector<const RuntimeModDescriptor*> pending_mods;
    for (const auto& mod : bootstrap.mods) {
        if (!mod.HasLuaEntry()) {
            continue;
        }

        if (mod.api_version != SDMOD_RUNTIME_API_VERSION) {
            Log(
                "[lua][" + mod.id + "] skipping mod due to apiVersion mismatch. host=" +
                std::string(SDMOD_RUNTIME_API_VERSION) + " mod=" + mod.api_version);
            continue;
        }

        std::string missing_capability;
        if (!SupportsLuaModRequiredCapabilities(mod, capabilities, &missing_capability)) {
            Log(
                "[lua][" + mod.id +
                "] skipping mod due to unsupported required capability: " + missing_capability);
            continue;
        }

        pending_mods.push_back(&mod);
    }

    auto& loaded_mods = LoadedLuaModsStorage();
    std::unordered_set<std::string> loaded_contracts;
    while (!pending_mods.empty()) {
        bool made_progress = false;
        std::vector<const RuntimeModDescriptor*> still_pending;
        for (const auto* mod : pending_mods) {
            const auto missing_contract = std::find_if(
                mod->requires.begin(),
                mod->requires.end(),
                [&loaded_contracts](const std::string& contract) {
                    return loaded_contracts.find(contract) == loaded_contracts.end();
                });
            if (missing_contract != mod->requires.end()) {
                still_pending.push_back(mod);
                continue;
            }

            made_progress = true;
            auto loaded_mod = std::make_unique<LoadedLuaMod>();
            loaded_mod->descriptor = *mod;
            loaded_mod->capabilities = capabilities;
            loaded_mods.push_back(std::move(loaded_mod));
            auto* live_mod = loaded_mods.back().get();

            std::string load_error;
            if (!CreateLuaStateForMod(live_mod, &load_error)) {
                CloseLuaStateForMod(live_mod);
                loaded_mods.pop_back();
                Log("[lua][" + mod->id + "] failed to load entry script: " + load_error);
                continue;
            }

            LogLuaMessage(
                *live_mod,
                "loaded entry script: " + mod->entry_script_path.string());
            loaded_contracts.insert(mod->provides.begin(), mod->provides.end());
        }

        if (!made_progress) {
            for (const auto* mod : still_pending) {
                const auto missing_contract = std::find_if(
                    mod->requires.begin(),
                    mod->requires.end(),
                    [&loaded_contracts](const std::string& contract) {
                        return loaded_contracts.find(contract) == loaded_contracts.end();
                    });
                Log(
                    "[lua][" + mod->id +
                    "] skipping mod due to unavailable runtime contract: " +
                    (missing_contract == mod->requires.end()
                        ? std::string("unknown")
                        : *missing_contract));
            }
            break;
        }
        pending_mods = std::move(still_pending);
    }
}

}  // namespace sdmod::detail
