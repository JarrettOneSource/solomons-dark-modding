[CmdletBinding(DefaultParameterSetName = "Action")]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$')]
    [string]$Instance,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [int]::MaxValue)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9_]+$')]
    [string]$EdgeId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9_]+$')]
    [string]$SourceScreen,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9_]+$')]
    [string]$DestinationScreen,

    [Parameter(Mandatory = $true)]
    [string]$Trigger,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true, ParameterSetName = "Action")]
    [string]$ActionId,

    [Parameter(Mandatory = $true, ParameterSetName = "Action")]
    [string]$SurfaceId,

    [Parameter(Mandatory = $true, ParameterSetName = "Key")]
    [string]$Key,

    [Parameter(Mandatory = $true, ParameterSetName = "Lua")]
    [string]$LuaActionCode,

    [Parameter(Mandatory = $true, ParameterSetName = "Click")]
    [float]$ClientX,

    [Parameter(Mandatory = $true, ParameterSetName = "Click")]
    [float]$ClientY,

    [Parameter(Mandatory = $true, ParameterSetName = "Observe")]
    [switch]$ObserveOnly,

    [string]$ExpectedSourceSurface = "",
    [string]$ExpectedDestinationSurface = "",

    [ValidateRange(50, 10000)]
    [int]$WaitMilliseconds = 900,

    [string]$CaptureCommit = ""
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$instanceRoot = Join-Path $root (
    "runtime\instances\" + $Instance.ToLowerInvariant()
)
$expectedExecutable = [IO.Path]::GetFullPath(
    (Join-Path $instanceRoot "stage\SolomonDark.exe")
)
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
if (
    $null -eq $process -or
    $null -eq $process.ExecutablePath -or
    -not [string]::Equals(
        [IO.Path]::GetFullPath($process.ExecutablePath),
        $expectedExecutable,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "PID $ProcessId does not own the exact $Instance staged executable."
}

if ([string]::IsNullOrWhiteSpace($CaptureCommit)) {
    $CaptureCommit = (& git -C $root rev-parse HEAD).Trim()
}
if ($CaptureCommit -notmatch '^[0-9a-f]{40}$') {
    throw "CaptureCommit must be a full lowercase Git SHA."
}

$pipeName = "SolomonDarkModLoader_LuaExec_$Instance"
$luaExecClient = Join-Path $root "tools\lua-exec.py"
function Invoke-TargetLua {
    param([Parameter(Mandatory = $true)][string]$LuaCode)

    $previousPipe = $env:SDMOD_LUA_EXEC_PIPE_NAME
    try {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $pipeName
        $result = $LuaCode | & py.exe -3 $luaExecClient
        if ($LASTEXITCODE -ne 0) {
            throw "Lua exec failed with exit code $LASTEXITCODE."
        }
        return ($result -join "`n").Trim()
    } finally {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $previousPipe
    }
}

function Get-LiveObservation {
    param(
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [Parameter(Mandatory = $true)][string]$FramePath
    )

    $result = Invoke-TargetLua -LuaCode @"
local semantic = sd.ui.get_snapshot()
local tagged = sd.ui.capture_current_layout([[$ScreenId]])
if type(tagged) ~= 'table' then error('current layout unavailable') end
local ok, message = sd.debug.capture_backbuffer([[$FramePath]])
if not ok then error(tostring(message)) end
return table.concat({
  tostring(semantic and semantic.surface_id or ''),
  tostring(semantic and semantic.generation or 0),
  tostring(tagged.screen_id or ''),
  tostring(tagged.generation or 0),
  tostring(#(tagged.elements or {})),
  tostring(tagged.capture_method or '')
}, '|')
"@
    $parts = @($result.Split('|', 6))
    if ($parts.Count -ne 6) {
        throw "Malformed live observation: $result"
    }
    if (-not (Test-Path -LiteralPath $FramePath -PathType Leaf)) {
        throw "Live observation did not create its frame capture."
    }
    return [ordered]@{
        semantic_surface = $parts[0]
        semantic_generation = [uint64]$parts[1]
        tagged_screen = $parts[2]
        layout_generation = [uint64]$parts[3]
        element_count = [int]$parts[4]
        capture_method = $parts[5]
        frame_sha256 = (
            Get-FileHash -LiteralPath $FramePath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
}

$tempDirectory = Join-Path ([IO.Path]::GetTempPath()) (
    "sdmod-menu-transition-" + [Guid]::NewGuid().ToString("N")
)
[IO.Directory]::CreateDirectory($tempDirectory) | Out-Null
$beforeFrame = Join-Path $tempDirectory "before.bmp"
$afterFrame = Join-Path $tempDirectory "after.bmp"
try {
    $before = Get-LiveObservation `
        -ScreenId $SourceScreen `
        -FramePath $beforeFrame
    if (
        -not [string]::IsNullOrWhiteSpace($ExpectedSourceSurface) -and
        $before.semantic_surface -ne $ExpectedSourceSurface
    ) {
        throw (
            "Source semantic surface '$($before.semantic_surface)' did not " +
            "match '$ExpectedSourceSurface'."
        )
    }

    $dispatchResult = "observed"
    if ($PSCmdlet.ParameterSetName -eq "Action") {
        $actionLiteral = "[[${ActionId}]]"
        $surfaceLiteral = "[[${SurfaceId}]]"
        $dispatchResult = Invoke-TargetLua -LuaCode @"
local ok, request = sd.ui.activate_action($actionLiteral, $surfaceLiteral)
if not ok then error(tostring(request)) end
return tostring(request)
"@
    } elseif ($PSCmdlet.ParameterSetName -eq "Key") {
        $keyLiteral = "[[${Key}]]"
        $dispatchResult = Invoke-TargetLua -LuaCode @"
local ok, message = sd.input.press_key($keyLiteral)
if not ok then error(tostring(message)) end
return 'key'
"@
    } elseif ($PSCmdlet.ParameterSetName -eq "Lua") {
        $dispatchResult = Invoke-TargetLua -LuaCode $LuaActionCode
    } elseif ($PSCmdlet.ParameterSetName -eq "Click") {
        & (Join-Path $PSScriptRoot "Invoke-ExactProcessClientClick.ps1") `
            -Instance $Instance `
            -ProcessId $ProcessId `
            -ClientX $ClientX `
            -ClientY $ClientY |
            Out-Null
        $dispatchResult = "exact_owned_client_click=$ClientX,$ClientY"
    }

    Start-Sleep -Milliseconds $WaitMilliseconds
    $after = Get-LiveObservation `
        -ScreenId $DestinationScreen `
        -FramePath $afterFrame
    if (
        -not [string]::IsNullOrWhiteSpace($ExpectedDestinationSurface) -and
        $after.semantic_surface -ne $ExpectedDestinationSurface
    ) {
        throw (
            "Destination semantic surface '$($after.semantic_surface)' did " +
            "not match '$ExpectedDestinationSurface'."
        )
    }

    $outputItemPath = [IO.Path]::GetFullPath($OutputPath)
    [IO.Directory]::CreateDirectory(
        (Split-Path -Parent $outputItemPath)
    ) | Out-Null
    $nativeSha256 = (
        Get-FileHash -LiteralPath $expectedExecutable -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $loaderPath = Join-Path $root "dist\launcher\SolomonDarkModLoader.dll"
    $loaderSha256 = (
        Get-FileHash -LiteralPath $loaderPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    if (Test-Path -LiteralPath $outputItemPath -PathType Leaf) {
        $fixture = Get-Content -LiteralPath $outputItemPath -Raw |
            ConvertFrom-Json
        if ($fixture.schema -ne "solomon-dark-native-menu-navigation-v1") {
            throw "Existing navigation fixture has an incompatible schema."
        }
    } else {
        $fixture = [ordered]@{
            schema = "solomon-dark-native-menu-navigation-v1"
            header = [ordered]@{
                capture_method = (
                    "live semantic action/key dispatch + tagged native UI " +
                    "tree generations + before/after D3D9 frame hashes"
                )
                sessions = @()
            }
            edges = @()
        }
    }

    $fixture.header.sessions = @($fixture.header.sessions) + @(
        [ordered]@{
            instance = $Instance
            process_id = $ProcessId
            capture_commit = $CaptureCommit
            native_exe_sha256 = $nativeSha256
            loader_dll_sha256 = $loaderSha256
            captured_at_utc = [DateTime]::UtcNow.ToString("o")
        }
    )
    $fixture.edges = @($fixture.edges) + @(
        [ordered]@{
            id = $EdgeId
            source = $SourceScreen
            trigger = $Trigger
            action_id = $(if ($PSCmdlet.ParameterSetName -eq "Action") {
                $ActionId
            } else { "" })
            destination = $DestinationScreen
            dispatch_result = $dispatchResult
            before = $before
            after = $after
            observed_at_utc = [DateTime]::UtcNow.ToString("o")
        }
    )
    [IO.File]::WriteAllText(
        $outputItemPath,
        ($fixture | ConvertTo-Json -Depth 100) + "`n",
        [Text.UTF8Encoding]::new($false)
    )

    [pscustomobject]@{
        success = $true
        edge = $EdgeId
        source = $before.semantic_surface
        destination = $after.semantic_surface
        output = $outputItemPath
    } | ConvertTo-Json -Compress
} finally {
    if (Test-Path -LiteralPath $tempDirectory) {
        Remove-Item -LiteralPath $tempDirectory -Recurse -Force
    }
}
