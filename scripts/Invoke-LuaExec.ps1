[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [AllowEmptyString()]
    [string]$Code,

    [Parameter(Mandatory = $false)]
    [switch]$Interactive,

    [Parameter(ValueFromPipeline = $true)]
    [AllowEmptyString()]
    [string[]]$InputObject
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$pipeName = 'SolomonDarkModLoader_LuaExec'
$utf8 = [System.Text.UTF8Encoding]::new($false)

function Test-SolomonDarkRunning {
    $processes = Get-Process SolomonDark -ErrorAction SilentlyContinue
    return $null -ne $processes -and @($processes).Count -gt 0
}

function Get-SolomonDarkCrashDiagnostics {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $searchPaths = @(
        (Join-Path $repoRoot "runtime"),
        (Join-Path $repoRoot "runtime\stage\.sdmod\logs")
    )

    $artifacts = [System.Collections.Generic.List[string]]::new()
    foreach ($path in $searchPaths) {
        if (-not (Test-Path $path)) {
            continue
        }

        Get-ChildItem -Path $path -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object {
                $extension = $_.Extension.ToLowerInvariant()
                if ($extension -in @('.log', '.dmp', '.mdmp')) {
                    return $true
                }

                if ($extension -eq '.txt' -and $_.DirectoryName -match '[\\/]logs([\\/]|$)') {
                    return $true
                }

                return $false
            } |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 8 |
            ForEach-Object {
                $artifacts.Add($_.FullName)
            }
    }

    if ($artifacts.Count -eq 0) {
        return "Game process not detected. The game may have crashed or exited before the Lua runtime came up. No crash/log artifacts were found under runtime/ or runtime/stage/.sdmod/logs."
    }

    $artifactSummary = ($artifacts | Select-Object -Unique) -join '; '
    return "Game process not detected. The game may have crashed or exited before the Lua runtime came up. Check these artifacts: $artifactSummary"
}

function Invoke-LuaExecCode {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$LuaCode
    )

    if ([string]::IsNullOrWhiteSpace($LuaCode)) {
        return ''
    }

    $pipe = $null
    $memory = $null

    try {
        $pipe = [System.IO.Pipes.NamedPipeClientStream]::new(
            '.',
            $pipeName,
            [System.IO.Pipes.PipeDirection]::InOut,
            [System.IO.Pipes.PipeOptions]::None
        )
        $pipe.Connect(5000)
        $pipe.ReadMode = [System.IO.Pipes.PipeTransmissionMode]::Message

        $bytes = $utf8.GetBytes($LuaCode)
        $pipe.Write($bytes, 0, $bytes.Length)
        $pipe.Flush()

        $memory = [System.IO.MemoryStream]::new()
        $buffer = New-Object byte[] 4096

        while ($true) {
            $read = $pipe.Read($buffer, 0, $buffer.Length)
            if ($read -le 0) {
                break
            }

            $memory.Write($buffer, 0, $read)

            if ($pipe.IsMessageComplete) {
                break
            }
        }

        return $utf8.GetString($memory.ToArray())
    } catch [System.TimeoutException] {
        if (-not (Test-SolomonDarkRunning)) {
            throw "Cannot connect to pipe '$pipeName'. $(Get-SolomonDarkCrashDiagnostics)"
        }

        throw "Cannot connect to pipe '$pipeName'. SolomonDark.exe is running, so the mod loader or Lua runtime may not be initialized yet."
    } catch [System.IO.IOException] {
        $message = $_.Exception.Message
        if ([string]::IsNullOrWhiteSpace($message)) {
            $message = "I/O error while talking to pipe '$pipeName'."
        }

        if (-not (Test-SolomonDarkRunning)) {
            $message += " " + (Get-SolomonDarkCrashDiagnostics)
        }

        throw $message
    } finally {
        if ($memory -ne $null) {
            $memory.Dispose()
        }

        if ($pipe -ne $null) {
            $pipe.Dispose()
        }
    }
}

function Write-LuaExecResult {
    param(
        [AllowEmptyString()]
        [string]$Text,
        [switch]$AppendNewline
    )

    if ($null -eq $Text) {
        return
    }

    [Console]::Out.Write($Text)

    if ($AppendNewline -and $Text.Length -gt 0 -and -not $Text.EndsWith("`n") -and -not $Text.EndsWith("`r")) {
        [Console]::Out.WriteLine()
    }
}

function Write-LuaExecResponse {
    param(
        [AllowEmptyString()]
        [string]$Text,
        [switch]$AppendNewlineForRaw
    )

    if ($null -eq $Text) {
        return
    }

    $parsed = $null
    $trimmed = $Text.TrimStart()
    if ($trimmed.StartsWith('{')) {
        try {
            $parsed = $Text | ConvertFrom-Json -ErrorAction Stop
        } catch {
            $parsed = $null
        }
    }

    if ($null -eq $parsed -or
        -not ($parsed.PSObject.Properties.Name -contains 'ok') -or
        -not ($parsed.PSObject.Properties.Name -contains 'print_output') -or
        -not ($parsed.PSObject.Properties.Name -contains 'results') -or
        -not ($parsed.PSObject.Properties.Name -contains 'error')) {
        Write-LuaExecResult -Text $Text -AppendNewline:$AppendNewlineForRaw
        return
    }

    $stdout = [System.Text.StringBuilder]::new()
    $printOutput = $parsed.print_output
    if ($printOutput -is [string] -and $printOutput.Length -gt 0) {
        [void]$stdout.Append($printOutput)
        if (-not $printOutput.EndsWith("`n") -and -not $printOutput.EndsWith("`r")) {
            [void]$stdout.Append([Environment]::NewLine)
        }
    }

    if ($parsed.ok) {
        $results = @()
        if ($null -ne $parsed.results) {
            $results = @($parsed.results)
        }

        if ($results.Count -gt 0) {
            foreach ($result in $results) {
                [void]$stdout.Append([string]$result)
                [void]$stdout.Append([Environment]::NewLine)
            }
        } elseif ($stdout.Length -eq 0) {
            [void]$stdout.Append('ok')
            [void]$stdout.Append([Environment]::NewLine)
        }

        [Console]::Out.Write($stdout.ToString())
        return
    }

    if ($stdout.Length -gt 0) {
        [Console]::Out.Write($stdout.ToString())
    }

    $error = $parsed.error
    if (-not ($error -is [string]) -or [string]::IsNullOrWhiteSpace($error)) {
        $error = 'Lua execution failed.'
    }

    [Console]::Error.Write($error)
    if (-not $error.EndsWith("`n") -and -not $error.EndsWith("`r")) {
        [Console]::Error.WriteLine()
    }

    exit 1
}

function Invoke-LuaExecInteractive {
    while ($true) {
        $line = [Console]::In.ReadLine()
        if ($null -eq $line) {
            break
        }

        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0) {
            continue
        }

        if ($trimmed.Equals('exit', [System.StringComparison]::OrdinalIgnoreCase) -or
            $trimmed.Equals('quit', [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }

        Write-LuaExecResponse -Text (Invoke-LuaExecCode -LuaCode $line) -AppendNewlineForRaw
    }
}

function Invoke-LuaExecMain {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$Code,

        [Parameter(Mandatory = $false)]
        [switch]$Interactive,

        [AllowEmptyString()]
        [string[]]$InputObject
    )

    try {
        $pipedChunks = [System.Collections.Generic.List[string]]::new()
        if ($null -ne $InputObject) {
            foreach ($chunk in $InputObject) {
                $pipedChunks.Add($chunk)
            }
        }

        $hasCode = $PSBoundParameters.ContainsKey('Code')
        $hasPipelineInput = $pipedChunks.Count -gt 0
        $hasRedirectedInput = [Console]::IsInputRedirected

        if ($Interactive) {
            if ($hasCode -or $hasPipelineInput -or $hasRedirectedInput) {
                throw 'Interactive mode does not accept -Code or piped input.'
            }

            Invoke-LuaExecInteractive
            return
        }

        if ($hasCode) {
            Write-LuaExecResponse -Text (Invoke-LuaExecCode -LuaCode $Code)
            return
        }

        if ($hasPipelineInput) {
            Write-LuaExecResponse -Text (Invoke-LuaExecCode -LuaCode ($pipedChunks -join [Environment]::NewLine))
            return
        }

        if ($hasRedirectedInput) {
            $stdin = [Console]::In.ReadToEnd()
            if ([string]::IsNullOrWhiteSpace($stdin)) {
                return
            }

            Write-LuaExecResponse -Text (Invoke-LuaExecCode -LuaCode $stdin)
            return
        }

        throw 'No Lua code provided. Use -Code, -Interactive, or pipe input.'
    } catch {
        $message = $_.Exception.Message
        if ([string]::IsNullOrWhiteSpace($message)) {
            $message = 'Lua exec failed.'
        }

        if (-not $message.StartsWith('ERROR:', [System.StringComparison]::OrdinalIgnoreCase)) {
            $message = "ERROR: $message"
        }

        [Console]::Error.WriteLine($message)
        exit 1
    }
}

$invokeParams = @{}
if ($PSBoundParameters.ContainsKey('Code')) {
    $invokeParams.Code = $Code
}
if ($Interactive) {
    $invokeParams.Interactive = $true
}
if ($PSBoundParameters.ContainsKey('InputObject')) {
    $invokeParams.InputObject = $InputObject
}

Invoke-LuaExecMain @invokeParams
