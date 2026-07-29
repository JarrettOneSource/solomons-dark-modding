[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$StageRoot,

    [Parameter(Mandatory = $true)]
    [string]$RequestPath,

    [Parameter(Mandatory = $true)]
    [string]$ResultPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[a-z0-9][a-z0-9-]{0,39}$")]
    [string]$TaskToken,

    [ValidateRange(10, 600)]
    [int]$TimeoutSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$expectedStageRoot = Join-Path $env:USERPROFILE "sd-netrepro-stage"
if (-not [string]::Equals(
        [System.IO.Path]::GetFullPath($StageRoot).TrimEnd("\"),
        [System.IO.Path]::GetFullPath($expectedStageRoot).TrimEnd("\"),
        [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The workstation20 controller is confined to the temporary account staging root."
}
foreach ($path in @($RequestPath, $ResultPath)) {
    $fullPath = [System.IO.Path]::GetFullPath($path)
    $prefix = [System.IO.Path]::GetFullPath($StageRoot).TrimEnd("\") + "\"
    if (-not $fullPath.StartsWith(
            $prefix,
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Session control path escapes the staging root: $path"
    }
}
if (-not (Test-Path -LiteralPath $RequestPath -PathType Leaf)) {
    throw "Session request is missing: $RequestPath"
}
if (Test-Path -LiteralPath $ResultPath) {
    throw "Session result path must be new: $ResultPath"
}

$worker = Join-Path $StageRoot "tools\Run-RealFlowWindowsSessionWorker.ps1"
if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) {
    throw "Session worker is missing: $worker"
}
$steam = @(
    Get-Process steam -IncludeUserName -ErrorAction Stop |
        Where-Object { $_.SessionId -gt 0 }
)
if ($steam.Count -ne 1) {
    throw "Expected exactly one logged-on interactive Steam process."
}
$steamProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($steam[0].Id)"
$owner = Invoke-CimMethod -InputObject $steamProcess -MethodName GetOwner
if ($owner.ReturnValue -ne 0 -or [string]::IsNullOrWhiteSpace($owner.User)) {
    throw "Could not resolve the owner of the interactive Steam process."
}
$userId = "$($owner.Domain)\$($owner.User)"
$taskName = "SolomonDarkNetrepro_$TaskToken"
$task = $null
try {
    Unregister-ScheduledTask `
        -TaskName $taskName `
        -Confirm:$false `
        -ErrorAction SilentlyContinue
    $quotedWorker = '"' + $worker.Replace('"', '""') + '"'
    $quotedRequest = '"' + $RequestPath.Replace('"', '""') + '"'
    $quotedResult = '"' + $ResultPath.Replace('"', '""') + '"'
    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $quotedWorker,
        "-RequestPath", $quotedRequest,
        "-ResultPath", $quotedResult
    ) -join " "
    $action = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -Argument $arguments `
        -WorkingDirectory $StageRoot
    $principal = New-ScheduledTaskPrincipal `
        -UserId $userId `
        -LogonType Interactive `
        -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Seconds $TimeoutSeconds) `
        -MultipleInstances IgnoreNew
    $task = Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Principal $principal `
        -Settings $settings `
        -Force
    $startedAt = [DateTime]::UtcNow
    Start-ScheduledTask -TaskName $taskName
    $deadline = $startedAt.AddSeconds($TimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 100
        if (Test-Path -LiteralPath $ResultPath -PathType Leaf) {
            $text = Get-Content -LiteralPath $ResultPath -Raw
            $parsed = $text | ConvertFrom-Json -ErrorAction Stop
            if (-not $parsed.ok) {
                throw "Interactive session action failed: $($parsed.error.message)"
            }
            [Console]::Out.Write($text.Trim())
            return
        }
        $info = Get-ScheduledTaskInfo -TaskName $taskName
        $state = (Get-ScheduledTask -TaskName $taskName).State
        if (
            $info.LastRunTime -ge $startedAt.AddSeconds(-1) -and
            $state -eq "Ready" -and
            [int64]$info.LastTaskResult -ne 267009
        ) {
            throw "Interactive session action exited without a result; task result=$($info.LastTaskResult)."
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Interactive session action timed out after $TimeoutSeconds seconds."
} finally {
    if ($null -ne $task) {
        Unregister-ScheduledTask `
            -TaskName $taskName `
            -Confirm:$false `
            -ErrorAction SilentlyContinue
    }
}
