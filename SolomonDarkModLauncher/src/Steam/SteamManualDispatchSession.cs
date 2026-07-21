using System.Runtime.InteropServices;

namespace SolomonDarkModLauncher.Steam;

[StructLayout(LayoutKind.Sequential, Pack = 4)]
internal readonly struct SteamCallbackMessage
{
    public readonly int User;
    public readonly int CallbackId;
    public readonly nint Parameter;
    public readonly int ParameterSize;
}

internal sealed class SteamManualDispatchSession : IDisposable
{
    private nint module_;
    private SteamShutdown? shutdown_;
    private SteamManualDispatchRunFrame? runFrame_;
    private SteamManualDispatchGetNextCallback? getNextCallback_;
    private SteamManualDispatchFreeLastCallback? freeLastCallback_;
    private bool initialized_;

    public SteamManualDispatchSession(string steamApiPath, string appId)
    {
        if (Environment.Is64BitProcess)
        {
            throw new InvalidOperationException(
                "Steam callbacks must run through the packaged x86 launcher.");
        }

        module_ = NativeLibrary.Load(steamApiPath);
        try
        {
            var init = Load<SteamInitSafe>("SteamAPI_InitSafe");
            shutdown_ = Load<SteamShutdown>("SteamAPI_Shutdown");
            var getPipe = Load<SteamGetPipe>("SteamAPI_GetHSteamPipe");
            var manualDispatchInit = Load<SteamManualDispatchInit>(
                "SteamAPI_ManualDispatch_Init");
            runFrame_ = Load<SteamManualDispatchRunFrame>(
                "SteamAPI_ManualDispatch_RunFrame");
            getNextCallback_ = Load<SteamManualDispatchGetNextCallback>(
                "SteamAPI_ManualDispatch_GetNextCallback");
            freeLastCallback_ = Load<SteamManualDispatchFreeLastCallback>(
                "SteamAPI_ManualDispatch_FreeLastCallback");

            var previousAppId = Environment.GetEnvironmentVariable("SteamAppId");
            var previousGameId = Environment.GetEnvironmentVariable("SteamGameId");
            try
            {
                Environment.SetEnvironmentVariable("SteamAppId", appId);
                Environment.SetEnvironmentVariable("SteamGameId", appId);
                if (!init())
                {
                    throw new InvalidOperationException(
                        "Steam is unavailable. Start Steam, sign in, and try again.");
                }
            }
            finally
            {
                Environment.SetEnvironmentVariable("SteamAppId", previousAppId);
                Environment.SetEnvironmentVariable("SteamGameId", previousGameId);
            }

            initialized_ = true;
            manualDispatchInit();
            Pipe = getPipe();
            if (Pipe == 0)
            {
                throw new InvalidOperationException(
                    "Steam initialized without a signed-in user session.");
            }
        }
        catch
        {
            Dispose();
            throw;
        }
    }

    public int Pipe { get; }

    public T Load<T>(string exportName) where T : Delegate =>
        Marshal.GetDelegateForFunctionPointer<T>(
            NativeLibrary.GetExport(module_, exportName));

    public nint GetInterface(string accessorExport)
    {
        var accessor = Load<SteamInterfaceAccessor>(accessorExport);
        var instance = accessor();
        return instance != 0
            ? instance
            : throw new InvalidOperationException(
                $"Steam interface {accessorExport} is unavailable.");
    }

    public void RunCallbacks(Action<SteamCallbackMessage> handler)
    {
        ArgumentNullException.ThrowIfNull(handler);
        if (!initialized_ || runFrame_ is null ||
            getNextCallback_ is null || freeLastCallback_ is null)
        {
            throw new ObjectDisposedException(nameof(SteamManualDispatchSession));
        }

        runFrame_(Pipe);
        while (getNextCallback_(Pipe, out var callback))
        {
            try
            {
                handler(callback);
            }
            finally
            {
                freeLastCallback_(Pipe);
            }
        }
    }

    public void Dispose()
    {
        if (initialized_)
        {
            shutdown_!();
            initialized_ = false;
        }
        if (module_ != 0)
        {
            NativeLibrary.Free(module_);
            module_ = 0;
        }
    }

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)]
    private delegate bool SteamInitSafe();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamShutdown();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int SteamGetPipe();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamManualDispatchInit();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamManualDispatchRunFrame(int pipe);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.I1)]
    private delegate bool SteamManualDispatchGetNextCallback(
        int pipe,
        out SteamCallbackMessage callback);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SteamManualDispatchFreeLastCallback(int pipe);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate nint SteamInterfaceAccessor();
}
