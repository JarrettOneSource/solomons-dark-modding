using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace SolomonDarkModLauncher.Steam;

internal static class SteamInviteListener
{
    public const string InternalCommand = "__listen-steam-invites";
    public const string EventPrefix = "SDMOD_STEAM_INVITE ";

    private const int GameLobbyJoinRequestedCallbackId = 333;
    private const int GameRichPresenceJoinRequestedCallbackId = 337;
    private const int LobbyInviteCallbackId = 503;
    private const int LobbyJoinCallbackBytes = 16;
    private const int RichPresenceJoinCallbackBytes = 264;
    private const int LobbyInviteCallbackBytes = 24;
    private const int RichPresenceConnectBytes = 256;
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
        if (args.Length != 2 ||
            !int.TryParse(args[1], out var parentProcessId) ||
            parentProcessId <= 0)
        {
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

        using (parentProcess)
        {
            while (!parentProcess.HasExited)
            {
                try
                {
                    Listen(parentProcess);
                    return 0;
                }
                catch (Exception ex) when (ex is InvalidOperationException or
                                             DllNotFoundException or
                                             BadImageFormatException or
                                             EntryPointNotFoundException)
                {
                    WriteEvent("unavailable", error: ex.Message);
                    if (parentProcess.WaitForExit(5000))
                    {
                        return 0;
                    }
                }
            }
        }

        return 0;
    }

    private static void Listen(Process parentProcess)
    {
        var steamConfiguration = SteamBootstrapConfiguration.CreateDefault(
            SteamBootstrapConfiguration.SpacewarDevelopmentAppId,
            apiDllOverridePath: null);
        var steamApiPath = SteamBootstrapMaterializer.ResolveSteamApiSourcePath(
            steamConfiguration)
            ?? throw new InvalidOperationException(
                "Automatic Steam invite handling requires the packaged x86 steam_api.dll.");

        using var dispatch = new SteamManualDispatchSession(steamApiPath);
        var steamFriends = dispatch.GetInterface("SteamAPI_SteamFriends_v017");
        var getFriendPersonaName = dispatch.Load<SteamGetFriendPersonaName>(
            "SteamAPI_ISteamFriends_GetFriendPersonaName");
        WriteEvent("ready");

        ulong lastAcceptedLobbyId = 0;
        var lastAcceptedAtUtc = DateTime.MinValue;
        while (!parentProcess.HasExited)
        {
            dispatch.RunCallbacks(callback =>
            {
                if (!TryReadInvite(callback, out var kind, out var lobbyId, out var friendId) ||
                    lobbyId == 0)
                {
                    return;
                }

                if (kind == "accepted" &&
                    lobbyId == lastAcceptedLobbyId &&
                    DateTime.UtcNow - lastAcceptedAtUtc < TimeSpan.FromSeconds(5))
                {
                    return;
                }

                if (kind == "accepted")
                {
                    lastAcceptedLobbyId = lobbyId;
                    lastAcceptedAtUtc = DateTime.UtcNow;
                }

                var friendName = friendId == 0
                    ? string.Empty
                    : ReadUtf8(getFriendPersonaName(steamFriends, friendId));
                WriteEvent(kind, lobbyId, friendId, friendName);
            });
            Thread.Sleep(20);
        }
    }

    private static bool TryReadInvite(
        SteamCallbackMessage callback,
        out string kind,
        out ulong lobbyId,
        out ulong friendId)
    {
        kind = string.Empty;
        lobbyId = 0;
        friendId = 0;
        if (callback.Parameter == 0)
        {
            return false;
        }

        switch (callback.CallbackId)
        {
            case GameLobbyJoinRequestedCallbackId
                when callback.ParameterSize >= LobbyJoinCallbackBytes:
                kind = "accepted";
                lobbyId = ReadUInt64(callback.Parameter, 0);
                friendId = ReadUInt64(callback.Parameter, 8);
                return true;

            case GameRichPresenceJoinRequestedCallbackId
                when callback.ParameterSize >= RichPresenceJoinCallbackBytes:
                friendId = ReadUInt64(callback.Parameter, 0);
                if (!TryParseLobbyId(
                        ReadFixedUtf8(
                            callback.Parameter + 8,
                            RichPresenceConnectBytes),
                        out lobbyId))
                {
                    return false;
                }
                kind = "accepted";
                return true;

            case LobbyInviteCallbackId
                when callback.ParameterSize >= LobbyInviteCallbackBytes:
                kind = "received";
                friendId = ReadUInt64(callback.Parameter, 0);
                lobbyId = ReadUInt64(callback.Parameter, 8);
                return true;

            default:
                return false;
        }
    }

    private static bool TryParseLobbyId(string connect, out ulong lobbyId)
    {
        lobbyId = 0;
        var parts = connect.Split(
            ' ',
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        return parts.Length == 2 &&
               parts[0] == "+connect_lobby" &&
               ulong.TryParse(parts[1], out lobbyId) &&
               lobbyId != 0;
    }

    private static ulong ReadUInt64(nint address, int offset) =>
        unchecked((ulong)Marshal.ReadInt64(address, offset));

    private static string ReadFixedUtf8(nint address, int maximumBytes)
    {
        var bytes = new byte[maximumBytes];
        Marshal.Copy(address, bytes, 0, bytes.Length);
        var terminator = Array.IndexOf(bytes, (byte)0);
        return Encoding.UTF8.GetString(
            bytes,
            0,
            terminator >= 0 ? terminator : bytes.Length);
    }

    private static string ReadUtf8(nint address) =>
        address == 0 ? string.Empty : Marshal.PtrToStringUTF8(address) ?? string.Empty;

    private static void WriteEvent(
        string kind,
        ulong lobbyId = 0,
        ulong friendId = 0,
        string friendName = "",
        string error = "")
    {
        Console.WriteLine(EventPrefix + JsonSerializer.Serialize(
            new SteamInviteEvent(
                kind,
                lobbyId == 0 ? null : lobbyId.ToString(),
                friendId == 0 ? null : friendId.ToString(),
                friendName,
                error),
            JsonOptions));
        Console.Out.Flush();
    }

    private sealed record SteamInviteEvent(
        string Kind,
        string? LobbyId,
        string? FriendSteamId,
        string FriendName,
        string Error);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate nint SteamGetFriendPersonaName(
        nint steamFriends,
        ulong friendSteamId);
}
