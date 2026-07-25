[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [int[]]$ProcessId,

    [ValidateRange(1, 120)]
    [int]$SampleCount = 1,

    [ValidateRange(10, 60000)]
    [int]$IntervalMilliseconds = 250
)

$ErrorActionPreference = "Stop"

if (-not ("SolomonDark.AudioSessionProbe" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace SolomonDark
{
    public enum AudioSessionState
    {
        Inactive = 0,
        Active = 1,
        Expired = 2
    }

    public sealed class AudioSessionRecord
    {
        public string DeviceId { get; set; }
        public uint ProcessId { get; set; }
        public string State { get; set; }
        public string SessionIdentifier { get; set; }
        public string SessionInstanceIdentifier { get; set; }
    }

    public static class AudioSessionProbe
    {
        private const uint ClsctxAll = 0x00000017;

        public static AudioSessionRecord[] Find(uint processId)
        {
            var records = new List<AudioSessionRecord>();
            var enumerator = (IMMDeviceEnumerator)Activator.CreateInstance(
                Type.GetTypeFromCLSID(
                    new Guid(
                        "BCDE0395-E52F-467C-8E3D-C4579291692E")));
            IMMDevice device = null;
            try
            {
                ThrowIfFailed(
                    enumerator.GetDefaultAudioEndpoint(
                        EDataFlow.Render,
                        1,
                        out device));
                string deviceId;
                ThrowIfFailed(device.GetId(out deviceId));

                var managerIid =
                    typeof(IAudioSessionManager2).GUID;
                object activated;
                ThrowIfFailed(
                    device.Activate(
                        ref managerIid,
                        ClsctxAll,
                        IntPtr.Zero,
                        out activated));
                var manager =
                    (IAudioSessionManager2)activated;
                try
                {
                    IAudioSessionEnumerator sessions;
                    ThrowIfFailed(
                        manager.GetSessionEnumerator(
                            out sessions));
                    try
                    {
                        int sessionCount;
                        ThrowIfFailed(
                            sessions.GetCount(
                                out sessionCount));
                        for (var sessionIndex = 0;
                             sessionIndex < sessionCount;
                             sessionIndex++)
                        {
                            IAudioSessionControl control = null;
                            try
                            {
                                ThrowIfFailed(
                                    sessions.GetSession(
                                        sessionIndex,
                                        out control));
                                var control2 =
                                    (IAudioSessionControl2)control;
                                uint ownerProcessId;
                                ThrowIfFailed(
                                    control2.GetProcessId(
                                        out ownerProcessId));
                                if (ownerProcessId != processId)
                                {
                                    continue;
                                }

                                AudioSessionState state;
                                ThrowIfFailed(
                                    control2.GetState(
                                        out state));
                                string sessionIdentifier;
                                string instanceIdentifier;
                                ThrowIfFailed(
                                    control2.GetSessionIdentifier(
                                        out sessionIdentifier));
                                ThrowIfFailed(
                                    control2
                                        .GetSessionInstanceIdentifier(
                                            out instanceIdentifier));
                                records.Add(
                                    new AudioSessionRecord
                                    {
                                        DeviceId =
                                            deviceId ?? "",
                                        ProcessId =
                                            ownerProcessId,
                                        State =
                                            state.ToString(),
                                        SessionIdentifier =
                                            sessionIdentifier ?? "",
                                        SessionInstanceIdentifier =
                                            instanceIdentifier ?? ""
                                    });
                            }
                            finally
                            {
                                Release(control);
                            }
                        }
                    }
                    finally
                    {
                        Release(sessions);
                    }
                }
                finally
                {
                    Release(manager);
                }
            }
            finally
            {
                Release(device);
                Release(enumerator);
            }

            return records.ToArray();
        }

        private static void ThrowIfFailed(int result)
        {
            if (result < 0)
            {
                Marshal.ThrowExceptionForHR(result);
            }
        }

        private static void Release(object value)
        {
            if (value != null && Marshal.IsComObject(value))
            {
                Marshal.ReleaseComObject(value);
            }
        }
    }

    internal enum EDataFlow
    {
        Render = 0,
        Capture = 1,
        All = 2
    }

    [ComImport]
    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDeviceEnumerator
    {
        [PreserveSig]
        int EnumAudioEndpoints(
            EDataFlow dataFlow,
            uint stateMask,
            out IMMDeviceCollection devices);

        [PreserveSig]
        int GetDefaultAudioEndpoint(
            EDataFlow dataFlow,
            int role,
            out IMMDevice endpoint);

        [PreserveSig]
        int GetDevice(
            [MarshalAs(UnmanagedType.LPWStr)] string id,
            out IMMDevice device);

        [PreserveSig]
        int RegisterEndpointNotificationCallback(IntPtr client);

        [PreserveSig]
        int UnregisterEndpointNotificationCallback(IntPtr client);
    }

    [ComImport]
    [Guid("0BD7A1BE-7A1A-44DB-8397-C0A2C3CDA52D")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDeviceCollection
    {
        [PreserveSig]
        int GetCount(out uint count);

        [PreserveSig]
        int Item(uint index, out IMMDevice device);
    }

    [ComImport]
    [Guid("D666063F-1587-4E43-81F1-B948E807363F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDevice
    {
        [PreserveSig]
        int Activate(
            ref Guid iid,
            uint clsctx,
            IntPtr activationParameters,
            [MarshalAs(UnmanagedType.IUnknown)] out object result);

        [PreserveSig]
        int OpenPropertyStore(uint access, out IntPtr properties);

        [PreserveSig]
        int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);

        [PreserveSig]
        int GetState(out uint state);
    }

    [ComImport]
    [Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionManager2
    {
        [PreserveSig]
        int GetAudioSessionControl(
            ref Guid sessionGuid,
            uint streamFlags,
            out IAudioSessionControl control);

        [PreserveSig]
        int GetSimpleAudioVolume(
            ref Guid sessionGuid,
            uint streamFlags,
            out IntPtr volume);

        [PreserveSig]
        int GetSessionEnumerator(
            out IAudioSessionEnumerator enumerator);
    }

    [ComImport]
    [Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionEnumerator
    {
        [PreserveSig]
        int GetCount(out int count);

        [PreserveSig]
        int GetSession(
            int index,
            out IAudioSessionControl control);
    }

    [ComImport]
    [Guid("F4B1A599-7266-4319-A8CA-E70ACB11E8CD")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionControl
    {
        [PreserveSig]
        int GetState(out AudioSessionState state);

        [PreserveSig]
        int GetDisplayName(
            [MarshalAs(UnmanagedType.LPWStr)] out string displayName);

        [PreserveSig]
        int SetDisplayName(
            [MarshalAs(UnmanagedType.LPWStr)] string displayName,
            ref Guid eventContext);

        [PreserveSig]
        int GetIconPath(
            [MarshalAs(UnmanagedType.LPWStr)] out string iconPath);

        [PreserveSig]
        int SetIconPath(
            [MarshalAs(UnmanagedType.LPWStr)] string iconPath,
            ref Guid eventContext);

        [PreserveSig]
        int GetGroupingParam(out Guid groupingId);

        [PreserveSig]
        int SetGroupingParam(
            ref Guid groupingId,
            ref Guid eventContext);

        [PreserveSig]
        int RegisterAudioSessionNotification(IntPtr client);

        [PreserveSig]
        int UnregisterAudioSessionNotification(IntPtr client);
    }

    [ComImport]
    [Guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionControl2
    {
        [PreserveSig]
        int GetState(out AudioSessionState state);

        [PreserveSig]
        int GetDisplayName(
            [MarshalAs(UnmanagedType.LPWStr)] out string displayName);

        [PreserveSig]
        int SetDisplayName(
            [MarshalAs(UnmanagedType.LPWStr)] string displayName,
            ref Guid eventContext);

        [PreserveSig]
        int GetIconPath(
            [MarshalAs(UnmanagedType.LPWStr)] out string iconPath);

        [PreserveSig]
        int SetIconPath(
            [MarshalAs(UnmanagedType.LPWStr)] string iconPath,
            ref Guid eventContext);

        [PreserveSig]
        int GetGroupingParam(out Guid groupingId);

        [PreserveSig]
        int SetGroupingParam(
            ref Guid groupingId,
            ref Guid eventContext);

        [PreserveSig]
        int RegisterAudioSessionNotification(IntPtr client);

        [PreserveSig]
        int UnregisterAudioSessionNotification(IntPtr client);

        [PreserveSig]
        int GetSessionIdentifier(
            [MarshalAs(UnmanagedType.LPWStr)] out string identifier);

        [PreserveSig]
        int GetSessionInstanceIdentifier(
            [MarshalAs(UnmanagedType.LPWStr)] out string identifier);

        [PreserveSig]
        int GetProcessId(out uint processId);

        [PreserveSig]
        int IsSystemSoundsSession();

        [PreserveSig]
        int SetDuckingPreference(
            [MarshalAs(UnmanagedType.Bool)] bool optOut);
    }
}
'@
}

$samples = @()
for ($sampleIndex = 0; $sampleIndex -lt $SampleCount; $sampleIndex++) {
    $processes = @()
    foreach ($targetProcessId in $ProcessId) {
        $process = Get-Process `
            -Id $targetProcessId `
            -ErrorAction SilentlyContinue
        $processPath = $null
        if ($null -ne $process) {
            try {
                $processPath = $process.MainModule.FileName
            } catch {
                $processPath = $null
            }
        }
        $sessions = @(
            [SolomonDark.AudioSessionProbe]::Find(
                [uint32]$targetProcessId)
        )
        $processes += [ordered]@{
            processId = $targetProcessId
            processExists = $null -ne $process
            processPath = $processPath
            sessionCount = $sessions.Count
            sessions = $sessions
        }
    }
    $samples += [ordered]@{
        capturedAtUtc = [DateTimeOffset]::UtcNow.ToString("o")
        processes = $processes
    }
    if ($sampleIndex + 1 -lt $SampleCount) {
        Start-Sleep -Milliseconds $IntervalMilliseconds
    }
}

[ordered]@{
    success = $true
    deviceScope = "default-multimedia-render"
    sampleCount = $SampleCount
    intervalMilliseconds = $IntervalMilliseconds
    samples = $samples
} | ConvertTo-Json -Depth 8
