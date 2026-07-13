namespace SolomonDarkModLauncher.Launch;

internal sealed record MultiplayerLaunchOptions(
    MultiplayerLaunchMode Mode,
    ulong? LobbyId,
    int MaxParticipants,
    bool OpenInviteDialog)
{
    public const int DefaultMaxParticipants = 4;
    public const int MaximumSupportedParticipants = 4;

    public static MultiplayerLaunchOptions Create(
        MultiplayerLaunchMode mode,
        ulong? lobbyId,
        int maxParticipants,
        bool openInviteDialog)
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

        if (!openInviteDialog && mode != MultiplayerLaunchMode.Host)
        {
            throw new InvalidOperationException(
                "--no-invite-dialog requires --multiplayer host.");
        }

        return new MultiplayerLaunchOptions(
            mode,
            lobbyId,
            maxParticipants,
            openInviteDialog);
    }
}
