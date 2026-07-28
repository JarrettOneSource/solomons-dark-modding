using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.IO.Pipes;
using SolomonDarkModding.Versioning;
using SolomonDarkModding.Updates;
using SolomonDarkModLauncher.App;
using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Launch;
using SolomonDarkModLauncher.ModSettings;
using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Steam;
using SolomonDarkModLauncher.Target;
using SolomonDarkModLauncher.UI.Infrastructure;
using SolomonDarkModLauncher.UI.ViewModels;
using SolomonDarkModLauncher.Workspace;
using SolomonDarkLauncherUpdater;
using SolomonDarkModding.IO;

var tests = new (string Name, Func<Task> Run)[]
{
    ("website package install and cache", TestWebsitePackageInstallAsync),
    ("automatic mod updates", TestAutomaticModUpdatesAsync),
    ("semantic version ordering", TestSemanticVersionOrderingAsync),
    ("minimum loader compatibility", TestMinimumLoaderCompatibilityAsync),
    ("launcher release selection", TestLauncherReleaseSelectionAsync),
    ("launcher download progress", TestLauncherDownloadProgressAsync),
    ("update progress JSON protocol", TestUpdateProgressJsonProtocolAsync),
    ("launcher update installation", TestLauncherUpdateInstallationAsync),
    ("no Desktop shell dependency", TestNoDesktopShellDependencyAsync),
    ("downloaded package traversal rejection", TestDownloadedPackageTraversalAsync),
    ("downloaded package contract", TestDownloadedPackageContractAsync),
    ("website lobby preflight", TestWebsiteLobbyPreflightAsync),
    ("lobby join preview classification", TestJoinPreviewClassificationAsync),
    ("exact manual catalog", TestExactManualCatalogAsync),
    ("canonical mod identifiers", TestCanonicalModIdentifiersAsync),
    ("strict multiplayer mod parity", TestStrictMultiplayerModParityAsync),
    ("loading screen asset staging", TestLoadingScreenAssetStagingAsync),
    ("Lua hot reload bootstrap", TestLuaHotReloadBootstrapAsync),
    ("Lua bus runtime contracts", TestLuaBusRuntimeContractsAsync),
    ("invalid Boneyard rejection", TestInvalidBoneyardRejectionAsync),
    ("automatic website sync with offline fallback", TestAutomaticWebsiteSyncAsync),
    ("website join URI", TestWebsiteJoinUriAsync),
    ("website install-mod URI", TestWebsiteInstallModUriAsync),
    ("website install-mod UI command ordering", TestWebsiteInstallModUiCommandOrderingAsync),
    ("scoped activation isolation", TestScopedActivationIsolationAsync),
    ("website install-mod pipeline", TestWebsiteInstallModPipelineAsync),
    ("clean install enables zero mods", TestCleanInstallEnablesZeroModsAsync),
    ("crash capture archive", TestCrashCaptureArchiveAsync),
    ("isolated local save catalog", TestIsolatedLocalSaveCatalogAsync),
    ("cloud save archive integrity", TestCloudSaveArchiveIntegrityAsync),
    ("selected save launch routing", TestSelectedSaveLaunchRoutingAsync),
    ("fresh install isolation", TestFreshInstallIsolationAsync),
    ("tutorial bypass launch routing", TestTutorialBypassLaunchRoutingAsync),
    ("audio disable launch routing", TestAudioDisableLaunchRoutingAsync),
    ("normal runtime hides diagnostic UI", TestNormalRuntimeHidesDiagnosticUiAsync),
    ("multiplayer quick-start launch routing", TestMultiplayerQuickStartLaunchRoutingAsync),
    ("manual lobby launch state", TestManualLobbyLaunchStateAsync),
    ("Steam lobby capacity bounds", TestSteamLobbyCapacityBoundsAsync),
    ("bot member status compatibility", TestBotMemberStatusCompatibilityAsync),
    ("Steam shortcut child launch identity", TestSteamShortcutChildLaunchIdentityAsync),
    ("Steam shortcut UI child isolation", TestSteamShortcutUiChildIsolationAsync),
    ("shared mod settings validation vectors", TestModSettingsValidationVectorsAsync),
    ("mod settings backend services", TestModSettingsBackendServicesAsync),
    ("bot-brain roster vocabulary migration", TestBotBrainRosterMigrationAsync),
    ("mod settings view-facing coordinator", TestModSettingsCoordinatorAsync)
};

static Task TestBotBrainRosterMigrationAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var settingsDirectory =
            Path.Combine(root, ".sdmod", "mod-settings");
        Directory.CreateDirectory(settingsDirectory);
        var settingsPath =
            Path.Combine(settingsDirectory, "bot.brain.json");
        File.WriteAllText(
            settingsPath,
            """
            {
              "schemaVersion": 1,
              "values": {
                "roster": [
                  {
                    "name": "Ember",
                    "element": "fire",
                    "discipline": "guardian"
                  },
                  {
                    "name": "Brook",
                    "element": "water",
                    "discipline": "striker"
                  }
                ]
              }
            }
            """);

        Require(
            BotBrainRosterSettingsMigration.TryMigrateStage(root),
            "legacy bot-brain roster was not migrated");
        using (var migrated = JsonDocument.Parse(
                   File.ReadAllText(settingsPath)))
        {
            var rows = migrated.RootElement
                .GetProperty("values")
                .GetProperty("roster")
                .EnumerateArray()
                .ToArray();
            Require(
                rows[0].GetProperty("behavior").GetString() == "guardian" &&
                rows[0].GetProperty("discipline").GetString() == "arcane" &&
                rows[1].GetProperty("behavior").GetString() == "striker" &&
                rows[1].GetProperty("discipline").GetString() == "arcane",
                "legacy AI Discipline was not rewritten as Behavior plus native Arcane");
        }

        var migratedBytes = File.ReadAllBytes(settingsPath);
        Require(
            !BotBrainRosterSettingsMigration.TryMigrateStage(root),
            "already-migrated bot-brain roster was rewritten again");
        Require(
            migratedBytes.SequenceEqual(File.ReadAllBytes(settingsPath)),
            "second migration changed the persisted roster");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
    return Task.CompletedTask;
}

var failures = 0;
foreach (var test in tests)
{
    try
    {
        await test.Run();
        Console.WriteLine($"PASS {test.Name}");
    }
    catch (Exception exception)
    {
        failures++;
        Console.Error.WriteLine($"FAIL {test.Name}: {exception}");
    }
}

return failures == 0 ? 0 : 1;

static Task TestModSettingsValidationVectorsAsync()
{
    var fixturePath = Path.Combine(
        AppContext.BaseDirectory,
        "fixtures",
        "mod-settings-validation-vectors.json");
    using var fixture = JsonDocument.Parse(File.ReadAllText(fixturePath));
    var root = fixture.RootElement;
    Require(
        root.GetProperty("schemaVersion").GetInt32() == 1,
        "mod-settings vectors use an unsupported schema");

    var required = root.GetProperty("requiredRules")
        .EnumerateArray()
        .Select(rule => rule.GetString() ?? string.Empty)
        .ToHashSet(StringComparer.Ordinal);
    var requiredValueRules = root.GetProperty("requiredValueRules")
        .EnumerateArray()
        .Select(rule => rule.GetString() ?? string.Empty)
        .ToHashSet(StringComparer.Ordinal);
    var accepts = new HashSet<string>(StringComparer.Ordinal);
    var rejects = new HashSet<string>(StringComparer.Ordinal);
    var valueAccepts = new HashSet<string>(StringComparer.Ordinal);
    var valueRejects = new HashSet<string>(StringComparer.Ordinal);
    var manifests = new Dictionary<string, JsonElement>(
        StringComparer.Ordinal);
    var service = new ModSettingsManifestService();
    var count = 0;
    foreach (var vector in root.GetProperty("vectors").EnumerateArray())
    {
        var name = vector.GetProperty("name").GetString() ?? string.Empty;
        Require(
            manifests.TryAdd(
                name,
                vector.GetProperty("manifest").Clone()),
            $"duplicate validation vector name '{name}'");
        var expected = vector.GetProperty("valid").GetBoolean();
        var validation = service.ValidateJson(
            vector.GetProperty("manifest").GetRawText());
        var actual =
            validation.Status == ModSettingsManifestStatus.Valid;
        Require(
            actual == expected,
            $"{name}: expected valid={expected}, actual status={validation.Status}, error={validation.Error}");
        foreach (var ruleElement in vector.GetProperty("rules").EnumerateArray())
        {
            var rule = ruleElement.GetString() ?? string.Empty;
            Require(
                required.Contains(rule),
                $"{name}: vector names unknown rule '{rule}'");
            (expected ? accepts : rejects).Add(rule);
        }
        count++;
    }
    foreach (var vector in root.GetProperty("valueVectors").EnumerateArray())
    {
        var name = vector.GetProperty("name").GetString() ?? string.Empty;
        var expected = vector.GetProperty("valid").GetBoolean();
        var definitionName =
            vector.GetProperty("definitionVector").GetString() ??
            string.Empty;
        var entryKey =
            vector.GetProperty("entryKey").GetString() ?? string.Empty;
        Require(
            manifests.TryGetValue(definitionName, out var manifest),
            $"{name}: referenced definition vector was not found");
        var validation = service.ValidateJson(manifest.GetRawText());
        Require(
            validation.Status == ModSettingsManifestStatus.Valid &&
            validation.Definition is not null,
            $"{name}: referenced definition is invalid: {validation.Error}");

        var temporaryRoot = CreateTemporaryDirectory();
        try
        {
            var store = new ModSettingsStore(service);
            var path = store.GetSettingsPath(
                temporaryRoot,
                "vector.value");
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(
                path,
                $$"""
                {
                  "schemaVersion": 1,
                  "values": {
                    "{{entryKey}}": {{vector.GetProperty("value").GetRawText()}}
                  }
                }
                """);
            var snapshot = store.Load(
                temporaryRoot,
                "vector.value",
                validation.Definition!);
            var actual = snapshot.Warnings.Count == 0;
            Require(
                actual == expected,
                $"{name}: expected value valid={expected}, warnings={string.Join("; ", snapshot.Warnings)}");
        }
        finally
        {
            Directory.Delete(temporaryRoot, recursive: true);
        }

        foreach (var ruleElement in
                 vector.GetProperty("rules").EnumerateArray())
        {
            var rule = ruleElement.GetString() ?? string.Empty;
            Require(
                requiredValueRules.Contains(rule),
                $"{name}: value vector names unknown rule '{rule}'");
            (expected ? valueAccepts : valueRejects).Add(rule);
        }
        count++;
    }

    foreach (var rule in required)
    {
        Require(
            accepts.Contains(rule) && rejects.Contains(rule),
            $"{rule}: C# suite requires one accept and reject vector");
    }
    foreach (var rule in requiredValueRules)
    {
        Require(
            valueAccepts.Contains(rule) && valueRejects.Contains(rule),
            $"{rule}: C# suite requires one accept and reject value vector");
    }
    Require(count >= 70, "shared validation vector coverage regressed");
    var expectedKeybinds = Enumerable.Range('A', 26)
        .Select(value => ((char)value).ToString())
        .Concat(Enumerable.Range(0, 10).Select(value => value.ToString()))
        .Concat(Enumerable.Range(1, 24).Select(value => $"F{value}"))
        .Concat(
        [
            "SPACE", "TAB", "ENTER", "SHIFT", "CTRL", "ALT",
            "UP", "DOWN", "LEFT", "RIGHT",
            "MOUSE3", "MOUSE4", "MOUSE5", "NONE"
        ])
        .ToArray();
    Require(
        service.CanonicalKeybindNames.SequenceEqual(expectedKeybinds),
        "canonical keybind namespace is incomplete or reordered");
    return Task.CompletedTask;
}

static async Task TestModSettingsBackendServicesAsync()
{
    var fixturePath = Path.Combine(
        AppContext.BaseDirectory,
        "fixtures",
        "mod-settings-validation-vectors.json");
    using var fixture = JsonDocument.Parse(File.ReadAllText(fixturePath));
    var manifestJson = fixture.RootElement
        .GetProperty("vectors")[0]
        .GetProperty("manifest")
        .GetRawText();
    var manifestService = new ModSettingsManifestService();
    var validation = manifestService.ValidateJson(manifestJson);
    Require(
        validation.Status == ModSettingsManifestStatus.Valid &&
        validation.Definition is not null,
        $"settings service rejected shared valid manifest: {validation.Error}");
    var definition = validation.Definition!;
    var textEntry = definition.Find("text_1") ??
        throw new InvalidOperationException(
            "shared valid vector has no text entry");
    Require(
        !manifestService.TryValidateValue(
            textEntry,
            ModSettingValue.String("\uD800"),
            out var invalidUtf8Error) &&
        invalidUtf8Error.Contains(
            "valid UTF-8",
            StringComparison.Ordinal),
        "settings validator accepted an unpaired UTF-16 surrogate");
    var invalidManifestUnicode = manifestService.ValidateJson(
        """
        {
          "settings": {
            "version": 1,
            "entries": [
              {
                "key": "name",
                "type": "text",
                "label": "\uD800",
                "default": ""
              }
            ]
          }
        }
        """);
    Require(
        invalidManifestUnicode.Status == ModSettingsManifestStatus.Invalid &&
        invalidManifestUnicode.Error.Contains(
            "valid UTF-8",
            StringComparison.Ordinal),
        "settings manifest accepted an unpaired Unicode surrogate");

    var root = CreateTemporaryDirectory();
    try
    {
        var store = new ModSettingsStore(manifestService);
        var values = definition.Entries
            .Where(entry =>
                entry.Type != ModSettingType.Action &&
                entry.DefaultValue is not null)
            .ToDictionary(
                entry => entry.Key,
                entry => entry.DefaultValue!,
                StringComparer.Ordinal);
        values["number_1"] = ModSettingValue.Number(8);
        values["text_1"] = ModSettingValue.String("é");
        store.Save(root, "vector.valid", definition, values);
        var path = store.GetSettingsPath(root, "vector.valid");
        Require(File.Exists(path), "settings store did not write canonical path");
        Require(
            !Directory.EnumerateFiles(
                    Path.GetDirectoryName(path)!,
                    "*.tmp")
                .Any(),
            "settings store left an atomic-write temporary file");
        using (var written = JsonDocument.Parse(File.ReadAllText(path)))
        {
            var writtenRoot = written.RootElement;
            Require(
                writtenRoot.GetProperty("schemaVersion").GetInt32() == 1,
                "settings store wrote the wrong schemaVersion");
            var writtenValues = writtenRoot.GetProperty("values");
            Require(
                writtenValues.GetProperty("number_1").GetDouble() == 8 &&
                !writtenValues.TryGetProperty("action_1", out _),
                "settings store did not preserve values or persisted an action");
        }

        var loaded = store.Load(root, "vector.valid", definition);
        Require(
            loaded.Values["number_1"].NumberValue == 8 &&
            loaded.Values["text_1"].StringValue == "é" &&
            loaded.Warnings.Count == 0,
            "settings store did not round-trip typed values");

        var listManifestJson = fixture.RootElement
            .GetProperty("vectors")
            .EnumerateArray()
            .Single(vector =>
                vector.GetProperty("name").GetString() ==
                    "accept_structured_list_entry")
            .GetProperty("manifest")
            .GetRawText();
        var listValidation =
            manifestService.ValidateJson(listManifestJson);
        Require(
            listValidation.Status == ModSettingsManifestStatus.Valid &&
            listValidation.Definition is not null,
            $"settings service rejected list schema: {listValidation.Error}");
        var normalizedListDefault = listValidation.Definition!
            .Find("roster")!
            .DefaultValue!
            .ListValue
            .Single();
        Require(
            normalizedListDefault.Count == 4 &&
            normalizedListDefault["enabled"].BooleanValue &&
            normalizedListDefault["weight"].NumberValue == 1.5,
            "settings model did not expose a normalized list default");
        var partialListRow =
            new Dictionary<string, ModSettingValue>(StringComparer.Ordinal)
            {
                ["name"] = ModSettingValue.String("River"),
                ["element"] = ModSettingValue.String("water")
            };
        var listValues = new Dictionary<string, ModSettingValue>(
            StringComparer.Ordinal)
        {
            ["roster"] = ModSettingValue.List([partialListRow])
        };
        store.Save(
            root,
            "vector.list",
            listValidation.Definition!,
            listValues);
        var loadedList = store.Load(
            root,
            "vector.list",
            listValidation.Definition!);
        var loadedRow = loadedList.Values["roster"].ListValue.Single();
        Require(
            loadedList.Warnings.Count == 0 &&
            loadedRow.Count == 4 &&
            loadedRow["enabled"].BooleanValue &&
            loadedRow["weight"].NumberValue == 1.5 &&
            loadedRow["name"].StringValue == "River" &&
            loadedRow["element"].StringValue == "water",
            "settings store did not normalize and round-trip a flat list row");
        using (var listDocument = JsonDocument.Parse(
                   File.ReadAllText(
                       store.GetSettingsPath(root, "vector.list"))))
        {
            var persistedRow = listDocument.RootElement
                .GetProperty("values")
                .GetProperty("roster")[0];
            Require(
                persistedRow.ValueKind == JsonValueKind.Object &&
                persistedRow.EnumerateObject().Count() == 4 &&
                persistedRow.GetProperty("name").GetString() == "River",
                "settings store did not persist the list as flat JSON objects");
        }

        var sizeManifestJson = fixture.RootElement
            .GetProperty("vectors")
            .EnumerateArray()
            .Single(vector =>
                vector.GetProperty("name").GetString() ==
                    "accept_list_schema_with_small_default_and_large_valid_runtime_space")
            .GetProperty("manifest")
            .GetRawText();
        var sizeValidation =
            manifestService.ValidateJson(sizeManifestJson);
        Require(
            sizeValidation.Status == ModSettingsManifestStatus.Valid &&
            sizeValidation.Definition is not null,
            $"settings service rejected list-size schema: {sizeValidation.Error}");
        var oversizedRows = Enumerable.Range(0, 32)
            .Select(_ =>
                (IReadOnlyDictionary<string, ModSettingValue>)
                new Dictionary<string, ModSettingValue>(
                    StringComparer.Ordinal))
            .ToArray();
        var oversizedRejected = false;
        try
        {
            store.Save(
                root,
                "vector.oversized",
                sizeValidation.Definition!,
                new Dictionary<string, ModSettingValue>(
                    StringComparer.Ordinal)
                {
                    ["rows"] = ModSettingValue.List(oversizedRows)
                });
        }
        catch (ModSettingsEntryValidationException exception)
            when (exception.EntryKey == "rows" &&
                  exception.Message.Contains(
                      "8192",
                      StringComparison.Ordinal))
        {
            oversizedRejected = true;
        }
        Require(
            oversizedRejected,
            "settings store accepted an oversized normalized list save");

        File.WriteAllText(
            path,
            """
            {
              "schemaVersion": 1,
              "values": {
                "number_1": 999,
                "unknown": true,
                "action_1": false
              }
            }
            """);
        var pruned = store.Load(root, "vector.valid", definition);
        Require(
            pruned.Values["number_1"].NumberValue == 4 &&
            !pruned.Values.ContainsKey("unknown") &&
            !pruned.Values.ContainsKey("action_1") &&
            pruned.Warnings.Count == 3,
            "settings store did not ignore invalid, unknown, and action values");

        var modsRoot = Path.Combine(root, "mods");
        var validRoot = Path.Combine(modsRoot, "valid");
        var invalidRoot = Path.Combine(modsRoot, "invalid");
        var noneRoot = Path.Combine(modsRoot, "none");
        Directory.CreateDirectory(validRoot);
        Directory.CreateDirectory(invalidRoot);
        Directory.CreateDirectory(noneRoot);
        File.WriteAllText(
            Path.Combine(validRoot, "manifest.json"),
            manifestJson);
        File.WriteAllText(
            Path.Combine(invalidRoot, "manifest.json"),
            """
            {
              "id": "invalid.settings",
              "name": "Invalid",
              "version": "1.0.0",
              "settings": { "version": 2, "entries": [] }
            }
            """);
        File.WriteAllText(
            Path.Combine(noneRoot, "manifest.json"),
            """
            {
              "id": "no.settings",
              "name": "None",
              "version": "1.0.0"
            }
            """);
        var discovered = new ModSettingsDiscoveryService(manifestService)
            .Discover(modsRoot);
        Require(
            discovered.Count == 2 &&
            discovered.Any(item =>
                item.Validation.Status ==
                ModSettingsManifestStatus.Valid) &&
            discovered.Any(item =>
                item.Validation.Status ==
                ModSettingsManifestStatus.Invalid),
            "settings discovery did not return valid and warning records only");

        var runtimeClient = new ModSettingsRuntimeClient();
        var reloadPipe =
            $"sdmod-settings-contract-{Guid.NewGuid():N}";
        var reloadServer = ServeLuaExecResponseAsync(
            reloadPipe,
            "__settings_reload",
            """
            {"ok":true,"print_output":"","results":["1","kite_radius\u001fthink_profile",""],"error":""}
            """);
        var reload = await runtimeClient.ReloadAsync(
            reloadPipe,
            "bot.brain");
        await reloadServer;
        Require(
            reload.Ok &&
            reload.Changed.SequenceEqual(
                new[] { "kite_radius", "think_profile" }) &&
            reload.EntryErrors.Count == 0 &&
            reload.Error.Length == 0,
            "runtime client did not decode privileged reload result");

        var entryErrorPipe =
            $"sdmod-settings-contract-{Guid.NewGuid():N}";
        var entryErrorServer = ServeLuaExecResponseAsync(
            entryErrorPipe,
            "__settings_reload",
            """
            {"ok":true,"print_output":"","results":["0","roster","one or more settings failed to apply","roster","roster entry 3 could not claim a gameplay slot"],"error":""}
            """);
        var entryErrorReload = await runtimeClient.ReloadAsync(
            entryErrorPipe,
            "bot.brain");
        await entryErrorServer;
        Require(
            !entryErrorReload.Ok &&
            entryErrorReload.Changed.SequenceEqual(["roster"]) &&
            entryErrorReload.EntryErrors.TryGetValue(
                "roster",
                out var rosterError) &&
            rosterError.Contains(
                "entry 3",
                StringComparison.Ordinal) &&
            entryErrorReload.Error ==
                "one or more settings failed to apply",
            "runtime client did not decode a per-entry reload error");

        var actionPipe =
            $"sdmod-settings-contract-{Guid.NewGuid():N}";
        var actionServer = ServeLuaExecResponseAsync(
            actionPipe,
            "__settings_invoke_action",
            """
            {"ok":true,"print_output":"","results":["1",""],"error":""}
            """);
        var action = await runtimeClient.InvokeActionAsync(
            actionPipe,
            "bot.brain",
            "respawn_bot");
        await actionServer;
        Require(
            action.Ok && action.Error.Length == 0,
            "runtime client did not decode privileged action result");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static async Task TestModSettingsCoordinatorAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var modsRoot = Path.Combine(root, "mods");
        var stageRoot = Path.Combine(root, "runtime", "stage");
        var modRoot = Path.Combine(modsRoot, "bot-brain");
        Directory.CreateDirectory(modRoot);
        File.WriteAllText(
            Path.Combine(modRoot, "manifest.json"),
            """
            {
              "id": "bot.brain",
              "name": "Bot Brain",
              "version": "0.1.0",
              "settings": {
                "version": 1,
                "entries": [
                  {
                    "key": "kite_radius",
                    "type": "number",
                    "label": "Kite radius",
                    "default": 340,
                    "min": 100,
                    "max": 900,
                    "step": 10,
                    "integer": true,
                    "scope": "host"
                  },
                  {
                    "key": "respawn_bot",
                    "type": "action",
                    "label": "Respawn bot",
                    "scope": "host",
                    "confirm": true
                  }
                ]
              }
            }
            """);

        var validator = new ModSettingsManifestService();
        var context = new ModSettingsInstanceContext();
        var runtime = new RecordingModSettingsRuntimeClient();
        var service = new ModSettingsService(
            modsRoot,
            stageRoot,
            new ModSettingsDiscoveryService(validator),
            new ModSettingsStore(validator),
            runtime,
            context);

        var stateEvents = 0;
        service.InstanceStateChanged += (_, _) => stateEvents++;
        var schema = service.GetSchema("bot.brain");
        Require(
            schema.Name == "Bot Brain" &&
            schema.Validation.Definition?.Entries.Count == 2,
            "coordinator did not expose the staged settings schema");

        var savedValues = new Dictionary<string, ModSettingValue>
        {
            ["kite_radius"] = ModSettingValue.Number(500)
        };
        var offlineSave = await service.SaveAsync(
            "bot.brain",
            savedValues);
        Require(
            offlineSave.Ok && runtime.ReloadCalls == 0,
            "offline settings save attempted live apply");
        var persisted = service.GetPersistedValues("bot.brain");
        Require(
            persisted.Values["kite_radius"].NumberValue == 500,
            "coordinator did not read its atomic persisted save");
        var invalidSave = await service.SaveAsync(
            "bot.brain",
            new Dictionary<string, ModSettingValue>
            {
                ["kite_radius"] = ModSettingValue.Number(999)
            });
        Require(
            !invalidSave.Ok &&
            invalidSave.EntryErrors.ContainsKey("kite_radius") &&
            runtime.ReloadCalls == 0,
            "coordinator did not surface a per-entry save validation error");

        context.Update(new OwnedModSettingsInstance
        {
            State = ModSettingsGameInstanceState.RunningHost,
            PipeName = "SolomonDarkModLoader_LuaExec_contract"
        });
        var liveSave = await service.SaveAsync("bot.brain", savedValues);
        Require(
            liveSave.Ok &&
            runtime.ReloadCalls == 1 &&
            runtime.LastPipeName ==
                "SolomonDarkModLoader_LuaExec_contract" &&
            stateEvents == 1 &&
            service.InstanceState ==
                ModSettingsGameInstanceState.RunningHost,
            "coordinator did not route live save through the owned instance");

        context.Update(new OwnedModSettingsInstance
        {
            State =
                ModSettingsGameInstanceState.RunningClientInSession,
            PipeName = "SolomonDarkModLoader_LuaExec_contract"
        });
        var rejected = await service.InvokeActionAsync(
            "bot.brain",
            "respawn_bot");
        Require(
            !rejected.Ok &&
            rejected.Error.Contains(
                "session authority",
                StringComparison.OrdinalIgnoreCase) &&
            runtime.ActionCalls == 0,
            "coordinator allowed a client host-scope action");

        context.Update(new OwnedModSettingsInstance
        {
            State = ModSettingsGameInstanceState.RunningHost,
            PipeName = "SolomonDarkModLoader_LuaExec_contract"
        });
        var invoked = await service.InvokeActionAsync(
            "bot.brain",
            "respawn_bot");
        Require(
            invoked.Ok &&
            runtime.ActionCalls == 1 &&
            runtime.LastModId == "bot.brain" &&
            runtime.LastEntryKey == "respawn_bot",
            "coordinator did not route the host action to the runtime client");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static async Task ServeLuaExecResponseAsync(
    string pipeName,
    string requiredRequestToken,
    string response)
{
    await using var pipe = new NamedPipeServerStream(
        pipeName,
        PipeDirection.InOut,
        1,
        PipeTransmissionMode.Message,
        PipeOptions.Asynchronous);
    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
    await pipe.WaitForConnectionAsync(timeout.Token);
    using var request = new MemoryStream();
    var buffer = new byte[4096];
    do
    {
        var count = await pipe.ReadAsync(buffer, timeout.Token);
        Require(count > 0, "runtime client sent an empty Lua request");
        request.Write(buffer, 0, count);
    }
    while (!pipe.IsMessageComplete);
    var code = Encoding.UTF8.GetString(request.ToArray());
    Require(
        code.Contains(requiredRequestToken, StringComparison.Ordinal),
        $"runtime client omitted {requiredRequestToken}");
    var payload = Encoding.UTF8.GetBytes(response);
    await pipe.WriteAsync(payload, timeout.Token);
    await pipe.FlushAsync(timeout.Token);
}

static Task TestNoDesktopShellDependencyAsync()
{
    var workspaceRoot = WorkspaceLocator.FindRootPath(AppContext.BaseDirectory);
    var uiRoot = Path.Combine(workspaceRoot, "SolomonDarkModLauncher.UI");
    var updaterRoot = Path.Combine(workspaceRoot, "SolomonDarkLauncherUpdater");
    var launcherRoot = Path.Combine(workspaceRoot, "SolomonDarkModLauncher");
    var sharedRoot = Path.Combine(workspaceRoot, "Shared");
    var launcherShellPath = Path.Combine(
        uiRoot,
        "src",
        "Infrastructure",
        "LauncherShell.cs");
    var productSources = new[] { uiRoot, updaterRoot, launcherRoot, sharedRoot }
        .SelectMany(root => Directory.EnumerateFiles(
            root,
            "*.cs",
            SearchOption.AllDirectories))
        .Where(path =>
            !path.Contains($"{Path.DirectorySeparatorChar}bin{Path.DirectorySeparatorChar}") &&
            !path.Contains($"{Path.DirectorySeparatorChar}obj{Path.DirectorySeparatorChar}"))
        .ToArray();

    foreach (var path in productSources)
    {
        var source = File.ReadAllText(path);
        Require(
            !source.Contains("SpecialFolder.Desktop", StringComparison.Ordinal) &&
            !source.Contains("SpecialFolder.DesktopDirectory", StringComparison.Ordinal) &&
            !source.Contains("FOLDERID_Desktop", StringComparison.Ordinal) &&
            !source.Contains("WScript.Shell", StringComparison.Ordinal) &&
            !source.Contains(".lnk", StringComparison.OrdinalIgnoreCase),
            $"launcher source depends on Desktop or shortcut resolution: {Path.GetRelativePath(workspaceRoot, path)}");

        if (!string.Equals(
                Path.GetFullPath(path),
                Path.GetFullPath(launcherShellPath),
                StringComparison.OrdinalIgnoreCase))
        {
            Require(
                !source.Contains("OpenFolderDialog", StringComparison.Ordinal) &&
                !source.Contains("UseShellExecute = true", StringComparison.Ordinal) &&
                !source.Contains("\"explorer.exe\"", StringComparison.OrdinalIgnoreCase),
                $"launcher shell access bypasses LauncherShell: {Path.GetRelativePath(workspaceRoot, path)}");
        }

        var processStartIndex = 0;
        while ((processStartIndex = source.IndexOf(
                   "new ProcessStartInfo",
                   processStartIndex,
                   StringComparison.Ordinal)) >= 0)
        {
            var initializerEnd = source.IndexOf(
                "};",
                processStartIndex,
                StringComparison.Ordinal);
            Require(
                initializerEnd >= 0 &&
                source.AsSpan(
                    processStartIndex,
                    initializerEnd - processStartIndex)
                    .Contains(
                        "WorkingDirectory",
                        StringComparison.Ordinal),
                $"launcher child process inherits its caller working directory: {Path.GetRelativePath(workspaceRoot, path)}");
            processStartIndex = initializerEnd + 2;
        }
    }

    var mainViewModel = File.ReadAllText(Path.Combine(
        uiRoot,
        "src",
        "ViewModels",
        "MainWindowViewModel.cs"));
    var saveViewModel = File.ReadAllText(Path.Combine(
        uiRoot,
        "src",
        "ViewModels",
        "SaveManagerViewModel.cs"));
    var modViewModel = File.ReadAllText(Path.Combine(
        uiRoot,
        "src",
        "ViewModels",
        "ModItemViewModel.cs"));
    var updaterProgram = File.ReadAllText(Path.Combine(
        updaterRoot,
        "Program.cs"));
    var launcherShell = File.ReadAllText(launcherShellPath);

    Require(
        !mainViewModel.Contains("new OpenFolderDialog", StringComparison.Ordinal),
        "game-folder selection bypasses the guarded non-Desktop folder policy");
    Require(
        !saveViewModel.Contains("new OpenFolderDialog", StringComparison.Ordinal),
        "save import bypasses the guarded non-Desktop folder policy");
    Require(
        !mainViewModel.Contains("UseShellExecute = true", StringComparison.Ordinal) &&
        !saveViewModel.Contains("UseShellExecute = true", StringComparison.Ordinal) &&
        !modViewModel.Contains("UseShellExecute = true", StringComparison.Ordinal),
        "a launcher view model invokes the Windows shell directly");
    Require(
        !updaterProgram.Contains("UseShellExecute = true", StringComparison.Ordinal),
        "the updater restart invokes the Windows shell");
    Require(
        launcherShell.Contains(
            "InitialDirectory = initialDirectory",
            StringComparison.Ordinal) &&
        launcherShell.Contains(
            "DefaultDirectory = initialDirectory",
            StringComparison.Ordinal),
        "folder dialogs do not force a resolved non-Desktop initial directory");
    Require(
        launcherShell.Contains("DereferenceLinks = false", StringComparison.Ordinal) &&
        launcherShell.Contains("AddToRecent = false", StringComparison.Ordinal),
        "folder dialogs can resolve or persist shell locations");
    Require(
        launcherShell.Contains("ErrorDialog = false", StringComparison.Ordinal),
        "URI shell activation can surface a Windows error dialog");
    Require(
        !launcherShell.Contains(
            "WorkingDirectory = AppContext.BaseDirectory",
            StringComparison.Ordinal),
        "shell operations can inherit a Desktop-based install directory");

    var root = CreateTemporaryDirectory();
    try
    {
        var deniedDesktop = Path.Combine(root, "Desktop");
        var documents = Path.Combine(root, "Documents");
        var applicationData = Path.Combine(root, "AppData", "Local");
        var installDirectory = Path.Combine(root, "Launcher");
        var log = new List<string>();
        var desktopWasProbed = false;
        var resolvedDefault = LauncherPathPolicy.ResolveReadableDirectory(
            [deniedDesktop, documents, applicationData, installDirectory],
            log.Add,
            path =>
            {
                if (string.Equals(
                        path,
                        deniedDesktop,
                        StringComparison.OrdinalIgnoreCase))
                {
                    desktopWasProbed = true;
                    throw new UnauthorizedAccessException(
                        "The Desktop fixture must be rejected before enumeration.");
                }

                return string.Equals(
                    path,
                    documents,
                    StringComparison.OrdinalIgnoreCase);
            });
        Require(
            string.Equals(
                resolvedDefault,
                documents,
                StringComparison.OrdinalIgnoreCase),
            "denied Desktop did not fall back to Documents");
        Require(
            log.Any(message =>
                message.Contains(deniedDesktop, StringComparison.OrdinalIgnoreCase)),
            "denied Desktop fallback did not emit a log line");
        Require(
            !desktopWasProbed,
            "folder dialog policy enumerated Desktop before falling back");

        log.Clear();
        var resolvedApplicationData = LauncherPathPolicy.ResolveApplicationDataRoot(
            log.Add,
            localApplicationDataPath: deniedDesktop,
            temporaryPath: applicationData,
            canWriteDirectory: path => path.StartsWith(
                applicationData,
                StringComparison.OrdinalIgnoreCase));
        Require(
            resolvedApplicationData.StartsWith(
                applicationData,
                StringComparison.OrdinalIgnoreCase) &&
            !resolvedApplicationData.StartsWith(
                deniedDesktop,
                StringComparison.OrdinalIgnoreCase),
            "launcher application data fell back through Desktop");
        Require(
            log.Any(message =>
                message.Contains(deniedDesktop, StringComparison.OrdinalIgnoreCase)),
            "denied application-data fallback did not emit a log line");
        Require(
            !LauncherLog.GetPath(resolvedApplicationData).StartsWith(
                deniedDesktop,
                StringComparison.OrdinalIgnoreCase),
            "launcher log path depends on Desktop");

        var settingsRoot = Path.Combine(root, "settings");
        Directory.CreateDirectory(settingsRoot);
        File.WriteAllText(
            Path.Combine(settingsRoot, "settings.json"),
            JsonSerializer.Serialize(new
            {
                gameDirectory = deniedDesktop
            }));
        var settings = new LauncherUiSettingsStore(settingsRoot);
        Require(
            settings.LoadGameDirectory() is null,
            "saved Desktop game directory remained active");
        var launcherLogPath = LauncherLog.GetPath(settingsRoot);
        Require(
            File.Exists(launcherLogPath) &&
            File.ReadAllText(launcherLogPath).Contains(
                deniedDesktop,
                StringComparison.OrdinalIgnoreCase),
            "ignored saved Desktop directory did not emit a log line");
        RequireThrows<InvalidOperationException>(
            () => settings.SaveGameDirectory(deniedDesktop),
            "launcher persisted a Desktop game directory");
        RequireThrows<InvalidOperationException>(
            () => StageSandboxCompatibilityLinks.Materialize(
                deniedDesktop,
                documents),
            "launcher staging touched a Desktop path");
        RequireThrows<ArgumentException>(
            () => LauncherUpdateInstaller.ResolvePackagedPath(
                deniedDesktop,
                "launcher.exe"),
            "updater accepted a Desktop target path");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    RequireThrows<ArgumentException>(
        () => LauncherUpdateInstaller.ResolvePackagedPath(
            "relative-launcher-root",
            "launcher.exe"),
        "updater accepted a current-directory-relative target path");

    return Task.CompletedTask;
}

static Task TestNormalRuntimeHidesDiagnosticUiAsync()
{
    var normal = RuntimeStageFlags.Create(RuntimeStageOptions.Default);
    Require(
        !normal.LoaderDebugUi,
        "the normal full runtime enabled diagnostic UI surfaces");

    var diagnostic = RuntimeStageFlags.Create(
        RuntimeStageOptions.Create(
            "full",
            [RuntimeStageFlags.LoaderDebugUiKey + "=true"]));
    Require(
        diagnostic.LoaderDebugUi,
        "the explicit diagnostic UI runtime override was ignored");

    return Task.CompletedTask;
}

static Task TestIsolatedLocalSaveCatalogAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var retailSavegamesRoot = Path.Combine(root, "retail", "savegames");
        var retailFilePath = Path.Combine(
            retailSavegamesRoot,
            "solomondark",
            "player.sav");
        Directory.CreateDirectory(Path.GetDirectoryName(retailFilePath)!);
        File.WriteAllText(retailFilePath, "retail-save");

        var launcherSettingsRoot = Path.Combine(root, "launcher");
        var settings = new LauncherUiSettingsStore(launcherSettingsRoot);
        var catalog = new LocalSaveCatalog(settings);
        Require(catalog.List().Count == LocalSaveCatalog.SlotCount, "launcher did not create eight save slots");
        Require(catalog.List().All(save => !save.HasLocalData), "retail save data leaked into a launcher slot");
        Require(
            Path.GetFullPath(catalog.SavesRoot) ==
            Path.GetFullPath(Path.Combine(launcherSettingsRoot, "saves")),
            "launcher saves were not rooted beneath the launcher settings area");

        var imported = catalog.Import(2, retailSavegamesRoot);
        Require(imported.HasLocalData, "explicit save import did not populate the selected slot");
        var importedFilePath = Path.Combine(
            imported.SavegamesRootPath,
            "solomondark",
            "player.sav");
        Require(
            File.ReadAllText(importedFilePath) == "retail-save",
            "explicit save import changed the save contents");
        File.WriteAllText(importedFilePath, "launcher-save");
        Require(
            File.ReadAllText(retailFilePath) == "retail-save",
            "launcher save writes contaminated the retail save");

        catalog.Select(2);
        catalog.Rename(2, "Steam Deck");
        catalog.MarkBackedUp(2, new string('a', 64), DateTimeOffset.UtcNow);

        var reloaded = new LocalSaveCatalog(
            new LauncherUiSettingsStore(launcherSettingsRoot));
        Require(reloaded.ActiveSlot == 2, "active save selection did not persist");
        Require(reloaded.Active.Name == "Steam Deck", "save name did not persist");
        Require(
            reloaded.Active.LastBackupFingerprint == new string('a', 64),
            "cloud backup receipt did not persist");

        RequireThrows<InvalidOperationException>(
            () => catalog.Import(3, Path.Combine(root, "not-a-savegames-folder")),
            "save import accepted a folder without solomondark");
        RequireThrows<InvalidOperationException>(
            () => SaveDirectoryMirror.Replace(
                imported.SavegamesRootPath,
                Path.Combine(imported.SavegamesRootPath, "nested")),
            "save replacement accepted overlapping paths");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestCloudSaveArchiveIntegrityAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var catalog = new LocalSaveCatalog(
            new LauncherUiSettingsStore(Path.Combine(root, "launcher")));
        catalog.Rename(0, "Wizard One");
        var playerFilePath = Path.Combine(
            catalog.Get(0).SavegamesRootPath,
            "solomondark",
            "player.sav");
        var nestedFilePath = Path.Combine(
            catalog.Get(0).SavegamesRootPath,
            "solomondark",
            "profiles",
            "achievements.dat");
        Directory.CreateDirectory(Path.GetDirectoryName(playerFilePath)!);
        Directory.CreateDirectory(Path.GetDirectoryName(nestedFilePath)!);
        File.WriteAllText(playerFilePath, "player-state");
        File.WriteAllBytes(nestedFilePath, [0, 1, 2, 3, 4]);

        var first = CloudSaveArchive.Build(catalog.Get(0));
        var repeated = CloudSaveArchive.Build(catalog.Get(0));
        Require(
            first.Bytes.SequenceEqual(repeated.Bytes),
            "unchanged local saves did not create a deterministic backup");
        Require(first.FileCount == 2, "cloud backup manifest lost a save file");

        File.WriteAllText(playerFilePath, "newer-local-state");
        catalog.Rename(0, "Temporary Name");
        var restoredName = CloudSaveArchive.Restore(catalog, 0, first.Bytes);
        Require(restoredName == "Wizard One", "cloud restore lost the saved slot name");
        Require(
            File.ReadAllText(playerFilePath) == "player-state",
            "cloud restore did not replace the local snapshot");

        var tamperedBytes = first.Bytes.ToArray();
        using (var stream = new MemoryStream(tamperedBytes))
        using (var archive = new ZipArchive(stream, ZipArchiveMode.Update, leaveOpen: true))
        {
            archive.GetEntry("savegames/solomondark/player.sav")!.Delete();
            var replacement = archive.CreateEntry(
                "savegames/solomondark/player.sav",
                CompressionLevel.Optimal);
            using var replacementStream = replacement.Open();
            replacementStream.Write("tampered"u8);
        }
        File.WriteAllText(playerFilePath, "preserve-on-rejection");
        RequireThrows<InvalidDataException>(
            () => CloudSaveArchive.Restore(catalog, 0, tamperedBytes),
            "cloud restore accepted a file with a mismatched hash");
        Require(
            File.ReadAllText(playerFilePath) == "preserve-on-rejection",
            "rejected cloud restore changed the local save");

        var traversalArchive = CreateZip(new Dictionary<string, byte[]>
        {
            ["manifest.json"] = """
                {
                  "schemaVersion": 1,
                  "slot": 0,
                  "name": "Unsafe",
                  "files": [{
                    "path": "../outside.sav",
                    "size": 1,
                    "sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"
                  }]
                }
                """u8.ToArray(),
            ["savegames/../outside.sav"] = "a"u8.ToArray()
        });
        RequireThrows<InvalidDataException>(
            () => CloudSaveArchive.Restore(catalog, 0, traversalArchive),
            "cloud restore accepted path traversal");
        Require(!File.Exists(Path.Combine(root, "outside.sav")), "cloud restore escaped its slot");

        var unsafeNameArchive = CreateZip(new Dictionary<string, byte[]>
        {
            ["manifest.json"] = """
                {
                  "schemaVersion": 1,
                  "slot": 0,
                  "name": "unsafe\u0001name",
                  "files": [{
                    "path": "solomondark/player.sav",
                    "size": 1,
                    "sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"
                  }]
                }
                """u8.ToArray(),
            ["savegames/solomondark/player.sav"] = "a"u8.ToArray()
        });
        RequireThrows<InvalidDataException>(
            () => CloudSaveArchive.Restore(catalog, 0, unsafeNameArchive),
            "cloud restore accepted a control character in the save name");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestSelectedSaveLaunchRoutingAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var selectedSavegamesRoot = Path.Combine(root, "selected", "savegames");
        var command = LauncherCommandParser.Parse(
        [
            "launch",
            "--savegames-root", selectedSavegamesRoot,
            "--multiplayer", "host",
            "--no-invite-dialog"
        ]);
        Require(
            command.SavegamesRootOverride == selectedSavegamesRoot,
            "launcher parser lost the selected save directory");
        Require(
            !command.OpenSteamInviteDialog,
            "Host Game did not suppress the automatic Steam invite picker");

        var workspace = WorkspacePaths.Create(
            Path.Combine(root, "workspace"),
            modsRootOverride: null,
            runtimeRootOverride: null,
            stageRootOverride: null);
        var defaultOptions = IsolatedProfileBootstrapper.CreateLaunchOptions(workspace);
        Require(
            defaultOptions.SavegamesRootPath ==
            Path.Combine(workspace.ProfileRootPath, "savegames"),
            "headless launcher defaulted saves into the staged retail tree");

        var selectedOptions = IsolatedProfileBootstrapper.CreateLaunchOptions(
            workspace,
            savegamesRootOverride: selectedSavegamesRoot);
        Require(
            selectedOptions.SavegamesRootPath == Path.GetFullPath(selectedSavegamesRoot),
            "selected save directory was not preserved in launch options");
        Require(
            Directory.Exists(selectedSavegamesRoot),
            "selected save directory was not prepared before launch");

        var mirrorSource = Path.Combine(root, "proton-stage-savegames");
        var localDestination = Path.Combine(root, "launcher-savegames");
        var sourceFile = Path.Combine(mirrorSource, "solomondark", "player.sav");
        var staleFile = Path.Combine(localDestination, "solomondark", "stale.sav");
        Directory.CreateDirectory(Path.GetDirectoryName(sourceFile)!);
        Directory.CreateDirectory(Path.GetDirectoryName(staleFile)!);
        File.WriteAllText(sourceFile, "proton-updated-save");
        File.WriteAllText(staleFile, "stale-save");
        SaveDirectoryMirror.Replace(mirrorSource, localDestination);
        Require(
            File.ReadAllText(Path.Combine(localDestination, "solomondark", "player.sav")) ==
            "proton-updated-save",
            "Proton stage copy-back lost the updated save");
        Require(!File.Exists(staleFile), "Proton stage copy-back retained stale local files");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestFreshInstallIsolationAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var sourceRoot = Path.Combine(root, "source-game");
        var stageRoot = Path.Combine(root, "stage");
        var sourceSandboxFile = Path.Combine(
            sourceRoot,
            "sandbox",
            "savegames",
            "solomondark",
            "retail.sav");
        var staleStageFile = Path.Combine(
            stageRoot,
            "sandbox",
            "savegames",
            "solomondark",
            "stale.sav");
        var stageMetadataFile = Path.Combine(stageRoot, ".sdmod", "keep.txt");
        Directory.CreateDirectory(Path.GetDirectoryName(sourceSandboxFile)!);
        Directory.CreateDirectory(Path.GetDirectoryName(staleStageFile)!);
        Directory.CreateDirectory(Path.GetDirectoryName(stageMetadataFile)!);
        File.WriteAllText(Path.Combine(sourceRoot, "SolomonDark.exe"), "game");
        File.WriteAllText(sourceSandboxFile, "retail-save");
        File.WriteAllText(staleStageFile, "stale-stage-save");
        File.WriteAllText(stageMetadataFile, "metadata");

        FileTreeMirror.Synchronize(
            sourceRoot,
            stageRoot,
            excludeSandbox: true);
        Require(
            File.Exists(Path.Combine(stageRoot, "SolomonDark.exe")),
            "fresh-install staging lost the base game");
        Require(
            !Directory.Exists(Path.Combine(stageRoot, "sandbox")),
            "fresh-install staging retained source or stale sandbox data");
        Require(
            File.ReadAllText(stageMetadataFile) == "metadata",
            "fresh-install staging removed launcher metadata");
        Require(
            File.ReadAllText(sourceSandboxFile) == "retail-save",
            "fresh-install staging changed source sandbox data");

        var retailAppDataRoot = Path.Combine(root, "retail-appdata");
        var retailProfileFile = Path.Combine(retailAppDataRoot, "retail-profile.dat");
        Directory.CreateDirectory(retailAppDataRoot);
        File.WriteAllText(retailProfileFile, "retail-profile");

        var workspace = WorkspacePaths.Create(
            Path.Combine(root, "workspace"),
            modsRootOverride: null,
            runtimeRootOverride: null,
            stageRootOverride: null);
        var first = IsolatedProfileBootstrapper.CreateLaunchOptions(
            workspace,
            retailGameAppDataPath: retailAppDataRoot,
            freshInstall: true);
        Require(first.TemporaryProfile, "fresh install did not force a temporary profile");
        Require(
            first.ProfileRootPath is not null &&
            Path.GetFullPath(first.ProfileRootPath).StartsWith(
                Path.GetFullPath(workspace.RuntimeRootPath) +
                    Path.DirectorySeparatorChar,
                StringComparison.OrdinalIgnoreCase),
            "fresh-install profile escaped the isolated runtime root");
        Require(
            first.SavegamesRootPath is not null &&
            !Directory.EnumerateFileSystemEntries(first.SavegamesRootPath).Any(),
            "fresh-install save root was not empty");
        Require(
            !File.Exists(
                Path.Combine(
                    first.ProfileRootPath!,
                    "AppData",
                    "Roaming",
                    "solomondark",
                    "retail-profile.dat")),
            "fresh install imported the retail APPDATA profile");

        var isolatedSentinel = Path.Combine(first.ProfileRootPath!, "stale-profile.dat");
        File.WriteAllText(isolatedSentinel, "stale-isolated-data");
        _ = IsolatedProfileBootstrapper.CreateLaunchOptions(
            workspace,
            retailGameAppDataPath: retailAppDataRoot,
            freshInstall: true);
        Require(
            !File.Exists(isolatedSentinel),
            "fresh install did not reset its own isolated profile");
        Require(
            File.ReadAllText(retailProfileFile) == "retail-profile",
            "fresh install changed the retail APPDATA profile");

        var command = LauncherCommandParser.Parse(["launch", "--fresh-install"]);
        Require(command.FreshInstall, "launcher parser lost --fresh-install");
        Require(
            command.TemporaryProfile,
            "--fresh-install did not imply --temporary-profile");
        RequireThrows<InvalidOperationException>(
            () => LauncherCommandParser.Parse(
                ["launch", "--fresh-install", "--savegames-root", Path.Combine(root, "external")]),
            "--fresh-install accepted an external savegames root");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestMultiplayerQuickStartLaunchRoutingAsync()
{
    var options = new LaunchOptions(
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["PRESERVED"] = "value"
        });
    var host = MultiplayerLaunchEnvironment.Apply(
        options,
        MultiplayerLaunchOptions.Create(
            MultiplayerLaunchMode.Host,
            lobbyId: null,
            inviteSteamId: null,
            MultiplayerLaunchOptions.DefaultMaxParticipants,
            openInviteDialog: false));
    Require(
        host.EnvironmentOverrides?[MultiplayerLaunchEnvironment.QuickStartVariable] == "1",
        "Host Game did not enable multiplayer quick start");
    Require(
        host.EnvironmentOverrides?["PRESERVED"] == "value",
        "Host Game discarded an existing launch environment override");

    var join = MultiplayerLaunchEnvironment.Apply(
        options,
        MultiplayerLaunchOptions.Create(
            MultiplayerLaunchMode.Join,
            lobbyId: 123,
            inviteSteamId: null,
            MultiplayerLaunchOptions.DefaultMaxParticipants,
            openInviteDialog: true));
    Require(
        join.EnvironmentOverrides?[MultiplayerLaunchEnvironment.QuickStartVariable] == "1",
        "explicit multiplayer join launch did not enable quick start");

    var localJoin = MultiplayerLaunchEnvironment.Apply(
        new LaunchOptions(
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                [MultiplayerLaunchEnvironment.TransportVariable] = "local_udp",
                [MultiplayerLaunchEnvironment.RoleVariable] = "client"
            }),
        MultiplayerLaunchOptions.Create(
            MultiplayerLaunchMode.Join,
            lobbyId: 123,
            inviteSteamId: null,
            MultiplayerLaunchOptions.DefaultMaxParticipants,
            openInviteDialog: true));
    Require(
        localJoin.EnvironmentOverrides?[
            MultiplayerLaunchEnvironment.TransportVariable] == "local_udp" &&
        localJoin.EnvironmentOverrides?[
            MultiplayerLaunchEnvironment.RoleVariable] == "client" &&
        localJoin.EnvironmentOverrides?[
            MultiplayerLaunchEnvironment.LobbyIdVariable] == "123",
        "concrete website join replaced the explicit local test transport");

    var disabled = MultiplayerLaunchEnvironment.Apply(
        host,
        MultiplayerLaunchOptions.Create(
            MultiplayerLaunchMode.Off,
            lobbyId: null,
            inviteSteamId: null,
            MultiplayerLaunchOptions.DefaultMaxParticipants,
            openInviteDialog: true));
    Require(
        disabled.EnvironmentOverrides?[MultiplayerLaunchEnvironment.QuickStartVariable] == string.Empty,
        "single-player launch did not clear multiplayer quick start");

    return Task.CompletedTask;
}

static Task TestTutorialBypassLaunchRoutingAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var defaultCommand = LauncherCommandParser.Parse(["launch"]);
        Require(
            !defaultCommand.ShowStockTutorial,
            "launcher default unexpectedly opted in to the stock tutorial");
        var tutorialCommand = LauncherCommandParser.Parse(
            ["launch", "--show-stock-tutorial"]);
        Require(
            tutorialCommand.ShowStockTutorial,
            "launcher parser lost --show-stock-tutorial");

        var settingsRoot = Path.Combine(root, "ui-settings");
        var settings = new LauncherUiSettingsStore(settingsRoot);
        Require(
            !settings.LoadShowStockTutorial(),
            "desktop launcher settings defaulted to the stock tutorial");
        settings.SaveShowStockTutorial(true);
        Require(
            new LauncherUiSettingsStore(settingsRoot)
                .LoadShowStockTutorial(),
            "desktop launcher did not persist the stock tutorial opt-in");

        var workspace = WorkspacePaths.Create(
            Path.Combine(root, "workspace"),
            modsRootOverride: null,
            runtimeRootOverride: null,
            stageRootOverride: null);
        var profileCases = new[]
        {
            (Name: "normal", Temporary: false, Fresh: false),
            (Name: "temporary", Temporary: true, Fresh: false),
            (Name: "fresh-install", Temporary: false, Fresh: true)
        };
        var launchModes = new[]
        {
            MultiplayerLaunchMode.Unspecified,
            MultiplayerLaunchMode.Off,
            MultiplayerLaunchMode.Host,
            MultiplayerLaunchMode.Join
        };

        foreach (var profileCase in profileCases)
        {
            var profileOptions =
                IsolatedProfileBootstrapper.CreateLaunchOptions(
                    workspace,
                    new Dictionary<string, string>(
                        StringComparer.OrdinalIgnoreCase)
                    {
                        ["PRESERVED"] = profileCase.Name,
                        [TutorialLaunchEnvironment
                            .SkipFreshSaveTutorialVariable] =
                            string.Empty
                    },
                    temporaryProfile: profileCase.Temporary,
                    freshInstall: profileCase.Fresh);

            foreach (var mode in launchModes)
            {
                var multiplayer = MultiplayerLaunchOptions.Create(
                    mode,
                    lobbyId: null,
                    inviteSteamId: null,
                    MultiplayerLaunchOptions.DefaultMaxParticipants,
                    openInviteDialog:
                        mode != MultiplayerLaunchMode.Host);
                var defaultLaunch = MultiplayerLaunchEnvironment.Apply(
                    TutorialLaunchEnvironment.Apply(
                        profileOptions,
                        showStockTutorial: false),
                    multiplayer);
                Require(
                    defaultLaunch.EnvironmentOverrides?[
                        TutorialLaunchEnvironment
                            .SkipFreshSaveTutorialVariable] == "1",
                    $"{profileCase.Name} {mode} launch omitted the tutorial-bypass signal");
                Require(
                    defaultLaunch.EnvironmentOverrides?["PRESERVED"] ==
                        profileCase.Name,
                    $"{profileCase.Name} {mode} launch discarded existing environment overrides");
                Require(
                    defaultLaunch.EnvironmentOverrides?["APPDATA"] is not null &&
                    defaultLaunch.EnvironmentOverrides?["LOCALAPPDATA"] is not null,
                    $"{profileCase.Name} {mode} launch lost its isolated profile environment");

                var stockTutorialLaunch =
                    MultiplayerLaunchEnvironment.Apply(
                        TutorialLaunchEnvironment.Apply(
                            profileOptions,
                            showStockTutorial: true),
                        multiplayer);
                Require(
                    stockTutorialLaunch.EnvironmentOverrides?[
                        TutorialLaunchEnvironment
                            .SkipFreshSaveTutorialVariable] ==
                            string.Empty,
                    $"{profileCase.Name} {mode} launch ignored the stock tutorial opt-in");
            }
        }

        Require(
            TutorialLaunchEnvironment.SkipFreshSaveTutorialVariable !=
                MultiplayerLaunchEnvironment.QuickStartVariable,
            "tutorial bypass and multiplayer quick start share one environment gate");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestAudioDisableLaunchRoutingAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var defaultCommand = LauncherCommandParser.Parse(["launch"]);
        Require(
            !defaultCommand.DisableAudio,
            "normal player launch unexpectedly disabled audio");
        var silentCommand = LauncherCommandParser.Parse(
            ["launch", "--disable-audio"]);
        Require(
            silentCommand.DisableAudio,
            "launcher parser lost --disable-audio");

        var settingsRoot = Path.Combine(root, "ui-settings");
        var settings = new LauncherUiSettingsStore(settingsRoot);
        Require(
            !settings.LoadDisableAudio(),
            "desktop launcher settings defaulted to disabled audio");
        settings.SaveDisableAudio(true);
        Require(
            new LauncherUiSettingsStore(settingsRoot)
                .LoadDisableAudio(),
            "desktop launcher did not persist the audio opt-out");

        var workspace = WorkspacePaths.Create(
            Path.Combine(root, "workspace"),
            modsRootOverride: null,
            runtimeRootOverride: null,
            stageRootOverride: null);
        var profileCases = new[]
        {
            (Name: "normal", Temporary: false, Fresh: false),
            (Name: "temporary", Temporary: true, Fresh: false),
            (Name: "fresh-install", Temporary: false, Fresh: true)
        };
        var launchModes = new[]
        {
            MultiplayerLaunchMode.Unspecified,
            MultiplayerLaunchMode.Off,
            MultiplayerLaunchMode.Host,
            MultiplayerLaunchMode.Join
        };

        foreach (var profileCase in profileCases)
        {
            var profileOptions =
                IsolatedProfileBootstrapper.CreateLaunchOptions(
                    workspace,
                    new Dictionary<string, string>(
                        StringComparer.OrdinalIgnoreCase)
                    {
                        ["PRESERVED"] = profileCase.Name,
                        [AudioLaunchEnvironment.DisableAudioVariable] = "1"
                    },
                    temporaryProfile: profileCase.Temporary,
                    freshInstall: profileCase.Fresh);

            foreach (var mode in launchModes)
            {
                var multiplayer = MultiplayerLaunchOptions.Create(
                    mode,
                    lobbyId: null,
                    inviteSteamId: null,
                    MultiplayerLaunchOptions.DefaultMaxParticipants,
                    openInviteDialog:
                        mode != MultiplayerLaunchMode.Host);
                var normalLaunch = MultiplayerLaunchEnvironment.Apply(
                    AudioLaunchEnvironment.Apply(
                        profileOptions,
                        disableAudio: false),
                    multiplayer);
                Require(
                    normalLaunch.EnvironmentOverrides?[
                        AudioLaunchEnvironment.DisableAudioVariable] ==
                        string.Empty,
                    $"{profileCase.Name} {mode} normal player launch inherited the audio-disable signal");
                Require(
                    normalLaunch.EnvironmentOverrides?["PRESERVED"] ==
                        profileCase.Name,
                    $"{profileCase.Name} {mode} launch discarded existing environment overrides");
                Require(
                    normalLaunch.EnvironmentOverrides?["APPDATA"] is not null &&
                    normalLaunch.EnvironmentOverrides?["LOCALAPPDATA"] is not null,
                    $"{profileCase.Name} {mode} launch lost its isolated profile environment");

                var silentLaunch = MultiplayerLaunchEnvironment.Apply(
                    AudioLaunchEnvironment.Apply(
                        profileOptions,
                        disableAudio: true),
                    multiplayer);
                Require(
                    silentLaunch.EnvironmentOverrides?[
                        AudioLaunchEnvironment.DisableAudioVariable] == "1",
                    $"{profileCase.Name} {mode} silent launch omitted the audio-disable signal");
            }
        }

        Require(
            AudioLaunchEnvironment.DisableAudioVariable !=
                TutorialLaunchEnvironment.SkipFreshSaveTutorialVariable &&
            AudioLaunchEnvironment.DisableAudioVariable !=
                MultiplayerLaunchEnvironment.QuickStartVariable,
            "audio disable shares an environment gate with another launch behavior");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestManualLobbyLaunchStateAsync()
{
    var state = new LobbyLaunchState();
    Require(state.PrimaryButtonText == "Join Game", "pre-join button text changed");
    Require(
        state.PrimaryAction == LobbyPrimaryAction.JoinLobby,
        "pre-join button no longer starts lobby membership");
    Require(
        LauncherUiCommandRouting.GetModeToken(
            LauncherUiCommandMode.PrepareSteamJoin) == "stage",
        "joining a lobby still routes through the game-launch command");
    Require(
        !LauncherUiCommandRouting.LaunchesGame(
            LauncherUiCommandMode.PrepareSteamJoin),
        "joining a lobby is still classified as a game launch");

    state.MarkJoined(123);
    Require(state.JoinedLobbyId == 123, "joined lobby identity was not retained");
    Require(state.PrimaryButtonText == "Launch Game", "joined button did not become Launch Game");
    Require(
        state.PrimaryAction == LobbyPrimaryAction.LaunchGame,
        "joined button does not explicitly launch the game");
    Require(
        LauncherUiCommandRouting.GetModeToken(
            LauncherUiCommandMode.LaunchSteamJoin) == "launch",
        "explicit Launch Game does not route through the game-launch command");
    Require(
        LauncherUiCommandRouting.LaunchesGame(
            LauncherUiCommandMode.LaunchSteamJoin),
        "explicit Launch Game is not classified as a game launch");

    state.Reset();
    Require(state.JoinedLobbyId is null, "leaving retained the old lobby identity");
    Require(state.PrimaryButtonText == "Join Game", "leaving did not restore Join Game");
    Require(
        state.PrimaryAction == LobbyPrimaryAction.JoinLobby,
        "disconnect did not restore the join action");

    return Task.CompletedTask;
}

static Task TestSteamLobbyCapacityBoundsAsync()
{
    var command = LauncherCommandParser.Parse(
        ["launch", "--multiplayer", "host", "--max-players", "4"]);
    Require(
        command.MultiplayerMaxParticipants == 4,
        "launcher parser lost the native participant ceiling");

    var launch = MultiplayerLaunchEnvironment.Apply(
        new LaunchOptions(),
        MultiplayerLaunchOptions.Create(
            MultiplayerLaunchMode.Host,
            lobbyId: null,
            inviteSteamId: null,
            command.MultiplayerMaxParticipants,
            openInviteDialog: false));
    Require(
        launch.EnvironmentOverrides?[MultiplayerLaunchEnvironment.MaxParticipantsVariable] == "4",
        "launcher did not pass the native participant ceiling to the loader");

    RequireThrows<InvalidOperationException>(
        () => LauncherCommandParser.Parse(
            ["launch", "--multiplayer", "host", "--max-players", "1"]),
        "launcher accepted a lobby capacity below two");
    RequireThrows<InvalidOperationException>(
        () => LauncherCommandParser.Parse(
            ["launch", "--multiplayer", "host", "--max-players", "5"]),
        "launcher accepted a capacity above the native participant ceiling");

    return Task.CompletedTask;
}

static Task TestBotMemberStatusCompatibilityAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var statusDirectory = Path.Combine(root, ".sdmod");
        Directory.CreateDirectory(statusDirectory);
        File.WriteAllText(
            Path.Combine(statusDirectory, "multiplayer-session-status.json"),
            """
            {
              "launchToken": "capacity-proof",
              "enabled": true,
              "isHost": true,
              "phase": "Connected",
              "gamePhase": "hub",
              "sessionState": "in-hub",
              "appId": 0,
              "lobbyId": 42,
              "hostSteamId": 42,
              "localSteamId": 42,
              "personaName": "Host",
              "privacy": "local",
              "protocolVersion": 87,
              "manifestSha256": "",
              "friendSteamIds": [],
              "maxParticipants": 4,
              "authenticatedPeerCount": 1,
              "overlayEnabled": false,
              "inviteDialogOpened": false,
              "inviteSent": false,
              "routeRelayed": false,
              "routePingMs": 0,
              "members": [
                {
                  "steamId": 42,
                  "participantId": 42,
                  "name": "Host",
                  "gameplaySlot": 0,
                  "isHost": true,
                  "isLocal": true,
                  "isSynthetic": false
                },
                {
                  "steamId": 0,
                  "participantId": 1152921504606851072,
                  "name": "Ember",
                  "gameplaySlot": 2,
                  "isHost": false,
                  "isLocal": false,
                  "isSynthetic": true,
                  "isBot": true
                }
              ],
              "statusText": "ready",
              "errorText": ""
            }
            """);

        var status = MultiplayerSessionStatusMonitor.TryRead(
            root,
            "capacity-proof");
        Require(status is not null, "launcher did not read bot member status");
        var parsedStatus = status!;
        Require(
            parsedStatus.Members.Length == 2,
            "launcher lost session members while reading bot status");
        Require(
            !parsedStatus.Members[0].IsBot,
            "missing isBot did not remain backward-compatible false");
        Require(
            parsedStatus.Members[1].IsBot &&
                parsedStatus.Members[1].IsSynthetic &&
                parsedStatus.Members[1].GameplaySlot == 2,
            "bot membership identity was not preserved");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestSteamShortcutChildLaunchIdentityAsync()
{
    const string shortcutAppId = "11710076608562855936";
    var configuration = new LauncherConfiguration
    {
        Game = null!,
        Workspace = null!,
        Runtime = null!,
        Steam = SteamBootstrapConfiguration.CreateDefault(
            appIdOverride: null,
            apiDllOverridePath: null)
    };
    var stage = new StageBuildResult(
        StageRootPath: "stage",
        StageExecutablePath: "SolomonDark.exe",
        StageReportPath: "stage-report.json",
        StageConfigRootPath: "config",
        StageBinaryLayoutPath: "binary-layout.json",
        StageDebugUiConfigPath: "debug-ui.json",
        StageRuntimeRootPath: "runtime",
        StageRuntimeBootstrapPath: "bootstrap.json",
        StageRuntimeFlagsPath: "runtime-flags.json",
        StageMirror: null!,
        RuntimeMetadata: null!,
        MultiplayerCompatibility: new MultiplayerCompatibilityStageResult(
            "multiplayer-manifest.json",
            new string('a', 64),
            80,
            []),
        SteamBootstrap: new SteamStageBootstrapResult(
            Enabled: true,
            AppId: SteamBootstrapConfiguration.DefaultAppId,
            StageAppIdPath: "steam_appid.txt",
            StageApiDllPath: "steam_api.dll",
            SteamApiSourcePath: "steam_api.dll",
            ReadyForInitialization: true),
        HudLabels: null!,
        EnabledModCount: 0,
        AppliedOverlayCount: 0);
    var inheritedShortcutEnvironment = new Dictionary<string, string>(
        StringComparer.OrdinalIgnoreCase)
    {
        ["SteamAppId"] = shortcutAppId,
        ["SteamGameId"] = shortcutAppId
    };
    var launchOptions = StagedGameLauncher.ApplySteamBootstrap(
        configuration,
        stage,
        new LaunchOptions(inheritedShortcutEnvironment));

    Require(
        launchOptions.EnvironmentOverrides?["SteamAppId"] ==
        SteamBootstrapConfiguration.DefaultAppId,
        "staged game inherited the non-Steam shortcut SteamAppId");
    Require(
        launchOptions.EnvironmentOverrides?["SteamGameId"] ==
        SteamBootstrapConfiguration.DefaultAppId,
        "staged game inherited the non-Steam shortcut SteamGameId");

    return Task.CompletedTask;
}

static Task TestSteamShortcutUiChildIsolationAsync()
{
    var startInfo = new System.Diagnostics.ProcessStartInfo
    {
        UseShellExecute = false
    };
    var shortcutVariables = new[]
    {
        "SteamAppId",
        "SteamGameId",
        "SteamOverlayGameId",
        "SteamClientLaunch",
        "SteamEnv",
        "SteamPath"
    };
    foreach (var variableName in shortcutVariables)
    {
        startInfo.Environment[variableName] = "synthetic-shortcut-value";
    }
    startInfo.Environment["PRESERVED"] = "value";

    SteamShortcutChildEnvironment.RemoveFrom(startInfo);

    foreach (var variableName in shortcutVariables)
    {
        Require(
            !startInfo.Environment.ContainsKey(variableName),
            $"desktop launcher CLI child retained {variableName}");
    }
    Require(
        startInfo.Environment["PRESERVED"] == "value",
        "desktop launcher CLI child isolation removed an unrelated variable");

    return Task.CompletedTask;
}

static Task TestCanonicalModIdentifiersAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var modRoot = Path.Combine(root, "mod");
        Directory.CreateDirectory(Path.Combine(modRoot, "scripts"));
        File.WriteAllText(Path.Combine(modRoot, "scripts", "main.lua"), "return true\n");

        File.WriteAllText(
            Path.Combine(modRoot, "manifest.json"),
            """
            {
              "id": "Tests.Uppercase",
              "name": "Invalid Identity",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              }
            }
            """);
        var uppercaseRejected = false;
        try
        {
            ModDiscovery.DiscoverRoot(modRoot);
        }
        catch (InvalidOperationException)
        {
            uppercaseRejected = true;
        }
        Require(uppercaseRejected, "manifest accepted a non-canonical mod id");

        File.WriteAllText(
            Path.Combine(modRoot, "manifest.json"),
            """
            {
              "id": "tests.canonical",
              "name": "Invalid Dependency Identity",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              },
              "requiredMods": ["Tests.Dependency"]
            }
            """);
        var dependencyRejected = false;
        try
        {
            ModDiscovery.DiscoverRoot(modRoot);
        }
        catch (InvalidOperationException)
        {
            dependencyRejected = true;
        }
        Require(dependencyRejected, "manifest accepted a non-canonical required mod id");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestStrictMultiplayerModParityAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var modRoot = Path.Combine(root, "mod");
        var scriptPath = Path.Combine(modRoot, "scripts", "main.lua");
        Directory.CreateDirectory(Path.GetDirectoryName(scriptPath)!);
        File.WriteAllText(scriptPath, "return true\n");
        File.WriteAllText(
            Path.Combine(modRoot, "manifest.json"),
            """
            {
              "id": "tests.presentation-parity",
              "name": "Presentation Parity Test",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              }
            }
            """);

        var mod = ModDiscovery.DiscoverRoot(modRoot);
        var stageRoot = Path.Combine(root, "stage");
        var executablePath = Path.Combine(root, "SolomonDark.exe");
        var layoutPath = Path.Combine(root, "binary-layout.ini");
        var loaderPath = Path.Combine(root, "SolomonDarkModLoader.dll");
        File.WriteAllBytes(executablePath, [1, 2, 3]);
        File.WriteAllText(layoutPath, "[binary]\nname=SolomonDark.exe\n");
        File.WriteAllBytes(loaderPath, [4, 5, 6]);

        var firstRuntime = RuntimeMetadataStageMaterializer.Materialize(
            stageRoot,
            [mod],
            RuntimeStageOptions.Default);
        var first = MultiplayerCompatibilityMaterializer.Materialize(
            stageRoot,
            executablePath,
            layoutPath,
            firstRuntime,
            [mod],
            loaderPath);

        File.AppendAllText(scriptPath, "-- presentation-only edit\n");
        var secondRuntime = RuntimeMetadataStageMaterializer.Materialize(
            stageRoot,
            [mod],
            RuntimeStageOptions.Default);
        var second = MultiplayerCompatibilityMaterializer.Materialize(
            stageRoot,
            executablePath,
            layoutPath,
            secondRuntime,
            [mod],
            loaderPath);
        Require(
            first.FingerprintSha256 != second.FingerprintSha256,
            "presentation-intended mod content did not change exact session parity");
        Require(
            first.EnabledMods.Single().ContentSha256 !=
                second.EnabledMods.Single().ContentSha256,
            "presentation-intended mod edit did not change its directory identity");

        var repeated = MultiplayerCompatibilityMaterializer.Materialize(
            stageRoot,
            executablePath,
            layoutPath,
            secondRuntime,
            [mod],
            loaderPath);
        Require(
            repeated.FingerprintSha256 == second.FingerprintSha256,
            "unchanged exact mod set produced a different session fingerprint");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestLuaHotReloadBootstrapAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var modRoot = Path.Combine(root, "mod");
        var scriptPath = Path.Combine(modRoot, "scripts", "main.lua");
        Directory.CreateDirectory(Path.GetDirectoryName(scriptPath)!);
        File.WriteAllText(scriptPath, "return true\n");
        File.WriteAllText(
            Path.Combine(modRoot, "manifest.json"),
            """
            {
              "id": "tests.hot-reload",
              "name": "Hot Reload Test",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua",
                "hotReload": true
              }
            }
            """);

        var mod = ModDiscovery.DiscoverRoot(modRoot);
        var stageRoot = Path.Combine(root, "stage");
        var runtime = RuntimeMetadataStageMaterializer.Materialize(
            stageRoot,
            [mod],
            RuntimeStageOptions.Default);
        var staged = runtime.StagedRuntimeMods.Single();
        Require(staged.HotReload, "stage descriptor disabled manifest hot reload");
        Require(
            Path.GetFullPath(staged.SourceModRootPath) == Path.GetFullPath(modRoot),
            "stage descriptor lost the source mod root");
        Require(
            Path.GetFullPath(staged.SourceEntryScriptPath!) == Path.GetFullPath(scriptPath),
            "stage descriptor lost the source Lua entry path");
        Require(
            Path.GetFullPath(staged.StageEntryScriptPath!) != Path.GetFullPath(scriptPath),
            "stage and source Lua entry paths were not isolated");

        var bootstrap = File.ReadAllText(runtime.RuntimeBootstrapPath);
        Require(
            bootstrap.Contains("hot_reload=true", StringComparison.Ordinal),
            "runtime bootstrap disabled manifest hot reload");
        Require(
            bootstrap.Contains(
                $"source_entry_script_path={scriptPath}",
                StringComparison.Ordinal),
            "runtime bootstrap omitted the source Lua entry path");

        Directory.CreateDirectory(Path.Combine(modRoot, "files"));
        File.WriteAllText(Path.Combine(modRoot, "files", "data.txt"), "data");
        File.WriteAllText(
            Path.Combine(modRoot, "manifest.json"),
            """
            {
              "id": "tests.hot-reload",
              "name": "Invalid Hot Reload Test",
              "version": "1.0.0",
              "overlays": [{
                "target": "data/data.txt",
                "source": "files/data.txt"
              }],
              "runtime": {
                "hotReload": true
              }
            }
            """);
        var nonLuaRejected = false;
        try
        {
            ModDiscovery.DiscoverRoot(modRoot);
        }
        catch (InvalidOperationException)
        {
            nonLuaRejected = true;
        }
        Require(nonLuaRejected, "manifest accepted hot reload without a Lua entry point");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestLoadingScreenAssetStagingAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var workspaceRoot = Path.Combine(root, "workspace");
        var stageRoot = Path.Combine(root, "stage");
        var sourcePath = Path.Combine(
            workspaceRoot,
            "assets",
            "loading",
            LoadingScreenAssetMaterializer.BackgroundFileName);
        Directory.CreateDirectory(Path.GetDirectoryName(sourcePath)!);
        var expected = Encoding.UTF8.GetBytes(
            "canonical-loading-screen-background");
        File.WriteAllBytes(sourcePath, expected);

        var stagedPath = LoadingScreenAssetMaterializer.Materialize(
            workspaceRoot,
            stageRoot);
        Require(
            stagedPath == Path.Combine(
                stageRoot,
                ".sdmod",
                "assets",
                "loading",
                LoadingScreenAssetMaterializer.BackgroundFileName),
            "loading screen background staged to the wrong runtime path");
        Require(
            File.ReadAllBytes(stagedPath).SequenceEqual(expected),
            "loading screen background staging changed the canonical bytes");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestCleanInstallEnablesZeroModsAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var modsRoot = Path.Combine(root, "mods");
        Directory.CreateDirectory(modsRoot);
        foreach (var id in new[] { "tests.first", "tests.second" })
        {
            var modRoot = Path.Combine(modsRoot, id);
            Directory.CreateDirectory(modRoot);
            File.WriteAllText(
                Path.Combine(modRoot, "manifest.json"),
                $$"""
                {
                  "id": "{{id}}",
                  "name": "{{id}}",
                  "version": "1.0.0",
                  "overlays": [{
                    "target": "images/{{id}}.png",
                    "source": "files/{{id}}.png"
                  }]
                }
                """);
            Directory.CreateDirectory(Path.Combine(modRoot, "files"));
            File.WriteAllText(Path.Combine(modRoot, "files", $"{id}.png"), id);
        }

        var statePath = Path.Combine(root, "runtime", "mod-manager-state.json");
        var cleanCatalog = ModCatalog.Load(modsRoot, ModStateStore.Load(statePath));
        Require(cleanCatalog.DiscoveredMods.Count == 2, "clean install did not discover packaged mods");
        Require(cleanCatalog.EnabledMods.Count == 0, "clean install enabled packaged mods by default");

        ModStateStore.SetEnabledAtomic(statePath, "tests.first", enabled: true);
        var optedInCatalog = ModCatalog.Load(modsRoot, ModStateStore.Load(statePath));
        Require(optedInCatalog.EnabledMods.Count == 1, "an explicit mod choice was not persisted");
        Require(optedInCatalog.IsEnabled("tests.first"), "the selected mod was not enabled");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestCrashCaptureArchiveAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var stageRoot = Path.Combine(root, "stage");
        var runtimeRoot = Path.Combine(stageRoot, ".sdmod", "runtime");
        var logsRoot = Path.Combine(stageRoot, ".sdmod", "logs");
        Directory.CreateDirectory(logsRoot);
        var crashLogPath = Path.Combine(logsRoot, "solomondarkmodloader.crash.log");
        var loaderLogPath = Path.Combine(logsRoot, "solomondarkmodloader.log");
        var startupStatusPath = Path.Combine(
            stageRoot,
            ".sdmod",
            "startup-status.json");
        File.WriteAllText(crashLogPath, "unhandled exception code=0xC0000005\n");
        File.WriteAllText(loaderLogPath, "loader attached\n");
        File.WriteAllText(startupStatusPath, """{"success":true}""");
        var dumpPath = Path.Combine(
            logsRoot,
            "solomondarkmodloader.crash.20260722_120000_000.tid7.dmp");
        File.WriteAllBytes(dumpPath, [0x4D, 0x44, 0x4D, 0x50]);

        var response = new LauncherCliResponse
        {
            Success = true,
            Configuration = new LauncherCliConfiguration { RuntimeProfile = "release" },
            Mods =
            [
                new LauncherCliMod { Id = "tests.enabled", Version = "1.2.3", Enabled = true },
                new LauncherCliMod { Id = "tests.disabled", Version = "4.5.6", Enabled = false }
            ],
            Stage = new LauncherCliStage
            {
                StageRoot = stageRoot,
                StageRuntimeRootPath = runtimeRoot,
                StageReportPath = Path.Combine(stageRoot, ".sdmod", "stage-report.json")
            },
            Launch = new LauncherCliLaunch
            {
                ProcessId = 123,
                LaunchToken = "0123456789abcdef0123456789abcdef",
                StartedAtUtc = DateTimeOffset.UtcNow.AddMinutes(-1),
                LoaderPath = Path.Combine(root, "SolomonDarkModLoader.dll"),
                StartupLogPath = loaderLogPath
            }
        };

        var capture = CrashReportCapture.TryCreate(response, 0, "contract-test")
            ?? throw new InvalidOperationException("native crash artifacts were not detected");
        Require(capture.Metadata.HasCrashLog, "crash log was not recorded in metadata");
        Require(capture.Metadata.MinidumpCount == 1, "minidump was not recorded in metadata");
        Require(capture.Metadata.EnabledMods.Count == 1, "crash report did not isolate enabled mods");
        Require(
            capture.Metadata.LoaderVersion == "contract-test",
            "crash report did not identify the packaged loader build");

        var archivePath = CrashReportArchiveBuilder.Build(capture);
        try
        {
            using var archive = ZipFile.OpenRead(archivePath);
            var entryNames = archive.Entries.Select(entry => entry.FullName).ToHashSet(StringComparer.Ordinal);
            Require(entryNames.Contains("report.json"), "crash archive is missing report.json");
            Require(entryNames.Contains("logs/crash.log"), "crash archive is missing the crash log");
            Require(entryNames.Contains("logs/loader.log"), "crash archive is missing the loader log");
            Require(
                entryNames.Contains("diagnostics/startup-status.json"),
                "crash archive is missing the loader startup status");
            Require(entryNames.Contains($"dumps/{Path.GetFileName(dumpPath)}"), "crash archive is missing the minidump");
            Require(entryNames.All(name => !Path.IsPathRooted(name)), "crash archive exposed absolute entry paths");
            using var manifestReader = new StreamReader(
                archive.GetEntry("report.json")!.Open());
            var manifest = manifestReader.ReadToEnd();
            Require(
                !manifest.Contains(root, StringComparison.OrdinalIgnoreCase),
                "crash manifest exposed a local source path");
        }
        finally
        {
            File.Delete(archivePath);
        }

        File.WriteAllText(crashLogPath, string.Empty);
        File.Delete(dumpPath);
        Require(
            CrashReportCapture.TryCreate(response, 0, "contract-test") is null,
            "a clean zero exit was classified as a crash");
        Require(
            CrashReportCapture.TryCreate(response, unchecked((int)0xC0000005), "contract-test") is not null,
            "an abnormal process exit without a dump was not classified as a crash");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static async Task TestWebsitePackageInstallAsync()
{
    var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
    {
        ["manifest.json"] = Encoding.UTF8.GetBytes(
            """
            {
              "id": "tests.combined",
              "name": "Combined Test",
              "version": "1.0.0",
              "priority": 20,
              "overlays": [
                {
                  "target": "sandbox/DarkCloud/mylevels/Contract Arena.boneyard",
                  "source": "files/Contract Arena.boneyard",
                  "format": "boneyard"
                },
                {
                  "target": "images/Skills.png",
                  "source": "files/Skills.png"
                }
              ],
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua",
                "requiredCapabilities": [],
                "optionalCapabilities": ["ui"]
              }
            }
            """),
        ["files/Contract Arena.boneyard"] = BoneyardFixture(),
        ["files/Skills.png"] = "website art contract"u8.ToArray(),
        ["scripts/main.lua"] = Encoding.UTF8.GetBytes("return true\n")
    };
    var package = CreateZip(entries);
    var required = new MultiplayerModDescriptor(
        "tests.combined",
        "1.0.0",
        ComputeContentHash(entries));
    var resolved = new WebsiteResolvedMod(
        required.Id,
        required.Version,
        required.ContentSha256,
        Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant(),
        "api/mods/tests/versions/1/download");

    var cacheRoot = CreateTemporaryDirectory();
    try
    {
        using var client = new HttpClient(new PackageHandler(package))
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var progress = new RecordingProgress();
        var installed = await WebsiteModPackageInstaller.InstallAsync(
            client,
            resolved,
            required,
            cacheRoot,
            CancellationToken.None,
            progress);
        Require(
            progress.Values.Any(value =>
                value.Phase == UpdateProgressPhase.Downloading &&
                value.Completed == package.Length &&
                value.Total == package.Length),
            "website package download did not report its real byte total");
        Require(
            progress.Values.Any(value => value.Phase == UpdateProgressPhase.Verifying) &&
            progress.Values.Any(value => value.Phase == UpdateProgressPhase.Installing),
            "website package progress omitted verification or installation");
        Require(installed.Manifest.Id == required.Id, "installed manifest id changed");
        Require(installed.RequiresLuaRuntime, "combined package did not retain Lua runtime");
        Require(installed.Manifest.Overlays.Count == 2, "combined package did not retain Boneyard and art overlays");
        Require(File.Exists(Path.Combine(installed.RootPath, "scripts", "main.lua")), "Lua script missing");
        Require(
            File.Exists(Path.Combine(installed.RootPath, "files", "Contract Arena.boneyard")),
            "Boneyard missing");

        var stageRoot = Path.Combine(cacheRoot, "stage");
        Directory.CreateDirectory(stageRoot);
        Require(
            OverlayStageMaterializer.Materialize(stageRoot, [installed]) == 2,
            "combined package overlays were not materialized");
        var stagedBoneyard = Path.Combine(
            stageRoot,
            "sandbox",
            "DarkCloud",
            "mylevels",
            "Contract Arena.boneyard");
        Require(File.Exists(stagedBoneyard), "custom Boneyard was staged outside the native sandbox path");
        Require(
            File.ReadAllBytes(stagedBoneyard).SequenceEqual(BoneyardFixture()),
            "staged custom Boneyard bytes changed");
        var stagedArt = Path.Combine(stageRoot, "images", "Skills.png");
        Require(File.Exists(stagedArt), "website art overlay was not staged under images/");
        Require(
            File.ReadAllBytes(stagedArt).SequenceEqual(entries["files/Skills.png"]),
            "staged website art bytes changed");

        var cached = WebsiteModPackageInstaller.TryLoadExact(installed.RootPath, required);
        Require(cached is not null, "exact cached package was not reusable");
    }
    finally
    {
        Directory.Delete(cacheRoot, recursive: true);
    }
}

static async Task TestAutomaticModUpdatesAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var modsRoot = Path.Combine(root, "mods");
        var currentRoot = Path.Combine(modsRoot, "auto-update");
        Directory.CreateDirectory(Path.Combine(currentRoot, "files"));
        File.WriteAllText(
            Path.Combine(currentRoot, "manifest.json"),
            """
            {
              "id": "tests.auto-update",
              "name": "Automatic Update Test",
              "version": "1.0.0",
              "overlays": [{
                "target": "images/update.txt",
                "source": "files/update.txt"
              }]
            }
            """);
        File.WriteAllText(Path.Combine(currentRoot, "files", "update.txt"), "old");
        File.WriteAllText(Path.Combine(currentRoot, "user-edit.txt"), "remove with old edition");

        var updateEntries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
        {
            ["manifest.json"] = Encoding.UTF8.GetBytes(
                """
                {
                  "id": "tests.auto-update",
                  "name": "Automatic Update Test",
                  "version": "1.1.0",
                  "overlays": [{
                    "target": "images/update.txt",
                    "source": "files/update.txt"
                  }]
                }
                """),
            ["files/update.txt"] = Encoding.UTF8.GetBytes("new")
        };
        var package = CreateZip(updateEntries);
        var required = new MultiplayerModDescriptor(
            "tests.auto-update",
            "1.1.0",
            ComputeContentHash(updateEntries));
        var packageSha256 = Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant();
        var catalog = ModCatalog.CreateExact(
            [ModDiscovery.DiscoverRoot(currentRoot)]);
        var cacheRoot = Path.Combine(root, "cache");
        var handler = new ModUpdateHandler(package, required, packageSha256);
        using var client = new HttpClient(handler)
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var progress = new RecordingProgress();

        var result = await WebsiteModUpdater.UpdateAsync(
            catalog,
            modsRoot,
            cacheRoot,
            client,
            progress);
        Require(result.Error is null, $"automatic update failed: {result.Error}");
        Require(result.UpdatedModCount == 1, "website update did not replace one mod");
        Require(
            handler.RequestedIds.SequenceEqual(["tests.auto-update"]),
            "website updater requested the wrong installed mod");
        Require(
            handler.LoaderVersion == "0.1.0-beta.21",
            "website updater omitted the current loader version");
        var updated = ModDiscovery.DiscoverRoot(currentRoot);
        Require(updated.Manifest.Version == "1.1.0", "installed manifest version did not advance");
        Require(
            File.ReadAllText(Path.Combine(currentRoot, "files", "update.txt")) == "new",
            "installed mod content did not advance");
        Require(
            !File.Exists(Path.Combine(currentRoot, "user-edit.txt")),
            "old edition files survived package replacement");
        Require(
            progress.Values.First().Phase == UpdateProgressPhase.Checking &&
            progress.Values.Last().Phase == UpdateProgressPhase.Completed,
            "automatic mod update did not report checking through completion");
        using var offlineClient = new HttpClient(new OfflineDirectoryHandler())
        {
            BaseAddress = new Uri("https://offline.example.test/")
        };
        var reloaded = ModCatalog.CreateExact(
            ModDiscovery.Discover(modsRoot).ToArray());
        var offlineProgress = new RecordingProgress();
        var offline = await WebsiteModUpdater.UpdateAsync(
            reloaded,
            modsRoot,
            cacheRoot,
            offlineClient,
            offlineProgress);
        Require(offline.Error is not null, "offline update check did not report its skip reason");
        Require(
            offlineProgress.Values.Last().Phase == UpdateProgressPhase.Failed,
            "offline update failure was not reported visibly");
        Require(
            ModDiscovery.DiscoverRoot(currentRoot).Manifest.Version == "1.1.0",
            "offline update check changed the installed mod");

        var invalidEntries = new Dictionary<string, byte[]>(updateEntries, StringComparer.Ordinal)
        {
            ["manifest.json"] = Encoding.UTF8.GetBytes(
                """
                {
                  "id": "tests.auto-update",
                  "name": "Automatic Update Test",
                  "version": "1.2.0",
                  "overlays": [{
                    "target": "images/update.txt",
                    "source": "files/update.txt"
                  }]
                }
                """)
        };
        var expectedPackage = CreateZip(invalidEntries);
        var invalidRequired = new MultiplayerModDescriptor(
            "tests.auto-update",
            "1.2.0",
            ComputeContentHash(invalidEntries));
        var invalidHandler = new ModUpdateHandler(
            package,
            invalidRequired,
            Convert.ToHexString(SHA256.HashData(expectedPackage)).ToLowerInvariant());
        using var invalidClient = new HttpClient(invalidHandler)
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var invalidProgress = new RecordingProgress();
        var rejected = await WebsiteModUpdater.UpdateAsync(
            reloaded,
            modsRoot,
            Path.Combine(root, "invalid-cache"),
            invalidClient,
            invalidProgress);
        Require(rejected.Error is not null, "tampered update package was accepted");
        Require(
            invalidProgress.Values.Last().Phase == UpdateProgressPhase.Failed,
            "tampered update failure was not reported visibly");
        Require(
            ModDiscovery.DiscoverRoot(currentRoot).Manifest.Version == "1.1.0",
            "rejected update damaged the installed mod");

        var backupPath = Path.Combine(modsRoot, ".sdmod-backup-recovered");
        Directory.CreateDirectory(Path.Combine(backupPath, "files"));
        File.WriteAllText(
            Path.Combine(backupPath, "manifest.json"),
            """
            {
              "id": "tests.recovered",
              "name": "Recovered Update",
              "version": "1.0.0",
              "overlays": [{
                "target": "data/recovered.txt",
                "source": "files/recovered.txt"
              }]
            }
            """);
        File.WriteAllText(Path.Combine(backupPath, "files", "recovered.txt"), "recovered");
        var abandonedPath = Path.Combine(modsRoot, ".sdmod-update-abandoned");
        Directory.CreateDirectory(abandonedPath);
        WebsiteModUpdater.RecoverTransactions(modsRoot);
        Require(
            ModDiscovery.DiscoverRoot(Path.Combine(modsRoot, "recovered")).Manifest.Id ==
            "tests.recovered",
            "interrupted update backup was not restored");
        Require(!Directory.Exists(abandonedPath), "abandoned update staging directory survived recovery");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static Task TestSemanticVersionOrderingAsync()
{
    Require(SemanticVersion.TryParse("1.0.0-beta.2", out var beta2), "beta.2 was rejected");
    Require(SemanticVersion.TryParse("1.0.0-beta.10", out var beta10), "beta.10 was rejected");
    Require(
        SemanticVersion.TryParse("1.0.0-beta.2147483648", out var largePrerelease),
        "large numeric prerelease identifier was rejected");
    Require(
        SemanticVersion.TryParse("2147483648.0.0", out var largeCore),
        "large core version identifier was rejected");
    Require(SemanticVersion.TryParse("1.0.0", out var stable), "stable version was rejected");
    Require(beta10!.CompareTo(beta2) > 0, "numeric prerelease identifiers sorted lexically");
    Require(
        largePrerelease!.CompareTo(beta10) > 0,
        "large numeric prerelease identifier sorted incorrectly");
    Require(stable!.CompareTo(beta10) > 0, "stable release did not sort after prerelease");
    Require(largeCore!.CompareTo(stable) > 0, "large core version sorted incorrectly");
    Require(
        !SemanticVersion.TryParse("1.0", out _) &&
        !SemanticVersion.TryParse("1.0.0-beta.01", out _),
        "invalid semantic versions were accepted");
    return Task.CompletedTask;
}

static Task TestMinimumLoaderCompatibilityAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        Directory.CreateDirectory(Path.Combine(root, "scripts"));
        var manifestPath = Path.Combine(root, "manifest.json");
        File.WriteAllText(Path.Combine(root, "scripts", "main.lua"), "return true\n");
        File.WriteAllText(
            manifestPath,
            """
            {
              "id": "tests.minimum-loader",
              "name": "Minimum Loader Test",
              "version": "1.0.0",
              "minimumLoaderVersion": "0.1.0-beta.20",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              }
            }
            """);

        var mod = ModDiscovery.DiscoverRoot(root);
        Require(
            !ModCompatibility.IsLoaderCompatible(mod.Manifest, "0.1.0-beta.19"),
            "beta.19 accepted a beta.20-only mod");
        Require(
            ModCompatibility.IsLoaderCompatible(mod.Manifest, "0.1.0-beta.20"),
            "beta.20 rejected a beta.20-compatible mod");
        Require(
            ModCompatibility.IsLoaderCompatible(mod.Manifest, "0.1.0"),
            "stable loader did not satisfy a prerelease minimum");

        File.WriteAllText(
            manifestPath,
            File.ReadAllText(manifestPath).Replace(
                "0.1.0-beta.20",
                "beta.20",
                StringComparison.Ordinal));
        var rejected = false;
        try
        {
            ModDiscovery.DiscoverRoot(root);
        }
        catch (InvalidOperationException)
        {
            rejected = true;
        }
        Require(rejected, "invalid minimumLoaderVersion was accepted");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static async Task TestDownloadedPackageTraversalAsync()
{
    var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
    {
        ["manifest.json"] = Encoding.UTF8.GetBytes(
            """
            {
              "id": "tests.traversal",
              "name": "Traversal Test",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              }
            }
            """),
        ["scripts/main.lua"] = Encoding.UTF8.GetBytes("return true\n"),
        ["../outside.txt"] = Encoding.UTF8.GetBytes("must not escape")
    };
    var package = CreateZip(entries);
    var required = new MultiplayerModDescriptor(
        "tests.traversal",
        "1.0.0",
        ComputeContentHash(entries));
    var resolved = new WebsiteResolvedMod(
        required.Id,
        required.Version,
        required.ContentSha256,
        Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant(),
        "api/mods/tests/versions/1/download");
    var cacheRoot = CreateTemporaryDirectory();
    try
    {
        using var client = new HttpClient(new PackageHandler(package))
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var rejected = false;
        try
        {
            await WebsiteModPackageInstaller.InstallAsync(
                client,
                resolved,
                required,
                cacheRoot,
                CancellationToken.None);
        }
        catch (InvalidDataException)
        {
            rejected = true;
        }
        Require(rejected, "downloaded ZIP traversal was accepted");
    }
    finally
    {
        Directory.Delete(cacheRoot, recursive: true);
    }
}

static async Task TestDownloadedPackageContractAsync()
{
    var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
    {
        ["manifest.json"] = Encoding.UTF8.GetBytes(
            """
            {
              "id": "tests.invalid-package-file",
              "name": "Invalid Package File",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              }
            }
            """),
        ["scripts/main.lua"] = Encoding.UTF8.GetBytes("return true\n"),
        ["files/payload.DLL"] = Encoding.UTF8.GetBytes("not a dll")
    };
    var package = CreateZip(entries);
    var required = new MultiplayerModDescriptor(
        "tests.invalid-package-file",
        "1.0.0",
        ComputeContentHash(entries));
    var resolved = new WebsiteResolvedMod(
        required.Id,
        required.Version,
        required.ContentSha256,
        Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant(),
        "api/mods/tests/versions/1/download");
    var cacheRoot = CreateTemporaryDirectory();
    try
    {
        using var client = new HttpClient(new PackageHandler(package))
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var rejected = false;
        try
        {
            await WebsiteModPackageInstaller.InstallAsync(
                client,
                resolved,
                required,
                cacheRoot,
                CancellationToken.None);
        }
        catch (InvalidDataException)
        {
            rejected = true;
        }
        Require(rejected, "downloaded DLL payload was accepted");

        var dataEntries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
        {
            ["manifest.json"] = Encoding.UTF8.GetBytes(
                """
                {
                  "id": "tests.non-boneyard-data",
                  "name": "Non-Boneyard Data",
                  "version": "1.0.0",
                  "overlays": [{
                    "target": "data/wave.txt",
                    "source": "files/wave.txt"
                  }]
                }
                """),
            ["files/wave.txt"] = Encoding.UTF8.GetBytes("wave data")
        };
        var dataPackage = CreateZip(dataEntries);
        var dataRequired = new MultiplayerModDescriptor(
            "tests.non-boneyard-data",
            "1.0.0",
            ComputeContentHash(dataEntries));
        var dataResolved = new WebsiteResolvedMod(
            dataRequired.Id,
            dataRequired.Version,
            dataRequired.ContentSha256,
            Convert.ToHexString(SHA256.HashData(dataPackage)).ToLowerInvariant(),
            "api/mods/tests/versions/1/download");
        using var dataClient = new HttpClient(new PackageHandler(dataPackage))
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        rejected = false;
        try
        {
            await WebsiteModPackageInstaller.InstallAsync(
                dataClient,
                dataResolved,
                dataRequired,
                cacheRoot,
                CancellationToken.None);
        }
        catch (InvalidDataException)
        {
            rejected = true;
        }
        Require(rejected, "downloaded non-Boneyard data overlay was accepted");
    }
    finally
    {
        Directory.Delete(cacheRoot, recursive: true);
    }
}

static Task TestExactManualCatalogAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var boneyardRoot = Path.Combine(root, "boneyard");
        Directory.CreateDirectory(Path.Combine(boneyardRoot, "files"));
        File.WriteAllText(
            Path.Combine(boneyardRoot, "manifest.json"),
            """
            {
              "id": "tests.manual-boneyard",
              "name": "Manual Boneyard",
              "version": "1.0.0",
              "overlays": [{
                "target": "data/levels/survival.boneyard",
                "source": "files/survival.boneyard"
              }]
            }
            """);
        File.WriteAllBytes(
            Path.Combine(boneyardRoot, "files", "survival.boneyard"),
            BoneyardFixture());

        var luaRoot = Path.Combine(root, "lua");
        Directory.CreateDirectory(Path.Combine(luaRoot, "scripts"));
        File.WriteAllText(
            Path.Combine(luaRoot, "manifest.json"),
            """
            {
              "id": "tests.manual-lua",
              "name": "Manual Lua",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              },
              "requiredMods": ["tests.manual-boneyard"]
            }
            """);
        File.WriteAllText(Path.Combine(luaRoot, "scripts", "main.lua"), "return true\n");

        var boneyard = ModDiscovery.DiscoverRoot(boneyardRoot);
        var lua = ModDiscovery.DiscoverRoot(luaRoot);
        var catalog = ModCatalog.CreateExact([lua, boneyard]);
        Require(catalog.EnabledMods.Count == 2, "exact manual set was not fully enabled");
        Require(catalog.IsEnabled("tests.manual-boneyard"), "manual dependency was not enabled");
        Require(catalog.IsEnabled("tests.manual-lua"), "manual Lua mod was not enabled");

        var missingDependencyRejected = false;
        try
        {
            ModCatalog.CreateExact([lua]);
        }
        catch (InvalidOperationException)
        {
            missingDependencyRejected = true;
        }
        Require(missingDependencyRejected, "exact sets accepted a missing dependency");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestLuaBusRuntimeContractsAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var providerRoot = Path.Combine(root, "provider");
        Directory.CreateDirectory(Path.Combine(providerRoot, "scripts"));
        File.WriteAllText(
            Path.Combine(providerRoot, "manifest.json"),
            """
            {
              "id": "tests.bus-provider",
              "name": "Bus Provider",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              },
              "provides": ["tests.bus.echo.v1"]
            }
            """);
        File.WriteAllText(
            Path.Combine(providerRoot, "scripts", "main.lua"),
            "return true\n");

        var consumerRoot = Path.Combine(root, "consumer");
        Directory.CreateDirectory(Path.Combine(consumerRoot, "scripts"));
        File.WriteAllText(
            Path.Combine(consumerRoot, "manifest.json"),
            """
            {
              "id": "tests.bus-consumer",
              "name": "Bus Consumer",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              },
              "requires": ["tests.bus.echo.v1"]
            }
            """);
        File.WriteAllText(
            Path.Combine(consumerRoot, "scripts", "main.lua"),
            "return true\n");

        var provider = ModDiscovery.DiscoverRoot(providerRoot);
        var consumer = ModDiscovery.DiscoverRoot(consumerRoot);
        var catalog = ModCatalog.CreateExact([consumer, provider]);
        Require(catalog.EnabledMods.Count == 2, "bus contract set did not resolve");

        var stageRoot = Path.Combine(root, "stage");
        var runtime = RuntimeMetadataStageMaterializer.Materialize(
            stageRoot,
            catalog.EnabledMods,
            RuntimeStageOptions.Default);
        var bootstrap = File.ReadAllText(runtime.RuntimeBootstrapPath);
        Require(
            bootstrap.Contains("provides=tests.bus.echo.v1", StringComparison.Ordinal),
            "provided bus contract was not staged");
        Require(
            bootstrap.Contains("requires=tests.bus.echo.v1", StringComparison.Ordinal),
            "required bus contract was not staged");
        Require(
            runtime.StagedRuntimeMods.Single(mod => mod.Id == provider.Manifest.Id)
                .Provides.SequenceEqual(["tests.bus.echo.v1"]),
            "provider stage descriptor lost its contract");
        Require(
            runtime.StagedRuntimeMods.Single(mod => mod.Id == consumer.Manifest.Id)
                .Requires.SequenceEqual(["tests.bus.echo.v1"]),
            "consumer stage descriptor lost its contract");

        var missingProviderRejected = false;
        try
        {
            ModCatalog.CreateExact([consumer]);
        }
        catch (InvalidOperationException)
        {
            missingProviderRejected = true;
        }
        Require(missingProviderRejected, "catalog accepted an unresolved bus contract");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestInvalidBoneyardRejectionAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        Directory.CreateDirectory(Path.Combine(root, "files"));
        File.WriteAllText(
            Path.Combine(root, "manifest.json"),
            """
            {
              "id": "tests.invalid-boneyard",
              "name": "Invalid Boneyard",
              "version": "1.0.0",
              "overlays": [{
                "target": "data/levels/survival.boneyard",
                "source": "files/survival.boneyard",
                "format": "boneyard"
              }]
            }
            """);
        File.WriteAllBytes(Path.Combine(root, "files", "survival.boneyard"), []);

        var rejected = false;
        try
        {
            ModDiscovery.DiscoverRoot(root);
        }
        catch (InvalidDataException)
        {
            rejected = true;
        }
        Require(rejected, "a zero-byte Boneyard was accepted");

        File.WriteAllBytes(
            Path.Combine(root, "files", "survival.boneyard"),
            BoneyardFixture());
        File.WriteAllText(
            Path.Combine(root, "manifest.json"),
            """
            {
              "id": "tests.wrong-boneyard-target",
              "name": "Wrong Boneyard Target",
              "version": "1.0.0",
              "overlays": [{
                "target": "DarkCloud/mylevels/Wrong.boneyard",
                "source": "files/survival.boneyard",
                "format": "boneyard"
              }]
            }
            """);
        rejected = false;
        try
        {
            ModDiscovery.DiscoverRoot(root);
        }
        catch (InvalidOperationException)
        {
            rejected = true;
        }
        Require(rejected, "a custom Boneyard target without the native sandbox prefix was accepted");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestAutomaticWebsiteSyncAsync()
{
    var direct = LauncherCommandParser.Parse(
        ["launch", "--multiplayer", "join", "--lobby-id", "123"]);
    Require(direct.LobbyTicket is null, "direct P2P lobby join unexpectedly has a website ticket");
    Require(
        direct.LobbyHost.DirectoryBaseUrl == LobbyHostOptions.DefaultDirectoryBaseUrl,
        "direct P2P lobby join did not retain the default website fallback");

    var website = LauncherCommandParser.Parse(
        [
            "launch",
            "--multiplayer", "join",
            "--lobby-id", "123",
            "--directory-url", "https://mods.example.test/community",
            "--lobby-ticket", "signed-ticket"
        ]);
    Require(website.LobbyTicket == "signed-ticket", "website ticket was not retained");
    Require(
        website.LobbyHost.DirectoryBaseUrl == "https://mods.example.test/community",
        "website directory path base was lost");
    Require(
        LauncherCommandExecutor.RequiresLobbyModSync(website),
        "concrete launch joins did not request website mod synchronization");

    var stage = LauncherCommandParser.Parse(
        [
            "stage",
            "--multiplayer", "join",
            "--lobby-id", "123",
            "--directory-url", "https://mods.example.test/community"
        ]);
    Require(
        LauncherCommandExecutor.RequiresLobbyModSync(stage),
        "concrete stage joins did not request website mod synchronization");
    var ordinaryStage = LauncherCommandParser.Parse(["stage"]);
    Require(
        !LauncherCommandExecutor.RequiresLobbyModSync(ordinaryStage),
        "ordinary staging unexpectedly requested website mod synchronization");

    var invalidRejected = false;
    try
    {
        LauncherCommandParser.Parse(
            ["launch", "--multiplayer", "join", "--lobby-ticket", "signed-ticket"]);
    }
    catch (InvalidOperationException)
    {
        invalidRejected = true;
    }
    Require(invalidRejected, "website ticket was accepted without a concrete lobby id");
    return Task.CompletedTask;
}

static async Task TestWebsiteLobbyPreflightAsync()
{
    var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
    {
        ["manifest.json"] = Encoding.UTF8.GetBytes(
            """
            {
              "id": "tests.preflight",
              "name": "Preflight Test",
              "version": "3.0.0",
              "overlays": [{
                "target": "data/levels/survival.boneyard",
                "source": "files/survival.boneyard"
              }]
            }
            """),
        ["files/survival.boneyard"] = BoneyardFixture()
    };
    var package = CreateZip(entries);
    var required = new MultiplayerModDescriptor(
        "tests.preflight",
        "3.0.0",
        ComputeContentHash(entries));
    var packageSha256 = Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant();
    var root = CreateTemporaryDirectory();
    try
    {
        var unrelatedRoot = Path.Combine(root, "unrelated");
        Directory.CreateDirectory(Path.Combine(unrelatedRoot, "files"));
        File.WriteAllText(
            Path.Combine(unrelatedRoot, "manifest.json"),
            """
            {
              "id": "tests.unrelated",
              "name": "Unrelated",
              "version": "1.0.0",
              "overlays": [{
                "target": "data/unrelated.txt",
                "source": "files/unrelated.txt"
              }]
            }
            """);
        File.WriteAllText(Path.Combine(unrelatedRoot, "files", "unrelated.txt"), "unrelated");
        var localCatalog = ModCatalog.CreateExact([ModDiscovery.DiscoverRoot(unrelatedRoot)]);

        var handler = new LobbyDirectoryHandler(package, required, packageSha256);
        using var client = new HttpClient(handler)
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var cacheRoot = Path.Combine(root, "cache");
        var progress = new RecordingProgress();
        var result = await LobbyModSynchronizer.SynchronizeAsync(
            localCatalog,
            42,
            ticket: null,
            cacheRoot,
            client,
            progress);
        Require(result.UsedWebsite, "available website unexpectedly selected offline fallback");
        Require(result.RequiredModCount == 1, "preflight required count changed");
        Require(result.DownloadedModCount == 1, "missing website mod was not downloaded");
        Require(result.Catalog.EnabledMods.Count == 1, "preflight staged extra local mods");
        Require(result.Catalog.FindById(required.Id) is not null, "required website mod was not selected");
        Require(result.Catalog.FindById("tests.unrelated") is null, "unrelated local mod remained selected");
        Require(handler.JoinManifestRequests == 1, "preflight did not request the join manifest once");
        Require(handler.ResolveRequests == 1, "preflight did not resolve the missing package once");
        Require(
            handler.ResolveLoaderVersion == "0.1.0-beta.21",
            "preflight resolution omitted the current loader version");
        Require(handler.DownloadRequests == 1, "preflight did not download the missing package once");
        Require(
            progress.Values.Any(value => value.Phase == UpdateProgressPhase.Downloading) &&
            progress.Values.Last().Phase == UpdateProgressPhase.Completed,
            "lobby mod sync did not report download through completion");

        var manualCatalog = ModCatalog.CreateExact(result.Catalog.EnabledMods);
        var manualHandler = new LobbyDirectoryHandler(
            package,
            required,
            packageSha256,
            rejectResolution: true);
        using var manualClient = new HttpClient(manualHandler)
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var manualResult = await LobbyModSynchronizer.SynchronizeAsync(
            manualCatalog,
            42,
            ticket: null,
            Path.Combine(root, "unused-cache"),
            manualClient);
        Require(manualResult.ReusedManualModCount == 1, "exact manual package was not reused");
        Require(manualResult.DownloadedModCount == 0, "exact manual package was downloaded again");
        Require(manualHandler.ResolveRequests == 0, "manual reuse unnecessarily called resolution");

        using var offlineClient = new HttpClient(new OfflineDirectoryHandler())
        {
            BaseAddress = new Uri("https://offline.example.test/")
        };
        var offlineProgress = new RecordingProgress();
        var offlineResult = await LobbyModSynchronizer.SynchronizeAsync(
            manualCatalog,
            42,
            ticket: null,
            Path.Combine(root, "offline-cache"),
            offlineClient,
            offlineProgress);
        Require(!offlineResult.UsedWebsite, "unavailable website did not select offline fallback");
        Require(
            offlineProgress.Values.Last().Phase == UpdateProgressPhase.Failed,
            "offline host mod sync failure was not reported visibly");
        Require(
            offlineResult.Catalog.EnabledMods.Count == 1 &&
            offlineResult.Catalog.IsEnabled(required.Id),
            "offline fallback changed the locally enabled exact mod set");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static async Task TestJoinPreviewClassificationAsync()
{
    var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
    {
        ["manifest.json"] = Encoding.UTF8.GetBytes(
            """
            {
              "id": "tests.preview",
              "name": "Preview Test",
              "version": "2.0.0",
              "overlays": [{
                "target": "data/levels/survival.boneyard",
                "source": "files/survival.boneyard"
              }]
            }
            """),
        ["files/survival.boneyard"] = BoneyardFixture()
    };
    var package = CreateZip(entries);
    var required = new MultiplayerModDescriptor(
        "tests.preview",
        "2.0.0",
        ComputeContentHash(entries));
    var packageSha256 = Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant();
    var root = CreateTemporaryDirectory();
    try
    {
        var emptyCatalog = ModCatalog.CreateExact([]);
        var handler = new LobbyDirectoryHandler(package, required, packageSha256);
        using var client = new HttpClient(handler)
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };

        var downloadPreview = await LobbyModSynchronizer.PreviewAsync(
            emptyCatalog,
            42,
            ticket: null,
            Path.Combine(root, "cache"),
            client);
        Require(downloadPreview.UsedWebsite, "preview did not use the available website");
        Require(downloadPreview.Error is null, "preview reported an unexpected error");
        Require(
            downloadPreview.HostBuild is
            {
                ProtocolVersion: LobbyDirectoryHandler.HostProtocolVersion,
                ManifestSha256: LobbyDirectoryHandler.HostManifestSha256,
                LoaderVersion: LobbyDirectoryHandler.HostLoaderVersion
            },
            "preview did not parse the host build descriptor");
        Require(
            downloadPreview.DownloadCount == 1 &&
            downloadPreview.InstalledCount == 0 &&
            downloadPreview.UnavailableCount == 0,
            "missing website mod was not classified as needing download");
        Require(
            downloadPreview.Mods.Single() is
            {
                State: LobbyJoinPreviewModState.NeedsDownload,
                Name: LobbyDirectoryHandler.WebsiteModName,
                DownloadSizeBytes: 4096
            },
            "download preview did not carry website name and size");
        Require(
            handler.DownloadRequests == 0,
            "preview downloaded a package instead of only classifying it");

        var localRoot = Path.Combine(root, "local");
        Directory.CreateDirectory(Path.Combine(localRoot, "files"));
        File.WriteAllBytes(
            Path.Combine(localRoot, "manifest.json"),
            entries["manifest.json"]);
        File.WriteAllBytes(
            Path.Combine(localRoot, "files", "survival.boneyard"),
            entries["files/survival.boneyard"]);
        var localCatalog = ModCatalog.CreateExact([ModDiscovery.DiscoverRoot(localRoot)]);
        var installedPreview = await LobbyModSynchronizer.PreviewAsync(
            localCatalog,
            42,
            ticket: null,
            Path.Combine(root, "cache-installed"),
            client);
        Require(
            installedPreview.InstalledCount == 1 && installedPreview.DownloadCount == 0,
            "exact local mod was not classified as installed");

        var unavailableHandler = new LobbyDirectoryHandler(
            package,
            required,
            packageSha256,
            resolveReportsMissing: true);
        using var unavailableClient = new HttpClient(unavailableHandler)
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var unavailablePreview = await LobbyModSynchronizer.PreviewAsync(
            emptyCatalog,
            42,
            ticket: null,
            Path.Combine(root, "cache-unavailable"),
            unavailableClient);
        Require(
            unavailablePreview.UnavailableCount == 1 &&
            unavailablePreview.DownloadCount == 0,
            "unresolvable host mod was not classified as unavailable");

        using var offlineClient = new HttpClient(new OfflineDirectoryHandler())
        {
            BaseAddress = new Uri("https://offline.example.test/")
        };
        var offlinePreview = await LobbyModSynchronizer.PreviewAsync(
            emptyCatalog,
            42,
            ticket: null,
            Path.Combine(root, "cache-offline"),
            offlineClient);
        Require(
            !offlinePreview.UsedWebsite && offlinePreview.Error is not null,
            "offline preview did not report an error");

        var mismatchThrown = false;
        try
        {
            await LobbyModSynchronizer.SynchronizeAsync(
                emptyCatalog,
                42,
                ticket: null,
                Path.Combine(root, "cache-sync"),
                unavailableClient);
        }
        catch (InvalidOperationException exception)
        {
            mismatchThrown = true;
            Require(
                exception.Message.Contains("Mod list mismatch", StringComparison.Ordinal),
                "unrepairable sync did not raise a mod list mismatch message");
        }
        Require(mismatchThrown, "unrepairable sync did not throw");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static Task TestWebsiteJoinUriAsync()
{
    var valid =
        "solomondarkrevived://join/123?directory=https%3A%2F%2Fmods.example.test%2Fcommunity&ticket=signed-token";
    Require(LauncherJoinUri.TryParse(valid, out var activation), "valid website join URI was rejected");
    Require(activation.LobbyId == 123, "website join URI lobby id changed");
    Require(
        activation.DirectoryBaseUrl == "https://mods.example.test/community",
        "website join URI directory changed");
    Require(activation.Ticket == "signed-token", "website join URI ticket changed");

    Require(
        !LauncherJoinUri.TryParse("solomondarkrevived://join/123", out _),
        "website join URI without directory was accepted");
    Require(
        !LauncherJoinUri.TryParse(
            "solomondarkrevived://join/123?directory=http%3A%2F%2Fevil.example.test",
            out _),
        "remote plaintext website origin was accepted");
    Require(
        !LauncherJoinUri.TryParse(
            "solomondarkrevived://join/123?directory=https%3A%2F%2Fmods.example.test&extra=x",
            out _),
        "unknown website join URI parameter was accepted");
    return Task.CompletedTask;
}

static Task TestWebsiteInstallModUriAsync()
{
    const string valid =
        "solomondarkrevived://install-mod/arcane-bots?directory=http%3A%2F%2F127.0.0.1%3A5173";
    Require(
        LauncherJoinUri.TryParseInstallMod(valid, out var activation),
        "valid install-mod URI was rejected");
    Require(
        activation.Slug == "arcane-bots" &&
        activation.DirectoryBaseUrl == "http://127.0.0.1:5173",
        "install-mod URI fields changed");

    var invalid = new[]
    {
        "solomondarkrevived://install-mod/arcane-bots",
        "solomondarkrevived://install-mod/Arcane?directory=https%3A%2F%2Fmods.example.test",
        "solomondarkrevived://install-mod/arcane--bots?directory=https%3A%2F%2Fmods.example.test",
        "solomondarkrevived://install-mod/arcane/bots?directory=https%3A%2F%2Fmods.example.test",
        "solomondarkrevived://install-mod/arcane-bots?directory=http%3A%2F%2Fmods.example.test",
        "solomondarkrevived://install-mod/arcane-bots?directory=https%3A%2F%2Fuser%40mods.example.test",
        "solomondarkrevived://install-mod/arcane-bots?directory=https%3A%2F%2Fmods.example.test&extra=x",
        "solomondarkrevived://install-mod/arcane-bots?directory=https%3A%2F%2Fmods.example.test%23fragment",
    };
    foreach (var value in invalid)
    {
        Require(
            !LauncherJoinUri.TryParseInstallMod(value, out _),
            $"unsafe install-mod URI was accepted: {value}");
    }

    var command = LauncherCommandParser.Parse(
        [
            "install-mod",
            "arcane-bots",
            "--directory-url",
            "http://127.0.0.1:5173"
        ]);
    Require(
        command.Mode == LauncherMode.InstallMod &&
        command.TargetModId == "arcane-bots" &&
        command.LobbyHost.DirectoryBaseUrl == "http://127.0.0.1:5173",
        "install-mod CLI routing changed");
    return Task.CompletedTask;
}

static Task TestWebsiteInstallModUiCommandOrderingAsync()
{
    var root = CreateTemporaryDirectory();
    var previous = Environment.GetEnvironmentVariable(
        LauncherPathPolicy.TestApplicationDataRootEnvironmentVariable);
    try
    {
        Environment.SetEnvironmentVariable(
            LauncherPathPolicy.TestApplicationDataRootEnvironmentVariable,
            root);
        var client = new LauncherUiCommandClient();
        var preview = client.BuildCommandPreview(
            LauncherUiCommandMode.InstallModPreview,
            "arcane-bots");
        var install = client.BuildCommandPreview(
            LauncherUiCommandMode.InstallMod,
            "arcane-bots");
        Require(
            preview.StartsWith(
                "SolomonDarkModLauncher.exe install-mod-preview arcane-bots --json --progress-json",
                StringComparison.Ordinal) &&
            install.StartsWith(
                "SolomonDarkModLauncher.exe install-mod arcane-bots --json --progress-json",
                StringComparison.Ordinal),
            "website install-mod UI put JSON flags between the verb and its slug");
    }
    finally
    {
        Environment.SetEnvironmentVariable(
            LauncherPathPolicy.TestApplicationDataRootEnvironmentVariable,
            previous);
        Directory.Delete(root, recursive: true);
    }
    return Task.CompletedTask;
}

static Task TestScopedActivationIsolationAsync()
{
    Require(
        LauncherStartupArguments.TryParse(
            ["--test-activation-scope=qol-browser"],
            out var primary) &&
        primary.IsTestScoped &&
        primary.TestScope == "qol-browser" &&
        primary.ActivationArgument.Length == 0,
        "scoped primary launcher arguments were rejected");
    const string activation =
        "solomondarkrevived://install-mod/arcane-bots" +
        "?directory=http%3A%2F%2F127.0.0.1%3A5173";
    Require(
        LauncherStartupArguments.TryParse(
            [
                "--test-activation-scope=qol-browser",
                activation
            ],
            out var secondary) &&
        secondary.ActivationArgument == activation &&
        secondary.ProtocolCommandScopeArgument ==
            "--test-activation-scope=qol-browser",
        "scoped browser activation did not retain its URI");
    Require(
        !LauncherStartupArguments.TryParse(
            ["--test-activation-scope=QOL"],
            out _) &&
        !LauncherStartupArguments.TryParse(
            [
                "--test-activation-scope=qol",
                activation,
                "extra"
            ],
            out _),
        "unsafe scoped activation arguments were accepted");

    var previous = Environment.GetEnvironmentVariable(
        LauncherPathPolicy
            .TestApplicationDataRootEnvironmentVariable);
    try
    {
        primary.ApplyTestIsolation();
        var isolatedRoot = Environment.GetEnvironmentVariable(
            LauncherPathPolicy
                .TestApplicationDataRootEnvironmentVariable);
        Require(
            !string.IsNullOrWhiteSpace(isolatedRoot) &&
            isolatedRoot.Contains(
                Path.Combine(
                    ".sdmod-test-data",
                    "qol-browser"),
                StringComparison.OrdinalIgnoreCase),
            "scoped launcher did not isolate application data");
    }
    finally
    {
        Environment.SetEnvironmentVariable(
            LauncherPathPolicy
                .TestApplicationDataRootEnvironmentVariable,
            previous);
    }
    return Task.CompletedTask;
}

static async Task TestWebsiteInstallModPipelineAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var modsRoot = Path.Combine(root, "mods");
        var cacheRoot = Path.Combine(root, "cache");
        var handler = new InstallModDirectoryHandler();
        using var client = new HttpClient(handler)
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };

        var empty = ModCatalog.CreateExact([]);
        var preview = await WebsiteModInstaller.PreviewAsync(
            empty,
            InstallModDirectoryHandler.Slug,
            client);
        Require(
            preview.Disposition == WebsiteModInstallDisposition.Install &&
            preview.Name == InstallModDirectoryHandler.Name &&
            preview.Version == "1.0.0",
            "new website mod was not offered as an install");

        var progress = new RecordingProgress();
        var installed = await WebsiteModInstaller.InstallAsync(
            empty,
            modsRoot,
            cacheRoot,
            InstallModDirectoryHandler.Slug,
            client,
            progress);
        Require(installed.Changed, "new website mod was not installed");
        var installedRoot = Path.Combine(
            modsRoot,
            InstallModDirectoryHandler.Id);
        Require(
            ModDiscovery.DiscoverRoot(installedRoot).Manifest.Version == "1.0.0",
            "installed website mod did not appear in the managed Mods directory");
        Require(
            progress.Values.Any(value =>
                value.Phase == UpdateProgressPhase.Verifying) &&
            progress.Values.Last().Phase == UpdateProgressPhase.Completed,
            "install-mod did not use the verified package pipeline");

        var v1Catalog = ModCatalog.CreateExact(
            [ModDiscovery.DiscoverRoot(installedRoot)]);
        var current = await WebsiteModInstaller.PreviewAsync(
            v1Catalog,
            InstallModDirectoryHandler.Slug,
            client);
        Require(
            current.Disposition == WebsiteModInstallDisposition.Current,
            "current website mod was not recognized");

        handler.Publish("1.1.0");
        var update = await WebsiteModInstaller.PreviewAsync(
            v1Catalog,
            InstallModDirectoryHandler.Slug,
            client);
        Require(
            update.Disposition == WebsiteModInstallDisposition.Update &&
            update.InstalledVersion == "1.0.0",
            "older website mod was not offered an update");
        var updated = await WebsiteModInstaller.InstallAsync(
            v1Catalog,
            modsRoot,
            cacheRoot,
            InstallModDirectoryHandler.Slug,
            client);
        Require(
            updated.Changed &&
            ModDiscovery.DiscoverRoot(installedRoot).Manifest.Version == "1.1.0",
            "install-mod update did not atomically replace the older edition");

        await RequireThrowsAsync<InvalidOperationException>(
            () => WebsiteModInstaller.PreviewAsync(
                ModCatalog.CreateExact([]),
                "unknown-mod",
                client),
            "unknown website mod did not fail explicitly");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static Task TestLauncherReleaseSelectionAsync()
{
    Require(
        SemanticVersion.TryParse("0.1.0-beta.11", out var currentVersion),
        "current launcher version did not parse");
    var release = LauncherSelfUpdater.SelectUpdate(
        """
        [
          {
            "tag_name": "v0.1.0-beta.14",
            "draft": true,
            "assets": [
              {
                "name": "SolomonDarkMultiplayerBeta-v0.1.0-beta.14.zip",
                "browser_download_url": "https://example.test/beta14.zip"
              }
            ]
          },
          {
            "tag_name": "v0.1.0-beta.13",
            "draft": false,
            "assets": [
              {
                "name": "source.zip",
                "browser_download_url": "https://example.test/source.zip"
              }
            ]
          },
          {
            "tag_name": "v0.1.0-beta.12",
            "draft": false,
            "assets": [
              {
                "name": "SolomonDarkMultiplayerBeta-v0.1.0-beta.12.zip",
                "browser_download_url": "https://example.test/beta12.zip"
              }
            ]
          }
        ]
        """,
        currentVersion!);

    Require(release is not null, "new launcher release was not selected");
    Require(
        release!.Version.Value == "0.1.0-beta.12",
        "launcher selected a draft or a release without its package");
    Require(
        release.AssetName == "SolomonDarkMultiplayerBeta-v0.1.0-beta.12.zip",
        "launcher selected the wrong release asset");
    return Task.CompletedTask;
}

static async Task TestLauncherDownloadProgressAsync()
{
    Require(
        SemanticVersion.TryParse("0.1.0-beta.12", out var version),
        "launcher download test version did not parse");
    var archive = CreateZip(new Dictionary<string, byte[]>
    {
        ["SolomonDarkMultiplayerBeta-v0.1.0-beta.12/launcher.bin"] =
            Enumerable.Range(0, 700_000).Select(index => (byte)(index % 251)).ToArray()
    });
    var root = CreateTemporaryDirectory();
    try
    {
        var archivePath = Path.Combine(root, "launcher-update.zip");
        using var client = new HttpClient(new ByteArrayHandler(archive));
        var progress = new RecordingProgress();
        await LauncherSelfUpdater.DownloadArchiveAsync(
            client,
            new LauncherRelease(
                version!,
                "SolomonDarkMultiplayerBeta-v0.1.0-beta.12.zip",
                "https://updates.example.test/launcher.zip"),
            archivePath,
            progress,
            CancellationToken.None);

        Require(
            File.ReadAllBytes(archivePath).SequenceEqual(archive),
            "launcher update download changed the archive bytes");
        var finalDownload = progress.Values.Last(value =>
            value.Phase == UpdateProgressPhase.Downloading);
        Require(
            finalDownload.Completed == archive.Length &&
            finalDownload.Total == archive.Length &&
            finalDownload.Unit == UpdateProgressUnit.Bytes,
            "launcher download did not report its real byte total");
        Require(
            progress.Values.Last().Phase == UpdateProgressPhase.Verifying,
            "launcher download did not enter archive verification");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static Task TestUpdateProgressJsonProtocolAsync()
{
    var expected = new UpdateProgress(
        UpdateProgressPhase.Downloading,
        "Downloading launcher v1.2.3…",
        512,
        1024,
        UpdateProgressUnit.Bytes);
    var payload = LauncherJsonConsole.SerializeProgress(expected);
    Require(
        LauncherJsonResponseReader.TryParseUpdateProgress(payload, out var parsed),
        "desktop launcher did not recognize the CLI progress envelope");
    Require(parsed == expected, "CLI progress JSON changed in transit");
    Require(
        payload.Contains("\"phase\":\"downloading\"", StringComparison.Ordinal) &&
        payload.Contains("\"completed\":512", StringComparison.Ordinal) &&
        payload.Contains("\"total\":1024", StringComparison.Ordinal),
        "progress JSON omitted the phase or real byte counters");

    var presentation = UpdateProgressPresentation.Create(parsed!);
    Require(
        presentation.Value == 50 &&
        presentation.DetailText.Contains("512 bytes of 1 KB", StringComparison.Ordinal),
        "desktop progress presentation did not calculate the real percentage and bytes");

    var command = LauncherCommandParser.Parse(
        ["list-mods", "--json", "--progress-json"]);
    Require(command.ProgressJson, "launcher parser did not enable streamed progress");
    RequireThrows<InvalidOperationException>(
        () => LauncherCommandParser.Parse(["list-mods", "--progress-json"]),
        "launcher accepted progress streaming without final JSON output");

    var originalOutput = Console.Out;
    var originalError = Console.Error;
    using var failedOutput = new StringWriter();
    using var failedError = new StringWriter();
    int exitCode;
    try
    {
        Console.SetOut(failedOutput);
        Console.SetError(failedError);
        exitCode = LauncherApplication.Run(
            ["list-mods", "--json", "--progress-json", "--unknown-option"]);
    }
    finally
    {
        Console.SetOut(originalOutput);
        Console.SetError(originalError);
    }

    var failureLines = failedOutput.ToString()
        .Split(
            [Environment.NewLine],
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    var failureErrorLines = failedError.ToString()
        .Split(
            [Environment.NewLine],
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    Require(exitCode == 1, "invalid streamed command unexpectedly succeeded");
    Require(
        failureLines.Length == 1 &&
        LauncherJsonResponseReader.TryParseUpdateProgress(
            failureLines[0],
            out var failureProgress) &&
        failureProgress?.Phase == UpdateProgressPhase.Failed,
        "failing streamed command did not terminate progress with a failed phase");
    Require(
        failureErrorLines.Length == 1,
        "failing streamed command omitted its final JSON error response");
    using var failureDocument = JsonDocument.Parse(failureErrorLines[0]);
    Require(
        failureDocument.RootElement.TryGetProperty("success", out var success) &&
        success.ValueKind == JsonValueKind.False,
        "failing streamed command omitted its final JSON error response");
    return Task.CompletedTask;
}

static Task TestLauncherUpdateInstallationAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var target = Path.Combine(root, "installed");
        WriteDistribution(
            target,
            new Dictionary<string, string>
            {
                ["SolomonDarkMultiplayerBeta.exe"] = "old launcher",
                ["SolomonDarkLauncherUpdater.exe"] = "old updater",
                ["solomon-dark-multiplayer.json"] = """{"version":"0.1.0-beta.11"}""",
                ["launcher/old-runtime.txt"] = "old runtime"
            });
        var userModPath = Path.Combine(target, "mods", "my-mod", "main.lua");
        Directory.CreateDirectory(Path.GetDirectoryName(userModPath)!);
        File.WriteAllText(userModPath, "return 'mine'\n");

        var sourceRoot = Path.Combine(
            root,
            "source",
            "SolomonDarkMultiplayerBeta-v0.1.0-beta.12");
        WriteDistribution(
            sourceRoot,
            new Dictionary<string, string>
            {
                ["SolomonDarkMultiplayerBeta.exe"] = "new launcher",
                ["SolomonDarkLauncherUpdater.exe"] = "new updater",
                ["solomon-dark-multiplayer.json"] = """{"version":"0.1.0-beta.12"}""",
                ["launcher/new-runtime.txt"] = "new runtime"
            });
        var archivePath = Path.Combine(root, "update.zip");
        ZipFile.CreateFromDirectory(
            sourceRoot,
            archivePath,
            CompressionLevel.Optimal,
            includeBaseDirectory: true);

        var progress = new RecordingProgress();
        LauncherUpdateInstaller.Install(archivePath, target, progress);
        Require(
            File.ReadAllText(Path.Combine(target, "SolomonDarkMultiplayerBeta.exe")) ==
                "new launcher",
            "launcher update did not install the new launcher");
        Require(
            File.Exists(Path.Combine(target, "launcher", "new-runtime.txt")),
            "launcher update did not install the new package");
        Require(
            !File.Exists(Path.Combine(target, "launcher", "old-runtime.txt")),
            "launcher update retained an obsolete package file");
        Require(
            File.ReadAllText(userModPath) == "return 'mine'\n",
            "launcher update did not preserve a user-installed mod");
        Require(
            progress.Values.Any(value =>
                value.Phase == UpdateProgressPhase.Installing &&
                value.Unit == UpdateProgressUnit.Bytes &&
                value.Completed == value.Total),
            "launcher installer did not report real extraction progress");
        Require(
            progress.Values.Any(value => value.Phase == UpdateProgressPhase.Verifying) &&
            progress.Values.Last().StatusText == "Launcher files installed.",
            "launcher installer did not report verification through installation");

        var nextSourceRoot = Path.Combine(
            root,
            "next-source",
            "SolomonDarkMultiplayerBeta-v0.1.0-beta.13");
        WriteDistribution(
            nextSourceRoot,
            new Dictionary<string, string>
            {
                ["SolomonDarkMultiplayerBeta.exe"] = "replacement launcher",
                ["SolomonDarkLauncherUpdater.exe"] = "replacement updater",
                ["solomon-dark-multiplayer.json"] = """{"version":"0.1.0-beta.13"}""",
                ["launcher/replacement-runtime.txt"] = "replacement runtime"
            });
        var nextArchivePath = Path.Combine(root, "next-update.zip");
        ZipFile.CreateFromDirectory(
            nextSourceRoot,
            nextArchivePath,
            CompressionLevel.Optimal,
            includeBaseDirectory: true);
        using (File.Open(userModPath, FileMode.Open, FileAccess.Read, FileShare.None))
        {
            var installFailed = false;
            try
            {
                LauncherUpdateInstaller.Install(nextArchivePath, target);
            }
            catch (IOException)
            {
                installFailed = true;
            }
            Require(installFailed, "locked user data did not fail launcher replacement");
            Require(
                File.ReadAllText(Path.Combine(target, "SolomonDarkMultiplayerBeta.exe")) ==
                    "new launcher",
                "failed launcher replacement did not roll back");
        }

        var invalidArchivePath = Path.Combine(root, "invalid-update.zip");
        using (var archive = ZipFile.Open(
                   invalidArchivePath,
                   ZipArchiveMode.Create))
        {
            var entry = archive.CreateEntry(
                "SolomonDarkMultiplayerBeta-v0.1.0-beta.13/../outside.txt");
            using var writer = new StreamWriter(entry.Open());
            writer.Write("unsafe");
        }

        var rejected = false;
        try
        {
            LauncherUpdateInstaller.Install(invalidArchivePath, target);
        }
        catch (InvalidDataException)
        {
            rejected = true;
        }
        Require(rejected, "launcher update accepted an unsafe archive path");
        Require(
            File.ReadAllText(Path.Combine(target, "SolomonDarkMultiplayerBeta.exe")) ==
                "new launcher",
            "rejected launcher update changed the installed launcher");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
    return Task.CompletedTask;
}

static void WriteDistribution(
    string root,
    IReadOnlyDictionary<string, string> files)
{
    Directory.CreateDirectory(root);
    foreach (var pair in files)
    {
        var path = Path.Combine(root, pair.Key.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, pair.Value);
    }

    var ownedFiles = files.Keys
        .Append(".distribution-files.json")
        .OrderBy(path => path, StringComparer.Ordinal)
        .ToArray();
    File.WriteAllText(
        Path.Combine(root, ".distribution-files.json"),
        JsonSerializer.Serialize(new
        {
            schemaVersion = 1,
            files = ownedFiles
        }));
}

static byte[] CreateZip(IReadOnlyDictionary<string, byte[]> entries)
{
    using var buffer = new MemoryStream();
    using (var archive = new ZipArchive(buffer, ZipArchiveMode.Create, leaveOpen: true))
    {
        foreach (var pair in entries)
        {
            var entry = archive.CreateEntry(pair.Key, CompressionLevel.Optimal);
            using var stream = entry.Open();
            stream.Write(pair.Value);
        }
    }
    return buffer.ToArray();
}

static byte[] BoneyardFixture() =>
    File.ReadAllBytes(Path.Combine(
        AppContext.BaseDirectory,
        "fixtures",
        "flat_multiplayer_test.boneyard"));

static string ComputeContentHash(IReadOnlyDictionary<string, byte[]> entries)
{
    using var aggregate = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
    foreach (var pair in entries.OrderBy(pair => pair.Key, StringComparer.Ordinal))
    {
        var fileHash = Convert.ToHexString(SHA256.HashData(pair.Value)).ToLowerInvariant();
        aggregate.AppendData(Encoding.UTF8.GetBytes($"{pair.Key}\0{fileHash}\n"));
    }
    return Convert.ToHexString(aggregate.GetHashAndReset()).ToLowerInvariant();
}

static string CreateTemporaryDirectory()
{
    var path = Path.Combine(Path.GetTempPath(), $"sdr-launcher-contract-{Guid.NewGuid():N}");
    Directory.CreateDirectory(path);
    return path;
}

static void Require(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static void RequireThrows<TException>(Action action, string message)
    where TException : Exception
{
    try
    {
        action();
    }
    catch (TException)
    {
        return;
    }
    throw new InvalidOperationException(message);
}

static async Task RequireThrowsAsync<TException>(
    Func<Task> action,
    string message)
    where TException : Exception
{
    try
    {
        await action();
    }
    catch (TException)
    {
        return;
    }
    throw new InvalidOperationException(message);
}

file sealed class RecordingProgress : IProgress<UpdateProgress>
{
    public List<UpdateProgress> Values { get; } = [];

    public void Report(UpdateProgress value)
    {
        Values.Add(value);
    }
}

file sealed class ByteArrayHandler(byte[] content) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken) =>
        Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(content)
        });
}

file sealed class PackageHandler(byte[] package) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        if (request.Method != HttpMethod.Get ||
            request.RequestUri?.AbsoluteUri !=
            "https://mods.example.test/community/api/mods/tests/versions/1/download")
        {
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
        }

        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(package)
        });
    }
}

file sealed class InstallModDirectoryHandler : HttpMessageHandler
{
    public const string Slug = "arcane-bots";
    public const string Id = "tests.install-link";
    public const string Name = "Install Link Test";

    private byte[] package_ = [];
    private string version_ = string.Empty;
    private string packageSha256_ = string.Empty;
    private string contentSha256_ = string.Empty;
    private int versionId_;

    public InstallModDirectoryHandler()
    {
        Publish("1.0.0");
    }

    public void Publish(string version)
    {
        version_ = version;
        versionId_++;
        var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
        {
            ["manifest.json"] = Encoding.UTF8.GetBytes(
                $$"""
                {
                  "id": "{{Id}}",
                  "name": "{{Name}}",
                  "version": "{{version}}",
                  "runtime": {
                    "apiVersion": "0.2.0",
                    "entryScript": "scripts/main.lua",
                    "requiredCapabilities": [],
                    "optionalCapabilities": []
                  }
                }
                """),
            ["scripts/main.lua"] = Encoding.UTF8.GetBytes(
                $"-- {version}\nreturn true\n")
        };
        package_ = BuildZip(entries);
        packageSha256_ = Convert.ToHexString(
            SHA256.HashData(package_)).ToLowerInvariant();
        contentSha256_ = HashContent(entries);
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var path = request.RequestUri?.AbsolutePath;
        if (request.Method == HttpMethod.Get &&
            path == $"/community/api/mods/{Slug}")
        {
            return Task.FromResult(Json(
                $$"""
                {"slug":"{{Slug}}","name":"{{Name}}","launcherModId":"{{Id}}","versions":[{"id":{{versionId_}},"manifestVersion":"{{version_}}","packageSha256":"{{packageSha256_}}","contentSha256":"{{contentSha256_}}","fileSize":{{package_.Length}}}]}
                """));
        }
        if (request.Method == HttpMethod.Get &&
            path ==
            $"/community/api/mods/{Slug}/versions/{versionId_}/download")
        {
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(package_)
            });
        }
        return Task.FromResult(
            new HttpResponseMessage(HttpStatusCode.NotFound));
    }

    private static HttpResponseMessage Json(string value) =>
        new(HttpStatusCode.OK)
        {
            Content = new StringContent(
                value,
                Encoding.UTF8,
                "application/json")
        };

    private static byte[] BuildZip(
        IReadOnlyDictionary<string, byte[]> entries)
    {
        using var buffer = new MemoryStream();
        using (var archive = new ZipArchive(
                   buffer,
                   ZipArchiveMode.Create,
                   leaveOpen: true))
        {
            foreach (var pair in entries)
            {
                var entry = archive.CreateEntry(
                    pair.Key,
                    CompressionLevel.Optimal);
                using var stream = entry.Open();
                stream.Write(pair.Value);
            }
        }
        return buffer.ToArray();
    }

    private static string HashContent(
        IReadOnlyDictionary<string, byte[]> entries)
    {
        using var aggregate =
            IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        foreach (var pair in entries.OrderBy(
                     pair => pair.Key,
                     StringComparer.Ordinal))
        {
            var fileHash = Convert.ToHexString(
                SHA256.HashData(pair.Value)).ToLowerInvariant();
            aggregate.AppendData(
                Encoding.UTF8.GetBytes(
                    $"{pair.Key}\0{fileHash}\n"));
        }
        return Convert.ToHexString(
            aggregate.GetHashAndReset()).ToLowerInvariant();
    }
}

file sealed class OfflineDirectoryHandler : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken) =>
        throw new HttpRequestException("Website unavailable for contract test.");
}

file sealed class LobbyDirectoryHandler(
    byte[] package,
    MultiplayerModDescriptor required,
    string packageSha256,
    bool rejectResolution = false,
    bool resolveReportsMissing = false) : HttpMessageHandler
{
    public const string WebsiteModName = "Preflight Test";
    public const string HostLoaderVersion = "9.9.9-test";
    public const int HostProtocolVersion = 80;
    public const string HostManifestSha256 =
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    public int JoinManifestRequests { get; private set; }
    public int ResolveRequests { get; private set; }
    public int DownloadRequests { get; private set; }
    public string? ResolveLoaderVersion { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var path = request.RequestUri?.AbsolutePath;
        if (request.Method == HttpMethod.Get &&
            path == "/community/api/lobbies/42/join-manifest")
        {
            JoinManifestRequests++;
            return await Json(
                $$"""
                {"lobbyId":"42","build":{"appId":3362180,"protocolVersion":{{HostProtocolVersion}},"manifestSha256":"{{HostManifestSha256}}","loaderVersion":"{{HostLoaderVersion}}"},"mods":[{"id":"{{required.Id}}","version":"{{required.Version}}","contentSha256":"{{required.ContentSha256}}"}]}
                """);
        }

        if (request.Method == HttpMethod.Post && path == "/community/api/mods/resolve")
        {
            ResolveRequests++;
            if (rejectResolution)
            {
                return new HttpResponseMessage(HttpStatusCode.InternalServerError);
            }
            var payload = await request.Content!.ReadAsStringAsync(cancellationToken);
            using var document = JsonDocument.Parse(payload);
            ResolveLoaderVersion = document.RootElement.GetProperty("loaderVersion").GetString();
            if (resolveReportsMissing)
            {
                return await Json(
                    $$"""
                    {"mods":[],"missing":[{"id":"{{required.Id}}","version":"{{required.Version}}","contentSha256":"{{required.ContentSha256}}"}]}
                    """);
            }
            return await Json(
                $$"""
                {"mods":[{"id":"{{required.Id}}","version":"{{required.Version}}","contentSha256":"{{required.ContentSha256}}","packageSha256":"{{packageSha256}}","name":"{{WebsiteModName}}","fileSize":4096,"downloadUrl":"api/mods/tests/versions/1/download"}],"missing":[]}
                """);
        }

        if (request.Method == HttpMethod.Get &&
            path == "/community/api/mods/tests/versions/1/download")
        {
            DownloadRequests++;
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(package)
            };
        }

        return new HttpResponseMessage(HttpStatusCode.NotFound);
    }

    private static Task<HttpResponseMessage> Json(string value) =>
        Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(value, Encoding.UTF8, "application/json")
        });
}

file sealed class ModUpdateHandler(
    byte[] package,
    MultiplayerModDescriptor required,
    string packageSha256) : HttpMessageHandler
{
    public IReadOnlyList<string> RequestedIds { get; private set; } = [];
    public string? LoaderVersion { get; private set; }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var path = request.RequestUri?.AbsolutePath;
        if (request.Method == HttpMethod.Post && path == "/community/api/mods/updates")
        {
            var payload = await request.Content!.ReadAsStringAsync(cancellationToken);
            using var document = JsonDocument.Parse(payload);
            LoaderVersion = document.RootElement.GetProperty("loaderVersion").GetString();
            RequestedIds = document.RootElement
                .GetProperty("mods")
                .EnumerateArray()
                .Select(mod => mod.GetProperty("id").GetString()!)
                .ToArray();
            return Json(
                $$"""
                {"updates":[{"id":"{{required.Id}}","version":"{{required.Version}}","contentSha256":"{{required.ContentSha256}}","packageSha256":"{{packageSha256}}","downloadUrl":"api/mods/tests/versions/2/download"}]}
                """);
        }

        if (request.Method == HttpMethod.Get &&
            path == "/community/api/mods/tests/versions/2/download")
        {
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(package)
            };
        }

        return new HttpResponseMessage(HttpStatusCode.NotFound);
    }

    private static HttpResponseMessage Json(string value) =>
        new(HttpStatusCode.OK)
        {
            Content = new StringContent(value, Encoding.UTF8, "application/json")
        };
}

file sealed class RecordingModSettingsRuntimeClient :
    IModSettingsRuntimeClient
{
    public int ReloadCalls { get; private set; }
    public int ActionCalls { get; private set; }
    public string LastPipeName { get; private set; } = string.Empty;
    public string LastModId { get; private set; } = string.Empty;
    public string LastEntryKey { get; private set; } = string.Empty;

    public Task<ModSettingsRuntimeResult> ReloadAsync(
        string pipeName,
        string modId,
        CancellationToken cancellationToken = default)
    {
        ReloadCalls++;
        LastPipeName = pipeName;
        LastModId = modId;
        return Task.FromResult(new ModSettingsRuntimeResult
        {
            Ok = true,
            Changed = ["kite_radius"]
        });
    }

    public Task<ModSettingsRuntimeResult> InvokeActionAsync(
        string pipeName,
        string modId,
        string entryKey,
        CancellationToken cancellationToken = default)
    {
        ActionCalls++;
        LastPipeName = pipeName;
        LastModId = modId;
        LastEntryKey = entryKey;
        return Task.FromResult(new ModSettingsRuntimeResult { Ok = true });
    }
}
