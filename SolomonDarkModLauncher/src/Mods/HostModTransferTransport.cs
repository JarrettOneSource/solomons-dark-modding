using SolomonDarkModLauncher.Launch;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.Steam;
using SolomonDarkModLauncher.Target;

namespace SolomonDarkModLauncher.Mods;

internal interface IHostModTransferTransport : IAsyncDisposable
{
    ulong LobbyId { get; }
    ValueTask SendAsync(ReadOnlyMemory<byte> packet, CancellationToken cancellationToken);
    ValueTask<byte[]> ReceiveAsync(CancellationToken cancellationToken);
}

internal static class HostModTransferTransportFactory
{
    public static async Task<IHostModTransferTransport> ConnectAsync(
        LauncherConfiguration configuration,
        ulong lobbyId,
        CancellationToken cancellationToken)
    {
        if (MultiplayerLaunchEnvironment.IsLocalTransportRequested())
        {
            return await LocalUdpHostModTransferTransport.ConnectAsync(cancellationToken);
        }

        var steamApiPath = SteamBootstrapMaterializer.ResolveSteamApiSourcePath(
            configuration.Steam)
            ?? throw new InvalidOperationException(
                "Direct host mod transfer over Steam needs the packaged x86 steam_api.dll.");
        return await SteamHostModTransferTransport.ConnectAsync(
            steamApiPath,
            configuration.Steam.AppId,
            lobbyId,
            cancellationToken);
    }
}
