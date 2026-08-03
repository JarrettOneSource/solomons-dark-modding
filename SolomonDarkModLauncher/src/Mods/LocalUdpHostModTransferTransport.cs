using System.Net;
using System.Net.Sockets;

namespace SolomonDarkModLauncher.Mods;

internal sealed class LocalUdpHostModTransferTransport : IHostModTransferTransport
{
    private const string LocalPortVariable = "SDMOD_MULTIPLAYER_LOCAL_PORT";
    private const string RemoteHostVariable = "SDMOD_MULTIPLAYER_REMOTE_HOST";
    private const string RemotePortVariable = "SDMOD_MULTIPLAYER_REMOTE_PORT";
    private const int DefaultClientPort = 47771;
    private const int DefaultHostPort = 47770;
    private readonly Socket socket_;

    private LocalUdpHostModTransferTransport(Socket socket)
    {
        socket_ = socket;
    }

    public ulong LobbyId => 0;

    public static async Task<LocalUdpHostModTransferTransport> ConnectAsync(
        CancellationToken cancellationToken)
    {
        var localPort = ReadPort(LocalPortVariable, DefaultClientPort);
        var remotePort = ReadPort(RemotePortVariable, DefaultHostPort);
        var remoteHost = Environment.GetEnvironmentVariable(RemoteHostVariable);
        if (string.IsNullOrWhiteSpace(remoteHost))
        {
            remoteHost = "127.0.0.1";
        }
        var addresses = await Dns.GetHostAddressesAsync(remoteHost, cancellationToken);
        var remoteAddress = addresses.FirstOrDefault(address =>
            address.AddressFamily == AddressFamily.InterNetwork)
            ?? throw new InvalidOperationException(
                $"The local multiplayer host is not an IPv4 endpoint: {remoteHost}");
        var bindAddress = IPAddress.IsLoopback(remoteAddress)
            ? IPAddress.Loopback
            : IPAddress.Any;
        var socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp)
        {
            ReceiveBufferSize = 256 * 1024,
            SendBufferSize = 256 * 1024
        };
        try
        {
            socket.Bind(new IPEndPoint(bindAddress, localPort));
            await socket.ConnectAsync(
                new IPEndPoint(remoteAddress, remotePort),
                cancellationToken);
            return new LocalUdpHostModTransferTransport(socket);
        }
        catch
        {
            socket.Dispose();
            throw;
        }
    }

    public async ValueTask SendAsync(
        ReadOnlyMemory<byte> packet,
        CancellationToken cancellationToken)
    {
        var sent = await socket_.SendAsync(packet, SocketFlags.None, cancellationToken);
        if (sent != packet.Length)
        {
            throw new IOException("The local mod transfer packet was only partially sent.");
        }
    }

    public async ValueTask<byte[]> ReceiveAsync(CancellationToken cancellationToken)
    {
        var buffer = new byte[1200];
        var received = await socket_.ReceiveAsync(
            buffer,
            SocketFlags.None,
            cancellationToken);
        if (received < 12)
        {
            throw new InvalidDataException("The local host returned a truncated mod transfer packet.");
        }
        return buffer[..received];
    }

    public ValueTask DisposeAsync()
    {
        socket_.Dispose();
        return ValueTask.CompletedTask;
    }

    private static int ReadPort(string variable, int fallback)
    {
        var value = Environment.GetEnvironmentVariable(variable);
        if (string.IsNullOrWhiteSpace(value))
        {
            return fallback;
        }
        return int.TryParse(value, out var port) && port is >= 1 and <= 65535
            ? port
            : throw new InvalidOperationException(
                $"{variable} must be a valid UDP port.");
    }
}
