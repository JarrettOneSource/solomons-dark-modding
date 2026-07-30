namespace SolomonDarkModLauncher.UI.Infrastructure;

/// <summary>
/// One rendered frame of lobby-connect progress: what the launcher should say,
/// how far along the bar sits, and whether the journey is finished or failed.
/// Fractions follow the loader's real session phase ladder
/// (CreatingLobby/JoiningLobby → Handshaking → LobbyReady → Connected →
/// in-hub/in-boneyard) so the bar only reflects observed state, never a timer.
/// </summary>
internal sealed record SessionConnectProgress(
    string Text,
    double Fraction,
    bool IsError,
    bool IsComplete);

internal static class SessionConnectProgressMapper
{
    public const double JoiningLobbyFraction = 0.08;
    public const double PreparingLobbyFraction = 0.11;
    public const double StagingGameFraction = 0.13;
    public const double StartingGameFraction = 0.15;
    public const double SessionBootFraction = 0.22;
    public const double LobbyPhaseFraction = 0.35;
    public const double HandshakeFraction = 0.55;
    public const double LobbyReadyFraction = 0.7;
    public const double ConnectedFraction = 0.85;
    public const double CompleteFraction = 1.0;

    /// <summary>Launcher-side stage: the Steam lobby join has been requested
    /// and no joined/status event has arrived yet.</summary>
    public static SessionConnectProgress JoiningLobby(ulong lobbyId) =>
        new($"Joining lobby {lobbyId}…", JoiningLobbyFraction, false, false);

    /// <summary>Launcher-side stage: the joined lobby is being prepared —
    /// host mod sync and instance staging before launch.</summary>
    public static SessionConnectProgress PreparingLobby() =>
        new(
            "Preparing the lobby — syncing host mods…",
            PreparingLobbyFraction,
            false,
            false);

    /// <summary>Launcher-side stage: the staged instance is being assembled
    /// right before the game process starts.</summary>
    public static SessionConnectProgress StagingGame() =>
        new("Staging the game…", StagingGameFraction, false, false);

    /// <summary>Launcher-side stage: the game process was launched and the
    /// loader has not written a session status yet.</summary>
    public static SessionConnectProgress StartingGame() =>
        new("Starting the game…", StartingGameFraction, false, false);

    public static SessionConnectProgress FromSessionStatus(
        LauncherCliMultiplayerSession status)
    {
        var peerText = DescribePeers(status);
        var ping = status.RoutePingMs > 0 ? $" ({status.RoutePingMs} ms)" : string.Empty;

        switch (status.SessionState)
        {
            case "in-hub":
                return new(
                    $"Connected — in the hub{peerText}.",
                    CompleteFraction,
                    false,
                    true);
            case "in-boneyard":
                return new(
                    $"Connected — match running{peerText}.",
                    CompleteFraction,
                    false,
                    true);
        }

        return status.Phase switch
        {
            "Error" => new(
                string.IsNullOrWhiteSpace(status.ErrorText)
                    ? "The multiplayer session failed."
                    : status.ErrorText,
                ConnectedFraction,
                true,
                false),
            "CreatingLobby" => new(
                "Creating the Steam lobby…",
                LobbyPhaseFraction,
                false,
                false),
            "JoiningLobby" => new(
                "Connecting to the Steam lobby…",
                LobbyPhaseFraction,
                false,
                false),
            "Reconnecting" => new(
                "Connection dropped — reconnecting…",
                HandshakeFraction,
                false,
                false),
            "Handshaking" => new(
                status.IsHost
                    ? "Players are handshaking…"
                    : "Handshaking with the host…",
                HandshakeFraction,
                false,
                false),
            "LobbyReady" => new(
                "Preparing the session…",
                LobbyReadyFraction,
                false,
                false),
            "Connected" => new(
                status.IsHost
                    ? $"Session up — waiting in the hub{peerText}{ping}…"
                    : $"Connected to the host{ping} — loading the world…",
                ConnectedFraction,
                false,
                false),
            "WaitingForInvite" => new(
                "Preparing the Steam session…",
                SessionBootFraction,
                false,
                false),
            _ => new(
                "Starting the multiplayer session…",
                SessionBootFraction,
                false,
                false)
        };
    }

    private static string DescribePeers(LauncherCliMultiplayerSession status)
    {
        if (status.AuthenticatedPeerCount == 0)
        {
            return string.Empty;
        }
        var noun = status.AuthenticatedPeerCount == 1 ? "player" : "players";
        return $" with {status.AuthenticatedPeerCount} other {noun}";
    }
}
