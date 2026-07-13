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
            $stdout = Get-Content -Path $stdoutPath -Raw -ErrorAction SilentlyContinue
            $stderr = Get-Content -Path $stderrPath -Raw -ErrorAction SilentlyContinue
            if (-not [string]::IsNullOrWhiteSpace($stdout)) {
                $result = ConvertFrom-MultiplayerLauncherJson -Text $stdout
                if ($null -ne $result) {
                    break
                }
            }
            if ($process.HasExited -and $process.ExitCode -ne 0) {
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
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previous[$key], "Process")
        }
        Remove-Item $stdoutPath, $stderrPath -ErrorAction SilentlyContinue
    }
}
