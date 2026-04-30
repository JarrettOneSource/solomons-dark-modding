param(
    [string]$Preset = "title_menu_to_explore_dark_cloud_sort",
    [string]$ScreenshotPath = "",
    [ValidateSet("screen", "window")]
    [string]$CaptureMethod = "screen",
    [ValidateRange(10, 300)]
    [int]$CompletionTimeoutSeconds = 90,
    [ValidateRange(5, 120)]
    [int]$ProcessStartTimeoutSeconds = 30,
    [string[]]$PostKeys = @(),
    [ValidateRange(50, 10000)]
    [int]$PostKeyIntervalMs = 1000,
    [ValidateRange(0, 10000)]
    [int]$PostKeySettleMs = 1500,
    [string]$BotSet = "",
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root "dist/launcher/SolomonDarkModLauncher.exe"
$captureScript = Join-Path $PSScriptRoot "capture_window.py"
$luaExecPython = Join-Path $root "tools/lua-exec.py"
$sendKeysScript = Join-Path $PSScriptRoot "send_window_keys.py"
$loaderLog = Join-Path $root "runtime/stage/.sdmod/logs/solomondarkmodloader.log"
$sandboxPresetPath = Join-Path $root "mods/lua_ui_sandbox_lab/config/active_preset.txt"
$traceLog = Join-Path $root "runtime/replay-ui-sandbox.log"
$sandboxModId = "sample.lua.ui_sandbox_lab"
$bootstrapModId = "sample.lua.dark_cloud_sort_bootstrap"
$botsModId = "sample.lua.bots"
$sandboxPresetEnvVar = "SDMOD_UI_SANDBOX_PRESET"
$botSetEnvVar = "SDMOD_LUA_BOTS_ACTIVE"

function Assert-LastExitCode {
    param([string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Write-TraceLine {
    param([Parameter(Mandatory = $true)][string]$Message)

    $traceDirectory = Split-Path -Parent $traceLog
    if (-not (Test-Path -LiteralPath $traceDirectory)) {
        New-Item -ItemType Directory -Path $traceDirectory -Force | Out-Null
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    Add-Content -LiteralPath $traceLog -Value "[$timestamp] $Message"
}

function Stop-SolomonDarkProcess {
    Get-Process SolomonDark -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

function Wait-ForSolomonDarkProcess {
    param(
        [int]$TimeoutSeconds = 30,
        [object]$LaunchHandle = $null
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $process = Get-Process SolomonDark -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $process) {
            return $process
        }

        if ($null -ne $LaunchHandle -and $null -ne $LaunchHandle.Process -and $LaunchHandle.Process.HasExited -and
            $LaunchHandle.Process.ExitCode -ne 0) {
            throw (Get-LauncherCommandFailureMessage -LaunchHandle $LaunchHandle)
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for SolomonDark to start."
}

function Read-SharedTextFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = $null
    $reader = $null
    try {
        $stream = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite)
        $reader = New-Object System.IO.StreamReader($stream)
        return $reader.ReadToEnd()
    }
    finally {
        if ($reader -ne $null) {
            $reader.Dispose()
        }
        elseif ($stream -ne $null) {
            $stream.Dispose()
        }
    }
}

function Wait-ForSandboxOutcome {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LogPath,
        [Parameter(Mandatory = $true)]
        [string]$PresetName,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $completeMarker = "sequence complete preset=$PresetName"
    $abortedMarker = "sequence aborted preset=$PresetName"
    $timeoutMarker = "timeout preset=$PresetName"

    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process SolomonDark -ErrorAction SilentlyContinue)) {
            throw "SolomonDark exited before the sandbox preset completed."
        }

        if (Test-Path -LiteralPath $LogPath) {
            $contents = Read-SharedTextFile -Path $LogPath
            if ($contents.Contains($completeMarker)) {
                return "complete"
            }
            if ($contents.Contains($abortedMarker)) {
                throw "Sandbox preset '$PresetName' aborted. Inspect $LogPath."
            }
            if ($contents.Contains($timeoutMarker)) {
                throw "Sandbox preset '$PresetName' timed out. Inspect $LogPath."
            }
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for sandbox preset '$PresetName' to complete."
}

function Set-ActiveSandboxPreset {
    param([Parameter(Mandatory = $true)][string]$PresetName)

    $sandboxConfigDirectory = Split-Path -Parent $sandboxPresetPath
    if (-not (Test-Path -LiteralPath $sandboxConfigDirectory)) {
        New-Item -ItemType Directory -Path $sandboxConfigDirectory | Out-Null
    }

    Set-Content -LiteralPath $sandboxPresetPath -Value $PresetName -NoNewline
}

function Restore-ActiveSandboxPreset {
    param(
        [Parameter(Mandatory = $true)][bool]$Existed,
        [AllowNull()][string]$Content
    )

    if ($Existed) {
        $sandboxConfigDirectory = Split-Path -Parent $sandboxPresetPath
        if (-not (Test-Path -LiteralPath $sandboxConfigDirectory)) {
            New-Item -ItemType Directory -Path $sandboxConfigDirectory -Force | Out-Null
        }
        [System.IO.File]::WriteAllText($sandboxPresetPath, $Content)
        return
    }

    Remove-Item -LiteralPath $sandboxPresetPath -Force -ErrorAction SilentlyContinue
}

function Resolve-BotSet {
    param([AllowEmptyString()][string]$Value)

    $rawValue = if ($null -eq $Value) { "" } else { $Value }
    $normalized = $rawValue.Trim().ToLowerInvariant()
    if ($normalized -eq "") {
        return ""
    }
    if ($normalized -eq "default") {
        return "default"
    }
    if ($normalized -eq "all" -or $normalized -eq "*") {
        return "all"
    }

    $validKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    @("fire", "earth", "water", "air", "ether") | ForEach-Object { [void]$validKeys.Add($_) }

    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $keys = [System.Collections.Generic.List[string]]::new()
    foreach ($token in ($normalized -split "[,\s]+")) {
        $key = $token.Trim()
        if ($key -eq "") {
            continue
        }
        if (-not $validKeys.Contains($key)) {
            throw "Unsupported BotSet token '$key'. Use default, all, or a comma-separated subset of fire, earth, water, air, ether."
        }
        if ($seen.Add($key)) {
            $keys.Add($key)
        }
    }

    return ($keys -join ",")
}

function Resolve-CreateSelectionPreset {
    param([Parameter(Mandatory = $true)][string]$PresetName)

    $normalized = $PresetName
    if ($normalized -match "_hub$") {
        $normalized = $normalized.Substring(0, $normalized.Length - 4)
    }

    if ($normalized -eq "enter_gameplay_start_run_ready" -or
        $normalized -eq "enter_gameplay_wait" -or
        $normalized -eq "trace_rich_item_startup") {
        return @{
            element = "water"
            discipline = "arcane"
        }
    }

    if ($normalized -match '^(create_ready|map_create)_(?<element>[a-z]+)_(?<discipline>[a-z]+)$') {
        return @{
            element = $Matches.element
            discipline = $Matches.discipline
        }
    }

    if ($normalized -match '^(create_ready|map_create)_(?<element>[a-z]+)$') {
        return @{
            element = $Matches.element
            discipline = "arcane"
        }
    }

    return $null
}

function Test-PresetStartsTestRun {
    param([Parameter(Mandatory = $true)][string]$PresetName)

    $normalized = $PresetName
    if ($normalized -match "_hub$") {
        return $false
    }

    if ($normalized -eq "enter_gameplay_start_run_ready" -or
        $normalized -eq "trace_rich_item_startup") {
        return $true
    }

    return $normalized -match '^map_create_[a-z]+(_[a-z]+)?$'
}

function Get-ExpectedBotCount {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$ResolvedBotSet)

    if ($ResolvedBotSet -eq "all") {
        return 5
    }
    if ($ResolvedBotSet -eq "default") {
        return 2
    }
    if ($ResolvedBotSet -eq "") {
        return 0
    }

    return ($ResolvedBotSet -split "," | Where-Object { $_ -ne "" }).Count
}

function Wait-ForCreateSurface {
    param([int]$TimeoutSeconds = 20)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $loaderLog) {
            $contents = Read-SharedTextFile -Path $loaderLog
            if ($contents -match 'surface=create title=Create') {
                return
            }
        }
        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for the create surface."
}

function ConvertTo-LuaSingleQuotedString {
    param([Parameter(Mandatory = $true)][string]$Value)

    return "'" + $Value.Replace("\", "\\").Replace("'", "\'") + "'"
}

function Invoke-LuaExecRaw {
    param(
        [Parameter(Mandatory = $true)][string]$Code,
        [Parameter(Mandatory = $true)][string]$Step
    )

    $output = & py -3 $luaExecPython $Code 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE. $($output -join [Environment]::NewLine)"
    }

    return (($output | ForEach-Object { [string]$_ }) -join "`n").Trim()
}

function Invoke-SemanticUiAction {
    param(
        [Parameter(Mandatory = $true)][string]$ActionId,
        [Parameter(Mandatory = $true)][string]$SurfaceId,
        [int]$TimeoutSeconds = 20
    )

    $actionLiteral = ConvertTo-LuaSingleQuotedString -Value $ActionId
    $surfaceLiteral = ConvertTo-LuaSingleQuotedString -Value $SurfaceId
    $activationDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $activation = ""
    $activationParts = @()
    while ((Get-Date) -lt $activationDeadline) {
        $activation = Invoke-LuaExecRaw `
            -Step "Semantic UI action activation $ActionId" `
            -Code "local ok, result = sd.ui.activate_action($actionLiteral, $surfaceLiteral); return tostring(ok) .. '|' .. tostring(result)"

        $activationParts = $activation -split '\|', 2
        if ($activationParts.Count -ge 2 -and $activationParts[0] -eq "true") {
            break
        }

        Start-Sleep -Milliseconds 250
    }

    if ($activationParts.Count -lt 2 -or $activationParts[0] -ne "true") {
        throw "Semantic UI action '$ActionId' failed to queue: $activation"
    }

    $requestId = 0
    if (-not [int]::TryParse($activationParts[1], [ref]$requestId) -or $requestId -le 0) {
        throw "Semantic UI action '$ActionId' returned invalid request id: $activation"
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $dispatch = Invoke-LuaExecRaw `
            -Step "Semantic UI action dispatch $ActionId" `
            -Code "local d = sd.ui.get_action_dispatch($requestId); if type(d) ~= 'table' then return 'missing||' end; return tostring(d.status) .. '|' .. tostring(d.action_id) .. '|' .. tostring(d.error_message or '')"
        $dispatchParts = $dispatch -split '\|', 3
        $status = if ($dispatchParts.Count -gt 0) { $dispatchParts[0] } else { "" }
        if ($status -eq "dispatched") {
            return $requestId
        }
        if ($status -eq "failed") {
            throw "Semantic UI action '$ActionId' dispatch failed: $dispatch"
        }
        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for semantic UI action '$ActionId' dispatch."
}

function Wait-ForSceneName {
    param(
        [Parameter(Mandatory = $true)][string]$SceneName,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process SolomonDark -ErrorAction SilentlyContinue)) {
            throw "SolomonDark exited before scene '$SceneName' became active."
        }

        $state = Invoke-LuaExecRaw `
            -Step "Scene probe $SceneName" `
            -Code "local scene = sd.world.get_scene(); return 'name=' .. tostring(scene and scene.name) .. '|kind=' .. tostring(scene and scene.kind)"
        if ($state -match "name=$([regex]::Escape($SceneName))\|") {
            return "complete"
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for scene '$SceneName'."
}

function Invoke-HubStartTestRun {
    $result = Invoke-LuaExecRaw `
        -Step "Hub start testrun" `
        -Code "if type(sd.hub) ~= 'table' or type(sd.hub.start_testrun) ~= 'function' then return 'false|sd.hub.start_testrun unavailable' end; local ok, result = pcall(sd.hub.start_testrun); return tostring(ok and result == true) .. '|' .. tostring(result)"

    $parts = $result -split '\|', 2
    if ($parts.Count -lt 2 -or $parts[0] -ne "true") {
        throw "Failed to start testrun from hub: $result"
    }
}

function Read-CreateSelectionState {
    return Invoke-LuaExecRaw `
        -Step "Create selection state probe" `
        -Code "local owner=0; local snap=sd.ui.get_snapshot(); if type(snap)=='table' then for _,e in ipairs(snap.elements or {}) do if e.surface_id=='create' or e.surface_root_id=='create' then owner=tonumber(e.surface_object_ptr) or 0; break end end end; local function r32(off) if owner == 0 then return nil end; local ok,v=pcall(sd.debug.read_u32, owner+off); if ok then return tonumber(v) end return nil end; local function r8(off) local value=r32(off); if value == nil then return nil end return value % 256 end; return 'surface=' .. tostring(type(snap)=='table' and snap.surface_id or nil) .. '|owner=' .. tostring(owner) .. '|element_selected=' .. tostring(r32(0x1A4)) .. '|discipline_enabled=' .. tostring(r8(0x228)) .. '|discipline_selected=' .. tostring(r32(0x22C))"
}

function Test-CreateSelectionSet {
    param([AllowNull()][string]$Value)

    $numeric = 0L
    if (-not [long]::TryParse($Value, [ref]$numeric)) {
        return $false
    }

    return $numeric -ne -1 -and $numeric -ne 4294967295
}

function Wait-ForCreateElementSelection {
    param([int]$TimeoutSeconds = 5)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastState = ""
    while ((Get-Date) -lt $deadline) {
        $lastState = Read-CreateSelectionState
        $elementValue = $null
        $disciplineEnabled = 0
        if ($lastState -match 'element_selected=([^|]+)') {
            $elementValue = $Matches[1]
        }
        if ($lastState -match 'discipline_enabled=([^|]+)') {
            [void][int]::TryParse($Matches[1], [ref]$disciplineEnabled)
        }

        if ((Test-CreateSelectionSet -Value $elementValue) -and $disciplineEnabled -ne 0) {
            return $true
        }

        Start-Sleep -Milliseconds 250
    }

    Write-TraceLine "stage=create-element-wait-timeout state=$lastState"
    return $false
}

function Invoke-CreateSelectionAutomation {
    param(
        [Parameter(Mandatory = $true)][string]$PresetName
    )

    $selection = Resolve-CreateSelectionPreset -PresetName $PresetName
    if ($null -eq $selection) {
        return
    }

    Wait-ForCreateSurface -TimeoutSeconds 20
    Start-Sleep -Milliseconds 500

    $elementActionId = "create.select_element_$($selection.element)"
    $disciplineActionId = "create.select_discipline_$($selection.discipline)"

    $elementSelected = $false
    for ($attempt = 1; $attempt -le 3 -and -not $elementSelected; $attempt += 1) {
        Write-TraceLine "preset=$PresetName stage=create-semantic action=$elementActionId attempt=$attempt"
        [void](Invoke-SemanticUiAction -ActionId $elementActionId -SurfaceId "create")
        $elementSelected = Wait-ForCreateElementSelection -TimeoutSeconds 5
    }
    if (-not $elementSelected) {
        throw "Timed out waiting for create element selection to latch."
    }

    Write-TraceLine "preset=$PresetName stage=create-semantic action=$disciplineActionId"
    [void](Invoke-SemanticUiAction -ActionId $disciplineActionId -SurfaceId "create")
}

function Wait-ForHubBotReady {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string]$ResolvedBotSet,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $expectedCount = Get-ExpectedBotCount -ResolvedBotSet $ResolvedBotSet
    if ($expectedCount -le 0) {
        return "complete"
    }

    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process SolomonDark -ErrorAction SilentlyContinue)) {
            throw "SolomonDark exited before the hub bot became ready."
        }

        $state = Invoke-LuaExecRaw `
            -Step "Hub bot ready probe" `
            -Code "local count = type(sd.bots) == 'table' and type(sd.bots.get_count) == 'function' and sd.bots.get_count() or 0; local scene = sd.world.get_scene(); return 'scene=' .. tostring(scene and scene.name) .. '|count=' .. tostring(count)"
        if ($state -match 'scene=hub\|count=(\d+)') {
            if ([int]$Matches[1] -ge $expectedCount) {
                return "complete"
            }
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for the hub bot spawn marker."
}

function Wait-ForRunBotReady {
    param(
        [Parameter(Mandatory = $true)][string]$ResolvedBotSet,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $expectedCount = Get-ExpectedBotCount -ResolvedBotSet $ResolvedBotSet
    if ($expectedCount -le 0) {
        return "complete"
    }

    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process SolomonDark -ErrorAction SilentlyContinue)) {
            throw "SolomonDark exited before the run bot became ready."
        }

        $state = Invoke-LuaExecRaw `
            -Step "Run bot ready probe" `
            -Code "local count = type(sd.bots) == 'table' and type(sd.bots.get_count) == 'function' and sd.bots.get_count() or 0; local scene = sd.world.get_scene(); return 'scene=' .. tostring(scene and scene.name) .. '|count=' .. tostring(count)"
        if ($state -match 'scene=testrun\|count=(\d+)') {
            if ([int]$Matches[1] -ge $expectedCount) {
                return "complete"
            }
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for the run bot spawn marker."
}

function Read-LauncherCommandOutput {
    param([Parameter(Mandatory = $true)][object]$LaunchHandle)

    $stdout = if (Test-Path -LiteralPath $LaunchHandle.StdoutPath) {
        Get-Content -LiteralPath $LaunchHandle.StdoutPath -Raw
    }
    else {
        ""
    }
    $stderr = if (Test-Path -LiteralPath $LaunchHandle.StderrPath) {
        Get-Content -LiteralPath $LaunchHandle.StderrPath -Raw
    }
    else {
        ""
    }

    return @{
        Stdout = $stdout
        Stderr = $stderr
    }
}

function Get-LauncherCommandFailureMessage {
    param([Parameter(Mandatory = $true)][object]$LaunchHandle)

    $output = Read-LauncherCommandOutput -LaunchHandle $LaunchHandle
    $exitCode = $null
    if ($null -ne $LaunchHandle.Process) {
        try {
            if ($LaunchHandle.Process.HasExited) {
                $LaunchHandle.Process.WaitForExit()
                $exitCode = $LaunchHandle.Process.ExitCode
            }
        }
        catch {
            $exitCode = $null
        }
    }

    $exitCodeText = if ($null -eq $exitCode) { "(unavailable)" } else { "$exitCode" }
    $details = @($output.Stdout, $output.Stderr) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    if ($details.Count -gt 0) {
        return "$($LaunchHandle.Step) failed with exit code $exitCodeText.`n$($details -join [Environment]::NewLine)"
    }

    return "$($LaunchHandle.Step) failed with exit code $exitCodeText."
}

function Remove-LauncherCommandArtifacts {
    param([object]$LaunchHandle)

    if ($null -eq $LaunchHandle) {
        return
    }

    Remove-Item -LiteralPath $LaunchHandle.StdoutPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $LaunchHandle.StderrPath -Force -ErrorAction SilentlyContinue
}

function Invoke-LauncherCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Step
    )

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()

    try {
        $process = Start-Process `
            -FilePath $launcher `
            -ArgumentList $Arguments `
            -WorkingDirectory $root `
            -Wait `
            -PassThru `
            -NoNewWindow `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath

        $launchHandle = @{
            Step = $Step
            Process = $process
            StdoutPath = $stdoutPath
            StderrPath = $stderrPath
        }

        if ($process.ExitCode -ne 0) {
            throw (Get-LauncherCommandFailureMessage -LaunchHandle $launchHandle)
        }

        return (Read-LauncherCommandOutput -LaunchHandle $launchHandle).Stdout
    }
    finally {
        Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Start-LauncherLaunchCommand {
    param([Parameter(Mandatory = $true)][string]$Step)

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()

    $process = Start-Process `
        -FilePath $launcher `
        -ArgumentList @("launch") `
        -WorkingDirectory $root `
        -PassThru `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    return @{
        Step = $Step
        Process = $process
        StdoutPath = $stdoutPath
        StderrPath = $stderrPath
    }
}

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Launcher not found: $launcher"
}

if ($ScreenshotPath -and -not (Test-Path -LiteralPath $captureScript)) {
    throw "Capture script not found: $captureScript"
}

Stop-SolomonDarkProcess

if (Test-Path -LiteralPath $loaderLog) {
    Remove-Item -LiteralPath $loaderLog -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $traceLog) {
    Remove-Item -LiteralPath $traceLog -Force -ErrorAction SilentlyContinue
}

if ($ScreenshotPath -and (Test-Path -LiteralPath $ScreenshotPath)) {
    Remove-Item -LiteralPath $ScreenshotPath -Force -ErrorAction SilentlyContinue
}

$previousSandboxPresetFileExisted = Test-Path -LiteralPath $sandboxPresetPath
$previousSandboxPresetFileContent = if ($previousSandboxPresetFileExisted) {
    Read-SharedTextFile -Path $sandboxPresetPath
} else {
    $null
}
$resolvedBotSet = Resolve-BotSet -Value $BotSet
Set-ActiveSandboxPreset -PresetName $Preset

$previousSandboxPreset = [Environment]::GetEnvironmentVariable($sandboxPresetEnvVar, "Process")
$previousBotSet = [Environment]::GetEnvironmentVariable($botSetEnvVar, "Process")
[Environment]::SetEnvironmentVariable($sandboxPresetEnvVar, $Preset, "Process")
if ($resolvedBotSet -ne "") {
    [Environment]::SetEnvironmentVariable($botSetEnvVar, $resolvedBotSet, "Process")
}
$launchHandle = $null

try {
    Write-TraceLine "preset=$Preset stage=begin bot_set=$resolvedBotSet"
    Invoke-LauncherCommand -Arguments @("disable-mod", $bootstrapModId) -Step "Disable bootstrap mod" | Out-Null
    Write-TraceLine "preset=$Preset stage=bootstrap-disabled"

    Invoke-LauncherCommand -Arguments @("enable-mod", $sandboxModId) -Step "Enable sandbox mod" | Out-Null
    Write-TraceLine "preset=$Preset stage=sandbox-enabled"
    if ($resolvedBotSet -ne "") {
        Invoke-LauncherCommand -Arguments @("enable-mod", $botsModId) -Step "Enable bot mod" | Out-Null
        Write-TraceLine "preset=$Preset stage=bots-enabled bot_set=$resolvedBotSet"
    }

    $launchHandle = Start-LauncherLaunchCommand -Step "Launcher launch"
    Write-TraceLine "preset=$Preset stage=launch-started pid=$($launchHandle.Process.Id)"

    $process = Wait-ForSolomonDarkProcess -TimeoutSeconds $ProcessStartTimeoutSeconds -LaunchHandle $launchHandle
    Write-TraceLine "preset=$Preset stage=process-started pid=$($process.Id)"
    if ($null -ne $launchHandle -and -not $launchHandle.Process.HasExited) {
        $null = $launchHandle.Process.WaitForExit(2000)
    }
    $launchExitCode = $null
    if ($null -ne $launchHandle -and $launchHandle.Process.HasExited) {
        $launchHandle.Process.WaitForExit()
        $launchExitCode = $launchHandle.Process.ExitCode
    }
    if ($null -ne $launchExitCode -and $launchExitCode -ne 0) {
        throw (Get-LauncherCommandFailureMessage -LaunchHandle $launchHandle)
    }
    Write-TraceLine "preset=$Preset stage=launch-returned exited=$($launchHandle.Process.HasExited) exit_code=$launchExitCode"

    $selection = Resolve-CreateSelectionPreset -PresetName $Preset
    if ($null -ne $selection) {
        Invoke-CreateSelectionAutomation -PresetName $Preset
    }

    if (Test-PresetStartsTestRun -PresetName $Preset) {
        Write-TraceLine "preset=$Preset stage=wait-hub-after-create"
        [void](Wait-ForSceneName -SceneName "hub" -TimeoutSeconds $CompletionTimeoutSeconds)
        Write-TraceLine "preset=$Preset stage=start-testrun"
        Invoke-HubStartTestRun
        Write-TraceLine "preset=$Preset stage=wait-testrun"
        [void](Wait-ForSceneName -SceneName "testrun" -TimeoutSeconds $CompletionTimeoutSeconds)
        $outcome = Wait-ForRunBotReady -ResolvedBotSet $resolvedBotSet -TimeoutSeconds $CompletionTimeoutSeconds
    }
    elseif ($null -ne $selection -and $Preset -match '_hub$') {
        $outcome = Wait-ForHubBotReady -LogPath $loaderLog -ResolvedBotSet $resolvedBotSet -TimeoutSeconds $CompletionTimeoutSeconds
    }
    else {
        $outcome = Wait-ForSandboxOutcome -LogPath $loaderLog -PresetName $Preset -TimeoutSeconds $CompletionTimeoutSeconds
    }
    Write-TraceLine "preset=$Preset stage=outcome outcome=$outcome"

    $resolvedPostKeys = @()
    foreach ($entry in $PostKeys) {
        foreach ($part in ($entry -split ',')) {
            $trimmed = $part.Trim()
            if ($trimmed -ne "") {
                $resolvedPostKeys += $trimmed
            }
        }
    }
    if ($resolvedPostKeys.Count -gt 0) {
        Write-TraceLine "preset=$Preset stage=post-keys keys=$($resolvedPostKeys -join ',') interval_ms=$PostKeyIntervalMs"
        $sendKeysArgs = @(
            "-3",
            $sendKeysScript,
            "--pid",
            $process.Id,
            "--activate",
            "--interval-ms",
            $PostKeyIntervalMs
        ) + $resolvedPostKeys
        & py @sendKeysArgs
        Assert-LastExitCode "Post-key send"
        if ($PostKeySettleMs -gt 0) {
            Start-Sleep -Milliseconds $PostKeySettleMs
        }
        Write-TraceLine "preset=$Preset stage=post-keys-done"
    }

    if ($ScreenshotPath) {
        $captureArgs = @(
            "-3",
            $captureScript,
            "--pid",
            $process.Id,
            "--output",
            $ScreenshotPath,
            "--method",
            $CaptureMethod
        )
        if ($CaptureMethod -eq "screen") {
            $captureArgs += "--activate"
        }

        & py @captureArgs
        Assert-LastExitCode "Window capture"
    }

    $processAliveBeforeCleanup = $null -ne (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)
    Write-TraceLine "preset=$Preset stage=process-alive-before-cleanup alive=$processAliveBeforeCleanup"

    if (-not $KeepRunning) {
        Write-TraceLine "preset=$Preset stage=stop-game-begin"
        Stop-SolomonDarkProcess
        Write-TraceLine "preset=$Preset stage=stop-game-end"
    }

    $processAlive = $null -ne (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)
    Write-TraceLine "preset=$Preset stage=process-alive-after-cleanup alive=$processAlive"

    Write-Output "PRESET=$Preset"
    Write-Output "BOT_SET=$resolvedBotSet"
    Write-Output "OUTCOME=$outcome"
    Write-Output "PROCESS_ID=$($process.Id)"
    Write-Output "PROCESS_ALIVE=$processAlive"
}
finally {
    Write-TraceLine "preset=$Preset stage=finally"
    Remove-LauncherCommandArtifacts -LaunchHandle $launchHandle
    [Environment]::SetEnvironmentVariable($sandboxPresetEnvVar, $previousSandboxPreset, "Process")
    [Environment]::SetEnvironmentVariable($botSetEnvVar, $previousBotSet, "Process")
    Restore-ActiveSandboxPreset -Existed $previousSandboxPresetFileExisted -Content $previousSandboxPresetFileContent
}
