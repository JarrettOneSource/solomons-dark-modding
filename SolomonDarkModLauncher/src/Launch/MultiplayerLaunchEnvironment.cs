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
    public const string LobbyPrivacyVariable = "SDMOD_LOBBY_PRIVACY";
    public const string DirectorySecretVariable = "SDMOD_LOBBY_DIRECTORY_SECRET";
    public const string JoinTicketVariable = "SDMOD_LOBBY_JOIN_TICKET";
    public const string BoneyardIdVariable = "SDMOD_LOBBY_BONEYARD_ID";
    public const string BoneyardNameVariable = "SDMOD_LOBBY_BONEYARD_NAME";
    public const string BoneyardSha256Variable = "SDMOD_LOBBY_BONEYARD_SHA256";
    public const string LobbyPhaseVariable = "SDMOD_LOBBY_PHASE";
    public const string LobbyWaveVariable = "SDMOD_LOBBY_WAVE";
    public const string LobbyDifficultyVariable = "SDMOD_LOBBY_DIFFICULTY";
    public const string LobbyElapsedSecondsVariable = "SDMOD_LOBBY_ELAPSED_SECONDS";
    public const string LobbyStatusTextVariable = "SDMOD_LOBBY_STATUS_TEXT";

    public static LaunchOptions Apply(
        LaunchOptions options,
        MultiplayerLaunchOptions multiplayer,
        string? directorySecret)
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
            environment[DirectorySecretVariable] = string.Empty;
            environment[JoinTicketVariable] = string.Empty;
            return options with { EnvironmentOverrides = environment };
        }

        var isHost = multiplayer.Mode == MultiplayerLaunchMode.Host;
        environment[TransportVariable] = "steam";
        environment[RoleVariable] = isHost ? "host" : "client";
        environment[SessionModeVariable] = isHost ? "host" : "join";
        environment[LobbyIdVariable] = multiplayer.LobbyId?.ToString() ?? string.Empty;
        environment[MaxParticipantsVariable] = multiplayer.MaxParticipants.ToString();
        environment[OpenInviteVariable] = multiplayer.OpenInviteDialog ? "1" : "0";
        environment[InviteSteamIdVariable] = multiplayer.InviteSteamId?.ToString() ?? string.Empty;
        environment[LobbyPrivacyVariable] =
            MultiplayerLobbyPrivacyTokens.ToApiToken(multiplayer.Host.Privacy);
        environment[DirectorySecretVariable] = directorySecret ?? string.Empty;
        environment[JoinTicketVariable] = multiplayer.JoinTicket ?? string.Empty;
        environment[BoneyardIdVariable] = multiplayer.Host.Game.BoneyardId ?? string.Empty;
        environment[BoneyardNameVariable] = multiplayer.Host.Game.BoneyardName ?? string.Empty;
        environment[BoneyardSha256Variable] = multiplayer.Host.Game.BoneyardSha256 ?? string.Empty;
        environment[LobbyPhaseVariable] = multiplayer.Host.Game.Phase;
        environment[LobbyWaveVariable] = multiplayer.Host.Game.Wave?.ToString() ?? string.Empty;
        environment[LobbyDifficultyVariable] = multiplayer.Host.Game.Difficulty ?? string.Empty;
        environment[LobbyElapsedSecondsVariable] =
            multiplayer.Host.Game.ElapsedSeconds?.ToString() ?? string.Empty;
        environment[LobbyStatusTextVariable] = multiplayer.Host.Game.StatusText ?? string.Empty;
        return options with { EnvironmentOverrides = environment };
    }
}
