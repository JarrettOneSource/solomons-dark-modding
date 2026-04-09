param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [switch]$LaunchAndVerifyLoader
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$buildScript = Join-Path $PSScriptRoot "Build-All.ps1"
$resetScript = Join-Path $PSScriptRoot "Reset-LocalRuntimeState.ps1"
$launcher = Join-Path $root "dist/launcher/SolomonDarkModLauncher.exe"
$stageBinaryLayout = Join-Path $root "runtime/stage/.sdmod/config/binary-layout.ini"
$stageDebugUiConfig = Join-Path $root "runtime/stage/.sdmod/config/debug-ui.ini"
$loaderLog = Join-Path $root "runtime/stage/.sdmod/logs/solomondarkmodloader.log"

function Assert-LastExitCode {
    param([string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Launcher {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $launcher @Arguments
    Assert-LastExitCode "Launcher command '$($Arguments -join ' ')'"
}

function Wait-ForFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [int]$TimeoutSeconds = 10
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $Path) {
            return
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for file: $Path"
}

function Wait-ForFileContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string[]]$Patterns,
        [int]$TimeoutSeconds = 10
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $Path) {
            $content = Get-Content $Path -Raw -ErrorAction SilentlyContinue
            if ($null -ne $content) {
                $allMatched = $true
                foreach ($pattern in $Patterns) {
                    if ($content -notmatch $pattern) {
                        $allMatched = $false
                        break
                    }
                }

                if ($allMatched) {
                    return $content
                }
            }
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for expected log markers in $Path"
}

function Stop-SolomonDarkProcess {
    $gameProcesses = @(Get-Process SolomonDark -ErrorAction SilentlyContinue)
    if ($gameProcesses.Count -gt 0) {
        $gameProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

& $resetScript -KeepAppData

& $buildScript -Configuration $Configuration

Invoke-Launcher -Arguments @("list-mods")
Invoke-Launcher -Arguments @("stage")

if (-not (Test-Path $stageBinaryLayout)) {
    throw "Stage verification failed. Expected staged binary layout was not found at $stageBinaryLayout"
}

if (-not (Test-Path $stageDebugUiConfig)) {
    throw "Stage verification failed. Expected staged debug UI config was not found at $stageDebugUiConfig"
}

if ($LaunchAndVerifyLoader) {
    Stop-SolomonDarkProcess

    if (Test-Path $loaderLog) {
        Remove-Item $loaderLog -Force
    }

    try {
        Invoke-Launcher -Arguments @("launch")
        $loaderLogContent = Wait-ForFileContent -Path $loaderLog -Patterns @(
            "SolomonDarkModLoader attached\.",
            "Binary layout loaded\.",
            "Debug UI config loaded\.",
            "Lua engine stub initialized\."
        )
    }
    finally {
        Stop-SolomonDarkProcess
    }
}

Write-Host "Workspace verification passed."
