"""Static contracts for manifest-backed Lua mod settings."""

from __future__ import annotations

import json

from static_multiplayer_contract_support import _read, _require_in_order


def test_mod_settings_are_scoped_atomic_privileged_and_replicated() -> str:
    header = _read("SolomonDarkModLoader/include/mod_settings.h")
    validator = _read("SolomonDarkModLoader/src/mod_settings.cpp")
    list_validator = _read(
        "SolomonDarkModLoader/src/mod_settings_list.cpp"
    )
    values = _read("SolomonDarkModLoader/src/mod_settings_values.cpp")
    persistence = _read(
        "SolomonDarkModLoader/src/mod_settings_persistence.cpp"
    )
    runtime = (
        _read("SolomonDarkModLoader/src/lua_settings_runtime.cpp")
        + _read(
            "SolomonDarkModLoader/src/"
            "lua_settings_runtime_actions.inl"
        )
    )
    bindings = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_settings.cpp"
    )
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    wait = _read("SolomonDarkModLoader/src/lua_exec_wait.inl")
    manifest_service = _read(
        "SolomonDarkModLauncher/src/ModSettings/"
        "ModSettingsManifestService.cs"
    )
    models = _read(
        "SolomonDarkModLauncher/src/ModSettings/"
        "ModSettingsModels.cs"
    )
    store = _read(
        "SolomonDarkModLauncher/src/ModSettings/ModSettingsStore.cs"
    )
    discovery = _read(
        "SolomonDarkModLauncher/src/ModSettings/"
        "ModSettingsDiscoveryService.cs"
    )
    coordinator = _read(
        "SolomonDarkModLauncher/src/ModSettings/ModSettingsService.cs"
    )
    runtime_client = _read(
        "SolomonDarkModLauncher/src/ModSettings/"
        "ModSettingsRuntimeClient.cs"
    )
    fixture = json.loads(
        _read("tests/fixtures/mod-settings-validation-vectors.json")
    )
    bot_manifest = json.loads(_read("mods/bot-brain/manifest.json"))
    brain = _read("mods/bot-brain/scripts/main.lua")
    brain_policy = _read("mods/bot-brain/scripts/brain.lua")
    roster = _read("mods/bot-brain/scripts/roster.lua")
    verifier = _read("tools/verify_mod_settings_lifecycle.py")
    design = _read("docs/design/mod-settings-2026-07-27.md")
    api_docs = _read("docs/lua-settings.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    generated = _read("api/lua/sd.lua")

    bot_scripts = brain + brain_policy
    for token in (
        "ModSettingsManifestResult",
        "ModSettingsValuesResult",
        "ParseModSettingsManifestJson",
        "LoadPersistedModSettings",
        "ValidateModSettingValue",
        "NormalizeModSettingValue",
        "SerializedModSettingListValueBytes",
        "kModSettingListMaxSerializedBytes = 8192",
        "IsCanonicalModSettingKeybind",
    ):
        assert token in header, f"native settings contract lacks: {token}"
    for token in (
        "^[a-z0-9_]{1,48}$",
        "settings.version must be 1",
        "duplicate key",
        "min must be less than max",
        "max_length",
        "choices",
        "default is forbidden for action",
    ):
        assert token in validator, f"native manifest validation lacks: {token}"
    for token in (
        "item.fields must contain 1-12 fields",
        "type must be toggle, number, text, or choice",
        "max_items must be an integer from 1 through 32",
        "min_items must be an integer from 0 through max_items",
        "item_label references unknown field",
        "ConvertJsonModSettingValue",
        "NormalizeModSettingValue",
    ):
        assert token in list_validator, (
            f"native list validation lacks: {token}"
        )
    for token in (
        "value must be a single line",
        "value exceeds max_length UTF-8 bytes",
        "MOUSE3",
        "MOUSE4",
        "MOUSE5",
        "number >= 1 && number <= 24",
        "serialized list value exceeds 8192 UTF-8 bytes",
    ):
        assert token in values, f"native value validation lacks: {token}"
    for token in (
        "kReadAttemptCount = 3",
        "kReadRetryDelay",
        "atomic-replace retry",
        "ignored persisted action setting",
        "ignored unknown persisted setting",
    ):
        assert token in persistence, f"atomic settings reader lacks: {token}"

    for token in (
        'kReplicatedSettingsModId[] = "SDMOD:settings"',
        "SetLuaModStateValue(",
        "PublishAuthoritativeLuaModStateSet(",
        "GetLocalTransportAuthorityParticipantId() != 0",
        "TryGetReplicatedValue",
        "!entry.requires_restart",
        "ScopedSuspendedSettingsPrivilege",
        "GetLuaSettingsPrivilegedExecState",
        "persisted_schema_invalid",
        "manifest_validation_failed",
        "LuaModValueType::Array",
        "LuaModValueType::Object",
        "ModSettingValueType::List",
        "result.entry_errors",
    ):
        assert token in runtime, f"settings runtime lacks: {token}"
    assert 'kReplicatedSettingsModId[] = "sd.settings"' not in runtime
    _require_in_order(
        runtime,
        "ModSettingValues next_local;",
        "ReadLocalValues(",
        "mod->local_settings_values[entry.key] = value->second",
        "ApplyEffectiveChange(",
        "PublishHostValue(",
    )

    for token in (
        '"sd.settings.get"',
        '"sd.settings.get_all"',
        '"sd.settings.on_changed"',
        '"sd.settings.on_action"',
        '"sd.settings.is_keybind_down"',
        "GetForegroundWindow()",
        "GetWindowThreadProcessId",
        "GetAsyncKeyState(virtual_key) & 0x8000",
        "VK_MBUTTON",
        "VK_XBUTTON1",
        "VK_XBUTTON2",
        "RequirePrivileged",
        "GetLuaSettingsPrivilegedExecState() != state",
        '"sd.__settings_reload"',
        '"sd.__settings_invoke_action"',
        "RemoveLuaSettingsPrivilegedBindings",
        '"entry_errors"',
    ):
        assert token in bindings, f"Lua settings bindings lack: {token}"
    assert "gameplay_seams" not in bindings
    for token in (
        "ScopedSettingsPrivilegedBindings",
        "InstallLuaSettingsPrivilegedBindings",
        "RemoveLuaSettingsPrivilegedBindings",
        "SetLuaSettingsPrivilegedExecState(state_)",
        "SetLuaSettingsPrivilegedExecState(nullptr)",
    ):
        assert token in engine, f"exec-pipe privilege scope lacks: {token}"
    assert "true);" in wait

    for token in (
        "CanonicalKeybindNames",
        "TryValidateValue",
        "throwOnInvalidBytes: true",
        "ValidateUnicode",
        "MOUSE3",
        "MOUSE4",
        "MOUSE5",
        "F24",
        "TryNormalizeListValue",
        "MaximumSerializedListValueBytes = 8192",
        "item.fields must contain 1-12 fields",
    ):
        assert token in manifest_service, f"C# validation lacks: {token}"
    _require_in_order(
        store,
        "FileMode.CreateNew",
        "stream.Flush(flushToDisk: true)",
        "File.Move(temporaryPath, path, overwrite: true)",
    )
    assert "throwOnInvalidBytes: true" in store
    for token in (
        "ModSettingValueType.List",
        "ModSettingsEntryValidationException",
        "TryNormalizeValue",
        "writer.WriteStartArray()",
    ):
        assert token in store, f"C# list store lacks: {token}"
    for token in (
        "List",
        "ListValue",
        "MinItems",
        "MaxItems",
        "ItemLabel",
        "ItemFields",
        "TryNormalizeValue",
    ):
        assert token in models, f"C# list models lack: {token}"
    assert "IModSettingsDiscoveryService" in discovery
    for token in (
        "public interface IModSettingsService",
        "public interface IModSettingsInstanceContext",
        "ModSettingsGameInstanceState",
        "string modsRootPath",
        "string stageRootPath",
        "_modsRootPath = Path.GetFullPath(modsRootPath)",
        "_store.Save(",
        "_runtime.ReloadAsync(",
        "_runtime.InvokeActionAsync(",
        "InstanceStateChanged",
    ):
        assert token in coordinator, f"view-facing service lacks: {token}"
    for token in (
        "public interface IModSettingsRuntimeClient",
        "__settings_reload",
        "__settings_invoke_action",
        "NamedPipeClientStream",
        "EntryErrors",
        "r.entry_errors",
    ):
        assert token in runtime_client, f"launcher pipe client lacks: {token}"

    required_rules = set(fixture["requiredRules"])
    accepted: set[str] = set()
    rejected: set[str] = set()
    for vector in fixture["vectors"]:
        (accepted if vector["valid"] else rejected).update(vector["rules"])
    assert required_rules
    assert required_rules <= accepted
    assert required_rules <= rejected
    required_value_rules = set(fixture["requiredValueRules"])
    value_accepted: set[str] = set()
    value_rejected: set[str] = set()
    for vector in fixture["valueVectors"]:
        (value_accepted if vector["valid"] else value_rejected).update(
            vector["rules"]
        )
    assert required_value_rules
    assert required_value_rules <= value_accepted
    assert required_value_rules <= value_rejected

    assert "settings.self" in bot_manifest["runtime"]["requiredCapabilities"]
    entries = {
        entry["key"]: entry
        for entry in bot_manifest["settings"]["entries"]
    }
    assert set(entries) == {
        "kite_radius",
        "offense_enabled",
        "roster",
        "think_profile",
        "focus_bot_key",
        "respawn_bot",
    }
    assert entries["kite_radius"]["default"] == 340
    assert entries["roster"]["type"] == "list"
    assert entries["roster"]["max_items"] == 3
    assert "persona_name" not in entries
    assert entries["respawn_bot"]["confirm"] is True
    for token in (
        'sd.settings.get("kite_radius")',
        'sd.settings.get("roster")',
        "not context.shared.offense_enabled",
        'sd.settings.on_changed(function(key, new_value, old_value)',
        'sd.settings.is_keybind_down("focus_bot_key")',
        'sd.settings.on_action("respawn_bot"',
        "manager:respawn_all(",
    ):
        assert token in bot_scripts, f"bot settings dogfood lacks: {token}"
    for token in (
        "context.bot:despawn()",
        "class = context.row.element",
        "roster entry ",
    ):
        assert token in roster, f"roster reconciliation lacks: {token}"

    for token in (
        'INSTANCE_PREFIX = "ms2"',
        "HOST_PORT = 49211",
        "CLIENT_PORT = 49212",
        "enable_audio=False",
        "kill_existing=False",
        "os.replace(temporary, path)",
        "stop_exact_game_processes(launch)",
        "guardian_ward_distance",
        "flee_threshold",
        "entry_error.roster",
        "EXHAUSTED_ROSTER",
        "__settings_reload",
    ):
        assert token in verifier, f"lifecycle verifier lacks: {token}"
    assert "stop_game_processes(" not in verifier
    assert "49011" not in verifier and "49012" not in verifier

    for token in (
        "sd.settings.is_keybind_down(entry_key)",
        "Harness keyboard injection",
        "reliable Lua mod-state stream",
        "No new Solomon Dark native address",
        "entry_errors",
        "8192-byte compact UTF-8 JSON cap",
    ):
        assert token in design, f"normative implementation notes lack: {token}"
    for token in (
        "GetAsyncKeyState",
        "MOUSE3",
        "MOUSE5",
        "requires_restart",
        "Structured lists",
        "ms2-host",
        "49211/49212",
    ):
        assert token in api_docs, f"settings API docs lack: {token}"
    assert "**`sd.settings`**" in roadmap
    for function_name in (
        "get",
        "get_all",
        "on_changed",
        "on_action",
        "is_keybind_down",
    ):
        assert (
            f"function sd_settings.{function_name}(" in generated
        ), f"generated sd.settings stub lacks: {function_name}"

    return (
        "Mod settings share strict native/C# validation, launcher-only atomic "
        "writes, scoped Lua reads, exec-only privileged mutation, reliable "
        "host state, foreground passive keybinds, and exact-pair acceptance"
    )
