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
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [string]$ReferencePngPath
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
$referenceItemPath = [IO.Path]::GetFullPath($ReferencePngPath)
$fixtureBasename = [IO.Path]::GetFileNameWithoutExtension($outputItemPath)
if ([string]::IsNullOrWhiteSpace($fixtureBasename)) {
    throw "OutputPath does not derive a fixture basename."
}
$traceDirectory = Join-Path (
    Split-Path -Parent (Split-Path -Parent $outputItemPath)
) "menu-settlement-traces"
$traceItemPath = Join-Path (
    $traceDirectory
) "$fixtureBasename.settlement.json"
[IO.Directory]::CreateDirectory(
    $traceDirectory
) | Out-Null
[IO.Directory]::CreateDirectory(
    (Split-Path -Parent $outputItemPath)
) | Out-Null
[IO.Directory]::CreateDirectory(
    (Split-Path -Parent $referenceItemPath)
) | Out-Null

$tempDirectory = Join-Path ([IO.Path]::GetTempPath()) (
    "sdmod-menu-layout-" + [Guid]::NewGuid().ToString("N")
)
[IO.Directory]::CreateDirectory($tempDirectory) | Out-Null
$referenceBmpPath = Join-Path $tempDirectory "settled-frame.bmp"
try {
    $latencyClock = [Diagnostics.Stopwatch]::StartNew()
    $observation = Get-SettledNativeMenuObservation `
        -Context $context `
        -ScreenId $ScreenId `
        -FramePath $referenceBmpPath `
        -LatencyClock $latencyClock
    if ($observation.tagged_screen -ne $ScreenId) {
        throw (
            "STOP: requested '$ScreenId' but the settled live layout reported " +
            "'$($observation.tagged_screen)'."
        )
    }
    Assert-NativeMenuCaptureSurfaceAgreement `
        -OperatorScreenTag $ScreenId `
        -MachineClassifiedSurface $observation.semantic_surface
    if ($observation.element_count -eq 0) {
        throw "STOP: the settled live '$ScreenId' layout was empty."
    }
    Convert-NativeMenuBmpToPng `
        -SourcePath $referenceBmpPath `
        -DestinationPath $referenceItemPath
} finally {
    if (Test-Path -LiteralPath $tempDirectory -PathType Container) {
        Remove-Item -LiteralPath $tempDirectory -Recurse -Force
    }
}

$capturedAtUtc = [DateTime]::UtcNow.ToString("o")
$trace = [ordered]@{
    schema = "solomon-dark-native-menu-settlement-trace-v2"
    header = [ordered]@{
        label = $ScreenId
        instance = $Instance
        process_id = $ProcessId
        source = $context.Source
        recorded_live = $true
        captured_at_utc = $capturedAtUtc
        capture_method = $observation.capture_method
    }
    settlement = $observation.settlement
    structural_phases = @(
        $observation.settlement_trace.structural_phases
    )
    settled_window_samples = @(
        $observation.settlement_trace.settled_window_samples
    )
}
[IO.File]::WriteAllText(
    $traceItemPath,
    ($trace | ConvertTo-Json -Depth 100) + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)

$outputDirectoryUri = [Uri]::new(
    (Split-Path -Parent $outputItemPath).TrimEnd('\') + '\'
)
$referenceRelative = [Uri]::UnescapeDataString(
    $outputDirectoryUri.MakeRelativeUri(
        [Uri]::new($referenceItemPath)
    ).ToString()
)
$traceItem = Get-Item -LiteralPath $traceItemPath
$fixture = [ordered]@{
    schema = "solomon-dark-native-menu-layout-v2"
    header = [ordered]@{
        label = $ScreenId
        instance = $Instance
        process_id = $ProcessId
        source = $context.Source
        capture_method = $observation.capture_method
        recorded_live = $true
        captured_at_utc = $capturedAtUtc
        settlement = $observation.settlement
        raw_recording = [ordered]@{
            evidence_filename = $traceItem.Name
            sha256 = (
                Get-FileHash -LiteralPath $traceItem.FullName -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            bytes = $traceItem.Length
        }
        reference_capture = $referenceRelative
    }
    layout = $observation.layout
}
[IO.File]::WriteAllText(
    $outputItemPath,
    ($fixture | ConvertTo-Json -Depth 100) + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)

[pscustomobject]@{
    success = $true
    screen = $ScreenId
    elements = $observation.element_count
    animated_elements = @($observation.animated_element_ids).Count
    settle_latency_milliseconds = (
        $observation.settlement.settle_latency_milliseconds
    )
    output = $outputItemPath
    reference = $referenceItemPath
    settlement_trace = $traceItemPath
} | ConvertTo-Json -Compress
