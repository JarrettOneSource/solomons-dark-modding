param(
    [string]$Preset = "map_create_fire_mind_hub",
    [string]$HostPreset = "",
    [string]$ClientPreset = "",
    [string]$ThirdPreset = "",
    [UInt16]$HostPort = 47770,
    [UInt16]$ClientPort = 47771,
    [UInt16]$ThirdPort = 47772,
    [string]$RemoteHost = "127.0.0.1",
    [string]$HostParticipantId = "0x2000000000001001",
    [string]$ClientParticipantId = "0x2000000000001002",
    [string]$ThirdParticipantId = "0x2000000000001003",
    [string]$HostName = "Host Player",
    [string]$ClientName = "Client Player",
    [string]$ThirdName = "Observer Player",
    [switch]$EnableThird,
    [switch]$DisableMultiplayerTransport,
    [switch]$UseSandboxPresetFlow,
    [switch]$TemporaryHostProfile,
    [switch]$GodMode,
    [string]$TestSurvivalBoneyardOverride = "",
    [switch]$TestBlankBoneyard,
    [string]$TestWaveOverride = "",
    [switch]$NoTileWindows,
    [switch]$NoKill,
    [switch]$AllowFocusSteal,
    [string]$ProcessIdOutputPath = "",
    [string]$ExactModIds = ""
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$launcher = Join-Path $root "dist\launcher\SolomonDarkModLauncher.exe"
$launcherDir = Split-Path $launcher -Parent
$luaExecScript = Join-Path $PSScriptRoot "Invoke-LuaExec.ps1"
$clickWindowScript = Join-Path $PSScriptRoot "click_window.py"
$launcherProcessHelpers = Join-Path $PSScriptRoot "LocalMultiplayerLauncher.Process.ps1"

if (-not (Test-Path $launcher)) {
    throw "Launcher was not found at $launcher. Build and stage the launcher first."
}
if (-not (Test-Path $luaExecScript)) {
    throw "Lua exec script was not found at $luaExecScript."
}
if (-not (Test-Path $clickWindowScript)) {
    throw "Window click helper was not found at $clickWindowScript."
}
if (-not (Test-Path $launcherProcessHelpers)) {
    throw "Launcher process helpers were not found at $launcherProcessHelpers."
}

. $launcherProcessHelpers

function Write-LaunchedProcessIds {
    param(
        [object]$HostResult = $null,
        [object]$ClientResult = $null,
        [object]$ThirdResult = $null
    )

    if ([string]::IsNullOrWhiteSpace($ProcessIdOutputPath)) {
        return
    }

    $payload = [pscustomobject]@{
        hostProcessId = if ($null -ne $HostResult) {
            [int]$HostResult.launch.processId
        } else {
            $null
        }
        clientProcessId = if ($null -ne $ClientResult) {
            [int]$ClientResult.launch.processId
        } else {
            $null
        }
        thirdProcessId = if ($null -ne $ThirdResult) {
            [int]$ThirdResult.launch.processId
        } else {
            $null
        }
    }
    [System.IO.File]::WriteAllText(
        $ProcessIdOutputPath,
        ($payload | ConvertTo-Json -Compress)
    )
}

$resolvedTestSurvivalBoneyardOverride = ""
if (-not [string]::IsNullOrWhiteSpace($TestSurvivalBoneyardOverride)) {
    $resolvedOverrideItem = Get-Item -LiteralPath $TestSurvivalBoneyardOverride -ErrorAction Stop
    if ($resolvedOverrideItem.PSIsContainer -or
        $resolvedOverrideItem.Extension -notmatch '^\.boneyard$') {
        throw "Test survival boneyard override must be a .boneyard file: $TestSurvivalBoneyardOverride"
    }
    $resolvedTestSurvivalBoneyardOverride = $resolvedOverrideItem.FullName
}

$resolvedTestWaveOverride = ""
if (-not [string]::IsNullOrWhiteSpace($TestWaveOverride)) {
    $resolvedWaveOverrideItem = Get-Item -LiteralPath $TestWaveOverride -ErrorAction Stop
    if ($resolvedWaveOverrideItem.PSIsContainer -or
        $resolvedWaveOverrideItem.Extension -notmatch '^\.txt$') {
        throw "Test wave override must be a .txt file: $TestWaveOverride"
    }
    $resolvedTestWaveOverride = $resolvedWaveOverrideItem.FullName
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
    }
    if ($GodMode) {
        $env.SDMOD_MULTIPLAYER_GODMODE = "1"
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedTestSurvivalBoneyardOverride)) {
        $env.SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE = $resolvedTestSurvivalBoneyardOverride
    }
    if ($TestBlankBoneyard) {
        $env.SDMOD_TEST_BLANK_BONEYARD = "1"
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedTestWaveOverride)) {
        $env.SDMOD_TEST_WAVE_OVERRIDE = $resolvedTestWaveOverride
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

    Invoke-LauncherWithEnvironment `
        -LauncherPath $launcher `
        -WorkingDirectory $launcherDir `
        -Environment $env `
        -Arguments $args
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

function Enable-InstanceGodMode {
    param([string]$PipeName)

    $resultText = Invoke-InstanceLuaExec `
        -PipeName $PipeName `
        -Code @"
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local function sustain()
  local player = sd.player.get_state()
  if type(player) ~= 'table' then
    return false, 'player_unavailable'
  end

  local progression = tonumber(player.progression_address) or 0
  if progression == 0 then
    local actor = tonumber(player.actor_address) or 0
    if actor ~= 0 and sd.debug and sd.debug.layout_offset and sd.debug.read_ptr then
      local ok_offset, offset = pcall(sd.debug.layout_offset, 'actor_progression_runtime_state')
      if ok_offset and tonumber(offset) ~= nil then
        local ok_ptr, ptr = pcall(sd.debug.read_ptr, actor + tonumber(offset))
        if ok_ptr then
          progression = tonumber(ptr) or 0
        end
      end
    end
  end
  if progression == 0 then
    return false, 'progression_unavailable'
  end

  local ok_hp, hp_offset = pcall(sd.debug.layout_offset, 'progression_hp')
  local ok_max_hp, max_hp_offset = pcall(sd.debug.layout_offset, 'progression_max_hp')
  local ok_mp, mp_offset = pcall(sd.debug.layout_offset, 'progression_mp')
  local ok_max_mp, max_mp_offset = pcall(sd.debug.layout_offset, 'progression_max_mp')
  if not (ok_hp and ok_max_hp and ok_mp and ok_max_mp) then
    return false, 'layout_unavailable'
  end

  local max_hp = tonumber(sd.debug.read_float(progression + max_hp_offset)) or tonumber(player.max_hp) or 0
  local max_mp = tonumber(sd.debug.read_float(progression + max_mp_offset)) or tonumber(player.max_mp) or 0
  if max_hp > 0 then
    sd.debug.write_float(progression + hp_offset, max_hp)
  end
  if max_mp > 0 then
    sd.debug.write_float(progression + mp_offset, max_mp)
  end
  return true, 'ok'
end

if not _G.__sdmod_launch_godmode_enabled then
  local ok_register, err = pcall(function()
    sd.events.on('runtime.tick', function()
      sustain()
    end)
  end)
  if not ok_register then
    error('failed to register godmode tick: ' .. tostring(err))
  end
  _G.__sdmod_launch_godmode_enabled = true
end

local ok, status = sustain()
emit('registered', true)
emit('initial_apply', ok)
emit('status', status)
"@
    $values = Convert-KeyValueText -Text $resultText
    if ($values["registered"] -ne "true") {
        throw "Failed to enable godmode on pipe $PipeName. Output: $resultText"
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
    param(
        [string]$PipeName,
        [string]$ActionId = ""
    )

    $escapedActionId = $ActionId.Replace("\", "\\").Replace("'", "\'")

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
local action_id = '$escapedActionId'
local action = nil
if action_id ~= '' and type(sd.ui) == 'table' and type(sd.ui.find_action) == 'function' then
  action = sd.ui.find_action(action_id, 'create')
end
emit('scene', scene and (scene.name or scene.kind) or '')
emit('ui', snap and snap.surface_id or '')
emit('owner', owner)
emit('element_enabled', read_u8(0x18C))
emit('element_selected', read_u32(0x1A4))
emit('discipline_enabled', read_u8(0x228))
emit('discipline_selected', read_u32(0x22C))
emit('action_found', action ~= nil)
emit('action_enabled', action and action.enabled or false)
emit('action_interactive', action and action.interactive or false)
"@
    return Convert-KeyValueText -Text $resultText
}

function Test-CreateSelectionUnset {
    param([object]$Value)

    $text = [string]$Value
    return [string]::IsNullOrWhiteSpace($text) -or $text -eq "-1" -or $text -eq "4294967295"
}

function Wait-CreateSelectionReady {
    param(
        [string]$PipeName,
        [ValidateSet("element", "discipline")][string]$Phase,
        [string]$ActionId,
        [int]$TimeoutSeconds = 30
    )

    $enabledKey = if ($Phase -eq "element") { "element_enabled" } else { "discipline_enabled" }
    $selectedKey = if ($Phase -eq "element") { "element_selected" } else { "discipline_selected" }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = $null
    while ((Get-Date) -lt $deadline) {
        $state = Get-CreateSelectionState -PipeName $PipeName -ActionId $ActionId
        $lastState = $state
        $owner = 0L
        $enabled = 0L
        $ownerReady = [long]::TryParse([string]$state["owner"], [ref]$owner) -and $owner -ne 0
        $phaseEnabled = [long]::TryParse([string]$state[$enabledKey], [ref]$enabled) -and $enabled -ne 0
        $selectionUnset = Test-CreateSelectionUnset -Value $state[$selectedKey]
        if ($ownerReady -and
            $phaseEnabled -and
            $selectionUnset -and
            $state["ui"] -eq "create" -and
            $state["action_found"] -eq "true") {
            return $state
        }
        Start-Sleep -Milliseconds 250
    }

    $lastStateJson = if ($null -ne $lastState) {
        $lastState | ConvertTo-Json -Compress
    } else {
        "{}"
    }
    throw "Timed out waiting for native create $Phase selection readiness for '$ActionId' on $PipeName. Last state: $lastStateJson"
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
        [void](Wait-CreateSelectionReady `
            -PipeName $PipeName `
            -Phase "element" `
            -ActionId $elementActionId)
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
        [void](Wait-CreateSelectionReady `
            -PipeName $PipeName `
            -Phase "discipline" `
            -ActionId $disciplineActionId)
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

    # The stock create scene reports `hub` before its outgoing UI/preview
    # objects have finished their deferred destruction.  Starting the live
    # verifiers at that first sample makes their native visual/world queries
    # overlap the allocator cleanup window (and has produced repeatable
    # RtlFreeHeap failures before any remote actor was materialized).  Give the
    # game thread a quiet window, then prove that the destination scene is still
    # alive before returning ownership of the Lua pipe to the verifier.
    Start-Sleep -Milliseconds 3500
    Wait-InstanceLuaValue `
        -PipeName $PipeName `
        -ExpectedValue "hub" `
        -TimeoutSeconds 10 `
        -Code "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')"
}

$effectiveHostPreset = if ([string]::IsNullOrWhiteSpace($HostPreset)) { $Preset } else { $HostPreset }
$effectiveClientPreset = if ([string]::IsNullOrWhiteSpace($ClientPreset)) { $Preset } else { $ClientPreset }
$effectiveThirdPreset = if ([string]::IsNullOrWhiteSpace($ThirdPreset)) { $Preset } else { $ThirdPreset }

$hostSelection = Resolve-CreateSelection -PresetName $effectiveHostPreset
$clientSelection = Resolve-CreateSelection -PresetName $effectiveClientPreset
$thirdSelection = Resolve-CreateSelection -PresetName $effectiveThirdPreset
$hostLaunchPreset = $effectiveHostPreset
$clientLaunchPreset = $effectiveClientPreset
$thirdLaunchPreset = $effectiveThirdPreset
if ($null -ne $hostSelection -and -not $UseSandboxPresetFlow) {
    $hostLaunchPreset = "create_manual"
}
if ($null -ne $clientSelection -and -not $UseSandboxPresetFlow) {
    $clientLaunchPreset = "create_manual"
}
if ($null -ne $thirdSelection -and -not $UseSandboxPresetFlow) {
    $thirdLaunchPreset = "create_manual"
}
$hostWaitForHub = (Test-PresetWaitsForHub -PresetName $effectiveHostPreset) -or ($null -ne $hostSelection)
$clientWaitForHub = (Test-PresetWaitsForHub -PresetName $effectiveClientPreset) -or ($null -ne $clientSelection)
$thirdWaitForHub = (Test-PresetWaitsForHub -PresetName $effectiveThirdPreset) -or ($null -ne $thirdSelection)

if (-not [string]::IsNullOrWhiteSpace($ExactModIds)) {
    $exactModIdList = $ExactModIds.Split(',')
    Set-ExactMultiplayerModState `
        -RootPath $root `
        -Instance "local-mp-host" `
        -ModIds $exactModIdList
    Set-ExactMultiplayerModState `
        -RootPath $root `
        -Instance "local-mp-client" `
        -ModIds $exactModIdList
    if ($EnableThird) {
        Set-ExactMultiplayerModState `
            -RootPath $root `
            -Instance "local-mp-third" `
            -ModIds $exactModIdList
    }
}

$hostResult = Start-MultiplayerInstance `
    -Instance "local-mp-host" `
    -InstanceLaunchPreset $hostLaunchPreset `
    -Role "host" `
    -LocalPort $HostPort `
    -RemotePort $ClientPort `
    -ParticipantId $HostParticipantId `
    -PlayerName $HostName `
    -RemotePlayerName $ClientName

Write-LaunchedProcessIds -HostResult $hostResult

if ($GodMode) {
    Enable-InstanceGodMode -PipeName "SolomonDarkModLoader_LuaExec_local-mp-host" | Out-Null
}

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

Write-LaunchedProcessIds `
    -HostResult $hostResult `
    -ClientResult $clientResult

if ($GodMode) {
    Enable-InstanceGodMode -PipeName "SolomonDarkModLoader_LuaExec_local-mp-client" | Out-Null
}

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

$thirdResult = $null
if ($EnableThird) {
    Start-Sleep -Seconds 2

    $thirdResult = Start-MultiplayerInstance `
        -Instance "local-mp-third" `
        -InstanceLaunchPreset $thirdLaunchPreset `
        -Role "client" `
        -LocalPort $ThirdPort `
        -RemotePort $HostPort `
        -ParticipantId $ThirdParticipantId `
        -PlayerName $ThirdName `
        -RemotePlayerName $HostName

    Write-LaunchedProcessIds `
        -HostResult $hostResult `
        -ClientResult $clientResult `
        -ThirdResult $thirdResult

    if ($GodMode) {
        Enable-InstanceGodMode -PipeName "SolomonDarkModLoader_LuaExec_local-mp-third" | Out-Null
    }

    if ($null -ne $thirdSelection -and -not $UseSandboxPresetFlow) {
        Invoke-CreateSelection `
            -PipeName "SolomonDarkModLoader_LuaExec_local-mp-third" `
            -Element $thirdSelection.Element `
            -Discipline $thirdSelection.Discipline `
            -ProcessId ([int]$thirdResult.launch.processId)
    }
    if ($thirdWaitForHub) {
        Wait-InstanceHub -PipeName "SolomonDarkModLoader_LuaExec_local-mp-third"
    }
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
    thirdPreset = if ($EnableThird) { $effectiveThirdPreset } else { $null }
    hostLaunchPreset = $hostLaunchPreset
    clientLaunchPreset = $clientLaunchPreset
    thirdLaunchPreset = if ($EnableThird) { $thirdLaunchPreset } else { $null }
    hostProcessId = $hostResult.launch.processId
    clientProcessId = $clientResult.launch.processId
    thirdProcessId = if ($null -ne $thirdResult) { $thirdResult.launch.processId } else { $null }
    hostPort = $HostPort
    clientPort = $ClientPort
    thirdPort = if ($EnableThird) { $ThirdPort } else { $null }
    thirdEnabled = [bool]$EnableThird
    multiplayerTransportEnabled = -not $DisableMultiplayerTransport
    sandboxPresetFlowEnabled = [bool]$UseSandboxPresetFlow
    temporaryHostProfile = [bool]$TemporaryHostProfile
    godModeEnabled = [bool]$GodMode
    testSurvivalBoneyardOverride = $resolvedTestSurvivalBoneyardOverride
    testBlankBoneyardEnabled = [bool]$TestBlankBoneyard
    testWaveOverride = $resolvedTestWaveOverride
    allowFocusSteal = [bool]$AllowFocusSteal
    hostParticipantId = $HostParticipantId
    clientParticipantId = $ClientParticipantId
    thirdParticipantId = if ($EnableThird) { $ThirdParticipantId } else { $null }
    hostName = $HostName
    clientName = $ClientName
    thirdName = if ($EnableThird) { $ThirdName } else { $null }
    hostLuaPipe = "SolomonDarkModLoader_LuaExec_local-mp-host"
    clientLuaPipe = "SolomonDarkModLoader_LuaExec_local-mp-client"
    thirdLuaPipe = if ($EnableThird) { "SolomonDarkModLoader_LuaExec_local-mp-third" } else { $null }
    hostLog = $hostResult.launch.startupLogPath
    clientLog = $clientResult.launch.startupLogPath
    thirdLog = if ($null -ne $thirdResult) { $thirdResult.launch.startupLogPath } else { $null }
    graphicsResolution = $stagedGraphicsResolution
    windowLayout = $windowLayout
    windowLayoutError = $windowLayoutError
} | ConvertTo-Json -Depth 4 -Compress
