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
    [switch]$EnableAudio,
    [string]$ProcessIdOutputPath = ""
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

if (-not [string]::IsNullOrWhiteSpace($ExactModIds)) {
    Set-ExactMultiplayerModState `
        -RuntimeRootPath $effectiveRuntimeRoot `
        -Instance $Instance `
        -ModIds $ExactModIds.Split(',')
}

$pipeName = "SolomonDarkModLoader_LuaExec_$Instance"
$environment = @{
    SDMOD_UI_SANDBOX_PRESET = $Preset
    SDMOD_LUA_EXEC_PIPE_NAME = $pipeName
    SDMOD_MULTIPLAYER_TRANSPORT = "local_udp"
    SDMOD_MULTIPLAYER_ROLE = "host"
    SDMOD_MULTIPLAYER_LOCAL_PORT = [string]$LocalPort
    SDMOD_MULTIPLAYER_REMOTE_HOST = "127.0.0.1"
    SDMOD_MULTIPLAYER_REMOTE_PORT = [string]$UnusedRemotePort
    SDMOD_MULTIPLAYER_PARTICIPANT_ID = $ParticipantId
    SDMOD_MULTIPLAYER_PLAYER_NAME = $PlayerName
    SDMOD_MULTIPLAYER_QUICK_START = $(if ($QuickStart) { "1" } else { "" })
    SDMOD_MULTIPLAYER_QUICK_START_ELEMENT = $(if (
        $QuickStart) { $QuickStartElement } else { "" })
    SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE = $(if (
        $QuickStart) { $QuickStartDiscipline } else { "" })
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

if (-not [string]::IsNullOrWhiteSpace($ProcessIdOutputPath)) {
    [System.IO.File]::WriteAllText(
        $ProcessIdOutputPath,
        ([pscustomobject]@{
            processId = [int]$result.launch.processId
        } | ConvertTo-Json -Compress)
    )
}

$instanceRoot = Join-Path $effectiveRuntimeRoot (
    Join-Path "instances" $Instance.ToLowerInvariant())
[pscustomobject]@{
    success = $true
    instance = $Instance
    preset = $Preset
    processId = [int]$result.launch.processId
    participantId = $ParticipantId
    playerName = $PlayerName
    localPort = [int]$LocalPort
    unusedRemotePort = [int]$UnusedRemotePort
    luaPipe = $pipeName
    startupLogPath = $result.launch.startupLogPath
    audioDisabled = -not [bool]$audioEnabled
    runtimeRoot = $effectiveRuntimeRoot
    executablePath = Join-Path $instanceRoot "stage\SolomonDark.exe"
} | ConvertTo-Json -Depth 4 -Compress
