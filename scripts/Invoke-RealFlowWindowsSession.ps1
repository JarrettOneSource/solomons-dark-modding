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

$resolvedStageRoot = [System.IO.Path]::GetFullPath($StageRoot).TrimEnd("\")
$steam = @(
    Get-Process steam -IncludeUserName -ErrorAction Stop |
        Where-Object { $_.SessionId -gt 0 }
)
if ($steam.Count -ne 1) {
    throw "Expected exactly one logged-on interactive Steam process."
}
$steamProcess =
    Get-CimInstance Win32_Process -Filter "ProcessId=$($steam[0].Id)"
$owner = Invoke-CimMethod -InputObject $steamProcess -MethodName GetOwner
if ($owner.ReturnValue -ne 0 -or [string]::IsNullOrWhiteSpace($owner.User)) {
    throw "Could not resolve the owner of the interactive Steam process."
}
$ownerSid = Invoke-CimMethod -InputObject $steamProcess -MethodName GetOwnerSid
if (
    $ownerSid.ReturnValue -ne 0 -or
    [string]::IsNullOrWhiteSpace($ownerSid.Sid)
) {
    throw "Could not resolve the interactive Steam owner SID."
}
$profiles = @(
    Get-CimInstance Win32_UserProfile |
        Where-Object { $_.SID -eq $ownerSid.Sid -and $_.Loaded }
)
if (
    $profiles.Count -ne 1 -or
    [string]::IsNullOrWhiteSpace($profiles[0].LocalPath)
) {
    throw "Could not resolve the interactive Steam owner profile."
}
$resolvedProfile = [System.IO.Path]::GetFullPath(
    [string]$profiles[0].LocalPath).TrimEnd("\")
if (-not [System.IO.Directory]::Exists($resolvedProfile)) {
    throw "The interactive Steam owner profile does not exist."
}
$stageLeaf = [System.IO.Path]::GetFileName($resolvedStageRoot)
if (
    -not [string]::Equals(
        [System.IO.Path]::GetDirectoryName($resolvedStageRoot),
        $resolvedProfile,
        [System.StringComparison]::OrdinalIgnoreCase) -or
    $stageLeaf -notmatch '^sd-[a-z0-9][a-z0-9-]{0,31}-stage$'
) {
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
        $lastRunUtc = $info.LastRunTime.ToUniversalTime()
        if (
            $lastRunUtc -ge $startedAt.AddSeconds(-1) -and
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
