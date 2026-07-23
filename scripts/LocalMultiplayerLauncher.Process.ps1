function ConvertTo-MultiplayerProcessArgument {
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

function ConvertFrom-MultiplayerLauncherJson {
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

function Set-ExactMultiplayerModState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootPath,
        [Parameter(Mandatory = $true)]
        [string]$Instance,
        [Parameter(Mandatory = $true)]
        [string[]]$ModIds
    )

    if ($Instance.Length -gt 64 -or
        $Instance -notmatch '^[A-Za-z0-9._-]+$' -or
        $Instance -notmatch '[A-Za-z0-9]') {
        throw "Invalid exact-mod instance name: $Instance"
    }
    if ($ModIds.Count -eq 0) {
        throw "At least one exact mod id is required."
    }
    $seenModIds = @{}
    foreach ($ModId in $ModIds) {
        if ($ModId -notmatch '^[a-z0-9][a-z0-9._-]*$') {
            throw "Invalid exact mod id: $ModId"
        }
        if ($seenModIds.ContainsKey($ModId)) {
            throw "Duplicate exact mod id: $ModId"
        }
        $seenModIds[$ModId] = $true
    }

    $instancesRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $RootPath "runtime\instances"))
    $normalizedInstance = $Instance.ToLowerInvariant()
    $instanceRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $instancesRoot $normalizedInstance))
    $requiredPrefix = $instancesRoot.TrimEnd('\') + '\'
    if (-not $instanceRoot.StartsWith(
        $requiredPrefix,
        [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Exact-mod instance escaped the runtime root: $Instance"
    }

    [System.IO.Directory]::CreateDirectory($instanceRoot) | Out-Null
    $mods = [ordered]@{}
    foreach ($ModId in $ModIds) {
        $mods[$ModId] = [ordered]@{ Enabled = $true }
    }
    $document = [ordered]@{ Mods = $mods }
    [System.IO.File]::WriteAllText(
        (Join-Path $instanceRoot "mod-manager-state.json"),
        ($document | ConvertTo-Json -Depth 4)
    )
}

function Read-MultiplayerProcessOutput {
    param([string]$Path)

    $stream = $null
    $reader = $null
    try {
        $stream = [System.IO.FileStream]::new(
            $Path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite)
        $reader = [System.IO.StreamReader]::new($stream)
        return $reader.ReadToEnd()
    } finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        } elseif ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Invoke-LauncherWithEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LauncherPath,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [hashtable]$Environment,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 60
    )

    $previous = @{}
    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    $process = $null
    foreach ($key in $Environment.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }

    try {
        $process = Start-Process `
            -FilePath $LauncherPath `
            -ArgumentList (($Arguments | ForEach-Object { ConvertTo-MultiplayerProcessArgument $_ }) -join " ") `
            -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath `
            -PassThru

        $result = $null
        $stdout = ""
        $stderr = ""
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            $process.Refresh()
            $stdout = Read-MultiplayerProcessOutput -Path $stdoutPath
            $stderr = Read-MultiplayerProcessOutput -Path $stderrPath
            if (-not [string]::IsNullOrWhiteSpace($stdout)) {
                $result = ConvertFrom-MultiplayerLauncherJson -Text $stdout
                if ($null -ne $result) {
                    break
                }
            }
            if ($process.HasExited) {
                # WaitForExit also drains the redirected streams. Without it,
                # a fast launcher exit can leave only the first buffered chunk
                # visible here, producing a valid-but-truncated JSON document.
                $process.WaitForExit()
                $stdout = Read-MultiplayerProcessOutput -Path $stdoutPath
                $stderr = Read-MultiplayerProcessOutput -Path $stderrPath
                if (-not [string]::IsNullOrWhiteSpace($stdout)) {
                    $result = ConvertFrom-MultiplayerLauncherJson -Text $stdout
                }
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
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previous[$key], "Process")
        }
        Remove-Item $stdoutPath, $stderrPath -ErrorAction SilentlyContinue
    }
}
