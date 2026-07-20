using SolomonDarkModLauncher.Workspace;
using SolomonDarkModLauncher.Launch;

namespace SolomonDarkModLauncher.Commands;

internal static class LauncherCommandParser
{
    public static LauncherCommand Parse(string[] args)
    {
        var mode = LauncherMode.Launch;
        var showHelp = false;
        var jsonOutput = false;
        string? instanceName = null;
        string? targetModId = null;
        string? gameDir = null;
        string? modsRoot = null;
        string? runtimeRoot = null;
        string? stageRoot = null;
        string? runtimeProfile = null;
        var runtimeFlagOverrides = new List<string>();
        var temporaryProfile = false;
        string? steamAppId = null;
        string? steamApiDll = null;
        var multiplayerMode = MultiplayerLaunchMode.Unspecified;
        ulong? steamLobbyId = null;
        ulong? inviteSteamId = null;
        var multiplayerMaxParticipants = MultiplayerLaunchOptions.DefaultMaxParticipants;
        var openSteamInviteDialog = true;
        var lobbyPrivacy = MultiplayerLobbyPrivacy.FriendsOnly;
        string? directoryBaseUrl = null;

        for (var index = 0; index < args.Length; index++)
        {
            var arg = args[index];
            if (arg is "--help" or "-h" or "/?")
            {
                showHelp = true;
                continue;
            }

            if (arg is "launch" or "stage" or "list-mods" or "directory-auth")
            {
                mode = ParseMode(arg);
                continue;
            }

            if (arg == "--json")
            {
                jsonOutput = true;
                continue;
            }

            if (arg is "enable-mod" or "disable-mod")
            {
                mode = ParseMode(arg);
                targetModId = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--game-dir")
            {
                gameDir = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--instance")
            {
                instanceName = LauncherInstance.Normalize(ReadValue(args, ref index, arg));
                continue;
            }

            if (arg == "--mods-root")
            {
                modsRoot = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--stage-root")
            {
                stageRoot = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--runtime-root")
            {
                runtimeRoot = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--runtime-profile")
            {
                runtimeProfile = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--runtime-flag")
            {
                runtimeFlagOverrides.Add(ReadValue(args, ref index, arg));
                continue;
            }

            if (arg == "--temporary-profile")
            {
                temporaryProfile = true;
                continue;
            }

            if (arg == "--steam-appid")
            {
                steamAppId = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--steam-api-dll")
            {
                steamApiDll = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--multiplayer")
            {
                multiplayerMode = ParseMultiplayerMode(ReadValue(args, ref index, arg));
                continue;
            }

            if (arg == "--lobby-id")
            {
                steamLobbyId = ParseLobbyId(ReadValue(args, ref index, arg));
                continue;
            }

            if (arg == "--max-players")
            {
                multiplayerMaxParticipants = ParseMaxParticipants(
                    ReadValue(args, ref index, arg));
                continue;
            }

            if (arg == "--lobby-privacy")
            {
                lobbyPrivacy = MultiplayerLobbyPrivacyTokens.Parse(
                    ReadValue(args, ref index, arg));
                continue;
            }

            if (arg == "--directory-url")
            {
                directoryBaseUrl = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--invite-steam-id")
            {
                inviteSteamId = ParseSteamId(ReadValue(args, ref index, arg));
                continue;
            }

            if (arg == "--no-invite-dialog")
            {
                openSteamInviteDialog = false;
                continue;
            }

            throw new InvalidOperationException($"Unknown argument: {arg}");
        }

        var lobbyHost = LobbyHostOptions.Create(lobbyPrivacy, directoryBaseUrl);
        var multiplayer = MultiplayerLaunchOptions.Create(
            multiplayerMode,
            steamLobbyId,
            inviteSteamId,
            multiplayerMaxParticipants,
            openSteamInviteDialog,
            lobbyHost);

        return new LauncherCommand(
            mode,
            showHelp,
            jsonOutput,
            instanceName,
            gameDir,
            modsRoot,
            runtimeRoot,
            stageRoot,
            targetModId,
            runtimeProfile,
            runtimeFlagOverrides,
            temporaryProfile,
            steamAppId,
            steamApiDll,
            multiplayer.Mode,
            multiplayer.LobbyId,
            multiplayer.InviteSteamId,
            multiplayer.MaxParticipants,
            multiplayer.OpenInviteDialog,
            multiplayer.Host);
    }

    private static LauncherMode ParseMode(string value)
    {
        return value switch
        {
            "launch" => LauncherMode.Launch,
            "stage" => LauncherMode.Stage,
            "list-mods" => LauncherMode.ListMods,
            "directory-auth" => LauncherMode.AuthenticateDirectory,
            "enable-mod" => LauncherMode.EnableMod,
            "disable-mod" => LauncherMode.DisableMod,
            _ => throw new InvalidOperationException($"Unsupported mode: {value}")
        };
    }

    private static string ReadValue(string[] args, ref int index, string optionName)
    {
        if (index + 1 >= args.Length)
        {
            throw new InvalidOperationException($"Missing value for {optionName}");
        }

        index++;
        return args[index];
    }

    private static MultiplayerLaunchMode ParseMultiplayerMode(string value)
    {
        return value.ToLowerInvariant() switch
        {
            "off" => MultiplayerLaunchMode.Off,
            "host" => MultiplayerLaunchMode.Host,
            "join" => MultiplayerLaunchMode.Join,
            _ => throw new InvalidOperationException(
                $"Unsupported multiplayer mode '{value}'. Expected off, host, or join.")
        };
    }

    private static ulong ParseLobbyId(string value)
    {
        return ulong.TryParse(value, out var lobbyId) && lobbyId != 0
            ? lobbyId
            : throw new InvalidOperationException(
                $"Steam lobby id must be a positive unsigned integer: {value}");
    }

    private static ulong ParseSteamId(string value)
    {
        return ulong.TryParse(value, out var steamId) && steamId != 0
            ? steamId
            : throw new InvalidOperationException(
                $"Steam user ID must be a positive unsigned integer: {value}");
    }

    private static int ParseMaxParticipants(string value)
    {
        return int.TryParse(value, out var count) &&
               count is >= 2 and <= MultiplayerLaunchOptions.MaximumSupportedParticipants
            ? count
            : throw new InvalidOperationException(
                $"--max-players must be between 2 and {MultiplayerLaunchOptions.MaximumSupportedParticipants}: {value}");
    }
}
