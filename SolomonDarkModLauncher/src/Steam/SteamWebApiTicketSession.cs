using System.Diagnostics;
using System.Runtime.InteropServices;

namespace SolomonDarkModLauncher.Steam;

internal sealed class SteamWebApiTicketSession : IDisposable
{
    private const string TicketIdentity = "solomon-dark-directory-v1";
    private const int GetTicketForWebApiCallback = 168;
    private const int TicketHeaderBytes = 12;
    private const int MaximumTicketBytes = 2560;
    private const int ResultOk = 1;
    private static readonly TimeSpan TicketTimeout = TimeSpan.FromSeconds(10);

    private IntPtr module_;
    private SteamApiShutdown? shutdown_;
    private SteamApiCancelAuthTicket? cancelAuthTicket_;
    private IntPtr steamUser_;
    private uint authTicket_;
    private bool initialized_;

    private SteamWebApiTicketSession()
    {
    }

    public string TicketHex { get; private set; } = string.Empty;

    public static SteamWebApiTicketSession Open(string steamApiDllPath)
    {
        if (IntPtr.Size != 4)
        {
            throw new InvalidOperationException(
                "Steam directory authentication must run through the x86 launcher.");
        }

        var session = new SteamWebApiTicketSession();
        try
        {
            session.TicketHex = session.InitializeAndAcquire(steamApiDllPath);
            return session;
        }
        catch
        {
            session.Dispose();
            throw;
        }
    }

    public void Dispose()
    {
        if (authTicket_ != 0 && steamUser_ != IntPtr.Zero && cancelAuthTicket_ is not null)
        {
            cancelAuthTicket_(steamUser_, authTicket_);
            authTicket_ = 0;
        }
        if (initialized_ && shutdown_ is not null)
        {
            shutdown_();
            initialized_ = false;
        }
        if (module_ != IntPtr.Zero)
        {
            NativeLibrary.Free(module_);
            module_ = IntPtr.Zero;
        }
    }

    private string InitializeAndAcquire(string steamApiDllPath)
    {
        Environment.SetEnvironmentVariable("SteamAppId", SteamBootstrapConfiguration.SpacewarDevelopmentAppId);
        Environment.SetEnvironmentVariable("SteamGameId", SteamBootstrapConfiguration.SpacewarDevelopmentAppId);

        module_ = NativeLibrary.Load(steamApiDllPath);
        var initialize = Load<SteamApiInit>("SteamAPI_Init");
        shutdown_ = Load<SteamApiShutdown>("SteamAPI_Shutdown");
        var getPipe = Load<SteamApiGetPipe>("SteamAPI_GetHSteamPipe");
        var getSteamUser = Load<SteamApiGetSteamUser>("SteamAPI_SteamUser_v023");
        var manualDispatchInit = Load<SteamApiManualDispatchInit>("SteamAPI_ManualDispatch_Init");
        var runFrame = Load<SteamApiManualDispatchRunFrame>("SteamAPI_ManualDispatch_RunFrame");
        var getNextCallback = Load<SteamApiManualDispatchGetNextCallback>(
            "SteamAPI_ManualDispatch_GetNextCallback");
        var freeLastCallback = Load<SteamApiManualDispatchFreeLastCallback>(
            "SteamAPI_ManualDispatch_FreeLastCallback");
        var getAuthTicket = Load<SteamApiGetAuthTicketForWebApi>(
            "SteamAPI_ISteamUser_GetAuthTicketForWebApi");
        cancelAuthTicket_ = Load<SteamApiCancelAuthTicket>(
            "SteamAPI_ISteamUser_CancelAuthTicket");

        if (!initialize())
        {
            throw new InvalidOperationException(
                "Steam authentication could not start. Make sure Steam is running and signed in.");
        }
        initialized_ = true;
        manualDispatchInit();

        var pipe = getPipe();
        steamUser_ = getSteamUser();
        if (pipe == 0 || steamUser_ == IntPtr.Zero)
        {
            throw new InvalidOperationException(
                "Steam did not expose the signed-in user to the launcher.");
        }

        authTicket_ = getAuthTicket(steamUser_, TicketIdentity);
        if (authTicket_ == 0)
        {
            throw new InvalidOperationException(
                "Steam could not create a Web API authentication ticket.");
        }

        var stopwatch = Stopwatch.StartNew();
        while (stopwatch.Elapsed < TicketTimeout)
        {
            runFrame(pipe);
            while (getNextCallback(pipe, out var callback))
            {
                try
                {
                    if (callback.CallbackId != GetTicketForWebApiCallback)
                    {
                        continue;
                    }

                    var ticket = ReadTicketCallback(callback);
                    if (ticket is not null)
                    {
                        return ticket;
                    }
                }
                finally
                {
                    freeLastCallback(pipe);
                }
            }

            Thread.Sleep(10);
        }

        throw new TimeoutException(
            "Steam did not return a Web API authentication ticket within 10 seconds.");
    }

    private string? ReadTicketCallback(SteamCallbackMessage callback)
    {
        if (callback.Parameter == IntPtr.Zero || callback.ParameterSize < TicketHeaderBytes)
        {
            throw new InvalidOperationException(
                "Steam returned an invalid Web API ticket callback.");
        }

        var callbackTicket = unchecked((uint)Marshal.ReadInt32(callback.Parameter, 0));
        if (callbackTicket != authTicket_)
        {
            return null;
        }

        var result = Marshal.ReadInt32(callback.Parameter, 4);
        if (result != ResultOk)
        {
            throw new InvalidOperationException(
                $"Steam rejected the Web API ticket request (EResult {result}).");
        }

        var ticketLength = Marshal.ReadInt32(callback.Parameter, 8);
        if (ticketLength is <= 0 or > MaximumTicketBytes ||
            callback.ParameterSize < TicketHeaderBytes + ticketLength)
        {
            throw new InvalidOperationException(
                "Steam returned an invalid Web API authentication ticket.");
        }

        var ticket = new byte[ticketLength];
        Marshal.Copy(IntPtr.Add(callback.Parameter, TicketHeaderBytes), ticket, 0, ticket.Length);
        return Convert.ToHexString(ticket).ToLowerInvariant();
    }

    private T Load<T>(string exportName) where T : Delegate =>
        Marshal.GetDelegateForFunctionPointer<T>(NativeLibrary.GetExport(module_, exportName));

    [StructLayout(LayoutKind.Sequential)]
    private struct SteamCallbackMessage
    {
        public int SteamUser;
        public int CallbackId;
        public IntPtr Parameter;
        public int ParameterSize;
    }

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)]
    private delegate bool SteamApiInit();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamApiShutdown();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int SteamApiGetPipe();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate IntPtr SteamApiGetSteamUser();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamApiManualDispatchInit();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamApiManualDispatchRunFrame(int pipe);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)]
    private delegate bool SteamApiManualDispatchGetNextCallback(
        int pipe,
        out SteamCallbackMessage callback);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamApiManualDispatchFreeLastCallback(int pipe);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate uint SteamApiGetAuthTicketForWebApi(
        IntPtr steamUser,
        [MarshalAs(UnmanagedType.LPStr)] string identity);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamApiCancelAuthTicket(IntPtr steamUser, uint authTicket);
}
