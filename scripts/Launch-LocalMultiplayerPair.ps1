param(
    [string]$Preset = "map_create_fire_mind_hub",
    [string]$HostPreset = "",
    [string]$ClientPreset = "",
    [UInt16]$HostPort = 47770,
    [UInt16]$ClientPort = 47771,
    [string]$RemoteHost = "127.0.0.1",
    [string]$HostParticipantId = "0x2000000000001001",
    [string]$ClientParticipantId = "0x2000000000001002",
    [string]$HostName = "Host Player",
    [string]$ClientName = "Client Player",
    [switch]$DisableMultiplayerTransport,
    [switch]$UseSandboxPresetFlow,
    [switch]$TemporaryHostProfile,
    [switch]$NoTileWindows,
    [switch]$NoKill,
    [switch]$AllowFocusSteal
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
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll", EntryPoint="GetWindowLongW")] public static extern int GetWindowLong(IntPtr hWnd, int nIndex);
    [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool AdjustWindowRectEx(ref RECT lpRect, int dwStyle, bool bMenu, int dwExStyle);

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }
}
"@

Add-Type -AssemblyName System.Windows.Forms

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

function ConvertFrom-FirstJsonObject {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $null
    }

    $start = $Text.IndexOf('{')
    if ($start -lt 0) {
        return $null
    }

    $depth = 0
    $inString = $false
    $escaped = $false
    for ($index = $start; $index -lt $Text.Length; $index += 1) {
        $character = $Text[$index]
        if ($inString) {
            if ($escaped) {
                $escaped = $false
            } elseif ($character -eq '\') {
                $escaped = $true
            } elseif ($character -eq '"') {
                $inString = $false
            }
            continue
        }

        if ($character -eq '"') {
            $inString = $true
            continue
        }
        if ($character -eq '{') {
            $depth += 1
            continue
        }
        if ($character -eq '}') {
            $depth -= 1
            if ($depth -eq 0) {
                $candidate = $Text.Substring($start, ($index - $start) + 1)
                try {
                    return $candidate | ConvertFrom-Json -ErrorAction Stop
                } catch {
                    return $null
                }
            }
        }
    }

    return $null
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
                $result = ConvertFrom-FirstJsonObject -Text $stdout
                if ($null -ne $result) {
                    break
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
        [string]$InstanceLaunchPreset,
        [string]$Role,
        [UInt16]$LocalPort,
        [UInt16]$RemotePort,
        [string]$ParticipantId,
        [string]$PlayerName,
        [string]$RemotePlayerName
    )

    $env = @{
        SDMOD_UI_SANDBOX_PRESET = $InstanceLaunchPreset
        SDMOD_LUA_EXEC_PIPE_NAME = "SolomonDarkModLoader_LuaExec_$Instance"
        SDMOD_HUD_ALLY_LABEL = $RemotePlayerName
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
    if ($Role -eq "client" -or ($Role -eq "host" -and $TemporaryHostProfile)) {
        $args += "--temporary-profile"
    }

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

$createElementIds = @{
    ether = 0
    fire = 1
    air = 2
    water = 3
    earth = 4
}

$createDisciplineIds = @{
    mind = 0
    body = 1
    arcane = 2
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

function Get-StagedGraphicsResolution {
    $settingsPath = Join-Path $root "runtime\stage\sandbox\settings.txt"
    if (Test-Path $settingsPath) {
        foreach ($line in (Get-Content -Path $settingsPath -ErrorAction SilentlyContinue)) {
            if ($line -match "^Graphics\.Resolution=(\d+),(\d+)\s*$") {
                $width = [int]$Matches[1]
                $height = [int]$Matches[2]
                if ($width -gt 0 -and $height -gt 0) {
                    return [pscustomobject]@{
                        Width = $width
                        Height = $height
                    }
                }
            }
        }
    }

    return [pscustomobject]@{
        Width = 1600
        Height = 900
    }
}

$stagedGraphicsResolution = Get-StagedGraphicsResolution

function Get-AspectCorrectOuterSize {
    param(
        [IntPtr]$WindowHandle,
        [int]$MaxOuterWidth,
        [int]$MaxOuterHeight,
        [double]$AspectRatio
    )

    $gwlStyle = -16
    $gwlExStyle = -20
    $style = [SolomonDarkWindowActivator]::GetWindowLong($WindowHandle, $gwlStyle)
    $exStyle = [SolomonDarkWindowActivator]::GetWindowLong($WindowHandle, $gwlExStyle)
    $frame = New-Object SolomonDarkWindowActivator+RECT
    $hasMenu = [SolomonDarkWindowActivator]::GetMenu($WindowHandle) -ne [IntPtr]::Zero
    [void][SolomonDarkWindowActivator]::AdjustWindowRectEx([ref]$frame, $style, $hasMenu, $exStyle)

    $frameWidth = $frame.Right - $frame.Left
    $frameHeight = $frame.Bottom - $frame.Top
    $clientWidth = [Math]::Max(640, $MaxOuterWidth - $frameWidth)
    $clientHeight = [int][Math]::Round($clientWidth / $AspectRatio)
    $outerWidth = $clientWidth + $frameWidth
    $outerHeight = $clientHeight + $frameHeight

    if ($outerHeight -gt $MaxOuterHeight) {
        $clientHeight = [Math]::Max(360, $MaxOuterHeight - $frameHeight)
        $clientWidth = [int][Math]::Round($clientHeight * $AspectRatio)
        $outerWidth = $clientWidth + $frameWidth
        $outerHeight = $clientHeight + $frameHeight
    }

    return [pscustomobject]@{
        Width = $outerWidth
        Height = $outerHeight
        ClientWidth = $clientWidth
        ClientHeight = $clientHeight
    }
}

function Set-LocalMultiplayerWindowLayout {
    param(
        [int]$HostProcessId,
        [int]$ClientProcessId
    )

    $hostProcess = Get-Process -Id $HostProcessId -ErrorAction Stop
    $clientProcess = Get-Process -Id $ClientProcessId -ErrorAction Stop
    if ($hostProcess.MainWindowHandle -eq 0 -or $clientProcess.MainWindowHandle -eq 0) {
        throw "One or both multiplayer windows are not ready for tiling."
    }

    $workingArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $columnWidth = [int][Math]::Floor($workingArea.Width / 2)
    $aspectRatio = [double]$stagedGraphicsResolution.Width / [double]$stagedGraphicsResolution.Height
    $hostSize = Get-AspectCorrectOuterSize `
        -WindowHandle $hostProcess.MainWindowHandle `
        -MaxOuterWidth $columnWidth `
        -MaxOuterHeight $workingArea.Height `
        -AspectRatio $aspectRatio
    $clientSize = Get-AspectCorrectOuterSize `
        -WindowHandle $clientProcess.MainWindowHandle `
        -MaxOuterWidth $columnWidth `
        -MaxOuterHeight $workingArea.Height `
        -AspectRatio $aspectRatio

    $flags = 0x0004 -bor 0x0010 -bor 0x0040
    $showNoActivate = 4
    [void][SolomonDarkWindowActivator]::ShowWindow($hostProcess.MainWindowHandle, $showNoActivate)
    [void][SolomonDarkWindowActivator]::ShowWindow($clientProcess.MainWindowHandle, $showNoActivate)
    [void][SolomonDarkWindowActivator]::SetWindowPos(
        $hostProcess.MainWindowHandle,
        [IntPtr]::Zero,
        $workingArea.Left,
        $workingArea.Top,
        $hostSize.Width,
        $hostSize.Height,
        $flags)
    [void][SolomonDarkWindowActivator]::SetWindowPos(
        $clientProcess.MainWindowHandle,
        [IntPtr]::Zero,
        $workingArea.Left + $columnWidth,
        $workingArea.Top,
        $clientSize.Width,
        $clientSize.Height,
        $flags)

    return [pscustomobject]@{
        host = $hostSize
        client = $clientSize
        aspectRatio = $aspectRatio
    }
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
            if ($AllowFocusSteal) {
                [void][SolomonDarkWindowActivator]::ShowWindow($process.MainWindowHandle, 9)
                [void][SolomonDarkWindowActivator]::BringWindowToTop($process.MainWindowHandle)
                [void][SolomonDarkWindowActivator]::SetForegroundWindow($process.MainWindowHandle)
                Start-Sleep -Milliseconds 400
            } else {
                [void][SolomonDarkWindowActivator]::ShowWindow($process.MainWindowHandle, 4)
                Start-Sleep -Milliseconds 100
            }
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
    if (-not $AllowFocusSteal) {
        throw "Window click fallback requires -AllowFocusSteal; use Lua UI actions for no-focus automation."
    }
    Set-ProcessForeground -ProcessId $ProcessId
    $clickOutput = & py -3 $clickWindowScript `
        --pid $ProcessId `
        --x $point.X `
        --y $point.Y `
        --virtual-width $stagedGraphicsResolution.Width `
        --virtual-height $stagedGraphicsResolution.Height `
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
        [int]$ExpectedElementId,
        [int]$TimeoutSeconds = 8
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = $null
    while ((Get-Date) -lt $deadline) {
        $state = Get-CreateSelectionState -PipeName $PipeName
        $lastState = $state
        $selectedElement = 0L
        $hasSelectedElement = [long]::TryParse([string]$state["element_selected"], [ref]$selectedElement)
        if ($hasSelectedElement -and
            $selectedElement -eq $ExpectedElementId -and
            $state["discipline_enabled"] -ne "0") {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }

    if ($null -ne $lastState) {
        Write-Warning "Timed out waiting for create element id $ExpectedElementId on $PipeName. Last state: $($lastState | ConvertTo-Json -Compress)"
    }
    return $false
}

function Wait-CreateDisciplineAccepted {
    param(
        [string]$PipeName,
        [int]$ExpectedDisciplineId,
        [int]$TimeoutSeconds = 10
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = $null
    while ((Get-Date) -lt $deadline) {
        $state = Get-CreateSelectionState -PipeName $PipeName
        $lastState = $state
        $selectedDiscipline = 0L
        $hasSelectedDiscipline = [long]::TryParse([string]$state["discipline_selected"], [ref]$selectedDiscipline)
        if ($hasSelectedDiscipline -and $selectedDiscipline -eq $ExpectedDisciplineId) {
            return $true
        }
        if ($state["scene"] -eq "hub" -or $state["ui"] -ne "create") {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }

    if ($null -ne $lastState) {
        Write-Warning "Timed out waiting for create discipline id $ExpectedDisciplineId on $PipeName. Last state: $($lastState | ConvertTo-Json -Compress)"
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

    if (-not $createElementIds.ContainsKey($Element)) {
        throw "Unknown create element '$Element'."
    }
    if (-not $createDisciplineIds.ContainsKey($Discipline)) {
        throw "Unknown create discipline '$Discipline'."
    }
    $expectedElementId = [int]$createElementIds[$Element]
    $expectedDisciplineId = [int]$createDisciplineIds[$Discipline]

    Wait-InstanceLuaValue `
        -PipeName $PipeName `
        -ExpectedValue "create" `
        -Code "local u=sd.ui.get_snapshot(); return tostring(u and u.surface_id or '')"

    $elementActionId = "create.select_element_$Element"
    $elementLatched = $false
    for ($attempt = 1; $attempt -le 3 -and -not $elementLatched; $attempt += 1) {
        Invoke-UiActionAndWait `
            -PipeName $PipeName `
            -ActionId $elementActionId `
            -SurfaceId "create" `
            -ProcessId $ProcessId
        $elementLatched = Wait-CreateElementLatched `
            -PipeName $PipeName `
            -ExpectedElementId $expectedElementId
    }
    if (-not $elementLatched) {
        $state = Get-CreateSelectionState -PipeName $PipeName
        throw "Create element action $elementActionId did not latch expected id $expectedElementId on $PipeName. State: $($state | ConvertTo-Json -Compress)"
    }

    $disciplineActionId = "create.select_discipline_$Discipline"
    $disciplineAccepted = $false
    for ($attempt = 1; $attempt -le 3 -and -not $disciplineAccepted; $attempt += 1) {
        Invoke-UiActionAndWait `
            -PipeName $PipeName `
            -ActionId $disciplineActionId `
            -SurfaceId "create" `
            -ProcessId $ProcessId
        $disciplineAccepted = Wait-CreateDisciplineAccepted `
            -PipeName $PipeName `
            -ExpectedDisciplineId $expectedDisciplineId
    }
    if (-not $disciplineAccepted) {
        $state = Get-CreateSelectionState -PipeName $PipeName
        throw "Create discipline action $disciplineActionId was not accepted with expected id $expectedDisciplineId on $PipeName. State: $($state | ConvertTo-Json -Compress)"
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

$effectiveHostPreset = if ([string]::IsNullOrWhiteSpace($HostPreset)) { $Preset } else { $HostPreset }
$effectiveClientPreset = if ([string]::IsNullOrWhiteSpace($ClientPreset)) { $Preset } else { $ClientPreset }

$hostSelection = Resolve-CreateSelection -PresetName $effectiveHostPreset
$clientSelection = Resolve-CreateSelection -PresetName $effectiveClientPreset
$hostLaunchPreset = $effectiveHostPreset
$clientLaunchPreset = $effectiveClientPreset
if ($null -ne $hostSelection -and -not $UseSandboxPresetFlow) {
    $hostLaunchPreset = "create_manual"
}
if ($null -ne $clientSelection -and -not $UseSandboxPresetFlow) {
    $clientLaunchPreset = "create_manual"
}
$hostWaitForHub = (Test-PresetWaitsForHub -PresetName $effectiveHostPreset) -or ($null -ne $hostSelection)
$clientWaitForHub = (Test-PresetWaitsForHub -PresetName $effectiveClientPreset) -or ($null -ne $clientSelection)

$hostResult = Start-MultiplayerInstance `
    -Instance "local-mp-host" `
    -InstanceLaunchPreset $hostLaunchPreset `
    -Role "host" `
    -LocalPort $HostPort `
    -RemotePort $ClientPort `
    -ParticipantId $HostParticipantId `
    -PlayerName $HostName `
    -RemotePlayerName $ClientName

if ($null -ne $hostSelection -and -not $UseSandboxPresetFlow) {
    Invoke-CreateSelection `
        -PipeName "SolomonDarkModLoader_LuaExec_local-mp-host" `
        -Element $hostSelection.Element `
        -Discipline $hostSelection.Discipline `
        -ProcessId ([int]$hostResult.launch.processId)
}
if ($hostWaitForHub) {
    Wait-InstanceHub -PipeName "SolomonDarkModLoader_LuaExec_local-mp-host"
}

Start-Sleep -Seconds 2

$clientResult = Start-MultiplayerInstance `
    -Instance "local-mp-client" `
    -InstanceLaunchPreset $clientLaunchPreset `
    -Role "client" `
    -LocalPort $ClientPort `
    -RemotePort $HostPort `
    -ParticipantId $ClientParticipantId `
    -PlayerName $ClientName `
    -RemotePlayerName $HostName

if ($null -ne $clientSelection -and -not $UseSandboxPresetFlow) {
    Invoke-CreateSelection `
        -PipeName "SolomonDarkModLoader_LuaExec_local-mp-client" `
        -Element $clientSelection.Element `
        -Discipline $clientSelection.Discipline `
        -ProcessId ([int]$clientResult.launch.processId)
}
if ($clientWaitForHub) {
    Wait-InstanceHub -PipeName "SolomonDarkModLoader_LuaExec_local-mp-client"
}

$windowLayout = $null
$windowLayoutError = $null
if (-not $NoTileWindows) {
    try {
        $windowLayout = Set-LocalMultiplayerWindowLayout `
            -HostProcessId ([int]$hostResult.launch.processId) `
            -ClientProcessId ([int]$clientResult.launch.processId)
    } catch {
        $windowLayoutError = $_.Exception.Message
    }
}

[pscustomobject]@{
    preset = $Preset
    hostPreset = $effectiveHostPreset
    clientPreset = $effectiveClientPreset
    hostLaunchPreset = $hostLaunchPreset
    clientLaunchPreset = $clientLaunchPreset
    hostProcessId = $hostResult.launch.processId
    clientProcessId = $clientResult.launch.processId
    hostPort = $HostPort
    clientPort = $ClientPort
    multiplayerTransportEnabled = -not $DisableMultiplayerTransport
    sandboxPresetFlowEnabled = [bool]$UseSandboxPresetFlow
    temporaryHostProfile = [bool]$TemporaryHostProfile
    allowFocusSteal = [bool]$AllowFocusSteal
    hostParticipantId = $HostParticipantId
    clientParticipantId = $ClientParticipantId
    hostName = $HostName
    clientName = $ClientName
    hostLuaPipe = "SolomonDarkModLoader_LuaExec_local-mp-host"
    clientLuaPipe = "SolomonDarkModLoader_LuaExec_local-mp-client"
    hostLog = $hostResult.launch.startupLogPath
    clientLog = $clientResult.launch.startupLogPath
    graphicsResolution = $stagedGraphicsResolution
    windowLayout = $windowLayout
    windowLayoutError = $windowLayoutError
} | ConvertTo-Json -Depth 4 -Compress
