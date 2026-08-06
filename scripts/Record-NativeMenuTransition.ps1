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
    [string]$ExpectedDestinationSurface = ""
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
. (Join-Path $PSScriptRoot "NativeMenuCaptureSupport.ps1")
$context = New-NativeMenuCaptureContext `
    -Root $root `
    -Instance $Instance `
    -ProcessId $ProcessId

$outputItemPath = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $outputItemPath -PathType Leaf) {
    $fixture = Get-Content -LiteralPath $outputItemPath -Raw |
        ConvertFrom-Json
    if ($fixture.schema -ne "solomon-dark-native-menu-navigation-v2") {
        throw "Existing navigation recording has an incompatible schema."
    }
    $allIds = @($fixture.edges | ForEach-Object { [string]$_.id })
    $duplicateIds = @(
        $allIds | Group-Object | Where-Object Count -gt 1 |
            ForEach-Object Name
    )
    if ($duplicateIds.Count -gt 0) {
        throw (
            "Existing navigation recording contains ambiguous duplicate " +
            "edge IDs: $($duplicateIds -join ', ')."
        )
    }
    if ($allIds -contains $EdgeId) {
        throw "Navigation edge '$EdgeId' is already recorded; refusing ambiguity."
    }
} else {
    $fixture = [ordered]@{
        schema = "solomon-dark-native-menu-navigation-v2"
        header = [ordered]@{
            capture_method = (
            "Settlement v2.4 raw-window structural native UI semantics + measured " +
                "animated geometry + exact-process action/key/click dispatch " +
                "+ same-call D3D9 frame hashes + canonical draw-order/id " +
                "cross-capture comparison"
            )
            settlement_criterion = (
                "at least 40 consecutive samples spanning at least 2 seconds " +
                "with byte-identical structural payloads; screen-member motion " +
                "capability is resolved across fresh-instance pairs after capture; " +
                "raw element-list position is non-contractual"
            )
            recorded_live = $true
            sessions = @()
        }
        edges = @()
    }
}

$tempDirectory = Join-Path ([IO.Path]::GetTempPath()) (
    "sdmod-menu-transition-" + [Guid]::NewGuid().ToString("N")
)
[IO.Directory]::CreateDirectory($tempDirectory) | Out-Null
$beforeFrame = Join-Path $tempDirectory "before.bmp"
$afterFrame = Join-Path $tempDirectory "after.bmp"
$populationSamplerArmed = $false
try {
    $sourceClock = [Diagnostics.Stopwatch]::StartNew()
    $before = Get-SettledNativeMenuObservation `
        -Context $context `
        -ScreenId $SourceScreen `
        -FramePath $beforeFrame `
        -LatencyClock $sourceClock
    if (
        -not [string]::IsNullOrWhiteSpace($ExpectedSourceSurface) -and
        $before.semantic_surface -ne $ExpectedSourceSurface
    ) {
        throw (
            "STOP: source semantic surface '$($before.semantic_surface)' did " +
            "not match '$ExpectedSourceSurface'."
        )
    }

    Initialize-NativeMenuPopulationSampler -Context $context
    Start-NativeMenuPopulationSampler `
        -Context $context `
        -ScreenId $DestinationScreen `
        -ExpectedSurface $ExpectedDestinationSurface
    $populationSamplerArmed = $true

    $destinationClock = [Diagnostics.Stopwatch]::StartNew()
    $dispatchResult = "observed"
    if ($PSCmdlet.ParameterSetName -eq "Action") {
        $dispatchResult = (Invoke-NativeMenuLua `
            -Context $context `
            -LuaCode @"
local ok, request = sd.ui.activate_action([=[$ActionId]=], [=[$SurfaceId]=])
if not ok then error(tostring(request)) end
return tostring(request)
"@).Text
    } elseif ($PSCmdlet.ParameterSetName -eq "Key") {
        $dispatchResult = (Invoke-NativeMenuLua `
            -Context $context `
            -LuaCode @"
local ok, message = sd.input.press_key([=[$Key]=])
if not ok then error(tostring(message)) end
return 'key'
"@).Text
    } elseif ($PSCmdlet.ParameterSetName -eq "Lua") {
        $dispatchResult = (Invoke-NativeMenuLua `
            -Context $context `
            -LuaCode $LuaActionCode).Text
    } elseif ($PSCmdlet.ParameterSetName -eq "Click") {
        & (Join-Path $PSScriptRoot "Invoke-ExactProcessClientClick.ps1") `
            -Instance $Instance `
            -ProcessId $ProcessId `
            -ClientX $ClientX `
            -ClientY $ClientY |
            Out-Null
        $dispatchResult = "exact_owned_client_click=$ClientX,$ClientY"
    }

    $after = Get-SettledNativeMenuObservation `
        -Context $context `
        -ScreenId $DestinationScreen `
        -FramePath $afterFrame `
        -LatencyClock $destinationClock
    $populationTrace = Stop-NativeMenuPopulationSampler -Context $context
    $populationSamplerArmed = $false
    $after.settlement_trace["high_cadence_sample_count"] = (
        [int]$populationTrace.sample_count
    )
    $after.settlement_trace["high_cadence_structural_phases"] = @(
        $populationTrace.structural_phases
    )
    if (
        -not [string]::IsNullOrWhiteSpace($ExpectedDestinationSurface) -and
        $after.semantic_surface -ne $ExpectedDestinationSurface
    ) {
        throw (
            "STOP: destination semantic surface '$($after.semantic_surface)' " +
            "did not match '$ExpectedDestinationSurface'."
        )
    }

    [IO.Directory]::CreateDirectory(
        (Split-Path -Parent $outputItemPath)
    ) | Out-Null
    $frameDirectory = [IO.Path]::ChangeExtension(
        $outputItemPath,
        $null
    ) + ".frames"
    [IO.Directory]::CreateDirectory($frameDirectory) | Out-Null
    $beforeEvidencePath = Join-Path $frameDirectory "$EdgeId.before.bmp"
    $afterEvidencePath = Join-Path $frameDirectory "$EdgeId.after.bmp"
    Copy-Item -LiteralPath $beforeFrame -Destination $beforeEvidencePath
    Copy-Item -LiteralPath $afterFrame -Destination $afterEvidencePath

    $capturedAtUtc = [DateTime]::UtcNow.ToString("o")
    $fixture.header.sessions = @($fixture.header.sessions) + @(
        [ordered]@{
            instance = $Instance
            process_id = $ProcessId
            source = $context.Source
            recorded_live = $true
            captured_at_utc = $capturedAtUtc
        }
    )
    $fixture.edges = @($fixture.edges) + @(
        [ordered]@{
            header = [ordered]@{
                label = $EdgeId
                instance = $Instance
                process_id = $ProcessId
                source = $context.Source
                capture_method = [string]$fixture.header.capture_method
                recorded_live = $true
                captured_at_utc = $capturedAtUtc
                settlement = [ordered]@{
                    source = $before.settlement
                    destination = $after.settlement
                }
                raw_frames = [ordered]@{
                    before = [ordered]@{
                        evidence_filename = [IO.Path]::GetFileName(
                            $beforeEvidencePath
                        )
                        sha256 = $before.frame_sha256
                        bytes = (
                            Get-Item -LiteralPath $beforeEvidencePath
                        ).Length
                    }
                    after = [ordered]@{
                        evidence_filename = [IO.Path]::GetFileName(
                            $afterEvidencePath
                        )
                        sha256 = $after.frame_sha256
                        bytes = (
                            Get-Item -LiteralPath $afterEvidencePath
                        ).Length
                    }
                }
            }
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
            observed_at_utc = $capturedAtUtc
        }
    )
    [IO.File]::WriteAllText(
        $outputItemPath,
        ($fixture | ConvertTo-Json -Depth 100) + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )

    [pscustomobject]@{
        success = $true
        edge = $EdgeId
        source = $before.semantic_surface
        destination = $after.semantic_surface
        source_animated_elements = @($before.animated_element_ids).Count
        destination_animated_elements = @($after.animated_element_ids).Count
        source_settle_latency_milliseconds = (
            $before.settlement.settle_latency_milliseconds
        )
        destination_settle_latency_milliseconds = (
            $after.settlement.settle_latency_milliseconds
        )
        output = $outputItemPath
    } | ConvertTo-Json -Compress
} finally {
    if ($populationSamplerArmed) {
        try {
            Stop-NativeMenuPopulationSampler -Context $context | Out-Null
        } catch {
            Write-Warning (
                "Could not disarm native-menu population sampler after " +
                "transition failure: $($_.Exception.Message)"
            )
        }
    }
    if (Test-Path -LiteralPath $tempDirectory -PathType Container) {
        Remove-Item -LiteralPath $tempDirectory -Recurse -Force
    }
}
