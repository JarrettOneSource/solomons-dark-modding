param(
    [string]$Preset = "title_menu_to_settings",
    [ValidateRange(5, 120)]
    [int]$StartTimeoutSeconds = 30,
    [ValidateRange(1, 30)]
    [int]$ProbeTimeoutSeconds = 10,
    [switch]$KeepGameOpen
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$replayScript = Join-Path $PSScriptRoot "Replay-UiSandbox.ps1"
$loaderLog = Join-Path $root "runtime/stage/.sdmod/logs/solomondarkmodloader.log"
$settingsRegex = [regex]"Debug UI settings action mapped: settings=0x([0-9A-F]+) label=CUSTOMIZE KEYBOARD action=settings.controls source=0x([0-9A-F]+) owner=0x([0-9A-F]+) child=0x([0-9A-F]+) callback_owner=0x([0-9A-F]+)"

function Resolve-CdbPath {
    $preferredPaths = @(
        "C:\Program Files\WindowsApps\Microsoft.WinDbg_1.2601.12001.0_x64__8wekyb3d8bbwe\x86\cdb.exe"
    )

    foreach ($path in $preferredPaths) {
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }

    $roots = @(
        "C:\Program Files\WindowsApps",
        "C:\Program Files (x86)\Windows Kits",
        "C:\Program Files\Windows Kits"
    )

    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }

        $match = Get-ChildItem -LiteralPath $root -Recurse -Filter cdb.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\x86\\cdb\.exe$" } |
            Select-Object -First 1
        if ($null -ne $match) {
            return $match.FullName
        }
    }

    throw "Unable to resolve x86 cdb.exe."
}

function Stop-ReplayArtifacts {
    param(
        [System.Diagnostics.Process]$ReplayProcess,
        [string]$ReplayStdoutPath = "",
        [string]$ReplayStderrPath = ""
    )

    Get-Process SolomonDark -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if ($null -ne $ReplayProcess -and -not $ReplayProcess.HasExited) {
        Stop-Process -Id $ReplayProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($ReplayStdoutPath -and (Test-Path -LiteralPath $ReplayStdoutPath)) {
        Remove-Item -LiteralPath $ReplayStdoutPath -Force -ErrorAction SilentlyContinue
    }
    if ($ReplayStderrPath -and (Test-Path -LiteralPath $ReplayStderrPath)) {
        Remove-Item -LiteralPath $ReplayStderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Wait-ForSolomonDark {
    param(
        [int]$TimeoutSeconds,
        [System.Diagnostics.Process]$ReplayProcess = $null,
        [string]$ReplayStdoutPath = "",
        [string]$ReplayStderrPath = ""
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $process = Get-Process SolomonDark -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $process) {
            return $process
        }

        if ($null -ne $ReplayProcess -and $ReplayProcess.HasExited) {
            $stdout = if ($ReplayStdoutPath -and (Test-Path -LiteralPath $ReplayStdoutPath)) {
                Get-Content -LiteralPath $ReplayStdoutPath -Raw
            }
            else {
                ""
            }
            $stderr = if ($ReplayStderrPath -and (Test-Path -LiteralPath $ReplayStderrPath)) {
                Get-Content -LiteralPath $ReplayStderrPath -Raw
            }
            else {
                ""
            }
            $details = @($stdout.Trim(), $stderr.Trim()) | Where-Object { $_ }
            throw ("Replay helper exited before SolomonDark started. ExitCode={0}{1}" -f $ReplayProcess.ExitCode, $(if ($details.Count -gt 0) { "`n" + ($details -join "`n") } else { "" }))
        }

        Start-Sleep -Milliseconds 100
    }

    throw "Timed out waiting for SolomonDark."
}

function Wait-ForCustomizeMapping {
    param(
        [string]$Path,
        [regex]$Pattern,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $Path) {
            $contents = Get-Content -LiteralPath $Path -Raw
            $match = $Pattern.Match($contents)
            if ($match.Success) {
                return $match
            }
        }

        Start-Sleep -Milliseconds 50
    }

    throw "Timed out waiting for the Customize Keyboard mapping line."
}

function Invoke-CdbDump {
    param(
        [string]$CdbPath,
        [int]$ProcessId,
        [UInt32]$ExeBaseAddress,
        [string]$SettingsHex,
        [string]$SourceHex,
        [string]$CallbackOwnerHex
    )

    $preferredExeBase = 0x00400000
    $globalAddresses = @(
        0x0081c264,
        0x008203ec,
        0x008203e8
    ) | ForEach-Object {
        '{0:x8}' -f ($ExeBaseAddress + ($_ - $preferredExeBase))
    }

    $commands = @(
        "dd $($globalAddresses[0]) L1",
        "dd $($globalAddresses[1]) L1",
        "dd $($globalAddresses[2]) L1",
        "dd $SettingsHex L8",
        "dd $SettingsHex+2ec L4",
        "dd $SettingsHex+15a0 L1",
        "dd $SettingsHex+1654 L4",
        "dd $SettingsHex+1664 L1",
        "dd $SourceHex L16",
        "dd $SourceHex+c4 L8",
        "dd poi($SourceHex+c4) L8",
        "dd poi(poi($SourceHex+c4))+cc L1",
        "dd $SourceHex+f0 L4",
        "dd $CallbackOwnerHex L8",
        "q"
    ) -join ";"

    return (& $CdbPath -p $ProcessId -c $commands 2>&1 | Out-String)
}

$cdbPath = Resolve-CdbPath
$replayProcess = $null
$replayStdoutPath = [System.IO.Path]::GetTempFileName()
$replayStderrPath = [System.IO.Path]::GetTempFileName()

try {
    Stop-ReplayArtifacts -ReplayStdoutPath $replayStdoutPath -ReplayStderrPath $replayStderrPath
    if (Test-Path -LiteralPath $loaderLog) {
        Remove-Item -LiteralPath $loaderLog -Force -ErrorAction SilentlyContinue
    }

    $replayProcess = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"{0}"' -f $replayScript), "-Preset", $Preset, "-KeepRunning") `
        -WorkingDirectory $root `
        -PassThru `
        -RedirectStandardOutput $replayStdoutPath `
        -RedirectStandardError $replayStderrPath

    $gameProcess = Wait-ForSolomonDark `
        -TimeoutSeconds $StartTimeoutSeconds `
        -ReplayProcess $replayProcess `
        -ReplayStdoutPath $replayStdoutPath `
        -ReplayStderrPath $replayStderrPath
    $match = Wait-ForCustomizeMapping -Path $loaderLog -Pattern $settingsRegex -TimeoutSeconds $ProbeTimeoutSeconds

    $settingsHex = $match.Groups[1].Value
    $sourceHex = $match.Groups[2].Value
    $ownerHex = $match.Groups[3].Value
    $childHex = $match.Groups[4].Value
    $callbackOwnerHex = $match.Groups[5].Value
    $exeBaseAddress = [UInt32]$gameProcess.MainModule.BaseAddress.ToInt64()
    $dump = Invoke-CdbDump `
        -CdbPath $cdbPath `
        -ProcessId $gameProcess.Id `
        -ExeBaseAddress $exeBaseAddress `
        -SettingsHex $settingsHex `
        -SourceHex $sourceHex `
        -CallbackOwnerHex $callbackOwnerHex
    $logTail = if (Test-Path -LiteralPath $loaderLog) {
        Get-Content -LiteralPath $loaderLog -Tail 80 | Out-String
    }
    else {
        ""
    }

    Write-Output "PID=$($gameProcess.Id)"
    Write-Output ("EXE_BASE=0x{0:x8}" -f $exeBaseAddress)
    Write-Output "SETTINGS=0x$settingsHex"
    Write-Output "SOURCE=0x$sourceHex"
    Write-Output "OWNER=0x$ownerHex"
    Write-Output "CHILD=0x$childHex"
    Write-Output "CALLBACK_OWNER=0x$callbackOwnerHex"
    Write-Output "---CDB---"
    Write-Output $dump.TrimEnd()
    Write-Output "---LOG-TAIL---"
    Write-Output $logTail.TrimEnd()
}
finally {
    if (-not $KeepGameOpen) {
        Stop-ReplayArtifacts `
            -ReplayProcess $replayProcess `
            -ReplayStdoutPath $replayStdoutPath `
            -ReplayStderrPath $replayStderrPath
    }
}
