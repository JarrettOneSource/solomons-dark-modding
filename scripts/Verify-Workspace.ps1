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
$launcherProcessHelpers =
    Join-Path $PSScriptRoot "LocalMultiplayerLauncher.Process.ps1"
$launcher = Join-Path $root "dist/launcher/SolomonDarkModLauncher.exe"
$launcherDirectory = Split-Path -Parent $launcher
if (-not (Test-Path $launcherProcessHelpers)) {
    throw "Launcher process helpers were not found at $launcherProcessHelpers"
}
. $launcherProcessHelpers

if ([string]::IsNullOrWhiteSpace($InstanceName)) {
    $InstanceName =
        "verify-$PID-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
}
if ($InstanceName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
    throw "InstanceName must be 1-64 filename-safe characters."
}
$InstanceName = $InstanceName.ToLowerInvariant()

$gameSearchRoot = $root
for ($depth = 0;
     $depth -lt 4 -and [string]::IsNullOrWhiteSpace($GameDirectory);
     $depth++) {
    $gameSearchRoot = Split-Path -Parent $gameSearchRoot
    if ([string]::IsNullOrWhiteSpace($gameSearchRoot)) {
        break
    }
    $candidateGameDirectory =
        Join-Path $gameSearchRoot "SolomonDarkAbandonware"
    if (Test-Path (Join-Path $candidateGameDirectory "SolomonDark.exe")) {
        $GameDirectory = $candidateGameDirectory
    }
}
if (-not [string]::IsNullOrWhiteSpace($GameDirectory)) {
    $GameDirectory = [System.IO.Path]::GetFullPath($GameDirectory)
    if (-not (Test-Path (Join-Path $GameDirectory "SolomonDark.exe"))) {
        throw "GameDirectory does not contain SolomonDark.exe: $GameDirectory"
    }
}

$launcherContextArguments = @("--instance", $InstanceName)
if (-not [string]::IsNullOrWhiteSpace($GameDirectory)) {
    $launcherContextArguments += @("--game-dir", $GameDirectory)
}
$instanceRoot = Join-Path $root "runtime/instances/$InstanceName"
$stageBinaryLayout = Join-Path $instanceRoot "stage/.sdmod/config/binary-layout.ini"
$stageDebugUiConfig = Join-Path $instanceRoot "stage/.sdmod/config/debug-ui.ini"

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

    $effectiveArguments = @($Arguments) + $launcherContextArguments
    & $launcher @effectiveArguments
    Assert-LastExitCode "Launcher command '$($Arguments -join ' ')'"
}

function Invoke-LauncherJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    return Invoke-LauncherWithEnvironment `
        -LauncherPath $launcher `
        -WorkingDirectory $launcherDirectory `
        -Environment @{} `
        -Arguments (@("--json") + @($Arguments) + $launcherContextArguments) `
        -TimeoutSeconds 30
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

function Stop-OwnedSolomonDarkProcess {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return
    }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -ne $process -and $process.ProcessName -eq "SolomonDark") {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

if (Test-Path $instanceRoot) {
    Remove-Item $instanceRoot -Recurse -Force
}

& $sourceOrganizationScript
Assert-LastExitCode "Source organization check"

& $buildScript -Configuration $Configuration
Assert-LastExitCode "$Configuration build"

Invoke-Launcher -Arguments @("list-mods")
Invoke-Launcher -Arguments @("stage")

if (-not (Test-Path $stageBinaryLayout)) {
    throw "Stage verification failed. Expected staged binary layout was not found at $stageBinaryLayout"
}

if (-not (Test-Path $stageDebugUiConfig)) {
    throw "Stage verification failed. Expected staged debug UI config was not found at $stageDebugUiConfig"
}

if ($LaunchAndVerifyLoader) {
    $gameProcessId = 0
    try {
        $launchResult = Invoke-LauncherJson -Arguments @(
            "launch",
            "--temporary-profile"
        )
        $gameProcessId = [int]$launchResult.launch.processId
        $loaderLog = [string]$launchResult.launch.startupLogPath
        if ([string]::IsNullOrWhiteSpace($loaderLog)) {
            throw "Launcher did not report the instance loader log path."
        }
        $loaderLogContent = Wait-ForFileContent -Path $loaderLog -Patterns @(
            "SolomonDarkModLoader attached\.",
            "Binary layout loaded\.",
            "Debug UI config loaded\.",
            "Lua engine initialized\."
        )
    }
    finally {
        Stop-OwnedSolomonDarkProcess -ProcessId $gameProcessId
    }
}

Write-Host "Workspace verification passed for instance '$InstanceName'."
