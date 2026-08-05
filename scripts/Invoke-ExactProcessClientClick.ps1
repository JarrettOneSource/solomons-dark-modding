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
    public static extern bool SetForegroundWindow(IntPtr window);

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

[MenureNativeInput]::SetForegroundWindow($window) | Out-Null
Start-Sleep -Milliseconds 100
if (-not [MenureNativeInput]::SetCursorPos($point.X, $point.Y)) {
    throw 'SetCursorPos failed.'
}

[MenureNativeInput]::mouse_event(
    0x0002,
    0,
    0,
    0,
    [UIntPtr]::Zero
)
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
    capture_method = 'queried live control rect center + exact-PID Windows client click'
} | ConvertTo-Json -Compress
