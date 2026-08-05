[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$LoaderCapturePath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$LoaderCaptureCommit,

    [Parameter(Mandatory = $true)]
    [string]$LoadingCapturePath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$LoadingCaptureCommit
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$fixtureRoot = Join-Path $root "tests\fixtures\webgame"
$layoutRoot = Join-Path $fixtureRoot "menu-layouts"
$referenceRoot = Join-Path $fixtureRoot "menu-reference-captures"
[IO.Directory]::CreateDirectory($layoutRoot) | Out-Null
[IO.Directory]::CreateDirectory($referenceRoot) | Out-Null

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

function Get-OptionalHash {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return ""
    }
    return (
        Get-FileHash -LiteralPath $Path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
}

function New-CaptureHeader {
    param(
        [Parameter(Mandatory = $true)][string]$Instance,
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$CaptureCommit,
        [Parameter(Mandatory = $true)][string]$CaptureMethod,
        [Parameter(Mandatory = $true)][string]$SourceJsonPath,
        [Parameter(Mandatory = $true)][string]$SourceFramePath,
        [Parameter(Mandatory = $true)][string]$ReferenceCapture
    )

    $instanceRoot = Join-Path $root (
        "runtime\instances\" + $Instance.ToLowerInvariant()
    )
    $nativeExecutable = Join-Path $instanceRoot "stage\SolomonDark.exe"
    $stagedLoader = Join-Path $instanceRoot (
        "stage\SolomonDarkModLoader.dll"
    )
    return [ordered]@{
        instance = $Instance
        process_id = $ProcessId
        capture_commit = $CaptureCommit
        native_exe_sha256 = Get-OptionalHash $nativeExecutable
        loader_dll_sha256 = Get-OptionalHash $stagedLoader
        captured_at_utc = (
            Get-Item -LiteralPath $SourceJsonPath
        ).LastWriteTimeUtc.ToString("o")
        capture_method = $CaptureMethod
        source_json_sha256 = Get-OptionalHash $SourceJsonPath
        source_frame_sha256 = Get-OptionalHash $SourceFramePath
        reference_capture = $ReferenceCapture
    }
}

$loaderCaptureItem = Get-Item -LiteralPath $LoaderCapturePath
$loader = Get-Content -LiteralPath $loaderCaptureItem.FullName -Raw |
    ConvertFrom-Json
if ($loader.schema -ne "solomon-dark-native-loader-capture-v1") {
    throw "Loader capture schema was not recognized."
}
$loaderSamples = @($loader.samples)
if ($loaderSamples.Count -ne 1) {
    throw "Expected exactly one live loader-layout sample."
}
$loaderSample = $loaderSamples[0]
$loaderSourceFrame = Join-Path (
    Split-Path -Parent $loaderCaptureItem.FullName
) $loaderSample.reference_capture
if (-not (Test-Path -LiteralPath $loaderSourceFrame -PathType Leaf)) {
    throw "Loader reference frame was not found: $loaderSourceFrame"
}
$loaderReferenceName = "native-loader.png"
$loaderReferencePath = Join-Path $referenceRoot $loaderReferenceName
Convert-BmpToPng $loaderSourceFrame $loaderReferencePath
$loaderInstance = Resolve-InstanceName $loader.instance
$loaderElements = [Collections.Generic.List[object]]::new()
$loaderIndex = 0
foreach ($element in @($loaderSample.elements)) {
    $loaderIndex += 1
    $loaderElements.Add([ordered]@{
        id = "native_loader.art.$(($element.art_id -replace '\.', '_').ToLowerInvariant()).$loaderIndex"
        kind = "art"
        text = ""
        action_id = ""
        art_id = [string]$element.art_id
        font_id = ""
        text_style = [string]$element.draw_kind
        visible = $true
        interactive = $false
        draw_order = $loaderIndex
        rect = @($element.rect)
        unclipped_rect = @($element.unclipped_rect)
    })
}
$loaderFixture = [ordered]@{
    schema = "solomon-dark-native-menu-layout-v1"
    header = New-CaptureHeader `
        -Instance $loaderInstance `
        -ProcessId ([int]$loader.process_id) `
        -CaptureCommit $LoaderCaptureCommit `
        -CaptureMethod ([string]$loader.capture_method) `
        -SourceJsonPath $loaderCaptureItem.FullName `
        -SourceFramePath $loaderSourceFrame `
        -ReferenceCapture "../menu-reference-captures/$loaderReferenceName"
    layout = [ordered]@{
        generation = 1
        captured_at_milliseconds = 0
        screen_id = "native_loader"
        screen_title = "Raptisoft loader"
        capture_method = [string]$loader.capture_method
        elapsed_milliseconds = [int]$loaderSample.elapsed_milliseconds
        progress_numerator = [int]$loaderSample.numerator
        progress_denominator = [int]$loaderSample.denominator
        progress = [double]$loaderSample.progress
        complete = [bool]$loaderSample.complete
        elements = $loaderElements
    }
}
Write-Utf8Json $loaderFixture (Join-Path $layoutRoot "native-loader.json")

$loadingCaptureItem = Get-Item -LiteralPath $LoadingCapturePath
$loading = Get-Content -LiteralPath $loadingCaptureItem.FullName -Raw |
    ConvertFrom-Json
if ($loading.schema -ne "native-loading-layout/v1") {
    throw "Loading capture schema was not recognized."
}
$loadingSourceFrame = [IO.Path]::ChangeExtension(
    $loadingCaptureItem.FullName,
    ".bmp"
)
if (-not (Test-Path -LiteralPath $loadingSourceFrame -PathType Leaf)) {
    throw "Loading reference frame was not found: $loadingSourceFrame"
}
$loadingReferenceName = "loading-screen.png"
$loadingReferencePath = Join-Path $referenceRoot $loadingReferenceName
Convert-BmpToPng $loadingSourceFrame $loadingReferencePath
$loadingInstance = Resolve-InstanceName $loading.header.instance
$loadingElements = [Collections.Generic.List[object]]::new()
$loadingIndex = 0
foreach ($element in @($loading.elements)) {
    $loadingIndex += 1
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
        draw_order = $loadingIndex
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
    $loadingElements.Add($entry)
}
$loadingFixture = [ordered]@{
    schema = "solomon-dark-native-menu-layout-v1"
    header = New-CaptureHeader `
        -Instance $loadingInstance `
        -ProcessId ([int]$loading.header.pid) `
        -CaptureCommit $LoadingCaptureCommit `
        -CaptureMethod ([string]$loading.header.capture_method) `
        -SourceJsonPath $loadingCaptureItem.FullName `
        -SourceFramePath $loadingSourceFrame `
        -ReferenceCapture "../menu-reference-captures/$loadingReferenceName"
    layout = [ordered]@{
        generation = [int]$loading.sequence
        captured_at_milliseconds = 0
        screen_id = "loading_screen"
        screen_title = [string]$loading.elements[-1].text
        capture_method = [string]$loading.header.capture_method
        stage_id = [string]$loading.stage_id
        progress = [double]$loading.progress
        viewport = @($loading.viewport)
        source_crop = @($loading.source_crop)
        elements = $loadingElements
    }
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
