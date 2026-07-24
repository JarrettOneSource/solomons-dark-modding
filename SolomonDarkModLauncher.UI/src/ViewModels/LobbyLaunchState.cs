namespace SolomonDarkModLauncher.UI.ViewModels;

internal enum LobbyPrimaryAction
{
    JoinLobby,
    LaunchGame
}

internal sealed class LobbyLaunchState
{
    public ulong? JoinedLobbyId { get; private set; }

    public string PrimaryButtonText =>
        JoinedLobbyId.HasValue ? "Launch Game" : "Join Game";

    public LobbyPrimaryAction PrimaryAction =>
        JoinedLobbyId.HasValue
            ? LobbyPrimaryAction.LaunchGame
            : LobbyPrimaryAction.JoinLobby;

    public void MarkJoined(ulong lobbyId)
    {
        if (lobbyId == 0)
        {
            throw new ArgumentOutOfRangeException(nameof(lobbyId));
        }

        JoinedLobbyId = lobbyId;
    }

    public void Reset()
    {
        JoinedLobbyId = null;
    }
}
