param(
    [string]$Instance = "game-over-solo",
    [string]$Preset = "map_create_fire_mind_hub",
    [string]$RuntimeRoot = "",
    [UInt16]$LocalPort = 47780,
    [UInt16]$UnusedRemotePort = 47781,
    [string]$ParticipantId = "0x2000000000001A01",
    [string]$PlayerName = "Solo Player",
    [string]$GameDirectory = "",
    [string]$LauncherPath = "",
    [switch]$FreshInstall,
    [switch]$QuickStart,
    [string]$QuickStartElement = "fire",
    [string]$QuickStartDiscipline = "mind",
    [string]$ExactModIds = "",
    [string]$BotSettingsPath = "",
    [string]$LuaExecTargetModId = "",
    [ValidateRange(2, 4)]
    [int]$MaxParticipants = 2,
    [switch]$EnableNetworkTelemetry,
    [switch]$TestBlankBoneyard,
    [string]$TestWaveOverride = "",
    [switch]$Headless,
    [switch]$DisableMultiplayerTransport,
    [switch]$EnableAudio,
    [string]$ProcessIdOutputPath = "",
    [string]$ResultOutputPath = ""
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"
$audioEnabled = $EnableAudio -or $env:SDMOD_ENABLE_AUDIO -eq "1"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$launcher = if ([string]::IsNullOrWhiteSpace($LauncherPath)) {
    Join-Path $root "dist\launcher\SolomonDarkModLauncher.exe"
} else {
    (Resolve-Path -LiteralPath $LauncherPath).ProviderPath
}
$launcherDir = Split-Path $launcher -Parent
$launcherProcessHelpers =
    Join-Path $PSScriptRoot "LocalMultiplayerLauncher.Process.ps1"

if ($Instance.Length -gt 48 -or
    $Instance -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
    throw "Instance must be 1-48 filename-safe characters."
}
if ($LocalPort -eq $UnusedRemotePort) {
    throw "LocalPort and UnusedRemotePort must be distinct."
}
if (-not (Test-Path $launcher)) {
    throw "Launcher was not found at $launcher. Build and stage it first."
}
if (-not (Test-Path $launcherProcessHelpers)) {
    throw "Launcher process helpers were not found at $launcherProcessHelpers."
}

. $launcherProcessHelpers

$runtimeRootOverride = Resolve-MultiplayerRuntimeRootOverride `
    -RootPath $root `
    -RequestedRuntimeRoot $RuntimeRoot
$effectiveRuntimeRoot = if ([string]::IsNullOrWhiteSpace(
        $runtimeRootOverride)) {
    Join-Path $root "runtime"
} else {
    $runtimeRootOverride
}
$instanceRoot = Join-Path $effectiveRuntimeRoot (
    Join-Path "instances" $Instance.ToLowerInvariant())
$expectedExecutable = [System.IO.Path]::GetFullPath(
    (Join-Path $instanceRoot "stage\SolomonDark.exe")
)
$conflict = Get-CimInstance Win32_Process |
    Where-Object {
        $null -ne $_.ExecutablePath -and
        [string]::Equals(
            [System.IO.Path]::GetFullPath($_.ExecutablePath),
            $expectedExecutable,
            [System.StringComparison]::OrdinalIgnoreCase)
    } |
    Select-Object ProcessId, ExecutablePath
if ($null -ne $conflict) {
    throw "The exact local-solo stage already has a live process: $($conflict | ConvertTo-Json -Compress)"
}
$portOwner = @(
    Get-NetUDPEndpoint -LocalPort $LocalPort -ErrorAction SilentlyContinue
)
if ($portOwner.Count -ne 0) {
    throw "UDP port $LocalPort is already owned; no process was touched."
}

$resolvedTestWaveOverride = ""
if (-not [string]::IsNullOrWhiteSpace($TestWaveOverride)) {
    $resolvedWaveOverrideItem =
        Get-Item -LiteralPath $TestWaveOverride -ErrorAction Stop
    if ($resolvedWaveOverrideItem.PSIsContainer -or
        $resolvedWaveOverrideItem.Extension -notmatch '^\.txt$') {
        throw "Test wave override must be a .txt file: $TestWaveOverride"
    }
    $resolvedTestWaveOverride = $resolvedWaveOverrideItem.FullName
}

if (-not [string]::IsNullOrWhiteSpace($ExactModIds)) {
    Set-ExactMultiplayerModState `
        -RuntimeRootPath $effectiveRuntimeRoot `
        -Instance $Instance `
        -ModIds $ExactModIds.Split(',')
}
if (-not [string]::IsNullOrWhiteSpace($BotSettingsPath)) {
    $settingsSource = (
        Get-Item -LiteralPath $BotSettingsPath -ErrorAction Stop
    ).FullName
    $settingsDestination = Join-Path (
        Join-Path $instanceRoot "stage\.sdmod\mod-settings"
    ) "bot.brain.json"
    [System.IO.Directory]::CreateDirectory(
        (Split-Path -Parent $settingsDestination)
    ) | Out-Null
    Copy-Item `
        -LiteralPath $settingsSource `
        -Destination $settingsDestination `
        -Force
}

$pipeName = "SolomonDarkModLoader_LuaExec_$Instance"
$environment = @{
    SDMOD_UI_SANDBOX_PRESET = $Preset
    SDMOD_LUA_EXEC_PIPE_NAME = $pipeName
    SDMOD_LUA_EXEC_TARGET_MOD_ID = $LuaExecTargetModId
    SDMOD_MULTIPLAYER_MAX_PARTICIPANTS = [string]$MaxParticipants
    SDMOD_MULTIPLAYER_QUICK_START = $(if ($QuickStart) { "1" } else { "" })
    SDMOD_MULTIPLAYER_QUICK_START_ELEMENT = $(if (
        $QuickStart) { $QuickStartElement } else { "" })
    SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE = $(if (
        $QuickStart) { $QuickStartDiscipline } else { "" })
    SDMOD_TEST_BLANK_BONEYARD = $(if ($TestBlankBoneyard) { "1" } else { "" })
    SDMOD_TEST_WAVE_OVERRIDE = $resolvedTestWaveOverride
    SDMOD_NETWORK_TELEMETRY = $(if (
        $EnableNetworkTelemetry) { "1" } else { "" })
}
if (-not $audioEnabled) {
    $environment["SDMOD_DISABLE_AUDIO"] = "1"
    $environment["SDMOD_ENABLE_AUDIO"] = "0"
}
if (-not $DisableMultiplayerTransport) {
    $environment.SDMOD_MULTIPLAYER_TRANSPORT = "local_udp"
    $environment.SDMOD_MULTIPLAYER_ROLE = "host"
    $environment.SDMOD_MULTIPLAYER_LOCAL_PORT = [string]$LocalPort
    $environment.SDMOD_MULTIPLAYER_REMOTE_HOST = "127.0.0.1"
    $environment.SDMOD_MULTIPLAYER_REMOTE_PORT = [string]$UnusedRemotePort
    $environment.SDMOD_MULTIPLAYER_PARTICIPANT_ID = $ParticipantId
    $environment.SDMOD_MULTIPLAYER_PLAYER_NAME = $PlayerName
} else {
    $environment.SDMOD_MULTIPLAYER_TRANSPORT = ""
    $environment.SDMOD_MULTIPLAYER_ROLE = ""
    $environment.SDMOD_MULTIPLAYER_LOCAL_PORT = ""
    $environment.SDMOD_MULTIPLAYER_REMOTE_HOST = ""
    $environment.SDMOD_MULTIPLAYER_REMOTE_PORT = ""
    $environment.SDMOD_MULTIPLAYER_PARTICIPANT_ID = ""
    $environment.SDMOD_MULTIPLAYER_PLAYER_NAME = ""
}
$arguments = @(
    "--json",
    "launch",
    "--instance", $Instance,
    "--runtime-flag", "multiplayer.steam_bootstrap=false"
)
if ($FreshInstall) {
    $arguments += "--fresh-install"
} else {
    $arguments += "--temporary-profile"
}
if (-not $audioEnabled) {
    $arguments += "--disable-audio"
}
if ($Headless) {
    $arguments += "--headless"
}
if (-not [string]::IsNullOrWhiteSpace($GameDirectory)) {
    $arguments += @("--game-dir", $GameDirectory)
}
if (-not [string]::IsNullOrWhiteSpace($runtimeRootOverride)) {
    $arguments += @("--runtime-root", $runtimeRootOverride)
}

$result = Invoke-LauncherWithEnvironment `
    -LauncherPath $launcher `
    -WorkingDirectory $launcherDir `
    -Environment $environment `
    -Arguments $arguments

$processId = [int]$result.launch.processId
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
if (
    $null -eq $process -or
    $null -eq $process.ExecutablePath -or
    -not [string]::Equals(
        [System.IO.Path]::GetFullPath($process.ExecutablePath),
        $expectedExecutable,
        [System.StringComparison]::OrdinalIgnoreCase)
) {
    throw "Launcher returned a process that does not own the exact staged executable."
}

$summary = [ordered]@{
    success = $true
    instance = $Instance
    preset = $Preset
    processId = $processId
    participantId = $ParticipantId
    playerName = $PlayerName
    localPort = [int]$LocalPort
    unusedRemotePort = [int]$UnusedRemotePort
    luaPipe = $pipeName
    startupLogPath = $result.launch.startupLogPath
    audioDisabled = -not [bool]$audioEnabled
    maxParticipants = $MaxParticipants
    telemetryEnabled = [bool]$EnableNetworkTelemetry
    headlessEnabled = [bool]$Headless
    multiplayerTransportEnabled = -not [bool]$DisableMultiplayerTransport
    testBlankBoneyardEnabled = [bool]$TestBlankBoneyard
    testWaveOverride = $resolvedTestWaveOverride
    runtimeRoot = $effectiveRuntimeRoot
    executablePath = Join-Path $instanceRoot "stage\SolomonDark.exe"
}
$summaryJson = $summary | ConvertTo-Json -Depth 4 -Compress
if (-not [string]::IsNullOrWhiteSpace($ProcessIdOutputPath)) {
    $outputParent = Split-Path -Parent $ProcessIdOutputPath
    if (-not [string]::IsNullOrWhiteSpace($outputParent)) {
        [System.IO.Directory]::CreateDirectory(
            $outputParent
        ) | Out-Null
    }
    [System.IO.File]::WriteAllText(
        $ProcessIdOutputPath,
        $summaryJson)
}
if (-not [string]::IsNullOrWhiteSpace($ResultOutputPath)) {
    $resultParent = Split-Path -Parent $ResultOutputPath
    if (-not [string]::IsNullOrWhiteSpace($resultParent)) {
        [System.IO.Directory]::CreateDirectory($resultParent) | Out-Null
    }
    [System.IO.File]::WriteAllText($ResultOutputPath, $summaryJson)
}
$summaryJson
