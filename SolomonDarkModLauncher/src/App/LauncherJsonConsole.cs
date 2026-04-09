using System.Text.Json;
using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Staging;

namespace SolomonDarkModLauncher.App;

internal static class LauncherJsonConsole
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    public static void PrintExecution(LauncherCommandExecution execution)
    {
        var runtimeFlags = RuntimeStageFlags.Create(execution.Configuration.Runtime);

        var response = new LauncherJsonResponse
        {
            Success = true,
            Mode = GetModeToken(execution.Command.Mode),
            Transcript = LauncherOutputFormatter.FormatExecution(execution),
            Error = null,
            Configuration = new LauncherJsonConfiguration
            {
                WorkspaceRoot = execution.Configuration.Workspace.RootPath,
                Instance = execution.Configuration.Workspace.InstanceName,
                GameDirectory = execution.Configuration.Game.InstallDirectory,
                ConfigRoot = execution.Configuration.Workspace.ConfigRootPath,
                ModsRoot = execution.Configuration.Workspace.ModsRootPath,
                ModStatePath = execution.Configuration.Workspace.ModStatePath,
                StageRoot = execution.Configuration.Workspace.StageRootPath,
                ProfileRoot = execution.Configuration.Workspace.ProfileRootPath,
                IsolatedGameAppDataPath = execution.Configuration.Workspace.IsolatedGameAppDataPath,
                RuntimeProfile = SolomonDarkModLauncher.Staging.RuntimeStageFlags.ToProfileName(execution.Configuration.Runtime.Profile),
                HasRuntimeFlagOverrides = execution.Configuration.Runtime.HasOverrides,
                LoaderDebugUi = runtimeFlags.LoaderDebugUi,
                SteamAppId = execution.Configuration.Steam.AppId,
                SteamApiOverride = execution.Configuration.Steam.ApiDllOverridePath
            },
            Mods = execution.Catalog.DiscoveredMods.Select(
                mod => new LauncherJsonMod
                {
                    Id = mod.Manifest.Id,
                    Name = mod.Manifest.Name,
                    Version = mod.Manifest.Version,
                    Priority = mod.Manifest.Priority,
                    RuntimeKind = mod.Manifest.RuntimeKind,
                    OverlayCount = mod.Manifest.Overlays.Count,
                    RequiredMods = mod.Manifest.RequiredMods.ToArray(),
                    RootPath = mod.RootPath,
                    ManifestPath = mod.ManifestPath,
                    Enabled = execution.Catalog.IsEnabled(mod)
                }).ToArray(),
            Stage = execution.StageResult is null
                ? null
                : new LauncherJsonStage
                {
                    StageRoot = execution.StageResult.StageRootPath,
                    StageExecutablePath = execution.StageResult.StageExecutablePath,
                    StageReportPath = execution.StageResult.StageReportPath,
                    StageConfigRootPath = execution.StageResult.StageConfigRootPath,
                    StageBinaryLayoutPath = execution.StageResult.StageBinaryLayoutPath,
                    StageDebugUiConfigPath = execution.StageResult.StageDebugUiConfigPath,
                    StageRuntimeRootPath = execution.StageResult.StageRuntimeRootPath,
                    StageRuntimeBootstrapPath = execution.StageResult.StageRuntimeBootstrapPath,
                    StageRuntimeFlagsPath = execution.StageResult.StageRuntimeFlagsPath,
                    EnabledModCount = execution.StageResult.EnabledModCount,
                    AppliedOverlayCount = execution.StageResult.AppliedOverlayCount
                },
            Launch = execution.LaunchedGame is null
                ? null
                : new LauncherJsonLaunch
                {
                    ProcessId = execution.LaunchedGame.ProcessId,
                    LoaderPath = execution.LaunchedGame.LoaderPath,
                    StartupCode = execution.LaunchedGame.StartupStatus.Code,
                    StartupMessage = execution.LaunchedGame.StartupStatus.Message,
                    StartupLogPath = execution.LaunchedGame.StartupStatus.LogPath
                },
            ModStateChange = execution.ModStateChange is null
                ? null
                : new LauncherJsonModStateChange
                {
                    ModId = execution.ModStateChange.ModId,
                    Enabled = execution.ModStateChange.Enabled,
                    StatePath = execution.ModStateChange.StatePath
                }
        };

        Console.WriteLine(JsonSerializer.Serialize(response, JsonOptions));
    }

    public static void PrintError(Exception ex)
    {
        var response = new LauncherJsonResponse
        {
            Success = false,
            Mode = null,
            Transcript = null,
            Error = ex.Message,
            Configuration = null,
            Mods = [],
            Stage = null,
            Launch = null,
            ModStateChange = null
        };

        Console.Error.WriteLine(JsonSerializer.Serialize(response, JsonOptions));
    }

    private static string GetModeToken(LauncherMode mode)
    {
        return mode switch
        {
            LauncherMode.Launch => "launch",
            LauncherMode.Stage => "stage",
            LauncherMode.ListMods => "list-mods",
            LauncherMode.EnableMod => "enable-mod",
            LauncherMode.DisableMod => "disable-mod",
            _ => throw new InvalidOperationException($"Unsupported mode: {mode}")
        };
    }

    private sealed class LauncherJsonResponse
    {
        public required bool Success { get; init; }
        public required string? Mode { get; init; }
        public required string? Transcript { get; init; }
        public required string? Error { get; init; }
        public required LauncherJsonConfiguration? Configuration { get; init; }
        public required IReadOnlyList<LauncherJsonMod> Mods { get; init; }
        public required LauncherJsonStage? Stage { get; init; }
        public required LauncherJsonLaunch? Launch { get; init; }
        public required LauncherJsonModStateChange? ModStateChange { get; init; }
    }

    private sealed class LauncherJsonConfiguration
    {
        public required string WorkspaceRoot { get; init; }
        public required string Instance { get; init; }
        public required string GameDirectory { get; init; }
        public required string ConfigRoot { get; init; }
        public required string ModsRoot { get; init; }
        public required string ModStatePath { get; init; }
        public required string StageRoot { get; init; }
        public required string ProfileRoot { get; init; }
        public required string IsolatedGameAppDataPath { get; init; }
        public required string RuntimeProfile { get; init; }
        public required bool HasRuntimeFlagOverrides { get; init; }
        public required bool LoaderDebugUi { get; init; }
        public required string SteamAppId { get; init; }
        public required string? SteamApiOverride { get; init; }
    }

    private sealed class LauncherJsonMod
    {
        public required string Id { get; init; }
        public required string Name { get; init; }
        public required string Version { get; init; }
        public required int Priority { get; init; }
        public required string RuntimeKind { get; init; }
        public required int OverlayCount { get; init; }
        public required IReadOnlyList<string> RequiredMods { get; init; }
        public required string RootPath { get; init; }
        public required string ManifestPath { get; init; }
        public required bool Enabled { get; init; }
    }

    private sealed class LauncherJsonStage
    {
        public required string StageRoot { get; init; }
        public required string StageExecutablePath { get; init; }
        public required string StageReportPath { get; init; }
        public required string StageConfigRootPath { get; init; }
        public required string StageBinaryLayoutPath { get; init; }
        public required string StageDebugUiConfigPath { get; init; }
        public required string StageRuntimeRootPath { get; init; }
        public required string StageRuntimeBootstrapPath { get; init; }
        public required string StageRuntimeFlagsPath { get; init; }
        public required int EnabledModCount { get; init; }
        public required int AppliedOverlayCount { get; init; }
    }

    private sealed class LauncherJsonLaunch
    {
        public required int ProcessId { get; init; }
        public required string LoaderPath { get; init; }
        public required string StartupCode { get; init; }
        public required string StartupMessage { get; init; }
        public required string? StartupLogPath { get; init; }
    }

    private sealed class LauncherJsonModStateChange
    {
        public required string ModId { get; init; }
        public required bool Enabled { get; init; }
        public required string StatePath { get; init; }
    }
}
