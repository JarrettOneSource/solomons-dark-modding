#include "lua_content_registry.h"

#include <iostream>
#include <string>

namespace {

bool Require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

}  // namespace

int main() {
    using namespace sdmod;

    ResetLuaContentRegistry();
    if (!Require(IsValidLuaContentIdentifier("sample.lua.items"), "valid mod id rejected") ||
        !Require(IsValidLuaContentIdentifier("golden_focus"), "valid key rejected") ||
        !Require(!IsValidLuaContentIdentifier("GoldenFocus"), "uppercase key accepted") ||
        !Require(!IsValidLuaContentIdentifier("bad/key"), "path-like key accepted") ||
        !Require(
            ComputeLuaContentNetworkId("sample.lua.items", "golden_focus") ==
                8108516122269430198ull,
            "golden_focus content ID drifted") ||
        !Require(
            ComputeLuaContentNetworkId("sample.lua.spells", "shock_nova") ==
                6415373166652859851ull,
            "shock_nova content ID drifted") ||
        !Require(
            ComputeLuaContentNetworkId(
                "sample.lua.spells_registry_lab",
                "gravity_well") == 8348995147374483494ull,
            "gravity_well content ID drifted") ||
        !Require(
            ComputeLuaContentNetworkId("sample.lua.enemies", "grave_tyrant") ==
                7260085584278011992ull,
            "grave_tyrant content ID drifted") ||
        !Require(
            ComputeLuaContentNetworkId(
                "sample.lua.enemies_registry_lab",
                "grave_tyrant") == 8726222830294414077ull,
            "enemy registry lab content ID drifted") ||
        !Require(
            ComputeLuaContentNetworkId(
                "sample.lua.items_registry_lab",
                "pentaclostic_ring") == 5785942626980372610ull,
            "pentaclostic_ring content ID drifted")) {
        return 1;
    }

    LuaContentIdentity spell;
    std::string error;
    if (!Require(
            RegisterLuaContentIdentity(
                LuaContentKind::Spell,
                "sample.lua.spells",
                "shock_nova",
                &spell,
                &error),
            "initial spell registration failed") ||
        !Require(spell.network_id == 6415373166652859851ull, "registered ID drifted") ||
        !Require(GetLuaContentIdentityCount() == 1, "registry count did not advance")) {
        std::cerr << error << '\n';
        return 1;
    }

    LuaContentIdentity duplicate;
    if (!Require(
            !RegisterLuaContentIdentity(
                LuaContentKind::Spell,
                "sample.lua.spells",
                "shock_nova",
                &duplicate,
                &error),
            "duplicate registration was accepted") ||
        !Require(error.find("duplicate") != std::string::npos, "duplicate error was unclear") ||
        !Require(
            !RegisterLuaContentIdentity(
                LuaContentKind::Item,
                "sample.lua.spells",
                "shock_nova",
                &duplicate,
                &error),
            "cross-kind key reuse was accepted") ||
        !Require(
            error.find("already registered as spell") != std::string::npos,
            "cross-kind error was unclear")) {
        return 1;
    }

    const auto found = FindLuaContentIdentity(spell.network_id);
    if (!Require(found.has_value(), "registered content could not be resolved") ||
        !Require(found->mod_id == "sample.lua.spells", "resolved mod id drifted") ||
        !Require(found->key == "shock_nova", "resolved key drifted")) {
        return 1;
    }

    UnregisterLuaContentIdentitiesForMod("sample.lua.spells");
    if (!Require(GetLuaContentIdentityCount() == 0, "mod unload left content registered") ||
        !Require(
            !FindLuaContentIdentity(spell.network_id).has_value(),
            "unloaded content still resolved")) {
        return 1;
    }

    std::cout << "Lua content identity registry passed\n";
    return 0;
}
