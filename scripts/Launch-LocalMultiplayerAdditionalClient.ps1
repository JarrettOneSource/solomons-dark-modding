param(
    [string]$Instance = "local-mp-third",
    [string]$Preset = "create_manual",
    [UInt16]$LocalPort = 47772,
    [string]$ParticipantId = "0x2000000000001003",
    [string]$PlayerName = "Observer Player",
    [string]$HostName = "Host Player",
    [string]$RemoteHost = "127.0.0.1",
    [UInt16]$HostPort = 47770,
    [switch]$GodMode,
    [string]$TestSurvivalBoneyardOverride = "",
    [switch]$TestBlankBoneyard,
    [string]$TestWaveOverride = ""
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$launcher = Join-Path $root "dist\launcher\SolomonDarkModLauncher.exe"
$launcherDir = Split-Path $launcher -Parent
$launcherProcessHelpers = Join-Path $PSScriptRoot "LocalMultiplayerLauncher.Process.ps1"

if (-not (Test-Path $launcher)) {
    throw "Launcher was not found at $launcher. Build and stage the launcher first."
}
if (-not (Test-Path $launcherProcessHelpers)) {
    throw "Launcher process helpers were not found at $launcherProcessHelpers."
}

. $launcherProcessHelpers

$resolvedOverride = ""
if (-not [string]::IsNullOrWhiteSpace($TestSurvivalBoneyardOverride)) {
    $overrideItem = Get-Item -LiteralPath $TestSurvivalBoneyardOverride -ErrorAction Stop
    if ($overrideItem.PSIsContainer -or $overrideItem.Extension -notmatch '^\.boneyard$') {
        throw "Test survival boneyard override must be a .boneyard file: $TestSurvivalBoneyardOverride"
    }
    $resolvedOverride = $overrideItem.FullName
}

$resolvedWaveOverride = ""
if (-not [string]::IsNullOrWhiteSpace($TestWaveOverride)) {
    $waveOverrideItem = Get-Item -LiteralPath $TestWaveOverride -ErrorAction Stop
    if ($waveOverrideItem.PSIsContainer -or $waveOverrideItem.Extension -notmatch '^\.txt$') {
        throw "Test wave override must be a .txt file: $TestWaveOverride"
    }
    $resolvedWaveOverride = $waveOverrideItem.FullName
}

$pipeName = "SolomonDarkModLoader_LuaExec_$Instance"
$environment = @{
    SDMOD_UI_SANDBOX_PRESET = $Preset
    SDMOD_LUA_EXEC_PIPE_NAME = $pipeName
    SDMOD_MULTIPLAYER_TRANSPORT = "local_udp"
    SDMOD_MULTIPLAYER_ROLE = "client"
    SDMOD_MULTIPLAYER_LOCAL_PORT = [string]$LocalPort
    SDMOD_MULTIPLAYER_REMOTE_HOST = $RemoteHost
    SDMOD_MULTIPLAYER_REMOTE_PORT = [string]$HostPort
    SDMOD_MULTIPLAYER_PARTICIPANT_ID = $ParticipantId
    SDMOD_MULTIPLAYER_PLAYER_NAME = $PlayerName
}
if ($GodMode) {
    $environment.SDMOD_MULTIPLAYER_GODMODE = "1"
}
if (-not [string]::IsNullOrWhiteSpace($resolvedOverride)) {
    $environment.SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE = $resolvedOverride
}
if ($TestBlankBoneyard) {
    $environment.SDMOD_TEST_BLANK_BONEYARD = "1"
}
if (-not [string]::IsNullOrWhiteSpace($resolvedWaveOverride)) {
    $environment.SDMOD_TEST_WAVE_OVERRIDE = $resolvedWaveOverride
}

$arguments = @(
    "--json",
    "launch",
    "--instance", $Instance,
    "--runtime-flag", "multiplayer.steam_bootstrap=false",
    "--temporary-profile"
)
$result = Invoke-LauncherWithEnvironment `
    -LauncherPath $launcher `
    -WorkingDirectory $launcherDir `
    -Environment $environment `
    -Arguments $arguments

[pscustomobject]@{
    success = $true
    instance = $Instance
    preset = $Preset
    processId = $result.launch.processId
    participantId = $ParticipantId
    playerName = $PlayerName
    localPort = $LocalPort
    hostPort = $HostPort
    luaPipe = $pipeName
    startupLogPath = $result.launch.startupLogPath
    testSurvivalBoneyardOverride = $resolvedOverride
    testBlankBoneyardEnabled = [bool]$TestBlankBoneyard
    testWaveOverride = $resolvedWaveOverride
} | ConvertTo-Json -Depth 4 -Compress
