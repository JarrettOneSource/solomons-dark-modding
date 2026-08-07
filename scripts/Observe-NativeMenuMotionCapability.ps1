[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$')]
    [string]$Instance,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [int]::MaxValue)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9_]+$')]
    [string]$ScreenId,

    [Parameter(Mandatory = $true)]
    [string]$BaselineRecordingPath,

    [ValidatePattern('^[a-z0-9_]+$')]
    [string]$EdgeId = "",

    [ValidateSet("source", "destination")]
    [string]$EdgeSide = "destination",

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
. (Join-Path $PSScriptRoot "NativeMenuCaptureSupport.ps1")
$context = New-NativeMenuCaptureContext `
    -Root $root `
    -Instance $Instance `
    -ProcessId $ProcessId

$baselinePath = [IO.Path]::GetFullPath($BaselineRecordingPath)
$outputItemPath = [IO.Path]::GetFullPath($OutputPath)
if (-not (Test-Path -LiteralPath $baselinePath -PathType Leaf)) {
    throw "BROKEN: motion-capability baseline '$baselinePath' does not exist."
}
if (Test-Path -LiteralPath $outputItemPath) {
    throw "Motion-capability evidence '$outputItemPath' already exists; refusing ambiguity."
}
$baselineFile = Get-Item -LiteralPath $baselinePath
$baseline = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
$baselineHeader = $null
$baselineSettlement = $null
$baselineLayout = $null
$baselineSelector = [ordered]@{ schema = [string]$baseline.schema }
switch ([string]$baseline.schema) {
    { $_ -in @(
        "solomon-dark-native-menu-layout-v2",
        "solomon-dark-native-menu-layout-v3"
    ) } {
        if (-not [string]::IsNullOrWhiteSpace($EdgeId)) {
            throw "BROKEN: EdgeId cannot select inside a standalone baseline."
        }
        $baselineHeader = $baseline.header
        $baselineSettlement = $baseline.header.settlement
        $baselineLayout = $baseline.layout
    }
    { $_ -in @(
        "solomon-dark-native-menu-animation-confirmation-v2",
        "solomon-dark-native-menu-animation-confirmation-v3",
        "solomon-dark-native-menu-animation-confirmation-v4"
    ) } {
        if (-not [string]::IsNullOrWhiteSpace($EdgeId)) {
            throw "BROKEN: EdgeId cannot select inside a confirmation baseline."
        }
        $baselineHeader = $baseline.header
        $baselineSettlement = $baseline.settlement
        $baselineLayout = $baseline.confirmation_layout
    }
    "solomon-dark-native-menu-navigation-v2" {
        if ([string]::IsNullOrWhiteSpace($EdgeId)) {
            throw "BROKEN: a navigation baseline requires one exact EdgeId."
        }
        $matches = @($baseline.edges | Where-Object { [string]$_.id -ceq $EdgeId })
        if ($matches.Count -ne 1) {
            throw (
                "BROKEN: navigation baseline edge '$EdgeId' is absent or ambiguous."
            )
        }
        $baselineHeader = $matches[0].header
        $endpoint = if ($EdgeSide -ceq "source") {
            $matches[0].before
        } else {
            $matches[0].after
        }
        $baselineSettlement = $endpoint.settlement
        $baselineLayout = $endpoint.layout
        $baselineSelector.edge_id = $EdgeId
        $baselineSelector.edge_side = $EdgeSide
    }
    default {
        throw "BROKEN: motion-capability baseline schema is not recognized."
    }
}
if ($null -eq $baselineHeader -or $null -eq $baselineSettlement -or
    $null -eq $baselineLayout) {
    throw "BROKEN: motion-capability baseline did not resolve one layout window."
}
if ([string]$baselineHeader.instance -cne $Instance -or
    [int]$baselineHeader.process_id -ne $ProcessId) {
    throw (
        "BROKEN: motion-capability baseline does not belong to exact instance " +
        "'$Instance' PID $ProcessId."
    )
}
if ([string]$baselineLayout.screen_id -cne $ScreenId) {
    throw (
        "BROKEN: motion-capability baseline screen '$($baselineLayout.screen_id)' " +
        "does not equal requested '$ScreenId'."
    )
}
$baselineSourceJson = $baselineHeader.source | ConvertTo-Json -Compress
$currentSourceJson = $context.Source | ConvertTo-Json -Compress
if ($baselineSourceJson -cne $currentSourceJson) {
    throw (
        "BROKEN: motion-capability baseline provenance does not identify the " +
        "current committed recorder and exact binaries."
    )
}
$stableSpanMilliseconds = [long]$baselineSettlement.stable_span_milliseconds
if ($stableSpanMilliseconds -lt $script:NativeMenuSettleMinimumSpanMilliseconds) {
    throw "BROKEN: motion-capability baseline lacks a valid settled span."
}
$requiredSpanMilliseconds = [Math]::Max(
    [long]$script:NativeMenuExtendedMinimumMilliseconds,
    [long]$script:NativeMenuExtendedSpanMultiplier * $stableSpanMilliseconds
)
$sampleCensusDeadlineMilliseconds = (
    [long]$script:NativeMenuExtendedMinimumSamples *
    [long]$script:NativeMenuExtendedPerSampleBudgetMilliseconds
)
$deadlineMilliseconds = [Math]::Max(
    $requiredSpanMilliseconds +
        [long]$script:NativeMenuSettleTimeoutMilliseconds,
    $sampleCensusDeadlineMilliseconds
)
$samples = [Collections.Generic.List[object]]::new()
$busyCount = 0
$notReadyCount = 0
$lastUnavailable = ""
$clock = [Diagnostics.Stopwatch]::StartNew()
$observedSpanMilliseconds = 0L
while (
    $observedSpanMilliseconds -lt $requiredSpanMilliseconds -or
    $samples.Count -lt $script:NativeMenuExtendedMinimumSamples
) {
    if ($clock.ElapsedMilliseconds -gt $deadlineMilliseconds) {
        throw (
            "STOP: '$ScreenId' could not produce at least 200 runnable samples " +
            "across its derived $requiredSpanMilliseconds ms motion observation; " +
            "samples=$($samples.Count) " +
            "busy=$busyCount not_ready=$notReadyCount last='$lastUnavailable'."
        )
    }
    $probe = Get-NativeMenuLayoutProbe -Context $context -ScreenId $ScreenId
    if ($probe.Status -ne "ready") {
        if ($probe.Status -eq "busy") {
            $busyCount += 1
        } else {
            $notReadyCount += 1
        }
        $lastUnavailable = [string]$probe.Detail
        Start-Sleep -Milliseconds $script:NativeMenuSettlePollMilliseconds
        continue
    }
    if ([string]$probe.SemanticPayload.screen_id -cne $ScreenId) {
        throw (
            "STOP: motion observation requested '$ScreenId' but live capture " +
            "reported '$($probe.SemanticPayload.screen_id)'."
        )
    }
    Assert-NativeMenuOverlayHygiene `
        -Context $context `
        -Layout $probe.SemanticPayload
    $samples.Add([ordered]@{
        elapsed_milliseconds = [long]$clock.ElapsedMilliseconds
        captured_at_milliseconds = [uint64]$probe.CapturedAtMilliseconds
        semantic_surface = $probe.SemanticSurface
        semantic_generation = $probe.SemanticGeneration
        payload = $probe.SemanticPayload
    })
    if ($samples.Count -ge 2) {
        $observedSpanMilliseconds = [long](
            $samples[$samples.Count - 1].elapsed_milliseconds -
            $samples[0].elapsed_milliseconds
        )
    }
    Start-Sleep -Milliseconds 250
}
$clock.Stop()
$classification = Invoke-NativeMenuExtendedObservationClassifier `
    -Context $context `
    -Samples @($samples) `
    -RequiredSpanMilliseconds $requiredSpanMilliseconds

[IO.Directory]::CreateDirectory((Split-Path -Parent $outputItemPath)) | Out-Null
$capturedAtUtc = [DateTime]::UtcNow.ToString("o")
$recording = [ordered]@{
    schema = "solomon-dark-native-menu-motion-capability-observation-v1"
    header = [ordered]@{
        label = $ScreenId
        instance = $Instance
        process_id = $ProcessId
        source = $context.Source
        recorded_live = $true
        captured_at_utc = $capturedAtUtc
        capture_method = "sd.ui.capture_current_layout sampled continuously"
        baseline = [ordered]@{
            evidence_filename = $baselineFile.Name
            sha256 = (
                Get-FileHash -LiteralPath $baselineFile.FullName -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            bytes = $baselineFile.Length
            selector = $baselineSelector
            stable_span_milliseconds = $stableSpanMilliseconds
            raw_window_animated_element_ids = @(
                $baselineLayout.animated_element_ids
            )
        }
    }
    required_span_milliseconds = $requiredSpanMilliseconds
    observed_span_milliseconds = [long]$classification.observed_span_milliseconds
    sample_count = [int]$classification.sample_count
    moving_element_ids = @($classification.moving_element_ids)
    motion_event_count = [int]$classification.motion_event_count
    motion_events = @($classification.motion_events)
    samples = @($samples)
}
[IO.File]::WriteAllText(
    $outputItemPath,
    (($recording | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
)

$outputItem = Get-Item -LiteralPath $outputItemPath
[pscustomobject]@{
    success = $true
    screen = $ScreenId
    instance = $Instance
    process_id = $ProcessId
    required_span_milliseconds = $requiredSpanMilliseconds
    observed_span_milliseconds = [long]$classification.observed_span_milliseconds
    samples = [int]$classification.sample_count
    motion_events = [int]$classification.motion_event_count
    moving_element_ids = @($classification.moving_element_ids)
    output = $outputItem.FullName
    sha256 = (
        Get-FileHash -LiteralPath $outputItem.FullName -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    bytes = $outputItem.Length
} | ConvertTo-Json -Compress
