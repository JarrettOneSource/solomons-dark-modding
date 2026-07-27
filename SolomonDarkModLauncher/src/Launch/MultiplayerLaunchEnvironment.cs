namespace SolomonDarkModLauncher.Launch;

internal static class MultiplayerLaunchEnvironment
{
    public const string TransportVariable = "SDMOD_MULTIPLAYER_TRANSPORT";
    public const string RoleVariable = "SDMOD_MULTIPLAYER_ROLE";
    public const string SessionModeVariable = "SDMOD_STEAM_SESSION_MODE";
    public const string LobbyIdVariable = "SDMOD_STEAM_LOBBY_ID";
    public const string MaxParticipantsVariable = "SDMOD_MULTIPLAYER_MAX_PARTICIPANTS";
    public const string OpenInviteVariable = "SDMOD_STEAM_OPEN_INVITE";
    public const string InviteSteamIdVariable = "SDMOD_STEAM_INVITE_STEAM_ID";
    public const string LobbyPrivacyVariable = "SDMOD_STEAM_LOBBY_PRIVACY";
    public const string QuickStartVariable = "SDMOD_MULTIPLAYER_QUICK_START";
    public const string LocalTransportToken = "local_udp";

    public static bool IsLocalTransport(LaunchOptions options) =>
        options.EnvironmentOverrides is not null &&
        options.EnvironmentOverrides.TryGetValue(
            TransportVariable,
            out var transport) &&
        string.Equals(
            transport,
            LocalTransportToken,
            StringComparison.OrdinalIgnoreCase);

    public static bool IsLocalTransportRequested() =>
        string.Equals(
            Environment.GetEnvironmentVariable(TransportVariable),
            LocalTransportToken,
            StringComparison.OrdinalIgnoreCase);

    public static LaunchOptions Apply(
        LaunchOptions options,
        MultiplayerLaunchOptions multiplayer)
    {
        if (multiplayer.Mode == MultiplayerLaunchMode.Unspecified)
        {
            return options;
        }

        var environment = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (options.EnvironmentOverrides is not null)
        {
            foreach (var pair in options.EnvironmentOverrides)
            {
                environment[pair.Key] = pair.Value;
            }
        }

        if (multiplayer.Mode == MultiplayerLaunchMode.Off)
        {
            environment[TransportVariable] = "none";
            environment[RoleVariable] = string.Empty;
            environment[SessionModeVariable] = string.Empty;
            environment[LobbyIdVariable] = string.Empty;
            environment[InviteSteamIdVariable] = string.Empty;
            environment[LobbyPrivacyVariable] = string.Empty;
            environment[QuickStartVariable] = string.Empty;
            return options with { EnvironmentOverrides = environment };
        }

        var isHost = multiplayer.Mode == MultiplayerLaunchMode.Host;
        if (IsLocalTransport(options))
        {
            environment[RoleVariable] = isHost ? "host" : "client";
            environment[SessionModeVariable] = string.Empty;
            environment[LobbyIdVariable] =
                multiplayer.LobbyId?.ToString() ?? string.Empty;
            environment[MaxParticipantsVariable] =
                multiplayer.MaxParticipants.ToString();
            environment[QuickStartVariable] = "1";
            return options with { EnvironmentOverrides = environment };
        }

        environment[TransportVariable] = "steam";
        environment[RoleVariable] = isHost ? "host" : "client";
        environment[SessionModeVariable] = isHost ? "host" : "join";
        environment[LobbyIdVariable] = multiplayer.LobbyId?.ToString() ?? string.Empty;
        environment[MaxParticipantsVariable] = multiplayer.MaxParticipants.ToString();
        environment[OpenInviteVariable] = multiplayer.OpenInviteDialog ? "1" : "0";
        environment[InviteSteamIdVariable] = multiplayer.InviteSteamId?.ToString() ?? string.Empty;
        environment[LobbyPrivacyVariable] =
            MultiplayerLobbyPrivacyTokens.ToLauncherToken(multiplayer.Host.Privacy);
        environment[QuickStartVariable] = "1";
        return options with { EnvironmentOverrides = environment };
    }
}
