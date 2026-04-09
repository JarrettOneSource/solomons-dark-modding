param(
    [switch]$KeepAppData,
    [switch]$KeepRuntimeWorkspace
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $root "runtime"
$distRoot = Join-Path $root "dist"
$appDataRoot = Join-Path $env:APPDATA "solomondark"

function Remove-PathWithRetries {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathToRemove,
        [int]$MaxAttempts = 10,
        [int]$DelayMilliseconds = 250
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        if (-not (Test-Path $PathToRemove)) {
            return
        }

        try {
            Remove-Item $PathToRemove -Recurse -Force -ErrorAction Stop
        }
        catch {
            if ($attempt -eq $MaxAttempts) {
                throw
            }
        }

        if (-not (Test-Path $PathToRemove)) {
            return
        }

        Start-Sleep -Milliseconds $DelayMilliseconds
    }

    if (Test-Path $PathToRemove) {
        throw "Failed to remove path after retries: $PathToRemove"
    }
}

Write-Host "Stopping running SolomonDark.exe processes..."
$gameProcesses = @(Get-Process SolomonDark -ErrorAction SilentlyContinue)
if ($gameProcesses.Count -gt 0) {
    $gameProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
}

if (-not $KeepRuntimeWorkspace -and (Test-Path $runtimeRoot)) {
    Write-Host "Removing runtime workspace: $runtimeRoot"
    Remove-PathWithRetries -PathToRemove $runtimeRoot
}

if (Test-Path $distRoot) {
    Write-Host "Removing dist output: $distRoot"
    Remove-PathWithRetries -PathToRemove $distRoot
}

if (-not $KeepAppData -and (Test-Path $appDataRoot)) {
    Write-Host "Removing APPDATA profile: $appDataRoot"
    Remove-PathWithRetries -PathToRemove $appDataRoot
}

Write-Host "Reset complete."
