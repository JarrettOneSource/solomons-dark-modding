using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using SolomonDarkModding.Versioning;
using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Launch;
using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.UI.Infrastructure;
using SolomonDarkModLauncher.Workspace;
using SolomonDarkLauncherUpdater;

var tests = new (string Name, Func<Task> Run)[]
{
    ("website package install and cache", TestWebsitePackageInstallAsync),
    ("automatic mod updates", TestAutomaticModUpdatesAsync),
    ("semantic version ordering", TestSemanticVersionOrderingAsync),
    ("launcher release selection", TestLauncherReleaseSelectionAsync),
    ("launcher update installation", TestLauncherUpdateInstallationAsync),
    ("downloaded package traversal rejection", TestDownloadedPackageTraversalAsync),
    ("downloaded package contract", TestDownloadedPackageContractAsync),
    ("website lobby preflight", TestWebsiteLobbyPreflightAsync),
    ("exact manual catalog", TestExactManualCatalogAsync),
    ("canonical mod identifiers", TestCanonicalModIdentifiersAsync),
    ("strict multiplayer mod parity", TestStrictMultiplayerModParityAsync),
    ("Lua hot reload bootstrap", TestLuaHotReloadBootstrapAsync),
    ("Lua bus runtime contracts", TestLuaBusRuntimeContractsAsync),
    ("invalid Boneyard rejection", TestInvalidBoneyardRejectionAsync),
    ("automatic website sync with offline fallback", TestAutomaticWebsiteSyncAsync),
    ("website join URI", TestWebsiteJoinUriAsync),
    ("clean install enables zero mods", TestCleanInstallEnablesZeroModsAsync),
    ("crash capture archive", TestCrashCaptureArchiveAsync),
    ("isolated local save catalog", TestIsolatedLocalSaveCatalogAsync),
    ("cloud save archive integrity", TestCloudSaveArchiveIntegrityAsync),
    ("selected save launch routing", TestSelectedSaveLaunchRoutingAsync),
    ("multiplayer quick-start launch routing", TestMultiplayerQuickStartLaunchRoutingAsync)
};

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
        "Join Game did not enable multiplayer quick start");

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
        var logsRoot = Path.Combine(runtimeRoot, "logs");
        Directory.CreateDirectory(logsRoot);
        var crashLogPath = Path.Combine(logsRoot, "solomondarkmodloader.crash.log");
        var loaderLogPath = Path.Combine(logsRoot, "solomondarkmodloader.log");
        File.WriteAllText(crashLogPath, "unhandled exception code=0xC0000005\n");
        File.WriteAllText(loaderLogPath, "loader attached\n");
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
                LoaderPath = Path.Combine(root, "SolomonDarkModLoader.dll")
            }
        };

        var capture = CrashReportCapture.TryCreate(response, 0, "contract-test")
            ?? throw new InvalidOperationException("native crash artifacts were not detected");
        Require(capture.Metadata.HasCrashLog, "crash log was not recorded in metadata");
        Require(capture.Metadata.MinidumpCount == 1, "minidump was not recorded in metadata");
        Require(capture.Metadata.EnabledMods.Count == 1, "crash report did not isolate enabled mods");

        var archivePath = CrashReportArchiveBuilder.Build(capture);
        try
        {
            using var archive = ZipFile.OpenRead(archivePath);
            var entryNames = archive.Entries.Select(entry => entry.FullName).ToHashSet(StringComparer.Ordinal);
            Require(entryNames.Contains("report.json"), "crash archive is missing report.json");
            Require(entryNames.Contains("logs/crash.log"), "crash archive is missing the crash log");
            Require(entryNames.Contains("logs/loader.log"), "crash archive is missing the loader log");
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
        var installed = await WebsiteModPackageInstaller.InstallAsync(
            client,
            resolved,
            required,
            cacheRoot,
            CancellationToken.None);
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

        var result = await WebsiteModUpdater.UpdateAsync(
            catalog,
            modsRoot,
            cacheRoot,
            client);
        Require(result.Error is null, $"automatic update failed: {result.Error}");
        Require(result.UpdatedModCount == 1, "website update did not replace one mod");
        Require(
            handler.RequestedIds.SequenceEqual(["tests.auto-update"]),
            "website updater requested the wrong installed mod");
        var updated = ModDiscovery.DiscoverRoot(currentRoot);
        Require(updated.Manifest.Version == "1.1.0", "installed manifest version did not advance");
        Require(
            File.ReadAllText(Path.Combine(currentRoot, "files", "update.txt")) == "new",
            "installed mod content did not advance");
        Require(
            !File.Exists(Path.Combine(currentRoot, "user-edit.txt")),
            "old edition files survived package replacement");
        using var offlineClient = new HttpClient(new OfflineDirectoryHandler())
        {
            BaseAddress = new Uri("https://offline.example.test/")
        };
        var reloaded = ModCatalog.CreateExact(
            ModDiscovery.Discover(modsRoot).ToArray());
        var offline = await WebsiteModUpdater.UpdateAsync(
            reloaded,
            modsRoot,
            cacheRoot,
            offlineClient);
        Require(offline.Error is not null, "offline update check did not report its skip reason");
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
        var rejected = await WebsiteModUpdater.UpdateAsync(
            reloaded,
            modsRoot,
            Path.Combine(root, "invalid-cache"),
            invalidClient);
        Require(rejected.Error is not null, "tampered update package was accepted");
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
        var result = await LobbyModSynchronizer.SynchronizeAsync(
            localCatalog,
            42,
            ticket: null,
            cacheRoot,
            client);
        Require(result.UsedWebsite, "available website unexpectedly selected offline fallback");
        Require(result.RequiredModCount == 1, "preflight required count changed");
        Require(result.DownloadedModCount == 1, "missing website mod was not downloaded");
        Require(result.Catalog.EnabledMods.Count == 1, "preflight staged extra local mods");
        Require(result.Catalog.FindById(required.Id) is not null, "required website mod was not selected");
        Require(result.Catalog.FindById("tests.unrelated") is null, "unrelated local mod remained selected");
        Require(handler.JoinManifestRequests == 1, "preflight did not request the join manifest once");
        Require(handler.ResolveRequests == 1, "preflight did not resolve the missing package once");
        Require(handler.DownloadRequests == 1, "preflight did not download the missing package once");

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
        var offlineResult = await LobbyModSynchronizer.SynchronizeAsync(
            manualCatalog,
            42,
            ticket: null,
            Path.Combine(root, "offline-cache"),
            offlineClient);
        Require(!offlineResult.UsedWebsite, "unavailable website did not select offline fallback");
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

        LauncherUpdateInstaller.Install(archivePath, target);
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
    bool rejectResolution = false) : HttpMessageHandler
{
    public int JoinManifestRequests { get; private set; }
    public int ResolveRequests { get; private set; }
    public int DownloadRequests { get; private set; }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var path = request.RequestUri?.AbsolutePath;
        if (request.Method == HttpMethod.Get &&
            path == "/community/api/lobbies/42/join-manifest")
        {
            JoinManifestRequests++;
            return Json(
                $$"""
                {"lobbyId":"42","mods":[{"id":"{{required.Id}}","version":"{{required.Version}}","contentSha256":"{{required.ContentSha256}}"}]}
                """);
        }

        if (request.Method == HttpMethod.Post && path == "/community/api/mods/resolve")
        {
            ResolveRequests++;
            if (rejectResolution)
            {
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.InternalServerError));
            }
            return Json(
                $$"""
                {"mods":[{"id":"{{required.Id}}","version":"{{required.Version}}","contentSha256":"{{required.ContentSha256}}","packageSha256":"{{packageSha256}}","downloadUrl":"api/mods/tests/versions/1/download"}],"missing":[]}
                """);
        }

        if (request.Method == HttpMethod.Get &&
            path == "/community/api/mods/tests/versions/1/download")
        {
            DownloadRequests++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(package)
            });
        }

        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
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

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var path = request.RequestUri?.AbsolutePath;
        if (request.Method == HttpMethod.Post && path == "/community/api/mods/updates")
        {
            var payload = await request.Content!.ReadAsStringAsync(cancellationToken);
            using var document = JsonDocument.Parse(payload);
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
