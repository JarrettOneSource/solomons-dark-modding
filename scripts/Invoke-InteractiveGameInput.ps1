[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("activate", "key", "click", "drag", "release")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$ProcessId,

    [ValidateSet(
        "enter", "escape", "space", "tab", "up", "down", "left", "right",
        "home", "end", "pageup", "pagedown", "a", "d", "s", "w"
    )]
    [string]$Key = "d",

    [ValidateRange(0, 10000)]
    [int]$HoldMilliseconds = 0,

    [ValidateRange(0.0, 1.0)]
    [double]$X = 0.0,

    [ValidateRange(0.0, 1.0)]
    [double]$Y = 0.0,

    [ValidateRange(0.0, 1.0)]
    [double]$DestinationX = 0.0,

    [ValidateRange(0.0, 1.0)]
    [double]$DestinationY = 0.0,

    [ValidateRange(1, 60)]
    [int]$TimeoutSeconds = 20,

    [string]$HelperDirectory = "C:\Users\Public\Documents\SolomonDarkBeta5RemoteTest\ui-test-helpers",

    [Parameter(Mandatory = $true)]
    [string]$ExpectedExecutablePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Require-HelperFile {
    param([Parameter(Mandatory = $true)][string]$Name)

    $path = Join-Path $HelperDirectory $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required interactive input helper is missing: $path"
    }
    return $path
}

$gameProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
if (
    $null -eq $gameProcess -or
    $gameProcess.Name -ne "SolomonDark.exe" -or
    -not [string]::Equals(
        [string]$gameProcess.ExecutablePath,
        $ExpectedExecutablePath,
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "Process $ProcessId is not the exact SolomonDark.exe test process."
}
if ([int]$gameProcess.SessionId -le 0) {
    throw "SolomonDark.exe process $ProcessId is not in an interactive session."
}

$owner = Invoke-CimMethod -InputObject $gameProcess -MethodName GetOwner
if ($owner.ReturnValue -ne 0 -or [string]::IsNullOrWhiteSpace($owner.User)) {
    throw "Could not resolve the interactive owner of SolomonDark.exe process $ProcessId."
}
$userId = "$($owner.Domain)\$($owner.User)"

$python = (Get-Command py.exe -ErrorAction Stop).Source
$resultPath = Join-Path $HelperDirectory "interactive-input-result-$ProcessId.txt"
Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue
$argumentList = switch ($Action) {
    "activate" {
        @(
            "-3", ('"{0}"' -f (Require-HelperFile "activate_window.py")),
            "--pid", $ProcessId, "--delay-ms", 100
        )
    }
    "key" {
        @(
            "-3", ('"{0}"' -f (Require-HelperFile "send_window_keys.py")),
            "--pid", $ProcessId, "--activate", "--activation-delay-ms", 150,
            "--hold-ms", $HoldMilliseconds, "--post-delay-ms", 100, $Key
        )
    }
    "click" {
        @(
            "-3", ('"{0}"' -f (Require-HelperFile "click_window.py")),
            "--pid", $ProcessId, "--relative", "--x", $X, "--y", $Y,
            "--result-path", ('"{0}"' -f $resultPath),
            "--activate", "--activation-delay-ms", 150, "--post-delay-ms", 150,
            "--hold-ms", 300, "--button", "left", "--global-only"
        )
    }
    "drag" {
        @(
            "-3", ('"{0}"' -f (Require-HelperFile "click_window.py")),
            "--pid", $ProcessId, "--relative", "--x", $X, "--y", $Y,
            "--drag-x", $DestinationX, "--drag-y", $DestinationY,
            "--result-path", ('"{0}"' -f $resultPath),
            "--activate", "--activation-delay-ms", 150, "--post-delay-ms", 500,
            "--hold-ms", 600, "--button", "left", "--global-only"
        )
    }
    "release" {
        @(
            "-3", ('"{0}"' -f (Require-HelperFile "click_window.py")),
            "--release-only", "--button", "left",
            "--result-path", ('"{0}"' -f $resultPath)
        )
    }
}

$taskName = "SolomonDarkBeta5InteractiveInput_$ProcessId"
$task = $null
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    $taskAction = New-ScheduledTaskAction `
        -Execute $python `
        -Argument ($argumentList -join " ") `
        -WorkingDirectory $HelperDirectory
    $principal = New-ScheduledTaskPrincipal `
        -UserId $userId `
        -LogonType Interactive `
        -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Seconds $TimeoutSeconds) `
        -MultipleInstances IgnoreNew
    $task = Register-ScheduledTask `
        -TaskName $taskName `
        -Action $taskAction `
        -Principal $principal `
        -Settings $settings `
        -Force

    $startedAt = Get-Date
    Start-ScheduledTask -TaskName $taskName
    $deadline = $startedAt.AddSeconds($TimeoutSeconds)
    $lastResult = $null
    do {
        Start-Sleep -Milliseconds 50
        $taskState = (Get-ScheduledTask -TaskName $taskName).State
        $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
        if ($taskInfo.LastRunTime -ge $startedAt.AddSeconds(-1) -and $taskState -eq "Ready") {
            $lastResult = [int64]$taskInfo.LastTaskResult
            break
        }
    } while ((Get-Date) -lt $deadline)

    if ($null -eq $lastResult) {
        throw "Interactive input action '$Action' timed out for process $ProcessId."
    }
    if ($lastResult -ne 0) {
        throw "Interactive input action '$Action' failed with task result $lastResult."
    }

    Write-Output "ok=true"
    Write-Output "action=$Action"
    Write-Output "process_id=$ProcessId"
    Write-Output "session_id=$($gameProcess.SessionId)"
    if (Test-Path -LiteralPath $resultPath -PathType Leaf) {
        $helperResult = (Get-Content -LiteralPath $resultPath -Raw).Trim()
        Write-Output "helper_result=$helperResult"
    }
} finally {
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue
}
