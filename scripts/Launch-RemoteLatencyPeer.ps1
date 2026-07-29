param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("host", "client")]
    [string]$Role,
    [Parameter(Mandatory = $true)]
    [UInt16]$LocalPort,
    [Parameter(Mandatory = $true)]
    [string]$RemoteHost,
    [Parameter(Mandatory = $true)]
    [UInt16]$RemotePort,
    [Parameter(Mandatory = $true)]
    [string]$ParticipantId,
    [Parameter(Mandatory = $true)]
    [string]$PlayerName,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")]
    [string]$Instance,
    [Parameter(Mandatory = $true)]
    [string]$GameDirectory,
    [Parameter(Mandatory = $true)]
    [string]$RuntimeRoot,
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath,
    [Parameter(Mandatory = $true)]
    [string]$BotSettingsPath,
    [Parameter(Mandatory = $true)]
    [string]$ProcessIdOutputPath,
    [ValidateSet("ether", "fire", "air", "water", "earth")]
    [string]$Element = "fire",
    [ValidateSet("mind", "body", "arcane")]
    [string]$Discipline = "mind",
    [ValidateRange(2, 4)]
    [int]$MaxParticipants = 4
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$processHelpers = Join-Path $PSScriptRoot "LocalMultiplayerLauncher.Process.ps1"
if (-not (Test-Path -LiteralPath $processHelpers -PathType Leaf)) {
    throw "Launcher process helpers were not found: $processHelpers"
}
. $processHelpers

$launcher = (Get-Item -LiteralPath $LauncherPath -ErrorAction Stop).FullName
$game = (Get-Item -LiteralPath $GameDirectory -ErrorAction Stop).FullName
$runtime = [System.IO.Path]::GetFullPath($RuntimeRoot)
$settingsSource = (
    Get-Item -LiteralPath $BotSettingsPath -ErrorAction Stop
).FullName
$output = [System.IO.Path]::GetFullPath($ProcessIdOutputPath)
$launcherDirectory = Split-Path -Parent $launcher
$instanceRoot = Join-Path (
    Join-Path $runtime "instances"
) $Instance.ToLowerInvariant()
$stageRoot = Join-Path $instanceRoot "stage"
$settingsDestination = Join-Path (
    Join-Path $stageRoot ".sdmod\mod-settings"
) "bot.brain.json"

if ($PlayerName -ne "client B" -and $Role -eq "client") {
    throw "The committed WAN harness identifies the second player as client B."
}
if ($LocalPort -notin @(50311, 50312)) {
    throw "The owner-scoped WAN harness only permits local UDP ports 50311/50312."
}
if (-not (Test-Path -LiteralPath $game -PathType Container)) {
    throw "Staged game directory was not found: $game"
}
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Launcher was not found: $launcher"
}
$expectedExecutable = [System.IO.Path]::GetFullPath(
    (Join-Path $stageRoot "SolomonDark.exe")
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
    throw "The exact net-lag stage already has a live process: $($conflict | ConvertTo-Json -Compress)"
}

$portOwner = @(
    Get-NetUDPEndpoint -LocalPort $LocalPort -ErrorAction SilentlyContinue
)
if ($portOwner.Count -ne 0) {
    throw "UDP port $LocalPort is already owned; no process was touched."
}

if (Test-Path -LiteralPath $instanceRoot) {
    Remove-Item -LiteralPath $instanceRoot -Recurse -Force
}

Set-ExactMultiplayerModState `
    -RuntimeRootPath $runtime `
    -Instance $Instance `
    -ModIds @(
        "harness.remote_latency_controller",
        "bot.brain"
    )

[System.IO.Directory]::CreateDirectory(
    (Split-Path -Parent $settingsDestination)
) | Out-Null
Copy-Item `
    -LiteralPath $settingsSource `
    -Destination $settingsDestination `
    -Force

$environment = @{
    SDMOD_UI_SANDBOX_PRESET = "idle"
    SDMOD_LUA_EXEC_PIPE_NAME = "SolomonDarkModLoader_LuaExec_$Instance"
    SDMOD_LUA_EXEC_TARGET_MOD_ID = "harness.remote_latency_controller"
    SDMOD_MULTIPLAYER_QUICK_START = ""
    SDMOD_MULTIPLAYER_QUICK_START_ELEMENT = ""
    SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE = ""
    SDMOD_MULTIPLAYER_QUICK_START_RUN = ""
    SDMOD_MULTIPLAYER_MAX_PARTICIPANTS = [string]$MaxParticipants
    SDMOD_MULTIPLAYER_TRANSPORT = "local_udp"
    SDMOD_MULTIPLAYER_ROLE = $Role
    SDMOD_MULTIPLAYER_LOCAL_PORT = [string]$LocalPort
    SDMOD_MULTIPLAYER_REMOTE_HOST = $RemoteHost
    SDMOD_MULTIPLAYER_REMOTE_PORT = [string]$RemotePort
    SDMOD_MULTIPLAYER_PARTICIPANT_ID = $ParticipantId
    SDMOD_MULTIPLAYER_PLAYER_NAME = $PlayerName
    SDMOD_DISABLE_AUDIO = "1"
    SDMOD_ENABLE_AUDIO = "0"
    SDMOD_NETWORK_TELEMETRY = "1"
}

$arguments = @(
    "--json",
    "launch",
    "--instance", $Instance,
    "--runtime-root", $runtime,
    "--game-dir", $game,
    "--runtime-flag", "multiplayer.steam_bootstrap=false",
    "--temporary-profile",
    "--disable-audio"
)
$result = Invoke-LauncherWithEnvironment `
    -LauncherPath $launcher `
    -WorkingDirectory $launcherDirectory `
    -Environment $environment `
    -Arguments $arguments `
    -TimeoutSeconds 90

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

$payload = [ordered]@{
    role = $Role
    instance = $Instance
    processId = $processId
    executablePath = $expectedExecutable
    localPort = [int]$LocalPort
    remoteHost = $RemoteHost
    remotePort = [int]$RemotePort
    participantId = $ParticipantId
    playerName = $PlayerName
    audioDisabled = $true
    telemetryEnabled = $true
    stageRoot = $stageRoot
    telemetryPath = Join-Path (
        Join-Path $stageRoot ".sdmod\logs"
    ) "network-telemetry.jsonl"
    logPath = Join-Path (
        Join-Path $stageRoot ".sdmod\logs"
    ) "solomondarkmodloader.log"
}
[System.IO.Directory]::CreateDirectory(
    (Split-Path -Parent $output)
) | Out-Null
$json = $payload | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($output, $json)
Write-Output $json
