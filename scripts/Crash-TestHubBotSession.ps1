[CmdletBinding()]
param(
    [string]$Preset = "enter_gameplay_wait",
    [ValidateRange(60, 900)]
    [int]$SoakSeconds = 180,
    [ValidateRange(10, 300)]
    [int]$ReadyTimeoutSeconds = 120,
    [ValidateRange(1, 30)]
    [int]$ProbeIntervalSeconds = 5,
    [ValidateRange(1, 60)]
    [int]$ProbeTimeoutSeconds = 10,
    [ValidateRange(1, 10)]
    [int]$FreezeFailureThreshold = 2,
    [switch]$RequireAttachmentLane,
    [switch]$KeepRunning
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root "dist/launcher/SolomonDarkModLauncher.exe"
$luaExecScript = Join-Path $PSScriptRoot "Invoke-LuaExec.ps1"
$captureScript = Join-Path $PSScriptRoot "Capture-SolomonDarkWindow.ps1"
$procdumpPath = Join-Path $root "tools/procdump/procdump.exe"
$presetPath = Join-Path $root "mods/lua_ui_sandbox_lab/config/active_preset.txt"
$loaderLogPath = Join-Path $root "runtime/stage/.sdmod/logs/solomondarkmodloader.log"
$crashLogPath = Join-Path $root "runtime/stage/.sdmod/logs/solomondarkmodloader.crash.log"
$stageReportPath = Join-Path $root "runtime/stage/.sdmod/stage-report.json"

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$artifactRoot = Join-Path $root "runtime/crash-tests/$timestamp"
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null

function Read-SharedTextFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

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
        } elseif ($stream -ne $null) {
            $stream.Dispose()
        }
    }
}

function Get-SharedTail {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$MaxLines = 80
    )

    $text = Read-SharedTextFile -Path $Path
    if ([string]::IsNullOrWhiteSpace($text)) {
        return @()
    }

    return ($text -split "`r?`n" | Where-Object { $_ -ne "" } | Select-Object -Last $MaxLines)
}

function Get-SolomonDarkProcess {
    return Get-Process SolomonDark -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Get-ProcessInfo {
    $process = Get-SolomonDarkProcess
    if ($null -eq $process) {
        return $null
    }

    return [ordered]@{
        id = $process.Id
        responding = $process.Responding
        cpu = $process.CPU
        ws = $process.WorkingSet64
        start_time = $process.StartTime.ToString("o")
    }
}

function Get-NewArtifacts {
    param([datetime]$SinceUtc)

    $paths = @(
        $loaderLogPath,
        $crashLogPath
    )

    $logDirectory = Split-Path -Parent $crashLogPath
    if (Test-Path -LiteralPath $logDirectory) {
        $paths += Get-ChildItem -LiteralPath $logDirectory -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @(".dmp", ".mdmp") } |
            Where-Object { $_.LastWriteTimeUtc -ge $SinceUtc } |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -ExpandProperty FullName
    }

    return @($paths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -Unique)
}

function Test-AutomationComplete {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string]$PresetName
    )

    if (-not (Test-Path -LiteralPath $LogPath)) {
        return $false
    }

    return (Read-SharedTextFile -Path $LogPath).Contains("sequence complete preset=$PresetName")
}

function Invoke-LuaProbe {
    param([Parameter(Mandatory = $true)][string]$Code)

    $stdoutPath = Join-Path $artifactRoot ("probe_stdout_{0:yyyyMMdd_HHmmss_fff}.log" -f (Get-Date))
    $stderrPath = Join-Path $artifactRoot ("probe_stderr_{0:yyyyMMdd_HHmmss_fff}.log" -f (Get-Date))
    $process = $null
    $output = ""
    $exitCode = -1
    try {
        $process = Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList @(
                "-NoProfile",
                "-File",
                $luaExecScript,
                "-Code",
                $Code
            ) `
            -PassThru `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath

        if (-not $process.WaitForExit($ProbeTimeoutSeconds * 1000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            return [ordered]@{
                ok = $false
                exit_code = -2
                text = "Lua probe timed out after ${ProbeTimeoutSeconds}s."
            }
        }

        $exitCode = $process.ExitCode
        $stdout = if (Test-Path -LiteralPath $stdoutPath) {
            Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue
        }
        else {
            ""
        }
        $stderr = if (Test-Path -LiteralPath $stderrPath) {
            Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
        }
        else {
            ""
        }
        $output = @($stdout, $stderr) -join [Environment]::NewLine
    }
    finally {
        Remove-Item -LiteralPath $stdoutPath,$stderrPath -Force -ErrorAction SilentlyContinue
    }

    return [ordered]@{
        ok = ($exitCode -eq 0)
        exit_code = $exitCode
        text = (($output | ForEach-Object { "$_" }) -join [Environment]::NewLine).Trim()
    }
}

function Capture-ScreenshotArtifact {
    param([string]$Label)

    $path = Join-Path $artifactRoot "$Label.png"
    try {
        & $captureScript -OutputPath $path -StartupTimeoutSeconds 5 | Out-Null
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }
    catch {
    }

    return $null
}

function Capture-HangDumpArtifact {
    param([int]$ProcessId)

    if (-not (Test-Path -LiteralPath $procdumpPath)) {
        return $null
    }

    $path = Join-Path $artifactRoot "freeze_dump_$ProcessId.dmp"
    try {
        & $procdumpPath -accepteula -ma $ProcessId $path | Out-Null
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }
    catch {
    }

    return $null
}

function Stop-SolomonDark {
    & cmd.exe /c "taskkill /IM SolomonDark.exe /F /T >NUL 2>&1" | Out-Null
}

$probeCode = @'
local scene = type(sd) == "table" and type(sd.world) == "table" and type(sd.world.get_scene) == "function" and sd.world.get_scene() or nil
local bots = type(sd) == "table" and type(sd.bots) == "table" and type(sd.bots.get_state) == "function" and sd.bots.get_state() or nil
local bot = type(bots) == "table" and bots[1] or nil
local attachment = type(bot) == "table" and bot.attachment_visual_lane or nil
local primary = type(bot) == "table" and bot.primary_visual_lane or nil
local secondary = type(bot) == "table" and bot.secondary_visual_lane or nil
return table.concat({
  "scene=" .. tostring(scene and scene.name or "nil"),
  "kind=" .. tostring(scene and scene.kind or "nil"),
  "bot_available=" .. tostring(bot and bot.available or false),
  "bot_materialized=" .. tostring(bot and (bot.materialized == true or ((bot.actor or 0) ~= 0)) or false),
  "bot_actor=" .. tostring(bot and (bot.actor or 0) or 0),
  "bot_slot=" .. tostring(bot and (bot.gameplay_slot or bot.slot or "nil") or "nil"),
  "attach_type=" .. tostring(attachment and (attachment.current_object_type_id or 0) or 0),
  "attach_obj=" .. tostring(attachment and (attachment.current_object_address or 0) or 0),
  "primary_type=" .. tostring(primary and (primary.current_object_type_id or 0) or 0),
  "secondary_type=" .. tostring(secondary and (secondary.current_object_type_id or 0) or 0)
}, "|")
'@

$originalPreset = if (Test-Path -LiteralPath $presetPath) {
    Get-Content -LiteralPath $presetPath -Raw
}
else {
    $null
}

$summary = [ordered]@{
    status = "unknown"
    preset = $Preset
    soak_seconds = $SoakSeconds
    ready_timeout_seconds = $ReadyTimeoutSeconds
    probe_interval_seconds = $ProbeIntervalSeconds
    probe_timeout_seconds = $ProbeTimeoutSeconds
    freeze_failure_threshold = $FreezeFailureThreshold
    require_attachment_lane = $RequireAttachmentLane.IsPresent
    process = $null
    launch_transcript = $null
    launch_transcript_path = $null
    readiness_elapsed_seconds = $null
    soak_elapsed_seconds = $null
    automation_complete_seen = $false
    probe_output = @()
    artifacts = [ordered]@{
        screenshot = $null
        freeze_dump = $null
        crash_artifacts = @()
        stage_report = if (Test-Path -LiteralPath $stageReportPath) { $stageReportPath } else { $null }
        loader_log = if (Test-Path -LiteralPath $loaderLogPath) { $loaderLogPath } else { $null }
        crash_log = if (Test-Path -LiteralPath $crashLogPath) { $crashLogPath } else { $null }
    }
    loader_log_tail = @()
    crash_log_tail = @()
}

$startedUtc = [datetime]::UtcNow

try {
    Stop-SolomonDark
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $presetPath) | Out-Null
    Set-Content -LiteralPath $presetPath -Value $Preset -NoNewline -Encoding ASCII
    $env:SDMOD_UI_SANDBOX_PRESET = $Preset

    $launchOutput = & $launcher launch --json
    if ($LASTEXITCODE -ne 0) {
        throw "Launcher launch --json failed with exit code $LASTEXITCODE."
    }

    $launch = $launchOutput | ConvertFrom-Json
    if (-not $launch.success) {
        throw "Launcher reported failure: $($launch.error)"
    }

    $launchTranscriptPath = Join-Path $artifactRoot "launch.json"
    Set-Content -LiteralPath $launchTranscriptPath -Value $launchOutput -Encoding UTF8

    $summary.process = [ordered]@{
        pid = $launch.launch.processId
        startup_code = $launch.launch.startupCode
        startup_message = $launch.launch.startupMessage
    }
    $summary.launch_transcript = $launch.transcript
    $summary.launch_transcript_path = $launchTranscriptPath

    $readyStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $consecutiveProbeFailures = 0
    while ($readyStopwatch.Elapsed.TotalSeconds -lt $ReadyTimeoutSeconds) {
        $processInfo = Get-ProcessInfo
        if ($null -eq $processInfo) {
            $summary.status = if ($summary.automation_complete_seen) { "crashed_after_automation" } else { "crashed_before_ready" }
            break
        }

        if (-not $summary.automation_complete_seen -and (Test-AutomationComplete -LogPath $loaderLogPath -PresetName $Preset)) {
            $summary.automation_complete_seen = $true
        }

        $probe = Invoke-LuaProbe -Code $probeCode
        if ($probe.ok) {
            $summary.probe_output += $probe.text
            $consecutiveProbeFailures = 0

            $ready = $summary.automation_complete_seen -and
                $probe.text -match 'scene=hub' -and
                $probe.text -match 'bot_available=true'
            if ($RequireAttachmentLane) {
                $ready = $ready -and
                    ($probe.text -match 'attach_type=(?!0\b)\d+') -and
                    ($probe.text -match 'attach_obj=(?!0\b)\d+')
            }
            if ($ready) {
                $summary.readiness_elapsed_seconds = [math]::Round($readyStopwatch.Elapsed.TotalSeconds, 2)
                $summary.status = "ready"
                break
            }
        }
        else {
            $summary.probe_output += $probe.text
            $consecutiveProbeFailures += 1
        }

        Start-Sleep -Seconds $ProbeIntervalSeconds
    }

    if ($summary.status -eq "unknown") {
        $summary.status = "ready_timeout"
    }

    if ($summary.status -eq "ready") {
        $soakStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        $consecutiveProbeFailures = 0
        while ($soakStopwatch.Elapsed.TotalSeconds -lt $SoakSeconds) {
            $processInfo = Get-ProcessInfo
            if ($null -eq $processInfo) {
                $summary.status = "crashed_during_soak"
                break
            }

            if ($processInfo.responding -eq $false) {
                $summary.status = "frozen_not_responding"
                $summary.artifacts.screenshot = Capture-ScreenshotArtifact -Label "freeze_window"
                $summary.artifacts.freeze_dump = Capture-HangDumpArtifact -ProcessId $processInfo.id
                Stop-SolomonDark
                break
            }

            $probe = Invoke-LuaProbe -Code $probeCode
            $summary.probe_output += $probe.text
            if ($probe.ok) {
                $consecutiveProbeFailures = 0
            }
            else {
                $consecutiveProbeFailures += 1
                if ($consecutiveProbeFailures -ge $FreezeFailureThreshold) {
                    $summary.status = "frozen_lua_unresponsive"
                    $summary.artifacts.screenshot = Capture-ScreenshotArtifact -Label "freeze_window"
                    $summary.artifacts.freeze_dump = Capture-HangDumpArtifact -ProcessId $processInfo.id
                    Stop-SolomonDark
                    break
                }
            }

            Start-Sleep -Seconds $ProbeIntervalSeconds
        }

        $summary.soak_elapsed_seconds = [math]::Round($soakStopwatch.Elapsed.TotalSeconds, 2)
        if ($summary.status -eq "ready") {
            $summary.status = "passed"
        }
    }

    $summary.artifacts.crash_artifacts = Get-NewArtifacts -SinceUtc $startedUtc
    $summary.loader_log_tail = Get-SharedTail -Path $loaderLogPath
    $summary.crash_log_tail = Get-SharedTail -Path $crashLogPath
}
finally {
    if (-not $KeepRunning) {
        Stop-SolomonDark
    }

    if ($null -eq $originalPreset) {
        Remove-Item -LiteralPath $presetPath -Force -ErrorAction SilentlyContinue
    }
    else {
        Set-Content -LiteralPath $presetPath -Value $originalPreset -Encoding ASCII
    }
}

$summaryPath = Join-Path $artifactRoot "summary.json"
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Output $summaryPath
if ($summary.status -ne "passed") {
    exit 1
}
