[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$LoaderCapturePath,

    [Parameter(Mandatory = $true)]
    [string]$LoadingCapturePath,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$fixtureRoot = [IO.Path]::GetFullPath($OutputRoot)
$layoutRoot = Join-Path $fixtureRoot "menu-layouts"
$referenceRoot = Join-Path $fixtureRoot "menu-reference-captures"
[IO.Directory]::CreateDirectory($layoutRoot) | Out-Null
[IO.Directory]::CreateDirectory($referenceRoot) | Out-Null

function Invoke-CaptureGit {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $result = @(& git -C $root @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw (
            "Could not derive special-capture Git provenance: " +
            (($result | ForEach-Object { [string]$_ }) -join "`n")
        )
    }
    return (($result | ForEach-Object { [string]$_ }) -join "`n").Trim()
}

$baseCommitSha = Invoke-CaptureGit @("rev-parse", "HEAD")
$sourceTreeSha = Invoke-CaptureGit @("rev-parse", "HEAD^{tree}")
if (
    $baseCommitSha -notmatch '^[0-9a-f]{40}$' -or
    $sourceTreeSha -notmatch '^[0-9a-f]{40}$'
) {
    throw "Special-capture Git provenance was not a full lowercase SHA."
}
$trackedChanges = Invoke-CaptureGit @(
    "status",
    "--porcelain",
    "--untracked-files=no"
)
if (-not [string]::IsNullOrWhiteSpace($trackedChanges)) {
    throw (
        "Special-capture import requires a clean tracked tree so " +
        "base_commit_sha describes the recorder."
    )
}

function Write-Utf8Json {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $json = $Value | ConvertTo-Json -Depth 40
    [IO.File]::WriteAllText(
        $Path,
        $json + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
}

function Convert-BmpToPng {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    Add-Type -AssemblyName System.Drawing
    $bitmap = [Drawing.Bitmap]::new($SourcePath)
    try {
        $bitmap.Save(
            $DestinationPath,
            [Drawing.Imaging.ImageFormat]::Png
        )
    } finally {
        $bitmap.Dispose()
    }
}

function Resolve-InstanceName {
    param([Parameter(Mandatory = $true)][string]$Value)

    return $Value -replace '^SolomonDarkModLoader_LuaExec_', ''
}

function Get-OptionalProperty {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [object]$Default = $null
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return $Default
    }
    return $property.Value
}

function New-CaptureHeader {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Instance,
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$CaptureMethod,
        [Parameter(Mandatory = $true)][string]$SourceJsonPath,
        [Parameter(Mandatory = $true)][string]$SourceFramePath,
        [Parameter(Mandatory = $true)][object]$Settlement,
        [Parameter(Mandatory = $true)][string]$ReferenceCapture
    )

    $instanceRoot = Join-Path $root (
        "runtime\instances\" + $Instance.ToLowerInvariant()
    )
    $nativeExecutable = Join-Path $instanceRoot "stage\SolomonDark.exe"
    $injectedLoader = Join-Path $root (
        "dist\launcher\SolomonDarkModLoader.dll"
    )
    if (-not (Test-Path -LiteralPath $nativeExecutable -PathType Leaf)) {
        throw "Exact staged game executable is missing for '$Instance'."
    }
    if (-not (Test-Path -LiteralPath $injectedLoader -PathType Leaf)) {
        throw "Exact launcher-side loader DLL is missing for '$Instance'."
    }
    $gameExecutableSha256 = (
        Get-FileHash -LiteralPath $nativeExecutable -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $loaderDllSha256 = (
        Get-FileHash -LiteralPath $injectedLoader -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $compatibilityPath = Join-Path $instanceRoot (
        "stage\.sdmod\multiplayer-compatibility.json"
    )
    $compatibility = Get-Content -LiteralPath $compatibilityPath -Raw |
        ConvertFrom-Json
    if (
        [string]$compatibility.compatibility.gameExecutable.sha256 -ne
            $gameExecutableSha256 -or
        [string]$compatibility.compatibility.loader.sha256 -ne
            $loaderDllSha256
    ) {
        throw (
            "Staged compatibility receipt does not identify the exact game " +
            "and launcher-side loader being imported."
        )
    }
    $sourceJson = Get-Item -LiteralPath $SourceJsonPath
    return [ordered]@{
        label = $Label
        instance = $Instance
        process_id = $ProcessId
        source = [ordered]@{
            base_commit_sha = $baseCommitSha
            source_tree_sha = $sourceTreeSha
            capture_tree = "exact committed tree at base_commit_sha"
            game_executable_sha256 = $gameExecutableSha256
            loader_dll_sha256 = $loaderDllSha256
        }
        recorded_live = $true
        captured_at_utc = $sourceJson.LastWriteTimeUtc.ToString("o")
        capture_method = $CaptureMethod
        settlement = $Settlement
        raw_recording = [ordered]@{
            evidence_filename = $sourceJson.Name
            sha256 = (
                Get-FileHash `
                    -LiteralPath $sourceJson.FullName `
                    -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            bytes = $sourceJson.Length
            frame_sha256 = (
                Get-FileHash `
                    -LiteralPath $SourceFramePath `
                    -Algorithm SHA256
            ).Hash.ToLowerInvariant()
        }
        reference_capture = $ReferenceCapture
    }
}

function Find-SettledCaptureSampleV2 {
    param(
        [Parameter(Mandatory = $true)][object[]]$Samples,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Samples.Count -eq 0) {
        throw "STOP: '$Label' capture contained no semantic samples."
    }
    $classifierPath = Join-Path $root "tools\native_menu_settlement_v2.py"
    if (-not (Test-Path -LiteralPath $classifierPath -PathType Leaf)) {
        throw "Settlement v2 classifier is missing from the capture tree."
    }
    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
        "sdmod-special-settlement-v2-" + [Guid]::NewGuid().ToString("N")
    )
    [IO.Directory]::CreateDirectory($temporaryDirectory) | Out-Null
    $inputPath = Join-Path $temporaryDirectory "samples.json"
    $outputPath = Join-Path $temporaryDirectory "classification.json"
    try {
        Write-Utf8Json $Samples $inputPath
        $result = @(
            & py.exe -3 $classifierPath find `
                --input $inputPath `
                --output $outputPath 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            $message = (
                ($result | ForEach-Object { [string]$_ }) -join "`n"
            ).Trim()
            throw "STOP: '$Label' Settlement v2 classification failed: $message"
        }
        return Get-Content -LiteralPath $outputPath -Raw | ConvertFrom-Json
    } finally {
        if (Test-Path -LiteralPath $temporaryDirectory -PathType Container) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

function Assert-RecordedSettlementMatches {
    param(
        [Parameter(Mandatory = $true)][object]$Recorded,
        [Parameter(Mandatory = $true)][object]$Computed,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (
        [bool]$Recorded.settled -ne $true -or
        [long]$Recorded.settle_latency_milliseconds -ne
            [long]$Computed.settle_latency_milliseconds -or
        [long]$Recorded.stable_span_milliseconds -ne
            [long]$Computed.stable_span_milliseconds -or
        [int]$Recorded.consecutive_structural_samples -ne
            [int]$Computed.consecutive_structural_samples -or
        [int]$Recorded.total_semantic_samples -ne
            [int]$Computed.total_semantic_samples
    ) {
        throw (
            "STOP: '$Label' recorder settlement header does not match its " +
            "own Settlement v2 structural sample trail."
        )
    }
}

function ConvertTo-SettlementSummaryV2 {
    param([Parameter(Mandatory = $true)][object]$Classification)

    return [ordered]@{
        criterion = [string]$Classification.criterion
        settle_latency_milliseconds = (
            [long]$Classification.settle_latency_milliseconds
        )
        stable_span_milliseconds = (
            [long]$Classification.stable_span_milliseconds
        )
        consecutive_structural_samples = (
            [int]$Classification.consecutive_structural_samples
        )
        animated_id_set_sample_count = (
            [int]$Classification.animated_id_set_sample_count
        )
        total_semantic_samples = (
            [int]$Classification.total_semantic_samples
        )
        structural_sha256 = [string]$Classification.structural_sha256
        animated_element_ids = @($Classification.animated_element_ids)
        animated_element_count = (
            [int]$Classification.animated_element_count
        )
        element_count = [int]$Classification.element_count
        animated_fraction = [double]$Classification.animated_fraction
    }
}

$loaderCaptureItem = Get-Item -LiteralPath $LoaderCapturePath
$loader = Get-Content -LiteralPath $loaderCaptureItem.FullName -Raw |
    ConvertFrom-Json
if ($loader.schema -ne "solomon-dark-native-loader-capture-v1") {
    throw "Loader capture schema was not recognized."
}
$loaderSamples = @($loader.samples)
$loaderClassifierSamples = [Collections.Generic.List[object]]::new()
foreach ($sample in $loaderSamples) {
    $elements = [Collections.Generic.List[object]]::new()
    $elementIndex = 0
    foreach ($element in @($sample.elements)) {
        $elementIndex += 1
        $elements.Add([ordered]@{
            id = "native_loader.art.$(($element.art_id -replace '\.', '_').ToLowerInvariant()).$elementIndex"
            kind = "art"
            text = ""
            action_id = ""
            art_id = [string]$element.art_id
            font_id = ""
            text_style = [string]$element.draw_kind
            visible = $true
            interactive = $false
            draw_order = $elementIndex
            rect = @($element.rect)
            unclipped_rect = @($element.unclipped_rect)
        })
    }
    $loaderClassifierSamples.Add([ordered]@{
        elapsed_milliseconds = [long]$sample.elapsed_milliseconds
        captured_at_milliseconds = [long]$sample.elapsed_milliseconds
        payload = [ordered]@{
            generation = 1
            screen_id = "native_loader"
            screen_title = "Raptisoft loader"
            capture_method = [string]$loader.capture_method
            progress_numerator = [int]$sample.numerator
            progress_denominator = [int]$sample.denominator
            progress = [double]$sample.progress
            complete = [bool]$sample.complete
            elements = $elements
        }
    })
}
$loaderSettled = Find-SettledCaptureSampleV2 `
    -Samples @($loaderClassifierSamples) `
    -Label "native_loader"
Assert-RecordedSettlementMatches `
    -Recorded $loader.settlement `
    -Computed $loaderSettled `
    -Label "native_loader"
$loaderReferenceSample = $null
for (
    $loaderSampleIndex = [int]$loaderSettled.stable_start_index;
    $loaderSampleIndex -le [int]$loaderSettled.stable_end_index;
    $loaderSampleIndex += 1
) {
    if (-not [string]::IsNullOrWhiteSpace(
        [string]$loaderSamples[$loaderSampleIndex].reference_capture
    )) {
        if ($null -ne $loaderReferenceSample) {
            throw (
                "Ambiguous native_loader settled run contains more than one " +
                "reference frame."
            )
        }
        $loaderReferenceSample = $loaderSamples[$loaderSampleIndex]
    }
}
if ($null -eq $loaderReferenceSample) {
    throw "STOP: settled native_loader run has no same-payload reference frame."
}
$loaderSourceFrame = Join-Path (
    Split-Path -Parent $loaderCaptureItem.FullName
) $loaderReferenceSample.reference_capture
if (-not (Test-Path -LiteralPath $loaderSourceFrame -PathType Leaf)) {
    throw "Loader reference frame was not found: $loaderSourceFrame"
}
$loaderReferenceName = "native-loader.png"
$loaderReferencePath = Join-Path $referenceRoot $loaderReferenceName
Convert-BmpToPng $loaderSourceFrame $loaderReferencePath
$loaderInstance = Resolve-InstanceName $loader.instance
$loaderFixture = [ordered]@{
    schema = "solomon-dark-native-menu-layout-v2"
    header = New-CaptureHeader `
        -Label "native_loader" `
        -Instance $loaderInstance `
        -ProcessId ([int]$loader.process_id) `
        -CaptureMethod ([string]$loader.capture_method) `
        -SourceJsonPath $loaderCaptureItem.FullName `
        -SourceFramePath $loaderSourceFrame `
        -Settlement (ConvertTo-SettlementSummaryV2 $loaderSettled) `
        -ReferenceCapture "../menu-reference-captures/$loaderReferenceName"
    layout = $loaderSettled.layout
}
Write-Utf8Json $loaderFixture (Join-Path $layoutRoot "native-loader.json")

$loadingCaptureItem = Get-Item -LiteralPath $LoadingCapturePath
$loadingRecording = Get-Content -LiteralPath $loadingCaptureItem.FullName -Raw |
    ConvertFrom-Json
if (
    $loadingRecording.schema -ne
        "solomon-dark-native-loading-capture-v1"
) {
    throw "Loading capture schema was not recognized."
}
$loadingSamples = @($loadingRecording.samples)
$loadingClassifierSamples = [Collections.Generic.List[object]]::new()
foreach ($sample in $loadingSamples) {
    $loading = $sample.layout
    $elements = [Collections.Generic.List[object]]::new()
    $elementIndex = 0
    foreach ($element in @($loading.elements)) {
        $elementIndex += 1
        $entry = [ordered]@{
            id = "loading.$($element.id)"
            kind = [string]$element.kind
            text = [string](Get-OptionalProperty $element "text" "")
            action_id = ""
            art_id = [string](Get-OptionalProperty $element "art_id" "")
            font_id = [string](Get-OptionalProperty $element "font" "")
            text_style = [string]$element.kind
            visible = $true
            interactive = $false
            draw_order = $elementIndex
            rect = @($element.rect)
            unclipped_rect = @($element.rect)
        }
        foreach ($property in @(
            "color",
            "color_top",
            "color_bottom",
            "source_size",
            "font_height",
            "font_weight",
            "scale"
        )) {
            $propertyValue = Get-OptionalProperty $element $property
            if ($null -ne $propertyValue) {
                $entry[$property] = $propertyValue
            }
        }
        $elements.Add($entry)
    }
    $loadingClassifierSamples.Add([ordered]@{
        elapsed_milliseconds = [long]$sample.elapsed_milliseconds
        captured_at_milliseconds = [long]$sample.elapsed_milliseconds
        payload = [ordered]@{
            generation = [int]$loading.sequence
            screen_id = "loading_screen"
            screen_title = [string]$loading.elements[-1].text
            capture_method = [string]$loadingRecording.header.capture_method
            stage_id = [string]$loading.stage_id
            progress = [double]$loading.progress
            viewport = @($loading.viewport)
            source_crop = @($loading.source_crop)
            elements = $elements
        }
    })
}
$loadingSettled = Find-SettledCaptureSampleV2 `
    -Samples @($loadingClassifierSamples) `
    -Label "loading_screen"
Assert-RecordedSettlementMatches `
    -Recorded $loadingRecording.settlement `
    -Computed $loadingSettled `
    -Label "loading_screen"
$loadingReferenceSample = $null
for (
    $loadingSampleIndex = [int]$loadingSettled.stable_start_index;
    $loadingSampleIndex -le [int]$loadingSettled.stable_end_index;
    $loadingSampleIndex += 1
) {
    if (-not [string]::IsNullOrWhiteSpace(
        [string]$loadingSamples[$loadingSampleIndex].reference_capture
    )) {
        if ($null -ne $loadingReferenceSample) {
            throw (
                "Ambiguous loading_screen settled run contains more than one " +
                "reference frame."
            )
        }
        $loadingReferenceSample = $loadingSamples[$loadingSampleIndex]
    }
}
if ($null -eq $loadingReferenceSample) {
    throw "STOP: settled loading_screen run has no same-payload reference frame."
}
$loadingSourceFrame = Join-Path (
    Split-Path -Parent $loadingCaptureItem.FullName
) $loadingReferenceSample.reference_capture
if (-not (Test-Path -LiteralPath $loadingSourceFrame -PathType Leaf)) {
    throw "Loading reference frame was not found: $loadingSourceFrame"
}
$loadingReferenceName = "loading-screen.png"
$loadingReferencePath = Join-Path $referenceRoot $loadingReferenceName
Convert-BmpToPng $loadingSourceFrame $loadingReferencePath
$loadingInstance = Resolve-InstanceName $loadingRecording.header.instance
$loadingFixture = [ordered]@{
    schema = "solomon-dark-native-menu-layout-v2"
    header = New-CaptureHeader `
        -Label "loading_screen" `
        -Instance $loadingInstance `
        -ProcessId ([int]$loadingRecording.header.pid) `
        -CaptureMethod ([string]$loadingRecording.header.capture_method) `
        -SourceJsonPath $loadingCaptureItem.FullName `
        -SourceFramePath $loadingSourceFrame `
        -Settlement (ConvertTo-SettlementSummaryV2 $loadingSettled) `
        -ReferenceCapture "../menu-reference-captures/$loadingReferenceName"
    layout = $loadingSettled.layout
}
Write-Utf8Json $loadingFixture (Join-Path $layoutRoot "loading-screen.json")

[ordered]@{
    success = $true
    outputs = @(
        (Join-Path $layoutRoot "native-loader.json"),
        $loaderReferencePath,
        (Join-Path $layoutRoot "loading-screen.json"),
        $loadingReferencePath
    )
} | ConvertTo-Json -Compress
