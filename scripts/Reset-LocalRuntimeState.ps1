param(
    [switch]$KeepRuntimeWorkspace,
    [int[]]$OwnedProcessIds = @()
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $root "runtime"
$distRoot = Join-Path $root "dist"

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

foreach ($processId in @($OwnedProcessIds | Sort-Object -Unique)) {
    if ($processId -le 0) {
        continue
    }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -ne $process -and $process.ProcessName -eq "SolomonDark") {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

if (-not $KeepRuntimeWorkspace -and (Test-Path $runtimeRoot)) {
    Write-Host "Removing runtime workspace: $runtimeRoot"
    Remove-PathWithRetries -PathToRemove $runtimeRoot
}

if (Test-Path $distRoot) {
    Write-Host "Removing dist output: $distRoot"
    Remove-PathWithRetries -PathToRemove $distRoot
}

Write-Host "Reset complete."
