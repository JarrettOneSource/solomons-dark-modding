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
        string? lobbyPasswordSalt = null;
        string? lobbyPasswordHash = null;
        string? directoryBaseUrl = null;
        string? joinTicket = null;
        string? boneyardId = null;
        string? boneyardName = null;
        string? boneyardSha256 = null;
        var lobbyPhase = "hub";
        int? lobbyWave = null;
        string? lobbyDifficulty = null;
        int? lobbyElapsedSeconds = null;
        string? lobbyStatusText = null;

        for (var index = 0; index < args.Length; index++)
        {
            var arg = args[index];
            if (arg is "--help" or "-h" or "/?")
            {
                showHelp = true;
                continue;
            }

            if (arg is "launch" or "stage" or "list-mods")
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

            if (arg == "--lobby-password-salt")
            {
                lobbyPasswordSalt = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--lobby-password-hash")
            {
                lobbyPasswordHash = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--directory-url")
            {
                directoryBaseUrl = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--join-ticket")
            {
                joinTicket = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--boneyard-id")
            {
                boneyardId = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--boneyard-name")
            {
                boneyardName = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--boneyard-sha256")
            {
                boneyardSha256 = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--lobby-phase")
            {
                lobbyPhase = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--lobby-wave")
            {
                lobbyWave = ParseInt(ReadValue(args, ref index, arg), arg);
                continue;
            }

            if (arg == "--lobby-difficulty")
            {
                lobbyDifficulty = ReadValue(args, ref index, arg);
                continue;
            }

            if (arg == "--lobby-elapsed-seconds")
            {
                lobbyElapsedSeconds = ParseInt(ReadValue(args, ref index, arg), arg);
                continue;
            }

            if (arg == "--lobby-status-text")
            {
                lobbyStatusText = ReadValue(args, ref index, arg);
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

        var host = LobbyHostOptions.Create(
            lobbyPrivacy,
            directoryBaseUrl,
            lobbyPasswordSalt,
            lobbyPasswordHash,
            boneyardId,
            boneyardName,
            boneyardSha256,
            lobbyPhase,
            lobbyWave,
            lobbyDifficulty,
            lobbyElapsedSeconds,
            lobbyStatusText);
        var multiplayer = MultiplayerLaunchOptions.Create(
            multiplayerMode,
            steamLobbyId,
            inviteSteamId,
            multiplayerMaxParticipants,
            openSteamInviteDialog,
            host,
            joinTicket);

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
            multiplayer);
    }

    private static LauncherMode ParseMode(string value)
    {
        return value switch
        {
            "launch" => LauncherMode.Launch,
            "stage" => LauncherMode.Stage,
            "list-mods" => LauncherMode.ListMods,
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
                $"Steam invite user id must be a positive unsigned integer: {value}");
    }

    private static int ParseMaxParticipants(string value)
    {
        return int.TryParse(value, out var count) &&
               count is >= 2 and <= MultiplayerLaunchOptions.MaximumSupportedParticipants
            ? count
            : throw new InvalidOperationException(
                $"--max-players must be between 2 and {MultiplayerLaunchOptions.MaximumSupportedParticipants}: {value}");
    }

    private static int ParseInt(string value, string optionName)
    {
        return int.TryParse(value, out var parsed)
            ? parsed
            : throw new InvalidOperationException($"{optionName} requires an integer: {value}");
    }
}
