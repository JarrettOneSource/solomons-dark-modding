[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RequestPath,

    [Parameter(Mandatory = $true)]
    [string]$ResultPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function ConvertTo-Array {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) {
        return @()
    }
    return @($Value)
}

function Get-ExactProcess {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [switch]$AllowAbsent
    )

    $matches = @(
        Get-CimInstance Win32_Process |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
                [string]::Equals(
                    [string]$_.ExecutablePath,
                    $ExecutablePath,
                    [System.StringComparison]::OrdinalIgnoreCase)
            }
    )
    if ($matches.Count -eq 0 -and $AllowAbsent) {
        return $null
    }
    if ($matches.Count -ne 1) {
        throw "Expected exactly one process at '$ExecutablePath'; found $($matches.Count)."
    }
    return $matches[0]
}

function Get-UiElements {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    Add-Type -AssemblyName UIAutomationClient
    $process = Get-Process -Id $ProcessId
    $process.Refresh()
    if ($process.MainWindowHandle -eq 0) {
        throw "Launcher process $ProcessId has no main window."
    }
    $root = [System.Windows.Automation.AutomationElement]::FromHandle(
        $process.MainWindowHandle)
    $elements = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    $rows = @()
    for ($index = 0; $index -lt $elements.Count; $index++) {
        $element = $elements.Item($index)
        $value = ""
        $pattern = $null
        if ($element.TryGetCurrentPattern(
                [System.Windows.Automation.ValuePattern]::Pattern,
                [ref]$pattern)) {
            $value = [string]$pattern.Current.Value
        }
        $rows += [pscustomobject]@{
            Name = [string]$element.Current.Name
            ControlType = [string]$element.Current.ControlType.ProgrammaticName
            Enabled = [bool]$element.Current.IsEnabled
            Offscreen = [bool]$element.Current.IsOffscreen
            Value = $value
        }
    }
    return $rows
}

function Wait-Ui {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastSummary = [ordered]@{
        visibleElementCount = 0
        safeBoundaries = @()
    }
    do {
        try {
            $rows = @(Get-UiElements -ProcessId $ProcessId)
            $visibleNames = @(
                $rows |
                    Where-Object { -not $_.Offscreen -and $_.Name } |
                    ForEach-Object Name
            )
            $lastSummary = [ordered]@{
                visibleElementCount = $visibleNames.Count
                safeBoundaries = @(
                    $visibleNames |
                        Where-Object {
                            $_ -in @(
                                "Ready",
                                "Join Game",
                                "Launch Game",
                                "Host Game",
                                "Start Lobby"
                            ) -or $_ -match "^Players [0-9]+/[0-9]+$"
                        } |
                        Sort-Object -Unique
                )
            }
            $match = @(
                $rows |
                    Where-Object {
                        $_.Name -eq $Name -and
                        $_.Enabled -and
                        -not $_.Offscreen
                    }
            )
            if ($match.Count -ge 1) {
                return $rows
            }
        } catch {
            $lastSummary = [ordered]@{
                visibleElementCount = 0
                safeBoundaries = @()
            }
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    throw (
        "Timed out waiting for launcher UI '$Name'; " +
        "visibleElementCount=$($lastSummary.visibleElementCount); " +
        "safeBoundaries=$($lastSummary.safeBoundaries -join ',')."
    )
}

function Invoke-UiButton {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Name
    )

    Add-Type -AssemblyName UIAutomationClient
    $process = Get-Process -Id $ProcessId
    $root = [System.Windows.Automation.AutomationElement]::FromHandle(
        $process.MainWindowHandle)
    $condition = New-Object System.Windows.Automation.AndCondition(
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Button)),
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            $Name)))
    $matches = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        $condition)
    $usable = @()
    for ($index = 0; $index -lt $matches.Count; $index++) {
        $candidate = $matches.Item($index)
        if ($candidate.Current.IsEnabled -and -not $candidate.Current.IsOffscreen) {
            $usable += $candidate
        }
    }
    if ($usable.Count -ne 1) {
        throw "Expected one visible enabled launcher button '$Name'; found $($usable.Count)."
    }
    $pattern = $usable[0].GetCurrentPattern(
        [System.Windows.Automation.InvokePattern]::Pattern)
    ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
}

function Set-LauncherInstance {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Instance
    )

    Add-Type -AssemblyName UIAutomationClient
    $process = Get-Process -Id $ProcessId
    $root = [System.Windows.Automation.AutomationElement]::FromHandle(
        $process.MainWindowHandle)
    $advanced = $root.FindFirst(
        [System.Windows.Automation.TreeScope]::Descendants,
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            "Advanced")))
    if ($null -eq $advanced) {
        throw "Launcher Advanced expander was not found."
    }
    $expand = $advanced.GetCurrentPattern(
        [System.Windows.Automation.ExpandCollapsePattern]::Pattern)
    ([System.Windows.Automation.ExpandCollapsePattern]$expand).Expand()
    Start-Sleep -Milliseconds 150
    $condition = New-Object System.Windows.Automation.AndCondition(
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Edit)),
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            "Instance")))
    $edit = $root.FindFirst(
        [System.Windows.Automation.TreeScope]::Descendants,
        $condition)
    if ($null -eq $edit) {
        throw "Launcher Instance edit was not found."
    }
    $value = $edit.GetCurrentPattern(
        [System.Windows.Automation.ValuePattern]::Pattern)
    ([System.Windows.Automation.ValuePattern]$value).SetValue($Instance)
    Invoke-UiButton -ProcessId $ProcessId -Name "Apply"
    ([System.Windows.Automation.ExpandCollapsePattern]$expand).Collapse()
}

function Set-LauncherLobbyId {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][uint64]$LobbyId
    )

    Add-Type -AssemblyName UIAutomationClient
    $process = Get-Process -Id $ProcessId
    $root = [System.Windows.Automation.AutomationElement]::FromHandle(
        $process.MainWindowHandle)
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit)
    $matches = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        $condition)
    $usable = @()
    for ($index = 0; $index -lt $matches.Count; $index++) {
        $candidate = $matches.Item($index)
        if ($candidate.Current.IsEnabled -and -not $candidate.Current.IsOffscreen) {
            $pattern = $null
            if ($candidate.TryGetCurrentPattern(
                    [System.Windows.Automation.ValuePattern]::Pattern,
                    [ref]$pattern)) {
                $usable += [pscustomobject]@{
                    Element = $candidate
                    Pattern = $pattern
                    Name = [string]$candidate.Current.Name
                }
            }
        }
    }
    $named = @(
        $usable |
            Where-Object {
                $_.Name -eq "Lobby ID" -or $_.Name -like "*Lobby ID*"
            }
    )
    $target = if ($named.Count -eq 1) {
        $named[0]
    } elseif ($usable.Count -eq 1) {
        $usable[0]
    } else {
        $null
    }
    if ($null -eq $target) {
        throw "Could not uniquely resolve the visible Lobby ID edit."
    }
    ([System.Windows.Automation.ValuePattern]$target.Pattern).SetValue(
        [string]$LobbyId)
}

function Start-Client {
    param([Parameter(Mandatory = $true)][object]$Request)

    $existing = Get-ExactProcess `
        -ExecutablePath ([string]$Request.LauncherExecutable) `
        -AllowAbsent
    if ($null -eq $existing) {
        $start = [System.Diagnostics.ProcessStartInfo]::new()
        $start.FileName = [string]$Request.LauncherExecutable
        $start.WorkingDirectory = [string]$Request.LauncherRoot
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $false
        $start.Arguments = "--test-activation-scope=$($Request.LauncherScope)"
        foreach ($property in $Request.Environment.PSObject.Properties) {
            $start.EnvironmentVariables[[string]$property.Name] = [string]$property.Value
        }
        $launcher = [System.Diagnostics.Process]::Start($start)
        if ($null -eq $launcher) {
            throw "Desktop launcher did not start."
        }
        Wait-Ui `
            -ProcessId $launcher.Id `
            -Name "Host Game" `
            -TimeoutSeconds ([int]$Request.TimeoutSeconds) | Out-Null
        Set-LauncherInstance `
            -ProcessId $launcher.Id `
            -Instance ([string]$Request.Instance)
        Wait-Ui `
            -ProcessId $launcher.Id `
            -Name "Host Game" `
            -TimeoutSeconds ([int]$Request.TimeoutSeconds) | Out-Null
        Set-LauncherLobbyId `
            -ProcessId $launcher.Id `
            -LobbyId ([uint64]$Request.LobbyId)
        Wait-Ui `
            -ProcessId $launcher.Id `
            -Name "Join Game" `
            -TimeoutSeconds ([int]$Request.TimeoutSeconds) | Out-Null
        Invoke-UiButton -ProcessId $launcher.Id -Name "Join Game"
    } else {
        $launcher = Get-Process -Id $existing.ProcessId
    }
    $rows = Wait-Ui `
        -ProcessId $launcher.Id `
        -Name "Launch Game" `
        -TimeoutSeconds ([int]$Request.TimeoutSeconds)
    $visibleAtLaunch = @(
        $rows |
            Where-Object { -not $_.Offscreen -and $_.Name } |
            ForEach-Object Name
    )
    Invoke-UiButton -ProcessId $launcher.Id -Name "Launch Game"

    $deadline = [DateTime]::UtcNow.AddSeconds([int]$Request.TimeoutSeconds)
    $game = $null
    do {
        $game = Get-ExactProcess `
            -ExecutablePath ([string]$Request.GameExecutable) `
            -AllowAbsent
        if ($null -ne $game) {
            break
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($null -eq $game) {
        throw "Staged client game did not start."
    }
    return [ordered]@{
        uiPid = [int]$launcher.Id
        gamePid = [int]$game.ProcessId
        gameExecutable = [string]$game.ExecutablePath
        lobbyId = [string]$Request.LobbyId
        explicitLaunchGame = $true
        sessionId = [int]$game.SessionId
        boundariesAtLaunch = [ordered]@{
            ready = [bool]($visibleAtLaunch -contains "Ready")
            launchGame = [bool]($visibleAtLaunch -contains "Launch Game")
            playerCount = [string](
                $visibleAtLaunch |
                    Where-Object { $_ -match "^Players [0-9]+/[0-9]+$" } |
                    Select-Object -First 1
            )
        }
    }
}

function Invoke-RealInput {
    param([Parameter(Mandatory = $true)][object]$Request)

    if ($Request.Action -eq "click-sequence") {
        $targets = @(ConvertTo-Array -Value $Request.Targets)
        if ($targets.Count -lt 2 -or $targets.Count -gt 8) {
            throw "Click sequence must contain 2 through 8 targets."
        }
        $intervalMilliseconds = [int]$Request.IntervalMilliseconds
        if (
            $intervalMilliseconds -lt 100 -or
            $intervalMilliseconds -gt 1500
        ) {
            throw "Click sequence interval must be 100 through 1500 milliseconds."
        }
        $helperOutputs = @()
        for ($index = 0; $index -lt $targets.Count; $index++) {
            $target = $targets[$index]
            $arguments = @(
                "click",
                [string]$Request.ProcessId,
                [string]$Request.GameExecutable,
                [string]$target.X,
                [string]$target.Y,
                [string]$Request.HoldMilliseconds
            )
            $output = & ([string]$Request.InputHelper) @arguments 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Real-input helper failed with exit code $LASTEXITCODE`: $output"
            }
            $helperOutputs += [string]($output | Out-String).Trim()
            if ($index + 1 -lt $targets.Count) {
                Start-Sleep -Milliseconds $intervalMilliseconds
            }
        }
        return [ordered]@{
            action = [string]$Request.Action
            processId = [int]$Request.ProcessId
            clickCount = $targets.Count
            helper = $helperOutputs
        }
    }

    $arguments = @(
        [string]$Request.Action,
        [string]$Request.ProcessId,
        [string]$Request.GameExecutable
    )
    if ($Request.Action -eq "key") {
        $arguments += @(
            [string]$Request.Key,
            [string]$Request.HoldMilliseconds
        )
    } else {
        $arguments += @(
            [string]$Request.X,
            [string]$Request.Y,
            [string]$Request.HoldMilliseconds
        )
    }
    $output = & ([string]$Request.InputHelper) @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Real-input helper failed with exit code $LASTEXITCODE`: $output"
    }
    return [ordered]@{
        action = [string]$Request.Action
        processId = [int]$Request.ProcessId
        helper = [string]($output | Out-String).Trim()
    }
}

function Test-SteamAttach {
    param([Parameter(Mandatory = $true)][object]$Request)

    $launcher = [System.IO.Path]::GetFullPath(
        [string]$Request.LauncherExecutable)
    $stagePrefix = [System.IO.Path]::GetFullPath(
        [Environment]::CurrentDirectory).TrimEnd("\") + "\"
    if (-not $launcher.StartsWith(
            $stagePrefix,
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The Steam attach probe launcher escapes the owned stage."
    }
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        throw "The staged launcher CLI is missing: $launcher"
    }

    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $launcher
    $start.WorkingDirectory = [System.IO.Path]::GetDirectoryName($launcher)
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.CreateNoWindow = $true
    $start.Arguments = "__join-steam-lobby " +
        [System.Diagnostics.Process]::GetCurrentProcess().Id.ToString() +
        " " + ([uint64]$Request.LobbyId).ToString()

    $process = [System.Diagnostics.Process]::Start($start)
    if ($null -eq $process) {
        throw "The staged Steam attach probe did not start."
    }
    try {
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit([int]$Request.TimeoutSeconds * 1000)) {
            $process.StandardInput.WriteLine("leave")
            $process.StandardInput.Flush()
            if (-not $process.WaitForExit(3000)) {
                $current = Get-ExactProcess `
                    -ExecutablePath $launcher `
                    -AllowAbsent
                if ($null -ne $current -and
                    $current.ProcessId -eq $process.Id) {
                    $process.Kill()
                    $process.WaitForExit(3000)
                }
            }
        }

        $outputLines = @(
            $stdout.GetAwaiter().GetResult() -split "`r?`n" |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        $errorLines = @(
            $stderr.GetAwaiter().GetResult() -split "`r?`n" |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        return [ordered]@{
            processId = [int]$process.Id
            exitCode = [int]$process.ExitCode
            stdout = $outputLines
            stderr = $errorLines
        }
    } finally {
        $process.Dispose()
    }
}

function Close-RunProcesses {
    param([Parameter(Mandatory = $true)][object]$Request)

    $prefix = ([string]$Request.RunRoot).TrimEnd("\") + "\"
    $owned = @(
        Get-CimInstance Win32_Process |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
                $_.ExecutablePath.StartsWith(
                    $prefix,
                    [System.StringComparison]::OrdinalIgnoreCase)
            }
    )
    $requests = @()
    foreach ($record in $owned | Sort-Object ProcessId -Descending) {
        $process = Get-Process -Id $record.ProcessId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            continue
        }
        $requested = $false
        if ($process.MainWindowHandle -ne 0) {
            $requested = $process.CloseMainWindow()
        }
        $requests += [ordered]@{
            processId = [int]$record.ProcessId
            executablePath = [string]$record.ExecutablePath
            closeRequested = [bool]$requested
        }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $remaining = @(
            Get-CimInstance Win32_Process |
                Where-Object {
                    -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
                    $_.ExecutablePath.StartsWith(
                        $prefix,
                        [System.StringComparison]::OrdinalIgnoreCase)
                }
        )
        if ($remaining.Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    $forced = @()
    foreach ($record in $remaining | Sort-Object ProcessId -Descending) {
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.ProcessId)"
        if (
            $null -eq $current -or
            -not [string]::Equals(
                [string]$current.ExecutablePath,
                [string]$record.ExecutablePath,
                [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            throw "Refusing to stop PID $($record.ProcessId); its executable changed."
        }
        Stop-Process -Id $record.ProcessId -Force
        $forced += [ordered]@{
            processId = [int]$record.ProcessId
            executablePath = [string]$record.ExecutablePath
        }
    }
    return [ordered]@{
        gracefulRequests = $requests
        forced = $forced
    }
}

$started = [DateTime]::UtcNow
$result = [ordered]@{
    schemaVersion = 1
    ok = $false
    startedUtc = $started.ToString("o")
    sessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
}
try {
    $request = Get-Content -LiteralPath $RequestPath -Raw |
        ConvertFrom-Json -ErrorAction Stop
    $result.action = [string]$request.Action
    $result.detail = switch ([string]$request.Action) {
        "launch-client" { Start-Client -Request $request }
        "probe-steam" { Test-SteamAttach -Request $request }
        "key" { Invoke-RealInput -Request $request }
        "click" { Invoke-RealInput -Request $request }
        "click-sequence" { Invoke-RealInput -Request $request }
        "close" { Close-RunProcesses -Request $request }
        default { throw "Unsupported session-worker action '$($request.Action)'." }
    }
    $result.ok = $true
} catch {
    $result.error = [ordered]@{
        type = $_.Exception.GetType().FullName
        message = $_.Exception.Message
        scriptStackTrace = $_.ScriptStackTrace
    }
} finally {
    $result.completedUtc = [DateTime]::UtcNow.ToString("o")
    $resultDirectory = Split-Path -Parent $ResultPath
    New-Item -ItemType Directory -Path $resultDirectory -Force | Out-Null
    $temporary = "$ResultPath.tmp"
    $result | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $ResultPath -Force
}

if (-not $result.ok) {
    exit 1
}
