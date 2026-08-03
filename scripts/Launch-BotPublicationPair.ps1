[CmdletBinding()]
param(
    [string]$GameDirectory = "C:\Users\User\Documents\GitHub\SB Modding\Solomon Dark\SolomonDarkAbandonware",
    [string]$EvidenceRoot = "D:\codex-evidence\botpub-20260727",
    [string]$DirectoryUrl = "http://127.0.0.1:49411",
    [string]$LobbyId = "76561198000006666",
    [string]$ResultPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "LocalMultiplayerLauncher.Process.ps1")

$launcher = Join-Path $root "dist\launcher\SolomonDarkModLauncher.exe"
Assert-StagedReleaseLoader `
    -Path (Join-Path (Split-Path -Parent $launcher) "SolomonDarkModLoader.dll") |
    Out-Null
$runtimeRoot = Join-Path $EvidenceRoot "launcher\runtime"
$hostModsRoot = Join-Path $EvidenceRoot "launcher\host-mods"
$clientModsRoot = Join-Path $EvidenceRoot "launcher\client-mods"
$hostInstance = "bpub-host"
$clientInstance = "bpub-client"
$hostPort = 49411
$clientPort = 49412
$hostParticipantId = "0x2000000000006601"
$clientParticipantId = "0x2000000000006602"

if (-not $DirectoryUrl.StartsWith(
    "http://127.0.0.1:49411",
    [System.StringComparison]::Ordinal)) {
    throw "The publication verifier only permits the local website on port 49411."
}
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Published launcher not found: $launcher"
}
if (-not (Test-Path -LiteralPath $hostModsRoot -PathType Container)) {
    throw "Website-installed host mod root not found: $hostModsRoot"
}
if (-not (Test-Path -LiteralPath $clientModsRoot -PathType Container)) {
    throw "Isolated client mod root not found: $clientModsRoot"
}
foreach ($port in @($hostPort, $clientPort)) {
    $owner = Get-NetUDPEndpoint `
        -LocalPort $port `
        -ErrorAction SilentlyContinue
    if ($null -ne $owner) {
        throw "Publication UDP port $port is already owned; no process was touched."
    }
}

function Assert-OwnedGameProcess {
    param(
        [Parameter(Mandatory = $true)]
        [object]$LauncherResult,
        [Parameter(Mandatory = $true)]
        [string]$Instance
    )

    $processId = [int]$LauncherResult.launch.processId
    $process = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId=$processId"
    if ($null -eq $process) {
        throw "The $Instance game process exited before ownership could be verified."
    }
    $expected = [System.IO.Path]::GetFullPath(
        (Join-Path $runtimeRoot "instances\$Instance\stage\SolomonDark.exe"))
    if (-not [string]::Equals(
        [System.IO.Path]::GetFullPath([string]$process.ExecutablePath),
        $expected,
        [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The $Instance launch escaped its owned stage: $($process.ExecutablePath)"
    }
    return [pscustomobject]@{
        processId = $processId
        parentProcessId = [int]$process.ParentProcessId
        executablePath = [string]$process.ExecutablePath
    }
}

function Stop-OwnedGameProcess {
    param(
        [object]$LauncherResult,
        [string]$Instance
    )

    if ($null -eq $LauncherResult -or $null -eq $LauncherResult.launch) {
        return
    }
    try {
        $owned = Assert-OwnedGameProcess `
            -LauncherResult $LauncherResult `
            -Instance $Instance
        Stop-Process -Id $owned.processId -ErrorAction Stop
        Wait-Process `
            -Id $owned.processId `
            -Timeout 10 `
            -ErrorAction SilentlyContinue
    } catch {
        Write-Warning "Exact cleanup for $Instance failed: $($_.Exception.Message)"
    }
}

function Start-PublicationInstance {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Instance,
        [Parameter(Mandatory = $true)]
        [ValidateSet("host", "client")]
        [string]$Role,
        [Parameter(Mandatory = $true)]
        [int]$LocalPort,
        [Parameter(Mandatory = $true)]
        [int]$RemotePort,
        [Parameter(Mandatory = $true)]
        [string]$ParticipantId,
        [Parameter(Mandatory = $true)]
        [string]$PlayerName,
        [Parameter(Mandatory = $true)]
        [string]$ModsRoot
    )

    $environment = @{
        SDMOD_DISABLE_AUDIO = "1"
        SDMOD_ENABLE_AUDIO = "0"
        SDMOD_LUA_EXEC_PIPE_NAME = "SolomonDarkModLoader_LuaExec_$Instance"
        SDMOD_MULTIPLAYER_LOCAL_PORT = [string]$LocalPort
        SDMOD_MULTIPLAYER_PARTICIPANT_ID = $ParticipantId
        SDMOD_MULTIPLAYER_PLAYER_NAME = $PlayerName
        SDMOD_MULTIPLAYER_QUICK_START = "1"
        SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE = "mind"
        SDMOD_MULTIPLAYER_QUICK_START_ELEMENT = "fire"
        SDMOD_MULTIPLAYER_REMOTE_HOST = "127.0.0.1"
        SDMOD_MULTIPLAYER_REMOTE_PORT = [string]$RemotePort
        SDMOD_MULTIPLAYER_ROLE = $Role
        SDMOD_MULTIPLAYER_TRANSPORT = "local_udp"
        SDMOD_UI_SANDBOX_PRESET = "map_create_fire_mind_hub"
    }
    $arguments = @(
        "--json",
        "launch",
        "--instance", $Instance,
        "--game-dir", $GameDirectory,
        "--mods-root", $ModsRoot,
        "--runtime-root", $runtimeRoot,
        "--directory-url", $DirectoryUrl,
        "--runtime-flag", "multiplayer.steam_bootstrap=false",
        "--temporary-profile",
        "--disable-audio"
    )
    if ($Role -eq "client") {
        $arguments += @(
            "--multiplayer", "join",
            "--lobby-id", $LobbyId
        )
    }

    return Invoke-LauncherWithEnvironment `
        -LauncherPath $launcher `
        -WorkingDirectory (Split-Path -Parent $launcher) `
        -Environment $environment `
        -Arguments $arguments `
        -TimeoutSeconds 90
}

$hostResult = $null
$clientResult = $null
try {
    $hostResult = Start-PublicationInstance `
        -Instance $hostInstance `
        -Role host `
        -LocalPort $hostPort `
        -RemotePort $clientPort `
        -ParticipantId $hostParticipantId `
        -PlayerName "Bpub Host" `
        -ModsRoot $hostModsRoot
    $hostOwned = Assert-OwnedGameProcess `
        -LauncherResult $hostResult `
        -Instance $hostInstance

    Start-Sleep -Seconds 2

    $clientResult = Start-PublicationInstance `
        -Instance $clientInstance `
        -Role client `
        -LocalPort $clientPort `
        -RemotePort $hostPort `
        -ParticipantId $clientParticipantId `
        -PlayerName "Bpub Client" `
        -ModsRoot $clientModsRoot
    $clientOwned = Assert-OwnedGameProcess `
        -LauncherResult $clientResult `
        -Instance $clientInstance

    $publicationResult = [pscustomobject]@{
        success = $true
        instancePrefix = "bpub"
        ports = [ordered]@{
            host = $hostPort
            client = $clientPort
        }
        audioDisabled = $true
        lobbyId = $LobbyId
        directoryUrl = $DirectoryUrl
        host = [ordered]@{
            process = $hostOwned
            launcher = $hostResult
        }
        client = [ordered]@{
            process = $clientOwned
            launcher = $clientResult
        }
    }
    $publicationJson = $publicationResult |
        ConvertTo-Json -Depth 20 -Compress
    if (-not [string]::IsNullOrWhiteSpace($ResultPath)) {
        $resultDirectory = Split-Path -Parent $ResultPath
        [System.IO.Directory]::CreateDirectory($resultDirectory) | Out-Null
        $temporaryResultPath =
            "$ResultPath.$PID.$([System.Diagnostics.Stopwatch]::GetTimestamp()).tmp"
        [System.IO.File]::WriteAllText(
            $temporaryResultPath,
            $publicationJson + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false))
        if ([System.IO.File]::Exists($ResultPath)) {
            [System.IO.File]::Delete($ResultPath)
        }
        [System.IO.File]::Move($temporaryResultPath, $ResultPath)
    }
    Write-Output $publicationJson
} catch {
    Stop-OwnedGameProcess `
        -LauncherResult $clientResult `
        -Instance $clientInstance
    Stop-OwnedGameProcess `
        -LauncherResult $hostResult `
        -Instance $hostInstance
    throw
}
