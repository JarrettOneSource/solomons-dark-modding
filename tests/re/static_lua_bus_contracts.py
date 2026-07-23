"""Contracts for the bounded local cross-mod Lua bus."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_bus_is_manifest_resolved_bounded_and_local() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    bus = _read("SolomonDarkModLoader/src/lua_engine_bindings_bus.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    mod_loading = _read("SolomonDarkModLoader/src/lua_engine_mod_loading.cpp")
    bootstrap_header = _read("SolomonDarkModLoader/include/runtime_bootstrap.h")
    bootstrap_parser = _read("SolomonDarkModLoader/src/runtime_bootstrap.cpp")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    manifest = _read("SolomonDarkModLauncher/src/Mods/ModManifest.cs")
    validator = _read("SolomonDarkModLauncher/src/Mods/ModManifestValidator.cs")
    catalog = _read("SolomonDarkModLauncher/src/Mods/ModCatalog.cs")
    stage_entry = _read("SolomonDarkModLauncher/src/Staging/RuntimeStageManifestEntry.cs")
    stage = _read("SolomonDarkModLauncher/src/Staging/RuntimeMetadataStageMaterializer.cs")
    launcher_tests = _read("tests/launcher-contracts/Program.cs")
    documentation = _read("docs/lua-bus.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    provider_manifest = _read("mods/lua_bus_provider_lab/manifest.json")
    provider = _read("mods/lua_bus_provider_lab/scripts/main.lua")
    consumer_manifest = _read("mods/lua_bus_consumer_lab/manifest.json")
    consumer = _read("mods/lua_bus_consumer_lab/scripts/main.lua")
    verifier = _read("tools/verify_lua_bus.py")

    assert "RegisterLuaBusBindings(mod->state)" in bindings
    assert "lua_createtable(mod->state, 0, 18);" in bindings
    assert "std::vector<LuaBusSubscription> bus_subscriptions" in internal
    assert '"bus.local.contracts"' in engine
    assert "ClearLuaBusSubscriptionsForMod(mod)" in engine
    assert "lua_engine_bindings_bus.cpp" in project

    for token in (
        "kLuaBusMaximumSubscriptionsPerMod = 128",
        "kLuaBusMaximumDeliveriesPerPublish = 256",
        "kLuaBusMaximumDispatchDepth = 16",
        "ReadLuaModValue(state, 2, &payload",
        "std::vector<LuaBusDispatchTarget> targets",
        'lua_setfield(target.mod->state, -2, "publisher_mod_id")',
        'RegisterFunction(state, &LuaBusPublish, "publish")',
        'RegisterFunction(state, &LuaBusSubscribe, "subscribe")',
        'RegisterFunction(state, &LuaBusUnsubscribe, "unsubscribe")',
        'RegisterFunction(state, &LuaBusHas, "has")',
        'RegisterFunction(state, &LuaBusProviders, "providers")',
        'lua_setfield(state, -2, "bus")',
    ):
        assert token in bus, f"Lua bus implementation lacks: {token}"

    for token in (
        "std::vector<std::string> provides",
        "std::vector<std::string> requires",
    ):
        assert token in bootstrap_header
    for token in (
        '"provides"',
        '"requires"',
        "mod.provides = SplitCapabilities(provides)",
        "mod.requires = SplitCapabilities(requires)",
    ):
        assert token in bootstrap_parser
    assert "LoadLuaModsForBootstrap(bootstrap, capabilities)" in engine
    _require_in_order(
        mod_loading,
        "std::unordered_set<std::string> loaded_contracts",
        "mod->requires.begin()",
        "CreateLuaStateForMod(live_mod",
        "loaded_contracts.insert(mod->provides.begin()",
    )
    assert "unavailable runtime contract" in mod_loading

    assert "public List<string> Provides" in manifest
    assert "public List<string> Requires" in manifest
    assert "ValidateRuntimeContracts" in validator
    assert "Invalid lowercase contract identifier" in validator
    assert "EnsureRuntimeContractsResolved(enabledMods)" in catalog
    assert "requires missing runtime contract" in catalog
    assert "IReadOnlyList<string> Provides" in stage_entry
    assert "IReadOnlyList<string> Requires" in stage_entry
    assert 'builder.Append("provides=")' in stage
    assert 'builder.Append("requires=")' in stage
    for token in (
        '"Lua bus runtime contracts"',
        '"provides": ["tests.bus.echo.v1"]',
        '"requires": ["tests.bus.echo.v1"]',
        "catalog accepted an unresolved bus contract",
    ):
        assert token in launcher_tests

    assert '"provides"' in provider_manifest
    assert '"requires"' in consumer_manifest
    assert '"sample.lua.bus_provider_lab"' in consumer_manifest
    assert "sd.bus.subscribe" in provider
    assert "sd.bus.publish" in provider
    assert "sd.bus.has" in consumer
    assert "startup bus round trip failed" in consumer

    for token in (
        "## Manifest contracts",
        "## API",
        "## Multiplayer",
        "never replicated",
        "128 subscriptions",
        "256 subscriptions",
        "depth 16",
        "bus.local.contracts",
    ):
        assert token in documentation, f"Lua bus documentation lacks: {token}"
    assert "**Implemented 2026-07-22.** `sd.bus`" in roadmap
    for token in (
        'sd.bus.publish("sample.bus.consumer.request"',
        "cross-mod response count mismatch",
        "cyclic payload was accepted",
        "publisher_mod_id",
    ):
        assert token in verifier, f"Lua bus verifier lacks: {token}"

    return (
        "sd.bus resolves manifest contracts against successfully loaded providers, "
        "copies bounded payloads across isolated states, and dispatches locally"
    )
