param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [switch]$LaunchAndVerifyLoader,
    [string]$GameDirectory = "",
    [string]$InstanceName = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$buildScript = Join-Path $PSScriptRoot "Build-All.ps1"
$sourceOrganizationScript = Join-Path $PSScriptRoot "Check-SourceOrganization.ps1"
$launcher = Join-Path $root "dist/launcher/SolomonDarkModLauncher.exe"
if ([string]::IsNullOrWhiteSpace($InstanceName)) {
    $InstanceName = "verify-$PID-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
}
$instanceRoot = Join-Path $root "runtime/instances/$InstanceName"
$stageBinaryLayout = Join-Path $instanceRoot "stage/.sdmod/config/binary-layout.ini"
$stageDebugUiConfig = Join-Path $instanceRoot "stage/.sdmod/config/debug-ui.ini"
$commonLauncherArguments = @("--instance", $InstanceName)
if (-not [string]::IsNullOrWhiteSpace($GameDirectory)) {
    $commonLauncherArguments += @("--game-dir", $GameDirectory)
}

function Assert-LastExitCode {
    param([string]$Step)

    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
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

function Invoke-LauncherJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = & $launcher @Arguments
    Assert-LastExitCode "Launcher command '$($Arguments -join ' ')'"
    $text = $output -join [Environment]::NewLine
    try {
        $result = $text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Launcher command did not return valid JSON: $text"
    }
    if (-not $result.success) {
        throw "Launcher command failed: $($result.error)"
    }
    return $result
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
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return
    }
    $gameProcess = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -eq "SolomonDark" }
    if ($null -ne $gameProcess) {
        $gameProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

if (Test-Path $instanceRoot) {
    Remove-Item $instanceRoot -Recurse -Force
}

& $sourceOrganizationScript
Assert-LastExitCode "Source organization check"

& $buildScript -Configuration $Configuration
Assert-LastExitCode "$Configuration build"

Invoke-Launcher -Arguments (@("list-mods") + $commonLauncherArguments)
Invoke-Launcher -Arguments (@("stage") + $commonLauncherArguments)

if (-not (Test-Path $stageBinaryLayout)) {
    throw "Stage verification failed. Expected staged binary layout was not found at $stageBinaryLayout"
}

if (-not (Test-Path $stageDebugUiConfig)) {
    throw "Stage verification failed. Expected staged debug UI config was not found at $stageDebugUiConfig"
}

if ($LaunchAndVerifyLoader) {
    $processId = 0
    try {
        $launchResult = Invoke-LauncherJson -Arguments (
            @("launch", "--json", "--temporary-profile") +
            $commonLauncherArguments
        )
        $processId = [int]$launchResult.launch.processId
        $loaderLog = [string]$launchResult.launch.startupLogPath
        if ([string]::IsNullOrWhiteSpace($loaderLog)) {
            throw "Launcher did not report the instance loader log path."
        }
        $loaderLogContent = Wait-ForFileContent -Path $loaderLog -Patterns @(
            "SolomonDarkModLoader attached\.",
            "Binary layout loaded\.",
            "Debug UI config loaded\.",
            "Lua engine stub initialized\."
        )
    }
    finally {
        Stop-SolomonDarkProcess -ProcessId $processId
    }
}

Write-Host "Workspace verification passed for instance '$InstanceName'."
