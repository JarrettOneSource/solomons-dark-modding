param(
    [string]$Preset = "map_create_fire_mind_hub",
    [UInt16]$HostPort = 47770,
    [UInt16]$ClientPort = 47771,
    [string]$RemoteHost = "127.0.0.1",
    [string]$HostParticipantId = "0x2000000000001001",
    [string]$ClientParticipantId = "0x2000000000001002",
    [string]$HostName = "Host Player",
    [string]$ClientName = "Client Player",
    [switch]$DisableMultiplayerTransport,
    [switch]$UseSandboxPresetFlow,
    [switch]$NoKill
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$launcher = Join-Path $root "dist\launcher\SolomonDarkModLauncher.exe"
$launcherDir = Split-Path $launcher -Parent
$luaExecScript = Join-Path $PSScriptRoot "Invoke-LuaExec.ps1"
$clickWindowScript = Join-Path $PSScriptRoot "click_window.py"

if (-not (Test-Path $launcher)) {
    throw "Launcher was not found at $launcher. Build and stage the launcher first."
}
if (-not (Test-Path $luaExecScript)) {
    throw "Lua exec script was not found at $luaExecScript."
}
if (-not (Test-Path $clickWindowScript)) {
    throw "Window click helper was not found at $clickWindowScript."
}

if (-not $NoKill) {
    Get-Process SolomonDark* -ErrorAction SilentlyContinue | Stop-Process -Force
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class SolomonDarkWindowActivator {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

function ConvertTo-ProcessArgument {
    param([string]$Value)

    if ($null -eq $Value -or $Value.Length -eq 0) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes += 1
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-LauncherWithEnvironment {
    param(
        [hashtable]$Environment,
        [string[]]$Arguments
    )

    $previous = @{}
    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    foreach ($key in $Environment.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }

    try {
        $process = Start-Process `
            -FilePath $launcher `
            -ArgumentList (($Arguments | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join " ") `
            -WorkingDirectory $launcherDir `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath `
            -PassThru

        $result = $null
        $stdout = ""
        $stderr = ""
        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline) {
            $process.Refresh()
            $stdout = Get-Content -Path $stdoutPath -Raw -ErrorAction SilentlyContinue
            $stderr = Get-Content -Path $stderrPath -Raw -ErrorAction SilentlyContinue
            if (-not [string]::IsNullOrWhiteSpace($stdout)) {
                try {
                    $result = $stdout | ConvertFrom-Json
                    break
                } catch {
                    $result = $null
                }
            }
            if ($process.HasExited -and $process.ExitCode -ne 0) {
                break
            }
            Start-Sleep -Milliseconds 200
        }

        $exitCode = $null
        if ($process.HasExited) {
            $exitCode = $process.ExitCode
        }
        if ($null -ne $exitCode -and "$exitCode" -ne "" -and $exitCode -ne 0) {
            throw "Launcher failed with exit code $exitCode. Output: $stdout Error: $stderr"
        }
        if ([string]::IsNullOrWhiteSpace($stdout)) {
            throw "Launcher produced no JSON output. Error: $stderr"
        }
        if ($null -eq $result) {
            throw "Launcher did not produce parseable JSON output before timeout. Output: $stdout Error: $stderr"
        }
        if (-not $result.success) {
            throw "Launcher reported failure: $($result.error)"
        }
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        return $result
    } finally {
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previous[$key], "Process")
        }
        Remove-Item $stdoutPath, $stderrPath -ErrorAction SilentlyContinue
    }
}

function Start-MultiplayerInstance {
    param(
        [string]$Instance,
        [string]$Role,
        [UInt16]$LocalPort,
        [UInt16]$RemotePort,
        [string]$ParticipantId,
        [string]$PlayerName
    )

    $env = @{
        SDMOD_UI_SANDBOX_PRESET = $launchPreset
        SDMOD_LUA_EXEC_PIPE_NAME = "SolomonDarkModLoader_LuaExec_$Instance"
    }
    if (-not $DisableMultiplayerTransport) {
        $env.SDMOD_MULTIPLAYER_TRANSPORT = "local_udp"
        $env.SDMOD_MULTIPLAYER_ROLE = $Role
        $env.SDMOD_MULTIPLAYER_LOCAL_PORT = [string]$LocalPort
        $env.SDMOD_MULTIPLAYER_REMOTE_HOST = $RemoteHost
        $env.SDMOD_MULTIPLAYER_REMOTE_PORT = [string]$RemotePort
        $env.SDMOD_MULTIPLAYER_PARTICIPANT_ID = $ParticipantId
        $env.SDMOD_MULTIPLAYER_PLAYER_NAME = $PlayerName
    } else {
        $env.SDMOD_MULTIPLAYER_TRANSPORT = ""
        $env.SDMOD_MULTIPLAYER_ROLE = ""
        $env.SDMOD_MULTIPLAYER_LOCAL_PORT = ""
        $env.SDMOD_MULTIPLAYER_REMOTE_HOST = ""
        $env.SDMOD_MULTIPLAYER_REMOTE_PORT = ""
        $env.SDMOD_MULTIPLAYER_PARTICIPANT_ID = ""
        $env.SDMOD_MULTIPLAYER_PLAYER_NAME = ""
    }

    $args = @(
        "--json",
        "launch",
        "--instance", $Instance,
        "--runtime-flag", "multiplayer.steam_bootstrap=false"
    )

    Invoke-LauncherWithEnvironment -Environment $env -Arguments $args
}

function Test-PresetWaitsForHub {
    param([string]$PresetName)

    return $PresetName -eq "enter_gameplay_wait" -or $PresetName -match "_hub$"
}

function Resolve-CreateSelection {
    param([string]$PresetName)

    $normalized = $PresetName -replace "_hub$", ""
    if ($normalized -match "^(create_ready|map_create)_([a-z]+)_([a-z]+)$") {
        return @{
            Element = $Matches[2]
            Discipline = $Matches[3]
        }
    }
    if ($normalized -match "^(create_ready|map_create)_([a-z]+)$") {
        return @{
            Element = $Matches[2]
            Discipline = "arcane"
        }
    }
    return $null
}

function Invoke-InstanceLuaExec {
    param(
        [string]$PipeName,
        [string]$Code
    )

    $output = & powershell.exe `
        -NoProfile `
        -NonInteractive `
        -ExecutionPolicy Bypass `
        -File $luaExecScript `
        -PipeName $PipeName `
        -Code $Code 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String)
    if ($exitCode -ne 0) {
        throw "Lua exec failed on pipe $PipeName. Output: $text"
    }
    return $text
}

function Convert-KeyValueText {
    param([string]$Text)

    $values = @{}
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match "^([^=]+)=(.*)$") {
            $values[$Matches[1]] = $Matches[2]
        }
    }
    return $values
}

function Wait-InstanceLuaValue {
    param(
        [string]$PipeName,
        [string]$Code,
        [string]$ExpectedValue,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $last = (Invoke-InstanceLuaExec -PipeName $PipeName -Code $Code | Out-String).Trim()
            if ($last -eq $ExpectedValue) {
                return
            }
        } catch {
            $last = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for $ExpectedValue on Lua pipe $PipeName. Last value: $last"
}

function Set-ProcessForeground {
    param([int]$ProcessId)

    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.MainWindowHandle -ne 0) {
            [void][SolomonDarkWindowActivator]::ShowWindow($process.MainWindowHandle, 9)
            [void][SolomonDarkWindowActivator]::BringWindowToTop($process.MainWindowHandle)
            [void][SolomonDarkWindowActivator]::SetForegroundWindow($process.MainWindowHandle)
            Start-Sleep -Milliseconds 400
            return
        }
        Start-Sleep -Milliseconds 100
    }

    throw "Timed out waiting for a foreground-capable window for process $ProcessId."
}

function Get-CreateActionCenter {
    param(
        [string]$PipeName,
        [string]$ActionId
    )

    $escapedActionId = $ActionId.Replace("\", "\\").Replace("'", "\'")
    $resultText = Invoke-InstanceLuaExec `
        -PipeName $PipeName `
        -Code @"
local target = '$escapedActionId'
local snap = sd.ui.get_snapshot()
if type(snap) ~= 'table' then
  error('UI snapshot unavailable')
end
for _, element in ipairs(snap.elements or {}) do
  if element.action_id == target then
    print('x=' .. tostring(((tonumber(element.left) or 0) + (tonumber(element.right) or 0)) / 2))
    print('y=' .. tostring(((tonumber(element.top) or 0) + (tonumber(element.bottom) or 0)) / 2))
    print('owner=' .. tostring(element.surface_object_ptr or 0))
    return
  end
end
error('create action not found: ' .. target)
"@
    $values = Convert-KeyValueText -Text $resultText
    if (-not $values.ContainsKey("x") -or -not $values.ContainsKey("y")) {
        throw "Could not resolve create action $ActionId center on $PipeName. Output: $resultText"
    }

    return @{
        X = [double]$values["x"]
        Y = [double]$values["y"]
        Owner = if ($values.ContainsKey("owner")) { [UInt64]$values["owner"] } else { 0 }
    }
}

function Invoke-CreateWindowClick {
    param(
        [string]$PipeName,
        [string]$ActionId,
        [int]$ProcessId
    )

    $point = Get-CreateActionCenter -PipeName $PipeName -ActionId $ActionId
    Set-ProcessForeground -ProcessId $ProcessId
    $clickOutput = & py -3 $clickWindowScript `
        --pid $ProcessId `
        --x $point.X `
        --y $point.Y `
        --activate `
        --activation-delay-ms 500 `
        --post-delay-ms 250 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Window click for create action $ActionId failed on process $ProcessId. Output: $($clickOutput | Out-String)"
    }
}

function Get-CreateSelectionState {
    param([string]$PipeName)

    $resultText = Invoke-InstanceLuaExec `
        -PipeName $PipeName `
        -Code @"
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local scene = sd.world.get_scene()
local snap = sd.ui.get_snapshot()
local owner = 0
if type(snap) == 'table' then
  for _, element in ipairs(snap.elements or {}) do
    if element.surface_id == 'create' or element.surface_root_id == 'create' then
      owner = tonumber(element.surface_object_ptr) or 0
      break
    end
  end
end
local function read_u32(offset)
  if owner == 0 then return nil end
  local ok, value = pcall(sd.debug.read_u32, owner + offset)
  if ok then return tonumber(value) end
  return nil
end
local function read_u8(offset)
  local value = read_u32(offset)
  if value == nil then return nil end
  return value % 256
end
emit('scene', scene and (scene.name or scene.kind) or '')
emit('ui', snap and snap.surface_id or '')
emit('owner', owner)
emit('element_selected', read_u32(0x1A4))
emit('discipline_enabled', read_u8(0x228))
emit('discipline_selected', read_u32(0x22C))
"@
    return Convert-KeyValueText -Text $resultText
}

function Test-CreateSelectionUnset {
    param([object]$Value)

    $text = [string]$Value
    return [string]::IsNullOrWhiteSpace($text) -or $text -eq "-1" -or $text -eq "4294967295"
}

function Wait-CreateElementLatched {
    param(
        [string]$PipeName,
        [int]$TimeoutSeconds = 8
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $state = Get-CreateSelectionState -PipeName $PipeName
        if (-not (Test-CreateSelectionUnset $state["element_selected"]) -and
            $state["discipline_enabled"] -ne "0") {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }

    return $false
}

function Wait-CreateDisciplineAccepted {
    param(
        [string]$PipeName,
        [int]$TimeoutSeconds = 10
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $state = Get-CreateSelectionState -PipeName $PipeName
        if ($state["scene"] -eq "hub" -or $state["ui"] -ne "create" -or
            -not (Test-CreateSelectionUnset $state["discipline_selected"])) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }

    return $false
}

function Invoke-UiActionAndWait {
    param(
        [string]$PipeName,
        [string]$ActionId,
        [string]$SurfaceId,
        [int]$ProcessId
    )

    Set-ProcessForeground -ProcessId $ProcessId
    $resultText = Invoke-InstanceLuaExec `
        -PipeName $PipeName `
        -Code "local ok, result = sd.ui.activate_action('$ActionId', '$SurfaceId'); print('ok=' .. tostring(ok)); print('request=' .. tostring(result))"
    $values = @{}
    foreach ($line in ($resultText -split "`r?`n")) {
        if ($line -match "^([^=]+)=(.*)$") {
            $values[$Matches[1]] = $Matches[2]
        }
    }
    if (-not $values.ContainsKey("ok") -or $values["ok"] -ne "true") {
        throw "UI action $ActionId failed on pipe $PipeName. Output: $resultText"
    }

    $requestId = $values["request"]
    $deadline = (Get-Date).AddSeconds(10)
    $last = ""
    while ((Get-Date) -lt $deadline) {
        $last = (Invoke-InstanceLuaExec `
            -PipeName $PipeName `
            -Code "local d=sd.ui.get_action_dispatch($requestId); local status=tostring(d and d.status or ''); if status == 'failed' then return 'failed:' .. tostring(d and d.error_message or '') end; if status ~= '' and status ~= 'queued' and status ~= 'dispatching' then return 'done:' .. status end; return status" | Out-String).Trim()
        if ($last -match "^done:") {
            return
        }
        if ($last -match "^failed:") {
            throw "UI action $ActionId dispatch failed on pipe $PipeName. Status: $last"
        }
        Start-Sleep -Milliseconds 100
    }

    throw "Timed out waiting for UI action $ActionId dispatch on pipe $PipeName. Last status: $last"
}

function Invoke-CreateSelection {
    param(
        [string]$PipeName,
        [string]$Element,
        [string]$Discipline,
        [int]$ProcessId
    )

    Wait-InstanceLuaValue `
        -PipeName $PipeName `
        -ExpectedValue "create" `
        -Code "local u=sd.ui.get_snapshot(); return tostring(u and u.surface_id or '')"

    $elementActionId = "create.select_element_$Element"
    $elementLatched = $false
    for ($attempt = 1; $attempt -le 3 -and -not $elementLatched; $attempt += 1) {
        Invoke-CreateWindowClick `
            -PipeName $PipeName `
            -ActionId $elementActionId `
            -ProcessId $ProcessId
        $elementLatched = Wait-CreateElementLatched -PipeName $PipeName
    }
    if (-not $elementLatched) {
        $state = Get-CreateSelectionState -PipeName $PipeName
        throw "Create element action $elementActionId did not latch on $PipeName. State: $($state | ConvertTo-Json -Compress)"
    }

    $disciplineActionId = "create.select_discipline_$Discipline"
    $disciplineAccepted = $false
    for ($attempt = 1; $attempt -le 3 -and -not $disciplineAccepted; $attempt += 1) {
        Invoke-CreateWindowClick `
            -PipeName $PipeName `
            -ActionId $disciplineActionId `
            -ProcessId $ProcessId
        $disciplineAccepted = Wait-CreateDisciplineAccepted -PipeName $PipeName
    }
    if (-not $disciplineAccepted) {
        $state = Get-CreateSelectionState -PipeName $PipeName
        throw "Create discipline action $disciplineActionId was not accepted on $PipeName. State: $($state | ConvertTo-Json -Compress)"
    }
}

function Wait-InstanceHub {
    param([string]$PipeName)

    Wait-InstanceLuaValue `
        -PipeName $PipeName `
        -ExpectedValue "hub" `
        -TimeoutSeconds 45 `
        -Code "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')"
}

$selection = Resolve-CreateSelection -PresetName $Preset
$launchPreset = $Preset
if ($null -ne $selection -and -not $UseSandboxPresetFlow) {
    $launchPreset = "create_manual"
}
$waitForHub = (Test-PresetWaitsForHub -PresetName $Preset) -or ($null -ne $selection)

$hostResult = Start-MultiplayerInstance `
    -Instance "local-mp-host" `
    -Role "host" `
    -LocalPort $HostPort `
    -RemotePort $ClientPort `
    -ParticipantId $HostParticipantId `
    -PlayerName $HostName

if ($null -ne $selection -and -not $UseSandboxPresetFlow) {
    Invoke-CreateSelection `
        -PipeName "SolomonDarkModLoader_LuaExec_local-mp-host" `
        -Element $selection.Element `
        -Discipline $selection.Discipline `
        -ProcessId ([int]$hostResult.launch.processId)
}
if ($waitForHub) {
    Wait-InstanceHub -PipeName "SolomonDarkModLoader_LuaExec_local-mp-host"
}

Start-Sleep -Seconds 2

$clientResult = Start-MultiplayerInstance `
    -Instance "local-mp-client" `
    -Role "client" `
    -LocalPort $ClientPort `
    -RemotePort $HostPort `
    -ParticipantId $ClientParticipantId `
    -PlayerName $ClientName

if ($null -ne $selection -and -not $UseSandboxPresetFlow) {
    Invoke-CreateSelection `
        -PipeName "SolomonDarkModLoader_LuaExec_local-mp-client" `
        -Element $selection.Element `
        -Discipline $selection.Discipline `
        -ProcessId ([int]$clientResult.launch.processId)
}
if ($waitForHub) {
    Wait-InstanceHub -PipeName "SolomonDarkModLoader_LuaExec_local-mp-client"
}

[pscustomobject]@{
    preset = $Preset
    launchPreset = $launchPreset
    hostProcessId = $hostResult.launch.processId
    clientProcessId = $clientResult.launch.processId
    hostPort = $HostPort
    clientPort = $ClientPort
    multiplayerTransportEnabled = -not $DisableMultiplayerTransport
    sandboxPresetFlowEnabled = [bool]$UseSandboxPresetFlow
    hostParticipantId = $HostParticipantId
    clientParticipantId = $ClientParticipantId
    hostName = $HostName
    clientName = $ClientName
    hostLuaPipe = "SolomonDarkModLoader_LuaExec_local-mp-host"
    clientLuaPipe = "SolomonDarkModLoader_LuaExec_local-mp-client"
    hostLog = $hostResult.launch.startupLogPath
    clientLog = $clientResult.launch.startupLogPath
} | ConvertTo-Json -Depth 4
