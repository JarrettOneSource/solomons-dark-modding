[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$')]
    [string]$Instance,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [int]::MaxValue)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [float]$ClientX,

    [Parameter(Mandatory = $true)]
    [float]$ClientY
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).ProviderPath
$expectedExecutable = [IO.Path]::GetFullPath((Join-Path $root (
    'runtime\instances\' + $Instance.ToLowerInvariant() +
    '\stage\SolomonDark.exe'
)))
$processRecord = Get-CimInstance Win32_Process -Filter (
    'ProcessId = ' + $ProcessId
)
if (
    $null -eq $processRecord -or
    $null -eq $processRecord.ExecutablePath -or
    -not [string]::Equals(
        [IO.Path]::GetFullPath($processRecord.ExecutablePath),
        $expectedExecutable,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "PID $ProcessId does not own the exact $Instance staged executable."
}

if (-not ('MenureNativeInput' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class MenureNativeInput
{
    [StructLayout(LayoutKind.Sequential)]
    public struct Point
    {
        public int X;
        public int Y;
    }

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool ClientToScreen(IntPtr window, ref Point point);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(
        IntPtr window,
        out uint processId
    );

    [DllImport("kernel32.dll")]
    public static extern uint GetCurrentThreadId();

    [DllImport("user32.dll")]
    public static extern bool AttachThreadInput(
        uint firstThread,
        uint secondThread,
        bool attach
    );

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr window);

    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr window);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr window, int command);

    [DllImport("user32.dll")]
    public static extern void mouse_event(
        uint flags,
        uint x,
        uint y,
        uint data,
        UIntPtr extraInfo
    );
}
'@
}

$process = Get-Process -Id $ProcessId
$window = $process.MainWindowHandle
if ($window -eq [IntPtr]::Zero) {
    throw "PID $ProcessId has no main window."
}

$point = [MenureNativeInput+Point]::new()
$point.X = [int][Math]::Round($ClientX)
$point.Y = [int][Math]::Round($ClientY)
if (-not [MenureNativeInput]::ClientToScreen($window, [ref]$point)) {
    throw 'ClientToScreen failed.'
}

$foregroundWindow = [MenureNativeInput]::GetForegroundWindow()
[uint32]$foregroundProcessId = 0
$foregroundThread = [MenureNativeInput]::GetWindowThreadProcessId(
    $foregroundWindow,
    [ref]$foregroundProcessId
)
$currentThread = [MenureNativeInput]::GetCurrentThreadId()
$attached = [MenureNativeInput]::AttachThreadInput(
    $currentThread,
    $foregroundThread,
    $true
)
try {
    [MenureNativeInput]::ShowWindow($window, 5) | Out-Null
    [MenureNativeInput]::BringWindowToTop($window) | Out-Null
    $setForeground = [MenureNativeInput]::SetForegroundWindow($window)
}
finally {
    if ($attached) {
        [MenureNativeInput]::AttachThreadInput(
            $currentThread,
            $foregroundThread,
            $false
        ) | Out-Null
    }
}
Start-Sleep -Milliseconds 500
$foregroundWindow = [MenureNativeInput]::GetForegroundWindow()
[uint32]$foregroundProcessId = 0
[MenureNativeInput]::GetWindowThreadProcessId(
    $foregroundWindow,
    [ref]$foregroundProcessId
) | Out-Null
if ($foregroundProcessId -ne $ProcessId) {
    throw (
        "PID $ProcessId did not become the foreground owner " +
        "(SetForegroundWindow=$setForeground)."
    )
}
if (-not [MenureNativeInput]::SetCursorPos($point.X, $point.Y)) {
    throw 'SetCursorPos failed.'
}

[MenureNativeInput]::mouse_event(
    0x0001,
    0,
    0,
    0,
    [UIntPtr]::Zero
)
Start-Sleep -Milliseconds 1000
[MenureNativeInput]::mouse_event(
    0x0002,
    0,
    0,
    0,
    [UIntPtr]::Zero
)
Start-Sleep -Milliseconds 250
[MenureNativeInput]::mouse_event(
    0x0004,
    0,
    0,
    0,
    [UIntPtr]::Zero
)

[ordered]@{
    process_id = $ProcessId
    executable_path = $expectedExecutable
    client_x = [double]$ClientX
    client_y = [double]$ClientY
    screen_x = $point.X
    screen_y = $point.Y
    foreground_process_id = $foregroundProcessId
    capture_method = 'queried live control rect center + exact-PID Windows client click'
} | ConvertTo-Json -Compress
