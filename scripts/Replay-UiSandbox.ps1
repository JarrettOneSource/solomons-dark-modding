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
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root "dist/launcher/SolomonDarkModLauncher.exe"
$captureScript = Join-Path $PSScriptRoot "capture_window.py"
$sendKeysScript = Join-Path $PSScriptRoot "send_window_keys.py"
$loaderLog = Join-Path $root "runtime/stage/.sdmod/logs/solomondarkmodloader.log"
$sandboxPresetPath = Join-Path $root "mods/lua_ui_sandbox_lab/config/active_preset.txt"
$traceLog = Join-Path $root "runtime/replay-ui-sandbox.log"
$sandboxModId = "sample.lua.ui_sandbox_lab"
$bootstrapModId = "sample.lua.dark_cloud_sort_bootstrap"
$sandboxPresetEnvVar = "SDMOD_UI_SANDBOX_PRESET"

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

Set-ActiveSandboxPreset -PresetName $Preset

$previousSandboxPreset = [Environment]::GetEnvironmentVariable($sandboxPresetEnvVar, "Process")
[Environment]::SetEnvironmentVariable($sandboxPresetEnvVar, $Preset, "Process")
$launchHandle = $null

try {
    Write-TraceLine "preset=$Preset stage=begin"
    Invoke-LauncherCommand -Arguments @("disable-mod", $bootstrapModId) -Step "Disable bootstrap mod" | Out-Null
    Write-TraceLine "preset=$Preset stage=bootstrap-disabled"

    Invoke-LauncherCommand -Arguments @("enable-mod", $sandboxModId) -Step "Enable sandbox mod" | Out-Null
    Write-TraceLine "preset=$Preset stage=sandbox-enabled"

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
    $outcome = Wait-ForSandboxOutcome -LogPath $loaderLog -PresetName $Preset -TimeoutSeconds $CompletionTimeoutSeconds
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
    Write-Output "OUTCOME=$outcome"
    Write-Output "PROCESS_ID=$($process.Id)"
    Write-Output "PROCESS_ALIVE=$processAlive"
}
finally {
    Write-TraceLine "preset=$Preset stage=finally"
    Remove-LauncherCommandArtifacts -LaunchHandle $launchHandle
    [Environment]::SetEnvironmentVariable($sandboxPresetEnvVar, $previousSandboxPreset, "Process")
}
