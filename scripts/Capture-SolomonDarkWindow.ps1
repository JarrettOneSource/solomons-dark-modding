param(
    [string]$ProcessName = "SolomonDark",
    [string]$OutputPath = "runtime/window_capture_bot2.png",
    [int]$DelaySeconds = 0,
    [int]$StartupTimeoutSeconds = 30
)

if ($DelaySeconds -gt 0) {
    Start-Sleep -Seconds $DelaySeconds
}

Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class WindowCaptureNative
{
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll")]
    public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

function Test-IsMostlyBlack {
    param(
        [System.Drawing.Bitmap]$Bitmap
    )

    $samplePoints = @(
        [System.Drawing.Point]::new([int]($Bitmap.Width * 0.25), [int]($Bitmap.Height * 0.25)),
        [System.Drawing.Point]::new([int]($Bitmap.Width * 0.50), [int]($Bitmap.Height * 0.25)),
        [System.Drawing.Point]::new([int]($Bitmap.Width * 0.75), [int]($Bitmap.Height * 0.25)),
        [System.Drawing.Point]::new([int]($Bitmap.Width * 0.25), [int]($Bitmap.Height * 0.50)),
        [System.Drawing.Point]::new([int]($Bitmap.Width * 0.50), [int]($Bitmap.Height * 0.50)),
        [System.Drawing.Point]::new([int]($Bitmap.Width * 0.75), [int]($Bitmap.Height * 0.50)),
        [System.Drawing.Point]::new([int]($Bitmap.Width * 0.25), [int]($Bitmap.Height * 0.75)),
        [System.Drawing.Point]::new([int]($Bitmap.Width * 0.50), [int]($Bitmap.Height * 0.75)),
        [System.Drawing.Point]::new([int]($Bitmap.Width * 0.75), [int]($Bitmap.Height * 0.75))
    )

    foreach ($point in $samplePoints) {
        $pixel = $Bitmap.GetPixel($point.X, $point.Y)
        if (($pixel.R + $pixel.G + $pixel.B) -gt 24) {
            return $false
        }
    }

    return $true
}

$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
$process = $null
while ((Get-Date) -lt $deadline) {
    $process = Get-Process $ProcessName -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 } |
        Select-Object -First 1
    if ($process) {
        break
    }

    Start-Sleep -Milliseconds 250
}

if (-not $process) {
    throw "Process '$ProcessName' was not found within ${StartupTimeoutSeconds}s."
}

$rect = New-Object WindowCaptureNative+RECT
[void][WindowCaptureNative]::GetWindowRect($process.MainWindowHandle, [ref]$rect)

$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -le 0 -or $height -le 0) {
    throw "Invalid window bounds: ${width}x${height}."
}

$outputDirectory = Split-Path -Parent $OutputPath
if ($outputDirectory -and -not (Test-Path $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)

$shell = New-Object -ComObject WScript.Shell
[void][WindowCaptureNative]::ShowWindow($process.MainWindowHandle, 9)
[void][WindowCaptureNative]::SetForegroundWindow($process.MainWindowHandle)
[void]$shell.AppActivate($process.Id)
Start-Sleep -Milliseconds 500

$hdc = $graphics.GetHdc()
$printWindowOk = $false
try {
    $printWindowOk = [WindowCaptureNative]::PrintWindow($process.MainWindowHandle, $hdc, 2)
}
finally {
    $graphics.ReleaseHdc($hdc)
}

if ((-not $printWindowOk) -or (Test-IsMostlyBlack -Bitmap $bitmap)) {
    $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
}

$bitmap.Save($OutputPath)
$graphics.Dispose()
$bitmap.Dispose()

Write-Output $OutputPath
