using System.Runtime.InteropServices;
using SolomonDarkModLauncher.Steam;

namespace SolomonDarkModLauncher.Mods;

internal sealed class SteamHostModTransferTransport : IHostModTransferTransport
{
    private const int LobbyEnterCallbackId = 504;
    private const int SteamApiCallCompletedCallbackId = 703;
    private const int NetworkingSessionRequestCallbackId = 1251;
    private const uint LobbyEnterSuccess = 1;
    private const int ReliableNoNagle = 9;
    private const int SessionBulkChannel = 0;
    private const int MaximumMessageBytes = 1200;
    private readonly SteamManualDispatchSession dispatch_;
    private readonly SteamLobbyApi lobby_;
    private readonly SteamNetworkingApi networking_;
    private readonly ulong hostSteamId_;
    private bool disposed_;

    private SteamHostModTransferTransport(
        SteamManualDispatchSession dispatch,
        SteamLobbyApi lobby,
        SteamNetworkingApi networking,
        ulong lobbyId,
        ulong hostSteamId)
    {
        dispatch_ = dispatch;
        lobby_ = lobby;
        networking_ = networking;
        LobbyId = lobbyId;
        hostSteamId_ = hostSteamId;
    }

    public ulong LobbyId { get; }

    public static async Task<SteamHostModTransferTransport> ConnectAsync(
        string steamApiPath,
        string appId,
        ulong lobbyId,
        CancellationToken cancellationToken)
    {
        if (lobbyId == 0)
        {
            throw new ArgumentOutOfRangeException(nameof(lobbyId));
        }
        var dispatch = new SteamManualDispatchSession(steamApiPath, appId);
        try
        {
            var lobby = new SteamLobbyApi(dispatch);
            var joinCall = lobby.Join(lobbyId);
            if (joinCall == 0)
            {
                throw new InvalidOperationException(
                    "Steam rejected the transfer lobby join before it was sent.");
            }
            var deadline = DateTime.UtcNow.AddSeconds(30);
            while (DateTime.UtcNow < deadline)
            {
                uint? response = null;
                dispatch.RunCallbacks(callback =>
                {
                    if (TryReadLobbyEnterResult(
                            dispatch,
                            callback,
                            joinCall,
                            lobbyId,
                            out var result))
                    {
                        response = result;
                    }
                });
                if (response is { } lobbyResponse)
                {
                    if (lobbyResponse != LobbyEnterSuccess)
                    {
                        throw new InvalidOperationException(
                            $"Steam could not join the host mod transfer lobby (response {lobbyResponse}).");
                    }
                    var hostSteamId = lobby.GetOwner(lobbyId);
                    if (hostSteamId == 0 || hostSteamId == lobby.LocalSteamId)
                    {
                        throw new InvalidOperationException(
                            "The host left before direct mod transfer started.");
                    }
                    return new SteamHostModTransferTransport(
                        dispatch,
                        lobby,
                        new SteamNetworkingApi(dispatch),
                        lobbyId,
                        hostSteamId);
                }
                await Task.Delay(25, cancellationToken);
            }
            throw new TimeoutException(
                "Steam did not join the host mod transfer lobby within 30 seconds.");
        }
        catch
        {
            dispatch.Dispose();
            throw;
        }
    }

    public ValueTask SendAsync(
        ReadOnlyMemory<byte> packet,
        CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(disposed_, this);
        cancellationToken.ThrowIfCancellationRequested();
        PumpCallbacks();
        networking_.Send(hostSteamId_, packet.Span);
        return ValueTask.CompletedTask;
    }

    public async ValueTask<byte[]> ReceiveAsync(CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(disposed_, this);
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            PumpCallbacks();
            var packet = networking_.TryReceive(hostSteamId_);
            if (packet is not null)
            {
                return packet;
            }
            await Task.Delay(10, cancellationToken);
        }
    }

    public ValueTask DisposeAsync()
    {
        if (disposed_)
        {
            return ValueTask.CompletedTask;
        }
        disposed_ = true;
        try
        {
            networking_.Close(hostSteamId_);
            lobby_.Leave(LobbyId);
        }
        finally
        {
            dispatch_.Dispose();
        }
        return ValueTask.CompletedTask;
    }

    private void PumpCallbacks()
    {
        dispatch_.RunCallbacks(callback =>
        {
            if (callback.CallbackId != NetworkingSessionRequestCallbackId ||
                callback.Parameter == 0 ||
                callback.ParameterSize < SteamNetworkingIdentity.Size)
            {
                return;
            }
            var remoteSteamId = networking_.GetSteamId(callback.Parameter);
            if (remoteSteamId == hostSteamId_)
            {
                networking_.Accept(hostSteamId_);
            }
        });
    }

    private static bool TryReadLobbyEnterResult(
        SteamManualDispatchSession dispatch,
        SteamCallbackMessage callback,
        ulong expectedApiCall,
        ulong expectedLobbyId,
        out uint response)
    {
        response = 0;
        if (callback.Parameter == 0)
        {
            return false;
        }
        if (callback.CallbackId == LobbyEnterCallbackId &&
            callback.ParameterSize >= 20 &&
            unchecked((ulong)Marshal.ReadInt64(callback.Parameter, 0)) == expectedLobbyId)
        {
            response = unchecked((uint)Marshal.ReadInt32(callback.Parameter, 16));
            return true;
        }
        if (callback.CallbackId != SteamApiCallCompletedCallbackId ||
            callback.ParameterSize < 16 ||
            unchecked((ulong)Marshal.ReadInt64(callback.Parameter, 0)) != expectedApiCall)
        {
            return false;
        }
        var completedCallbackId = Marshal.ReadInt32(callback.Parameter, 8);
        var parameterSize = Marshal.ReadInt32(callback.Parameter, 12);
        if (completedCallbackId != LobbyEnterCallbackId || parameterSize < 20 ||
            !dispatch.TryGetApiCallResult(
                expectedApiCall,
                completedCallbackId,
                parameterSize,
                out var result) ||
            BitConverter.ToUInt64(result, 0) != expectedLobbyId)
        {
            return false;
        }
        response = BitConverter.ToUInt32(result, 16);
        return true;
    }

    private sealed class SteamLobbyApi
    {
        private readonly nint matchmaking_;
        private readonly SteamJoinLobby join_;
        private readonly SteamLeaveLobby leave_;
        private readonly SteamGetLobbyOwner getOwner_;

        public SteamLobbyApi(SteamManualDispatchSession dispatch)
        {
            matchmaking_ = dispatch.GetInterface("SteamAPI_SteamMatchmaking_v009");
            var user = dispatch.GetInterface("SteamAPI_SteamUser_v023");
            join_ = dispatch.Load<SteamJoinLobby>(
                "SteamAPI_ISteamMatchmaking_JoinLobby");
            leave_ = dispatch.Load<SteamLeaveLobby>(
                "SteamAPI_ISteamMatchmaking_LeaveLobby");
            getOwner_ = dispatch.Load<SteamGetLobbyOwner>(
                "SteamAPI_ISteamMatchmaking_GetLobbyOwner");
            var getSteamId = dispatch.Load<SteamGetSteamId>(
                "SteamAPI_ISteamUser_GetSteamID");
            LocalSteamId = getSteamId(user);
        }

        public ulong LocalSteamId { get; }
        public ulong Join(ulong lobbyId) => join_(matchmaking_, lobbyId);
        public void Leave(ulong lobbyId) => leave_(matchmaking_, lobbyId);
        public ulong GetOwner(ulong lobbyId) => getOwner_(matchmaking_, lobbyId);
    }

    private sealed class SteamNetworkingApi
    {
        private readonly nint networking_;
        private readonly SteamIdentityClear clearIdentity_;
        private readonly SteamIdentitySetSteamId setSteamId_;
        private readonly SteamIdentityGetSteamId getSteamId_;
        private readonly SteamNetworkingSend send_;
        private readonly SteamNetworkingReceive receive_;
        private readonly SteamNetworkingAccept accept_;
        private readonly SteamNetworkingClose close_;
        private readonly SteamNetworkingMessageRelease release_;

        public SteamNetworkingApi(SteamManualDispatchSession dispatch)
        {
            networking_ = dispatch.GetInterface(
                "SteamAPI_SteamNetworkingMessages_SteamAPI_v002");
            clearIdentity_ = dispatch.Load<SteamIdentityClear>(
                "SteamAPI_SteamNetworkingIdentity_Clear");
            setSteamId_ = dispatch.Load<SteamIdentitySetSteamId>(
                "SteamAPI_SteamNetworkingIdentity_SetSteamID64");
            getSteamId_ = dispatch.Load<SteamIdentityGetSteamId>(
                "SteamAPI_SteamNetworkingIdentity_GetSteamID64");
            send_ = dispatch.Load<SteamNetworkingSend>(
                "SteamAPI_ISteamNetworkingMessages_SendMessageToUser");
            receive_ = dispatch.Load<SteamNetworkingReceive>(
                "SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel");
            accept_ = dispatch.Load<SteamNetworkingAccept>(
                "SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser");
            close_ = dispatch.Load<SteamNetworkingClose>(
                "SteamAPI_ISteamNetworkingMessages_CloseSessionWithUser");
            release_ = dispatch.Load<SteamNetworkingMessageRelease>(
                "SteamAPI_SteamNetworkingMessage_t_Release");
        }

        public void Send(ulong steamId, ReadOnlySpan<byte> packet)
        {
            var identity = BuildIdentity(steamId);
            var buffer = Marshal.AllocHGlobal(packet.Length);
            try
            {
                Marshal.Copy(packet.ToArray(), 0, buffer, packet.Length);
                var result = send_(
                    networking_,
                    ref identity,
                    buffer,
                    checked((uint)packet.Length),
                    ReliableNoNagle,
                    SessionBulkChannel);
                if (result != 1)
                {
                    throw new IOException(
                        $"Steam rejected a host mod transfer packet (result {result}).");
                }
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        public byte[]? TryReceive(ulong expectedSteamId)
        {
            var messages = new nint[1];
            var count = Math.Clamp(
                receive_(networking_, SessionBulkChannel, messages, messages.Length),
                0,
                messages.Length);
            byte[]? result = null;
            for (var index = 0; index < count; index++)
            {
                var message = messages[index];
                if (message == 0)
                {
                    continue;
                }
                try
                {
                    var size = Marshal.ReadInt32(message, 4);
                    var sender = GetSteamId(message + 12);
                    var data = Marshal.ReadIntPtr(message, 0);
                    if (result is null && sender == expectedSteamId && data != 0 &&
                        size is >= 12 and <= MaximumMessageBytes)
                    {
                        result = new byte[size];
                        Marshal.Copy(data, result, 0, size);
                    }
                }
                finally
                {
                    release_(message);
                }
            }
            return result;
        }

        public ulong GetSteamId(nint identity) => getSteamId_(identity);

        public void Accept(ulong steamId)
        {
            var identity = BuildIdentity(steamId);
            if (!accept_(networking_, ref identity))
            {
                throw new IOException("Steam rejected the host mod transfer session.");
            }
        }

        public void Close(ulong steamId)
        {
            var identity = BuildIdentity(steamId);
            close_(networking_, ref identity);
        }

        private SteamNetworkingIdentity BuildIdentity(ulong steamId)
        {
            var identity = SteamNetworkingIdentity.Create();
            clearIdentity_(ref identity);
            setSteamId_(ref identity, steamId);
            return identity;
        }
    }

    [StructLayout(LayoutKind.Sequential, Pack = 1, Size = Size)]
    private struct SteamNetworkingIdentity
    {
        public const int Size = 136;
        public int Type;
        public int ValueSize;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 128)]
        public byte[] Value;

        public static SteamNetworkingIdentity Create() =>
            new() { Value = new byte[128] };
    }

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate ulong SteamJoinLobby(nint matchmaking, ulong lobbyId);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamLeaveLobby(nint matchmaking, ulong lobbyId);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate ulong SteamGetLobbyOwner(nint matchmaking, ulong lobbyId);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate ulong SteamGetSteamId(nint user);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamIdentityClear(ref SteamNetworkingIdentity identity);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamIdentitySetSteamId(
        ref SteamNetworkingIdentity identity,
        ulong steamId);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate ulong SteamIdentityGetSteamId(nint identity);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int SteamNetworkingSend(
        nint networking,
        ref SteamNetworkingIdentity identity,
        nint data,
        uint size,
        int flags,
        int channel);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int SteamNetworkingReceive(
        nint networking,
        int channel,
        [Out] nint[] messages,
        int maximumMessages);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)]
    private delegate bool SteamNetworkingAccept(
        nint networking,
        ref SteamNetworkingIdentity identity);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)]
    private delegate bool SteamNetworkingClose(
        nint networking,
        ref SteamNetworkingIdentity identity);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamNetworkingMessageRelease(nint message);
}
