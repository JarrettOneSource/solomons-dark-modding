namespace SolomonDarkModLauncher.Launch;

internal sealed record MultiplayerLaunchOptions(
    MultiplayerLaunchMode Mode,
    ulong? LobbyId,
    ulong? InviteSteamId,
    int MaxParticipants,
    bool OpenInviteDialog,
    LobbyHostOptions Host,
    string? JoinTicket)
{
    public const int DefaultMaxParticipants = 4;
    public const int MaximumSupportedParticipants = 4;

    public static MultiplayerLaunchOptions Create(
        MultiplayerLaunchMode mode,
        ulong? lobbyId,
        ulong? inviteSteamId,
        int maxParticipants,
        bool openInviteDialog,
        LobbyHostOptions host,
        string? joinTicket)
    {
        if (maxParticipants is < 2 or > MaximumSupportedParticipants)
        {
            throw new InvalidOperationException(
                $"Multiplayer supports 2-{MaximumSupportedParticipants} players.");
        }

        if (lobbyId is not null && lobbyId == 0)
        {
            throw new InvalidOperationException("Steam lobby id must be greater than zero.");
        }

        if (lobbyId is not null && mode != MultiplayerLaunchMode.Join)
        {
            throw new InvalidOperationException("--lobby-id requires --multiplayer join.");
        }

        if (inviteSteamId is not null && inviteSteamId == 0)
        {
            throw new InvalidOperationException("Steam invite user id must be greater than zero.");
        }

        if (inviteSteamId is not null && mode != MultiplayerLaunchMode.Host)
        {
            throw new InvalidOperationException(
                "--invite-steam-id requires --multiplayer host.");
        }

        if (!openInviteDialog && mode != MultiplayerLaunchMode.Host)
        {
            throw new InvalidOperationException(
                "--no-invite-dialog requires --multiplayer host.");
        }

        joinTicket = string.IsNullOrWhiteSpace(joinTicket) ? null : joinTicket.Trim();
        if (joinTicket is not null &&
            (mode != MultiplayerLaunchMode.Join || lobbyId is null))
        {
            throw new InvalidOperationException(
                "--join-ticket requires --multiplayer join and --lobby-id.");
        }

        if (joinTicket is { Length: > 159 } ||
            (joinTicket is not null && joinTicket.Any(character =>
                !(char.IsAsciiLetterOrDigit(character) || character is '.' or '-' or '_'))))
        {
            throw new InvalidOperationException("The lobby join ticket is malformed.");
        }

        return new MultiplayerLaunchOptions(
            mode,
            lobbyId,
            inviteSteamId,
            maxParticipants,
            openInviteDialog,
            host,
            joinTicket);
    }
}
