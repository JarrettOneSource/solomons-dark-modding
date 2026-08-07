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
    [string]$PrimaryFixturePath,

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

$primaryItemPath = [IO.Path]::GetFullPath($PrimaryFixturePath)
$outputItemPath = [IO.Path]::GetFullPath($OutputPath)
$confirmationBasename = [IO.Path]::GetFileNameWithoutExtension($outputItemPath)
if ([string]::IsNullOrWhiteSpace($confirmationBasename)) {
    throw "OutputPath does not derive a confirmation basename."
}
if (Test-Path -LiteralPath $outputItemPath) {
    throw "Animation confirmation '$outputItemPath' already exists; refusing ambiguity."
}
$primary = Get-Content -LiteralPath $primaryItemPath -Raw | ConvertFrom-Json
if ($primary.schema -ne "solomon-dark-native-menu-layout-v2") {
    throw "Primary animation fixture does not use the Settlement v2 schema."
}
if ([string]$primary.header.label -ne $ScreenId) {
    throw (
        "Primary fixture label '$($primary.header.label)' does not match " +
        "confirmation screen '$ScreenId'."
    )
}
if ([string]$primary.header.instance -eq $Instance) {
    throw "Animated-ID confirmation must come from a different fresh instance."
}
if ([int]$primary.header.process_id -eq $ProcessId) {
    throw "Animated-ID confirmation must come from a different exact process."
}
$primarySourceJson = $primary.header.source | ConvertTo-Json -Compress
$confirmationSourceJson = $context.Source | ConvertTo-Json -Compress
if ($primarySourceJson -cne $confirmationSourceJson) {
    throw (
        "Animated-ID confirmation must use the same commit, tree, game, and " +
        "loader provenance as the primary capture."
    )
}
if ($null -ne $primary.header.PSObject.Properties["animation_confirmation"]) {
    throw "Primary fixture already names an animation confirmation; refusing ambiguity."
}

[IO.Directory]::CreateDirectory(
    (Split-Path -Parent $outputItemPath)
) | Out-Null
$frameDirectory = Join-Path (
    Split-Path -Parent $outputItemPath
) "frames"
[IO.Directory]::CreateDirectory($frameDirectory) | Out-Null
$frameItemPath = Join-Path $frameDirectory "$confirmationBasename.bmp"
$tempDirectory = Join-Path ([IO.Path]::GetTempPath()) (
    "sdmod-menu-confirmation-" + [Guid]::NewGuid().ToString("N")
)
[IO.Directory]::CreateDirectory($tempDirectory) | Out-Null
$tempFramePath = Join-Path $tempDirectory "settled-frame.bmp"
try {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $observation = Get-SettledNativeMenuObservation `
        -Context $context `
        -ScreenId $ScreenId `
        -FramePath $tempFramePath `
        -LatencyClock $clock
    if ($observation.tagged_screen -ne $ScreenId) {
        throw (
            "STOP: confirmation requested '$ScreenId' but the settled live " +
            "layout reported '$($observation.tagged_screen)'."
        )
    }
    Assert-NativeMenuCaptureSurfaceAgreement `
        -OperatorScreenTag $ScreenId `
        -MachineClassifiedSurface $observation.semantic_surface
    Copy-Item -LiteralPath $tempFramePath -Destination $frameItemPath
} finally {
    if (Test-Path -LiteralPath $tempDirectory -PathType Container) {
        Remove-Item -LiteralPath $tempDirectory -Recurse -Force
    }
}

$primaryIds = @($primary.layout.animated_element_ids | ForEach-Object { [string]$_ })
$confirmationIds = @(
    $observation.layout.animated_element_ids | ForEach-Object { [string]$_ }
)
foreach ($labelAndIds in @(
    [pscustomobject]@{ Label = "primary"; Ids = $primaryIds },
    [pscustomobject]@{ Label = "confirmation"; Ids = $confirmationIds }
)) {
    $duplicates = @(
        $labelAndIds.Ids | Group-Object | Where-Object Count -gt 1 |
            ForEach-Object Name
    )
    if ($duplicates.Count -ne 0) {
        throw (
            "STOP: $($labelAndIds.Label) animated ID set is ambiguous: " +
            ($duplicates -join ", ")
        )
    }
}
$primaryIdsJson = ConvertTo-Json -InputObject @($primaryIds | Sort-Object) -Compress
$confirmationIdsJson = ConvertTo-Json `
    -InputObject @($confirmationIds | Sort-Object) `
    -Compress
$rawSetsMatchNoncontractual = $primaryIdsJson -ceq $confirmationIdsJson

$capturedAtUtc = [DateTime]::UtcNow.ToString("o")
$frameItem = Get-Item -LiteralPath $frameItemPath
$confirmation = [ordered]@{
    schema = "solomon-dark-native-menu-animation-confirmation-v4"
    header = [ordered]@{
        label = $ScreenId
        instance = $Instance
        process_id = $ProcessId
        source = $context.Source
        recorded_live = $true
        captured_at_utc = $capturedAtUtc
        capture_method = $observation.capture_method
        frame = [ordered]@{
            evidence_filename = $frameItem.Name
            sha256 = (
                Get-FileHash -LiteralPath $frameItem.FullName -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            bytes = $frameItem.Length
        }
    }
    settlement = $observation.settlement
    animated_element_ids = @($observation.animated_element_ids)
    raw_primary_animated_element_ids = @($primaryIds)
    raw_sets_match_noncontractual = $rawSetsMatchNoncontractual
    requires_campaign_resolution = $true
    structural_sha256 = [string]$observation.settlement.structural_sha256
    confirmation_layout = $observation.layout
    structural_phases = @(
        $observation.settlement_trace.structural_phases
    )
    settled_window_samples = @(
        $observation.settlement_trace.settled_window_samples
    )
}
[IO.File]::WriteAllText(
    $outputItemPath,
    (($confirmation | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
)

$confirmationItem = Get-Item -LiteralPath $outputItemPath
$confirmationHeader = [pscustomobject][ordered]@{
    evidence_filename = $confirmationItem.Name
    sha256 = (
        Get-FileHash `
            -LiteralPath $confirmationItem.FullName `
            -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    bytes = $confirmationItem.Length
    instance = $Instance
    process_id = $ProcessId
    source = $context.Source
    confirmation_structural_sha256 = (
        [string]$observation.settlement.structural_sha256
    )
    animated_element_ids_sha256 = Get-NativeMenuStringSha256 $confirmationIdsJson
    raw_primary_animated_element_ids = @($primaryIds)
    raw_confirmation_animated_element_ids = @($confirmationIds)
    raw_sets_match_noncontractual = $rawSetsMatchNoncontractual
    requires_campaign_resolution = $true
}
$primary.header | Add-Member `
    -NotePropertyName animation_confirmation `
    -NotePropertyValue $confirmationHeader
[IO.File]::WriteAllText(
    $primaryItemPath,
    (($primary | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
)

[pscustomobject]@{
    success = $true
    screen = $ScreenId
    animated_elements = @($observation.animated_element_ids).Count
    raw_sets_match_noncontractual = $rawSetsMatchNoncontractual
    requires_campaign_resolution = $true
    structural_sha256 = [string]$observation.settlement.structural_sha256
    output = $outputItemPath
    primary_fixture = $primaryItemPath
} | ConvertTo-Json -Compress
