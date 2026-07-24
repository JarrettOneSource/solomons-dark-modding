using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace SolomonDarkModLauncher.Steam;

internal static class SteamLobbySession
{
    public const string InternalCommand = "__join-steam-lobby";
    public const string EventPrefix = "SDMOD_STEAM_LOBBY ";

    private const int SteamServersDisconnectedCallbackId = 103;
    private const int LobbyEnterCallbackId = 504;
    private const int LobbyChatUpdateCallbackId = 506;
    private const int SteamApiCallCompletedCallbackId = 703;
    private const uint LobbyEnterSuccess = 1;
    private const uint MemberDepartureMask = 0x02 | 0x04 | 0x08 | 0x10;
    private const int JoinTimeoutSeconds = 30;
    private static readonly JsonSerializerOptions JsonOptions =
        new(JsonSerializerDefaults.Web);

    public static bool TryRun(string[] args, out int exitCode)
    {
        if (args.Length == 0 || !string.Equals(
                args[0],
                InternalCommand,
                StringComparison.Ordinal))
        {
            exitCode = 0;
            return false;
        }

        exitCode = Run(args);
        return true;
    }

    private static int Run(string[] args)
    {
        if (args.Length != 3 ||
            !int.TryParse(args[1], out var parentProcessId) ||
            parentProcessId <= 0 ||
            !ulong.TryParse(args[2], out var lobbyId) ||
            lobbyId == 0)
        {
            WriteEvent("error", error: "The Steam lobby helper received invalid arguments.");
            return 2;
        }

        Process parentProcess;
        try
        {
            parentProcess = Process.GetProcessById(parentProcessId);
        }
        catch (ArgumentException)
        {
            return 0;
        }

        try
        {
            using (parentProcess)
            {
                HoldMembership(parentProcess, lobbyId);
            }
            return 0;
        }
        catch (Exception exception) when (
            exception is InvalidOperationException or
            DllNotFoundException or
            BadImageFormatException or
            EntryPointNotFoundException)
        {
            WriteEvent("error", lobbyId, error: exception.Message);
            return 1;
        }
    }

    private static void HoldMembership(Process parentProcess, ulong lobbyId)
    {
        var steamConfiguration = SteamBootstrapConfiguration.CreateDefault(
            appIdOverride: null,
            apiDllOverridePath: null);
        var steamApiPath = SteamBootstrapMaterializer.ResolveSteamApiSourcePath(
            steamConfiguration)
            ?? throw new InvalidOperationException(
                "Joining a Steam lobby needs the packaged x86 steam_api.dll.");

        using var dispatch = new SteamManualDispatchSession(
            steamApiPath,
            steamConfiguration.AppId);
        var lobbyApi = new LobbyApi(dispatch);
        var localSteamId = lobbyApi.LocalSteamId;
        if (localSteamId == 0)
        {
            throw new InvalidOperationException(
                "Steam initialized without a signed-in local user.");
        }

        var joinCall = lobbyApi.Join(lobbyId);
        if (joinCall == 0)
        {
            throw new InvalidOperationException(
                "Steam rejected the lobby join request before it was sent.");
        }

        var leaveCommand = Task.Run(Console.In.ReadLine);
        var joinDeadline = DateTime.UtcNow.AddSeconds(JoinTimeoutSeconds);
        var joined = false;
        var joinCompleted = false;
        var originalHostSteamId = 0UL;
        var lastSnapshotSignature = string.Empty;

        try
        {
            while (!parentProcess.HasExited)
            {
                uint? joinResponse = null;
                string? disconnectReason = null;
                dispatch.RunCallbacks(callback =>
                {
                    if (!joinCompleted &&
                        TryReadLobbyEnterResult(
                            dispatch,
                            callback,
                            joinCall,
                            out var enteredLobbyId,
                            out var response) &&
                        enteredLobbyId == lobbyId)
                    {
                        joinResponse = response;
                        joinCompleted = true;
                    }

                    if (callback.CallbackId == SteamServersDisconnectedCallbackId)
                    {
                        disconnectReason =
                            "Steam disconnected while you were waiting to launch.";
                        return;
                    }

                    if (joined &&
                        callback.CallbackId == LobbyChatUpdateCallbackId &&
                        callback.Parameter != 0 &&
                        callback.ParameterSize >= 28)
                    {
                        var changedLobbyId = ReadUInt64(callback.Parameter, 0);
                        var changedUserId = ReadUInt64(callback.Parameter, 8);
                        var stateChange = ReadUInt32(callback.Parameter, 24);
                        if (changedLobbyId != lobbyId ||
                            (stateChange & MemberDepartureMask) == 0)
                        {
                            return;
                        }

                        if (changedUserId == originalHostSteamId)
                        {
                            disconnectReason =
                                "The host left the lobby before you launched.";
                        }
                        else if (changedUserId == localSteamId)
                        {
                            disconnectReason =
                                "Steam disconnected you from the lobby before launch.";
                        }
                    }
                });

                if (!string.IsNullOrWhiteSpace(disconnectReason))
                {
                    WriteEvent(
                        disconnectReason.StartsWith("The host", StringComparison.Ordinal)
                            ? "hostDeparted"
                            : "disconnected",
                        lobbyId,
                        error: disconnectReason);
                    return;
                }

                if (joinResponse is { } response)
                {
                    if (response != LobbyEnterSuccess)
                    {
                        WriteEvent(
                            "error",
                            lobbyId,
                            error: DescribeJoinFailure(response));
                        return;
                    }

                    originalHostSteamId = lobbyApi.GetOwner(lobbyId);
                    if (originalHostSteamId == 0 ||
                        originalHostSteamId == localSteamId)
                    {
                        WriteEvent(
                            "hostDeparted",
                            lobbyId,
                            error: "The host left the lobby before the join completed.");
                        return;
                    }
                    joined = true;
                }

                if (!joined && DateTime.UtcNow >= joinDeadline)
                {
                    WriteEvent(
                        "error",
                        lobbyId,
                        error: "Steam did not join the lobby within 30 seconds.");
                    return;
                }

                if (joined)
                {
                    var snapshot = lobbyApi.ReadSnapshot(
                        lobbyId,
                        originalHostSteamId,
                        localSteamId);
                    if (!snapshot.Members.Any(member => member.SteamId == localSteamId))
                    {
                        WriteEvent(
                            "disconnected",
                            lobbyId,
                            error: "Steam disconnected you from the lobby before launch.");
                        return;
                    }
                    if (snapshot.HostSteamId != originalHostSteamId ||
                        !snapshot.Members.Any(member =>
                            member.SteamId == originalHostSteamId))
                    {
                        WriteEvent(
                            "hostDeparted",
                            lobbyId,
                            error: "The host left the lobby before you launched.");
                        return;
                    }
                    if (!string.IsNullOrWhiteSpace(snapshot.State) &&
                        !string.Equals(
                            snapshot.State,
                            "open",
                            StringComparison.OrdinalIgnoreCase))
                    {
                        WriteEvent(
                            "hostDeparted",
                            lobbyId,
                            error: "The host closed the lobby before you launched.");
                        return;
                    }

                    var signature = snapshot.Signature;
                    if (!string.Equals(
                            signature,
                            lastSnapshotSignature,
                            StringComparison.Ordinal))
                    {
                        WriteEvent(
                            string.IsNullOrEmpty(lastSnapshotSignature)
                                ? "joined"
                                : "status",
                            snapshot);
                        lastSnapshotSignature = signature;
                    }
                }

                if (leaveCommand.IsCompleted)
                {
                    return;
                }

                Thread.Sleep(50);
            }
        }
        finally
        {
            if (joined)
            {
                lobbyApi.Leave(lobbyId);
            }
        }
    }

    private static bool TryReadLobbyEnterResult(
        SteamManualDispatchSession dispatch,
        SteamCallbackMessage callback,
        ulong expectedApiCall,
        out ulong lobbyId,
        out uint response)
    {
        lobbyId = 0;
        response = 0;
        if (callback.Parameter == 0)
        {
            return false;
        }

        if (callback.CallbackId == LobbyEnterCallbackId &&
            callback.ParameterSize >= 20)
        {
            lobbyId = ReadUInt64(callback.Parameter, 0);
            response = ReadUInt32(callback.Parameter, 16);
            return true;
        }

        if (callback.CallbackId != SteamApiCallCompletedCallbackId ||
            callback.ParameterSize < 16)
        {
            return false;
        }

        var apiCall = ReadUInt64(callback.Parameter, 0);
        var completedCallbackId = Marshal.ReadInt32(callback.Parameter, 8);
        var parameterSize = Marshal.ReadInt32(callback.Parameter, 12);
        if (apiCall != expectedApiCall ||
            completedCallbackId != LobbyEnterCallbackId ||
            parameterSize < 20 ||
            !dispatch.TryGetApiCallResult(
                apiCall,
                completedCallbackId,
                parameterSize,
                out var result))
        {
            return false;
        }

        lobbyId = BitConverter.ToUInt64(result, 0);
        response = BitConverter.ToUInt32(result, 16);
        return true;
    }

    private static string DescribeJoinFailure(uint response) =>
        response switch
        {
            2 => "The Steam lobby no longer exists.",
            3 => "Steam did not allow this account to join the lobby.",
            4 => "The Steam lobby is full.",
            6 => "This Steam account is banned from the lobby.",
            7 => "This Steam account is too limited to join the lobby.",
            9 => "Steam community access is required to join the lobby.",
            10 => "A lobby member has blocked this Steam account.",
            11 => "This Steam account has blocked a lobby member.",
            _ => $"Steam could not join the lobby (response {response})."
        };

    private static ulong ReadUInt64(nint address, int offset) =>
        unchecked((ulong)Marshal.ReadInt64(address, offset));

    private static uint ReadUInt32(nint address, int offset) =>
        unchecked((uint)Marshal.ReadInt32(address, offset));

    private static void WriteEvent(
        string kind,
        ulong lobbyId = 0,
        string error = "") =>
        WriteEvent(
            new SteamLobbyEvent(
                kind,
                lobbyId == 0 ? null : lobbyId.ToString(),
                null,
                null,
                string.Empty,
                0,
                [],
                error));

    private static void WriteEvent(string kind, LobbySnapshot snapshot) =>
        WriteEvent(
            new SteamLobbyEvent(
                kind,
                snapshot.LobbyId.ToString(),
                snapshot.HostSteamId.ToString(),
                snapshot.LocalSteamId.ToString(),
                snapshot.Privacy,
                snapshot.MaxParticipants,
                snapshot.Members.Select(member =>
                    new SteamLobbyMemberEvent(
                        member.SteamId.ToString(),
                        member.Name,
                        member.IsHost,
                        member.IsLocal)).ToArray(),
                string.Empty));

    private static void WriteEvent(SteamLobbyEvent value)
    {
        Console.WriteLine(EventPrefix + JsonSerializer.Serialize(value, JsonOptions));
        Console.Out.Flush();
    }

    private sealed class LobbyApi
    {
        private readonly nint matchmaking_;
        private readonly nint friends_;
        private readonly SteamJoinLobby joinLobby_;
        private readonly SteamLeaveLobby leaveLobby_;
        private readonly SteamGetLobbyOwner getLobbyOwner_;
        private readonly SteamGetNumLobbyMembers getNumLobbyMembers_;
        private readonly SteamGetLobbyMemberByIndex getLobbyMemberByIndex_;
        private readonly SteamGetLobbyData getLobbyData_;
        private readonly SteamGetFriendPersonaName getFriendPersonaName_;
        private readonly SteamGetPersonaName getPersonaName_;

        public LobbyApi(SteamManualDispatchSession dispatch)
        {
            matchmaking_ = dispatch.GetInterface("SteamAPI_SteamMatchmaking_v009");
            friends_ = dispatch.GetInterface("SteamAPI_SteamFriends_v017");
            var user = dispatch.GetInterface("SteamAPI_SteamUser_v023");
            joinLobby_ = dispatch.Load<SteamJoinLobby>(
                "SteamAPI_ISteamMatchmaking_JoinLobby");
            leaveLobby_ = dispatch.Load<SteamLeaveLobby>(
                "SteamAPI_ISteamMatchmaking_LeaveLobby");
            getLobbyOwner_ = dispatch.Load<SteamGetLobbyOwner>(
                "SteamAPI_ISteamMatchmaking_GetLobbyOwner");
            getNumLobbyMembers_ = dispatch.Load<SteamGetNumLobbyMembers>(
                "SteamAPI_ISteamMatchmaking_GetNumLobbyMembers");
            getLobbyMemberByIndex_ = dispatch.Load<SteamGetLobbyMemberByIndex>(
                "SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex");
            getLobbyData_ = dispatch.Load<SteamGetLobbyData>(
                "SteamAPI_ISteamMatchmaking_GetLobbyData");
            getFriendPersonaName_ = dispatch.Load<SteamGetFriendPersonaName>(
                "SteamAPI_ISteamFriends_GetFriendPersonaName");
            getPersonaName_ = dispatch.Load<SteamGetPersonaName>(
                "SteamAPI_ISteamFriends_GetPersonaName");
            var getSteamId = dispatch.Load<SteamGetSteamId>(
                "SteamAPI_ISteamUser_GetSteamID");
            LocalSteamId = getSteamId(user);
        }

        public ulong LocalSteamId { get; }

        public ulong Join(ulong lobbyId) => joinLobby_(matchmaking_, lobbyId);

        public void Leave(ulong lobbyId) => leaveLobby_(matchmaking_, lobbyId);

        public ulong GetOwner(ulong lobbyId) =>
            getLobbyOwner_(matchmaking_, lobbyId);

        public LobbySnapshot ReadSnapshot(
            ulong lobbyId,
            ulong hostSteamId,
            ulong localSteamId)
        {
            var currentOwner = GetOwner(lobbyId);
            var memberCount = Math.Clamp(
                getNumLobbyMembers_(matchmaking_, lobbyId),
                0,
                250);
            var members = new List<LobbyMemberSnapshot>(memberCount);
            for (var index = 0; index < memberCount; index++)
            {
                var memberSteamId = getLobbyMemberByIndex_(
                    matchmaking_,
                    lobbyId,
                    index);
                if (memberSteamId == 0)
                {
                    continue;
                }

                var name = memberSteamId == localSteamId
                    ? ReadUtf8(getPersonaName_(friends_))
                    : ReadUtf8(getFriendPersonaName_(friends_, memberSteamId));
                members.Add(new LobbyMemberSnapshot(
                    memberSteamId,
                    name,
                    memberSteamId == hostSteamId,
                    memberSteamId == localSteamId));
            }

            var maxParticipants = int.TryParse(
                GetLobbyData(lobbyId, "sdmod_max_players"),
                out var parsedMax)
                ? Math.Clamp(parsedMax, 2, 250)
                : Math.Max(2, members.Count);
            return new LobbySnapshot(
                lobbyId,
                currentOwner,
                localSteamId,
                GetLobbyData(lobbyId, "sdmod_privacy"),
                maxParticipants,
                GetLobbyData(lobbyId, "sdmod_state"),
                members);
        }

        private string GetLobbyData(ulong lobbyId, string key) =>
            ReadUtf8(getLobbyData_(matchmaking_, lobbyId, key));

        private static string ReadUtf8(nint address) =>
            address == 0
                ? string.Empty
                : Marshal.PtrToStringUTF8(address) ?? string.Empty;
    }

    private sealed record LobbySnapshot(
        ulong LobbyId,
        ulong HostSteamId,
        ulong LocalSteamId,
        string Privacy,
        int MaxParticipants,
        string State,
        IReadOnlyList<LobbyMemberSnapshot> Members)
    {
        public string Signature => string.Join(
            "\n",
            new[]
            {
                HostSteamId.ToString(),
                LocalSteamId.ToString(),
                Privacy,
                MaxParticipants.ToString(),
                State
            }.Concat(Members.Select(member =>
                $"{member.SteamId}|{member.Name}|{member.IsHost}|{member.IsLocal}")));
    }

    private sealed record LobbyMemberSnapshot(
        ulong SteamId,
        string Name,
        bool IsHost,
        bool IsLocal);

    private sealed record SteamLobbyEvent(
        string Kind,
        string? LobbyId,
        string? HostSteamId,
        string? LocalSteamId,
        string Privacy,
        int MaxParticipants,
        IReadOnlyList<SteamLobbyMemberEvent> Members,
        string Error);

    private sealed record SteamLobbyMemberEvent(
        string SteamId,
        string Name,
        bool IsHost,
        bool IsLocal);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate ulong SteamJoinLobby(nint matchmaking, ulong lobbyId);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamLeaveLobby(nint matchmaking, ulong lobbyId);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate ulong SteamGetLobbyOwner(nint matchmaking, ulong lobbyId);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int SteamGetNumLobbyMembers(nint matchmaking, ulong lobbyId);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate ulong SteamGetLobbyMemberByIndex(
        nint matchmaking,
        ulong lobbyId,
        int memberIndex);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate nint SteamGetLobbyData(
        nint matchmaking,
        ulong lobbyId,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string key);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate nint SteamGetFriendPersonaName(
        nint friends,
        ulong friendSteamId);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate nint SteamGetPersonaName(nint friends);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate ulong SteamGetSteamId(nint user);
}
