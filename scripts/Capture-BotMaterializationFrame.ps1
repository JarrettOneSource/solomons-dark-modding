param(
    [string]$OutputPath = "runtime/window_capture_bot2_python_inline.png",
    [int]$TimeoutSeconds = 45,
    [string]$Preset = "enter_gameplay_start_run",
    [string]$ProcessName = "SolomonDark",
    [ValidateSet("screen", "window")]
    [string]$CaptureMethod = "screen",
    [int]$PostMaterializationDelayMs = 0,
    [string]$ReadyPattern = "BOT REGRESSION:"
)

$logPath = "runtime/stage/.sdmod/logs/solomondarkmodloader.log"
Remove-Item $logPath -Force -ErrorAction SilentlyContinue

$start = Get-Date
$absoluteOutputPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputPath))
$env:SDMOD_CAPTURE_OUTPUT = $absoluteOutputPath
$env:PYTHONIOENCODING = "utf-8"

$null = ./scripts/Launch-TestBotSession.ps1 -Preset $Preset

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $logPath) {
        $logItem = Get-Item $logPath
        if ($logItem.LastWriteTime -gt $start -and
            (Select-String -Path $logPath -Pattern $ReadyPattern -Quiet)) {
            break
        }
    }

    Start-Sleep -Milliseconds 100
}

if (-not (Test-Path $logPath)) {
    throw "Fresh log file was not created."
}

$logItem = Get-Item $logPath
if (-not ($logItem.LastWriteTime -gt $start -and
    (Select-String -Path $logPath -Pattern $ReadyPattern -Quiet))) {
    throw "Fresh ready log line matching '$ReadyPattern' was not observed within ${TimeoutSeconds}s."
}

$postMaterializationDelayMs = [Math]::Max(0, $PostMaterializationDelayMs)
if ($postMaterializationDelayMs -gt 0) {
    Start-Sleep -Milliseconds $postMaterializationDelayMs
}

$process = Get-Process $ProcessName -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } |
    Select-Object -First 1
if (-not $process) {
    throw "Process '$ProcessName' with a visible window was not found."
}

$env:SDMOD_CAPTURE_PROCESS_PID = $process.Id.ToString()

$python = @"
import os
import pathlib
import sys

sys.path.insert(0, r"scripts")

import capture_window as cw

window = cw.find_window(None, None, int(os.environ["SDMOD_CAPTURE_PROCESS_PID"]))
output_path = pathlib.Path(os.environ["SDMOD_CAPTURE_OUTPUT"])
capture_method = os.environ["SDMOD_CAPTURE_METHOD"]
if capture_method == "screen":
    cw.activate_window(window.hwnd, 700)
    cw.capture_window_from_screen(window, output_path)
else:
    if not cw.capture_window_from_dc(window, output_path):
        raise RuntimeError("PrintWindow capture failed.")
print(f"captured {window.title} -> {output_path}")
"@

$tempPythonPath = Join-Path $env:TEMP "sdmod_capture_window_inline.py"
Set-Content -Path $tempPythonPath -Value $python -Encoding UTF8
$env:SDMOD_CAPTURE_METHOD = $CaptureMethod
py -3 $tempPythonPath
